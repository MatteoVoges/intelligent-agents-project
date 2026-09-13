"""Per-tab login state.

`app.storage.user` is keyed by the browser's session cookie, so every tab of a browser shares
one dict — and Chrome puts *all* incognito windows in a single cookie jar, so two "separate"
incognito logins overwrite each other. The page still looked right until it was rebuilt,
because the user id was captured in the page closure; a reload then handed both windows
whichever account logged in last.

Identity therefore lives in `app.storage.tab`, which NiceGUI keys by an id kept in the tab's
`sessionStorage`: private to one tab, distinct between windows, and it survives a reload. The
cookie storage is kept only as the "last login in this browser" hint a freshly opened tab
adopts, and a tab pins its account on first use so a later login elsewhere cannot move it.
"""

from __future__ import annotations

from dataclasses import dataclass

from nicegui import app
from nicegui import context


@dataclass(frozen=True)
class Session:
    user_id: str
    username: str


async def current() -> Session | None:
    """Account bound to the calling tab, or None if it has not logged in.

    Awaits the websocket: `app.storage.tab` does not exist before the tab announces its id.
    """
    await context.client.connected()
    tab = app.storage.tab
    if not tab.get("user_id"):
        # A brand-new tab has no identity of its own; adopt this browser's last login and
        # pin it immediately, so logging in elsewhere afterwards leaves this tab alone.
        fallback = app.storage.user.get("user_id")
        if not fallback:
            return None
        tab["user_id"] = fallback
        tab["username"] = app.storage.user.get("username", "")
    return Session(tab["user_id"], tab.get("username", ""))


def bind(user_id: str, username: str) -> None:
    """Log the calling tab in. Only valid from an event handler (the socket is up by then)."""
    app.storage.tab["user_id"] = user_id
    app.storage.tab["username"] = username
    app.storage.user["user_id"] = user_id
    app.storage.user["username"] = username


def unbind() -> None:
    app.storage.tab.pop("user_id", None)
    app.storage.tab.pop("username", None)
    app.storage.user.clear()
