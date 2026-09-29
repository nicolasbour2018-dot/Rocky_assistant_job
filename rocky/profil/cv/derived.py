"""A CV template derived from an imported CV, and its rendering (decision D2, Q15, Q16, Q20, Q24, Q29–Q33).

The imported CV is up to date: only the blocks that follow the offer change — technical skills (groups), soft
skills, projects (Q29). Everything else stays as the imported CV drew it: the page itself, with the texts of the
variable blocks taken out, becomes one opaque image (the layer); each variable block becomes a region at the place
its lines occupied, with the fonts, sizes, colours, spacing and alignment measured there. A project is one region
that flows in its card, its parts one after the other (Q31). The lines kept in the layer are also written as
invisible text, so that PDF readers still read the whole CV. One template per language (Q33).
"""

from __future__ import annotations

import hashlib
import json
import re
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from io import BytesIO
from itertools import pairwise
from typing import Any, NoReturn

from markupsafe import Markup, escape
from PIL import Image

from rocky.profil.cv.check import Fact
from rocky.profil.cv.content import CvContent
from rocky.profil.cv.library import font_assets, font_faces, match_pdf_font
from rocky.profil.cv.pdf_page import (
    Block,
    Box,
    Line,
    PageError,
    PageLayout,
    Style,
    cut_svg,
    page_svg,
    photo_candidate,
)
from rocky.profil.cv.rendering import CvPdf, CvRefusedError, Photo, problems
from rocky.profil.cv.semantics import PROJECT_ROLES, BlockRole, Role
from rocky.profil.cv.template import Slots
from rocky.system.render import Rendered, render_image, render_pdf

# 3: only the variable blocks are regions (2: every rubric was; 1: the layer was an SVG, drawn black by Preview).
FORMAT = "rocky-cv-gabarit/3"
TEMPLATE_FILE = "template.json"
LAYER = "calque.png"
LAYER_DPI = 300  # the resolution of the design's own images
ROOM = 1.0  # a region may grow by one line: fonts measure a hair differently than the design tool
VARIABLE = frozenset({Role.GROUPS, Role.TRANSVERSAL}) | PROJECT_ROLES
PROJECT_PARTS = (
    Role.PROJECT_PROBLEM,
    Role.PROJECT_STACK,
    Role.PROJECT_WORK,
    Role.PROJECT_RESULTS,
)
# The places ``content.missing`` names for the variable blocks.
VARIABLE_TEXTS = ("Groupe", "Compétence", "Projet")
FACT_KINDS = {
    Role.NAME: "Nom",
    Role.EMAIL: "E-mail",
    Role.PHONE: "Téléphone",
    Role.HEADING: "Section",
}


# Building


@dataclass(frozen=True)
class DerivedTemplate:
    files: Mapping[str, bytes]  # stored as one immutable bundle (Q24)
    slots: Slots
    warnings: tuple[str, ...]  # replaced fonts (Q22)
    photo: (
        Photo | None
    )  # the photo found in the CV, proposed to the profile (for the neutral template)


def derive(
    pdf: bytes, layout: PageLayout, roles: Sequence[BlockRole], name: str, language: str
) -> DerivedTemplate:
    page_area = layout.width * layout.height
    if any(
        image.box.width * image.box.height >= 0.8 * page_area for image in layout.images
    ):
        raise PageError(
            "Ce CV est une image de page (son texte y est superposé) : son design ne peut pas être séparé de "
            "ses textes, Rocky ne peut donc pas le reproduire. Ton CV sera rendu avec le gabarit neutre."
        )
    roles = _continued(layout, _by_column(layout, roles))
    blocks = {block.id: block for block in layout.blocks}
    changed = [blocks[r.block_id] for r in roles if r.role in VARIABLE]
    kept = [(r, blocks[r.block_id]) for r in roles if r.role not in VARIABLE]
    regions = _regions(layout, roles)
    cut = cut_svg(
        page_svg(pdf),
        text_areas=[block.box for block in changed],
        image_areas=(),
        decoration_areas=[region["room"] for region in regions],
    )
    fonts = {style.font for block in layout.blocks for style in block.style_counts()}
    replaced = sorted(font for font in fonts if match_pdf_font(font).replaced)
    template: dict[str, Any] = {
        "format": FORMAT,
        "name": name,
        "language": language,
        "page": {"width": layout.width, "height": layout.height},
        "regions": [
            {**region, "room": _box_json(region["room"])} for region in regions
        ],
        "kept": [_kept_line(block) for _, block in kept],
        "facts": [
            {"kind": FACT_KINDS[role.role], "text": _words(block.text)}
            for role, block in kept
            if role.role in FACT_KINDS and block.text.strip()
        ],
        "slots": _slots(regions),
    }
    files = {
        TEMPLATE_FILE: json.dumps(template, ensure_ascii=False, indent=1).encode(),
        LAYER: _png(render_image(cut.svg, layout.width, layout.height, LAYER_DPI)),
    }
    found = photo_candidate(layout)
    photo = None
    if found is not None:
        buffer = BytesIO()
        found.image.convert("RGB").save(buffer, format="JPEG", quality=92)
        photo = Photo(buffer.getvalue(), "jpg")
    return DerivedTemplate(
        files=files,
        slots=slots_of(template),
        warnings=tuple(
            f"La police « {font} » n'est pas dans Rocky : remplacée par « {match_pdf_font(font).family} »."
            for font in replaced
        ),
        photo=photo,
    )


def _by_column(layout: PageLayout, roles: Sequence[BlockRole]) -> list[BlockRole]:
    """Projects numbered by geometry, left to right: each project line belongs to the project whose name stands
    nearest horizontally (the model's numbers are not reliable across calls)."""
    boxes = {block.id: block.box for block in layout.blocks}
    # Columns: the project names' lines, joined when they overlap horizontally (a name may take two lines).
    columns: list[Box] = []
    for box in sorted(
        (boxes[item.block_id] for item in roles if item.role is Role.PROJECT_NAME),
        key=lambda box: box.x,
    ):
        if columns and box.x < columns[-1].right:
            columns[-1] = columns[-1].union(box)
        else:
            columns.append(box)
    if not columns:
        return list(roles)

    def column(box: Box) -> int:
        middle = box.x + box.width / 2
        return min(
            range(len(columns)),
            key=lambda i: abs(columns[i].x + columns[i].width / 2 - middle),
        )

    return [
        replace(item, index=column(boxes[item.block_id]))
        if item.role in PROJECT_ROLES
        else item
        for item in roles
    ]


def _continued(layout: PageLayout, roles: Sequence[BlockRole]) -> list[BlockRole]:
    """A project line that does not open with its own label continues the part above it, in the same project
    (the model may give it another part, or take it for the project's name)."""
    boxes = {block.id: block.box for block in layout.blocks}
    texts = {block.id: block.text for block in layout.blocks}
    fixed = list(roles)
    order = sorted(
        range(len(fixed)),
        key=lambda i: (boxes[fixed[i].block_id].y, boxes[fixed[i].block_id].x),
    )
    current: dict[int, Role] = {}
    for i in order:
        item = fixed[i]
        if item.role not in PROJECT_ROLES:
            continue
        starts = item.label and _starts_with(texts[item.block_id], item.label)
        if item.role is not Role.PROJECT_NAME and starts:
            current[item.index] = item.role
        elif item.index in current and current[item.index] is not item.role:
            fixed[i] = replace(item, role=current[item.index])
    return fixed


def _starts_with(text: str, label: str) -> bool:
    return (
        " ".join(text.split()).casefold().startswith(" ".join(label.split()).casefold())
    )


def _regions(layout: PageLayout, roles: Sequence[BlockRole]) -> list[dict[str, Any]]:
    """Skill groups, soft skills, and for each project its name and its body."""
    blocks = {block.id: block for block in layout.blocks}
    grouped: dict[tuple[str, int], list[tuple[BlockRole, Block]]] = defaultdict(list)
    for item in roles:
        if item.role not in VARIABLE:
            continue
        kind = "project_body" if item.role in PROJECT_PARTS else item.role.value
        index = item.index if item.role in PROJECT_ROLES else 0
        grouped[(kind, index)].append((item, blocks[item.block_id]))
    regions = []
    for (kind, index), members in sorted(grouped.items()):
        lines = sorted(
            (line for _, block in members for line in block.lines),
            key=lambda line: line.box.y,
        )
        box = lines[0].box
        for line in lines[1:]:
            box = box.union(line.box)
        measure = _measure(lines)
        region: dict[str, Any] = {
            "kind": kind,
            "index": index,
            "count": len(lines),
            **measure,
        }
        if kind == "project_body":
            region["parts"] = _parts(members, measure["line_height"])
        half = max((measure["line_height"] - measure["ink"]) / 2, 0)
        region["room"] = Box(
            box.x - 1,
            box.y - 1 - half,
            box.width + 2,
            box.height + 1 + half + measure["line_height"] * ROOM,
        )
        regions.append(region)
    return regions


def _parts(
    members: Sequence[tuple[BlockRole, Block]], line_height: float
) -> list[dict[str, Any]]:
    """The parts of a project body in their order, each with its label and the space above it."""
    firsts: dict[Role, tuple[BlockRole, Line]] = {}
    lasts: dict[Role, Line] = {}
    for item, block in sorted(members, key=lambda member: member[1].box.y):
        line = block.lines[0]
        if item.role not in firsts:
            firsts[item.role] = (item, line)
        lasts[item.role] = line
    order = sorted(firsts, key=lambda role: firsts[role][1].box.y)
    parts = []
    previous: Role | None = None
    for role in order:
        item, first = firsts[role]
        gap = 0.0
        if previous is not None:
            gap = max(first.baseline - lasts[previous].baseline - line_height, 0.0)
        parts.append({"role": role.value, "label": item.label, "gap": round(gap, 2)})
        previous = role
    return parts


def _measure(lines: Sequence[Line]) -> dict[str, Any]:
    counts: Counter[Style] = Counter()
    for line in lines:
        for run in line.runs:
            counts[run.style] += len(run.text.strip())
    main = counts.most_common(1)[0][0]
    strong = next((s for s, _ in counts.most_common() if s.bold), main)
    baselines = sorted(line.baseline for line in lines)
    # Line spacing within a paragraph; the wider steps between two paragraphs are left out.
    steps = [
        b - a
        for a, b in pairwise(baselines)
        if 0.5 * main.size < b - a < 2.2 * main.size
    ]
    line_height = (
        round(statistics.median(steps), 2) if steps else round(main.size * 1.3, 2)
    )
    return {
        "main": _style_json(main),
        "strong": _style_json(strong),
        "line_height": line_height,
        "ink": statistics.median([line.box.height for line in lines]),
        "align": _align(lines),
    }


def _align(lines: Sequence[Line]) -> str:
    """Centred when the lines' middles vary much less than their starts (a design tool centres to a few points),
    right-aligned likewise with their ends."""
    if len(lines) < 2:
        return "left"
    lefts = [line.box.x for line in lines]
    middles = [line.box.x + line.box.width / 2 for line in lines]
    rights = [line.box.right for line in lines]
    spread = max(lefts) - min(lefts)
    if spread <= 6:
        return "left"
    if max(middles) - min(middles) < spread / 3:
        return "center"
    if max(rights) - min(rights) < spread / 3:
        return "right"
    return "left"


def _slots(regions: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    kinds = {region["kind"]: region for region in regions}
    projects = {
        region["index"] for region in regions if region["kind"] == "project_name"
    }
    groups = kinds.get("groups")
    return {
        "projects": len(projects),
        "groups": max(1, min(8, groups["count"] // 2)) if groups else 0,
        "skills_per_group": 30,
        "transversal": kinds["transversal"]["count"] if "transversal" in kinds else 0,
        # Hobbies stay as the imported CV wrote them (Q29): no limit from this template.
        "hobbies": 99,
    }


def slots_of(template: Mapping[str, Any]) -> Slots:
    slots = template.get("slots") or {}
    return Slots(
        projects=int(slots.get("projects", 0)),
        groups=int(slots.get("groups", 0)),
        skills_per_group=int(slots.get("skills_per_group", 30)),
        transversal=int(slots.get("transversal", 0)),
        hobbies=int(slots.get("hobbies", 99)),
    )


def _kept_line(block: Block) -> dict[str, Any]:
    runs = block.lines[0].runs
    return {
        "box": _box_json(block.box),
        "text": _words(block.text),
        "size": runs[0].style.size if runs else 8.0,
    }


def _words(text: str) -> str:
    """The words of a line; a title spaced letter by letter (« P R O J E T S ») read as « PROJETS »."""
    words = text.split()
    if len(words) > 2 and sum(len(word) == 1 for word in words) >= 0.8 * len(words):
        return unspaced(text)
    return " ".join(words)


def unspaced(text: str) -> str:
    """« P R O J E T S » → « PROJETS »: the shortest run of spaces parts two letters, a longer run two words."""
    runs = re.findall(r" +", text.strip())
    if not runs:
        return text.strip()
    letter = min(len(run) for run in runs)
    words = re.split(rf" {{{letter + 1},}}", text.strip())
    return " ".join(word.replace(" " * letter, "") for word in words)


def _box_json(box: Box) -> dict[str, float]:
    return {
        "x": round(box.x, 2),
        "y": round(box.y, 2),
        "width": round(box.width, 2),
        "height": round(box.height, 2),
    }


def _style_json(style: Style) -> dict[str, Any]:
    font = match_pdf_font(style.font)
    return {
        "family": font.family,
        "weight": font.weight,
        "italic": font.italic,
        "size": style.size,
        "color": style.color,
        "pdf_font": style.font,
    }


def _png(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


# Rendering


def render_derived(files: Mapping[str, bytes], content: CvContent) -> CvPdf:
    """The CV in the account's template; refused with its reasons (English missing, overflow, beyond slots)."""
    # Only the variable blocks come from the profile (Q29): the rest of the CV is the imported one.
    missing = [m for m in content.missing if m.startswith(VARIABLE_TEXTS)]
    if missing:
        raise CvRefusedError(
            (
                "Le CV anglais attend encore ces textes en anglais (profil) : "
                + " ; ".join(missing)
                + ".",
            )
        )
    rendered, html, reasons = draw_derived(files, content)
    if reasons:
        raise CvRefusedError(reasons)
    template = json.loads(files[TEMPLATE_FILE])
    return CvPdf(
        pdf=rendered.pdf,
        html_sha256=hashlib.sha256(html.encode()).hexdigest(),
        template=str(template.get("name", "")),
    )


def draw_derived(
    files: Mapping[str, bytes], content: CvContent
) -> tuple[Rendered, str, tuple[str, ...]]:
    """The rendering whatever its problems, with them: the import preview shows what went wrong."""
    template = json.loads(files[TEMPLATE_FILE])
    if template.get("format") != FORMAT:
        _old_format()
    html = derived_html(template, content)
    rendered = render_pdf(html, {**font_assets(), LAYER: files[LAYER]})
    return rendered, html, (*problems(rendered), *_beyond_slots(template, content))


def derived_facts(files: Mapping[str, bytes], content: CvContent) -> tuple[Fact, ...]:
    """What PDF readers must find (« Vérifier mon CV »): the kept name, contact and titles, the variable blocks."""
    template = json.loads(files[TEMPLATE_FILE])
    shown = slots_of(template).projects
    facts = [Fact(item["kind"], item["text"]) for item in template.get("facts", [])]
    facts += [
        Fact("Compétence", skill) for group in content.groups for skill in group.skills
    ]
    facts += [Fact("Compétence", skill) for skill in content.transversal]
    facts += [Fact("Projet", project.name) for project in content.projects[:shown]]
    return tuple(dict.fromkeys(facts))


def derived_html(template: Mapping[str, Any], content: CvContent) -> str:
    page = template["page"]
    parts = [
        '<!doctype html><html><head><meta charset="utf-8"><style>',
        font_faces(),
        f"@page {{ size: {page['width']}pt {page['height']}pt; margin: 0; }}",
        "* { box-sizing: border-box; } html, body { margin: 0; padding: 0; }",
        (
            f".page {{ position: relative; width: {page['width']}pt; "
            f"height: {page['height']}pt; overflow: hidden; }}"
        ),
        ".layer { position: absolute; left: 0; top: 0; width: 100%; height: 100%; }",
        # Lines break between words only: a word wider than its block is an overflow, said, never cut.
        ".region { position: absolute; overflow: hidden; }",
        ".region p { margin: 0; }",
        (
            ".kept { position: absolute; margin: 0; white-space: nowrap; color: transparent; "
            "font-family: 'Poppins'; }"
        ),
        '</style></head><body><main class="page" data-box="page">',
        f'<img class="layer" src="{LAYER}" alt="">',
    ]
    # The kept lines are in the layer image: their words, invisible, let PDF readers read the whole CV.
    parts += [
        f'<p class="kept" style="left:{line["box"]["x"]}pt; top:{line["box"]["y"]}pt; '
        f'font-size:{line["size"]}pt;">{escape(line["text"])}</p>'
        for line in template["kept"]
        if line["text"]
    ]
    colon = (
        " :" if content.language == "fr" else ":"
    )  # French typography puts a space before it
    for region in template["regions"]:
        inner = _region_html(region, content, colon)
        if inner is None:
            continue
        name = escape(_region_name(region))
        style = _box_css(region["room"]) + _text_css(region)
        parts.append(
            f'<div class="region" data-box="{name}" style="{style}">{inner}</div>'
        )
    parts.append("</main></body></html>")
    return "\n".join(parts)


def _region_html(
    region: Mapping[str, Any], content: CvContent, colon: str
) -> str | None:
    kind, index = region["kind"], int(region["index"])
    if kind == "groups":
        return "".join(
            f"<p>{_strong(region, group.name + colon)}</p><p>{escape(', '.join(group.skills))}</p>"
            for group in content.groups
            if group.skills
        )
    if kind == "transversal":
        return _lines(content.transversal)
    if index >= len(content.projects):
        return None
    project = content.projects[index]
    if kind == "project_name":
        return _lines([project.name])
    texts = {
        Role.PROJECT_PROBLEM.value: project.problem,
        Role.PROJECT_STACK.value: ", ".join(project.stack),
        Role.PROJECT_WORK.value: project.work,
        Role.PROJECT_RESULTS.value: project.results,
    }
    paragraphs: list[str] = []
    for part in region.get("parts", []):
        text = texts.get(part["role"], "")
        if not text:
            continue
        label = (
            _strong(region, part["label"] + colon) + Markup(" ")
            if part["label"]
            else Markup("")
        )
        gap = part["gap"] if paragraphs else 0
        paragraphs.append(f'<p style="margin-top:{gap}pt">{label}{escape(text)}</p>')
    return "".join(paragraphs)


REGION_NAMES = {
    "groups": "zone des compétences techniques",
    "transversal": "zone des compétences transversales",
}


def _region_name(region: Mapping[str, Any]) -> str:
    kind = region["kind"]
    if kind == "project_name":
        return f"zone du nom du projet {region['index'] + 1}"
    if kind == "project_body":
        return f"carte du projet {region['index'] + 1}"
    return REGION_NAMES.get(kind, str(kind))


def _box_css(box: Mapping[str, float]) -> str:
    return f"left:{box['x']}pt; top:{box['y']}pt; width:{box['width']}pt; height:{box['height']}pt; "


def _font_css(style: Mapping[str, Any]) -> str:
    return (
        # Single quotes: this CSS goes into a style="…" attribute.
        f"font-family:'{style['family']}'; font-weight:{style['weight']}; "
        f"font-style:{'italic' if style['italic'] else 'normal'}; font-size:{style['size']}pt; "
        f"color:{style['color']}; "
    )


def _text_css(region: Mapping[str, Any]) -> str:
    return (
        _font_css(region["main"])
        + f"line-height:{region['line_height']}pt; text-align:{region['align']}; "
    )


def _strong(region: Mapping[str, Any], text: str) -> Markup:
    return Markup('<span style="{}">{}</span>').format(
        Markup(_font_css(region["strong"])), text
    )


def _lines(items: Iterable[str]) -> str:
    return "".join(f"<p>{escape(item)}</p>" for item in items)


def _beyond_slots(template: Mapping[str, Any], content: CvContent) -> list[str]:
    slots = slots_of(template)
    if len(content.projects) > slots.projects:
        return [
            (
                f"Ton gabarit a {slots.projects} emplacement(s) de projet et ton CV maître en choisit "
                f"{len(content.projects)} : retires-en de ton CV maître."
            )
        ]
    return []


OLD_FORMAT = "Ton gabarit date d'une version précédente de Rocky : réimporte ton CV pour le refaire."


def _old_format() -> NoReturn:
    raise CvRefusedError((OLD_FORMAT,))
