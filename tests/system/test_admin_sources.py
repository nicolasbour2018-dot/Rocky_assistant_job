"""``rocky-admin sources``: a real collection for the active tracks of an account, told source by source."""

from __future__ import annotations

import io
from uuid import uuid4

from sqlalchemy import Engine

from rocky.offres.sources.model import (
    Availability,
    CollectedOffer,
    QuerySkippedError,
    SearchQuery,
    SourceCode,
    SourceFailedError,
    SourceRefusedError,
)
from rocky.profil.model import TrackDraft, TrackStatus
from rocky.profil.sql import SqlProfileStore
from rocky.system.admin import check_sources
from rocky.system.auth.sql import SqlAuthStore
from tests.offres.sources.fakes import FakeDetailSource, FakeSource, offer
from tests.system.auth.fakes import FakeClock


def account_with_tracks(engine: Engine, *tracks: tuple[TrackDraft, TrackStatus]) -> str:
    email = f"{uuid4().hex}@example.fr"
    now = FakeClock()()
    with engine.begin() as connection:
        account_id = SqlAuthStore(connection).create_account(email, now)
        store = SqlProfileStore(connection)
        profile_id = store.create_profile(account_id, email, now)
        for draft, status in tracks:
            track_id = store.add_track(profile_id, draft, now)
            if status is not TrackStatus.ACTIVE:
                store.set_track_status(profile_id, track_id, status, now)
    return email


DATA = TrackDraft(
    "Data", titles=("Data analyst", "BI"), locations=("Paris", "Télétravail")
)
BI = TrackDraft("BI", titles=("BI analyst",), locations=("Lyon",))


def refused(query: SearchQuery) -> list[CollectedOffer]:
    raise SourceRefusedError("Refusé par LinkedIn : la plateforme bloque (HTTP 429).")


def failed(query: SearchQuery) -> list[CollectedOffer]:
    raise SourceFailedError("Adzuna a répondu par une erreur (HTTP 503).")


def apec(query: SearchQuery) -> list[CollectedOffer]:
    if query.location == "Télétravail":
        raise QuerySkippedError("Lieu non reconnu par Apec : « Télétravail ».")
    return [offer(SourceCode.APEC, f"a-{query.title}-{query.location}", complete=False)]


def run(
    engine: Engine, email: str, *, track_name: str | None = None, detail: bool = False
) -> tuple[int, str, list[FakeSource]]:
    sources: list[FakeSource] = [
        FakeDetailSource(SourceCode.APEC, apec),
        FakeSource(SourceCode.ADZUNA, failed),
        FakeSource(
            SourceCode.WTTJ,
            lambda query: [offer(SourceCode.WTTJ, "w1")],
            filters_location=False,
        ),
        FakeSource(SourceCode.LINKEDIN, refused),
        FakeSource(
            SourceCode.FRANCE_TRAVAIL,
            lambda query: [],
            available=Availability.PENDING_ACCESS,
        ),
    ]
    out = io.StringIO()
    code = check_sources(
        engine,
        email=email,
        track_name=track_name,
        detail=detail,
        sources=sources,
        limit=20,
        out=out,
    )
    return code, out.getvalue(), sources


def test_every_source_is_told_and_a_failure_does_not_stop_the_others(
    migrated_engine: Engine,
) -> None:
    email = account_with_tracks(
        migrated_engine,
        (DATA, TrackStatus.ACTIVE),
        (BI, TrackStatus.PAUSED),
    )

    code, text, sources = run(migrated_engine, email)

    assert code == 0
    assert text.splitlines() == [
        "Collecte réelle pour « Data » : 4 requête(s) intitulé × lieu.",
        "",
        "Apec — Collectée · 2 offres dont 2 incomplètes",
        "  requêtes sautées (2) : Lieu non reconnu par Apec : « Télétravail ».",
        "Adzuna — En panne",
        "  raison : Adzuna a répondu par une erreur (HTTP 503).",
        "Welcome to the Jungle — Collectée · 1 offre",
        "  lieu non filtré par cette source : une requête par intitulé",
        "LinkedIn — Refusée par la plateforme",
        "  raison : Refusé par LinkedIn : la plateforme bloque (HTTP 429).",
        "France Travail — En attente d'accès",
        "  activée quand l'accès à l'API sera accordé (D8)",
    ]
    # The paused track is not searched; the pending source is never called.
    assert sources[0].queries == [
        SearchQuery("Data analyst", "Paris"),
        SearchQuery("Data analyst", "Télétravail"),
        SearchQuery("BI", "Paris"),
        SearchQuery("BI", "Télétravail"),
    ]
    assert sources[4].queries == []


def test_details_are_asked_on_demand(migrated_engine: Engine) -> None:
    email = account_with_tracks(migrated_engine, (DATA, TrackStatus.ACTIVE))

    code, text, sources = run(migrated_engine, email, detail=True)

    assert code == 0
    assert "Apec — Collectée · 2 offres\n" in text
    assert isinstance(sources[0], FakeDetailSource)
    assert sources[0].completed == ["a-Data analyst-Paris", "a-BI-Paris"]


def test_one_track_by_its_name(migrated_engine: Engine) -> None:
    email = account_with_tracks(
        migrated_engine, (DATA, TrackStatus.ACTIVE), (BI, TrackStatus.ACTIVE)
    )

    code, text, sources = run(migrated_engine, email, track_name="bi")

    assert code == 0
    assert text.startswith("Collecte réelle pour « BI » : 1 requête(s)")
    assert sources[0].queries == [SearchQuery("BI analyst", "Lyon")]


def test_without_active_track_nothing_is_asked(migrated_engine: Engine) -> None:
    email = account_with_tracks(migrated_engine, (DATA, TrackStatus.PAUSED))

    code, text, sources = run(migrated_engine, email)

    assert code == 1
    assert text == f"Aucune piste active pour {email}.\n"
    assert all(source.queries == [] for source in sources)


def test_an_unknown_account_is_reported(migrated_engine: Engine) -> None:
    code, text, _ = run(migrated_engine, "personne@example.fr")

    assert (code, text) == (1, "Aucun compte pour personne@example.fr.\n")
