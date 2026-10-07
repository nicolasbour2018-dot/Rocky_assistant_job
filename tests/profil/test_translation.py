"""Translation of the profile field by field (decision D3, Q5, Q6, Q12–Q14, Q19, Q21)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest

from rocky.profil.model import Remembered
from rocky.profil.rules import (
    ProfileInputError,
    make_experience,
    make_identity,
    make_project,
    make_skill,
    text_sha256,
)
from rocky.profil.translation import (
    TranslationError,
    checks,
    glossary_pairs,
    is_stale_translation,
    propose,
    protected_names,
    segments_of,
    to_translate,
)
from rocky.profil.usecases import ProfileEditor
from rocky.system.llm import LlmUnavailableError
from tests.profil.fakes import InMemoryProfileStore
from tests.system.auth.fakes import FakeClock


class EchoModel:
    """Answers with the translations it is given; keeps what it was sent."""

    def __init__(self, translations: Mapping[str, str]) -> None:
        self.translations = translations
        self.prompts: list[str] = []

    def complete_json(
        self, instructions: str, prompt: str, schema: Mapping[str, Any]
    ) -> Any:
        self.prompts.append(prompt)
        asked = json.loads(prompt.split("Textes à traduire :\n", 1)[1])
        return {
            "translations": [
                {"id": item["id"], "en": self.translations[item["fr"]]}
                for item in asked
                if item["fr"] in self.translations
            ]
        }


class DownModel:
    def complete_json(
        self, instructions: str, prompt: str, schema: Mapping[str, Any]
    ) -> Any:
        raise LlmUnavailableError("Gemini est en panne (HTTP 503).")


def new_editor() -> ProfileEditor:
    return ProfileEditor(
        InMemoryProfileStore(), clock=FakeClock(), account_id=1, email="c@example.fr"
    )


def filled() -> tuple[ProfileEditor, int]:
    editor = new_editor()
    editor.save_identity(make_identity(full_name="Camille Martin", city="Chartres"))
    editor.add_skill(make_skill(label_fr="Pilotage", category="business"))
    editor.add_skill(
        make_skill(label_fr="Python", label_en="Python", category="technical")
    )
    editor.add_experience(
        make_experience(
            kind="job",
            title_fr="Responsable d'exploitation",
            organisation="Transports Exemple",
            start="2019-01",
            bullets_fr="Pilotage de 3 entrepôts à Chartres",
        )
    )
    project = editor.add_project(
        make_project(
            name_fr="Tri des messages",
            problem_fr="Des **milliers** de messages",
            stack="Python\nBase vectorielle",
        )
    )
    return editor, project


def test_every_text_a_cv_can_show_is_listed_with_its_english() -> None:
    editor, project = filled()

    segments = {s.key: s for s in segments_of(editor.profile())}

    assert segments[f"project:{project}:stack"].source == "Python\nBase vectorielle"
    assert segments[f"project:{project}:stack"].english is None
    assert any(s.english == "Python" for s in segments.values())
    # Employers and places are never texts to translate.
    assert all(s.source != "Transports Exemple" for s in segments.values())


def test_the_memory_is_used_without_calling_the_model() -> None:
    editor, project = filled()
    missing, _ = to_translate(editor.profile(), {})
    stack = next(s for s in missing if s.key == f"project:{project}:stack")
    model = EchoModel({})

    (proposal,) = propose(
        [stack],
        memory={
            stack.source_sha256: Remembered(stack.source, "Python\nVector database")
        },
        pairs=(),
        protected=(),
        model=model,
    )

    assert proposal.from_memory and proposal.english == "Python\nVector database"
    assert model.prompts == []


def test_protected_names_are_never_sent_as_texts_and_the_glossary_is_sent() -> None:
    editor, _ = filled()
    editor.save_glossary_term("pilotage", "Steering")
    profile = editor.profile()
    missing, _ = to_translate(profile, {})
    model = EchoModel({})

    propose(
        missing,
        memory={},
        pairs=glossary_pairs(profile, editor.glossary()),
        protected=protected_names(profile),
        model=model,
    )

    (sent,) = model.prompts
    assert "- pilotage → Steering" in sent
    assert "- Python → Python" in sent
    assert '"fr": "Camille Martin"' not in sent


def test_a_proposal_that_breaks_the_rules_says_why() -> None:
    warnings = checks(
        "Pilotage de 3 entrepôts à **Chartres**\nSuivi",
        "Management of 3 warehouses in Chartre",
        pairs=(("Pilotage", "Steering"),),
        protected=("Chartres",),
    )

    assert warnings == (
        "2 lignes en français, 1 en anglais.",
        "Le gras (**…**) n'est pas repris comme en français.",
        "Glossaire : « Pilotage » devait devenir « Steering ».",
        "« Chartres » devait rester tel quel.",
    )


def test_a_text_the_model_forgot_is_shown_empty_with_its_reason() -> None:
    editor, _ = filled()
    missing, _ = to_translate(editor.profile(), {})

    proposals = propose(missing, memory={}, pairs=(), protected=(), model=EchoModel({}))

    assert all(p.english == "" for p in proposals)
    assert proposals[0].warnings == ("Le modèle n'a rien proposé pour ce texte.",)


def test_a_model_down_or_answering_badly_is_a_visible_refusal() -> None:
    editor, _ = filled()
    missing, _ = to_translate(editor.profile(), {})

    with pytest.raises(TranslationError, match="HTTP 503"):
        propose(missing, memory={}, pairs=(), protected=(), model=DownModel())

    class Garbled:
        def complete_json(
            self, instructions: str, prompt: str, schema: Mapping[str, Any]
        ) -> Any:
            return {"translations": "none"}

    with pytest.raises(TranslationError, match="forme attendue"):
        propose(missing, memory={}, pairs=(), protected=(), model=Garbled())


def test_an_accepted_translation_is_written_remembered_and_journaled() -> None:
    editor, project = filled()
    key = f"project:{project}:stack"
    source = "Python\nBase vectorielle"

    editor.accept_translation(key, text_sha256(source), " Python \n\n Vector database ")

    content = next(p for p in editor.profile().projects if p.id == project).content
    assert content.stack_en == ("Python", "Vector database")
    assert editor.translation_memory()[text_sha256(source)].translation == (
        "Python\nVector database"
    )
    store = editor._store
    assert isinstance(store, InMemoryProfileStore)
    assert store.event_types()[-1] == "profil.translation_accepted"


def test_every_kind_of_text_takes_its_english() -> None:
    editor, _project = filled()
    profile = editor.profile()
    for segment in segments_of(profile):
        if segment.english is None:
            english = "\n".join(f"EN {line}" for line in segment.source.split("\n"))
            editor.accept_translation(segment.key, segment.source_sha256, english)

    missing, stale = to_translate(editor.profile(), editor.translation_memory())

    assert missing == ()
    assert stale == ()


def test_a_translation_is_refused_when_the_french_changed_since() -> None:
    editor, project = filled()

    with pytest.raises(ProfileInputError, match="a changé"):
        editor.accept_translation(f"project:{project}:stack", text_sha256("autre"), "x")


def test_an_english_translated_from_an_older_french_is_to_review() -> None:
    editor, project = filled()
    old = "Des **milliers** de messages"
    editor.accept_translation(
        f"project:{project}:problem", text_sha256(old), "**Thousands** of messages"
    )
    content = next(p for p in editor.profile().projects if p.id == project).content
    editor.update_project(
        project,
        make_project(
            name_fr=content.name.fr,
            problem_fr="Des **centaines** de messages",
            problem_en=content.problem.en,
            stack=content.stack,
        ),
    )

    _, stale = to_translate(editor.profile(), editor.translation_memory())

    assert [s.key for s in stale] == [f"project:{project}:problem"]
    hand_written = next(
        s for s in segments_of(editor.profile()) if s.key == f"project:{project}:name"
    )
    assert not is_stale_translation(hand_written, editor.translation_memory())


def test_a_glossary_term_needs_both_languages() -> None:
    with pytest.raises(ProfileInputError):
        new_editor().save_glossary_term("Pilotage", " ")
