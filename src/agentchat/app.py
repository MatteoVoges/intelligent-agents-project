"""Entrypoint: initialise the DB, register pages, run the NiceGUI server."""

from __future__ import annotations

import socket

from nicegui import app
from nicegui import ui

from . import config
from .db import database


def _resolve_port(host: str, preferred: int) -> int:
    """Return `preferred` if it's bindable, otherwise an OS-assigned free port.

    Avoids WinError 10048 when a previous run left the port occupied. Small
    TOCTOU gap between this check and NiceGUI's own bind — fine for local use.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, preferred))
            return preferred
        except OSError:
            pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


# Importing the UI modules registers their @ui.page routes.
from .ui import login as _login  # noqa: E402, F401
from .ui import main as _main  # noqa: E402, F401


@app.on_startup
def _startup() -> None:
    database.init_db()


def main() -> None:
    port = _resolve_port(config.HOST, config.PORT)
    if port != config.PORT:
        print(f"Port {config.PORT} is busy; using {port} instead.")
    ui.run(
        title="AgentChat",
        host=config.HOST,
        port=port,
        storage_secret=config.STORAGE_SECRET,
        reload=False,
        show=False,
    )


# `python -m agentchat.app` and the `agentchat` script both land here.
# NiceGUI's reloader may re-import under __mp_main__, so guard both.
if __name__ in {"__main__", "__mp_main__"}:
    main()
