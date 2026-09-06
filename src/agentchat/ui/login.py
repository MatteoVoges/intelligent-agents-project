from __future__ import annotations

from nicegui import app
from nicegui import ui

from .. import services


@ui.page("/login")
def login_page() -> None:
    def do_login() -> None:
        name = (username.value or "").strip()
        if not name:
            ui.notify("Enter a username", type="warning")
            return
        user = services.get_or_create_user(name)
        app.storage.user["user_id"] = user.id
        app.storage.user["username"] = user.username
        ui.navigate.to("/")

    ui.colors(primary="#334155")
    with ui.card().classes("absolute-center w-96 items-stretch shadow-none border border-gray-200"):
        ui.label("AgentChat").classes("text-xl font-medium text-center")
        ui.label("Enter a username to start or resume your workspace.").classes("text-sm text-gray-500 text-center")
        username = ui.input("Username").props("autofocus outlined dense").on("keydown.enter", lambda _: do_login())
        ui.button("Enter", on_click=do_login).props("unelevated").classes("w-full")
