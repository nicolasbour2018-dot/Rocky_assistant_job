"""A CV template derived from an imported CV (decision D2, Q15, Q16, Q20–Q24), and its rendering.

The design is the imported page itself: its drawing (``pdf_page.page_svg``) with the content texts and the photo
taken out becomes a fixed layer; each content role (experiences, projects…) becomes a region at the place its
blocks occupied, with the fonts, sizes, colours, line spacing and alignment measured there. Only the texts change.
In French, the fixed texts of the design (section titles) stay in the layer; in English they are written again.
"""

from __future__ import annotations

import hashlib
import json
import re
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from io import BytesIO
from itertools import pairwise
from typing import Any

from markupsafe import Markup, escape

from rocky.profil.cv.content import CvContent, CvEntry, Span
from rocky.profil.cv.library import font_assets, font_faces, match_pdf_font
from rocky.profil.cv.pdf_page import (
    Block,
    Box,
    PageLayout,
    PhotoFrame,
    Style,
    cut_svg,
    page_svg,
    photo_candidate,
    photo_frame,
)
from rocky.profil.cv.rendering import CvPdf, CvRefusedError, Photo, problems
from rocky.profil.cv.semantics import PROJECT_ROLES, BlockRole, Role
from rocky.profil.cv.template import Slots
from rocky.system.render import Rendered, render_pdf

FORMAT = "rocky-cv-gabarit/1"
TEMPLATE_FILE = "template.json"
LAYER_FR = "calque-fr.svg"  # design with its fixed texts
LAYER_EN = "calque.svg"  # design without any text
PHOTO_FILE = "photo-importee"  # + suffix: proposed to the profile, never shown by the template itself
ROOM = 0.6  # a region may grow by this share of a line: fonts measure a hair differently than the design tool


# Building


@dataclass(frozen=True)
class DerivedTemplate:
    files: Mapping[str, bytes]  # stored as one immutable bundle (Q24)
    slots: Slots
    warnings: tuple[str, ...]  # replaced fonts (Q22)
    photo: Photo | None  # the photo found in the CV, proposed to the profile (Q20)


def derive(
    pdf: bytes, layout: PageLayout, roles: Sequence[BlockRole], name: str
) -> DerivedTemplate:
    by_block = {role.block_id: role for role in roles}
    blocks = {block.id: block for block in layout.blocks}
    content_blocks = [
        blocks[r.block_id] for r in roles if r.role not in (Role.HEADING, Role.FIXED)
    ]
    fixed_blocks = [
        blocks[r.block_id] for r in roles if r.role in (Role.HEADING, Role.FIXED)
    ]
    regions = _regions(layout, roles)
    photo = photo_candidate(layout)
    photo_areas = [photo.box] if photo else []
    svg = page_svg(pdf)
    decorations = [region.room for region in regions]
    layer_fr = cut_svg(
        svg,
        text_areas=[b.box for b in content_blocks],
        image_areas=photo_areas,
        decoration_areas=decorations,
    )
    layer_en = cut_svg(
        svg,
        text_areas=[b.box for b in (*content_blocks, *fixed_blocks)],
        image_areas=photo_areas,
        decoration_areas=decorations,
    )
    fonts = {style.font for block in layout.blocks for style in block.style_counts()}
    replaced = sorted(font for font in fonts if match_pdf_font(font).replaced)
    template: dict[str, Any] = {
        "format": FORMAT,
        "name": name,
        "page": {
            "width": layout.width,
            "height": layout.height,
            "background": layout.background,
        },
        "photo": _photo_json(photo_frame(pdf, photo.box, layout.background))
        if photo
        else None,
        "regions": [region.to_json() for region in regions],
        "fixed": [
            {
                "box": _box_json(block.box),
                # An empty English text continues the heading above it (translated whole on its first line).
                "text": {"fr": block.text, "en": by_block[block.id].text_en},
                **_style_json(_measure(block.lines, block.box)),
            }
            for block in fixed_blocks
        ],
        "slots": _slots_json(regions),
    }
    files: dict[str, bytes] = {
        TEMPLATE_FILE: json.dumps(template, ensure_ascii=False, indent=1).encode(),
        LAYER_FR: layer_fr.svg.encode(),
        LAYER_EN: layer_en.svg.encode(),
    }
    found = None
    if photo is not None:
        buffer = BytesIO()
        photo.image.convert("RGB").save(buffer, format="JPEG", quality=92)
        found = Photo(buffer.getvalue(), "jpg")
    return DerivedTemplate(
        files=files,
        slots=slots_of(template),
        warnings=tuple(
            f"La police « {font} » n'est pas dans Rocky : remplacée par « {match_pdf_font(font).family} »."
            for font in replaced
        ),
        photo=found,
    )


@dataclass(frozen=True)
class Region:
    role: Role
    index: int
    box: Box
    measure: Measure
    label: str
    label_en: str
    dash: str  # the separator written between two years (« 2018 - 2025 »)
    count: int  # lines of the region: the room of a list

    @property
    def room(self) -> Box:
        """The box, plus a little room below (the fonts of the design tool measure a hair differently)."""
        extra = self.measure.line_height * ROOM
        return Box(
            self.box.x - 1,
            self.box.y - 1,
            self.box.width + 2,
            self.box.height + 1 + extra,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "role": self.role.value,
            "index": self.index,
            "box": _box_json(self.room),
            "label": {"fr": self.label, "en": self.label_en or self.label},
            "dash": self.dash,
            "count": self.count,
            **_style_json(self.measure),
        }


@dataclass(frozen=True)
class Measure:
    main: Style
    strong: Style
    soft: Style
    plain: Style  # neither bold nor italic (the school of an education line)
    line_height: float
    gap: float  # extra space between two entries of a list (experiences), in points
    align: str  # left, center, right
    letter_spacing: float
    uppercase: bool
    indent: (
        float  # extra left margin of the lines after the first style change (bullets)
    )


def _regions(layout: PageLayout, roles: Sequence[BlockRole]) -> list[Region]:
    blocks = {block.id: block for block in layout.blocks}
    grouped: dict[tuple[Role, int], list[Block]] = defaultdict(list)
    labels: dict[tuple[Role, int], BlockRole] = {}
    for item in roles:
        if item.role in (Role.HEADING, Role.FIXED):
            continue
        # Only projects are numbered; any other rubric is one region, whatever index the model gave.
        key = (item.role, item.index if item.role in PROJECT_ROLES else 0)
        grouped[key].append(blocks[item.block_id])
        labels.setdefault(key, item)
    regions = []
    for (role, index), members in grouped.items():
        box = members[0].box
        for member in members[1:]:
            box = box.union(member.box)
        lines = [line for member in members for line in member.lines]
        text = " ".join(line.text for line in lines)
        dash = re.search(r"\d{4}\s*([-–—])\s*\d{4}", text)
        regions.append(
            Region(
                role=role,
                index=index,
                box=box,
                measure=_measure(lines, box),
                label=labels[(role, index)].label,
                label_en=labels[(role, index)].label_en,
                dash=dash.group(1) if dash else "–",
                count=len(lines),
            )
        )
    return regions


def _measure(lines: Sequence[Any], box: Box) -> Measure:
    counts: Counter[Style] = Counter()
    for line in lines:
        for run in line.runs:
            counts[run.style] += len(run.text.strip())
    main = counts.most_common(1)[0][0]
    strong = next((s for s, _ in counts.most_common() if s.bold), main)
    soft = next((s for s, _ in counts.most_common() if s.italic), main)
    plain = next(
        (s for s, _ in counts.most_common() if not s.bold and not s.italic), main
    )
    baselines = sorted(line.baseline for line in lines)
    steps = [b - a for a, b in pairwise(baselines) if b - a > 0.5 * main.size]
    line_height = (
        round(statistics.median(steps), 2) if steps else round(main.size * 1.3, 2)
    )
    wide = [step - line_height for step in steps if step > 1.5 * line_height]
    letters = "".join(line.text for line in lines)
    return Measure(
        main=main,
        strong=strong,
        soft=soft,
        plain=plain,
        line_height=min(line_height, main.size * 2.2),
        gap=round(statistics.median(wide), 2) if wide else 0.0,
        align=_align(lines, box),
        letter_spacing=statistics.median([line.letter_spacing for line in lines])
        if lines
        else 0.0,
        uppercase=sum(c.isalpha() for c in letters) > 3 and letters == letters.upper(),
        indent=_indent(lines),
    )


def _align(lines: Sequence[Any], box: Box) -> str:
    if len(lines) < 2:
        return "left"
    lefts = [line.box.x - box.x for line in lines]
    centres = [
        abs(line.box.x + line.box.width / 2 - (box.x + box.width / 2)) for line in lines
    ]
    rights = [box.right - line.box.right for line in lines]
    if max(centres) < 2.5 and max(lefts) > 3:
        return "center"
    if max(rights) < 2 and max(lefts) > 3:
        return "right"
    return "left"


def _indent(lines: Sequence[Any]) -> float:
    if not lines:
        return 0.0
    first = min(line.box.x for line in lines)
    others = sorted(line.box.x - first for line in lines if line.box.x - first > 3)
    return round(others[0], 1) if others else 0.0


def _slots_json(regions: Sequence[Region]) -> dict[str, int]:
    projects = {region.index for region in regions if region.role is Role.PROJECT_NAME}
    counts = {region.role: region for region in regions}
    groups = counts.get(Role.GROUPS)
    return {
        "projects": len(projects),
        "groups": max(1, _group_count(groups)) if groups else 0,
        "skills_per_group": 30,
        "transversal": counts[Role.TRANSVERSAL].count
        if Role.TRANSVERSAL in counts
        else 0,
        "hobbies": counts[Role.HOBBIES].count if Role.HOBBIES in counts else 0,
    }


def _group_count(region: Region | None) -> int:
    return 3 if region is None else max(1, min(8, region.count // 2))


def _photo_json(frame: PhotoFrame) -> dict[str, Any]:
    return {
        "image": _box_json(frame.image),
        "visible": _box_json(frame.visible),
        "round": frame.round,
    }


def slots_of(template: Mapping[str, Any]) -> Slots:
    slots = template.get("slots") or {}
    return Slots(
        projects=int(slots.get("projects", 0)),
        groups=int(slots.get("groups", 0)),
        skills_per_group=int(slots.get("skills_per_group", 30)),
        transversal=int(slots.get("transversal", 0)),
        hobbies=int(slots.get("hobbies", 0)),
    )


def _box_json(box: Box) -> dict[str, float]:
    return {
        "x": round(box.x, 2),
        "y": round(box.y, 2),
        "width": round(box.width, 2),
        "height": round(box.height, 2),
    }


def _style_json(measure: Measure) -> dict[str, Any]:
    return {
        "main": _one_style(measure.main),
        "strong": _one_style(measure.strong),
        "soft": _one_style(measure.soft),
        "plain": _one_style(measure.plain),
        "line_height": measure.line_height,
        "gap": measure.gap,
        "align": measure.align,
        "letter_spacing": measure.letter_spacing,
        "uppercase": measure.uppercase,
        "indent": measure.indent,
    }


def _one_style(style: Style) -> dict[str, Any]:
    font = match_pdf_font(style.font)
    return {
        "family": font.family,
        "weight": font.weight,
        "italic": font.italic,
        "size": style.size,
        "color": style.color,
        "pdf_font": style.font,
    }


# Rendering


def render_derived(
    files: Mapping[str, bytes], content: CvContent, photo: Photo | None
) -> CvPdf:
    """The CV in the account's template; refused with its reasons (English missing, overflow, beyond slots)."""
    if content.missing:
        raise CvRefusedError(
            (
                "Le CV anglais attend encore ces textes en anglais (profil) : "
                + " ; ".join(content.missing)
                + ".",
            )
        )
    rendered, html, reasons = draw_derived(files, content, photo)
    if reasons:
        raise CvRefusedError(reasons)
    template = json.loads(files[TEMPLATE_FILE])
    return CvPdf(
        pdf=rendered.pdf,
        html_sha256=hashlib.sha256(html.encode()).hexdigest(),
        template=str(template.get("name", "")),
    )


def draw_derived(
    files: Mapping[str, bytes], content: CvContent, photo: Photo | None
) -> tuple[Rendered, str, tuple[str, ...]]:
    """The rendering whatever its problems, with them: the import preview shows what went wrong."""
    template = json.loads(files[TEMPLATE_FILE])
    html = derived_html(
        template,
        content,
        with_photo=photo is not None,
        suffix=photo.suffix if photo else "jpg",
    )
    layer = LAYER_FR if content.language == "fr" else LAYER_EN
    assets = {**font_assets(), "calque.svg": files[layer]}
    if photo is not None:
        assets[f"photo.{photo.suffix}"] = photo.content
    rendered = render_pdf(html, assets)
    return rendered, html, (*problems(rendered), *_beyond_slots(template, content))


def derived_headings(files: Mapping[str, bytes], language: str) -> tuple[str, ...]:
    """The section titles of the template, as the CV writes them (checked by « Vérifier mon CV »)."""
    template = json.loads(files[TEMPLATE_FILE])
    return tuple(
        " ".join(item["text"][language].split())
        for item in template["fixed"]
        if " " not in item["text"][language].strip() or len(item["text"][language]) < 40
    )


def derived_html(
    template: Mapping[str, Any],
    content: CvContent,
    *,
    with_photo: bool,
    suffix: str = "jpg",
) -> str:
    page = template["page"]
    parts = [
        '<!doctype html><html><head><meta charset="utf-8"><style>',
        font_faces(),
        f"@page {{ size: {page['width']}pt {page['height']}pt; margin: 0; }}",
        "* { box-sizing: border-box; } html, body { margin: 0; padding: 0; }",
        (
            f".page {{ position: relative; width: {page['width']}pt; height: {page['height']}pt; "
            f"background: {page['background']}; overflow: hidden; }}"
        ),
        ".layer { position: absolute; left: 0; top: 0; width: 100%; height: 100%; }",
        ".region { position: absolute; overflow: hidden; white-space: normal; overflow-wrap: break-word; }",
        ".region p { margin: 0; } .entry { margin: 0; } .bullet { display: block; }",
        '</style></head><body><main class="page" data-box="page">',
        '<img class="layer" src="calque.svg" alt="">',
    ]
    photo = template.get("photo")
    if photo and with_photo:
        # The frame shows what the design showed; the image keeps its place and size inside it (Q15).
        shown, whole = photo["visible"], photo["image"]
        radius = "50%" if photo.get("round") else "0"
        parts.append(
            f'<div style="position:absolute; left:{shown["x"]}pt; top:{shown["y"]}pt; width:{shown["width"]}pt; '
            f'height:{shown["height"]}pt; border-radius:{radius}; overflow:hidden;">'
            f'<img src="photo.{suffix}" alt="" style="position:absolute; left:{whole["x"] - shown["x"]}pt; '
            f"top:{whole['y'] - shown['y']}pt; width:{whole['width']}pt; height:{whole['height']}pt; "
            'object-fit:cover;"></div>'
        )
    if content.language != "fr":
        parts += [
            _fixed_html(item, content.language)
            for item in template["fixed"]
            if item["text"][content.language].strip()
        ]
    for region in template["regions"]:
        inner = _region_html(region, content)
        if inner is None:
            continue
        name = escape(_region_name(region))
        style = _box_css(region) + _text_css(region)
        parts.append(
            f'<div class="region" data-box="{name}" style="{style}">{inner}</div>'
        )
    parts.append("</main></body></html>")
    return "\n".join(parts)


REGION_NAMES = {
    Role.NAME: "zone du nom",
    Role.TITLE: "zone du titre",
    Role.AGE: "zone de l'âge",
    Role.HEADLINE: "zone de l'accroche",
    Role.EMAIL: "zone de l'e-mail",
    Role.PHONE: "zone du téléphone",
    Role.CITY: "zone de la ville",
    Role.GROUPS: "zone des compétences techniques",
    Role.TRANSVERSAL: "zone des compétences transversales",
    Role.LANGUAGES: "zone des langues",
    Role.HOBBIES: "zone des loisirs",
    Role.EXPERIENCES: "zone des expériences",
    Role.EDUCATION: "zone des formations",
}


def _region_name(region: Mapping[str, Any]) -> str:
    role = Role(region["role"])
    if role.value.startswith("project_"):
        part = {
            Role.PROJECT_NAME: "nom",
            Role.PROJECT_PROBLEM: "problème",
            Role.PROJECT_STACK: "stack",
            Role.PROJECT_WORK: "réalisation",
            Role.PROJECT_RESULTS: "résultats",
        }[role]
        return f"zone du projet {region['index'] + 1} ({part})"
    return REGION_NAMES.get(role, role.value)


def _box_css(region: Mapping[str, Any]) -> str:
    box = region["box"]
    return f"left:{box['x']}pt; top:{box['y']}pt; width:{box['width']}pt; height:{box['height']}pt; "


def _font_css(style: Mapping[str, Any]) -> str:
    return (
        # Single quotes: this CSS goes into a style="…" attribute.
        f"font-family:'{style['family']}'; font-weight:{style['weight']}; "
        f"font-style:{'italic' if style['italic'] else 'normal'}; font-size:{style['size']}pt; color:{style['color']}; "
    )


def _text_css(region: Mapping[str, Any]) -> str:
    css = _font_css(region["main"])
    css += f"line-height:{region['line_height']}pt; text-align:{region['align']}; "
    if region.get("letter_spacing"):
        css += f"letter-spacing:{region['letter_spacing']}pt; "
    if region.get("uppercase"):
        css += "text-transform:uppercase; "
    return css


def _fixed_html(item: Mapping[str, Any], language: str) -> str:
    box = item["box"]
    # A translation may be longer: never cut, it may run past the old box.
    width = box["width"] + 40
    left = box["x"] - (20 if item["align"] == "center" else 0)
    css = f"left:{left}pt; top:{box['y']}pt; width:{width}pt; " + _text_css(item)
    text = item["text"][language]
    if item.get("letter_spacing"):
        # « S K I L L S » drawn with letter spacing: the letters without their spaces, words kept apart.
        text = re.sub(r"(?<=\S) (?=\S)", "", text)
        text = re.sub(r" {2,}", " ", text)
    lines = "".join(f"<p>{escape(line)}</p>" for line in text.split("\n"))
    return f'<div class="region" style="{css} overflow:visible;">{lines}</div>'


def _span(text: str, style: Mapping[str, Any], *, underline: bool = False) -> Markup:
    css = _font_css(style) + ("text-decoration:underline; " if underline else "")
    return Markup('<span style="{}">{}</span>').format(Markup(css), text)


def _strong(region: Mapping[str, Any], text: str) -> Markup:
    return _span(text, region["strong"])


def _soft(region: Mapping[str, Any], text: str) -> Markup:
    return _span(text, region["soft"])


def _lines(items: Iterable[str | Markup]) -> str:
    return "".join(f"<p>{escape(item)}</p>" for item in items)


def _led(region: Mapping[str, Any], text: str) -> Markup:
    """« Analyse de performance : suivi… » → the lead in the strong style, like the design writes it."""
    lead, separator, rest = text.partition(" : ")
    if separator and len(lead) <= 60:
        return Markup("{}{}").format(
            _strong(region, lead + separator.rstrip() + " "), rest
        )
    return Markup("{}").format(text)


def _region_html(region: Mapping[str, Any], content: CvContent) -> str | None:
    role = Role(region["role"])
    index = int(region["index"])
    label = region["label"].get(content.language) or region["label"].get("fr", "")
    simple = {
        Role.NAME: content.full_name,
        Role.TITLE: content.title,
        Role.AGE: content.age or "",
        Role.EMAIL: content.email or "",
        Role.PHONE: content.phone or "",
        Role.CITY: content.city or "",
    }
    if role in simple:
        if not simple[role]:
            return ""
        wrap = "" if role is Role.NAME else ' style="white-space:nowrap"'
        return f"<p{wrap}>{escape(simple[role])}</p>"
    if role is Role.HEADLINE:
        return "".join(
            f"<p>{_spans(region, paragraph)}</p>" for paragraph in content.headline
        )
    if role is Role.GROUPS:
        return "".join(
            f"<p>{_strong(region, group.name + ' :')}</p><p>{escape(', '.join(group.skills))}</p>"
            for group in content.groups
            if group.skills
        )
    if role is Role.TRANSVERSAL:
        return _lines(content.transversal)
    if role is Role.HOBBIES:
        return _lines(content.hobbies)
    if role is Role.LANGUAGES:
        return "".join(
            f"<p>{_strong(region, name)} ({escape(level)})</p>"
            for name, level in content.languages
        )
    if role in (Role.EXPERIENCES, Role.EDUCATION):
        entries = content.experiences if role is Role.EXPERIENCES else content.education
        return "".join(_entry_html(region, entry, role) for entry in entries)
    if index >= len(content.projects):
        return None
    project = content.projects[index]
    parts = {
        Role.PROJECT_NAME: project.name,
        Role.PROJECT_PROBLEM: project.problem,
        Role.PROJECT_STACK: ", ".join(project.stack),
        Role.PROJECT_WORK: project.work,
        Role.PROJECT_RESULTS: project.results,
    }
    text = parts[role]
    if not text:
        return ""
    if role is Role.PROJECT_NAME or not label:
        return _lines([text])
    return f"<p>{_strong(region, label + ' :')} {escape(text)}</p>"


def _entry_html(region: Mapping[str, Any], entry: CvEntry, role: Role) -> str:
    period = entry.period.replace(" – ", f" {region['dash']} ")
    indent = region.get("indent") or 0
    gap = region.get("gap") or 0
    if role is Role.EXPERIENCES:
        head = Markup("{}{}").format(
            _strong(region, f"{period} : {entry.title}"),
            _soft(region, f" - {entry.organisation} -"),
        )
        bullets = [_led(region, bullet) for bullet in entry.bullets]
    else:
        head = Markup("{}<br>{}").format(
            _strong(region, f"{period} - {entry.title} :"),
            _span(
                entry.organisation, region.get("plain", region["main"]), underline=True
            ),
        )
        bullets = [_soft(region, bullet) for bullet in entry.bullets]
    # A hanging bullet: the lines that follow start under the text, not under the bullet.
    hang = f"padding-left:{indent + 6}pt; text-indent:-6pt;"
    items = "".join(
        f'<span class="bullet" style="{hang}">•&nbsp;{bullet}</span>'
        for bullet in bullets
    )
    return f'<div class="entry" style="margin-bottom:{gap}pt"><p>{head}</p><p>{items}</p></div>'


def _spans(region: Mapping[str, Any], spans: Sequence[Span]) -> str:
    return "".join(
        str(_strong(region, span.text)) if span.bold else str(escape(span.text))
        for span in spans
    )


def _beyond_slots(template: Mapping[str, Any], content: CvContent) -> list[str]:
    slots = slots_of(template)
    found = []
    if len(content.projects) > slots.projects:
        found.append(
            f"Ton gabarit a {slots.projects} emplacement(s) de projet et ton CV maître en choisit "
            f"{len(content.projects)} : retires-en de ton CV maître."
        )
    return found
