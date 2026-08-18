"""Simulation locale et explicable de compatibilité avec les ATS."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from dashboard.job_analysis import analyze_job

from .errors import DocumentError
from .models import JobOffer
from .text_utils import normalize_text


@dataclass(frozen=True)
class AtsReport:
    """Petit rapport indicatif destiné à guider une relecture humaine."""

    score: int
    rating: str
    cv_score: int
    letter_score: int
    keyword_coverage: int | None
    readability_score: int
    cv_pages: int
    cv_characters: int
    letter_words: int
    matched_keywords: tuple[str, ...]
    missing_keywords: tuple[str, ...]
    strengths: tuple[str, ...]
    alerts: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AtsSkillMatch:
    """Rapprochement partiel affiché comme tel, jamais comme match exact."""

    required_skill: str
    cv_evidence: str
    confidence: int


@dataclass(frozen=True)
class AtsV2Report:
    """Rapport V2 distinguant parsing, exactitude et proximité sémantique."""

    score: int
    rating: str
    cv_score: int
    letter_score: int
    exact_keyword_coverage: int | None
    adjusted_keyword_coverage: int | None
    parsing_score: int
    cv_pages: int
    cv_characters: int
    letter_words: int
    text_source: str
    exact_keywords: tuple[str, ...]
    related_keywords: tuple[AtsSkillMatch, ...]
    missing_keywords: tuple[str, ...]
    strengths: tuple[str, ...]
    alerts: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


RELATED_SKILLS: dict[str, tuple[tuple[str, int], ...]] = {
    "agile": (("gestion de projet", 58), ("scrum", 90), ("kanban", 90)),
    "git": (("github", 82), ("gitlab", 82)),
    "jupyter": (("notebook", 88), ("jupyterlab", 95)),
    "matplotlib": (
        ("seaborn", 78),
        ("plotly", 72),
        ("data visualisation", 56),
    ),
    "power bi": (
        ("dashboarding", 62),
        ("data visualisation", 54),
        ("tableau", 52),
    ),
    "numpy": (("pandas", 52),),
    "pandas": (("numpy", 52),),
}


def extract_pdf_text(path: str | Path) -> tuple[str, int, int]:
    """Extrait le texte visible d’un PDF comme le ferait un parseur d’ATS."""
    cv_path = Path(path)
    if not cv_path.is_file():
        raise DocumentError("Le CV associé au profil est introuvable.")
    if cv_path.suffix.lower() != ".pdf":
        raise DocumentError("Le test ATS attend un CV au format PDF.")
    try:
        from pypdf import PdfReader

        reader = PdfReader(cv_path)
        if reader.is_encrypted and reader.decrypt("") == 0:
            raise DocumentError(
                "Le CV est chiffré : un ATS risque de ne pas pouvoir le lire."
            )
        page_texts = [(page.extract_text() or "").strip() for page in reader.pages]
    except DocumentError:
        raise
    except Exception as error:
        raise DocumentError(
            "Le texte du CV PDF n’a pas pu être extrait pour le test ATS."
        ) from error
    text = "\n".join(page_texts).strip()
    return text, len(page_texts), sum(bool(text) for text in page_texts)


def repair_spaced_pdf_text(text: str) -> tuple[str, float]:
    """Réassemble les PDF qui exposent chaque lettre comme un glyphe séparé.

    La réparation n'est appliquée qu'aux segments composés majoritairement de
    caractères isolés. Les phrases normalement espacées restent inchangées.
    """
    isolated = 0
    tokens_count = 0
    repaired_lines: list[str] = []
    for line in text.splitlines():
        segments = re.split(r" {2,}", line)
        repaired_segments: list[str] = []
        for segment in segments:
            tokens = [token for token in segment.split(" ") if token]
            if not tokens:
                continue
            single_count = sum(len(token) == 1 for token in tokens)
            isolated += single_count
            tokens_count += len(tokens)
            if len(tokens) >= 2 and single_count / len(tokens) >= 0.65:
                repaired_segments.append("".join(tokens))
            else:
                repaired_segments.append(" ".join(tokens))
        repaired_lines.append(" ".join(repaired_segments).strip())
    ratio = isolated / tokens_count if tokens_count else 0.0
    return "\n".join(repaired_lines).strip(), ratio


def ats_text_path(profiles_dir: Path, profile_id: int) -> Path:
    return profiles_dir / str(profile_id) / "cv_ats.txt"


def load_ats_cv_text(
    cv_path: str | Path, override_path: str | Path | None = None
) -> tuple[str, bool]:
    """Charge la correction utilisateur ou reconstruit le texte du PDF."""
    if override_path:
        saved_path = Path(override_path)
        if saved_path.is_file():
            return saved_path.read_text(encoding="utf-8"), True
    raw_text, _, _ = extract_pdf_text(cv_path)
    repaired_text, _ = repair_spaced_pdf_text(raw_text)
    return repaired_text, False


def save_ats_cv_text(path: str | Path, text: str) -> Path:
    """Enregistre uniquement le texte d'analyse, jamais le PDF original."""
    clean_text = text.strip()
    if len(clean_text) < 100:
        raise DocumentError(
            "Le texte ATS du CV est trop court pour remplacer l’extraction PDF."
        )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(clean_text + "\n", encoding="utf-8")
    return target


def _weighted_score(parts: list[tuple[float | None, float]]) -> int:
    available = [(score, weight) for score, weight in parts if score is not None]
    total_weight = sum(weight for _, weight in available)
    if not total_weight:
        return 0
    value = sum(float(score) * weight for score, weight in available) / total_weight
    return round(min(100.0, max(0.0, value)))


def _ordered_unique(values: list[str]) -> list[str]:
    found: dict[str, str] = {}
    for value in values:
        key = normalize_text(value)
        if key:
            found.setdefault(key, value.strip())
    return list(found.values())


def _skills_in_text(text: str) -> set[str]:
    return {
        normalize_text(skill)
        for skill in analyze_job("", text)["all_skills"]
        if normalize_text(skill)
    }


def _keyword_present(
    keyword: str, detected_skills: set[str], normalized_document: str
) -> bool:
    key = normalize_text(keyword)
    if key in detected_skills:
        return True
    if not key:
        return False
    return re.search(
        r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])",
        normalized_document,
    ) is not None


def _rating(score: int) -> str:
    if score >= 80:
        return "Compatibilité solide"
    if score >= 65:
        return "Base correcte, à optimiser"
    if score >= 45:
        return "Compatibilité fragile"
    return "Risque de lecture ou de ciblage"


def _contact_and_structure_scores(text: str) -> tuple[int, int, list[str]]:
    normalized = normalize_text(text)
    email_found = bool(
        re.search(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", text, re.IGNORECASE)
    )
    phone_found = bool(
        re.search(r"(?:\+33|0)[1-9](?:[ .-]?\d{2}){4}", text)
    )
    contact_score = 50 * int(email_found) + 50 * int(phone_found)
    sections = (
        ("experience", "parcours"),
        ("competence", "technologies", "outils", "stack technique"),
        ("formation", "education", "diplome", "certification"),
    )
    structure_score = round(
        100
        * sum(any(term in normalized for term in alternatives) for alternatives in sections)
        / len(sections)
    )
    missing_contacts = []
    if not email_found:
        missing_contacts.append("adresse e-mail")
    if not phone_found:
        missing_contacts.append("numéro de téléphone")
    return contact_score, structure_score, missing_contacts


def _letter_score(
    letter_text: str, offer: JobOffer, required_keywords: list[str]
) -> tuple[int, int, bool, bool]:
    normalized = normalize_text(letter_text)
    letter_skills = _skills_in_text(letter_text)
    word_count = len(re.findall(r"\b[\wÀ-ÿ'-]+\b", letter_text))
    if 180 <= word_count <= 600:
        length_score = 100.0
    elif word_count < 180:
        length_score = min(100.0, 100 * word_count / 180)
    else:
        length_score = max(35.0, 100 - (word_count - 600) / 4)
    title_present = normalize_text(offer.job_title) in normalized
    company_present = normalize_text(offer.company_name) in normalized
    personalization_score = 50 * int(title_present) + 50 * int(company_present)
    keyword_count = sum(
        _keyword_present(keyword, letter_skills, normalized)
        for keyword in required_keywords
    )
    desired_keywords = min(4, len(required_keywords))
    keyword_score = (
        min(100.0, 100 * keyword_count / desired_keywords)
        if desired_keywords
        else None
    )
    structure_signals = (
        "objet" in normalized,
        "madame" in normalized or "monsieur" in normalized,
        "salutations" in normalized or "cordialement" in normalized,
    )
    score = _weighted_score(
        [
            (float(personalization_score), 35),
            (keyword_score, 30),
            (length_score, 25),
            (float(round(100 * sum(structure_signals) / 3)), 10),
        ]
    )
    return score, word_count, title_present, company_present


def _near_skill_match(
    required_skill: str,
    cv_skills: dict[str, str],
    normalized_cv: str,
) -> AtsSkillMatch | None:
    required_key = normalize_text(required_skill)
    best_evidence = ""
    best_confidence = 0
    for evidence, confidence in RELATED_SKILLS.get(required_key, ()): 
        evidence_key = normalize_text(evidence)
        if _keyword_present(evidence, set(cv_skills), normalized_cv):
            if confidence > best_confidence:
                best_evidence = cv_skills.get(evidence_key, evidence)
                best_confidence = confidence
    if len(required_key) >= 3:
        for skill_key, skill_name in cv_skills.items():
            ratio = round(100 * SequenceMatcher(None, required_key, skill_key).ratio())
            if ratio >= 62 and ratio > best_confidence:
                best_evidence = skill_name
                best_confidence = min(ratio, 88)
    if best_confidence < 52:
        return None
    return AtsSkillMatch(required_skill, best_evidence, best_confidence)


def analyze_application_ats_v2(
    cv_path: str | Path,
    letter_text: str,
    offer: JobOffer,
    *,
    cv_text_override: str | None = None,
) -> AtsV2Report:
    """Analyse V2 tolérant le tracking PDF, les alias et les compétences proches."""
    raw_text, cv_pages, readable_pages = extract_pdf_text(cv_path)
    repaired_text, spacing_ratio = repair_spaced_pdf_text(raw_text)
    cv_text = (cv_text_override or repaired_text).strip()
    if not cv_text:
        raise DocumentError("Le texte du CV est vide après extraction.")
    if not normalize_text(letter_text):
        raise DocumentError("La lettre est vide : le test ATS ne peut pas démarrer.")
    text_source = "Texte corrigé manuellement" if cv_text_override else "PDF réparé"

    analysis = analyze_job(offer.job_title, offer.responsibilities)
    required_keywords = _ordered_unique(
        [*offer.detected_skills, *analysis["all_skills"]]
    )
    detected_cv_skills = analyze_job("", cv_text)["all_skills"]
    cv_skills = {
        normalize_text(skill): skill for skill in detected_cv_skills
    }
    normalized_cv = normalize_text(cv_text)
    exact: list[str] = []
    related: list[AtsSkillMatch] = []
    missing: list[str] = []
    for requirement in required_keywords:
        if _keyword_present(requirement, set(cv_skills), normalized_cv):
            exact.append(requirement)
            continue
        near_match = _near_skill_match(requirement, cv_skills, normalized_cv)
        if near_match:
            related.append(near_match)
        else:
            missing.append(requirement)

    exact_coverage = (
        round(100 * len(exact) / len(required_keywords))
        if required_keywords
        else None
    )
    related_credit = sum(0.65 * match.confidence / 100 for match in related)
    adjusted_coverage = (
        round(100 * (len(exact) + related_credit) / len(required_keywords))
        if required_keywords
        else None
    )

    # Un texte présent mais espacé caractère par caractère est lisible après
    # réparation. Il conserve néanmoins un risque de parsing chez certains ATS.
    page_score = 100 * readable_pages / cv_pages if cv_pages else 0
    parsing_score = round(page_score)
    if spacing_ratio >= 0.35:
        parsing_score = min(parsing_score, 72)
    elif spacing_ratio >= 0.15:
        parsing_score = min(parsing_score, 85)
    contact_score, structure_score, missing_contacts = (
        _contact_and_structure_scores(cv_text)
    )
    title_tokens = set(normalize_text(offer.job_title).split())
    cv_title_tokens = set(normalized_cv[:500].split())
    title_score = (
        round(100 * len(title_tokens & cv_title_tokens) / len(title_tokens))
        if title_tokens
        else 0
    )
    cv_score = _weighted_score(
        [
            (
                float(adjusted_coverage)
                if adjusted_coverage is not None
                else None,
                50,
            ),
            (float(parsing_score), 15),
            (float(structure_score), 15),
            (float(contact_score), 10),
            (float(title_score), 10),
        ]
    )
    letter_score, letter_words, title_present, company_present = _letter_score(
        letter_text, offer, required_keywords
    )
    score = round(0.65 * cv_score + 0.35 * letter_score)

    strengths: list[str] = []
    alerts: list[str] = []
    if exact_coverage is not None:
        strengths.append(
            f"{len(exact)} compétence(s) exacte(s) sur "
            f"{len(required_keywords)} exigence(s) détectée(s)."
        )
    if related:
        strengths.append(
            f"{len(related)} compétence(s) proche(s) identifiée(s), avec crédit partiel."
        )
    if not missing_contacts:
        strengths.append("L’e-mail et le téléphone sont détectés après normalisation.")
    else:
        alerts.append("Coordonnée non détectée : " + " et ".join(missing_contacts) + ".")
    if spacing_ratio >= 0.15:
        alerts.append(
            "Le PDF expose de nombreux caractères séparés. Rocky les réassemble, "
            "mais certains ATS peuvent lire ce fichier moins correctement."
        )
    if missing:
        alerts.append(
            "Compétences sans preuve suffisante dans le CV : "
            + ", ".join(missing[:6])
            + "."
        )
    if title_present and company_present:
        strengths.append("La lettre cite clairement le poste et l’entreprise.")
    else:
        alerts.append("La lettre doit citer explicitement le poste et l’entreprise.")
    if letter_words > 600:
        alerts.append("La lettre dépasse 600 mots et gagnerait à être resserrée.")
    if not alerts:
        alerts.append("Aucune alerte majeure détectée par le contrôle V2.")

    return AtsV2Report(
        score=score,
        rating=_rating(score),
        cv_score=cv_score,
        letter_score=letter_score,
        exact_keyword_coverage=exact_coverage,
        adjusted_keyword_coverage=adjusted_coverage,
        parsing_score=parsing_score,
        cv_pages=cv_pages,
        cv_characters=len(cv_text),
        letter_words=letter_words,
        text_source=text_source,
        exact_keywords=tuple(exact),
        related_keywords=tuple(related),
        missing_keywords=tuple(missing),
        strengths=tuple(strengths[:5]),
        alerts=tuple(alerts[:5]),
    )


def analyze_application_ats(
    cv_path: str | Path,
    letter_text: str,
    offer: JobOffer,
) -> AtsReport:
    """Évalue localement le CV et la lettre face à une annonce.

    Ce score est une heuristique transparente. Il mesure des signaux courants
    de parsing et de ciblage mais ne prédit pas la décision d’un ATS propriétaire.
    """
    cv_text, cv_pages, readable_pages = extract_pdf_text(cv_path)
    cv_normalized = normalize_text(cv_text)
    letter_normalized = normalize_text(letter_text)
    if not letter_normalized:
        raise DocumentError("La lettre est vide : le test ATS ne peut pas démarrer.")

    analysis = analyze_job(offer.job_title, offer.responsibilities)
    required_keywords = _ordered_unique(
        [*offer.detected_skills, *analysis["all_skills"]]
    )
    cv_skills = _skills_in_text(cv_text)
    letter_skills = _skills_in_text(letter_text)
    matched_keywords = [
        keyword
        for keyword in required_keywords
        if _keyword_present(keyword, cv_skills, cv_normalized)
    ]
    missing_keywords = [
        keyword for keyword in required_keywords if keyword not in matched_keywords
    ]
    keyword_coverage = (
        round(100 * len(matched_keywords) / len(required_keywords))
        if required_keywords
        else None
    )

    characters_score = min(100.0, len(cv_text) / 10)
    page_readability = (
        100 * readable_pages / cv_pages if cv_pages else 0.0
    )
    readability_score = round(0.55 * page_readability + 0.45 * characters_score)

    section_terms = (
        ("experience", "parcours"),
        ("competence", "technologies", "outils"),
        ("formation", "education", "diplome"),
    )
    section_count = sum(
        any(term in cv_normalized for term in alternatives)
        for alternatives in section_terms
    )
    structure_score = round(100 * section_count / len(section_terms))
    email_found = bool(
        re.search(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", cv_text, re.IGNORECASE)
    )
    phone_found = bool(
        re.search(r"(?:\+33|0)[1-9](?:[ .-]?\d{2}){4}", cv_text)
    )
    contact_score = 50 * int(email_found) + 50 * int(phone_found)
    cv_score = _weighted_score(
        [
            (float(keyword_coverage) if keyword_coverage is not None else None, 50),
            (float(readability_score), 25),
            (float(structure_score), 15),
            (float(contact_score), 10),
        ]
    )

    letter_words = len(re.findall(r"\b[\wÀ-ÿ'-]+\b", letter_text))
    if 180 <= letter_words <= 600:
        length_score = 100.0
    elif letter_words < 180:
        length_score = min(100.0, 100 * letter_words / 180)
    else:
        length_score = max(35.0, 100 - (letter_words - 600) / 4)
    title_present = normalize_text(offer.job_title) in letter_normalized
    company_present = normalize_text(offer.company_name) in letter_normalized
    personalization_score = 50 * int(title_present) + 50 * int(company_present)
    letter_keyword_count = sum(
        _keyword_present(keyword, letter_skills, letter_normalized)
        for keyword in required_keywords
    )
    desired_letter_keywords = min(4, len(required_keywords))
    letter_keyword_score = (
        min(100.0, 100 * letter_keyword_count / desired_letter_keywords)
        if desired_letter_keywords
        else None
    )
    structure_signals = (
        "objet" in letter_normalized,
        "madame" in letter_normalized or "monsieur" in letter_normalized,
        "salutations" in letter_normalized or "cordialement" in letter_normalized,
    )
    letter_structure_score = round(100 * sum(structure_signals) / 3)
    letter_score = _weighted_score(
        [
            (float(personalization_score), 35),
            (letter_keyword_score, 30),
            (length_score, 25),
            (float(letter_structure_score), 10),
        ]
    )
    score = round(0.6 * cv_score + 0.4 * letter_score)

    strengths: list[str] = []
    alerts: list[str] = []
    if readability_score >= 85:
        strengths.append("Le texte du CV est correctement extractible du PDF.")
    elif len(cv_text) < 500:
        alerts.append(
            "Très peu de texte a été extrait du CV : vérifier les colonnes, "
            "images et blocs graphiques."
        )
    else:
        alerts.append("Certaines pages ou zones du CV peuvent être mal lues.")
    if keyword_coverage is None:
        alerts.append(
            "Rocky n’a pas identifié assez de compétences dans l’annonce pour "
            "mesurer la couverture des mots-clés."
        )
    elif keyword_coverage >= 70:
        strengths.append(
            f"Le CV couvre {keyword_coverage} % des compétences détectées."
        )
    else:
        alerts.append(
            f"Le CV ne couvre que {keyword_coverage} % des compétences détectées."
        )
    if not email_found or not phone_found:
        missing_contacts = []
        if not email_found:
            missing_contacts.append("adresse e-mail")
        if not phone_found:
            missing_contacts.append("numéro de téléphone")
        alerts.append("Coordonnée non détectée : " + " et ".join(missing_contacts) + ".")
    if title_present and company_present:
        strengths.append("La lettre cite clairement le poste et l’entreprise.")
    else:
        alerts.append("La lettre doit citer explicitement le poste et l’entreprise.")
    if letter_words < 180:
        alerts.append("La lettre est courte ; vérifier qu’elle démontre assez le ciblage.")
    elif letter_words > 600:
        alerts.append("La lettre dépasse 600 mots et gagnerait à être resserrée.")
    if missing_keywords:
        alerts.append(
            "Compétences prioritaires à vérifier dans le CV : "
            + ", ".join(missing_keywords[:5])
            + "."
        )
    if not alerts:
        alerts.append("Aucune alerte majeure détectée par ce contrôle local.")

    return AtsReport(
        score=score,
        rating=_rating(score),
        cv_score=cv_score,
        letter_score=letter_score,
        keyword_coverage=keyword_coverage,
        readability_score=readability_score,
        cv_pages=cv_pages,
        cv_characters=len(cv_text),
        letter_words=letter_words,
        matched_keywords=tuple(matched_keywords),
        missing_keywords=tuple(missing_keywords),
        strengths=tuple(strengths[:4]),
        alerts=tuple(alerts[:5]),
    )
