# memory-governance

**English** | [中文](README.zh-CN.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776ab.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-compatible-green.svg)](https://modelcontextprotocol.io/)
[![Tests](https://img.shields.io/badge/tests-13%20passed-brightgreen.svg)](#)

**Your AI agent remembers your database passwords. Who else can read that memory? When does it get deleted? Can you prove what it knew when it made a decision?**

Memory Governance is a policy layer for AI agent memory, delivered as an [MCP](https://modelcontextprotocol.io/) server. It sits between your AI tools and their memory storage, enforcing access control, audit trails, retention policies, and PII redaction — so you don't have to trust the agent to govern itself.

```
AI Agent (Claude / Cursor / Copilot)
         │
         ▼
┌─────────────────────────┐
│  memory-governance      │  ← policy enforcement happens here
│  (MCP Server)           │
│                         │
│  Access control (RBAC)  │
│  Audit logging          │
│  PII redaction          │
│  Episode cap + dedup    │
│  Retention policies     │
└─────────┬───────────────┘
          ▼
   Memory Storage (flat files)
```

## Why

AI coding assistants now have persistent memory. That's powerful — and risky:

- **No access control.** Every tool that can read the memory directory sees everything: project secrets, user corrections, compliance notes.
- **No audit trail.** You can't answer "what did the agent know when it generated that code?" — a question regulators will eventually ask.
- **No retention policy.** PII captured in episode logs stays forever unless someone manually cleans it.
- **No PII protection.** An email address in a task description gets stored as-is in the memory file.

These aren't hypothetical risks. They're the reality of running AI agents in any environment that cares about data governance — financial services, healthcare, government, or any team with compliance requirements.

## Quick Start

### Install

```bash
pip install memory-governance
```

Or from source:

```bash
git clone https://github.com/mzyag/memory-governance.git
cd memory-governance
pip install -e .
```

### Configure

Create a `policy.yaml`:

```yaml
retention:
  project:
    max_age_days: 365
    episode_cap: 10
  feedback:
    max_age_days: null   # never expires

access:
  roles:
    default:
      read: [project, area, feedback, resource]
      write: [project]
    compliance_officer:
      read: [project, area, feedback, resource]
      write: []           # read-only

pii:
  enabled: true
  redact_emails: true
  redact_phones: true
  redact_tokens: true

audit:
  retention_days: 2555    # ~7 years
```

### Connect to Claude Code

Add to your Claude Code MCP settings (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "memory-governance": {
      "command": "memory-governance",
      "env": {
        "MG_POLICY_FILE": "/path/to/policy.yaml",
        "MG_MEMORY_DIR": "/path/to/memory",
        "MG_ROLE": "default"
      }
    }
  }
}
```

### Connect to Cursor

Add to `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "memory-governance": {
      "command": "memory-governance",
      "env": {
        "MG_POLICY_FILE": "./policy.yaml",
        "MG_MEMORY_DIR": "./.memory",
        "MG_ROLE": "default"
      }
    }
  }
}
```

## Tools

The server exposes six tools to any MCP-compatible AI client:

| Tool | Description |
|------|-------------|
| `list_memories` | List memory files, optionally filtered by category |
| `read_memory` | Read a file — access control enforced |
| `write_episode` | Append an episode — PII redaction, dedup, cap enforcement |
| `create_memory` | Create a new memory file with proper frontmatter |
| `check_staleness` | Find memories that haven't been updated recently |
| `query_audit_log` | Search the audit trail by date, action, role, or category |

Every operation is logged to `audit.jsonl` with timestamp, role, action, target, outcome, and any PII detections.

## Memory Schema

Memory files use a minimal 4-field YAML frontmatter:

```yaml
---
name: ap-my-project
description: One-line summary for relevance matching
category: project        # project | area | feedback | resource
updated: 2026-05-28
---
```

Four categories with different governance profiles:

| Category | Prefix | Default Access | Typical Content |
|----------|--------|---------------|-----------------|
| `project` | `ap-` | read + write | Architecture, decisions, episode logs |
| `area` | `area-` | read only | User profile, ongoing responsibilities |
| `feedback` | `fb-` | read only | Behavioral corrections, validated approaches |
| `resource` | `res-` | read only | External references, service pointers |

## Policy-as-Code

All governance rules live in a single YAML file — version-controlled, auditable, reviewable:

- **Access control**: RBAC per role per category. An `analyst` can read projects but not feedback; a `compliance_officer` can read everything but write nothing.
- **Retention**: Per-category `max_age_days` and `episode_cap`. When a file exceeds its cap, oldest episodes archive automatically.
- **PII redaction**: Emails, phone numbers, bearer tokens, and API keys are detected and replaced with `[REDACTED:type]` before storage.
- **Audit**: Every read, write, create, and denied access is logged with full context.

## Design Principles

1. **Governance at the boundary, not in the prompt.** Telling an agent "don't store PII" is advisory (70-90% compliance). Redacting PII in the server is deterministic (100%).
2. **Storage-agnostic.** This version uses flat Markdown files. The governance layer doesn't care — swap in SQLite, S3, or a vector DB without changing policies.
3. **Policy-as-code.** YAML in version control, not buried in UI settings. Reviewable in PRs. Auditable by compliance teams.
4. **Local-first.** Your memory stays on your machine. The server runs locally. No cloud dependency.

## Background

This project grew out of eight months of running AI agents in a regulated financial services environment. The memory architecture, four-dimension taxonomy, and governance patterns are documented in detail:

- [Memory Architecture for Production Agents](https://mzyag.github.io/writing/memory-architecture.html) — three-tier design, content taxonomy, budget-aware injection
- [Maintaining an Agent's Knowledge Layer](https://mzyag.github.io/writing/optimizing-agent-knowledge-layer.html) — episode noise, write-path hardening, gate amnesia

## License

MIT
