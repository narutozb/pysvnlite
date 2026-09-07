from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import List, Optional

from .models import ListEntry
from .utils import parse_svn_datetime


def parse_list_xml(xml_text: str) -> List[ListEntry]:
    """
    解析 `svn list --xml` 输出，返回 ListEntry 列表。
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    items: List[ListEntry] = []

    # XML 结构通常如下：
    # <lists>
    #   <list path="...">
    #     <entry kind="file">
    #       <name>README.txt</name>
    #       <size>12</size>
    #       <commit revision="2">
    #         <author>user</author>
    #         <date>...</date>
    #       </commit>
    #     </entry>
    #   </list>
    # </lists>

    for list_el in root.findall("list"):
        for entry_el in list_el.findall("entry"):
            kind = entry_el.get("kind") or "unknown"
            name = _text(entry_el.find("name")) or ""

            size_el = entry_el.find("size")
            size = _to_int(size_el.text) if size_el is not None else None

            commit_el = entry_el.find("commit")
            commit_rev = None
            commit_author = None
            commit_date = None

            if commit_el is not None:
                commit_rev = _to_int(commit_el.get("revision"))
                commit_author = _text(commit_el.find("author"))
                date_str = _text(commit_el.find("date"))
                if date_str:
                    commit_date = parse_svn_datetime(date_str)

            items.append(
                ListEntry(
                    kind=kind,
                    name=name,
                    size=size,
                    commit_rev=commit_rev,
                    commit_author=commit_author,
                    commit_date=commit_date,
                )
            )
    return items


def _text(el: Optional[ET.Element]) -> Optional[str]:
    return el.text if (el is not None and el.text is not None) else None


def _to_int(s: Optional[str]) -> Optional[int]:
    if s is None:
        return None
    try:
        return int(s)
    except ValueError:
        return None
