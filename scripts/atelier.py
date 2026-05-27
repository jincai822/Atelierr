#!/usr/bin/env python3
"""
atelier.py: small helper CLI for portable Atelier workflows.

Claude Code has native project slash commands. Codex does not currently expose
a documented custom project slash-command format, so this helper gives Codex a
stable command discovery surface:

    python3 scripts/atelier.py commands
    python3 scripts/atelier.py prompt hi
    python3 scripts/atelier.py source hi
    python3 scripts/atelier.py agents
    python3 scripts/atelier.py agent-prompt researcher
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import textwrap
import tomllib
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
COMMANDS_PATH = ROOT / "harness" / "commands.toml"
AGENTS_PATH = ROOT / "harness" / "agents.toml"
MODELS_PATH = ROOT / "harness" / "models.toml"
CAPABILITIES_PATH = ROOT / "harness" / "capabilities.toml"
INTENTS_PATH = ROOT / "harness" / "intents.toml"

INTENT_MISS_FALLBACK_DIR = Path.home() / ".cache" / "atelier" / "intent_misses"
INTENT_MISS_KINDS = ("fallback", "ambiguous", "low_confidence")
INTENT_MISS_RUNTIMES = ("claude-code", "codex")
INTENT_MISS_DISTINCT_DAYS_THRESHOLD = 3
INTENT_MISS_KINDS_COL_WIDTH = len(",".join(sorted(INTENT_MISS_KINDS)))


def load_commands() -> dict[str, dict[str, Any]]:
    commands = load_table(COMMANDS_PATH, "commands")
    if not isinstance(commands, dict):
        raise SystemExit("atelier: harness/commands.toml has no [commands] table")
    return commands


def load_agents() -> dict[str, dict[str, Any]]:
    agents = load_table(AGENTS_PATH, "agents")
    if not isinstance(agents, dict):
        raise SystemExit("atelier: harness/agents.toml has no [agents] table")
    return agents


def load_intents() -> dict[str, dict[str, Any]]:
    intents = load_table(INTENTS_PATH, "intents")
    if not isinstance(intents, dict):
        raise SystemExit("atelier: harness/intents.toml has no [intents] table")
    return intents


def match_intents(text: str, intents: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Match user text against intents.toml patterns.

    Substring match, case-insensitive. Returns matched intents sorted by
    descending priority. The fallback intent (empty patterns, priority 0) is
    included in results ONLY when no other intent matched, mirroring the
    "no specific intent matched" branch in hi.md.
    """
    text_lc = text.lower()
    matched: list[dict[str, Any]] = []
    fallback: dict[str, Any] | None = None
    for name, row in intents.items():
        if not isinstance(row, dict):
            continue
        patterns = row.get("patterns") or []
        priority = int(row.get("priority", 0))
        entry = {
            "name": name,
            "mode": str(row.get("mode", "")),
            "agents": list(row.get("agents") or []),
            "profile_reads": list(row.get("profile_reads") or []),
            "priority": priority,
            "pattern": str(row.get("pattern", "")),
            "parallel": bool(row.get("parallel", False)),
            "expected_subagent_count": int(row.get("expected_subagent_count", 0)),
        }
        if not patterns:
            fallback = entry
            continue
        if not isinstance(patterns, list):
            continue
        hit = next((p for p in patterns if isinstance(p, str) and p.lower() in text_lc), None)
        if hit:
            entry["matched_pattern"] = hit
            matched.append(entry)
    matched.sort(key=lambda e: -int(e["priority"]))
    if not matched and fallback is not None:
        fallback["matched_pattern"] = "<fallback: no patterns matched>"
        matched.append(fallback)
    return matched


def load_table(path: Path, table: str) -> dict[str, Any]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if table not in data:
        raise SystemExit(f"atelier: {path.relative_to(ROOT)} has no [{table}] table")
    value = data[table]
    if not isinstance(value, dict):
        raise SystemExit(f"atelier: {path.relative_to(ROOT)} [{table}] is not a table")
    return value


def require_command(commands: dict[str, dict[str, Any]], name: str) -> dict[str, Any]:
    try:
        command = commands[name]
    except KeyError:
        known = ", ".join(sorted(commands))
        raise SystemExit(f"atelier: unknown command `{name}`. Known commands: {known}") from None
    if not isinstance(command, dict):
        raise SystemExit(f"atelier: command `{name}` is not a table")
    # Resolve aliases: `status = "alias"` with `alias_of = "<target>"` redirects
    # source/codex_prompt lookups to the target entry. The alias's own row
    # remains visible in `commands` listings as a documentation breadcrumb.
    if command.get("status") == "alias":
        target_name = command.get("alias_of")
        if not isinstance(target_name, str) or not target_name:
            raise SystemExit(f"atelier: command `{name}` is `status = \"alias\"` but missing `alias_of`")
        if target_name == name:
            raise SystemExit(f"atelier: command `{name}` aliases itself")
        try:
            target = commands[target_name]
        except KeyError:
            raise SystemExit(f"atelier: command `{name}` aliases unknown command `{target_name}`") from None
        if not isinstance(target, dict):
            raise SystemExit(f"atelier: alias target `{target_name}` is not a table")
        if target.get("status") == "alias":
            raise SystemExit(f"atelier: alias chains are not allowed (`{name}` -> `{target_name}` -> alias)")
        return target
    return command


def require_agent(agents: dict[str, dict[str, Any]], name: str) -> dict[str, Any]:
    try:
        agent = agents[name]
    except KeyError:
        known = ", ".join(sorted(agents))
        raise SystemExit(f"atelier: unknown agent `{name}`. Known agents: {known}") from None
    if not isinstance(agent, dict):
        raise SystemExit(f"atelier: agent `{name}` is not a table")
    return agent


def print_rows(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> None:
    widths = [
        max(len(headers[i]), *(len(row[i]) for row in rows))
        for i in range(len(headers))
    ]
    print("  ".join(f"{headers[i]:<{widths[i]}}" for i in range(len(headers))))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(f"{row[i]:<{widths[i]}}" for i in range(len(headers))))


def cmd_commands(args: argparse.Namespace) -> int:
    commands = load_commands()
    selected: dict[str, dict[str, Any]] = {}
    for name, command in sorted(commands.items()):
        if args.category and command.get("category") != args.category:
            continue
        selected[name] = command
    if args.json:
        print(json.dumps(selected, indent=2, sort_keys=True))
        return 0

    rows: list[tuple[str, str, str, str]] = []
    for name, command in selected.items():
        rows.append((
            name,
            str(command.get("category", "")),
            str(command.get("status", "")),
            str(command.get("description", "")),
        ))
    if not rows:
        return 0

    print_rows(("command", "category", "status", "description"), rows)
    return 0


def cmd_agents(args: argparse.Namespace) -> int:
    agents = load_agents()
    selected: dict[str, dict[str, Any]] = {}
    for name, agent in sorted(agents.items()):
        if args.member:
            voices = agent.get("voices") or {}
            members = list(voices.values()) if isinstance(voices, dict) else []
            if args.member not in members:
                continue
        if args.kind:
            kinds = agent.get("kinds") or []
            if not isinstance(kinds, list) or args.kind not in kinds:
                continue
        selected[name] = agent
    if args.json:
        print(json.dumps(selected, indent=2, sort_keys=True))
        return 0

    rows: list[tuple[str, str, str, str]] = []
    for name, agent in selected.items():
        voices = agent.get("voices") or {}
        if isinstance(voices, dict):
            voices_str = ",".join(f"{leg}={model}" for leg, model in sorted(voices.items()))
        else:
            voices_str = str(voices)
        rows.append((
            name,
            voices_str,
            str(agent.get("status", "")),
            str(agent.get("description", "")),
        ))
    if not rows:
        return 0
    print_rows(("agent", "voices", "status", "description"), rows)
    return 0


def cmd_prompt(args: argparse.Namespace) -> int:
    commands = load_commands()
    command = require_command(commands, args.command)
    source = str(command.get("source", ""))
    base_prompt = str(command.get("codex_prompt", "")).strip()
    if not base_prompt:
        base_prompt = f"Run the /{args.command} workflow using `{source}`."

    extra_args = " ".join(args.arguments).strip()
    parts = [
        base_prompt,
        "",
        "Before acting, read `AGENTS.md`, `CLAUDE.md`, and `protocols/runtime-adapters.md`.",
        "Translate Claude Code tool syntax to the current runtime. Prefer local `$OV/` files and ask before any Reflect write.",
    ]
    if extra_args:
        parts.extend(["", f"Arguments/context: {extra_args}"])
    print("\n".join(parts))
    return 0


def cmd_agent_prompt(args: argparse.Namespace) -> int:
    agents = load_agents()
    agent = require_agent(agents, args.agent)
    source = str(agent.get("source", ""))
    base_prompt = str(agent.get("codex_prompt", "")).strip()
    if not base_prompt:
        base_prompt = f"Emulate the {args.agent} role using `{source}`."

    extra_args = " ".join(args.arguments).strip()
    parts = [
        base_prompt,
        "",
        "Before acting, read `AGENTS.md`, `CLAUDE.md`, and `protocols/runtime-adapters.md`.",
        "Use the agent spec as a role brief. Translate Claude Code tool syntax to the current runtime.",
    ]
    if extra_args:
        parts.extend(["", f"Task/context: {extra_args}"])
    print("\n".join(parts))
    return 0


def cmd_source(args: argparse.Namespace) -> int:
    commands = load_commands()
    command = require_command(commands, args.command)
    source = ROOT / str(command.get("source", ""))
    if args.path_only:
        print(source.relative_to(ROOT).as_posix())
        return 0
    if not source.exists():
        raise SystemExit(f"atelier: command source `{source}` does not exist")
    print(source.read_text(encoding="utf-8"))
    return 0


def cmd_agent_source(args: argparse.Namespace) -> int:
    agents = load_agents()
    agent = require_agent(agents, args.agent)
    source = ROOT / str(agent.get("source", ""))
    if args.path_only:
        print(source.relative_to(ROOT).as_posix())
        return 0
    if not source.exists():
        raise SystemExit(f"atelier: agent source `{source}` does not exist")
    print(source.read_text(encoding="utf-8"))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    commands = load_commands()
    command = require_command(commands, args.command)
    source = str(command.get("source", ""))
    base_prompt = str(command.get("codex_prompt", "")).strip()
    if not base_prompt:
        base_prompt = f"Run the /{args.command} workflow using `{source}`."

    extra = (args.context or "").strip()
    parts = [
        base_prompt,
        "",
        "Before acting, read `AGENTS.md`, `CLAUDE.md`, and `protocols/runtime-adapters.md`.",
        "Translate Claude Code tool syntax to the current runtime. Prefer local `$OV/` files and ask before any Reflect write.",
    ]
    if extra:
        parts.extend(["", f"Arguments/context: {extra}"])
    prompt = "\n".join(parts)

    if args.fork and args.exec:
        raise SystemExit("atelier: --fork is not supported with --exec; `codex exec` has no fork subcommand.")

    resume_friendly = bool(command.get("resume_friendly", False))
    if (args.resume or args.fork) and not resume_friendly:
        sys.stderr.write(
            f"atelier: warning: `{args.command}` is not marked resume_friendly; "
            "carrying prior session context may pollute reflection-style workflows. "
            "Consider running fresh, or `--fork` to isolate side effects.\n"
        )

    if args.print:
        print(prompt)
        return 0

    if args.fork:
        codex_cmd = ["codex", "fork", "--last", prompt]
    elif args.resume:
        codex_cmd = (
            ["codex", "exec", "resume", "--last", prompt]
            if args.exec
            else ["codex", "resume", "--last", prompt]
        )
    elif args.exec:
        codex_cmd = ["codex", "exec", "-C", str(ROOT), prompt]
    else:
        codex_cmd = ["codex", "-C", str(ROOT), prompt]

    try:
        return subprocess.run(codex_cmd, cwd=str(ROOT)).returncode
    except FileNotFoundError:
        raise SystemExit(
            "atelier: codex CLI not found on PATH. Install with `npm i -g @openai/codex`."
        ) from None


def cmd_intent(args: argparse.Namespace) -> int:
    """Match user text against the intent router (Codex parity for /hi).

    Mirrors the substring + priority matcher hi.md describes. Returns the
    winning intent + its dispatch shape (mode, agents, parallel). When
    multiple non-fallback intents match (ambiguity), all winners are listed
    and the caller (Codex orchestrator) should ask for clarification.
    """
    text = " ".join(args.text).strip()
    if not text:
        raise SystemExit("atelier: intent requires a text argument. Example: intent 'review my goals'")
    intents = load_intents()
    matches = match_intents(text, intents)

    if not matches:
        # Shouldn't happen since fallback is included on empty, but defend.
        payload: dict[str, Any] = {"input": text, "matched": [], "ambiguous": False, "fallback": True}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"input: {text}\n(no intent matched and no fallback declared)")
        return 0

    is_fallback = matches[0].get("matched_pattern", "").startswith("<fallback")
    top_priority = int(matches[0]["priority"])
    top_matches = [m for m in matches if int(m["priority"]) == top_priority and not m.get("matched_pattern", "").startswith("<fallback")]
    ambiguous = len(top_matches) > 1

    payload = {
        "input": text,
        "winner": matches[0]["name"],
        "mode": matches[0]["mode"],
        "agents": matches[0]["agents"],
        "parallel": matches[0]["parallel"],
        "profile_reads": matches[0]["profile_reads"],
        "matched_pattern": matches[0].get("matched_pattern", ""),
        "priority": top_priority,
        "ambiguous": ambiguous,
        "fallback": is_fallback,
        "all_matches": [
            {
                "name": m["name"],
                "mode": m["mode"],
                "priority": int(m["priority"]),
                "matched_pattern": m.get("matched_pattern", ""),
                "agents": m["agents"],
                "parallel": m["parallel"],
            }
            for m in matches
        ],
    }

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print(f"input:    {text}")
    print(f"winner:   intents.{payload['winner']}  (priority {top_priority}, mode {payload['mode']})")
    if payload["matched_pattern"]:
        print(f"matched:  {payload['matched_pattern']}")
    if payload["agents"]:
        agent_list = ", ".join(payload["agents"])
        para = " (parallel)" if payload["parallel"] else " (sequential)"
        print(f"agents:   {agent_list}{para}")
    else:
        print("agents:   (none — script-driven or solo orchestrator)")
    if payload["profile_reads"]:
        print(f"profile:  {', '.join(payload['profile_reads'])}")
    if is_fallback:
        print()
        print("note: no specific patterns matched; defaulted to fallback reflection.")
        print("      consider asking the user for confirmation before dispatching.")
    if ambiguous:
        print()
        print(f"AMBIGUOUS: {len(top_matches)} intents at priority {top_priority} match this input:")
        for m in top_matches:
            print(f"  - intents.{m['name']}  (pattern: {m.get('matched_pattern', '')}, mode: {m['mode']})")
        print("ask the user which intent they meant before dispatching.")
    return 0


def resolve_intent_miss_dir() -> Path:
    """Where intent-miss JSONL files live.

    Prefers `$OV/_meta/intent_misses/` when `$OV` is set (the durable Atelier
    location alongside `shadow_logs/`). Falls back to
    `~/.cache/atelier/intent_misses/` otherwise so tests / CI / fresh checkouts
    without `$OV` can still exercise the round trip.
    """
    ov = os.environ.get("OV")
    if ov:
        return Path(ov) / "_meta" / "intent_misses"
    return INTENT_MISS_FALLBACK_DIR


def write_intent_miss(payload: dict[str, Any]) -> Path | None:
    """Append one JSONL line to today's intent-miss log.

    Returns the file path on success, or None on OSError. Never raises:
    miss logging is best-effort and must not block a live `/hi` flow.
    """
    miss_dir = resolve_intent_miss_dir()
    try:
        miss_dir.mkdir(parents=True, exist_ok=True)
        log_file = miss_dir / f"{date.today().isoformat()}.jsonl"
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return log_file
    except OSError:
        return None


def cmd_intent_log(args: argparse.Namespace) -> int:
    """Record an unclassified `/hi` invocation for batch coverage review.

    Called by the orchestrator after deciding routing. Three trigger cases
    (see `.claude/commands/hi.md` → "Miss Logging"):
      - fallback: `intents.reflection` won by default; nothing else matched.
      - ambiguous: 2+ non-fallback intents tied at the top priority.
      - low_confidence: a generic substring matched inside a longer message
        whose primary intent looked different; orchestrator used
        `AskUserQuestion` to confirm.
    """
    raw = args.input.strip()
    if not raw:
        sys.stderr.write("atelier: intent-log skipped (empty --input)\n")
        return 0
    try:
        priority_val: int | None = (
            int(args.initial_priority) if args.initial_priority is not None else None
        )
    except (TypeError, ValueError):
        sys.stderr.write(
            f"atelier: intent-log dropping --initial-priority (not an int: {args.initial_priority!r})\n"
        )
        priority_val = None
    payload: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "runtime": args.runtime,
        "raw_input": raw,
        "match_kind": args.match_kind,
        "initial_match": {
            "name": args.initial_name or None,
            "priority": priority_val,
            "matched_pattern": args.initial_pattern or None,
        },
    }
    if args.candidates:
        try:
            payload["ambiguity_candidates"] = json.loads(args.candidates)
        except json.JSONDecodeError as e:
            sys.stderr.write(
                f"atelier: intent-log dropping malformed --candidates (preserved as raw string): {e}\n"
            )
            payload["ambiguity_candidates_raw"] = args.candidates
    if args.clarified_to:
        payload["clarified_to"] = args.clarified_to
    if args.final_dispatch:
        payload["final_dispatch"] = args.final_dispatch
    if args.notes:
        payload["notes"] = args.notes

    path = write_intent_miss(payload)
    if path is None:
        sys.stderr.write("atelier: intent-log write failed; skipped (best-effort, never blocks /hi)\n")
        return 0
    if not args.quiet:
        print(f"intent-log: {path}")
    return 0


def cmd_intent_hook(args: argparse.Namespace) -> int:
    """`UserPromptSubmit` hook entry — out-of-band intent-miss capture.

    Reads the hook's stdin JSON (Claude Code hook contract — `prompt`,
    `session_id`, `transcript_path`, etc), detects `/hi <text>` invocations,
    runs the same deterministic matcher the orchestrator does, and auto-logs
    the fallback / ambiguous branches without the orchestrator ever calling
    a Bash tool. Silent on success (no stdout) so the hook output never feeds
    back into the orchestrator's context.

    Cases the hook CANNOT classify (intentional carve-out — the orchestrator
    retains the in-band `intent-log` path for these):
      - `low_confidence`: heuristic over message shape; LLM judgment lives
        in `.claude/commands/hi.md` § Clarify before dispatching.
      - Post-clarification enrichment (`clarified_to`, `final_dispatch`):
        only known after `AskUserQuestion` resolves.

    Best-effort throughout: every failure path returns 0 silently. A broken
    hook must never block a live `/hi` invocation.
    """
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError, ValueError):
        return 0
    if not isinstance(data, dict):
        return 0
    prompt = str(data.get("prompt", ""))
    if not prompt.startswith("/hi "):
        return 0
    user_text = prompt[len("/hi "):].strip()
    if not user_text:
        return 0  # bare `/hi` opens the menu; nothing to classify
    try:
        intents = load_intents()
        matches = match_intents(user_text, intents)
    except (OSError, ValueError, KeyError, tomllib.TOMLDecodeError):
        return 0
    if not matches:
        return 0
    is_fallback = matches[0].get("matched_pattern", "").startswith("<fallback")
    top_priority = int(matches[0]["priority"])
    top_matches = [
        m for m in matches
        if int(m["priority"]) == top_priority
        and not m.get("matched_pattern", "").startswith("<fallback")
    ]
    is_ambiguous = len(top_matches) > 1
    if not (is_fallback or is_ambiguous):
        return 0
    payload: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "runtime": args.runtime,
        "raw_input": user_text,
        "match_kind": "fallback" if is_fallback else "ambiguous",
        "initial_match": {
            "name": matches[0]["name"],
            "priority": top_priority,
            "matched_pattern": matches[0].get("matched_pattern", ""),
        },
        "logged_by": "user_prompt_submit_hook",
    }
    if is_ambiguous:
        payload["ambiguity_candidates"] = [
            {
                "name": m["name"],
                "priority": int(m["priority"]),
                "matched_pattern": m.get("matched_pattern", ""),
            }
            for m in top_matches
        ]
    if data.get("session_id"):
        payload["session_id"] = str(data["session_id"])
    write_intent_miss(payload)
    return 0


def _normalize_phrase(raw: Any) -> str:
    """Normalize a raw_input string for recurrence aggregation.

    NFKC unifies width / form differences (full-width vs half-width CJK
    punctuation, ligatures); collapsing whitespace + casefold makes
    `"improve  the repo"` and `"Improve The Repo"` aggregate together.
    Trailing length cap matches the original ≤200-char clamp. Punctuation
    is NOT stripped — `url.com` and `Yes.` should not collide.
    """
    s = unicodedata.normalize("NFKC", str(raw))
    return " ".join(s.split()).casefold()[:200]


def cmd_intent_misses(args: argparse.Namespace) -> int:
    """Aggregate the intent-miss log for batch coverage review.

    Use to spot phrases that recur often enough to become trigger candidates
    for an existing or new intent. Signal: same phrase logged on
    INTENT_MISS_DISTINCT_DAYS_THRESHOLD+ distinct file-dates → strong
    candidate for a `harness/intents.toml` pattern addition.
    """
    try:
        since = date.fromisoformat(args.since) if args.since else None
    except ValueError:
        raise SystemExit(
            f"atelier: --since must be YYYY-MM-DD (got {args.since!r})"
        ) from None
    miss_dir = resolve_intent_miss_dir()
    if not miss_dir.is_dir():
        if args.json:
            print(json.dumps({"events": [], "since": args.since, "miss_dir": str(miss_dir)}))
        else:
            print(f"intent-misses: no log directory at {miss_dir}")
            print("Nothing logged yet. Directory is created on first miss.")
        return 0

    # Pair every event with the date of the file it came from. file_date is
    # the consumer-side ground truth for the "distinct days" coverage signal
    # AND for --since filtering — keeps both axes consistent, defending the
    # signal against TZ slips between writer wall-clock and event timestamps.
    events: list[tuple[date, dict[str, Any]]] = []
    for p in sorted(miss_dir.glob("*.jsonl")):
        try:
            file_date = date.fromisoformat(p.stem)
        except ValueError:
            continue
        if since and file_date < since:
            continue
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(ev, dict):
                    events.append((file_date, ev))
        except OSError:
            continue

    if args.match_kind:
        events = [(d, e) for (d, e) in events if e.get("match_kind") == args.match_kind]
    if args.runtime:
        events = [(d, e) for (d, e) in events if e.get("runtime") == args.runtime]

    kind_counts: dict[str, int] = {}
    phrase_stats: dict[str, dict[str, Any]] = {}
    empty_phrase_count = 0
    for file_date, ev in events:
        kind = str(ev.get("match_kind", "(unknown)"))
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        phrase = _normalize_phrase(ev.get("raw_input", ""))
        if not phrase:
            empty_phrase_count += 1
            continue
        entry = phrase_stats.setdefault(
            phrase,
            {"count": 0, "first_seen": None, "last_seen": None, "kinds": set(), "days": set()},
        )
        entry["count"] += 1
        entry["kinds"].add(kind)
        entry["days"].add(file_date.isoformat())
        ts = ev.get("timestamp")
        if isinstance(ts, str):
            if entry["first_seen"] is None or ts < entry["first_seen"]:
                entry["first_seen"] = ts
            if entry["last_seen"] is None or ts > entry["last_seen"]:
                entry["last_seen"] = ts

    if args.json:
        payload = {
            "since": args.since,
            "miss_dir": str(miss_dir),
            "total_events": len(events),
            "by_kind": kind_counts,
            "events_with_empty_phrase": empty_phrase_count,
            "phrases": [
                {
                    "phrase": phrase,
                    "count": pc["count"],
                    "distinct_days": len(pc["days"]),
                    "first_seen": pc["first_seen"],
                    "last_seen": pc["last_seen"],
                    "kinds": sorted(pc["kinds"]),
                }
                for phrase, pc in sorted(
                    phrase_stats.items(), key=lambda kv: (-kv[1]["count"], kv[0])
                )
            ],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    print(f"Intent miss log: {miss_dir}")
    print(f"Total events: {len(events)}" + (f"  (since {args.since})" if args.since else ""))
    print()
    print("By match kind:")
    if not kind_counts:
        print("  (none)")
    for k in sorted(kind_counts.keys()):
        print(f"  {k}: {kind_counts[k]}")
    print()
    if not phrase_stats:
        print("No phrases logged.")
        return 0
    sorted_phrases = sorted(phrase_stats.items(), key=lambda kv: (-kv[1]["count"], kv[0]))
    if empty_phrase_count:
        print(f"({empty_phrase_count} event(s) had empty raw_input — counted in by-kind totals, omitted from the phrase table below.)")
    print(f"Top phrases (showing up to {args.top}):")
    col_w = INTENT_MISS_KINDS_COL_WIDTH
    print(f"  count  days  {'kinds'.ljust(col_w)}  phrase")
    for phrase, pc in sorted_phrases[: args.top]:
        kinds_str = ",".join(sorted(pc["kinds"])).ljust(col_w)
        days_str = f"{len(pc['days']):>4}"
        count_str = f"{pc['count']:>5}"
        print(f"  {count_str}  {days_str}  {kinds_str}  {phrase}")
    repeaters = [
        (phrase, pc) for phrase, pc in sorted_phrases
        if len(pc["days"]) >= INTENT_MISS_DISTINCT_DAYS_THRESHOLD
    ]
    if repeaters:
        print()
        print(
            f"Coverage signal: {len(repeaters)} phrase(s) recurred across "
            f"{INTENT_MISS_DISTINCT_DAYS_THRESHOLD}+ distinct days."
        )
        print("Consider adding a trigger to harness/intents.toml for these.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    commands = load_commands()
    agents = load_agents()
    models = load_table(MODELS_PATH, "models")
    capabilities = load_table(CAPABILITIES_PATH, "capabilities")

    payload = {
        "roots": {
            "AGENTS.md": {
                "exists": (ROOT / "AGENTS.md").exists(),
                "bytes": (ROOT / "AGENTS.md").stat().st_size if (ROOT / "AGENTS.md").exists() else 0,
            },
            "CLAUDE.md": {
                "exists": (ROOT / "CLAUDE.md").exists(),
                "bytes": (ROOT / "CLAUDE.md").stat().st_size if (ROOT / "CLAUDE.md").exists() else 0,
            },
        },
        "registries": {
            "commands": len(commands),
            "agents": len(agents),
            "models": len(models),
            "capabilities": len(capabilities),
        },
        "commands_by_category": count_by(commands, "category"),
        "agents_by_voices_member": count_by_voices(agents),
        "agents_by_kind": count_by_kinds(agents),
        "paths": {
            "commands": COMMANDS_PATH.relative_to(ROOT).as_posix(),
            "agents": AGENTS_PATH.relative_to(ROOT).as_posix(),
            "models": MODELS_PATH.relative_to(ROOT).as_posix(),
            "capabilities": CAPABILITIES_PATH.relative_to(ROOT).as_posix(),
            "runtime_adapters": "protocols/runtime-adapters.md",
            "skill": ".agents/skills/atelier/SKILL.md",
        },
    }

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print("Atelier harness status")
    print("")
    print(f"AGENTS.md: {payload['roots']['AGENTS.md']['bytes']} bytes")
    print(f"CLAUDE.md: {payload['roots']['CLAUDE.md']['bytes']} bytes")
    print("")
    print("Registries")
    for key, value in payload["registries"].items():
        print(f"- {key}: {value}")
    print("")
    print("Commands by category")
    for key, value in payload["commands_by_category"].items():
        print(f"- {key}: {value}")
    print("")
    print("Agents by voices member")
    for key, value in payload["agents_by_voices_member"].items():
        print(f"- {key}: {value}")
    print("")
    print("Agents by kind")
    for key, value in payload["agents_by_kind"].items():
        print(f"- {key}: {value}")
    return 0


def count_by(items: dict[str, dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items.values():
        key = str(item.get(field, "") or "(unset)")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def count_by_voices(agents: dict[str, dict[str, Any]]) -> dict[str, int]:
    """Count how many agents bind each model identity in their voices.

    Each agent's `voices` is a keyed inline table mapping leg name to model
    identity; an agent contributes one increment per distinct model it binds.
    Totals exceed `len(agents)` when each agent declares multiple legs.
    """
    counts: dict[str, int] = {}
    for agent in agents.values():
        voices = agent.get("voices") or {}
        if not isinstance(voices, dict):
            continue
        for model_id in voices.values():
            key = str(model_id) if model_id else "(unset)"
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def count_by_kinds(agents: dict[str, dict[str, Any]]) -> dict[str, int]:
    """Count how many agents declare each kind."""
    counts: dict[str, int] = {}
    for agent in agents.values():
        kinds = agent.get("kinds") or []
        if not isinstance(kinds, list):
            continue
        for kind in kinds:
            key = str(kind) if kind else "(unset)"
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts/atelier.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Discover Atelier command specs and generate Codex prompts.",
        epilog=textwrap.dedent(
            """\
            Examples:
              python3 scripts/atelier.py status
              python3 scripts/atelier.py commands
              python3 scripts/atelier.py commands --category session --json
              python3 scripts/atelier.py intent "review my goals"
              python3 scripts/atelier.py intent "https://arxiv.org/abs/2501.12345"
              python3 scripts/atelier.py intent "5/4 早上去了 X" --json
              python3 scripts/atelier.py intent-log --input "improve the repo" \\
                --match-kind fallback --runtime claude-code \\
                --initial-name reflection --initial-priority 0 \\
                --initial-pattern "<fallback>" --final-dispatch "engineering-task"
              python3 scripts/atelier.py intent-misses --since 2026-05-01
              python3 scripts/atelier.py prompt hi -- "I had a tough day"
              python3 scripts/atelier.py run hi "I had a tough day"
              python3 scripts/atelier.py run lint --exec
              python3 scripts/atelier.py source lint --path-only
              python3 scripts/atelier.py agents
              python3 scripts/atelier.py agent-prompt researcher -- "find notes about agency"
            """
        ),
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    commands = sub.add_parser("commands", help="List portable command specs.")
    commands.add_argument("--category", help="Filter by command category.")
    commands.add_argument("--json", action="store_true", help="Emit JSON.")
    commands.set_defaults(func=cmd_commands)

    agents = sub.add_parser("agents", help="List portable agent role specs.")
    agents.add_argument(
        "--member",
        help="Filter to agents whose voices include this model identity (e.g., opus, deepseek_pro_max).",
    )
    agents.add_argument(
        "--kind",
        choices=("system", "app"),
        help="Filter to agents whose kinds include this value.",
    )
    agents.add_argument("--json", action="store_true", help="Emit JSON.")
    agents.set_defaults(func=cmd_agents)

    status = sub.add_parser("status", help="Summarize the portable harness registries.")
    status.add_argument("--json", action="store_true", help="Emit JSON.")
    status.set_defaults(func=cmd_status)

    intent = sub.add_parser(
        "intent",
        help="Match text against the /hi intent router and report the winning intent + dispatch shape.",
        description=(
            "Codex-side parity for `/hi <text>`. Reads harness/intents.toml, runs the "
            "same substring+priority matcher hi.md describes, and reports the matched "
            "intent (or AMBIGUOUS when multiple priority-tied intents match)."
        ),
    )
    intent.add_argument("text", nargs="+", help="User text to match against intent patterns.")
    intent.add_argument("--json", action="store_true", help="Emit JSON.")
    intent.set_defaults(func=cmd_intent)

    intent_log = sub.add_parser(
        "intent-log",
        help="Record an unclassified /hi invocation for batch coverage review.",
        description=(
            "Append one JSONL line to $OV/_meta/intent_misses/YYYY-MM-DD.jsonl "
            "(falls back to ~/.cache/atelier/intent_misses/ when $OV is unset). "
            "Call from the orchestrator after a /hi invocation that fell back, "
            "was ambiguous, or was clarified due to low confidence. "
            "See protocols/intent-coverage.md."
        ),
    )
    intent_log.add_argument("--input", required=True, help="Raw /hi <text> the user typed.")
    intent_log.add_argument(
        "--match-kind", required=True, choices=INTENT_MISS_KINDS,
        help="Why this counted as a miss.",
    )
    intent_log.add_argument(
        "--runtime", default="claude-code", choices=INTENT_MISS_RUNTIMES,
        help="Which orchestrator runtime logged the miss.",
    )
    intent_log.add_argument("--initial-name", default=None, help="Name of the initial matched intent (e.g., 'reflection' for fallback).")
    intent_log.add_argument("--initial-priority", default=None, help="Priority of the initial match.")
    intent_log.add_argument("--initial-pattern", default=None, help="Pattern that matched (or '<fallback>' for the fallback case).")
    intent_log.add_argument(
        "--candidates", default=None,
        help=(
            "For ambiguous: JSON array of {name, priority, matched_pattern}. "
            "Key name matches `intent --json` output verbatim — pass the matcher's "
            "objects straight through without renaming."
        ),
    )
    intent_log.add_argument("--clarified-to", default=None, help="Intent name the user picked from the clarification menu.")
    intent_log.add_argument("--final-dispatch", default=None, help="What was actually dispatched (intent name, or free-text label like 'engineering-task').")
    intent_log.add_argument("--notes", default=None, help="Free-text orchestrator note about why this was a miss.")
    intent_log.add_argument("--quiet", action="store_true", help="Don't print the appended path on success.")
    intent_log.set_defaults(func=cmd_intent_log)

    intent_misses = sub.add_parser(
        "intent-misses",
        help="Aggregate the intent-miss log for batch coverage review.",
        description=(
            "Print counts by match_kind and the top distinct phrases from the "
            "intent-miss log. Phrases recurring across 3+ distinct days are "
            "flagged as candidate triggers for harness/intents.toml."
        ),
    )
    intent_misses.add_argument(
        "--since",
        help=(
            "YYYY-MM-DD; only include events from this date forward. "
            "Filter applies at FILE-DATE granularity (the log file's filename "
            "date), not at event-timestamp granularity — a TZ-skewed event "
            "near midnight is grouped with its file's date."
        ),
    )
    intent_misses.add_argument(
        "--match-kind", choices=INTENT_MISS_KINDS,
        help="Filter to one match_kind (vocabulary matches intent-log --match-kind).",
    )
    intent_misses.add_argument("--runtime", choices=INTENT_MISS_RUNTIMES, help="Filter to one runtime.")
    intent_misses.add_argument("--top", type=int, default=20, help="Top-N distinct phrases to display (default 20).")
    intent_misses.add_argument("--json", action="store_true", help="Emit JSON.")
    intent_misses.set_defaults(func=cmd_intent_misses)

    intent_hook = sub.add_parser(
        "intent-hook",
        help="UserPromptSubmit hook entry — out-of-band intent-miss capture (silent).",
        description=(
            "Wire as a Claude Code UserPromptSubmit hook command. Reads the "
            "hook's stdin JSON, detects /hi <text>, runs the deterministic "
            "matcher, and auto-logs fallback/ambiguous to "
            "$OV/_meta/intent_misses/YYYY-MM-DD.jsonl. Silent on success — no "
            "stdout — so the orchestrator's context stays clean. "
            "Best-effort: every failure returns 0."
        ),
    )
    intent_hook.add_argument(
        "--runtime", default="claude-code", choices=INTENT_MISS_RUNTIMES,
        help="Which orchestrator runtime is firing this hook.",
    )
    intent_hook.set_defaults(func=cmd_intent_hook)

    prompt = sub.add_parser("prompt", help="Print a Codex-ready prompt for a command.")
    prompt.add_argument("command", help="Command name, without leading slash.")
    prompt.add_argument("arguments", nargs=argparse.REMAINDER, help="Optional command arguments or context.")
    prompt.set_defaults(func=cmd_prompt)

    agent_prompt = sub.add_parser("agent-prompt", help="Print a Codex-ready prompt for an agent role.")
    agent_prompt.add_argument("agent", help="Agent name.")
    agent_prompt.add_argument("arguments", nargs=argparse.REMAINDER, help="Optional role task or context.")
    agent_prompt.set_defaults(func=cmd_agent_prompt)

    source = sub.add_parser("source", help="Print the source command spec.")
    source.add_argument("command", help="Command name, without leading slash.")
    source.add_argument("--path-only", action="store_true", help="Print only the source path.")
    source.set_defaults(func=cmd_source)

    agent_source = sub.add_parser("agent-source", help="Print the source agent role spec.")
    agent_source.add_argument("agent", help="Agent name.")
    agent_source.add_argument("--path-only", action="store_true", help="Print only the source path.")
    agent_source.set_defaults(func=cmd_agent_source)

    run = sub.add_parser("run", help="Launch Codex with the generated workflow prompt.")
    run.add_argument("command", help="Command name, without leading slash.")
    run.add_argument("context", nargs="?", default="", help="Optional context string.")
    run.add_argument("--exec", action="store_true", help="Use `codex exec` (non-interactive) instead of the interactive TUI.")
    run.add_argument("--print", action="store_true", help="Print the prompt without invoking Codex.")
    session = run.add_mutually_exclusive_group()
    session.add_argument("--resume", action="store_true", help="Continue the most recent Codex session (`codex resume --last`). Carries prior session context; warns when not resume_friendly.")
    session.add_argument("--fork", action="store_true", help="Fork the most recent Codex session (`codex fork --last`). Branches from prior context without mutating the original session.")
    run.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
