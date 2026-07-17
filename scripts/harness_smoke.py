#!/usr/bin/env python3
"""Deterministic smoke tests for native Claude and Codex harness edges.

This avoids the private vault and network. It checks registry-backed Codex
command skills, native adapters, lint, and intent-hook behavior.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

import privacy_check

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


class SmokeFailure(Exception):
    pass


def run(
    args: list[str],
    *,
    input_text: str | None = None,
    env_overrides: dict[str, str] | None = None,
) -> str:
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    result = subprocess.run(
        [PYTHON, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        input=input_text,
        env=env,
    )
    if result.returncode != 0:
        raise SmokeFailure(
            f"`{PYTHON} {' '.join(args)}` failed with exit {result.returncode}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result.stdout


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def check_harness_lint() -> None:
    payload = json.loads(run(["scripts/harness_lint.py", "--json"]))
    counts = payload["counts"]
    expect(counts.get("error", 0) == 0, f"harness_lint.py reports {counts.get('error', 0)} error(s)")
    expect(counts.get("warn", 0) == 0, f"harness_lint.py reports {counts.get('warn', 0)} warn(s)")
    error_or_warn = [f for f in payload["findings"] if f.get("severity") in ("ERROR", "WARN")]
    expect(error_or_warn == [], f"harness_lint.py returned {len(error_or_warn)} error/warn finding(s)")


def check_codex_command_skills() -> None:
    with (ROOT / "harness" / "commands.toml").open("rb") as handle:
        commands = tomllib.load(handle)["commands"]
    expected = {
        name: entry
        for name, entry in commands.items()
        if isinstance(entry, dict) and entry.get("user_facing", True) is not False
    }
    expect(len(expected) >= 10, "expected user-facing portable commands")
    actual = {
        path.parent.name
        for path in (ROOT / ".agents" / "skills").glob("*/SKILL.md")
        if path.parent.name != "atelier"
    }
    expect(actual == set(expected), "native Codex command skills drifted from user-facing registry rows")
    for name, entry in expected.items():
        skill_dir = ROOT / ".agents" / "skills" / name
        skill_path = skill_dir / "SKILL.md"
        metadata_path = skill_dir / "agents" / "openai.yaml"
        expect(skill_path.exists(), f"missing Codex command skill `${name}`")
        expect(metadata_path.exists(), f"missing Codex metadata for `${name}`")
        skill = skill_path.read_text(encoding="utf-8")
        metadata = metadata_path.read_text(encoding="utf-8")
        expect(str(entry["source"]) in skill, f"`${name}` does not point to its command source")
        expect("scripts/atelier.py" not in skill, f"`${name}` still calls the retired bridge")
        expect(f"${name}" in metadata, f"`${name}` metadata lacks its explicit invocation")
        expect(
            "allow_implicit_invocation: false" in metadata,
            f"`${name}` must remain explicit-only",
        )


def check_codex_native_agents() -> None:
    with (ROOT / "harness" / "agents.toml").open("rb") as handle:
        agents = tomllib.load(handle)["agents"]
    with (ROOT / "harness" / "models.toml").open("rb") as handle:
        models = tomllib.load(handle)["models"]
    expected = {
        name for name, entry in agents.items()
        if isinstance(entry, dict) and entry.get("status") != "script-driven"
    }
    actual = {path.stem for path in (ROOT / ".codex" / "agents").glob("*.toml")}
    expect(actual == expected, "native Codex agent adapters drifted from harness/agents.toml")
    effort_by_tier = {"light": "low", "balanced": "medium", "deep": "high"}
    for name in expected:
        with (ROOT / ".codex" / "agents" / f"{name}.toml").open("rb") as handle:
            adapter = tomllib.load(handle)
        native_identity = agents[name]["voices"]["native"]
        reasoning_tier = models[native_identity]["reasoning_tier"]
        expect(
            adapter.get("model_reasoning_effort")
            == effort_by_tier[reasoning_tier],
            f"native Codex agent `{name}` reasoning effort drift",
        )


def check_codex_routine_runner() -> None:
    runner_path = ROOT / "scripts" / "routine_runner.sh"
    runner = runner_path.read_text(encoding="utf-8")
    autoevo = (ROOT / ".claude" / "commands" / "autoevo-nightly.md").read_text(
        encoding="utf-8"
    )
    required_fragments = (
        'python3 "$SCRIPTS_DIR/atelier_runtime.py" resolve',
        'export ATELIER_ACTIVE_RUNTIME="$RUNTIME"',
        "harness/commands.toml",
        "LOCK_CMD=(uv run",
        "codex --ask-for-approval never exec",
        "--ignore-user-config",
        "--sandbox danger-full-access",
        "--dangerously-bypass-hook-trust",
        "--ephemeral",
        'web_search="disabled"',
        "env -i",
    )
    for fragment in required_fragments:
        expect(fragment in runner, f"routine runner missing Codex contract fragment: {fragment}")
    expect(
        runner.index('if [ -n "$RUNTIME_RESOLUTION_ERROR" ]')
        < runner.index('LOCK_RESULT=$("${LOCK_CMD[@]}" acquire'),
        "runtime selection must fail before acquiring the distributed lock",
    )
    expect("claude -p" in runner, "routine runner must retain the supported Claude path")
    expect("$autoevo-nightly" not in runner, "bot-only autoevo must not become a Codex user skill")
    expect(
        'git -C "$OV" commit --only' in autoevo,
        "autoevo audit commits must not absorb a dirty pre-flight index",
    )

    invalid = subprocess.run(
        ["bash", str(runner_path), "../escape", "/autoevo-nightly"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    expect(invalid.returncode == 2, "routine runner must reject unsafe routine names")

    result = subprocess.run(
        ["bash", "-n", str(runner_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    expect(result.returncode == 0, f"routine runner shell syntax failed: {result.stderr}")


def check_runtime_selector() -> None:
    status = json.loads(run(["scripts/atelier_runtime.py", "status", "--json"]))
    expect(status["committed_default"] == "codex", "shipped runtime default must be Codex")
    expect(set(status["available"]) == {"claude", "codex"}, "runtime registry must expose both CLIs")

    codex = run(
        [
            "scripts/atelier_runtime.py",
            "run",
            "--runtime",
            "codex",
            "--dry-run",
            "hi",
            "smoke",
        ]
    ).strip()
    expect("codex -C" in codex and "'$hi smoke'" in codex, "Codex selector command drift")

    claude = run(
        [
            "scripts/atelier_runtime.py",
            "run",
            "--runtime",
            "claude",
            "--non-interactive",
            "--dry-run",
            "lint",
        ]
    ).strip()
    expect(claude == "claude -p /lint", "Claude selector command drift")

    overridden = json.loads(
        run(
            ["scripts/atelier_runtime.py", "resolve", "--json"],
            env_overrides={"ATELIER_RUNTIME": "claude"},
        )
    )
    expect(overridden == {"runtime": "claude", "source": "environment"}, "runtime env override drift")

    codex_native = run(
        ["scripts/shadow.py", "native-model", "--agent", "thinker", "--runtime", "codex"]
    ).strip()
    claude_native = run(
        ["scripts/shadow.py", "native-model", "--agent", "thinker", "--runtime", "claude"]
    ).strip()
    expect(codex_native == "codex_native", "Codex native shadow identity drift")
    expect(claude_native == "opus", "Claude native shadow identity drift")

    neutral_env = os.environ.copy()
    for key in (
        "ATELIER_ACTIVE_RUNTIME",
        "CODEX_THREAD_ID",
        "CLAUDECODE",
        "CLAUDE_PROJECT_DIR",
    ):
        neutral_env.pop(key, None)
    neutral = subprocess.run(
        [PYTHON, "scripts/shadow.py", "native-model", "--agent", "thinker"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=neutral_env,
    )
    expect(neutral.returncode == 0, f"neutral native model lookup failed: {neutral.stderr}")
    expected_neutral = "codex_native" if status["runtime"] == "codex" else "opus"
    expect(
        neutral.stdout.strip() == expected_neutral,
        "native model lookup must honor the selected runtime outside a live session",
    )


def check_runtime_cue_syntax() -> None:
    with tempfile.TemporaryDirectory(prefix="atelier-cue-runtime-") as temp_dir:
        (Path(temp_dir) / "reflections").mkdir()
        codex = json.loads(
            run(
                ["scripts/cues.py", "--only", "weekly", "--json", "--runtime", "codex"],
                env_overrides={"OV": temp_dir},
            )
        )
        claude = json.loads(
            run(
                ["scripts/cues.py", "--only", "weekly", "--json", "--runtime", "claude"],
                env_overrides={"OV": temp_dir},
            )
        )
        expect(len(codex) == 1 and "`$weekly`" in codex[0]["message"], "Codex cue syntax drift")
        expect(len(claude) == 1 and "`/weekly`" in claude[0]["message"], "Claude cue syntax drift")


def check_privacy_scanner() -> None:
    """Catch staged-only leaks and the boundary cases that previously escaped."""
    with tempfile.TemporaryDirectory(prefix="atelier-privacy-") as temp_dir:
        repo = Path(temp_dir)

        def git(*args: str) -> None:
            result = subprocess.run(
                ["git", *args],
                cwd=repo,
                capture_output=True,
                text=True,
            )
            expect(
                result.returncode == 0,
                f"privacy fixture git {' '.join(args)} failed: {result.stderr}",
            )

        git("init", "-q")
        (repo / "README.md").write_text("public fixture\n", encoding="utf-8")
        git("add", "README.md")
        git(
            "-c",
            "user.name=Atelier Smoke",
            "-c",
            "user.email=smoke@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-q",
            "-m",
            "base",
        )

        candidate = repo / "Private-Example-Person.md"
        candidate.write_text("PRIVATE EXAMPLE PERSON\n", encoding="utf-8")
        git("add", candidate.name)
        candidate.write_text("clean working copy\n", encoding="utf-8")

        files = privacy_check.tracked_files(repo)
        expect(candidate.name in files, "newly staged privacy fixture is not public-bound")
        sources = privacy_check.content_sources(files, repo)
        sources.extend(privacy_check.path_sources(files))
        hits = privacy_check.scan(["Private Example Person"], sources)
        expect(
            any(
                hit["file"] == candidate.name and hit["source"] == "index"
                for hit in hits
            ),
            "privacy scanner missed a case-insensitive staged-only leak",
        )
        expect(
            not any(hit["source"] == "worktree" for hit in hits),
            "clean worktree fixture should not report a worktree leak",
        )
        expect(
            any(hit["source"] == "path" for hit in hits),
            "privacy scanner missed a filename-only leak",
        )

    boundary_sources = [
        ("inside.md", "worktree", "a masterpiece"),
        ("exact.md", "worktree", "中文Aster中文"),
    ]
    boundary_hits = privacy_check.scan_slugs({"aster"}, boundary_sources)
    expect(
        len(boundary_hits) == 1 and boundary_hits[0]["file"] == "exact.md",
        "private slug boundary matching drift",
    )
    candidates = privacy_check._wikilink_candidates(
        "people/Example-Person.md#Background"
    )
    expect(
        {"Example-Person", "Example Person"} <= candidates,
        "path-qualified wikilink normalization drift",
    )


def check_codex_intent_hook() -> None:
    with tempfile.TemporaryDirectory(prefix="atelier-codex-hook-") as temp_dir:
        payload = {
            "prompt": "$hi qzxv-codex-hook-smoke",
            "session_id": "smoke-session",
        }
        output = run(
            ["scripts/intent_coverage.py", "intent-hook", "--runtime", "codex"],
            input_text=json.dumps(payload),
            env_overrides={"OV": temp_dir},
        )
        expect(output == "", "intent hook must stay silent")
        logs = list((Path(temp_dir) / "_meta" / "intent_misses").glob("*.jsonl"))
        expect(len(logs) == 1, "Codex $hi skill should create one fallback miss log")
        events = [json.loads(line) for line in logs[0].read_text(encoding="utf-8").splitlines()]
        expect(len(events) == 1, "expected one Codex intent-miss event")
        event = events[0]
        expect(event.get("runtime") == "codex", "Codex hook event runtime drift")
        expect(event.get("raw_input") == "qzxv-codex-hook-smoke", "Codex hook stripped input drift")
        expect(event.get("logged_by") == "user_prompt_submit_hook", "Codex hook provenance drift")

        run(
            ["scripts/intent_coverage.py", "intent-hook", "--runtime", "codex"],
            input_text=json.dumps({"prompt": "$reflect qzxv-codex-skill-smoke"}),
            env_overrides={"OV": temp_dir},
        )
        skill_events = logs[0].read_text(encoding="utf-8").splitlines()
        expect(len(skill_events) == 2, "explicit $reflect entry should be hook-logged")
        skill_event = json.loads(skill_events[-1])
        expect(
            skill_event.get("raw_input") == "qzxv-codex-skill-smoke",
            "explicit $reflect entry stripped input drift",
        )

        run(
            ["scripts/intent_coverage.py", "intent-hook", "--runtime", "codex"],
            input_text=json.dumps({"prompt": "ordinary engineering question"}),
            env_overrides={"OV": temp_dir},
        )
        events_after = logs[0].read_text(encoding="utf-8").splitlines()
        expect(len(events_after) == 2, "ordinary Codex prompts must not be logged as Atelier misses")

        for retired_shape in (
            "hi qzxv-retired-bare-shape",
            "/hi qzxv-codex-slash-shape",
            "$atelier hi qzxv-retired-router-shape",
        ):
            run(
                ["scripts/intent_coverage.py", "intent-hook", "--runtime", "codex"],
                input_text=json.dumps({"prompt": retired_shape}),
                env_overrides={"OV": temp_dir},
            )
        events_after_retired_shapes = logs[0].read_text(encoding="utf-8").splitlines()
        expect(
            len(events_after_retired_shapes) == 2,
            "Codex intent hook must accept only explicit $hi and $reflect entry shapes",
        )


def check_claude_intent_hook() -> None:
    with tempfile.TemporaryDirectory(prefix="atelier-claude-hook-") as temp_dir:
        for prompt in (
            "/hi qzxv-claude-hook-smoke",
            "/reflect qzxv-claude-reflect-smoke",
        ):
            run(
                ["scripts/intent_coverage.py", "intent-hook", "--runtime", "claude-code"],
                input_text=json.dumps({"prompt": prompt}),
                env_overrides={"OV": temp_dir},
            )
        logs = list((Path(temp_dir) / "_meta" / "intent_misses").glob("*.jsonl"))
        expect(len(logs) == 1, "Claude slash commands should create an intent-miss log")
        events = logs[0].read_text(encoding="utf-8").splitlines()
        expect(len(events) == 2, "Claude /hi and /reflect should both be hook-logged")

        run(
            ["scripts/intent_coverage.py", "intent-hook", "--runtime", "claude-code"],
            input_text=json.dumps({"prompt": "$hi qzxv-claude-dollar-shape"}),
            env_overrides={"OV": temp_dir},
        )
        events_after_dollar = logs[0].read_text(encoding="utf-8").splitlines()
        expect(
            len(events_after_dollar) == 2,
            "Claude intent hook must accept slash commands, not Codex $skills",
        )


def main() -> int:
    checks = [
        ("harness lint", check_harness_lint),
        ("Codex command skills", check_codex_command_skills),
        ("Codex native agents", check_codex_native_agents),
        ("runtime selector", check_runtime_selector),
        ("runtime cue syntax", check_runtime_cue_syntax),
        ("privacy scanner", check_privacy_scanner),
        ("Codex routine runner", check_codex_routine_runner),
        ("Codex intent hook", check_codex_intent_hook),
        ("Claude intent hook", check_claude_intent_hook),
    ]
    try:
        for label, check in checks:
            check()
            print(f"ok: {label}")
    except SmokeFailure as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("harness_smoke: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
