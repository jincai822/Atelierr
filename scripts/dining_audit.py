#!/usr/bin/env python3
"""Audit the private dining registry and canonical meal-history table."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

REQUIRED_ROLES = (
    "Regional dining catalog",
    "Meal-history tracker",
    "Credit-perks catalog",
    "Benefits tracker",
    "Prepaid-balance tracker",
)
EXPECTED_COLUMNS = (
    "Date",
    "Restaurant",
    "City",
    "类型",
    "⭐",
    "评分",
    "再去",
    "健康",
    "人数",
    "总额",
    "人均",
    "Platform",
    "Credit",
    "必点·备注",
)
UNKNOWN = {"", "—", "-"}
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
MONEY_RE = re.compile(r"^(~)?\$([0-9]+(?:\.[0-9]{1,2})?)$")
PROFILE_ROLE_RE = re.compile(r"^[A-Za-z][A-Za-z -]+$")


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    path: str
    detail: str
    row: int | None = None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "severity": self.severity,
            "code": self.code,
            "path": self.path,
            "detail": self.detail,
        }
        if self.row is not None:
            payload["row"] = self.row
        return payload


def _display_path(path: Path, vault: Path) -> str:
    try:
        return f"$OV/{path.resolve().relative_to(vault.resolve()).as_posix()}"
    except ValueError:
        return path.as_posix()


def _split_markdown_row(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for character in stripped[1:-1]:
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(character)
    if escaped:
        current.append("\\")
    cells.append("".join(current).strip())
    return cells


def _section(text: str, heading: str) -> str | None:
    marker = f"## {heading}"
    if marker not in text:
        return None
    remainder = text.split(marker, 1)[1]
    next_heading = re.search(r"^## ", remainder, flags=re.MULTILINE)
    return remainder[: next_heading.start()] if next_heading else remainder


def _parse_catalog_paths(
    profile_path: Path, vault: Path
) -> tuple[dict[str, Path], list[Finding]]:
    findings: list[Finding] = []
    display = _display_path(profile_path, vault)
    if not profile_path.is_file():
        return {}, [
            Finding(
                "error",
                "profile_missing",
                display,
                "private dining profile does not exist",
            )
        ]

    text = profile_path.read_text(encoding="utf-8")
    section = _section(text, "Catalog files")
    if section is None:
        return {}, [
            Finding(
                "error",
                "catalog_section_missing",
                display,
                "profile has no 'Catalog files' section",
            )
        ]

    mappings: dict[str, Path] = {}
    for line_number, line in enumerate(section.splitlines(), start=1):
        cells = _split_markdown_row(line)
        if len(cells) < 2:
            continue
        role = cells[0].strip()
        raw_path = cells[1].strip().strip("`")
        if role in {"Role", "---"} or not PROFILE_ROLE_RE.fullmatch(role):
            continue
        if not raw_path:
            findings.append(
                Finding(
                    "error",
                    "catalog_path_empty",
                    display,
                    f"catalog role {role!r} has an empty path",
                    line_number,
                )
            )
            continue
        candidate = Path(raw_path).expanduser()
        resolved = candidate if candidate.is_absolute() else vault / candidate
        if role in mappings:
            findings.append(
                Finding(
                    "error",
                    "catalog_role_duplicate",
                    display,
                    f"catalog role {role!r} is declared more than once",
                    line_number,
                )
            )
            continue
        mappings[role] = resolved.resolve()

    for role in REQUIRED_ROLES:
        if role not in mappings:
            findings.append(
                Finding(
                    "error",
                    "catalog_role_missing",
                    display,
                    f"required catalog role {role!r} is not mapped",
                )
            )
            continue
        target = mappings[role]
        if not target.is_file():
            findings.append(
                Finding(
                    "error",
                    "catalog_file_missing",
                    _display_path(target, vault),
                    f"mapped file for {role!r} does not exist",
                )
            )

    duplicate_paths: dict[Path, list[str]] = {}
    for role, target in mappings.items():
        duplicate_paths.setdefault(target, []).append(role)
    for target, roles in duplicate_paths.items():
        if len(roles) > 1:
            findings.append(
                Finding(
                    "error",
                    "catalog_path_reused",
                    _display_path(target, vault),
                    f"one file is mapped to multiple roles: {', '.join(sorted(roles))}",
                )
            )
    return mappings, findings


def _health_vocabulary(profile_path: Path) -> set[str]:
    if not profile_path.is_file():
        return set()
    section = _section(
        profile_path.read_text(encoding="utf-8"), "Full health-flag taxonomy"
    )
    if section is None:
        return set()
    return {
        match.group(1).strip()
        for match in re.finditer(r"^- `([^`]+)`\s", section, flags=re.MULTILINE)
    }


def _parse_money(value: str) -> tuple[Decimal | None, bool]:
    if value in UNKNOWN:
        return None, False
    match = MONEY_RE.fullmatch(value)
    if not match:
        raise ValueError(value)
    try:
        return Decimal(match.group(2)), bool(match.group(1))
    except InvalidOperation as exc:
        raise ValueError(value) from exc


def _parse_party(value: str) -> int | None:
    if value in UNKNOWN:
        return None
    if not value.isdigit() or int(value) <= 0:
        raise ValueError(value)
    return int(value)


def _audit_meal_history(
    path: Path, profile_path: Path, vault: Path
) -> tuple[list[Finding], dict[str, int]]:
    findings: list[Finding] = []
    stats = {"rows": 0, "dated_rows": 0, "health_flags": 0}
    display = _display_path(path, vault)
    if not path.is_file():
        return [
            Finding("error", "meal_history_missing", display, "meal history is missing")
        ], stats

    lines = path.read_text(encoding="utf-8").splitlines()
    header_indexes = [
        index
        for index, line in enumerate(lines)
        if tuple(_split_markdown_row(line)) == EXPECTED_COLUMNS
    ]
    if not header_indexes:
        return [
            Finding(
                "error",
                "meal_table_missing",
                display,
                "meal history has no table with the canonical schema",
            )
        ], stats
    if len(header_indexes) > 1:
        return [
            Finding(
                "error",
                "meal_table_ambiguous",
                display,
                "meal history has more than one table with the canonical schema",
            )
        ], stats

    header_index = header_indexes[0]
    table_rows: list[tuple[int, list[str]]] = []
    for index in range(header_index, len(lines)):
        line = lines[index]
        if not line.strip().startswith("|"):
            break
        table_rows.append((index + 1, _split_markdown_row(line)))
    if len(table_rows) < 2:
        return [
            Finding(
                "error",
                "meal_table_empty",
                display,
                "canonical meal-history table has no separator row",
            )
        ], stats

    header_line, header = table_rows[0]
    if tuple(header) != EXPECTED_COLUMNS:
        findings.append(
            Finding(
                "error",
                "schema_mismatch",
                display,
                f"expected {len(EXPECTED_COLUMNS)} canonical columns, got {header!r}",
                header_line,
            )
        )

    health_vocabulary = _health_vocabulary(profile_path)
    if not health_vocabulary:
        findings.append(
            Finding(
                "error",
                "health_taxonomy_missing",
                _display_path(profile_path, vault),
                "profile has no parseable health-flag taxonomy",
            )
        )

    previous_date: date | None = None
    seen: set[tuple[date, str]] = set()
    for line_number, cells in table_rows[2:]:
        if not cells or all(set(cell) <= {"-", ":", " "} for cell in cells):
            continue
        stats["rows"] += 1
        if len(cells) != len(EXPECTED_COLUMNS):
            findings.append(
                Finding(
                    "error",
                    "row_width",
                    display,
                    f"expected {len(EXPECTED_COLUMNS)} columns, got {len(cells)}",
                    line_number,
                )
            )
            continue

        row = dict(zip(EXPECTED_COLUMNS, cells, strict=True))
        date_match = DATE_RE.search(row["Date"])
        if not date_match:
            findings.append(
                Finding(
                    "error",
                    "date_missing",
                    display,
                    f"row has no ISO event date: {row['Date']!r}",
                    line_number,
                )
            )
            continue
        try:
            event_date = date.fromisoformat(date_match.group(1))
        except ValueError:
            findings.append(
                Finding(
                    "error",
                    "date_invalid",
                    display,
                    f"row has an invalid event date: {date_match.group(1)!r}",
                    line_number,
                )
            )
            continue
        stats["dated_rows"] += 1
        if previous_date is not None and event_date < previous_date:
            findings.append(
                Finding(
                    "error",
                    "date_order",
                    display,
                    f"{event_date.isoformat()} appears after {previous_date.isoformat()}",
                    line_number,
                )
            )
        previous_date = event_date

        identity = (event_date, re.sub(r"\[|\]|\([^)]*\)", "", row["Restaurant"]))
        if identity in seen:
            findings.append(
                Finding(
                    "warning",
                    "possible_duplicate",
                    display,
                    f"duplicate date and restaurant: {event_date} {row['Restaurant']}",
                    line_number,
                )
            )
        seen.add(identity)

        if row["健康"] not in UNKNOWN:
            flags = [flag.strip() for flag in row["健康"].split("·") if flag.strip()]
            stats["health_flags"] += len(flags)
            for flag in flags:
                if flag not in health_vocabulary:
                    findings.append(
                        Finding(
                            "error",
                            "health_flag_unknown",
                            display,
                            f"health flag {flag!r} is absent from profile taxonomy",
                            line_number,
                        )
                    )

        try:
            party = _parse_party(row["人数"])
        except ValueError:
            findings.append(
                Finding(
                    "error",
                    "party_invalid",
                    display,
                    f"party size must be a positive integer or dash: {row['人数']!r}",
                    line_number,
                )
            )
            party = None
        try:
            total, total_approximate = _parse_money(row["总额"])
        except ValueError:
            findings.append(
                Finding(
                    "error",
                    "total_invalid",
                    display,
                    f"total must be $N, ~$N, or dash: {row['总额']!r}",
                    line_number,
                )
            )
            total, total_approximate = None, False
        try:
            per_person, per_person_approximate = _parse_money(row["人均"])
        except ValueError:
            findings.append(
                Finding(
                    "error",
                    "per_person_invalid",
                    display,
                    f"per-person must be $N, ~$N, or dash: {row['人均']!r}",
                    line_number,
                )
            )
            per_person, per_person_approximate = None, False

        if party is not None and total is not None:
            expected = (total / Decimal(party)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if per_person is None:
                findings.append(
                    Finding(
                        "error",
                        "per_person_missing",
                        display,
                        f"party and total imply a per-person value of ${expected}",
                        line_number,
                    )
                )
            elif abs(per_person - expected) > Decimal("0.01"):
                findings.append(
                    Finding(
                        "error",
                        "per_person_mismatch",
                        display,
                        f"stored ${per_person} does not match ${total} / {party} = ${expected}",
                        line_number,
                    )
                )
            if total_approximate and not per_person_approximate:
                findings.append(
                    Finding(
                        "warning",
                        "approximation_lost",
                        display,
                        "approximate total produced a non-approximate per-person value",
                        line_number,
                    )
                )

    return findings, stats


def audit(vault: Path) -> dict[str, Any]:
    vault = vault.expanduser().resolve()
    profile_path = vault / "profile" / "diet.md"
    mappings, findings = _parse_catalog_paths(profile_path, vault)
    stats: dict[str, object] = {
        "catalog_roles": len(mappings),
        "rows": 0,
        "dated_rows": 0,
        "health_flags": 0,
    }
    meal_history = mappings.get("Meal-history tracker")
    if meal_history is not None and meal_history.is_file():
        table_findings, table_stats = _audit_meal_history(
            meal_history, profile_path, vault
        )
        findings.extend(table_findings)
        stats.update(table_stats)

    errors = [finding.as_dict() for finding in findings if finding.severity == "error"]
    warnings = [
        finding.as_dict() for finding in findings if finding.severity == "warning"
    ]
    return {
        "ok": not errors,
        "vault": "$OV",
        "stats": stats,
        "errors": errors,
        "warnings": warnings,
    }


def _resolve_vault(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    raw = os.environ.get("OV")
    if not raw:
        raise ValueError("$OV is not set; pass --vault explicitly")
    return Path(raw)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        payload = audit(_resolve_vault(args.vault))
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"dining_audit: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        status = "clean" if payload["ok"] else "failed"
        print(
            f"dining_audit: {status}; "
            f"errors={len(payload['errors'])} warnings={len(payload['warnings'])}"
        )
        for finding in [*payload["errors"], *payload["warnings"]]:
            row = f":{finding['row']}" if "row" in finding else ""
            print(
                f"{finding['severity']}: {finding['path']}{row}: "
                f"{finding['code']}: {finding['detail']}"
            )
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
