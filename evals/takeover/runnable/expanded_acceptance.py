"""Hidden behavior checks for the data-driven runnable takeover task pack."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from typing import cast

CHECK_IDS: dict[str, tuple[str, ...]] = {
    "rc02_retry_after": ("delta_seconds", "http_date", "clamp", "invalid_value"),
    "rc03_customer_csv": (
        "quoted_fields",
        "multiline_record",
        "bom_crlf",
        "header_validation",
    ),
    "rc04_config_precedence": (
        "precedence",
        "falsy_values",
        "none_is_missing",
        "input_immutability",
    ),
    "rc05_json_merge_patch": (
        "null_delete",
        "nested_merge",
        "scalar_array_replace",
        "input_immutability",
    ),
    "rc06_http_cache_key": (
        "url_normalization",
        "query_normalization",
        "vary_headers",
        "sensitive_headers",
    ),
    "rc07_refresh_rotation": (
        "successful_rotation",
        "replay_revokes_family",
        "unknown_is_atomic",
        "family_isolation",
    ),
    "pe02_cli_color": (
        "default_and_modes",
        "legacy_flag",
        "conflicts",
        "invalid_values",
    ),
    "pe03_timezone_migration": (
        "aware_to_utc",
        "naive_default_zone",
        "idempotent",
        "input_immutability",
    ),
    "pe04_package_template": (
        "wheel_content",
        "sdist_content",
        "resource_read",
        "import_smoke",
    ),
    "pe05_batch_checkpoint": (
        "after_success",
        "no_skip_after_failure",
        "atomic_file",
        "order",
    ),
    "pe06_cleanup_dry_run": (
        "dry_run_no_mutation",
        "plan_parity",
        "real_delete",
        "preserve_recent",
    ),
    "pe07_file_manifest": (
        "content_and_hash",
        "exclusions",
        "canonical_bytes",
        "repeatability",
    ),
    "rr02_falsy_config_review": (
        "reviews_active_candidate",
        "verdict_matches_probe",
        "blocker_set_matches_probe",
    ),
    "rr03_retry_after_review": (
        "reviews_active_candidate",
        "verdict_matches_probe",
        "blocker_set_matches_probe",
    ),
    "rr04_csv_splitter_review": (
        "reviews_active_candidate",
        "verdict_matches_probe",
        "blocker_set_matches_probe",
    ),
    "rr05_package_data_review": (
        "reviews_active_candidate",
        "verdict_matches_probe",
        "blocker_set_matches_probe",
    ),
    "rr06_checkpoint_review": (
        "reviews_active_candidate",
        "verdict_matches_probe",
        "blocker_set_matches_probe",
    ),
}

CANDIDATE_IDS = {
    "rr02_falsy_config_review": "config_patch_v2",
    "rr03_retry_after_review": "retry_after_patch_v4",
    "rr04_csv_splitter_review": "csv_patch_v1",
    "rr05_package_data_review": "package_data_patch_v3",
    "rr06_checkpoint_review": "checkpoint_patch_v5",
}


@dataclass(frozen=True)
class Check:
    id: str
    passed: bool
    detail: str | None = None


def _run(check_id: str, assertion: Callable[[], None]) -> Check:
    try:
        assertion()
    except Exception as error:
        return Check(check_id, False, f"{type(error).__name__}: {error}")
    return Check(check_id, True)


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _load_solution(workspace: Path) -> ModuleType:
    path = workspace / "task_app" / "solution.py"
    if not path.is_file():
        raise FileNotFoundError("task_app/solution.py is missing")
    name = f"_takeover_candidate_{os.getpid()}_{id(path)}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError("candidate module could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


def _retry_checks(module: ModuleType) -> dict[str, Callable[[], None]]:
    now = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)

    def delta() -> None:
        _expect(
            module.parse_retry_after("120", now=now, max_delay=3600) == 120,
            "delta-seconds changed",
        )

    def http_date() -> None:
        _expect(
            module.parse_retry_after(
                "Wed, 30 Sep 2026 12:02:30 GMT", now=now, max_delay=3600
            )
            == 150,
            "HTTP-date changed",
        )

    def clamp() -> None:
        _expect(
            module.parse_retry_after("99999", now=now, max_delay=300) == 300,
            "future delay was not clamped",
        )
        _expect(
            module.parse_retry_after(
                "Wed, 30 Sep 2026 11:00:00 GMT", now=now, max_delay=300
            )
            == 0,
            "past date was not clamped to zero",
        )

    def invalid() -> None:
        for value in ("", "-1", "1.5", "tomorrow"):
            _expect(
                module.parse_retry_after(value, now=now, max_delay=300) is None,
                f"accepted {value!r}",
            )

    return {
        "delta_seconds": delta,
        "http_date": http_date,
        "clamp": clamp,
        "invalid_value": invalid,
    }


def _rc03_checks(module: ModuleType) -> dict[str, Callable[[], None]]:
    def quoted() -> None:
        rows = module.parse_customers(
            'id,name,email\n1,"Doe, Jane",jane@example.test\n'
        )
        _expect(
            rows == [{"id": "1", "name": "Doe, Jane", "email": "jane@example.test"}],
            "quoted comma was corrupted",
        )

    def multiline() -> None:
        rows = module.parse_customers(
            'id,name,email\n2,"Ada\nLovelace",ada@example.test\n'
        )
        _expect(rows[0]["name"] == "Ada\nLovelace", "quoted newline was corrupted")

    def bom_crlf() -> None:
        rows = module.parse_customers(
            "\ufeffid,name,email\r\n3,Zoë,zoe@example.test\r\n"
        )
        _expect(rows[0]["name"] == "Zoë", "BOM or CRLF changed the record")

    def header() -> None:
        try:
            module.parse_customers("name,id\nA,1\n")
        except ValueError:
            return
        raise AssertionError("wrong header was accepted")

    return {
        "quoted_fields": quoted,
        "multiline_record": multiline,
        "bom_crlf": bom_crlf,
        "header_validation": header,
    }


def _rc04_checks(module: ModuleType) -> dict[str, Callable[[], None]]:
    layers = (
        {"timeout": 30, "debug": True, "label": "base"},
        {"timeout": 20},
        {"timeout": 10, "debug": True},
        {"timeout": 5},
    )

    def precedence() -> None:
        _expect(
            module.resolve_config(*layers)["timeout"] == 5, "highest layer did not win"
        )

    def falsy() -> None:
        result = module.resolve_config(
            {"timeout": 30, "debug": True, "label": "base"},
            {"timeout": 0, "debug": False, "label": ""},
        )
        _expect(
            result == {"timeout": 0, "debug": False, "label": ""},
            "explicit falsy values were lost",
        )

    def missing() -> None:
        _expect(
            module.resolve_config({"timeout": 30}, {"timeout": None})
            == {"timeout": 30},
            "None did not mean missing",
        )

    def immutable() -> None:
        before = deepcopy(layers)
        module.resolve_config(*layers)
        _expect(layers == before, "input layer mutated")

    return {
        "precedence": precedence,
        "falsy_values": falsy,
        "none_is_missing": missing,
        "input_immutability": immutable,
    }


def _rc05_checks(module: ModuleType) -> dict[str, Callable[[], None]]:
    def delete() -> None:
        _expect(
            module.merge_patch({"a": 1, "b": 2}, {"a": None}) == {"b": 2},
            "null did not delete",
        )

    def nested() -> None:
        _expect(
            module.merge_patch({"a": {"x": 1, "y": 2}}, {"a": {"x": 9}})
            == {"a": {"x": 9, "y": 2}},
            "object did not merge",
        )

    def replace() -> None:
        _expect(
            module.merge_patch({"a": [1, 2]}, {"a": [3]}) == {"a": [3]},
            "array was not replaced",
        )
        _expect(
            module.merge_patch({"a": 1}, "done") == "done",
            "scalar patch did not replace target",
        )

    def immutable() -> None:
        target = {"a": {"x": [1]}}
        patch = {"a": {"x": [2]}}
        before = deepcopy((target, patch))
        module.merge_patch(target, patch)
        _expect((target, patch) == before, "input mutated")

    return {
        "null_delete": delete,
        "nested_merge": nested,
        "scalar_array_replace": replace,
        "input_immutability": immutable,
    }


def _rc06_checks(module: ModuleType) -> dict[str, Callable[[], None]]:
    def key(url: str, headers: dict[str, str] | None = None) -> str:
        return module.canonical_cache_key("get", url, headers or {})

    def url() -> None:
        _expect(
            key("HTTPS://Example.COM:443/items#part")
            == key("https://example.com/items"),
            "host, port, or fragment not normalized",
        )

    def query() -> None:
        _expect(
            key("https://e.test/x?b=2&a=1&utm_source=z")
            == key("https://e.test/x?a=1&b=2"),
            "query order or tracking key changed cache key",
        )

    def vary() -> None:
        _expect(
            key("https://e.test/", {"Accept": "json"})
            != key("https://e.test/", {"Accept": "html"}),
            "Accept did not vary key",
        )
        _expect(
            key("https://e.test/", {"ACCEPT-LANGUAGE": "en"})
            != key("https://e.test/", {"Accept-Language": "fr"}),
            "language did not vary key",
        )

    def sensitive() -> None:
        _expect(
            key("https://e.test/", {"Authorization": "a"})
            == key("https://e.test/", {"Authorization": "b"}),
            "Authorization entered cache key",
        )

    return {
        "url_normalization": url,
        "query_normalization": query,
        "vary_headers": vary,
        "sensitive_headers": sensitive,
    }


def _records() -> dict[str, dict[str, object]]:
    return {
        "a1": {"family": "a", "used": False, "revoked": False},
        "b1": {"family": "b", "used": False, "revoked": False},
    }


def _rc07_checks(module: ModuleType) -> dict[str, Callable[[], None]]:
    def success() -> None:
        records = _records()
        _expect(
            module.rotate_refresh(records, "a1", "a2") == "a2", "wrong returned token"
        )
        _expect(
            records["a1"]["used"] is True and records["a2"]["family"] == "a",
            "rotation state is incomplete",
        )

    def replay() -> None:
        records = _records()
        module.rotate_refresh(records, "a1", "a2")
        try:
            module.rotate_refresh(records, "a1", "a3")
        except ValueError:
            pass
        else:
            raise AssertionError("replay was accepted")
        _expect(
            all(item["revoked"] for item in records.values() if item["family"] == "a"),
            "family was not revoked",
        )

    def unknown() -> None:
        records = _records()
        before = deepcopy(records)
        try:
            module.rotate_refresh(records, "missing", "new")
        except ValueError:
            pass
        else:
            raise AssertionError("unknown token was accepted")
        _expect(records == before, "unknown token mutated store")

    def isolation() -> None:
        records = _records()
        module.rotate_refresh(records, "a1", "a2")
        try:
            module.rotate_refresh(records, "a1", "a3")
        except ValueError:
            pass
        _expect(records["b1"]["revoked"] is False, "other family was revoked")

    return {
        "successful_rotation": success,
        "replay_revokes_family": replay,
        "unknown_is_atomic": unknown,
        "family_isolation": isolation,
    }


def _pe02_checks(module: ModuleType) -> dict[str, Callable[[], None]]:
    def modes() -> None:
        _expect(module.parse_color_mode([]) == "auto", "default changed")
        for mode in ("auto", "always", "never"):
            _expect(
                module.parse_color_mode(["--color", mode]) == mode,
                f"mode {mode} failed",
            )

    def legacy() -> None:
        _expect(
            module.parse_color_mode(["--no-color"]) == "never", "legacy flag changed"
        )

    def conflicts() -> None:
        for argv in (
            ["--no-color", "--color", "always"],
            ["--color", "auto", "--color", "never"],
        ):
            try:
                module.parse_color_mode(argv)
            except ValueError:
                continue
            raise AssertionError(f"conflict accepted: {argv}")

    def invalid() -> None:
        for argv in (["--color"], ["--color", "sometimes"]):
            try:
                module.parse_color_mode(argv)
            except ValueError:
                continue
            raise AssertionError(f"invalid input accepted: {argv}")

    return {
        "default_and_modes": modes,
        "legacy_flag": legacy,
        "conflicts": conflicts,
        "invalid_values": invalid,
    }


def _pe03_checks(module: ModuleType) -> dict[str, Callable[[], None]]:
    def aware() -> None:
        rows = module.migrate_rows(
            [{"id": 1, "occurred_at": "2026-09-30T14:00:00+02:00"}], "UTC"
        )
        _expect(
            rows[0]["occurred_at_utc"] == "2026-09-30T12:00:00Z",
            "aware instant changed",
        )

    def naive() -> None:
        rows = module.migrate_rows([{"occurred_at": "2026-07-01T08:00:00"}], "-04:00")
        _expect(
            rows[0]["occurred_at_utc"] == "2026-07-01T12:00:00Z",
            "default timezone ignored",
        )

    def idempotent() -> None:
        once = module.migrate_rows([{"occurred_at": "2026-07-01T08:00:00"}], "-04:00")
        twice = module.migrate_rows(once, "-04:00")
        _expect(twice == once, "second migration changed output")

    def immutable() -> None:
        original = [{"occurred_at": "2026-01-01T00:00:00", "meta": {"x": 1}}]
        before = deepcopy(original)
        module.migrate_rows(original, "UTC")
        _expect(original == before, "input rows mutated")

    return {
        "aware_to_utc": aware,
        "naive_default_zone": naive,
        "idempotent": idempotent,
        "input_immutability": immutable,
    }


def _package_probes(workspace: Path) -> dict[str, Callable[[], None]]:
    template = "task_app/templates/default.txt"

    def archives() -> tuple[set[str], set[str]]:
        try:
            from setuptools import build_meta  # type: ignore[import-untyped]
        except ImportError as error:
            raise AssertionError("setuptools build backend unavailable") from error
        old = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            os.chdir(workspace)
            try:
                wheel_name = build_meta.build_wheel(str(output))
                sdist_name = build_meta.build_sdist(str(output))
            finally:
                os.chdir(old)
            with zipfile.ZipFile(output / wheel_name) as wheel:
                wheel_names = set(wheel.namelist())
            with tarfile.open(output / sdist_name) as sdist:
                sdist_names = {
                    name.split("/", 1)[-1] for name in sdist.getnames() if "/" in name
                }
        return wheel_names, sdist_names

    cached: list[tuple[set[str], set[str]]] = []

    def built() -> tuple[set[str], set[str]]:
        if not cached:
            cached.append(archives())
        return cached[0]

    def wheel() -> None:
        _expect(template in built()[0], "wheel omitted template")

    def sdist() -> None:
        _expect(template in built()[1], "sdist omitted template")

    def resource() -> None:
        import importlib

        old = Path.cwd()
        sys.path.insert(0, str(workspace))
        sys.modules.pop("task_app", None)
        try:
            os.chdir(workspace.parent)
            module = importlib.import_module("task_app")
            _expect(
                module.resource_text() == "Hello, {{ name }} — café\n",
                "runtime resource bytes changed",
            )
        finally:
            os.chdir(old)
            sys.modules.pop("task_app", None)
            sys.path.remove(str(workspace))

    def import_smoke() -> None:
        source = (workspace / "task_app" / "__init__.py").read_text(encoding="utf-8")
        compile(source, "task_app/__init__.py", "exec")

    return {
        "wheel_content": wheel,
        "sdist_content": sdist,
        "resource_read": resource,
        "import_smoke": import_smoke,
    }


def _checkpoint_checks(module: ModuleType, root: Path) -> dict[str, Callable[[], None]]:
    def exercise() -> tuple[list[str], list[str], Path]:
        checkpoint = root / "checkpoint.json"
        calls: list[str] = []
        failed = False

        def process(item: str) -> None:
            nonlocal failed
            calls.append(item)
            if item == "c" and not failed:
                failed = True
                raise RuntimeError("injected")

        try:
            module.run_batch(["a", "b", "c", "d"], process, checkpoint)
        except RuntimeError:
            pass
        first = json.loads(checkpoint.read_text(encoding="utf-8"))
        module.run_batch(["a", "b", "c", "d"], process, checkpoint)
        return calls, first, checkpoint

    cached: list[tuple[list[str], list[str], Path]] = []

    def result() -> tuple[list[str], list[str], Path]:
        if not cached:
            cached.append(exercise())
        return cached[0]

    def after_success() -> None:
        _expect(result()[1] == ["a", "b"], "failed item entered checkpoint")

    def retry_failure() -> None:
        _expect(
            result()[0] == ["a", "b", "c", "c", "d"],
            "resume skipped or repeated the wrong item",
        )

    def atomic() -> None:
        checkpoint = result()[2]
        _expect(
            not checkpoint.with_suffix(checkpoint.suffix + ".tmp").exists(),
            "temporary checkpoint remained",
        )
        _expect(
            json.loads(checkpoint.read_text()) == ["a", "b", "c", "d"],
            "final checkpoint invalid",
        )

    def order() -> None:
        _expect(result()[0][-2:] == ["c", "d"], "resumed order changed")

    return {
        "after_success": after_success,
        "no_skip_after_failure": retry_failure,
        "atomic_file": atomic,
        "order": order,
    }


def _pe06_checks(module: ModuleType, root: Path) -> dict[str, Callable[[], None]]:
    old = root / "b-old.txt"
    old2 = root / "a-old.txt"
    recent = root / "recent.txt"
    for path in (old, old2, recent):
        path.write_text(path.name)
    cutoff = datetime(2026, 9, 30, tzinfo=timezone.utc)
    old_time = (cutoff - timedelta(days=2)).timestamp()
    new_time = (cutoff + timedelta(days=1)).timestamp()
    os.utime(old, (old_time, old_time))
    os.utime(old2, (old_time, old_time))
    os.utime(recent, (new_time, new_time))
    dry_plan: list[Path] = []

    def dry() -> None:
        dry_plan[:] = module.cleanup(
            [old, recent, old2, root / "missing"], older_than=cutoff, dry_run=True
        )
        _expect(
            old.exists() and old2.exists() and recent.exists(), "dry-run deleted a file"
        )

    def parity() -> None:
        if not dry_plan:
            dry()
        _expect(dry_plan == [old2, old], "dry plan is not sorted and exact")

    def real() -> None:
        plan = module.cleanup([old, recent, old2], older_than=cutoff, dry_run=False)
        _expect(
            plan == [old2, old] and not old.exists() and not old2.exists(),
            "real cleanup did not apply the plan",
        )

    def preserve() -> None:
        _expect(recent.exists(), "recent file was deleted")

    return {
        "dry_run_no_mutation": dry,
        "plan_parity": parity,
        "real_delete": real,
        "preserve_recent": preserve,
    }


def _pe07_checks(module: ModuleType, root: Path) -> dict[str, Callable[[], None]]:
    tree = root / "tree"
    (tree / "nested").mkdir(parents=True)
    (tree / ".git").mkdir()
    (tree / "α.txt").write_text("alpha", encoding="utf-8")
    (tree / "nested" / "empty.bin").write_bytes(b"")
    (tree / ".git" / "config").write_text("secret")
    (tree / "discard.tmp").write_text("temp")
    output = tree / "manifest.json"
    first_bytes: list[bytes] = []

    def content() -> None:
        rows = module.build_manifest(tree, output)
        expected = {
            "nested/empty.bin": (0, hashlib.sha256(b"").hexdigest()),
            "α.txt": (5, hashlib.sha256(b"alpha").hexdigest()),
        }
        observed = {row["path"]: (row["size"], row["sha256"]) for row in rows}
        _expect(observed == expected, "manifest content or hash differs")
        first_bytes[:] = [output.read_bytes()]

    def exclusions() -> None:
        if not output.exists():
            content()
        text = output.read_text(encoding="utf-8")
        _expect(
            ".git" not in text and ".tmp" not in text and "manifest.json" not in text,
            "excluded file entered manifest",
        )

    def canonical() -> None:
        if not output.exists():
            content()
        raw = output.read_bytes()
        _expect(
            raw.endswith(b"\n") and not raw.endswith(b"\n\n"),
            "manifest must have one final newline",
        )
        _expect(
            json.loads(raw) == module.build_manifest(tree, output),
            "written and returned rows differ",
        )

    def repeat() -> None:
        if not first_bytes:
            content()
        module.build_manifest(tree, output)
        _expect(output.read_bytes() == first_bytes[0], "consecutive outputs differ")

    return {
        "content_and_hash": content,
        "exclusions": exclusions,
        "canonical_bytes": canonical,
        "repeatability": repeat,
    }


def _source_assertions(
    task_id: str, module: ModuleType | None, workspace: Path, temp: Path
) -> dict[str, Callable[[], None]]:
    if task_id == "pe04_package_template":
        return _package_probes(workspace)
    if module is None:
        raise RuntimeError("source task did not load a module")
    if task_id == "rc02_retry_after":
        return _retry_checks(module)
    if task_id == "rc03_customer_csv":
        return _rc03_checks(module)
    if task_id == "rc04_config_precedence":
        return _rc04_checks(module)
    if task_id == "rc05_json_merge_patch":
        return _rc05_checks(module)
    if task_id == "rc06_http_cache_key":
        return _rc06_checks(module)
    if task_id == "rc07_refresh_rotation":
        return _rc07_checks(module)
    if task_id == "pe02_cli_color":
        return _pe02_checks(module)
    if task_id == "pe03_timezone_migration":
        return _pe03_checks(module)
    if task_id == "pe05_batch_checkpoint":
        return _checkpoint_checks(module, temp)
    if task_id == "pe06_cleanup_dry_run":
        return _pe06_checks(module, temp)
    if task_id == "pe07_file_manifest":
        return _pe07_checks(module, temp)
    raise KeyError(task_id)


def _review_blockers(task_id: str, workspace: Path, temp: Path) -> tuple[str, ...]:
    module = (
        None if task_id == "rr05_package_data_review" else _load_solution(workspace)
    )
    failed: list[str] = []
    if task_id == "rr02_falsy_config_review":
        assert module is not None
        result = module.resolve(
            {"timeout": 30, "debug": True, "label": "base"},
            {},
            {},
            {"timeout": 0, "debug": False, "label": ""},
        )
        if result != {"timeout": 0, "debug": False, "label": ""}:
            failed.append("FALSY_OVERRIDE")
    elif task_id == "rr03_retry_after_review":
        assert module is not None
        for issue, assertion in _retry_checks(module).items():
            try:
                assertion()
            except Exception:
                failed.append(issue.upper())
    elif task_id == "rr04_csv_splitter_review":
        assert module is not None
        try:
            rows = module.parse_rows('id,name\n1,"Doe, Jane"\n')
            if rows != [{"id": "1", "name": "Doe, Jane"}]:
                failed.append("CSV_QUOTED_FIELD")
        except Exception:
            failed.append("CSV_QUOTED_FIELD")
        try:
            rows = module.parse_rows('id,name\n2,"Ada\nLovelace"\n')
            if rows != [{"id": "2", "name": "Ada\nLovelace"}]:
                failed.append("CSV_MULTILINE_RECORD")
        except Exception:
            failed.append("CSV_MULTILINE_RECORD")
    elif task_id == "rr05_package_data_review":
        for issue, assertion in _package_probes(workspace).items():
            try:
                assertion()
            except Exception:
                failed.append(issue.upper())
    elif task_id == "rr06_checkpoint_review":
        assert module is not None
        for issue, assertion in _checkpoint_checks(module, temp).items():
            try:
                assertion()
            except Exception:
                failed.append(issue.upper())
    else:
        raise KeyError(task_id)
    return tuple(failed)


def _load_review(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != {
        "candidate_id",
        "verdict",
        "blocking_issue_ids",
    }:
        raise ValueError("invalid review shape")
    if payload["verdict"] not in {"approve", "request_changes"}:
        raise ValueError("invalid verdict")
    blockers = payload["blocking_issue_ids"]
    if (
        not isinstance(blockers, list)
        or not all(isinstance(item, str) for item in blockers)
        or len(blockers) != len(set(blockers))
    ):
        raise ValueError("invalid blockers")
    return payload


def _payload(
    checks: tuple[Check, ...], blockers: tuple[str, ...] | None = None
) -> dict[str, object]:
    result: dict[str, object] = {
        "overall": bool(checks) and all(check.passed for check in checks),
        "checks": [
            {"id": check.id, "passed": check.passed, "detail": check.detail}
            for check in checks
        ],
    }
    if blockers is not None:
        result["derived_blocking_issue_ids"] = list(blockers)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", choices=tuple(CHECK_IDS), required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--review", type=Path)
    arguments = parser.parse_args(argv)
    task_id = arguments.task_id
    try:
        with (
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
            tempfile.TemporaryDirectory() as directory,
        ):
            temp = Path(directory)
            if task_id.startswith("rr"):
                if arguments.review is None:
                    raise ValueError("review file required")
                review = _load_review(arguments.review)
                blockers = _review_blockers(task_id, arguments.workspace, temp)
                expected_verdict = "request_changes" if blockers else "approve"
                checks: tuple[Check, ...] = (
                    Check(
                        "reviews_active_candidate",
                        review["candidate_id"] == CANDIDATE_IDS[task_id],
                    ),
                    Check(
                        "verdict_matches_probe", review["verdict"] == expected_verdict
                    ),
                    Check(
                        "blocker_set_matches_probe",
                        set(cast(list[str], review["blocking_issue_ids"]))
                        == set(blockers),
                    ),
                )
                payload = _payload(checks, blockers)
            else:
                module = (
                    None
                    if task_id == "pe04_package_template"
                    else _load_solution(arguments.workspace)
                )
                assertions = _source_assertions(
                    task_id, module, arguments.workspace, temp
                )
                checks = tuple(
                    _run(check_id, assertions[check_id])
                    for check_id in CHECK_IDS[task_id]
                )
                payload = _payload(checks)
    except Exception as error:
        checks = tuple(
            Check(check_id, False, f"{type(error).__name__}: {error}")
            for check_id in CHECK_IDS[task_id]
        )
        payload = _payload(checks, () if task_id.startswith("rr") else None)
    print(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
