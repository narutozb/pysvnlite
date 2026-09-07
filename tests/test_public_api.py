from __future__ import annotations

import pysvnlite
from pysvnlite.exceptions import SVNOutputLimitError
from pysvnlite.models import (
    BlameLine,
    ListEntry,
    LogEntryEnd,
    LogEntryStart,
    LogPathChangeEvent,
)


def test_pysvnlite_exports_return_models() -> None:
    assert pysvnlite.ListEntry is ListEntry
    assert pysvnlite.BlameLine is BlameLine
    assert "ListEntry" in pysvnlite.__all__
    assert "BlameLine" in pysvnlite.__all__


def test_pysvnlite_exports_bounded_log_capability_without_io() -> None:
    assert "bounded_verbose_log_v1" in pysvnlite.CAPABILITIES
    assert pysvnlite.SVNRepo.CAPABILITIES is pysvnlite.CAPABILITIES
    assert pysvnlite.LogEntryStart is LogEntryStart
    assert pysvnlite.LogPathChangeEvent is LogPathChangeEvent
    assert pysvnlite.LogEntryEnd is LogEntryEnd
    assert pysvnlite.SVNOutputLimitError is SVNOutputLimitError
    assert "LogEvent" in pysvnlite.__all__
