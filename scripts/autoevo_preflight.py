#!/usr/bin/env python3
"""Deterministic preflight and blocker audit for autoevo-nightly.

The scheduled runner calls this before starting Codex. A ready result has no
side effects. A blocked result writes the canonical autoevo audit artifact and
attempts a path-limited audit commit when Git is healthy enough to do so.

This helper never repairs Git state, stages arbitrary paths, runs the decay
sweep, or pushes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from _paths import tier, vault_root
from routine_claim import validate_cycle_id

ATELIER_ROOT = Path(__file__).resolve().parents[1]
SESSION_LOCK_TTL_SECONDS = 6 * 60 * 60
GENERIC_RETRY_DELAY_SECONDS = 60 * 60
OWNED_AUDIT_STATE = "autoevo-preflight-owned-audit.json"


class PreflightError(RuntimeError):
    """The deterministic preflight could not produce a trustworthy result."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


PrivacyProbe = Callable[[], dict[str, object]]
SemanticProbe = Callable[[], dict[str, object]]


def _run(
    command: list[str],
    *,
    cwd: Path,
    timeout: float = 30,
    env: dict[str, str] | None = None,
) -> CommandResult:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PreflightError(f"cannot run {command[0]}: {exc}") from exc
    return CommandResult(result.returncode, result.stdout, result.stderr)


def _git(vault: Path, *args: str, timeout: float = 30) -> CommandResult:
    return _run(["git", *args], cwd=vault, timeout=timeout)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(vault: Path, value: object) -> Path:
    if not isinstance(value, str):
        raise PreflightError("managed audit path is not a string")
    path = Path(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise PreflightError("managed audit path is unsafe")
    resolved = (vault / path).resolve()
    try:
        resolved.relative_to(vault)
    except ValueError as exc:
        raise PreflightError("managed audit path escapes the vault") from exc
    return resolved


def _git_path(vault: Path, name: str) -> Path:
    result = _git(vault, "rev-parse", "--git-path", name)
    if result.returncode != 0:
        raise PreflightError(
            f"cannot resolve Git path {name}: {result.stderr.strip() or 'unknown error'}"
        )
    path = Path(result.stdout.strip())
    return path if path.is_absolute() else (vault / path).resolve()


def _inside_worktree(vault: Path) -> bool:
    result = _git(vault, "rev-parse", "--is-inside-work-tree")
    return result.returncode == 0 and result.stdout.strip() == "true"


def _status_summary(vault: Path) -> tuple[int, dict[str, int]]:
    result = _git(vault, "status", "--porcelain=v1", "-z")
    if result.returncode != 0:
        raise PreflightError(
            f"git status failed: {result.stderr.strip() or 'unknown error'}"
        )
    records = [raw for raw in result.stdout.split("\0") if raw]
    counts: Counter[str] = Counter()
    entries = 0
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        code = record[:2] if len(record) >= 2 else "??"
        entries += 1
        counts[code] += 1
        if "R" in code or "C" in code:
            index += 1
    return entries, dict(sorted(counts.items()))


def _branch_health(vault: Path) -> dict[str, object]:
    branch = _git(vault, "branch", "--show-current")
    upstream = _git(
        vault,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{upstream}",
    )
    health: dict[str, object] = {
        "branch": branch.stdout.strip() if branch.returncode == 0 else "",
        "upstream": None,
        "ahead": None,
        "behind": None,
    }
    if upstream.returncode != 0:
        return health
    upstream_name = upstream.stdout.strip()
    health["upstream"] = upstream_name
    divergence = _git(
        vault,
        "rev-list",
        "--left-right",
        "--count",
        f"{upstream_name}...HEAD",
    )
    if divergence.returncode != 0:
        return health
    fields = divergence.stdout.split()
    if len(fields) == 2 and all(field.isdigit() for field in fields):
        health["behind"] = int(fields[0])
        health["ahead"] = int(fields[1])
    return health


def _lfs_health(vault: Path) -> dict[str, object]:
    result = _git(vault, "lfs", "status", timeout=45)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        return {
            "available": False,
            "objects_to_push": None,
            "detail": detail[:240],
        }
    in_push_section = False
    objects_to_push = 0
    for line in result.stdout.splitlines():
        if line.startswith("Objects to be pushed"):
            in_push_section = True
            continue
        if in_push_section and line.startswith("Objects to be committed"):
            break
        if in_push_section and line.startswith("\t"):
            objects_to_push += 1
    return {
        "available": True,
        "objects_to_push": objects_to_push,
        "detail": "",
    }


def _default_privacy_probe() -> dict[str, object]:
    result = _run(
        [sys.executable, str(ATELIER_ROOT / "scripts" / "privacy_check.py"), "--json"],
        cwd=ATELIER_ROOT,
        timeout=120,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PreflightError(
            "privacy_check did not return valid JSON: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        ) from exc
    if result.returncode not in (0, 1):
        raise PreflightError(
            "privacy_check failed: "
            f"{result.stderr.strip() or result.stdout.strip() or result.returncode}"
        )
    if not isinstance(payload, dict):
        raise PreflightError("privacy_check returned a non-object JSON value")
    return payload


def _default_semantic_probe() -> dict[str, object]:
    started = time.time()
    offline_env = os.environ.copy()
    offline_env["HF_HUB_OFFLINE"] = "1"
    offline_env["TRANSFORMERS_OFFLINE"] = "1"
    try:
        result = _run(
            [
                "uv",
                "run",
                "--offline",
                "--quiet",
                str(ATELIER_ROOT / "scripts" / "semantic.py"),
                "query",
                "autoevo readiness probe",
                "--top",
                "1",
                "--format",
                "json",
                "--sources",
                "local",
            ],
            cwd=ATELIER_ROOT,
            timeout=180,
            env=offline_env,
        )
    except PreflightError as exc:
        return {
            "ready": False,
            "detail": str(exc),
            "duration_seconds": round(time.time() - started, 3),
        }
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = None
    ready = result.returncode == 0 and isinstance(payload, list)
    detail = ""
    if not ready:
        detail = (
            result.stderr.strip()
            or result.stdout.strip()
            or f"semantic probe exited {result.returncode}"
        )[:500]
    mode = (
        "real"
        if "real mode:" in result.stderr
        else ("stub" if "STUB" in result.stderr else "unknown")
    )
    return {
        "ready": ready,
        "detail": detail,
        "mode": mode,
        "result_count": len(payload) if isinstance(payload, list) else None,
        "duration_seconds": round(time.time() - started, 3),
    }


def inspect_preflight(
    *,
    vault: Path | None = None,
    lock_path: Path | None = None,
    now: float | None = None,
    privacy_probe: PrivacyProbe | None = None,
    semantic_probe: SemanticProbe | None = None,
) -> dict[str, object]:
    """Return a structured ready or blocked decision without writing files."""
    vault = (vault or vault_root()).resolve()
    lock_path = lock_path or (tier("cache") / "atelier-session-lock")
    now = time.time() if now is None else now
    blockers: list[dict[str, object]] = []
    health: dict[str, object] = {
        "vault": str(vault),
        "git_worktree": False,
        "git_index": "unknown",
        "git_index_lock": "unknown",
        "worktree_entries": None,
        "worktree_status_codes": {},
        "session_lock_age_seconds": None,
        "zettelm_entries": None,
        "privacy_hits": None,
        "semantic_ready": None,
        "semantic_mode": None,
        "semantic_probe_seconds": None,
        "branch": "",
        "upstream": None,
        "ahead": None,
        "behind": None,
        "lfs_available": None,
        "lfs_objects_to_push": None,
    }

    if lock_path.exists():
        try:
            age = max(0, int(now - lock_path.stat().st_mtime))
        except OSError as exc:
            blockers.append(
                {
                    "gate": "session_lock_unreadable",
                    "detail": f"cannot read session lock metadata: {exc}",
                }
            )
        else:
            health["session_lock_age_seconds"] = age

    if not _inside_worktree(vault):
        blockers.append(
            {
                "gate": "git_not_worktree",
                "detail": "$OV is not a Git work tree, so recovery commits are unavailable",
            }
        )
    else:
        health["git_worktree"] = True
        index_path = _git_path(vault, "index")
        index_lock_path = _git_path(vault, "index.lock")
        index_exists = index_path.is_file()
        index_lock_exists = index_lock_path.exists()
        health["git_index"] = "present" if index_exists else "missing"
        health["git_index_lock"] = "present" if index_lock_exists else "absent"
        if not index_exists:
            blockers.append(
                {
                    "gate": "git_index_missing",
                    "detail": (
                        "Git index is missing; git status would misclassify tracked "
                        "files as mass deletions and untracked files"
                    ),
                }
            )
        if index_lock_exists:
            blockers.append(
                {
                    "gate": "git_index_lock_present",
                    "detail": (
                        "Git index.lock exists; autoevo will not delete or replace it"
                    ),
                }
            )

        if index_exists and not index_lock_exists:
            entries, codes = _status_summary(vault)
            health["worktree_entries"] = entries
            health["worktree_status_codes"] = codes
            if entries:
                blockers.append(
                    {
                        "gate": "dirty_vault_worktree",
                        "detail": f"$OV has {entries} Git status entries",
                    }
                )
            health.update(_branch_health(vault))
            lfs = _lfs_health(vault)
            health["lfs_available"] = lfs["available"]
            health["lfs_objects_to_push"] = lfs["objects_to_push"]
            if lfs["detail"]:
                health["lfs_detail"] = lfs["detail"]

            zettelm = vault / "zettelm"
            if zettelm.is_dir() and _inside_worktree(zettelm):
                zettelm_entries, _ = _status_summary(zettelm)
                health["zettelm_entries"] = zettelm_entries
                if zettelm_entries:
                    blockers.append(
                        {
                            "gate": "dirty_zettelm_worktree",
                            "detail": f"zettelm has {zettelm_entries} Git status entries",
                        }
                    )

    lock_age = health["session_lock_age_seconds"]
    if isinstance(lock_age, int) and lock_age < SESSION_LOCK_TTL_SECONDS:
        blockers.append(
            {
                "gate": "session_active",
                "detail": (
                    f"session-active lock is {lock_age}s old, below the "
                    f"{SESSION_LOCK_TTL_SECONDS}s safety window"
                ),
            }
        )

    if not blockers:
        probe = privacy_probe or _default_privacy_probe
        privacy = probe()
        hits = privacy.get("hit_count", 0)
        if not isinstance(hits, int):
            raise PreflightError("privacy_check hit_count is not an integer")
        health["privacy_hits"] = hits
        if hits > 0:
            blockers.append(
                {
                    "gate": "privacy_hits",
                    "detail": f"privacy_check found {hits} public-bound hits",
                }
            )

    if not blockers:
        probe = semantic_probe or _default_semantic_probe
        semantic = probe()
        ready = semantic.get("ready")
        if not isinstance(ready, bool):
            raise PreflightError("semantic probe omitted boolean ready")
        health["semantic_ready"] = ready
        health["semantic_mode"] = semantic.get("mode")
        health["semantic_probe_seconds"] = semantic.get("duration_seconds")
        if not ready:
            blockers.append(
                {
                    "gate": "semantic_unavailable",
                    "detail": str(
                        semantic.get("detail") or "semantic readiness probe failed"
                    ),
                }
            )

    primary = blockers[0] if blockers else None
    retry_after_epoch: int | None = None
    if primary is not None:
        retry_delay = GENERIC_RETRY_DELAY_SECONDS
        if primary["gate"] == "session_active" and isinstance(lock_age, int):
            retry_delay = max(1, SESSION_LOCK_TTL_SECONDS - lock_age + 1)
        retry_after_epoch = int(now) + retry_delay
    return {
        "ready": not blockers,
        "gate": primary["gate"] if primary else None,
        "detail": primary["detail"] if primary else "",
        "blockers": blockers,
        "health": health,
        "retry_after_epoch": retry_after_epoch,
    }


def _owned_state_path() -> Path:
    return tier("cache") / OWNED_AUDIT_STATE


def _write_owned_state(audit_path: Path) -> None:
    vault = vault_root()
    relative = audit_path.resolve().relative_to(vault).as_posix()
    state = {
        "path": relative,
        "sha256": _sha256(audit_path),
        "written_at": datetime.now().astimezone().isoformat(),
    }
    destination = _owned_state_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, destination)


def _clear_owned_state() -> None:
    _owned_state_path().unlink(missing_ok=True)


def _commit_audit(vault: Path, audit_path: Path, run_date: str) -> CommandResult:
    relative = audit_path.resolve().relative_to(vault).as_posix()
    added = _git(vault, "add", "--", relative)
    if added.returncode != 0:
        return added
    message = (
        f"[autoevo:audit] agent-findings: record nightly run {run_date}\n\n"
        "Auto-applied: 0, Pending: 0, Errors: 0\n\n"
        "Co-Authored-By: Atelier Autoevo Bot <noreply@atelier.local>"
    )
    return _git(
        vault,
        "commit",
        "--only",
        "-m",
        message,
        "--",
        relative,
        timeout=120,
    )


def recover_owned_audit() -> dict[str, object]:
    """Commit an unchanged bot-owned audit left by an earlier Git blocker."""
    state_path = _owned_state_path()
    if not state_path.is_file():
        return {"status": "none"}
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        vault = vault_root()
        audit_path = _safe_relative(vault, state.get("path"))
        expected_hash = state.get("sha256")
        if not isinstance(expected_hash, str) or len(expected_hash) != 64:
            raise PreflightError("managed audit checksum is invalid")
    except (OSError, json.JSONDecodeError, PreflightError) as exc:
        return {"status": "invalid", "detail": str(exc)}
    if not audit_path.is_file():
        return {
            "status": "missing",
            "detail": "managed audit file no longer exists; refusing recovery",
        }
    if _sha256(audit_path) != expected_hash:
        return {
            "status": "modified",
            "detail": "managed audit changed after autoevo wrote it; refusing recovery",
        }
    if not _inside_worktree(vault):
        return {"status": "deferred", "detail": "$OV is not a Git work tree"}
    try:
        index_path = _git_path(vault, "index")
        index_lock_path = _git_path(vault, "index.lock")
    except PreflightError as exc:
        return {"status": "deferred", "detail": str(exc)}
    if not index_path.is_file():
        return {"status": "deferred", "detail": "Git index is still missing"}
    if index_lock_path.exists():
        return {"status": "deferred", "detail": "Git index.lock is still present"}
    status = _git(
        vault,
        "status",
        "--porcelain=v1",
        "--",
        audit_path.resolve().relative_to(vault).as_posix(),
    )
    if status.returncode != 0:
        return {
            "status": "deferred",
            "detail": status.stderr.strip() or "cannot inspect managed audit",
        }
    if not status.stdout.strip():
        _clear_owned_state()
        return {"status": "already_clean"}
    run_date = audit_path.stem.removeprefix("autoevo-applied-")
    committed = _commit_audit(vault, audit_path, run_date)
    if committed.returncode != 0:
        return {
            "status": "commit_failed",
            "detail": committed.stderr.strip() or committed.stdout.strip(),
        }
    _clear_owned_state()
    return {"status": "committed"}


def _health_lines(result: dict[str, object]) -> list[str]:
    health = result["health"]
    assert isinstance(health, dict)
    branch = health.get("branch") or "(detached or unavailable)"
    upstream = health.get("upstream") or "(none)"
    ahead = health.get("ahead")
    behind = health.get("behind")
    divergence = (
        f"ahead {ahead}, behind {behind}"
        if isinstance(ahead, int) and isinstance(behind, int)
        else "unavailable"
    )
    lfs = health.get("lfs_objects_to_push")
    lfs_text = str(lfs) if isinstance(lfs, int) else "unavailable"
    return [
        f"- Git worktree: {health.get('git_worktree')}",
        f"- Git index: {health.get('git_index')}",
        f"- Git index lock: {health.get('git_index_lock')}",
        f"- Worktree status entries: {health.get('worktree_entries')}",
        f"- Branch: {branch}; upstream: {upstream}; {divergence}",
        f"- Git LFS objects pending push: {lfs_text}",
        f"- Session lock age: {health.get('session_lock_age_seconds')}s",
        f"- Privacy hits: {health.get('privacy_hits')}",
        (
            f"- Semantic search: ready={health.get('semantic_ready')}, "
            f"mode={health.get('semantic_mode')}, "
            f"probe={health.get('semantic_probe_seconds')}s"
        ),
    ]


def _validate_run_identity(run_date: str, cycle: str) -> None:
    try:
        validated_run_date = validate_cycle_id(run_date)
        validated_cycle = validate_cycle_id(cycle)
    except ValueError as exc:
        raise PreflightError(str(exc)) from exc
    if validated_run_date != validated_cycle:
        raise PreflightError("run date must match the selected cycle")


def record_blocker(
    result: dict[str, object],
    *,
    run_date: str,
    run_ts: str,
    cycle: str,
) -> dict[str, object]:
    """Write and, when safe, commit the canonical blocker audit."""
    if result.get("ready") is not False:
        raise PreflightError("record_blocker requires a blocked result")
    _validate_run_identity(run_date, cycle)
    vault = vault_root()
    findings = tier("agent_findings")
    findings.mkdir(parents=True, exist_ok=True)
    audit_path = findings / f"autoevo-applied-{run_date}.md"
    gate = str(result.get("gate") or "unknown")
    detail = str(result.get("detail") or "no detail")
    relative = audit_path.resolve().relative_to(vault).as_posix()
    if audit_path.exists():
        path_status = _git(
            vault,
            "status",
            "--porcelain=v1",
            "--",
            relative,
        )
        if path_status.returncode != 0 or path_status.stdout.strip():
            commit_detail = (
                path_status.stderr.strip()
                if path_status.returncode != 0
                else "audit path already had uncommitted changes; left unchanged"
            )
            return {
                **result,
                "output_file": relative,
                "summary": (
                    f"preflight blocked: {gate}; model not started; "
                    "audit_commit=deferred (audit path not clean)"
                ),
                "audit_commit": "deferred",
                "audit_commit_detail": commit_detail,
            }
    if audit_path.is_file() and audit_path.stat().st_size:
        existing = audit_path.read_text(encoding="utf-8")
        latest_start = existing.rfind("## Autoevo Run:")
        latest = existing[latest_start:] if latest_start >= 0 else ""
        if f"Cycle ID: {cycle}" in latest and f"- {gate}: {detail}" in latest:
            return {
                **result,
                "output_file": relative,
                "summary": (
                    f"preflight still blocked: {gate}; model not started; "
                    "audit_commit=reused"
                ),
                "audit_commit": "reused",
                "audit_commit_detail": "",
            }
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    block = "\n".join(
        [
            f"## Autoevo Run: {timestamp}",
            "",
            f"Run ID: {run_ts}",
            "",
            f"Cycle ID: {cycle}",
            "",
            "### Repository health",
            *_health_lines(result),
            "",
            "### Auto-applied (0)",
            "- (none)",
            "",
            "### Logged to pending queue (0)",
            "- (none)",
            "",
            "### Contradicted rhetorical dismissals (0)",
            "- (none)",
            "",
            "### Lint",
            "- Not run: deterministic preflight blocked before model launch.",
            "",
            "### Skipped (reason)",
            f"- {gate}: {detail}",
            "",
            "### Errors",
            "- (none)",
            "",
        ]
    )
    prefix = ""
    if audit_path.exists() and audit_path.stat().st_size:
        existing = audit_path.read_text(encoding="utf-8")
        prefix = existing.rstrip() + "\n\n"
    audit_path.write_text(prefix + block, encoding="utf-8")
    _write_owned_state(audit_path)

    health = result["health"]
    assert isinstance(health, dict)
    commit_status = "deferred"
    commit_detail = ""
    can_commit = (
        health.get("git_worktree") is True
        and health.get("git_index") == "present"
        and health.get("git_index_lock") == "absent"
        and gate != "privacy_hits"
    )
    if can_commit:
        committed = _commit_audit(vault, audit_path, run_date)
        if committed.returncode == 0:
            commit_status = "committed"
            _clear_owned_state()
        else:
            commit_status = "failed"
            commit_detail = committed.stderr.strip() or committed.stdout.strip()
            with audit_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    "\n### Audit commit error\n"
                    f"- Path-limited commit failed: {commit_detail[:500]}\n"
                )
            _write_owned_state(audit_path)

    summary = (
        f"preflight blocked: {gate}; model not started; audit_commit={commit_status}"
    )
    return {
        **result,
        "output_file": relative,
        "summary": summary,
        "audit_commit": commit_status,
        "audit_commit_detail": commit_detail,
    }


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _result_payload(recorded: dict[str, object]) -> dict[str, object]:
    return {
        "routine": "autoevo-nightly",
        "outcome": "noop",
        "output_file": recorded["output_file"],
        "summary": recorded["summary"],
        "skipped_inputs": [
            "forgetter sweeps",
            "routing and auto-apply",
            "pending queue update",
            "lint",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-blocker", action="store_true")
    parser.add_argument("--result-file", type=Path)
    parser.add_argument("--run-date", default=date.today().isoformat())
    parser.add_argument("--cycle", default=date.today().isoformat())
    parser.add_argument(
        "--run-ts",
        default=datetime.now().astimezone().strftime("%Y%m%d-%H%M%S"),
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        _validate_run_identity(args.run_date, args.cycle)
        recovery = recover_owned_audit()
        if recovery["status"] in {"invalid", "missing", "modified", "commit_failed"}:
            raise PreflightError(
                "managed audit recovery requires review: "
                f"{recovery.get('detail', recovery['status'])}"
            )
        result = inspect_preflight()
        result["owned_audit_recovery"] = recovery
        if args.record_blocker and result["ready"] is False:
            result = record_blocker(
                result,
                run_date=args.run_date,
                run_ts=args.run_ts,
                cycle=args.cycle,
            )
            if args.result_file:
                _atomic_json(args.result_file, _result_payload(result))
        elif args.result_file and result["ready"] is False:
            raise PreflightError("--result-file requires --record-blocker")
    except (OSError, PreflightError) as exc:
        print(json.dumps({"ready": False, "error": str(exc)}, sort_keys=True))
        return 2

    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print("ready" if result["ready"] else f"blocked: {result['gate']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
