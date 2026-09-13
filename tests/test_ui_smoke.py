"""Render both pages against a real NiceGUI client.

These pages are built entirely in Python at request time, so a bad Quasar prop or a stale
function signature only surfaces when the page is actually constructed — which, without this
test, would mean surfacing it during a live demo.
"""

import sys

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


def _log_in(monkeypatch, main_module, account) -> None:
    """Pretend `account` owns the tab that is about to open the page.

    The real lookup reads `app.storage.tab`, which needs a live websocket handshake the
    simulated client does not perform; stubbing it keeps these tests about rendering.
    """
    logged_in = main_module.session.Session(account.id, account.username)

    async def current():
        return logged_in

    monkeypatch.setattr(main_module.session, "current", current)


async def test_login_page_renders(user: User) -> None:
    await user.open("/login")
    await user.should_see("Francois")
    await user.should_see("Username")


async def test_main_page_renders_for_a_logged_in_user(user: User, monkeypatch) -> None:
    """Build the chat page with a seeded session.

    The session is stubbed rather than driven through the login form: NiceGUI's user
    simulation does not carry storage across a simulated click, and the point here is that
    the page itself constructs, not that the login button works.
    """
    from agentchat import config
    from agentchat import services
    from agentchat.ui import main as main_module

    account = services.get_or_create_user("alice")
    project = services.create_project(account.id, "Thesis")
    services.create_conversation(account.id, project.id, "qwen2.5-7b")
    services.create_conversation(account.id, None, "qwen2.5-7b")

    _log_in(monkeypatch, main_module, account)

    await user.open("/")
    await user.should_see("New chat")
    await user.should_see("Memory")
    await user.should_see("Tools")
    await user.should_see("Bonjour, alice.")  # the greeting names the logged-in user
    await user.should_see("Thesis")  # sidebar groups the chats under their project
    await user.should_see(config.DEFAULT_PROJECT_NAME)  # the unfiled chat is grouped too


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

    _log_in(monkeypatch, main_module, account)

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

    _log_in(monkeypatch, main_module, account)
    monkeypatch.setattr(main_module.engine, "generate", fake_generate)

    await user.open("/")
    user.find("Type a message…").type("count the words in a b c d")
    user.find("arrow_upward").click()

    await user.should_see("→ tool call: wordcount")
    await user.should_see("← wordcount output")
    await user.should_see("There are 4 words.")


async def test_unreachable_model_is_reported_on_the_message(user: User, monkeypatch) -> None:
    """A model whose server is down fails on send, in the chat, with the fix.

    This is the whole of the "is it loaded?" story since the selector stopped probing: the
    page offers every configured model unconditionally, and a dead endpoint is reported where
    it is discovered instead of being guessed at by a timer. The guess was the bug — a server
    busy generating misses a probe deadline and the model it is serving reads "not loaded".
    """
    from agentchat import services
    from agentchat.ui import main as main_module

    account = services.get_or_create_user("alice")

    async def fake_generate(conversation, user_text, **kwargs):
        raise ConnectionError("All connection attempts failed")
        yield  # unreachable; makes this an async generator like the real one

    _log_in(monkeypatch, main_module, account)
    monkeypatch.setattr(main_module.engine, "generate", fake_generate)

    await user.open("/")
    user.find("Type a message…").type("hello")
    user.find("arrow_upward").click()

    await user.should_see("did not answer")
    await user.should_see("All connection attempts failed")
    await user.should_see("bash serve.sh")  # the command that starts it


async def test_every_configured_model_is_selectable(user: User, monkeypatch) -> None:
    """No entry is greyed out or annotated by a probe — the labels are the labels."""
    from agentchat import config
    from agentchat import services
    from agentchat.ui import main as main_module

    account = services.get_or_create_user("alice")
    _log_in(monkeypatch, main_module, account)

    await user.open("/")
    options = main_module.config.MODELS
    assert len(options) >= 2, "the brief asks for at least two switchable models"
    for spec in options:
        assert "not loaded" not in spec.label
    await user.should_see(config.model_label(config.DEFAULT_MODEL_ID))


async def test_tool_events_are_folded_and_the_answer_sits_below_them(user: User, monkeypatch) -> None:
    """Tool calls render collapsed, and the answer renders after them.

    Both are easy to regress by reordering two lines: the bubble is created lazily *because*
    NiceGUI appends in call order, and a bubble made up front would float above the tool
    events it depends on. Element ids increase with creation, so they are the ordering check.
    """
    from nicegui import ui

    from agentchat import services
    from agentchat.ui import main as main_module

    account = services.get_or_create_user("alice")

    async def fake_generate(conversation, user_text, **kwargs):
        yield {"type": "tool_call", "name": "wordcount", "arguments": '{"text": "a b c d"}'}
        yield {"type": "tool_result", "name": "wordcount", "result": "4"}
        yield {"type": "token", "text": "There are 4 words."}
        yield {"type": "done", "content": "There are 4 words."}

    _log_in(monkeypatch, main_module, account)
    monkeypatch.setattr(main_module.engine, "generate", fake_generate)

    await user.open("/")
    user.find("Type a message…").type("count the words in a b c d")
    user.find("arrow_upward").click()
    await user.should_see("There are 4 words.")

    def only(label: str):
        (element,) = user.find(label).elements
        return element

    call, result = only("→ tool call: wordcount"), only("← wordcount output")
    for event in (call, result):
        assert isinstance(event, ui.expansion), "a tool event should be a fold, not a fixed block"
        assert event.value is False, "tool events start collapsed"

    answer = only("There are 4 words.")
    assert answer.id > result.id > call.id, "the answer belongs below the tools it used"
