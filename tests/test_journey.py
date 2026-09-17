"""Full lead journey through the real aiogram routers.

Nothing is mocked except the Telegram HTTP layer: a recording ``BaseSession`` stands in
for the Bot API, so ``/start`` -> language -> 10 questions -> qualification -> sales-group
card -> manager taps "booked" is exercised end to end (routers, middlewares, FSM, DB).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import (
    AnswerCallbackQuery,
    DeleteMessage,
    EditMessageReplyMarkup,
    EditMessageText,
    GetMe,
    SendMessage,
)
from aiogram.types import Chat, Message, Update, User
from app.bot import create_dispatcher
from app.config import Settings
from app.database.models import Classification, LeadStatus
from app.database.repository import LeadRepository

USER_ID = 4242
PRIVATE_CHAT = USER_ID
BOT_MESSAGE_ID = 500
SALES_GROUP = -1001234567890

USER_DICT = {
    "id": USER_ID,
    "is_bot": False,
    "first_name": "Azizbek",
    "last_name": "Karimov",
    "username": "azizbek_karimov",
    "language_code": "uz",
}


class RecordingSession(BaseSession):
    """A Bot API that never says no - and remembers everything the bot wanted to send."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[Any] = []
        self._next_id = 1000

    async def close(self) -> None:
        return None

    async def stream_content(
        self, *args: Any, **kwargs: Any
    ) -> AsyncGenerator[bytes, None]:  # pragma: no cover
        yield b""

    def _message(self, chat_id: int, text: str | None, message_id: int | None = None) -> Message:
        chat_type = "private" if (chat_id or 0) > 0 else "supergroup"
        if message_id is None:
            self._next_id += 1
            message_id = self._next_id
        return Message(
            message_id=message_id,
            date=datetime.now(UTC),
            chat=Chat(id=chat_id, type=chat_type),
            text=text,
        )

    async def make_request(self, bot: Bot, method: Any, timeout: int | None = None) -> Any:
        self.calls.append(method)
        if isinstance(method, GetMe):
            return User(id=777, is_bot=True, first_name="FOODERA EXPO", username="foodera_bot")
        if isinstance(method, SendMessage):
            return self._message(int(method.chat_id), method.text)
        if isinstance(method, (EditMessageText, EditMessageReplyMarkup)):
            return self._message(
                int(method.chat_id), getattr(method, "text", None), message_id=method.message_id
            )
        if isinstance(method, DeleteMessage):
            return True
        if isinstance(method, AnswerCallbackQuery):
            return True
        return True

    # ------------------------------------------------------------- assertions
    def sent_to(self, chat_id: int) -> list[str]:
        return [
            method.text or ""
            for method in self.calls
            if isinstance(method, SendMessage) and int(method.chat_id) == chat_id
        ]

    def edits(self) -> list[str]:
        return [method.text or "" for method in self.calls if isinstance(method, EditMessageText)]

    def messages_to(self, chat_id: int) -> list[str]:
        """Every text that ended up in a chat, in order - new messages and edits alike."""
        return [
            method.text or ""
            for method in self.calls
            if isinstance(method, (SendMessage, EditMessageText)) and int(method.chat_id) == chat_id
        ]

    def last_text(self, chat_id: int = PRIVATE_CHAT) -> str:
        """The last thing the user (or the group) can see - what the tests assert on."""
        texts = self.messages_to(chat_id)
        assert texts, f"the bot never wrote anything to chat {chat_id}"
        return texts[-1]

    def answers(self) -> list[tuple[str, bool]]:
        """``(text, show_alert)`` of every callback answer, in order."""
        return [
            (method.text or "", bool(method.show_alert))
            for method in self.calls
            if isinstance(method, AnswerCallbackQuery)
        ]

    def last_answer(self) -> tuple[str, bool]:
        answers = self.answers()
        assert answers, "the bot never answered a callback"
        return answers[-1]

    def keyboards(self) -> list[Any]:
        return [
            getattr(method, "reply_markup", None)
            for method in self.calls
            if isinstance(method, (SendMessage, EditMessageText))
        ]

    def last_keyboard_texts(self) -> list[str]:
        for markup in reversed(self.keyboards()):
            if markup is not None and getattr(markup, "inline_keyboard", None):
                return [button.text or "" for row in markup.inline_keyboard for button in row]
        return []

    def last_keyboard_callbacks(self) -> list[str]:
        for method in reversed(self.calls):
            if isinstance(method, (SendMessage, EditMessageText)):
                markup = getattr(method, "reply_markup", None)
                if markup is not None and getattr(markup, "inline_keyboard", None):
                    return [
                        button.callback_data or ""
                        for row in markup.inline_keyboard
                        for button in row
                    ]
        return []


@pytest.fixture(scope="module")
def journey_settings(tmp_path_factory) -> Settings:
    """One settings/database/dispatcher pair per module.

    aiogram routers are module singletons (a router can only be attached to one
    dispatcher), so the wiring is built once and the state is wiped between tests.
    """
    directory = tmp_path_factory.mktemp("journey")
    return Settings(
        _env_file=None,
        bot_token="123456:journey-test-token-abcdefg",
        database_url=f"sqlite+aiosqlite:///{directory / 'journey.db'}",
        sales_group_id=SALES_GROUP,
        sales_group_topic_id=None,
        visitor_group_id=None,
        admin_user_ids=[111],
        default_language="uz",
        support_username="foodera_support",
        display_timezone="UTC",
        rate_limit_per_minute=100000,
        auto_create_tables=True,
    )


@pytest.fixture(scope="module")
async def journey(journey_settings):
    from app.database.session import Database

    database = Database.from_url(journey_settings.database_url)
    await database.create_schema()
    session = RecordingSession()
    bot = Bot(token=journey_settings.bot_token_value, session=session)
    dispatcher = create_dispatcher(journey_settings, database, bot)
    yield SimpleNamespace(
        bot=bot, dp=dispatcher, database=database, session=session, settings=journey_settings
    )
    await database.dispose()


@pytest.fixture(autouse=True)
async def clean_state(journey):
    """Truncate tables, reset FSM storage and the recorded API calls."""
    from sqlalchemy import text

    async with journey.database.engine.begin() as connection:
        for table in ("lead_events", "leads", "bot_users"):
            await connection.execute(text(f"DELETE FROM {table}"))
    storage = journey.dp.fsm.storage
    if hasattr(storage, "storage"):
        storage.storage.clear()
    journey.session.calls.clear()
    yield


@pytest.fixture
def harness(journey) -> Harness:
    return Harness(journey.bot, journey.dp)


@pytest.fixture
def session(journey) -> RecordingSession:
    return journey.session


@pytest.fixture
def settings(journey) -> Settings:
    return journey.settings


class FreshRepo:
    """Repository proxy for assertions: one short session per call.

    A long-lived session would keep reading the snapshot its first SELECT took, so a
    status change made by the bot (on another connection) would look like it never
    happened - which is exactly what these tests must not confuse themselves with.
    """

    def __init__(self, database) -> None:
        self._database = database

    def __getattr__(self, name: str):
        async def call(*args: Any, **kwargs: Any) -> Any:
            async with self._database.session() as session:
                return await getattr(LeadRepository(session), name)(*args, **kwargs)

        return call


@pytest.fixture
def repo(journey) -> FreshRepo:
    return FreshRepo(journey.database)


class Harness:
    def __init__(self, bot: Bot, dispatcher: Any) -> None:
        self.bot = bot
        self.dispatcher = dispatcher
        self.update_id = 0

    async def send(
        self,
        text: str | None = None,
        *,
        chat_id: int = PRIVATE_CHAT,
        contact_phone: str | None = None,
        user: dict | None = None,
    ) -> None:
        self.update_id += 1
        message: dict[str, Any] = {
            "message_id": self.update_id,
            "date": datetime.now(UTC).isoformat(),
            "chat": {"id": chat_id, "type": "private", "first_name": "Azizbek"},
            "from": user or USER_DICT,
        }
        if contact_phone:
            message["contact"] = {
                "phone_number": contact_phone,
                "first_name": (user or USER_DICT)["first_name"],
                "user_id": (user or USER_DICT)["id"],
            }
        else:
            message["text"] = text
            length = len((text or "").split(" ")[0])
            message["entities"] = (
                [{"type": "bot_command", "offset": 0, "length": length}]
                if (text or "").startswith("/")
                else []
            )
        await self.feed({"update_id": self.update_id, "message": message})

    async def send_media(self, *, caption: str | None = None, chat_id: int = PRIVATE_CHAT) -> None:
        """A photo (with an optional caption) - the funnel must survive it."""
        self.update_id += 1
        message: dict[str, Any] = {
            "message_id": self.update_id,
            "date": datetime.now(UTC).isoformat(),
            "chat": {"id": chat_id, "type": "private", "first_name": "Azizbek"},
            "from": USER_DICT,
            "photo": [
                {
                    "file_id": "small",
                    "file_unique_id": "uq-small",
                    "file_size": 120,
                    "width": 90,
                    "height": 90,
                }
            ],
        }
        if caption:
            message["caption"] = caption
        await self.feed({"update_id": self.update_id, "message": message})

    async def press(
        self, data: str, *, chat_id: int = PRIVATE_CHAT, user: dict | None = None
    ) -> None:
        self.update_id += 1
        await self.feed(
            {
                "update_id": self.update_id,
                "callback_query": {
                    "id": f"query-{self.update_id}",
                    "from": user or USER_DICT,
                    "chat_instance": "instance",
                    "data": data,
                    "message": {
                        "message_id": BOT_MESSAGE_ID,
                        "date": datetime.now(UTC).isoformat(),
                        "chat": {"id": chat_id, "type": "private" if chat_id > 0 else "supergroup"},
                        "from": {"id": 777, "is_bot": True, "first_name": "FOODERA EXPO"},
                        "text": "question",
                    },
                },
            }
        )

    async def feed(self, payload: dict[str, Any]) -> None:
        update = Update.model_validate(payload, context={"bot": self.bot})
        await self.dispatcher.feed_update(self.bot, update)


async def complete_questionnaire(harness: Harness, *, readiness: str = "ready_to_book") -> None:
    """Drive the exhibitor funnel from /start to the last question."""
    await harness.send("/start tgads_foodera_uz_01")
    await harness.press("lang:uz")
    await harness.press("flow:start")
    await harness.press("q:intent:stand")
    await harness.press("q:company_type:manufacturer")
    await harness.press("q:category:confectionery_and_bakery")
    await harness.send("SAMARQAND FOOD LLC")
    await harness.press("q:region:samarkand")
    await harness.press("q:online:both")
    await harness.send("samarqandfood.uz\n@samarqand_food")
    await harness.send("Azizbek — Savdo direktori")
    await harness.send(contact_phone="+998 90 123 45 67")
    await harness.press("q:stand:size_18")
    await harness.press(f"q:readiness:{readiness}")


class TestJourney:
    async def test_welcome_flow_asks_the_language_first(
        self, harness: Harness, session: RecordingSession, repo: LeadRepository
    ) -> None:
        await harness.send("/start tgads_foodera_uz_01")
        assert session.sent_to(PRIVATE_CHAT)[-1].startswith("🌐")
        assert session.last_keyboard_texts() == ["🇺🇿 O‘zbekcha", "🇷🇺 Русский"]

        user = await repo.get_user(USER_ID)
        assert user is not None
        assert user.start_payload == "tgads_foodera_uz_01"
        assert user.source == "telegram_ads"
        assert user.campaign == "foodera"
        assert user.creative == "uz_01"

    async def test_language_choice_leads_to_the_welcome_message(
        self, harness: Harness, session: RecordingSession
    ) -> None:
        await harness.send("/start tgads_foodera_ru_01")
        await harness.press("lang:ru")
        assert "Здравствуйте" in session.sent_to(PRIVATE_CHAT)[-1]
        assert "Начать →" in session.last_keyboard_texts()

    async def test_full_journey_creates_a_hot_lead_and_notifies_the_group(
        self, harness: Harness, session: RecordingSession, repo: LeadRepository, settings
    ) -> None:
        await complete_questionnaire(harness)

        cards = session.sent_to(settings.sales_group_id)
        assert cards, "the sales group must receive the lead card"
        card = cards[-1]
        assert "SAMARQAND FOOD LLC" in card
        assert "+998901234567" in card
        assert "tgads_foodera_uz_01" in card

        leads = await repo.list_leads()
        assert len(leads) == 1
        lead = leads[0]
        assert lead.classification == Classification.HOT.value
        assert lead.score == 100
        assert lead.lead_type == "exhibitor"
        assert lead.lead_status == LeadStatus.NEW.value
        assert lead.phone == "+998901234567"
        assert lead.contact_name == "Azizbek"
        assert lead.position == "Savdo direktori"
        assert lead.website == "samarqandfood.uz"
        assert lead.instagram == "@samarqand_food"
        assert lead.preferred_stand_size == "size_18"
        assert lead.completed_at is not None
        assert lead.is_draft is False
        assert lead.current_step is None
        assert lead.notify_chat_id == settings.sales_group_id
        assert lead.notify_message_id is not None

        # the user is thanked without ever being told about scoring
        thanks = session.last_text()
        assert "Rahmat" in thanks
        for text in session.messages_to(PRIVATE_CHAT):
            lowered = text.lower()
            assert "score" not in lowered and "/100" not in text and "hot" not in lowered.split()
            assert "qualified" not in lowered

    async def test_progress_counter_is_shown_during_the_funnel(
        self, harness: Harness, session: RecordingSession
    ) -> None:
        await harness.send("/start")
        await harness.press("lang:uz")
        await harness.press("flow:start")
        assert "Savol 1/10" in session.last_text()
        await harness.press("q:intent:pricing")
        assert "Savol 2/10" in session.last_text()

    async def test_pricing_intent_still_gets_the_stand_question(
        self, harness: Harness, session: RecordingSession, repo: LeadRepository
    ) -> None:
        await harness.send("/start tgads_foodera_ru_01")
        await harness.press("lang:ru")
        await harness.press("flow:start")
        await harness.press("q:intent:pricing")
        await harness.press("q:company_type:distributor")
        await harness.press("q:category:frozen_and_semi_finished")
        await harness.send("Distributor ACME")
        await harness.press("q:region:tashkent")
        await harness.press("q:online:none")
        await harness.send("Dilnoza — Menecer")
        await harness.send(contact_phone="+998901112233")
        assert "формат стенда" in session.last_text()

    async def test_visitor_journey_is_not_sent_to_the_sales_group(
        self, harness: Harness, session: RecordingSession, repo: LeadRepository, settings
    ) -> None:
        await harness.send("/start tgads_foodera_uz_01")
        await harness.press("lang:uz")
        await harness.press("flow:start")
        await harness.press("q:intent:visitor")
        assert "3 ta qisqa savol" in session.sent_to(PRIVATE_CHAT)[-1]

        await harness.send("Malika")
        await harness.send(contact_phone="+998905554433")
        await harness.press("q:region:tashkent")
        await harness.press("q:visitor_relation:student")

        assert session.sent_to(settings.sales_group_id) == []
        leads = await repo.list_leads()
        assert len(leads) == 1
        assert leads[0].classification == Classification.VISITOR.value
        assert leads[0].lead_type == "visitor"
        assert leads[0].preferred_stand_size is None
        assert "mehmon" in session.sent_to(PRIVATE_CHAT)[-1].lower()

    async def test_back_button_returns_to_the_previous_question(
        self, harness: Harness, session: RecordingSession
    ) -> None:
        await harness.send("/start")
        await harness.press("lang:uz")
        await harness.press("flow:start")
        await harness.press("q:intent:stand")
        await harness.press("q:company_type:manufacturer")
        await harness.press("nav:back")
        text = session.last_text()
        assert "Kompaniyangiz qaysi turga kiradi?" in text
        assert "Savol 2/" in text

    async def test_skip_is_offered_for_optional_steps(
        self, harness: Harness, session: RecordingSession
    ) -> None:
        await harness.send("/start")
        await harness.press("lang:uz")
        await harness.press("flow:start")
        await harness.press("q:intent:stand")
        await harness.press("q:company_type:manufacturer")
        await harness.press("q:category:grocery")
        await harness.send("ACME")
        await harness.press("q:region:samarkand")
        await harness.press("q:online:website")
        await harness.press("nav:skip")  # no link shared
        await harness.send("Aziz")
        await harness.press("nav:skip")  # no phone
        assert "Qaysi format" in session.last_text()

    async def test_invalid_text_is_rejected_and_asked_again(
        self, harness: Harness, session: RecordingSession
    ) -> None:
        await harness.send("/start")
        await harness.press("lang:uz")
        await harness.press("flow:start")
        await harness.press("q:intent:stand")
        await harness.press("q:company_type:manufacturer")
        await harness.press("q:category:grocery")
        await harness.send("A")  # too short
        assert "⚠️" in session.last_text()
        await harness.send("ACME FOOD")
        assert "q:region:tashkent" in session.last_keyboard_callbacks()

    async def test_typing_where_buttons_are_expected_is_handled(
        self, harness: Harness, session: RecordingSession
    ) -> None:
        await harness.send("/start")
        await harness.press("lang:uz")
        await harness.press("flow:start")
        await harness.send("salom")
        assert "tugmalardan" in session.last_text()

    async def test_a_photo_in_the_middle_of_the_funnel_changes_nothing(
        self, harness: Harness, session: RecordingSession, repo: LeadRepository
    ) -> None:
        """Photos and stickers are answered, not swallowed: the lead stays on the question."""
        await harness.send("/start")
        await harness.press("lang:uz")
        await harness.press("flow:start")
        await harness.press("q:intent:stand")
        await harness.send_media(caption="salom")

        assert "tugmalardan" in session.last_text()
        lead = (await repo.list_leads(only_completed=False))[0]
        assert lead.intent == "stand"
        assert lead.current_step == "company_type"

    async def test_stale_button_press_after_answer_is_ignored(
        self, harness: Harness, session: RecordingSession
    ) -> None:
        await harness.send("/start")
        await harness.press("lang:uz")
        await harness.press("flow:start")
        await harness.press("q:intent:stand")
        await harness.press("q:intent:pricing")  # the user goes back to an old card
        assert "Savol 2/" in session.last_text()

    async def test_anti_spam_offers_update_instead_of_a_second_lead(
        self, harness: Harness, session: RecordingSession, repo: LeadRepository
    ) -> None:
        await complete_questionnaire(harness)
        before = len(await repo.list_leads())

        # the welcome is shown again, but starting over is refused: the user is offered
        # to update the existing application instead of creating a duplicate lead
        await harness.send("/start tgads_foodera_uz_02")
        await harness.press("flow:start")
        gate = session.last_text()
        assert "avval qabul qilingan" in gate
        assert "Ma’lumotlarni yangilash" in session.last_keyboard_texts()
        assert "/100" not in gate  # the score stays internal, even here

        await harness.press("flow:update")
        await harness.press("q:intent:stand")
        assert len(await repo.list_leads(only_completed=False)) == before  # same lead, updated
        assert len(await repo.list_leads()) == before

    async def test_manager_can_book_a_lead_from_the_group(
        self, harness: Harness, session: RecordingSession, repo: LeadRepository, settings
    ) -> None:
        await complete_questionnaire(harness)
        lead = (await repo.list_leads())[0]

        manager = {"id": 555, "is_bot": False, "first_name": "Manager", "username": "sales_manager"}

        # a brand-new lead cannot jump straight to BOOKED: the funnel has to be walked
        await harness.press(f"lead:{lead.id}:booked", chat_id=settings.sales_group_id, user=manager)
        assert (await repo.get_lead(lead.id)).lead_status == LeadStatus.NEW.value
        assert "ruxsat yo‘q" in session.last_answer()[0]

        await harness.press(
            f"lead:{lead.id}:contacted", chat_id=settings.sales_group_id, user=manager
        )
        await harness.press(f"lead:{lead.id}:booked", chat_id=settings.sales_group_id, user=manager)

        fresh = await repo.get_lead(lead.id)
        assert fresh.lead_status == LeadStatus.BOOKED.value
        assert fresh.manager_user_id == 555
        assert fresh.manager_username == "sales_manager"
        assert fresh.status_changed_at is not None
        assert "✅ BOOKED" in session.last_text(settings.sales_group_id), (
            "the card must be edited in place"
        )

    async def test_outsider_cannot_change_a_lead_status(
        self, harness: Harness, session: RecordingSession, repo: LeadRepository, settings
    ) -> None:
        await complete_questionnaire(harness)
        lead = (await repo.list_leads())[0]
        stranger = {"id": 999, "is_bot": False, "first_name": "Stranger"}

        await harness.press(f"lead:{lead.id}:booked", chat_id=-100999888777, user=stranger)
        assert (await repo.get_lead(lead.id)).lead_status == LeadStatus.NEW.value

    async def test_duplicate_status_press_is_a_no_op(
        self, harness: Harness, session: RecordingSession, repo: LeadRepository, settings
    ) -> None:
        await complete_questionnaire(harness)
        lead = (await repo.list_leads())[0]
        manager = {"id": 555, "is_bot": False, "first_name": "Manager"}

        await harness.press(
            f"lead:{lead.id}:contacted", chat_id=settings.sales_group_id, user=manager
        )
        edited = len([1 for call in session.messages_to(settings.sales_group_id) if call])
        await harness.press(
            f"lead:{lead.id}:contacted", chat_id=settings.sales_group_id, user=manager
        )

        assert (await repo.get_lead(lead.id)).lead_status == LeadStatus.CONTACTED.value
        assert "allaqachon" in session.last_answer()[0]  # second tap: polite no-op
        assert (
            len(session.messages_to(settings.sales_group_id)) == edited
        )  # the card was not touched

    async def test_admin_stats_command(
        self, harness: Harness, session: RecordingSession, settings
    ) -> None:
        await complete_questionnaire(harness)
        admin = {"id": 111, "is_bot": False, "first_name": "Admin", "username": "admin"}
        await harness.send("/stats", chat_id=111, user=admin)
        report = session.sent_to(111)[-1]
        assert "FOODERA Leads" in report
        assert "Total: 1" in report
        assert "HOT: 1" in report
        assert "Leads: 1" in report
        assert "Completion rate: 100.0%" in report

    async def test_admin_commands_are_hidden_from_strangers(
        self, harness: Harness, session: RecordingSession
    ) -> None:
        await harness.send("/stats")
        assert not [text for text in session.sent_to(PRIVATE_CHAT) if "FOODERA Leads" in text]

    async def test_lead_card_contains_a_lead_code_and_the_funnel_is_logged(
        self, harness: Harness, session: RecordingSession, repo: LeadRepository
    ) -> None:
        await complete_questionnaire(harness)
        lead = (await repo.list_leads())[0]
        assert lead.lead_code == f"FD{lead.id:06d}"
        events = await repo.events_for_lead(lead.id)
        names = [event.event for event in events]
        for expected in (
            "APPLICATION_OPENED",
            "INTENT_SELECTED",
            "COMPANY_TYPE_SELECTED",
            "CATEGORY_SELECTED",
            "COMPANY_ENTERED",
            "PHONE_ENTERED",
            "READINESS_SELECTED",
            "COMPLETED",
            "NOTIFICATION_SENT",
        ):
            assert expected in names, f"{expected} missing from {names}"
