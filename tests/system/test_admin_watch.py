"""``rocky-admin veille``: a real watch of an account, written, then told with its status and source by source."""

from __future__ import annotations

import io
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from sqlalchemy import Engine

from rocky.offres.sources.model import (
    CollectedOffer,
    JobSource,
    SearchQuery,
    SourceCode,
    SourceFailedError,
)
from rocky.offres.sql import SqlStorage
from rocky.offres.watch.service import WatchService
from rocky.system.admin import watch_account
from tests.offres.fakes import NOW, new_seeker, posting
from tests.offres.sources.fakes import FakeDetailSource, FakeSource


def failed(query: SearchQuery) -> list[CollectedOffer]:
    raise SourceFailedError("Adzuna a répondu par une erreur (HTTP 401).")


def service(engine: Engine) -> WatchService:
    sources: list[JobSource] = [
        FakeSource(SourceCode.APEC, lambda query: [posting(f"a-{query.title}")]),
        FakeSource(SourceCode.ADZUNA, failed),
    ]

    @contextmanager
    def fake_sources() -> Iterator[Sequence[JobSource]]:
        yield sources

    return WatchService(engine, sources=fake_sources, limit=20, clock=lambda: NOW)


def run(engine: Engine, email: str, track_name: str | None = None) -> tuple[int, str]:
    out = io.StringIO()
    code = watch_account(
        engine, email=email, track_name=track_name, service=service(engine), out=out
    )
    return code, out.getvalue()


def test_the_watch_is_written_and_told_with_its_status(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        seeker = new_seeker(connection)

    code, output = run(migrated_engine, seeker.email)

    assert code == 0
    assert output.splitlines()[0] == (
        "Veille partielle : 2 offre(s) trouvée(s), 2 nouvelle(s), 0 complétée(s), "
        "0 sous le seuil, 0 incomplète(s), 0 non écrite(s)."
    )
    assert (
        "raison : Adzuna : En panne (Adzuna a répondu par une erreur (HTTP 401).)"
        in (output)
    )
    assert "Apec — Collectée · 2 offres" in output
    assert "Adzuna — En panne" in output
    assert output.endswith("Offres sans score ou sans piste : 0.\n")


def test_one_track_only(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        seeker = new_seeker(connection)

    code, output = run(migrated_engine, seeker.email, track_name="ia")

    assert code == 0
    assert "1 offre(s) trouvée(s)" in output


def test_an_unknown_track_or_account_runs_nothing(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        seeker = new_seeker(connection)

    code, output = run(migrated_engine, seeker.email, track_name="Inconnue")
    assert (code, output) == (
        1,
        f"Aucune piste nommée « Inconnue » pour {seeker.email}.\n",
    )
    assert run(migrated_engine, "personne@example.fr")[1] == (
        "Aucun compte pour personne@example.fr.\n"
    )
    with SqlStorage(migrated_engine).transaction() as store:
        assert store.last_run(seeker.account_id) is None


def test_a_running_watch_is_not_started_twice(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        seeker = new_seeker(connection)

    with SqlStorage(migrated_engine).lock(seeker.account_id):
        code, output = run(migrated_engine, seeker.email)

    assert code == 1
    assert (
        output
        == f"Une veille de {seeker.email} est déjà en cours : rien n'a été lancé.\n"
    )


def test_a_known_complete_offer_is_not_told_incomplete_when_seen_as_an_excerpt(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        seeker = new_seeker(connection)
    detail = FakeDetailSource(
        SourceCode.WTTJ,
        lambda query: [posting("w1", source="wttj", complete=False)],
        filters_location=False,
    )

    @contextmanager
    def wttj() -> Iterator[Sequence[JobSource]]:
        yield [detail]

    def watch() -> str:
        out = io.StringIO()
        watch_account(
            migrated_engine,
            email=seeker.email,
            track_name=None,
            service=WatchService(
                migrated_engine, sources=wttj, limit=20, clock=lambda: NOW
            ),
            out=out,
        )
        return out.getvalue()

    watch()
    second = watch()

    # The detail was read once; the second search gives an excerpt, the stored text is complete.
    assert detail.completed == ["w1"]
    assert "Welcome to the Jungle — Collectée · 1 offre\n" in second
    assert "0 incomplète(s)" in second
