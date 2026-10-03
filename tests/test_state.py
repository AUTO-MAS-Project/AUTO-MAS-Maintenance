import json
import subprocess
from pathlib import Path

import pytest

from automas_api import state

POLICY = {
    "schema_version": 1,
    "generated_at": "2026-10-03T10:00:00+08:00",
    "games": {"arknights": {"maintenance": None}, "endfield": {"maintenance": None}},
}


def run(directory, *args):
    return subprocess.check_output(["git", "-C", str(directory), *args], text=True).strip()


@pytest.fixture
def repository(tmp_path, monkeypatch):
    remote = tmp_path / "remote.git"
    checkout = tmp_path / "checkout"
    run(tmp_path, "init", "--bare", str(remote))
    run(tmp_path, "init", "--initial-branch=main", str(checkout))
    run(checkout, "config", "user.name", "Test")
    run(checkout, "config", "user.email", "test@example.com")
    run(checkout, "remote", "add", "origin", str(remote))
    monkeypatch.chdir(checkout)
    Path("api/v1").mkdir(parents=True)
    Path("config").mkdir()
    Path("api/v1/maintain.json").write_text(json.dumps(POLICY))
    Path("config/overrides.json").write_text('{"schema_version": 1, "games": {}}')
    Path("code.py").write_text("# Code stays on main\n")
    run(checkout, "add", ".")
    run(checkout, "commit", "-m", "seed")
    run(checkout, "push", "origin", "main")
    return checkout, remote


def test_save_only_data_branch_and_restore_opening_record(repository):
    checkout, remote = repository
    main = run(remote, "rev-parse", "main")
    index = run(checkout, "write-tree")
    state.load()
    opening = {"schema_version": 1, "games": {"arknights": {"opened_at": POLICY["generated_at"]}}}
    Path("config/overrides.json").write_text(json.dumps(opening))
    state.save()
    first = run(remote, "rev-parse", "data")
    assert run(remote, "rev-parse", "main") == main
    assert run(checkout, "branch", "--show-current") == "main"
    assert run(checkout, "write-tree") == index
    assert set(run(remote, "ls-tree", "-r", "--name-only", "data").splitlines()) == set(
        state.DOCUMENTS
    )
    assert run(remote, "rev-list", "--count", "data") == "1"
    Path("config/overrides.json").write_text('{"schema_version": 1, "games": {}}')
    state.load(require_existing=True)
    assert json.loads(Path("config/overrides.json").read_text()) == opening
    state.save()
    assert run(remote, "rev-parse", "data") == first
    policy = {**POLICY, "generated_at": "2026-10-03T11:00:00+08:00"}
    Path("api/v1/maintain.json").write_text(json.dumps(policy))
    state.save()
    assert run(remote, "rev-parse", "data^") == first
    assert run(remote, "rev-parse", "main") == main


def test_sync_requires_existing_state(repository):
    with pytest.raises(ValueError, match="data branch is missing"):
        state.load(require_existing=True)


def test_concurrent_edit_is_not_overwritten(repository):
    checkout, remote = repository
    state.load()
    state.save()
    state.load()
    parent = state.PARENT.read_text()
    Path("api/v1/maintain.json").write_text(
        json.dumps({**POLICY, "generated_at": "2026-10-03T11:00:00+08:00"})
    )
    state.save()
    newer = run(remote, "rev-parse", "data")
    state.PARENT.write_text(parent)
    Path("api/v1/maintain.json").write_text(
        json.dumps({**POLICY, "generated_at": "2026-10-03T12:00:00+08:00"})
    )
    with pytest.raises(subprocess.CalledProcessError):
        state.save()
    assert run(remote, "rev-parse", "data") == newer
    assert run(checkout, "branch", "--show-current") == "main"
