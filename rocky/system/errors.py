"""The base of the business errors whose message is for the user (step H1).

A route that forgets to catch one does not answer 500: the web shell's handler (``shell.show_user_error``) shows the
message and logs it. Pure: imported by the rules and models of the modules.
"""

from __future__ import annotations


class UserFacingError(Exception):
    """An error whose message is for the user, in French; each line of it is shown as is."""

    @property
    def lines(self) -> tuple[str, ...]:
        return tuple(str(self).splitlines())
