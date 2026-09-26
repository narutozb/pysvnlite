"""Exercise real SVN from a Windows host with no parent console."""

import ctypes
import json
import subprocess
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from pysvnlite import SVNRepo  # noqa: E402
from pysvnlite import runner  # noqa: E402


def exercise(root: Path) -> dict:
    ctypes.windll.kernel32.GetConsoleWindow.restype = ctypes.c_void_p
    console = ctypes.windll.kernel32.GetConsoleWindow() or 0
    assert console == 0
    flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    repository = root / "repository"
    subprocess.run(
        ["svnadmin", "create", str(repository)], check=True, timeout=15,
        stdin=subprocess.DEVNULL, capture_output=True, creationflags=flags,
    )
    calls = []

    class RecordingSubprocess:
        def __getattr__(self, name):
            return getattr(subprocess, name)

        def Popen(self, command, **kwargs):
            assert kwargs["creationflags"] == flags
            calls.append(command)
            return subprocess.Popen(command, **kwargs)

    runner.subprocess = RecordingSubprocess()
    repo = SVNRepo.checkout(repository.as_uri(), root / "wc", timeout=15, hide_window=True)
    asset = Path(repo.target) / "asset.bin"
    content = bytes(range(256))
    asset.write_bytes(content)
    repo.add([asset])
    repo.propset("test:property", "value", asset)
    assert repo.commit(message="initial asset", paths=[asset]).success
    repo.update()
    assert repo.status() == []
    assert repo.info().url == repository.as_uri()
    assert repo.list()[0].name == asset.name
    assert repo.log()[0].revision == 1
    assert list(repo.iter_log_events())
    assert repo.cat(asset) == content
    assert repo.cat(asset, max_output_bytes=256) == content
    output = root / "download.bin"
    repo.cat_to_file(asset, output)
    assert output.read_bytes() == content
    repo.cat_to_file(asset, output, max_output_bytes=256)
    assert output.read_bytes() == content
    assert repo.copy([asset], Path(repo.target) / "copy.bin") is None
    assert repo.move([Path(repo.target) / "copy.bin"], Path(repo.target) / "moved.bin") is None
    assert repo.commit(message="copy and move").success
    return {"host_console": console, "svn_calls": len(calls), "binary_matches": True}


if __name__ == "__main__":
    try:
        report = exercise(Path(sys.argv[1]))
    except BaseException:
        Path(sys.argv[2]).write_text(json.dumps({"error": traceback.format_exc()}), encoding="utf-8")
        raise SystemExit(1)
    Path(sys.argv[2]).write_text(json.dumps(report), encoding="utf-8")
