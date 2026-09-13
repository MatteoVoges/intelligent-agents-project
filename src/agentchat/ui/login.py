from __future__ import annotations

from nicegui import ui

from .. import services
from . import session
from . import theme


@ui.page("/login")
def login_page() -> None:
    def do_login() -> None:
        name = (username.value or "").strip()
        if not name:
            ui.notify("Enter a username", type="warning")
            return
        user = services.get_or_create_user(name)
        session.bind(user.id, user.username)
        ui.navigate.to("/")

    theme.apply()
    with ui.card().classes("absolute-center w-96 items-stretch gap-3 shadow-none border fr-surface fr-border"):
        with ui.row().classes("items-center justify-center gap-2 no-wrap"):
            ui.icon("auto_awesome").classes("fr-accent text-2xl")
            ui.label(theme.APP_NAME).classes("text-2xl font-semibold tracking-tight")
        ui.label(theme.TAGLINE).classes("text-sm fr-muted text-center")
        username = ui.input("Username").props("autofocus outlined dense").on("keydown.enter", lambda _: do_login())
        ui.button("Enter", on_click=do_login).props("unelevated").classes("w-full")
        ui.label("No password — the username is your workspace.").classes("text-xs fr-muted text-center")
