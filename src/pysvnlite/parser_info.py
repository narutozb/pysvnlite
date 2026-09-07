from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional
from .models import RepoInfo
from .utils import parse_svn_datetime


def parse_info_xml(xml_text: str) -> RepoInfo:
    """
    把 `svn info --xml` 的输出解析成 RepoInfo
    注意：svn info --xml 可能返回多个 <entry>，我们先只取第一个。
    """

    root = ET.fromstring(xml_text)
    entry_el = root.find("entry")
    if entry_el is None:
        # 理论上不应该发生，除非 svn 返回了奇怪输出
        raise ValueError("No <entry> in svn info XML")

    # 基础字段
    url = _text(entry_el.find("url")) or ""
    repo_root = _text(entry_el.find("repository/root"))
    repo_uuid = _text(entry_el.find("repository/uuid"))

    wcroot_path: Optional[Path] = None
    wcroot_el = entry_el.find("wc-info/wcroot-abspath")
    if wcroot_el is not None and wcroot_el.text:
        wcroot_path = Path(wcroot_el.text)

    revision = _int(entry_el.get("revision"))
    kind = entry_el.get("kind")

    commit_el = entry_el.find("commit")
    last_rev = _int(commit_el.get("revision")) if commit_el is not None else None
    last_author = _text(commit_el.find("author")) if commit_el is not None else None
    last_date_raw = _text(commit_el.find("date")) if commit_el is not None else None
    last_date = parse_svn_datetime(last_date_raw) if last_date_raw else None

    return RepoInfo(
        url=url,
        repo_root_url=repo_root,
        repo_uuid=repo_uuid,
        wc_root=wcroot_path,
        revision=revision,
        node_kind=kind,
        last_changed_rev=last_rev,
        last_changed_author=last_author,
        last_changed_date=last_date,
    )


def _text(el: Optional[ET.Element]) -> Optional[str]:
    return el.text if (el is not None and el.text is not None) else None


def _int(v: Optional[str]) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except ValueError:
        return None
