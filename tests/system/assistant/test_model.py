"""The assistant's rules (decision G4): the facts within their budget, the prompt, the check of the answer."""

from __future__ import annotations

import pytest

from rocky.system.assistant.model import (
    CUT_MARK,
    NO_FACTS_ANSWER,
    AnswerOutcome,
    Exchange,
    Fact,
    Subject,
    SubjectKind,
    checked,
    fit,
    parse_subject,
    prompt,
    unique,
)

SCORE = Fact("offre.score", "Score", "62 sur 100", "/offres/12/fiche")
TITLE = Fact("offre.titre", "Intitulé", "Data analyst chez Valeo")
DESCRIPTION = Fact("offre.description", "Description", "x" * 500, cut_first=True)


def test_a_screen_names_its_object_and_anything_else_is_the_general_conversation() -> (
    None
):
    assert parse_subject("offre:12") == Subject(SubjectKind.OFFER, 12)
    assert parse_subject(" candidature:3 ") == Subject(SubjectKind.APPLICATION, 3)
    assert Subject(SubjectKind.MESSAGE, 7).token == "message:7"
    for raw in (
        None,
        "",
        "offre",
        "offre:",
        "offre:-1",
        "offre:1a",
        "compte:2",
        "offre:١",
    ):
        assert parse_subject(raw) is None


def test_a_fact_id_is_dotted_lowercase_and_unique() -> None:
    with pytest.raises(ValueError, match="invalid fact id"):
        Fact("Offre score", "Score", "62")
    with pytest.raises(ValueError, match="duplicate fact id"):
        unique([SCORE, SCORE])


def test_the_long_texts_are_cut_first_then_the_last_facts_left_out() -> None:
    full = (TITLE, DESCRIPTION, SCORE)
    size = sum(len(fact.line) + 1 for fact in full)

    assert fit(full, size) == full
    cut = fit(full, size - 100)
    assert [fact.id for fact in cut] == [
        "offre.titre",
        "offre.description",
        "offre.score",
    ]
    assert cut[1].text.endswith(CUT_MARK)
    assert sum(len(fact.line) + 1 for fact in cut) <= size - 100
    assert [fact.id for fact in fit(full, len(TITLE.line) + 1 + 20)] == ["offre.titre"]


def test_the_prompt_gives_the_facts_the_last_exchanges_then_the_question() -> None:
    history = [Exchange(f"q{index}", f"r{index}") for index in range(8)]

    text = prompt([SCORE], history, "Pourquoi ce score ?")

    assert text.startswith("Faits :\n[offre.score] Score : 62 sur 100\n")
    assert "q1" not in text and "Question : q2\nRéponse : r2" in text
    assert text.endswith("\nQuestion : Pourquoi ce score ?")


def test_an_answer_citing_known_facts_is_shown_with_them() -> None:
    answer = checked(
        {
            "reponse": " Ton score est de 62. ",
            "faits": ["offre.score", "offre.score"],
            "sans_reponse": False,
        },
        [SCORE, TITLE],
    )

    assert answer.outcome is AnswerOutcome.ANSWERED
    assert answer.text == "Ton score est de 62."
    assert answer.cited == (SCORE,)


def test_an_answer_saying_the_facts_do_not_answer_is_shown_as_is() -> None:
    answer = checked(
        {"reponse": "Tes données ne le disent pas.", "faits": [], "sans_reponse": True},
        [SCORE],
    )

    assert (answer.outcome, answer.text, answer.cited) == (
        AnswerOutcome.NO_ANSWER,
        "Tes données ne le disent pas.",
        (),
    )


@pytest.mark.parametrize(
    "raw",
    [
        {"reponse": "Ton score est bon.", "faits": [], "sans_reponse": False},
        {
            "reponse": "Ton score est de 70.",
            "faits": ["offre.salaire"],
            "sans_reponse": False,
        },
        {"reponse": "", "faits": ["offre.score"], "sans_reponse": False},
        {"reponse": "62.", "faits": "offre.score", "sans_reponse": False},
        {"reponse": "62.", "faits": ["offre.score"]},
        ["62"],
        None,
    ],
)
def test_an_answer_without_known_facts_is_replaced(raw: object) -> None:
    answer = checked(raw, [SCORE])

    assert (answer.outcome, answer.text, answer.cited) == (
        AnswerOutcome.REJECTED,
        NO_FACTS_ANSWER,
        (),
    )


def test_an_id_cited_as_shown_in_the_prompt_with_its_brackets_is_known() -> None:
    """Recette of G4: GPT-5.4 mini, and Gemini once, cited « [offre.score] » as the prompt shows it."""
    answer = checked(
        {
            "reponse": "Ton score est de 62.",
            "faits": ["[offre.score]", " offre.titre "],
            "sans_reponse": False,
        },
        [SCORE, TITLE],
    )

    assert answer.outcome is AnswerOutcome.ANSWERED
    assert answer.cited == (SCORE, TITLE)


def test_a_bracketed_id_that_is_not_a_fact_is_still_unknown() -> None:
    answer = checked(
        {
            "reponse": "Ton score est de 90.",
            "faits": ["[offre.salaire]"],
            "sans_reponse": False,
        },
        [SCORE],
    )

    assert answer.outcome is AnswerOutcome.REJECTED
