"""Tests for the audit logger."""

from memory_governance.audit import AuditLogger


def test_log_and_query(tmp_path):
    logger = AuditLogger(tmp_path / "audit.jsonl")
    logger.log("read", role="analyst", category="project", target="ap-test.md")
    logger.log("write", role="default", category="project", target="ap-test.md")
    logger.log("read", role="compliance", category="feedback", target="fb-rules.md")

    all_entries = logger.query()
    assert len(all_entries) == 3

    reads = logger.query(action="read")
    assert len(reads) == 2

    by_role = logger.query(role="compliance")
    assert len(by_role) == 1
    assert by_role[0]["target"] == "fb-rules.md"


def test_pii_detections_logged(tmp_path):
    logger = AuditLogger(tmp_path / "audit.jsonl")
    logger.log("write", pii_detections=["email:test@example.com", "phone:555-1234"])

    entries = logger.query()
    assert len(entries) == 1
    assert "email:test@example.com" in entries[0]["pii_detections"]
