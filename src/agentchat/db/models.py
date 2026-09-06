from __future__ import annotations

import uuid
from datetime import UTC
from datetime import datetime

from sqlmodel import Field
from sqlmodel import SQLModel


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


class User(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    username: str = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=_now)


class Project(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    user_id: str = Field(index=True, foreign_key="user.id")
    name: str
    created_at: datetime = Field(default_factory=_now)


class Conversation(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    user_id: str = Field(index=True, foreign_key="user.id")
    project_id: str | None = Field(default=None, index=True, foreign_key="project.id")
    title: str = "New chat"
    model_id: str = "qwen2.5-7b"
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class Message(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    conversation_id: str = Field(index=True, foreign_key="conversation.id")
    role: str  # system | user | assistant | tool
    content: str = ""
    # tool-calling metadata (JSON strings / ids), used to reconstruct API context
    tool_calls: str | None = None  # assistant turns that requested tools
    tool_call_id: str | None = None  # tool result turns
    name: str | None = None  # tool name for tool result turns
    created_at: datetime = Field(default_factory=_now)


class MemoryItem(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    project_id: str = Field(index=True, foreign_key="project.id")
    content: str
    embedding: bytes  # float32 vector
    source_conversation_id: str | None = None
    created_at: datetime = Field(default_factory=_now)


class ToolDef(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    user_id: str = Field(index=True, foreign_key="user.id")
    name: str
    type: str = "shell"  # shell | python
    command: str = ""
    args: str = "[]"  # JSON list of {name, description?}
    description: str = ""
    created_at: datetime = Field(default_factory=_now)
