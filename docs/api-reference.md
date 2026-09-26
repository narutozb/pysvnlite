# API 参考

当前源码的 [SVNRepo](../src/pysvnlite/repo.py)及[模型定义](../src/pysvnlite/models.py)。签名省略 `self`；`Revision = Union[int, str]`，`Path` 来自 `pathlib`，集合类型来自 `typing`。

修订属性写入的 `revision`、批量目标文件及启动错误分类尚未发布；正式包请查阅对应发行标签的文档。

## 调用约定

- 构造函数保存目标路径或 URL，不执行检出。方法默认使用实例 `target`；显式相对路径通常以进程工作目录为基准，绝对路径不受工作目录影响。
- `checkout` 为静态方法，`target` / `timeout` 是只读属性。`CAPABILITIES` 包含 `bounded_verbose_log_v1`，也可通过 `SVNRepo.CAPABILITIES` 查询。
- `revision` 指定内容修订，`peg` 定位历史对象。`peg` 参数和 `@` 消歧仅适用于支持它们的方法。
- 读取方法的 `Path` 输入始终按字面路径处理。字符串末尾 `@` 保留旧的空 peg 语义；末尾字面量 `@` 使用 `peg=""` 或具体修订消歧。
- `propset` / `propdel` 的 `revprop=True` 必须显式提供 revision；普通属性写入不能提供 revision。数值、HEAD 或日期表达式原样交给 SVN 解析，不自动查询或补充修订。修改修订属性仍需仓库允许 `pre-revprop-change` 钩子，库不修改钩子或权限。
- `status()` 不接受历史 peg；字面量 `@` 路径使用 `Path`，字符串末尾 `@` 仍表示原生空 peg。它只添加必要的空 peg 转义，不猜测修订或改查父目录。
- URL `mkdir/delete` 必须且只能提供 message 或 message_file，并立即提交；工作副本形式不接受提交信息，只调度本地变更。
- URL `copy/move` 返回 CommitResult；工作副本操作返回 None。多次方法调用不组成事务。
- `cat` / `diff` 返回 bytes；`cat_to_file` 原子替换成功结果。list 的 ignore_externals 参数保留兼容，但不会传给原生 SVN。
- `cat` / `cat_to_file` 的可选 `max_output_bytes` 限制捕获的 stdout，超限抛出 SVNOutputLimitError；默认 None 不设上限，0 仅允许空内容。此参数从 0.2.3 起提供。
- `diff` 原样返回原生客户端输出，标题与正文可能使用不同编码；bytes 不保证 Unicode 文件名无损。见 [Windows 编码限制](windows-paths.md)。
- `log` 返回列表，`iter_log` 按 revision 返回模型，`iter_log_events` 按路径返回事件；两种 iterator 都先完成 stdout 捕获再解析。需要限制日志大小时设置 max_output_bytes，并确保 spool_dir 已存在且可写。
- `blame` 只解析 XML 元数据，BlameLine.content 不提供文件正文，需另行 cat。

日志预算与 spool 不限制原生 SVN 的 RAM；原生客户端可能先缓冲整个修订，路径级事件与 `limit=1` 不能拆分该缓冲。资源边界见[有界日志](basic-usage.md#有界日志)。

## 失败与提交结果

大多数命令的启动、非零返回码、超时和检出后置条件失败抛出 SVNCommandError。无效参数组合可能抛出 ValueError。启用预算的输出超限抛出其子类 SVNOutputLimitError，category 为 output_limit。

`commit` 的冲突阻断、自动清理失败或原生提交非零返回可能产生 `CommitResult(success=False)`；前置 status、add 或进程启动失败可能抛出异常。调用方需同时检查结果和异常。

显式 `paths` 的状态摘要与自动准备仅针对所选目标，不扩大到父目录；空列表使用实例目标。自动准备递归处理所选子树，`depth` 只限制最终提交。准备造成的工作副本修改不会自动回滚，浅层提交使用显式 add/delete 清单。

`fail_on_conflicts=True` 在准备操作前阻断内容、属性及树冲突；`CommitSummary.conflicted` 包含内容或属性冲突，树冲突仍单独记录。`StatusItem.wc_status` 保留原生内容状态，不用属性冲突覆盖它。

`revision=None` 可能表示没有新提交或未解析出修订号。提交后的日志补查失败时 `changed_paths` 可为空；审计数据需另行核对 SVN。

版本解析仅接受完整的已知提交完成行。不从进度行猜测数字，也不以提交后查询到的 HEAD 代替本次修订，以免并发提交串号。

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

`str(exc)` 会脱敏 URL userinfo。`cmd`、`stdout`、`stderr` 和 CommitResult 的原始字段需使用 `redact_url_credentials` 处理后记录；该函数不处理任意命令行密码参数。

`category` 包括 `timeout`、`authentication`、`authorization`、`network`、`not_found`、`property_not_found`、`unknown`、输出上限子类的 `output_limit` 和启动失败子类的 `process_start`。原生错误文本分类受客户端语言影响。检出路径异常通过 `stderr` 描述，详见 [Windows 路径兼容性](windows-paths.md)。

`SVNProcessStartError` 是 `SVNCommandError` 的子类，仅表示操作系统拒绝创建进程。保留 `returncode=-1`、原始 `OSError` 作为 `__cause__`，并暴露 `errno` / `winerror`（不可用时为 None）。例如 Windows 命令行过长的 `winerror=206` 不属于超时。捕获 `SVNCommandError` 的现有代码仍适用；文件写入、原生非零退出或已启动进程的通信失败不属于此子类。

## 批量目标

`add`、`delete`、`revert`、`commit` 的 `targets_encoding=None` 保留原有 argv 传递。显式设置编码时，把原目标清单写入临时文件，通过 SVN 原生 `--targets` 执行；文件在成功、失败或超时后清理。调用方不需要创建目标文件。

- `targets_encoding` 必须对应实际 SVN 客户端读取目标文件的本地编码，库不检测或猜测编码。纯 ASCII 清单可使用 `"ascii"`；非 ASCII 清单须先在临时仓库核验客户端环境。Python UTF-8 模式不证明 SVN 也使用 UTF-8。
- 按指定编码严格写入，不替换不可表示的字符。为避免原生分行及裁剪改变目标，拒绝空字符串、行首尾空白、CR/LF/NUL，以及带 BOM 或非 ASCII 兼容的编码。目标顺序、重复项和原有 peg 写法保持不变，不自动修正路径。
- `commit` 仍只运行一次原生提交，不分批生成修订，不回退到父目录；status 仍逐一检查所选目标。自动 add/delete/revert 同样使用目标文件；在准备动作前检查已知准备目标的编码，准备不是事务，不保证失败后自动回滚。
- `paths=None` 或空列表仍遵循各方法原有默认规则。URL delete 的提交信息要求不变。
- 仅缩短目标部分的命令行，不解决超长单一路径、提交消息或其他参数。长提交信息使用 `message_file`。原生 Unicode 路径与 diff 限制仍见 [Windows 路径兼容性](windows-paths.md)。

```python
from pysvnlite import SVNRepo

repo = SVNRepo("working-copy", timeout=60)
result = repo.commit(
    message="Selected assets", paths=["working-copy/a.txt", "working-copy/b.txt"],
    add_unversioned=True, targets_encoding="ascii",
)
assert result.success, result.stderr
```

原生目标文件转换及分行行为见 [Subversion 1.14.5 命令行实现](https://github.com/apache/subversion/blob/1.14.5/subversion/svn/svn.c)。

## 完整方法签名

签名与源码通过文档测试校验。

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
cat(path_or_url: Union[str, Path], *, revision: Optional[Revision]=None, peg: Optional[Revision]=None, max_output_bytes: Optional[int]=None) -> bytes
```

### SVNRepo.cat_to_file

```text
cat_to_file(path_or_url: Union[str, Path], output_path: Union[str, Path], *, revision: Optional[Revision]=None, peg: Optional[Revision]=None, max_output_bytes: Optional[int]=None) -> None
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
add(paths: Sequence[Union[str, Path]] | None=None, *, force: bool=True, no_ignore: bool=False, depth: Optional[str]=None, targets_encoding: Optional[str]=None) -> None
```

### SVNRepo.revert

```text
revert(paths: Sequence[Union[str, Path]], *, depth: Optional[str]=None, include_parents: bool=False, targets_encoding: Optional[str]=None) -> None
```

### SVNRepo.delete

```text
delete(paths: Sequence[Union[str, Path]], *, force: bool=False, keep_local: bool=False, message: Optional[str]=None, message_file: Optional[Union[str, Path]]=None, targets_encoding: Optional[str]=None) -> None
```

### SVNRepo.mkdir

```text
mkdir(paths: Sequence[Union[str, Path]], *, parents: bool=False, message: Optional[str]=None, message_file: Optional[Union[str, Path]]=None) -> None
```

### SVNRepo.propset

```text
propset(name: str, value: str, path: Union[str, Path], *, revprop: bool=False, revision: Optional[Revision]=None) -> None
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
propdel(name: str, path: Union[str, Path], *, revprop: bool=False, revision: Optional[Revision]=None) -> None
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
commit(*, message: Optional[str]=None, message_file: Optional[Union[str, Path]]=None, paths: Optional[Sequence[Union[str, Path]]]=None, depth: Optional[str]=None, no_unlock: bool=False, keep_changelists: bool=False, include_parents: bool=False, add_unversioned: bool=False, add_ignored: bool=False, auto_delete_missing: bool=False, fail_on_conflicts: bool=True, targets_encoding: Optional[str]=None) -> CommitResult
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

字段：`path`、`wc_status`、`repos_status`、`locked`、`switched`、`copied`、`tree_conflicted`、`revision`、`commit_rev`、`commit_author`、`commit_date`、`props_status`。

`props_status` 对应原生 `wc-status/@props`，缺少该属性时为 None，旧的位置参数构造方式不变。仅属性冲突时可同时出现 wc_status="normal" 与 props_status="conflicted"。

### ListEntry

字段：`kind`、`name`、`size`、`commit_rev`、`commit_author`、`commit_date`。

### BlameLine

字段：`line_number`、`revision`、`author`、`date`、`content`。

LogEvent 是 LogEntryStart、LogPathChangeEvent、LogEntryEnd 的联合类型，不是另一种运行时模型。事件顺序与有界日志语义见[使用指南](basic-usage.md)。
