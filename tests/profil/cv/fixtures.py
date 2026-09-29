"""A fictional designed CV, made on the spot as a PDF, and a fake model that reads it (no network, no real person).

The page mimics what a design tool exports: a coloured background, shapes, a photo clipped to a circle, spaced
section titles, bullets and fixed texts.
"""

from __future__ import annotations

import io
import re
from collections.abc import Mapping
from typing import Any

from PIL import Image, ImageDraw

from rocky.profil.cv.library import font_assets, font_faces
from rocky.system.render import render_pdf

HEADINGS = {
    "C O N T A C T": "C O N T A C T",
    "E X P É R I E N C E S": "E X P E R I E N C E",
    "P R O J E T S": "P R O J E C T S",
}

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


def designed_cv() -> bytes:
    """Written in Poppins, a font Rocky ships: its template needs no replacement."""
    html = PAGE.format(faces=font_faces())
    return render_pdf(html, {**font_assets(), "photo.png": photo_png()}).pdf


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
    "transversal": ["Curiosité"],
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
        {"name": "Tri des messages clients", "problem": "Des milliers de messages"}
    ],
}


class ReaderModel:
    """Fake language model: names each line of the prompt from ``ROLES``; ``skip`` leaves lines unnamed."""

    def __init__(self, *, skip: int = 0) -> None:
        self.prompts: list[str] = []
        self.skip = skip

    def complete_json(
        self, instructions: str, prompt: str, schema: Mapping[str, Any]
    ) -> Any:
        self.prompts.append(prompt)
        roles = []
        for number, raw in re.findall(r"^\[(\d+)\][^:]*: (.*)$", prompt, re.MULTILINE):
            text = " ".join(raw.split())
            role = next((r for start, r in ROLES if text.startswith(start)), None)
            if role is None:
                continue
            item: dict[str, Any] = {"id": int(number), "role": role}
            if role == "heading":
                item["en"] = HEADINGS.get(text.strip(), text)
            if role == "fixed":
                item["en"] = "Designed for responsible reading"
            if role == "project_problem":
                item["label"], item["en"] = "Problématique", "Problem"
            roles.append(item)
        return {"roles": roles[self.skip :], "profile": dict(PROFILE)}
