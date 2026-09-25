"""Exit criterion of C4: the "Data Protection Analyst" (79.6 % in v1) no longer rises, and for the right reason.

The posting comes from the archive (``data/data_protection_analyst.json``). The profile is close to Nicolas's and set
to favour the posting: its only skill found is key and proven, Paris is a place of the track, freelance is wanted.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from rocky.offres.analysis.rules import account_skills, analyze
from rocky.offres.scoring.model import (
    ComponentCode,
    ConfidenceLevel,
    ProfileSkill,
    ScoringProfile,
    ScoringTrack,
)
from rocky.offres.scoring.rules import score
from rocky.offres.sources.model import CollectedOffer
from rocky.profil.model import Contract, LanguageLevel, Preferences, RemoteMode
from rocky.profil.rules import make_skill

TODAY = date(2026, 9, 25)
POSTING = Path(__file__).parent / "data" / "data_protection_analyst.json"
SKILLS = (
    ("Python", ""),
    ("SQL", ""),
    ("Machine Learning", ""),
    ("Gestion des données", "Data management"),
    ("Power BI", ""),
    ("Statistiques", "Statistics"),
    ("Tableau", ""),
)
PROFILE = ScoringProfile(
    skills=tuple(ProfileSkill(label, is_key=True, proven=True) for label, _ in SKILLS),
    tracks=(
        ScoringTrack(
            id=1,
            name="Data",
            titles=("Data Scientist", "Data Analyst"),
            locations=("Eure-et-Loir", "Paris"),
        ),
    ),
    preferences=Preferences(
        contracts=(Contract.PERMANENT, Contract.FREELANCE),
        remote_modes=(RemoteMode.HYBRID, RemoteMode.FULL_REMOTE),
        min_salary_eur=45_000,
        min_daily_rate_eur=400,
    ),
    languages=(("fr", LanguageLevel.NATIVE), ("en", LanguageLevel.C1)),
)


def posting() -> CollectedOffer:
    data: dict[str, Any] = {
        key: value
        for key, value in json.loads(POSTING.read_text()).items()
        if not key.startswith("_")
    }
    return CollectedOffer(description_complete=True, **data)


def test_the_data_protection_analyst_stays_under_the_threshold() -> None:
    offer = posting()
    skills = account_skills(
        make_skill(label_fr=label, label_en=label_en, category="technical")
        for label, label_en in SKILLS
    )
    analysis = analyze(offer, skills, today=TODAY)

    result = score(analysis, offer, PROFILE, today=TODAY)

    best = result.best
    assert [match.skill for match in analysis.skills] == ["Gestion des données"]
    assert best.display < 50
    assert result.threshold_reason == f"Score sous le seuil ({best.display} < 50)"
    # For the right reason: one skill is not enough evidence, whatever the other components say.
    skills_value = best.component(ComponentCode.SKILLS).value
    assert skills_value is not None
    assert skills_value < 0.5
    assert best.component(ComponentCode.TITLE).value == 0.5
    assert best.confidence.level == ConfidenceLevel.LOW
    assert best.confidence.reasons[0].startswith("Preuves insuffisantes")
