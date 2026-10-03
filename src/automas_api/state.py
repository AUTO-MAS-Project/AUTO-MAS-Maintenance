"""Keep generated policy and opening events on the data branch only."""

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

from .models import validate_status
from .overrides import parse_overrides

BRANCH = "refs/heads/data"
PARENT = Path(".maintenance-state-parent")
DOCUMENTS = {
    "api/v1/maintain.json": validate_status,
    "config/overrides.json": parse_overrides,
}


def git(*args: str, env=None, strip: bool = True) -> str:
    output = subprocess.check_output(["git", *args], text=True, env=env)
    return output.strip() if strip else output


def load(*, require_existing: bool = False) -> None:
    PARENT.unlink(missing_ok=True)
    result = subprocess.run(
        ["git", "ls-remote", "--exit-code", "origin", BRANCH],
        stdout=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode == 2:
        if require_existing:
            raise ValueError("data branch is missing; run the update workflow first")
        return
    result.check_returncode()
    git("fetch", "--depth=1", "origin", BRANCH)
    parent = git("rev-parse", "FETCH_HEAD")
    documents = {}
    for filename, validate in DOCUMENTS.items():
        content = git("show", f"{parent}:{filename}", strip=False)
        validate(json.loads(content))
        documents[filename] = content
    # Validate both files before replacing the checkout's seed documents.
    for filename, content in documents.items():
        Path(filename).write_text(content, encoding="utf-8")
    PARENT.write_text(parent, encoding="ascii")


def save() -> None:
    for filename, validate in DOCUMENTS.items():
        validate(json.loads(Path(filename).read_text(encoding="utf-8")))
    parent = PARENT.read_text(encoding="ascii").strip() if PARENT.exists() else None
    with tempfile.TemporaryDirectory() as directory:
        env = {
            **os.environ,
            "GIT_INDEX_FILE": str(Path(directory) / "index"),
            "GIT_AUTHOR_NAME": "github-actions[bot]",
            "GIT_AUTHOR_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
            "GIT_COMMITTER_NAME": "github-actions[bot]",
            "GIT_COMMITTER_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
        }
        git("read-tree", "--empty", env=env)
        git("add", "--", *DOCUMENTS, env=env)
        tree = git("write-tree", env=env)
        if parent and tree == git("rev-parse", f"{parent}^{{tree}}"):
            return
        parents = ["-p", parent] if parent else []
        commit = git(
            "commit-tree", tree, *parents, "-m", "chore: refresh maintenance policy", env=env
        )
    # Always target data explicitly. Concurrent edits reject this stale result;
    # never force-push or rebase it over a newer opening event.
    git("push", "origin", f"{commit}:{BRANCH}")
    PARENT.write_text(commit, encoding="ascii")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["load", "save"])
    parser.add_argument("--require-existing", action="store_true")
    args = parser.parse_args()
    try:
        if args.operation == "load":
            load(require_existing=args.require_existing)
        else:
            save()
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"State {args.operation} failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
