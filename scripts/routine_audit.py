#!/usr/bin/env python3
"""Validate routine support declarations and resolve execution permissions.

Routine names and paths are private policy in ``$OV/_meta/routine_watch.toml``.
This script knows only the public capability-profile schema.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from routine_claim import validate_claim
from routine_prompt_guard import check as credential_lines
from routine_prompt_guard import structure_error

ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / "harness" / "routine_profiles.toml"
SUPPORT_SURFACES = {
    "local-only": {"local"},
    "hybrid": {"local", "cloud"},
    "cloud-only": {"cloud"},
}
EXECUTION_SURFACE = {"local": "local", "remote": "cloud", "cloud": "cloud"}
LOCAL_SANDBOXES = {"read-only", "workspace-write", "danger-full-access"}
WEB_MODES = {"disabled", "live"}
USER_CONFIG_MODES = {"ignore", "required"}
SHELL_NETWORK_MODES = {"disabled", "enabled", "unrestricted"}
ATELIER_ACCESS_MODES = {"read", "read-write"}
REASONING_EFFORTS = {"low", "medium", "high"}
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SAFE_COMMAND = re.compile(r"^/[A-Za-z0-9][A-Za-z0-9._-]*$")
SAFE_PERMISSION = re.compile(r"^[a-z0-9][a-z0-9._:-]*$")


class AuditError(Exception):
    """Configuration or system readiness error."""


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            value = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise AuditError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AuditError(f"expected TOML table in {path}")
    return value


def _vault_root() -> Path:
    value = os.environ.get("OV", "").strip()
    if not value:
        raise AuditError("OV is not set")
    return Path(value).expanduser()


def _load_profiles() -> dict[str, dict[str, Any]]:
    document = _load_toml(PROFILE_PATH)
    if document.get("version") != 1:
        raise AuditError(f"unsupported routine profile version in {PROFILE_PATH}")
    profiles = document.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise AuditError(f"no profiles declared in {PROFILE_PATH}")
    return profiles


def _load_watch() -> tuple[Path, list[dict[str, Any]]]:
    path = _vault_root() / "_meta" / "routine_watch.toml"
    document = _load_toml(path)
    rows = document.get("routine")
    if not isinstance(rows, list):
        raise AuditError(f"expected [[routine]] rows in {path}")
    return path, rows


def _string_list(value: Any, field: str, profile_name: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise AuditError(
            f"profile {profile_name!r} field {field!r} must be a string array"
        )
    return value


def _profile_fingerprint(name: str, profile: dict[str, Any]) -> str:
    fields = {
        "name": name,
        "sandbox": profile.get("sandbox"),
        "atelier_access": profile.get("atelier_access"),
        "web_search": profile.get("web_search"),
        "shell_network": profile.get("shell_network"),
        "user_config": profile.get("user_config"),
        "timeout_seconds": profile.get("timeout_seconds"),
        "reasoning_effort": profile.get("reasoning_effort"),
        "permissions": profile.get("permissions"),
        "required_clis": profile.get("required_clis"),
        "required_plugins": profile.get("required_plugins"),
        "optional_plugins": profile.get("optional_plugins"),
        "allowed_commands": profile.get("allowed_commands"),
    }
    encoded = json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _validate_profiles(profiles: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for name, profile in profiles.items():
        if not isinstance(profile, dict):
            errors.append(f"profile {name!r} must be a table")
            continue
        surface = profile.get("surface")
        if surface not in {"local", "cloud"}:
            errors.append(f"profile {name!r} has invalid surface {surface!r}")
            continue
        if profile.get("web_search") not in WEB_MODES:
            errors.append(f"profile {name!r} has invalid web_search")
        if profile.get("reasoning_effort") not in REASONING_EFFORTS:
            errors.append(f"profile {name!r} has invalid reasoning_effort")
        for field in ("permissions",):
            try:
                values = _string_list(profile.get(field), field, name)
                if any(not SAFE_PERMISSION.fullmatch(value) for value in values):
                    errors.append(f"profile {name!r} has invalid permissions")
            except AuditError as exc:
                errors.append(str(exc))
        if surface == "local":
            if profile.get("sandbox") not in LOCAL_SANDBOXES:
                errors.append(f"profile {name!r} has invalid sandbox")
            shell_network = profile.get("shell_network")
            if shell_network not in SHELL_NETWORK_MODES:
                errors.append(f"profile {name!r} has invalid shell_network")
            elif profile.get("sandbox") == "danger-full-access":
                if shell_network != "unrestricted":
                    errors.append(
                        f"profile {name!r} danger-full-access requires shell_network='unrestricted'"
                    )
            elif shell_network == "unrestricted":
                errors.append(
                    f"profile {name!r} shell_network='unrestricted' requires danger-full-access"
                )
            if profile.get("user_config") not in USER_CONFIG_MODES:
                errors.append(f"profile {name!r} has invalid user_config")
            atelier_access = profile.get("atelier_access")
            if atelier_access not in ATELIER_ACCESS_MODES:
                errors.append(f"profile {name!r} has invalid atelier_access")
            permissions = profile.get("permissions", [])
            if atelier_access == "read" and "atelier:read-write" in permissions:
                errors.append(
                    f"profile {name!r} read-only Atelier access conflicts with permissions"
                )
            if (
                atelier_access == "read-write"
                and "atelier:read-write" not in permissions
            ):
                errors.append(
                    f"profile {name!r} read-write Atelier access is not declared"
                )
            if (
                profile.get("sandbox") == "danger-full-access"
                and atelier_access != "read-write"
            ):
                errors.append(
                    f"profile {name!r} danger-full-access requires read-write Atelier access"
                )
            timeout_seconds = profile.get("timeout_seconds")
            if (
                not isinstance(timeout_seconds, int)
                or isinstance(timeout_seconds, bool)
                or not 30 <= timeout_seconds <= 14400
            ):
                errors.append(f"profile {name!r} has invalid timeout_seconds")
            for field in (
                "required_clis",
                "required_plugins",
                "optional_plugins",
                "allowed_commands",
            ):
                try:
                    values = _string_list(profile.get(field), field, name)
                    if field == "allowed_commands" and (
                        not values
                        or any(not SAFE_COMMAND.fullmatch(value) for value in values)
                    ):
                        errors.append(f"profile {name!r} has invalid allowed_commands")
                except AuditError as exc:
                    errors.append(str(exc))
            if (
                profile.get("required_plugins")
                and profile.get("user_config") == "ignore"
            ):
                errors.append(
                    f"profile {name!r} requires plugins but ignores user config"
                )
        else:
            for field in ("required_connectors", "optional_connectors"):
                try:
                    _string_list(profile.get(field), field, name)
                except AuditError as exc:
                    errors.append(str(exc))
    return errors


def _routine_record(
    routine: dict[str, Any], profiles: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    name = routine.get("name")
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(name, str) or not SAFE_NAME.fullmatch(name):
        name = str(name or "<missing>")
        errors.append("invalid or missing routine name")

    execution = routine.get("execution", "remote")
    surface = EXECUTION_SURFACE.get(execution)
    if surface is None:
        errors.append(f"invalid execution {execution!r}")
    scheduler = routine.get("scheduler") if surface == "cloud" else None
    if surface == "cloud" and not isinstance(scheduler, str):
        warnings.append("active cloud execution has no scheduler identity")

    support = routine.get("support")
    allowed = SUPPORT_SURFACES.get(support)
    if allowed is None:
        errors.append("missing or invalid support (local-only, hybrid, cloud-only)")
        allowed = set()
    if surface and surface not in allowed:
        errors.append(
            f"execution surface {surface!r} conflicts with support {support!r}"
        )

    local_profile = routine.get("local_profile")
    cloud_profile = routine.get("cloud_profile")
    expected = {
        "local": local_profile,
        "cloud": cloud_profile,
    }
    for candidate_surface in ("local", "cloud"):
        profile_name = expected[candidate_surface]
        declared = candidate_surface in allowed
        if declared and not isinstance(profile_name, str):
            errors.append(f"support {support!r} requires {candidate_surface}_profile")
            continue
        if not declared and profile_name is not None:
            errors.append(
                f"{candidate_surface}_profile conflicts with support {support!r}"
            )
            continue
        if isinstance(profile_name, str):
            profile = profiles.get(profile_name)
            if not isinstance(profile, dict):
                errors.append(f"unknown {candidate_surface}_profile {profile_name!r}")
            elif profile.get("surface") != candidate_surface:
                errors.append(
                    f"profile {profile_name!r} has surface {profile.get('surface')!r}, "
                    f"expected {candidate_surface!r}"
                )

    selected_profile_name = expected.get(surface) if surface else None
    selected_profile = (
        profiles.get(selected_profile_name)
        if isinstance(selected_profile_name, str)
        else None
    )
    if surface == "cloud" and isinstance(selected_profile, dict):
        warnings.append(
            "cloud connector authentication is scheduler-managed and not locally verified"
        )

    support_matrix: dict[str, Any] = {}
    for candidate_surface, profile_name in expected.items():
        profile = profiles.get(profile_name) if isinstance(profile_name, str) else None
        if candidate_surface not in allowed or not isinstance(profile, dict):
            continue
        requirement = {
            "profile": profile_name,
            "permissions": list(profile.get("permissions", [])),
            "web_search": profile.get("web_search"),
            "reasoning_effort": profile.get("reasoning_effort"),
        }
        if candidate_surface == "local":
            requirement.update(
                {
                    "sandbox": profile.get("sandbox"),
                    "atelier_access": profile.get("atelier_access"),
                    "shell_network": profile.get("shell_network"),
                    "user_config": profile.get("user_config"),
                    "timeout_seconds": profile.get("timeout_seconds"),
                    "required_clis": list(profile.get("required_clis", [])),
                    "required_plugins": list(profile.get("required_plugins", [])),
                    "optional_plugins": list(profile.get("optional_plugins", [])),
                    "allowed_commands": list(profile.get("allowed_commands", [])),
                }
            )
        else:
            requirement.update(
                {
                    "required_connectors": list(profile.get("required_connectors", [])),
                    "optional_connectors": list(profile.get("optional_connectors", [])),
                }
            )
        support_matrix[candidate_surface] = requirement

    prompt_archive = _vault_root() / "_routine_prompts" / f"{name}.md"
    cloud_capable = "cloud" in allowed
    prompt_error: str | None = None
    if cloud_capable and prompt_archive.is_file():
        if support == "hybrid":
            prompt_error = structure_error(prompt_archive)
        if prompt_error is None:
            findings = credential_lines(prompt_archive)
            if findings:
                prompt_error = "literal credential detected at line(s): " + ", ".join(
                    str(line) for line in findings
                )
    chatgpt_scheduled = surface == "cloud" and scheduler == "chatgpt-scheduled"
    cloud_migration = {
        "capable": cloud_capable,
        "active": surface == "cloud",
        "current_scheduler": scheduler,
        "chatgpt_scheduled": chatgpt_scheduled,
        "prompt_archive": str(prompt_archive),
        "prompt_archived": prompt_archive.is_file(),
        "prompt_valid": prompt_archive.is_file() and prompt_error is None,
        "management_surface": "chatgpt-web-or-mobile",
        "connector_auth": "scheduler-managed-unverified"
        if cloud_capable
        else "not-applicable",
        "blockers": [],
    }
    if cloud_capable and not prompt_archive.is_file():
        cloud_migration["blockers"].append("private prompt archive missing")
    elif prompt_error is not None:
        cloud_migration["blockers"].append(
            f"private prompt archive invalid: {prompt_error}"
        )
    if cloud_capable and not chatgpt_scheduled:
        cloud_migration["blockers"].append(
            "create and first-run-test task in ChatGPT Scheduled"
        )
    if surface == "cloud" and isinstance(scheduler, str) and not chatgpt_scheduled:
        cloud_migration["blockers"].append(
            f"disable existing {scheduler} trigger after ChatGPT Scheduled first-run"
        )

    return {
        "name": name,
        "label": routine.get("label"),
        "cron": routine.get("cron"),
        "execution": execution,
        "scheduler": scheduler,
        "surface": surface,
        "support": support,
        "local_profile": local_profile,
        "cloud_profile": cloud_profile,
        "selected_profile": selected_profile_name,
        "permissions": list(selected_profile.get("permissions", []))
        if isinstance(selected_profile, dict)
        else [],
        "support_matrix": support_matrix,
        "cloud_migration": cloud_migration,
        "errors": errors,
        "warnings": warnings,
    }


def _installed_codex_plugins() -> tuple[set[str], str | None]:
    try:
        result = subprocess.run(
            ["codex", "plugin", "list"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return set(), str(exc)
    if result.returncode != 0:
        return set(), (result.stderr or result.stdout).strip()
    installed: set[str] = set()
    for line in result.stdout.splitlines():
        columns = line.split()
        if len(columns) >= 3 and columns[1:3] == ["installed,", "enabled"]:
            installed.add(columns[0])
    return installed, None


def _loaded_launchd_labels(labels: set[str]) -> tuple[set[str], str | None]:
    if sys.platform != "darwin" or shutil.which("launchctl") is None:
        return set(), "launchd unavailable on this platform"
    loaded: set[str] = set()
    domain = f"gui/{os.getuid()}"
    for label in labels:
        result = subprocess.run(
            ["launchctl", "print", f"{domain}/{label}"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode == 0:
            loaded.add(label)
    return loaded, None


def _plist_labels_by_routine(routine_names: set[str]) -> dict[str, str]:
    candidates = list((ROOT / "scripts" / "launchd").glob("*.plist"))
    private_dir = _vault_root() / "_meta" / "launchd"
    if private_dir.is_dir():
        candidates.extend(private_dir.glob("*.plist"))
    labels: dict[str, str] = {}
    for path in candidates:
        try:
            with path.open("rb") as handle:
                plist = plistlib.load(handle)
        except (OSError, plistlib.InvalidFileException):
            continue
        label = plist.get("Label")
        arguments = plist.get("ProgramArguments", [])
        if not isinstance(label, str) or not isinstance(arguments, list):
            continue
        invocations: list[list[str]] = [[str(item) for item in arguments]]
        for item in arguments:
            if not isinstance(item, str):
                continue
            try:
                invocations.append(shlex.split(item))
            except ValueError:
                continue
        for invocation in invocations:
            for index, token in enumerate(invocation[:-1]):
                if Path(token).name != "routine_runner.sh":
                    continue
                routine_name = invocation[index + 1]
                if routine_name in routine_names:
                    labels[routine_name] = label
    return labels


def _background_evidence(
    records: list[dict[str, Any]], profiles: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    runs_root = _vault_root() / "_meta" / "routine_runs"
    smokes_root = _vault_root() / "_meta" / "routine_profile_smokes"
    permission_smokes_root = _vault_root() / "_meta" / "routine_permission_smokes"
    machine = os.uname().nodename
    latest_completed: dict[str, Any] | None = None
    latest_profile_smoke: dict[str, Any] | None = None
    real_run_profiles: set[str] = set()
    profile_smoke_profiles: set[str] = set()
    for record in records:
        routine_dir = runs_root / record["name"]
        if not routine_dir.is_dir():
            continue
        for path in routine_dir.glob("*.toml"):
            try:
                claim = _load_toml(path)
                validate_claim(
                    claim,
                    routine=record["name"],
                    cycle=path.stem,
                    allow_legacy_owner_generation=True,
                )
            except (AuditError, ValueError):
                continue
            if (
                claim.get("machine") != machine
                or claim.get("status") != "completed"
                or claim.get("contract_version") != 2
                or claim.get("runtime") != "codex"
                or not isinstance(claim.get("profile"), str)
            ):
                continue
            profile = claim.get("profile")
            current_profile = (
                profiles.get(profile) if isinstance(profile, str) else None
            )
            if not isinstance(current_profile, dict) or claim.get(
                "profile_fingerprint"
            ) != _profile_fingerprint(profile, current_profile):
                continue
            if isinstance(profile, str):
                real_run_profiles.add(profile)
            completed_at = claim.get("completed_at")
            candidate = {
                "routine": record["name"],
                "profile": profile,
                "runtime": claim.get("runtime"),
                "completed_at": completed_at,
                "claim": str(path),
            }
            if latest_completed is None or str(completed_at or "") > str(
                latest_completed.get("completed_at") or ""
            ):
                latest_completed = candidate

    if smokes_root.is_dir():
        for path in smokes_root.glob("*/*.toml"):
            try:
                claim = _load_toml(path)
            except AuditError:
                continue
            if (
                claim.get("machine") != machine
                or claim.get("status") != "completed"
                or claim.get("kind") != "runtime-envelope"
                or claim.get("contract_version") != 2
                or claim.get("runtime") != "codex"
                or claim.get("connector_access") != "not-exercised"
                or claim.get("approval_policy") != "never"
                or not isinstance(claim.get("profile"), str)
            ):
                continue
            launcher = claim.get("launcher")
            if not isinstance(launcher, str) or not launcher.startswith(
                "com.atelier.profile-smoke."
            ):
                continue
            profile = claim["profile"]
            current_profile = profiles.get(profile)
            if not isinstance(current_profile, dict) or claim.get(
                "profile_fingerprint"
            ) != _profile_fingerprint(profile, current_profile):
                continue
            profile_smoke_profiles.add(profile)
            completed_at = claim.get("completed_at")
            candidate = {
                "routine": claim.get("routine"),
                "profile": profile,
                "runtime": "codex",
                "completed_at": completed_at,
                "claim": str(path),
                "connector_access": "not-exercised",
                "approval_policy": "never",
                "launcher": launcher,
            }
            if latest_profile_smoke is None or str(completed_at or "") > str(
                latest_profile_smoke.get("completed_at") or ""
            ):
                latest_profile_smoke = candidate
    required_profiles = {
        record["selected_profile"]
        for record in records
        if isinstance(record.get("selected_profile"), str)
    }
    external_permissions_required: dict[str, set[str]] = {}
    for record in records:
        profile = record.get("selected_profile")
        if not isinstance(profile, str):
            continue
        permissions = [
            value
            for value in record.get("permissions", [])
            if isinstance(value, str)
            and value.split(":", 1)[0] in {"gmail", "readwise"}
        ]
        if permissions:
            external_permissions_required.setdefault(profile, set()).update(permissions)

    external_permissions_exercised: dict[str, set[str]] = {}
    latest_permission_smoke: dict[str, Any] | None = None
    record_profiles = {
        record["name"]: record.get("selected_profile")
        for record in records
        if isinstance(record.get("name"), str)
    }
    now = datetime.now(timezone.utc)
    if permission_smokes_root.is_dir():
        for path in permission_smokes_root.glob("*/*.toml"):
            try:
                claim = _load_toml(path)
            except AuditError:
                continue
            profile = claim.get("profile")
            permission = claim.get("permission")
            routine = claim.get("routine")
            current_profile = (
                profiles.get(profile) if isinstance(profile, str) else None
            )
            if (
                claim.get("machine") != machine
                or claim.get("status") != "completed"
                or claim.get("kind") != "external-permission"
                or claim.get("contract_version") != 1
                or claim.get("runtime") != "codex"
                or claim.get("approval_policy") != "never"
                or claim.get("user_authorized") is not True
                or claim.get("verification") != "model-reported"
                or not isinstance(profile, str)
                or not isinstance(permission, str)
                or not isinstance(routine, str)
                or record_profiles.get(routine) != profile
                or permission not in external_permissions_required.get(profile, set())
                or not isinstance(current_profile, dict)
                or claim.get("sandbox") != current_profile.get("sandbox")
                or claim.get("web_search") != current_profile.get("web_search")
                or claim.get("shell_network") != current_profile.get("shell_network")
                or claim.get("user_config") != current_profile.get("user_config")
                or claim.get("atelier_access") != current_profile.get("atelier_access")
                or claim.get("profile_fingerprint")
                != _profile_fingerprint(profile, current_profile)
            ):
                continue
            launcher = claim.get("launcher")
            if not isinstance(launcher, str) or not launcher.startswith(
                "com.atelier.permission-smoke."
            ):
                continue
            completed_at = claim.get("completed_at")
            if not isinstance(completed_at, str):
                continue
            try:
                completed = datetime.fromisoformat(completed_at).astimezone(
                    timezone.utc
                )
            except ValueError:
                continue
            if completed > now + timedelta(hours=1) or now - completed > timedelta(
                days=30
            ):
                continue
            expected_mutation = {
                "gmail:read": "read-only",
                "readwise:create-document": "idempotent-test-write",
            }.get(permission)
            if claim.get("mutation_mode") != expected_mutation:
                continue
            external_permissions_exercised.setdefault(profile, set()).add(permission)
            candidate = {
                "routine": routine,
                "profile": profile,
                "permission": permission,
                "runtime": "codex",
                "completed_at": completed_at,
                "claim": str(path),
                "launcher": launcher,
                "mutation_mode": expected_mutation,
                "verification": "model-reported",
            }
            if latest_permission_smoke is None or completed_at > str(
                latest_permission_smoke.get("completed_at") or ""
            ):
                latest_permission_smoke = candidate

    external_permissions_unverified = {
        profile: sorted(required - external_permissions_exercised.get(profile, set()))
        for profile, required in external_permissions_required.items()
        if required - external_permissions_exercised.get(profile, set())
    }
    runtime_verified_profiles = real_run_profiles | profile_smoke_profiles
    return {
        "verified": latest_completed is not None,
        "all_profiles_verified": required_profiles <= runtime_verified_profiles,
        "all_runtime_profiles_verified": required_profiles <= runtime_verified_profiles,
        "machine": machine,
        "required_profiles": sorted(required_profiles),
        "verified_profiles": sorted(runtime_verified_profiles),
        "real_run_profiles": sorted(real_run_profiles),
        "profile_smoke_profiles": sorted(profile_smoke_profiles),
        "unverified_profiles": sorted(required_profiles - runtime_verified_profiles),
        "external_permissions_required": {
            profile: sorted(permissions)
            for profile, permissions in sorted(external_permissions_required.items())
        },
        "external_permissions_exercised": {
            profile: sorted(permissions)
            for profile, permissions in sorted(external_permissions_exercised.items())
        },
        "external_permissions_unverified": external_permissions_unverified,
        "latest_completed": latest_completed,
        "latest_profile_smoke": latest_profile_smoke,
        "latest_permission_smoke": latest_permission_smoke,
    }


def _system_checks(
    records: list[dict[str, Any]],
    profiles: dict[str, dict[str, Any]],
    runtime_override: str | None = None,
) -> dict[str, Any]:
    local_records = [record for record in records if record["surface"] == "local"]
    required_clis: set[str] = set()
    required_plugins: set[str] = set()
    optional_plugins: set[str] = set()
    for record in local_records:
        profile = profiles.get(record.get("selected_profile"), {})
        required_clis.update(profile.get("required_clis", []))
        required_plugins.update(profile.get("required_plugins", []))
        optional_plugins.update(profile.get("optional_plugins", []))

    runtime_error = None
    if runtime_override is not None:
        runtime = runtime_override
    else:
        runtime = "codex"
    if runtime:
        required_clis.add(runtime)
    if local_records and sys.platform == "darwin":
        required_clis.add("caffeinate")
    cli_status = {name: shutil.which(name) for name in sorted(required_clis)}
    plugins, plugin_error = (
        _installed_codex_plugins()
        if required_plugins or optional_plugins
        else (set(), None)
    )
    local_names = {record["name"] for record in local_records}
    plist_labels = _plist_labels_by_routine(local_names)
    loaded_labels, launchd_error = _loaded_launchd_labels(set(plist_labels.values()))
    launchd = {
        name: {
            "label": plist_labels.get(name),
            "loaded": bool(plist_labels.get(name) in loaded_labels),
        }
        for name in sorted(local_names)
    }
    background = _background_evidence(local_records, profiles)

    owner_result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "routine_owner.py"),
            "status",
            "--json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    owner = None
    owner_error = None
    if owner_result.returncode == 0:
        try:
            owner = json.loads(owner_result.stdout)
        except json.JSONDecodeError as exc:
            owner_error = str(exc)
    else:
        owner_error = (owner_result.stderr or owner_result.stdout).strip()

    errors: list[str] = []
    warnings: list[str] = []
    missing_clis = [name for name, path in cli_status.items() if path is None]
    missing_plugins = sorted(required_plugins - plugins)
    missing_plists = [name for name, value in launchd.items() if not value["label"]]
    unloaded = [
        name
        for name, value in launchd.items()
        if value["label"] and not value["loaded"]
    ]
    if missing_clis:
        errors.append(f"missing required CLIs: {', '.join(missing_clis)}")
    if plugin_error:
        errors.append(f"cannot inspect Codex plugins: {plugin_error}")
    elif missing_plugins:
        errors.append(f"missing required Codex plugins: {', '.join(missing_plugins)}")
    if runtime != "codex":
        errors.append(
            f"unattended local routines require codex; selected runtime is {runtime or 'unresolved'}"
        )
    if runtime_error:
        errors.append(f"runtime resolution failed: {runtime_error}")
    if owner_error:
        errors.append(f"owner status failed: {owner_error}")
    elif not owner or not owner.get("eligible"):
        errors.append("this machine is not the active local routine owner")
    if missing_plists:
        errors.append(
            f"local routines without launchd plists: {', '.join(missing_plists)}"
        )
    if unloaded:
        errors.append(f"local routine launchd jobs not loaded: {', '.join(unloaded)}")
    unavailable_optional = sorted(optional_plugins - plugins)
    if unavailable_optional:
        warnings.append(
            f"optional Codex plugins unavailable: {', '.join(unavailable_optional)}"
        )
    if launchd_error:
        errors.append(f"cannot inspect launchd: {launchd_error}")
    if not background["verified"]:
        warnings.append(
            "no completed launchd claim from this machine; background macOS file permissions remain unverified"
        )
    elif background["unverified_profiles"]:
        warnings.append(
            "background runtime smoke missing capability profiles: "
            + ", ".join(background["unverified_profiles"])
        )
    if background["external_permissions_unverified"]:
        warnings.append(
            "external content permissions not exercised or stale: "
            + ", ".join(
                f"{profile} ({', '.join(permissions)})"
                for profile, permissions in sorted(
                    background["external_permissions_unverified"].items()
                )
            )
        )

    return {
        "ready": not errors,
        "runtime": runtime,
        "owner": owner,
        "clis": cli_status,
        "plugins": {
            "installed_enabled": sorted(plugins),
            "required": sorted(required_plugins),
            "optional": sorted(optional_plugins),
        },
        "launchd": launchd,
        "background": background,
        "errors": errors,
        "warnings": warnings,
    }


def _audit(check_system: bool) -> tuple[dict[str, Any], int]:
    profiles = _load_profiles()
    profile_errors = _validate_profiles(profiles)
    watch_path, routines = _load_watch()
    records = [_routine_record(row, profiles) for row in routines]
    errors = list(profile_errors)
    for record in records:
        errors.extend(f"{record['name']}: {message}" for message in record["errors"])
    system = (
        _system_checks(records, profiles)
        if check_system and not profile_errors
        else None
    )
    if system:
        errors.extend(system["errors"])
    counts = {
        "routines": len(records),
        "local_only": sum(record["support"] == "local-only" for record in records),
        "hybrid": sum(record["support"] == "hybrid" for record in records),
        "cloud_only": sum(record["support"] == "cloud-only" for record in records),
        "execution_local": sum(record["surface"] == "local" for record in records),
        "execution_cloud": sum(record["surface"] == "cloud" for record in records),
        "cloud_capable": sum(
            record["cloud_migration"]["capable"] for record in records
        ),
        "cloud_prompt_archived": sum(
            record["cloud_migration"]["capable"]
            and record["cloud_migration"]["prompt_archived"]
            for record in records
        ),
    }
    payload = {
        "ok": not errors,
        "watch_path": str(watch_path),
        "profiles_path": str(PROFILE_PATH),
        "counts": counts,
        "errors": errors,
        "routines": records,
    }
    if system is not None:
        payload["system"] = system
    return payload, 0 if not errors else 2


def _resolve(
    name: str,
    surface: str,
    check_system: bool,
    output_format: str,
    runtime: str | None,
    command: str | None,
) -> int:
    if not SAFE_NAME.fullmatch(name):
        raise AuditError(f"invalid routine name: {name}")
    profiles = _load_profiles()
    profile_errors = _validate_profiles(profiles)
    if profile_errors:
        raise AuditError("; ".join(profile_errors))
    _, routines = _load_watch()
    matches = [row for row in routines if row.get("name") == name]
    if len(matches) != 1:
        raise AuditError(
            f"expected exactly one routine named {name!r}, found {len(matches)}"
        )
    record = _routine_record(matches[0], profiles)
    if record["errors"]:
        raise AuditError("; ".join(record["errors"]))
    if surface not in SUPPORT_SURFACES[record["support"]]:
        raise AuditError(f"routine {name!r} does not support {surface} execution")
    profile_name = matches[0].get(f"{surface}_profile")
    profile = profiles[profile_name]
    command_name = command.split(" ", 1)[0] if command else None
    if surface == "local" and command_name is not None:
        if not SAFE_COMMAND.fullmatch(command_name):
            raise AuditError(f"invalid scheduled command: {command_name}")
        if command_name not in profile.get("allowed_commands", []):
            raise AuditError(
                f"command {command_name!r} is not allowed by local profile {profile_name!r}"
            )
    payload = {
        "routine": name,
        "support": record["support"],
        "surface": surface,
        "profile": profile_name,
        **profile,
    }
    if check_system:
        selected_record = dict(record)
        selected_record["surface"] = surface
        selected_record["selected_profile"] = profile_name
        system = _system_checks([selected_record], profiles, runtime_override=runtime)
        payload["system"] = system
        if system["errors"]:
            if output_format == "json":
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print("; ".join(system["errors"]), file=sys.stderr)
            return 2
    if output_format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        if surface != "local":
            raise AuditError("TSV resolution is only defined for local profiles")
        fields = (
            str(profile_name),
            str(profile["sandbox"]),
            str(profile["atelier_access"]),
            str(profile["web_search"]),
            str(profile["shell_network"]),
            str(profile["user_config"]),
            str(profile["timeout_seconds"]),
            str(profile["reasoning_effort"]),
            _profile_fingerprint(str(profile_name), profile),
            ",".join(profile["permissions"]),
        )
        if any("\t" in field or "\n" in field for field in fields):
            raise AuditError("profile metadata contains unsafe whitespace")
        print("\t".join(fields))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    audit_parser = subparsers.add_parser("audit", help="audit every routine")
    audit_parser.add_argument("--check-system", action="store_true")
    audit_parser.add_argument("--json", action="store_true")
    resolve_parser = subparsers.add_parser(
        "resolve", help="resolve one routine profile"
    )
    resolve_parser.add_argument("routine")
    resolve_parser.add_argument("--surface", choices=("local", "cloud"), required=True)
    resolve_parser.add_argument("--check-system", action="store_true")
    resolve_parser.add_argument("--runtime", choices=("codex", "claude"))
    resolve_parser.add_argument("--command")
    resolve_parser.add_argument("--format", choices=("json", "tsv"), default="json")
    args = parser.parse_args()
    try:
        if args.command == "audit":
            payload, exit_code = _audit(args.check_system)
            if args.json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(
                    f"routine audit: {'ok' if payload['ok'] else 'failed'}; "
                    f"{payload['counts']['routines']} routine(s)"
                )
                for message in payload["errors"]:
                    print(f"ERROR: {message}", file=sys.stderr)
            return exit_code
        return _resolve(
            args.routine,
            args.surface,
            args.check_system,
            args.format,
            args.runtime,
            args.command,
        )
    except AuditError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
