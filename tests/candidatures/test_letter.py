"""The letter of an application: title, header, sheet, checks, adaptation and what is in force (decision D4)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from rocky.candidatures.letter import (
    LetterError,
    checked_adaptation,
    clean_job_title,
    default_header,
    in_force,
    letter_sheet,
    letter_state,
    make_header,
    signals,
    version_at,
)
from rocky.candidatures.model import (
    LetterHeader,
    LetterOrigin,
    LetterParagraph,
    LetterState,
    LetterVersion,
    NoLetter,
)
from rocky.profil.rules import make_identity


@pytest.mark.parametrize(
    ("title", "location", "cleaned"),
    [
        ("Data analyst (H/F)", None, "Data analyst"),
        ("Data Scientist H/F - CDI - Paris 8e", "Paris", "Data Scientist"),
        ("Chef de projet Data F/H", None, "Chef de projet Data"),
        ("Data Engineer (H/F/X) – Remote", None, "Data Engineer"),
        ("Data Analyst - Courbevoie (92)", "Courbevoie", "Data Analyst"),
        ("Ingénieur IA, Stage", None, "Ingénieur IA"),
        ("Data Analyst | Lyon", "Lyon 3e", "Data Analyst"),
        ("Ingénieur CI/CD - Data", None, "Ingénieur CI/CD - Data"),
        ("H/F", None, "H/F"),  # never empty
    ],
)
def test_the_job_title_loses_gender_contract_and_place(
    title: str, location: str | None, cleaned: str
) -> None:
    assert clean_job_title(title, location) == cleaned


def test_the_header_is_proposed_then_kept_as_entered() -> None:
    proposed = default_header("fr", "Data Analyst", "Acme")

    assert proposed == LetterHeader(
        "Candidature au poste de Data Analyst", "Service recrutement\nAcme"
    )
    assert default_header("en", "Data Analyst", None) == LetterHeader(
        "Application for the position of Data Analyst", "Hiring team"
    )
    assert make_header("", " Mme Durand \n\n Acme ", proposed) == LetterHeader(
        proposed.subject, "Mme Durand\nAcme"
    )


def version(
    language: str = "fr", version_id: int = 1, at: datetime | None = None
) -> LetterVersion:
    return LetterVersion(
        id=version_id,
        language=language,
        paragraphs=(
            LetterParagraph("opening", "Je postule.", LetterOrigin.GENERIC),
            LetterParagraph("why_you", "", LetterOrigin.GENERIC),
            LetterParagraph("closing", "Merci.", LetterOrigin.EDITED),
        ),
        header=LetterHeader("Candidature au poste de Data Analyst", "Acme"),
        generic_sha256="abc",
        created_at=at or datetime(2026, 10, 1, tzinfo=UTC),
    )


def test_the_sheet_writes_header_and_formulas() -> None:
    identity = make_identity(
        full_name="Camille Martin",
        contact_email="c@example.fr",
        phone="06 00 00 00 00",
        city="Chartres",
        postal_code="28000",
    )

    sheet = letter_sheet(identity, version(), date(2026, 10, 1))

    assert sheet.sender == (
        "Camille Martin",
        "28000 Chartres",
        "06 00 00 00 00",
        "c@example.fr",
    )
    assert sheet.place_date == "Chartres, le 1er octobre 2026"
    assert sheet.paragraphs == ("Je postule.", "Merci.")  # the empty place is left out
    assert sheet.body.startswith("Madame, Monsieur,\n\nJe postule.")
    assert sheet.body.endswith("salutations distinguées.\n\nCamille Martin")
    english = letter_sheet(identity, version("en"), date(2026, 10, 4))
    assert english.place_date == "Chartres, 4 October 2026"
    assert english.salutation == "Dear Hiring Team,"


REFERENCE = "Pendant huit ans, j'ai piloté des projets chez Renault."
SOURCES = "Acme cherche un Data Analyst SQL. Équipe de 12 personnes."


def flagged(text: str, **kwargs: object) -> tuple[str, ...]:
    return signals(
        text,
        language="fr",
        reference=REFERENCE,
        sources=SOURCES,
        **kwargs,  # type: ignore[arg-type]
    )


def test_a_plain_text_drawn_from_the_offer_is_not_flagged() -> None:
    assert (
        flagged("Chez Acme, une équipe de 12 personnes : j'ai piloté des projets.")
        == ()
    )


@pytest.mark.parametrize(
    ("text", "signal"),
    [
        ("Acme — une belle équipe.", "Tiret long"),
        ("Je suis **motivé**.", "Mise en forme Markdown"),
        ("Je suis prêt 🚀.", "Emoji."),
        ("Je suis passionné par la donnée.", "Formule convenue : « passionné »"),
        ("Malgré mon parcours, je postule.", "Ton : « malgré »"),
        (
            "Une équipe de 40 personnes.",
            "Chiffre absent de l'annonce et de ton profil : 40",
        ),
        (
            "J'ai travaillé chez Google.",
            "Nom absent de l'annonce et de ton profil : Google",
        ),
        ("Chez {entreprise}.", "Variable non remplacée"),
        ("C’est l’équipe.", "Apostrophes typographiques"),
    ],
)
def test_what_a_generated_text_gives_away_is_flagged(text: str, signal: str) -> None:
    assert any(found.startswith(signal) for found in flagged(text)), flagged(text)


def test_what_the_user_wrote_themselves_is_never_flagged() -> None:
    reference = "Je suis passionné — depuis toujours — par Renault."

    assert (
        signals(
            "Passionné par la donnée — et par Renault.",
            language="fr",
            reference=reference,
            sources="",
        )
        == ()
    )


def test_lengths_are_compared() -> None:
    assert flagged("Court.", original="Un paragraphe bien plus long que celui-ci.")
    assert flagged("Court.", length=(150, 900)) == (
        "6 caractères (150 à 900 attendus).",
    )


def test_the_adaptation_keeps_known_paragraphs_only() -> None:
    adaptation = checked_adaptation(
        {
            "why_you": "  Acme  m'attire. ",
            "paragraphs": [
                {"id": "p0", "text": "Je postule chez Acme."},
                {"id": "p9", "text": "Inconnu."},
                {"id": "p2", "text": "  "},
            ],
        },
        3,
    )

    assert adaptation.why_you == "Acme m'attire."
    assert adaptation.paragraphs == {0: "Je postule chez Acme."}
    with pytest.raises(LetterError, match="forme attendue"):
        checked_adaptation({"why_you": 1, "paragraphs": []}, 3)


def test_the_letter_in_force_and_the_one_sent() -> None:
    first = version(version_id=1, at=datetime(2026, 10, 1, tzinfo=UTC))
    english = version("en", 2, datetime(2026, 10, 2, tzinfo=UTC))
    second = version(version_id=3, at=datetime(2026, 10, 5, tzinfo=UTC))
    entries = [first, english, second]

    assert letter_state([]) is LetterState.NONE
    assert letter_state(entries) is LetterState.VALIDATED
    assert (
        letter_state([*entries, NoLetter(4, second.created_at)]) is LetterState.SKIPPED
    )
    assert in_force(entries, "fr") == second
    assert in_force(entries, "en") == english
    assert version_at(entries, "fr", datetime(2026, 10, 3, tzinfo=UTC)) == first


def test_a_proposal_that_copies_the_paragraph_says_so() -> None:
    from rocky.candidatures.letter import Adaptation
    from rocky.candidatures.letter_view import letter_view
    from rocky.offres.model import OfferHeading
    from rocky.profil.letter import letter_sha256, make_letter
    from rocky.profil.model import LetterOrigin as GenericOrigin
    from rocky.profil.model import StoredLetter

    generic = make_letter("fr", [("opening", "Je postule chez {entreprise}.")])
    stored = StoredLetter(
        1,
        generic,
        GenericOrigin.IMPORT,
        letter_sha256(generic),
        None,
        datetime.now(UTC),
    )
    view = letter_view(
        language="fr",
        offer=OfferHeading(1, "Data analyst", "Acme", "Paris"),
        generic=stored,
        english_outdated=False,
        entries=(),
        messages=(),
        sent_at=None,
        editing=False,
        adaptation=Adaptation("", {0: "Je postule chez Acme."}),
    )

    assert view.rows[0].adapted_signals[0] == "Identique à ton paragraphe."
    assert (
        view.rows[1].adapted is None
    )  # no « pourquoi vous » proposed: no empty choice
