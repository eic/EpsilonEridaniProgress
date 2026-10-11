#!/usr/bin/env python3
"""Tests for check_progress_pins.py and .github/actions/progress-pin. No network.

Run with: python3 .github/scripts/test_check_progress_pins.py
"""

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check_progress_pins as cpp  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
OLD, NEW = "a" * 40, "b" * 40

MERGE = textwrap.dedent("""\
    on:
      workflow_call:
        inputs:
          pr: {required: true, type: number}
          progress_ref: {required: true, type: string}
          {app}: {required: true, type: string}
          dry_run: {required: false, default: false, type: boolean}
        secrets:
          APP_PRIVATE_KEY: {required: true}
    jobs: {}
    """)
ANNOUNCE = textwrap.dedent("""\
    on:
      workflow_call:
        inputs:
          progress_ref: {required: true, type: string}
          channel: {required: false, default: EpsilonEridani, type: string}
          topic: {required: false, default: Progress logs, type: string}
        secrets:
          ZULIP_EMAIL: {required: true}
          ZULIP_API_KEY: {required: true}
          ZULIP_SITE: {required: false}
    jobs: {}
    """)


class Check(unittest.TestCase):
    """The repository's own callers, against called workflows written into a temporary directory."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.root = self.tmp / "repo"
        shutil.copytree(ROOT / ".github", self.root / ".github")
        self.called = self.tmp / "called"
        self.sha = self.pin("progress-merge.yml")
        self.write_called(self.sha, app="client_id")

    def pin(self, workflow):
        text = (self.root / ".github" / "workflows" / workflow).read_text()
        return cpp.USES.match(next(line.split("uses:")[1].strip() for line in text.splitlines()
                                   if "eic/EpsilonEridaniProgress/" in line)).group(2)

    def write_called(self, sha, app):
        d = self.called / sha
        d.mkdir(parents=True, exist_ok=True)
        (d / "merge.yml").write_text(MERGE.replace("{app}", app))
        (d / "announce.yml").write_text(ANNOUNCE)

    def edit(self, workflow, old, new):
        path = self.root / ".github" / "workflows" / workflow
        text = path.read_text()
        self.assertIn(old, text)
        path.write_text(text.replace(old, new))

    def problems(self):
        return cpp.problems(self.root, self.called)

    def test_the_repository_checks_out(self):
        self.assertEqual(self.problems(), [])

    def test_a_renamed_input_fails(self):
        # 53ca020 -> 781fc26: merge.yml renamed app_id to client_id; the caller still passed app_id
        self.write_called(self.sha, app="client_id")
        self.edit("progress-merge.yml", "      client_id: ${{", "      app_id: ${{")
        found = self.problems()
        self.assertTrue(any("input `app_id` is not defined" in p for p in found), found)
        self.assertTrue(any("required input `client_id`" in p for p in found), found)

    def test_a_literal_progress_ref_fails(self):
        self.edit("progress-announce.yml", "progress_ref: ${{ needs.pin.outputs.sha }}",
                  f"progress_ref: {self.sha}")
        self.assertTrue(any("literal SHA" in p for p in self.problems()))

    def test_callers_on_different_commits_fail(self):
        self.edit("progress-announce.yml", f"announce.yml@{self.sha}", f"announce.yml@{NEW}")
        self.write_called(NEW, app="client_id")
        self.assertTrue(any("2 different commits" in p for p in self.problems()))

    def test_an_unknown_secret_and_a_missing_required_secret_fail(self):
        self.edit("progress-announce.yml", "ZULIP_EMAIL: ${{", "ZULIP_MAIL: ${{")
        found = self.problems()
        self.assertTrue(any("secret `ZULIP_MAIL` is not defined" in p for p in found), found)
        self.assertTrue(any("required secret `ZULIP_EMAIL`" in p for p in found), found)

    def test_an_unpinned_call_fails(self):
        self.edit("progress-announce.yml", f"announce.yml@{self.sha}", "announce.yml@main")
        self.assertTrue(any("not pinned to a full 40-hex" in p for p in self.problems()))

    def test_an_unreadable_called_workflow_fails_closed(self):
        shutil.rmtree(self.called / self.sha)
        self.assertTrue(any("cannot read" in p for p in self.problems()))


class Action(unittest.TestCase):
    """The pin reader's shell, as the composite action runs it."""

    def run_action(self, workflow_text):
        action = yaml.safe_load((ROOT / ".github/actions/progress-pin/action.yml").read_text())
        script = action["runs"]["steps"][0]["run"]
        with tempfile.TemporaryDirectory() as tmp:
            wf = pathlib.Path(tmp) / ".github" / "workflows"
            wf.mkdir(parents=True)
            (wf / "x.yml").write_text(workflow_text)
            out = pathlib.Path(tmp) / "out"
            out.write_text("")
            env = dict(os.environ, GITHUB_WORKSPACE=tmp, GITHUB_OUTPUT=str(out), WORKFLOW="x.yml")
            proc = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
            return proc.returncode, out.read_text(), proc.stdout + proc.stderr

    def test_every_caller_has_exactly_one_pin(self):
        for name in ("progress-merge.yml", "progress-announce.yml"):
            code, out, _ = self.run_action((ROOT / ".github/workflows" / name).read_text())
            self.assertEqual(code, 0, name)
            self.assertRegex(out, r"^sha=[0-9a-f]{40}\n$")

    def test_no_pin_fails(self):
        code, _, log = self.run_action("jobs: {}\n")
        self.assertNotEqual(code, 0)
        self.assertIn("found: none", log)

    def test_conflicting_pins_fail(self):
        text = (f"jobs:\n  a:\n    uses: eic/EpsilonEridaniProgress/.github/workflows/merge.yml@{OLD}\n"
                f"  b:\n    uses: eic/EpsilonEridaniProgress/.github/workflows/announce.yml@{NEW}\n")
        code, _, log = self.run_action(text)
        self.assertNotEqual(code, 0)
        self.assertIn("expected exactly one", log)


if __name__ == "__main__":
    unittest.main()
