"""The limits that keep the preset tools from being a hole in the app.

Tool commands are not sandboxed (that elective was not chosen), so these boundaries are the
only thing between a model-chosen argument and the machine. They are cheap to assert and
expensive to discover missing.
"""

import os
from types import SimpleNamespace

import pytest

from agentchat import config
from agentchat.tools import executor
from agentchat.tools import websearch
from agentchat.tools.calculator import CalcError
from agentchat.tools.calculator import evaluate


# --- calculator: parses, never evaluates --------------------------------------------------
@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("2 + 2", 4),
        ("10 / 4", 2.5),
        ("2 ** 10", 1024),
        ("sqrt(16)", 4.0),
        ("math.sqrt(16)", 4.0),  # the dotted form a model tends to write
        ("min(3, 1, 2)", 1),
        ("round(pi, 2)", 3.14),
    ],
)
def test_arithmetic_is_evaluated(expression, expected):
    assert evaluate(expression) == expected


@pytest.mark.parametrize(
    "expression",
    [
        '__import__("os").system("id")',
        "open('/etc/passwd').read()",
        "(1).__class__.__base__.__subclasses__()",
        "os.getcwd()",
        "eval('1+1')",
        "[x for x in range(3)]",
        "lambda: 1",
    ],
)
def test_anything_that_is_not_arithmetic_is_refused(expression):
    """The whole point of the tool: `python -c {expression}` would run every one of these."""
    with pytest.raises(CalcError):
        evaluate(expression)


def test_absurd_exponents_are_refused_rather_than_computed():
    with pytest.raises(CalcError, match="exponent"):
        evaluate("9 ** 9 ** 9")


# --- websearch / read_page: no requests to the private network ----------------------------
@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://localhost:8000/v1/models",  # the vLLM server this app talks to
        "http://127.0.0.1:8080/",  # the app itself
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://10.0.0.1/",
        "http://192.168.1.1/",
        "ftp://example.com/file",
        "not a url",
    ],
)
def test_non_public_urls_are_blocked(url):
    with pytest.raises(websearch.BlockedURL):
        websearch._check_url(url)


def test_public_addresses_are_allowed():
    websearch._check_url("http://93.184.216.34/")  # a literal, so no DNS lookup is needed


# --- executor: bounded and stripped of the app's environment ------------------------------
def _python_tool(source: str, args: str = "[]"):
    return SimpleNamespace(command=source, args=args, type="python")


@pytest.fixture
def tool(monkeypatch):
    """Install one tool definition for `executor.run` to find, bypassing the database."""

    def install(definition):
        monkeypatch.setattr(executor.services, "get_tool", lambda _uid, _name: definition)

    return install


async def test_secrets_in_the_app_environment_do_not_reach_the_tool(tool, monkeypatch):
    monkeypatch.setenv("VLLM_API_KEY", "super-secret")
    monkeypatch.setenv("AGENTCHAT_SECRET", "also-secret")
    tool(_python_tool("import os; print(sorted(os.environ))"))

    out = await executor.run("u1", "envdump", "{}")

    assert "VLLM_API_KEY" not in out
    assert "AGENTCHAT_SECRET" not in out
    assert "PATH" in out  # but the tool is still runnable


async def test_a_tool_that_prints_forever_is_cut_off_not_waited_out(tool):
    tool(_python_tool("while True: print('spam' * 20)"))

    out = await executor.run("u1", "flood", "{}")

    assert "truncated" in out
    assert len(out) <= executor.MAX_OUTPUT_CHARS + 100


async def test_a_hanging_tool_is_killed_at_the_timeout(tool, monkeypatch):
    monkeypatch.setattr(config, "TOOL_TIMEOUT", 1)
    tool(_python_tool("import time; time.sleep(60)"))

    out = await executor.run("u1", "sleeper", "{}")

    assert "timed out" in out


@pytest.mark.skipif(not hasattr(os, "killpg"), reason="process groups are POSIX-only")
async def test_the_timeout_also_reaps_a_child_the_tool_spawned(tool, monkeypatch, tmp_path):
    """A tool that forks and hangs must not leave the child running after the timeout.

    Without `start_new_session` plus a process-group kill, only the direct child dies and the
    grandchild keeps the app's file descriptors — and its work — alive indefinitely.
    """
    marker = tmp_path / "child-still-alive"
    source = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', \"import time, pathlib; time.sleep(3); "
        f"pathlib.Path(r'{marker}').touch()\"]); "
        "time.sleep(60)"
    )
    monkeypatch.setattr(config, "TOOL_TIMEOUT", 1)
    tool(_python_tool(source))

    assert "timed out" in await executor.run("u1", "forker", "{}")

    import asyncio

    await asyncio.sleep(3.5)  # past the moment the orphan would have written its marker
    assert not marker.exists()


async def test_oversized_arguments_are_capped(tool):
    tool(_python_tool("import sys; print(len(sys.stdin.read()))", '[{"name":"text"}]'))

    out = await executor.run("u1", "sizer", '{"text": "%s"}' % ("x" * 50_000))

    assert out.strip() == str(executor.MAX_ARG_CHARS)


async def test_a_tool_that_ignores_its_input_is_not_reported_as_an_error(tool):
    """`true`-style tools exit without reading stdin, so every write is a broken pipe."""
    tool(_python_tool("print('done')", '[{"name":"text"}]'))

    out = await executor.run("u1", "ignorer", '{"text": "unread"}')

    assert out.strip() == "done"
