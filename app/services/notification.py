"""Sales-group notifications: lead card rendering + delivery.

``build_lead_card`` is a pure function (no network) so the exact text managers
receive can be unit-tested.  :class:`LeadNotifier` only deals with Telegram
transport, retries and the "bot is not in the group" failure mode.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Any

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramRetryAfter,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Message
from app.config import Settings
from app.database.models import Classification, Lead, LeadStatus
from app.i18n import option_label, t
from app.keyboards.inline import lead_actions_kb
from app.options import Region
from app.services.source_tracking import SOURCE_LABELS
from app.services.statuses import (
    ACTION_STATUS,
    STATUS_ACTIONS,
    STATUS_LABEL_KEYS,
    can_transition,
    transition_error_key,
)
from app.utils.text import esc, format_datetime, or_dash

__all__ = [
    "ACTION_STATUS",
    "MAX_MESSAGE_LENGTH",
    "STATUS_ACTIONS",
    "LeadNotifier",
    "build_lead_card",
    "build_visitor_card",
    "card_status_line",
]

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 3800


# --------------------------------------------------------------------------- card
def _labelled(label_key: str, value: str, lang: str) -> str:
    """``🏢 Kompaniya:\n<b>NAME</b>`` - label line plus value line."""
    return f"{t(label_key, lang)}:\n{value}"


def _link(url: str, text: str) -> str:
    return f'<a href="{esc(url)}">{esc(text)}</a>'


def _source_label(lead: Lead) -> str:
    source = str(lead.source or "direct")
    return SOURCE_LABELS.get(source, source.replace("_", " ").title())


def _contact_display(lead: Lead) -> str:
    """Contact person, falling back to the Telegram profile when the answer is thin."""
    name = (lead.contact_name or "").strip()
    if not name:
        parts = [lead.telegram_first_name, lead.telegram_last_name]
        return (
            " ".join(part for part in parts if part)
            or f"@{lead.telegram_username or lead.telegram_user_id}"
        )
    last_name = (lead.telegram_last_name or "").strip()
    if last_name and " " not in name and last_name not in name:
        # user typed "Azizbek", profile says "Karimov" - managers want both
        name = f"{name} {last_name}"
    return name


def _location(lead: Lead, lang: str) -> str:
    region = str(lead.region or "")
    if region == Region.FOREIGN.value and lead.country:
        return esc(lead.country)
    if region == Region.OTHER_REGION.value and lead.country:
        return f"{option_label('region', region, lang)} · {esc(lead.country)}"
    if lead.country and not region:
        return esc(lead.country)
    return option_label("region", region or None, lang)


def _presence_line(label_key: str, value: str | None, lang: str) -> str | None:
    if not value:
        return None
    text = esc(value)
    if value.startswith("@"):
        text = _link(f"https://instagram.com/{value.lstrip('@')}", value)
    elif "." in value and " " not in value:
        href = value if value.startswith("http") else f"https://{value}"
        text = _link(href, value)
    return _labelled(label_key, text, lang)


def card_status_line(lead: Lead, lang: str) -> str:
    """Footer line: current pipeline status plus who changed it and when."""
    status = str(lead.lead_status or LeadStatus.NEW.value)
    label = t(STATUS_LABEL_KEYS.get(status, "status.NEW"), lang)
    if not lead.status_changed_at:
        return t("card.status_line", lang, status=label)
    manager = (
        f"@{lead.manager_username}"
        if lead.manager_username
        else (f"id:{lead.manager_user_id}" if lead.manager_user_id else t("card.value_none", lang))
    )
    return t(
        "card.status_meta",
        lang,
        status=label,
        manager=manager,
        time=format_datetime(lead.status_changed_at),
    )


def build_lead_card(
    lead: Lead,
    *,
    lang: str,
    settings: Settings | None = None,
    show_status_line: bool = True,
) -> str:
    """The lead card posted into the private sales group."""
    timezone_name = getattr(settings, "display_timezone", None)
    classification = str(lead.classification or Classification.LOW.value)

    header = [t("card.title_lead", lang)]
    score_line = (
        f"{t('card.status', lang)}: {t('cls.' + classification, lang)}\n"
        f"{t('card.score', lang)}: {int(lead.score or 0)}/100"
    )
    if lead.is_high_intent:
        score_line += f"\n{t('card.high_intent', lang)}"
    header.append(score_line)

    details = [
        _labelled("card.company", f"<b>{esc(or_dash(lead.company_name))}</b>", lang),
        _labelled(
            "card.contact",
            f"<b>{esc(_contact_display(lead))}</b>"
            + (f"\n{esc(lead.position)}" if lead.position else ""),
            lang,
        ),
        _labelled(
            "card.phone",
            _link(f"tel:{lead.phone}", lead.phone) if lead.phone else t("card.value_none", lang),
            lang,
        ),
        _labelled("card.region", _location(lead, lang), lang),
        _labelled("card.company_type", option_label("company_type", lead.company_type, lang), lang),
        _labelled("card.category", option_label("category", lead.category, lang), lang),
    ]
    if lead.business_relation:
        details.append(
            _labelled("card.relation", option_label("relation", lead.business_relation, lang), lang)
        )
    if lead.preferred_stand_size:
        details.append(
            _labelled("card.stand", option_label("stand", lead.preferred_stand_size, lang), lang)
        )
    if lead.readiness:
        details.append(
            _labelled("card.readiness", option_label("readiness", lead.readiness, lang), lang)
        )

    campaign_value = esc(lead.start_payload or lead.campaign or t("card.value_none", lang))
    attribution = [
        _labelled("card.source", esc(_source_label(lead)), lang),
        _labelled("card.campaign", campaign_value, lang),
    ]
    if lead.creative:
        attribution.append(_labelled("card.creative", esc(lead.creative), lang))

    identity = []
    if lead.telegram_username:
        identity.append(
            _labelled(
                "card.telegram",
                _link(f"https://t.me/{lead.telegram_username}", f"@{lead.telegram_username}"),
                lang,
            )
        )
    identity.append(_labelled("card.user_id", f"<code>{int(lead.telegram_user_id)}</code>", lang))
    identity.append(_labelled("card.lead_id", f"<code>#{esc(lead.lead_code)}</code>", lang))
    identity.append(
        _labelled(
            "card.sent_at",
            format_datetime(lead.completed_at or lead.created_at, timezone_name),
            lang,
        )
    )

    blocks = [
        header[0],
        "\n".join(header[1:]),
        "\n\n".join(details),
        "\n\n".join(
            line
            for line in (
                _presence_line("card.instagram", lead.instagram, lang),
                _presence_line("card.website", lead.website, lang),
            )
            if line
        ),
        "\n\n".join(attribution),
        "\n\n".join(identity),
    ]
    if show_status_line:
        blocks.append(card_status_line(lead, lang))

    return "\n\n".join(block for block in blocks if block).strip()[:MAX_MESSAGE_LENGTH]


def build_visitor_card(lead: Lead, *, lang: str, settings: Settings | None = None) -> str:
    """Compact card for the optional visitor group - no scoring, no stand data."""
    timezone_name = getattr(settings, "display_timezone", None)
    body = "\n\n".join(
        [
            _labelled("card.contact", f"<b>{esc(_contact_display(lead))}</b>", lang),
            _labelled(
                "card.phone",
                _link(f"tel:{lead.phone}", lead.phone)
                if lead.phone
                else t("card.value_none", lang),
                lang,
            ),
            _labelled("card.region", _location(lead, lang), lang),
            _labelled(
                "card.relation", option_label("relation", lead.business_relation, lang), lang
            ),
        ]
    )
    footer = "\n\n".join(
        [
            _labelled(
                "card.telegram",
                f"@{esc(lead.telegram_username)}"
                if lead.telegram_username
                else t("card.value_none", lang),
                lang,
            ),
            _labelled("card.user_id", f"<code>{int(lead.telegram_user_id)}</code>", lang),
            _labelled("card.lead_id", f"<code>#{esc(lead.lead_code)}</code>", lang),
            _labelled("card.source", esc(_source_label(lead)), lang),
            _labelled(
                "card.sent_at",
                format_datetime(lead.completed_at or lead.created_at, timezone_name),
                lang,
            ),
        ]
    )
    return f"{t('card.title_visitor', lang)}\n\n{body}\n\n{footer}"[:MAX_MESSAGE_LENGTH]


# ------------------------------------------------------------------- transport
class LeadNotifier:
    """Delivers lead cards to the sales / visitor groups and keeps them in sync."""

    def __init__(self, bot: Any, settings: Settings) -> None:
        self.bot = bot
        self.settings = settings

    # --------------------------------------------------------------- targets
    @property
    def sales_target(self) -> tuple[int, int | None] | None:
        if not self.settings.sales_group_id:
            return None
        return self.settings.sales_group_id, self.settings.sales_group_topic_id

    @property
    def visitor_target(self) -> tuple[int, int | None] | None:
        if not self.settings.visitor_group_id:
            return None
        return self.settings.visitor_group_id, self.settings.visitor_group_topic_id

    @property
    def configured(self) -> bool:
        return self.sales_target is not None or self.visitor_target is not None

    def card_language(self, lead: Lead) -> str:
        return self.settings.card_language_for(lead.language)

    # ------------------------------------------------------------------ sends
    async def _send(
        self,
        target: tuple[int, int | None] | None,
        text: str,
        reply_markup: Any = None,
    ) -> Message | None:
        if target is None:
            logger.warning("lead notification skipped: group is not configured")
            return None
        if self.bot is None:  # unit tests / dry runs
            logger.info("lead notification skipped: no bot instance")
            return None

        chat_id, thread_id = target
        for attempt in range(3):
            try:
                return await self.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=reply_markup,
                    message_thread_id=thread_id,
                    link_preview_options=LinkPreviewOptions(
                        is_disabled=False, prefer_small_media=True
                    ),
                )
            except TelegramRetryAfter as exc:
                logger.warning("group flood limited, waiting %ss", exc.retry_after)
                await asyncio.sleep(min(int(exc.retry_after), 15))
            except (TelegramForbiddenError, TelegramNotFound):
                logger.error(
                    "cannot post to group %s - add the bot to the group and make sure it can send messages",
                    chat_id,
                )
                await self.alert_admins(
                    f"⚠️ Lead card could not be posted to <code>{chat_id}</code>.\n"
                    "Check SALES_GROUP_ID: the bot must be a member of the group with "
                    "<i>Send messages</i> permission."
                )
                return None
            except TelegramBadRequest as exc:
                logger.error("bad request while posting to %s: %s", chat_id, exc)
                return None
            except Exception:  # pragma: no cover - network safety net
                logger.exception("unexpected error while posting a lead card")
                if attempt == 2:
                    return None
                await asyncio.sleep(1.5 * (attempt + 1))
        return None

    async def send_lead_card(self, lead: Lead) -> Message | None:
        lang = self.card_language(lead)
        return await self._send(
            self.sales_target,
            build_lead_card(lead, lang=lang, settings=self.settings),
            lead_actions_kb(lead.id, lang),
        )

    async def send_visitor_card(self, lead: Lead) -> Message | None:
        lang = self.card_language(lead)
        return await self._send(
            self.visitor_target, build_visitor_card(lead, lang=lang, settings=self.settings)
        )

    async def update_lead_card(self, lead: Lead) -> bool:
        """Re-render the card in place after a status change."""
        if not lead.notify_chat_id or not lead.notify_message_id or self.bot is None:
            return False
        lang = self.card_language(lead)
        body = build_lead_card(lead, lang=lang, settings=self.settings)
        try:
            await self.bot.edit_message_text(
                chat_id=lead.notify_chat_id,
                message_id=lead.notify_message_id,
                text=body,
                link_preview_options=LinkPreviewOptions(is_disabled=False, prefer_small_media=True),
            )
            return True
        except TelegramBadRequest as exc:
            logger.info("could not edit lead card (message too old or unchanged): %s", exc)
            return False
        except Exception:  # pragma: no cover
            logger.exception("unexpected error while editing a lead card")
            return False

    async def lock_card(self, lead: Lead, note: str) -> None:
        """Replace the action buttons with an info button (lead closed)."""
        if not lead.notify_chat_id or not lead.notify_message_id or self.bot is None:
            return
        markup = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=note[:64], callback_data="noop")]]
        )
        with suppress(TelegramBadRequest):  # pragma: no cover - there is nothing to change
            await self.bot.edit_message_reply_markup(
                chat_id=lead.notify_chat_id,
                message_id=lead.notify_message_id,
                reply_markup=markup,
            )

    # ------------------------------------------------------------------- ACL
    def allows_manager(self, user_id: int, chat_id: int | None) -> bool:
        """Managers = ADMIN_USER_IDS, or (by default) any member of the private sales group."""
        if user_id in self.settings.admin_user_ids:
            return True
        if self.settings.allow_group_managers and self.settings.sales_group_id:
            return chat_id == self.settings.sales_group_id
        return False

    @staticmethod
    def can_transition(lead: Lead, new_status: str) -> bool:
        return can_transition(lead.lead_status, new_status)

    @staticmethod
    def transition_error_key(current: str | None, new: str) -> str:
        return transition_error_key(current, new)

    async def alert_admins(self, text: str) -> None:
        """Operational alerts (broken group id, delivery failures, ...)."""
        if self.bot is None:
            return
        for admin_id in self.settings.admin_user_ids:
            try:
                await self.bot.send_message(admin_id, text[:MAX_MESSAGE_LENGTH])
            except Exception as exc:  # pragma: no cover - best effort
                logger.debug("admin alert to %s failed: %s", admin_id, type(exc).__name__)
