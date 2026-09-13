"""Unfiled chats still have a memory scope.

Memory is stored per project, so before the default project existed a chat you never filed
had no cross-chat recall at all — silently, which is the worst version of that. These tests
pin the two halves of the fix: new chats get the default project, and older rows that still
carry NULL adopt it the first time they are used.
"""

import pytest

from agentchat import config
from agentchat import services
from agentchat.db import database
from agentchat.db.models import Conversation


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(database, "_engine", None, raising=False)
    database.init_db()


def test_default_project_exists_from_the_first_login() -> None:
    user = services.get_or_create_user("alice")
    names = [p.name for p in services.list_projects(user.id)]
    assert names == [config.DEFAULT_PROJECT_NAME]


def test_default_project_is_stable_across_calls() -> None:
    user = services.get_or_create_user("alice")
    assert services.default_project(user.id).id == services.default_project(user.id).id
    assert len(services.list_projects(user.id)) == 1


def test_unfiled_chats_share_one_memory_scope() -> None:
    user = services.get_or_create_user("alice")
    first = services.create_conversation(user.id)
    second = services.create_conversation(user.id)
    assert first.project_id == second.project_id == services.default_project(user.id).id


def test_an_explicit_project_still_wins() -> None:
    user = services.get_or_create_user("alice")
    thesis = services.create_project(user.id, "Thesis")
    conv = services.create_conversation(user.id, thesis.id)
    assert conv.project_id == thesis.id
    assert services.conversation_project(conv) == thesis.id


def test_a_legacy_null_row_is_adopted_on_use() -> None:
    """Rows written by an older build, and chats whose project was deleted, both hit this."""
    user = services.get_or_create_user("alice")
    with database.session() as s:
        conv = Conversation(user_id=user.id, project_id=None)
        s.add(conv)
        s.commit()
        s.refresh(conv)

    pid = services.conversation_project(conv)

    assert pid == services.default_project(user.id).id
    assert conv.project_id == pid  # the in-memory object is updated too, not just the row
    assert services.get_conversation(conv.id).project_id == pid  # and it was persisted


def test_each_user_gets_their_own_default_project() -> None:
    alice = services.get_or_create_user("alice")
    bob = services.get_or_create_user("bob")
    assert services.default_project(alice.id).id != services.default_project(bob.id).id
