from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Iterator, List, Optional, Union
from urllib.parse import unquote, urlsplit

from .exceptions import SVNCommandError, SVNOutputLimitError


_PUMP_CHUNK_BYTES = 64 * 1024
_STDOUT_SPOOL_MEMORY_BYTES = 1024 * 1024
_ERROR_CAPTURE_BYTES = 128 * 1024
_PROCESS_POLL_SECONDS = 0.05
_PROCESS_CLEANUP_SECONDS = 2.0
_PUMP_JOIN_SECONDS = 2.0
_TRUNCATION_MARKER = b"\n... output truncated ...\n"
_ORIGINAL_POPEN = subprocess.Popen


class _BoundedBytesCapture:
    def __init__(self, max_bytes: int) -> None:
        self._head_limit = max_bytes // 2
        self._tail_limit = max_bytes - self._head_limit
        self._head = bytearray()
        self._tail = bytearray()
        self.total_bytes = 0

    def append(self, chunk: bytes) -> None:
        self.total_bytes += len(chunk)
        head_remaining = self._head_limit - len(self._head)
        if head_remaining > 0:
            self._head.extend(chunk[:head_remaining])
            chunk = chunk[head_remaining:]
        if chunk and self._tail_limit > 0:
            self._tail.extend(chunk)
            if len(self._tail) > self._tail_limit:
                del self._tail[: -self._tail_limit]

    def as_bytes(self) -> bytes:
        if self.total_bytes <= self._head_limit:
            return bytes(self._head)
        if self.total_bytes <= self._head_limit + self._tail_limit:
            return bytes(self._head + self._tail)
        return bytes(self._head) + _TRUNCATION_MARKER + bytes(self._tail)

    def as_text(self) -> str:
        return self.as_bytes().decode("utf-8", errors="replace")


class _PumpState:
    def __init__(self) -> None:
        self.output_bytes = 0
        self.output_limit_observed: Optional[int] = None
        self.output_limit_event = threading.Event()
        self.error: Optional[BaseException] = None
        self.error_event = threading.Event()
        self._error_lock = threading.Lock()

    def record_error(self, error: BaseException) -> None:
        with self._error_lock:
            if self.error is None:
                self.error = error
                self.error_event.set()


def _wait_process(
    proc: subprocess.Popen[bytes],
    timeout: float = _PROCESS_CLEANUP_SECONDS,
) -> Optional[int]:
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    except OSError:
        return proc.poll()


def _taskkill_process_tree(pid: int) -> bool:
    creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        helper = _ORIGINAL_POPEN(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
    except OSError:
        return False

    returncode = _wait_process(helper)
    if returncode is None:
        try:
            helper.kill()
        except OSError:
            pass
        _wait_process(helper)
        return False
    return returncode == 0


def _kill_process(proc: subprocess.Popen[bytes]) -> None:
    pid = getattr(proc, "pid", None)
    if isinstance(pid, int):
        if os.name == "posix":
            killpg = getattr(os, "killpg", None)
            sigkill = getattr(signal, "SIGKILL", 9)
            try:
                if callable(killpg):
                    killpg(pid, sigkill)
            except OSError:
                pass
        elif os.name == "nt":
            _taskkill_process_tree(pid)

    try:
        proc.kill()
    except OSError:
        pass


def _kill_and_wait(proc: subprocess.Popen[bytes]) -> None:
    _kill_process(proc)
    _wait_process(proc)


def _join_pump_threads(*threads: threading.Thread) -> bool:
    deadline = time.monotonic() + _PUMP_JOIN_SECONDS
    for thread in threads:
        remaining = max(0.0, deadline - time.monotonic())
        thread.join(timeout=remaining)
    return not any(thread.is_alive() for thread in threads)


def _pump_stdout(
    proc: subprocess.Popen[bytes],
    stream: IO[bytes],
    spool: IO[bytes],
    max_output_bytes: Optional[int],
    state: _PumpState,
) -> None:
    try:
        while True:
            read_size = _PUMP_CHUNK_BYTES
            if max_output_bytes is not None:
                remaining = max_output_bytes - state.output_bytes
                read_size = min(read_size, max(1, remaining + 1))
            chunk = stream.read(read_size)
            if not chunk:
                break

            if max_output_bytes is not None:
                remaining = max_output_bytes - state.output_bytes
                if len(chunk) > remaining:
                    if remaining > 0:
                        spool.write(chunk[:remaining])
                        state.output_bytes += remaining
                    state.output_limit_observed = state.output_bytes + (len(chunk) - remaining)
                    state.output_limit_event.set()
                    _kill_process(proc)
                    break

            spool.write(chunk)
            state.output_bytes += len(chunk)
    except BaseException as error:
        state.record_error(error)
        _kill_process(proc)
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _pump_stderr(
    proc: subprocess.Popen[bytes],
    stream: IO[bytes],
    capture: _BoundedBytesCapture,
    state: _PumpState,
) -> None:
    try:
        while True:
            chunk = stream.read(_PUMP_CHUNK_BYTES)
            if not chunk:
                break
            capture.append(chunk)
    except BaseException as error:
        state.record_error(error)
        _kill_process(proc)
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _read_spool_excerpt(stream: IO[bytes]) -> str:
    try:
        original_position = stream.tell()
        stream.flush()
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(0)
        if size <= _ERROR_CAPTURE_BYTES:
            output = stream.read()
        else:
            head_size = _ERROR_CAPTURE_BYTES // 2
            tail_size = _ERROR_CAPTURE_BYTES - head_size
            head = stream.read(head_size)
            stream.seek(-tail_size, os.SEEK_END)
            output = head + _TRUNCATION_MARKER + stream.read(tail_size)
        stream.seek(original_position)
    except OSError:
        return ""
    return output.decode("utf-8", errors="replace")


def _decode_output(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _timeout_error(
    full_cmd: List[str],
    timeout: Optional[float],
    *,
    stdout: object = None,
    stderr: object = None,
) -> SVNCommandError:
    timeout_text = "unknown" if timeout is None else f"{timeout:g}"
    message = f"SVN command timed out after {timeout_text} seconds."
    stderr_text = _decode_output(stderr)
    if stderr_text:
        message = f"{message}\n{stderr_text}"
    return SVNCommandError(
        cmd=full_cmd,
        returncode=-1,
        stdout=_decode_output(stdout),
        stderr=message,
    )


def _checkout_paths(args: List[str], cwd: Optional[str]) -> List[Path]:
    # Recognize SVN checkout options without treating their values as targets.
    value_options = {
        "-r",
        "--revision",
        "--depth",
        "--username",
        "--password",
        "--config-dir",
        "--config-option",
        "--trust-server-cert-failures",
    }
    flag_options = {
        "-q",
        "--quiet",
        "--force",
        "--ignore-externals",
        "--non-interactive",
        "--no-auth-cache",
        "--trust-server-cert",
    }
    positional: List[str] = []
    iterator = iter(args)
    for arg in iterator:
        if arg == "--":
            positional.extend(iterator)
            break
        if arg in value_options:
            if next(iterator, None) is None:
                return []
        elif arg.split("=", 1)[0] in value_options and "=" in arg:
            continue
        elif arg.startswith("-r") and len(arg) > 2:
            continue
        elif arg in flag_options:
            continue
        elif arg.startswith("-"):
            return []
        else:
            positional.append(arg)
            if len(positional) == 1 and arg not in ("checkout", "co"):
                return []
    if len(positional) < 2:
        return []
    targets = positional[1:]

    def is_url(target: str) -> bool:
        return urlsplit(target).scheme in ("file", "svn", "svn+ssh", "http", "https")

    explicit_dest = not is_url(targets[-1])
    base = Path(cwd) if cwd is not None else Path.cwd()
    if explicit_dest:
        base = base / targets.pop()
    if not targets or not all(is_url(target) for target in targets):
        return []
    if explicit_dest and len(targets) == 1:
        return [base]
    paths: List[Path] = []
    for url in targets:
        path = urlsplit(url).path
        if "@" in path:
            path = path.rsplit("@", 1)[0]
        paths.append(base / unquote(path.rstrip("/").rsplit("/", 1)[-1]))
    return paths


def _verify_checkout_path(path: Path, cmd: List[str], stdout: str) -> None:
    if not (path / ".svn").is_dir():
        raise SVNCommandError(
            cmd,
            -1,
            stdout,
            "SVN reported checkout success but the expected working copy has no .svn "
            f"directory: {path}. The native SVN client may have misdecoded a Unicode "
            "path. Inspect the destination and sibling directories; use an ASCII "
            "working-copy path or a verified Unicode-capable SVN client. "
            "No directories were automatically removed or renamed.",
        )


def run_svn(
    args: List[str],
    cwd: Optional[str] = None,
    timeout: Optional[float] = None,
) -> str:
    """
    运行 svn 子进程并返回 stdout(str)。
    强行加 --non-interactive，避免阻塞在密码输入。
    如果 svn 返回非0则抛 SVNCommandError。
    """

    # 确保我们不会卡在交互认证
    base_cmd = ["svn", "--non-interactive"]
    full_cmd = base_cmd + args

    try:
        proc = subprocess.run(
            full_cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise _timeout_error(
            full_cmd,
            timeout,
            stdout=e.stdout,
            stderr=e.stderr,
        ) from e
    except OSError as e:
        raise SVNCommandError(full_cmd, -1, "", str(e)) from e

    if proc.returncode != 0:
        raise SVNCommandError(
            cmd=full_cmd,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )

    for checkout_path in _checkout_paths(args, cwd):
        _verify_checkout_path(checkout_path, full_cmd, proc.stdout)
    return proc.stdout


def run_svn_bytes(
    args: List[str],
    cwd: Optional[str] = None,
    timeout: Optional[float] = None,
) -> bytes:
    """
    运行 svn 子进程并返回 stdout(bytes)。
    用于 svn cat 等可能返回二进制内容的命令。
    """
    base_cmd = ["svn", "--non-interactive"]
    full_cmd = base_cmd + args

    try:
        proc = subprocess.run(
            full_cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,  # 二进制模式
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise _timeout_error(
            full_cmd,
            timeout,
            stdout=e.stdout,
            stderr=e.stderr,
        ) from e
    except OSError as e:
        raise SVNCommandError(full_cmd, -1, "", str(e)) from e

    if proc.returncode != 0:
        # 即使失败，stderr 也是 bytes，需要 decode 以便阅读
        err_msg = proc.stderr.decode("utf-8", errors="replace")
        out_msg = proc.stdout.decode("utf-8", errors="replace")
        raise SVNCommandError(
            cmd=full_cmd,
            returncode=proc.returncode,
            stdout=out_msg,
            stderr=err_msg,
        )

    return proc.stdout


@contextmanager
def run_svn_spooled(
    args: List[str],
    cwd: Optional[str] = None,
    timeout: Optional[float] = None,
    max_output_bytes: Optional[int] = None,
    spool_dir: Optional[Union[str, Path]] = None,
) -> Iterator[IO[bytes]]:
    """
    运行 svn 并把 stdout 写入内存有界、可自动滚盘的二进制 spool。

    max_output_bytes 按原始 stdout 字节计数。超过上限时立即终止子进程并抛出
    SVNOutputLimitError。stderr 始终由独立线程排空，错误对象只保留有界摘要。
    """
    if max_output_bytes is not None and max_output_bytes < 0:
        raise ValueError("max_output_bytes must be greater than or equal to zero")

    full_cmd = ["svn", "--non-interactive"] + args
    stderr_capture = _BoundedBytesCapture(_ERROR_CAPTURE_BYTES)
    state = _PumpState()
    spool_directory = str(spool_dir) if spool_dir is not None else None

    with tempfile.SpooledTemporaryFile(
        mode="w+b",
        max_size=_STDOUT_SPOOL_MEMORY_BYTES,
        dir=spool_directory,
    ) as stdout_spool:
        try:
            proc = subprocess.Popen(
                full_cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=os.name == "posix",
                creationflags=(
                    int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
                    if os.name == "nt"
                    else 0
                ),
            )
        except OSError as error:
            raise SVNCommandError(full_cmd, -1, "", str(error)) from error

        if proc.stdout is None or proc.stderr is None:
            _kill_and_wait(proc)
            raise SVNCommandError(full_cmd, -1, "", "Failed to capture SVN output pipes.")

        stdout_thread = threading.Thread(
            target=_pump_stdout,
            args=(proc, proc.stdout, stdout_spool, max_output_bytes, state),
            name="pysvnlite-stdout",
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_pump_stderr,
            args=(proc, proc.stderr, stderr_capture, state),
            name="pysvnlite-stderr",
            daemon=True,
        )
        stdout_started = False
        stderr_started = False
        try:
            stdout_thread.start()
            stdout_started = True
            stderr_thread.start()
            stderr_started = True
        except BaseException:
            _kill_and_wait(proc)
            if stdout_started:
                stdout_thread.join(timeout=_PUMP_JOIN_SECONDS)
            else:
                proc.stdout.close()
            if stderr_started:
                stderr_thread.join(timeout=_PUMP_JOIN_SECONDS)
            else:
                proc.stderr.close()
            raise

        deadline = None if timeout is None else time.monotonic() + timeout
        timed_out = False
        try:
            while proc.poll() is None:
                if state.output_limit_event.is_set() or state.error_event.is_set():
                    _kill_and_wait(proc)
                    break

                wait_seconds = _PROCESS_POLL_SECONDS
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        timed_out = True
                        _kill_and_wait(proc)
                        break
                    wait_seconds = min(wait_seconds, remaining)
                try:
                    proc.wait(timeout=wait_seconds)
                except subprocess.TimeoutExpired:
                    continue

            if _wait_process(proc) is None:
                _kill_and_wait(proc)
        except BaseException:
            _kill_and_wait(proc)
            _join_pump_threads(stdout_thread, stderr_thread)
            raise

        if not _join_pump_threads(stdout_thread, stderr_thread):
            _kill_and_wait(proc)
            state.record_error(
                RuntimeError("SVN output pipes did not close within the cleanup deadline.")
            )
        stderr_text = stderr_capture.as_text()
        stdout_excerpt = _read_spool_excerpt(stdout_spool)

        if state.output_limit_event.is_set():
            observed = state.output_limit_observed or state.output_bytes
            message = (
                "SVN command stdout exceeded max_output_bytes="
                f"{max_output_bytes} (observed at least {observed} bytes)."
            )
            if stderr_text:
                message = f"{message}\n{stderr_text}"
            raise SVNOutputLimitError(full_cmd, -1, stdout_excerpt, message)

        if timed_out:
            raise _timeout_error(
                full_cmd,
                timeout,
                stdout=stdout_excerpt,
                stderr=stderr_text,
            )

        if state.error is not None:
            message = f"Failed to capture SVN command output: {state.error}"
            if stderr_text:
                message = f"{message}\n{stderr_text}"
            raise SVNCommandError(full_cmd, -1, stdout_excerpt, message) from state.error

        returncode = proc.returncode if proc.returncode is not None else -1
        if returncode != 0:
            raise SVNCommandError(
                cmd=full_cmd,
                returncode=returncode,
                stdout=stdout_excerpt,
                stderr=stderr_text,
            )

        stdout_spool.seek(0)
        yield stdout_spool


def run_svn_to_file(
    args: List[str],
    output_path: Union[str, Path],
    cwd: Optional[str] = None,
    timeout: Optional[float] = None,
) -> None:
    """
    运行 svn 子进程并把 stdout 直接写入文件。
    用于 svn cat 大文件，避免 Python 进程一次性持有完整 bytes。
    """
    base_cmd = ["svn", "--non-interactive"]
    full_cmd = base_cmd + args

    destination = Path(output_path)
    temp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".part",
            delete=False,
        ) as output_file:
            temp_path = Path(output_file.name)
            try:
                proc = subprocess.Popen(
                    full_cmd,
                    cwd=cwd,
                    stdout=output_file,
                    stderr=subprocess.PIPE,
                )
                try:
                    _, stderr = proc.communicate(timeout=timeout)
                except subprocess.TimeoutExpired as e:
                    try:
                        proc.kill()
                    except OSError:
                        pass
                    final_stderr: Optional[bytes]
                    try:
                        _, final_stderr = proc.communicate()
                    except OSError:
                        final_stderr = e.stderr
                        try:
                            proc.wait()
                        except OSError:
                            pass
                    raise _timeout_error(
                        full_cmd,
                        timeout,
                        stderr=final_stderr or e.stderr,
                    ) from e
                except BaseException:
                    try:
                        proc.kill()
                    except OSError:
                        pass
                    try:
                        proc.wait()
                    except OSError:
                        pass
                    raise
            except OSError as e:
                raise SVNCommandError(full_cmd, -1, "", str(e)) from e

        if proc.returncode != 0:
            err_msg = (stderr or b"").decode("utf-8", errors="replace")
            raise SVNCommandError(
                cmd=full_cmd,
                returncode=proc.returncode,
                stdout="",
                stderr=err_msg,
            )

        os.replace(temp_path, destination)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
