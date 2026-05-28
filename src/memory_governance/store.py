"""Flat-file memory store with governance enforcement."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .policy import Policy, RetentionPolicy

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)
EPISODE_ENTRY_RE = re.compile(r"^- \*\*\d{4}-\d{2}-\d{2}\*\*.*\[.+\]")


class MemoryStore:
    def __init__(self, memory_dir: Path | str, policy: Policy) -> None:
        self._dir = Path(memory_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._policy = policy

    @property
    def memory_dir(self) -> Path:
        return self._dir

    def list_memories(self, *, category: str | None = None) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        for f in sorted(self._dir.glob("*.md")):
            if f.name == "MEMORY.md":
                continue
            meta = self._read_frontmatter(f)
            if category and meta.get("category") != category:
                continue
            results.append({
                "file": f.name,
                "name": meta.get("name", f.stem),
                "description": meta.get("description", ""),
                "category": meta.get("category", ""),
                "updated": meta.get("updated", ""),
            })
        return results

    def read_memory(self, filename: str) -> dict[str, Any]:
        filepath = self._dir / filename
        if not filepath.exists():
            return {"error": f"File not found: {filename}"}
        content = filepath.read_text("utf-8")
        meta = self._read_frontmatter(filepath)
        return {
            "file": filename,
            "metadata": meta,
            "content": content,
        }

    def write_episode(
        self,
        filename: str,
        entry: str,
    ) -> dict[str, Any]:
        filepath = self._dir / filename
        if not filepath.exists():
            return {"error": f"File not found: {filename}"}

        content = filepath.read_text("utf-8")

        # Dedup check — first 60 chars
        dedup_key = entry[:min(len(entry), 60)]
        if dedup_key in content:
            return {"status": "skipped", "reason": "duplicate"}

        # Ensure Episode Log section exists
        if "## Episode Log" not in content:
            if not content.endswith("\n"):
                content += "\n"
            content += "\n## Episode Log\n"

        if not content.endswith("\n"):
            content += "\n"
        content += entry + "\n"
        filepath.write_text(content, "utf-8")

        # Update timestamp
        self._update_timestamp(filepath)

        # Check episode cap
        meta = self._read_frontmatter(filepath)
        category = meta.get("category", "project")
        retention = self._policy.get_retention(category)
        ep_count = self._count_episodes(filepath)
        compacted = False
        if ep_count > retention.episode_cap:
            self._compact(filepath, retention.episode_cap)
            compacted = True

        return {
            "status": "written",
            "file": filename,
            "episode_count": self._count_episodes(filepath),
            "compacted": compacted,
        }

    def create_memory(
        self,
        name: str,
        description: str,
        category: str = "project",
    ) -> dict[str, Any]:
        safe_name = re.sub(r"[^a-z0-9-]", "-", name.lower())[:40].strip("-")
        prefix = {"project": "ap-", "area": "area-", "feedback": "fb-", "resource": "res-"}.get(category, "ap-")
        filename = f"{prefix}{safe_name}.md"
        filepath = self._dir / filename
        if filepath.exists():
            return {"status": "exists", "file": filename}
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        content = f"""---
name: {prefix}{safe_name}
description: {description}
category: {category}
updated: {today}
---

## Episode Log
"""
        filepath.write_text(content, "utf-8")
        return {"status": "created", "file": filename}

    def get_stale_memories(self, max_age_days: int = 30) -> list[dict[str, str]]:
        cutoff = datetime.now(timezone.utc)
        results: list[dict[str, str]] = []
        for f in sorted(self._dir.glob("*.md")):
            if f.name == "MEMORY.md":
                continue
            meta = self._read_frontmatter(f)
            updated = meta.get("updated", "")
            if not updated:
                continue
            try:
                updated_dt = datetime.strptime(updated, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            age_days = (cutoff - updated_dt).days
            if age_days > max_age_days:
                results.append({
                    "file": f.name,
                    "category": meta.get("category", ""),
                    "updated": updated,
                    "age_days": str(age_days),
                })
        return results

    def _read_frontmatter(self, filepath: Path) -> dict[str, str]:
        content = filepath.read_text("utf-8")
        match = FRONTMATTER_RE.match(content)
        if not match:
            return {}
        try:
            data = yaml.safe_load(match.group(1))
            return {str(k): str(v) for k, v in (data or {}).items()}
        except yaml.YAMLError:
            return {}

    def _count_episodes(self, filepath: Path) -> int:
        count = 0
        for line in filepath.read_text("utf-8").splitlines():
            if EPISODE_ENTRY_RE.match(line):
                count += 1
        return count

    def _update_timestamp(self, filepath: Path) -> None:
        content = filepath.read_text("utf-8")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        content = re.sub(r"updated: \d{4}-\d{2}-\d{2}", f"updated: {today}", content)
        filepath.write_text(content, "utf-8")

    def _compact(self, filepath: Path, keep: int) -> None:
        content = filepath.read_text("utf-8")
        if "## Episode Log" not in content:
            return
        parts = content.split("## Episode Log", 1)
        header = parts[0]
        log_section = parts[1] if len(parts) > 1 else ""

        episodes: list[str] = []
        non_episodes: list[str] = []
        for line in log_section.strip().splitlines():
            if EPISODE_ENTRY_RE.match(line):
                episodes.append(line)
            elif line.startswith("> **Archive**"):
                continue
            elif line.strip():
                non_episodes.append(line)

        if len(episodes) <= keep:
            return

        old = episodes[:-keep]
        recent = episodes[-keep:]

        success = sum(1 for e in old if "[success]" in e)
        partial = sum(1 for e in old if "[partial]" in e)
        failure = len(old) - success - partial

        dates = [m.group(1) for e in old if (m := re.search(r"\*\*(\d{4}-\d{2}-\d{2})\*\*", e))]
        date_range = f"{dates[0]} to {dates[-1]}" if dates else "unknown"

        archive_summary = (
            f"> **Archive**: {len(old)} earlier episodes ({date_range}). "
            f"{success} success, {partial} partial, {failure} failure."
        )

        # Write archive
        episodes_dir = self._dir / "episodes"
        episodes_dir.mkdir(exist_ok=True)
        archive_path = episodes_dir / filepath.with_suffix(".archive.md").name
        if archive_path.exists():
            existing = archive_path.read_text("utf-8")
            if not existing.endswith("\n"):
                existing += "\n"
            existing += "\n".join(old) + "\n"
            archive_path.write_text(existing, "utf-8")
        else:
            archive_path.write_text(
                f"# Episode Archive: {filepath.stem}\n\n" + "\n".join(old) + "\n",
                "utf-8",
            )

        new_log = "\n## Episode Log\n"
        new_log += archive_summary + "\n"
        for ne in non_episodes:
            new_log += ne + "\n"
        for ep in recent:
            new_log += ep + "\n"

        filepath.write_text(header + new_log, "utf-8")
