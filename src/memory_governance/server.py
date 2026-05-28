"""MCP server exposing governed memory operations."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .audit import AuditLogger
from .policy import Policy, load_policy
from .store import MemoryStore

POLICY_PATH = Path(os.environ.get("MG_POLICY_FILE", "policy.yaml"))
MEMORY_DIR = Path(os.environ.get("MG_MEMORY_DIR", ".memory"))
AUDIT_PATH = Path(os.environ.get("MG_AUDIT_FILE", ".memory/audit.jsonl"))
ROLE = os.environ.get("MG_ROLE", "default")


def _build_server() -> tuple[Server, Policy, MemoryStore, AuditLogger]:
    policy = load_policy(POLICY_PATH)
    store = MemoryStore(MEMORY_DIR, policy)
    audit = AuditLogger(AUDIT_PATH)
    server = Server("memory-governance")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="list_memories",
                description="List all memory files, optionally filtered by category (project/area/feedback/resource).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "description": "Filter by category: project, area, feedback, or resource.",
                            "enum": ["project", "area", "feedback", "resource"],
                        },
                    },
                },
            ),
            Tool(
                name="read_memory",
                description="Read a memory file. Access control enforced by policy.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "file": {
                            "type": "string",
                            "description": "Filename to read (e.g. ap-my-project.md).",
                        },
                    },
                    "required": ["file"],
                },
            ),
            Tool(
                name="write_episode",
                description="Append an episode entry to a memory file. Enforces write access, PII redaction, dedup, and episode cap.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "file": {
                            "type": "string",
                            "description": "Target memory file (e.g. ap-my-project.md).",
                        },
                        "date": {
                            "type": "string",
                            "description": "Episode date in YYYY-MM-DD format.",
                        },
                        "outcome": {
                            "type": "string",
                            "description": "Episode outcome.",
                            "enum": ["success", "partial", "failure"],
                        },
                        "goal": {
                            "type": "string",
                            "description": "What was the goal of this task.",
                        },
                        "reflection": {
                            "type": "string",
                            "description": "What was learned or what to reuse next time.",
                        },
                    },
                    "required": ["file", "date", "outcome", "goal"],
                },
            ),
            Tool(
                name="create_memory",
                description="Create a new memory file with proper frontmatter.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Short kebab-case name for the memory (e.g. my-new-project).",
                        },
                        "description": {
                            "type": "string",
                            "description": "One-line description of what this memory tracks.",
                        },
                        "category": {
                            "type": "string",
                            "description": "Memory category.",
                            "enum": ["project", "area", "feedback", "resource"],
                        },
                    },
                    "required": ["name", "description", "category"],
                },
            ),
            Tool(
                name="check_staleness",
                description="List memory files that haven't been updated within a given number of days.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "max_age_days": {
                            "type": "integer",
                            "description": "Flag memories older than this many days (default: 30).",
                        },
                    },
                },
            ),
            Tool(
                name="query_audit_log",
                description="Query the audit trail of memory operations.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "start_date": {
                            "type": "string",
                            "description": "ISO date to start from (e.g. 2026-05-01).",
                        },
                        "end_date": {
                            "type": "string",
                            "description": "ISO date to end at.",
                        },
                        "action": {
                            "type": "string",
                            "description": "Filter by action type.",
                            "enum": ["read", "write", "create", "list", "denied"],
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max results to return (default: 50).",
                        },
                    },
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        import json

        if name == "list_memories":
            category = arguments.get("category")
            if category and not policy.can_read(ROLE, category):
                audit.log("list", role=ROLE, category=category or "", outcome="denied")
                return [TextContent(type="text", text=f"Access denied: role '{ROLE}' cannot read category '{category}'.")]
            result = store.list_memories(category=category)
            audit.log("list", role=ROLE, category=category or "all", outcome="allowed", detail=f"{len(result)} files")
            return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

        elif name == "read_memory":
            filename = arguments["file"]
            meta = store.read_memory(filename)
            if "error" in meta:
                return [TextContent(type="text", text=meta["error"])]
            category = meta.get("metadata", {}).get("category", "project")
            if not policy.can_read(ROLE, category):
                audit.log("read", role=ROLE, category=category, target=filename, outcome="denied")
                return [TextContent(type="text", text=f"Access denied: role '{ROLE}' cannot read category '{category}'.")]
            audit.log("read", role=ROLE, category=category, target=filename, outcome="allowed")
            return [TextContent(type="text", text=meta["content"])]

        elif name == "write_episode":
            filename = arguments["file"]
            meta = store.read_memory(filename)
            if "error" in meta:
                return [TextContent(type="text", text=meta["error"])]
            category = meta.get("metadata", {}).get("category", "project")
            if not policy.can_write(ROLE, category):
                audit.log("write", role=ROLE, category=category, target=filename, outcome="denied")
                return [TextContent(type="text", text=f"Access denied: role '{ROLE}' cannot write to category '{category}'.")]
            goal = arguments["goal"]
            reflection = arguments.get("reflection", "")
            goal, goal_pii = policy.redact_pii(goal)
            reflection, refl_pii = policy.redact_pii(reflection)
            all_pii = goal_pii + refl_pii
            entry = f"- **{arguments['date']}** [{arguments['outcome']}] {goal}"
            if reflection:
                entry += f" → {reflection}"
            result = store.write_episode(filename, entry)
            audit.log(
                "write", role=ROLE, category=category, target=filename,
                outcome="allowed", detail=json.dumps(result, ensure_ascii=False),
                pii_detections=all_pii,
            )
            return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

        elif name == "create_memory":
            cat = arguments["category"]
            if not policy.can_write(ROLE, cat):
                audit.log("create", role=ROLE, category=cat, outcome="denied")
                return [TextContent(type="text", text=f"Access denied: role '{ROLE}' cannot write to category '{cat}'.")]
            result = store.create_memory(arguments["name"], arguments["description"], cat)
            audit.log("create", role=ROLE, category=cat, target=result.get("file", ""), outcome="allowed")
            return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

        elif name == "check_staleness":
            max_age = arguments.get("max_age_days", 30)
            result = store.get_stale_memories(max_age)
            return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

        elif name == "query_audit_log":
            result = audit.query(
                start_date=arguments.get("start_date"),
                end_date=arguments.get("end_date"),
                action=arguments.get("action"),
                limit=arguments.get("limit", 50),
            )
            return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    return server, policy, store, audit


async def _run() -> None:
    server, *_ = _build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
