"""A fake model for the assistant (decision G4): its answers in order, the last one repeated; the prompts it read."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class Assistant:
    """``answers`` in order (the last one kept); an exception among them is raised."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []

    def complete_json(
        self, instructions: str, prompt: str, schema: Mapping[str, Any]
    ) -> Any:
        self.prompts.append(prompt)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer


def citing(text: str, *facts: str) -> dict[str, Any]:
    """An answer of the model citing ``facts``."""
    return {"reponse": text, "faits": list(facts), "sans_reponse": False}
