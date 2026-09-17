"""Inline keyboards: questions, navigation, manager actions."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.i18n import t
from app.options import OPTION_GROUPS

__all__ = [
    "CATEGORIES_PER_PAGE",
    "CAT_PAGE_PREFIX",
    "CHOICE_PREFIX",
    "category_kb",
    "choice_value",
    "language_kb",
    "lead_actions_kb",
    "nav_kb",
    "prompt_kb",
    "question_kb",
    "single_choice_kb",
    "start_kb",
]

#: ``q:<step>:<value>`` - generic answer callback, validated against the option group
CHOICE_PREFIX = "q"
CAT_PAGE_PREFIX = "cat"
NAV_PREFIX = "nav"
LEAD_PREFIX = "lead"

CATEGORIES_PER_PAGE = 8


def choice_value(callback_data: str) -> tuple[str, str] | None:
    """Parse ``q:company_type:manufacturer`` -> ``("company_type", "manufacturer")``."""
    parts = str(callback_data).split(":", 2)
    if len(parts) != 3 or parts[0] != CHOICE_PREFIX:
        return None
    return parts[1], parts[2]


def _btn(text: str, callback_data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text[:64], callback_data=callback_data)


def _url_btn(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text[:64], url=url)


def language_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn(t("lang.uz", "uz"), "lang:uz")],
            [_btn(t("lang.ru", "ru"), "lang:ru")],
        ]
    )


def start_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn(t("btn.start", lang), "flow:start")]])


def single_choice_kb(
    group: str,
    lang: str,
    step: str,
    *,
    columns: int = 1,
    back: bool = True,
    skip: bool = False,
    manual: bool = False,
    current: str | None = None,
) -> InlineKeyboardMarkup:
    """One question, buttons for every option of an option group."""
    options = list(OPTION_GROUPS[group])
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for option in options:
        label = t(f"opt.{group}.{option.value}", lang)
        text = f"{option.emoji} {label}".strip() if option.emoji else label
        if current and option.value == current:
            text = f"✓ {text}"
        row.append(_btn(text, f"{CHOICE_PREFIX}:{step}:{option.value}"))
        if len(row) >= max(1, columns):
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    nav = _nav_row(lang, back=back, skip=skip, manual=manual)
    if nav:
        rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def category_kb(
    lang: str,
    *,
    page: int = 0,
    per_page: int = CATEGORIES_PER_PAGE,
    step: str = "category",
    current: str | None = None,
    back: bool = True,
) -> tuple[InlineKeyboardMarkup, int, int]:
    """Paginated FOODERA direction picker. Returns ``(keyboard, page, pages)``."""
    options = list(OPTION_GROUPS["category"])
    pages = max(1, -(-len(options) // per_page))
    page = max(0, min(page, pages - 1))
    chunk = options[page * per_page : (page + 1) * per_page]

    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for option in chunk:
        label = t(f"opt.category.{option.value}", lang)
        if current and option.value == current:
            label = f"✓ {label}"
        row.append(_btn(label, f"{CHOICE_PREFIX}:{step}:{option.value}"))
        if len(row) >= 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(_btn(t("btn.fewer_categories", lang), f"{CAT_PAGE_PREFIX}:page:{page - 1}"))
    if page < pages - 1:
        nav.append(_btn(t("btn.more_categories", lang), f"{CAT_PAGE_PREFIX}:page:{page + 1}"))
    if back:
        nav.append(_btn(t("btn.back", lang), f"{NAV_PREFIX}:back"))
    if nav:
        rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows), page, pages


def _nav_row(
    lang: str, *, back: bool = True, skip: bool = False, manual: bool = False
) -> list[InlineKeyboardButton]:
    row: list[InlineKeyboardButton] = []
    if back:
        row.append(_btn(t("btn.back", lang), f"{NAV_PREFIX}:back"))
    if skip:
        row.append(_btn(t("btn.skip", lang), f"{NAV_PREFIX}:skip"))
    if manual:
        row.append(_btn(t("btn.manual_phone", lang), f"{NAV_PREFIX}:manual"))
    return row


def nav_kb(
    lang: str, *, back: bool = True, skip: bool = False, manual: bool = False
) -> InlineKeyboardMarkup | None:
    row = _nav_row(lang, back=back, skip=skip, manual=manual)
    return InlineKeyboardMarkup(inline_keyboard=[row]) if row else None


def question_kb(
    lang: str, *, back: bool = True, skip: bool = False, manual: bool = False
) -> InlineKeyboardMarkup | None:
    """Navigation row shown under free-text questions (no inline choices there)."""
    return nav_kb(lang, back=back, skip=skip, manual=manual)


def prompt_kb(buttons: list[tuple[str, str]], *, columns: int = 1) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for text, callback in buttons:
        row.append(_btn(text, callback))
        if len(row) >= columns:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def lead_actions_kb(lead_id: int, lang: str = "uz", *, columns: int = 2) -> InlineKeyboardMarkup:
    """Status buttons for the sales group (labels follow the card language)."""
    from app.services.notification import STATUS_ACTIONS

    buttons = [
        _btn(t(label_key, lang), f"{LEAD_PREFIX}:{lead_id}:{action}")
        for label_key, action in STATUS_ACTIONS
    ]
    rows = [buttons[i : i + columns] for i in range(0, len(buttons), columns)]
    return InlineKeyboardMarkup(inline_keyboard=rows or [[]])
