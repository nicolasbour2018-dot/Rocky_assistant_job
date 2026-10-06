"""Fictional designed CVs, made on the spot as PDFs, and a fake model that reads them (no network, no real person).

The first page mimics what a design tool exports: a coloured background, shapes, a photo clipped to a circle, spaced
section titles, bullets and fixed texts. The second one is another design (decision G5, Q3): one column, project
cards stacked one above the other, names ending with a colon, a part running over two lines.
"""

from __future__ import annotations

import io
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from rocky.profil.cv.importer import ImportedCv, import_cv, read_proposals
from rocky.profil.cv.library import font_assets, font_faces
from rocky.system.files import FileStore
from rocky.system.render import render_pdf

LABELS = {"project_problem": "Problématique", "project_stack": "Stack technique"}

PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
{faces}
@page {{ size: 595pt 842pt; margin: 0; }}
body {{ margin: 0; font-family: "Poppins", sans-serif; }}
.page {{ position: relative; width: 595pt; height: 842pt; background: #f4f1ea; overflow: hidden; }}
.t {{ position: absolute; margin: 0; white-space: nowrap; }}
.h {{ letter-spacing: 3pt; font-size: 12pt; color: #1f5f7a; }}
</style></head><body><div class="page">
<svg style="position:absolute;left:0;top:0" width="595pt" height="842pt" viewBox="0 0 595 842">
  <path d="M0 250 C 150 230, 170 180, 180 0" stroke="#27b6d8" stroke-width="3" fill="none"/>
  <rect x="200" y="330" width="170" height="160" rx="12" fill="none" stroke="#666" stroke-width="5"/>
  <circle cx="30" cy="560" r="2" fill="#333"/>
</svg>
<img src="curve.png" style="position:absolute;left:380pt;top:600pt;width:200pt;height:200pt">
<div style="position:absolute;left:400pt;top:40pt;width:140pt;height:140pt;border-radius:50%;overflow:hidden">
  <img src="photo.png" style="width:140pt;height:170pt;display:block">
</div>
<p class="t" style="left:30pt;top:40pt;font-size:26pt;font-weight:bold">CAMILLE MARTIN</p>
<p class="t" style="left:30pt;top:80pt;font-size:13pt">DATA SCIENTIST</p>
<p class="t" style="left:30pt;top:110pt;font-size:9pt">Data scientist issue de la logistique, je transforme</p>
<p class="t" style="left:30pt;top:122pt;font-size:9pt">des données opérationnelles en outils de décision.</p>
<p class="t h" style="left:30pt;top:280pt">C O N T A C T</p>
<p class="t" style="left:30pt;top:300pt;font-size:9pt">camille.martin@example.org</p>
<p class="t" style="left:30pt;top:313pt;font-size:9pt">06 00 00 00 00</p>
<p class="t h" style="left:210pt;top:300pt">P R O J E T S</p>
<p class="t" style="left:215pt;top:345pt;font-size:8pt;font-weight:bold">Tri des messages clients</p>
<p class="t" style="left:215pt;top:360pt;font-size:7pt">Problématique : Des milliers de messages</p>
<p class="t" style="left:215pt;top:385pt;font-size:7pt">Stack technique : Python, Docker</p>
<p class="t" style="left:30pt;top:360pt;font-size:8pt;font-weight:bold">Langages :</p>
<p class="t" style="left:30pt;top:372pt;font-size:8pt">Python, SQL</p>
<p class="t" style="left:30pt;top:420pt;font-size:8pt">Curiosité</p>
<p class="t" style="left:30pt;top:432pt;font-size:8pt">Rigueur</p>
<p class="t h" style="left:30pt;top:530pt">E X P É R I E N C E S</p>
<p class="t" style="left:30pt;top:550pt;font-size:8pt">
  <b>2023 - 2026 : Data scientist</b><i> - Transports Exemple -</i></p>
<p class="t" style="left:40pt;top:562pt;font-size:8pt">• Prévision de la demande par entrepôt.</p>
<p class="t" style="left:220pt;top:820pt;font-size:6pt;font-style:italic">Conçu pour une lecture responsable</p>
</div></body></html>"""


def photo_png() -> bytes:
    image = Image.new("RGB", (280, 340), "#d8c3a5")
    draw = ImageDraw.Draw(image)
    for step in range(0, 340, 4):
        draw.line(
            [(0, step), (280, step)],
            fill=(40 + step // 3, 90 + step // 5, 160 - step // 4),
        )
    draw.ellipse((80, 60, 200, 200), fill=(230, 190, 160))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def curve_png() -> bytes:
    """A cyan arc on a transparent ground, like the curves a design tool exports as images."""
    image = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    ImageDraw.Draw(image).arc(
        (20, 20, 380, 380), 180, 300, fill=(39, 182, 216, 255), width=10
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def designed_cv() -> bytes:
    """Written in Poppins, a font Rocky ships: its template needs no replacement."""
    html = PAGE.format(faces=font_faces())
    assets = {**font_assets(), "photo.png": photo_png(), "curve.png": curve_png()}
    return render_pdf(html, assets).pdf


def image_only_cv() -> bytes:
    html = '<!doctype html><html><body style="margin:0"><img src="photo.png" style="width:595pt"></body></html>'
    return render_pdf(html, {"photo.png": photo_png()}).pdf


def scanned_cv() -> bytes:
    """A page that is one picture, its text laid over it (like an exported image with a text layer)."""
    html = (
        f"<!doctype html><html><head><style>{font_faces()}"
        "@page { size: 595pt 842pt; margin: 0; } body { margin: 0; }"
        '</style></head><body><img src="photo.png" style="position:absolute; width:595pt; height:842pt">'
        '<p style="position:absolute; left:30pt; top:40pt; font: 26pt Poppins; color: transparent">'
        "CAMILLE MARTIN</p>"
        '<p style="position:absolute; left:30pt; top:90pt; font: 9pt Poppins; color: transparent">'
        "Data scientist issue de la logistique, je transforme des données opérationnelles.</p>"
        "</body></html>"
    )
    return render_pdf(html, {**font_assets(), "photo.png": photo_png()}).pdf


# The roles a careful reader gives to each line of the designed CV.
ROLES = (
    ("CAMILLE MARTIN", "name"),
    ("DATA SCIENTIST", "title"),
    ("Data scientist issue", "headline"),
    ("des données", "headline"),
    ("C O N T A C T", "heading"),
    ("camille.martin", "email"),
    ("06 00", "phone"),
    ("P R O J E T S", "heading"),
    ("Tri des messages", "project_name"),
    ("Problématique", "project_problem"),
    ("Stack technique", "project_stack"),
    ("Langages", "groups"),
    ("Python, SQL", "groups"),
    ("Curiosité", "transversal"),
    ("Rigueur", "transversal"),
    ("E X P É R I E N C E S", "heading"),
    ("2023 - 2026", "experiences"),
    ("- Transports", "experiences"),
    ("• Prévision", "experiences"),
    ("Conçu pour", "fixed"),
)

PROFILE: Mapping[str, Any] = {
    "full_name": "Camille Martin",
    "title": "Data Scientist",
    "headline": "Data scientist issue de la logistique, je transforme des données opérationnelles en outils "
    "de décision.",
    "email": "camille.martin@example.org",
    "phone": "06 00 00 00 00",
    "skill_groups": [{"name": "Langages", "skills": ["Python", "SQL"]}],
    "transversal": ["Curiosité", "Rigueur"],
    "languages": [{"name": "Anglais", "level": "c1"}],
    "hobbies": ["Randonnée"],
    "experiences": [
        {
            "kind": "job",
            "title": "Data scientist",
            "organisation": "Transports Exemple",
            "start_year": 2023,
            "end_year": 2026,
            "bullets": ["Prévision de la demande par entrepôt."],
        }
    ],
    "projects": [
        {
            "name": "Tri des messages clients",
            "problem": "Des milliers de messages",
            "stack": ["Python", "Docker"],
        }
    ],
}


# A line's start, its role, and when the model gives them, its project number and its label.
type Reading = tuple[str, str] | tuple[str, str, int, str | None]


class ReaderModel:
    """Fake language model: names each line of the prompt from ``roles``; ``skip`` leaves lines unnamed."""

    def __init__(
        self,
        *,
        skip: int = 0,
        roles: tuple[Reading, ...] = ROLES,
        labels: Mapping[str, str] = LABELS,
        profile: Mapping[str, Any] = PROFILE,
    ) -> None:
        self.prompts: list[str] = []
        self.skip = skip
        self.roles = roles
        self.labels = labels
        self.profile = profile

    def complete_json(
        self, instructions: str, prompt: str, schema: Mapping[str, Any]
    ) -> Any:
        self.prompts.append(prompt)
        roles = []
        for number, raw in re.findall(r"^\[(\d+)\][^:]*: (.*)$", prompt, re.MULTILINE):
            text = " ".join(raw.split())
            reading = next((r for r in self.roles if text.startswith(r[0])), None)
            if reading is None:
                continue
            role = reading[1]
            item: dict[str, Any] = {"id": int(number), "role": role}
            label = reading[3] if len(reading) == 4 else self.labels.get(role)
            if label is not None:
                item["label"] = label
            if len(reading) == 4:
                item["index"] = reading[2]
            roles.append(item)
        return {"roles": roles[self.skip :], "profile": dict(self.profile)}


# The second design (decision G5, Q3): one column, two project cards stacked, names ending with a colon.

LISTED_PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
{faces}
@page {{ size: 595pt 842pt; margin: 0; }}
body {{ margin: 0; font-family: "Poppins", sans-serif; }}
.page {{ position: relative; width: 595pt; height: 842pt; background: #ffffff; overflow: hidden; }}
.t {{ position: absolute; margin: 0; white-space: nowrap; font-size: 8pt; }}
.h {{ font-size: 11pt; font-weight: bold; color: #8a3b12; }}
</style></head><body><div class="page">
<svg style="position:absolute;left:0;top:0" width="595pt" height="842pt" viewBox="0 0 595 842">
  <rect x="0" y="0" width="595" height="90" fill="#f3e3d3"/>
  <rect x="40" y="300" width="515" height="100" rx="8" fill="#faf6f1" stroke="#8a3b12" stroke-width="1"/>
  <rect x="40" y="415" width="515" height="100" rx="8" fill="#faf6f1" stroke="#8a3b12" stroke-width="1"/>
  <path d="M40 532 L555 532" stroke="#8a3b12" stroke-width="1"/>
</svg>
<p class="t" style="left:40pt;top:30pt;font-size:22pt;font-weight:bold">LÉA DUPONT</p>
<p class="t" style="left:40pt;top:62pt;font-size:11pt">ANALYSTE DE DONNÉES</p>
<p class="t" style="left:40pt;top:110pt">lea.dupont@example.org</p>
<p class="t" style="left:300pt;top:110pt">07 00 00 00 00</p>
<p class="t h" style="left:40pt;top:150pt">COMPÉTENCES</p>
<p class="t" style="left:40pt;top:170pt"><b>Langages :</b> Python, SQL</p>
<p class="t" style="left:40pt;top:182pt"><b>Outils :</b> Docker, Airflow</p>
<p class="t" style="left:40pt;top:210pt">Rigueur · Écoute</p>
<p class="t h" style="left:40pt;top:275pt">PROJETS</p>
<p class="t" style="left:55pt;top:312pt;font-weight:bold">Prévision des stocks :</p>
<p class="t" style="left:55pt;top:328pt">Problème : Ruptures fréquentes en fin de mois dans</p>
<p class="t" style="left:55pt;top:340pt">les entrepôts régionaux.</p>
<p class="t" style="left:55pt;top:358pt">Stack : Python, Pandas</p>
<p class="t" style="left:55pt;top:374pt">Résultats : 30 % de ruptures en moins.</p>
<p class="t" style="left:55pt;top:427pt;font-weight:bold">Tri des messages :</p>
<p class="t" style="left:55pt;top:443pt">Problème : Des milliers de messages par jour.</p>
<p class="t" style="left:55pt;top:459pt">Stack : Python, FastAPI</p>
<p class="t" style="left:55pt;top:475pt">Résultats : 85 % des messages orientés.</p>
<p class="t h" style="left:40pt;top:545pt">EXPÉRIENCES</p>
<p class="t" style="left:40pt;top:565pt"><b>Analyste de données</b> · Commerce Exemple · 2022 – 2026</p>
</div></body></html>"""

LISTED_LABELS = {
    "project_problem": "Problème",
    "project_stack": "Stack",
    "project_results": "Résultats",
}

# A careful reading: the projects numbered from the top, each line with its own part.
LISTED_ROLES: tuple[Reading, ...] = (
    ("LÉA DUPONT", "name"),
    ("ANALYSTE", "title"),
    ("lea.dupont", "email"),
    ("07 00", "phone"),
    ("COMPÉTENCES", "heading"),
    ("Langages", "groups"),
    ("Outils", "groups"),
    ("Rigueur", "transversal"),
    ("PROJETS", "heading"),
    ("Prévision des stocks", "project_name", 0, None),
    ("Problème : Ruptures", "project_problem", 0, "Problème"),
    ("les entrepôts", "project_problem", 0, "Problème"),
    ("Stack : Python, Pandas", "project_stack", 0, "Stack"),
    ("Résultats : 30", "project_results", 0, "Résultats"),
    ("Tri des messages", "project_name", 1, None),
    ("Problème : Des milliers", "project_problem", 1, "Problème"),
    ("Stack : Python, FastAPI", "project_stack", 1, "Stack"),
    ("Résultats : 85", "project_results", 1, "Résultats"),
    ("EXPÉRIENCES", "heading"),
    ("Analyste de données", "experiences"),
)

# Another call on the same lines (D2: two calls never sorted them alike): projects numbered the other way, the second
# line of a part taken for a name, a part given the label of another.
LISTED_ROLES_OTHERWISE: tuple[Reading, ...] = (
    *LISTED_ROLES[:9],
    ("Prévision des stocks", "project_name", 1, None),
    ("Problème : Ruptures", "project_problem", 1, "Problème"),
    ("les entrepôts", "project_name", 1, None),
    ("Stack : Python, Pandas", "project_stack", 1, "Stack"),
    ("Résultats : 30", "project_problem", 1, "Problème"),
    ("Tri des messages", "project_name", 0, None),
    ("Problème : Des milliers", "project_problem", 0, "Problème"),
    ("Stack : Python, FastAPI", "project_problem", 0, "Problème"),
    ("Résultats : 85", "project_results", 0, "Résultats"),
    *LISTED_ROLES[18:],
)

LISTED_PROFILE: Mapping[str, Any] = {
    "full_name": "Léa Dupont",
    "title": "Analyste de données",
    "email": "lea.dupont@example.org",
    "phone": "07 00 00 00 00",
    "skill_groups": [
        {"name": "Langages", "skills": ["Python", "SQL"]},
        {"name": "Outils", "skills": ["Docker", "Airflow"]},
    ],
    "transversal": ["Rigueur", "Écoute"],
    "experiences": [
        {
            "kind": "job",
            "title": "Analyste de données",
            "organisation": "Commerce Exemple",
            "start_year": 2022,
            "end_year": 2026,
            "bullets": [],
        }
    ],
    "projects": [
        {
            "name": "Prévision des stocks",
            "problem": "Ruptures fréquentes en fin de mois dans les entrepôts régionaux.",
            "stack": ["Python", "Pandas"],
            "results": "30 % de ruptures en moins.",
        },
        {
            "name": "Tri des messages",
            "problem": "Des milliers de messages par jour.",
            "stack": ["Python", "FastAPI"],
            "results": "85 % des messages orientés.",
        },
    ],
}


def listed_cv() -> bytes:
    return render_pdf(LISTED_PAGE.format(faces=font_faces()), dict(font_assets())).pdf


def listed_reader(*, otherwise: bool = False) -> ReaderModel:
    return ReaderModel(
        roles=LISTED_ROLES_OTHERWISE if otherwise else LISTED_ROLES,
        labels=LISTED_LABELS,
        profile=LISTED_PROFILE,
    )


TODAY = date(2026, 9, 29)


def imported(
    pdf: bytes, root: Path, model: ReaderModel | None = None, language: str = "fr"
) -> ImportedCv:
    return import_cv(
        pdf,
        model=model or ReaderModel(),
        files=FileStore(root),
        account_id=1,
        today=TODAY,
        language=language,
    )


@dataclass
class Shared:
    """One import of the designed CV, read by several tests."""

    root: Path
    result: ImportedCv
    model: ReaderModel

    def files(self) -> Mapping[str, bytes]:
        assert self.result.template is not None
        return FileStore(self.root).read_bundle(
            self.result.template.path, self.result.template.sha256
        )

    def proposals(self) -> Mapping[str, Any]:
        return read_proposals(FileStore(self.root), 1, self.result.proposals.sha256)[0]
