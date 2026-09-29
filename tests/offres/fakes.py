"""A job seeker with a real profile (SQL), and postings, for the tests of the stored offers and of the watch."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy import Connection

from rocky.offres.sources.model import CollectedOffer
from rocky.profil.model import Profile
from rocky.profil.rules import make_preferences, make_skill, make_track
from rocky.profil.sql import SqlProfileStore
from rocky.profil.usecases import ProfileEditor
from rocky.system.auth.sql import SqlAuthStore

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
TODAY = date(2026, 9, 29)
DESCRIPTION = (
    "Nous recherchons un Data analyst en CDI à Paris.\n"
    "Compétences requises : Python et SQL.\n"
    "Un plus : Tableau."
)


@dataclass(frozen=True)
class Seeker:
    account_id: int
    email: str
    # Track ids by track name.
    tracks: dict[str, int] = field(default_factory=dict)

    def editor(self, connection: Connection) -> ProfileEditor:
        return ProfileEditor(
            SqlProfileStore(connection),
            clock=lambda: NOW,
            account_id=self.account_id,
            email=self.email,
        )

    def profile(self, connection: Connection) -> Profile:
        return self.editor(connection).profile()


def new_seeker(connection: Connection, *, activated: bool = True) -> Seeker:
    """An account with skills and two active tracks: « Data » (Data analyst, Paris) and « IA » (Data scientist)."""
    email = f"{uuid4().hex}@example.fr"
    auth = SqlAuthStore(connection)
    account_id = auth.create_account(email, NOW)
    if activated:
        auth.activate_account(account_id, "hash", NOW)
    seeker = Seeker(account_id, email)
    editor = seeker.editor(connection)
    editor.save_preferences(make_preferences(contracts=["permanent"]))
    for label, is_key in (("Python", True), ("SQL", False), ("Tableau", False)):
        editor.add_skill(
            make_skill(label_fr=label, category="technical", is_key=is_key)
        )
    seeker.tracks["Data"] = editor.add_track(
        make_track(name="Data", titles=["Data analyst"], locations=["Paris"])
    )
    seeker.tracks["IA"] = editor.add_track(
        make_track(name="IA", titles=["Data scientist"], locations=["Paris"])
    )
    return seeker


def posting(
    external_id: str,
    *,
    source: str = "apec",
    title: str = "Data analyst (H/F)",
    company: str | None = "Exemple",
    description: str = DESCRIPTION,
    complete: bool = True,
    url: str | None = None,
    **facts: object,
) -> CollectedOffer:
    return CollectedOffer(
        source=source,
        external_id=external_id,
        url=url or f"https://{source}.example/offres/{external_id}",
        title=title,
        description=description if complete else description[:40],
        description_complete=complete,
        incomplete_reason=None if complete else "Extrait seulement.",
        company=company,
        location="Paris",
        country="France",
        **facts,  # type: ignore[arg-type]
    )
