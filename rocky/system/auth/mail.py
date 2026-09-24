"""Account e-mails (invitation, password reset) and their SMTP delivery."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from typing import Protocol

from rocky.system.auth.usecases import MailKind, OutgoingMail
from rocky.system.config import SmtpSettings

IMPLICIT_TLS_PORT = 465
SMTP_TIMEOUT_SECONDS = 15

SUBJECTS = {
    MailKind.INVITATION: "Ton invitation à Rocky",
    MailKind.PASSWORD_RESET: "Réinitialise ton mot de passe Rocky",
}
BODIES = {
    MailKind.INVITATION: (
        "Tu es invité·e à utiliser Rocky, ton assistant de recherche d'emploi.\n\n"
        "Choisis ton mot de passe pour activer ton compte :\n\n{link}\n\n"
        "Ce lien est personnel et reste valable 7 jours."
    ),
    MailKind.PASSWORD_RESET: (
        "Une réinitialisation de ton mot de passe Rocky a été demandée.\n\n"
        "Choisis un nouveau mot de passe avec ce lien :\n\n{link}\n\n"
        "Ce lien est personnel et reste valable 1 heure. "
        "Si tu n'as rien demandé, ignore ce message."
    ),
}


class Mailer(Protocol):
    def send(self, mail: OutgoingMail) -> None: ...


class MailNotConfiguredError(Exception):
    """No SMTP settings: account e-mails cannot be sent."""


class MailDeliveryError(Exception):
    """The SMTP server could not be reached or refused the message."""


def compose(mail: OutgoingMail, sender: str) -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = mail.recipient
    message["Subject"] = SUBJECTS[mail.kind]
    message.set_content(BODIES[mail.kind].format(link=mail.link))
    return message


class SmtpMailer:
    def __init__(self, settings: SmtpSettings | None) -> None:
        self._settings = settings

    def send(self, mail: OutgoingMail) -> None:
        settings = self._settings
        if settings is None:
            raise MailNotConfiguredError(
                "ROCKY_SMTP_HOST and ROCKY_SMTP_FROM are unset"
            )
        message = compose(mail, settings.sender)
        context = ssl.create_default_context()
        try:
            if settings.port == IMPLICIT_TLS_PORT:
                smtp: smtplib.SMTP = smtplib.SMTP_SSL(
                    settings.host,
                    settings.port,
                    timeout=SMTP_TIMEOUT_SECONDS,
                    context=context,
                )
            else:
                smtp = smtplib.SMTP(
                    settings.host, settings.port, timeout=SMTP_TIMEOUT_SECONDS
                )
            with smtp:
                if settings.starttls and settings.port != IMPLICIT_TLS_PORT:
                    smtp.starttls(context=context)
                if settings.username:
                    smtp.login(settings.username, settings.password or "")
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException) as error:
            raise MailDeliveryError(
                f"SMTP delivery to {settings.host}:{settings.port} failed: {error}"
            ) from error
