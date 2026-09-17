"""Manager-side surface: admin analytics commands + lead status buttons in the sales group.

Commands are restricted to ``ADMIN_USER_IDS``.  The inline status buttons on a lead
card may additionally be used by members of the private sales group (toggle with
``ALLOW_GROUP_MANAGERS``), because that is how a sales team actually works.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, LinkPreviewOptions, Message

from app.config import Settings
from app.database.models import Lead, LeadStatus
from app.filters import IsOwnerOrAdmin
from app.i18n import option_label, t
from app.services.lead_service import LeadService
from app.services.notification import LeadNotifier, build_lead_card
from app.services.source_tracking import SOURCE_LABELS
from app.services.statuses import ACTION_STATUS, STATUS_LABEL_KEYS, is_valid_status
from app.utils.text import clean_text, esc, format_datetime

__all__ = ["router", "start_of_today"]

logger = logging.getLogger(__name__)

router = Router(name="admin")

_NO_PREVIEW = LinkPreviewOptions(is_disabled=True)

_ADMIN_COMMANDS = (
    "stats",
    "leads",
    "hot",
    "warm",
    "today",
    "source",
    "lead",
    "setstatus",
    "chatid",
)

_FUNNEL_ORDER = (
    ("STARTED", "starts"),
    ("LANGUAGE_SELECTED", "language"),
    ("INTENT_SELECTED", "intent"),
    ("COMPANY_TYPE_SELECTED", "type"),
    ("CATEGORY_SELECTED", "category"),
    ("COMPANY_ENTERED", "company"),
    ("CONTACT_ENTERED", "contact"),
    ("PHONE_ENTERED", "phone"),
    ("COMPLETED", "done"),
)


def start_of_today(timezone_name: str | None) -> datetime:
    """Midnight of the operational day in the sales timezone, normalised to UTC."""
    try:
        zone = ZoneInfo(timezone_name or "UTC")
    except Exception:  # pragma: no cover - slim images without tzdata
        zone = UTC
    local_midnight = datetime.now(zone).replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(UTC)


def _lead_line(lead: Lead) -> str:
    company = esc(clean_text(lead.company_name or lead.contact_name or "-", max_len=38))
    classification = esc(lead.classification or "LOW")
    status = esc(str(lead.lead_status or LeadStatus.NEW.value))
    day = format_datetime(lead.created_at).split(" ")[0]
    phone = esc(lead.phone or "no phone")
    return (
        f"<code>#{esc(lead.lead_code)}</code> · {classification} {int(lead.score or 0)} "
        f"· {company} · {phone} · {status} · {day}"
    )


async def _reply(message: Message, text: str) -> None:
    await message.answer(text[:3900], link_preview_options=_NO_PREVIEW)


@router.message(Command(*_ADMIN_COMMANDS), IsOwnerOrAdmin())
async def admin_command(message: Message, command: CommandObject, **data: Any) -> None:
    """One entry point for all admin commands - keeps the routing table short."""
    settings: Settings = data["settings"]
    leads: LeadService = data["leads"]
    repo = leads.repo
    name = (command.command or "").lower()
    args = (command.args or "").strip()

    if name == "chatid":
        await _reply(
            message,
            "Use these values in <b>.env</b>:\n"
            f"chat id: <code>{message.chat.id}</code>\n"
            f"topic id: <code>{message.message_thread_id or 0}</code>\n"
            f"your user id: <code>{message.from_user.id if message.from_user else '?'}</code>",
        )
        return

    if name == "stats":
        await _reply(message, await _stats(repo, settings))
        return

    if name == "source":
        await _reply(message, await _sources(repo))
        return

    if name == "lead":
        await _reply(message, await _lead_detail(repo, args))
        return

    if name == "setstatus":
        if message.from_user is None or message.from_user.id not in settings.admin_user_ids:
            await _reply(message, t("err.admin_only", settings.default_language))
            return
        await _reply(message, await _set_status(leads, args))
        return

    classification = {"hot": "HOT", "warm": "WARM"}.get(name)
    since = start_of_today(settings.display_timezone) if name == "today" else None
    limit = max(1, min(int(args), 50)) if args.isdigit() else 10

    rows = await repo.list_leads(classification=classification, since=since, limit=limit)
    if not rows:
        await _reply(message, t("info.no_leads", settings.default_language))
        return

    headers = {
        "hot": f"🔥 HOT leads ({len(rows)})",
        "warm": f"🌤 WARM leads ({len(rows)})",
        "today": f"📅 Completed today ({len(rows)})",
    }
    header = headers.get(name, f"📋 Latest leads ({len(rows)})")
    body = "\n".join(_lead_line(lead) for lead in rows)
    await _reply(message, f"<b>{header}</b>\n{body}")


async def _stats(repo: Any, settings: Settings) -> str:
    since = start_of_today(settings.display_timezone)
    today = await repo.classification_counts(since=since)
    visitors_today = await repo.visitor_count(since=since)
    today_total = await repo.count_leads(since=since)
    total_completed = await repo.count_leads()
    qualified = await repo.count_leads(classification=["HOT", "WARM"])
    statuses = await repo.status_counts()
    booked = int(statuses.get(LeadStatus.BOOKED.value, 0))
    starts = await repo.started_count()
    funnel = await repo.funnel_counts()
    average = await repo.average_score()
    total_visitors = await repo.visitor_count()
    completion = round(100.0 * total_completed / starts, 1) if starts else 0.0

    lines = [
        "<b>📊 FOODERA Leads</b>",
        "",
        "<b>Today:</b>",
        f"Total: {today_total}",
        (
            f"HOT: {today.get('HOT', 0)} · WARM: {today.get('WARM', 0)} · "
            f"COLD: {today.get('COLD', 0)} · Visitors: {visitors_today}"
        ),
        "",
        "<b>Total:</b>",
        f"Leads: {total_completed} · Qualified: {qualified} · Booked: {booked}",
        f"Visitors: {total_visitors} · Avg score: {average}",
        f"Starts: {starts} · Completion rate: {completion}%",
        "",
        "<b>Funnel (unique users):</b>",
        " › ".join(f"{label}={funnel.get(event, 0)}" for event, label in _FUNNEL_ORDER),
        "",
        "<b>Pipeline:</b> "
        + " · ".join(f"{key}={value}" for key, value in sorted(statuses.items())),
        "",
        (
            f"<i>Thresholds: HOT ≥ {settings.hot_min_score} · WARM ≥ {settings.warm_min_score} · "
            f"COLD ≥ {settings.cold_min_score} · push from {settings.qualify_min_classification.upper()} "
            "and up (see .env)</i>"
        ),
    ]
    return "\n".join(lines)


async def _sources(repo: Any) -> str:
    rows = await repo.source_breakdown()
    payloads = await repo.payload_breakdown(limit=15)
    if not rows:
        return "No traffic recorded yet."

    lines = ["<b>📢 Source performance</b>", ""]
    for row in rows:
        label = SOURCE_LABELS.get(str(row["source"]), str(row["source"]))
        campaign = esc(row["campaign"] or "—")
        total, completed = int(row["total"] or 0), int(row["completed"] or 0)
        qualified, hot, visitors = (
            int(row["qualified"] or 0),
            int(row["hot"] or 0),
            int(row["visitors"] or 0),
        )
        rate = round(100.0 * completed / total, 1) if total else 0.0
        lines.append(
            f"<b>{esc(label)}</b> · <code>{campaign}</code>\n"
            f"  leads {total} · completed {completed} ({rate}%) · qualified {qualified} · "
            f"hot {hot} · visitors {visitors}"
        )
    if payloads:
        lines.extend(["", "<b>By start payload (creative):</b>"])
        for row in payloads:
            lines.append(
                f"<code>{esc(row['start_payload'])}</code>: leads {int(row['total'])} · "
                f"qualified {int(row['qualified'])} · visitors {int(row['visitors'])}"
            )
    return "\n".join(lines)


async def _lead_detail(repo: Any, args: str) -> str:
    if not args:
        return "Usage: /lead &lt;FD000123 | id&gt;"
    lead = await repo.find_lead(args)
    if lead is None:
        return t("err.lead_not_found", "uz")

    lang = lead.language or "uz"
    fields = [
        ("Company", clean_text(lead.company_name or "-", max_len=80)),
        (
            "Contact",
            clean_text(
                " ".join(part for part in (lead.contact_name, lead.position) if part) or "-",
                max_len=80,
            ),
        ),
        ("Phone", clean_text(lead.phone or "-", max_len=32)),
        ("Region", option_label("region", lead.region, lang)),
        ("Country", clean_text(lead.country or "-", max_len=60)),
        ("Type", option_label("company_type", lead.company_type, lang)),
        ("Category", option_label("category", lead.category, lang)),
        ("Stand", option_label("stand", lead.preferred_stand_size, lang)),
        ("Readiness", option_label("readiness", lead.readiness, lang)),
        ("Relation", option_label("relation", lead.business_relation, lang)),
        ("Website", clean_text(lead.website or "-", max_len=60)),
        ("Instagram", clean_text(lead.instagram or "-", max_len=60)),
        ("Source", f"{lead.source} / {lead.campaign or '-'} / {lead.creative or '-'}"),
        ("Payload", clean_text(lead.start_payload or "-", max_len=80)),
        (
            "Telegram",
            f"@{lead.telegram_username}" if lead.telegram_username else str(lead.telegram_user_id),
        ),
    ]
    body = "\n".join(f"{label}: <b>{esc(value)}</b>" for label, value in fields)
    breakdown = lead.score_breakdown or {}
    score_line = (
        f"Score: <b>{int(lead.score or 0)}/100</b> · {esc(lead.classification or 'LOW')}"
        + (" · 🔥 HIGH INTENT" if lead.is_high_intent else "")
    )
    breakdown_line = (
        " · ".join(f"{esc(key)} +{int(value)}" for key, value in breakdown.items()) or "—"
    )
    manager = (
        f" · @{esc(lead.manager_username)} {format_datetime(lead.status_changed_at)}"
        if lead.manager_username
        else ""
    )
    status_line = f"Status: <b>{esc(str(lead.lead_status))}</b>{manager}"

    events = await repo.events_for_lead(lead.id)
    trail = " › ".join(esc(str(event.event)) for event in events[-12:]) or "—"
    link = (
        f'\n\n<a href="https://t.me/{lead.telegram_username}">Open profile</a>'
        if lead.telegram_username
        else ""
    )

    return (
        f"<b>#{esc(lead.lead_code)}</b> · user <code>{int(lead.telegram_user_id)}</code>\n"
        f"{score_line}\n{breakdown_line}\n{status_line}\n\n{body}\n\n<i>{trail}</i>{link}"
    )


async def _set_status(leads: LeadService, args: str) -> str:
    parts = args.split()
    if len(parts) < 2:
        return (
            "Usage: /setstatus &lt;FD000123 | id&gt; "
            "&lt;NEW|CONTACTED|NEGOTIATION|BOOKED|NOT_QUALIFIED|CLOSED&gt;"
        )
    identifier, status = parts[0], parts[1].upper()
    if not is_valid_status(status):
        return f"Unknown status {esc(status)}."
    lead = await leads.repo.find_lead(identifier)
    if lead is None:
        return t("err.lead_not_found", leads.settings.default_language)
    result = await leads.change_status(
        lead.id,
        status,
        manager_user_id=None,
        manager_username="admin",
        force=True,
    )
    if not result.ok or result.lead is None:
        return t("err.lead_not_found", leads.settings.default_language)
    return f"#{esc(result.lead.lead_code)} → {esc(status)}"


# --------------------------------------------------------------- sales-group buttons
@router.callback_query(F.data.startswith("lead:"))
async def lead_status_button(callback: CallbackQuery, **data: Any) -> None:
    """``lead:<id>:<action>`` - a manager taps a status on the lead card."""
    settings: Settings = data["settings"]
    leads: LeadService = data["leads"]
    notifier: LeadNotifier = data["notifier"]
    lang: str = data.get("lang", settings.default_language)

    from_user = callback.from_user
    chat_id = callback.message.chat.id if callback.message else None
    if from_user is None or not notifier.allows_manager(from_user.id, chat_id):
        await callback.answer(t("err.not_manager", lang), show_alert=True)
        return

    parts = str(callback.data or "").split(":")
    if len(parts) != 3 or not parts[1].isdigit() or parts[2] not in ACTION_STATUS:
        await callback.answer(t("err.stale_callback", lang), show_alert=True)
        return

    lead_id, action = int(parts[1]), parts[2]
    new_status = ACTION_STATUS[action]
    result = await leads.change_status(
        lead_id,
        new_status,
        manager_user_id=from_user.id,
        manager_username=from_user.username,
        force=from_user.id in settings.admin_user_ids,
    )

    if not result.ok:
        message_key = result.message_key or "err.status_transition"
        await callback.answer(t(message_key, lang), show_alert=True)
        return

    # the card in the sales group is edited by the service; if that was not possible
    # (e.g. the card was forwarded into another chat) edit the tapped message itself
    if not result.card_updated and callback.message is not None and result.lead is not None:
        try:
            await callback.message.edit_text(
                build_lead_card(
                    result.lead, lang=notifier.card_language(result.lead), settings=settings
                ),
                link_preview_options=_NO_PREVIEW,
            )
        except TelegramBadRequest as exc:  # pragma: no cover
            logger.debug("could not edit forwarded lead card: %s", exc)

    label = t(STATUS_LABEL_KEYS.get(new_status, "status.NEW"), lang)
    await callback.answer(f"✅ {label}")
