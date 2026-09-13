from types import SimpleNamespace

from agentchat.memory import store


def test_parse_facts_plain_json_array():
    assert store._parse_facts('["likes dark mode", "uses WSL2"]') == ["likes dark mode", "uses WSL2"]


def test_parse_facts_strips_markdown_fence():
    raw = '```json\n["prefers concise answers"]\n```'
    assert store._parse_facts(raw) == ["prefers concise answers"]


def test_parse_facts_empty_array_yields_nothing():
    assert store._parse_facts("[]") == []


def test_parse_facts_garbage_yields_nothing():
    assert store._parse_facts("not json at all") == []
    assert store._parse_facts("") == []


def test_parse_facts_ignores_non_string_entries():
    assert store._parse_facts('["ok", 42, null, "also ok"]') == ["ok", "also ok"]


def _fake_response(content: str):
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


class _FakeCompletions:
    def __init__(self, content: str):
        self._content = content
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return _fake_response(self._content)


class _FakeClient:
    def __init__(self, content: str):
        self.chat = SimpleNamespace(completions=_FakeCompletions(content))


async def test_extract_and_remember_saves_parsed_facts(monkeypatch):
    fake_client = _FakeClient('["remembers to bring an umbrella"]')
    monkeypatch.setattr("agentchat.inference.client.client", lambda _url=None: fake_client)

    remembered: list[tuple] = []
    monkeypatch.setattr(store, "remember", lambda *a: remembered.append(a))

    await store.extract_and_remember("proj-1", "conv-1", "will it rain?", "yes, bring an umbrella")

    assert remembered == [("proj-1", "remembers to bring an umbrella", "conv-1")]
    assert fake_client.chat.completions.calls[0]["messages"][1]["content"] == (
        "User: will it rain?\nAssistant: yes, bring an umbrella"
    )


async def test_extract_and_remember_saves_nothing_when_model_says_no_facts(monkeypatch):
    fake_client = _FakeClient("[]")
    monkeypatch.setattr("agentchat.inference.client.client", lambda _url=None: fake_client)
    remembered: list[tuple] = []
    monkeypatch.setattr(store, "remember", lambda *a: remembered.append(a))

    await store.extract_and_remember("proj-1", "conv-1", "hi", "hello there")

    assert remembered == []


async def test_extract_and_remember_swallows_client_errors(monkeypatch):
    class _Boom:
        chat = SimpleNamespace(completions=SimpleNamespace(create=None))

    def _raise():
        raise RuntimeError("vLLM unreachable")

    monkeypatch.setattr("agentchat.inference.client.client", _raise)
    remembered: list[tuple] = []
    monkeypatch.setattr(store, "remember", lambda *a: remembered.append(a))

    await store.extract_and_remember("proj-1", "conv-1", "hi", "hello there")  # must not raise

    assert remembered == []


async def test_extract_and_remember_skips_empty_assistant_text():
    # no monkeypatch needed: it must return before touching the client
    await store.extract_and_remember("proj-1", "conv-1", "hi", "   ")
