from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import List, Optional
from .models import StatusItem
from .utils import parse_svn_datetime

def parse_status_xml(xml_text: str) -> List[StatusItem]:
    """
    解析 `svn status --xml` 输出，返回 StatusItem 列表。
    """
    root = ET.fromstring(xml_text)
    items: List[StatusItem] = []

    for entry_el in root.findall("target/entry"):
        path = entry_el.get("path") or ""

        wc_el = entry_el.find("wc-status")
        wc_status = wc_el.get("item") if wc_el is not None else None
        # 注意：svn status --xml 里 <wc-status> 的属性有 item, props, revision 等；
        # 但“repos-status”并不是直接给的，有时候需要 <repos-status> 节点（不同 svn 版本稍有出入）。
        # 为了广泛兼容，这里更稳妥的方式是找 <repos-status> 节点。

        locked = _attr_bool(wc_el, "locked")
        switched = _attr_bool(wc_el, "switched")
        copied = _attr_bool(wc_el, "copied")
        tree_conflicted = _attr_bool(wc_el, "tree-conflicted")
        rev_attr = wc_el.get("revision") if wc_el is not None else None
        wc_rev = _to_int(rev_attr)

        # repos-status（可选）
        repos_el = entry_el.find("repos-status")
        repos_status_val = repos_el.get("item") if repos_el is not None else None

        # 最后一次提交信息
        commit_el = wc_el.find("commit") if wc_el is not None else None
        commit_rev = _to_int(commit_el.get("revision")) if commit_el is not None else None
        commit_author = _text(commit_el.find("author")) if commit_el is not None else None
        commit_date_raw = _text(commit_el.find("date")) if commit_el is not None else None
        commit_date = parse_svn_datetime(commit_date_raw) if commit_date_raw else None

        items.append(StatusItem(
            path=path,
            wc_status=wc_status or "",
            repos_status=repos_status_val,
            locked=bool(locked),
            switched=bool(switched),
            copied=bool(copied),
            tree_conflicted=bool(tree_conflicted),
            revision=wc_rev,
            commit_rev=commit_rev,
            commit_author=commit_author,
            commit_date=commit_date,
        ))

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


def _attr_bool(el: Optional[ET.Element], name: str) -> bool:
    if el is None:
        return False
    v = el.get(name)
    # svn xml 通常是 'true'|'false'
    return True if (v and v.lower() == "true") else False
