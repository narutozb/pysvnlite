from __future__ import annotations

import io
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from pysvnlite.exceptions import SVNCommandError
from pysvnlite.runner import run_svn, run_svn_bytes, run_svn_spooled, run_svn_to_file


class FakePopen:
    returncode = 0
    calls: list[dict[str, object]] = []
    communicate_timeouts: list[float | None] = []

    def __init__(self, cmd, cwd=None, stdout=None, stderr=None) -> None:
        self.cmd = cmd
        self.cwd = cwd
        self.stdout = stdout
        self.stderr = stderr
        self.__class__.calls.append({
            "cmd": cmd,
            "cwd": cwd,
            "stdout": stdout,
            "stderr": stderr,
        })

    def communicate(self, timeout=None):
        self.__class__.communicate_timeouts.append(timeout)
        self.stdout.write(b"streamed artifact")
        return None, b""


class FailingPopen(FakePopen):
    returncode = 1

    def communicate(self, timeout=None):
        self.__class__.communicate_timeouts.append(timeout)
        return None, b"E160013: path not found"


class InterruptedPopen(FakePopen):
    killed = False
    waited = False

    def communicate(self, timeout=None):
        self.stdout.write(b"partial artifact")
        raise KeyboardInterrupt

    def kill(self) -> None:
        self.__class__.killed = True

    def wait(self) -> int:
        self.__class__.waited = True
        return -9


class TimedOutPopen(FakePopen):
    killed = False
    communicate_calls = 0

    def communicate(self, timeout=None):
        self.__class__.communicate_calls += 1
        if self.__class__.communicate_calls == 1:
            self.stdout.write(b"partial artifact")
            raise subprocess.TimeoutExpired(
                self.cmd,
                timeout,
                stderr=b"connection stalled",
            )
        return None, b"connection stalled"

    def kill(self) -> None:
        self.__class__.killed = True


class SpoolPopen:
    stdout_bytes = b""
    stderr_bytes = b""
    final_returncode = 0
    hang_until_killed = False
    instances: list["SpoolPopen"] = []

    def __init__(self, cmd, cwd=None, stdout=None, stderr=None, **kwargs) -> None:
        self.cmd = cmd
        self.cwd = cwd
        self.stdout = io.BytesIO(self.__class__.stdout_bytes)
        self.stderr = io.BytesIO(self.__class__.stderr_bytes)
        self.returncode = None if self.__class__.hang_until_killed else self.__class__.final_returncode
        self.killed = False
        self.waited = False
        self.__class__.instances.append(self)

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.waited = True
        if self.returncode is not None:
            return self.returncode
        if timeout is not None:
            raise subprocess.TimeoutExpired(self.cmd, timeout)
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class InterruptingSpoolPopen(SpoolPopen):
    hang_until_killed = True

    def wait(self, timeout=None):
        self.waited = True
        if not self.killed:
            raise KeyboardInterrupt
        return self.returncode


def test_run_svn_to_file_streams_stdout_to_file(monkeypatch, tmp_path: Path) -> None:
    FakePopen.calls = []
    FakePopen.communicate_timeouts = []
    output_path = tmp_path / "artifact.whl"

    monkeypatch.setattr("pysvnlite.runner.subprocess.Popen", FakePopen)

    run_svn_to_file(["cat", "svn://repo/demo.whl"], output_path)

    assert output_path.read_bytes() == b"streamed artifact"
    assert FakePopen.calls[0]["cmd"] == [
        "svn",
        "--non-interactive",
        "cat",
        "svn://repo/demo.whl",
    ]
    assert FakePopen.calls[0]["stdout"] is not None
    assert FakePopen.communicate_timeouts == [None]


def test_run_svn_to_file_raises_svn_error(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("pysvnlite.runner.subprocess.Popen", FailingPopen)

    output_path = tmp_path / "missing.whl"
    output_path.write_bytes(b"existing content")

    with pytest.raises(SVNCommandError) as exc_info:
        run_svn_to_file(["cat", "svn://repo/missing.whl"], output_path)

    assert exc_info.value.category == "not_found"
    assert output_path.read_bytes() == b"existing content"


@pytest.mark.parametrize("runner", [run_svn, run_svn_bytes])
def test_run_svn_wraps_process_start_failure(monkeypatch, runner) -> None:
    def fail_to_start(*args, **kwargs):
        raise FileNotFoundError("svn executable not found")

    monkeypatch.setattr("pysvnlite.runner.subprocess.run", fail_to_start)

    with pytest.raises(SVNCommandError) as exc_info:
        runner(["list", "svn://repo"])

    assert exc_info.value.returncode == -1
    assert "svn executable not found" in exc_info.value.stderr


def test_run_svn_to_file_wraps_process_start_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def fail_to_start(*args, **kwargs):
        raise FileNotFoundError("svn executable not found")

    monkeypatch.setattr("pysvnlite.runner.subprocess.Popen", fail_to_start)
    output_path = tmp_path / "artifact.whl"

    with pytest.raises(SVNCommandError) as exc_info:
        run_svn_to_file(["cat", "svn://repo/artifact.whl"], output_path)

    assert exc_info.value.returncode == -1
    assert not output_path.exists()


def test_run_svn_to_file_kills_process_and_preserves_target_on_interrupt(
    monkeypatch,
    tmp_path: Path,
) -> None:
    InterruptedPopen.killed = False
    InterruptedPopen.waited = False
    monkeypatch.setattr("pysvnlite.runner.subprocess.Popen", InterruptedPopen)
    output_path = tmp_path / "artifact.whl"
    output_path.write_bytes(b"existing artifact")

    with pytest.raises(KeyboardInterrupt):
        run_svn_to_file(["cat", "svn://repo/artifact.whl"], output_path)

    assert InterruptedPopen.killed is True
    assert InterruptedPopen.waited is True
    assert output_path.read_bytes() == b"existing artifact"
    assert list(tmp_path.glob(".artifact.whl.*.part")) == []


@pytest.mark.parametrize(
    ("runner", "output", "stderr"),
    [
        (run_svn, "partial", "connection stalled"),
        (run_svn_bytes, b"partial", b"connection stalled"),
    ],
)
def test_run_svn_wraps_timeout(monkeypatch, runner, output, stderr) -> None:
    def time_out(*args, **kwargs):
        assert kwargs["timeout"] == 1.5
        raise subprocess.TimeoutExpired(
            args[0],
            kwargs["timeout"],
            output=output,
            stderr=stderr,
        )

    monkeypatch.setattr("pysvnlite.runner.subprocess.run", time_out)

    with pytest.raises(SVNCommandError) as exc_info:
        runner(["log", "svn://repo"], timeout=1.5)

    assert exc_info.value.category == "timeout"
    assert exc_info.value.returncode == -1
    assert exc_info.value.stdout == "partial"
    assert "1.5 seconds" in exc_info.value.stderr
    assert "connection stalled" in exc_info.value.stderr


def test_run_svn_to_file_kills_process_and_preserves_target_on_timeout(
    monkeypatch,
    tmp_path: Path,
) -> None:
    TimedOutPopen.killed = False
    TimedOutPopen.communicate_calls = 0
    monkeypatch.setattr("pysvnlite.runner.subprocess.Popen", TimedOutPopen)
    output_path = tmp_path / "artifact.whl"
    output_path.write_bytes(b"existing artifact")

    with pytest.raises(SVNCommandError) as exc_info:
        run_svn_to_file(
            ["cat", "svn://repo/artifact.whl"],
            output_path,
            timeout=2,
        )

    assert exc_info.value.category == "timeout"
    assert TimedOutPopen.killed is True
    assert TimedOutPopen.communicate_calls == 2
    assert output_path.read_bytes() == b"existing artifact"
    assert list(tmp_path.glob(".artifact.whl.*.part")) == []


def test_run_svn_spooled_accepts_exact_limit_and_uses_requested_directory(
    monkeypatch,
    tmp_path: Path,
) -> None:
    content = b"<log/>"
    SpoolPopen.stdout_bytes = content
    SpoolPopen.stderr_bytes = b""
    SpoolPopen.final_returncode = 0
    SpoolPopen.hang_until_killed = False
    SpoolPopen.instances = []
    monkeypatch.setattr("pysvnlite.runner.subprocess.Popen", SpoolPopen)

    with run_svn_spooled(
        ["log", "--xml", "svn://repo"],
        max_output_bytes=len(content),
        spool_dir=tmp_path,
    ) as stream:
        assert stream.read() == content

    assert SpoolPopen.instances[0].cmd == [
        "svn",
        "--non-interactive",
        "log",
        "--xml",
        "svn://repo",
    ]


def test_run_svn_spooled_raises_stable_limit_error_and_reaps_process(
    monkeypatch,
) -> None:
    content = b"<log/>"
    SpoolPopen.stdout_bytes = content
    SpoolPopen.stderr_bytes = b"warning"
    SpoolPopen.hang_until_killed = True
    SpoolPopen.instances = []
    monkeypatch.setattr("pysvnlite.runner.subprocess.Popen", SpoolPopen)

    with pytest.raises(SVNCommandError) as exc_info:
        with run_svn_spooled(
            ["log", "--xml", "svn://repo"],
            max_output_bytes=len(content) - 1,
        ):
            pass

    assert exc_info.value.category == "output_limit"
    assert exc_info.value.stdout == content[:-1].decode()
    assert "max_output_bytes=5" in exc_info.value.stderr
    assert "warning" in exc_info.value.stderr
    assert SpoolPopen.instances[0].killed is True
    assert SpoolPopen.instances[0].waited is True


def test_run_svn_spooled_kills_and_waits_on_interrupt(monkeypatch) -> None:
    InterruptingSpoolPopen.stdout_bytes = b""
    InterruptingSpoolPopen.stderr_bytes = b""
    InterruptingSpoolPopen.instances = []
    monkeypatch.setattr("pysvnlite.runner.subprocess.Popen", InterruptingSpoolPopen)

    with pytest.raises(KeyboardInterrupt):
        with run_svn_spooled(["log", "--xml", "svn://repo"]):
            pass

    assert InterruptingSpoolPopen.instances[0].killed is True
    assert InterruptingSpoolPopen.instances[0].waited is True


def test_run_svn_spooled_kills_and_waits_on_timeout(monkeypatch) -> None:
    SpoolPopen.stdout_bytes = b"partial"
    SpoolPopen.stderr_bytes = b"connection stalled"
    SpoolPopen.hang_until_killed = True
    SpoolPopen.instances = []
    monkeypatch.setattr("pysvnlite.runner.subprocess.Popen", SpoolPopen)

    with pytest.raises(SVNCommandError) as exc_info:
        with run_svn_spooled(["log", "svn://repo"], timeout=0.01):
            pass

    assert exc_info.value.category == "timeout"
    assert exc_info.value.stdout == "partial"
    assert "connection stalled" in exc_info.value.stderr
    assert SpoolPopen.instances[0].killed is True
    assert SpoolPopen.instances[0].waited is True


def _process_is_running(pid: int) -> bool:
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        still_active = 259
        handle = ctypes.windll.kernel32.OpenProcess(  # type: ignore[attr-defined]
            process_query_limited_information,
            False,
            pid,
        )
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(  # type: ignore[attr-defined]
                handle,
                ctypes.byref(exit_code),
            ):
                return False
            return exit_code.value == still_active
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]

    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _force_kill_process(pid: int) -> None:
    if os.name == "nt":
        import ctypes

        process_terminate = 0x0001
        handle = ctypes.windll.kernel32.OpenProcess(  # type: ignore[attr-defined]
            process_terminate,
            False,
            pid,
        )
        if handle:
            try:
                ctypes.windll.kernel32.TerminateProcess(handle, 1)  # type: ignore[attr-defined]
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def test_run_svn_spooled_timeout_reaps_grandchild_inheriting_stdio(
    monkeypatch,
    tmp_path: Path,
) -> None:
    real_popen = subprocess.Popen
    grandchild_pid_path = tmp_path / "grandchild.pid"
    grandchild_script = "import time; time.sleep(30)"
    helper_script = (
        "import pathlib,subprocess,sys,time; "
        f"child=subprocess.Popen([sys.executable, '-c', {grandchild_script!r}]); "
        f"pathlib.Path({str(grandchild_pid_path)!r}).write_text(str(child.pid)); "
        "sys.stdout.buffer.write(b'partial'); sys.stdout.buffer.flush(); "
        "time.sleep(30)"
    )

    def launch_helper(cmd, **kwargs):
        return real_popen([sys.executable, "-c", helper_script], **kwargs)

    monkeypatch.setattr("pysvnlite.runner.subprocess.Popen", launch_helper)
    started = time.monotonic()
    grandchild_pid = None
    try:
        with pytest.raises(SVNCommandError) as exc_info:
            with run_svn_spooled(["log"], timeout=0.5):
                pass

        assert exc_info.value.category == "timeout"
        assert time.monotonic() - started < 5
        assert grandchild_pid_path.exists()
        grandchild_pid = int(grandchild_pid_path.read_text())
        deadline = time.monotonic() + 2
        while _process_is_running(grandchild_pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not _process_is_running(grandchild_pid)
    finally:
        if grandchild_pid is not None and _process_is_running(grandchild_pid):
            _force_kill_process(grandchild_pid)


def test_run_svn_spooled_drains_large_stderr_without_deadlock(monkeypatch) -> None:
    real_popen = subprocess.Popen
    stderr_head = "stderr-head-"
    stderr_tail = "-stderr-tail"
    script = (
        "import sys; "
        "sys.stdout.buffer.write(b'x' * 200000); sys.stdout.flush(); "
        f"sys.stderr.write({stderr_head!r} + 'e' * 200000 + {stderr_tail!r}); "
        "sys.stderr.flush(); raise SystemExit(1)"
    )

    def launch_helper(cmd, **kwargs):
        return real_popen([sys.executable, "-c", script], **kwargs)

    monkeypatch.setattr("pysvnlite.runner.subprocess.Popen", launch_helper)

    with pytest.raises(SVNCommandError) as exc_info:
        with run_svn_spooled(["log"], timeout=5):
            pass

    assert exc_info.value.returncode == 1
    assert stderr_head in exc_info.value.stderr
    assert stderr_tail in exc_info.value.stderr
    assert "output truncated" in exc_info.value.stderr
    assert len(exc_info.value.stdout) < 140000
