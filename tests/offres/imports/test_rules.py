"""Reading posting pages: the recorded pages of ``data/`` (see its README) and a few built ones."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from rocky.offres.imports.model import ImportMethod, InvalidPasteError
from rocky.offres.imports.rules import (
    EXCERPT_REASON,
    NO_CONTENT_REASON,
    VISIBLE_TEXT_REASON,
    check_link,
    enriched,
    offer_from_paste,
    parse_page,
    pasted_text,
    with_pasted_description,
)
from rocky.offres.sources.model import (
    CollectedOffer,
    InvalidLinkError,
    SourceCode,
    SourceFailedError,
)

DATA = Path(__file__).parent / "data"
TODAY = date(2026, 9, 25)
LINKEDIN = "https://fr.linkedin.com/jobs/view/data-analyst-at-plenitude-4468625023"
WTTJ = "https://www.welcometothejungle.com/fr/companies/keyrus/jobs/business-analyst-data-analyst-h-f-nb_levallois"
RECRUITEE = "https://avisia.recruitee.com/o/data-analyst-confirmee-hf-paris-5"
HELLOWORK = "https://www.hellowork.com/fr-fr/emplois/77695894.html"
HELLOWORK_SEARCH = (
    "https://www.hellowork.com/fr-fr/emploi/recherche.html?k=data+analyst&l=paris"
)
SITE = "https://jobs.site.example/offre/7"


def recorded(name: str, url: str) -> CollectedOffer:
    preview = parse_page((DATA / name).read_text(), url, today=TODAY)
    assert preview.method == ImportMethod.JSON_LD
    assert preview.warnings == ()
    return preview.offer


def page(*blocks: object, body: str = "", head: str = "") -> str:
    scripts = "".join(
        f'<script type="application/ld+json">{block if isinstance(block, str) else json.dumps(block)}</script>'
        for block in blocks
    )
    return f"<html><head>{head}{scripts}</head><body>{body}</body></html>"


def posting(**fields: object) -> dict[str, object]:
    return {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": "Data analyst",
        "description": "<p>Analyser les données.</p>",
        **fields,
    }


# Links.


@pytest.mark.parametrize(
    ("link", "reason"),
    [
        ("", "Colle le lien de l'annonce."),
        ("   ", "Colle le lien de l'annonce."),
        ("pas-une-url", "Le lien doit commencer par http:// ou https://."),
        (
            "www.hellowork.com/fr-fr/emplois/1.html",
            "Le lien doit commencer par http:// ou https://.",
        ),
        ("ftp://site.example/offre", "Le lien doit commencer par http:// ou https://."),
        ("javascript:alert(1)", "Le lien doit commencer par http:// ou https://."),
        (
            "https://moi:secret@site.example/offre",
            "Le lien ne doit contenir ni identifiant ni mot de passe.",
        ),
        ("http://localhost/offre", "Le lien n'a pas de nom de site valide."),
        ("https:///offre", "Le lien n'a pas de nom de site valide."),
        (
            "https://site.example:99999/offre",
            "Le port indiqué dans le lien est invalide.",
        ),
        (
            "http://site.example:5432/",
            "Le lien utilise un port inhabituel (5432) : Rocky ne lit que les sites web ordinaires.",
        ),
        (
            f"https://site.example/{'a' * 2048}",
            "Le lien est trop long pour être celui d'une annonce.",
        ),
    ],
)
def test_an_invalid_link_says_why(link: str, reason: str) -> None:
    with pytest.raises(InvalidLinkError) as error:
        check_link(link)

    assert error.value.reason == reason


def test_a_link_is_read_without_its_fragment() -> None:
    assert check_link("  HTTPS://Site.example/offre?id=7#postuler ") == (
        "https://Site.example/offre?id=7"
    )


# Recorded pages.


def test_linkedin_posting_decodes_its_twice_escaped_description() -> None:
    offer = recorded("linkedin/posting.html", LINKEDIN)

    assert offer.source == SourceCode.LINKEDIN
    assert offer.url == LINKEDIN
    assert offer.external_id == LINKEDIN
    assert offer.title == "Data Analyst"
    assert offer.company == "Plenitude"
    assert (offer.location, offer.country) == ("Levallois-Perret", "FR")
    assert offer.contract == "FULL_TIME"
    assert offer.sector == "Services pour les énergies renouvelables"
    assert (offer.published_on, offer.deadline) == (
        date(2026, 9, 17),
        date(2026, 10, 17),
    )
    assert offer.description.startswith(
        "Job title: DATA ANALYST\n\nLocation: Paris, France"
    )
    assert "<p>" not in offer.description
    assert "&lt;" not in offer.description
    assert offer.description_complete is True


def test_wttj_posting_reads_a_list_of_places_and_ignores_the_faq() -> None:
    offer = recorded("wttj/posting.html", WTTJ)

    assert offer.source == SourceCode.WTTJ
    assert offer.title == "Business Analyst/Data Analyst H/F/NB"
    assert offer.company == "Keyrus"
    assert (offer.location, offer.country) == ("Levallois-Perret", "FR")
    assert offer.description.startswith("Qui sommes-nous ? Une success story")


def test_a_career_site_posting_is_named_after_its_host() -> None:
    offer = recorded("avisia.recruitee.com/posting.html", RECRUITEE)

    assert offer.source == "avisia.recruitee.com"
    assert offer.company == "AVISIA"
    assert offer.location == "Paris"
    # ``baseSalary``, ``validThrough`` and ``jobLocationType`` are null on this page.
    assert (offer.salary_min, offer.deadline, offer.remote) == (None, None, None)


def test_hellowork_estimate_is_not_taken_for_the_salary() -> None:
    offer = recorded("hellowork.com/posting.html", HELLOWORK)

    assert offer.source == "hellowork.com"
    assert offer.company == "Alteca"
    assert offer.sector == "Secteur informatique, ESN"
    # ``baseSalary`` has no amount; ``estimatedSalary`` (median 50 000) is Hellowork's estimate, not the employer's.
    assert (offer.salary_min, offer.salary_max, offer.salary_currency) == (
        None,
        None,
        None,
    )


def test_a_page_without_posting_gives_its_visible_text_marked_incomplete() -> None:
    preview = parse_page(
        (DATA / "hellowork.com/page.html").read_text(), HELLOWORK_SEARCH, today=TODAY
    )
    offer = preview.offer

    assert preview.method == ImportMethod.VISIBLE_TEXT
    assert offer.title == "Recherche Offres d'emploi en France | Hellowork"
    assert offer.description_complete is False
    assert offer.incomplete_reason == VISIBLE_TEXT_REASON
    assert "data analyst • paris" in offer.description
    assert "{" not in offer.description  # no script left in the text


# Built pages.


def test_a_posting_is_found_inside_a_graph_and_with_several_types() -> None:
    html = page(
        {
            "@context": "https://schema.org",
            "@graph": [
                {"@type": "WebSite", "name": "Site"},
                posting(**{"@type": ["JobPosting", "Thing"], "title": "Analyste"}),
            ],
        }
    )

    assert parse_page(html, SITE, today=TODAY).offer.title == "Analyste"


def test_an_unreadable_block_is_ignored_and_reported() -> None:
    preview = parse_page(page("{not json", posting()), SITE, today=TODAY)

    assert preview.offer.title == "Data analyst"
    assert preview.warnings == ("Données structurées illisibles ignorées (1 bloc).",)


def test_salary_bounds_currency_and_period_come_from_base_salary() -> None:
    salary = {
        "@type": "MonetaryAmount",
        "currency": "EUR",
        "value": {
            "@type": "QuantitativeValue",
            "minValue": 45000,
            "maxValue": "55000",
            "unitText": "YEAR",
        },
    }

    offer = parse_page(page(posting(baseSalary=salary)), SITE, today=TODAY).offer

    assert (offer.salary_min, offer.salary_max) == (45000.0, 55000.0)
    assert (offer.salary_currency, offer.salary_period) == ("EUR", "YEAR")


def test_a_single_salary_value_gives_both_bounds() -> None:
    salary = {"currency": "EUR", "value": 450, "unitText": "DAY"}

    offer = parse_page(page(posting(baseSalary=salary)), SITE, today=TODAY).offer

    assert (offer.salary_min, offer.salary_max, offer.salary_period) == (
        450.0,
        450.0,
        "DAY",
    )


def test_remote_work_and_contract_stay_source_texts() -> None:
    offer = parse_page(
        page(
            posting(
                jobLocationType="TELECOMMUTE",
                employmentType=["FULL_TIME", "CONTRACTOR"],
            )
        ),
        SITE,
        today=TODAY,
    ).offer

    assert (offer.remote, offer.contract) == ("TELECOMMUTE", "FULL_TIME, CONTRACTOR")


def test_a_passed_closing_date_is_a_warning_not_a_rejection() -> None:
    preview = parse_page(page(posting(validThrough="2026-09-01")), SITE, today=TODAY)

    assert preview.offer.deadline == date(2026, 9, 1)
    assert preview.warnings == (
        "La date limite de candidature est passée (01/09/2026).",
    )


def test_a_cut_description_is_an_excerpt() -> None:
    offer = parse_page(
        page(posting(description="Nous recherchons un analyste pour…")),
        SITE,
        today=TODAY,
    ).offer

    assert offer.description_complete is False
    assert offer.incomplete_reason == EXCERPT_REASON


def test_the_canonical_link_names_the_posting() -> None:
    html = page(posting(), head='<link rel="canonical" href="/offre/7">')

    offer = parse_page(html, f"{SITE}?utm_source=alerte", today=TODAY).offer

    assert offer.url == offer.external_id == SITE


def test_without_structured_data_a_known_container_gives_the_description() -> None:
    html = page(
        head='<meta property="og:title" content="Analyste de données">',
        body=(
            "<nav>Menu</nav>"
            "<div data-testid='job-section-description'><p>Missions</p><ul><li>SQL</li></ul></div>"
        ),
    )

    preview = parse_page(html, SITE, today=TODAY)

    assert preview.method == ImportMethod.TARGETED_HTML
    assert preview.offer.title == "Analyste de données"
    assert preview.offer.description == "Missions\n\n- SQL"
    assert preview.offer.description_complete is True


def test_a_page_without_title_says_so() -> None:
    preview = parse_page(page(body="<p>Une annonce sans titre.</p>"), SITE, today=TODAY)

    assert preview.offer.title == ""
    assert preview.warnings == ("Intitulé introuvable sur la page.",)


def test_a_page_with_nothing_to_read_is_a_failure() -> None:
    html = page(body="<div id='app'></div><script>boot()</script>")

    with pytest.raises(SourceFailedError) as error:
        parse_page(html, SITE, today=TODAY)

    assert error.value.reason == NO_CONTENT_REASON


def test_a_long_visible_text_is_cut_and_reported() -> None:
    preview = parse_page(
        page(head="<title>Offre</title>", body=f"<p>{'mot ' * 6000}</p>"),
        SITE,
        today=TODAY,
    )

    assert len(preview.offer.description) == 20_000
    assert preview.warnings == ("Texte visible tronqué à 20 000 caractères.",)


# Enrichment.


def incomplete_offer(**fields: object) -> CollectedOffer:
    values: dict[str, object] = {
        "source": SourceCode.APEC,
        "external_id": "179271987W",
        "url": "https://www.apec.fr/offre/179271987W",
        "title": "Data analyst",
        "description": "Au sein de la Digital Factory…",
        "description_complete": False,
        "incomplete_reason": "Apec ne donne qu'un extrait.",
        "company": "BRAIN LOGIC",
        **fields,
    }
    return CollectedOffer(**values)  # type: ignore[arg-type]


def test_an_enrichment_takes_a_complete_description_and_fills_the_unknown_facts() -> (
    None
):
    found = parse_page(
        page(
            posting(hiringOrganization={"name": "Autre nom"}, validThrough="2026-10-30")
        ),
        SITE,
        today=TODAY,
    ).offer

    offer = enriched(incomplete_offer(), found)

    assert offer.description == "Analyser les données."
    assert (offer.description_complete, offer.incomplete_reason) == (True, None)
    assert offer.deadline == date(2026, 10, 30)
    # Identity and known facts are kept.
    assert (offer.source, offer.external_id, offer.url) == (
        SourceCode.APEC,
        "179271987W",
        "https://www.apec.fr/offre/179271987W",
    )
    assert offer.company == "BRAIN LOGIC"


def test_an_enrichment_never_replaces_a_description_by_an_incomplete_one() -> None:
    found = incomplete_offer(description="Texte visible de la page", company=None)

    offer = enriched(incomplete_offer(description="Extrait…"), found)

    assert offer.description == "Extrait…"
    assert offer.description_complete is False


# Pasted descriptions.


def test_a_pasted_text_is_normalised() -> None:
    assert pasted_text("  Missions\r\n\r\n\r\n- SQL \t et\xa0Python  \n\n") == (
        "Missions\n\n- SQL et Python"
    )


def test_a_pasted_description_completes_the_offer() -> None:
    offer = with_pasted_description(incomplete_offer(), "Toute l'annonce.")

    assert (offer.description, offer.description_complete, offer.incomplete_reason) == (
        "Toute l'annonce.",
        True,
        None,
    )


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        (" \n ", "Colle le texte de l'annonce."),
        (
            "x" * 50_001,
            "Le texte collé est trop long pour une annonce (50 000 caractères au plus).",
        ),
    ],
    ids=["blank", "too-long"],
)
def test_an_unusable_paste_says_why(value: str, reason: str) -> None:
    with pytest.raises(InvalidPasteError) as error:
        with_pasted_description(incomplete_offer(), value)

    assert str(error.value) == reason


def test_an_offer_is_made_from_its_link_and_what_the_user_copied() -> None:
    preview = offer_from_paste(
        HELLOWORK, "  Data  analyst ", "Missions : SQL.", " Alteca "
    )

    assert preview.method == ImportMethod.PASTED
    assert preview.offer.source == "hellowork.com"
    assert (preview.offer.title, preview.offer.company) == ("Data analyst", "Alteca")
    assert preview.offer.external_id == HELLOWORK
    assert preview.offer.description_complete is True


def test_an_offer_made_from_a_paste_needs_a_title() -> None:
    with pytest.raises(InvalidPasteError, match=r"Indique l'intitulé de l'annonce\."):
        offer_from_paste(HELLOWORK, " ", "Missions : SQL.")
