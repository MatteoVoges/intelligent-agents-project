from types import SimpleNamespace

from agentchat.tools.executor import PYTHON
from agentchat.tools.executor import _build_invocation


def _tool(command, args, type="shell"):
    return SimpleNamespace(command=command, args=args, type=type)


def test_placeholder_substitution_keeps_stdin_empty():
    tool = _tool("ls -la {path}", '[{"name":"path"}]')
    argv, stdin = _build_invocation(tool, {"path": "/tmp"})
    assert argv == ["ls", "-la", "/tmp"]
    assert stdin is None


def test_single_argument_without_placeholder_goes_to_stdin():
    tool = _tool("wc -w", '[{"name":"text"}]')
    argv, stdin = _build_invocation(tool, {"text": "hello brave new world"})
    assert argv == ["wc", "-w"]
    assert stdin == "hello brave new world"


def test_multiple_arguments_without_placeholder_go_to_stdin_as_json():
    tool = _tool("./script.sh", '[{"name":"a"},{"name":"b"}]')
    argv, stdin = _build_invocation(tool, {"a": "1", "b": "2"})
    assert argv == ["./script.sh"]
    assert stdin == '{"a": "1", "b": "2"}'


def test_missing_argument_becomes_empty_string():
    tool = _tool("echo {msg}", '[{"name":"msg"}]')
    argv, _ = _build_invocation(tool, {})
    assert argv == ["echo", ""]


def test_python_script_tool_is_prefixed_with_interpreter():
    tool = _tool("count.py", '[{"name":"text"}]', type="python")
    argv, stdin = _build_invocation(tool, {"text": "abc"})
    assert argv == [PYTHON, "count.py"]
    assert stdin == "abc"


def test_python_tool_without_a_script_path_runs_as_inline_source():
    """The reported failure: shlex.split turned the source into words and python opened
    the first one as a file (`can't open file ./import`)."""
    tool = _tool("import math; print({expression})", '[{"name":"expression"}]', type="python")
    argv, stdin = _build_invocation(tool, {"expression": "math.sqrt(16)"})
    assert argv == [PYTHON, "-c", "import math; print(math.sqrt(16))"]
    assert stdin is None


def test_inline_python_without_placeholders_reads_its_argument_from_stdin():
    tool = _tool("import sys; print(sys.stdin.read().upper())", '[{"name":"text"}]', type="python")
    argv, stdin = _build_invocation(tool, {"text": "hi"})
    assert argv == [PYTHON, "-c", "import sys; print(sys.stdin.read().upper())"]
    assert stdin == "hi"


def test_unrelated_braces_survive_substitution():
    tool = _tool("awk {prog} {path}", '[{"name":"prog"},{"name":"path"}]')
    argv, stdin = _build_invocation(tool, {"prog": "{print $1}", "path": "/tmp/f"})
    assert argv == ["awk", "{print $1}", "/tmp/f"]
    assert stdin is None


def test_literal_braces_in_command_are_not_placeholders():
    tool = _tool("awk '{print $1}'", '[{"name":"text"}]')
    argv, stdin = _build_invocation(tool, {"text": "a b"})
    assert argv == ["awk", "{print $1}"]
    assert stdin == "a b"


def test_no_arguments_means_no_stdin():
    tool = _tool("nvidia-smi", "[]")
    argv, stdin = _build_invocation(tool, {})
    assert argv == ["nvidia-smi"]
    assert stdin is None
