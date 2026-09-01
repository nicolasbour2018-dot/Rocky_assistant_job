"""Planificateur de secours exécuté tant que Rocky local est ouvert.

Le cron système reste la voie documentée. Sur macOS, son installation peut
nécessiter une autorisation hors de Streamlit; ce scheduler garantit néanmoins
la même exécution à midi lorsque le serveur Rocky tourne.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

_scheduler: Any | None = None


def _launch_daily(project_dir: Path) -> None:
    """Lance la routine quotidienne hors du processus Streamlit pour ne pas le bloquer."""
    subprocess.Popen(
        [sys.executable, str(project_dir / "scripts" / "run_daily.py")],
        cwd=project_dir,
        start_new_session=True,
    )


def ensure_local_scheduler(project_dir: Path):
    """Démarre une seule tâche quotidienne à midi, heure de Paris."""
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    scheduler = BackgroundScheduler(timezone="Europe/Paris")
    scheduler.add_job(
        _launch_daily,
        CronTrigger(hour=12, minute=0, timezone="Europe/Paris"),
        args=[project_dir],
        id="rocky_daily_noon",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=6 * 60 * 60,
    )
    scheduler.start()
    _scheduler = scheduler
    return scheduler
