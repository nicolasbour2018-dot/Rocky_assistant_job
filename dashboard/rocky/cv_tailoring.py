"""Adaptation bornée des zones autorisées du CV Canva.

Le PDF source n'est jamais modifié. Son empreinte et le nombre de pages sont
contrôlés avant toute redaction. Les autres zones restent celles du document
original, ce qui rend l'opération à la fois réversible et vérifiable.
"""

from __future__ import annotations

import hashlib
import html
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from .config import Settings
from .errors import DocumentError
from .models import (
    JobOffer,
    ProfileProject,
    TailoredCvPlan,
    TailoredProject,
)
from .text_utils import normalize_text

TECHNICAL_GROUPS = (
    (
        "Langages et Data",
        (
            "python",
            "sql",
            "pandas",
            "numpy",
            "plotly",
            "excel",
            "postgres",
            "aws",
            "spark",
        ),
    ),
    (
        "Data Science et IA",
        (
            "machine",
            "scikit",
            "nlp",
            "rag",
            "llm",
            "langchain",
            "transform",
            "pytorch",
            "tensorflow",
        ),
    ),
    (
        "Déploiement / Dev",
        (
            "api",
            "fastapi",
            "docker",
            "git",
            "streamlit",
            "hugging",
            "mlflow",
            "n8n",
            "cloud",
        ),
    ),
)

# Le modèle Canva réserve beaucoup d'espace vide sous les contenus courts des
# cartes. Ce décalage constant rapproche visuellement le bloc de texte du
# centre du cadre sans déplacer le titre ni les éléments hors zone autorisée.
PROJECT_BODY_TOP_INSET = 9


def file_sha256(path: Path) -> str:
    """Calcule l'empreinte du CV source afin de protéger les zones verrouillées."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _offer_text(offer: JobOffer) -> str:
    """Réunit les termes métier de l'annonce servant à classer les éléments du CV."""
    return normalize_text(
        " ".join(
            [
                offer.job_title,
                offer.responsibilities,
                offer.short_description,
                " ".join(offer.detected_skills),
                offer.main_domain,
            ]
        )
    )


def _relevance(value: str, offer_text: str, core: bool = False) -> float:
    """Évalue la pertinence explicable d'une compétence ou projet pour une offre."""
    normalized = normalize_text(value)
    if not normalized:
        return 0
    score = 3.0 if normalized in offer_text else 0.0
    tokens = {token for token in normalized.split() if len(token) > 2}
    score += sum(1.0 for token in tokens if token in offer_text)
    return score + (0.35 if core else 0)


def _group_skills(
    skills: list[dict[str, object]], offer_text: str
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Sélectionne et groupe les compétences du profil pour les zones éditables du CV."""
    # Les compétences métier alimentent le bloc transversal ; les répéter dans
    # le bloc technique rendrait les badges et le CV finaux ambigus.
    technical = [
        skill
        for skill in skills
        if str(skill.get("skill_category") or "").lower() not in {"soft", "business"}
    ]
    selected: set[str] = set()
    groups: list[tuple[str, tuple[str, ...]]] = []
    for label, markers in TECHNICAL_GROUPS:
        candidates = []
        for skill in technical:
            name = str(skill.get("skill_name") or "").strip()
            normalized = normalize_text(name)
            if any(marker in normalized for marker in markers):
                candidates.append(
                    (
                        _relevance(name, offer_text, bool(skill.get("is_core_skill"))),
                        name,
                    )
                )
        names = []
        for _, name in sorted(candidates, key=lambda item: (-item[0], item[1])):
            key = normalize_text(name)
            if key and key not in selected:
                selected.add(key)
                names.append(name)
            if len(names) == 6:
                break
        if names:
            groups.append((label, tuple(names)))
    remaining = []
    for skill in technical:
        name = str(skill.get("skill_name") or "").strip()
        if normalize_text(name) not in selected:
            remaining.append(
                (_relevance(name, offer_text, bool(skill.get("is_core_skill"))), name)
            )
    if remaining:
        label = groups[0][0] if groups else "Outils et méthodes"
        additions = tuple(
            name
            for _, name in sorted(remaining, key=lambda item: (-item[0], item[1]))[:6]
        )
        if groups:
            # Un bloc de compétences du CV ne peut accueillir que six badges.
            # Cette borne s'applique aussi aux compétences hors taxonomie.
            groups[0] = (label, (*groups[0][1], *additions)[:6])
        else:
            groups.append((label, additions))
    return tuple(groups[:3])


def _select_transversal(
    skills: list[dict[str, object]], offer_text: str
) -> tuple[str, ...]:
    """Retient les compétences transversales utiles sans dépasser la zone du modèle."""
    candidates = []
    for skill in skills:
        if str(skill.get("skill_category") or "").lower() not in {"soft", "business"}:
            continue
        name = str(skill.get("skill_name") or "").strip()
        candidates.append(
            (_relevance(name, offer_text, bool(skill.get("is_core_skill"))), name)
        )
    return tuple(
        name for _, name in sorted(candidates, key=lambda item: (-item[0], item[1]))[:6]
    )


def _compact(value: str, limit: int) -> str:
    """Réduit un libellé pour préserver la mise en page à une page du CV ciblé."""
    cleaned = " ".join(str(value or "").split())
    if len(cleaned) <= limit:
        return cleaned
    cut = cleaned[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:.-")
    return cut + "."


def _select_projects(
    projects: Iterable[ProfileProject], offer_text: str
) -> tuple[TailoredProject, ...]:
    """Retient au plus trois projets factuels pour illustrer l'adéquation à l'offre."""
    ranked = []
    for project in projects:
        if not project.is_active:
            continue
        evidence = " ".join(
            [
                project.name,
                project.problem,
                " ".join(project.stack),
                project.deliverable,
                project.details,
                " ".join(project.skills),
                project.results,
            ]
        )
        ranked.append((_relevance(evidence, offer_text), project.sort_order, project))
    selected = sorted(ranked, key=lambda item: (-item[0], item[1]))[:3]
    return tuple(_tailored_project(project) for _, _, project in selected)


def _tailored_project(project: ProfileProject) -> TailoredProject:
    """Réduit un projet validé aux limites physiques de sa carte CV."""
    return TailoredProject(
        slug=project.slug,
        title=_compact(project.name, 42),
        problem=_compact(project.problem, 145),
        stack=_compact(", ".join(project.stack), 120),
        deliverable=_compact(project.deliverable, 125),
    )


def build_tailored_cv_plan_from_selection(
    technical_groups: Iterable[tuple[str, Iterable[str]]],
    transversal_skills: Iterable[str],
    projects: Iterable[ProfileProject],
) -> TailoredCvPlan:
    """Construit le plan du CV depuis des badges choisis dans le profil.

    Les valeurs sont déjà issues du profil et non de champs de texte libres.
    Les bornes sont appliquées ici aussi afin que le générateur reste protégé
    même si l'interface évolue ou qu'une session Streamlit est périmée.
    """
    groups = tuple(
        (label, tuple(str(value).strip() for value in values if str(value).strip())[:6])
        for label, values in technical_groups
        if str(label).strip()
    )
    non_empty_groups = tuple((label, values) for label, values in groups if values)
    selected_projects = tuple(
        _tailored_project(project) for project in projects if project.is_active
    )[:3]
    return TailoredCvPlan(
        technical_groups=non_empty_groups,
        transversal_skills=tuple(
            str(value).strip() for value in transversal_skills if str(value).strip()
        )[:6],
        projects=selected_projects,
    )


def build_tailored_cv_plan(
    offer: JobOffer,
    skills: list[dict[str, object]],
    projects: list[ProfileProject],
) -> TailoredCvPlan:
    """Sélectionne uniquement des faits existants selon leur pertinence."""
    offer_text = _offer_text(offer)
    plan = TailoredCvPlan(
        technical_groups=_group_skills(skills, offer_text),
        transversal_skills=_select_transversal(skills, offer_text),
        projects=_select_projects(projects, offer_text),
    )
    if not plan.technical_groups or not plan.projects:
        raise DocumentError(
            "Le profil doit contenir des compétences et au moins un projet validé."
        )
    return plan


@dataclass(frozen=True)
class _CvTemplate:
    """Description des zones modifiables du CV de référence."""

    source_sha256: str
    page_count: int
    zones: dict[str, tuple[float, float, float, float]]
    background_rgb: tuple[int, int, int]


def _template(settings: Settings) -> _CvTemplate:
    """Charge la description des zones autorisées du modèle Canva, sans modifier le PDF."""
    path = settings.project_dir / "assets" / "cv_template_v1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    red, green, blue = payload["background_rgb"]
    return _CvTemplate(
        source_sha256=str(payload["source_sha256"]),
        page_count=int(payload["page_count"]),
        zones={
            str(name): (float(x0), float(y0), float(x1), float(y1))
            for name, (x0, y0, x1, y1) in payload["zones"].items()
        },
        background_rgb=(int(red), int(green), int(blue)),
    )


def _validate_source(source: Path, template: _CvTemplate) -> None:
    """Vérifie l'empreinte du CV de référence avant toute adaptation ciblée."""
    if not source.is_file():
        raise DocumentError(f"CV source introuvable : {source}")
    if file_sha256(source) != template.source_sha256:
        raise DocumentError(
            "Le CV source a changé. Recalibre le modèle avant de générer un CV ciblé."
        )
    with pymupdf.open(source) as document:
        if document.page_count != template.page_count:
            raise DocumentError("Le CV source doit contenir exactement une page.")


def _redact_zone_text(
    page: pymupdf.Page, zone: pymupdf.Rect, fill: tuple[float, ...]
) -> None:
    """Retire uniquement la portion des glyphes comprise dans une zone.

    Canva peut exporter une ligne complète comme un seul ``span`` PDF, même
    lorsque cette ligne traverse plusieurs colonnes. Utiliser toute la boîte du
    span effacerait alors du contenu statique hors du cadre ciblé. L'intersection
    stricte garantit que la redaction ne déborde jamais de la zone autorisée.
    """
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                rect = pymupdf.Rect(span["bbox"])
                if rect.intersects(zone):
                    clipped = rect & zone
                    page.add_redact_annot(clipped, fill=fill)


def _font_css(settings: Settings) -> str:
    """Construit le CSS de police compatible avec le rendu PyMuPDF du modèle."""
    fonts = settings.project_dir / "assets" / "fonts"
    return f"""
    @font-face {{ font-family: Poppins; src: url('{fonts / "Poppins-Regular.ttf"}'); }}
    @font-face {{ font-family: Poppins; src: url('{fonts / "Poppins-Bold.ttf"}'); font-weight: bold; }}
    @font-face {{ font-family: Questrial; src: url('{fonts / "Questrial-Regular.ttf"}'); }}
    * {{ box-sizing: border-box; }}
    """


def _insert(
    page: pymupdf.Page,
    rect: pymupdf.Rect,
    body: str,
    css: str,
    minimum_scale: float = 0.82,
) -> None:
    """Insère du texte dans une zone autorisée en protégeant l'équilibre du CV."""
    spare, scale = page.insert_htmlbox(rect, body, css=css, scale_low=minimum_scale)
    if spare < -0.01 or scale < minimum_scale:
        raise DocumentError("Le contenu ciblé dépasse la zone autorisée du CV.")


def create_tailored_cv(
    source: Path,
    target: Path,
    plan: TailoredCvPlan,
    settings: Settings,
) -> Path:
    """Crée une copie ciblée en ne modifiant que les zones autorisées."""
    template = _template(settings)
    _validate_source(source, template)
    zones = {name: pymupdf.Rect(values) for name, values in template.zones.items()}
    rgb = tuple(value / 255 for value in template.background_rgb)
    document = pymupdf.open(source)
    page = document[0]
    for zone in zones.values():
        _redact_zone_text(page, zone, rgb)
    page.apply_redactions(images=0, graphics=0)

    css = _font_css(settings)
    technical = "".join(
        f"<div class='group'><b>{html.escape(label)} :</b><br>"
        f"{html.escape(', '.join(values))}</div>"
        for label, values in plan.technical_groups
    )
    _insert(
        page,
        zones["technical"],
        f"<div style='font-family:Poppins;text-align:center;font-size:9.4px;line-height:1.14'>{technical}</div>",
        css + ".group{margin:0 0 3px 0}",
        0.78,
    )
    transversal = "<br>".join(html.escape(value) for value in plan.transversal_skills)
    transversal_style = (
        "font-family:Questrial;text-align:center;color:#666;"
        "font-size:10.5px;line-height:1.35"
    )
    _insert(
        page,
        zones["transversal"],
        f"<div style='{transversal_style}'>{transversal}</div>",
        css,
        0.82,
    )
    for index, project in enumerate(plan.projects, start=1):
        title = html.escape(project.title)
        _insert(
            page,
            zones[f"project_{index}_title"],
            f"<div style='font-family:Poppins;text-align:center;font-size:7.6px;line-height:1.05'>{title}</div>",
            css,
            0.82,
        )
        body = (
            f"<b>Problématique :</b> {html.escape(project.problem)}<br><br>"
            f"<b>Stack technique :</b> {html.escape(project.stack)}<br><br>"
            f"<b>Livrable :</b> {html.escape(project.deliverable)}"
        )
        body_rect = pymupdf.Rect(zones[f"project_{index}_body"])
        body_rect.y0 += PROJECT_BODY_TOP_INSET
        _insert(
            page,
            body_rect,
            f"<div style='font-family:Poppins;text-align:center;font-size:7.6px;line-height:1.08'>{body}</div>",
            css,
            0.72,
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    document.save(target, garbage=4, deflate=True)
    document.close()
    with pymupdf.open(target) as check:
        if check.page_count != 1 or len(check[0].get_text().strip()) < 500:
            raise DocumentError("Le contrôle final du CV ciblé a échoué.")
    return target
