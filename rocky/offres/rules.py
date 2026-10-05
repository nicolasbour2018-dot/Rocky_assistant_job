"""Rules of the stored offers: no I/O. Fingerprint of the scoring inputs, cross-site match key, best track."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import date

from rocky.offres.analysis.model import RULES_VERSION as ANALYSIS_RULES_VERSION
from rocky.offres.analysis.model import AccountSkill
from rocky.offres.analysis.rules import account_skills
from rocky.offres.model import ScoringInputs
from rocky.offres.scoring.model import RULES_VERSION as SCORE_RULES_VERSION
from rocky.offres.scoring.model import Score, ScoringProfile
from rocky.offres.scoring.rules import scoring_profile
from rocky.offres.sources.model import CollectedOffer
from rocky.profil.model import Profile
from rocky.profil.rules import normalize_term

# Words that name the legal form or the group, not the employer: "Jems Group" and "JEMS" are one employer (Q4).
COMPANY_NOISE = frozenset(
    {
        "group",
        "groupe",
        "sa",
        "sas",
        "sasu",
        "sarl",
        "se",
        "inc",
        "ltd",
        "llc",
        "gmbh",
        "holding",
        "france",
    }
)
# Gender markers of a French job title: "Data analyst (H/F)" is "Data analyst".
GENDER_MARKERS = frozenset(
    {"h", "f", "x", "m", "hf", "fh", "hfx", "fhx", "mf", "fm", "hfd", "fhd"}
)


def scoring_inputs(profile: Profile) -> ScoringInputs:
    """What the analysis and the score read of ``profile``, with its fingerprint."""
    skills = account_skills(skill.content for skill in profile.skills)
    scoring = scoring_profile(profile)
    return ScoringInputs(skills, scoring, inputs_hash(skills, scoring))


def inputs_hash(skills: tuple[AccountSkill, ...], scoring: ScoringProfile) -> str:
    """Fingerprint of everything a score depends on, besides the posting and the day: the account's skill terms, the
    part of the profile the score reads and both rule versions. A text correction of the profile leaves it unchanged.
    """
    content = json.dumps(
        {
            "analysis": ANALYSIS_RULES_VERSION,
            "score": SCORE_RULES_VERSION,
            "skills": [asdict(skill) for skill in skills],
            "profile": asdict(scoring),
        },
        default=_json_default,
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(content.encode()).hexdigest()


def _json_default(value: object) -> object:
    if isinstance(value, set | frozenset):
        return sorted(str(item) for item in value)
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"not a JSON value: {type(value).__name__}")


def description_hash(offer: CollectedOffer) -> str:
    """Fingerprint of the description: a stored summary of another one is stale (C7, Q6)."""
    return hashlib.sha256(offer.description.encode()).hexdigest()


def match_key(offer: CollectedOffer) -> str | None:
    """Title and employer in comparison form: two sites showing the same key probably show the same posting.

    ``None`` without an employer: a title alone is not enough to bring two offers together.
    """
    company = [
        word
        for word in normalize_term(offer.company or "").split()
        if word not in COMPANY_NOISE
    ]
    title = [
        word
        for word in normalize_term(offer.title).split()
        if word not in GENDER_MARKERS
    ]
    if not company or not title:
        return None
    return f"{' '.join(title)}|{' '.join(company)}"


def best_track(score: Score) -> int | None:
    """The track where the offer scores best (an import is linked to it, Q10); None without an active track."""
    return score.best.track_id
