"""Execute user-defined tools as subprocesses.

Safety posture (full sandboxing was NOT elected, so this is best-effort):
- no shell=True; the command is split with shlex and exec'd directly, so argument text is
  never reinterpreted as shell syntax
- hard timeout, enforced against the whole process group so a tool cannot outlive it by
  spawning children
- bounded input and output: arguments, stdin and captured output are all capped, so a tool
  that prints forever cannot exhaust memory before the timeout fires
- a scrubbed environment: the child gets a short allowlist, never the app's secrets
  (AGENTCHAT_SECRET, VLLM_API_KEY, HF_TOKEN, ...) which it would otherwise inherit
- runs inside a dedicated working directory

Documented limitation: user-provided commands still run with the app's OS privileges and
with network access. The preset tools in `examples.py` carry their own limits on top of this
(see `calculator`, which parses instead of evaluating, and `websearch`, which refuses
private addresses); a tool the user writes is only as safe as what they typed.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shlex
import signal
import sys

from .. import config
from .. import services

# The app's own interpreter, so `python` tools can import anything the app can (including
# `agentchat.tools.websearch`) regardless of what a bare `python3` on PATH would resolve to.
PYTHON = sys.executable or "python3"

MAX_ARG_CHARS = 8_000  # per argument, before substitution
MAX_STDIN_BYTES = 64_000
MAX_OUTPUT_BYTES = 256_000  # read cap; the text handed to the model is truncated further
MAX_OUTPUT_CHARS = 8_000

# Passed through to the child; everything else in os.environ is dropped. PATH and HOME are
# what ordinary commands need; the rest keep text decoding and temp files sane.
_ENV_ALLOWLIST = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TZ", "SYSTEMROOT", "COMSPEC")


def _child_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in _ENV_ALLOWLIST}
    env.setdefault("PATH", os.defpath)
    return env


def _is_interpreter_args(command: str) -> bool:
    """True when a python tool's command is arguments for the interpreter, not source code.

    `count.py --verbose` and `-m agentchat.tools.websearch` are invocations; anything else,
    like `import math; print(2+2)`, is source to run with `-c`.
    """
    head = command.strip().split(maxsplit=1)
    if not head:
        return False
    first = head[0].strip("'\"")
    return first.endswith(".py") or first.startswith("-")


def _stdin_for(values: dict[str, str]) -> str | None:
    """Arguments as they reach a command that declared no placeholders."""
    if not values:
        return None
    if len(values) == 1:
        return next(iter(values.values()))
    return json.dumps(values)


def _build_invocation(tool, args: dict) -> tuple[list[str], str | None]:
    """Return (argv, stdin_text) for a tool definition.

    Two calling conventions, chosen by the tool author:
      - the command contains `{argname}` placeholders -> substituted in place, nothing on stdin
      - no placeholders -> argv is the bare command and the arguments go to stdin
        (a single argument is sent raw, several are sent as a JSON object)

    The stdin path is what makes ordinary filters like `wc -w` or `sort` usable as tools;
    appending arguments blindly to argv would make those read them as filenames.

    A `python` tool whose command is neither a `.py` path nor an interpreter flag is inline
    source and goes to `python -c`.
    """
    specs = json.loads(tool.args or "[]")
    names = [s["name"] for s in specs]
    # Capped: a model that loops while emitting arguments must not be able to build an argv
    # past the OS limit (which fails as an opaque OSError) or a multi-megabyte stdin.
    values = {n: str(args.get(n, ""))[:MAX_ARG_CHARS] for n in names}

    uses_placeholders = any("{" + n + "}" in tool.command for n in names)

    # Substitute the exact `{name}` tokens rather than str.format, so unrelated braces in
    # the command survive untouched — `awk '{print $1}' {path}` has to keep working.
    def substitute(part: str) -> str:
        for n, v in values.items():
            part = part.replace("{" + n + "}", v)
        return part

    if tool.type == "python" and not _is_interpreter_args(tool.command):
        # Inline source must not be shlex.split: `import math; print({expression})` would
        # become ["import", "math;", ...] and python would try to open a file called "import".
        # Placeholders are spliced into the source text, so an argument can carry code —
        # acceptable only because tool commands already run unsandboxed (see module docstring).
        code = substitute(tool.command) if uses_placeholders else tool.command
        return [PYTHON, "-c", code], None if uses_placeholders else _stdin_for(values)

    if uses_placeholders:
        argv = [substitute(part) for part in shlex.split(tool.command)]
        stdin_text = None
    else:
        argv = shlex.split(tool.command)
        stdin_text = _stdin_for(values)

    if tool.type == "python":
        argv = [PYTHON, *argv]
    return argv, stdin_text


async def run(user_id: str, name: str, arguments_json: str) -> str:
    tool = services.get_tool(user_id, name)
    if tool is None:
        return f"[error] unknown tool '{name}'"

    try:
        args = json.loads(arguments_json or "{}")
        if not isinstance(args, dict):
            args = {}
    except json.JSONDecodeError:
        args = {}

    try:
        argv, stdin_text = _build_invocation(tool, args)
    except (KeyError, IndexError, ValueError) as e:
        return f"[error] could not build command for '{name}': {e}"
    config.TOOL_WORKDIR.mkdir(parents=True, exist_ok=True)

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(config.TOOL_WORKDIR),
            env=_child_env(),
            # Own session/process group, so the timeout can take the tool's children with it.
            start_new_session=True,
        )
    except FileNotFoundError:
        return f"[error] command not found: {argv[0] if argv else '<empty>'}"
    except Exception as e:
        return f"[error] failed to start tool: {e}"

    try:
        out, truncated = await asyncio.wait_for(_collect(proc, stdin_text), timeout=config.TOOL_TIMEOUT)
    except TimeoutError:
        await _terminate(proc)
        return f"[error] tool '{name}' timed out after {config.TOOL_TIMEOUT}s"

    text = out.decode(errors="replace")[:MAX_OUTPUT_CHARS]
    if truncated or len(out) > MAX_OUTPUT_CHARS:
        text += "\n[…output truncated]"
    if not text.strip():
        return f"[tool '{name}' exited {proc.returncode} with no output]"
    return text


async def _collect(proc, stdin_text: str | None) -> tuple[bytes, bool]:
    """Feed stdin, then read stdout up to the cap. Returns (output, was_truncated).

    `proc.communicate()` would read until EOF, so a tool printing in a loop could fill memory
    for the whole timeout window. Reading a bounded amount and killing the process on overflow
    keeps the cost of a misbehaving tool constant.
    """
    # A tool may exit without reading its input (`true`, or a command that errors on startup),
    # which turns every write into a broken pipe. That is the tool's business, not an error
    # for us to report, so the whole stdin exchange is best-effort.
    with contextlib.suppress(ConnectionError, BrokenPipeError, OSError):
        if stdin_text:
            proc.stdin.write(stdin_text.encode()[:MAX_STDIN_BYTES])
            await proc.stdin.drain()
        proc.stdin.close()

    # `StreamReader.read(n)` returns as soon as *any* data is available, not n bytes, so the
    # cap has to be accumulated across reads rather than asked for in one call.
    chunks: list[bytes] = []
    size = 0
    while size < MAX_OUTPUT_BYTES:
        chunk = await proc.stdout.read(MAX_OUTPUT_BYTES - size)
        if not chunk:  # EOF: the tool is done writing
            await proc.wait()
            return b"".join(chunks), False
        chunks.append(chunk)
        size += len(chunk)
    await _terminate(proc)
    return b"".join(chunks), True


async def _terminate(proc) -> None:
    """Kill the tool and anything it started, then reap it so no zombie is left behind."""
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        if hasattr(os, "killpg"):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            proc.kill()
    with contextlib.suppress(ProcessLookupError):
        await proc.wait()
