from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from pysvnlite import SVNRepo
from pysvnlite import repo as repo_module
from pysvnlite import runner


@pytest.mark.parametrize("hide_window", [False, True])
@pytest.mark.parametrize("kind", ["text", "bytes", "file", "spooled", "result", "bounded_bytes", "bounded_file"])
def test_window_policy_reaches_native_process(monkeypatch, tmp_path, hide_window, kind):
    real_popen = subprocess.Popen
    calls = []
    script = (
        "import ctypes,json,os; "
        "print(json.dumps({'console': ctypes.windll.kernel32.GetConsoleWindow() "
        "if os.name == 'nt' else None}))"
    )

    def launch(cmd, **kwargs):
        calls.append(kwargs)
        return real_popen([sys.executable, "-c", script], **kwargs)

    monkeypatch.setattr(runner.subprocess, "Popen", launch)
    options = {"timeout": 10, "hide_window": hide_window}
    destination = tmp_path / "output.json"
    if kind == "text":
        output = runner.run_svn(["info"], **options)
    elif kind in {"bytes", "bounded_bytes"}:
        output = runner.run_svn_bytes(
            ["cat"], max_output_bytes=1024 if kind == "bounded_bytes" else None, **options,
        )
    elif kind in {"file", "bounded_file"}:
        runner.run_svn_to_file(
            ["cat"], destination,
            max_output_bytes=1024 if kind == "bounded_file" else None, **options,
        )
        output = destination.read_bytes()
    elif kind == "spooled":
        with runner.run_svn_spooled(["log"], **options) as stream:
            output = stream.read()
    else:
        output = repo_module._run_svn_result(["commit"], **options).stdout
    assert len(calls) == 1
    expected_flags = 0
    if os.name == "nt":
        expected_flags = subprocess.CREATE_NEW_PROCESS_GROUP
        if hide_window:
            expected_flags |= subprocess.CREATE_NO_WINDOW
            assert json.loads(output)["console"] == 0
    assert calls[0]["creationflags"] == expected_flags
    assert calls[0]["start_new_session"] == (os.name == "posix")
    assert calls[0]["stdin"] == subprocess.DEVNULL


@pytest.mark.parametrize("hide_window", [False, True])
def test_repo_propagates_window_policy_to_reads_writes_and_scoped_status(monkeypatch, tmp_path, hide_window):
    calls = []

    def text(args, **kwargs):
        calls.append((args, kwargs))
        return {"status": "<status/>", "list": "<lists/>", "blame": "<blame/>"}.get(args[0], "")

    def binary(args, **kwargs):
        calls.append((args, kwargs))
        return b"data"

    def to_file(args, output_path, **kwargs):
        calls.append((args, kwargs))

    @contextmanager
    def spooled(args, **kwargs):
        calls.append((args, kwargs))
        yield io.BytesIO(b"<log/>")

    def captured(args, **kwargs):
        calls.append((args, kwargs))
        return b"Committed revision 1.\n", b""

    monkeypatch.setattr(repo_module, "run_svn", text)
    monkeypatch.setattr(repo_module, "run_svn_bytes", binary)
    monkeypatch.setattr(repo_module, "run_svn_to_file", to_file)
    monkeypatch.setattr(repo_module, "run_svn_spooled", spooled)
    monkeypatch.setattr(repo_module, "_run_captured", captured)
    monkeypatch.setattr(repo_module, "parse_info_xml", lambda output: None)
    destination = tmp_path / "wc"
    (destination / ".svn").mkdir(parents=True)
    repo = SVNRepo.checkout("file:///repository", destination, timeout=7, hide_window=hide_window)
    assert repo.hide_window is hide_window
    assert repo.timeout == 7
    repo.info()
    repo.status()
    repo.list()
    repo.log()
    list(repo.iter_log_events())
    repo.cat("asset")
    repo.cat("asset", max_output_bytes=4)
    repo.cat_to_file("asset", tmp_path / "download")
    repo.cat_to_file("asset", tmp_path / "download", max_output_bytes=4)
    repo.blame("asset")
    repo.diff()
    repo.add(["asset"])
    repo.propset("test:prop", "value", "asset")
    repo.update()
    assert repo.commit(message="test", paths=[Path("asset@")]).success
    assert repo.copy(["file:///repository/a"], "file:///repository/b", message="copy").success
    assert repo.move(["file:///repository/b"], "file:///repository/c", message="move").success
    assert calls
    for _, options in calls:
        assert options["hide_window"] is hide_window
        assert options["timeout"] == 7
    assert any(args == ["status", "--xml", "--depth", "infinity", "--ignore-externals", "asset@"] for args, _ in calls)


@pytest.mark.skipif(os.name != "nt", reason="Windows pythonw host required")
def test_real_svn_from_pythonw_host(tmp_path):
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists() or not shutil.which("svn") or not shutil.which("svnadmin"):
        pytest.skip("pythonw and Subversion CLI tools are required")
    report = tmp_path / "report.json"
    helper = Path(__file__).parent / "fixtures" / "hidden_window_host.py"
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    result = subprocess.run(
        [str(pythonw), str(helper), str(tmp_path), str(report)],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=60, env=env,
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    assert report.exists(), result.stderr
    data = json.loads(report.read_text(encoding="utf-8"))
    assert result.returncode == 0, data
    assert data["host_console"] == 0
    assert data["svn_calls"] >= 15
    assert data["binary_matches"] is True
