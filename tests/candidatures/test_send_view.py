"""What the step « Envoi » shows of a sending: its day is the user's, in Paris (step H2)."""

from __future__ import annotations

from rocky.candidatures.model import Change, ChangeKind, LetterState, Stage
from rocky.candidatures.send_view import send_view
from rocky.offres.decisions import Author
from rocky.profil.model import Identity
from tests.offres.fakes import HALF_PAST_MIDNIGHT, TODAY


def test_a_sending_at_half_past_midnight_in_paris_is_of_the_paris_day() -> None:
    # A stage « Envoyée » confirmed before D5: no sending, its day is the change's.
    sent = Change(
        1, 1, ChangeKind.STAGE, Author.USER, HALF_PAST_MIDNIGHT, stage=Stage.SENT
    )

    view = send_view(
        language="fr",
        revisions=(),
        inputs={},
        letter=LetterState.NONE,
        letter_in_language=False,
        messages=(),
        changes=(sent,),
        sendings=(),
        prefills=(),
        stage=Stage.SENT,
        identity=Identity(),
        apply_url="",
    )

    assert view.sent is not None and not view.sent.linked
    assert view.sent.on == TODAY
