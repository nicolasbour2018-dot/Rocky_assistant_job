"""C2 captures: read a few real posting pages once and record what the platforms answer.

Records, per response: its status, its anti-bot headers and its body (``<n>-<host>.html`` and ``manifest.json``).
Stops at the first refusal (collection rule of C1, Q5). Usage: see README.md next to this file.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx2

from rocky.offres.sources.http import PublicHttp
from rocky.offres.sources.model import SourceError, SourceRefusedError

KEPT_HEADERS = ("content-type", "x-datadome", "cf-mitigated", "location")


class RecordingTransport(httpx2.BaseTransport):
    """Forwards each request and writes the response to ``out``."""

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
        name = f"{self._count:02d}-{request.url.host}.html"
        (self._out / name).write_bytes(body)
        self.manifest.append(
            {
                "file": name,
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
    parser.add_argument("urls", nargs="+", help="posting pages, read in this order")
    arguments = parser.parse_args()
    out: Path = arguments.out
    out.mkdir(parents=True, exist_ok=True)
    recorder = RecordingTransport(out)
    http = PublicHttp(transport=recorder, pause_seconds=2.0)
    try:
        for url in arguments.urls:
            try:
                page = http.get_text("la page", url)
                print(f"{url}: lue ({len(page)} caractères)")
            except SourceRefusedError as refused:
                print(f"{url}: {refused.reason}\nArrêt au premier refus : en parler à Nicolas.")
                break
            except SourceError as error:
                print(f"{url}: {error.reason}")
    finally:
        http.close()
        (out / "manifest.json").write_text(json.dumps(recorder.manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
