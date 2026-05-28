"""Tests for the policy engine."""

from pathlib import Path
from textwrap import dedent

from memory_governance.policy import Policy, load_policy, PiiPolicy, AccessRule, RetentionPolicy


def test_default_policy():
    policy = load_policy(Path("/nonexistent/policy.yaml"))
    assert policy.can_read("default", "project")
    assert policy.can_read("default", "feedback")
    assert policy.can_write("default", "project")
    assert not policy.can_write("default", "feedback")


def test_load_policy_from_yaml(tmp_path):
    policy_file = tmp_path / "policy.yaml"
    policy_file.write_text(dedent("""\
        retention:
          project:
            max_age_days: 365
            episode_cap: 10
        access:
          roles:
            analyst:
              read: [project, resource]
              write: [project]
            compliance:
              read: [project, area, feedback, resource]
              write: []
        pii:
          enabled: true
          redact_emails: true
          redact_urls: true
    """))
    policy = load_policy(policy_file)
    assert policy.can_read("analyst", "project")
    assert policy.can_read("analyst", "resource")
    assert not policy.can_read("analyst", "feedback")
    assert policy.can_write("analyst", "project")
    assert policy.can_read("compliance", "feedback")
    assert not policy.can_write("compliance", "project")
    assert policy.pii.redact_urls is True


def test_pii_redaction():
    policy = Policy(pii=PiiPolicy(enabled=True))
    text = "Contact john@example.com or call +1-555-123-4567. Token: Bearer abc123xyz"
    redacted, detections = policy.redact_pii(text)
    assert "john@example.com" not in redacted
    assert "[REDACTED:email]" in redacted
    assert "[REDACTED:phone]" in redacted
    assert "abc123xyz" not in redacted
    assert any("email" in d for d in detections)


def test_pii_disabled():
    policy = Policy(pii=PiiPolicy(enabled=False))
    text = "john@example.com"
    redacted, detections = policy.redact_pii(text)
    assert redacted == text
    assert detections == []


def test_unknown_role_denied():
    policy = Policy(access={"analyst": AccessRule(read=["project"], write=[])})
    assert not policy.can_read("unknown_role", "project")
    assert not policy.can_write("unknown_role", "project")
