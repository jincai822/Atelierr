#!/usr/bin/env python3
"""Fail closed before a private routine prompt is sent to a headless model."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SECRET_PATTERNS = (
    re.compile(
        r"(?i)authorization\s*:\s*(?:basic|token|bearer)\s+"
        r"(?!<|\$\{|\{\{|redacted\b|placeholder\b)[A-Za-z0-9._~+/=-]{12,}"
    ),
    re.compile(
        r"(?i)[\"']?(?:api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|"
        r"secret[_-]?access[_-]?key|password|passwd|secret)[\"']?\s*[:=]\s*[\"']?"
        r"(?!<|\$\{|\{\{|redacted\b|placeholder\b|example\b|changeme\b)"
        r"[A-Za-z0-9._~+/=-]{12,}"
    ),
    re.compile(
        r"(?m)(?:^|\s)(?:[A-Z][A-Z0-9_]*(?:TOKEN|KEY|SECRET|PASSWORD)|"
        r"AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY)\s*=\s*[\"']?"
        r"(?!<|\$\{|\{\{|REDACTED\b|PLACEHOLDER\b|EXAMPLE\b|CHANGEME\b)"
        r"[A-Za-z0-9._~+/=-]{12,}"
    ),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(
        r"(?i)\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|"
        r"github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{16,}|"
        r"AIza[A-Za-z0-9_-]{20,})\b"
    ),
    re.compile(
        r"(?i)--(?:api[_-]?)?token(?:=|\s+)[\"']?"
        r"(?!<|\$\{|\{\{|redacted\b|placeholder\b)[A-Za-z0-9._~+/=-]{12,}"
    ),
    re.compile(r"(?i)https?://[^\s/:@]+:[^\s/@]{8,}@"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
ORIGINAL_PROMPT_MARKER = re.compile(
    r"(?m)^--- ORIGINAL ROUTINE PROMPT .* ---\s*$"
)


def check(path: Path) -> list[int]:
    text = path.read_text(encoding="utf-8")
    lines: set[int] = set()
    for pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            lines.add(text.count("\n", 0, match.start()) + 1)
    return sorted(lines)


def structure_error(path: Path) -> str | None:
    text = path.read_text(encoding="utf-8")
    first_line = text.splitlines()[0] if text.splitlines() else ""
    if not first_line.startswith("LOCAL EXECUTION OVERRIDE"):
        return "first line must begin with LOCAL EXECUTION OVERRIDE"
    if ORIGINAL_PROMPT_MARKER.search(text) is None:
        return "missing ORIGINAL ROUTINE PROMPT boundary marker"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Reject archived prompts with literal credentials.")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()

    if not args.path.is_file():
        print(f"ERROR: routine prompt missing: {args.path}", file=sys.stderr)
        return 2
    try:
        invalid_structure = structure_error(args.path)
        findings = check(args.path)
    except OSError as exc:
        print(f"ERROR: cannot read routine prompt: {exc}", file=sys.stderr)
        return 2
    if invalid_structure:
        print(f"ERROR: invalid local-adapter preamble: {invalid_structure}", file=sys.stderr)
        return 1
    if findings:
        joined = ", ".join(str(line) for line in findings)
        print(
            f"ERROR: literal credential detected in routine prompt at line(s): {joined}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
