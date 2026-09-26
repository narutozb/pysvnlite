from __future__ import annotations

import shutil
import os
import subprocess
from pathlib import Path

import pytest

from pysvnlite import SVNCommandError, SVNOutputLimitError, SVNRepo
from pysvnlite.repo import _parse_commit_revision, _with_peg


@pytest.mark.parametrize(
    "output",
    [
        "Adding         assets/提交/shot_0007.ma\n",
        "Adding         build/revision-notes-v3.txt\n",
        "Sending        Committed revision 42.txt\n",
        "Sending        提交版本12.txt\n",
        "Warning: revision 99 was not committed\n",
        "Adding         revision/3.txt\nRevision 42 ubertragen.\n",
    ],
)
def test_revision_parser_does_not_guess_from_progress(output: str) -> None:
    assert _parse_commit_revision(output) is None


@pytest.mark.parametrize(
    "line",
    ["Committed revision 42.", "提交后的版本为 42。", "已提交版本 42。", "提交版本42"],
)
def test_revision_parser_accepts_complete_known_lines(line: str) -> None:
    assert _parse_commit_revision(f"Adding revision/3.txt\n{line}\n") == 42


@pytest.mark.parametrize("name", ["asset@", "asset@@", "asset@3", "dir@/asset@"])
def test_path_inputs_are_literal_peg_targets(name: str) -> None:
    path = Path(name)
    assert _with_peg(path, None) == f"{path}@"
    assert _with_peg(path, "") == f"{path}@"
    assert _with_peg(path, 3) == f"{path}@3"


@pytest.fixture
def working_copy(tmp_path: Path) -> Path:
    if shutil.which("svn") is None or shutil.which("svnadmin") is None:
        pytest.skip("Subversion CLI tools are not installed")
    source = tmp_path / "source"
    files = {
        "database/wanted/edit.txt": b"original\n",
        "database/wanted/missing.txt": b"remove inside\n",
        "database/other/keep.txt": b"keep outside\n",
        "database/wanted-other/keep.txt": b"prefix sibling\n",
        "asset.txt": b"wrong sibling\n",
        "asset.txt@": b"correct requested file\n",
        "asset.txt@@": b"double at\n",
        "only.txt@": b"only at\n",
        "dir/wrong.txt": b"wrong directory\n",
        "dir@/correct.txt": b"correct directory\n",
        "binary.bin": bytes(range(256)),
        "empty.bin": b"",
    }
    for name, content in files.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    repository = tmp_path / "repository"
    subprocess.run(["svnadmin", "create", str(repository)], check=True, timeout=15)
    _svn("import", str(source), repository.as_uri(), "-m", "fixture")
    wc = tmp_path / "wc"
    _svn("checkout", repository.as_uri(), str(wc))
    return wc


def _svn(*args: str) -> bytes:
    return subprocess.run(
        ["svn", "--non-interactive", *args],
        check=True,
        capture_output=True,
        timeout=15,
    ).stdout


@pytest.mark.parametrize("relative", [False, True])
@pytest.mark.parametrize("subdirectory_repo", [False, True])
def test_scoped_commit_leaves_siblings_unscheduled(
    working_copy: Path,
    monkeypatch,
    relative: bool,
    subdirectory_repo: bool,
) -> None:
    database = working_copy / "database"
    wanted = database / "wanted"
    outside = database / "other"
    (wanted / "edit.txt").write_bytes(b"updated\n")
    (wanted / "missing.txt").unlink()
    (wanted / "new.txt").write_bytes(b"new\n")
    (outside / "keep.txt").unlink()
    (outside / "private.txt").write_bytes(b"synthetic private fixture\n")
    (database / "wanted-other/keep.txt").unlink()
    (outside / "pending.txt").write_bytes(b"pending\n")
    _svn("add", str(outside / "pending.txt"))
    (outside / "pending.txt").unlink()
    monkeypatch.chdir(working_copy)
    target = Path("database/wanted") if relative else wanted
    repo = SVNRepo(database if subdirectory_repo else working_copy, timeout=15)
    before = {
        item.path: item.wc_status
        for item in repo.status()
        if "/wanted/" not in item.path.replace("\\", "/")
    }
    result = repo.commit(
        message="only wanted",
        paths=[target],
        add_unversioned=True,
        auto_delete_missing=True,
    )
    assert result.success, result.stderr
    assert SVNRepo(wanted).status() == []
    assert {item.path: item.wc_status for item in repo.status()} == before
    summary_paths = [path for values in vars(result.pre_summary).values() for path in values]
    assert all(Path(path).resolve().is_relative_to(wanted) for path in summary_paths)
    assert {change.path for change in result.changed_paths} == {
        "/database/wanted/edit.txt",
        "/database/wanted/missing.txt",
        "/database/wanted/new.txt",
    }


def test_multi_file_commit_preserves_unselected_changes(working_copy: Path) -> None:
    database = working_copy / "database"
    modified = database / "wanted/edit.txt"
    new_file = database / "other/new.txt"
    modified.write_bytes(b"updated\n")
    new_file.write_bytes(b"new\n")
    (database / "other/keep.txt").unlink()
    private = database / "wanted/private.txt"
    private.write_bytes(b"unselected\n")
    repo = SVNRepo(working_copy, timeout=15)
    result = repo.commit(
        message="selected files",
        paths=[modified, new_file, new_file],
        add_unversioned=True,
        auto_delete_missing=True,
    )
    assert result.success, result.stderr
    remaining = {Path(item.path).name: item.wc_status for item in repo.status()}
    assert remaining == {"keep.txt": "missing", "private.txt": "unversioned"}
    assert len(result.pre_summary.added) == 1


def test_bounded_cat_preserves_binary_revision_and_destination(
    working_copy: Path, tmp_path: Path
) -> None:
    repo = SVNRepo(working_copy, timeout=15)
    path = working_copy / "binary.bin"
    original = path.read_bytes()
    output = tmp_path / "download.bin"
    path.write_bytes(b"new revision")
    _svn("commit", str(path), "-m", "new binary version")
    assert repo.cat(path, revision=1, peg=1, max_output_bytes=256) == original
    repo.cat_to_file(path, output, revision=1, peg=1, max_output_bytes=256)
    assert output.read_bytes() == original
    for limit in (0, 255):
        with pytest.raises(SVNOutputLimitError):
            repo.cat(path, revision=1, peg=1, max_output_bytes=limit)
        with pytest.raises(SVNOutputLimitError):
            repo.cat_to_file(path, output, revision=1, peg=1, max_output_bytes=limit)
        assert output.read_bytes() == original
        assert not list(tmp_path.glob("*.part"))
    empty = working_copy / "empty.bin"
    assert repo.cat(empty, max_output_bytes=0) == b""
    repo.cat_to_file(empty, output, max_output_bytes=0)
    assert output.read_bytes() == b""


@pytest.mark.parametrize("name", ["asset.txt@", "asset.txt@@", "only.txt@"])
def test_trailing_at_file_reads_literal_path(working_copy: Path, tmp_path: Path, name: str) -> None:
    path = working_copy / name
    expected = path.read_bytes()
    repo = SVNRepo(path, timeout=15)
    assert repo.target == str(path)
    assert repo.info().url.endswith("/" + name)
    assert repo.info(path).url.endswith("/" + name)
    assert repo.cat(path) == expected
    assert repo.cat(str(path), peg="") == expected
    assert repo.cat(path, revision=1, peg=1) == expected
    assert repo.cat(repo.info().url, revision=1, peg=1) == expected
    assert [item.name for item in repo.list()] == [name]
    assert [item.name for item in repo.list(path)] == [name]
    output = tmp_path / "download.txt"
    repo.cat_to_file(path, output)
    assert output.read_bytes() == expected
    path.write_bytes(b"changed requested file\n")
    _svn("commit", str(path) + "@", "-m", "update requested file")
    assert repo.log(limit=1)[0].revision == 2
    assert repo.blame(path)[0].revision == 2
    assert b"+changed requested file" in repo.diff(revision=1, revision_to=2)
    assert b"+changed requested file" in repo.diff(path, revision=1, revision_to=2)


def test_trailing_at_directory_and_legacy_strings(working_copy: Path) -> None:
    path = working_copy / "dir@"
    assert [entry.name for entry in SVNRepo(path).list()] == ["correct.txt"]
    assert [entry.name for entry in SVNRepo(working_copy).list(path)] == ["correct.txt"]
    raw = str(working_copy / "asset.txt@")
    repo = SVNRepo(raw)
    assert repo.cat(raw, peg="") == b"correct requested file\n"
    assert repo.cat(raw) == b"wrong sibling\n"
    assert repo.info().url.endswith("/asset.txt")


@pytest.mark.parametrize("operation", ["commit", "copy", "move"])
def test_unknown_commit_revision_does_not_query_unrelated_history(
    monkeypatch, operation: str
) -> None:
    repo = SVNRepo("file:///repository")
    monkeypatch.setattr(repo, "status", lambda **kwargs: [])
    monkeypatch.setattr(
        repo,
        "_run_result",
        lambda args: subprocess.CompletedProcess(args, 0, "Adding revision/3.txt\n", ""),
    )
    monkeypatch.setattr(
        repo, "changed_files_of_commit", lambda revision: pytest.fail("untrusted revision")
    )
    if operation == "commit":
        result = repo.commit(message="test")
    else:
        result = getattr(repo, operation)(
            ["file:///repository/a"], "file:///repository/b", message="test"
        )
    assert result.success
    assert result.revision is None
    assert result.changed_paths == []


def test_revision_property_write_and_delete(working_copy: Path) -> None:
    repository = working_copy.parent / "repository"
    hook = repository / "hooks" / (
        "pre-revprop-change.bat" if os.name == "nt" else "pre-revprop-change"
    )
    hook.write_text("@exit /b 0\n" if os.name == "nt" else "#!/bin/sh\nexit 0\n")
    hook.chmod(0o755)
    repo = SVNRepo(repository.as_uri(), timeout=15)
    repo.propset("test:revision", "value", repo.target, revprop=True, revision=1)
    assert repo.propget("test:revision", repo.target, revprop=True, revision=1) == "value"
    repo.propdel("test:revision", repo.target, revprop=True, revision="HEAD")
    assert repo.propget("test:revision", repo.target, revprop=True, revision=1) is None


@pytest.mark.parametrize("method", ["propset", "propdel"])
@pytest.mark.parametrize("revprop,revision", [(True, None), (False, 1)])
def test_property_write_rejects_invalid_revision_combination(monkeypatch, method, revprop, revision):
    repo = SVNRepo("file:///test")
    monkeypatch.setattr(repo, "_run", lambda args: pytest.fail("Invalid input must not execute SVN"))
    args = ["test:revision", "value", repo.target] if method == "propset" else ["test:revision", repo.target]
    with pytest.raises(ValueError):
        getattr(repo, method)(*args, revprop=revprop, revision=revision)


@pytest.mark.parametrize("method", ["propset", "propdel"])
@pytest.mark.parametrize("revision", [0, "HEAD", "{2026-09-01T00:00:00Z}"])
def test_revision_property_write_forwards_explicit_revision(monkeypatch, method, revision):
    repo = SVNRepo("file:///repository")
    calls = []
    monkeypatch.setattr(repo, "_run", lambda args: calls.append(args) or "")
    args = ["test:revision", "value", repo.target] if method == "propset" else ["test:revision", repo.target]
    getattr(repo, method)(*args, revprop=True, revision=revision)
    assert calls == [[method, *args, "--revprop", "-r", str(revision)]]


def test_revision_property_write_preserves_native_hook_rejection(working_copy: Path) -> None:
    repository = working_copy.parent / "repository"
    repo = SVNRepo(repository.as_uri(), timeout=15)
    with pytest.raises(SVNCommandError) as error:
        repo.propset("test:revision", "rejected", repo.target, revprop=True, revision=1)
    assert error.value.returncode != 0
    assert repo.propget("test:revision", repo.target, revprop=True, revision=1) is None
    hook = repository / "hooks" / (
        "pre-revprop-change.bat" if os.name == "nt" else "pre-revprop-change"
    )
    assert not hook.exists()
