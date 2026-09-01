"""Démarre Rocky localement en arrière-plan et vérifie son état de santé.

Le processus, son PID et ses logs restent entièrement dans le dossier du
projet. Rocky écoute uniquement sur 127.0.0.1 : il n'est pas exposé au réseau.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

PROJECT_DIR = Path(__file__).resolve().parents[1]
LOGS_DIR = PROJECT_DIR / "logs"
PID_PATH = LOGS_DIR / "rocky_streamlit.pid"
LOG_PATH = LOGS_DIR / "rocky_streamlit.log"
HEALTH_URL = "http://127.0.0.1:8501/_stcore/health"


def _running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def _existing_pid() -> int | None:
    if not PID_PATH.is_file():
        return None
    try:
        pid = int(PID_PATH.read_text(encoding="utf-8").strip())
    except ValueError:
        return None
    return pid if _running(pid) else None


def _healthy() -> bool:
    try:
        with urlopen(HEALTH_URL, timeout=2) as response:
            return response.status == 200 and response.read().strip() == b"ok"
    except (OSError, URLError):
        return False


def main() -> int:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    existing = _existing_pid()
    if existing and _healthy():
        print(f"Rocky fonctionne déjà (PID {existing}).")
        print("URL : http://127.0.0.1:8501")
        return 0

    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "dashboard/dashboard_v2.py",
        "--server.address=127.0.0.1",
        "--server.port=8501",
        "--server.headless=true",
        "--server.fileWatcherType=none",
        "--browser.gatherUsageStats=false",
    ]
    with LOG_PATH.open("a", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            command,
            cwd=PROJECT_DIR,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    PID_PATH.write_text(str(process.pid), encoding="utf-8")

    for _ in range(30):
        if process.poll() is not None:
            print(f"ERREUR : Rocky s'est arrêté. Consulte {LOG_PATH}.")
            return 1
        if _healthy():
            print(f"OK Rocky local (PID {process.pid}).")
            print("URL : http://127.0.0.1:8501")
            print(f"Logs : {LOG_PATH}")
            return 0
        time.sleep(1)
    print(f"ERREUR : Rocky ne répond pas. Consulte {LOG_PATH}.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
