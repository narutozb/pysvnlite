from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, Generator, List, Optional, Sequence, Union

from subprocess import CompletedProcess
from urllib.parse import urlparse

from .runner import run_svn, run_svn_bytes, run_svn_spooled, run_svn_to_file
from .runner import _run_captured, _verify_checkout_path
from .parser_info import parse_info_xml
from .parser_log import iter_log_xml, iter_log_xml_events
from .parser_status import parse_status_xml
from .parser_list import parse_list_xml
from .parser_props import parse_propget_xml, parse_proplist_xml
from .parser_blame import parse_blame_xml
from .models import (
    BlameLine,
    CommitResult,
    CommitSummary,
    ListEntry,
    LogEntry,
    LogEvent,
    LogPathChange,
    RepoInfo,
    StatusItem,
)
from .exceptions import SVNCommandError


_commit_rev_patterns = (
    re.compile(r"Committed revision\s+(\d+)", re.IGNORECASE),
    re.compile(r"提交后的版本为\s*(\d+)", re.IGNORECASE),
    re.compile(r"已提交版本\s*(\d+)", re.IGNORECASE),
    re.compile(r"提交版本\s*(\d+)", re.IGNORECASE),
)
_commit_hint_re = re.compile(r"(commit|committed|revision|版本|提交|リビジョン)", re.IGNORECASE)
_any_number_re = re.compile(r"(\d+)")
Revision = Union[int, str]
CAPABILITIES = frozenset({"bounded_verbose_log_v1"})


def _decode_process_output(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _run_svn_result(args: List[str], timeout: Optional[float] = None) -> CompletedProcess[str]:
    full_cmd = ["svn", "--non-interactive"] + args
    try:
        stdout, stderr = _run_captured(full_cmd, cwd=None, timeout=timeout)
    except SVNCommandError as error:
        if error.returncode < 0:
            raise
        return CompletedProcess(full_cmd, error.returncode, error.stdout, error.stderr)
    return CompletedProcess(
        full_cmd, 0, _decode_process_output(stdout), _decode_process_output(stderr),
    )


def _exists(p: str) -> bool:
    try:
        return os.path.exists(p)
    except Exception:
        return False


def _is_url(p: Union[str, Path]) -> bool:
    s = str(p)
    try:
        u = urlparse(s)
        return u.scheme in ("http", "https", "svn", "svn+ssh", "file")
    except Exception:
        return False


def _with_peg(target: Union[str, Path], peg: Optional[Revision]) -> str:
    target_text = str(target)
    if peg is not None:
        return f"{target_text}@{peg}"
    if "@" in target_text and not target_text.endswith("@"):
        return f"{target_text}@"
    return target_text


def _parse_commit_revision(stdout: str) -> Optional[int]:
    content = stdout or ""

    for pattern in _commit_rev_patterns:
        m = pattern.search(content)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return None

    for line in content.splitlines():
        if not _commit_hint_re.search(line):
            continue
        m = _any_number_re.search(line)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return None

    return None


def _summarize_status(items: List[StatusItem]) -> CommitSummary:
    buck = CommitSummary()
    for it in items:
        s = (it.wc_status or "").lower()
        if s == "added":
            buck.added.append(it.path)
        elif s == "modified":
            buck.modified.append(it.path)
        elif s == "deleted":
            buck.deleted.append(it.path)
        elif s == "missing":
            buck.missing.append(it.path)
        elif s == "conflicted":
            buck.conflicted.append(it.path)
        elif s == "unversioned":
            buck.unversioned.append(it.path)
        if it.tree_conflicted or s == "tree-conflicted":
            buck.tree_conflicted.append(it.path)
    return buck


class SVNRepo:
    CAPABILITIES = CAPABILITIES

    def __init__(self, target: Union[str, Path], *, timeout: Optional[float] = None):
        self._target = str(target)
        self._timeout = timeout

    @property
    def target(self) -> str:
        return self._target

    @property
    def timeout(self) -> Optional[float]:
        return self._timeout

    def _run(self, args: List[str]) -> str:
        return run_svn(args, timeout=self._timeout)

    def _run_bytes(self, args: List[str]) -> bytes:
        return run_svn_bytes(args, timeout=self._timeout)

    def _run_to_file(self, args: List[str], output_path: Union[str, Path]) -> None:
        run_svn_to_file(args, output_path, timeout=self._timeout)

    def _run_result(self, args: List[str]) -> CompletedProcess[str]:
        return _run_svn_result(args, timeout=self._timeout)

    def _log_args(
        self,
        limit: Optional[int],
        *,
        revision: Optional[Revision],
        peg: Optional[Revision],
        stop_on_copy: bool,
        verbose: bool,
    ) -> List[str]:
        args = ["log", "--xml"]
        if revision is not None:
            args += ["-r", str(revision)]
        if stop_on_copy:
            args.append("--stop-on-copy")
        if verbose:
            args.append("-v")
        if limit is not None:
            args += ["-l", str(limit)]
        args.append(_with_peg(self._target, peg))
        return args

    # ---------- read ops ----------
    def info(
        self,
        path_or_url: Optional[Union[str, Path]] = None,
        *,
        revision: Optional[Revision] = None,
        peg: Optional[Revision] = None,
    ) -> RepoInfo:
        target = path_or_url if path_or_url is not None else self._target
        args = ["info", "--xml"]
        if revision is not None:
            args += ["-r", str(revision)]
        args.append(_with_peg(target, peg))
        xml_out = self._run(args)
        return parse_info_xml(xml_out)

    def log(
        self,
        limit: Optional[int] = 10,
        *,
        revision: Optional[Revision] = None,
        peg: Optional[Revision] = None,
        stop_on_copy: bool = False,
        verbose: bool = False,
        max_output_bytes: Optional[int] = None,
        spool_dir: Optional[Union[str, Path]] = None,
    ) -> List[LogEntry]:
        return list(
            self.iter_log(
                limit,
                revision=revision,
                peg=peg,
                stop_on_copy=stop_on_copy,
                verbose=verbose,
                max_output_bytes=max_output_bytes,
                spool_dir=spool_dir,
            )
        )

    def iter_log(
        self,
        limit: Optional[int] = 10,
        *,
        revision: Optional[Revision] = None,
        peg: Optional[Revision] = None,
        stop_on_copy: bool = False,
        verbose: bool = False,
        max_output_bytes: Optional[int] = None,
        spool_dir: Optional[Union[str, Path]] = None,
    ) -> Generator[LogEntry, None, None]:
        args = self._log_args(
            limit,
            revision=revision,
            peg=peg,
            stop_on_copy=stop_on_copy,
            verbose=verbose,
        )
        with run_svn_spooled(
            args,
            timeout=self._timeout,
            max_output_bytes=max_output_bytes,
            spool_dir=spool_dir,
        ) as xml_stream:
            yield from iter_log_xml(xml_stream)

    def iter_log_events(
        self,
        limit: Optional[int] = 10,
        *,
        revision: Optional[Revision] = None,
        peg: Optional[Revision] = None,
        stop_on_copy: bool = False,
        verbose: bool = False,
        max_output_bytes: Optional[int] = None,
        spool_dir: Optional[Union[str, Path]] = None,
    ) -> Generator[LogEvent, None, None]:
        args = self._log_args(
            limit,
            revision=revision,
            peg=peg,
            stop_on_copy=stop_on_copy,
            verbose=verbose,
        )
        with run_svn_spooled(
            args,
            timeout=self._timeout,
            max_output_bytes=max_output_bytes,
            spool_dir=spool_dir,
        ) as xml_stream:
            yield from iter_log_xml_events(xml_stream)

    def status(
        self,
        *,
        depth: Optional[str] = None,
        show_updates: bool = False,
        ignore_externals: bool = False,
    ) -> List[StatusItem]:
        args = ["status", "--xml"]
        if depth:
            args += ["--depth", depth]
        if show_updates:
            args.append("-u")
        if ignore_externals:
            args.append("--ignore-externals")
        args.append(self._target)
        xml_out = self._run(args)
        return parse_status_xml(xml_out)

    def list(
        self,
        path_or_url: Optional[Union[str, Path]] = None,
        *,
        revision: Optional[Revision] = None,
        peg: Optional[Revision] = None,
        depth: Optional[str] = None,
        recursive: bool = False,
        ignore_externals: bool = False,
    ) -> List[ListEntry]:
        """
        svn list: 列出版本库目录条目。
        默认列出 self.target (如果是 URL) 或工作副本对应的 URL。
        ignore_externals 为兼容参数；svn list 默认不包含 externals。
        """
        target = str(path_or_url) if path_or_url else self._target
        args = ["list", "--xml"]
        if revision is not None:
            args += ["-r", str(revision)]
        if depth:
            args += ["--depth", depth]
        if recursive:
            args.append("--recursive")

        args.append(_with_peg(target, peg))
        xml_out = self._run(args)
        return parse_list_xml(xml_out)

    def cat(
        self,
        path_or_url: Union[str, Path],
        *,
        revision: Optional[Revision] = None,
        peg: Optional[Revision] = None,
    ) -> bytes:
        """
        svn cat: 输出指定版本的文件内容。
        """
        args = ["cat"]
        if revision is not None:
            args += ["-r", str(revision)]
        args.append(_with_peg(path_or_url, peg))
        return self._run_bytes(args)

    def cat_to_file(
        self,
        path_or_url: Union[str, Path],
        output_path: Union[str, Path],
        *,
        revision: Optional[Revision] = None,
        peg: Optional[Revision] = None,
    ) -> None:
        """
        svn cat: 将指定版本的文件内容直接写入本地文件。
        """
        args = ["cat"]
        if revision is not None:
            args += ["-r", str(revision)]
        args.append(_with_peg(path_or_url, peg))
        self._run_to_file(args, output_path)

    def changed_files_of_commit(
        self,
        revision: int,
        *,
        max_output_bytes: Optional[int] = None,
        spool_dir: Optional[Union[str, Path]] = None,
    ) -> List[LogPathChange]:
        entries = self.log(
            limit=None,
            revision=revision,
            verbose=True,
            max_output_bytes=max_output_bytes,
            spool_dir=spool_dir,
        )
        return entries[0].changed_paths if entries else []

    # ---------- working copy ops ----------
    @staticmethod
    def checkout(
        url: Union[str, Path],
        dest: Union[str, Path],
        revision: Optional[int] = None,
        *,
        timeout: Optional[float] = None,
    ) -> "SVNRepo":
        args = ["checkout"]
        if revision is not None:
            args += ["--revision", str(revision)]
        args += [str(url), str(dest)]
        output = run_svn(args, timeout=timeout)
        _verify_checkout_path(Path(dest), ["svn", "--non-interactive"] + args, output)
        return SVNRepo(dest, timeout=timeout)

    def update(self, revision: Optional[int] = None) -> None:
        args = ["update"]
        if revision is not None:
            args += ["--revision", str(revision)]
        args.append(self._target)
        _ = self._run(args)

    def switch(
        self,
        url: str,
        path: Optional[Union[str, Path]] = None,
        *,
        revision: Optional[int] = None,
        depth: Optional[str] = None,
        ignore_externals: bool = False,
        force: bool = False,
    ) -> None:
        """
        svn switch URL [PATH]
        将工作副本切换到新的 URL（分支/标签）。
        """
        target = str(path) if path else self._target
        args = ["switch"]
        if revision is not None:
            args += ["-r", str(revision)]
        if depth:
            args += ["--depth", depth]
        if ignore_externals:
            args.append("--ignore-externals")
        if force:
            args.append("--force")

        args.append(url)
        args.append(target)
        _ = self._run(args)

    def add(
        self,
        paths: Sequence[Union[str, Path]] | None = None,
        *,
        force: bool = True,
        no_ignore: bool = False,
        # "empty"|"files"|"immediates"|"infinity"
        depth: Optional[str] = None,
    ) -> None:
        """
        等价 `svn add [--force] [--no-ignore] [--depth X] <paths...>`
        - paths 为空时，默认对 self._target 执行
        - unversioned 文件需要 add 后才能提交
        """
        targets = [self._target] if not paths else [str(p) for p in paths]
        args = ["add"]
        if force:
            args.append("--force")
        if no_ignore:
            args.append("--no-ignore")
        if depth:
            args += ["--depth", depth]
        args += targets
        _ = self._run(args)

    def revert(
        self,
        paths: Sequence[Union[str, Path]],
        *,
        depth: Optional[str] = None,
        include_parents: bool = False,
    ) -> None:
        if not paths:
            return
        args = ["revert"]
        if depth:
            args += ["--depth", depth]
        if include_parents:
            args.append("--include-parents")
        args += [str(p) for p in paths]
        _ = self._run(args)

    def delete(
        self,
        paths: Sequence[Union[str, Path]],
        *,
        force: bool = False,
        keep_local: bool = False,
        message: Optional[str] = None,
        message_file: Optional[Union[str, Path]] = None,
    ) -> None:
        if not paths:
            return
        targets = [str(path) for path in paths]
        url_targets = [_is_url(target) for target in targets]
        if any(url_targets) and not all(url_targets):
            raise ValueError("SVN delete cannot mix repository URLs and working-copy paths.")
        if all(url_targets):
            if (message is None) == (message_file is None):
                raise ValueError(
                    "For repository URL delete, provide exactly one of `message` or `message_file`."
                )
        elif message is not None or message_file is not None:
            raise ValueError(
                "`message` and `message_file` are only valid for repository URL delete."
            )

        args = ["delete"]
        if force:
            args.append("--force")
        if keep_local:
            args.append("--keep-local")
        if message is not None:
            args += ["-m", message]
        elif message_file is not None:
            args += ["-F", str(message_file)]
        args += targets
        _ = self._run(args)

    def mkdir(
        self,
        paths: Sequence[Union[str, Path]],
        *,
        parents: bool = False,
        message: Optional[str] = None,
        message_file: Optional[Union[str, Path]] = None,
    ) -> None:
        if not paths:
            return
        targets = [str(path) for path in paths]
        url_targets = [_is_url(target) for target in targets]
        if any(url_targets) and not all(url_targets):
            raise ValueError("SVN mkdir cannot mix repository URLs and working-copy paths.")
        if all(url_targets):
            if (message is None) == (message_file is None):
                raise ValueError(
                    "For repository URL mkdir, provide exactly one of `message` or `message_file`."
                )
        elif message is not None or message_file is not None:
            raise ValueError(
                "`message` and `message_file` are only valid for repository URL mkdir."
            )

        args = ["mkdir"]
        if parents:
            args.append("--parents")
        if message is not None:
            args += ["-m", message]
        elif message_file is not None:
            args += ["-F", str(message_file)]
        args += targets
        _ = self._run(args)

    def propset(
        self, name: str, value: str, path: Union[str, Path], *, revprop: bool = False
    ) -> None:
        args = ["propset", name, value, str(path)]
        if revprop:
            args.append("--revprop")
        _ = self._run(args)

    def propget(
        self,
        name: str,
        path: Union[str, Path],
        *,
        revprop: bool = False,
        revision: Optional[int] = None,
    ) -> Optional[str]:
        """
        svn propget: 获取属性值。
        如果是二进制值或复杂多行，XML 可能会有不同编码（base64 等），当前简化为 XML text。
        """
        args = ["propget", name, "--xml", str(path)]
        if revprop:
            args.append("--revprop")
        if revision is not None:
            args += ["-r", str(revision)]

        try:
            xml_out = self._run(args)
            return parse_propget_xml(xml_out)
        except SVNCommandError as e:
            if e.is_property_not_found:
                return None
            raise

    def proplist(
        self, path: Union[str, Path], *, revprop: bool = False, revision: Optional[int] = None
    ) -> Dict[str, str]:
        """
        svn proplist: 列出所有属性。
        返回 {prop_name: prop_value}。
        注意：必须加 --verbose 才能在 XML 中获取值。
        """
        args = ["proplist", "--xml", "--verbose", str(path)]
        if revprop:
            args.append("--revprop")
        if revision is not None:
            args += ["-r", str(revision)]

        xml_out = self._run(args)
        return parse_proplist_xml(xml_out)

    def propdel(self, name: str, path: Union[str, Path], *, revprop: bool = False) -> None:
        """
        svn propdel: 删除属性。
        """
        args = ["propdel", name, str(path)]
        if revprop:
            args.append("--revprop")
        _ = self._run(args)

    def resolve(
        self,
        path: Union[str, Path],
        accept: str = "working",  # 'base'|'working'|'mine-full'|'theirs-full'
        *,
        recursive: bool = False,
        depth: Optional[str] = None,
    ) -> None:
        """
        svn resolve --accept ACCEPT PATH
        解决冲突。
        """
        args = ["resolve", "--accept", accept, str(path)]
        if recursive:
            args.append("--recursive")
        if depth:
            args += ["--depth", depth]
        _ = self._run(args)

    def blame(
        self,
        path_or_url: Union[str, Path],
        *,
        revision: Optional[Revision] = None,
        peg: Optional[Revision] = None,
    ) -> List[BlameLine]:
        """
        svn blame: 追溯每行代码的修改历史。
        注意：使用 --xml 仅返回元数据（作者、版本、时间），不包含行内容。
        """
        args = ["blame", "--xml"]
        if revision is not None:
            args += ["-r", str(revision)]
        args.append(_with_peg(path_or_url, peg))
        xml_out = self._run(args)
        return parse_blame_xml(xml_out)

    def diff(
        self,
        path: Union[str, Path] | None = None,
        *,
        revision: Optional[Revision] = None,  # diff -r N
        revision_to: Optional[Revision] = None,  # diff -r N:M
        peg: Optional[Revision] = None,
        summarize: bool = False,
        ignore_properties: bool = False,
    ) -> bytes:
        """
        svn diff: 获取变更差异。
        返回 bytes，因为 diff 输出可能包含非 UTF-8 内容（虽然通常是文本）。
        """
        args = ["diff"]
        if summarize:
            args.append("--summarize")
        if ignore_properties:
            args.append("--ignore-properties")

        # Revisions: -r N or -r N:M
        if revision is not None:
            rev_str = str(revision)
            if revision_to is not None:
                rev_str += f":{revision_to}"
            args += ["-r", rev_str]

        target = path if path else self._target
        args.append(_with_peg(target, peg))

        return self._run_bytes(args)

    def lock(
        self, paths: Sequence[Union[str, Path]], message: Optional[str] = None, force: bool = False
    ) -> None:
        """
        svn lock: 锁定文件。
        """
        if not paths:
            return
        args = ["lock"]
        if message:
            args += ["-m", message]
        if force:
            args.append("--force")
        args += [str(p) for p in paths]
        _ = self._run(args)

    def unlock(self, paths: Sequence[Union[str, Path]], force: bool = False) -> None:
        """
        svn unlock: 解锁文件。
        """
        if not paths:
            return
        args = ["unlock"]
        if force:
            args.append("--force")
        args += [str(p) for p in paths]
        _ = self._run(args)

    # ---------- commit (enhanced) ----------
    def commit(
        self,
        *,
        message: Optional[str] = None,
        message_file: Optional[Union[str, Path]] = None,
        paths: Optional[Sequence[Union[str, Path]]] = None,
        # "empty"|"files"|"immediates"|"infinity"
        depth: Optional[str] = None,
        no_unlock: bool = False,
        keep_changelists: bool = False,
        include_parents: bool = False,
        add_unversioned: bool = False,  # 提交前自动 add 新文件
        add_ignored: bool = False,  # 自动 add 时是否包含 ignore 项
        auto_delete_missing: bool = False,  # 提交前把 missing 转为 delete
        fail_on_conflicts: bool = True,  # 发现冲突则中止提交
    ) -> CommitResult:

        if (message is None) == (message_file is None):
            raise ValueError("Exactly one of `message` or `message_file` must be provided.")

        commit_targets: List[str] = [self._target] if not paths else [str(p) for p in paths]

        # (1) 预采样状态摘要
        pre_items = self.status(depth="infinity")
        pre_summary = _summarize_status(pre_items)

        # (2) 冲突阻断
        if fail_on_conflicts and (pre_summary.conflicted or pre_summary.tree_conflicted):
            return CommitResult(
                success=False,
                revision=None,
                stdout="",
                stderr=f"Conflicts exist. Resolve first. conflicted={pre_summary.conflicted}, tree_conflicted={pre_summary.tree_conflicted}",
                returncode=1,
                pre_summary=pre_summary,
                changed_paths=[],
            )

        # (3) 更稳的“缺失清理”：
        #     - 真·缺失（版本化项缺失） => svn delete
        #     - 已 add 但磁盘缺失 => svn revert（取消 add）
        if auto_delete_missing:
            # A. 真·缺失：wc_status == "missing"
            missing_versioned = [p for p in pre_summary.missing]

            # B. added 但本地不存在（最容易触发 E155010 的场景）
            added_but_missing = [p for p in pre_summary.added if not _exists(p)]

            # 先删子后删父，避免父目录先删导致子项报错
            missing_versioned_sorted = sorted(missing_versioned, key=len, reverse=True)
            added_but_missing_sorted = sorted(added_but_missing, key=len, reverse=True)

            # 对“版本化缺失”用 delete
            if missing_versioned_sorted:
                try:
                    self.delete(missing_versioned_sorted, force=True, keep_local=False)
                except SVNCommandError as e:
                    # 不直接崩：把失败信息带回去
                    return CommitResult(
                        success=False,
                        revision=None,
                        stdout="",
                        stderr=f"Auto delete missing failed: {e}",
                        returncode=e.returncode,
                        pre_summary=pre_summary,
                        changed_paths=[],
                    )

            # 对“已 add 但缺失”用 revert
            if added_but_missing_sorted:
                try:
                    self.revert(added_but_missing_sorted, depth=None, include_parents=False)
                except SVNCommandError as e:
                    return CommitResult(
                        success=False,
                        revision=None,
                        stdout="",
                        stderr=f"Auto revert added-but-missing failed: {e}",
                        returncode=e.returncode,
                        pre_summary=pre_summary,
                        changed_paths=[],
                    )

            # 重新采样摘要（让返回结果更真实）
            pre_items = self.status(depth="infinity")
            pre_summary = _summarize_status(pre_items)

        # (4) 可选：自动 add 未受控新文件
        if add_unversioned and pre_summary.unversioned:
            self.add(pre_summary.unversioned, force=True, no_ignore=add_ignored, depth=None)
            pre_items = self.status(depth="infinity")
            pre_summary = _summarize_status(pre_items)

        # (5) 拼接 commit 命令
        args: List[str] = ["commit"]
        if message is not None:
            args += ["-m", message]
        else:
            args += ["-F", str(message_file)]
        if depth:
            args += ["--depth", depth]
        if no_unlock:
            args.append("--no-unlock")
        if keep_changelists:
            args.append("--keep-changelists")
        if include_parents:
            args.append("--include-parents")
        args += commit_targets

        # (6) 执行提交（保留 stdout/stderr/returncode）
        proc = self._run_result(args)
        stdout, stderr, code = proc.stdout, proc.stderr, proc.returncode

        rev = _parse_commit_revision(stdout)
        success = code == 0

        # (7) 若成功，提取本次变更路径（log -v）
        changed_paths: List[LogPathChange] = []
        if success and rev is not None:
            try:
                changed_paths = self.changed_files_of_commit(rev)
            except Exception:
                # 非核心失败不影响主流程
                changed_paths = []

        return CommitResult(
            success=success,
            revision=rev,
            stdout=stdout,
            stderr=stderr,
            returncode=code,
            pre_summary=pre_summary,
            changed_paths=changed_paths,
        )

    def __repr__(self) -> str:
        return f"SVNRepo(target={self._target!r})"

    # ---------- copy ----------
    def copy(
        self,
        srcs: Sequence[Union[str, Path]],
        dest: Union[str, Path],
        *,
        revision: Optional[int] = None,  # 对源使用 -r REV（统一指定）
        parents: bool = False,  # --parents（仓库侧/工作拷贝侧都可用）
        force: bool = False,  # 仅工作拷贝 copy 时有用
        message: Optional[str] = None,  # 仓库→仓库时必需其一
        message_file: Optional[Union[str, Path]] = None,
    ) -> Optional[CommitResult]:
        """
        svn copy：支持
        - 工作拷贝 → 工作拷贝（不提交，返回 None）
        - 仓库URL → 仓库URL（直接提交，返回 CommitResult）
        注意：当且仅当 srcs 全是 URL 且 dest 是 URL 时，会触发“仓库侧直接提交”，须提供 message 或 message_file。
        """
        if not srcs:
            return None

        src_list = [str(s) for s in srcs]
        dest_s = str(dest)
        src_all_url = all(_is_url(s) for s in src_list)
        dest_is_url = _is_url(dest_s)
        repo_to_repo = src_all_url and dest_is_url

        args: List[str] = ["copy"]
        if revision is not None:
            args += ["-r", str(revision)]
        if parents:
            args.append("--parents")
        if force:
            args.append("--force")

        # 仓库→仓库：需要提交信息（非交互环境下否则会失败）
        if repo_to_repo:
            if (message is None) == (message_file is None):
                raise ValueError(
                    "For repository-to-repository copy, provide exactly one of `message` or `message_file`."
                )
            if message is not None:
                args += ["-m", message]
            else:
                args += ["-F", str(message_file)]

        args += src_list + [dest_s]

        # 执行
        if repo_to_repo:
            # 直接提交：返回 CommitResult（含修订号与 changed_paths）
            proc = self._run_result(args)
            stdout, stderr, code = proc.stdout, proc.stderr, proc.returncode
            rev = _parse_commit_revision(stdout)
            success = code == 0
            changed_paths: List[LogPathChange] = []
            if success and rev is not None:
                try:
                    changed_paths = self.changed_files_of_commit(rev)
                except Exception:
                    changed_paths = []
            return CommitResult(
                success=success,
                revision=rev,
                stdout=stdout,
                stderr=stderr,
                returncode=code,
                pre_summary=CommitSummary(),  # 仓库侧操作，不取本地摘要
                changed_paths=changed_paths,
            )
        else:
            # 工作拷贝侧 copy：不提交，返回 None
            _ = self._run(args)
            return None

    # ---------- move ----------
    def move(
        self,
        srcs: Sequence[Union[str, Path]],
        dest: Union[str, Path],
        *,
        parents: bool = False,  # --parents
        force: bool = False,  # 覆盖/强制
        message: Optional[str] = None,  # 仓库→仓库时必需其一
        message_file: Optional[Union[str, Path]] = None,
    ) -> Optional[CommitResult]:
        """
        svn move：支持
        - 工作拷贝内重命名/移动（不提交，返回 None）
        - 仓库URL→仓库URL 的服务器端移动（直接提交，返回 CommitResult）
        备注：move 本质是 copy + delete，优势是保留历史且一步完成。
        """
        if not srcs:
            return None

        src_list = [str(s) for s in srcs]
        dest_s = str(dest)
        src_all_url = all(_is_url(s) for s in src_list)
        dest_is_url = _is_url(dest_s)
        repo_to_repo = src_all_url and dest_is_url

        args: List[str] = ["move"]
        if parents:
            args.append("--parents")
        if force:
            args.append("--force")

        if repo_to_repo:
            if (message is None) == (message_file is None):
                raise ValueError(
                    "For repository-to-repository move, provide exactly one of `message` or `message_file`."
                )
            if message is not None:
                args += ["-m", message]
            else:
                args += ["-F", str(message_file)]

        args += src_list + [dest_s]

        if repo_to_repo:
            proc = self._run_result(args)
            stdout, stderr, code = proc.stdout, proc.stderr, proc.returncode
            rev = _parse_commit_revision(stdout)
            success = code == 0
            changed_paths: List[LogPathChange] = []
            if success and rev is not None:
                try:
                    changed_paths = self.changed_files_of_commit(rev)
                except Exception:
                    changed_paths = []
            return CommitResult(
                success=success,
                revision=rev,
                stdout=stdout,
                stderr=stderr,
                returncode=code,
                pre_summary=CommitSummary(),
                changed_paths=changed_paths,
            )
        else:
            _ = self._run(args)
            return None

    # ---------- cleanup ----------
    def cleanup(
        self,
        paths: Sequence[Union[str, Path]] | None = None,
        *,
        remove_unversioned: bool = False,
        remove_ignored: bool = False,
        include_externals: bool = False,
    ) -> None:
        """
        svn cleanup [PATH...]
        递归清理工作副本，移除锁并恢复未完成的操作。
        SVN 1.9+ 支持清理未受控/忽略的文件。
        """
        targets = [self._target] if not paths else [str(p) for p in paths]
        args = ["cleanup"]
        if remove_unversioned:
            args.append("--remove-unversioned")
        if remove_ignored:
            args.append("--remove-ignored")
        if include_externals:
            args.append("--include-externals")
        args += targets
        _ = self._run(args)

    # ---------- export ----------
    def export(
        self,
        dest: Union[str, Path],
        src: Union[str, Path] | None = None,
        *,
        revision: Optional[int] = None,
        force: bool = False,
        ignore_externals: bool = False,
        ignore_keywords: bool = False,
    ) -> None:
        """
        svn export [-r REV] URL[@PEGREV] [PATH]
        svn export [-r REV] PATH1[@PEGREV] [PATH2]
        从版本库或工作副本导出干净的目录树（不含 .svn）。

        - src: 默认为 self._target。可是 URL 或工作副本路径。
        - dest: 目标本地路径。
        """
        source = str(src) if src else self._target
        destination = str(dest)
        args = ["export"]
        if revision is not None:
            args += ["-r", str(revision)]
        if force:
            args.append("--force")
        if ignore_externals:
            args.append("--ignore-externals")
        if ignore_keywords:
            args.append("--ignore-keywords")

        args += [source, destination]
        _ = self._run(args)
