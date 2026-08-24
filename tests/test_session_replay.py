"""Regression tests for private transcript replay capture."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "session_replay.py"
sys.path.insert(0, str(ROOT / "scripts"))
import session_replay  # noqa: E402


class SessionReplayTests(unittest.TestCase):
    def _run_hook(
        self,
        home: Path,
        vault: Path,
        payload: dict[str, object],
        *,
        runtime: str = "codex",
        extra_env: dict[str, str] | None = None,
        enabled: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["OV"] = str(vault)
        env["CODEX_HOME"] = str(home / ".codex")
        env[session_replay.ARCHIVE_ROOT_ENV] = str(vault / "_meta" / "session-replays")
        if enabled:
            env[session_replay.ENABLED_ENV] = "1"
        else:
            env[session_replay.ENABLED_ENV] = "0"
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [sys.executable, str(SCRIPT), "hook", "--runtime", runtime],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )

    @staticmethod
    def _events(vault: Path) -> list[dict[str, object]]:
        files = sorted((vault / "_meta" / "session-replays" / "events").glob("*.jsonl"))
        events: list[dict[str, object]] = []
        for path in files:
            events.extend(json.loads(line) for line in path.read_text().splitlines())
        return events

    def test_prompt_is_immediate_and_stop_archives_trusted_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "home"
            vault = root / "vault"
            source = (
                home
                / ".codex"
                / "sessions"
                / "2099"
                / "01"
                / "01"
                / "rollout-smoke.jsonl"
            )
            source.parent.mkdir(parents=True)
            source_text = '{"timestamp":"2099-01-01T00:00:00Z","type":"event_msg"}\n'
            source.write_text(source_text, encoding="utf-8")

            result = self._run_hook(
                home,
                vault,
                {
                    "prompt": "preserve this exact request",
                    "session_id": "smoke-session",
                    "turn_id": "turn-1",
                    "model": "fixture",
                    "hook_event_name": "UserPromptSubmit",
                    "transcript_path": str(source),
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            replay_root = vault / "_meta" / "session-replays"
            self.assertFalse((replay_root / "transcripts").exists())
            self.assertEqual(
                [event["kind"] for event in self._events(vault)],
                ["user_prompt"],
            )
            prompt_only = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "inspect",
                    "--root",
                    str(replay_root),
                    "--session-id",
                    "smoke-session",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(prompt_only.returncode, 0, prompt_only.stderr)
            self.assertEqual(
                json.loads(prompt_only.stdout)["sessions"][0]["completeness"],
                "prompt_only",
            )

            reconciled = self._run_hook(
                home,
                vault,
                {
                    "session_id": "smoke-session",
                    "turn_id": "turn-1",
                    "model": "fixture",
                    "hook_event_name": "Stop",
                    "transcript_path": str(source),
                },
            )
            self.assertEqual(reconciled.returncode, 0, reconciled.stderr)
            archived = next((replay_root / "transcripts" / "codex").glob("*.jsonl"))
            manifest_path = next((replay_root / "manifests" / "codex").glob("*.json"))
            event_file = next((replay_root / "events").glob("*.jsonl"))
            self.assertEqual(stat.S_IMODE(replay_root.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(event_file.stat().st_mode), 0o600)
            self.assertEqual(archived.read_text(encoding="utf-8"), source_text)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["sha256"], hashlib.sha256(source_text.encode()).hexdigest()
            )
            self.assertEqual(
                [event["kind"] for event in self._events(vault)],
                ["user_prompt", "transcript_snapshot"],
            )
            inspected = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "inspect",
                    "--root",
                    str(replay_root),
                    "--session-id",
                    "smoke-session",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(inspected.returncode, 0, inspected.stderr)
            self.assertEqual(
                json.loads(inspected.stdout)["sessions"][0]["completeness"],
                "current_snapshot",
            )
            manifest.pop("sha256")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            missing_hash = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "inspect",
                    "--root",
                    str(replay_root),
                    "--session-id",
                    "smoke-session",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(missing_hash.returncode, 0, missing_hash.stderr)
            self.assertEqual(
                json.loads(missing_hash.stdout)["sessions"][0]["completeness"],
                "hash_metadata_missing",
            )

    def test_explicit_disable_is_a_noop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "home"
            vault = root / "vault"
            result = self._run_hook(
                home,
                vault,
                {
                    "prompt": "do not retain this",
                    "session_id": "disabled",
                    "hook_event_name": "UserPromptSubmit",
                },
                enabled=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((vault / "_meta" / "session-replays").exists())

    def test_local_preference_enables_capture_and_environment_overrides_it(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            local_config = Path(temp_dir) / "session-replay.local.toml"
            local_config.write_text(
                "[session_replay]\nenabled = true\n", encoding="utf-8"
            )
            with (
                patch.object(session_replay, "LOCAL_CONFIG_PATH", local_config),
                patch.dict(os.environ, {}, clear=True),
            ):
                self.assertEqual(
                    session_replay.replay_activation(), (True, "local-config")
                )
                os.environ[session_replay.ENABLED_ENV] = "0"
                self.assertEqual(
                    session_replay.replay_activation(),
                    (False, f"environment:{session_replay.ENABLED_ENV}"),
                )

    def test_prompt_only_crash_does_not_override_later_transcript_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            events = root / "events"
            events.mkdir()
            events.joinpath("2026-08-08.jsonl").write_text(
                "\n".join(
                    (
                        json.dumps(
                            {
                                "session_id": "recovered",
                                "runtime": "codex",
                                "kind": "user_prompt",
                                "timestamp": "2026-08-08T12:00:00-07:00",
                            }
                        ),
                        json.dumps(
                            {
                                "session_id": "recovered",
                                "runtime": "codex",
                                "kind": "transcript_snapshot",
                                "timestamp": "2026-08-08T12:00:01-07:00",
                            }
                        ),
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            states = session_replay.event_states(root, "recovered")
            self.assertEqual(states["recovered"]["completeness"], "current_snapshot")

    def test_default_archive_root_is_local_even_when_ov_is_set(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "home"
            vault = root / "cloud-synced-vault"
            with patch.dict(
                os.environ,
                {"HOME": str(home), "OV": str(vault)},
                clear=True,
            ):
                self.assertEqual(
                    session_replay.archive_root(),
                    home / ".cache" / "atelier" / "session-replays",
                )

    def test_sensitive_transcript_is_not_copied_and_prompt_is_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "home"
            vault = root / "vault"
            source = home / ".codex" / "sessions" / "rollout-sensitive.jsonl"
            source.parent.mkdir(parents=True)
            source.write_text(
                '{"secret":"sk-proj-abcdefghijklmnopqrstuvwxyz"}\n',
                encoding="utf-8",
            )

            result = self._run_hook(
                home,
                vault,
                {
                    "prompt": "token sk-proj-abcdefghijklmnopqrstuvwxyz",
                    "session_id": "sensitive-session",
                    "transcript_path": str(source),
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            replay_root = vault / "_meta" / "session-replays"
            self.assertFalse(
                list((replay_root / "transcripts" / "codex").glob("*.jsonl"))
            )
            manifest = json.loads(
                next((replay_root / "manifests" / "codex").glob("*.json")).read_text()
            )
            self.assertEqual(manifest["capture_status"], "skipped_sensitive")
            events = self._events(vault)
            self.assertEqual(
                [event["kind"] for event in events],
                ["user_prompt", "transcript_snapshot_skipped_sensitive"],
            )
            self.assertEqual(events[0]["text"], "token <redacted:openai_api_key>")

    def test_fine_grained_github_token_is_not_archived(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "home"
            vault = root / "vault"
            token = "github_pat_" + "A" * 30
            source = home / ".codex" / "sessions" / "rollout-sensitive.jsonl"
            source.parent.mkdir(parents=True)
            source.write_text(json.dumps({"secret": token}) + "\n", encoding="utf-8")

            result = self._run_hook(
                home,
                vault,
                {
                    "prompt": f"token {token}",
                    "session_id": "fine-grained-pat",
                    "transcript_path": str(source),
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            replay_root = vault / "_meta" / "session-replays"
            self.assertFalse(
                list((replay_root / "transcripts" / "codex").glob("*.jsonl"))
            )
            events = self._events(vault)
            self.assertEqual(events[0]["text"], "token <redacted:github_token>")
            self.assertEqual(
                events[-1]["kind"], "transcript_snapshot_skipped_sensitive"
            )

    def test_archives_trusted_project_local_codex_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "home"
            vault = root / "vault"
            workspace = root / "workspace"
            source = workspace / ".codex" / "rollout.jsonl"
            source.parent.mkdir(parents=True)
            source.write_text('{"type":"user"}\n', encoding="utf-8")

            result = self._run_hook(
                home,
                vault,
                {
                    "session_id": "project-local",
                    "transcript_path": str(source),
                    "cwd": str(workspace),
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            archived = list(
                (vault / "_meta" / "session-replays" / "transcripts" / "codex").glob(
                    "*.jsonl"
                )
            )
            self.assertEqual(len(archived), 1)
            self.assertEqual(
                archived[0].read_text(encoding="utf-8"), source.read_text()
            )

    def test_unavailable_transcript_and_custom_claude_root_are_observable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "home"
            vault = root / "vault"
            missing = self._run_hook(
                home,
                vault,
                {"prompt": "keep the prompt", "session_id": "missing-session"},
            )
            self.assertEqual(missing.returncode, 0, missing.stderr)
            events = self._events(vault)
            self.assertEqual(events[-1]["kind"], "transcript_snapshot_unavailable")
            self.assertEqual(events[-1]["reason"], "path_absent")
            unavailable = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "inspect",
                    "--root",
                    str(vault / "_meta" / "session-replays"),
                    "--session-id",
                    "missing-session",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(unavailable.returncode, 0, unavailable.stderr)
            unavailable_session = json.loads(unavailable.stdout)["sessions"][0]
            self.assertEqual(
                unavailable_session["completeness"], "transcript_unavailable"
            )
            self.assertEqual(unavailable_session["reason"], "path_absent")

            claude_root = home / "custom-claude"
            source = claude_root / "projects" / "fixture" / "claude.jsonl"
            source.parent.mkdir(parents=True)
            source.write_text('{"type":"user"}\n', encoding="utf-8")
            captured = self._run_hook(
                home,
                vault,
                {
                    "session_id": "claude-session",
                    "transcript_path": str(source),
                    "hook_event_name": "SessionEnd",
                },
                runtime="claude-code",
                extra_env={"CLAUDE_CONFIG_DIR": str(claude_root)},
            )
            self.assertEqual(captured.returncode, 0, captured.stderr)
            self.assertTrue(
                list(
                    (
                        vault
                        / "_meta"
                        / "session-replays"
                        / "transcripts"
                        / "claude-code"
                    ).glob("*.jsonl")
                )
            )

    def test_session_ids_that_sanitize_the_same_do_not_collide(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "home"
            vault = root / "vault"
            source = home / ".codex" / "sessions" / "shared.jsonl"
            identifiers = (
                "a/b",
                "a-b",
                "x" * 200 + "-one",
                "x" * 200 + "-two",
            )
            for index, identifier in enumerate(identifiers):
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_text(f'{{"name":"{index}"}}\n', encoding="utf-8")
                result = self._run_hook(
                    home,
                    vault,
                    {"session_id": identifier, "transcript_path": str(source)},
                )
                self.assertEqual(result.returncode, 0, result.stderr)
            archived = list(
                (vault / "_meta" / "session-replays" / "transcripts" / "codex").glob(
                    "*.jsonl"
                )
            )
            self.assertEqual(len(archived), len(identifiers))

    def test_inspect_reports_later_capture_gap_and_orphan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "home"
            vault = root / "vault"
            source = home / ".codex" / "sessions" / "degraded.jsonl"
            source.parent.mkdir(parents=True)
            source.write_text('{"event":"captured"}\n', encoding="utf-8")
            captured = self._run_hook(
                home,
                vault,
                {"session_id": "degraded", "transcript_path": str(source)},
            )
            self.assertEqual(captured.returncode, 0, captured.stderr)
            source.unlink()
            unavailable = self._run_hook(
                home,
                vault,
                {"session_id": "degraded", "transcript_path": str(source)},
            )
            self.assertEqual(unavailable.returncode, 0, unavailable.stderr)
            replay_root = vault / "_meta" / "session-replays"
            orphan = replay_root / "transcripts" / "codex" / "orphan.jsonl"
            orphan.write_text('{"event":"orphan"}\n', encoding="utf-8")
            inspected = subprocess.run(
                [sys.executable, str(SCRIPT), "inspect", "--root", str(replay_root)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(inspected.returncode, 0, inspected.stderr)
            sessions = json.loads(inspected.stdout)["sessions"]
            degraded = next(row for row in sessions if row["session_id"] == "degraded")
            self.assertEqual(degraded["completeness"], "transcript_unavailable")
            self.assertEqual(degraded["reason"], "path_missing")
            self.assertTrue(
                any(row["completeness"] == "orphaned_archive" for row in sessions)
            )

    def test_event_precedence_uses_instants_across_dst_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            events = root / "events"
            events.mkdir()
            events.joinpath("2026-11-01.jsonl").write_text(
                "\n".join(
                    (
                        json.dumps(
                            {
                                "session_id": "dst",
                                "kind": "transcript_snapshot",
                                "timestamp": "2026-11-01T01:45:00-07:00",
                            }
                        ),
                        json.dumps(
                            {
                                "session_id": "dst",
                                "kind": "transcript_snapshot_unavailable",
                                "timestamp": "2026-11-01T01:30:00-08:00",
                                "reason": "path_missing",
                            }
                        ),
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(
                session_replay.event_states(root, "dst")["dst"]["completeness"],
                "transcript_unavailable",
            )


if __name__ == "__main__":
    unittest.main()
