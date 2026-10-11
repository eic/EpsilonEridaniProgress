#!/usr/bin/env python3
"""Check this repository's calls of the EpsilonEridaniProgress reusable workflows.

Dependabot bumps the `uses: eic/EpsilonEridaniProgress/.github/workflows/<file>@<sha>` lines and
nothing else. Two things can then go wrong, and neither shows on the bump's own pull request: the
callers run from the base branch (`pull_request_target`, `workflow_run`, `push`), so a broken call
only fails after the bump is merged.

1. `progress_ref` must name the same commit as `uses:`. It is therefore never written down: each
   caller reads it from its own `uses:` line at run time (.github/actions/progress-pin). This
   check refuses a literal SHA in `progress_ref`, and requires every EpsilonEridaniProgress pin in
   the repository to be the same commit (the two workflows are bumped together, one Dependabot
   group).
2. The call must fit the called workflow's interface at the pinned commit: every `with:` key and
   every secret passed must be one it declares, and every input or secret it requires (with no
   default) must be passed. A renamed input (`app_id` -> `client_id`, 53ca020 -> 781fc26) fails
   here, on the pull request, instead of on main.

Usage:
    check_progress_pins.py [--root DIR] [--called DIR]

`--called DIR` reads the called workflows from DIR/<sha>/<file> instead of fetching them from
raw.githubusercontent.com (for tests). Exits 0 when every call checks out, 1 otherwise. Needs
PyYAML.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
import urllib.request

import yaml

REPO = "eic/EpsilonEridaniProgress"
USES = re.compile(r"^eic/EpsilonEridaniProgress/(\.github/workflows/[^@\s]+)@([0-9a-f]{40})$")
SHA = re.compile(r"[0-9a-f]{40}")


def load(text: str) -> dict:
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError("not a mapping")
    return data


def on_block(workflow: dict) -> dict:
    # PyYAML reads the bare key `on` as the boolean True.
    on = workflow.get("on", workflow.get(True)) or {}
    return on if isinstance(on, dict) else {}


def interface(called: dict) -> tuple[dict, dict]:
    """The `workflow_call` inputs and secrets a called workflow declares."""
    call = on_block(called).get("workflow_call") or {}
    return call.get("inputs") or {}, call.get("secrets") or {}


def required(declared: dict) -> set[str]:
    return {name for name, spec in declared.items()
            if isinstance(spec, dict) and spec.get("required") and "default" not in spec}


def calls(root: pathlib.Path):
    """(caller file, job name, called path, pinned sha, job) for every EpsilonEridaniProgress call."""
    for path in sorted((root / ".github" / "workflows").glob("*.y*ml")):
        jobs = load(path.read_text()).get("jobs") or {}
        for name, job in jobs.items():
            uses = (job or {}).get("uses", "")
            if not isinstance(uses, str) or not uses.startswith(f"{REPO}/"):
                continue
            m = USES.match(uses)
            if not m:
                yield path.name, name, uses, None, job
            else:
                yield path.name, name, m.group(1), m.group(2), job


def fetch(sha: str, path: str, called_dir: pathlib.Path | None) -> str:
    if called_dir is not None:
        return (called_dir / sha / pathlib.Path(path).name).read_text()
    url = f"https://raw.githubusercontent.com/{REPO}/{sha}/{path}"
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read().decode()


def problems(root: pathlib.Path, called_dir: pathlib.Path | None = None) -> list[str]:
    out, pins = [], set()
    found = list(calls(root))
    if not found:
        return [f"no calls of {REPO} reusable workflows found"]
    for caller, job, path, sha, spec in found:
        where = f"{caller} job `{job}`"
        if sha is None:
            out.append(f"{where}: `uses: {path}` is not pinned to a full 40-hex commit SHA")
            continue
        pins.add(sha)
        given = spec.get("with") or {}
        ref = given.get("progress_ref")
        if ref is not None and SHA.search(str(ref)):
            out.append(f"{where}: `progress_ref` is written as a literal SHA; read it from the "
                       f"`uses:` pin (.github/actions/progress-pin) instead")
        elif ref is not None and "needs." not in str(ref):
            out.append(f"{where}: `progress_ref` ({ref!r}) is not derived from the `uses:` pin")
        try:
            inputs, secrets = interface(load(fetch(sha, path, called_dir)))
        except Exception as exc:  # unreadable upstream: fail closed with the reason
            out.append(f"{where}: cannot read {path}@{sha[:7]}: {type(exc).__name__}: {exc}")
            continue
        for key in sorted(set(given) - set(inputs)):
            out.append(f"{where}: input `{key}` is not defined by {path}@{sha[:7]}")
        for key in sorted(required(inputs) - set(given)):
            out.append(f"{where}: required input `{key}` of {path}@{sha[:7]} is not passed")
        passed = spec.get("secrets") or {}
        if passed != "inherit":
            for key in sorted(set(passed) - set(secrets)):
                out.append(f"{where}: secret `{key}` is not defined by {path}@{sha[:7]}")
            for key in sorted(required(secrets) - set(passed)):
                out.append(f"{where}: required secret `{key}` of {path}@{sha[:7]} is not passed")
    if len(pins) > 1:
        out.append(f"{REPO} is pinned to {len(pins)} different commits "
                   f"({', '.join(sorted(p[:7] for p in pins))}); bump all callers together")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", type=pathlib.Path, default=pathlib.Path(__file__).resolve().parents[2])
    ap.add_argument("--called", type=pathlib.Path)
    args = ap.parse_args(argv)
    found = problems(args.root, args.called)
    for p in found:
        print(f"::error::{p}")
    if not found:
        print(f"{REPO} calls check out")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
