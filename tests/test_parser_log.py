from __future__ import annotations

import io
import xml.etree.ElementTree as ET

import pytest

from pysvnlite.models import LogEntryEnd, LogEntryStart, LogPathChangeEvent
from pysvnlite.parser_log import iter_log_xml_events, parse_log_xml


VERBOSE_LOG_XML = """<?xml version="1.0" encoding="UTF-8"?>
<log>
  <logentry revision="12">
    <author>artist</author>
    <date>2026-08-20T01:02:03.000000Z</date>
    <paths>
      <path action="A" copyfrom-path="/old.ma" copyfrom-rev="11">/new.ma</path>
      <path action="M">/scene.fbx</path>
    </paths>
    <msg>资产更新</msg>
  </logentry>
  <logentry revision="11"><msg /></logentry>
</log>
""".encode("utf-8")


def test_iter_log_xml_events_preserves_path_order_and_metadata() -> None:
    events = list(iter_log_xml_events(io.BytesIO(VERBOSE_LOG_XML)))

    assert isinstance(events[0], LogEntryStart)
    assert events[0].revision == 12
    assert isinstance(events[1], LogPathChangeEvent)
    assert events[1].change.action == "A"
    assert events[1].change.path == "/new.ma"
    assert events[1].change.copy_from_path == "/old.ma"
    assert events[1].change.copy_from_rev == 11
    assert isinstance(events[2], LogPathChangeEvent)
    assert events[2].change.path == "/scene.fbx"
    assert isinstance(events[3], LogEntryEnd)
    assert events[3].revision == 12
    assert events[3].author == "artist"
    assert events[3].message == "资产更新"
    assert events[3].changed_paths_count == 2
    assert events[4] == LogEntryStart(revision=11)
    assert events[5] == LogEntryEnd(
        revision=11,
        author=None,
        date=None,
        message="",
        changed_paths_count=0,
    )


def test_parse_log_xml_keeps_existing_log_entry_shape() -> None:
    entries = parse_log_xml(VERBOSE_LOG_XML.decode("utf-8"))

    assert [entry.revision for entry in entries] == [12, 11]
    assert entries[0].message == "资产更新"
    assert [change.path for change in entries[0].changed_paths] == [
        "/new.ma",
        "/scene.fbx",
    ]
    assert entries[1].message == ""
    assert entries[1].changed_paths == []


def test_iter_log_xml_events_removes_completed_nodes_before_yield(monkeypatch) -> None:
    root = ET.Element("log")
    logentry = ET.SubElement(root, "logentry", revision="3")
    paths = ET.SubElement(logentry, "paths")
    path = ET.SubElement(paths, "path", action="M")
    path.text = "/large.bin"

    def fake_iterparse(source, events):
        assert events == ("start", "end")
        yield "start", root
        yield "start", logentry
        yield "start", paths
        yield "start", path
        yield "end", path
        yield "end", paths
        yield "end", logentry
        yield "end", root

    monkeypatch.setattr("pysvnlite.parser_log.ET.iterparse", fake_iterparse)
    iterator = iter_log_xml_events(io.BytesIO())

    assert next(iterator) == LogEntryStart(revision=3)
    assert isinstance(next(iterator), LogPathChangeEvent)
    assert len(paths) == 0
    assert next(iterator) == LogEntryEnd(
        revision=3,
        author=None,
        date=None,
        message="",
        changed_paths_count=1,
    )
    assert len(root) == 0
    with pytest.raises(StopIteration):
        next(iterator)


def test_iter_log_xml_events_reports_truncated_xml_after_completed_entries() -> None:
    iterator = iter_log_xml_events(io.BytesIO(
        b'<log><logentry revision="1"><msg>ok</msg></logentry><logentry revision="2">',
    ))

    assert next(iterator) == LogEntryStart(revision=1)
    assert next(iterator) == LogEntryEnd(
        revision=1,
        author=None,
        date=None,
        message="ok",
        changed_paths_count=0,
    )
    assert next(iterator) == LogEntryStart(revision=2)
    with pytest.raises(ET.ParseError):
        next(iterator)
