from types import SimpleNamespace

from agentchat.chat import prompt


def _tool(name, args, desc=""):
    return SimpleNamespace(name=name, args=args, description=desc)


def _msg(role, content, tool_calls=None, tool_call_id=None, name=None):
    return SimpleNamespace(role=role, content=content, tool_calls=tool_calls, tool_call_id=tool_call_id, name=name)


def test_title_from_truncates():
    assert prompt.title_from("  hello   world ") == "hello world"
    long = "x" * 80
    assert prompt.title_from(long).endswith("...")
    assert prompt.title_from("") == "New chat"


def test_to_openai_tools_schema():
    tools = prompt.to_openai_tools([_tool("sum", '[{"name":"text","description":"input"}]', "summarize")])
    assert tools[0]["function"]["name"] == "sum"
    params = tools[0]["function"]["parameters"]
    assert params["required"] == ["text"]
    assert params["properties"]["text"]["type"] == "string"


def test_to_api_messages_reconstructs_tool_turns():
    msgs = [
        _msg("user", "hi"),
        _msg("assistant", "", tool_calls='[{"id":"c1","type":"function","function":{"name":"sum","arguments":"{}"}}]'),
        _msg("tool", "result text", tool_call_id="c1", name="sum"),
        _msg("assistant", "final answer"),
    ]
    out = prompt.to_api_messages("SYS", "- fact", msgs)
    assert out[0]["role"] == "system" and "fact" in out[0]["content"]
    assert out[2]["tool_calls"][0]["id"] == "c1"
    assert out[3] == {"role": "tool", "tool_call_id": "c1", "content": "result text"}
    assert out[4] == {"role": "assistant", "content": "final answer"}
