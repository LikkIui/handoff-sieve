"""Portable repository tools: source access only, no reference-answer access."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


def git(root: Path, *args: str) -> str:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never"}
    result = subprocess.run(
        ["git", "-c", "core.autocrlf=false", *args],
        cwd=root,
        env=env,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=True,
    )
    return result.stdout


def prepare_source(task: dict[str, str], root: Path, proxy: str | None) -> None:
    root.mkdir(parents=True, exist_ok=False)
    git(root, "init", "-q")
    options = ["-c", f"http.proxy={proxy}"] if proxy else []
    git(
        root,
        *options,
        "fetch",
        "--depth=1",
        f"https://github.com/{task['repo']}.git",
        task["base_commit"],
    )
    git(root, "checkout", "--detach", "-q", "FETCH_HEAD")
    if git(root, "rev-parse", "HEAD").strip() != task["base_commit"]:
        raise ValueError("Unexpected source revision")


def fork_source(source: Path, target: Path) -> None:
    git(source.parent, "clone", "--shared", "--quiet", str(source), str(target))
    git(target, "config", "core.autocrlf", "false")


class RepositoryTools:
    def __init__(self, root: Path, *, writable: bool) -> None:
        self.root = root.resolve()
        self.writable = writable
        self.files = git(root, "ls-files").splitlines()

    def path(self, value: str) -> Path:
        candidate = (self.root / value).resolve()
        if (
            not candidate.is_relative_to(self.root)
            or ".git" in candidate.relative_to(self.root).parts
        ):
            raise ValueError("Path is outside the source checkout")
        return candidate

    def execute(self, action: dict[str, Any]) -> str:
        operation = action["operation"]
        if operation == "list":
            prefix = action["path"].strip("/")
            paths = [p for p in self.files if p.startswith(prefix)]
            return "\n".join(paths[:250]) + (
                "\n[more paths omitted]" if len(paths) > 250 else ""
            )
        if operation == "search":
            query = action["query"]
            if not query:
                raise ValueError("Search text must be nonempty")
            hits = []
            for name in self.files:
                if action["path"] and not name.startswith(action["path"]):
                    continue
                path = self.path(name)
                if not path.is_file() or path.stat().st_size > 500_000:
                    continue
                try:
                    lines = path.read_text(encoding="utf-8").splitlines()
                except (UnicodeError, OSError):
                    continue
                for number, line in enumerate(lines, 1):
                    if query.casefold() in line.casefold():
                        hits.append(f"{name}:{number}: {line[:400]}")
                        if len(hits) >= 80:
                            return "\n".join(hits) + "\n[more matches omitted]"
            return "\n".join(hits) or "No matches"
        path = self.path(action["path"])
        if operation == "read":
            start, end = action["start"], action["end"]
            if start < 1 or end < start or end - start > 240:
                raise ValueError("Read 1–241 lines at a time with explicit bounds")
            lines = path.read_text(encoding="utf-8").splitlines()
            return f"File: {action['path']} ({len(lines)} lines)\n" + "\n".join(
                f"{i}: {lines[i - 1]}" for i in range(start, min(end, len(lines)) + 1)
            )
        if operation == "edit":
            if not self.writable:
                raise ValueError("Researcher tools are read-only")
            if not action["old"]:
                raise ValueError("Edit requires a unique nonempty exact old text")
            text = path.read_text(encoding="utf-8")
            if text.count(action["old"]) != 1:
                raise ValueError("Old text must match exactly once")
            path.write_text(
                text.replace(action["old"], action["new"], 1),
                encoding="utf-8",
                newline="",
            )
            return f"Edited {action['path']}. No tests executed by this source tool."
        raise ValueError(f"Unsupported source operation: {operation}")


def action_schema(*, writable: bool) -> dict[str, Any]:
    fields: dict[str, Any] = {
        key: {"type": "string"}
        for key in ("operation", "path", "query", "old", "new", "note")
    }
    fields["operation"]["enum"] = ["list", "search", "read", "finish"] + (
        ["edit"] if writable else []
    )
    fields.update(start={"type": "integer"}, end={"type": "integer"})
    return {
        "type": "object",
        "properties": fields,
        "required": list(fields),
        "additionalProperties": False,
    }


def parse_action(text: str, *, writable: bool) -> dict[str, Any]:
    value = json.loads(text)
    schema = action_schema(writable=writable)
    if not isinstance(value, dict) or set(value) != set(schema["required"]):
        raise ValueError("Invalid source action fields")
    for key, definition in schema["properties"].items():
        expected = int if definition["type"] == "integer" else str
        if type(value[key]) is not expected:
            raise ValueError("Invalid source action type")
    if value["operation"] not in schema["properties"]["operation"]["enum"]:
        raise ValueError("Invalid source action operation")
    return value
