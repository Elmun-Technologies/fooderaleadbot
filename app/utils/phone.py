"""Phone number normalisation.

Rules (deterministic, no external dependencies):

* separators (spaces, dashes, parentheses) are removed;
* international dialling prefix ``00`` becomes ``+``;
* Uzbekistan numbers (``901 234 56 78`` / ``998...``) are normalised to
  ``+998XXXXXXXXX``;
* anything else that looks like E.164 is kept as typed, with a leading ``+``.

We deliberately do NOT force ``+998``: FOODERA EXPO invites international
exhibitors, and their numbers must stay valid leads.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["PhoneValue", "extract_phone_from_text", "is_uz", "normalize_phone"]

_SEPARATORS = re.compile(r"[\s\-()./]")
_DIGITS = re.compile(r"\d+")
_E164 = re.compile(r"^\+\d{7,15}$")
#: a phone-like run: optional plus, digits possibly separated by spaces/dashes/parens
_PHONE_LIKE = re.compile(r"\+?\d[\d\s\-().]{5,24}\d")

UZ_COUNTRY_CODE = "998"
UZ_NATIONAL_LENGTH = 9  # e.g. 901234567

# Only used for reporting/analytics ("which country is this lead from?").
_KNOWN_PREFIXES = (
    "998",
    "996",
    "992",
    "995",
    "994",
    "993",
    "997",  # Central Asia / Caucasus
    "7",
    "380",
    "374",
    "995",
    "86",
    "90",
    "91",
    "98",
    "44",
    "49",
    "33",
    "39",
    "34",
    "31",
    "41",
    "43",
    "48",
    "420",
    "40",
    "36",
    "359",
    "30",
    "971",
    "966",
    "965",
    "974",
    "968",
    "962",
    "963",
    "961",
    "964",
    "20",
    "212",
    "216",
    "234",
    "233",
    "254",
    "255",
    "27",
    "1",
)


@dataclass(frozen=True)
class PhoneValue:
    """Result of :func:`normalize_phone`."""

    number: str | None
    valid: bool
    raw: str = ""
    country_code: str | None = None

    def __bool__(self) -> bool:
        return self.valid


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def normalize_phone(raw: str | None) -> PhoneValue:
    """Normalise a user supplied phone number into E.164 when possible."""
    original = (raw or "").strip()
    if not original:
        return PhoneValue(None, False, original)

    text = _SEPARATORS.sub("", original)
    if text.startswith("00"):
        text = "+" + text[2:]
    had_plus = text.startswith("+")
    digits = _digits_only(text)
    if not digits:
        return PhoneValue(None, False, original)

    # Local Uzbekistan formats typed without a country code.
    if not had_plus:
        if len(digits) == UZ_NATIONAL_LENGTH and digits.startswith("9"):
            digits = UZ_COUNTRY_CODE + digits
        elif len(digits) == UZ_NATIONAL_LENGTH + 1 and digits.startswith("8"):
            digits = UZ_COUNTRY_CODE + digits[1:]

    candidate = f"+{digits}"
    if not _E164.match(candidate):
        return PhoneValue(None, False, original)

    return PhoneValue(
        candidate, True, original, country_code=_country_code(digits, had_plus=had_plus)
    )


def _country_code(digits: str, *, had_plus: bool) -> str:
    """Longest known country prefix of ``digits`` (analytics only, never validated)."""
    if not had_plus:
        return UZ_COUNTRY_CODE
    for prefix in sorted(_KNOWN_PREFIXES, key=len, reverse=True):
        if digits.startswith(prefix):
            return prefix
    return digits[: 1 if digits[:1] != "9" else 3]


def is_uz(phone: str | None) -> bool:
    return bool(phone) and phone.startswith(f"+{UZ_COUNTRY_CODE}")


def extract_phone_from_text(text: str | None) -> PhoneValue:
    """Best-effort extraction of the first phone-like run inside free text.

    Users type things like ``"Mening raqamim +998 90 123 45 67"``.
    """
    if not text:
        return PhoneValue(None, False, text or "")
    # longest candidates first, so "+998 90 123 45 67" wins over "998"
    for candidate in sorted(_PHONE_LIKE.findall(text), key=len, reverse=True):
        result = normalize_phone(candidate)
        if result.valid:
            return result
    for candidate in _DIGITS.findall(text):
        result = normalize_phone(candidate)
        if result.valid:
            return result
    return PhoneValue(None, False, text)
