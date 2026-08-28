"""The Codex edge must stay a pure function of the registries.

`render_runtime_edges.py --check` reproduces `.codex/agents/*.toml` and the
`.agents/skills/*` pair byte-for-byte; if someone hand-edits an adapter or a
registry without re-rendering, the check (run by the smoke suite through this
test) fails and names the drifted files.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class RenderCheckTest(unittest.TestCase):
    def test_committed_codex_edge_is_render_clean(self) -> None:
        proc = subprocess.run(
            [sys.executable, "scripts/atelier/render_runtime_edges.py", "--runtime", "codex", "--check"],
            cwd=REPO_ROOT, env=os.environ.copy(), capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("byte-for-byte", proc.stdout)

    def test_drifted_adapter_is_detected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="atelier-render-") as tmp:
            root = Path(tmp)
            (root / "harness").mkdir()
            (root / "harness" / "agents.toml").write_text(
                textwrap.dedent(
                    """
                    [agents.sample]
                    source = ".claude/agents/sample.md"
                    voices = { native = "sonnet" }
                    description = "Sample role."
                    """
                ),
                encoding="utf-8",
            )
            (root / "harness" / "commands.toml").write_text(
                textwrap.dedent(
                    """
                    [commands.sample]
                    source = ".claude/commands/sample.md"
                    description = "Sample command."
                    """
                ),
                encoding="utf-8",
            )
            (root / "harness" / "models.toml").write_text(
                '[models.sonnet]\nreasoning_tier = "xdeep"\n', encoding="utf-8"
            )
            (root / ".codex" / "agents").mkdir(parents=True)
            (root / ".codex" / "agents" / "sample.toml").write_text("hand-edited\n", encoding="utf-8")
            snippet = (
                "import sys, json\n"
                "sys.path.insert(0, 'scripts/atelier')\n"
                "import render_runtime_edges as r\n"
                f"r.ROOT = __import__('pathlib').Path({str(root)!r})\n"
                "code = r.main(['--runtime', 'codex', '--check'])\n"
                "print('EXIT', code)\n"
            )
            proc = subprocess.run(
                [sys.executable, "-c", snippet],
                cwd=REPO_ROOT, env=os.environ.copy(), capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("DRIFT", proc.stdout)
            self.assertIn("sample.toml", proc.stdout)
            self.assertIn("SKILL.md (missing)", proc.stdout)
            self.assertIn("EXIT 1", proc.stdout)


if __name__ == "__main__":
    unittest.main()
