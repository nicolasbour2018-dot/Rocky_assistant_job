"""E5 captures → test data: keep of a rendered posting page only what the import reads.

Keeps the ``JobPosting`` JSON-LD blocks, ``<title>``, the ``canonical`` link and the ``og:`` tags, and the container of
the posting (Apec: ``.container-details-offer``) without scripts, styles, images, map nor forms; e-mail addresses are
neutralised. Usage: ``uv run python docs/procedures/e5-captures/prepare.py <capture.json> <out.html>``; then read the
result again (no person's name, no address, no token) before committing it.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

CONTAINERS = (".container-details-offer",)
DROPPED = (
    "script",
    "style",
    "noscript",
    "svg",
    "img",
    "picture",
    "iframe",
    "aside",
    "form",
    "button",
)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def prepared(page_html: str, url: str) -> str:
    soup = BeautifulSoup(page_html, "html.parser")
    head: list[str] = [f"<title>{soup.title.get_text()}</title>"] if soup.title else []
    head.append(f'<link rel="canonical" href="{url}">')
    head.extend(str(tag) for tag in soup.find_all("meta", property=re.compile(r"^og:")))
    head.extend(
        str(tag)
        for tag in soup.find_all("script", attrs={"type": "application/ld+json"})
    )
    body: list[str] = []
    for selector in CONTAINERS:
        node = soup.select_one(selector)
        if node is None:
            continue
        for tag in node.find_all(DROPPED):
            tag.decompose()
        body.append(str(node))
    page = "<!doctype html><html><head>{}</head><body>{}</body></html>".format(
        "\n".join(head), "\n".join(body)
    )
    return EMAIL.sub("contact@example.org", page)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("out", type=Path)
    arguments = parser.parse_args(argv)
    data = json.loads(arguments.capture.read_text())
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(prepared(data["html"], data["url"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
