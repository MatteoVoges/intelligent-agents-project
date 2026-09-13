"""Login identity is per tab, not per browser.

The bug this guards: identity lived in `app.storage.user`, which is keyed by the session
cookie, so every tab of one browser shared it — and Chrome puts all incognito windows in a
single cookie jar. Logging in as a second user overwrote the first, and reloading either
window showed whichever account logged in last. Demonstrating multi-user isolation with two
windows on one machine is exactly the thing that breaks.

Tested here rather than through `nicegui.testing.User`: the simulated client performs no
websocket handshake, so `app.storage.tab` does not exist for it and the storage the real code
reads is never populated. Faking the two storage dicts tests the actual precedence rule.
"""

from types import SimpleNamespace

import pytest

from agentchat.ui import session


@pytest.fixture
def browser(monkeypatch):
    """One browser: several tab dicts, a single shared cookie dict."""
    cookie: dict = {}
    tabs: dict[str, dict] = {}
    current_tab = SimpleNamespace(name="tab-1")

    class _Storage:
        @property
        def tab(self) -> dict:
            return tabs.setdefault(current_tab.name, {})

        @property
        def user(self) -> dict:
            return cookie

    async def connected():
        return None

    monkeypatch.setattr(session, "app", SimpleNamespace(storage=_Storage()))
    monkeypatch.setattr(session, "context", SimpleNamespace(client=SimpleNamespace(connected=connected)))

    def switch_to(name: str) -> None:
        current_tab.name = name

    return SimpleNamespace(switch_to=switch_to, cookie=cookie, tabs=tabs)


async def test_a_second_login_in_another_tab_does_not_move_the_first(browser):
    browser.switch_to("tab-1")
    session.bind("id-alice", "alice")

    browser.switch_to("tab-2")
    session.bind("id-bob", "bob")
    assert (await session.current()).username == "bob"

    browser.switch_to("tab-1")
    assert (await session.current()).username == "alice"  # the regression: this was "bob"


async def test_a_tab_that_never_logged_in_has_no_identity(browser):
    browser.switch_to("tab-1")
    assert await session.current() is None


async def test_a_fresh_tab_adopts_the_browsers_last_login_and_pins_it(browser):
    """Convenience without the sharing: opening a new tab should not force a re-login, but
    the adopted account must stick even if someone logs in elsewhere afterwards."""
    browser.switch_to("tab-1")
    session.bind("id-alice", "alice")

    browser.switch_to("tab-2")  # never logged in
    assert (await session.current()).username == "alice"

    browser.switch_to("tab-3")
    session.bind("id-bob", "bob")

    browser.switch_to("tab-2")
    assert (await session.current()).username == "alice"  # pinned on first use, not re-adopted


async def test_logout_clears_only_the_calling_tab(browser):
    browser.switch_to("tab-1")
    session.bind("id-alice", "alice")
    browser.switch_to("tab-2")
    session.bind("id-bob", "bob")

    session.unbind()
    assert await session.current() is None

    browser.switch_to("tab-1")
    assert (await session.current()).username == "alice"
