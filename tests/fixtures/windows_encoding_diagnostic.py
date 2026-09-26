"""Compare native and library outputs in a disposable local SVN repository."""

from __future__ import annotations

import ctypes
import json
import os
import platform
import subprocess
import tempfile
from importlib.metadata import version
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree

import pysvnlite
from pysvnlite import SVNCommandError, SVNRepo
from pysvnlite.runner import run_svn_bytes


def native(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["svn", "--non-interactive", *args],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=20,
    )


def summarize(result: subprocess.CompletedProcess) -> dict:
    data = {"returncode": result.returncode, "stderr_hex": result.stderr.hex()}
    if result.returncode == 0:
        root = ElementTree.fromstring(result.stdout)
        data["paths"] = [entry.get("path") for entry in root.iter("entry")]
    return data


def exercise(root: Path) -> dict:
    root_text = str(root)
    if not root_text.isascii():
        raise ValueError("Use an existing writable ASCII temporary-directory parent.")
    repository = root / "repository"
    source = root / "source"
    source.mkdir()
    filename = "\u8bf4\u660e \u6587\u6863.txt"
    original = "before \u6b63\u6587\n".encode("utf-8")
    changed = "after \u6b63\u6587\n".encode("utf-8")
    (source / filename).write_bytes(original)
    subprocess.run(["svnadmin", "create", str(repository)], check=True, timeout=20)
    imported = native("import", str(source), repository.as_uri(), "-m", "fixture r1")
    imported.check_returncode()
    wc = root / "wc"
    native("checkout", repository.as_uri(), str(wc)).check_returncode()
    if not (wc / filename).is_file():
        return {
            "checkout_names": [path.name for path in wc.iterdir()],
            "expected_file_exists": False,
        }
    (wc / filename).write_bytes(changed)
    directory_args = ["status", "--xml", "--verbose", str(wc)]
    file_args = ["status", "--xml", "--verbose", str(wc / filename)]
    directory_status = native(*directory_args)
    file_status = native(*file_args)
    direct_info = native("info", "--xml", str(wc / filename))
    status_equal = (
        run_svn_bytes(file_args, timeout=20) == file_status.stdout
        if file_status.returncode == 0
        else None
    )
    # This fixture owns the entire working copy; parent commit is not a library fallback.
    native("commit", str(wc), "-m", "fixture r2").check_returncode()
    url = repository.as_uri() + "/" + quote(filename)
    url_info = native("info", "--xml", "-r", "2", url + "@2")
    diff = native("diff", "-r", "1:2", url + "@2")
    library_diff = None
    library_error = None
    try:
        library_diff = SVNRepo(url, timeout=20).diff(revision=1, revision_to=2, peg=2)
    except SVNCommandError as error:
        library_error = {"returncode": error.returncode, "stderr": error.stderr}
    header = next((line for line in diff.stdout.splitlines() if line.startswith(b"Index: ")), b"")
    return {
        "expected_file_exists": True,
        "expected_filename": filename,
        "directory_status": summarize(directory_status),
        "file_status": summarize(file_status),
        "direct_info": summarize(direct_info),
        "url_info": summarize(url_info),
        "status_bytes_equal": status_equal,
        "diff_returncode": diff.returncode,
        "diff_header_hex": header.hex(),
        "diff_header_utf8_filename": filename.encode("utf-8") in header,
        "diff_body_preserved": b"-" + original in diff.stdout and b"+" + changed in diff.stdout,
        "diff_bytes_equal": library_diff == diff.stdout,
        "library_error": library_error,
    }


if __name__ == "__main__":
    environment = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "package": version("pysvnlite"),
        "module": pysvnlite.__file__,
        "svn": native("--version", "--quiet").stdout.decode("ascii").strip(),
    }
    if os.name == "nt":
        environment.update(
            acp=ctypes.windll.kernel32.GetACP(), oem=ctypes.windll.kernel32.GetOEMCP()
        )
    with tempfile.TemporaryDirectory(prefix="pysvn-encoding-") as directory:
        print(
            json.dumps(
                {"environment": environment, "observations": exercise(Path(directory))}, indent=2
            )
        )
