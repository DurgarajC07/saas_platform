"""
PII Detector — flags personally identifiable information in call transcripts.

Detects:
    • Phone numbers  (E.164, NANP, common international formats)
    • Email addresses
    • Credit card numbers (Luhn-format 13–19 digit sequences)
    • US Social Security Numbers  (xxx-xx-xxxx)

None of the original PII values are stored — only a count and a list of
category names are attached to the call log's ``metadata_`` field as a
``"pii_flags"`` sub-object so that compliance audits are possible without
re-exposing the data.

Usage
─────
    from app.core.utils.pii_detector import PIIDetector

    result = PIIDetector.detect(transcript)
    if result.has_pii:
        metadata_["pii_flags"] = result.to_dict()
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import structlog

log = structlog.get_logger(__name__)

# ── Patterns ─────────────────────────────────────────────────────────────────

_PHONE = re.compile(
    r"""
    (?<!\d)                         # not preceded by a digit
    (?:
        \+?1[\s\-.]?                # US country code (optional)
    )?
    (?:
        \(\d{3}\)[\s\-.]?           # (NXX)
        | \d{3}[\s\-.]              # NXX-
    )
    \d{3}[\s\-.]                    # CO
    \d{4}                           # XXXX
    (?!\d)                          # not followed by a digit
    |
    \+\d{1,3}[\s\-.]?\d{1,14}       # E.164 variant
    """,
    re.VERBOSE,
)

_EMAIL = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
)

_CC = re.compile(
    r"\b(?:\d[ \-]?){13,19}\b",
)

_SSN = re.compile(
    r"\b\d{3}[- ]\d{2}[- ]\d{4}\b",
)


def _luhn(card: str) -> bool:
    """Return True if *card* (digits only) passes the Luhn check."""
    digits = [int(c) for c in reversed(card) if c.isdigit()]
    if len(digits) < 13:
        return False
    total = 0
    for i, d in enumerate(digits):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class PIIResult:
    """Detection result for a single transcript."""

    has_pii: bool = False
    categories: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "has_pii": self.has_pii,
            "categories": self.categories,
            "counts": self.counts,
        }


# ── Detector ──────────────────────────────────────────────────────────────────

class PIIDetector:
    """
    Stateless PII detection helper.

    Call :meth:`detect` with raw transcript text; receive a :class:`PIIResult`.
    """

    @staticmethod
    def detect(text: str | None) -> PIIResult:
        """Scan *text* for PII patterns; return a :class:`PIIResult`."""
        if not text:
            return PIIResult()

        result = PIIResult()

        _check_phones(text, result)
        _check_emails(text, result)
        _check_credit_cards(text, result)
        _check_ssn(text, result)

        result.has_pii = bool(result.categories)
        if result.has_pii:
            log.warning(
                "pii.detected",
                categories=result.categories,
                counts=result.counts,
            )
        return result

    @staticmethod
    def annotate_metadata(metadata: dict, transcript: str | None) -> dict:
        """
        Run :meth:`detect` and merge a ``"pii_flags"`` key into *metadata*.

        Returns the (possibly mutated) dict so callers can chain::

            meta = PIIDetector.annotate_metadata(meta or {}, transcript)
        """
        result = PIIDetector.detect(transcript)
        if result.has_pii:
            metadata["pii_flags"] = result.to_dict()
        return metadata


# ── Per-category helpers ──────────────────────────────────────────────────────

def _check_phones(text: str, result: PIIResult) -> None:
    matches = _PHONE.findall(text)
    if matches:
        result.categories.append("phone_number")
        result.counts["phone_number"] = len(matches)


def _check_emails(text: str, result: PIIResult) -> None:
    matches = _EMAIL.findall(text)
    if matches:
        result.categories.append("email_address")
        result.counts["email_address"] = len(matches)


def _check_credit_cards(text: str, result: PIIResult) -> None:
    raw_matches = _CC.findall(text)
    valid = [m for m in raw_matches if _luhn(re.sub(r"[\s\-]", "", m))]
    if valid:
        result.categories.append("credit_card")
        result.counts["credit_card"] = len(valid)


def _check_ssn(text: str, result: PIIResult) -> None:
    matches = _SSN.findall(text)
    if matches:
        result.categories.append("ssn")
        result.counts["ssn"] = len(matches)
