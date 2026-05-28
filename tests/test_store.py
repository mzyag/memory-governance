"""Tests for the memory store."""

from memory_governance.policy import Policy
from memory_governance.store import MemoryStore


def test_create_and_list(tmp_path):
    store = MemoryStore(tmp_path, Policy())
    result = store.create_memory("test-project", "A test project", "project")
    assert result["status"] == "created"
    assert result["file"] == "ap-test-project.md"

    memories = store.list_memories()
    assert len(memories) == 1
    assert memories[0]["name"] == "ap-test-project"


def test_write_episode_and_dedup(tmp_path):
    store = MemoryStore(tmp_path, Policy())
    store.create_memory("test", "test", "project")

    r1 = store.write_episode("ap-test.md", "- **2026-05-28** [success] build something → it worked")
    assert r1["status"] == "written"

    r2 = store.write_episode("ap-test.md", "- **2026-05-28** [success] build something → it worked")
    assert r2["status"] == "skipped"
    assert r2["reason"] == "duplicate"


def test_episode_cap_triggers_compact(tmp_path):
    from memory_governance.policy import RetentionPolicy
    policy = Policy(retention={"project": RetentionPolicy(episode_cap=3)})
    store = MemoryStore(tmp_path, policy)
    store.create_memory("test", "test", "project")

    for i in range(5):
        store.write_episode("ap-test.md", f"- **2026-05-{i+1:02d}** [success] task {i}")

    content = (tmp_path / "ap-test.md").read_text()
    assert "> **Archive**" in content
    assert (tmp_path / "episodes" / "ap-test.archive.md").exists()


def test_filter_by_category(tmp_path):
    store = MemoryStore(tmp_path, Policy())
    store.create_memory("proj", "a project", "project")
    store.create_memory("fb", "a feedback", "feedback")

    projects = store.list_memories(category="project")
    assert len(projects) == 1
    assert projects[0]["category"] == "project"

    feedbacks = store.list_memories(category="feedback")
    assert len(feedbacks) == 1
    assert feedbacks[0]["category"] == "feedback"


def test_staleness_check(tmp_path):
    store = MemoryStore(tmp_path, Policy())
    store.create_memory("old", "old project", "project")
    # Manually set an old date
    f = tmp_path / "ap-old.md"
    content = f.read_text()
    f.write_text(content.replace("updated: 2026-", "updated: 2025-"))

    stale = store.get_stale_memories(max_age_days=30)
    assert len(stale) == 1
    assert stale[0]["file"] == "ap-old.md"
