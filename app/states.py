"""State machine for the qualification questionnaire."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup

__all__ = ["FormState"]


class FormState(StatesGroup):
    """Two states are enough: the flow itself is driven by ``FSM data["step"]``.

    ``FSMStrategy.USER_IN_CHAT`` (the aiogram default) keeps the group-chat
    interactions of a manager separate from his private conversation with the bot.
    """

    choosing_language = State()
    choosing_action = State()  # update / resume / restart prompt (anti-spam)
    filling = State()  # answering questions
