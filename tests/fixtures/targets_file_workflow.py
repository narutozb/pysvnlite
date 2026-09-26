"""Installed-package acceptance for long target lists, using only a temporary repo."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from importlib.metadata import version
from pathlib import Path

import pysvnlite
from pysvnlite import SVNCommandError, SVNRepo


def exercise(root: Path) -> dict:
    repository = root / "repository"
    subprocess.run(["svnadmin", "create", str(repository)], check=True, timeout=15)
    repo = SVNRepo.checkout(repository.as_uri(), root / "wc", timeout=30)
    wc = Path(repo.target)
    paths = [wc / (f"{i:03d}-" + "x" * 145 + ".txt") for i in range(220)]
    for path in paths:
        path.write_bytes(b"selected\n")
    sibling = wc / "unselected.txt"
    sibling.write_bytes(b"must not be committed\n")
    command_chars = len(subprocess.list2cmdline(["svn", "add", *map(str, paths)]))
    assert command_chars > 32767
    baseline_winerror = None
    if os.name == "nt":
        try:
            repo.add(paths)
        except SVNCommandError as error:
            baseline_winerror = getattr(error.__cause__, "winerror", None)
            assert baseline_winerror == 206, str(error)
        else:
            raise AssertionError("Expected Windows argv size rejection")

    repo.add(paths, targets_encoding="ascii")
    repo.revert(paths, targets_encoding="ascii")
    assert all(path.exists() for path in paths)
    result = repo.commit(
        message="selected batch",
        paths=paths,
        add_unversioned=True,
        targets_encoding="ascii",
    )
    assert result.success, result.stderr
    remote = SVNRepo(repository.as_uri(), timeout=30)
    assert remote.log(limit=1)[0].revision == 1
    assert len(remote.list()) == len(paths)
    assert all(item.name != sibling.name for item in remote.list())
    assert any(
        Path(item.path) == sibling and item.wc_status == "unversioned" for item in repo.status()
    )

    repo.delete(paths, keep_local=True, targets_encoding="ascii")
    repo.revert(paths, targets_encoding="ascii")
    for path in paths[:2]:
        path.unlink()
    result = repo.commit(
        message="selected missing",
        paths=paths[:2],
        auto_delete_missing=True,
        targets_encoding="ascii",
    )
    assert result.success, result.stderr
    assert remote.log(limit=1)[0].revision == 2
    urls = [repository.as_uri() + "/" + path.name for path in paths[2:]]
    repo.delete(urls, message="one remote deletion", targets_encoding="ascii")
    assert remote.log(limit=1)[0].revision == 3
    assert remote.list() == []
    assert sibling.read_bytes() == b"must not be committed\n"
    return {
        "version": version("pysvnlite"),
        "module": pysvnlite.__file__,
        "targets": len(paths),
        "argv_chars": command_chars,
        "baseline_winerror": baseline_winerror,
        "final_revision": 3,
        "unselected_untouched": True,
    }


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="pysvn13-") as directory:
        print(json.dumps(exercise(Path(directory))))
