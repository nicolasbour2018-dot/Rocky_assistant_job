"""The generic cover letter: its rules, its import cut checked word for word, its English (decision D4, Q6, Q9, Q13)."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from rocky.profil.letter import (
    LetterImportError,
    checked_split,
    english_letter,
    filled,
    letter_segments,
    letter_sha256,
    letter_text,
    make_letter,
)
from rocky.profil.model import LetterOrigin, LetterParagraph, LetterRole
from rocky.profil.rules import ProfileInputError
from rocky.profil.usecases import ProfileEditor
from tests.profil.fakes import InMemoryProfileStore
from tests.system.auth.fakes import FakeClock
from tests.system.test_docx_read import docx, paragraph, run

LETTER = (
    "Madame, Monsieur,\n\n"
    "Data analyste en reconversion, je souhaite rejoindre Acme comme Data Analyst.\n\n"
    "Pendant huit ans, j'ai piloté des projets de bout en bout.\n\n"
    "Acme m'attire par ses produits de santé.\n\n"
    "Je serais heureux d'en parler avec vous.\n\n"
    "Je vous prie d'agréer mes salutations distinguées.\n\nCamille Martin"
)
ANSWER = {
    "paragraphs": [
        {"role": "salutation", "text": "Madame, Monsieur,"},
        {
            "role": "opening",
            "text": "Data analyste en reconversion, je souhaite rejoindre {entreprise} comme {poste}.",
        },
        {
            "role": "journey",
            "text": "Pendant huit ans, j'ai piloté des projets de bout en bout.",
        },
        {"role": "why_you", "text": "{entreprise} m'attire par ses produits de santé."},
        {"role": "closing", "text": "Je serais heureux d'en parler avec vous."},
        {
            "role": "politeness",
            "text": "Je vous prie d'agréer mes salutations distinguées.",
        },
        {"role": "signature", "text": "Camille Martin"},
    ],
    "job_title": "Data Analyst",
    "company": "Acme",
}


def test_the_model_cut_is_checked_word_for_word_with_its_variables() -> None:
    split = checked_split(LETTER, ANSWER)

    assert [p.role for p in split.kept] == ["opening", "journey", "why_you", "closing"]
    assert [p.role for p in split.set_aside] == [
        "salutation",
        "politeness",
        "signature",
    ]
    assert all(p.verbatim for p in split.paragraphs)
    assert (split.job_title, split.company) == ("Data Analyst", "Acme")


def test_a_paragraph_the_model_rewrote_is_flagged() -> None:
    answer = {
        **ANSWER,
        "paragraphs": [
            {"role": "journey", "text": "Pendant huit ans, j'ai dirigé des projets."}
        ],
    }

    (rewritten,) = checked_split(LETTER, answer).paragraphs

    assert not rewritten.verbatim


@pytest.mark.parametrize(
    "answer",
    [None, {"paragraphs": "x", "job_title": "", "company": ""}, {"paragraphs": []}],
)
def test_a_malformed_cut_is_refused(answer: object) -> None:
    with pytest.raises(LetterImportError, match="forme attendue"):
        checked_split(LETTER, answer)


def test_a_letter_gets_its_place_why_you_before_its_closing() -> None:
    letter = make_letter(
        "fr",
        [
            ("opening", "Je postule chez  {entreprise}\n comme {poste}."),
            ("strengths", ""),
            ("closing", "À bientôt."),
        ],
    )

    assert letter.paragraphs == (
        LetterParagraph(
            LetterRole.OPENING, "Je postule chez {entreprise} comme {poste}."
        ),
        LetterParagraph(LetterRole.WHY_YOU, ""),
        LetterParagraph(LetterRole.CLOSING, "À bientôt."),
    )
    assert filled(letter.paragraphs[0].text, "Data Analyst", "Acme") == (
        "Je postule chez Acme comme Data Analyst."
    )


@pytest.mark.parametrize(
    ("paragraphs", "reason"),
    [
        ([("why_you", "a"), ("why_you", "b")], "Un seul paragraphe"),
        ([("opening", "Chez {societe}.")], "Variable inconnue {societe}"),
        ([("why_you", "")], "La lettre est vide"),
        ([("unknown", "x")], "Rôle de paragraphe inconnu"),
    ],
)
def test_a_letter_that_cannot_be_kept_says_why(
    paragraphs: list[tuple[str, str]], reason: str
) -> None:
    with pytest.raises(ProfileInputError, match=reason):
        make_letter("fr", paragraphs)


def test_the_text_of_a_docx_letter_is_read() -> None:
    content = docx(paragraph(run("Madame, Monsieur,")) + paragraph(run("Je postule.")))

    assert letter_text(content) == "Madame, Monsieur,\n\nJe postule."


def test_a_pdf_without_text_is_refused_with_its_reason() -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (200, 280), "white").save(buffer, format="PDF")

    with pytest.raises(LetterImportError, match="aucun texte lisible"):
        letter_text(buffer.getvalue())


def test_another_file_is_refused() -> None:
    with pytest.raises(LetterImportError, match="DOCX ou PDF"):
        letter_text(b"GIF89a")


def test_the_english_letter_is_made_paragraph_by_paragraph() -> None:
    french = make_letter("fr", [("opening", "Je postule."), ("closing", "Merci.")])
    segments = letter_segments(french)

    # The empty place « pourquoi vous » is not a text to translate.
    assert [s.key for s in segments] == ["letter:0", "letter:2"]
    with pytest.raises(ProfileInputError, match="pas encore son anglais"):
        english_letter(french, {"letter:0": "I apply."})

    english = english_letter(french, {"letter:0": "I apply.", "letter:2": "Thank you."})
    assert [p.text for p in english.paragraphs] == ["I apply.", "", "Thank you."]
    assert english.language == "en"


def test_saving_the_letter_keeps_each_version_and_journals_it() -> None:
    store = InMemoryProfileStore()
    editor = ProfileEditor(store, clock=FakeClock(), account_id=1, email="c@example.fr")
    letter = make_letter("fr", [("opening", "Je postule.")])

    assert editor.save_generic_letter(letter, LetterOrigin.IMPORT)
    assert not editor.save_generic_letter(letter, LetterOrigin.EDIT)  # unchanged
    changed = make_letter("fr", [("opening", "Je postule chez {entreprise}.")])
    assert editor.save_generic_letter(changed, LetterOrigin.EDIT)

    stored = editor.generic_letter("fr")
    assert stored is not None
    assert (stored.letter, stored.origin) == (changed, LetterOrigin.EDIT)
    assert stored.sha256 == letter_sha256(changed)
    assert editor.generic_letter("en") is None
    assert store.event_types().count("profil.cover_letter_saved") == 2
