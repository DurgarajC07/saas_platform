"""
DTMF routing processor for IVR (Interactive Voice Response) agents.

``DTMFRouter`` sits in the pipeline immediately after the transport input.
It intercepts ``DTMFFrame`` objects emitted by ``TwilioInputProcessor``,
looks up the caller's digit in a configurable routing map, and dispatches
one of:

  * A ``TransferCallFrame`` — transfer the call to another number/agent
  * A built-in action  — ``hangup``, ``repeat``, ``operator``
  * All other frames pass through unchanged.

Usage (pipeline_builder.py)::

    from processors.dtmf import DTMFRouter
    from transports.twilio import DTMFFrame, TransferCallFrame

    router = DTMFRouter(
        routing_map={
            "1": ("transfer", "+15550001234"),
            "2": ("transfer", "+15550005678"),
            "0": ("operator", None),
            "*": ("repeat",   None),
            "#": ("hangup",   None),
        },
        on_digit=lambda digit, action, dest: log.info(
            "ivr_digit", digit=digit, action=action
        ),
    )

Routing map value format
────────────────────────
Each value is a ``(action, destination)`` tuple:

  action       | destination  | behaviour
  -------------|--------------|------------------------------------------
  "transfer"   | E.164 number | push TransferCallFrame(destination=…)
  "hangup"     | None         | push EndFrame() to terminate the call
  "repeat"     | None         | push a special RepeatMenuFrame (TTS re-plays menu)
  "operator"   | None         | transfer to a default operator number
  "none"       | None         | silently discard the digit (no-op)

Any unrecognised digit falls through to ``on_unrecognised`` if provided.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import structlog
from pipecat.frames.frames import EndFrame, Frame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from transports.twilio import DTMFFrame, TransferCallFrame

log: structlog.BoundLogger = structlog.get_logger(__name__)

# ── Additional IVR frames ──────────────────────────────────────────────────────

@dataclass
class RepeatMenuFrame(Frame):
    """
    Signals the TTS layer to replay the IVR greeting / menu audio.

    The session manager listens for this and triggers a new TTS utterance
    with the agent's ``welcome_message``.
    """
    pass


# ── DTMFRouter ─────────────────────────────────────────────────────────────────

# Action type — (action_name, optional_destination)
RoutingEntry = tuple[str, str | None]

class DTMFRouter(FrameProcessor):
    """
    IVR digit router.  Intercepts ``DTMFFrame``, dispatches the configured
    action, and passes all other frames through unchanged.

    Parameters
    ----------
    routing_map:
        ``{ digit: (action, destination) }`` — see module docstring.
    operator_number:
        Default transfer destination used by the ``"operator"`` action.
    on_digit:
        Optional async callback invoked for every received ``DTMFFrame``
        (before routing).  Signature: ``async def cb(digit, action, dest)``.
    on_unrecognised:
        Optional async callback for digits not in ``routing_map``.
        Signature: ``async def cb(digit)``.
    """

    def __init__(
        self,
        routing_map: dict[str, RoutingEntry] | None = None,
        operator_number: str = "",
        on_digit: Callable[[str, str, str | None], Awaitable[None]] | None = None,
        on_unrecognised: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        super().__init__()
        self._map             = routing_map or {}
        self._operator_number = operator_number
        self._on_digit        = on_digit
        self._on_unrecognised = on_unrecognised

        log.info(
            "dtmf_router_created",
            routes=list(self._map.keys()),
            operator=operator_number or "(none)",
        )

    # ── FrameProcessor ─────────────────────────────────────────────────

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if not isinstance(frame, DTMFFrame):
            await self.push_frame(frame, direction)
            return

        # Only act on finished (key-up) events to avoid double-triggering
        if not frame.finished:
            return

        digit  = frame.digit
        entry  = self._map.get(digit)
        action = entry[0] if entry else "none"
        dest   = entry[1] if entry else None

        if self._on_digit:
            try:
                await self._on_digit(digit, action, dest)
            except Exception as exc:
                log.warning("dtmf_on_digit_callback_error", error=str(exc))

        log.info("dtmf_routing", digit=digit, action=action, destination=dest)

        if entry is None:
            if self._on_unrecognised:
                try:
                    await self._on_unrecognised(digit)
                except Exception as exc:
                    log.warning("dtmf_on_unrecognised_error", error=str(exc))
            return  # unrecognised digit — do nothing

        if action == "transfer":
            destination = dest or self._operator_number
            if destination:
                await self.push_frame(
                    TransferCallFrame(destination=destination, transfer_type="cold"),
                    FrameDirection.DOWNSTREAM,
                )
            else:
                log.warning("dtmf_transfer_no_destination", digit=digit)

        elif action == "operator":
            if self._operator_number:
                await self.push_frame(
                    TransferCallFrame(
                        destination=self._operator_number,
                        transfer_type="warm",
                    ),
                    FrameDirection.DOWNSTREAM,
                )
            else:
                log.warning("dtmf_operator_no_number_configured")

        elif action == "hangup":
            log.info("dtmf_hangup_requested", digit=digit)
            await self.push_frame(EndFrame(), FrameDirection.DOWNSTREAM)

        elif action == "repeat":
            log.info("dtmf_repeat_menu", digit=digit)
            await self.push_frame(RepeatMenuFrame(), FrameDirection.DOWNSTREAM)

        elif action == "none":
            pass  # explicit no-op route

        else:
            log.warning("dtmf_unknown_action", action=action, digit=digit)
