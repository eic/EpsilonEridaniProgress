#!/usr/bin/env python3
"""The roadmap-workflows/ templates, installed into a scratch EpsilonEridaniRoadmaps layout, must call
THIS commit's reusable workflows correctly.

That is the check that matters at the source: a change to `merge.yml` or `announce.yml`'s inputs or
secrets (the `app_id` -> `client_id` rename of 781fc26, say) fails here, in the pull request that
makes it, instead of in EpsilonEridaniRoadmaps after a Dependabot bump lands. It runs the templates'
own check (roadmap-workflows/scripts/check_progress_pins.py) and its tests in the installed layout.

Needs PyYAML, unlike the other suites. CI installs it and sets REQUIRE_YAML=1; without it locally
the suite says so and exits 0.
"""

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "roadmap-workflows"
SHA = "c" * 40

try:
    import yaml  # noqa: F401
except ImportError:
    if os.environ.get("REQUIRE_YAML"):
        sys.exit("PyYAML is required (REQUIRE_YAML is set) but not installed")
    print("SKIPPED: PyYAML not installed (CI installs it and runs this suite)")
    sys.exit(0)


def install(tmp: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """The templates as README.md says to install them, pinned to SHA; and THIS commit's reusable
    workflows as the called workflows at SHA."""
    repo = tmp / "roadmaps"
    gh = repo / ".github"
    (gh / "workflows").mkdir(parents=True)
    (gh / "scripts").mkdir()
    for name in ("progress-merge.yml", "progress-announce.yml"):
        text = (TEMPLATES / name).read_text()
        assert "REPLACE_WITH_FULL_SHA" in text, name
        (gh / "workflows" / name).write_text(text.replace("REPLACE_WITH_FULL_SHA", SHA))
    shutil.copy(TEMPLATES / "progress-pins.yml", gh / "workflows" / "progress-pins.yml")
    shutil.copytree(TEMPLATES / "actions", gh / "actions")
    for name in ("check_progress_pins.py", "test_check_progress_pins.py"):
        shutil.copy(TEMPLATES / "scripts" / name, gh / "scripts" / name)
    called = tmp / "called" / SHA
    called.mkdir(parents=True)
    for name in ("merge.yml", "announce.yml"):
        shutil.copy(ROOT / ".github" / "workflows" / name, called / name)
    return repo, tmp / "called"


def main() -> int:
    failed = 0
    with tempfile.TemporaryDirectory() as tmp:
        repo, called = install(pathlib.Path(tmp))
        scripts = repo / ".github" / "scripts"
        check = subprocess.run([sys.executable, str(scripts / "check_progress_pins.py"),
                                "--root", str(repo), "--called", str(called)],
                               capture_output=True, text=True)
        print(check.stdout + check.stderr, end="")
        if check.returncode != 0:
            print("FAIL: the templates do not call this commit's merge.yml/announce.yml correctly")
            failed = 1
        tests = subprocess.run([sys.executable, str(scripts / "test_check_progress_pins.py")],
                               capture_output=True, text=True)
        if tests.returncode != 0:
            print(tests.stdout + tests.stderr, end="")
            print("FAIL: the templates' own check tests")
            failed = 1
        else:
            print("template check tests: OK")
    return failed


if __name__ == "__main__":
    sys.exit(main())
