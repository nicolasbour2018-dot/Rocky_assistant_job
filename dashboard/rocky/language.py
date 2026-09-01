"""Détection locale, déterministe et explicable du français ou de l'anglais."""

from __future__ import annotations

import re
from dataclasses import dataclass

FRENCH_MARKERS = {
    "le",
    "la",
    "les",
    "des",
    "une",
    "avec",
    "pour",
    "vous",
    "votre",
    "poste",
    "missions",
    "compétences",
    "expérience",
    "entreprise",
    "équipe",
}
ENGLISH_MARKERS = {
    "the",
    "and",
    "with",
    "for",
    "you",
    "your",
    "role",
    "skills",
    "experience",
    "company",
    "team",
    "responsibilities",
    "requirements",
}


@dataclass(frozen=True)
class LanguageDetection:
    """Résultat borné à FR/EN avec un niveau de confiance affichable."""

    locale: str
    confidence: float
    uncertain: bool = False


def detect_language(value: str) -> LanguageDetection:
    """Classe un texte à partir de marqueurs fréquents, sans service externe.

    Le score reste volontairement conservateur : un texte trop court ou à
    égalité retombe en français et sera signalé comme incertain dans l'UI.
    """
    tokens = re.findall(r"[a-zà-ÿ]+", value.casefold())
    french = sum(token in FRENCH_MARKERS for token in tokens)
    english = sum(token in ENGLISH_MARKERS for token in tokens)
    evidence = french + english
    if evidence < 3 or french == english:
        return LanguageDetection("fr", 0.5, True)
    locale = "en" if english > french else "fr"
    confidence = max(french, english) / evidence
    return LanguageDetection(locale, round(confidence, 3), confidence < 0.7)


def effective_language(detected: str, override: str = "") -> str:
    """Applique la correction humaine avant le résultat automatique."""
    if override in {"fr", "en"}:
        return override
    return "en" if detected == "en" else "fr"
