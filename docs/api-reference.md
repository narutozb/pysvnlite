# API 参考

本页对应 pysvnlite 0.2.1 的 [SVNRepo 源码](../src/pysvnlite/repo.py)及[模型定义](../src/pysvnlite/models.py)。签名省略绑定方法的 self；构造时使用 `SVNRepo(target, timeout=...)`。`Revision = Union[int, str]`，Path 来自 pathlib，集合类型来自 typing。

## 调用约定

- 实例保存目标路径/URL，不会仅因构造而检出仓库。方法的默认目标是实例 target；显式传入的相对路径通常相对于进程 cwd，不会自动拼接到工作副本根目录，建议使用明确的绝对路径。
- `checkout` 为静态方法，`target` / `timeout` 是只读属性。`CAPABILITIES` 包含 `bounded_verbose_log_v1`，也可通过 `SVNRepo.CAPABILITIES` 查询。
- `revision` 是 operative revision，`peg` 用于定位历史对象。读方法支持的 peg 见签名；不要假定所有写方法都有相同的 `@` 消歧能力。
- URL `mkdir/delete` 必须且只能提供 message 或 message_file，并立即提交；工作副本形式不接受提交信息，只调度本地变更。
- URL `copy/move` 返回 CommitResult；工作副本操作返回 None。操作前检查其参数组合，不要将多个调用视作事务。
- `cat` / `diff` 返回 bytes；`cat_to_file` 原子替换成功结果。list 的 ignore_externals 参数保留兼容，但不会传给原生 SVN。
- `log` 返回列表，`iter_log` 按 revision 返回模型，`iter_log_events` 按路径返回事件；两种 iterator 都先完成 stdout 捕获再解析。需要限制日志大小时设置 max_output_bytes，并确保 spool_dir 已存在且可写。
- `blame` 只解析 XML 元数据，BlameLine.content 不提供文件正文，需另行 cat。

## 失败与提交结果

大多数命令的启动、非零返回码、超时和检出后置条件失败抛出 SVNCommandError。无效参数组合可能抛出 ValueError。日志输出超限抛出其子类 SVNOutputLimitError，category 为 output_limit。

**commit 不能只依赖异常判断成功。** 冲突阻断、自动清理失败或原生提交非零返回可能产生 `CommitResult(success=False)`。前置 status、add 或进程启动等失败仍可能抛异常，调用方必须同时处理异常和结果。

成功的 revision 仍可能为 None：可能没有新提交，也可能是本地化回显未解析出修订号。因此不要仅凭 revision 为 None 宣称“没有变化”。成功后的日志补查失败时 changed_paths 可为空；需要审计完整性时另行核对 SVN。

```python
from pysvnlite import SVNCommandError, SVNRepo
from pysvnlite.exceptions import redact_url_credentials

wc = SVNRepo("working-copy", timeout=30)
try:
    result = wc.commit(message="Update tracked assets")
except SVNCommandError as exc:
    print(str(exc))
    raise
if not result.success:
    raise RuntimeError(redact_url_credentials(result.stderr))
print(result.revision)
```

该示例会提交工作副本，仅用于已授权测试仓库。`str(exc)` 会脱敏 URL userinfo；cmd/stdout/stderr 和 CommitResult 的原始字段不会自动脱敏，写入日志前需使用 redact_url_credentials。该函数不保证隐藏任意命令行密码参数，因此不要把密码放在参数里。

category 可能为 timeout、authentication、authorization、network、not_found、property_not_found、unknown，输出上限子类另为 output_limit；判定基于原生错误文本，不等于对所有本地化文案的承诺。检出路径异常没有专门 category，需阅读 stderr；详见 [Windows 说明](windows-paths.md)。

## 完整方法签名

以下签名由源码核对，文档测试会在发生漂移时失败。

### SVNRepo.__init__

```text
__init__(target: Union[str, Path], *, timeout: Optional[float]=None)
```

### SVNRepo.target

只读属性，使用 `repo.target`，不调用。

```text
target() -> str
```

### SVNRepo.timeout

只读属性，使用 `repo.timeout`，不调用。

```text
timeout() -> Optional[float]
```

### SVNRepo.info

```text
info(path_or_url: Optional[Union[str, Path]]=None, *, revision: Optional[Revision]=None, peg: Optional[Revision]=None) -> RepoInfo
```

### SVNRepo.log

```text
log(limit: Optional[int]=10, *, revision: Optional[Revision]=None, peg: Optional[Revision]=None, stop_on_copy: bool=False, verbose: bool=False, max_output_bytes: Optional[int]=None, spool_dir: Optional[Union[str, Path]]=None) -> List[LogEntry]
```

### SVNRepo.iter_log

```text
iter_log(limit: Optional[int]=10, *, revision: Optional[Revision]=None, peg: Optional[Revision]=None, stop_on_copy: bool=False, verbose: bool=False, max_output_bytes: Optional[int]=None, spool_dir: Optional[Union[str, Path]]=None) -> Generator[LogEntry, None, None]
```

### SVNRepo.iter_log_events

```text
iter_log_events(limit: Optional[int]=10, *, revision: Optional[Revision]=None, peg: Optional[Revision]=None, stop_on_copy: bool=False, verbose: bool=False, max_output_bytes: Optional[int]=None, spool_dir: Optional[Union[str, Path]]=None) -> Generator[LogEvent, None, None]
```

### SVNRepo.status

```text
status(*, depth: Optional[str]=None, show_updates: bool=False, ignore_externals: bool=False) -> List[StatusItem]
```

### SVNRepo.list

```text
list(path_or_url: Optional[Union[str, Path]]=None, *, revision: Optional[Revision]=None, peg: Optional[Revision]=None, depth: Optional[str]=None, recursive: bool=False, ignore_externals: bool=False) -> List[ListEntry]
```

### SVNRepo.cat

```text
cat(path_or_url: Union[str, Path], *, revision: Optional[Revision]=None, peg: Optional[Revision]=None) -> bytes
```

### SVNRepo.cat_to_file

```text
cat_to_file(path_or_url: Union[str, Path], output_path: Union[str, Path], *, revision: Optional[Revision]=None, peg: Optional[Revision]=None) -> None
```

### SVNRepo.changed_files_of_commit

```text
changed_files_of_commit(revision: int, *, max_output_bytes: Optional[int]=None, spool_dir: Optional[Union[str, Path]]=None) -> List[LogPathChange]
```

### SVNRepo.checkout

```text
checkout(url: Union[str, Path], dest: Union[str, Path], revision: Optional[int]=None, *, timeout: Optional[float]=None) -> 'SVNRepo'
```

### SVNRepo.update

```text
update(revision: Optional[int]=None) -> None
```

### SVNRepo.switch

```text
switch(url: str, path: Optional[Union[str, Path]]=None, *, revision: Optional[int]=None, depth: Optional[str]=None, ignore_externals: bool=False, force: bool=False) -> None
```

### SVNRepo.add

```text
add(paths: Sequence[Union[str, Path]] | None=None, *, force: bool=True, no_ignore: bool=False, depth: Optional[str]=None) -> None
```

### SVNRepo.revert

```text
revert(paths: Sequence[Union[str, Path]], *, depth: Optional[str]=None, include_parents: bool=False) -> None
```

### SVNRepo.delete

```text
delete(paths: Sequence[Union[str, Path]], *, force: bool=False, keep_local: bool=False, message: Optional[str]=None, message_file: Optional[Union[str, Path]]=None) -> None
```

### SVNRepo.mkdir

```text
mkdir(paths: Sequence[Union[str, Path]], *, parents: bool=False, message: Optional[str]=None, message_file: Optional[Union[str, Path]]=None) -> None
```

### SVNRepo.propset

```text
propset(name: str, value: str, path: Union[str, Path], *, revprop: bool=False) -> None
```

### SVNRepo.propget

```text
propget(name: str, path: Union[str, Path], *, revprop: bool=False, revision: Optional[int]=None) -> Optional[str]
```

### SVNRepo.proplist

```text
proplist(path: Union[str, Path], *, revprop: bool=False, revision: Optional[int]=None) -> Dict[str, str]
```

### SVNRepo.propdel

```text
propdel(name: str, path: Union[str, Path], *, revprop: bool=False) -> None
```

### SVNRepo.resolve

```text
resolve(path: Union[str, Path], accept: str='working', *, recursive: bool=False, depth: Optional[str]=None) -> None
```

### SVNRepo.blame

```text
blame(path_or_url: Union[str, Path], *, revision: Optional[Revision]=None, peg: Optional[Revision]=None) -> List[BlameLine]
```

### SVNRepo.diff

```text
diff(path: Union[str, Path] | None=None, *, revision: Optional[Revision]=None, revision_to: Optional[Revision]=None, peg: Optional[Revision]=None, summarize: bool=False, ignore_properties: bool=False) -> bytes
```

### SVNRepo.lock

```text
lock(paths: Sequence[Union[str, Path]], message: Optional[str]=None, force: bool=False) -> None
```

### SVNRepo.unlock

```text
unlock(paths: Sequence[Union[str, Path]], force: bool=False) -> None
```

### SVNRepo.commit

```text
commit(*, message: Optional[str]=None, message_file: Optional[Union[str, Path]]=None, paths: Optional[Sequence[Union[str, Path]]]=None, depth: Optional[str]=None, no_unlock: bool=False, keep_changelists: bool=False, include_parents: bool=False, add_unversioned: bool=False, add_ignored: bool=False, auto_delete_missing: bool=False, fail_on_conflicts: bool=True) -> CommitResult
```

### SVNRepo.copy

```text
copy(srcs: Sequence[Union[str, Path]], dest: Union[str, Path], *, revision: Optional[int]=None, parents: bool=False, force: bool=False, message: Optional[str]=None, message_file: Optional[Union[str, Path]]=None) -> Optional[CommitResult]
```

### SVNRepo.move

```text
move(srcs: Sequence[Union[str, Path]], dest: Union[str, Path], *, parents: bool=False, force: bool=False, message: Optional[str]=None, message_file: Optional[Union[str, Path]]=None) -> Optional[CommitResult]
```

### SVNRepo.cleanup

```text
cleanup(paths: Sequence[Union[str, Path]] | None=None, *, remove_unversioned: bool=False, remove_ignored: bool=False, include_externals: bool=False) -> None
```

### SVNRepo.export

```text
export(dest: Union[str, Path], src: Union[str, Path] | None=None, *, revision: Optional[int]=None, force: bool=False, ignore_externals: bool=False, ignore_keywords: bool=False) -> None
```

## 返回模型

模型从 pysvnlite 顶层导出；Optional 字段可能因原生输出缺失而为 None。

### RepoInfo

字段：`url`、`repo_root_url`、`repo_uuid`、`wc_root`、`revision`、`node_kind`、`last_changed_rev`、`last_changed_author`、`last_changed_date`。

### LogPathChange

字段：`action`、`path`、`copy_from_path`、`copy_from_rev`。

### LogEntry

字段：`revision`、`author`、`date`、`message`、`changed_paths`。

### LogEntryStart

字段：`revision`。

### LogPathChangeEvent

字段：`revision`、`change`。

### LogEntryEnd

字段：`revision`、`author`、`date`、`message`、`changed_paths_count`。

### CommitSummary

字段：`added`、`modified`、`deleted`、`missing`、`conflicted`、`tree_conflicted`、`unversioned`。

### CommitResult

字段：`success`、`revision`、`stdout`、`stderr`、`returncode`、`pre_summary`、`changed_paths`。

### StatusItem

字段：`path`、`wc_status`、`repos_status`、`locked`、`switched`、`copied`、`tree_conflicted`、`revision`、`commit_rev`、`commit_author`、`commit_date`。

### ListEntry

字段：`kind`、`name`、`size`、`commit_rev`、`commit_author`、`commit_date`。

### BlameLine

字段：`line_number`、`revision`、`author`、`date`、`content`。

LogEvent 是 LogEntryStart、LogPathChangeEvent、LogEntryEnd 的联合类型，不是另一种运行时模型。事件顺序与有界日志语义见[使用指南](basic-usage.md)。
