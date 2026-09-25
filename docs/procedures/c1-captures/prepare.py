"""C1 captures: turn a capture directory into the recorded datasets of the tests (anonymized, reduced).

Reads ``manifest.json`` written by ``capture.py`` and writes ``tests/offres/sources/data/<source>/<name>``.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parents[3] / "tests" / "offres" / "sources" / "data"
NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
# Challenge URL parameters identify a browser session: never recorded.
CHALLENGE_PARAMETERS = re.compile(r"\b(initialCid|cid|hash|[bset])=[^&\"]+")


def destination(entry: dict[str, Any]) -> tuple[str, str] | None:
    host, path, status = str(entry["host"]), str(entry["path"]), int(entry["status"])
    if host == "www.apec.fr":
        if path.endswith("lieuautocomplete"):
            return None  # two answers (label, then "label -"): named in main()
        if path.endswith("rechercheOffre"):
            return "apec", "search.json"
        if path.endswith("offre/public"):
            return "apec", "detail-refused.json" if status == 403 else "detail.json"
    if host == "api.welcometothejungle.com":
        return "wttj", "search.json" if "/v3/" in path else "detail.json"
    if host == "www.linkedin.com":
        return "linkedin", "search.html"
    if host == "wellfound.com":
        return "wellfound", "role-location.html"
    if host == "api.adzuna.com":
        return "adzuna", "search.json"
    return None


def reduced(source: str, name: str, body: str) -> str:
    if source == "apec" and name == "detail-refused.json":
        return CHALLENGE_PARAMETERS.sub(r"\1=anonymized", body)
    if source == "wttj" and name == "detail.json":
        data = json.loads(body)
        # Company videos name employees ("Rencontrez Laurent…"): not needed, not kept.
        for key in ("cta_content", "videos"):
            data["job"].pop(key, None)
        return json.dumps(data, ensure_ascii=False, indent=1)
    if source == "wellfound":
        match = NEXT_DATA.search(body)
        if match is None:
            raise SystemExit("Wellfound: no __NEXT_DATA__ in the capture")
        return (
            '<!DOCTYPE html><html><body><script id="__NEXT_DATA__" type="application/json">'
            f"{match.group(1)}</script></body></html>\n"
        )
    if name.endswith(".json"):
        return json.dumps(json.loads(body), ensure_ascii=False, indent=1)
    return body


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    capture: Path = parser.parse_args().capture
    manifest = json.loads((capture / "manifest.json").read_text())
    for entry in manifest:
        target = destination(entry)
        if target is None:
            continue
        source, name = target
        body = (capture / str(entry["file"])).read_text()
        (DATA / source).mkdir(parents=True, exist_ok=True)
        (DATA / source / name).write_text(reduced(source, name, body))
        print(f"{entry['file']} → {source}/{name}")
    places = [entry for entry in manifest if str(entry["path"]).endswith("lieuautocomplete")]
    for entry, name in zip(places, ("places-paris.json", "places-paris-dash.json"), strict=False):
        body = (capture / str(entry["file"])).read_text()
        (DATA / "apec" / name).write_text(json.dumps(json.loads(body), ensure_ascii=False, indent=1))
        print(f"{entry['file']} → apec/{name}")


if __name__ == "__main__":
    main()
