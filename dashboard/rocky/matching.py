"""Calcul transparent du score de correspondance annonce/profil."""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from dashboard.job_analysis import analyze_job

from .models import CandidateProfile, JobOffer, MatchResult
from .text_utils import normalize_text


WEIGHTS = {
    "skills": 55.0,
    "title": 20.0,
    "contract": 8.0,
    "location": 8.0,
    "remote": 5.0,
    "salary": 4.0,
}


def _tokens(value: str) -> set[str]:
    ignored = {"de", "du", "des", "le", "la", "les", "et", "en", "h", "f"}
    return {
        token
        for token in normalize_text(value).replace("/", " ").split()
        if len(token) > 1 and token not in ignored
    }


def _text_similarity(left: str, right: str) -> float:
    left_normalized = normalize_text(left)
    right_normalized = normalize_text(right)
    if not left_normalized or not right_normalized:
        return 0.0
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    union = left_tokens | right_tokens
    jaccard = len(left_tokens & right_tokens) / len(union) if union else 0.0
    sequence = SequenceMatcher(
        None, left_normalized, right_normalized
    ).ratio()
    return min(1.0, 0.65 * jaccard + 0.35 * sequence)


def _best_similarity(value: str, preferences: list[str]) -> float:
    return max((_text_similarity(value, item) for item in preferences), default=0.0)


def _preference_match(value: str, preferences: list[str]) -> float:
    normalized_value = normalize_text(value)
    if not normalized_value:
        return 0.0
    for preference in preferences:
        normalized_preference = normalize_text(preference)
        if (
            normalized_preference in normalized_value
            or normalized_value in normalized_preference
        ):
            return 1.0
    return _best_similarity(value, preferences)


def _add_breakdown(
    breakdown: dict[str, dict[str, Any]],
    name: str,
    raw_score: float,
    detail: str,
) -> None:
    """ Inclue les poids dans le calcul final et permet d'expliquer le score. """
    breakdown[name] = {
        "label": {
            "skills": "Compétences",
            "title": "Intitulé",
            "contract": "Contrat",
            "location": "Localisation",
            "remote": "Télétravail",
            "salary": "Salaire",
        }[name],
        "raw_score": round(raw_score * 100, 1),
        "weight": WEIGHTS[name],
        "detail": detail,
    }


def calculate_match(
    offer: JobOffer,
    profile: CandidateProfile,
    candidate_skills: list[dict[str, Any]],
) -> MatchResult:
    """Calcule le score, puis renormalise les seuls critères disponibles.

    Un salaire absent dans l'annonce n'ajoute ni bonus ni pénalité. Le détail
    de chaque composante reste accessible pour expliquer le résultat. Le
    résumé court n'est volontairement jamais analysé : la veille doit avoir
    récupéré la description complète avant d'appeler cette fonction.
    """
    analysis = analyze_job(
        offer.job_title,
        offer.responsibilities,
    )
    # Un recalcul doit réellement relire l'annonce. On fusionne donc les
    # compétences déjà enregistrées avec celles détectées dans le texte actuel,
    # au lieu de conserver silencieusement une ancienne liste incomplète.
    detected_by_key: dict[str, str] = {}
    for skill_name in [*offer.detected_skills, *analysis["all_skills"]]:
        key = normalize_text(skill_name)
        if key:
            detected_by_key.setdefault(key, skill_name)
    detected = sorted(detected_by_key.values(), key=normalize_text)
    offer.detected_skills = detected

    candidate_by_name = {
        normalize_text(skill.get("skill_name")): skill for skill in candidate_skills
    }
    profile_skill_names = [
        str(skill.get("skill_name") or "").strip()
        for skill in candidate_skills
        if str(skill.get("skill_name") or "").strip()
    ]
    matched_skills = []
    missing_skills = []
    for skill_name in detected:
        skill = candidate_by_name.get(normalize_text(skill_name))
        if skill:
            matched_skills.append(skill_name)
        else:
            missing_skills.append(skill_name)

    breakdown: dict[str, dict[str, Any]] = {}
    if detected:
        # Le score compétences mesure la couverture de l'annonce : une
        # compétence du profil absente de l'offre ne constitue pas une pénalité.
        skill_score = len(matched_skills) / len(detected)
        _add_breakdown(
            breakdown,
            "skills",
            skill_score,
            f"{len(matched_skills)} compétence(s) trouvée(s) sur {len(detected)}",
        )
        breakdown["skills"].update(
            {
                "profile_skills": profile_skill_names,
                "detected_skills": detected,
                "matched_skills": matched_skills,
                "missing_skills": missing_skills,
            }
        )

    if profile.target_job_titles and offer.job_title:
        title_score = _best_similarity(
            offer.job_title, profile.target_job_titles
        )
        _add_breakdown(
            breakdown,
            "title",
            title_score,
            "Comparaison avec les intitulés ciblés",
        )

    optional_criteria = [
        (
            "contract",
            offer.contract_type,
            profile.preferred_contracts,
            "Comparaison avec les contrats recherchés",
        ),
        (
            "location",
            " ".join(item for item in [offer.city, offer.country] if item),
            profile.preferred_locations,
            "Comparaison avec les zones recherchées",
        ),
        (
            "remote",
            offer.remote_policy,
            profile.remote_preferences,
            "Comparaison avec les préférences de télétravail",
        ),
    ]
    for name, value, preferences, detail in optional_criteria:
        if value and preferences:
            _add_breakdown(
                breakdown,
                name,
                _preference_match(value, preferences),
                detail,
            )

    offered_salary = offer.salary_min or offer.salary_max
    if offered_salary is not None and profile.minimum_salary is not None:
        salary_score = min(1.0, float(offered_salary) / float(profile.minimum_salary))
        _add_breakdown(
            breakdown,
            "salary",
            salary_score,
            f"Minimum annoncé comparé à {profile.minimum_salary:.0f} EUR",
        )

    active_weight = sum(item["weight"] for item in breakdown.values())
    if active_weight == 0:
        score = 0.0
    else:
        score = sum(
            item["raw_score"] * item["weight"] for item in breakdown.values()
        ) / active_weight

    strengths = [f"Compétence correspondante : {name}" for name in matched_skills]
    gaps = [f"Compétence non renseignée dans le profil : {name}" for name in missing_skills]
    for item in breakdown.values():
        if item["raw_score"] >= 75 and item["label"] != "Compétences":
            strengths.append(f"{item['label']} compatible")
        elif item["raw_score"] < 45 and item["label"] != "Compétences":
            gaps.append(f"{item['label']} peu compatible")

    return MatchResult(
        score=round(score, 1),
        breakdown=breakdown,
        strengths=strengths,
        gaps=gaps,
        detected_job_skills=detected,
    )
