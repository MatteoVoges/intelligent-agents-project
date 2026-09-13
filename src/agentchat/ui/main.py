from __future__ import annotations

import asyncio
import json

from nicegui import ui

from .. import config
from .. import services
from ..chat import engine
from ..inference import catalog
from ..memory import store as memory
from ..tools import examples as tool_examples
from . import session
from . import theme

UNFILED = "Unfiled"


def _serve_hint(spec: config.ModelSpec) -> str:
    """The command that would make this model selectable."""
    if spec.kind == "adapter":
        config_name = spec.id.replace("-", "_")
        return f"wsl/train-lora.sh training/configs/{config_name}.yaml, then restart wsl/serve-model.sh"
    if spec.url == config.VLLM_SMALL_URL:
        return f"wsl/serve-small.sh {spec.id}"
    return f"wsl/serve-model.sh {spec.id}"


@ui.page("/")
async def main_page() -> None:  # noqa: C901 — one NiceGUI page: handlers close over the page's widgets
    # async because the tab-scoped identity is only readable once the websocket is up;
    # NiceGUI ships the page shell immediately and builds the rest after the handshake.
    account = await session.current()
    if account is None:
        ui.navigate.to("/login")
        return
    uid = account.user_id

    theme.apply()

    # Configured models are a superset of loaded ones: one vLLM serves one base, and the
    # small-model server is optional. Probe once here, re-probe when a dark entry is picked.
    live: set[str] = await catalog.available_model_ids()

    state: dict = {
        "conversation_id": None,
        "project_id": None,
        "stop_event": None,
        "model_id": config.DEFAULT_MODEL_ID,
    }

    # --- helpers -------------------------------------------------------------
    def current_conversation():
        cid = state["conversation_id"]
        return services.get_conversation(cid) if cid else None

    def render_message(role: str, text: str):
        sent = role == "user"
        with messages:
            if sent:
                with ui.row().classes("w-full justify-end"):
                    bubble = ui.markdown(text).classes("fr-raised rounded-2xl px-4 py-2 max-w-xl")
            else:
                bubble = ui.markdown(text).classes("w-full px-1")
        return bubble

    def render_tool_event(label: str, body: str) -> None:
        with messages:
            with ui.column().classes("w-full border-l-2 pl-3 gap-0 my-1").style(f"border-color: {theme.ACCENT}"):
                ui.label(label).classes("font-mono text-xs fr-accent")
                if body.strip():
                    ui.label(body).classes("font-mono text-xs fr-muted whitespace-pre-wrap")

    def render_welcome(no_chat: bool) -> None:
        username = account.username or "there"
        hints = [
            ("tune", "Switch model right in the message box below."),
            ("folder", "Your chats are grouped by project in the sidebar."),
            ("psychology", "Facts saved to a project are remembered across its chats."),
        ]
        with messages:
            with ui.column().classes("w-full items-start gap-2 pt-16 pb-4"):
                ui.label(f"Bonjour, {username}.").classes("text-3xl font-semibold tracking-tight fr-accent")
                ui.label(f"I am {theme.APP_NAME}, running on your own machine.").classes("text-base")
                ui.label(
                    "Start a new chat below." if no_chat else "This chat is empty — say something to begin."
                ).classes("text-sm fr-muted")
                with ui.column().classes("gap-1 pt-6"):
                    for icon, hint in hints:
                        with ui.row().classes("items-center gap-2 no-wrap"):
                            ui.icon(icon).classes("fr-muted text-base")
                            ui.label(hint).classes("text-sm fr-muted")

    def scroll_bottom() -> None:
        messages_area.scroll_to(percent=1.0)

    def render_history(history) -> None:
        for m in history:
            if m.role in ("user", "assistant") and not m.tool_calls:
                if m.content.strip():
                    render_message(m.role, m.content)
            elif m.role == "assistant" and m.tool_calls:
                names = ", ".join(c["function"]["name"] for c in json.loads(m.tool_calls))
                render_tool_event(f"→ tool call: {names}", m.content or "")
            elif m.role == "tool":
                render_tool_event(f"← {m.name} output", m.content)

    def load_messages() -> None:
        messages.clear()
        conv = current_conversation()
        if conv is None:
            render_welcome(no_chat=True)
            return
        history = services.list_messages(conv.id)
        if not history:
            render_welcome(no_chat=False)
            return
        render_history(history)
        scroll_bottom()

    def set_generating(active: bool) -> None:
        send_btn.set_visibility(not active)
        stop_btn.set_visibility(active)
        text_input.set_enabled(not active)

    # --- sidebar refreshables ------------------------------------------------
    @ui.refreshable
    def project_select_ui() -> None:
        projects = services.list_projects(uid)
        options = {"": f"— {UNFILED} —"} | {p.id: p.name for p in projects}
        ui.select(
            options,
            value=state["project_id"] or "",
            label="New chats go to",
            on_change=lambda e: on_project_change(e.value or None),
        ).classes("w-full").props("outlined dense options-dense")

    @ui.refreshable
    def conversation_list_ui() -> None:
        """Every chat of the user, grouped under the project it belongs to."""
        names = {p.id: p.name for p in services.list_projects(uid)}
        groups: dict[str | None, list] = {}
        for c in services.list_conversations(uid):
            groups.setdefault(c.project_id if c.project_id in names else None, []).append(c)
        if not groups:
            ui.label("No conversations yet.").classes("fr-muted text-sm p-2")
            return
        order = [pid for pid in names if pid in groups] + ([None] if None in groups else [])
        for pid in order:
            active_group = pid == state["project_id"]
            with ui.row().classes("w-full items-center no-wrap gap-1 px-2 pt-3 pb-1"):
                ui.icon("folder" if pid else "inbox").classes(
                    "text-sm " + ("fr-accent" if active_group else "fr-muted")
                )
                ui.label(names[pid] if pid else UNFILED).classes(
                    "text-xs uppercase tracking-wide truncate "
                    + ("fr-accent font-medium" if active_group else "fr-muted")
                )
                ui.space()
                ui.label(str(len(groups[pid]))).classes("text-xs fr-muted")
            for c in groups[pid]:
                active = c.id == state["conversation_id"]
                with ui.row().classes("w-full items-center no-wrap rounded " + ("fr-active" if active else "fr-hover")):
                    ui.button(c.title, on_click=lambda _, cid=c.id: select_conversation(cid)).props(
                        "flat align=left dense"
                    ).classes("grow text-left normal-case truncate text-white")
                    ui.button(icon="delete", on_click=lambda _, cid=c.id: delete_conversation(cid)).props(
                        "flat dense round"
                    ).classes("fr-muted")

    def refresh_sidebar() -> None:
        project_select_ui.refresh()
        conversation_list_ui.refresh()

    # --- actions -------------------------------------------------------------
    def on_project_change(project_id: str | None) -> None:
        # only decides where new chats land — the list itself always shows every project
        state["project_id"] = project_id
        conversation_list_ui.refresh()

    def model_options() -> dict[str, str]:
        return {m.id: (m.label if m.id in live else f"{m.label} · not loaded") for m in config.MODELS}

    def select_conversation(cid: str) -> None:
        state["conversation_id"] = cid
        conv = services.get_conversation(cid)
        if conv:
            state["project_id"] = conv.project_id
            state["model_id"] = conv.model_id
            model_select.value = conv.model_id
        refresh_sidebar()
        load_messages()

    def new_conversation() -> None:
        conv = services.create_conversation(uid, state["project_id"], model_select.value)
        state["conversation_id"] = conv.id
        conversation_list_ui.refresh()
        load_messages()

    def delete_conversation(cid: str) -> None:
        services.delete_conversation(cid)
        if state["conversation_id"] == cid:
            state["conversation_id"] = None
        conversation_list_ui.refresh()
        load_messages()

    async def on_model_change(model_id: str) -> None:
        if model_id == state["model_id"]:
            return
        if model_id not in live:
            live.update(await catalog.available_model_ids())  # it may have just been started
            model_select.set_options(model_options(), value=model_id)
        if model_id not in live:
            spec = config.model_spec(model_id)
            ui.notify(f"{spec.label} is not loaded — start it with: {_serve_hint(spec)}", type="warning")
            model_select.set_value(state["model_id"])
            return
        state["model_id"] = model_id
        conv = current_conversation()
        if conv:
            services.set_conversation_model(conv.id, model_id)

    async def send() -> None:
        text = (text_input.value or "").strip()
        if not text:
            return
        if state["conversation_id"] is None:
            new_conversation()
        conv = current_conversation()
        text_input.value = ""
        history = services.list_messages(conv.id)
        if not history:  # replace the welcome block with the conversation itself
            messages.clear()
        render_message("user", text)
        bubble = render_message("assistant", "")
        scroll_bottom()
        acc: list[str] = []
        state["stop_event"] = asyncio.Event()
        set_generating(True)
        try:
            async for ev in engine.generate(conv, text, stop_event=state["stop_event"]):
                if ev["type"] == "token":
                    acc.append(ev["text"])
                    bubble.set_content("".join(acc))
                elif ev["type"] == "tool_call":
                    render_tool_event(f"→ tool call: {ev['name']}", ev["arguments"])
                elif ev["type"] == "tool_result":
                    render_tool_event(f"← {ev['name']} output", ev["result"])
                elif ev["type"] == "done" and not acc:
                    bubble.set_content(ev["content"])
                scroll_bottom()
        finally:
            state["stop_event"] = None
            set_generating(False)
            conversation_list_ui.refresh()

    def stop() -> None:
        ev = state.get("stop_event")
        if ev is not None:
            ev.set()

    # --- dialogs -------------------------------------------------------------
    def open_new_project_dialog() -> None:
        with ui.dialog() as dialog, ui.card().classes("fr-surface"):
            ui.label("New project").classes("text-lg")
            name = ui.input("Project name").props("outlined autofocus")

            def create() -> None:
                if (name.value or "").strip():
                    project = services.create_project(uid, name.value.strip())
                    state["project_id"] = project.id
                    refresh_sidebar()
                    dialog.close()

            with ui.row():
                ui.button("Create", on_click=create)
                ui.button("Cancel", on_click=dialog.close).props("flat")
        dialog.open()

    def open_memory_dialog() -> None:
        conv = current_conversation()
        if conv is None or not conv.project_id:
            ui.notify("Assign this chat to a project to use memory.", type="warning")
            return
        pid = conv.project_id

        with ui.dialog() as dialog, ui.card().classes("w-[36rem] fr-surface"):
            ui.label("Project memory").classes("text-lg")

            @ui.refreshable
            def items() -> None:
                mems = services.list_memory(pid)
                if not mems:
                    ui.label("No memory items yet.").classes("fr-muted text-sm")
                for it in mems:
                    with ui.row().classes("w-full items-center no-wrap"):
                        ui.label(it.content).classes("grow text-sm")
                        ui.button(
                            icon="delete",
                            on_click=lambda _, i=it.id: (
                                services.delete_memory_item(i),
                                items.refresh(),
                            ),
                        ).props("flat dense round")

            items()
            note = ui.textarea("Add a fact to remember").props("outlined").classes("w-full")

            async def add() -> None:
                if (note.value or "").strip():
                    await asyncio.to_thread(memory.remember, pid, note.value.strip(), conv.id)
                    note.value = ""
                    items.refresh()

            with ui.row():
                ui.button("Remember", on_click=add)
                ui.button("Close", on_click=dialog.close).props("flat")
        dialog.open()

    def open_tools_dialog() -> None:
        with ui.dialog() as dialog, ui.card().classes("w-[40rem] fr-surface"):
            ui.label("Custom tools").classes("text-lg")

            @ui.refreshable
            def tool_list() -> None:
                tools = services.list_tools(uid)
                if not tools:
                    ui.label("No tools defined.").classes("fr-muted text-sm")
                for t in tools:
                    with ui.row().classes("w-full items-center no-wrap"):
                        ui.label(f"{t.name} ({t.type}): {t.command}").classes("grow text-sm font-mono truncate")
                        ui.button(
                            icon="delete",
                            on_click=lambda _, i=t.id: (
                                services.delete_tool(i),
                                tool_list.refresh(),
                            ),
                        ).props("flat dense round")

            def add_example(example) -> None:
                if any(t.name == example.name for t in services.list_tools(uid)):
                    ui.notify(f"'{example.name}' already exists", type="warning")
                    return
                services.create_tool(
                    uid, example.name, example.type, example.command, example.args_json, example.description
                )
                tool_list.refresh()

            tool_list()
            ui.separator()
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                ui.label("Start from an example:").classes("text-sm fr-muted")
                for ex in tool_examples.EXAMPLES:
                    ui.button(ex.name, on_click=lambda _, e=ex: add_example(e)).props("flat dense").classes(
                        "normal-case fr-muted"
                    )
            ui.separator()
            ui.label("Add tool (definition on the fly)").classes("font-medium text-sm")
            ui.label(
                "Use {argname} in the command to place an argument, e.g. `ls -la {path}`. "
                "Without placeholders the arguments are piped to stdin, e.g. `wc -w`. "
                "A python command is source code — `import math; print({expression})` — unless it "
                "starts with a .py file or an interpreter flag like `-m`."
            ).classes("text-xs fr-muted")
            name = ui.input("name").props("outlined dense")
            ttype = ui.select(["shell", "python"], value="shell", label="type").props("outlined dense")
            command = ui.input("command").props("outlined dense").classes("w-full")
            desc = ui.input("description").props("outlined dense").classes("w-full")
            args = (
                ui.textarea('args (JSON list, e.g. [{"name":"text","description":"input"}])')
                .props("outlined")
                .classes("w-full")
            )
            args.value = "[]"

            def add_tool() -> None:
                if not (name.value or "").strip() or not (command.value or "").strip():
                    ui.notify("name and command are required", type="warning")
                    return
                try:
                    json.loads(args.value or "[]")
                except json.JSONDecodeError:
                    ui.notify("args must be valid JSON", type="negative")
                    return
                services.create_tool(
                    uid,
                    name.value.strip(),
                    ttype.value,
                    command.value.strip(),
                    args.value or "[]",
                    desc.value or "",
                )
                name.value = command.value = desc.value = ""
                args.value = "[]"
                tool_list.refresh()

            with ui.row():
                ui.button("Add tool", on_click=add_tool)
                ui.button("Close", on_click=dialog.close).props("flat")
        dialog.open()

    def logout() -> None:
        session.unbind()
        ui.navigate.to("/login")

    # --- layout --------------------------------------------------------------
    with ui.header().classes("items-center justify-between border-b fr-surface fr-border shadow-none"):
        with ui.row().classes("items-center gap-2 no-wrap"):
            ui.icon("auto_awesome").classes("fr-accent text-lg")
            ui.label(theme.APP_NAME).classes("text-base font-semibold tracking-tight")
        with ui.row().classes("items-center gap-3"):
            ui.label(account.username).classes("text-sm fr-muted")
            ui.button(icon="logout", on_click=logout).props("flat round dense").classes("fr-muted")

    # bottom_corner: the drawer owns the bottom-left corner, so the composer footer stops at
    # the sidebar's edge instead of spanning under it and cutting the chat list short.
    with ui.left_drawer(bottom_corner=True).classes("gap-2 border-r fr-surface fr-border fr-sidebar") as drawer:  # noqa: F841
        with ui.column().classes("w-full gap-2 shrink-0"):
            ui.button("New chat", icon="add", on_click=new_conversation).props("unelevated").classes("w-full")
            project_select_ui()
            ui.button("New project", icon="create_new_folder", on_click=open_new_project_dialog).props(
                "flat dense"
            ).classes("w-full fr-muted")
        ui.separator().classes("fr-border shrink-0")
        # min-h-0 matters: without it this flex child refuses to shrink and a long chat
        # list pushes the footer buttons off-screen instead of scrolling.
        with ui.column().classes("w-full grow min-h-0 overflow-y-auto gap-0"):
            conversation_list_ui()
        ui.separator().classes("fr-border shrink-0")
        with ui.row().classes("w-full shrink-0"):
            ui.button("Memory", icon="psychology", on_click=open_memory_dialog).props("flat dense").classes(
                "grow fr-muted"
            )
            ui.button("Tools", icon="build", on_click=open_tools_dialog).props("flat dense").classes("grow fr-muted")

    messages_area = ui.scroll_area().classes("w-full h-[80vh]")
    with messages_area:
        with ui.column().classes("w-full max-w-3xl mx-auto items-stretch"):
            messages = ui.column().classes("w-full gap-3 items-stretch")

    # page-coloured, not transparent: scrolled messages must not show through the composer
    with ui.footer().classes("p-0").style(f"background: {theme.BG}"):
        with ui.column().classes("w-full max-w-3xl mx-auto px-3 pb-2 pt-1 gap-1"):
            with ui.column().classes("w-full rounded-2xl px-3 py-2 gap-1 fr-composer"):
                text_input = (
                    ui.textarea(placeholder="Type a message…")
                    .props("borderless autogrow dense")
                    .classes("w-full")
                    .on("keydown.enter.prevent", lambda _: send())
                )
                with ui.row().classes("w-full items-center justify-between no-wrap gap-2"):
                    # model switching sits in the composer: it is a per-message choice
                    model_select = (
                        ui.select(
                            model_options(),
                            value=config.DEFAULT_MODEL_ID,
                            on_change=lambda e: on_model_change(e.value),
                        )
                        .props("borderless dense options-dense")
                        .classes("text-sm min-w-48")
                    )
                    with ui.row().classes("items-center gap-1 no-wrap"):
                        send_btn = ui.button(icon="arrow_upward", on_click=send).props("round unelevated dense")
                        stop_btn = ui.button(icon="stop", on_click=stop).props("round unelevated dense color=grey-8")
                        stop_btn.set_visibility(False)
            ui.label(f"{theme.APP_NAME} runs on your machine — verify anything that matters.").classes(
                "text-xs fr-muted text-center w-full"
            )

    load_messages()
