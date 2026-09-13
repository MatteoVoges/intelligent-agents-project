"""Data-access layer. Each function opens a short-lived session (SQLite + WAL)."""

from __future__ import annotations

from datetime import UTC
from datetime import datetime

from sqlmodel import select

from . import config
from .db.database import session
from .db.models import Conversation
from .db.models import MemoryItem
from .db.models import Message
from .db.models import Project
from .db.models import ToolDef
from .db.models import User


def _now() -> datetime:
    return datetime.now(UTC)


# --- users -------------------------------------------------------------------
def get_or_create_user(username: str) -> User:
    with session() as s:
        user = s.exec(select(User).where(User.username == username)).first()
        if user is None:
            user = User(username=username)
            s.add(user)
            s.commit()
            s.refresh(user)
    default_project(user.id)  # created up front, so no chat is ever without a memory scope
    return user


def get_user(user_id: str) -> User | None:
    with session() as s:
        return s.get(User, user_id)


# --- projects ----------------------------------------------------------------
def default_project(user_id: str) -> Project:
    """The project a chat belongs to when you never file it anywhere.

    Memory is scoped to a project, so without this an unfiled chat would silently have no
    cross-chat recall at all. Identified by name rather than a flag column: that keeps the
    schema migration-free, and a user who deliberately names a project this just gets that
    one, which is the behaviour they were asking for anyway.
    """
    with session() as s:
        p = s.exec(
            select(Project).where(Project.user_id == user_id, Project.name == config.DEFAULT_PROJECT_NAME)
        ).first()
        if p is None:
            p = Project(user_id=user_id, name=config.DEFAULT_PROJECT_NAME)
            s.add(p)
            s.commit()
            s.refresh(p)
        return p


def conversation_project(conversation) -> str:
    """The project id whose memory this conversation reads and writes.

    Rows written before the default project existed still carry NULL, as do chats whose
    project was deleted; adopt them on first use so recall does not depend on when the chat
    happened to be created.
    """
    if conversation.project_id:
        return conversation.project_id
    pid = default_project(conversation.user_id).id
    set_conversation_project(conversation.id, pid)
    conversation.project_id = pid
    return pid


def list_projects(user_id: str) -> list[Project]:
    with session() as s:
        return list(s.exec(select(Project).where(Project.user_id == user_id).order_by(Project.created_at)))


def create_project(user_id: str, name: str) -> Project:
    with session() as s:
        p = Project(user_id=user_id, name=name)
        s.add(p)
        s.commit()
        s.refresh(p)
        return p


def delete_project(project_id: str) -> None:
    with session() as s:
        # Detach the conversations and drop the project's memory. A detached chat falls back
        # to the default project the next time it is used — see `conversation_project`.
        for conv in s.exec(select(Conversation).where(Conversation.project_id == project_id)):
            conv.project_id = None
            s.add(conv)
        for mem in s.exec(select(MemoryItem).where(MemoryItem.project_id == project_id)):
            s.delete(mem)
        p = s.get(Project, project_id)
        if p:
            s.delete(p)
        s.commit()


# --- conversations -----------------------------------------------------------
def list_conversations(user_id: str, project_id: str | None = None) -> list[Conversation]:
    with session() as s:
        q = select(Conversation).where(Conversation.user_id == user_id)
        if project_id is not None:
            q = q.where(Conversation.project_id == project_id)
        return list(s.exec(q.order_by(Conversation.updated_at.desc())))


def get_conversation(conversation_id: str) -> Conversation | None:
    with session() as s:
        return s.get(Conversation, conversation_id)


def create_conversation(user_id: str, project_id: str | None = None, model_id: str | None = None) -> Conversation:
    # No chat is project-less: an unfiled one lands in the default project, so its memory is
    # shared with every other unfiled chat instead of being discarded.
    project_id = project_id or default_project(user_id).id
    with session() as s:
        c = Conversation(
            user_id=user_id,
            project_id=project_id,
            model_id=model_id or config.DEFAULT_MODEL_ID,
        )
        s.add(c)
        s.commit()
        s.refresh(c)
        return c


def rename_conversation(conversation_id: str, title: str) -> None:
    with session() as s:
        c = s.get(Conversation, conversation_id)
        if c:
            c.title = title[:120]
            s.add(c)
            s.commit()


def set_conversation_model(conversation_id: str, model_id: str) -> None:
    with session() as s:
        c = s.get(Conversation, conversation_id)
        if c:
            c.model_id = model_id
            s.add(c)
            s.commit()


def set_conversation_project(conversation_id: str, project_id: str | None) -> None:
    with session() as s:
        c = s.get(Conversation, conversation_id)
        if c:
            c.project_id = project_id
            s.add(c)
            s.commit()


def touch_conversation(conversation_id: str) -> None:
    with session() as s:
        c = s.get(Conversation, conversation_id)
        if c:
            c.updated_at = _now()
            s.add(c)
            s.commit()


def delete_conversation(conversation_id: str) -> None:
    with session() as s:
        for m in s.exec(select(Message).where(Message.conversation_id == conversation_id)):
            s.delete(m)
        c = s.get(Conversation, conversation_id)
        if c:
            s.delete(c)
        s.commit()


# --- messages ----------------------------------------------------------------
def list_messages(conversation_id: str) -> list[Message]:
    with session() as s:
        return list(
            s.exec(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at))
        )


def add_message(
    conversation_id: str,
    role: str,
    content: str,
    *,
    tool_calls: str | None = None,
    tool_call_id: str | None = None,
    name: str | None = None,
) -> Message:
    with session() as s:
        m = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
            name=name,
        )
        s.add(m)
        s.commit()
        s.refresh(m)
        return m


# --- memory ------------------------------------------------------------------
def add_memory_item(
    project_id: str, content: str, embedding: bytes, source_conversation_id: str | None = None
) -> MemoryItem:
    with session() as s:
        item = MemoryItem(
            project_id=project_id,
            content=content,
            embedding=embedding,
            source_conversation_id=source_conversation_id,
        )
        s.add(item)
        s.commit()
        s.refresh(item)
        return item


def list_memory(project_id: str) -> list[MemoryItem]:
    with session() as s:
        return list(
            s.exec(select(MemoryItem).where(MemoryItem.project_id == project_id).order_by(MemoryItem.created_at.desc()))
        )


def delete_memory_item(item_id: str) -> None:
    with session() as s:
        item = s.get(MemoryItem, item_id)
        if item:
            s.delete(item)
            s.commit()


# --- tools -------------------------------------------------------------------
def list_tools(user_id: str) -> list[ToolDef]:
    with session() as s:
        return list(s.exec(select(ToolDef).where(ToolDef.user_id == user_id).order_by(ToolDef.created_at)))


def get_tool(user_id: str, name: str) -> ToolDef | None:
    with session() as s:
        return s.exec(select(ToolDef).where(ToolDef.user_id == user_id, ToolDef.name == name)).first()


def create_tool(user_id: str, name: str, type: str, command: str, args: str, description: str) -> ToolDef:
    with session() as s:
        t = ToolDef(
            user_id=user_id,
            name=name,
            type=type,
            command=command,
            args=args,
            description=description,
        )
        s.add(t)
        s.commit()
        s.refresh(t)
        return t


def delete_tool(tool_id: str) -> None:
    with session() as s:
        t = s.get(ToolDef, tool_id)
        if t:
            s.delete(t)
            s.commit()
