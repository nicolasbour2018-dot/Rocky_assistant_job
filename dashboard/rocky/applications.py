"""Orchestration sûre de la paire de PDF associée à une candidature."""

from __future__ import annotations

from pathlib import Path
import shutil

from .config import Settings
from .cv_tailoring import build_tailored_cv_plan, create_tailored_cv, file_sha256
from .errors import DocumentError
from .letters import LetterVariables, create_docx, create_pdf
from .models import ApplicationPackage, CandidateProfile, JobOffer, TailoredCvPlan
from .projects import load_profile_projects
from .profile_documents import convert_docx_to_pdf, fill_letter_template
from .repository import RockyRepository
from .text_utils import project_relative, safe_filename_component, safe_slug


def _source_path(settings: Settings, profile: CandidateProfile) -> Path:
    """Résout le CV immuable du profil avant la génération du dossier de candidature."""
    path = Path(profile.cv_path).expanduser()
    return path if path.is_absolute() else settings.project_dir / path


def generate_application(
    job_id: int,
    profile: CandidateProfile,
    offer: JobOffer,
    letter_text: str,
    settings: Settings,
    repository: RockyRepository,
    plan: TailoredCvPlan | None = None,
    rocky_paragraph: str = "",
) -> ApplicationPackage:
    """Génère, contrôle et versionne exactement deux PDF.

    Une régénération réutilise le dossier de candidature existant mais conserve
    les anciennes versions dans ``application_documents``.
    """
    documents = {
        document.kind: document
        for document in repository.fetch_profile_documents(profile.id, profile.locale)
    }
    cv_document = documents.get("cv")
    letter_document = documents.get("letter")
    if profile.locale == "en" and (
        cv_document is None
        or letter_document is None
        or cv_document.status != "ready"
        or letter_document.status != "ready"
    ):
        # Une candidature anglaise s'appuie exclusivement sur le kit importé
        # par l'utilisateur : aucun CV ou modèle de lettre n'est traduit à la
        # volée ni remplacé par un document générique.
        raise DocumentError(
            "Importe et valide le CV PDF et la lettre DOCX anglais dans Profil & CV "
            "avant de générer la candidature."
        )
    source = (
        Path(cv_document.source_path).expanduser()
        if cv_document
        else _source_path(settings, profile)
    )
    if not source.is_absolute():
        source = settings.project_dir / source
    if not source.is_file():
        raise DocumentError("Le CV source immuable du profil est introuvable.")
    if profile.locale == "fr":
        # Seul le gabarit français historique possède des zones de ciblage.
        # Une version anglaise importée ou générée est recopiée telle quelle.
        projects = load_profile_projects(
            profile.id, settings, repository, profile.locale
        )
        skills = repository.fetch_skills(profile.id)
        plan = plan or build_tailored_cv_plan(offer, skills, projects)
    if profile.user_id is None:
        raise PermissionError(
            "Un compte authentifié est requis pour générer une candidature."
        )
    output_root = settings.user_output_dir(profile.user_id)
    folder = output_root / "_".join(
        [
            safe_slug(offer.company_name, "entreprise"),
            safe_slug(offer.job_title, "poste"),
        ]
    )
    folder.mkdir(parents=True, exist_ok=True)
    # Les deux PDF gardent le même nom d'une régénération à l'autre : le poste
    # et l'entreprise permettent de les retrouver immédiatement dans un
    # dossier de candidature, sans exposer un horodatage opaque.
    offer_component = safe_filename_component(offer.job_title, "Offre")
    company_component = safe_filename_component(offer.company_name, "Entreprise")
    candidate_component = safe_filename_component(
        profile.full_name or profile.profile_name, "Candidat"
    )
    cv_path = folder / (
        f"{candidate_component}_CV_{offer_component}_{company_component}.pdf"
    )
    letter_path = folder / (
        f"{candidate_component}_LM_{offer_component}_{company_component}.pdf"
    )
    if profile.locale == "en":
        if cv_document is None or cv_document.status != "ready":
            raise DocumentError("La version anglaise du CV doit être actualisée.")
        shutil.copy2(source, cv_path)
    else:
        create_tailored_cv(source, cv_path, plan, settings)
    variables = LetterVariables(
        job_title=offer.job_title,
        company_name=offer.company_name,
        company_paragraph="Contenu intégré dans la lettre validée.",
        sender_name=profile.full_name or profile.profile_name,
        sender_address=" · ".join(
            value
            for value in (profile.address, profile.postal_code, profile.home_city)
            if value
        ),
        sender_phone=profile.phone,
        sender_email=profile.email,
        city=profile.home_city,
        locale=profile.locale,
    )
    if letter_document is not None:
        if profile.locale == "en" and letter_document.status != "ready":
            raise DocumentError(
                "La version anglaise de la lettre doit être actualisée."
            )
        template_path = Path(letter_document.source_path).expanduser()
        if not template_path.is_absolute():
            template_path = settings.project_dir / template_path
        final_docx = folder / f"Lettre_{offer_component}_{company_component}.docx"
        if letter_text.strip():
            # Le texte sauvegardé dans l'atelier est la lettre relue et
            # adaptée à l'annonce. Il doit donc être la source du PDF final,
            # même lorsqu'un modèle DOCX a été importé pour le profil. Le
            # modèle ne redevient un repli que pour les appels historiques qui
            # ne fournissent aucun brouillon validé.
            create_docx(final_docx, variables, letter_text)
        else:
            fill_letter_template(
                template_path,
                final_docx,
                rocky_paragraph or variables.company_paragraph,
            )
        convert_docx_to_pdf(final_docx, letter_path)
    else:
        create_pdf(letter_path, variables, letter_text)
    existing = repository.fetch_latest_application_for_job(job_id, profile.id)
    cv_relative = project_relative(cv_path, settings.project_dir)
    letter_relative = project_relative(letter_path, settings.project_dir)
    if existing:
        application_id = int(existing["id"])
        repository.update_application_paths(
            application_id, cv_relative, letter_relative, profile.locale
        )
    else:
        application_id = repository.create_application(
            job_id,
            profile.id,
            cv_relative,
            None,
            letter_relative,
            profile.locale,
        )
    repository.add_application_document(
        application_id, "CV", cv_relative, file_sha256(cv_path)
    )
    repository.add_application_document(
        application_id, "LETTER", letter_relative, file_sha256(letter_path)
    )
    return ApplicationPackage(
        directory=str(folder),
        cv_pdf_path=str(cv_path),
        letter_pdf_path=str(letter_path),
        application_id=application_id,
        locale=profile.locale,
    )
