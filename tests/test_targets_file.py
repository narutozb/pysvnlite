from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from pysvnlite import SVNCommandError, SVNProcessStartError, SVNRepo
from pysvnlite import runner
from pysvnlite.models import StatusItem
from pysvnlite.repo import _encode_targets, _run_svn_result
from fixtures.targets_file_workflow import exercise


def status_item(path, state):
    return StatusItem(path, state, None, False, False, False, False, None, None, None, None)


@pytest.mark.parametrize("method", ["add", "delete", "revert", "commit"])
@pytest.mark.parametrize("failure", [False, True])
def test_target_file_content_and_cleanup(monkeypatch, method, failure):
    repo = SVNRepo("wc")
    paths = ["wc/a b", "wc/literal@@", "wc/a b"]
    seen = []

    def run(args):
        path = Path(args[args.index("--targets") + 1])
        assert path.read_bytes() == b"wc/a b\nwc/literal@@\nwc/a b\n"
        assert not any(p in args for p in paths)
        seen.append(path)
        if failure:
            raise SVNCommandError(args, -1, "", "SVN command timed out after 1 seconds.")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(repo, "_run", run)
    monkeypatch.setattr(repo, "_run_result", run)
    monkeypatch.setattr(SVNRepo, "status", lambda *args, **kwargs: [])
    options = {"message": "test"} if method == "commit" else {}
    if failure:
        with pytest.raises(SVNCommandError):
            getattr(repo, method)(paths=paths, targets_encoding="ascii", **options)
    else:
        getattr(repo, method)(paths=paths, targets_encoding="ascii", **options)
    assert len(seen) == 1
    assert not seen[0].parent.exists()


@pytest.mark.parametrize("target", ["", " leading", "trailing ", "a\nb", "a\rb", "a\0b", "a\t"])
@pytest.mark.parametrize("method", ["add", "delete", "revert", "commit"])
def test_unrepresentable_target_rejected_before_svn(monkeypatch, target, method):
    repo = SVNRepo("wc")

    def fail(*args, **kwargs):
        pytest.fail("Invalid target must not execute SVN")

    monkeypatch.setattr(repo, "_run", fail)
    monkeypatch.setattr(repo, "_run_result", fail)
    monkeypatch.setattr(SVNRepo, "status", fail)
    options = {"message": "test"} if method == "commit" else {}
    with pytest.raises(ValueError):
        getattr(repo, method)(paths=[target], targets_encoding="ascii", **options)


def test_explicit_encoding_is_strict_and_never_guessed():
    target = "wc/\u6587\u4ef6.txt"
    assert _encode_targets([target], "utf-8") == (target + "\n").encode("utf-8")
    assert _encode_targets([target], "cp936") == (target + "\n").encode("cp936")
    with pytest.raises(UnicodeEncodeError):
        _encode_targets([target], "ascii")
    for encoding in ("utf-16", "utf-8-sig"):
        with pytest.raises(ValueError):
            _encode_targets(["wc/asset"], encoding)
    with pytest.raises(LookupError):
        _encode_targets([target], "unknown-codec")


def test_commit_preparation_validates_all_encodings_before_mutation(monkeypatch):
    repo = SVNRepo("wc")
    monkeypatch.setattr(
        repo,
        "status",
        lambda **kwargs: [
            status_item("wc/missing", "missing"),
            status_item("wc/\u6587\u4ef6", "unversioned"),
        ],
    )

    def fail(*args, **kwargs):
        pytest.fail("Preparation must be fully validated before mutations")

    for method in ("add", "delete", "revert", "_run_result"):
        monkeypatch.setattr(repo, method, fail)
    with pytest.raises(UnicodeEncodeError):
        repo.commit(
            message="test",
            add_unversioned=True,
            auto_delete_missing=True,
            targets_encoding="ascii",
        )


def test_commit_reverts_missing_add_with_target_file(monkeypatch, tmp_path):
    path = str(tmp_path / "missing")
    repo = SVNRepo("wc")
    statuses = iter([[status_item(path, "added")], []])
    monkeypatch.setattr(repo, "status", lambda **kwargs: next(statuses))
    calls = []

    def run(args):
        target_file = Path(args[args.index("--targets") + 1])
        calls.append((args[0], target_file.read_text(encoding="ascii")))
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(repo, "_run", run)
    monkeypatch.setattr(repo, "_run_result", run)
    result = repo.commit(message="test", auto_delete_missing=True, targets_encoding="ascii")
    assert result.success
    assert calls == [("revert", path + "\n"), ("commit", "wc\n")]


@pytest.mark.parametrize(
    "kind", ["text", "bytes", "file", "spooled", "result", "bounded_bytes", "bounded_file"]
)
def test_process_start_error_preserves_original_os_error(monkeypatch, tmp_path, kind):
    original = OSError(7, "synthetic startup failure")
    original.winerror = 206

    def fail(*args, **kwargs):
        raise original

    monkeypatch.setattr(runner.subprocess, "Popen", fail)
    destination = tmp_path / "download.bin"
    destination.write_bytes(b"existing")
    with pytest.raises(SVNProcessStartError) as caught:
        if kind == "text":
            runner.run_svn(["info"])
        elif kind in {"bytes", "bounded_bytes"}:
            runner.run_svn_bytes(["cat"], max_output_bytes=1 if kind == "bounded_bytes" else None)
        elif kind in {"file", "bounded_file"}:
            runner.run_svn_to_file(
                ["cat"], destination, max_output_bytes=1 if kind == "bounded_file" else None
            )
        elif kind == "spooled":
            with runner.run_svn_spooled(["log"]):
                pass
        else:
            _run_svn_result(["commit"])
    error = caught.value
    assert isinstance(error, SVNCommandError)
    assert error.category == "process_start"
    assert not error.is_timeout_error
    assert error.returncode == -1
    assert error.__cause__ is original
    assert error.errno == 7
    assert error.winerror == 206
    assert destination.read_bytes() == b"existing"
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.skipif(
    not shutil.which("svn") or not shutil.which("svnadmin"), reason="SVN tools required"
)
def test_real_long_targets_preserve_atomic_commit_and_scope(tmp_path):
    report = exercise(tmp_path)
    assert report["final_revision"] == 3
    assert report["unselected_untouched"]
    if os.name == "nt":
        assert report["baseline_winerror"] == 206
