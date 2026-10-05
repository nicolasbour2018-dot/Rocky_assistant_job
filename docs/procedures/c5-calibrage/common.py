"""C5 calibration: what the sample, the page and the measure share (see README.md).

The archive (A1) gives the postings, the v1 scores and the applications; the development database gives the profile,
read only. Nothing is written.
"""

from __future__ import annotations

import csv
import importlib.util
import sys
from dataclasses import dataclass, replace
from datetime import date
from functools import cache
from pathlib import Path
from types import ModuleType
from typing import Any

HERE = Path(__file__).parent
# Same reference date as the C4 measure, so the measures stay comparable.
TODAY = date(2026, 9, 25)
PROFILE_ID = "1"
# Applications Nicolas would not make today (decision C5): 860 New York and 917 London, abroad being blocking (Q24);
# 272 "Quantitative consultant", 432 "BPCE", 655 "Responsable IA & Data", 752 "Business Analysis support Cash
# Management", jobs he no longer aims at (Q26).
LEFT_CONTROL = frozenset({"860", "917", "272", "432", "655", "752"})


@cache
def _c3_measure() -> ModuleType:
    """The C3 measure script (archive → collected offer), loaded under its own name: it is not a package."""
    path = HERE.parent / "c3-mesure" / "measure.py"
    spec = importlib.util.spec_from_file_location("c3_measure", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # its dataclasses look their module up
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class Archive:
    rows: dict[str, dict[str, str]]  # posting id → job_offers.csv row
    v1: dict[str, float]  # posting id → v1 score of the profile
    control: frozenset[str]  # postings Nicolas applied to (not withdrawn)

    @property
    def measured(self) -> list[str]:
        """The postings of the C4 measure: scored in v1, full description, from a source the new collection reads."""
        sources = _c3_measure().SOURCES
        return [
            identifier
            for identifier in self.v1
            if self.rows[identifier]["description_is_full"] == "True"
            and self.rows[identifier]["source_name"] in sources
        ]


def load_archive(archive: Path) -> Archive:
    csv.field_size_limit(sys.maxsize)
    exports = archive / "exports" / "csv"
    with (exports / "job_offers.csv").open(newline="") as file:
        rows = {row["id"]: row for row in csv.DictReader(file)}
    with (exports / "job_matches.csv").open(newline="") as file:
        v1 = {row["job_id"]: float(row["score"]) for row in csv.DictReader(file) if row["profile_id"] == PROFILE_ID}
    with (exports / "applications.csv").open(newline="") as file:
        control = frozenset(
            row["job_id"]
            for row in csv.DictReader(file)
            if row["profile_id"] == PROFILE_ID and row["status"] != "RETIRÉE"
        ) - LEFT_CONTROL
    return Archive(rows=rows, v1=v1, control=control)


def scorer(profile_id: int) -> Any:
    """``score(row) -> Score`` with the profile of the development database (application container only)."""
    from rocky.offres.analysis.rules import account_skills, analyze
    from rocky.offres.scoring.rules import score, scoring_profile
    from rocky.profil.sql import SqlProfileStore
    from rocky.system.config import load_settings
    from rocky.system.db import create_db_engine

    with create_db_engine(load_settings().database_url).connect() as connection:
        profile = SqlProfileStore(connection).load(profile_id)
    skills = account_skills(skill.content for skill in profile.skills)
    reading = scoring_profile(profile)
    offer = _c3_measure().offer

    def scored(row: dict[str, str]) -> Any:
        posting = replace(offer(row), location=row["city"] or None, country=row["country"] or None)
        return score(analyze(posting, skills, today=TODAY), posting, reading, today=TODAY)

    return scored
