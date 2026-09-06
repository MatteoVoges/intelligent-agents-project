"""Execute user-defined tools as subprocesses.

Safety posture (full sandboxing was NOT elected, so this is best-effort):
- no shell=True (args passed as argv, no shell injection)
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


def _build_argv(tool, args: dict) -> list[str]:
    argv = shlex.split(tool.command)
    for spec in json.loads(tool.args or "[]"):
        argv.append(str(args.get(spec["name"], "")))
    if tool.type == "python":
        argv = ["python", *argv]
    return argv


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

    argv = _build_argv(tool, args)
    config.TOOL_WORKDIR.mkdir(parents=True, exist_ok=True)

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(config.TOOL_WORKDIR),
        )
    except FileNotFoundError:
        return f"[error] command not found: {argv[0] if argv else '<empty>'}"
    except Exception as e:
        return f"[error] failed to start tool: {e}"

    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=config.TOOL_TIMEOUT)
    except TimeoutError:
        proc.kill()
        return f"[error] tool '{name}' timed out after {config.TOOL_TIMEOUT}s"

    text = out.decode(errors="replace")[:8000]
    if not text.strip():
        return f"[tool '{name}' exited {proc.returncode} with no output]"
    return text
