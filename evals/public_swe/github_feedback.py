"""Run one condition's frozen original tests, without sending model credentials.

The public worker receives a candidate patch and a fixed visible-test request.
Local callers retain complete feedback; published run reports can use counts.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import threading
import time
import zipfile
from pathlib import Path
from typing import Any

import httpx

from .visible import MAX_PATCH_BYTES, VISIBLE_PROFILES


class GitHubVisibleFeedback:
    def __init__(
        self,
        token: str,
        output: Path,
        *,
        repository: str,
        branch: str,
        base_sha: str,
        proxy: str | None = None,
        wait_seconds: int = 2100,
    ) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Invalid repository")
        if not re.fullmatch(r"eval/[a-z0-9-]+", branch):
            raise ValueError("Use a dedicated evaluation branch")
        if not re.fullmatch(r"[0-9a-f]{40}", base_sha):
            raise ValueError("Pin the public worker commit")
        self.repository = repository
        self.branch = branch
        self.base_sha = base_sha
        self.output = output
        self.wait_seconds = wait_seconds
        self.client = httpx.Client(
            timeout=90,
            proxy=proxy,
            follow_redirects=True,
            headers={
                "Authorization": "Bearer " + token,
                "Accept": "application/vnd.github+json",
            },
        )
        self.lock = threading.Lock()
        self.started = False

    def close(self) -> None:
        self.client.close()

    def _api(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.client.request(
            method, "https://api.github.com/repos/" + self.repository + path, **kwargs
        )
        response.raise_for_status()
        return response.json() if response.content else None

    def _publish(
        self,
        task_id: str,
        condition: str,
        round_number: int,
        patch: bytes,
    ) -> tuple[str, str]:
        profile = VISIBLE_PROFILES[task_id]
        prefix = "evals/public_swe/results/2026-10-12-mini-visible-rounds/"
        prefix += f"{task_id}-{condition}-{round_number:02d}"
        request_path = prefix + "/visible-request.json"
        request = {
            "schema": 1,
            "tasks": [
                {
                    "instance_id": task_id,
                    "command": list(profile[2]),
                    "candidates": [
                        {"condition": condition, "patch": prefix + "/candidate.patch"}
                    ],
                }
            ],
        }
        with self.lock:
            if not self.started:
                self._api(
                    "POST",
                    "/git/refs",
                    json={"ref": "refs/heads/" + self.branch, "sha": self.base_sha},
                )
                self.started = True
            parent = self._api("GET", "/git/ref/heads/" + self.branch)["object"]["sha"]
            tree_sha = self._api("GET", "/git/commits/" + parent)["tree"]["sha"]
            tree = []
            for path, data in (
                (prefix + "/candidate.patch", patch),
                (request_path, json.dumps(request, indent=2).encode("utf-8")),
            ):
                blob = self._api(
                    "POST",
                    "/git/blobs",
                    json={
                        "content": base64.b64encode(data).decode("ascii"),
                        "encoding": "base64",
                    },
                )
                tree.append(
                    {"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]}
                )
            new_tree = self._api(
                "POST", "/git/trees", json={"base_tree": tree_sha, "tree": tree}
            )
            commit = self._api(
                "POST",
                "/git/commits",
                json={
                    "message": (
                        f"[skip ci] Test {task_id} {condition} round {round_number}"
                    ),
                    "parents": [parent],
                    "tree": new_tree["sha"],
                },
            )
            self._api(
                "PATCH",
                "/git/refs/heads/" + self.branch,
                json={"sha": commit["sha"], "force": False},
            )
            self._api(
                "POST",
                "/actions/workflows/public-swe-visible.yml/dispatches",
                json={"ref": self.branch, "inputs": {"request": request_path}},
            )
        return request_path, str(commit["sha"])

    def __call__(
        self,
        task_id: str,
        condition: str,
        round_number: int,
        patch: bytes,
    ) -> dict[str, Any]:
        if task_id not in VISIBLE_PROFILES or not re.fullmatch(
            r"[a-z][a-z0-9_]{0,63}", condition
        ):
            raise ValueError("Unknown profile or invalid condition")
        if not 1 <= round_number <= 2 or len(patch) > MAX_PATCH_BYTES:
            raise ValueError("Test round or patch exceeds the common limit")
        patch.decode("utf-8")
        request_path, commit = self._publish(task_id, condition, round_number, patch)
        local = self.output / task_id / condition / f"visible-{round_number:02d}.json"
        local.parent.mkdir(parents=True, exist_ok=True)
        record: dict[str, Any] = {
            "request_path": request_path,
            "public_commit": commit,
            "patch_sha256": hashlib.sha256(patch).hexdigest(),
            "status": "dispatched",
        }
        local.write_text(json.dumps(record, indent=2), encoding="utf-8")
        started = time.monotonic()
        run = None
        title = "Visible feedback · " + request_path
        while time.monotonic() - started < 180:
            runs = self._api(
                "GET",
                "/actions/workflows/public-swe-visible.yml/runs",
                params={"event": "workflow_dispatch", "per_page": 30},
            )["workflow_runs"]
            matches = [r for r in runs if r["display_title"] == title]
            if len(matches) > 1:
                raise ValueError("Ambiguous visible feedback workflow")
            if matches:
                run = matches[0]
                break
            time.sleep(10)
        if run is None or run["head_sha"] != commit:
            raise ValueError("Worker did not pin the dispatched candidate commit")
        record.update(run_id=run["id"], workflow_url=run["html_url"])
        local.write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "event": "visible_started",
                    "task": task_id,
                    "condition": condition,
                    "round": round_number,
                    "run_id": run["id"],
                }
            ),
            flush=True,
        )
        while time.monotonic() - started < self.wait_seconds:
            run = self._api("GET", f"/actions/runs/{run['id']}")
            if run["status"] == "completed":
                break
            time.sleep(15)
        if run["status"] != "completed":
            raise TimeoutError("Visible feedback workflow did not finish")
        artifacts = self._api("GET", f"/actions/runs/{run['id']}/artifacts")[
            "artifacts"
        ]
        expected = "public-swe-visible-" + str(run["id"])
        selected = [a for a in artifacts if a["name"] == expected]
        if len(selected) != 1:
            raise ValueError("Missing condition-specific visible feedback artifact")
        response = self.client.get(selected[0]["archive_download_url"])
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            paths = [p for p in archive.namelist() if Path(p).name == task_id + ".json"]
            if len(paths) != 1:
                raise ValueError("Ambiguous visible test report")
            report = json.loads(archive.read(paths[0]))
        record.update(
            status="completed",
            seconds=round(time.monotonic() - started, 3),
            workflow_conclusion=run["conclusion"],
            report=report,
        )
        local.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        if not report["baseline_valid"]:
            raise ValueError("Original unchanged-source test control failed")
        own = report["outcomes"][condition]
        if (
            own["patch_sha256"] != record["patch_sha256"]
            or not own["base_commit_verified"]
        ):
            raise ValueError("Visible feedback belongs to a different source or patch")
        print(
            json.dumps(
                {
                    "event": "visible_completed",
                    "task": task_id,
                    "condition": condition,
                    "round": round_number,
                    "status": own["status"],
                }
            ),
            flush=True,
        )
        return {
            "status": own["status"],
            "test": own.get("test"),
            "error_type": own.get("error_type"),
            "error_message": own.get("error_message"),
            "base_commit": report["base_commit"],
            "baseline_valid": True,
            "workflow_url": run["html_url"],
            "visible_command": report["command"],
            "visible_test_blobs": own.get("visible_test_blobs"),
        }
