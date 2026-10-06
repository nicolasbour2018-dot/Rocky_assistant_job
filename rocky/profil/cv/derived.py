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
from itertools import combinations, pairwise
from typing import Any, NoReturn

from markupsafe import Markup, escape
from PIL import Image

from rocky.profil.cv.check import Fact
from rocky.profil.cv.content import CvContent
from rocky.profil.cv.library import font_assets, font_faces, match_pdf_font, text_path
from rocky.profil.cv.pdf_page import (
    Block,
    Box,
    Line,
    PageError,
    PageLayout,
    Style,
    cut_svg,
    drawn_boxes,
    page_svg,
    photo_candidate,
)
from rocky.profil.cv.rendering import (
    MISSING_ENGLISH,
    CvPdf,
    CvRefusedError,
    Photo,
    problems,
)
from rocky.profil.cv.semantics import PROJECT_ROLES, BlockRole, Role
from rocky.profil.cv.template import Slots
from rocky.system.render import Rendered, render_image, render_pdf

# 6: a project name keeps its zone, a centred one may take its card's width (G5, recette);
# 5: a block's room is its own lines, or the card drawn around it (G5, Q2), and a project name keeps its colon;
# 4: also the page without any text and the kept texts in units, for its English version (D3, Q24);
# 3: only the variable blocks are regions (2: every rubric was; 1: the layer was an SVG, drawn black by Preview).
FORMAT = "rocky-cv-gabarit/6"
READABLE_FORMATS = frozenset({FORMAT})
TEMPLATE_FILE = "template.json"
LAYER = "calque.png"
LAYER_BARE = "calque-sans-texte.png"  # the design without any text: the layer of the English version (D3, Q8)
LAYER_DPI = 300  # the resolution of the design's own images
# The old texts' decorations (bullets, underlines) are erased down to one line below them (D2).
ERASED_BELOW = 1.0
# How a design may join items written on one line (« Rigueur · Écoute »), in the order they are looked for (G5, Q3).
# Never a comma nor a slash: one skill may hold them (« Gestion de projet / produit »).
LIST_SEPARATORS = (" · ", " | ", " • ")
# A shape around a text is a card, not the page's background, below this share of the page (G5, Q2).
CARD_MAX_SHARE = 0.5
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
    svg = page_svg(pdf)
    cards = _cards(layout, drawn_boxes(svg))
    regions = _regions(layout, roles, cards)
    erased = [region.pop("erased") for region in regions]
    cut = cut_svg(
        svg,
        text_areas=[block.box for block in changed],
        image_areas=(),
        decoration_areas=erased,
    )
    units = _units(kept)
    for unit in units:
        if unit["kind"] == "paragraph":
            card = _card_around(_unit_box(unit), cards)
            unit["card"] = None if card is None else _box_json(card)
    bare = cut_svg(
        svg,
        text_areas=[block.box for block in layout.blocks],
        image_areas=(),
        decoration_areas=[
            *erased,
            *(_unit_box(unit) for unit in units if unit["kind"] == "paragraph"),
        ],
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
        "units": units,
    }
    files = {
        TEMPLATE_FILE: json.dumps(template, ensure_ascii=False, indent=1).encode(),
        LAYER: _png(render_image(cut.svg, layout.width, layout.height, LAYER_DPI)),
        LAYER_BARE: _png(
            render_image(bare.svg, layout.width, layout.height, LAYER_DPI)
        ),
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
    """Projects numbered by geometry, in reading order: columns left to right, then top to bottom within a column
    (cards side by side or stacked, G5, Q3); each project line belongs to the nearest name above it in its column
    (the model's numbers are not reliable across calls)."""
    boxes = {block.id: block.box for block in layout.blocks}
    parts = [
        boxes[item.block_id]
        for item in roles
        if item.role in PROJECT_ROLES and item.role is not Role.PROJECT_NAME
    ]

    def follows_a_part(box: Box) -> bool:
        """Right under a part's line, in its column: the part going on, taken for a name (``_continued``)."""
        return any(
            part.x < box.right
            and box.x < part.right
            and 0 <= box.y - part.bottom < box.height
            for part in parts
        )

    # Names: name lines joined when they overlap horizontally and follow each other (a name may take two lines).
    names: list[Box] = []
    for box in sorted(
        (
            boxes[item.block_id]
            for item in roles
            if item.role is Role.PROJECT_NAME
            and not follows_a_part(boxes[item.block_id])
        ),
        key=lambda box: (box.y, box.x),
    ):
        joined = next(
            (
                k
                for k, name in enumerate(names)
                if box.x < name.right
                and name.x < box.right
                and box.y - name.bottom < box.height
            ),
            None,
        )
        if joined is None:
            names.append(box)
        else:
            names[joined] = names[joined].union(box)
    if not names:
        return list(roles)
    # Columns: the names overlapping horizontally.
    columns: list[Box] = []
    for name in sorted(names, key=lambda box: box.x):
        if columns and name.x < columns[-1].right:
            columns[-1] = columns[-1].union(name)
        else:
            columns.append(name)

    def column(box: Box) -> int:
        middle = box.x + box.width / 2
        return min(
            range(len(columns)),
            key=lambda i: abs(columns[i].x + columns[i].width / 2 - middle),
        )

    ordered = sorted(names, key=lambda name: (column(name), name.y))

    def project(box: Box) -> int:
        in_column = [k for k, name in enumerate(ordered) if column(name) == column(box)]
        above = [k for k in in_column if ordered[k].y <= box.y + 1]
        return above[-1] if above else in_column[0]

    return [
        replace(item, index=project(boxes[item.block_id]))
        if item.role in PROJECT_ROLES
        else item
        for item in roles
    ]


def _continued(layout: PageLayout, roles: Sequence[BlockRole]) -> list[BlockRole]:
    """A project line that opens with a label the answer attests elsewhere is that label's part (G5, Q3: the model
    may give it another part's label); any other line continues the part above it, in the same project (the model
    may give it another part, or take it for the project's name)."""
    boxes = {block.id: block.box for block in layout.blocks}
    texts = {block.id: block.text for block in layout.blocks}
    fixed = list(roles)
    attested = {
        item.label: item.role
        for item in fixed
        if item.role in PROJECT_ROLES
        and item.role is not Role.PROJECT_NAME
        and item.label
        and _starts_with(texts[item.block_id], item.label)
    }
    order = sorted(
        range(len(fixed)),
        key=lambda i: (boxes[fixed[i].block_id].y, boxes[fixed[i].block_id].x),
    )
    current: dict[int, Role] = {}
    for i in order:
        item = fixed[i]
        if item.role not in PROJECT_ROLES:
            continue
        if item.role is not Role.PROJECT_NAME and not (
            item.label and _starts_with(texts[item.block_id], item.label)
        ):
            opened = next(
                (
                    label
                    for label in attested
                    if _starts_with(texts[item.block_id], label)
                ),
                None,
            )
            if opened is not None:
                item = fixed[i] = replace(item, role=attested[opened], label=opened)
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


def _cards(layout: PageLayout, shapes: Sequence[Box]) -> tuple[Box, ...]:
    """The drawn shapes a text may sit in: not the page's background."""
    page_area = layout.width * layout.height
    return tuple(
        shape
        for shape in shapes
        if 0 < shape.width * shape.height < CARD_MAX_SHARE * page_area
    )


def _card_around(box: Box, cards: Sequence[Box]) -> Box | None:
    """The smallest card drawn around ``box`` (G5, Q2), None when it sits on the page itself."""
    around = [
        card
        for card in cards
        if card.contains(box.x, box.y, margin=1)
        and card.contains(box.right, box.bottom, margin=1)
        and card.width * card.height > box.width * box.height
    ]
    return min(around, key=lambda card: card.width * card.height, default=None)


def _room(
    box: Box, measure: Mapping[str, Any], card: Box | None, below: float | None
) -> Box:
    """Where a block's text may go (G5, Q2): its own lines, with their leading; in a drawn card, down and right to the
    card's inner edge, as far from it as the text stands from its left edge, never over the text below."""
    half = max((measure["line_height"] - measure["ink"]) / 2, 0)
    room = Box(box.x - 1, box.y - 1 - half, box.width + 2, box.height + 2 + 2 * half)
    if card is None:
        return room
    inset = max(box.x - card.x, 0)
    bottom = (
        card.bottom - inset if below is None else min(card.bottom - inset, below - 1)
    )
    return Box(
        room.x,
        room.y,
        max(card.right - inset - room.x, room.width),
        max(bottom - room.y, room.height),
    )


def _regions(
    layout: PageLayout, roles: Sequence[BlockRole], cards: Sequence[Box]
) -> list[dict[str, Any]]:
    """Skill groups, soft skills, and for each project its name and its body."""
    blocks = {block.id: block for block in layout.blocks}
    body_rooms: dict[int, Box] = {}  # the bodies come before the names (sorted by kind)
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
        if kind == "groups":
            # « Langages : Python, SQL » on one line (a bold name, then plain text), or the group's name on a line
            # of its own, its skills below (Nicolas's Canva): as the design writes it (G5, Q3).
            region["inline"] = any(
                any(run.style.bold and run.text.strip() for run in line.runs)
                and any(not run.style.bold and run.text.strip() for run in line.runs)
                for line in lines
            )
        if kind == "transversal":
            # « Rigueur · Écoute » on one line, or one skill per line (Nicolas's Canva): as the design writes it.
            region["separator"] = next(
                (
                    mark
                    for mark in LIST_SEPARATORS
                    if any(mark in line.text.strip() for line in lines)
                ),
                None,
            )
        if kind == "project_name":
            # « Tri des messages : » keeps its colon, written the way of the CV's language.
            region["colon"] = lines[-1].text.rstrip().endswith(":")
        # A project's name keeps its zone (D2, Q31): only its body grows in the card around it.
        card = None if kind == "project_name" else _card_around(box, cards)
        own = {id(block) for _, block in members}
        below = min(
            (
                block.box.y
                for block in layout.blocks
                if id(block) not in own
                and block.box.y >= box.bottom - 1
                and block.box.x < (card or box).right
                and block.box.right > box.x
            ),
            default=None,
        )
        region["room"] = _room(box, measure, card, below)
        if kind == "project_body" and card is not None:
            body_rooms[index] = region["room"]
        if (
            kind == "project_name"
            and measure["align"] == "center"
            and index in body_rooms
        ):
            # A centred name stands over its card: it may take the card's width, both sides alike (G5, recette).
            room, body = region["room"], body_rooms[index]
            left, right = min(room.x, body.x), max(room.right, body.right)
            region["room"] = Box(left, room.y, right - left, room.height)
        half = max((measure["line_height"] - measure["ink"]) / 2, 0)
        region["erased"] = Box(
            box.x - 1,
            box.y - 1 - half,
            box.width + 2,
            box.height + 1 + half + measure["line_height"] * ERASED_BELOW,
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


# The kept texts in units, for the English version (decision D3, Q16, Q20, Q21): a line that stands alone keeps its
# place; the lines of one paragraph or one bullet form a unit that flows in its box. Bold and italic runs are marked
# (``**…**``, ``_…_``) so that the translation keeps them.

# Never sent to the model, copied as they are (Q21).
PROTECTED_ROLES = frozenset({Role.NAME, Role.EMAIL, Role.PHONE, Role.CITY})
_CONTACT = re.compile(
    r"@|https?://|www\.|linkedin|github|^\+?[\d .()/-]{8,}$", re.IGNORECASE
)
_BULLET = re.compile(r"^\s*[•·▪●◦‣\-–—]\s")
RUBRIC_LABELS = {
    Role.NAME: "Nom",
    Role.TITLE: "Titre",
    Role.AGE: "Âge",
    Role.HEADLINE: "Accroche",
    Role.EMAIL: "E-mail",
    Role.PHONE: "Téléphone",
    Role.CITY: "Ville",
    Role.HEADING: "Titre de section",
    Role.FIXED: "Texte du design",
    Role.LANGUAGES: "Langues",
    Role.HOBBIES: "Loisirs",
    Role.EXPERIENCES: "Expériences",
    Role.EDUCATION: "Formations",
}


def _units(kept: Sequence[tuple[BlockRole, Block]]) -> list[dict[str, Any]]:
    entries = sorted(
        ((item.role, line) for item, block in kept for line in block.lines),
        key=lambda entry: (entry[1].box.y, entry[1].box.x),
    )
    groups: list[tuple[Role, list[Line]]] = []
    for role, line in entries:
        if not line.text.strip():
            continue
        home = next(
            (
                lines
                for other, lines in reversed(groups[-8:])
                if other is role and _continues(lines, line, role, entries)
            ),
            None,
        )
        if home is None:
            groups.append((role, [line]))
        else:
            home.append(line)
    units: list[dict[str, Any]] = []
    for index, (role, lines) in enumerate(groups):
        unit = _unit(index, role, lines)
        above = next(
            (other for other in reversed(units) if _stacks_on(other, unit)), None
        )
        if above is None:
            units.append(unit)
        else:
            _stack(above, unit)
    return units


def _stacks_on(above: Mapping[str, Any], unit: Mapping[str, Any]) -> bool:
    """A section title on two lines (« COMPÉTENCES » over « TECHNIQUES »): one title, translated as a whole."""
    if above["kind"] != "heading" or unit["kind"] != "heading":
        return False
    last = above.get("lines", [above])[-1]
    size = max(last["main"]["size"], unit["main"]["size"])
    step = unit["baseline"] - last["baseline"]
    left = max(last["box"]["x"], unit["box"]["x"])
    right = min(
        last["box"]["x"] + last["box"]["width"],
        unit["box"]["x"] + unit["box"]["width"],
    )
    narrower = min(last["box"]["width"], unit["box"]["width"])
    return bool(0 < step <= 2.2 * size and right - left >= 0.5 * narrower)


_HEADING_LINE = ("text", "box", "baseline", "main", "letter_spacing", "spaced", "align")


def _stack(above: dict[str, Any], unit: Mapping[str, Any]) -> None:
    """Join a title line to the one above: one text, each line keeping its place and its style."""
    lines = above.get("lines") or [{key: above[key] for key in _HEADING_LINE}]
    above["lines"] = [*lines, {key: unit[key] for key in _HEADING_LINE}]
    above["text"] = f"{above['text']} {unit['text']}"
    above["box"] = _box_json(_unit_box(above).union(_unit_box(unit)))


def _continues(
    lines: Sequence[Line], line: Line, role: Role, entries: Sequence[tuple[Role, Line]]
) -> bool:
    """The next line of a paragraph: the next baseline, the indent of the line above (past a text bullet, the indent
    of its text), the line above filled to its column's width or too full for the next word (a wrapped line), and not
    a new item: a bullet, or a line opening in bold like the first one, after a sentence or another line opening in
    bold (« **Français** (Langue maternelle) » then « **Anglais** (écrit et parlé) - C1 »)."""
    if role in PROTECTED_ROLES or role in (Role.HEADING, Role.TITLE, Role.AGE):
        return False
    last, first = lines[-1], lines[0]
    main = _main_style(lines)
    size = main.size
    step = line.baseline - last.baseline
    if not 0 < step <= 1.8 * size or _BULLET.match(line.text):
        return False
    indent = line.box.x - last.box.x
    past_bullet = len(lines) == 1 and _BULLET.match(first.text) and 0 < indent <= size
    if abs(indent) > 0.5 * size and not past_bullet:
        return False
    widest = max(
        other.box.right - first.box.x
        for kind, other in entries
        if kind is role and abs(other.box.x - first.box.x) <= 3 * size
    )
    filled = last.box.right - first.box.x
    if filled < 0.8 * widest and not _pushed_down(last, line, widest - filled):
        return False
    ended = last.text.rstrip().endswith(_ENDS) or _opens_strong(last, main)
    return not (ended and _opens_strong(first, main) and _opens_strong(line, main))


_ENDS = (".", ";", ":", "!", "?", ")")


def _pushed_down(last: Line, line: Line, room: float) -> bool:
    """The first word of ``line`` would not have fitted at the end of ``last``: a wrapped line, however short."""
    words = line.text.split()
    if not words:
        return False
    letter = line.box.width / max(len(line.text.strip()), 1)
    return (len(words[0]) + 1) * letter > room


def _opens_strong(line: Line, main: Style) -> bool:
    """The line's first words are bold in a text that is not."""
    run = next((run for run in line.runs if run.text.strip()), None)
    return run is not None and run.style.bold and not main.bold


def _main_style(lines: Sequence[Line]) -> Style:
    counts: Counter[Style] = Counter()
    for line in lines:
        for run in line.runs:
            counts[run.style] += len(run.text.strip())
    return counts.most_common(1)[0][0]


def _marked(lines: Sequence[Line], main: Style) -> str:
    """The text of the unit, its bold and italic runs marked; wrapped lines joined into one text."""
    parts = []
    for line in lines:
        text = ""
        for run in line.runs:
            if not run.text.strip():
                text += run.text
                continue
            core = run.text.strip()
            lead = run.text[: len(run.text) - len(run.text.lstrip())]
            tail = run.text[len(run.text.rstrip()) :]
            if run.style.bold and not main.bold:
                core = f"**{core}**"
            elif run.style.italic and not main.italic:
                core = f"_{core}_"
            text += lead + core + tail
        parts.append(" ".join(text.split()))
    return " ".join(parts).replace("** **", " ").replace("_ _", " ")


def _unit(index: int, role: Role, lines: Sequence[Line]) -> dict[str, Any]:
    box = lines[0].box
    for line in lines[1:]:
        box = box.union(line.box)
    main = _main_style(lines)
    styles = {run.style for line in lines for run in line.runs if run.text.strip()}
    strong = next((style for style in styles if style.bold and not main.bold), main)
    soft = next((style for style in styles if style.italic and not main.italic), main)
    measure = _measure(lines)
    text = _marked(lines, main)
    spaced = role is Role.HEADING and _spaced(text)
    return {
        "id": index,
        "role": role.value,
        "kind": "heading"
        if role is Role.HEADING
        else "paragraph"
        if len(lines) > 1
        else "line",
        "box": _box_json(box),
        "baseline": round(lines[0].baseline, 2),
        "text": unspaced(text) if spaced else text,
        "spaced": spaced,
        "letter_spacing": round(lines[0].letter_spacing, 2),
        "protected": role in PROTECTED_ROLES or bool(_CONTACT.search(text)),
        "main": _style_json(main),
        "strong": _style_json(strong),
        "soft": _style_json(soft),
        "line_height": measure["line_height"],
        "ink": measure["ink"],
        "align": measure["align"],
    }


def _spaced(text: str) -> bool:
    words = text.split()
    return len(words) > 2 and sum(len(word) == 1 for word in words) >= 0.8 * len(words)


def _unit_box(unit: Mapping[str, Any]) -> Box:
    box = unit["box"]
    return Box(box["x"], box["y"], box["width"], box["height"])


def _kept_line(block: Block) -> dict[str, Any]:
    runs = block.lines[0].runs
    return {
        "box": _box_json(block.box),
        "text": _words(block.text),
        "size": runs[0].style.size if runs else 8.0,
    }


def _words(text: str) -> str:
    """The words of a line; a title spaced letter by letter (« P R O J E T S ») read as « PROJETS »."""
    if _spaced(text):
        return unspaced(text)
    return " ".join(text.split())


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
    refuse_missing_variable_texts(content)
    rendered, html, reasons = draw_derived(files, content)
    if reasons:
        raise CvRefusedError(reasons)
    template = json.loads(files[TEMPLATE_FILE])
    return CvPdf(
        pdf=rendered.pdf,
        html_sha256=hashlib.sha256(html.encode()).hexdigest(),
        template=str(template.get("name", "")),
    )


def refuse_missing_variable_texts(content: CvContent) -> None:
    """Only the variable blocks come from the profile (Q29): the rest of the CV is the imported one."""
    missing = [m for m in content.missing if m.startswith(VARIABLE_TEXTS)]
    if missing:
        raise CvRefusedError((MISSING_ENGLISH + " ; ".join(missing) + ".",))


def draw_derived(
    files: Mapping[str, bytes], content: CvContent
) -> tuple[Rendered, str, tuple[str, ...]]:
    """The rendering whatever its problems, with them: the import preview shows what went wrong."""
    template = json.loads(files[TEMPLATE_FILE])
    if template.get("format") not in READABLE_FORMATS:
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
    # The English version: the layer has no text; every kept unit is written in its validated English (D3, Q20).
    if template.get("translated"):
        parts += [_unit_html(template, unit) for unit in template["units"]]
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
        between = " " if region.get("inline") else "</p><p>"
        return "".join(
            f"<p>{_strong(region, group.name + colon)}{between}{escape(', '.join(group.skills))}</p>"
            for group in content.groups
            if group.skills
        )
    if kind == "transversal":
        separator = region.get("separator")
        if separator:
            return f"<p>{escape(separator.join(content.transversal))}</p>"
        return _lines(content.transversal)
    if index >= len(content.projects):
        return None
    project = content.projects[index]
    if kind == "project_name":
        return _lines([project.name + (colon if region.get("colon") else "")])
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


_PROJECT_BOX = re.compile(r"^(?:zone du nom|carte) du projet (\d+)$")


def overflowing_projects(rendered: Rendered) -> tuple[int, ...]:
    """The positions (from 0) of the CV's projects whose card or name spills over: what to shorten (G5, recette)."""
    found = (_PROJECT_BOX.match(overflow.box) for overflow in rendered.overflows)
    return tuple(sorted({int(match.group(1)) - 1 for match in found if match}))


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


# The English version of a template (decision D3, Q8, Q16–Q21): the design without any text, each kept unit written
# in the English the user validated (names and contacts copied), the variable blocks from the profile as in French.

ENGLISH_NEEDS_REIMPORT = (
    "Ton gabarit français date d'une version précédente de Rocky : réimporte ton CV français pour préparer "
    "sa version anglaise."
)
_MARKS = re.compile(r"\*\*(.+?)\*\*|(?<!\w)_(.+?)_(?!\w)")


@dataclass(frozen=True)
class KeptText:
    """A text of the imported CV to translate for its English version: a kept unit (``u<id>``) or the label that
    opens a part of the project cards (``label:<text>``, once for all the cards)."""

    id: str
    where: str
    text: str


def kept_texts(files: Mapping[str, bytes]) -> tuple[KeptText, ...]:
    """The texts of a French template to translate (Q16); names and contacts are left out (Q21). Refused for a
    template made before its units were kept (Q24: import the CV again)."""
    template = json.loads(files[TEMPLATE_FILE])
    if template.get("format") != FORMAT or LAYER_BARE not in files:
        raise CvRefusedError((ENGLISH_NEEDS_REIMPORT,))
    units = [
        KeptText(f"u{unit['id']}", _unit_where(unit), unit["text"])
        for unit in template["units"]
        if not unit["protected"] and unit["text"].strip()
    ]
    labels = dict.fromkeys(
        part["label"]
        for region in template["regions"]
        for part in region.get("parts", [])
        if part["label"]
    )
    return (
        *units,
        *(
            KeptText(f"label:{label}", f"Étiquette des projets : « {label} »", label)
            for label in labels
        ),
    )


def english_template(
    files: Mapping[str, bytes],
    translations: Mapping[str, str],
    source_sha256: str,
    *,
    partial: bool = False,
) -> dict[str, bytes]:
    """The bundle of the English version of a French template: its layer without text, each unit with its English.

    ``partial``: a preview; a unit not translated yet keeps its French. Otherwise every unit must have its English.
    """
    template = json.loads(files[TEMPLATE_FILE])
    if template.get("format") != FORMAT or LAYER_BARE not in files:
        raise CvRefusedError((ENGLISH_NEEDS_REIMPORT,))
    units = []
    for unit in template["units"]:
        english = (
            unit["text"] if unit["protected"] else translations.get(f"u{unit['id']}")
        )
        if english is None:
            if not partial:
                raise ValueError(f"unit {unit['id']} has no English")
            english = unit["text"]
        units.append({**unit, "en": english})
    headings = [
        {"kind": FACT_KINDS[Role.HEADING], "text": _words(_plain(unit["en"]))}
        for unit in units
        if unit["kind"] == "heading" and unit["en"].strip()
    ]
    regions = [
        {
            **region,
            "parts": [
                {**part, "label": _label(part["label"], translations, partial)}
                for part in region.get("parts", [])
            ],
        }
        if "parts" in region
        else region
        for region in template["regions"]
    ]
    english = {
        **template,
        "regions": regions,
        "name": f"{template['name']} — version anglaise",
        "language": "en",
        "translated": True,
        "source_sha256": source_sha256,
        "units": [_with_room(template, unit) for unit in units],
        "kept": [],
        "facts": [
            *(f for f in template["facts"] if f["kind"] != FACT_KINDS[Role.HEADING]),
            *headings,
        ],
    }
    return {
        TEMPLATE_FILE: json.dumps(english, ensure_ascii=False, indent=1).encode(),
        LAYER: files[LAYER_BARE],
    }


def _label(label: str, translations: Mapping[str, str], partial: bool) -> str:
    if not label:
        return label
    english = translations.get(f"label:{label}")
    if english is None:
        if not partial:
            raise ValueError(f"label {label!r} has no English")
        return label
    return english


def _with_room(template: Mapping[str, Any], unit: Mapping[str, Any]) -> dict[str, Any]:
    """The room a text may take in English. A line: up to the next text on its right, and no farther than the texts
    of its column reach (a drawn line may stand past them). A paragraph: down to the next text below it."""
    box = unit["box"]
    left, end = box["x"], box["x"] + box["width"]
    top, bottom = box["y"], box["y"] + box["height"]
    texts = [other["box"] for other in template["units"] if other["id"] != unit["id"]]
    others = texts + [region["room"] for region in template["regions"]]
    right = min(
        (
            other["x"]
            for other in others
            if other["x"] >= end - 1
            and other["y"] < bottom
            and other["y"] + other["height"] > top
        ),
        default=template["page"]["width"] - 12,
    )
    column = max(
        (
            other["x"] + other["width"]
            for other in texts
            if other["x"] < end and other["x"] + other["width"] > left
        ),
        default=end,
    )
    below = min(
        (
            other["y"]
            for other in others
            if other["y"] >= bottom - 1
            and other["x"] < end
            and other["x"] + other["width"] > left
        ),
        default=template["page"]["height"] - 12,
    )
    return {
        **unit,
        "room_width": round(max(min(right, column) - left - 2, box["width"] + 2), 2),
        "room_bottom": round(below, 2),
    }


def _unit_where(unit: Mapping[str, Any]) -> str:
    text = _plain(unit["text"])
    short = text if len(text) <= 50 else text[:49] + "…"
    return f"{RUBRIC_LABELS.get(Role(unit['role']), unit['role'])} : « {short} »"


def _plain(text: str) -> str:
    return _MARKS.sub(lambda match: match.group(1) or match.group(2), text)


def _unit_html(template: Mapping[str, Any], unit: Mapping[str, Any]) -> str:
    text = unit["en"]
    if not text.strip():
        return ""
    if unit["kind"] == "heading":
        return _heading_html(unit, text)
    box = unit["box"]
    line_height = float(unit["line_height"])
    half = max((line_height - float(unit["ink"])) / 2, 0)
    top = box["y"] - 1 - half
    if unit["kind"] == "paragraph":
        # Its own lines; in a drawn card, down to the card's inner edge, never over the text below (G5, Q2).
        width, height = box["width"] + 2, box["height"] + 2 + 2 * half
        card = unit.get("card")
        if card is not None:
            inset = max(box["x"] - card["x"], 0)
            bottom = card["y"] + card["height"] - inset
            if "room_bottom" in unit:
                bottom = min(bottom, unit["room_bottom"])
            height = max(bottom - top, height)
        left, wrap = box["x"] - 1, "normal"
    else:
        width, height = unit["room_width"], line_height + 1
        left, wrap = box["x"] - 1, "nowrap"
        if unit["align"] == "center":
            grow = min(unit["room_width"] - box["width"], box["x"] - 12)
            left, width = box["x"] - 1 - grow / 2, box["width"] + 2 + grow
    style = (
        f"left:{left:.2f}pt; top:{top:.2f}pt; width:{width:.2f}pt; height:{height:.2f}pt; "
        + _font_css(unit["main"])
        + f"line-height:{line_height}pt; text-align:{unit['align']}; white-space:{wrap}; "
    )
    name = escape(f"zone « {_unit_where(unit)} »")
    return f'<div class="region" data-box="{name}" style="{style}">{_marked_html(unit, text)}</div>'


def _marked_html(unit: Mapping[str, Any], text: str) -> Markup:
    parts: list[Markup] = []
    position = 0
    for match in _MARKS.finditer(text):
        parts.append(escape(text[position : match.start()]))
        if match.group(1) is not None:
            parts.append(_styled(unit["strong"], match.group(1)))
        else:
            parts.append(_styled(unit["soft"], match.group(2)))
        position = match.end()
    parts.append(escape(text[position:]))
    return Markup("").join(parts)


def _styled(style: Mapping[str, Any], text: str) -> Markup:
    return Markup('<span style="{}">{}</span>').format(Markup(_font_css(style)), text)


def _heading_html(unit: Mapping[str, Any], text: str) -> str:
    """A section title drawn as outlines (its letter spacing kept, never read letter by letter), and its words as
    invisible text for PDF readers (decision D2, « Titres des sections »)."""
    words = _plain(text)
    lines = unit.get("lines") or [unit]
    first = lines[0]
    hidden = (
        f"left:{first['box']['x']}pt; top:{first['box']['y']}pt; width:{first['box']['width'] + 60}pt; "
        + _font_css(first["main"])
        + "color:transparent; white-space:nowrap; overflow:visible;"
    )
    shapes = "".join(
        _heading_line(line, part)
        for line, part in zip(
            lines, title_lines(words, [line["text"] for line in lines]), strict=True
        )
        if part
    )
    return f'<div class="region" style="{hidden}">{escape(words)}</div>{shapes}'


def _heading_line(line: Mapping[str, Any], words: str) -> str:
    box, style = line["box"], line["main"]
    shape = text_path(
        words,
        style["family"],
        style["weight"],
        style["italic"],
        style["size"],
        float(line.get("letter_spacing") or 0),
    )
    left = box["x"]
    if line["align"] == "center" or line["spaced"]:
        # A spaced title stands centred where the French one stood.
        left = box["x"] + (box["width"] - shape.width) / 2
    top = float(line["baseline"]) - shape.ascent
    return (
        f'<svg style="position:absolute; left:{left:.2f}pt; top:{top:.2f}pt; overflow:visible" '
        f'width="{shape.width}pt" height="{shape.height}pt" viewBox="0 0 {shape.width} {shape.height}">'
        f'<path d="{shape.d}" fill="{style["color"]}"/></svg>'
    )


def title_lines(words: str, french: Sequence[str]) -> list[str]:
    """The words of a translated title over the lines of the French one: the cut whose longest line, measured
    against its French line, is the shortest (« TECHNICAL SKILLS » over « COMPÉTENCES / TECHNIQUES »)."""
    tokens = words.split()
    count = len(french)
    if count <= 1 or len(tokens) <= 1:
        return [" ".join(tokens), *[""] * (count - 1)]
    if len(tokens) < count:
        return [*tokens, *[""] * (count - len(tokens))]

    def worst(cut: tuple[int, ...]) -> float:
        bounds = (0, *cut, len(tokens))
        return max(
            len(" ".join(tokens[start:end])) / max(len(line), 1)
            for (start, end), line in zip(pairwise(bounds), french, strict=True)
        )

    best = min(combinations(range(1, len(tokens)), count - 1), key=worst)
    bounds = (0, *best, len(tokens))
    return [" ".join(tokens[start:end]) for start, end in pairwise(bounds)]
