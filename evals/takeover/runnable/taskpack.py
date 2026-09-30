"""Data-driven runnable takeover tasks beyond the first three pilots.

Only ``public_files`` are shown to the receiver. ``reference_files`` exist so
the host test suite can prove every hidden acceptance suite is satisfiable;
the provider runner never adds them to a prompt or receiver workspace.
"""

# The long lines inside embedded public/reference source files are intentional:
# they are the exact file bytes supplied to or returned by a receiver.
# ruff: noqa: E501

from __future__ import annotations

from dataclasses import dataclass
from textwrap import dedent
from typing import Literal

from evals.takeover.schema import Route, TakeoverTask


@dataclass(frozen=True)
class TaskFile:
    path: str
    output_field: str
    public_source: str
    reference_source: str | None = None


@dataclass(frozen=True)
class TaskPackSpec:
    task_id: str
    catalog_id: str
    route: Route
    title: str
    goal: str
    constraints: str
    decisions: str
    evidence: str
    pending_work: str
    check_ids: tuple[str, ...]
    files: tuple[TaskFile, ...]
    kind: Literal["source", "review"] = "source"
    candidate_id: str | None = None
    registered_issue_ids: tuple[str, ...] = ()


def _source(text: str) -> str:
    return dedent(text).lstrip()


_SIMPLE_STARTERS: dict[str, str] = {
    "rc02_retry_after": _source('''
        """Parse an HTTP Retry-After value."""
        from __future__ import annotations
        from datetime import datetime

        def parse_retry_after(value: str, *, now: datetime, max_delay: int) -> int | None:
            raise NotImplementedError
    '''),
    "rc03_customer_csv": _source('''
        """Import customer rows from CSV text."""
        from __future__ import annotations

        def parse_customers(text: str) -> list[dict[str, str]]:
            raise NotImplementedError
    '''),
    "rc04_config_precedence": _source('''
        """Merge configuration layers without losing explicit falsy values."""
        from __future__ import annotations
        from collections.abc import Mapping

        def resolve_config(*layers: Mapping[str, object | None]) -> dict[str, object]:
            raise NotImplementedError
    '''),
    "rc05_json_merge_patch": _source('''
        """Apply RFC 7396 JSON Merge Patch semantics."""
        from __future__ import annotations
        from typing import Any

        def merge_patch(target: Any, patch: Any) -> Any:
            raise NotImplementedError
    '''),
    "rc06_http_cache_key": _source('''
        """Build a canonical HTTP cache key."""
        from __future__ import annotations
        from collections.abc import Mapping

        def canonical_cache_key(method: str, url: str, headers: Mapping[str, str]) -> str:
            raise NotImplementedError
    '''),
    "rc07_refresh_rotation": _source('''
        """Rotate refresh tokens in a mutable token record store."""
        from __future__ import annotations
        from typing import Any

        def rotate_refresh(records: dict[str, dict[str, Any]], token: str, new_token: str) -> str:
            raise NotImplementedError
    '''),
    "pe02_cli_color": _source('''
        """Resolve the CLI color mode during a flag migration."""
        from __future__ import annotations
        from collections.abc import Sequence

        def parse_color_mode(argv: Sequence[str]) -> str:
            raise NotImplementedError
    '''),
    "pe03_timezone_migration": _source('''
        """Normalize event timestamps to UTC without mutating input rows."""
        from __future__ import annotations
        from collections.abc import Iterable, Mapping

        def migrate_rows(rows: Iterable[Mapping[str, object]], default_timezone: str) -> list[dict[str, object]]:
            raise NotImplementedError
    '''),
    "pe05_batch_checkpoint": _source('''
        """Run an ordered resumable batch with an atomic JSON checkpoint."""
        from __future__ import annotations
        from collections.abc import Callable, Iterable
        from pathlib import Path

        def run_batch(items: Iterable[str], process: Callable[[str], None], checkpoint_path: Path) -> list[str]:
            raise NotImplementedError
    '''),
    "pe06_cleanup_dry_run": _source('''
        """Delete old files while making dry-run use the identical plan."""
        from __future__ import annotations
        from datetime import datetime
        from pathlib import Path

        def cleanup(paths: list[Path], *, older_than: datetime, dry_run: bool) -> list[Path]:
            raise NotImplementedError
    '''),
    "pe07_file_manifest": _source('''
        """Write a deterministic manifest for regular files below a root."""
        from __future__ import annotations
        from pathlib import Path

        def build_manifest(root: Path, output: Path) -> list[dict[str, object]]:
            raise NotImplementedError
    '''),
}


_REFERENCES: dict[str, str] = {
    "rc02_retry_after": _source("""
        from __future__ import annotations
        from datetime import datetime, timezone
        from email.utils import parsedate_to_datetime

        def parse_retry_after(value: str, *, now: datetime, max_delay: int) -> int | None:
            if not isinstance(value, str) or max_delay < 0:
                return None
            value = value.strip()
            try:
                delay = int(value)
                if delay < 0 or str(delay) != value:
                    return None
            except ValueError:
                try:
                    target = parsedate_to_datetime(value)
                    if target.tzinfo is None:
                        return None
                    base = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
                    delay = max(0, int((target - base).total_seconds()))
                except (TypeError, ValueError, OverflowError):
                    return None
            return min(delay, max_delay)
    """),
    "rc03_customer_csv": _source("""
        from __future__ import annotations
        import csv
        import io

        def parse_customers(text: str) -> list[dict[str, str]]:
            stream = io.StringIO(text.lstrip("\ufeff"), newline="")
            reader = csv.DictReader(stream)
            if reader.fieldnames != ["id", "name", "email"]:
                raise ValueError("expected id,name,email header")
            return [dict(row) for row in reader if any(value for value in row.values())]
    """),
    "rc04_config_precedence": _source("""
        from __future__ import annotations
        from collections.abc import Mapping

        def resolve_config(*layers: Mapping[str, object | None]) -> dict[str, object]:
            result: dict[str, object] = {}
            for layer in layers:
                for key, value in layer.items():
                    if value is not None:
                        result[key] = value
            return result
    """),
    "rc05_json_merge_patch": _source("""
        from __future__ import annotations
        from copy import deepcopy
        from typing import Any

        def merge_patch(target: Any, patch: Any) -> Any:
            if not isinstance(patch, dict):
                return deepcopy(patch)
            result = deepcopy(target) if isinstance(target, dict) else {}
            for key, value in patch.items():
                if value is None:
                    result.pop(key, None)
                else:
                    result[key] = merge_patch(result.get(key), value)
            return result
    """),
    "rc06_http_cache_key": _source("""
        from __future__ import annotations
        import json
        from collections.abc import Mapping
        from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

        def canonical_cache_key(method: str, url: str, headers: Mapping[str, str]) -> str:
            parts = urlsplit(url)
            host = (parts.hostname or "").lower()
            port = parts.port
            if port and not ((parts.scheme.lower() == "http" and port == 80) or (parts.scheme.lower() == "https" and port == 443)):
                host = f"{host}:{port}"
            query = sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.lower().startswith("utm_"))
            normalized = urlunsplit((parts.scheme.lower(), host, parts.path or "/", urlencode(query), ""))
            lowered = {k.lower(): v.strip() for k, v in headers.items()}
            vary = {k: lowered[k] for k in ("accept", "accept-language") if k in lowered}
            return json.dumps([method.upper(), normalized, vary], sort_keys=True, separators=(",", ":"))
    """),
    "rc07_refresh_rotation": _source("""
        from __future__ import annotations
        from typing import Any

        def rotate_refresh(records: dict[str, dict[str, Any]], token: str, new_token: str) -> str:
            record = records.get(token)
            if record is None or record.get("revoked"):
                raise ValueError("invalid refresh token")
            family = record["family"]
            if record.get("used"):
                for item in records.values():
                    if item.get("family") == family:
                        item["revoked"] = True
                raise ValueError("refresh token replay")
            if new_token in records:
                raise ValueError("duplicate refresh token")
            record["used"] = True
            records[new_token] = {"family": family, "used": False, "revoked": False}
            return new_token
    """),
    "pe02_cli_color": _source("""
        from __future__ import annotations
        from collections.abc import Sequence

        def parse_color_mode(argv: Sequence[str]) -> str:
            legacy = "--no-color" in argv
            values = [argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg == "--color"]
            if argv and argv[-1] == "--color":
                raise ValueError("missing color mode")
            if len(values) > 1 or (legacy and values):
                raise ValueError("conflicting color flags")
            if legacy:
                return "never"
            mode = values[0] if values else "auto"
            if mode not in {"auto", "always", "never"}:
                raise ValueError("invalid color mode")
            return mode
    """),
    "pe03_timezone_migration": _source("""
        from __future__ import annotations
        from collections.abc import Iterable, Mapping
        from copy import deepcopy
        from datetime import datetime, timedelta, timezone

        def migrate_rows(rows: Iterable[Mapping[str, object]], default_timezone: str) -> list[dict[str, object]]:
            if default_timezone == "UTC":
                zone = timezone.utc
            else:
                sign = 1 if default_timezone.startswith("+") else -1
                hours, minutes = map(int, default_timezone[1:].split(":"))
                zone = timezone(sign * timedelta(hours=hours, minutes=minutes))
            result = []
            for original in rows:
                row = deepcopy(dict(original))
                value = row.get("occurred_at_utc", row.get("occurred_at"))
                if not isinstance(value, str):
                    raise ValueError("missing timestamp")
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=zone)
                row["occurred_at_utc"] = parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
                result.append(row)
            return result
    """),
    "pe05_batch_checkpoint": _source("""
        from __future__ import annotations
        import json
        import os
        from collections.abc import Callable, Iterable
        from pathlib import Path

        def run_batch(items: Iterable[str], process: Callable[[str], None], checkpoint_path: Path) -> list[str]:
            completed = json.loads(checkpoint_path.read_text()) if checkpoint_path.exists() else []
            for item in items:
                if item in completed:
                    continue
                process(item)
                completed.append(item)
                temporary = checkpoint_path.with_suffix(checkpoint_path.suffix + ".tmp")
                temporary.write_text(json.dumps(completed, separators=(",", ":")) + "\\n")
                os.replace(temporary, checkpoint_path)
            return completed
    """),
    "pe06_cleanup_dry_run": _source("""
        from __future__ import annotations
        from datetime import datetime, timezone
        from pathlib import Path

        def cleanup(paths: list[Path], *, older_than: datetime, dry_run: bool) -> list[Path]:
            cutoff = older_than.timestamp()
            selected = sorted((path for path in paths if path.is_file() and path.stat().st_mtime < cutoff), key=lambda path: path.as_posix())
            if not dry_run:
                for path in selected:
                    path.unlink()
            return selected
    """),
    "pe07_file_manifest": _source("""
        from __future__ import annotations
        import hashlib
        import json
        from pathlib import Path

        def build_manifest(root: Path, output: Path) -> list[dict[str, object]]:
            root = root.resolve()
            output = output.resolve()
            rows = []
            for path in root.rglob("*"):
                if not path.is_file() or path.resolve() == output or ".git" in path.relative_to(root).parts or path.suffix == ".tmp":
                    continue
                data = path.read_bytes()
                rows.append({"path": path.relative_to(root).as_posix(), "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
            rows.sort(key=lambda item: item["path"])
            output.write_text(json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\\n", encoding="utf-8")
            return rows
    """),
}


_PE04_FILES = (
    TaskFile(
        "pyproject.toml",
        "pyproject_toml",
        _source("""
            [build-system]
            requires = ["setuptools>=68"]
            build-backend = "setuptools.build_meta"

            [project]
            name = "takeover-template-package"
            version = "0.0.1"
        """),
        _source("""
            [build-system]
            requires = ["setuptools>=68"]
            build-backend = "setuptools.build_meta"

            [project]
            name = "takeover-template-package"
            version = "0.0.1"

            [tool.setuptools.package-data]
            task_app = ["templates/*.txt"]
        """),
    ),
    TaskFile(
        "task_app/__init__.py",
        "package_init_py",
        _source("""
            def resource_text() -> str:
                raise NotImplementedError
        """),
        _source("""
            from importlib.resources import files

            def resource_text() -> str:
                return files(__package__).joinpath("templates/default.txt").read_text(encoding="utf-8")
        """),
    ),
    TaskFile(
        "task_app/templates/default.txt",
        "template_txt",
        "Hello, {{ name }} — café\n",
        "Hello, {{ name }} — café\n",
    ),
)


_RR_CANDIDATES: dict[str, tuple[tuple[TaskFile, ...], str, tuple[str, ...]]] = {
    "rr02_falsy_config_review": (
        (
            TaskFile(
                "task_app/solution.py",
                "unused",
                _source("""
            def resolve(defaults, file_values, env_values, cli_values):
                keys = set(defaults) | set(file_values) | set(env_values) | set(cli_values)
                return {key: cli_values.get(key) or env_values.get(key) or file_values.get(key) or defaults.get(key) for key in keys}
        """),
            ),
        ),
        "config_patch_v2",
        ("FALSY_OVERRIDE",),
    ),
    "rr03_retry_after_review": (
        (TaskFile("task_app/solution.py", "unused", _REFERENCES["rc02_retry_after"]),),
        "retry_after_patch_v4",
        ("DELTA_SECONDS", "HTTP_DATE", "CLAMP", "INVALID_VALUE"),
    ),
    "rr04_csv_splitter_review": (
        (
            TaskFile(
                "task_app/solution.py",
                "unused",
                _source("""
            def parse_rows(text):
                lines = text.splitlines()
                header = lines[0].split(",")
                return [dict(zip(header, line.split(","), strict=True)) for line in lines[1:] if line]
        """),
            ),
        ),
        "csv_patch_v1",
        ("CSV_QUOTED_FIELD", "CSV_MULTILINE_RECORD"),
    ),
    "rr05_package_data_review": (
        tuple(
            TaskFile(
                file.path,
                "unused",
                file.reference_source or file.public_source,
            )
            for file in _PE04_FILES
        ),
        "package_data_patch_v3",
        ("WHEEL_CONTENT", "SDIST_CONTENT", "RESOURCE_READ", "IMPORT_SMOKE"),
    ),
    "rr06_checkpoint_review": (
        (
            TaskFile(
                "task_app/solution.py", "unused", _REFERENCES["pe05_batch_checkpoint"]
            ),
        ),
        "checkpoint_patch_v5",
        ("AFTER_SUCCESS", "NO_SKIP_AFTER_FAILURE", "ATOMIC_FILE", "ORDER"),
    ),
}


def _source_spec(
    task_id: str,
    catalog_id: str,
    route: Route,
    title: str,
    goal: str,
    constraints: str,
    decisions: str,
    evidence: str,
    pending_work: str,
    check_ids: tuple[str, ...],
    files: tuple[TaskFile, ...] | None = None,
) -> TaskPackSpec:
    if files is None:
        files = (
            TaskFile(
                "task_app/solution.py",
                "solution_py",
                _SIMPLE_STARTERS[task_id],
                _REFERENCES[task_id],
            ),
        )
    return TaskPackSpec(
        task_id=task_id,
        catalog_id=catalog_id,
        route=route,
        title=title,
        goal=goal,
        constraints=constraints,
        decisions=decisions,
        evidence=evidence,
        pending_work=pending_work,
        check_ids=check_ids,
        files=files,
    )


_SOURCE_SPECS = (
    _source_spec(
        "rc02_retry_after",
        "RC-02",
        "researcher_to_coder",
        "Parse Retry-After safely",
        "Implement both HTTP Retry-After forms.",
        "Support non-negative delta-seconds and IMF-fixdate; clamp to max_delay; invalid values return None.",
        "Use the caller-provided aware now value and whole elapsed seconds.",
        "Integer-only parsing failed the HTTP-date fixture and an unclamped date scheduled a multi-day retry.",
        "Complete parse_retry_after without dependencies.",
        ("delta_seconds", "http_date", "clamp", "invalid_value"),
    ),
    _source_spec(
        "rc03_customer_csv",
        "RC-03",
        "researcher_to_coder",
        "Import real CSV records",
        "Parse customer CSV without corrupting quoted data.",
        "Require id,name,email; support UTF-8 BOM, CRLF, quoted commas and embedded newlines.",
        "Use Python's CSV state machine and reject a wrong header.",
        "The manual splitter turned one quoted customer into three columns.",
        "Complete parse_customers and preserve text exactly.",
        ("quoted_fields", "multiline_record", "bom_crlf", "header_validation"),
    ),
    _source_spec(
        "rc04_config_precedence",
        "RC-04",
        "researcher_to_coder",
        "Preserve falsy config overrides",
        "Merge configuration layers with explicit precedence.",
        "Later layers win; only None means missing; never mutate inputs.",
        "Iterate layers from lowest to highest precedence.",
        "Using `or` replaced timeout=0, debug=False, and label=''.",
        "Complete resolve_config.",
        ("precedence", "falsy_values", "none_is_missing", "input_immutability"),
    ),
    _source_spec(
        "rc05_json_merge_patch",
        "RC-05",
        "researcher_to_coder",
        "Implement JSON Merge Patch",
        "Apply RFC 7396 merge-patch semantics.",
        "Null deletes object keys; arrays and scalars replace; nested objects merge; inputs stay unchanged.",
        "Recurse only when the patch is an object.",
        "A deep-merge prototype merged arrays by index and retained null keys.",
        "Complete merge_patch.",
        ("null_delete", "nested_merge", "scalar_array_replace", "input_immutability"),
    ),
    _source_spec(
        "rc06_http_cache_key",
        "RC-06",
        "researcher_to_coder",
        "Canonicalize an HTTP cache key",
        "Produce stable cache keys for equivalent requests.",
        "Normalize method/scheme/host/default port/query order; discard utm_* and fragments; vary on Accept and Accept-Language only.",
        "Serialize the normalized tuple as canonical JSON.",
        "Raw URL keys produced misses for query reordering and leaked Authorization into key material.",
        "Complete canonical_cache_key.",
        (
            "url_normalization",
            "query_normalization",
            "vary_headers",
            "sensitive_headers",
        ),
    ),
    _source_spec(
        "rc07_refresh_rotation",
        "RC-07",
        "researcher_to_coder",
        "Rotate refresh-token families",
        "Rotate one-time refresh tokens and detect replay.",
        "Successful use marks the old token used; replay revokes its family; unknown tokens fail; other families remain active.",
        "Mutate the supplied store only after validating the request.",
        "The first prototype allowed the same parent token to mint two children.",
        "Complete rotate_refresh.",
        (
            "successful_rotation",
            "replay_revokes_family",
            "unknown_is_atomic",
            "family_isolation",
        ),
    ),
    _source_spec(
        "pe02_cli_color",
        "PE-02",
        "planner_to_executor",
        "Migrate a CLI color flag",
        "Add --color while keeping the legacy disable flag.",
        "Modes are auto/always/never; --no-color maps to never; conflicting or malformed input raises ValueError.",
        "Keep auto as the default for compatibility.",
        "A permissive parser silently accepted --no-color with --color always.",
        "Complete parse_color_mode.",
        ("default_and_modes", "legacy_flag", "conflicts", "invalid_values"),
    ),
    _source_spec(
        "pe03_timezone_migration",
        "PE-03",
        "planner_to_executor",
        "Normalize stored timestamps",
        "Migrate event rows to explicit UTC timestamps.",
        "Aware timestamps keep their instant; naive values use a UTC offset such as -04:00; output uses Z; input rows are not mutated; reruns are stable.",
        "Prefer occurred_at_utc when already present.",
        "Treating every naive timestamp as UTC shifted the New York fixture by four hours.",
        "Complete migrate_rows.",
        ("aware_to_utc", "naive_default_zone", "idempotent", "input_immutability"),
    ),
    _source_spec(
        "pe04_package_template",
        "PE-04",
        "planner_to_executor",
        "Ship a runtime template",
        "Make the template available in wheel and sdist and readable at runtime.",
        "Use package data and importlib.resources; retain the exact UTF-8 template.",
        "Declare templates/*.txt under task_app package data.",
        "The source checkout worked while the built wheel omitted the template.",
        "Complete all three files.",
        ("wheel_content", "sdist_content", "resource_read", "import_smoke"),
        _PE04_FILES,
    ),
    _source_spec(
        "pe05_batch_checkpoint",
        "PE-05",
        "planner_to_executor",
        "Resume an ordered batch",
        "Persist progress only after successful item processing.",
        "Resume skips completed items; a failed item is retried; checkpoint replacement is atomic; order is stable.",
        "Write a sibling .tmp then os.replace after success.",
        "Checkpointing before process() caused item C to be skipped after a crash.",
        "Complete run_batch.",
        ("after_success", "no_skip_after_failure", "atomic_file", "order"),
    ),
    _source_spec(
        "pe06_cleanup_dry_run",
        "PE-06",
        "planner_to_executor",
        "Add cleanup dry-run",
        "Make dry-run report the exact real cleanup plan without deletion.",
        "Select regular files older than the cutoff, sort paths, preserve recent/missing paths, and keep dry-run side-effect free.",
        "Use one selection path for dry and real modes.",
        "A separate dry-run branch disagreed with real cleanup on boundary files.",
        "Complete cleanup.",
        ("dry_run_no_mutation", "plan_parity", "real_delete", "preserve_recent"),
    ),
    _source_spec(
        "pe07_file_manifest",
        "PE-07",
        "planner_to_executor",
        "Build a deterministic file manifest",
        "Hash a tree into a canonical reproducible manifest.",
        "Include regular files only; exclude .git, *.tmp, and output; POSIX-sort paths; write canonical JSON plus newline.",
        "Return the same rows that are written.",
        "Filesystem traversal order changed the old manifest on consecutive runs.",
        "Complete build_manifest.",
        ("content_and_hash", "exclusions", "canonical_bytes", "repeatability"),
    ),
)


def _review_spec(
    task_id: str,
    catalog_id: str,
    title: str,
    goal: str,
    constraints: str,
    decisions: str,
    evidence: str,
) -> TaskPackSpec:
    files, candidate_id, issues = _RR_CANDIDATES[task_id]
    return TaskPackSpec(
        task_id=task_id,
        catalog_id=catalog_id,
        route="researcher_to_reviewer",
        title=title,
        goal=goal,
        constraints=constraints,
        decisions=decisions,
        evidence=evidence,
        pending_work="Review only the active candidate and return the exact blocker set.",
        check_ids=(
            "reviews_active_candidate",
            "verdict_matches_probe",
            "blocker_set_matches_probe",
        ),
        files=files,
        kind="review",
        candidate_id=candidate_id,
        registered_issue_ids=issues,
    )


_REVIEW_SPECS = (
    _review_spec(
        "rr02_falsy_config_review",
        "RR-02",
        "Review falsy configuration overrides",
        "Decide whether the active config patch preserves explicit overrides.",
        "FALSY_OVERRIDE blocks merge when 0, False, or empty string is replaced; only None is missing.",
        "Four layers use highest explicit value.",
        "The active candidate combines values with Python `or`.",
    ),
    _review_spec(
        "rr03_retry_after_review",
        "RR-03",
        "Review a Retry-After implementation",
        "Assess the complete active Retry-After candidate.",
        "Check DELTA_SECONDS, HTTP_DATE, CLAMP, and INVALID_VALUE independently.",
        "Both wire formats are required.",
        "Frozen-time probes cover all four registered rules.",
    ),
    _review_spec(
        "rr04_csv_splitter_review",
        "RR-04",
        "Review a manual CSV splitter",
        "Identify every CSV behavior broken by the active candidate.",
        "CSV_QUOTED_FIELD and CSV_MULTILINE_RECORD are merge blockers.",
        "CSV must be parsed as records, not physical lines.",
        "The simple sample passes, while quoted comma and quoted newline samples are available.",
    ),
    _review_spec(
        "rr05_package_data_review",
        "RR-05",
        "Review a package-data fix",
        "Assess whether the runtime template fix is complete.",
        "WHEEL_CONTENT, SDIST_CONTENT, RESOURCE_READ, and IMPORT_SMOKE must all pass.",
        "The candidate uses package-data plus importlib.resources.",
        "A clean archive inspection and runtime probe are required.",
    ),
    _review_spec(
        "rr06_checkpoint_review",
        "RR-06",
        "Review resumable checkpoint behavior",
        "Assess the final checkpoint implementation after the earlier failed design.",
        "AFTER_SUCCESS, NO_SKIP_AFTER_FAILURE, ATOMIC_FILE, and ORDER are required.",
        "Checkpoint only after processing succeeds and replace atomically.",
        "The active candidate differs from the rejected checkpoint-before-work draft.",
    ),
)


TASKPACK: dict[str, TaskPackSpec] = {
    spec.task_id: spec for spec in (*_SOURCE_SPECS, *_REVIEW_SPECS)
}


def build_takeover_task(spec: TaskPackSpec) -> TakeoverTask:
    """Materialize the schema-valid handoff fixture for one expanded task."""

    sender, receiver = {
        "researcher_to_coder": ("researcher", "coder"),
        "planner_to_executor": ("planner", "executor"),
        "researcher_to_reviewer": ("researcher", "reviewer"),
    }[spec.route]
    required_fields = (
        ("candidate_id", "verdict", "blocking_issue_ids")
        if spec.kind == "review"
        else tuple(file.output_field for file in spec.files)
    )
    checks = [
        {
            "id": f"declares_{field}",
            "path": field,
            "operator": "equals",
            "expected": "host_graded",
        }
        for field in required_fields
    ]
    noise_subject = spec.title.lower()
    messages = [
        {
            "kind": "research_notes" if sender == "researcher" else "backlog",
            "content": [
                f"A future dashboard may visualize {noise_subject}; no dashboard work is part of this takeover.",
                "The team compared hosted services, queue products, deployment regions, and UI labels without accepting any of them.",
                "A discarded prototype used a different public API and belongs only to the archive.",
                "Release naming, screenshots, analytics, billing, and notification ideas remain separate backlog items.",
                "A long performance log used synthetic data that does not exercise the declared acceptance boundary.",
                "Documentation search results included navigation, cookie banners, related links, and version selectors.",
            ],
        },
        {
            "kind": "meeting_notes",
            "content": [
                "The meeting covered ownership rotations, launch timing, dashboard colors, and unrelated mobile requests.",
                "Several speculative extensions were deferred until the small accepted behavior has shipped.",
                "An older design was discussed for historical context and is not the active decision.",
                "No new dependency, remote service, storage system, or authentication layer was approved.",
            ],
        },
        {"kind": "constraints", "content": spec.constraints},
        {"kind": "decisions", "content": spec.decisions},
        {"kind": "evidence", "content": spec.evidence},
        {
            "kind": "completed_work",
            "content": "The public starter and stable function boundary already exist.",
        },
        {
            "kind": "failed_attempts",
            "content": "The evidence records the rejected behavior; do not restore it.",
        },
        {"kind": "pending_work", "content": spec.pending_work},
        {
            "kind": "tool_results",
            "content": "Baseline imports succeed; the hidden behavioral boundary has not been run on a receiver answer.",
        },
    ]
    return TakeoverTask.model_validate(
        {
            "schema_version": "1",
            "id": spec.task_id,
            "route": spec.route,
            "title": spec.title,
            "sender_state": {
                "sender": sender,
                "receiver": receiver,
                "messages": messages,
                "artifacts": [
                    {
                        "name": "active-workspace-map",
                        "media_type": "application/json",
                        "content": {
                            "catalog_id": spec.catalog_id,
                            "files": [file.path for file in spec.files],
                            "candidate_id": spec.candidate_id,
                        },
                    }
                ],
                "metadata": {
                    "catalog_id": spec.catalog_id,
                    "fixture_status": "not_run",
                },
            },
            "contract": {
                "goal": spec.goal,
                "required": [
                    "constraints",
                    "decisions",
                    "evidence",
                    "pending_work",
                    "artifacts",
                ],
                "preferred": ["completed_work", "failed_attempts", "tool_results"],
                "max_tokens": 1050,
            },
            "receiver_instruction": "Return only the declared JSON object.",
            "receiver_output_contract": {"required_fields": list(required_fields)},
            "success_validator": {"checks": checks},
        }
    )
