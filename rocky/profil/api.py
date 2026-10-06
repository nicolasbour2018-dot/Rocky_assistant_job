"""What ``profil`` gives the other modules outside a request. The screen helpers that need one (``profile_of``,
``cv_document``…) stay with the routes, in ``web.py`` (decision H4).
"""

from __future__ import annotations

from sqlalchemy import Connection

from rocky.profil.model import Profile
from rocky.profil.sql import SqlProfileStore


def stored_profile(connection: Connection, account_id: int) -> Profile | None:
    """The account's profile for the other modules outside a request (the watch, the messages); None without one.

    Read only: unlike ``profile_of``, a missing profile is not created.
    """
    store = SqlProfileStore(connection)
    profile_id = store.find_profile_id(account_id)
    return None if profile_id is None else store.load(profile_id)
