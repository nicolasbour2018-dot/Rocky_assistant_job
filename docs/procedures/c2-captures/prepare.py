"""C2 captures → recorded datasets of the import tests (``tests/offres/imports/data/<source>/``).

Each page keeps what the import reads: its JSON-LD blocks, its ``<title>``, ``canonical`` link and ``og:`` tags, and
its visible body. Everything else goes (other scripts, styles, images, forms), which also drops the trackers and
session tokens of the pages. A page holding a ``JobPosting`` is ``posting.html``, any other ``page.html``.
Usage: see README.md next to this file.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup, Comment, Tag

from rocky.offres.sources.rules import source_for_url

DATA = Path(__file__).resolve().parents[3] / "tests" / "offres" / "imports" / "data"
DROPPED = ("style", "noscript", "svg", "img", "picture", "iframe", "video", "form", "button", "input", "template")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PERSON_PROFILE = re.compile(r"linkedin\.com/in/")


def reduced(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script"):
        if isinstance(script, Tag) and script.get("type") != "application/ld+json":
            script.decompose()
    for tag in soup.find_all(DROPPED):
        tag.decompose()
    # The person who posted the offer (LinkedIn "message the recruiter" card): no name in a versioned file.
    # Employees filmed by the company (WTTJ "Rencontrez <prénom>" videos): first names, as in C1.
    for card in soup.select(".message-the-recruiter, [data-testid='block-videos-item']"):
        card.decompose()
    for profile in soup.find_all("a", href=PERSON_PROFILE):
        profile.decompose()
    for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
        comment.extract()
    for link in soup.find_all("link"):
        if isinstance(link, Tag) and "canonical" not in (link.get("rel") or []):
            link.decompose()
    for meta in soup.find_all("meta"):
        if isinstance(meta, Tag) and not str(meta.get("property", "")).startswith("og:"):
            meta.decompose()
    for tag in soup.find_all(True):
        if isinstance(tag, Tag):
            tag.attrs = {key: value for key, value in tag.attrs.items() if key in KEPT_ATTRIBUTES}
    text = str(soup)
    # No address of a recruiter in a versioned file.
    return EMAIL.sub("contact@exemple.fr", text)


# Attributes the import reads: JSON-LD and meta tags, canonical links, and the targeted description containers.
KEPT_ATTRIBUTES = {"type", "rel", "href", "property", "content", "id", "class", "data-testid", "data-test", "lang"}


def has_posting(html: str) -> bool:
    return '"JobPosting"' in html


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captures", type=Path, nargs="+", help="directories written by capture.py")
    arguments = parser.parse_args()
    for directory in arguments.captures:
        for entry in json.loads((directory / "manifest.json").read_text()):
            if entry["status"] != 200:
                print(f"{entry['file']}: HTTP {entry['status']}, ignoré")
                continue
            source = source_for_url(f"https://{entry['host']}") or "inconnu"
            if source == "apec":
                # An empty Angular shell: an Apec link is read through the public detail endpoint (C1 datasets).
                print(f"{entry['file']}: page Apec sans annonce, ignorée")
                continue
            html = (directory / entry["file"]).read_text()
            name = "posting.html" if has_posting(html) else "page.html"
            target = DATA / source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(reduced(html))
            print(f"{entry['file']} → {target.relative_to(DATA)} ({target.stat().st_size // 1024} Ko)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
