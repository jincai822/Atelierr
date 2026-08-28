#!/usr/bin/env python3
"""Build a private ChatGPT Scheduled migration bundle for cloud-capable routines."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib
from pathlib import Path
from typing import Any
from routine_prompt_guard import check as credential_lines
from routine_prompt_guard import structure_error

ROOT = Path(__file__).resolve().parents[2]
PROFILES_PATH = ROOT / "harness" / "routine_profiles.toml"
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
LOCAL_ADAPTER_MARKER = re.compile(
    r"(?m)^--- ORIGINAL ROUTINE PROMPT .* ---\s*$"
)


class BundleError(Exception):
    """Invalid private policy or unsafe bundle target."""


def load_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            value = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise BundleError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BundleError(f"expected TOML table in {path}")
    return value


def vault_root() -> Path:
    value = os.environ.get("OV", "").strip()
    if not value:
        raise BundleError("OV is not set")
    return Path(value).expanduser().resolve()


def private_output_path(output: Path, ov: Path) -> Path:
    resolved = output.expanduser().resolve()
    try:
        resolved.relative_to(ov)
    except ValueError as exc:
        raise BundleError(f"output must be inside the private vault: {ov}") from exc
    if resolved == ov:
        raise BundleError("output must be a dedicated directory below the private vault")
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise BundleError("output must not be inside the public Atelier repository")
    return resolved


def adaptation_notes(original: str, permissions: list[str]) -> list[str]:
    """Describe procedure clauses superseded by the cloud permission profile."""
    notes: list[str] = []
    permission_set = set(permissions)
    if "$OV" in original:
        notes.append("legacy $OV paths map to the Google Drive zk/ root")
    if re.search(
        r"(?im)\bBash\b|```bash|\blocal\s+`?[^\n`]*`?\s+CLI\b|\bclaude\s+-p\b|\blaunchd\b",
        original,
    ):
        notes.append("local shell and CLI instructions are disabled")
    if re.search(r"(?i)\bGmail\b", original) and not any(
        value.startswith("gmail:") for value in permission_set
    ):
        notes.append("Gmail reads and mutations are disabled by the permission profile")
    if re.search(r"(?i)\bReadwise\b", original) and not any(
        value.startswith("readwise:") for value in permission_set
    ):
        notes.append("Readwise reads and mutations are disabled by the permission profile")
    return notes


def original_prompt(archived: str) -> str:
    marker = LOCAL_ADAPTER_MARKER.search(archived)
    return archived[marker.end() :].lstrip() if marker else archived.lstrip()


def validate_archive(archive: Path, support: str, name: str) -> None:
    if support == "hybrid":
        invalid_structure = structure_error(archive)
        if invalid_structure:
            raise BundleError(
                f"invalid local-adapter archive for {name!r}: {invalid_structure}"
            )
    findings = credential_lines(archive)
    if findings:
        raise BundleError(
            f"literal credential detected in archive for {name!r} at line(s): "
            + ", ".join(str(line) for line in findings)
        )


def cloud_prompt(original: str, profile: dict[str, Any]) -> str:
    required = ", ".join(profile.get("required_connectors", [])) or "none"
    optional = ", ".join(profile.get("optional_connectors", [])) or "none"
    permissions = list(profile.get("permissions", []))
    allowed = ", ".join(permissions) or "none"
    web = profile.get("web_search", "disabled")
    header = f"""CHATGPT SCHEDULED TASK ADAPTER AND PERMISSION OVERRIDES

This task runs remotely in ChatGPT Scheduled, not on a local machine.
These rules override any incompatible instruction in the routine procedure below.

- Required connected plugins: {required}.
- Optional connected plugins: {optional}.
- Effective permission allowlist: {allowed}.
- Web search: {web}.
- There is no local `$OV` folder. Treat `zk/` as the vault root in Google Drive.
- Do not invoke Bash, a shell, `date`, Python, or any local CLI. Use the task runtime's current date and connected tools.
- Adapt legacy MCP or tool names to the matching connected plugin only when its action is in the permission allowlist.
- Connector installation indicates capability, not authorization. Skip and report every procedure action not present in the permission allowlist.
- The Google Drive artifact named by the procedure is the canonical output.
- Execute one bounded pass. Do not retry unavailable sources or connectors.
- If a required connector is unavailable, report the blocker and do not create an empty success artifact.
- Do not read Gmail, send mail, create drafts, change labels, or mutate Readwise unless the permission allowlist explicitly authorizes that action.

--- ROUTINE PROCEDURE (SUBJECT TO THE OVERRIDES ABOVE) ---

"""
    return header + original.rstrip() + "\n"


def build(output: Path) -> dict[str, Any]:
    ov = vault_root()
    output = private_output_path(output, ov)
    if output.exists():
        raise BundleError(f"output already exists: {output}")
    watch_path = ov / "_meta" / "routine_watch.toml"
    watch = load_toml(watch_path)
    profiles_document = load_toml(PROFILES_PATH)
    profiles = profiles_document.get("profiles", {})
    rows = watch.get("routine", [])
    if not isinstance(rows, list) or not isinstance(profiles, dict):
        raise BundleError("invalid routine registry or profile registry")

    for row in rows:
        if not isinstance(row, dict) or row.get("support") not in {"hybrid", "cloud-only"}:
            continue
        name = row.get("name")
        if not isinstance(name, str) or not SAFE_NAME.fullmatch(name):
            raise BundleError(f"invalid cloud-capable routine name: {name!r}")
        profile_name = row.get("cloud_profile")
        profile = profiles.get(profile_name) if isinstance(profile_name, str) else None
        if not isinstance(profile, dict) or profile.get("surface") != "cloud":
            raise BundleError(f"invalid cloud profile for {name!r}")
        archive = ov / "_routine_prompts" / f"{name}.md"
        if archive.is_file():
            validate_archive(archive, str(row["support"]), name)

    output.mkdir(parents=True, mode=0o700)
    prompts_dir = output / "prompts"
    prompts_dir.mkdir(mode=0o700)
    routines: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        support = row.get("support")
        if support not in {"hybrid", "cloud-only"}:
            continue
        if not isinstance(name, str) or not SAFE_NAME.fullmatch(name):
            raise BundleError(f"invalid cloud-capable routine name: {name!r}")
        profile_name = row.get("cloud_profile")
        profile = profiles.get(profile_name) if isinstance(profile_name, str) else None
        if not isinstance(profile, dict) or profile.get("surface") != "cloud":
            raise BundleError(f"invalid cloud profile for {name!r}")
        archive = ov / "_routine_prompts" / f"{name}.md"
        prompt_path: str | None = None
        blockers: list[str] = []
        active_execution = row.get("execution", "remote")
        current_scheduler = row.get("scheduler")
        chatgpt_scheduled = (
            active_execution == "remote" and current_scheduler == "chatgpt-scheduled"
        )
        if archive.is_file():
            archived = archive.read_text(encoding="utf-8")
            original = original_prompt(archived)
            prompt = cloud_prompt(original, profile)
            destination = prompts_dir / f"{name}.md"
            destination.write_text(prompt, encoding="utf-8")
            destination.chmod(0o600)
            prompt_path = str(destination.relative_to(output))
            adaptations = adaptation_notes(original, list(profile.get("permissions", [])))
        else:
            blockers.append("private prompt archive missing")
            adaptations = []
        if not chatgpt_scheduled:
            blockers.append("create and first-run-test task in ChatGPT Scheduled")
        if (
            active_execution == "remote"
            and isinstance(current_scheduler, str)
            and not chatgpt_scheduled
        ):
            blockers.append(
                f"disable existing {current_scheduler} trigger after ChatGPT Scheduled first-run"
            )
        routines.append(
            {
                "name": name,
                "support": support,
                "active_execution": active_execution,
                "current_scheduler": current_scheduler,
                "chatgpt_scheduled": chatgpt_scheduled,
                "cron": row.get("cron"),
                "profile": profile_name,
                "permissions": list(profile.get("permissions", [])),
                "required_connectors": list(profile.get("required_connectors", [])),
                "optional_connectors": list(profile.get("optional_connectors", [])),
                "web_search": profile.get("web_search"),
                "reasoning_effort": profile.get("reasoning_effort"),
                "prompt": prompt_path,
                "adaptations": adaptations,
                "blockers": blockers,
            }
        )

    manifest = {
        "version": 3,
        "source_watch": str(watch_path),
        "scheduler": "ChatGPT Scheduled",
        "management_surface": "ChatGPT web or mobile app",
        "routines": routines,
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_path.chmod(0o600)
    readme = output / "README.md"
    readme.write_text(
        """# Cloud routine migration bundle

This private bundle prepares cloud-capable routines for ChatGPT Scheduled.
The Codex CLI cannot create or manage Scheduled tasks.

For each routine:

1. Install and connect every `required_connectors` entry in ChatGPT.
2. Review the permission allowlist and the manifest's `adaptations` entries.
3. Test the generated prompt in a regular ChatGPT web or mobile chat.
4. Create the task in Scheduled using the declared cadence.
5. Verify the first Drive artifact and connector behavior.
6. Only then disable the previous cloud trigger or unload the local plist and
   change private `execution` policy. Never leave both schedulers active.

The local machine-owner fence does not govern a cloud task. Scheduler
exclusivity is therefore an explicit migration step, not an automatic lock.
""",
        encoding="utf-8",
    )
    readme.chmod(0o600)
    return {
        "output": str(output),
        "routines": len(routines),
        "prompts": sum(item["prompt"] is not None for item in routines),
        "missing_prompts": [item["name"] for item in routines if item["prompt"] is None],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        payload = build(args.output)
    except BundleError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            f"cloud bundle: {payload['prompts']}/{payload['routines']} prompt(s); "
            f"output={payload['output']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
