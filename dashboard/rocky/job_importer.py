"""Import d'une annonce à partir d'une URL publique."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from datetime import date
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from .errors import ImportError
from .llm import RockyLLM
from .models import JobOffer
from .text_utils import canonical_url


MAX_HTML_BYTES = 3_000_000
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 RockyJobAssistant/1.0"
)


@dataclass
class ImportPreview:
    offer: JobOffer
    extraction_method: str
    warnings: list[str]
    raw_text: str


@dataclass
class DescriptionHydration:
    """Résultat explicite de la lecture de la page détaillée d'une annonce."""

    offer: JobOffer
    is_complete: bool
    method: str = ""
    warning: str = ""


DETAIL_DESCRIPTION_SELECTORS = (
    "#jobDescriptionText",  # Indeed
    ".show-more-less-html__markup",  # LinkedIn
    ".description__text",  # LinkedIn, ancienne page publique
    "[data-testid='job-section-description']",  # WTTJ
    "[data-testid='job-description']",
    "[data-test='JobDescription']",  # Wellfound
    "[class*='job-description']",
)


def _validate_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ImportError("L'URL doit commencer par http:// ou https://.")
    return canonical_url(url)


def fetch_html(url: str, timeout: int = 15) -> tuple[str, str]:
    safe_url = _validate_url(url)
    try:
        response = requests.get(
            safe_url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
            },
            timeout=timeout,
            allow_redirects=True,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        raise ImportError(
            "La page refuse l'accès ou ne répond pas. "
            "Tu peux coller le texte de l'annonce dans le formulaire."
        ) from error
    content_type = response.headers.get("Content-Type", "")
    if "html" not in content_type.lower():
        raise ImportError("Cette URL ne renvoie pas une page HTML.")
    if len(response.content) > MAX_HTML_BYTES:
        raise ImportError("La page est trop volumineuse pour un import sûr.")
    return response.text, canonical_url(response.url)


def _json_ld_objects(value: Any):
    if isinstance(value, dict):
        if value.get("@type") == "JobPosting" or (
            isinstance(value.get("@type"), list)
            and "JobPosting" in value["@type"]
        ):
            yield value
        for child in value.values():
            yield from _json_ld_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _json_ld_objects(child)


def _plain_html(value: Any) -> str:
    if value is None:
        return ""
    return BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True)


def description_is_probably_truncated(value: Any) -> bool:
    """Détecte les aperçus coupés avant de les confondre avec une annonce.

    Plusieurs moteurs de recherche, notamment Apec, terminent leur extrait par
    ``...`` (parfois après des balises HTML). Un tel texte reste utile comme
    aperçu, mais il ne doit jamais servir au calcul du score de matching.
    """
    plain_text = _plain_html(value).rstrip()
    return bool(plain_text) and plain_text.endswith(("...", "…"))


def _targeted_description(soup: BeautifulSoup) -> str:
    """Lit uniquement les conteneurs connus pour porter l'annonce complète."""
    for selector in DETAIL_DESCRIPTION_SELECTORS:
        node = soup.select_one(selector)
        if node is None:
            continue
        description = re.sub(
            r"\s+", " ", node.get_text(" ", strip=True)
        ).strip()
        if description:
            return description
    return ""


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for key in ("value", "minValue", "maxValue"):
            result = _number(value.get(key))
            if result is not None:
                return result
    if value:
        match = re.search(r"\d[\d\s.,]*", str(value))
        if match:
            try:
                return float(
                    match.group(0).replace(" ", "").replace(",", ".")
                )
            except ValueError:
                return None
    return None


def _address(data: dict[str, Any]) -> tuple[str, str]:
    location = data.get("jobLocation")
    if isinstance(location, list):
        location = location[0] if location else {}
    if not isinstance(location, dict):
        return "", ""
    address = location.get("address", {})
    if not isinstance(address, dict):
        return "", ""
    return (
        str(address.get("addressLocality") or address.get("addressRegion") or ""),
        str(address.get("addressCountry") or ""),
    )


def _salary(data: dict[str, Any]) -> tuple[float | None, float | None, str]:
    salary = data.get("baseSalary", {})
    if not isinstance(salary, dict):
        return None, None, "EUR"
    currency = str(salary.get("currency") or "EUR")
    value = salary.get("value", {})
    if isinstance(value, dict):
        minimum = _number(value.get("minValue"))
        maximum = _number(value.get("maxValue"))
        if minimum is None and maximum is None:
            minimum = _number(value.get("value"))
            maximum = minimum
        return minimum, maximum, currency
    parsed = _number(value)
    return parsed, parsed, currency


def _source_name(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    known = {
        "linkedin": "LinkedIn",
        "indeed": "Indeed",
        "welcometothejungle": "Welcome to the Jungle",
        "francetravail": "France Travail",
        "pole-emploi": "France Travail",
        "adzuna": "Adzuna",
        "apec": "APEC",
    }
    for marker, label in known.items():
        if marker in host:
            return label
    return host.removeprefix("www.") or "URL"


def parse_html(html: str, url: str) -> ImportPreview:
    soup = BeautifulSoup(html, "html.parser")
    warnings: list[str] = []
    job_data: dict[str, Any] = {}
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            decoded = json.loads(script.string or script.get_text())
            job_data = next(_json_ld_objects(decoded), {})
        except (json.JSONDecodeError, StopIteration, TypeError):
            continue
        if job_data:
            break

    canonical_tag = soup.find("link", rel=lambda value: value and "canonical" in value)
    final_url = (
        urljoin(url, canonical_tag.get("href"))
        if canonical_tag and canonical_tag.get("href")
        else url
    )

    title_meta = soup.find("meta", property="og:title")
    description_meta = soup.find("meta", property="og:description")

    structured_description = _plain_html(job_data.get("description"))
    targeted_description = _targeted_description(soup)
    if structured_description:
        description = structured_description
        extraction_method = "JSON-LD"
        description_is_full = not description_is_probably_truncated(description)
    elif targeted_description:
        description = targeted_description
        extraction_method = "HTML ciblé"
        description_is_full = not description_is_probably_truncated(description)
    else:
        description = ""
        extraction_method = "HTML"
        description_is_full = False

    for element in soup(["script", "style", "noscript", "svg"]):
        element.decompose()
    raw_text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()

    organization = job_data.get("hiringOrganization", {})
    if not isinstance(organization, dict):
        organization = {}
    city, country = _address(job_data)
    salary_min, salary_max, currency = _salary(job_data)
    employment = job_data.get("employmentType", "")
    if isinstance(employment, list):
        employment = ", ".join(str(item) for item in employment)

    title = str(
        job_data.get("title")
        or (title_meta.get("content") if title_meta else "")
        or (soup.title.string if soup.title else "")
    ).strip()
    short_description = str(
        description_meta.get("content") if description_meta else ""
    ).strip()
    if not description:
        description = raw_text[:24000]
        warnings.append(
            "Aucune donnée JobPosting trouvée : extraction depuis le texte visible."
        )

    identifier = job_data.get("identifier", "")
    if isinstance(identifier, dict):
        identifier = identifier.get("value", "")

    offer = JobOffer(
        job_title=title,
        company_name=str(organization.get("name") or "").strip(),
        responsibilities=description,
        source_name=_source_name(final_url),
        source_url=canonical_url(final_url),
        application_url=str(job_data.get("url") or final_url),
        external_id=str(identifier or ""),
        city=city,
        country=country or "France",
        remote_policy=(
            "Télétravail"
            if job_data.get("jobLocationType") == "TELECOMMUTE"
            else ""
        ),
        contract_type=str(employment),
        work_schedule=str(employment),
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=currency,
        short_description=short_description,
        description_is_full=description_is_full,
        publication_date=job_data.get("datePosted"),
        application_deadline=job_data.get("validThrough"),
    )
    return ImportPreview(
        offer=offer,
        extraction_method=extraction_method,
        warnings=warnings,
        raw_text=raw_text,
    )


def _coerce_offer_fields(values: dict[str, Any]) -> dict[str, Any]:
    result = dict(values)
    for name in ("salary_min", "salary_max", "minimum_experience_years"):
        result[name] = _number(result.get(name))
    for name in ("publication_date", "application_deadline"):
        value = result.get(name)
        if isinstance(value, str):
            try:
                result[name] = date.fromisoformat(value[:10])
            except ValueError:
                result[name] = None
    return result


def import_job_url(url: str, llm: RockyLLM | None = None) -> ImportPreview:
    html, final_url = fetch_html(url)
    preview = parse_html(html, final_url)
    if llm and llm.is_configured:
        known = preview.offer.to_dict()
        enriched = llm.enrich_job(preview.raw_text, known)
        merged = {
            key: value
            for key, value in known.items()
            if value not in (None, "", [])
        }
        for key, value in enriched.items():
            if key in known and key not in merged and value not in (None, "", []):
                merged[key] = value
        merged.setdefault("source_name", preview.offer.source_name)
        merged.setdefault("source_url", preview.offer.source_url)
        merged.setdefault("application_url", preview.offer.application_url)
        merged.setdefault("job_title", preview.offer.job_title)
        merged.setdefault("company_name", preview.offer.company_name)
        merged.setdefault("responsibilities", preview.offer.responsibilities)
        # Mistral enrichit les champs mais ne peut pas transformer un aperçu
        # fourni par le site en description source complète.
        merged["description_is_full"] = preview.offer.description_is_full
        preview.offer = JobOffer(**_coerce_offer_fields(merged))
        preview.extraction_method += " + Mistral"
    return preview


def hydrate_job_offer(offer: JobOffer) -> DescriptionHydration:
    """Remplace un aperçu par la description issue de la page détaillée.

    Cette fonction n'appelle pas Mistral : elle récupère d'abord le texte
    source complet, qui sera ensuite utilisé par le moteur de matching. Elle
    conserve l'identité de l'annonce fournie par le connecteur de veille.
    """
    if (
        offer.description_is_full
        and offer.responsibilities.strip()
        and not description_is_probably_truncated(offer.responsibilities)
    ):
        return DescriptionHydration(
            offer=offer,
            is_complete=True,
            method="Description complète fournie par la source",
        )
    if not offer.source_url:
        return DescriptionHydration(
            offer=offer,
            is_complete=False,
            warning="Cette annonce ne fournit pas d’URL détaillée.",
        )
    host = urlsplit(offer.source_url).netloc.lower()
    if "welcometothejungle.com" in host:
        return _hydrate_wttj_offer(offer)
    if "apec.fr" in host or offer.source_name.strip().lower() == "apec":
        return _hydrate_apec_offer(offer)
    try:
        preview = import_job_url(offer.source_url)
    except ImportError as error:
        return DescriptionHydration(
            offer=offer,
            is_complete=False,
            warning=str(error),
        )
    detail = preview.offer
    if (
        not detail.description_is_full
        or not detail.responsibilities.strip()
        or description_is_probably_truncated(detail.responsibilities)
    ):
        return DescriptionHydration(
            offer=offer,
            is_complete=False,
            method=preview.extraction_method,
            warning=(
                "La plateforme n’a pas exposé de description complète "
                "identifiable sur sa page détaillée."
            ),
        )

    hydrated = replace(
        offer,
        responsibilities=detail.responsibilities.strip(),
        description_is_full=True,
        description_enrichment_source=offer.source_name,
        description_enrichment_external_id=(
            detail.external_id or offer.external_id
        ),
        short_description=(
            detail.short_description.strip() or offer.short_description
        ),
        company_name=(
            offer.company_name
            if offer.company_name not in {"", "Non précisée"}
            else detail.company_name
        ),
        city=offer.city or detail.city,
        country=offer.country or detail.country,
        remote_policy=offer.remote_policy or detail.remote_policy,
        contract_type=offer.contract_type or detail.contract_type,
        work_schedule=offer.work_schedule or detail.work_schedule,
        salary_min=offer.salary_min or detail.salary_min,
        salary_max=offer.salary_max or detail.salary_max,
        salary_currency=offer.salary_currency or detail.salary_currency,
        publication_date=offer.publication_date or detail.publication_date,
        application_deadline=(
            offer.application_deadline or detail.application_deadline
        ),
        application_url=detail.application_url or offer.application_url,
    )
    return DescriptionHydration(
        offer=hydrated,
        is_complete=True,
        method=preview.extraction_method,
    )


def _hydrate_apec_offer(offer: JobOffer) -> DescriptionHydration:
    """Lit l'endpoint de détail utilisé par la fiche officielle Apec.

    Le webservice de recherche ne renvoie qu'un extrait d'environ 280
    caractères. Le détail doit donc être demandé séparément avant tout score.
    Apec peut ponctuellement protéger cet endpoint contre les accès automatisés
    ; dans ce cas on conserve l'aperçu, explicitement marqué comme incomplet.
    """
    external_id = offer.external_id.strip()
    if not external_id:
        path_parts = [
            part for part in urlsplit(offer.source_url).path.split("/") if part
        ]
        external_id = path_parts[-1] if path_parts else ""
    if not external_id:
        return DescriptionHydration(
            offer=offer,
            is_complete=False,
            warning="L’identifiant de l’annonce Apec est absent.",
        )

    endpoint = "https://www.apec.fr/cms/webservices/offre/public"
    try:
        response = requests.get(
            endpoint,
            params={"numeroOffre": external_id},
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Accept-Language": "fr-FR,fr;q=0.9",
                "Referer": offer.source_url,
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return DescriptionHydration(
            offer=offer,
            is_complete=False,
            method="API détail Apec",
            warning=(
                "Apec n’a pas autorisé la lecture automatique du détail. "
                "Ouvre l’annonce puis colle sa description complète via "
                "« Modifier la fiche » avant de recalculer le score."
            ),
        )

    if not isinstance(payload, dict):
        payload = {}
    raw_description = str(
        payload.get("texteOffre")
        or payload.get("description")
        or payload.get("descriptif")
        or ""
    ).strip()
    if (
        not raw_description
        or description_is_probably_truncated(raw_description)
    ):
        return DescriptionHydration(
            offer=offer,
            is_complete=False,
            method="API détail Apec",
            warning="Apec n’a renvoyé qu’un aperçu incomplet de cette annonce.",
        )

    hydrated = replace(
        offer,
        responsibilities=raw_description,
        description_is_full=True,
        description_enrichment_source=offer.source_name,
        description_enrichment_external_id=external_id,
        company_name=str(
            payload.get("nomCommercial") or offer.company_name
        ).strip(),
        city=str(payload.get("lieuTexte") or offer.city).strip(),
        remote_policy=str(
            payload.get("typeTeletravail") or offer.remote_policy
        ).strip(),
        contract_type=str(
            payload.get("typeContratLibelle")
            or payload.get("typeContrat")
            or offer.contract_type
        ).strip(),
        work_schedule=str(
            payload.get("tempsTravail")
            or payload.get("dureeTravail")
            or offer.work_schedule
        ).strip(),
        application_url=str(
            payload.get("urlPostulation")
            or payload.get("urlCandidature")
            or offer.application_url
        ).strip(),
    )
    return DescriptionHydration(
        offer=hydrated,
        is_complete=True,
        method="API détail Apec",
    )


def _hydrate_wttj_offer(offer: JobOffer) -> DescriptionHydration:
    """Lit l'endpoint de détail public utilisé par les fiches WTTJ."""
    parts = [part for part in urlsplit(offer.source_url).path.split("/") if part]
    try:
        company_slug = parts[parts.index("companies") + 1]
        job_slug = parts[parts.index("jobs") + 1]
    except (ValueError, IndexError):
        return DescriptionHydration(
            offer=offer,
            is_complete=False,
            warning="L’URL Welcome to the Jungle n’est pas reconnue.",
        )
    endpoint = (
        "https://api.welcometothejungle.com/api/v1/organizations/"
        f"{quote(company_slug, safe='')}/jobs/{quote(job_slug, safe='')}"
    )
    try:
        response = requests.get(
            endpoint,
            params={"o": offer.external_id},
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Origin": "https://www.welcometothejungle.com",
                "Referer": offer.source_url,
                "wttj-user-language": "fr",
            },
            timeout=20,
        )
        response.raise_for_status()
        job = response.json().get("job", {})
    except (requests.RequestException, ValueError, AttributeError):
        return DescriptionHydration(
            offer=offer,
            is_complete=False,
            warning=(
                "Welcome to the Jungle n’a pas fourni le détail de cette annonce."
            ),
        )

    sections: list[str] = []
    section_fields = (
        ("Description du poste", job.get("description")),
        ("Profil recherché", job.get("profile")),
        ("Processus de recrutement", job.get("recruitment_process")),
    )
    for heading, raw_value in section_fields:
        content = _plain_html(raw_value)
        if content:
            sections.append(f"{heading}\n{content}")
    key_missions = [
        _plain_html(value)
        for value in job.get("key_missions", [])
        if _plain_html(value)
    ]
    if key_missions:
        sections.append("Missions clés\n" + "\n".join(key_missions))
    if not sections:
        return DescriptionHydration(
            offer=offer,
            is_complete=False,
            warning="La fiche WTTJ ne contient aucune description exploitable.",
        )

    tools = [
        str(tool.get("name") or "").strip()
        for tool in job.get("tools", [])
        if isinstance(tool, dict) and str(tool.get("name") or "").strip()
    ]
    hydrated = replace(
        offer,
        responsibilities="\n\n".join(sections),
        description_is_full=True,
        description_enrichment_source=offer.source_name,
        description_enrichment_external_id=offer.external_id,
        contract_type=str(job.get("contract_type") or offer.contract_type),
        work_schedule=str(job.get("contract_type") or offer.work_schedule),
        experience_level=str(
            job.get("experience_level") or offer.experience_level
        ),
        salary_min=job.get("salary_min") or offer.salary_min,
        salary_max=job.get("salary_max") or offer.salary_max,
        salary_currency=str(
            job.get("salary_currency") or offer.salary_currency
        ),
        application_url=str(job.get("apply_url") or offer.application_url),
        detected_skills=[*offer.detected_skills, *tools],
    )
    return DescriptionHydration(
        offer=hydrated,
        is_complete=True,
        method="API détail Welcome to the Jungle",
    )
