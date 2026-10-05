"""Turn real job alerts into anonymised test data (step E3, ``docs/decisions/E3-alertes.md``).

Input: a JSON-lines export of alert messages (one object per line: ``sender``, ``address``, ``subject``,
``received_at``, ``body_text``, ``body_html``), made by the read-only query of this folder's README; it holds personal
data and stays out of the repository. Output: one JSON file per chosen alert, for ``tests/messages/data/alerts/``.

What is kept: the tag structure of the HTML, the visible text, the job identifiers of the platforms (public numbers).
What is removed or rewritten: every attribute but ``href``, images (tracking pixels), styles, scripts, comments; the
paths and parameters of the links (tracking tokens) — tracking links become ``https://<host>/clic/<n>``; the first
and last names of the recipient, his address and headline.

Usage: ``uv run python anonymize_alerts.py <export.jsonl> <out_dir> <address>:<n>:<name> ...``
(``n``: rank of the alert of ``address`` in the export, most recent first).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Comment, Tag

NAMES = (
    (re.compile(r"\bNICOLAS\b"), "CAMILLE"),
    (re.compile(r"\bNicolas\b"), "Camille"),
    (re.compile(r"\bBOUR\b"), "MARTIN"),
    (re.compile(r"\bBour\b"), "Martin"),
)
# The LinkedIn footer names the recipient with his headline, up to the end of its line.
RECIPIENT = re.compile(r"(destiné à|intended for)\s+[^\r\n<]*")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
URL = re.compile(r"https?://[^\s<>\"')\]]+")
LINKEDIN_JOB = re.compile(r"/jobs/view/(\d+)")
EFC_JOB = re.compile(r"^(/emploi-[^?#]*\.id\d+)")


class Links:
    """Rewrites the links of one alert: the same link always gets the same rewriting."""

    def __init__(self) -> None:
        self._seen: dict[str, str] = {}

    def __call__(self, url: str) -> str:
        if url not in self._seen:
            self._seen[url] = self._rewrite(url, len(self._seen) + 1)
        return self._seen[url]

    @staticmethod
    def _rewrite(url: str, n: int) -> str:
        if url.startswith("mailto:"):
            return "mailto:candidat@example.com"
        if not url.startswith(("http://", "https://")):
            return url  # an anchor (« # ») or a relative link carries nothing personal
        parts = urlsplit(url)
        host = parts.hostname or "example.invalid"
        job = LINKEDIN_JOB.search(parts.path)
        if host.endswith("linkedin.com") and job:
            return f"https://{host}/comm/jobs/view/{job.group(1)}/?trackingId=jeton{n}"
        efc = EFC_JOB.match(parts.path)
        if host.endswith("efinancialcareers.fr") and efc:
            return f"https://{host}{efc.group(1)}?stlt=jeton{n}"
        return f"https://{host}/clic/{n:04d}"


def anonymous_text(value: str, links: Links) -> str:
    value = URL.sub(lambda match: links(match.group(0)), value)
    value = RECIPIENT.sub(r"\1 Camille Martin", value)
    value = EMAIL.sub("candidat@example.com", value)
    for pattern, name in NAMES:
        value = pattern.sub(name, value)
    return value


def anonymous_html(value: str, links: Links) -> str:
    soup = BeautifulSoup(value, "html.parser")
    for tag in soup(["style", "script", "head", "meta", "title", "img", "link"]):
        tag.decompose()
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    for tag in soup.find_all(True):
        assert isinstance(tag, Tag)
        href = tag.get("href")
        tag.attrs = {}
        if isinstance(href, str) and href.strip():
            tag.attrs["href"] = links(href.strip())
    for string in soup.find_all(string=True):
        cleaned = anonymous_text(str(string), links)
        if cleaned != str(string):
            string.replace_with(cleaned)
    html = str(soup)
    return re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t]+", " ", html))


def anonymous_alert(row: dict[str, Any]) -> dict[str, Any]:
    links = Links()
    return {
        "sender": anonymous_text(row["sender"], links).replace(
            "candidat@example.com", row["address"]
        ),
        "subject": anonymous_text(row["subject"], links),
        "received_at": row["received_at"],
        "body_text": anonymous_text(row["body_text"], links),
        "body_html": anonymous_html(row["body_html"], links),
    }


def main(argv: list[str]) -> int:
    export, out_dir, *chosen = argv
    rows = [json.loads(line) for line in Path(export).read_text().splitlines() if line]
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    for choice in chosen:
        address, rank, name = choice.split(":")
        of_sender = [row for row in rows if row["address"] == address]
        alert = anonymous_alert(of_sender[int(rank)])
        path = target / f"{name}.json"
        path.write_text(json.dumps(alert, ensure_ascii=False, indent=1) + "\n")
        print(f"{path}: {len(alert['body_html'])} caractères HTML")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
