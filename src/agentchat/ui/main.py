from __future__ import annotations

import asyncio
import json

from nicegui import app
from nicegui import ui

from .. import config
from .. import services
from ..chat import engine
from ..memory import store as memory


@ui.page("/")
def main_page() -> None:
    uid = app.storage.user.get("user_id")
    if not uid:
        ui.navigate.to("/login")
        return

    state: dict = {"conversation_id": None, "project_id": None, "stop_event": None}

    # --- helpers -------------------------------------------------------------
    def current_conversation():
        cid = state["conversation_id"]
        return services.get_conversation(cid) if cid else None

    def render_message(role: str, text: str):
        sent = role == "user"
        with messages:
            with ui.row().classes("w-full " + ("justify-end" if sent else "justify-start")):
                bubble = ui.markdown(text).classes(
                    "rounded-lg px-3 py-2 max-w-3xl " + ("bg-blue-100" if sent else "bg-gray-100")
                )
        return bubble

    def render_tool_event(label: str, body: str, color: str) -> None:
        with messages:
            with ui.card().classes(f"w-full max-w-3xl {color} text-xs"):
                ui.label(label).classes("font-mono font-bold")
                ui.label(body).classes("font-mono whitespace-pre-wrap")

    def scroll_bottom() -> None:
        messages_area.scroll_to(percent=1.0)

    def load_messages() -> None:
        messages.clear()
        conv = current_conversation()
        if conv is None:
            with messages:
                ui.label("Select or create a conversation to start.").classes("text-gray-400 m-auto")
            return
        for m in services.list_messages(conv.id):
            if m.role in ("user", "assistant") and not m.tool_calls:
                if m.content.strip():
                    render_message(m.role, m.content)
            elif m.role == "assistant" and m.tool_calls:
                names = ", ".join(c["function"]["name"] for c in json.loads(m.tool_calls))
                render_tool_event(f"→ tool call: {names}", m.content or "", "bg-amber-50")
            elif m.role == "tool":
                render_tool_event(f"← {m.name} output", m.content, "bg-emerald-50")
        scroll_bottom()

    def set_generating(active: bool) -> None:
        send_btn.set_visibility(not active)
        stop_btn.set_visibility(active)
        text_input.set_enabled(not active)

    # --- sidebar refreshables ------------------------------------------------
    @ui.refreshable
    def project_select_ui() -> None:
        projects = services.list_projects(uid)
        options = {"": "— No project —"} | {p.id: p.name for p in projects}
        ui.select(
            options,
            value=state["project_id"] or "",
            label="Active project",
            on_change=lambda e: on_project_change(e.value or None),
        ).classes("w-full").props("outlined dense")

    @ui.refreshable
    def conversation_list_ui() -> None:
        convs = services.list_conversations(uid, state["project_id"])
        if not convs:
            ui.label("No conversations yet.").classes("text-gray-400 text-sm p-2")
            return
        for c in convs:
            active = c.id == state["conversation_id"]
            with ui.row().classes(
                "w-full items-center no-wrap rounded " + ("bg-blue-50" if active else "hover:bg-gray-50")
            ):
                ui.button(c.title, on_click=lambda _, cid=c.id: select_conversation(cid)).props(
                    "flat align=left dense"
                ).classes("grow text-left normal-case truncate")
                ui.button(icon="delete", on_click=lambda _, cid=c.id: delete_conversation(cid)).props(
                    "flat dense round"
                ).classes("text-gray-400")

    def refresh_sidebar() -> None:
        project_select_ui.refresh()
        conversation_list_ui.refresh()

    # --- actions -------------------------------------------------------------
    def on_project_change(project_id: str | None) -> None:
        state["project_id"] = project_id
        state["conversation_id"] = None
        conversation_list_ui.refresh()
        load_messages()

    def select_conversation(cid: str) -> None:
        state["conversation_id"] = cid
        conv = services.get_conversation(cid)
        if conv:
            model_select.value = conv.model_id
        conversation_list_ui.refresh()
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

    def on_model_change(model_id: str) -> None:
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
                    render_tool_event(f"→ tool call: {ev['name']}", ev["arguments"], "bg-amber-50")
                elif ev["type"] == "tool_result":
                    render_tool_event(f"← {ev['name']} output", ev["result"], "bg-emerald-50")
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
        with ui.dialog() as dialog, ui.card():
            ui.label("New project").classes("text-lg")
            name = ui.input("Project name").props("outlined autofocus")

            def create() -> None:
                if (name.value or "").strip():
                    services.create_project(uid, name.value.strip())
                    project_select_ui.refresh()
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

        with ui.dialog() as dialog, ui.card().classes("w-[36rem]"):
            ui.label("Project memory").classes("text-lg")

            @ui.refreshable
            def items() -> None:
                mems = services.list_memory(pid)
                if not mems:
                    ui.label("No memory items yet.").classes("text-gray-400 text-sm")
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
        with ui.dialog() as dialog, ui.card().classes("w-[40rem]"):
            ui.label("Custom tools").classes("text-lg")

            @ui.refreshable
            def tool_list() -> None:
                tools = services.list_tools(uid)
                if not tools:
                    ui.label("No tools defined.").classes("text-gray-400 text-sm")
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

            tool_list()
            ui.separator()
            ui.label("Add tool (definition on the fly)").classes("font-bold text-sm")
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
        app.storage.user.clear()
        ui.navigate.to("/login")

    # --- layout --------------------------------------------------------------
    with ui.header().classes("items-center justify-between"):
        ui.label("AgentChat").classes("text-lg font-bold")
        with ui.row().classes("items-center gap-2"):
            model_select = (
                ui.select(
                    {m.id: m.label for m in config.MODELS},
                    value=config.DEFAULT_MODEL_ID,
                    on_change=lambda e: on_model_change(e.value),
                )
                .props("outlined dense dark")
                .classes("min-w-48")
            )
            ui.label(app.storage.user.get("username", "")).classes("text-sm")
            ui.button(icon="logout", on_click=logout).props("flat round dense")

    with ui.left_drawer().classes("bg-gray-50 gap-2") as drawer:  # noqa: F841
        ui.button("New chat", icon="add", on_click=new_conversation).classes("w-full")
        project_select_ui()
        ui.button("New project", icon="create_new_folder", on_click=open_new_project_dialog).props(
            "flat dense"
        ).classes("w-full")
        ui.separator()
        conversation_list_ui()
        ui.space()
        with ui.row().classes("w-full"):
            ui.button("Memory", icon="psychology", on_click=open_memory_dialog).props("flat dense").classes("grow")
            ui.button("Tools", icon="build", on_click=open_tools_dialog).props("flat dense").classes("grow")

    messages_area = ui.scroll_area().classes("w-full h-[80vh]")
    with messages_area:
        messages = ui.column().classes("w-full gap-2 items-stretch")

    with ui.footer().classes("bg-white"):
        with ui.row().classes("w-full items-end gap-2 p-2"):
            text_input = (
                ui.textarea(placeholder="Type a message…")
                .props("outlined autogrow")
                .classes("grow")
                .on("keydown.enter.prevent", lambda _: send())
            )
            send_btn = ui.button(icon="send", on_click=send).props("round")
            stop_btn = ui.button(icon="stop", on_click=stop).props("round color=red")
            stop_btn.set_visibility(False)

    load_messages()
