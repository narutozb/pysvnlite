from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import IO, Iterator, List, Optional, Union

from .models import (
    LogEntry,
    LogEntryEnd,
    LogEntryStart,
    LogEvent,
    LogPathChange,
    LogPathChangeEvent,
)
from .utils import parse_svn_datetime


LogXMLSource = Union[IO[str], IO[bytes]]


def _drop_finished_element(stack: List[ET.Element], element: ET.Element) -> None:
    if len(stack) >= 2:
        parent = stack[-2]
        try:
            parent.remove(element)
        except ValueError:
            pass
    element.clear()
    stack.pop()


def iter_log_xml_events(xml_source: LogXMLSource) -> Iterator[LogEvent]:
    """Incrementally parse svn log XML into revision and changed-path events."""
    stack: List[ET.Element] = []
    current_revision: Optional[int] = None
    current_author: Optional[str] = None
    current_date: Optional[datetime] = None
    current_message = ""
    changed_paths_count = 0

    for event, element in ET.iterparse(xml_source, events=("start", "end")):
        tag = element.tag
        if event == "start":
            stack.append(element)
            if tag == "logentry":
                revision_text = element.get("revision")
                current_revision = int(revision_text) if revision_text is not None else -1
                current_author = None
                current_date = None
                current_message = ""
                changed_paths_count = 0
                yield LogEntryStart(revision=current_revision)
            continue

        emitted_event: Optional[LogEvent] = None
        if current_revision is not None and tag == "author":
            current_author = element.text if element.text else None
        elif current_revision is not None and tag == "date":
            current_date = parse_svn_datetime(element.text) if element.text else None
        elif current_revision is not None and tag == "msg":
            current_message = element.text or ""
        elif current_revision is not None and tag == "path":
            copy_from_revision = element.get("copyfrom-rev")
            change = LogPathChange(
                action=element.get("action") or "",
                path=element.text or "",
                copy_from_path=element.get("copyfrom-path"),
                copy_from_rev=int(copy_from_revision) if copy_from_revision else None,
            )
            changed_paths_count += 1
            emitted_event = LogPathChangeEvent(
                revision=current_revision,
                change=change,
            )
        elif current_revision is not None and tag == "logentry":
            emitted_event = LogEntryEnd(
                revision=current_revision,
                author=current_author,
                date=current_date,
                message=current_message,
                changed_paths_count=changed_paths_count,
            )
            current_revision = None

        _drop_finished_element(stack, element)
        if emitted_event is not None:
            yield emitted_event


def iter_log_xml(xml_source: LogXMLSource) -> Iterator[LogEntry]:
    """Incrementally parse entries while preserving the existing LogEntry model."""
    changed_paths: List[LogPathChange] = []

    for event in iter_log_xml_events(xml_source):
        if isinstance(event, LogEntryStart):
            changed_paths = []
        elif isinstance(event, LogPathChangeEvent):
            changed_paths.append(event.change)
        elif isinstance(event, LogEntryEnd):
            yield LogEntry(
                revision=event.revision,
                author=event.author,
                date=event.date,
                message=event.message,
                changed_paths=changed_paths,
            )
            changed_paths = []


def parse_log_xml(xml_text: str) -> List[LogEntry]:
    """把 `svn log --xml` 输出解析成 LogEntry 列表。"""
    return list(iter_log_xml(io.StringIO(xml_text)))
