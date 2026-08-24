#!/usr/bin/env python3
"""Shared, validated loaders for the harness registries.

The same TOML files were parsed independently in up to six places with
divergent failure behavior (a malformed commands.toml was a hard lint error
but a silent cosmetic no-op in cue rendering). Production consumers load
through these functions and get one exception type, `RegistryError`; each
call site keeps its own edge policy (degrade, Finding, exit) but the parse
and shape validation happen once.

Deliberately NOT migrated: `harness_lint.py` and `harness_smoke.py` keep
their own independent parses, because a checker that shares the production
loader cannot catch that loader's own bugs. `atelier_runtime.load_registry`
remains the owner of runtimes.toml (it already validates the launch schema).
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RegistryError(RuntimeError):
    """A harness registry is missing, unparsable, or the wrong shape."""


def _load_table(filename: str, table: str, root: Path | None = None) -> dict:
    path = (root or ROOT) / "harness" / filename
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except OSError as exc:
        raise RegistryError(f"{filename}: unreadable: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise RegistryError(f"{filename}: parse error: {exc}") from exc
    value = data.get(table)
    if not isinstance(value, dict):
        raise RegistryError(f"{filename}: missing [{table}] table")
    return value


def load_commands(root: Path | None = None) -> dict[str, dict]:
    return {k: v for k, v in _load_table("commands.toml", "commands", root).items() if isinstance(v, dict)}


def load_agents(root: Path | None = None) -> dict[str, dict]:
    return {k: v for k, v in _load_table("agents.toml", "agents", root).items() if isinstance(v, dict)}


def load_intents(root: Path | None = None) -> dict[str, dict]:
    return {k: v for k, v in _load_table("intents.toml", "intents", root).items() if isinstance(v, dict)}


def load_models(root: Path | None = None) -> dict[str, dict]:
    return {k: v for k, v in _load_table("models.toml", "models", root).items() if isinstance(v, dict)}


if __name__ == "__main__":
    for name, loader in (
        ("commands", load_commands),
        ("agents", load_agents),
        ("intents", load_intents),
        ("models", load_models),
    ):
        try:
            print(f"{name}: {len(loader())} entries")
        except RegistryError as exc:
            print(f"{name}: ERROR {exc}", file=sys.stderr)
            sys.exit(1)
