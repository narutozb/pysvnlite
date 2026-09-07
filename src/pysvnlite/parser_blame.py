from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import List, Optional

from .models import BlameLine
from .utils import parse_svn_datetime


def parse_blame_xml(xml_text: str) -> List[BlameLine]:
    """
    解析 `svn blame --xml` 的输出。
    XML 结构：
    <target path="...">
        <entry line-number="1">
            <commit revision="2">
                <author>user</author>
                <date>...</date>
            </commit>
        </entry>
        ...
    </target>

    注意：XML 输出不包含行内容，只有元数据！
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    lines: List[BlameLine] = []

    # 通常只有一个 target
    for target in root.findall("target"):
        for entry in target.findall("entry"):
            line_str = entry.get("line-number")
            line_number = int(line_str) if line_str else 0

            commit_el = entry.find("commit")
            rev = -1
            author = ""
            date_dt = None

            if commit_el is not None:
                rev_str = commit_el.get("revision")
                rev = int(rev_str) if rev_str else -1
                author = _text(commit_el.find("author")) or ""
                date_str = _text(commit_el.find("date"))
                if date_str:
                    date_dt = parse_svn_datetime(date_str)

            lines.append(BlameLine(
                line_number=line_number,
                revision=rev,
                author=author,
                date=date_dt,
                content=""  # XML output doesn't include content
            ))

    return lines


def _text(el: Optional[ET.Element]) -> Optional[str]:
    return el.text if (el is not None and el.text is not None) else None
