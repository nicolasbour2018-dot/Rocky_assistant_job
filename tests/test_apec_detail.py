"""Tests du format d'extraction Apec, indépendants du site distant."""

import pytest

from dashboard.rocky.sources.apec_detail import (
    ApecExtractionError,
    build_extraction,
    extract_offer_number,
    html_to_text,
)

URL = (
    "https://www.apec.fr/candidat/recherche-emploi.html/emploi/detail-offre/179302541W"
)


def test_extract_offer_number_validates_apec_detail_url():
    assert extract_offer_number(URL) == "179302541W"
    with pytest.raises(ApecExtractionError):
        extract_offer_number("https://example.org/detail-offre/179302541W")
    with pytest.raises(ApecExtractionError):
        extract_offer_number("https://www.apec.fr/candidat/recherche-emploi.html")


def test_html_to_text_preserves_list_items():
    text = html_to_text("<p>Mission</p><ul><li>Python</li><li>SQL</li></ul>")
    assert "Mission" in text
    assert "- Python" in text
    assert "- SQL" in text


def test_build_extraction_keeps_normalized_and_raw_payloads():
    offer_payload = {
        "id": 179302541,
        "numeroOffre": "179302541W",
        "intitule": "Software Engineer F/H",
        "enseigne": "Externatic",
        "idEtablissement": 712953,
        "nombrePostes": 2,
        "salaireTexte": "A partir de 65 k€ brut annuel",
        "lieux": [{"libelleLieu": "Paris 08 - 75"}],
        "texteHtml": "<p>Construire le produit.</p>",
        "texteHtmlProfil": "<ul><li>Node.js</li></ul>",
        "texteHtmlEntreprise": "<p>Cabinet tech.</p>",
        "competences": [
            {
                "libelle": "Autonomie",
                "type": "SAVOIR_ETRE",
                "idNomCompetence": 1,
            },
            {
                "libelle": "Node.js",
                "type": "SAVOIR_FAIRE",
                "idNomCompetence": 2,
                "idNomNiveau": 3,
            },
        ],
    }
    company_payload = {
        "id": 1082,
        "enTete": {
            "raisonSociale": "EXTERNATIC",
            "accroche": "Connexions durables",
        },
        "mainSection": {
            "entrepriseTitre": "Cabinet de recrutement informatique",
            "entreprise": "<p>Présentation complète.</p>",
        },
    }
    dom = {
        "heading": "Software Engineer F/H",
        "metadata_items": ["Externatic", "2 CDI", "Paris 08 - 75"],
        "detail_fields": {"experience_text": "Minimum 4 ans"},
        "application_url": "https://www.apec.fr/postuler",
    }

    result = build_extraction(URL, "179302541W", offer_payload, company_payload, dom)

    assert result["offer"]["contract_type"] == "CDI"
    assert result["offer"]["description"]["text"] == "Construire le produit."
    assert result["offer"]["skills"]["hard_skills"][0]["label"] == "Node.js"
    assert result["company_profile"]["tagline"] == "Connexions durables"
    assert result["raw"]["offer_api"] is offer_payload
    assert result["raw"]["company_api"] is company_payload
