"""Tiny translation layer.

``t("q.intent", "uz")`` returns the localized string.  Unknown keys fall back to
the default language and finally to the key itself, so a missing translation can
never crash a conversation.
"""

from __future__ import annotations

from .catalog_ru import CATALOG as RU
from .catalog_uz import CATALOG as UZ

__all__ = ["CATALOGS", "DEFAULT_LANGUAGE", "SUPPORTED", "option_label", "t", "translate_options"]

CATALOGS: dict[str, dict[str, str]] = {"uz": UZ, "ru": RU}
SUPPORTED: tuple[str, ...] = ("uz", "ru")
DEFAULT_LANGUAGE = "uz"


def normalize_language(value: str | None) -> str:
    """Map anything Telegram may report (``uz-Cyrl-UZ``, ``en``, ``ru_RU``) to a supported code."""
    if not value:
        return DEFAULT_LANGUAGE
    code = value.lower().replace("_", "-")
    if code.startswith("uz"):
        return "uz"
    if code.startswith("ru"):
        return "ru"
    return DEFAULT_LANGUAGE


def t(key: str, language: str | None = None, **kwargs: object) -> str:
    """Translate ``key`` into ``language`` and format ``kwargs`` into it."""
    lang = normalize_language(language)
    template = CATALOGS[lang].get(key) or CATALOGS[DEFAULT_LANGUAGE].get(key) or key
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError, ValueError):  # malformed placeholder - keep the raw text
            return template
    return template


def option_label(group: str, value: str | None, language: str | None, *, emoji: str = "") -> str:
    """Human readable label of a stored option value (``("stand", "intent")`` -> text)."""
    none_text = t("card.value_none", language)
    if not value:
        return none_text
    label = t(f"opt.{group}.{value}", language)
    if label.startswith("opt."):  # key missing
        return value
    return f"{emoji} {label}" if emoji else label


def translate_options(group: str, language: str | None) -> dict[str, str]:
    """All labels of an option group: ``{value: label}`` (used by admin output)."""
    return {
        key.split(f"opt.{group}.", 1)[1]: value
        for key, value in CATALOGS[normalize_language(language)].items()
        if key.startswith(f"opt.{group}.")
    }
