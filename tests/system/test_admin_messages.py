"""``rocky-admin messages``: a real collection of an account's Gmail mailboxes, written, then told;
``rocky-admin messages-classer``: their classification, told; ``rocky-admin messages-etiquettes``: the user's labels
as CSV (decision E4, Q6); ``rocky-admin alertes``: the offers of the job alerts, told (decision E3)."""

from __future__ import annotations

import csv
import io

from sqlalchemy import Engine

from rocky.messages.classification.model import CLASSIFY_VERSION, View
from rocky.messages.model import Query
from rocky.messages.service import MessagesService
from rocky.messages.usecases import connect_mailbox
from rocky.system.admin import (
    LABEL_COLUMNS,
    classify_account_messages,
    collect_messages,
    export_mail_labels,
    read_account_alerts,
)
from rocky.system.auth.sql import SqlAuthStore
from rocky.system.config import GmailSettings
from tests.messages.fakes import (
    GMAIL,
    NOW,
    FakeGmail,
    ScriptedModel,
    cipher,
    new_account,
    recorded_alert,
    store_mail,
)
from tests.offres.fakes import equip


def run(engine: Engine, email: str, settings: GmailSettings = GMAIL) -> tuple[int, str]:
    out = io.StringIO()
    service = MessagesService(
        engine, settings=settings, clock=lambda: NOW, gmail=FakeGmail()
    )
    code = collect_messages(engine, email=email, service=service, out=out)
    return code, out.getvalue()


def account_with_mailbox(engine: Engine) -> str:
    with engine.begin() as connection:
        account_id = new_account(connection)
        account = SqlAuthStore(connection).get_account(account_id)
    assert account is not None
    connect_mailbox(
        MessagesService(engine, settings=GMAIL, clock=lambda: NOW).storage,
        cipher(),
        account_id=account_id,
        address="camille.dupont@example.com",
        refresh_token="1//r",
        now=NOW,
    )
    return account.email


def test_each_mailbox_is_collected_and_told(migrated_engine: Engine) -> None:
    email = account_with_mailbox(migrated_engine)

    code, output = run(migrated_engine, email)
    again, second = run(migrated_engine, email)

    assert (code, again) == (0, 0)
    assert output == (
        "camille.dupont@example.com : collecte terminée, 3 message(s) trouvé(s), "
        "0 déjà relevé(s), 3 nouveau(x), 0 non écrit(s).\n"
    )
    assert "3 déjà relevé(s), 0 nouveau(x)" in second


def test_an_account_without_mailbox_or_settings_says_so(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        account_id = new_account(connection)
        account = SqlAuthStore(connection).get_account(account_id)
    assert account is not None

    assert run(migrated_engine, account.email) == (
        1,
        f"Aucune boîte Gmail connectée ou libre pour {account.email}.\n",
    )
    code, output = run(migrated_engine, account.email, GmailSettings())
    assert code == 1
    assert output.startswith("Gmail n'est pas configuré")
    assert run(migrated_engine, "personne@example.fr") == (
        1,
        "Aucun compte pour personne@example.fr.\n",
    )


# ``rocky-admin messages-classer`` (decision E2, Q15, Q18): rules first, the model bounded by ``--limite``.


def classify(
    engine: Engine,
    email: str,
    *,
    use_model: bool,
    max_calls: int | None = None,
    model: ScriptedModel | None = None,
) -> tuple[int, str]:
    out = io.StringIO()
    service = MessagesService(
        engine, settings=GMAIL, clock=lambda: NOW, gmail=FakeGmail(), model=model
    )
    code = classify_account_messages(
        engine,
        email=email,
        service=service,
        use_model=use_model,
        max_calls=max_calls,
        again=False,
        out=out,
    )
    return code, out.getvalue()


def test_the_messages_are_classified_and_told(migrated_engine: Engine) -> None:
    email = account_with_mailbox(migrated_engine)
    run(migrated_engine, email)
    model = ScriptedModel(
        {
            "categorie": "unrelated",
            "candidature": "",
            "extrait": "x" * 20,
            "raison": ".",
        }
    )

    code, output = classify(migrated_engine, email, use_model=False)
    again, second = classify(
        migrated_engine, email, use_model=True, max_calls=0, model=model
    )

    assert (code, again) == (0, 0)
    assert output.startswith(
        f"Classement {CLASSIFY_VERSION} : 3 décision(s) par les règles, 0 par le modèle"
    )
    assert "Accusé de réception · Confiance moyenne : 1" in output
    assert "Alerte emploi · Confiance haute : 1" in output
    assert "0 décision(s) par les règles" in second
    assert model.prompts == []  # nothing left for the model, and --limite 0 anyway


def test_classifying_an_unknown_account_says_so(migrated_engine: Engine) -> None:
    assert classify(migrated_engine, "personne@example.fr", use_model=False) == (
        1,
        "Aucun compte pour personne@example.fr.\n",
    )


def test_the_labels_are_exported_as_csv(migrated_engine: Engine) -> None:
    email = account_with_mailbox(migrated_engine)
    run(migrated_engine, email)
    classify(migrated_engine, email, use_model=False)
    service = MessagesService(migrated_engine, settings=GMAIL, clock=lambda: NOW)
    with migrated_engine.connect() as connection:
        account = SqlAuthStore(connection).find_account(email)
    assert account is not None
    alert = next(
        message
        for message in service.state(account.id, View.ALERTS).messages
        if message.decision is not None
    )
    service.confirm(account.id, alert.id)
    out = io.StringIO()

    code = export_mail_labels(migrated_engine, email=email, service=service, out=out)

    rows = list(csv.DictReader(io.StringIO(out.getvalue())))
    assert code == 0
    assert tuple(rows[0]) == LABEL_COLUMNS
    assert [
        (row["gesture"], row["category"], row["reviewed_category"]) for row in rows
    ] == [("user.confirmed", "job_alert", "job_alert")]
    assert rows[0]["reviewed_author"] == "rule"


def test_exporting_the_labels_of_an_unknown_account_says_so(
    migrated_engine: Engine,
) -> None:
    out = io.StringIO()
    service = MessagesService(migrated_engine, settings=GMAIL, clock=lambda: NOW)

    code = export_mail_labels(
        migrated_engine, email="personne@example.fr", service=service, out=out
    )

    assert (code, out.getvalue()) == (1, "Aucun compte pour personne@example.fr.\n")


def test_the_alerts_give_their_offers_and_are_told(migrated_engine: Engine) -> None:
    email = account_with_mailbox(migrated_engine)
    service = MessagesService(migrated_engine, settings=GMAIL, clock=lambda: NOW)
    with migrated_engine.begin() as connection:
        account = SqlAuthStore(connection).find_account(email)
        assert account is not None
        equip(connection, account.id, email)
    (mailbox,) = service.state(account.id).mailboxes
    data = recorded_alert("hellowork_alerte")
    store_mail(
        service.storage,
        mailbox.mailbox.id,
        sender=data["sender"],
        subject=data["subject"],
        body_html=data["body_html"],
        found_by=Query.ALERTS,
    )
    service.classify(account.id, use_model=False)
    out = io.StringIO()

    code = read_account_alerts(
        migrated_engine, email=email, service=service, links=False, out=out
    )

    assert code == 0
    assert out.getvalue() == (
        "1 alerte(s) lue(s) : 4 offre(s), dont 4 nouvelle(s) ; 0 fiche(s) lue(s), 4 non lue(s) ; "
        "0 format(s) inconnu(s), 0 en échec.\n"
        "  Hellowork : 4 offre(s)\n"
    )


def test_reading_the_alerts_of_an_unknown_account_says_so(
    migrated_engine: Engine,
) -> None:
    out = io.StringIO()
    service = MessagesService(migrated_engine, settings=GMAIL, clock=lambda: NOW)

    code = read_account_alerts(
        migrated_engine,
        email="personne@example.com",
        service=service,
        links=False,
        out=out,
    )

    assert (code, out.getvalue()) == (1, "Aucun compte pour personne@example.com.\n")
