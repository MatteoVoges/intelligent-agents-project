"""Render both pages against a real NiceGUI client.

These pages are built entirely in Python at request time, so a bad Quasar prop or a stale
function signature only surfaces when the page is actually constructed — which, without this
test, would mean surfacing it during a live demo.
"""

import sys
from types import SimpleNamespace

import pytest
from nicegui.testing import User

pytest_plugins = ["nicegui.testing.user_plugin"]  # not `.plugin`, which drags in selenium


@pytest.fixture(autouse=True)
def _isolated_data(tmp_path, monkeypatch):
    # Drop the page modules so runpy re-executes their @ui.page decorators against the fresh
    # app instance each test gets. Only these — the db modules define SQLModel tables that
    # cannot be redefined on the same metadata.
    for name in ("agentchat.app", "agentchat.ui.main", "agentchat.ui.login"):
        sys.modules.pop(name, None)

    from agentchat import config
    from agentchat.db import database

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(database, "_engine", None, raising=False)
    database.init_db()


async def test_login_page_renders(user: User) -> None:
    await user.open("/login")
    await user.should_see("AgentChat")
    await user.should_see("Username")


async def test_main_page_renders_for_a_logged_in_user(user: User, monkeypatch) -> None:
    """Build the chat page with a seeded session.

    The session is stubbed rather than driven through the login form: NiceGUI's user
    simulation does not carry `app.storage.user` across a simulated click, and the point
    here is that the page itself constructs, not that the login button works.
    """
    from agentchat import services
    from agentchat.ui import main as main_module

    account = services.get_or_create_user("alice")
    services.create_project(account.id, "Thesis")
    services.create_conversation(account.id, None, "qwen2.5-7b")

    session = {"user_id": account.id, "username": account.username}
    monkeypatch.setattr(main_module, "app", SimpleNamespace(storage=SimpleNamespace(user=session)))

    await user.open("/")
    await user.should_see("New chat")
    await user.should_see("Memory")
    await user.should_see("Tools")


async def test_conversation_with_tool_history_renders(user: User, monkeypatch) -> None:
    """Replay a stored tool call/result pair through the page.

    Covers the tool-event rendering path, which type checks and linting cannot: the renderer
    is called from four places and a signature change silently breaks the ones not touched.
    """
    import json

    from agentchat import services
    from agentchat.ui import main as main_module

    account = services.get_or_create_user("alice")
    conv = services.create_conversation(account.id, None, "qwen2.5-7b")
    services.rename_conversation(conv.id, "Word counting")  # else it collides with the New chat button
    calls = [{"id": "c1", "type": "function", "function": {"name": "wordcount", "arguments": "{}"}}]
    services.add_message(conv.id, "user", "count the words")
    services.add_message(conv.id, "assistant", "", tool_calls=json.dumps(calls))
    services.add_message(conv.id, "tool", "4", tool_call_id="c1", name="wordcount")
    services.add_message(conv.id, "assistant", "There are 4 words.")

    session = {"user_id": account.id, "username": account.username}
    monkeypatch.setattr(main_module, "app", SimpleNamespace(storage=SimpleNamespace(user=session)))

    await user.open("/")
    user.find("Word counting").click()  # open the conversation from the sidebar
    await user.should_see("→ tool call: wordcount")
    await user.should_see("← wordcount output")
    await user.should_see("There are 4 words.")


async def test_streaming_tool_events_render(user: User, monkeypatch) -> None:
    """Drive a turn with a stubbed engine so the live event path is rendered.

    Separate from the stored-history test on purpose: the same events are rendered by two
    different code paths, and only this one covers the streaming branch.
    """
    from agentchat import services
    from agentchat.ui import main as main_module

    account = services.get_or_create_user("alice")

    async def fake_generate(conversation, user_text, **kwargs):
        yield {"type": "tool_call", "name": "wordcount", "arguments": '{"text": "a b c d"}'}
        yield {"type": "tool_result", "name": "wordcount", "result": "4"}
        yield {"type": "token", "text": "There are 4 words."}
        yield {"type": "done", "content": "There are 4 words."}

    session = {"user_id": account.id, "username": account.username}
    monkeypatch.setattr(main_module, "app", SimpleNamespace(storage=SimpleNamespace(user=session)))
    monkeypatch.setattr(main_module.engine, "generate", fake_generate)

    await user.open("/")
    user.find("Type a message…").type("count the words in a b c d")
    user.find("arrow_upward").click()

    await user.should_see("→ tool call: wordcount")
    await user.should_see("← wordcount output")
    await user.should_see("There are 4 words.")
