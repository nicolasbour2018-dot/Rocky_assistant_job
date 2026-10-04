"""The rules of the classification (E2), without database: senders, platforms, employers, sentences, signals, levels.

The cases of the exit criterion and of the old Rocky's mistakes are here with the messages of the archive A1 they come
from (anonymised): a Quora digest never goes to « French bee », a refusal from METRO never to « Ministère de la
justice », Google Agenda never to « Choisir le Service Public ».
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from rocky.candidatures.model import MailTarget, Stage
from rocky.messages.classification.model import (
    Category,
    Context,
    Level,
    MailToClassify,
    Pending,
    Tier,
    Verdict,
)
from rocky.messages.classification.rules import (
    classify,
    employer_domains,
    name_forms,
    readable,
    registrable,
    title_form,
)
from rocky.offres.decisions import Author

RECEIVED = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)


def mail(
    sender: str,
    subject: str,
    body: str = "",
    *,
    id_: int = 1,
    thread: str = "t1",
    mailbox: int = 1,
) -> MailToClassify:
    address = sender.rsplit("<", 1)[-1].rstrip(">").strip().lower()
    return MailToClassify(
        id=id_,
        mailbox_id=mailbox,
        thread_id=thread,
        received_at=RECEIVED,
        sender=sender,
        sender_address=address if "@" in address else None,
        subject=subject,
        body_text=body,
    )


def target(
    application_id: int,
    company: str,
    title: str = "Data Analyst H/F",
    *,
    domain: str | None = None,
    links: tuple[str, ...] = ("https://www.linkedin.com/jobs/view/1",),
) -> MailTarget:
    return MailTarget(
        application_id=application_id,
        company=company,
        title=title,
        stage=Stage.SENT,
        sent_on=date(2026, 9, 20),
        employer_domain=domain,
        links=links,
    )


def decided(found: Verdict | Pending) -> Verdict:
    assert isinstance(found, Verdict), found
    assert found.proofs and all(p.rule and p.excerpt and p.reason for p in found.proofs)
    return found


# Exit criterion and the old Rocky's mistakes (archive A1, ids 800, 144, 710, 747).


def test_the_quora_digest_is_never_attached_to_french_bee() -> None:
    found = decided(
        classify(
            mail(
                '"Sélection Quora" <french-personalized-digest@quora.com>',
                "Pourquoi Marine Le Pen ne sera jamais présidente de la France ?",
                "Franchement la question ne se pose même pas…",
            ),
            Context((target(36, "French bee", "Data Analyst - Data Steward H/F"),)),
        )
    )

    assert found.category is Category.UNRELATED
    assert found.application_id is None
    assert found.level is Level.HIGH
    assert found.proofs[0].tier is Tier.SENDER


def test_a_refusal_from_metro_is_not_attached_to_the_ministry_of_justice() -> None:
    found = decided(
        classify(
            mail(
                '"Équipe de recrutement de METRO France" <notifications@talent.metro.de>',
                "Retour concernant votre candidature",
                "Cher / Chère CAMILLE, Nous tenons à vous remercier d'avoir postulé à cette offre. "
                "Malheureusement votre profil ne correspond pas à nos besoins actuels.",
            ),
            Context((target(17, "Ministère de la justice"),)),
        )
    )

    assert found.category is Category.REJECTION
    assert found.application_id is None
    assert "Malheureusement votre profil ne" in found.proofs[0].excerpt


def test_a_calendar_notice_is_not_attached_to_choisir_le_service_public() -> None:
    found = decided(
        classify(
            mail(
                "Google Agenda <calendar-notification@google.com>",
                "Aucun événement planifié aujourd'hui.",
                "Google Agenda camille martin, vous n'avez aucun événement prévu aujourd'hui.",
            ),
            Context((target(41, "Choisir le Service Public"),)),
        )
    )

    assert (found.category, found.application_id) == (Category.UNRELATED, None)


def test_a_linkedin_alert_is_an_alert_whatever_the_names_in_it() -> None:
    found = decided(
        classify(
            mail(
                "Alertes LinkedIn Jobs <jobalerts-noreply@linkedin.com>",
                "Professeur anglais (H/F) chez OneSchool Global",
            ),
            Context((target(50, "Liberty Global", "Data Scientist"),)),
        )
    )

    assert (found.category, found.application_id, found.level) == (
        Category.JOB_ALERT,
        None,
        Level.HIGH,
    )


@pytest.mark.parametrize(
    ("sender", "subject", "body"),
    [
        (
            "GitHub <noreply@github.com>",
            "[GitHub] A third-party OAuth application has been added",
            "Hey camille! A third-party OAuth application was recently authorized.",
        ),
        (
            "Tony Dog <bonjour@tonydog.fr>",
            "Nouveau : les friandises de saison sont arrivées",
            "Découvrez notre sélection d'automne pour votre chien.",
        ),
        (
            "france.tv <newsletter@info.france.tv>",
            "Ce soir sur France 2 : votre série préférée",
            "Ne manquez pas le nouvel épisode.",
        ),
    ],
    ids=["github", "tony-dog", "france-tv"],
)
def test_the_noise_of_the_e1_acceptance_is_out_of_the_search(
    sender: str, subject: str, body: str
) -> None:
    found = decided(
        classify(mail(sender, subject, body), Context((target(1, "Exemple"),)))
    )

    assert (found.category, found.application_id) == (Category.UNRELATED, None)


def test_without_any_sign_of_the_search_the_rules_say_so() -> None:
    found = decided(
        classify(
            mail(
                "OVHcloud <support@services.ovhcloud.com>", "Une facture est disponible"
            ),
            Context(),
        )
    )

    assert found.category is Category.UNRELATED
    assert found.level is Level.MEDIUM  # deduced from an absence
    assert found.proofs[0].rule == "signal.none"
    assert found.author is Author.RULE


# Employers and applications (Q3, Q9, Q11).


def test_an_ats_refusal_naming_the_employer_and_the_offer_is_attached() -> None:
    found = decided(
        classify(
            mail(
                "ATHEIA <r-c-0000-0000@reply.hellowork.com>",
                "Votre candidature de Data Analyst / Scientist n'est pas retenue",
                "Notre équipe a étudié la vôtre pour être Data Analyst / Scientist. "
                "Votre candidature ne convient pas pour ce poste.",
            ),
            Context(
                (
                    target(45, "ATHEIA", "Data Analyst / Scientist"),
                    target(36, "French bee"),
                )
            ),
        )
    )

    assert (found.category, found.application_id, found.level) == (
        Category.REJECTION,
        45,
        Level.MEDIUM,
    )
    assert {p.rule for p in found.proofs} >= {"employer.name", "offer.title"}


def test_the_exact_domain_and_the_offer_give_a_high_level() -> None:
    found = decided(
        classify(
            mail(
                "Recrutement <talents@recrutement.exemple-conseil.fr>",
                "Votre candidature au poste de Data Analyst",
                "Nous avons bien reçu votre candidature au poste de Data Analyst.",
            ),
            Context((target(7, "Exemple Conseil", domain="exemple-conseil.fr"),)),
        )
    )

    assert (found.category, found.application_id, found.level) == (
        Category.ACKNOWLEDGEMENT,
        7,
        Level.HIGH,
    )
    assert found.proofs[-2].tier is Tier.DOMAIN


def test_the_employer_without_its_offer_is_attached_to_check() -> None:
    """Talan (archive 418): the only application at Talan is another post than the one of the message."""
    found = decided(
        classify(
            mail(
                "Talan <notification@smartrecruiters.talan.com>",
                "Votre candidature chez Talan - Lead Data Engineer Snowflake H/F - CDI",
                "Nous avons bien reçu votre candidature.",
            ),
            Context((target(47, "Talan", "Prompt Engineer - Vibe Coder Junior H/F"),)),
        )
    )

    assert (found.category, found.application_id, found.level) == (
        Category.ACKNOWLEDGEMENT,
        47,
        Level.LOW,
    )
    assert found.proofs[-1].rule == "offer.title_missing"


def test_a_word_of_the_name_is_never_enough() -> None:
    """« Choisir le Service Public », « La banque Postale »: their words are everywhere."""
    found = classify(
        mail(
            "CASDEN Banque Populaire <info@email.casden.banquepopulaire.fr>",
            "Participez à l'évènement Futurapolis : le service de la banque",
            "Nous avons le plaisir de vous inviter.",
        ),
        Context(
            (target(41, "Choisir le Service Public"), target(26, "La banque Postale"))
        ),
    )

    assert decided(found).application_id is None


def test_the_thread_of_an_attached_message_gives_its_application() -> None:
    found = decided(
        classify(
            mail(
                "Jeanne Martin <jeanne@gmail.com>",
                "Re: entretien",
                "Je vous propose un échange téléphonique jeudi.",
                thread="t9",
            ),
            Context((target(12, "Exemple Conseil"),), {(1, "t9"): 12}),
        )
    )

    assert (found.category, found.application_id, found.level) == (
        Category.INTERVIEW,
        12,
        Level.HIGH,
    )


def test_two_applications_at_one_employer_the_offer_decides() -> None:
    context = Context(
        (
            target(23, "Groupe Qair", "Data Scientist – Power Markets M/F – Paris"),
            target(43, "Groupe Qair", "Data Analyst – Power Markets M/F – Paris"),
        )
    )
    named = classify(
        mail(
            "Groupe Qair <jobs@qair.energy>",
            "Votre candidature",
            "Merci pour votre candidature au poste de Data Analyst – Power Markets.",
        ),
        context,
    )
    unnamed = classify(
        mail(
            "LinkedIn <jobs-noreply@linkedin.com>",
            "Camille, votre candidature a été envoyée à Groupe Qair",
        ),
        context,
    )

    assert decided(named).application_id == 43
    assert isinstance(unnamed, Pending)  # never chosen at random (Q11)
    assert {t.application_id for t in unnamed.candidates} == {23, 43}
    assert unnamed.category is Category.ACKNOWLEDGEMENT


def test_contradictory_sentences_go_to_the_model() -> None:
    found = classify(
        mail(
            "Recrutement <rh@exemple.fr>",
            "Votre candidature",
            "Nous souhaitons vous proposer un entretien. Nous ne donnerons pas suite à l'autre poste.",
        ),
        Context(),
    )

    assert isinstance(found, Pending)
    assert found.category is None
    assert {p.rule for p in found.findings} >= {"phrase.rejection", "phrase.interview"}


def test_a_sign_without_a_sentence_goes_to_the_model() -> None:
    found = classify(
        mail(
            "Thales Group <recruiting@jobalerts.thalesgroup.com>",
            "Thales - Application Update",
            "Hello Camille, I wanted to provide you with another quick update regarding your application.",
        ),
        Context((target(7, "Thales", "Data analyst F/H"),)),
    )

    assert isinstance(found, Pending)
    assert found.attached == 7 and found.attached_level is Level.LOW
    assert "signal.employer" in {p.rule for p in found.findings}


def test_an_acknowledgement_inside_a_refusal_is_courtesy() -> None:
    found = decided(
        classify(
            mail(
                "COVEA <notification@recrutement.covea.fr>",
                "Data scientist F/H - COVEA : Votre candidature",
                "Nous avons bien reçu votre candidature au poste de Data scientist F/H. Après étude, nous ne "
                "pouvons pas donner une suite favorable.",
            ),
            Context((target(39, "Covéa", "Data scientist F/H"),)),
        )
    )

    assert (found.category, found.application_id) == (Category.REJECTION, 39)


# Platforms (Q16).


def test_a_platform_names_the_employer_in_its_subject() -> None:
    found = decided(
        classify(
            mail(
                "LinkedIn <jobs-noreply@linkedin.com>",
                "Camille, votre candidature a été envoyée à Sequantis",
            ),
            Context((target(30, "Sequantis", "Data scientist junior"),)),
        )
    )

    assert (found.category, found.application_id) == (Category.ACKNOWLEDGEMENT, 30)
    assert Tier.PLATFORM in {proof.tier for proof in found.proofs}


def test_a_platform_shows_its_own_name_not_the_employers() -> None:
    """Hellowork (archive 517): an offer of « Hellowork » itself never takes the platform's notices."""
    found = decided(
        classify(
            mail(
                "Hellowork <emploi@emails.hellowork.com>",
                "Vous avez reçu des réponses négatives de plusieurs recruteurs",
            ),
            Context((target(3, "Hellowork", "Ingénieur Robotique F/H"),)),
        )
    )

    assert (found.category, found.application_id) == (Category.REJECTION, None)


@pytest.mark.parametrize(
    ("sender", "subject", "category"),
    [
        (
            "Alerte Emploi Meteojob <ne-pas-repondre@meteojob.com>",
            "Comptalents recrute un Office Manager H/F",
            Category.JOB_ALERT,
        ),
        (
            "Hellowork Candidature <contact@emails.hellowork.com>",
            "544765, votre code de vérification est disponible",
            Category.UNRELATED,
        ),
        (
            "LinkedIn <jobs-noreply@linkedin.com>",
            "Nouvelles offres d’emploi similaires à Chef de projet Data",
            Category.JOB_ALERT,
        ),
        (
            "LinkedIn <invitations@linkedin.com>",
            "Je souhaite que nous nous connections",
            Category.UNRELATED,
        ),
    ],
    ids=[
        "meteojob-hiring",
        "hellowork-code",
        "linkedin-similar",
        "linkedin-invitation",
    ],
)
def test_the_platforms_own_notices(
    sender: str, subject: str, category: Category
) -> None:
    found = decided(classify(mail(sender, subject), Context((target(1, "Exemple"),))))

    assert (found.category, found.level) == (category, Level.HIGH)


def test_an_alert_subject_from_another_sender_is_an_alert_of_medium_level() -> None:
    found = decided(
        classify(
            mail(
                "eFinancialCareers <offres@efinancial.example>",
                "Les dernières opportunités correspondant à votre profil",
            ),
            Context(),
        )
    )

    assert (found.category, found.level) == (Category.JOB_ALERT, Level.MEDIUM)


# Forms compared.


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("talent.metro.de", "metro.de"),
        ("METRO.DE", "metro.de"),
        ("applications.finances.gouv.fr", "finances.gouv.fr"),
        ("mail.exemple.co.uk", "exemple.co.uk"),
        ("covea.fr", "covea.fr"),
    ],
)
def test_the_registrable_domain(host: str, expected: str) -> None:
    assert registrable(host) == expected


def test_the_employer_domains_skip_job_boards_and_ats() -> None:
    found = target(
        1,
        "Natixis",
        domain="RH.natixis.com",
        links=(
            "https://recrutement.natixis.com/job/1",
            "https://fr.linkedin.com/jobs/view/2",
            "https://emertongroup.recruitee.com/o/3",
        ),
    )

    assert employer_domains(found) == ("natixis.com",)


def test_the_forms_of_a_name_and_a_title() -> None:
    assert name_forms("emagine Consulting SARL") == (
        "emagine consulting sarl",
        "emagine consulting",
    )
    assert name_forms("U") == ()
    assert title_form("Data Analyst H/F - CDI") == "data analyst"


# Seen on Nicolas's mailbox (acceptance of E2): conditions, surveys, newsletters.


def test_a_refusal_on_a_condition_is_an_acknowledgement() -> None:
    found = decided(
        classify(
            mail(
                "Devoteam <notification@recruitment.devoteam.com>",
                "Merci d'avoir postulé au poste de DATA ANALYST GCP",
                "Merci pour votre candidature. Sans retour de notre part dans les 3 semaines suivant votre "
                "candidature, vous pourrez considérer que celle-ci n'a malheureusement pas été retenue.",
            ),
            Context(),
        )
    )

    assert found.category is Category.ACKNOWLEDGEMENT


def test_a_platforms_survey_is_not_the_employers_decision() -> None:
    found = decided(
        classify(
            mail(
                "Hellowork <emploi@emails.hellowork.com>",
                "L'offre de Data Analyst H/F n'est plus disponible",
                "Avez-vous eu une réponse ? Oui, j'ai un entretien. Non, ma candidature n'a pas été retenue.",
            ),
            Context((target(8, "Exemple", "Data Analyst H/F"),)),
        )
    )

    # A title of two words names no application by itself.
    assert (found.category, found.application_id) == (Category.EMPLOYER_UPDATE, None)


def test_a_platforms_thread_lends_no_application() -> None:
    found = decided(
        classify(
            mail(
                "Hellowork <emploi@emails.hellowork.com>",
                "L'offre de Data Analyst Financier H/F n'est plus disponible",
                thread="t3",
            ),
            Context((target(8, "Exemple"),), {(1, "t3"): 8}),
        )
    )

    assert found.application_id is None


def test_a_text_part_written_with_html_entities_is_read_decoded() -> None:
    """Talan, Sopra Steria (acceptance of E2): « Nous avons bien re&ccedil;u votre candidature »."""
    found = decided(
        classify(
            mail(
                "Talan <notifications@smartrecruiters.talan.com>",
                "Votre candidature chez Coexya",
                readable(
                    "Nous avons bien re&ccedil;u votre candidature et vous remercions."
                ),
            ),
            Context(),
        )
    )

    assert found.category is Category.ACKNOWLEDGEMENT
    assert "bien reçu votre candidature" in found.proofs[0].excerpt
