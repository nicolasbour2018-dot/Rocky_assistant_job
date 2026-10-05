"""What a CV template can hold (decision D2, Q26): its repeated slots bound the choices of the master CV."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Slots:
    projects: int
    groups: int
    skills_per_group: int
    transversal: int
    hobbies: int


# The neutral template flows: its bounds keep one A4 page readable (Q23).
NEUTRAL_NAME = "neutre"
NEUTRAL_SLOTS = Slots(
    projects=4, groups=4, skills_per_group=10, transversal=8, hobbies=6
)
