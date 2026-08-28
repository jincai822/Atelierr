#!/usr/bin/env python3
"""Validate a model-reported local-routine result against its output policy."""

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
from datetime import datetime
from pathlib import Path
import sys as _s
_s.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import tier_segments  # noqa: E402
from typing import Any

SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SUCCESS_OUTCOMES = {"delivered", "noop"}


class ResultError(RuntimeError):
    """A routine result failed its delivery contract."""


def _vault() -> Path:
    raw = os.environ.get("OV")
    if not raw:
        raise ResultError("OV is not set")
    return Path(raw).expanduser().resolve()


def _safe_relative(value: str, *, field: str) -> Path:
    path = Path(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ResultError(f"{field} must stay relative to the vault")
    return path


def _load_watch_record(vault: Path, routine: str) -> dict[str, Any]:
    watch_path = vault / tier_segments().get("meta", "_meta") / "routine_watch.toml"
    try:
        config = tomllib.loads(watch_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ResultError(f"cannot read routine output policy: {exc}") from exc
    matches = [
        row
        for row in config.get("routine", [])
        if isinstance(row, dict) and row.get("name") == routine
    ]
    if len(matches) != 1:
        raise ResultError(f"expected exactly one routine policy row for {routine}")
    record = matches[0]
    if record.get("execution") != "local":
        raise ResultError(f"routine {routine} is not configured for local execution")
    return record


def _load_model_result(path: Path, routine: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResultError(f"model result is missing or invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ResultError("model result must be a JSON object")
    if value.get("routine") != routine:
        raise ResultError("model result routine does not match the claimed routine")
    outcome = value.get("outcome")
    if outcome == "failed":
        raise ResultError("model reported a failed routine outcome")
    if outcome not in SUCCESS_OUTCOMES:
        raise ResultError("model result has an invalid outcome")
    if not isinstance(value.get("summary"), str):
        raise ResultError("model result summary must be a string")
    skipped = value.get("skipped_inputs")
    if not isinstance(skipped, list) or any(not isinstance(item, str) for item in skipped):
        raise ResultError("model result skipped_inputs must be a string array")
    return value


def _reported_output(vault: Path, raw_value: object) -> Path:
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise ResultError("successful model result must name its output_file")
    value = raw_value.strip()
    if value.startswith("$OV/"):
        value = value[4:]
    path = Path(value).expanduser()
    candidate = path if path.is_absolute() else vault / path
    try:
        candidate = candidate.resolve()
        candidate.relative_to(vault)
    except (OSError, ValueError) as exc:
        raise ResultError("reported output_file escapes the vault") from exc
    return candidate


def _claimed_timestamp(value: str) -> float:
    try:
        claimed_at = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ResultError("claimed_at is not an ISO timestamp") from exc
    return claimed_at.timestamp()


def verify_result(
    routine: str,
    cycle: str,
    claimed_at: str,
    result_file: Path,
) -> dict[str, Any]:
    """Return a delivery attestation or raise ``ResultError``."""
    if not SAFE_COMPONENT.fullmatch(routine) or not SAFE_COMPONENT.fullmatch(cycle):
        raise ResultError("unsafe routine or cycle identifier")

    vault = _vault()
    record = _load_watch_record(vault, routine)
    output_dir = record.get("output_dir")
    pattern = record.get("file_pattern")
    if not isinstance(output_dir, str) or not isinstance(pattern, str):
        raise ResultError("routine policy must declare output_dir and file_pattern")
    output_root = vault / _safe_relative(output_dir, field="output_dir")
    _safe_relative(pattern, field="file_pattern")

    model_result = _load_model_result(result_file, routine)
    reported = _reported_output(vault, model_result.get("output_file"))
    threshold = _claimed_timestamp(claimed_at) - 2.0

    try:
        candidates = {
            path.resolve()
            for path in output_root.glob(pattern)
            if path.is_file() and path.stat().st_size > 0 and path.stat().st_mtime >= threshold
        }
    except OSError as exc:
        raise ResultError(f"cannot inspect declared routine outputs: {exc}") from exc

    if reported not in candidates:
        raise ResultError(
            "reported output_file is absent, empty, outside the declared pattern, "
            "or older than the cycle claim"
        )

    relative_output = reported.relative_to(vault).as_posix()
    return {
        "validated": True,
        "routine": routine,
        "cycle_id": cycle,
        "outcome": model_result["outcome"],
        "output_file": relative_output,
        "size_bytes": reported.stat().st_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("routine")
    parser.add_argument("--cycle", required=True)
    parser.add_argument("--claimed-at", required=True)
    parser.add_argument("--result-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        payload = verify_result(
            args.routine,
            args.cycle,
            args.claimed_at,
            args.result_file,
        )
    except ResultError as exc:
        print(json.dumps({"validated": False, "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
