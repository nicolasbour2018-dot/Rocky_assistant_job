"""The readers of the job alerts (E3) on real alerts, anonymised: every card of an alert, its facts as written, an
identity that is the same from one alert to the next, and never a tracking token in what is kept."""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parseaddr

import pytest

from rocky.messages.alerts.model import AlertCard, AlertMessage, Platform
from rocky.messages.alerts.rules import (
    card_key,
    card_offer,
    cards,
    merged,
    message_link,
    reader_of,
)
from rocky.offres.sources.model import CollectedOffer, SourceCode
from tests.messages.fakes import recorded_alert


def alert(name: str) -> AlertMessage:
    data = recorded_alert(name)
    return AlertMessage(
        id=1,
        received_at=datetime.fromisoformat(data["received_at"]),
        mailbox_address="camille@example.com",
        gmail_id="18f0a1b2c3d4e5f6",
        sender_address=parseaddr(data["sender"])[1].lower(),
        subject=data["subject"],
        body_text=data["body_text"],
        body_html=data["body_html"],
    )


def read(name: str) -> list[AlertCard]:
    message = alert(name)
    platform = reader_of(message)
    assert platform is not None
    return cards(message, platform)


@pytest.mark.parametrize(
    ("name", "platform", "count"),
    [
        ("hellowork_notification", Platform.HELLOWORK, 20),
        ("hellowork_alerte", Platform.HELLOWORK, 4),
        ("hellowork_recommandation", Platform.HELLOWORK, 1),
        ("cadremploi_nouvelles", Platform.CADREMPLOI, 5),
        ("cadremploi_profil", Platform.CADREMPLOI, 1),
        ("efc_selection", Platform.EFINANCIALCAREERS, 20),
        ("efc_opportunites", Platform.EFINANCIALCAREERS, 10),
        ("efc_recommandee", Platform.EFINANCIALCAREERS, 1),
        ("linkedin_alerte", Platform.LINKEDIN, 6),
        ("linkedin_relais", Platform.LINKEDIN, 4),
    ],
)
def test_every_card_of_an_alert_is_read(
    name: str, platform: Platform, count: int
) -> None:
    message = alert(name)

    found = cards(message, platform)

    assert reader_of(message) is platform
    assert len(found) == count
    assert [card.position for card in found] == list(range(1, count + 1))
    assert all(card.title and card.link for card in found)


def test_a_hellowork_card_gives_its_employer_place_contract_and_salary() -> None:
    first = read("hellowork_notification")[0]

    assert first == AlertCard(
        position=1,
        title="Data Scientist IA H/F",
        company="HOUSE OF ABY",
        location="Paris 8e - 75",
        contract="CDI",
        salary_text="45 000 € / an",
        link="https://emails.hellowork.com/clic/0003",
    )


def test_a_hellowork_card_without_employer_keeps_its_place() -> None:
    html = (
        '<table><tr><td><a href="https://emails.hellowork.com/clic/1">Business Analyst H/F</a>'
        '<a href="#">Champs-sur-Marne - 77</a><a href="#">CDI</a></td></tr>'
        '<tr><td><a href="https://emails.hellowork.com/clic/2">Voir l’offre</a></td></tr></table>'
    )
    message = AlertMessage(
        1, datetime(2026, 10, 5, tzinfo=UTC), "c@example.com", "g", None, "", "", html
    )

    (card,) = cards(message, Platform.HELLOWORK)

    assert (card.company, card.location, card.contract) == (
        None,
        "Champs-sur-Marne - 77",
        "CDI",
    )


def test_a_cadremploi_card_splits_employer_place_and_contract() -> None:
    first = read("cadremploi_nouvelles")[0]

    assert (first.title, first.company, first.location, first.contract) == (
        "DEVELOPPEUR BACKEND JAVA KAFKA SENIOR (H/F)",
        "Free-Work",
        "Paris",
        "CDI",
    )


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # Employer and place on their own lines, salary in the next paragraph.
        (
            "efc_selection",
            (
                "Stage Chargé(e) de Recrutement",
                "Bretteville Consulting",
                "Neuilly-sur-Seine, France",
                None,
                None,
                "Selon le profil",
                "24463078",
            ),
        ),
        # « Employeur, lieu », then contract and salary.
        (
            "efc_opportunites",
            (
                "Consultant scientifique en financement de l'innovation mécanique junior F/H",
                "Deloitte",
                "Paris, France",
                "CDI",
                None,
                "Competitive",
                "24742336",
            ),
        ),
        # « Intitulé | employeur », then remote work, contract and salary.
        (
            "efc_recommandee",
            (
                "Apprenti.e chargé.e de reporting comptable F/H",
                "Caisse des Dépôts et Consignations",
                "Paris, France",
                "Intérim",
                "Hybride",
                "Competitive",
                "24557294",
            ),
        ),
    ],
    ids=["selection", "opportunites", "recommandee"],
)
def test_the_three_forms_of_efinancialcareers(
    name: str, expected: tuple[str | None, ...]
) -> None:
    first = read(name)[0]

    assert (
        first.title,
        first.company,
        first.location,
        first.contract,
        first.remote,
        first.salary_text,
        first.platform_id,
    ) == expected


def test_a_linkedin_card_keeps_the_public_posting_without_tracking() -> None:
    found = read("linkedin_relais")

    assert found[0] == AlertCard(
        position=1,
        title="Data Analyst Full Remote (France entière)",
        company="AVELSEN",
        location="France",
        remote="À distance",
        link="https://www.linkedin.com/jobs/view/4463227701/",
        platform_id="4463227701",
    )
    assert all("tracking" not in (card.link or "") for card in found)


def test_no_tracking_token_is_kept_in_the_link_of_a_card() -> None:
    links = [card.link or "" for card in read("efc_selection")]

    assert all("?" not in link for link in links)
    assert links[0].endswith(".id24463078")


def test_an_alert_of_an_unknown_sender_has_no_reader() -> None:
    message = AlertMessage(
        1,
        datetime(2026, 10, 5, tzinfo=UTC),
        "c@example.com",
        "g",
        "mailer@jobleads.com",
        "Il y a 3 nouvelles offres",
        "",
        "",
    )

    assert reader_of(message) is None


# The identity of a card: the same posting in two alerts is the same offer.


def test_the_key_of_a_card_ignores_its_link_and_the_writing() -> None:
    card = AlertCard(1, "Data Analyst H/F", "Marvesting", "Levallois-Perret - 92")
    again = AlertCard(
        7,
        "DATA ANALYST H/F",
        "marvesting",
        "Levallois-Perret - 92",
        link="https://emails.hellowork.com/clic/9",
    )
    elsewhere = AlertCard(1, "Data Analyst H/F", "Marvesting", "Montrouge - 92")

    assert card_key(card) == card_key(again)
    assert card_key(card) != card_key(elsewhere)


def test_the_offer_of_a_card_has_its_facts_and_no_description() -> None:
    message = alert("linkedin_relais")
    card = cards(message, Platform.LINKEDIN)[0]

    offer = card_offer(message, card, Platform.LINKEDIN, reason="Fiche non lue.")

    assert offer == CollectedOffer(
        source=SourceCode.LINKEDIN.value,
        external_id="4463227701",
        url="https://www.linkedin.com/jobs/view/4463227701/",
        title="Data Analyst Full Remote (France entière)",
        description="",
        description_complete=False,
        incomplete_reason="Fiche non lue.",
        company="AVELSEN",
        location="France",
        remote="À distance",
    )


def test_a_card_without_number_is_known_by_its_key_and_without_link_by_the_alert() -> (
    None
):
    message = alert("hellowork_alerte")
    card = AlertCard(1, "Data Analyst H/F", "Marvesting", "Levallois-Perret - 92")
    other = AlertCard(2, "Data Engineer H/F", "Marvesting", "Levallois-Perret - 92")

    offer = card_offer(message, card, Platform.HELLOWORK, reason="r")
    other_offer = card_offer(message, other, Platform.HELLOWORK, reason="r")

    assert (offer.source, offer.external_id) == ("hellowork.com", card_key(card))
    assert offer.url == message_link(message, card_key(card))
    assert offer.url.startswith("https://mail.google.com/mail/u/camille%40example.com/")
    assert offer.url.endswith(f"#all/{message.gmail_id}")
    # H3: the address of each card is its own, or two cards of an alert would be one offer (same address).
    assert other_offer.url != offer.url


def test_the_posting_completes_the_card_and_gives_its_address() -> None:
    message = alert("hellowork_alerte")
    card = cards(message, Platform.HELLOWORK)[0]
    offer = card_offer(message, card, Platform.HELLOWORK, reason="r")
    page = CollectedOffer(
        source="hellowork.com",
        external_id="https://www.hellowork.com/fr-fr/emplois/1.html",
        url="https://www.hellowork.com/fr-fr/emplois/1.html",
        title="Data Analyst (H/F)",
        description="Nous recherchons un Data Analyst…" * 20,
        description_complete=True,
        company="Autre nom",
        salary_text="40 000 €",
    )

    result = merged(offer, page)

    assert (result.source, result.external_id) == (offer.source, offer.external_id)
    assert result.url == page.url
    assert result.description_complete and result.incomplete_reason is None
    assert (result.title, result.company) == (offer.title, offer.company)
    assert result.salary_text == "40 000 €"


def test_an_excerpt_of_the_posting_is_kept_for_a_card_without_description() -> None:
    message = alert("hellowork_alerte")
    card = cards(message, Platform.HELLOWORK)[0]
    offer = card_offer(message, card, Platform.HELLOWORK, reason="r")
    page = CollectedOffer(
        source="hellowork.com",
        external_id="https://www.hellowork.com/fr-fr/emplois/2.html",
        url="https://www.hellowork.com/fr-fr/emplois/2.html",
        title="Data Analyst (H/F)",
        description="Rejoignez notre équipe data pour…",
        description_complete=False,
        incomplete_reason="La page ne donne qu'un extrait de l'annonce.",
    )

    result = merged(offer, page)

    assert (result.description, result.description_complete) == (
        "Rejoignez notre équipe data pour…",
        False,
    )
    assert result.incomplete_reason == "La page ne donne qu'un extrait de l'annonce."
