from __future__ import annotations

import io
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest

from pysvnlite.exceptions import SVNCommandError
from pysvnlite.models import LogEntryEnd, LogEntryStart, LogPathChangeEvent, StatusItem
from pysvnlite.repo import SVNRepo, _with_peg


def test_propget_returns_none_only_for_missing_property(monkeypatch) -> None:
    def missing_property(args, **kwargs):
        raise SVNCommandError(
            ["svn"] + args,
            1,
            "",
            "W200017: Property 'demo:missing' not found on 'svn://repo'",
        )

    monkeypatch.setattr("pysvnlite.repo.run_svn", missing_property)

    assert SVNRepo("svn://repo").propget("demo:missing", "svn://repo") is None


def test_propget_preserves_authentication_error(monkeypatch) -> None:
    def authentication_failure(args, **kwargs):
        raise SVNCommandError(
            ["svn"] + args,
            1,
            "",
            "E215004: authentication failed",
        )

    monkeypatch.setattr("pysvnlite.repo.run_svn", authentication_failure)

    with pytest.raises(SVNCommandError) as exc_info:
        SVNRepo("svn://repo").propget("demo:value", "svn://repo")

    assert exc_info.value.category == "authentication"


def test_repository_copy_wraps_process_start_failure(monkeypatch) -> None:
    def fail_to_start(*args, **kwargs):
        raise FileNotFoundError("svn executable not found")

    monkeypatch.setattr("pysvnlite.repo.run", fail_to_start)

    with pytest.raises(SVNCommandError) as exc_info:
        SVNRepo("svn://repo").copy(
            ["svn://repo/source"],
            "svn://repo/destination",
            message="copy",
        )

    assert exc_info.value.returncode == -1
    assert "svn executable not found" in exc_info.value.stderr


def test_repository_copy_wraps_timeout(monkeypatch) -> None:
    def time_out(*args, **kwargs):
        assert kwargs["timeout"] == 1
        raise subprocess.TimeoutExpired(
            args[0],
            kwargs["timeout"],
            output="partial",
            stderr="connection stalled",
        )

    monkeypatch.setattr("pysvnlite.repo.run", time_out)

    with pytest.raises(SVNCommandError) as exc_info:
        SVNRepo("svn://repo", timeout=1).copy(
            ["svn://repo/source"],
            "svn://repo/destination",
            message="copy",
        )

    assert exc_info.value.category == "timeout"
    assert exc_info.value.stdout == "partial"
    assert "connection stalled" in exc_info.value.stderr


def test_repository_url_mkdir_accepts_message(monkeypatch) -> None:
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return "Committed revision 2."

    monkeypatch.setattr("pysvnlite.repo.run_svn", fake_run)

    SVNRepo("svn://repo", timeout=4).mkdir(
        ["svn://repo/assets/fbx"],
        parents=True,
        message="create asset directory",
    )

    assert calls == [
        (
            [
                "mkdir",
                "--parents",
                "-m",
                "create asset directory",
                "svn://repo/assets/fbx",
            ],
            {"timeout": 4},
        )
    ]


def test_repository_url_delete_accepts_message_file(monkeypatch, tmp_path: Path) -> None:
    calls = []
    message_file = tmp_path / "delete-message.txt"

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return "Committed revision 3."

    monkeypatch.setattr("pysvnlite.repo.run_svn", fake_run)

    SVNRepo("svn://repo").delete(
        ["svn://repo/assets/fbx"],
        force=True,
        message_file=message_file,
    )

    assert calls == [
        (
            [
                "delete",
                "--force",
                "-F",
                str(message_file),
                "svn://repo/assets/fbx",
            ],
            {"timeout": None},
        )
    ]


@pytest.mark.parametrize("method_name", ["mkdir", "delete"])
def test_repository_url_mutation_requires_exactly_one_message(
    monkeypatch,
    method_name: str,
) -> None:
    called = False

    def fake_run(args, **kwargs):
        nonlocal called
        called = True
        return ""

    monkeypatch.setattr("pysvnlite.repo.run_svn", fake_run)
    method = getattr(SVNRepo("svn://repo"), method_name)

    with pytest.raises(ValueError, match="provide exactly one"):
        method(["svn://repo/assets"])
    with pytest.raises(ValueError, match="provide exactly one"):
        method(
            ["svn://repo/assets"],
            message="message",
            message_file="message.txt",
        )

    assert called is False


@pytest.mark.parametrize("method_name", ["mkdir", "delete"])
def test_repository_mutation_rejects_mixed_url_and_working_copy_paths(
    method_name: str,
) -> None:
    method = getattr(SVNRepo("svn://repo"), method_name)

    with pytest.raises(ValueError, match="cannot mix"):
        method(
            ["svn://repo/assets", "local-assets"],
            message="message",
        )


@pytest.mark.parametrize("method_name", ["mkdir", "delete"])
def test_working_copy_mutation_rejects_repository_message(method_name: str) -> None:
    method = getattr(SVNRepo("working-copy"), method_name)

    with pytest.raises(ValueError, match="only valid for repository URL"):
        method(["working-copy/assets"], message="message")


def test_log_supports_history_options_and_timeout(monkeypatch) -> None:
    calls = []

    @contextmanager
    def fake_spooled(args, **kwargs):
        calls.append((args, kwargs))
        yield io.BytesIO(b"<log/>")

    monkeypatch.setattr("pysvnlite.repo.run_svn_spooled", fake_spooled)

    entries = SVNRepo("svn://repo/assets", timeout=2.5).log(
        limit=50,
        revision="100:1",
        peg=120,
        stop_on_copy=True,
        verbose=True,
    )

    assert entries == []
    assert calls == [
        (
            [
                "log",
                "--xml",
                "-r",
                "100:1",
                "--stop-on-copy",
                "-v",
                "-l",
                "50",
                "svn://repo/assets@120",
            ],
            {
                "timeout": 2.5,
                "max_output_bytes": None,
                "spool_dir": None,
            },
        )
    ]


def test_read_operations_support_peg_revision(monkeypatch, tmp_path: Path) -> None:
    text_calls = []
    bytes_calls = []
    file_calls = []

    def fake_text(args, **kwargs):
        text_calls.append((args, kwargs))
        if args[0] == "info":
            return "<info/>"
        if args[0] == "list":
            return "<lists/>"
        return "<blame/>"

    def fake_bytes(args, **kwargs):
        bytes_calls.append((args, kwargs))
        return b"content"

    def fake_to_file(args, output_path, **kwargs):
        file_calls.append((args, output_path, kwargs))

    monkeypatch.setattr("pysvnlite.repo.run_svn", fake_text)
    monkeypatch.setattr("pysvnlite.repo.run_svn_bytes", fake_bytes)
    monkeypatch.setattr("pysvnlite.repo.run_svn_to_file", fake_to_file)
    monkeypatch.setattr("pysvnlite.repo.parse_info_xml", lambda xml: xml)

    target = "svn://repo/assets/deleted.ma"
    repo = SVNRepo("svn://repo", timeout=3)
    output_path = tmp_path / "deleted.ma"

    assert repo.info(target, revision=4, peg=4) == "<info/>"
    assert repo.list(target, revision="4", peg="4") == []
    assert repo.cat(target, revision=4, peg=4) == b"content"
    repo.cat_to_file(target, output_path, revision=4, peg=4)
    assert repo.blame(target, revision="4:1", peg=4) == []
    assert repo.diff(target, revision=4, revision_to=2, peg=4) == b"content"

    assert text_calls == [
        (["info", "--xml", "-r", "4", f"{target}@4"], {"timeout": 3}),
        (["list", "--xml", "-r", "4", f"{target}@4"], {"timeout": 3}),
        (["blame", "--xml", "-r", "4:1", f"{target}@4"], {"timeout": 3}),
    ]
    assert bytes_calls == [
        (["cat", "-r", "4", f"{target}@4"], {"timeout": 3}),
        (["diff", "-r", "4:2", f"{target}@4"], {"timeout": 3}),
    ]
    assert file_calls == [
        (["cat", "-r", "4", f"{target}@4"], output_path, {"timeout": 3})
    ]


@pytest.mark.parametrize(
    ("target", "peg", "expected"),
    [
        ("svn://repo/assets/asset.ma", None, "svn://repo/assets/asset.ma"),
        ("svn://repo/assets/asset@2.ma", None, "svn://repo/assets/asset@2.ma@"),
        (
            Path("working@copy") / "asset.ma",
            None,
            str(Path("working@copy") / "asset.ma") + "@",
        ),
        ("svn://repo/assets/asset@2.ma@", None, "svn://repo/assets/asset@2.ma@"),
        ("svn://repo/assets/asset@2.ma", "HEAD", "svn://repo/assets/asset@2.ma@HEAD"),
        ("svn://repo/assets/asset@", 7, "svn://repo/assets/asset@@7"),
    ],
)
def test_with_peg_disambiguates_at_sign_paths(target, peg, expected) -> None:
    assert _with_peg(target, peg) == expected


def test_read_operations_escape_at_sign_and_list_ignores_externals_option(
    monkeypatch,
    tmp_path: Path,
) -> None:
    text_calls = []
    bytes_calls = []
    file_calls = []

    def fake_text(args, **kwargs):
        text_calls.append(args)
        roots = {
            "info": "<info/>",
            "log": "<log/>",
            "list": "<lists/>",
            "blame": "<blame/>",
        }
        return roots[args[0]]

    def fake_bytes(args, **kwargs):
        bytes_calls.append(args)
        return b"content"

    def fake_to_file(args, output_path, **kwargs):
        file_calls.append((args, output_path))

    @contextmanager
    def fake_spooled(args, **kwargs):
        text_calls.append(args)
        yield io.BytesIO(b"<log/>")

    monkeypatch.setattr("pysvnlite.repo.run_svn", fake_text)
    monkeypatch.setattr("pysvnlite.repo.run_svn_bytes", fake_bytes)
    monkeypatch.setattr("pysvnlite.repo.run_svn_to_file", fake_to_file)
    monkeypatch.setattr("pysvnlite.repo.run_svn_spooled", fake_spooled)
    monkeypatch.setattr("pysvnlite.repo.parse_info_xml", lambda xml: xml)

    target = "svn://repo/assets/asset@2.ma"
    escaped = f"{target}@"
    output_path = tmp_path / "asset@2.ma"
    repo = SVNRepo(target)

    assert repo.info() == "<info/>"
    assert repo.log(limit=1) == []
    assert repo.list(ignore_externals=True) == []
    assert repo.cat(target) == b"content"
    repo.cat_to_file(target, output_path)
    assert repo.blame(target) == []
    assert repo.diff(target) == b"content"

    assert text_calls == [
        ["info", "--xml", escaped],
        ["log", "--xml", "-l", "1", escaped],
        ["list", "--xml", escaped],
        ["blame", "--xml", escaped],
    ]
    assert bytes_calls == [["cat", escaped], ["diff", escaped]]
    assert file_calls == [(["cat", escaped], output_path)]


def test_iter_log_events_exposes_path_stream_and_releases_spool_on_close(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls = []
    closed = False
    xml = b"""<log><logentry revision="7"><paths>
    <path action="A">/asset.ma</path><path action="M">/asset.fbx</path>
    </paths><msg>assets</msg></logentry></log>"""

    @contextmanager
    def fake_spooled(args, **kwargs):
        nonlocal closed
        calls.append((args, kwargs))
        try:
            yield io.BytesIO(xml)
        finally:
            closed = True

    monkeypatch.setattr("pysvnlite.repo.run_svn_spooled", fake_spooled)
    iterator = SVNRepo("svn://repo/assets", timeout=3).iter_log_events(
        limit=None,
        revision="7:7",
        verbose=True,
        max_output_bytes=4096,
        spool_dir=tmp_path,
    )

    assert next(iterator) == LogEntryStart(revision=7)
    first_path = next(iterator)
    assert isinstance(first_path, LogPathChangeEvent)
    assert first_path.change.path == "/asset.ma"
    iterator.close()

    assert closed is True
    assert calls == [
        (
            ["log", "--xml", "-r", "7:7", "-v", "svn://repo/assets"],
            {
                "timeout": 3,
                "max_output_bytes": 4096,
                "spool_dir": tmp_path,
            },
        )
    ]


def test_iter_log_events_emits_end_after_all_paths(monkeypatch) -> None:
    xml = b"""<log><logentry revision="7"><author>a</author><paths>
    <path action="A">/one</path><path action="M">/two</path>
    </paths><msg>done</msg></logentry></log>"""

    @contextmanager
    def fake_spooled(args, **kwargs):
        yield io.BytesIO(xml)

    monkeypatch.setattr("pysvnlite.repo.run_svn_spooled", fake_spooled)
    events = list(SVNRepo("svn://repo").iter_log_events(verbose=True))

    assert [type(event) for event in events] == [
        LogEntryStart,
        LogPathChangeEvent,
        LogPathChangeEvent,
        LogEntryEnd,
    ]
    assert isinstance(events[-1], LogEntryEnd)
    assert events[-1].message == "done"
    assert events[-1].changed_paths_count == 2


@pytest.mark.parametrize(
    ("wc_status", "summary_field"),
    [("added", "added"), ("modified", "modified")],
)
def test_commit_stops_before_svn_for_tree_conflict(
    monkeypatch,
    wc_status: str,
    summary_field: str,
) -> None:
    path = "working-copy/conflicted.txt"
    item = StatusItem(
        path=path,
        wc_status=wc_status,
        repos_status=None,
        locked=False,
        switched=False,
        copied=wc_status == "added",
        tree_conflicted=True,
        revision=1,
        commit_rev=1,
        commit_author="tester",
        commit_date=None,
    )
    repo = SVNRepo("working-copy")
    monkeypatch.setattr(repo, "status", lambda **kwargs: [item])

    def fail_if_called(args):
        pytest.fail("svn commit must not run while a tree conflict exists")

    monkeypatch.setattr(repo, "_run_result", fail_if_called)

    result = repo.commit(message="must be blocked")

    assert result.success is False
    assert result.pre_summary.tree_conflicted == [path]
    assert getattr(result.pre_summary, summary_field) == [path]
    assert "Conflicts exist" in result.stderr


def test_timeout_applies_to_working_copy_operations(monkeypatch) -> None:
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return ""

    monkeypatch.setattr("pysvnlite.repo.run_svn", fake_run)

    repo = SVNRepo("working-copy", timeout=4)
    repo.update()

    assert repo.timeout == 4
    assert calls == [(["update", "working-copy"], {"timeout": 4})]
