from __future__ import annotations

import asyncio
import json

from nicegui import ui

from .. import config
from .. import services
from ..chat import engine
from ..memory import store as memory
from ..tools import examples as tool_examples
from . import session
from . import theme


def _serve_hint(spec: config.ModelSpec) -> str:
    """The command that would put this model back on its endpoint."""
    if spec.kind == "adapter":
        config_name = spec.id.replace("-", "_")
        return (
            f"train it: uv run python training/train_lora.py --config training/configs/{config_name}.yaml, "
            "then restart serve.sh"
        )
    return f"bash serve.sh {spec.id} — or serve.sh on its own for the default set"


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

    # Where chats go when you never file them — and, with them, their memory.
    default_pid = services.default_project(uid).id

    state: dict = {
        "conversation_id": None,
        "project_id": default_pid,
        "stop_event": None,
        "model_id": config.DEFAULT_MODEL_ID,
    }

    # --- helpers -------------------------------------------------------------
    def current_conversation():
        cid = state["conversation_id"]
        return services.get_conversation(cid) if cid else None

    def _project_names() -> dict[str, str]:
        """id -> name, default project first so it heads both the picker and the sidebar."""
        projects = services.list_projects(uid)
        return {p.id: p.name for p in sorted(projects, key=lambda p: p.id != default_pid)}

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
        """One tool call or result, folded shut.

        What the tool did is worth being able to check and not worth reading every time — and
        a raw result can be hundreds of lines, which pushed the answer off the screen. The
        header alone says which tool ran; click it for the payload.
        """
        with messages:
            with ui.column().classes("w-full border-l-2 pl-3 gap-0 my-1").style(f"border-color: {theme.ACCENT}"):
                if not body.strip():
                    ui.label(label).classes("font-mono text-xs fr-accent")
                    return
                with ui.expansion(label).props("dense dense-toggle expand-icon-class=text-xs").classes(
                    "w-full font-mono text-xs fr-accent"
                ):
                    ui.label(body).classes("font-mono text-xs fr-muted whitespace-pre-wrap")

    def deferred_answer_bubble():
        """Hand back a maker for this turn's assistant bubble, built on first use.

        NiceGUI appends in call order, so a bubble created before the turn starts sits *above*
        the tool events that follow it — the answer would read before the work it is based on.
        Created on the first token instead, it lands under them, which is also the order the
        stored history renders in.
        """
        holder: list = []

        def bubble():
            if not holder:
                holder.append(render_message("assistant", ""))
            return holder[0]

        return bubble

    def render_welcome(no_chat: bool) -> None:
        username = account.username or "there"
        hints = [
            ("tune", "Switch model right in the message box below."),
            ("folder", "Your chats are grouped by project in the sidebar."),
            ("psychology", f"Facts are remembered across a project's chats — {config.DEFAULT_PROJECT_NAME} included."),
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
                calls = json.loads(m.tool_calls)
                names = ", ".join(c["function"]["name"] for c in calls)
                # The arguments, same as the live path shows — so a reloaded chat folds open
                # to what it folded open to while it was being written.
                args = "\n".join(c["function"].get("arguments", "") for c in calls).strip()
                render_tool_event(f"→ tool call: {names}", args or m.content or "")
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
        # No "unfiled" entry: every chat has a project, the default one included, because
        # that is what gives an unfiled chat a memory scope.
        ui.select(
            _project_names(),
            value=state["project_id"],
            label="New chats go to",
            on_change=lambda e: on_project_change(e.value),
        ).classes("w-full").props("outlined dense options-dense")

    @ui.refreshable
    def conversation_list_ui() -> None:
        """Every chat of the user, grouped under the project it belongs to."""
        names = _project_names()
        groups: dict[str, list] = {}
        for c in services.list_conversations(uid):
            # A chat whose project was deleted is shown where it will actually be filed the
            # next time it is used — the default project.
            groups.setdefault(c.project_id if c.project_id in names else default_pid, []).append(c)
        if not groups:
            ui.label("No conversations yet.").classes("fr-muted text-sm p-2")
            return
        order = [default_pid] if default_pid in groups else []
        order += [pid for pid in names if pid in groups and pid != default_pid]
        for pid in order:
            active_group = pid == state["project_id"]
            with ui.row().classes("w-full items-center no-wrap gap-1 px-2 pt-3 pb-1"):
                ui.icon("inbox" if pid == default_pid else "folder").classes(
                    "text-sm " + ("fr-accent" if active_group else "fr-muted")
                )
                ui.label(names[pid]).classes(
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
    def on_project_change(project_id: str) -> None:
        # only decides where new chats land — the list itself always shows every project
        state["project_id"] = project_id
        conversation_list_ui.refresh()

    def model_options() -> dict[str, str]:
        return {m.id: m.label for m in config.MODELS}

    def select_conversation(cid: str) -> None:
        state["conversation_id"] = cid
        conv = services.get_conversation(cid)
        if conv:
            state["project_id"] = conv.project_id or default_pid
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

    def on_model_change(model_id: str) -> None:
        """Record the choice. Every configured model is offered, unconditionally.

        The selector used to probe each endpoint on a timer and grey out whatever did not
        answer. That lost races it had no business entering: a 7B mid-generation does not
        always answer `/v1/models` inside the probe timeout, so entries flickered to
        "not loaded" while they were serving fine. Whether a server is up is settled by
        asking it for an answer — `send()` does that, and reports a failure where it
        happens, next to the message it belongs to.
        """
        if model_id == state["model_id"]:
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
        scroll_bottom()
        acc: list[str] = []
        answer = deferred_answer_bubble()
        state["stop_event"] = asyncio.Event()
        set_generating(True)
        try:
            async for ev in engine.generate(conv, text, stop_event=state["stop_event"]):
                if ev["type"] == "token":
                    acc.append(ev["text"])
                    answer().set_content("".join(acc))
                elif ev["type"] == "tool_call":
                    render_tool_event(f"→ tool call: {ev['name']}", ev["arguments"])
                elif ev["type"] == "tool_result":
                    render_tool_event(f"← {ev['name']} output", ev["result"])
                elif ev["type"] == "done" and not acc:
                    answer().set_content(ev["content"])
                scroll_bottom()
        except Exception as e:
            # The one place a down endpoint shows up. Report it against the message that hit
            # it, with the command that fixes it, and leave the chat usable — the selector
            # deliberately no longer tries to predict this ahead of time.
            spec = config.model_spec(state["model_id"])
            answer().set_content(
                "".join(acc) + f"\n\n**{spec.label} did not answer.** `{e}`\n\n"
                f"Start it with: `{_serve_hint(spec)}`"
            )
            ui.notify(f"{spec.label} did not answer — see the message for the command", type="warning")
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
        # Always has a scope: the open chat's project, or — with no chat open — wherever the
        # next one would land. Nothing to assign first.
        conv = current_conversation()
        pid = services.conversation_project(conv) if conv else state["project_id"]

        with ui.dialog() as dialog, ui.card().classes("w-[36rem] fr-surface"):
            ui.label(f"Memory · {_project_names().get(pid, config.DEFAULT_PROJECT_NAME)}").classes("text-lg")
            ui.label("Recalled in every chat of this project.").classes("text-xs fr-muted")

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
                    await asyncio.to_thread(memory.remember, pid, note.value.strip(), conv.id if conv else None)
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
