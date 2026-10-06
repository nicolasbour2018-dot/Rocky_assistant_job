"""What the modules give the assistant (decision G4, Q2, Q4, Q11), registered when they install, like the cockpit's
parts: ``system`` imports no business module.

A sheet reader gives the facts of one object of the account (None when the account has no such object); several
readers may give facts about the same kind of object, the first one naming it. A summary reader gives facts about the
whole account. Readers only read: they never write nor lock (test ``test_read_only``).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from fastapi import FastAPI, Request

from rocky.system.assistant.model import Fact, FactSheet, Subject, SubjectKind
from rocky.system.auth.model import Account

type SheetReader = Callable[[Request, Account, int], FactSheet | None]
type SummaryReader = Callable[[Request, Account], Sequence[Fact]]
# The order of the account summary in the prompt.
SUMMARY_KEYS = ("profil", "cockpit", "candidatures")


def add_facts(app: FastAPI, kind: SubjectKind, reader: SheetReader) -> None:
    readers: dict[SubjectKind, tuple[SheetReader, ...]] = getattr(
        app.state, "assistant_sheets", {}
    )
    app.state.assistant_sheets = {**readers, kind: (*readers.get(kind, ()), reader)}


def add_summary(app: FastAPI, key: str, reader: SummaryReader) -> None:
    if key not in SUMMARY_KEYS:
        raise KeyError(key)
    readers: dict[str, SummaryReader] = getattr(app.state, "assistant_summary", {})
    app.state.assistant_summary = {**readers, key: reader}


def sheet_of(request: Request, account: Account, subject: Subject) -> FactSheet | None:
    """The facts of ``subject``; None when the account has no such object (it may belong to another account)."""
    readers: dict[SubjectKind, tuple[SheetReader, ...]] = getattr(
        request.app.state, "assistant_sheets", {}
    )
    found = [
        reader(request, account, subject.id) for reader in readers.get(subject.kind, ())
    ]
    sheets = [sheet for sheet in found if sheet is not None]
    if not sheets:
        return None
    first = sheets[0]
    return FactSheet(
        first.title,
        tuple(fact for sheet in sheets for fact in sheet.facts),
        first.link,
        first.suggestions,
    )


def summary_of(request: Request, account: Account) -> list[Fact]:
    readers: dict[str, SummaryReader] = getattr(
        request.app.state, "assistant_summary", {}
    )
    return [
        fact
        for key in SUMMARY_KEYS
        if key in readers
        for fact in readers[key](request, account)
    ]
