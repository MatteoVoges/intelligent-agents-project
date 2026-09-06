"""Top-level entry point: `uv run main.py`.

Also what NiceGUI's test `user` fixture imports to discover the @ui.page routes, which is why
it lives at the repo root rather than inside the package.
"""

from agentchat.app import main

if __name__ in {"__main__", "__mp_main__"}:
    main()
