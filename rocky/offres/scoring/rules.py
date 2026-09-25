"""Scoring rules: no I/O, no side effect. A posting analysis, the offer and the profile give a ``Score``.

Decision ``docs/decisions/C4-scoring.md``. The score never reads the text again: every fact comes from the posting
analysis (C3), with its evidence. One score per active track (Q1); each component says what it compared, and a
component without information is left out rather than guessed (Q17).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

from rocky.offres.analysis.model import (
    CONDITION_LABELS,
    IMPORTANCE_LABELS,
    PostingAnalysis,
    SalaryPeriod,
)
from rocky.offres.analysis.text import fold, term_pattern
from rocky.offres.scoring.model import (
    ABROAD,
    ABROAD_FULL_REMOTE,
    CAP,
    COMPONENT_LABELS,
    DEDUCED_PERIOD_FACTOR,
    EURO,
    FRANCE_NAMES,
    FULL_EVIDENCE,
    IMPORTANCE_POINTS,
    IN_ZONE,
    KEY_SKILL_FACTOR,
    LOW_EVIDENCE,
    LOWER_LANGUAGE_LEVEL,
    MANY_ABSENT,
    OPTIONAL_COMPONENTS,
    OUT_OF_ZONE,
    OUT_OF_ZONE_HYBRID,
    PARTIAL_TITLE_FACTOR,
    REQUIREMENT_PENALTY,
    RULES_VERSION,
    SCATTERED_TITLE,
    UNPROVEN_SKILL_FACTOR,
    WEIGHTS,
    Cap,
    CapKind,
    Component,
    ComponentCode,
    Confidence,
    ConfidenceLevel,
    Job,
    ProfileSkill,
    Score,
    ScoringProfile,
    ScoringTrack,
    TrackScore,
)
from rocky.offres.sources.model import CollectedOffer
from rocky.profil.model import (
    CONTRACT_LABELS,
    LANGUAGE_LEVEL_LABELS,
    LANGUAGE_NAMES,
    REMOTE_LABELS,
    ExperienceKind,
    LanguageLevel,
    Profile,
    RemoteMode,
    TrackStatus,
)

# Words a title comparison ignores (Q4), in comparison form.
_STOP_WORDS = frozenset(
    "h f hf fh x m w e de du des d le la les l et en a au aux un une the of and for in".split()  # noqa: SIM905  (a word list)
)
# Language levels from the lowest; ``LanguageLevel`` lists them in this order.
_LEVEL_RANK = {level: rank for rank, level in enumerate(LanguageLevel)}
_DAYS_PER_YEAR = 365.25


def scoring_profile(profile: Profile) -> ScoringProfile:
    """What the score reads of a profile: skills with their key flag and proof, active tracks, jobs (not trainings)."""
    proven = {
        *(
            i
            for experience in profile.experiences
            for i in experience.content.skill_ids
        ),
        *(i for project in profile.projects for i in project.content.skill_ids),
    }
    labels = {skill.id: skill.label.fr for skill in profile.skills}
    return ScoringProfile(
        skills=tuple(
            ProfileSkill(
                label=skill.label.fr,
                is_key=skill.content.is_key,
                proven=skill.id in proven,
                level=skill.content.level,
            )
            for skill in profile.skills
        ),
        tracks=tuple(
            ScoringTrack(
                id=track.id,
                name=track.name,
                titles=track.content.titles,
                keywords=track.content.keywords,
                excluded_keywords=track.content.excluded_keywords,
                locations=track.content.locations,
            )
            for track in profile.tracks
            if track.status == TrackStatus.ACTIVE
        ),
        preferences=profile.preferences,
        languages=tuple(
            (language.content.code, language.content.level)
            for language in profile.languages
        ),
        jobs=tuple(
            Job(
                start=experience.content.start,
                end=experience.content.end,
                skills=frozenset(
                    labels[skill_id]
                    for skill_id in experience.content.skill_ids
                    if skill_id in labels
                ),
            )
            for experience in profile.experiences
            if experience.content.kind == ExperienceKind.JOB
        ),
    )


def score(
    analysis: PostingAnalysis,
    offer: CollectedOffer,
    profile: ScoringProfile,
    *,
    today: date,
) -> Score:
    """The score of ``offer`` for each active track of the profile: a pure function, it writes nothing."""
    shared = _shared(analysis, offer, profile, today)
    tracks: Iterable[ScoringTrack | None] = profile.tracks or (None,)
    return Score(
        rules_version=RULES_VERSION,
        analysis_rules_version=analysis.rules_version,
        tracks=tuple(_track_score(shared, track) for track in tracks),
    )


@dataclass(frozen=True)
class _Shared:
    """What does not depend on the track, computed once per posting."""

    analysis: PostingAnalysis
    offer: CollectedOffer
    folded_title: str
    folded_description: str
    net_evidence: float
    skills: Component
    contract: Component
    remote: Component
    salary: Component
    experience: Component
    languages: Component
    caps: tuple[Cap, ...]
    features: dict[str, Any]


def _shared(
    analysis: PostingAnalysis,
    offer: CollectedOffer,
    profile: ScoringProfile,
    today: date,
) -> _Shared:
    skills, net_evidence, skill_features = _skills(analysis, profile)
    experience, experience_features = _experience(analysis, profile, today)
    salary = analysis.salary
    features: dict[str, Any] = {
        "description_complete": offer.description_complete,
        "skills": skill_features,
        "requirements": len(analysis.requirements),
        "net_evidence": net_evidence,
        "conditions": [condition.kind.value for condition in analysis.conditions],
        "contracts_offered": [contract.value for contract in analysis.contracts],
        "contracts_wanted": [c.value for c in profile.preferences.contracts],
        "remote": analysis.remote.value if analysis.remote else None,
        "remote_wanted": [mode.value for mode in profile.preferences.remote_modes],
        "location": offer.location,
        "country": offer.country,
        "salary": None
        if salary is None
        else {
            "minimum": salary.minimum,
            "maximum": salary.maximum,
            "currency": salary.currency,
            "period": salary.period.value,
            "period_deduced": salary.period_deduced,
        },
        "min_salary_eur": profile.preferences.min_salary_eur,
        "min_daily_rate_eur": profile.preferences.min_daily_rate_eur,
        **experience_features,
        "languages": [
            {
                "code": need.code,
                "level": need.level.value if need.level else None,
                "own_level": own.value
                if (own := dict(profile.languages).get(need.code))
                else None,
            }
            for need in analysis.languages
        ],
    }
    return _Shared(
        analysis=analysis,
        offer=offer,
        folded_title=fold(offer.title).text,
        folded_description=fold(analysis.description).text,
        net_evidence=net_evidence,
        skills=skills,
        contract=_contract(analysis, profile),
        remote=_remote(analysis, profile),
        salary=_salary(analysis, profile),
        experience=experience,
        languages=_languages(analysis, profile),
        caps=tuple(
            Cap(
                CapKind.CONDITION,
                f"Bloquant : {CONDITION_LABELS[condition.kind]}",
                condition.evidence,
            )
            for condition in analysis.conditions
        ),
        features=features,
    )


def _track_score(shared: _Shared, track: ScoringTrack | None) -> TrackScore:
    title, title_features = _title(shared, track)
    location, location_unknown, location_notes = _location(shared, track)
    caps, word_notes, word_features = _excluded_words(shared, track)
    components = (
        shared.skills,
        title,
        shared.contract,
        location,
        shared.remote,
        shared.salary,
        shared.experience,
        shared.languages,
    )
    all_caps = (*shared.caps, *caps)
    uncapped = _merge(components)
    value = min(uncapped, CAP) if all_caps else uncapped
    return TrackScore(
        track_id=track.id if track else None,
        track_name=track.name if track else None,
        value=value,
        uncapped=uncapped,
        components=components,
        confidence=_confidence(shared, track, components, location_unknown),
        caps=all_caps,
        gaps=_gaps(shared.analysis, components),
        notes=(*location_notes, *word_notes),
        features={
            **shared.features,
            **title_features,
            **word_features,
            "location_value": location.value,
        },
    )


def _merge(components: Iterable[Component]) -> float:
    """Weighted mean of the counted components, on 100; a left-out component weighs nothing (Q17)."""
    counted = [
        (item.value, item.weight) for item in components if item.value is not None
    ]
    total = sum(weight for _, weight in counted)
    if total == 0:
        return 0.0
    return round(100 * sum(value * weight for value, weight in counted) / total, 2)


# Skills (Q2, Q3, Q26).


def _skills(
    analysis: PostingAnalysis, profile: ScoringProfile
) -> tuple[Component, float, list[dict[str, Any]]]:
    by_label = {skill.label: skill for skill in profile.skills}
    points = 0.0
    evidence: list[str] = []
    features: list[dict[str, Any]] = []
    for match in analysis.skills:
        skill = by_label.get(match.skill, ProfileSkill(match.skill))
        value = (
            IMPORTANCE_POINTS[match.importance]
            * (KEY_SKILL_FACTOR if skill.is_key else 1.0)
            * (1.0 if skill.proven else UNPROVEN_SKILL_FACTOR)
        )
        points += value
        qualities = [
            IMPORTANCE_LABELS[match.importance].lower(),
            *(["clé"] if skill.is_key else []),
            "prouvée" if skill.proven else "non prouvée",
        ]
        evidence.append(
            f"{match.skill} ({', '.join(qualities)}, {number(value)} pt) : "
            f"« {match.evidence} »"
        )
        features.append(
            {
                "skill": match.skill,
                "importance": match.importance.value,
                "key": skill.is_key,
                "proven": skill.proven,
                "level": skill.level.value if skill.level else None,
                "points": round(value, 4),
            }
        )
    requirements = len(analysis.requirements)
    penalty = REQUIREMENT_PENALTY * requirements
    net = max(0.0, points - penalty)
    detail = (
        f"{len(analysis.skills)} compétence(s) du profil dans l'annonce : "
        f"{number(points)} point(s) de preuve"
    )
    if requirements:
        detail += (
            f", moins {number(penalty)} pour {requirements} exigence(s) hors profil"
        )
    detail += f" ; pleine à {number(FULL_EVIDENCE)} points"
    component = Component(
        ComponentCode.SKILLS,
        min(1.0, net / FULL_EVIDENCE),
        WEIGHTS[ComponentCode.SKILLS],
        detail,
        tuple(evidence),
    )
    return component, round(net, 4), features


# Title and excluded words (Q4, Q5, Q19).


def _title(
    shared: _Shared, track: ScoringTrack | None
) -> tuple[Component, dict[str, Any]]:
    weight = WEIGHTS[ComponentCode.TITLE]
    if track is None:
        return Component(
            ComponentCode.TITLE,
            None,
            weight,
            "Aucune piste active : intitulé non comparé",
        ), {"title_value": None, "track_title": None}
    if not track.titles:
        return Component(
            ComponentCode.TITLE,
            0.0,
            weight,
            f"La piste « {track.name} » n'a pas d'intitulé",
        ), {"title_value": 0.0, "track_title": None}
    best_value, best_title, best_detail = -1.0, "", ""
    for title in track.titles:
        value, detail = _title_value(shared.folded_title, title)
        if value > best_value:
            best_value, best_title, best_detail = value, title, detail
    return Component(ComponentCode.TITLE, best_value, weight, best_detail), {
        "title_value": best_value,
        "track_title": best_title,
    }


def _title_value(folded_offer_title: str, track_title: str) -> tuple[float, str]:
    phrase = fold(track_title).text
    if phrase and term_pattern(phrase).search(folded_offer_title):
        return 1.0, f"« {track_title} » figure tel quel dans l'intitulé"
    words = [
        word for word in phrase.split() if word not in _STOP_WORDS
    ] or phrase.split()
    if not words:
        return 0.0, f"« {track_title} » n'a aucun mot à comparer"
    present = sum(1 for word in words if term_pattern(word).search(folded_offer_title))
    if present == len(words):
        return (
            SCATTERED_TITLE,
            f"Les mots de « {track_title} » figurent dans l'intitulé, mais séparés",
        )
    return (
        PARTIAL_TITLE_FACTOR * present / len(words),
        f"{present} mot(s) sur {len(words)} de « {track_title} » dans l'intitulé",
    )


def _excluded_words(
    shared: _Shared, track: ScoringTrack | None
) -> tuple[tuple[Cap, ...], tuple[str, ...], dict[str, Any]]:
    """An excluded word in the title caps the score; in the description it is only shown (Q5)."""
    caps: list[Cap] = []
    notes: list[str] = []
    in_title: list[str] = []
    in_description: list[str] = []
    keywords: list[str] = []
    if track is not None:
        for word in track.excluded_keywords:
            folded = fold(word).text
            if not folded:
                continue
            pattern = term_pattern(folded)
            if pattern.search(shared.folded_title):
                in_title.append(word)
                caps.append(
                    Cap(
                        CapKind.EXCLUDED_WORD, f"Mot exclu : {word}", shared.offer.title
                    )
                )
            elif pattern.search(shared.folded_description):
                in_description.append(word)
                notes.append(f"Mot exclu dans la description : {word}")
        for word in track.keywords:
            folded = fold(word).text
            if folded and (
                term_pattern(folded).search(shared.folded_title)
                or term_pattern(folded).search(shared.folded_description)
            ):
                keywords.append(word)
    return (
        tuple(caps),
        tuple(notes),
        {
            "excluded_in_title": in_title,
            "excluded_in_description": in_description,
            "keywords_found": keywords,
        },
    )


# Contract and remote work (Q7).


def _contract(analysis: PostingAnalysis, profile: ScoringProfile) -> Component:
    weight = WEIGHTS[ComponentCode.CONTRACT]
    wanted = profile.preferences.contracts
    if not analysis.contracts:
        return Component(
            ComponentCode.CONTRACT, None, weight, "Contrat non précisé par l'annonce"
        )
    if not wanted:
        return Component(
            ComponentCode.CONTRACT,
            None,
            weight,
            "Aucun contrat recherché dans le profil",
        )
    matches = set(analysis.contracts) & set(wanted)
    return Component(
        ComponentCode.CONTRACT,
        1.0 if matches else 0.0,
        weight,
        f"Proposé : {_labels(CONTRACT_LABELS, analysis.contracts)} ; "
        f"recherché : {_labels(CONTRACT_LABELS, wanted)}",
    )


def _remote(analysis: PostingAnalysis, profile: ScoringProfile) -> Component:
    weight = WEIGHTS[ComponentCode.REMOTE]
    wanted = profile.preferences.remote_modes
    if analysis.remote is None:
        return Component(
            ComponentCode.REMOTE, None, weight, "Télétravail non précisé par l'annonce"
        )
    if not wanted:
        return Component(
            ComponentCode.REMOTE,
            None,
            weight,
            "Aucun mode de travail recherché dans le profil",
        )
    return Component(
        ComponentCode.REMOTE,
        1.0 if analysis.remote in wanted else 0.0,
        weight,
        f"Proposé : {REMOTE_LABELS[analysis.remote]} ; recherché : {_labels(REMOTE_LABELS, wanted)}",
    )


# Location (Q9, Q15).


def _location(
    shared: _Shared, track: ScoringTrack | None
) -> tuple[Component, bool, tuple[str, ...]]:
    """The place component, whether the place is unknown (confidence), and notes to show."""
    weight = WEIGHTS[ComponentCode.LOCATION]
    offer, remote = shared.offer, shared.analysis.remote
    place = (offer.location or "").strip()
    country = fold(offer.country or "").text
    if track is None:
        return (
            Component(
                ComponentCode.LOCATION,
                None,
                weight,
                "Aucune piste active : lieu non comparé",
            ),
            False,
            (),
        )
    if country and country not in FRANCE_NAMES:
        where = ", ".join(part for part in (place, offer.country or "") if part)
        if remote == RemoteMode.FULL_REMOTE:
            return (
                Component(
                    ComponentCode.LOCATION,
                    ABROAD_FULL_REMOTE,
                    weight,
                    f"À l'étranger ({where}), en télétravail complet : "
                    "vérifier le droit au travail et le fuseau horaire",
                ),
                False,
                (),
            )
        return (
            Component(
                ComponentCode.LOCATION,
                ABROAD,
                weight,
                f"Hors zone : à l'étranger ({where})",
            ),
            False,
            (),
        )
    if remote == RemoteMode.FULL_REMOTE:
        return (
            Component(
                ComponentCode.LOCATION,
                None,
                weight,
                "Télétravail complet : le lieu ne compte pas",
                neutral=True,
            ),
            False,
            (),
        )
    if not place:
        return (
            Component(
                ComponentCode.LOCATION, None, weight, "Lieu non précisé par l'annonce"
            ),
            True,
            (),
        )
    if not track.locations:
        return (
            Component(
                ComponentCode.LOCATION,
                None,
                weight,
                f"La piste « {track.name} » n'a pas de lieu",
            ),
            False,
            (),
        )
    folded_place = fold(place).text
    for location in track.locations:
        folded = fold(location).text
        if folded and (
            folded in FRANCE_NAMES or term_pattern(folded).search(folded_place)
        ):
            return (
                Component(
                    ComponentCode.LOCATION,
                    IN_ZONE,
                    weight,
                    f"{place} : dans la zone « {location} »",
                ),
                False,
                (),
            )
    hybrid = remote == RemoteMode.HYBRID
    notes = () if country else ("Pays non précisé : l'offre est lue comme en France",)
    return (
        Component(
            ComponentCode.LOCATION,
            OUT_OF_ZONE_HYBRID if hybrid else OUT_OF_ZONE,
            weight,
            f"{place} : hors des lieux de la piste ({', '.join(track.locations)})"
            + (", en hybride" if hybrid else ""),
        ),
        False,
        notes,
    )


# Salary (Q8, Q24).


def _salary(analysis: PostingAnalysis, profile: ScoringProfile) -> Component:
    weight = WEIGHTS[ComponentCode.SALARY]
    salary = analysis.salary
    if salary is None:
        return Component(
            ComponentCode.SALARY, None, weight, "Salaire non précisé par l'annonce"
        )
    evidence = (salary.evidence,) if salary.evidence else ()
    # A figure without a currency is read in euros: the sources are French.
    if salary.currency and salary.currency != EURO:
        return Component(
            ComponentCode.SALARY,
            None,
            weight,
            f"Salaire en {salary.currency}, non comparé",
            evidence,
        )
    if salary.period == SalaryPeriod.HOURLY:
        return Component(
            ComponentCode.SALARY, None, weight, "Salaire horaire, non comparé", evidence
        )
    if salary.period == SalaryPeriod.DAILY:
        minimum, amount, unit = (
            profile.preferences.min_daily_rate_eur,
            salary.maximum,
            "par jour",
        )
        missing = "Aucun TJM minimum dans le profil"
    else:
        yearly = 12 if salary.period == SalaryPeriod.MONTHLY else 1
        minimum, amount, unit = (
            profile.preferences.min_salary_eur,
            salary.maximum * yearly,
            "par an",
        )
        missing = "Aucun salaire minimum dans le profil"
    if minimum is None or minimum <= 0:
        return Component(ComponentCode.SALARY, None, weight, missing, evidence)
    detail = (
        f"{_money(amount)} € {unit} au plus, pour un minimum de {_money(minimum)} €"
    )
    if salary.period_deduced:
        weight *= DEDUCED_PERIOD_FACTOR
        detail += " ; période déduite du montant (poids réduit de moitié)"
    return Component(
        ComponentCode.SALARY, min(1.0, amount / minimum), weight, detail, evidence
    )


# Experience and languages (Q10, Q22, Q23).


def _experience(
    analysis: PostingAnalysis, profile: ScoringProfile, today: date
) -> tuple[Component, dict[str, Any]]:
    weight = WEIGHTS[ComponentCode.EXPERIENCE]
    need = analysis.experience
    matched = {match.skill for match in analysis.skills}
    relevant_jobs = [job for job in profile.jobs if job.skills & matched]
    relevant = _years(relevant_jobs, today)
    total = _years(profile.jobs, today)
    features = {
        "experience_asked": need.years if need else None,
        "relevant_years": relevant,
        "total_years": total,
    }
    if need is None:
        return Component(
            ComponentCode.EXPERIENCE,
            None,
            weight,
            "Expérience non précisée par l'annonce",
        ), features
    if relevant_jobs:
        used = sorted(
            {skill for job in relevant_jobs for skill in job.skills & matched}
        )
        detail = (
            f"{number(relevant)} an(s) sur des postes utilisant {', '.join(used[:5])}"
        )
    else:
        detail = "Aucun poste du profil lié aux compétences de l'annonce"
    detail += (
        f" ; {need.years} an(s) demandé(s) ; {number(total)} an(s) d'emploi au total"
    )
    value = 1.0 if need.years == 0 else min(1.0, relevant / need.years)
    return Component(
        ComponentCode.EXPERIENCE, value, weight, detail, (need.evidence,)
    ), features


def _years(jobs: Iterable[Job], today: date) -> float:
    """Years covered by the jobs, overlapping periods counted once."""
    periods = sorted((job.start, min(job.end or today, today)) for job in jobs)
    days = 0
    current_start: date | None = None
    current_end: date | None = None
    for start, end in periods:
        if end < start:
            continue
        if current_end is None or current_start is None or start > current_end:
            if current_end is not None and current_start is not None:
                days += (current_end - current_start).days
            current_start, current_end = start, end
        elif end > current_end:
            current_end = end
    if current_end is not None and current_start is not None:
        days += (current_end - current_start).days
    return round(days / _DAYS_PER_YEAR, 1)


def _languages(analysis: PostingAnalysis, profile: ScoringProfile) -> Component:
    weight = WEIGHTS[ComponentCode.LANGUAGES]
    if not analysis.languages:
        return Component(
            ComponentCode.LANGUAGES, None, weight, "Aucune langue demandée"
        )
    own = dict(profile.languages)
    values: list[float] = []
    parts: list[str] = []
    for need in analysis.languages:
        name = LANGUAGE_NAMES.get(need.code, need.code)
        asked = f" {LANGUAGE_LEVEL_LABELS[need.level]}" if need.level else ""
        level = own.get(need.code)
        if level is None:
            values.append(0.0)
            parts.append(f"{name}{asked} : absente du profil")
        elif need.level is None or _LEVEL_RANK[level] >= _LEVEL_RANK[need.level]:
            values.append(1.0)
            parts.append(f"{name}{asked} : {LANGUAGE_LEVEL_LABELS[level]} au profil")
        else:
            values.append(LOWER_LANGUAGE_LEVEL)
            parts.append(
                f"{name}{asked} : {LANGUAGE_LEVEL_LABELS[level]} au profil, niveau inférieur"
            )
    return Component(
        ComponentCode.LANGUAGES,
        sum(values) / len(values),
        weight,
        " ; ".join(parts),
        tuple(need.evidence for need in analysis.languages),
    )


# Confidence and gaps (Q11, Q25).


def _confidence(
    shared: _Shared,
    track: ScoringTrack | None,
    components: Iterable[Component],
    location_unknown: bool,
) -> Confidence:
    low: list[str] = []
    medium: list[str] = []
    offer = shared.offer
    if not offer.description_complete:
        reason = f" : {offer.incomplete_reason}" if offer.incomplete_reason else ""
        low.append(f"Description incomplète{reason}")
    if shared.net_evidence < LOW_EVIDENCE:
        low.append(
            f"Preuves insuffisantes : {number(shared.net_evidence)} point(s) de preuve, "
            f"{number(LOW_EVIDENCE)} au minimum"
        )
    if track is None:
        low.append("Aucune piste active : ni intitulé ni lieu comparés")
    absent = [
        item
        for item in components
        if item.code in OPTIONAL_COMPONENTS and item.value is None and not item.neutral
    ]
    if len(absent) >= MANY_ABSENT:
        names = ", ".join(COMPONENT_LABELS[item.code].lower() for item in absent)
        medium.append(
            f"{len(absent)} composantes sur {len(OPTIONAL_COMPONENTS)} sans information : {names}"
        )
    if (
        shared.salary.value is not None
        and shared.analysis.salary is not None
        and shared.analysis.salary.period_deduced
    ):
        medium.append("Période du salaire déduite du montant")
    if location_unknown:
        medium.append("Lieu non précisé")
    level = (
        ConfidenceLevel.LOW
        if low
        else ConfidenceLevel.MEDIUM
        if medium
        else ConfidenceLevel.HIGH
    )
    return Confidence(level, (*low, *medium))


def _gaps(
    analysis: PostingAnalysis, components: Iterable[Component]
) -> tuple[str, ...]:
    """What the posting asks and the profile lacks: requirements outside the profile, then weak components."""
    gaps = [
        f"Exigence hors profil : « {sentence} »" for sentence in analysis.requirements
    ]
    gaps.extend(
        f"{COMPONENT_LABELS[item.code]} : {item.detail}"
        for item in components
        if item.code != ComponentCode.SKILLS
        and item.value is not None
        and item.value < 1.0
    )
    return tuple(gaps)


# Display helpers (French numbers).


def _labels[C: str](labels: dict[C, str], values: Iterable[C]) -> str:
    return ", ".join(labels[value] for value in values)


def number(value: float) -> str:
    """French number for display: "1,5", "4", "0,45"."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def _money(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")
