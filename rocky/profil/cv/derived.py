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
from dataclasses import dataclass, replace
from io import BytesIO
from itertools import pairwise
from typing import Any, NoReturn

from markupsafe import Markup, escape
from PIL import Image, ImageChops, ImageFilter

from rocky.profil.cv.content import CvContent, CvEntry, Span
from rocky.profil.cv.library import (
    font_assets,
    font_faces,
    match_pdf_font,
    text_path,
)
from rocky.profil.cv.pdf_page import (
    Block,
    Box,
    PageError,
    PageLayout,
    PhotoFrame,
    Style,
    cut_svg,
    page_svg,
    photo_candidate,
    render_page,
)
from rocky.profil.cv.rendering import CvPdf, CvRefusedError, Photo, problems
from rocky.profil.cv.semantics import PROJECT_ROLES, BlockRole, Role
from rocky.profil.cv.template import Slots
from rocky.system.render import Rendered, render_image, render_pdf

FORMAT = "rocky-cv-gabarit/2"  # 2: the layer is an opaque image (1 was an SVG: black blocks in Apple's Preview)
TEMPLATE_FILE = "template.json"
LAYER_FR = (
    "calque-fr.png"  # design with its fixed texts (and the rubrics kept as they are)
)
LAYER_EN = "calque.png"  # design without any text
LAYER_DPI = 300  # the resolution of the design's own images
PHOTO_FILE = "photo-importee"  # + suffix: proposed to the profile, never shown by the template itself
ROOM = 1.0  # a region may grow by one line: fonts measure a hair differently than the design tool


# Building


@dataclass(frozen=True)
class DerivedTemplate:
    files: Mapping[str, bytes]  # stored as one immutable bundle (Q24)
    slots: Slots
    warnings: tuple[str, ...]  # replaced fonts (Q22)
    photo: Photo | None  # the photo found in the CV, proposed to the profile (Q20)


def derive(
    pdf: bytes,
    layout: PageLayout,
    roles: Sequence[BlockRole],
    name: str,
    titles: Sequence[tuple[tuple[int, ...], str]] = (),
    kept: frozenset[Role] = frozenset(),
) -> DerivedTemplate:
    """``kept``: rubrics the French CV shows as the imported one wrote them (the profile does not change them)."""
    page_area = layout.width * layout.height
    if any(
        image.box.width * image.box.height >= 0.8 * page_area for image in layout.images
    ):
        raise PageError(
            "Ce CV est une image de page (son texte y est superposé) : son design ne peut pas être séparé de "
            "ses textes, Rocky ne peut donc pas le reproduire. Ton CV sera rendu avec le gabarit neutre."
        )
    by_block = {role.block_id: _title_line(role, layout, titles) for role in roles}
    blocks = {block.id: block for block in layout.blocks}
    content_blocks = [
        blocks[r.block_id] for r in roles if r.role not in (Role.HEADING, Role.FIXED)
    ]
    changed_blocks = [
        blocks[r.block_id]
        for r in roles
        if r.role not in (Role.HEADING, Role.FIXED) and r.role not in kept
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
        text_areas=[b.box for b in changed_blocks],
        image_areas=photo_areas,
        decoration_areas=[region.room for region in regions if region.role not in kept],
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
        "photo": _photo_json(
            visible_photo(
                pdf, layer_fr.svg, photo.box, [b.box for b in content_blocks], layout
            )
        )
        if photo
        else None,
        "regions": [
            {**region.to_json(), "kept": region.role in kept} for region in regions
        ],
        "fixed": [
            {
                "box": _box_json(block.box),
                "role": by_block[block.id].role.value,
                "baseline": block.lines[0].baseline,
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
        LAYER_FR: _png(
            render_image(layer_fr.svg, layout.width, layout.height, LAYER_DPI)
        ),
        LAYER_EN: _png(
            render_image(layer_en.svg, layout.width, layout.height, LAYER_DPI)
        ),
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
    original: tuple[str, ...]  # its lines as the imported CV wrote them

    @property
    def room(self) -> Box:
        """The box, raised by half the leading (CSS sets a line in the middle of its line height, the PDF
        measures it from its ascent), plus one line of room below (fonts measure a hair differently)."""
        half = max((self.measure.line_height - self.measure.ink) / 2, 0)
        extra = self.measure.line_height * ROOM
        return Box(
            self.box.x - 1,
            self.box.y - 1 - half,
            self.box.width + 2,
            self.box.height + 1 + half + extra,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "original": list(self.original),
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
    ink: float  # height of one line as the PDF measures it (ascent to descent)
    gap: float  # extra space between two entries of a list (experiences), in points
    align: str  # left, center, right
    letter_spacing: float
    uppercase: bool
    indent: (
        float  # extra left margin of the lines after the first style change (bullets)
    )


def _by_column(layout: PageLayout, roles: Sequence[BlockRole]) -> list[BlockRole]:
    """Projects numbered by geometry, left to right: each project line belongs to the project whose name stands
    nearest above it horizontally (the model's numbers are not reliable across calls)."""
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
    """A project line without its own label continues the part above it, in the same project (the model may
    give it the next part): only the first line of « Stack technique : … » carries the label."""
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
            # Below a labelled part, even a line named as the project's title continues that part.
            fixed[i] = replace(item, role=current[item.index])
    return fixed


def _starts_with(text: str, label: str) -> bool:
    return (
        " ".join(text.split()).casefold().startswith(" ".join(label.split()).casefold())
    )


def _regions(layout: PageLayout, roles: Sequence[BlockRole]) -> list[Region]:
    blocks = {block.id: block for block in layout.blocks}
    roles = _continued(layout, _by_column(layout, roles))
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
                original=tuple(" ".join(line.text.split()) for line in lines),
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
        ink=statistics.median([line.box.height for line in lines])
        if lines
        else main.size,
        gap=round(statistics.median(wide), 2) if wide else 0.0,
        align=_align(lines, box),
        letter_spacing=statistics.median([line.letter_spacing for line in lines])
        if lines
        else 0.0,
        uppercase=sum(c.isalpha() for c in letters) > 3 and letters == letters.upper(),
        indent=_indent(lines),
    )


def _align(lines: Sequence[Any], box: Box) -> str:
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


def visible_photo(
    pdf: bytes, layer: str, box: Box, texts: Sequence[Box], layout: PageLayout
) -> PhotoFrame:
    """What the page shows of the photo: where the page differs from the layer without it, inside the image's box
    (content texts left aside). A circle clip leaves the corners of that part unchanged."""
    without = render_image(layer, layout.width, layout.height, 72)
    page = render_page(pdf, 72).resize(without.size)
    changed = (
        ImageChops.difference(page, without)
        .convert("L")
        .point(lambda v: 255 if v > 40 else 0)
    )
    inside = Image.new("L", changed.size, 0)
    inside.paste(255, (int(box.x), int(box.y), int(box.right) + 1, int(box.bottom) + 1))
    for text in texts:
        inside.paste(
            0,
            (
                int(text.x) - 1,
                int(text.y) - 1,
                int(text.right) + 2,
                int(text.bottom) + 2,
            ),
        )
    # Thin differences (anti-aliased edges of a curve crossing the image's box) go; the photo, a solid area, stays.
    solid = ImageChops.multiply(changed, inside).filter(ImageFilter.MinFilter(5))
    found = solid.getbbox()
    if found is None:
        return PhotoFrame(box, box, round=False)
    x0, y0, x1, y1 = (found[0] - 2, found[1] - 2, found[2] + 2, found[3] + 2)
    visible = Box(x0, y0, x1 - x0, y1 - y0)
    inset = max(2, int(min(visible.width, visible.height) * 0.08))
    corners = [
        (x0 + inset, y0 + inset),
        (x1 - inset, y0 + inset),
        (x0 + inset, y1 - inset),
        (x1 - inset, y1 - inset),
    ]
    round_clip = sum(changed.getpixel(point) == 0 for point in corners) >= 3
    return PhotoFrame(box, visible, round=round_clip)


def _title_line(
    role: BlockRole, layout: PageLayout, titles: Sequence[tuple[tuple[int, ...], str]]
) -> BlockRole:
    """The English of one line of a title, the whole translation spread over its lines, words in order."""
    if role.role is not Role.HEADING:
        return role
    for ids, english in titles:
        if role.block_id not in ids:
            continue
        tops = {block.id: block.box.y for block in layout.blocks}
        lines = sorted(ids, key=lambda i: tops.get(i, 0.0))
        spaced = len(english.split()) > 2 and all(len(w) == 1 for w in english.split())
        words = unspaced(english).split() if spaced else english.split()
        if len(words) < len(ids):
            # « S K I L L S T E C H N I C A L »: no word to spread over the lines, each line keeps its own English.
            return role
        share = -(
            -len(words) // len(lines)
        )  # ceiling: the first lines take the longer share
        position = lines.index(role.block_id)
        part = " ".join(words[position * share : (position + 1) * share])
        return replace(role, text_en=" ".join(part) if spaced else part)
    return role


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
    if template.get("format") != FORMAT:
        _old_format()
    layer = LAYER_FR if content.language == "fr" else LAYER_EN
    assets = {**font_assets(), "calque.png": files[layer]}
    if photo is not None:
        assets[f"photo.{photo.suffix}"] = photo.content
    rendered = render_pdf(html, assets)
    return rendered, html, (*problems(rendered), *_beyond_slots(template, content))


def derived_headings(files: Mapping[str, bytes], language: str) -> tuple[str, ...]:
    """The section titles of the template, as the CV writes them (checked by « Vérifier mon CV »)."""
    template = json.loads(files[TEMPLATE_FILE])
    return tuple(
        unspaced(text) if _spaced(text) else " ".join(text.split())
        for item in template["fixed"]
        if (text := item["text"][language]).strip() and item.get("role") == "heading"
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
        '<img class="layer" src="calque.png" alt="">',
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
    parts += [
        _fixed_html(item, content.language)
        for item in template["fixed"]
        if item["text"][content.language].strip()
    ]
    for region in template["regions"]:
        if region.get("kept") and content.language == "fr":
            # Drawn by the layer as the imported CV wrote it; its words, invisible, for PDF readers.
            parts.append(_kept_html(region))
            continue
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


def unspaced(text: str) -> str:
    """« P R O J E T S » → « PROJETS »: the shortest run of spaces parts two letters, a longer run two words."""
    runs = re.findall(r" +", text.strip())
    if not runs:
        return text.strip()
    letter = min(len(run) for run in runs)
    words = re.split(rf" {{{letter + 1},}}", text.strip())
    return " ".join(word.replace(" " * letter, "") for word in words)


def _spaced(text: str) -> bool:
    words = text.split()
    return len(words) > 2 and sum(len(word) == 1 for word in words) >= 0.8 * len(words)


def _fixed_html(item: Mapping[str, Any], language: str) -> str:
    """A fixed text of the design: drawn by the layer in French, as outlines in English; for PDF readers, the same
    words as invisible text, without the spaces a design puts between letters (Q12: headings read as words)."""
    box = item["box"]
    text = item["text"][language]
    words = unspaced(text) if _spaced(text) else " ".join(text.split())
    style = item["main"]
    hidden = (
        f"left:{box['x']}pt; top:{box['y']}pt; width:{box['width'] + 60}pt; "
        + _font_css(style)
        + "color:transparent; white-space:nowrap; overflow:visible;"
    )
    parts = [f'<div class="region" style="{hidden}">{escape(words)}</div>']
    if language != "fr":
        pitch = float(item.get("letter_spacing") or 0)
        drawn = words if _spaced(text) else text
        shape = text_path(
            drawn,
            style["family"],
            style["weight"],
            style["italic"],
            style["size"],
            pitch,
        )
        left = box["x"]
        if item.get("align") == "center" or _spaced(item["text"]["fr"]):
            # A spaced title stands centred where the French one stood.
            left = box["x"] + (box["width"] - shape.width) / 2
        top = float(item.get("baseline", box["y"] + shape.ascent)) - shape.ascent
        parts.append(
            f'<svg style="position:absolute; left:{left:.2f}pt; top:{top:.2f}pt; overflow:visible" '
            f'width="{shape.width}pt" height="{shape.height}pt" viewBox="0 0 {shape.width} {shape.height}">'
            f'<path d="{shape.d}" fill="{style["color"]}"/></svg>'
        )
    return "".join(parts)


def _kept_html(region: Mapping[str, Any]) -> str:
    style = (
        _box_css(region)
        + _font_css(region["main"])
        + f"line-height:{region['line_height']}pt; "
    )
    lines = "".join(f"<p>{escape(line)}</p>" for line in region.get("original", []))
    return f'<div class="region" style="{style} color:transparent;">{lines}</div>'


OLD_FORMAT = (
    "Ton gabarit date d'une version de Rocky qui l'affichait mal dans certains lecteurs de PDF : "
    "réimporte ton CV pour le refaire."
)


def _old_format() -> NoReturn:
    raise CvRefusedError((OLD_FORMAT,))


def _png(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _span(text: str, style: Mapping[str, Any], *, underline: bool = False) -> Markup:
    css = _font_css(style) + ("text-decoration:underline; " if underline else "")
    return Markup('<span style="{}">{}</span>').format(Markup(css), text)


def _strong(region: Mapping[str, Any], text: str) -> Markup:
    return _span(text, region["strong"])


def _soft(region: Mapping[str, Any], text: str) -> Markup:
    return _span(text, region["soft"])


def _lines(items: Iterable[str | Markup]) -> str:
    return "".join(f"<p>{escape(item)}</p>" for item in items)


_LEAD = re.compile(r"^(.{2,60}?)( ?:) ")


def _led(region: Mapping[str, Any], text: str) -> Markup:
    """« Analyse de performance : suivi… », « Performance analysis: tracking… » → the lead in the strong style."""
    match = _LEAD.match(text)
    if match is None:
        return Markup("{}").format(text)
    lead = match.group(1) + match.group(2)
    return Markup("{}{}").format(_strong(region, lead + " "), text[match.end() :])


def _region_html(region: Mapping[str, Any], content: CvContent) -> str | None:
    role = Role(region["role"])
    index = int(region["index"])
    label = region["label"].get(content.language) or region["label"].get("fr", "")
    colon = (
        " :" if content.language == "fr" else ":"
    )  # French typography puts a space before it
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
            f"<p>{_strong(region, group.name + colon)}</p><p>{escape(', '.join(group.skills))}</p>"
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
        return "".join(_entry_html(region, entry, role, colon) for entry in entries)
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
    return f"<p>{_strong(region, label + colon)} {escape(text)}</p>"


def _entry_html(
    region: Mapping[str, Any], entry: CvEntry, role: Role, colon: str
) -> str:
    period = entry.period.replace(" – ", f" {region['dash']} ")
    indent = float(region.get("indent") or 0)
    gap = region.get("gap") or 0
    if role is Role.EXPERIENCES:
        head = Markup("{}{}").format(
            _strong(region, f"{period}{colon} {entry.title}"),
            _soft(region, f" - {entry.organisation} -"),
        )
        bullets = [_led(region, bullet) for bullet in entry.bullets]
    else:
        school = (
            f"{entry.organisation} - {entry.place}"
            if entry.place
            else entry.organisation
        )
        head = Markup("{}<br>{}").format(
            _strong(region, f"{period} - {entry.title}{colon}"),
            _span(school, region.get("plain", region["main"]), underline=True),
        )
        bullets = [_soft(region, bullet) for bullet in entry.bullets]
    # The text starts where the design's text starts; the bullet sits in the margin before it.
    dot = max(indent - float(region["main"]["size"]) * 1.2, 0)
    hang = indent - dot
    items = "".join(
        f'<span class="bullet" style="padding-left:{indent}pt">'
        f'<span style="display:inline-block; width:{hang:.1f}pt; margin-left:-{hang:.1f}pt">•</span>'
        f"{bullet}</span>"
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
