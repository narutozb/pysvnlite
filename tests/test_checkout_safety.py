from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from pysvnlite import SVNCommandError, SVNRepo
from pysvnlite.runner import _checkout_paths, run_svn


@pytest.mark.parametrize(
    "args, expected",
    [
        (["checkout", "file:///repo", "dest"], ["dest"]),
        (["co", "-r1", "file:///repo", "dest", "--depth", "empty"], ["dest"]),
        (["--config-dir", "settings", "co", "file:///repo", "dest"], ["dest"]),
        (["co", "file:///one", "file:///two", "dest"], ["dest/one", "dest/two"]),
        (["co", "file:///one%40two@HEAD"], ["one@two"]),
        (["checkout", "--", "file:///repo", "-dest"], ["-dest"]),
        (["checkout", "--help"], []),
        (["info", "file:///repo"], []),
    ],
)
def test_checkout_paths(tmp_path, args, expected):
    assert _checkout_paths(args, str(tmp_path)) == [tmp_path / p for p in expected]


def test_run_svn_rejects_false_success_without_removing_other_paths(monkeypatch, tmp_path):
    wrong_path = tmp_path / "wrong"
    (wrong_path / ".svn").mkdir(parents=True)
    monkeypatch.setattr(
        "pysvnlite.runner.subprocess.run",
        lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, "Checked out revision 0.", ""),
    )
    with pytest.raises(SVNCommandError, match="expected working copy") as error:
        run_svn(["checkout", "file:///repo", "expected"], cwd=str(tmp_path))
    assert error.value.returncode == -1
    assert error.value.stdout == "Checked out revision 0."
    assert (wrong_path / ".svn").is_dir()


def test_checkout_high_level_verifies_destination(monkeypatch, tmp_path):
    monkeypatch.setattr("pysvnlite.repo.run_svn", lambda *a, **kw: "Checked out revision 0.")
    with pytest.raises(SVNCommandError, match="expected working copy"):
        SVNRepo.checkout("file:///repo", tmp_path / "missing")


@pytest.mark.skipif(
    not shutil.which("svn") or not shutil.which("svnadmin"),
    reason="Subversion CLI tools are not installed",
)
@pytest.mark.parametrize("name", ["ASCII user's path", "\u6d4b\u8bd5 user's path"])
@pytest.mark.parametrize("high_level", [False, True])
def test_real_checkout_returns_exact_path_or_explicit_compatibility_error(
    tmp_path: Path,
    name: str,
    high_level: bool,
) -> None:
    parent = tmp_path / name
    parent.mkdir()
    subprocess.run(
        ["svnadmin", "create", "repo"], cwd=parent, check=True, capture_output=True, timeout=10
    )
    target = parent / "working-copy"
    url = (parent / "repo").as_uri()
    try:
        if high_level:
            SVNRepo.checkout(url, target, timeout=10)
        else:
            run_svn(["checkout", url, str(target)], timeout=10)
    except SVNCommandError as error:
        # Only the reported native-client corruption is an accepted limitation.
        assert os.name == "nt"
        assert not name.isascii()
        assert error.returncode == -1
        assert "expected working copy" in error.stderr
        assert not (target / ".svn").exists()
        assert list(tmp_path.glob("*/working-copy/.svn"))
    else:
        assert (target / ".svn").is_dir()
