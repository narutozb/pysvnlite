from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from pysvnlite import (
    LogEntryEnd,
    LogEntryStart,
    LogPathChangeEvent,
    SVNCommandError,
    SVNRepo,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(
    shutil.which("svn") is None,
    reason="Subversion CLI tools are not installed",
)
def test_missing_file_repository_is_classified_as_not_found(tmp_path: Path) -> None:
    missing_url = (tmp_path / "missing-repository").as_uri()

    with pytest.raises(SVNCommandError) as exc_info:
        SVNRepo(missing_url, timeout=5).info()

    assert exc_info.value.is_local_repository_not_found
    assert exc_info.value.category == "not_found"


@pytest.mark.skipif(
    shutil.which("svn") is None or shutil.which("svnadmin") is None,
    reason="Subversion CLI tools are not installed",
)
def test_url_mkdir_and_delete_support_commit_messages(tmp_path: Path) -> None:
    repo_path = tmp_path / "mutation-repository"
    subprocess.run(["svnadmin", "create", str(repo_path)], check=True)
    repo_url = repo_path.as_uri()
    nested_url = f"{repo_url}/assets/fbx"
    repo = SVNRepo(repo_url, timeout=10)

    repo.mkdir(
        [nested_url],
        parents=True,
        message="create binary asset directory",
    )
    assert repo.info(nested_url).node_kind == "dir"

    message_file = tmp_path / "delete-message.txt"
    message_file.write_text("delete binary asset directory", encoding="utf-8")
    repo.delete([nested_url], message_file=message_file)

    with pytest.raises(SVNCommandError) as exc_info:
        repo.info(nested_url)
    assert exc_info.value.category == "not_found"
    assert [entry.message for entry in repo.log(limit=2)] == [
        "delete binary asset directory",
        "create binary asset directory",
    ]


@pytest.mark.skipif(
    shutil.which("svn") is None or shutil.which("svnadmin") is None,
    reason="Subversion CLI tools are not installed",
)
def test_history_api_reads_deleted_path_and_verbose_log(tmp_path: Path) -> None:
    repo_path = tmp_path / "history-repository"
    subprocess.run(["svnadmin", "create", str(repo_path)], check=True)
    repo_url = repo_path.as_uri()
    trunk_url = f"{repo_url}/trunk"
    subprocess.run(
        [
            "svn",
            "--non-interactive",
            "mkdir",
            trunk_url,
            "-m",
            "create trunk",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    working_copy = tmp_path / "history-wc"
    subprocess.run(
        ["svn", "--non-interactive", "checkout", trunk_url, str(working_copy)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    asset_path = working_copy / "deleted.txt"
    asset_path.write_bytes(b"historical content\n")
    subprocess.run(
        ["svn", "--non-interactive", "add", str(asset_path)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    subprocess.run(
        [
            "svn",
            "--non-interactive",
            "commit",
            str(working_copy),
            "-m",
            "add historical asset",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    subprocess.run(
        ["svn", "--non-interactive", "delete", str(asset_path)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    subprocess.run(
        [
            "svn",
            "--non-interactive",
            "commit",
            str(working_copy),
            "-m",
            "delete historical asset",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    asset_url = f"{trunk_url}/deleted.txt"
    repo = SVNRepo(repo_url, timeout=10)

    assert repo.cat(asset_url, revision=2, peg=2) == b"historical content\n"
    info = repo.info(asset_url, revision=2, peg=2)
    assert info.node_kind == "file"
    assert info.last_changed_rev == 2
    listing = repo.list(trunk_url, revision=2, peg=2)
    assert [entry.name for entry in listing] == ["deleted.txt"]

    output_path = tmp_path / "restored.txt"
    repo.cat_to_file(asset_url, output_path, revision=2, peg=2)
    assert output_path.read_bytes() == b"historical content\n"

    entries = repo.log(limit=2, revision="3:1", verbose=True)
    assert [entry.revision for entry in entries] == [3, 2]
    assert entries[0].changed_paths[0].action == "D"
    assert entries[0].changed_paths[0].path == "/trunk/deleted.txt"
    assert entries[1].changed_paths[0].action == "A"

    streamed_entries = list(repo.iter_log(limit=2, revision="3:1", verbose=True))
    assert streamed_entries == entries
    events = list(repo.iter_log_events(limit=2, revision="3:1", verbose=True))
    assert [type(event) for event in events] == [
        LogEntryStart,
        LogPathChangeEvent,
        LogEntryEnd,
        LogEntryStart,
        LogPathChangeEvent,
        LogEntryEnd,
    ]

    with pytest.raises(SVNCommandError) as exc_info:
        list(
            repo.iter_log_events(
                limit=2,
                revision="3:1",
                verbose=True,
                max_output_bytes=8,
            )
        )
    assert exc_info.value.category == "output_limit"
    assert repo.log(limit=1)[0].revision == 3


@pytest.mark.skipif(
    shutil.which("svn") is None or shutil.which("svnadmin") is None,
    reason="Subversion CLI tools are not installed",
)
def test_read_api_handles_at_sign_path_and_list_compatibility(tmp_path: Path) -> None:
    repo_path = tmp_path / "at-sign-repository"
    subprocess.run(["svnadmin", "create", str(repo_path)], check=True)
    repo_url = repo_path.as_uri()
    trunk_url = f"{repo_url}/trunk"
    subprocess.run(
        [
            "svn",
            "--non-interactive",
            "mkdir",
            trunk_url,
            "-m",
            "create trunk",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    source_path = tmp_path / "asset@2.ma"
    source_path.write_bytes(b"historical asset\n")
    asset_url = f"{trunk_url}/{source_path.name}"
    subprocess.run(
        [
            "svn",
            "--non-interactive",
            "import",
            str(source_path),
            asset_url,
            "-m",
            "add at-sign asset",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    repo = SVNRepo(asset_url, timeout=10)
    assert repo.cat(asset_url) == b"historical asset\n"
    assert repo.info().node_kind == "file"
    assert repo.log(limit=1)[0].revision == 2
    assert [entry.name for entry in repo.list(ignore_externals=True)] == ["asset@2.ma"]

    output_path = tmp_path / "restored@2.ma"
    repo.cat_to_file(asset_url, output_path)
    assert output_path.read_bytes() == b"historical asset\n"
    assert repo.blame(asset_url)[0].revision == 2
    assert b"historical asset" in repo.diff(
        asset_url,
        revision=1,
        revision_to=2,
    )


@pytest.mark.skipif(
    shutil.which("svn") is None or shutil.which("svnadmin") is None,
    reason="Subversion CLI tools are not installed",
)
def test_commit_blocks_real_tree_conflict_before_svn_commit(tmp_path: Path) -> None:
    repo_path = tmp_path / "tree-conflict-repository"
    subprocess.run(["svnadmin", "create", str(repo_path)], check=True)
    trunk_url = f"{repo_path.as_uri()}/trunk"

    seed = tmp_path / "seed"
    tracked_dir = seed / "dir"
    tracked_dir.mkdir(parents=True)
    (tracked_dir / "file.txt").write_bytes(b"base\n")
    subprocess.run(
        [
            "svn",
            "--non-interactive",
            "import",
            str(seed),
            trunk_url,
            "-m",
            "initial tree",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    first_wc = tmp_path / "first-wc"
    second_wc = tmp_path / "second-wc"
    for working_copy in (first_wc, second_wc):
        subprocess.run(
            [
                "svn",
                "--non-interactive",
                "checkout",
                trunk_url,
                str(working_copy),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    subprocess.run(
        ["svn", "--non-interactive", "delete", str(first_wc / "dir")],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    subprocess.run(
        [
            "svn",
            "--non-interactive",
            "commit",
            str(first_wc),
            "-m",
            "delete tracked tree",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    (second_wc / "dir" / "file.txt").write_bytes(b"local change\n")
    subprocess.run(
        [
            "svn",
            "--non-interactive",
            "update",
            "--accept",
            "postpone",
            str(second_wc),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    repo = SVNRepo(second_wc, timeout=10)
    status = repo.status(depth="infinity")
    tree_conflicts = [item.path for item in status if item.tree_conflicted]
    assert tree_conflicts

    result = repo.commit(message="must be blocked")
    assert result.success is False
    assert result.returncode == 1
    assert result.pre_summary.tree_conflicted == tree_conflicts
    assert "Conflicts exist" in result.stderr
