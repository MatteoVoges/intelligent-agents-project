"""Execute user-defined tools as subprocesses.

Safety posture (full sandboxing was NOT elected, so this is best-effort):
- no shell=True; the command is split with shlex and exec'd directly, so argument text is
  never reinterpreted as shell syntax
- hard timeout, output truncated
- runs inside a dedicated working directory
Documented limitation: user-provided commands run with the app's OS privileges.
"""

from __future__ import annotations

import asyncio
import json
import shlex

from .. import config
from .. import services


def _build_invocation(tool, args: dict) -> tuple[list[str], str | None]:
    """Return (argv, stdin_text) for a tool definition.

    Two calling conventions, chosen by the tool author:
      - the command contains `{argname}` placeholders -> substituted in place, nothing on stdin
      - no placeholders -> argv is the bare command and the arguments go to stdin
        (a single argument is sent raw, several are sent as a JSON object)

    The stdin path is what makes ordinary filters like `wc -w` or `sort` usable as tools;
    appending arguments blindly to argv would make those read them as filenames.
    """
    specs = json.loads(tool.args or "[]")
    names = [s["name"] for s in specs]
    values = {n: str(args.get(n, "")) for n in names}

    uses_placeholders = any("{" + n + "}" in tool.command for n in names)
    if uses_placeholders:
        # Substitute the exact `{name}` tokens rather than str.format, so unrelated braces in
        # the command survive untouched — `awk '{print $1}' {path}` has to keep working.
        def substitute(part: str) -> str:
            for n, v in values.items():
                part = part.replace("{" + n + "}", v)
            return part

        argv = [substitute(part) for part in shlex.split(tool.command)]
        stdin_text = None
    else:
        argv = shlex.split(tool.command)
        if not values:
            stdin_text = None
        elif len(values) == 1:
            stdin_text = next(iter(values.values()))
        else:
            stdin_text = json.dumps(values)

    if tool.type == "python":
        argv = ["python3", *argv]
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
        )
    except FileNotFoundError:
        return f"[error] command not found: {argv[0] if argv else '<empty>'}"
    except Exception as e:
        return f"[error] failed to start tool: {e}"

    try:
        out, _ = await asyncio.wait_for(
            proc.communicate(input=(stdin_text or "").encode()), timeout=config.TOOL_TIMEOUT
        )
    except TimeoutError:
        proc.kill()
        await proc.wait()  # reap it, or the killed child lingers as a zombie
        return f"[error] tool '{name}' timed out after {config.TOOL_TIMEOUT}s"

    text = out.decode(errors="replace")[:8000]
    if not text.strip():
        return f"[tool '{name}' exited {proc.returncode} with no output]"
    return text
