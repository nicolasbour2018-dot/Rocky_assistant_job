"""What the assistant 🐾 knows of an offer (decision G4, Q11): the facts of its card, each with an id it cites.

The card is built as the screens build it (``offer_card``): the same score, the same reasons; the summary only when
it was already asked (never generated for the assistant). Only this offer is read, never the list. The description is
cut first when the facts are too long.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from sqlalchemy import Engine

from rocky.offres.analysis.model import IMPORTANCE_LABELS
from rocky.offres.analysis.rules import analyze
from rocky.offres.decisions import DECISION_LABELS, effective_decisions, reason_label
from rocky.offres.rules import scoring_inputs
from rocky.offres.scoring.model import COMPONENT_LABELS, CONFIDENCE_LABELS
from rocky.offres.screen import OfferCard, offer_card
from rocky.offres.sql import SqlStore
from rocky.offres.usecases import stored_summary
from rocky.profil.api import stored_profile
from rocky.system.assistant.model import Fact, FactSheet, SubjectKind
from rocky.system.assistant.registry import add_facts
from rocky.system.auth.model import Account
from rocky.system.clock import today_of

SUGGESTIONS = (
    "Pourquoi ce score ?",
    "Qu'est-ce qui me manque pour ce poste ?",
    "Je postule ou pas ?",
)


def install(app: FastAPI) -> None:
    add_facts(app, SubjectKind.OFFER, _sheet)


def _sheet(request: Request, account: Account, offer_id: int) -> FactSheet | None:
    """The offer of the account, None for an unknown one or another account's."""
    engine: Engine = request.app.state.engine
    today = today_of(request)
    with engine.connect() as connection:
        store = SqlStore(connection)
        stored = store.offer_of(account.id, offer_id)
        score = None if stored is None else store.current_score(offer_id)
        profile = stored_profile(connection, account.id)
        if stored is None or score is None or profile is None:
            return None
        linked = store.track_ids(offer_id)
        summary = stored_summary(store, stored)
        decision = effective_decisions(store.decision_rows(account.id, offer_id)).get(
            offer_id
        )
    inputs = scoring_inputs(profile)
    card = offer_card(
        stored,
        score=score,
        analysis=analyze(stored.offer, inputs.skills, today=today),
        profile=inputs.profile,
        track_names={track.id: track.name for track in profile.tracks},
        linked=linked,
        same_posting=(),
        decision=decision,
        summary=summary,
        today=today,
    )
    return offer_sheet(card)


def offer_sheet(card: OfferCard) -> FactSheet:
    """The facts of ``card``, pure."""
    offer = card.stored.offer
    link = f"/offres/{card.id}/fiche"
    facts = [Fact("offre.intitule", "Intitulé", offer.title, link)]
    for fact_id, label, value in (
        ("offre.entreprise", "Entreprise", offer.company),
        ("offre.lieu", "Lieu", offer.location),
        ("offre.contrat", "Contrat", offer.contract),
        ("offre.teletravail", "Télétravail", offer.remote),
        ("offre.salaire", "Salaire", offer.salary_text),
        (
            "offre.publication",
            "Publiée le",
            None if offer.published_on is None else f"{offer.published_on:%d/%m/%Y}",
        ),
    ):
        if value:
            facts.append(Fact(fact_id, label, value, link))
    deadline = card.analysis.deadline or offer.deadline
    if deadline is not None:
        passed = " (passée)" if card.deadline_passed else ""
        facts.append(
            Fact(
                "offre.date_limite", "Date limite", f"{deadline:%d/%m/%Y}{passed}", link
            )
        )
    if card.tracks:
        facts.append(Fact("offre.pistes", "Pistes", ", ".join(card.tracks), link))
    facts += _score_facts(card, link)
    if card.skills:
        facts.append(
            Fact(
                "offre.competences",
                "Tes compétences citées par l'annonce",
                " ; ".join(
                    f"{line.match.skill} ({IMPORTANCE_LABELS[line.match.importance].lower()}"
                    f"{', prouvée par ton parcours' if line.proven else ''})"
                    for line in card.skills
                ),
                link,
            )
        )
    if card.analysis.requirements:
        facts.append(
            Fact(
                "offre.exigences",
                "Exigences hors de tes compétences",
                " ; ".join(card.analysis.requirements),
                link,
            )
        )
    if card.decision is not None and card.decision.decision is not None:
        decision = card.decision.decision
        reasons = ", ".join(
            reason_label(decision.value, code) for code in decision.reasons
        )
        text = (
            f"{DECISION_LABELS[decision.value]} le {card.decision.decided_at:%d/%m/%Y}"
        )
        if reasons:
            text += f" : {reasons}"
        if decision.note:
            text += f" ({decision.note})"
        facts.append(Fact("offre.decision", "Ta décision", text, link))
    if card.summary is not None:
        facts.append(
            Fact(
                "offre.resume",
                "Résumé de l'annonce",
                " ".join(f"{label} : {text}" for label, text in card.summary.bullets),
                link,
            )
        )
    if offer.description:
        facts.append(
            Fact(
                "offre.description", "Annonce", offer.description, link, cut_first=True
            )
        )
    title = offer.title if not offer.company else f"{offer.title} chez {offer.company}"
    return FactSheet(title, tuple(facts), link, SUGGESTIONS)


def _score_facts(card: OfferCard, link: str) -> list[Fact]:
    shown = card.shown
    track = f" pour la piste « {shown.track_name} »" if shown.track_name else ""
    text = f"{shown.display} sur 100{track} ; {CONFIDENCE_LABELS[shown.confidence.level].lower()}"
    if shown.confidence.reasons:
        text += f" ({', '.join(shown.confidence.reasons)})"
    if shown.caps:
        text += " ; plafonné : " + ", ".join(cap.label for cap in shown.caps)
    facts = [Fact("offre.score", "Score", text, link)]
    for component in shown.components:
        if component.neutral:
            value = "sans objet"
        elif component.value is None:
            value = "l'annonce n'en dit rien"
        else:
            value = f"{round(component.value * 100)} %"
        detail = f"{value} (poids {component.weight:g}) : {component.detail}"
        if component.evidence:
            detail += f" — « {' » ; « '.join(component.evidence)} »"
        facts.append(
            Fact(
                f"offre.score.{component.code}",
                f"Score, {COMPONENT_LABELS[component.code].lower()}",
                detail,
                link,
            )
        )
    if shown.gaps:
        facts.append(
            Fact("offre.manques", "Ce qui manque", " ; ".join(shown.gaps), link)
        )
    return facts
