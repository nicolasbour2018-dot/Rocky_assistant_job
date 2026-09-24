"""Every table of Rocky, registered on ``rocky.system.db.metadata``.

Imported by the Alembic environment and by the schema test: a table missing here is missing from the comparison
between declared tables and migrations.
"""

from __future__ import annotations

from rocky.system.auth.sql import account_tokens, accounts, sessions
from rocky.system.events import events

__all__ = ["account_tokens", "accounts", "events", "sessions"]
