"""Extraction exhaustive d'une fiche d'offre Apec avec un navigateur Playwright.

La page de détail Apec est une application Angular : le HTML reçu par une
requête HTTP classique ne contient pas la fiche. Ce module ouvre donc la page
réelle, lit le composant rendu et interroge, dans le même contexte navigateur,
les endpoints JSON utilisés par l'interface. La sortie conserve les données
normalisées et les réponses brutes afin qu'une future migration vers la base
Rocky ne perde aucun champ publié par Apec.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


APEC_HOSTS = {"apec.fr", "www.apec.fr"}
DETAIL_XPATH = (
    "/html/body/main/div/apec-offres/div/apec-detail-emploi/div/div/"
    "div[2]/article/div/div/apec-poste-informations"
)
OFFER_ENDPOINT = "https://www.apec.fr/cms/webservices/offre/public"
COMPANY_ENDPOINT = "https://www.apec.fr/cms/webservices/pageEntreprise/public"

DETAIL_FIELD_NAMES = {
    "Salaire": "salary_text",
    "Prise de poste": "start_date_text",
    "Expérience": "experience_text",
    "Métier": "job_family",
    "Statut du poste": "job_status",
    "Zone de déplacement": "travel_zone",
    "Secteur d’activité du poste": "industry",
}


class ApecExtractionError(RuntimeError):
    """Erreur lisible signalant qu'une fiche Apec n'a pas pu être extraite."""


def extract_offer_number(url: str) -> str:
    """Valide une URL publique de détail Apec et retourne son numéro d'offre.

    La validation stricte du domaine empêche le navigateur d'être détourné vers
    une URL arbitraire lorsque ce service sera appelé depuis l'interface Rocky.
    """
    parts = urlsplit(url.strip())
    if (
        parts.scheme not in {"http", "https"}
        or parts.netloc.lower() not in APEC_HOSTS
    ):
        raise ApecExtractionError(
            "L’URL doit être une fiche publique du domaine apec.fr."
        )
    match = re.search(r"/detail-offre/([^/?#]+)", parts.path)
    if not match or not re.fullmatch(r"\d+[A-Za-z]?", match.group(1)):
        raise ApecExtractionError("Le numéro d’offre Apec est absent ou invalide.")
    return match.group(1)


def html_to_text(value: Any) -> str:
    """Convertit un bloc HTML Apec en texte structuré sans perdre les listes."""
    if value in (None, ""):
        return ""
    soup = BeautifulSoup(str(value), "html.parser")
    for line_break in soup.find_all("br"):
        line_break.replace_with("\n")
    for item in soup.find_all("li"):
        # Aplatir le contenu du ``li`` évite que ``get_text`` place le tiret
        # et le libellé sur deux lignes lorsque le texte contient un ``strong``.
        item_text = item.get_text(" ", strip=True)
        item.clear()
        item.append(f"- {item_text}\n")
    text = soup.get_text("\n")
    lines = [re.sub(r"[ \t\xa0]+", " ", line).strip() for line in text.splitlines()]
    compact: list[str] = []
    for line in lines:
        if line or (compact and compact[-1]):
            compact.append(line)
    return "\n".join(compact).strip()


def _browser_json(page: Page, endpoint: str, suffix: str) -> dict[str, Any]:
    """Lit un endpoint Apec depuis la page pour réutiliser cookies et protections."""
    if suffix.startswith("?"):
        url = f"{endpoint}{suffix}"
    else:
        url = f"{endpoint}/{suffix}" if suffix else endpoint
    result = page.evaluate(
        """async url => {
            const response = await fetch(url, {
                credentials: 'include',
                headers: {Accept: 'application/json'}
            });
            const body = await response.text();
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${body.slice(0, 200)}`);
            }
            return JSON.parse(body);
        }""",
        url,
    )
    if not isinstance(result, dict):
        raise ApecExtractionError(f"Apec a renvoyé un JSON inattendu pour {url}.")
    return result


def _read_dom(page: Page, source_url: str) -> dict[str, Any]:
    """Extrait les libellés calculés par Angular et le composant XPath complet."""
    component = page.locator(f"xpath={DETAIL_XPATH}").first
    metadata = page.locator("apec-offre-metadata").first
    details = component.locator(".col-lg-4 .details-post").evaluate_all(
        """nodes => nodes.map(node => ({
            label: node.querySelector('h4')?.textContent?.trim() || '',
            value: node.querySelector('span')?.textContent?.trim() || ''
        }))"""
    )
    detail_fields = {
        DETAIL_FIELD_NAMES.get(item["label"], item["label"]): item["value"]
        for item in details
        if item["label"]
    }
    metadata_items = [
        re.sub(r"\s+", " ", value).strip()
        for value in metadata.locator("ul.details-offer-list > li").all_inner_texts()
    ]
    date_lines = [
        re.sub(r"\s+", " ", value).strip()
        for value in metadata.locator(".date-offre").all_inner_texts()
    ]
    apply_link = component.locator("a", has_text="Postuler").last
    apply_href = apply_link.get_attribute("href") if apply_link.count() else ""
    return {
        "xpath": DETAIL_XPATH,
        "page_title": page.title(),
        "heading": page.locator("main h1").first.inner_text().strip(),
        "metadata_text": metadata.inner_text().strip(),
        "metadata_items": metadata_items,
        "date_lines": date_lines,
        "detail_fields": detail_fields,
        "application_url": urljoin(source_url, apply_href or ""),
        # Ces deux champs garantissent un repli auditable si l'API évolue.
        "component_text": component.inner_text().strip(),
        "component_html": component.evaluate("element => element.outerHTML"),
    }


def _group_skills(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Regroupe toutes les compétences Apec, y compris celles masquées à l'écran."""
    grouped: dict[str, list[dict[str, Any]]] = {
        "soft_skills": [],
        "hard_skills": [],
        "languages": [],
        "other": [],
    }
    names = {
        "SAVOIR_ETRE": "soft_skills",
        "SAVOIR_FAIRE": "hard_skills",
        "LANGUE": "languages",
    }
    for skill in payload.get("competences") or []:
        if not isinstance(skill, dict):
            continue
        item = {
            "label": str(skill.get("libelle") or "").strip(),
            "type": str(skill.get("type") or "").strip(),
            "level_id": skill.get("idNomNiveau"),
            "skill_id": skill.get("idNomCompetence"),
        }
        grouped[names.get(item["type"], "other")].append(item)
    return grouped


def _contract_from_metadata(items: list[str]) -> str:
    """Isole le contrat dans la ligne qui contient aussi le nombre de postes."""
    if len(items) < 2:
        return ""
    return re.sub(r"^\d+\s*", "", items[1]).strip()


def build_extraction(
    source_url: str,
    offer_number: str,
    offer_payload: dict[str, Any],
    company_payload: dict[str, Any],
    dom: dict[str, Any],
) -> dict[str, Any]:
    """Assemble un document exhaustif, normalisé et prêt pour une future ingestion."""
    description_html = str(
        offer_payload.get("texteHtml")
        or offer_payload.get("texteOffre")
        or offer_payload.get("description")
        or ""
    )
    profile_html = str(offer_payload.get("texteHtmlProfil") or "")
    company_html = str(offer_payload.get("texteHtmlEntreprise") or "")
    metadata_items = dom.get("metadata_items") or []
    locations = [
        str(item.get("libelleLieu") or "").strip()
        for item in offer_payload.get("lieux") or []
        if isinstance(item, dict) and item.get("libelleLieu")
    ]
    company_header = company_payload.get("enTete") or {}
    company_main = company_payload.get("mainSection") or {}
    company_description_html = str(company_main.get("entreprise") or "")

    normalized_offer = {
        "external_id": str(offer_payload.get("numeroOffre") or offer_number),
        "numeric_id": offer_payload.get("id"),
        "title": str(offer_payload.get("intitule") or dom.get("heading") or "").strip(),
        "company_name": str(
            offer_payload.get("enseigne")
            or offer_payload.get("nomCompteEtablissement")
            or (metadata_items[0] if metadata_items else "")
        ).strip(),
        "company_establishment_id": offer_payload.get("idEtablissement"),
        "company_reference": str(offer_payload.get("referenceClientOffre") or "").strip(),
        "locations": locations,
        "contract_type": _contract_from_metadata(metadata_items),
        "number_of_positions": offer_payload.get("nombrePostes"),
        "salary_text": str(offer_payload.get("salaireTexte") or "").strip(),
        "part_time": offer_payload.get("tempsPartiel"),
        "publication_date": offer_payload.get("datePremierePublication"),
        "updated_date": (offer_payload.get("audit") or {}).get("dateModification"),
        "application_url": dom.get("application_url") or source_url,
        "application_type": offer_payload.get("typeCandidature"),
        "latitude": offer_payload.get("latitude"),
        "longitude": offer_payload.get("longitude"),
        "detail_fields": dom.get("detail_fields") or {},
        "description": {
            "html": description_html,
            "text": html_to_text(description_html),
        },
        "candidate_profile": {
            "html": profile_html,
            "text": html_to_text(profile_html),
        },
        "company_description": {
            "html": company_html,
            "text": html_to_text(company_html),
        },
        "skills": _group_skills(offer_payload),
        "recruiter": {
            "first_name": offer_payload.get("prenomInterlocuteur"),
            "last_name": offer_payload.get("nomInterlocuteur"),
            "contact_id": offer_payload.get("idInterlocuteurDirect"),
        },
        "postal_address": offer_payload.get("adresseOffre") or {},
    }
    normalized_company = {
        "id": company_payload.get("id"),
        "account_id": company_payload.get("idCompte"),
        "name": str(
            company_header.get("raisonSociale")
            or normalized_offer["company_name"]
        ),
        "tagline": str(company_header.get("accroche") or ""),
        "title": str(company_main.get("entrepriseTitre") or ""),
        "description": {
            "html": company_description_html,
            "text": html_to_text(company_description_html),
        },
        "postal_address": company_payload.get("adressePostale") or {},
        "benefits": company_payload.get("avantages") or [],
        "sections": company_payload.get("sections") or [],
        "key_facts": company_payload.get("eltCles") or {},
    }
    return {
        "schema_version": "apec-offer-extraction-v1",
        "extracted_at": datetime.now(UTC).isoformat(),
        "source": "Apec",
        "source_url": source_url,
        "offer": normalized_offer,
        "company_profile": normalized_company,
        "dom": dom,
        # Les payloads complets assurent l'exhaustivité et la rétrocompatibilité.
        "raw": {
            "offer_api": offer_payload,
            "company_api": company_payload,
        },
    }


def extract_apec_offer(
    url: str,
    *,
    headless: bool = False,
    timeout_ms: int = 30_000,
    slow_mo_ms: int = 100,
    pause_ms: int = 1_000,
) -> dict[str, Any]:
    """Ouvre une fiche Apec et retourne son contenu complet sous forme de dictionnaire.

    Le navigateur est visible par défaut, conformément au besoin d'audit humain.
    ``headless=True`` est réservé aux futures exécutions automatisées. Aucun clic
    sur « Postuler » ni aucune écriture en base n'est effectué.
    """
    source_url = url.strip()
    offer_number = extract_offer_number(source_url)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=headless,
                slow_mo=max(0, slow_mo_ms),
            )
            context = browser.new_context(locale="fr-FR")
            page = context.new_page()
            page.set_default_timeout(timeout_ms)
            page.goto(source_url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.locator(f"xpath={DETAIL_XPATH}").first.wait_for(state="visible")

            # L'appel depuis la page réutilise la session navigateur acceptée
            # par DataDome, contrairement à une requête HTTP Python isolée.
            offer_payload = _browser_json(
                page,
                OFFER_ENDPOINT,
                f"?numeroOffre={offer_number}",
            )
            company_id = offer_payload.get("idEtablissement")
            company_payload = (
                _browser_json(page, COMPANY_ENDPOINT, str(company_id))
                if company_id
                else {}
            )
            dom = _read_dom(page, source_url)
            if pause_ms > 0:
                page.wait_for_timeout(pause_ms)
            result = build_extraction(
                source_url,
                offer_number,
                offer_payload,
                company_payload,
                dom,
            )
            context.close()
            browser.close()
            return result
    except PlaywrightTimeoutError as error:
        raise ApecExtractionError(
            "La fiche Apec ne s’est pas affichée avant l’expiration du délai."
        ) from error
    except ApecExtractionError:
        raise
    except Exception as error:
        raise ApecExtractionError(f"Extraction Apec impossible : {error}") from error
