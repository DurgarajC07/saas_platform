"""Agents module domain exceptions."""

from __future__ import annotations

from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
    ValidationException,
)


class AgentNotFoundException(NotFoundException):
    def __init__(self, agent_id: str | None = None) -> None:
        super().__init__(
            f"Agent {agent_id} not found" if agent_id else "Agent not found"
        )


class AgentSlugConflictException(ConflictException):
    def __init__(self, slug: str) -> None:
        super().__init__(
            f"An agent with slug '{slug}' already exists in this organisation"
        )


class CallNotFoundException(NotFoundException):
    def __init__(self, call_id: str | None = None) -> None:
        super().__init__(
            f"Call {call_id} not found" if call_id else "Call not found"
        )


class RecordingNotFoundException(NotFoundException):
    def __init__(self) -> None:
        super().__init__("No recording available for this call")


class PhoneNumberConflictException(ConflictException):
    def __init__(self, phone: str) -> None:
        super().__init__(f"Phone number {phone} is already assigned to an agent")
