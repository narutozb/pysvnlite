from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Union


@dataclass
class RepoInfo:
    """结构化的 svn info 结果"""

    url: str
    repo_root_url: Optional[str]
    repo_uuid: Optional[str]

    wc_root: Optional[Path]          # 如果是工作拷贝路径则会有
    revision: Optional[int]
    node_kind: Optional[str]         # 'dir' / 'file'
    last_changed_rev: Optional[int]
    last_changed_author: Optional[str]
    last_changed_date: Optional[datetime]


@dataclass
class LogPathChange:
    """单条日志中某个文件/路径的变更信息"""
    action: str                      # 'A' 'M' 'D' 'R' ...
    path: str
    copy_from_path: Optional[str] = None
    copy_from_rev: Optional[int] = None


@dataclass
class LogEntry:
    """svn log 的一条提交记录"""
    revision: int
    author: Optional[str]
    date: Optional[datetime]
    message: str
    changed_paths: List[LogPathChange] = field(default_factory=list)


@dataclass
class LogEntryStart:
    """Marks the beginning of one revision in a path-level log stream."""

    revision: int


@dataclass
class LogPathChangeEvent:
    """One changed path associated with a streamed revision."""

    revision: int
    change: LogPathChange


@dataclass
class LogEntryEnd:
    """Completes one revision after all of its path events were emitted."""

    revision: int
    author: Optional[str]
    date: Optional[datetime]
    message: str
    changed_paths_count: int


LogEvent = Union[LogEntryStart, LogPathChangeEvent, LogEntryEnd]


@dataclass
class CommitSummary:
    """提交前的变更摘要（来自 svn status --xml）"""
    added: List[str] = field(default_factory=list)
    modified: List[str] = field(default_factory=list)
    deleted: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    conflicted: List[str] = field(default_factory=list)
    tree_conflicted: List[str] = field(default_factory=list)
    unversioned: List[str] = field(default_factory=list)

@dataclass
class CommitResult:
    """
    svn commit 的结果（增强版）。
    - success: returncode==0
    - revision: 解析到的修订号；可能为 None（本地化导致解析失败时）
    - pre_summary: 提交前的状态摘要
    - changed_paths: 若成功，来自 `svn log -v --xml -r <rev>` 的本次变更路径
    """
    success: bool
    revision: Optional[int]
    stdout: str
    stderr: str
    returncode: int
    pre_summary: CommitSummary = field(default_factory=CommitSummary)
    changed_paths: List["LogPathChange"] = field(default_factory=list)


@dataclass
class StatusItem:
    """
    一条工作拷贝状态信息（对应 svn status --xml 的 <entry>）
    """
    path: str                             # 本地路径
    wc_status: str                        # item 的内容变更状态: 'modified'|'added'|'deleted'|'unversioned'|'missing'|'conflicted'|'external'|...
    repos_status: Optional[str]           # 远端对该项的状态（可能 None）
    locked: bool                          # 是否被 WC 锁定
    switched: bool                        # 是否切换到非相对 URL
    copied: bool                          # 是否 copy 来的
    tree_conflicted: bool                 # 是否树冲突
    revision: Optional[int]               # 本地工作拷贝记录的 rev
    commit_rev: Optional[int]             # 最后一次提交 rev（来自 <commit revision=...>）
    commit_author: Optional[str]          # 最后一次提交作者
    commit_date: Optional["datetime"]     # 最后一次提交时间（aware, UTC）


@dataclass
class ListEntry:
    """svn list 的一条记录"""
    kind: str                        # 'file' or 'dir'
    name: str                        # 文件名/目录名
    size: Optional[int]              # 文件大小（目录无）
    commit_rev: Optional[int]        # 最后一次提交 rev
    commit_author: Optional[str]     # 最后一次提交作者
    commit_date: Optional[datetime]  # 最后一次提交时间


@dataclass
class BlameLine:
    """svn blame 的一行信息"""
    line_number: int            # 行号
    revision: int               # 该行最后修改的版本号
    author: str                 # 该行最后修改的作者
    date: Optional[datetime]    # 该行最后修改的时间
    content: str                # 行内容（注意：blame --xml 不含内容，需结合 cat 才能拼出完整信息，或仅返回元数据）
    # 注：svn blame --xml 输出不包含行内容本身！只包含 rev, author, date。
    # 通常 blame 还需要展示内容，但 svn blame --xml 确实不给。
    # 如果要像 IDE 那样展示，需要另外 cat 文件内容并合并。
    # 这里我们暂且只存储元数据，或者在 parser 里尝试读取文件内容（成本较高）。
    # 按照轻量级原则，我们先只解析 XML 返回的元数据。
