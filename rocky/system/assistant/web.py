"""The drawer 🐾 is the assistant (decision G4, Q6): the conversation about what the screen shows, read when the
drawer opens, a question at a time.

The screen names its object by a hidden field ``objet`` attached to the drawer's form (``assistant/subject.html``);
without one, or for an object the account does not have, the conversation is the general one (Q20, Q31).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import Engine

from rocky.system.assistant.model import (
    GENERAL_SUGGESTIONS,
    QUESTION_MAX,
    Fact,
    FactSheet,
    Subject,
    parse_subject,
)
from rocky.system.assistant.registry import sheet_of, summary_of
from rocky.system.assistant.sql import TurnRecord
from rocky.system.assistant.usecases import (
    ASSISTANT,
    LIMIT_REASON,
    UNAVAILABLE,
    Reply,
    ask,
    conversation,
    questions_left,
    start_over,
)
from rocky.system.auth.model import Account
from rocky.system.auth.web import CurrentAccount
from rocky.system.clock import today_of
from rocky.system.llm.calls import Models
from rocky.system.shell import page, wants_fragment

router = APIRouter(prefix="/tiroir")


def install(app: FastAPI) -> None:
    app.include_router(router)


@dataclass(frozen=True)
class Talk:
    """What the drawer shows: the object talked about (None: the general conversation), its turns, the suggestions."""

    subject: Subject | None
    sheet: FactSheet | None

    @property
    def title(self) -> str:
        return "Conversation générale" if self.sheet is None else self.sheet.title

    @property
    def suggestions(self) -> tuple[str, ...]:
        return GENERAL_SUGGESTIONS if self.sheet is None else self.sheet.suggestions


def _talk(request: Request, account: Account, objet: str) -> Talk:
    subject = parse_subject(objet)
    sheet = None if subject is None else sheet_of(request, account, subject)
    # Another account's object, or one gone: the general conversation.
    return Talk(subject if sheet is not None else None, sheet)


def _engine(request: Request) -> Engine:
    engine: Engine = request.app.state.engine
    return engine


def _models(request: Request) -> Models:
    models: Models = request.app.state.models
    return models


def _render(
    request: Request,
    account: Account,
    talk: Talk,
    *,
    reply: Reply | None = None,
) -> HTMLResponse:
    engine, models = _engine(request), _models(request)
    turns: Sequence[TurnRecord] = conversation(engine, account.id, talk.subject)
    left = (
        reply.left
        if reply is not None
        else questions_left(engine, models, account.id, today_of(request))
    )
    unavailable = models.unavailable_reason(ASSISTANT)
    context = {
        "talk": talk,
        "turns": turns,
        "left": left,
        "notice": reply.reason if reply is not None else None,
        "unavailable": None
        if unavailable is None
        else UNAVAILABLE.format(reason=unavailable),
        "limit_reached": left <= 0,
        "limit_reason": LIMIT_REASON,
        "answered": reply is not None and reply.answer is not None,
        "question_max": QUESTION_MAX,
    }
    if wants_fragment(request):
        templates: Jinja2Templates = request.app.state.templates
        return templates.TemplateResponse(request, "assistant/talk.html", context)
    return page(request, "assistant/page.html", active="today", context=context)


@router.get("", response_class=HTMLResponse)
def drawer(request: Request, account: CurrentAccount, objet: str = "") -> HTMLResponse:
    """The conversation about ``objet`` (« offre:12 »), read when the drawer opens (decision F1, Q12)."""
    return _render(request, account, _talk(request, account, objet))


@router.post("/question", response_class=HTMLResponse)
def question(
    request: Request,
    account: CurrentAccount,
    question: Annotated[str, Form()] = "",
    objet: Annotated[str, Form()] = "",
) -> HTMLResponse:
    talk = _talk(request, account, objet)

    def facts() -> list[Fact]:
        sheet = () if talk.sheet is None else talk.sheet.facts
        return [*sheet, *summary_of(request, account)]

    clock = request.app.state.auth.clock
    reply = ask(
        _engine(request),
        _models(request),
        account_id=account.id,
        subject=talk.subject,
        facts=facts,
        question=question,
        now=clock(),
        today=today_of(request),
    )
    return _render(request, account, talk, reply=reply)


@router.post("/nouvelle", response_class=HTMLResponse)
def new_conversation(
    request: Request, account: CurrentAccount, objet: Annotated[str, Form()] = ""
) -> HTMLResponse:
    """« Nouvelle conversation » (Q20)."""
    talk = _talk(request, account, objet)
    start_over(
        _engine(request), account.id, talk.subject, request.app.state.auth.clock()
    )
    return _render(request, account, talk)
