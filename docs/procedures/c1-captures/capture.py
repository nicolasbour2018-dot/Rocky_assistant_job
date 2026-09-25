"""C1 captures: run the real connectors once and record what the platforms answer.

Records, per response: its status, its anti-bot headers and its body. Never the request URL, its parameters nor
its headers (API keys travel there). Usage: see README.md next to this file.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx2

from rocky.offres.sources.http import PublicHttp
from rocky.offres.sources.model import SourceCode, SourceError
from rocky.offres.sources.registry import build_sources
from rocky.offres.sources.model import SearchQuery
from rocky.offres.sources.usecases import collect, complete_descriptions
from rocky.system.config import SourcesSettings, load_settings

KEPT_HEADERS = ("content-type", "x-datadome", "cf-mitigated")


class RecordingTransport(httpx2.BaseTransport):
    """Forwards each request and writes the response to ``out`` (``<n>-<host>.<ext>`` and a manifest)."""

    def __init__(self, out: Path) -> None:
        self._inner = httpx2.HTTPTransport()
        self._out = out
        self._count = 0
        self.manifest: list[dict[str, object]] = []

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        response = self._inner.handle_request(request)
        body = response.read()
        response.close()
        self._count += 1
        kind = response.headers.get("content-type", "")
        extension = "json" if "json" in kind else "html"
        name = f"{self._count:02d}-{request.url.host}.{extension}"
        (self._out / name).write_bytes(body)
        self.manifest.append(
            {
                "file": name,
                "method": request.method,
                "host": request.url.host,
                "path": request.url.path,
                "status": response.status_code,
                "headers": {key: response.headers[key] for key in KEPT_HEADERS if key in response.headers},
            }
        )
        # The body is already decoded: the rebuilt response must not announce a compression any more.
        headers = [
            (key, value)
            for key, value in response.headers.multi_items()
            if key.lower() not in {"content-encoding", "content-length", "transfer-encoding"}
        ]
        return httpx2.Response(response.status_code, headers=headers, content=body)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path, help="output directory (outside the repository)")
    parser.add_argument("--only", choices=[code.value for code in SourceCode], action="append")
    parser.add_argument("--title", default="Data analyst")
    parser.add_argument("--location", default="Paris")
    arguments = parser.parse_args()
    out: Path = arguments.out
    out.mkdir(parents=True, exist_ok=True)
    try:
        settings = load_settings().sources
    except Exception:  # noqa: BLE001  (outside the container: no database settings, keys absent)
        settings = SourcesSettings()
    recorder = RecordingTransport(out)
    http = PublicHttp(transport=recorder, pause_seconds=2.0)
    sources = [
        source
        for source in build_sources(settings, http)
        if not arguments.only or source.code.value in arguments.only
    ]
    report = collect(sources, [SearchQuery(arguments.title, arguments.location)], limit=5)
    for outcome in report.outcomes:
        print(f"{outcome.source}: {outcome.status} · {len(outcome.offers)} offre(s) · {outcome.reason or ''}")
        for skipped in outcome.skipped:
            print(f"  requête sautée : {skipped.reason}")
    # One detail per source that has one: enough for a recorded dataset, and a refusal stops it anyway.
    firsts = {offer.source: offer for offer in reversed(report.offers) if not offer.description_complete}
    detail = complete_descriptions(sources, list(firsts.values()))
    for offer in detail.offers:
        state = "complète" if offer.description_complete else f"incomplète ({offer.incomplete_reason})"
        print(f"détail {offer.source}: {state}")
    http.close()
    (out / "manifest.json").write_text(json.dumps(recorder.manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SourceError as error:
        print(error.reason)
        sys.exit(1)
