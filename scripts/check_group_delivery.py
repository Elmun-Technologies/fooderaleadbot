#!/usr/bin/env python3
"""Why is nothing reaching the group? End-to-end delivery diagnostics.

    python scripts/check_group_delivery.py            # read-only checks
    python scripts/check_group_delivery.py --send     # also post a real sample lead card

It checks, in order and with the exact remediation for each failure:

    1. configuration (BOT_TOKEN, SALES_GROUP_ID, *_TOPIC_ID, qualification gate)
    2. the token itself (Telegram getMe)
    3. the group: can Telegram see the chat, is the bot a member, may it post
    4. the topic (when *_TOPIC_ID is set) and actual delivery of a sample card

Run it where the bot runs, so it sees the same environment:

    fly ssh console -C "python scripts/check_group_delivery.py --send"

Exit code is 0 only when every configured target passes.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # allow `python scripts/check_group_delivery.py` from anywhere
    sys.path.insert(0, str(ROOT))

from aiogram import Bot  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.enums import ParseMode  # noqa: E402
from aiogram.exceptions import (  # noqa: E402
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramUnauthorizedError,
)
from app.config import Settings, get_settings  # noqa: E402
from app.database.models import Lead  # noqa: E402
from app.services.notification import (  # noqa: E402
    _bad_request_hint,
    build_lead_card,
)

#: A fully answered exhibitor lead - the same shape the sales group normally receives.
SAMPLE_EXHIBITOR = {
    "id": 0,
    "lead_code": "DIAG0001",
    "telegram_user_id": 4242,
    "telegram_username": "diagnostics",
    "telegram_first_name": "Delivery",
    "telegram_last_name": "Diagnostics",
    "language": "uz",
    "source": "telegram_ads",
    "campaign": "group_delivery_check",
    "start_payload": "diag",
    "lead_type": "exhibitor",
    "intent": "stand",
    "company_type": "manufacturer",
    "category": "non_alcoholic_drinks",
    "company_name": "Delivery Diagnostics LLC",
    "region": "tashkent",
    "online_presence": "both",
    "website": "example.uz",
    "instagram": "@example_uz",
    "contact_name": "Bot Diagnostics",
    "position": "Automated check",
    "phone": "+998901234567",
    "preferred_stand_size": "size_18",
    "readiness": "ready_to_book",
    "score": 96,
    "classification": "HOT",
    "is_high_intent": True,
    "lead_status": "NEW",
    "is_draft": False,
    "created_at": datetime.now(UTC),
    "completed_at": datetime.now(UTC),
}

_failures = 0


def report(ok: bool, label: str, *, fix: str = "") -> bool:
    """Print one check line and remember failures for the exit code."""
    global _failures
    icon = "OK  " if ok else "FAIL"
    if not ok:
        _failures += 1
    print(f"  [{icon}] {label}")
    if not ok and fix:
        print(f"         -> {fix}")
    return ok


def skip(label: str) -> None:
    print(f"  [SKIP] {label}")


def sample_lead() -> Lead:
    return Lead(**SAMPLE_EXHIBITOR)  # type: ignore[arg-type]


def check_configuration(settings: Settings) -> None:
    print("\n1) Configuration")
    report(
        bool(settings.bot_token_value),
        "BOT_TOKEN is set",
        fix="put it into .env / `fly secrets set BOT_TOKEN=…`",
    )

    if not settings.sales_group_id and not settings.visitor_group_id:
        report(
            False,
            "neither SALES_GROUP_ID nor VISITOR_GROUP_ID is set",
            fix="qualified leads are only stored in the database - set SALES_GROUP_ID to the "
            "negative -100… id of the sales group (`fly secrets set SALES_GROUP_ID=-100…`)",
        )
    else:
        if settings.sales_group_id:
            report(
                settings.sales_group_id < 0,
                f"SALES_GROUP_ID = {settings.sales_group_id}"
                + (
                    f" (topic {settings.sales_group_topic_id})"
                    if settings.sales_group_topic_id
                    else ""
                ),
                fix="a group id must be negative; a supergroup id starts with -100",
            )
        if settings.visitor_group_id:
            report(
                settings.visitor_group_id < 0,
                f"VISITOR_GROUP_ID = {settings.visitor_group_id}"
                + (
                    f" (topic {settings.visitor_group_topic_id})"
                    if settings.visitor_group_topic_id
                    else ""
                ),
                fix="a group id must be negative; a supergroup id starts with -100",
            )

    gate = {
        "hot": "HOT only",
        "warm": "WARM and HOT",
        "cold": "COLD and above",
    }[settings.qualify_min_classification]
    print(
        f"  [info] qualification gate: {gate} leads are pushed"
        + (" (+ phone required" if settings.require_phone_for_sales else "")
        + (", + company name required)" if settings.require_company_name_for_sales else ")")
    )
    print(
        "         leads below the gate are kept in the database but deliberately never\n"
        "         reach the group - if *some* leads arrive and others do not, that is this\n"
        f"         setting (QUALIFY_MIN_CLASSIFICATION={settings.qualify_min_classification})."
    )


async def check_target(
    bot: Bot,
    settings: Settings,
    *,
    name: str,
    chat_id: int | None,
    topic_id: int | None,
    send: bool,
) -> None:
    if not chat_id:
        skip(f"{name}: not configured")
        return

    print(f"\n   {name}  (chat {chat_id}" + (f", topic {topic_id}" if topic_id else "") + ")")

    where = {"sales": "SALES_GROUP_ID", "visitor": "VISITOR_GROUP_ID"}.get(
        name, f"{name.upper()}_GROUP_ID"
    )
    topic_var = where.replace("GROUP_ID", "GROUP_TOPIC_ID")

    # --- can Telegram see the chat at all? -------------------------------------
    try:
        chat = await bot.get_chat(chat_id)
    except (TelegramForbiddenError, TelegramNotFound):
        report(
            False,
            f"the bot cannot see the chat ({where}={chat_id})",
            fix="add the bot to the group; if it was already there, the group was probably "
            "upgraded to a supergroup - send /chatid inside the group and update the id",
        )
        return
    except TelegramBadRequest as exc:
        report(
            False,
            f"getChat failed: {exc}",
            fix="a supergroup id is negative and starts with -100 (plain positive ids and "
            "usernames do not work)",
        )
        return

    title = getattr(chat, "title", None) or chat.type
    report(True, f"chat found: {title!r} ({chat.type})")

    is_forum = bool(getattr(chat, "is_forum", False))
    if topic_id:
        report(
            is_forum,
            f"{topic_var}={topic_id} is set and the group has Topics enabled"
            if is_forum
            else f"{topic_var}={topic_id} is set but this group has NO Topics",
            fix=f"enable Topics in the group settings or clear {topic_var}",
        )
    elif is_forum:
        print(
            f"  [info] the group uses Topics but {topic_var} is empty - cards land in the\n"
            "         General topic; set the topic id to post into a specific one"
        )

    # --- is the bot a member that may post? -------------------------------------
    me = await bot.get_me()
    try:
        member = await bot.get_chat_member(chat_id, me.id)
    except TelegramBadRequest as exc:
        report(False, f"membership check failed: {exc}", fix="add the bot to the group")
        return

    status = str(getattr(member, "status", "?"))
    if status in {"left", "kicked"}:
        report(False, f"the bot is {status} in the group", fix="re-add the bot to the group")
        return
    if status == "restricted" and not getattr(member, "can_send_messages", True):
        report(
            False,
            "the bot is restricted and may not send messages",
            fix="unrestrict the bot or make it an administrator",
        )
        return
    report(True, f"bot membership: {status}")

    # --- the real thing: deliver a card -----------------------------------------
    if not send:
        skip("delivery test (re-run with --send to post a sample card into the group)")
        return

    lead = sample_lead()
    card = "🧪 <b>DIAGNOSTICS</b> - sample lead card\n\n" + build_lead_card(
        lead, lang=settings.card_language_for(lead.language), settings=settings
    )
    try:
        message = await bot.send_message(
            chat_id=chat_id,
            text=card,
            message_thread_id=topic_id,
        )
    except TelegramBadRequest as exc:
        report(False, f"sample card rejected: {exc}", fix=_hint_text(exc, chat_id))
        return
    except (TelegramForbiddenError, TelegramNotFound) as exc:
        report(
            False,
            f"sample card rejected: {exc}",
            fix="the bot was removed from the group or lost posting rights - see above",
        )
        return
    report(
        True,
        f"sample card posted as message #{message.message_id}"
        + (f" into topic {topic_id}" if topic_id else ""),
    )


def _hint_text(exc: TelegramBadRequest, chat_id: int) -> str:
    """Plain-text version of the admin-alert hint (no HTML tags in the console)."""
    hint = _bad_request_hint(exc, chat_id)
    for tag in ("<code>", "</code>", "<i>", "</i>", "<b>", "</b>"):
        hint = hint.replace(tag, "")
    return hint


async def run(send: bool) -> int:
    settings = get_settings()
    print("FOODERA lead bot - group delivery diagnostics")
    print("=" * 46)

    check_configuration(settings)
    if not settings.bot_token_value:
        return 1

    bot = Bot(
        token=settings.bot_token_value,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        print("\n2) Bot token")
        try:
            me = await bot.get_me()
            report(True, f"token valid - the bot is @{me.username} (id {me.id})")
        except TelegramUnauthorizedError:
            report(
                False,
                "Telegram rejected BOT_TOKEN (401)",
                fix="use the exact token from @BotFather",
            )
            return 1
        except TelegramAPIError as exc:
            report(False, f"cannot reach Telegram: {exc}", fix="check outbound HTTPS/DNS")
            return 1

        print("\n3) Group targets")
        await check_target(
            bot,
            settings,
            name="sales",
            chat_id=settings.sales_group_id,
            topic_id=settings.sales_group_topic_id,
            send=send,
        )
        await check_target(
            bot,
            settings,
            name="visitor",
            chat_id=settings.visitor_group_id,
            topic_id=settings.visitor_group_topic_id,
            send=send,
        )
    finally:
        await bot.session.close()

    print("\n" + "=" * 46)
    if _failures:
        print(f"RESULT: {_failures} problem(s) found - every FAIL line names its fix.")
        return 1
    print("RESULT: all checks passed. If leads still do not arrive, the cause is the")
    print("qualification gate above (score too low) - see the [info] block in step 1.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="post a sample lead card into each configured group (visible to managers)",
    )
    args = parser.parse_args()
    return asyncio.run(run(args.send))


if __name__ == "__main__":
    raise SystemExit(main())
