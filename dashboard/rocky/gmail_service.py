"""Synchronisation Gmail strictement en lecture seule.

Le service ne demande que ``gmail.readonly`` et ne stocke jamais le corps
intégral. Les contenus d'e-mail sont considérés comme non fiables : seuls des
motifs locaux et des liens HTTP(S) vers des domaines d'emploi autorisés sont
interprétés.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parseaddr
from html import unescape
from pathlib import Path
from urllib.parse import urlsplit

from .application_statuses import can_apply_automatic_transition
from .config import Settings
from .errors import ConfigurationError
from .job_importer import import_job_url
from .matching import calculate_match
from .models import CandidateProfile, EmailDecision
from .repository import RockyRepository
from .text_utils import normalize_text


GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
# Les deux seuils gardent les décisions Gmail prudentes : l'absence de lien
# emploi doit être très certaine pour être écartée, et une candidature ne peut
# évoluer sans une intention *et* un rattachement pratiquement certains.
AUTO_IGNORE_CONFIDENCE = 0.90
AUTO_APPLICATION_CONFIDENCE = 0.95
KNOWN_JOB_DOMAINS = (
    "indeed.",
    "linkedin.com",
    "apec.fr",
    "cadremploi.fr",
    "efinancialcareers.fr",
    "welcometothejungle.com",
    "hellowork.com",
    "francetravail.fr",
    "adzuna.",
    "wellfound.com",
    "greenhouse.io",
    "lever.co",
    "myworkdayjobs.com",
    "recruitee.com",
)

# Ces termes servent à séparer une réponse de candidature d'une newsletter
# personnelle. Ils ne déclenchent jamais un changement de statut à eux seuls :
# une candidature correspondante et une intention explicite restent requises.
APPLICATION_MARKERS = (
    "candidature",
    "postule",
    "recruitment process",
    "processus de recrutement",
    "recrutement",
    "talent team",
    "your application",
    "application at ",
    "application for ",
    "votre dossier",
)

JOB_ALERT_MARKERS = (
    "alerte emploi",
    "offres d emploi",
    "offre d emploi",
    "offre recommandee",
    "offres recommandees",
    "nouvelles offres",
    "opportunites correspondant",
    "job alert",
    "new jobs posted",
    "postulez pour",
    "n oubliez pas de postuler",
    "n'oubliez pas de postuler",
    "postulez !",
    "votre parcours pourrait correspondre",
    "offre d emploi suivante",
)

# Les formes juridiques n'identifient pas l'employeur. Les retirer permet par
# exemple de rapprocher « FIRST FINANCE SAS » de ``jobs@first-finance.com``.
EMPLOYER_LEGAL_SUFFIXES = {
    "ag",
    "bv",
    "corp",
    "corporation",
    "gmbh",
    "group",
    "groupe",
    "inc",
    "limited",
    "ltd",
    "sa",
    "sarl",
    "sas",
    "sasu",
    "se",
    "societe",
    "spa",
}

# Ces qualificatifs décrivent l'activité ou la structure, pas la marque. Ils
# ne suffisent pas seuls à rapprocher un expéditeur (« consulting », « group »).
EMPLOYER_GENERIC_WORDS = {
    "company",
    "conseil",
    "consulting",
    "digital",
    "france",
    "international",
    "partners",
    "services",
    "solutions",
    "technology",
    "technologies",
    "work",
}


@dataclass(frozen=True)
class GmailSyncSummary:
    """Bilan immuable d'une synchronisation Gmail locale, pour monitoring et audit."""

    fetched: int = 0
    inserted: int = 0
    auto_applied: int = 0
    auto_ignored: int = 0
    review: int = 0
    job_links_imported: int = 0
    errors: tuple[str, ...] = ()


def classify_email(subject: str, snippet: str) -> EmailDecision:
    """Évalue d'abord la pertinence emploi, puis l'intention du message.

    Les motifs explicites reçoivent une confiance élevée. Les signaux larges
    liés à une candidature restent volontairement dans la zone ambiguë : ils
    ne peuvent pas changer un dossier sans contrôle humain. L'absence de tout
    signal emploi est le seul chemin de classement automatique comme bruit.
    """
    text = normalize_text(f"{subject}\n{snippet}")
    rules = (
        (
            "OFFER",
            "OFFRE",
            0.99,
            (
                "proposition d embauche",
                "offre d embauche",
                "nous souhaitons vous recruter",
            ),
        ),
        (
            "REFUSAL",
            "REFUS",
            0.98,
            (
                "ne donnerons pas suite",
                "ne pouvons pas donner une suite favorable",
                "candidature non retenue",
                "avons retenu un autre profil",
                "malgre l interet de votre candidature",
                "malheureusement votre profil ne",
                "we regret to inform",
                "not moving forward",
                "decided not to move forward",
                "after careful consideration",
            ),
        ),
        (
            "TECHNICAL_TEST",
            "TEST TECHNIQUE",
            0.97,
            ("test technique", "cas pratique", "assessment", "test de recrutement"),
        ),
        (
            "INTERVIEW",
            "ENTRETIEN",
            0.96,
            (
                "convocation a un entretien",
                "proposer un entretien",
                "echange telephonique",
                "rencontrer prochainement",
                "disponibilites pour un entretien",
            ),
        ),
        (
            "ACKNOWLEDGEMENT",
            "ACCUSÉ DE RÉCEPTION",
            0.94,
            (
                "avons bien recu votre candidature",
                "bonne reception de votre candidature",
                "candidature a bien ete recue",
                "accuse de reception de votre candidature",
                "thank you for applying",
                "thank you for your interest",
                "we appreciate your interest",
                "merci d avoir postule",
                "merci d'avoir postule",
                "merci pour votre interet",
            ),
        ),
        (
            "IN_PROGRESS",
            "EN COURS",
            0.92,
            (
                "candidature est en cours",
                "etude de votre candidature",
                "profil en cours d examen",
            ),
        ),
    )
    for classification, status, confidence, markers in rules:
        marker = next((value for value in markers if value in text), None)
        if marker:
            return EmailDecision(
                classification, confidence, status, f"Motif explicite : {marker}"
            )
    if any(marker in text for marker in JOB_ALERT_MARKERS):
        return EmailDecision(
            "JOB_ALERT", 0.96, None, "Alerte emploi reconnue par motif explicite"
        )
    if any(marker in text for marker in APPLICATION_MARKERS):
        return EmailDecision(
            "APPLICATION_UPDATE",
            0.78,
            None,
            "Message lié à une candidature, intention à vérifier",
        )
    return EmailDecision(
        "NOISE", 0.96, None, "Aucun signal emploi détecté avec certitude élevée"
    )


def _employer_identity(value: object) -> tuple[str, tuple[str, ...]]:
    """Retourne le nom utile et ses mots, à partir de l'employeur de l'annonce."""
    tokens = tuple(
        token
        for token in re.findall(r"[a-z0-9]+", normalize_text(value))
        if token not in EMPLOYER_LEGAL_SUFFIXES and len(token) >= 2
    )
    return " ".join(tokens), tokens


def _decode_body(payload: dict[str, object]) -> str:
    """Extrait un aperçu lisible du corps Gmail sans conserver le message complet."""
    chunks: list[str] = []

    def visit(part: dict[str, object]) -> None:
        """Parcourt récursivement les parties MIME textuelles d'un message Gmail."""
        mime = str(part.get("mimeType") or "")
        data = dict(part.get("body") or {}).get("data")
        if data and mime in {"text/plain", "text/html"}:
            try:
                chunks.append(
                    base64.urlsafe_b64decode(str(data) + "===").decode(
                        "utf-8", errors="replace"
                    )
                )
            except (ValueError, UnicodeError):
                pass
        for child in part.get("parts") or []:
            if isinstance(child, dict):
                visit(child)

    visit(payload)
    return "\n".join(chunks)


def extract_job_links(body: str) -> list[str]:
    """Conserve uniquement des URLs HTTP(S) de domaines d'emploi connus."""
    candidates = re.findall(r"https?://[^\s<>\"']+", unescape(body))
    links: list[str] = []
    for candidate in candidates:
        cleaned = candidate.rstrip(".,);]}")
        host = urlsplit(cleaned).netloc.lower()
        if any(domain in host for domain in KNOWN_JOB_DOMAINS) and cleaned not in links:
            links.append(cleaned)
    return links[:20]


def match_application(
    applications,
    sender: str,
    subject: str,
    snippet: str,
) -> tuple[int | None, float, str]:
    """Rapproche une réponse uniquement via l'employeur stocké sur l'annonce.

    La plateforme ayant diffusé l'offre et l'intitulé du poste ne participent
    plus au score : le message peut légitimement arriver depuis le domaine de
    l'employeur après une candidature initiée sur Indeed, LinkedIn ou un ATS.
    """
    sender_name, sender_address = parseaddr(sender)
    sender_identity = normalize_text(f"{sender_name} {sender_address}")
    sender_tokens = set(re.findall(r"[a-z0-9]+", sender_identity))
    sender_compact = re.sub(r"[^a-z0-9]", "", sender_identity)
    message_identity = normalize_text(f"{subject} {snippet}")
    message_tokens = set(re.findall(r"[a-z0-9]+", message_identity))
    message_compact = re.sub(r"[^a-z0-9]", "", message_identity)
    ranked: list[tuple[float, int, str]] = []
    for _, row in applications.iterrows():
        _company_phrase, company_tokens = _employer_identity(row.get("company_name"))
        if not company_tokens:
            continue
        company_compact = "".join(company_tokens)
        brand_tokens = tuple(
            token for token in company_tokens if token not in EMPLOYER_GENERIC_WORDS
        )
        sender_brand_match = any(
            token in sender_tokens or (len(token) >= 4 and token in sender_compact)
            for token in brand_tokens
        )
        message_brand_match = any(
            token in message_tokens or (len(token) >= 4 and token in message_compact)
            for token in brand_tokens
        )
        sender_match = (
            all(token in sender_tokens for token in company_tokens)
            or (len(company_compact) >= 4 and company_compact in sender_compact)
            or sender_brand_match
        )
        message_match = (
            all(token in message_tokens for token in company_tokens)
            or (len(company_compact) >= 4 and company_compact in message_compact)
            or message_brand_match
        )
        if sender_match:
            ranked.append(
                (7.0, int(row["id"]), "employeur de la fiche reconnu dans l'expéditeur")
            )
        elif message_match:
            ranked.append(
                (5.5, int(row["id"]), "employeur de la fiche reconnu dans le message")
            )
    ranked.sort(reverse=True)
    if not ranked or ranked[0][0] < 4.0:
        return None, 0.0, "Aucun employeur de candidature reconnu"
    if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 1.0:
        return None, 0.0, "Plusieurs candidatures possibles pour cet employeur"
    confidence = min(0.99, 0.72 + ranked[0][0] / 20)
    return ranked[0][1], confidence, ranked[0][2]


def classify_and_match_email(
    applications,
    sender: str,
    subject: str,
    snippet: str,
) -> tuple[EmailDecision, int | None, float, str]:
    """Sépare strictement le flux d'annonces du flux de réponses employeur.

    Une alerte emploi reste pilotée par les motifs déterministes et les domaines
    autorisés de :func:`extract_job_links`. Les autres messages sont rapprochés
    uniquement de ``company_name``. Un message neutre provenant d'un employeur
    connu devient une mise à jour à vérifier au lieu d'être classé comme bruit.
    """
    decision = classify_email(subject, snippet)
    if decision.classification == "JOB_ALERT":
        return decision, None, 0.0, "Flux d'annonces déterministe"
    application_id, confidence, reason = match_application(
        applications, sender, subject, snippet
    )
    if application_id is not None and decision.classification == "NOISE":
        decision = EmailDecision(
            "APPLICATION_UPDATE",
            0.78,
            None,
            "Message provenant de l'employeur enregistré, intention à vérifier",
        )
    return decision, application_id, confidence, reason


class GmailService:
    """Client local Gmail mono-boîte dans la configuration multi-comptes.

    Une instance ne manipule qu'une adresse et son jeton dédié. Le client OAuth
    reste commun à toutes les boîtes, conformément au fonctionnement de Google.
    """

    def __init__(
        self,
        settings: Settings,
        repository: RockyRepository,
        profile: CandidateProfile,
        account_email: str | None = None,
    ):
        """Configure une seule boîte Gmail et son profil Rocky de rapprochement."""
        if repository.user_id is None:
            raise PermissionError(
                "Un compte authentifié est requis pour utiliser Gmail."
            )
        self.settings = settings
        self.repository = repository
        self.profile = profile
        selected_account = account_email or next(iter(settings.gmail_accounts), "")
        self.account_email = selected_account.strip().lower()
        if not self.account_email:
            raise ConfigurationError("Ajoute au moins une adresse dans GMAIL_ACCOUNTS.")

    @property
    def token_path(self) -> Path:
        """Retourne le jeton propre à la boîte, sans partager de session OAuth."""
        return self.settings.gmail_token_path_for(
            self.account_email, self.repository.user_id
        )

    @property
    def is_authorized(self) -> bool:
        """Indique si cette boîte possède déjà un jeton dédié."""
        return self.token_path.is_file()

    @staticmethod
    def _pending_path(settings: Settings, state: str, user_id: int) -> Path:
        """Transforme l'état OAuth non fiable en nom de fichier local sûr."""
        digest = hashlib.sha256(state.encode("utf-8")).hexdigest()
        return settings.gmail_oauth_pending_dir_for(user_id) / f"{digest}.json"

    @classmethod
    def _pending_authorization(
        cls, settings: Settings, state: str, user_id: int
    ) -> dict[str, object]:
        """Charge un échange OAuth récent et vérifie son état anti-CSRF."""
        if not state:
            raise ConfigurationError("L'état de l'autorisation Gmail est absent.")
        path = cls._pending_path(settings, state, user_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ConfigurationError(
                "Cette autorisation Gmail a expiré. Relance-la depuis Monitoring."
            ) from error
        created_at = float(payload.get("created_at") or 0)
        if payload.get("state") != state or time.time() - created_at > 900:
            path.unlink(missing_ok=True)
            raise ConfigurationError(
                "Cette autorisation Gmail a expiré. Relance-la depuis Monitoring."
            )
        return payload

    @classmethod
    def account_for_pending_authorization(
        cls, settings: Settings, state: str, user_id: int
    ) -> str:
        """Retrouve la boîte ciblée au retour de Google, sans faire confiance à l'URL."""
        payload = cls._pending_authorization(settings, state, user_id)
        account_email = str(payload.get("account_email") or "").strip().lower()
        if account_email not in settings.gmail_accounts:
            raise ConfigurationError("La boîte Gmail demandée n'est plus configurée.")
        return account_email

    @classmethod
    def discard_pending_authorization(
        cls, settings: Settings, state: str, user_id: int
    ) -> None:
        """Supprime un échange refusé ou annulé sans toucher aux jetons existants."""
        cls._pending_path(settings, state, user_id).unlink(missing_ok=True)

    def begin_browser_authorization(self, redirect_uri: str) -> str:
        """Prépare un lien Google que le navigateur local peut ouvrir.

        Le code PKCE et l'état sont conservés quinze minutes dans ``.secrets``.
        Ainsi le retour OAuth peut arriver dans une nouvelle session Streamlit
        sans exposer le secret du client ni dépendre d'un navigateur Docker.
        """
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as error:
            raise ConfigurationError(
                "Installe les dépendances Google de Rocky."
            ) from error
        client_secret_path = self._client_secret_path
        if client_secret_path is None or self.oauth_client_type != "installed":
            raise ConfigurationError(
                "Place un client OAuth Desktop app dans .secrets/gmail/credentials.json."
            )
        flow = InstalledAppFlow.from_client_secrets_file(
            client_secret_path,
            [GMAIL_READONLY_SCOPE],
            redirect_uri=redirect_uri,
        )
        authorization_url, state = flow.authorization_url(
            prompt="select_account consent",
            login_hint=self.account_email,
        )
        user_id = self.repository.user_id
        pending_path = self._pending_path(self.settings, state, user_id)
        pending_path.parent.mkdir(parents=True, exist_ok=True)
        pending_path.write_text(
            json.dumps(
                {
                    "state": state,
                    "account_email": self.account_email,
                    "redirect_uri": redirect_uri,
                    "code_verifier": flow.code_verifier,
                    "user_id": user_id,
                    "created_at": time.time(),
                }
            ),
            encoding="utf-8",
        )
        os.chmod(pending_path, 0o600)
        return authorization_url

    def complete_browser_authorization(
        self, *, state: str, code: str, redirect_uri: str
    ) -> None:
        """Échange le code Google, contrôle la boîte et enregistre son jeton."""
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as error:
            raise ConfigurationError(
                "Installe les dépendances Google de Rocky."
            ) from error
        user_id = self.repository.user_id
        payload = self._pending_authorization(self.settings, state, user_id)
        if (
            payload.get("account_email") != self.account_email
            or payload.get("redirect_uri") != redirect_uri
            or payload.get("user_id") != user_id
        ):
            raise ConfigurationError("Le retour Google ne correspond pas à la demande.")
        client_secret_path = self._client_secret_path
        if client_secret_path is None:
            raise ConfigurationError("Le client OAuth Gmail est introuvable.")
        flow = InstalledAppFlow.from_client_secrets_file(
            client_secret_path,
            [GMAIL_READONLY_SCOPE],
            state=state,
            redirect_uri=redirect_uri,
            code_verifier=str(payload.get("code_verifier") or ""),
        )
        flow.fetch_token(code=code)
        try:
            self._validated_client(flow.credentials)
        finally:
            self._pending_path(self.settings, state, user_id).unlink(missing_ok=True)

    @property
    def _client_secret_path(self) -> Path | None:
        """Trouve le premier client Desktop valide, même avec le nom Google."""
        preferred = self.settings.gmail_credentials_path
        candidates = [preferred]
        if preferred.parent.is_dir():
            candidates.extend(
                path
                for path in sorted(preferred.parent.glob("*.json"))
                if path != preferred
            )
        for path in candidates:
            if not path.is_file():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and "installed" in payload:
                return path
        return None

    @property
    def oauth_client_type(self) -> str | None:
        """Retourne le type OAuth sans exposer l'identifiant du client."""
        path = self.settings.gmail_credentials_path
        if self._client_secret_path is not None:
            return "installed"
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return "invalid"
        if isinstance(payload, dict) and "installed" in payload:
            return "installed"
        if isinstance(payload, dict) and "web" in payload:
            return "web"
        return "invalid"

    @property
    def is_configured(self) -> bool:
        """Indique si un client Desktop app compatible avec le loopback est prêt."""
        return self.oauth_client_type == "installed"

    def _credentials(self, interactive: bool, force_new: bool = False):
        """Charge ou crée le jeton sans l'enregistrer avant contrôle du compte."""
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as error:
            raise ConfigurationError(
                "Installe les dépendances Google de Rocky."
            ) from error
        token_path = self.token_path
        source_path = token_path if token_path.is_file() and not force_new else None
        credentials = None
        if source_path is not None:
            credentials = Credentials.from_authorized_user_file(
                source_path, [GMAIL_READONLY_SCOPE]
            )
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        if not credentials or not credentials.valid:
            if not interactive:
                raise ConfigurationError(
                    "Gmail attend l'autorisation initiale depuis la page Monitoring."
                )
            client_secret_path = self._client_secret_path
            if client_secret_path is None:
                raise ConfigurationError("Place credentials.json dans .secrets/gmail/.")
            if self.oauth_client_type != "installed":
                raise ConfigurationError(
                    "Le fichier Gmail doit être un client OAuth « Application de bureau » "
                    "(clé installed), pas un client Web."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                client_secret_path, [GMAIL_READONLY_SCOPE]
            )
            # Le choix explicite du compte empêche une session Google déjà
            # ouverte d'autoriser silencieusement la mauvaise boîte.
            credentials = flow.run_local_server(
                port=0,
                prompt="select_account",
                login_hint=self.account_email,
            )
        return credentials

    def authorize(self) -> None:
        """Autorise puis vérifie que Google a retourné la boîte demandée."""
        self._client(interactive=True, force_new=True)

    def _client(self, interactive: bool = False, force_new: bool = False):
        """Obtient un client Gmail validé pour cette boîte, avec OAuth contrôlé si demandé."""
        credentials = self._credentials(interactive, force_new=force_new)
        return self._validated_client(credentials)

    def _validated_client(self, credentials):
        """Vérifie l'adresse distante avant toute persistance du jeton OAuth."""
        from googleapiclient.discovery import build

        client = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        profile = client.users().getProfile(userId="me").execute()
        authenticated_email = str(profile.get("emailAddress") or "").strip().lower()
        if authenticated_email != self.account_email:
            raise ConfigurationError(
                "Google a autorisé une autre boîte que "
                f"{self.account_email}. Relance l'autorisation et choisis cette adresse."
            )
        # L'écriture n'arrive qu'après le contrôle de l'identité.
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(credentials.to_json(), encoding="utf-8")
        os.chmod(self.token_path, 0o600)
        return client

    def _import_links(self, links: list[str]) -> int:
        """Importe prudemment les liens d'alertes emploi qui franchissent le seuil Rocky."""
        imported = 0
        for url in links:
            try:
                preview = import_job_url(url)
                offer = preview.offer
                if (
                    not offer.job_title
                    or not offer.company_name
                    or not offer.responsibilities
                ):
                    continue
                result = calculate_match(
                    offer,
                    self.profile,
                    self.repository.fetch_skills(self.profile.id),
                )
                if result.score < self.settings.match_threshold:
                    continue
                job_id, inserted = self.repository.insert_job(offer, self.profile.id)
                self.repository.save_match(job_id, self.profile.id, result)
                imported += int(inserted)
            except Exception:
                # Un lien cassé ne doit ni arrêter Gmail ni déclencher un LLM.
                continue
        return imported

    @staticmethod
    def _stored_links(value: object) -> list[str]:
        """Normalise les liens JSON stockés sans faire confiance à leur type."""
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return []
        if not isinstance(value, (list, tuple)):
            return []
        return [
            str(item) for item in value if str(item).startswith(("http://", "https://"))
        ]

    def _triage_decision(
        self,
        *,
        email_id: int | None,
        reference: str = "",
        decision: EmailDecision,
        application_id: int | None,
        link_confidence: float,
        match_reason: str,
        links: list[str],
        import_links: bool,
    ) -> tuple[str, int]:
        """Applique une décision locale et renvoie l'état et le nombre importé."""
        imported = 0
        combined = min(decision.confidence, link_confidence) if application_id else 0
        state = "REVIEW"
        reason = f"{decision.reason}; {match_reason}"
        if decision.classification == "JOB_ALERT":
            # Une alerte n'est importée sans vérification que si son signal
            # est explicite ET qu'un lien emploi autorisé a été extrait.
            # Sans lien exploitable, elle reste visible dans la file au lieu
            # d'être silencieusement jetée comme une newsletter ordinaire.
            if (
                decision.confidence > AUTO_APPLICATION_CONFIDENCE
                and links
                and import_links
            ):
                imported = self._import_links(links)
                state = "IMPORTED" if imported else "REVIEW"
                if not imported:
                    reason += "; lien présent mais import à vérifier"
            elif decision.confidence > AUTO_APPLICATION_CONFIDENCE and links:
                # Les liens ont déjà été traités lors d'une passe précédente.
                state = "IMPORTED"
            else:
                reason += "; alerte ou annonce insuffisamment certaine à vérifier"
        elif (
            decision.proposed_status
            and application_id
            and combined > AUTO_APPLICATION_CONFIDENCE
        ):
            current = self.repository.fetch_application(application_id)
            if current and can_apply_automatic_transition(
                str(current["status"]), decision.proposed_status
            ):
                self.repository.update_application_status(
                    application_id,
                    decision.proposed_status,
                    source="GMAIL",
                    confidence=combined,
                    details={
                        "gmail_account": self.account_email,
                        "gmail_message_id": reference,
                        "email_message_id": email_id,
                        "reason": decision.reason,
                    },
                )
                state = "AUTO_APPLIED"
        elif (
            decision.classification == "NOISE"
            and not application_id
            and decision.confidence > AUTO_IGNORE_CONFIDENCE
        ):
            # Les newsletters, alertes techniques et notifications personnelles
            # sont archivées localement seulement lorsque leur absence de lien
            # emploi est suffisamment certaine, sans polluer la file de revue.
            state = "AUTO_IGNORED"
        elif decision.proposed_status and application_id:
            reason += (
                f"; décision à {combined:.0%}, sous le seuil automatique "
                f"de {AUTO_APPLICATION_CONFIDENCE:.0%}"
            )
        if email_id is not None:
            self.repository.update_email_triage(
                email_id,
                classification=decision.classification,
                confidence=combined or decision.confidence,
                processing_state=state,
                reason=reason,
                application_id=application_id,
            )
        return state, imported

    def _retriage_existing_pending(self, applications) -> tuple[int, int, int, int]:
        """Nettoie la file historique après l'amélioration des règles locales."""
        pending = self.repository.fetch_pending_email_messages(self.account_email)
        auto_applied = 0
        auto_ignored = 0
        imported = 0
        review = 0
        for _, row in pending.iterrows():
            decision, application_id, link_confidence, match_reason = (
                classify_and_match_email(
                    applications,
                    str(row.get("sender", "")),
                    str(row.get("subject", "")),
                    str(row.get("snippet", "")),
                )
            )
            state, count = self._triage_decision(
                email_id=int(row["id"]),
                reference=str(row.get("gmail_message_id") or ""),
                decision=decision,
                application_id=application_id,
                link_confidence=link_confidence,
                match_reason=match_reason,
                links=self._stored_links(row.get("extracted_links")),
                import_links=False,
            )
            auto_applied += int(state == "AUTO_APPLIED")
            auto_ignored += int(state == "AUTO_IGNORED")
            review += int(state == "REVIEW")
            imported += count
        return auto_applied, auto_ignored, imported, review

    def sync_gmail(self) -> GmailSyncSummary:
        """Lit, classe et applique seulement les décisions à haute confiance."""
        client = self._client(interactive=False)
        query = f"newer_than:{self.settings.gmail_lookback_days}d"
        listing = (
            client.users()
            .messages()
            .list(userId="me", q=query, maxResults=self.settings.gmail_max_messages)
            .execute()
        )
        applications = self.repository.fetch_applications(self.profile.id)
        counters = {
            "inserted": 0,
            "auto": 0,
            "ignored": 0,
            "review": 0,
            "links": 0,
        }
        historic_auto, historic_ignored, historic_imported, historic_review = (
            self._retriage_existing_pending(applications)
        )
        counters["auto"] += historic_auto
        counters["ignored"] += historic_ignored
        counters["review"] += historic_review
        counters["links"] += historic_imported
        errors: list[str] = []
        messages = listing.get("messages", [])
        for item in messages:
            gmail_id = str(item.get("id") or "")
            if not gmail_id or self.repository.email_message_exists(
                self.account_email, gmail_id
            ):
                continue
            try:
                message = (
                    client.users()
                    .messages()
                    .get(userId="me", id=gmail_id, format="full")
                    .execute()
                )
                headers = {
                    str(header.get("name") or "").lower(): str(
                        header.get("value") or ""
                    )
                    for header in message.get("payload", {}).get("headers", [])
                }
                sender = headers.get("from", "")
                subject = headers.get("subject", "")
                snippet = " ".join(str(message.get("snippet") or "").split())[:1000]
                body = _decode_body(message.get("payload", {}))
                links = extract_job_links(body)
                decision, application_id, link_confidence, match_reason = (
                    classify_and_match_email(applications, sender, subject, snippet)
                )
                state, imported = self._triage_decision(
                    email_id=None,
                    reference=gmail_id,
                    decision=decision,
                    application_id=application_id,
                    link_confidence=link_confidence,
                    match_reason=match_reason,
                    links=links,
                    import_links=True,
                )
                counters["links"] += imported
                counters["auto"] += int(state == "AUTO_APPLIED")
                counters["ignored"] += int(state == "AUTO_IGNORED")
                counters["review"] += int(state == "REVIEW")
                saved = self.repository.save_email_message(
                    {
                        "gmail_account": self.account_email,
                        "gmail_message_id": gmail_id,
                        "gmail_thread_id": message.get("threadId"),
                        "sender": sender,
                        "subject": subject,
                        "received_at": datetime.fromtimestamp(
                            int(message.get("internalDate", "0")) / 1000,
                            tz=timezone.utc,
                        ),
                        "snippet": snippet,
                        "classification": decision.classification,
                        "confidence": (
                            min(decision.confidence, link_confidence)
                            if application_id
                            else decision.confidence
                        ),
                        "matched_application_id": application_id,
                        "processing_state": state,
                        "reason": f"{decision.reason}; {match_reason}",
                        "extracted_links": links,
                    }
                )
                counters["inserted"] += int(saved is not None)
            except Exception as error:
                errors.append(f"{gmail_id}: {type(error).__name__}")
        return GmailSyncSummary(
            fetched=len(messages),
            inserted=counters["inserted"],
            auto_applied=counters["auto"],
            auto_ignored=counters["ignored"],
            review=counters["review"],
            job_links_imported=counters["links"],
            errors=tuple(errors),
        )
