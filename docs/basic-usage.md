# API 使用速查

本章给出独立发行包 `pysvnlite` 的常见调用样例：

```bash
python -m pip install pysvnlite
```

## 1) 列目录与查看日志

```python
from pysvnlite import SVNRepo

repo = SVNRepo(
    "svn+ssh://svn.company.com/python-packages/release",
    timeout=30,
)

entries = repo.list()
for item in entries:
    print(item.kind, item.name)

for log in repo.log(limit=5, verbose=True):
    print(log.revision, log.author, log.message)
    print(log.changed_paths)

# 继续读取更早的 50 条历史，避免重新拉取前一页。
page1 = repo.log(limit=50)
oldest = page1[-1].revision
page2 = repo.log(limit=50, revision=f"{oldest - 1}:0")
```

`revision` 会原样传给 `svn log -r`，因此也支持 `HEAD:1`、`100:50` 和 SVN 日期修订语法。`verbose=False` 是默认值，可保持原有日志查询开销；需要 `changed_paths` 时显式启用。

### 有界日志与路径级事件

需要读取大型 verbose 历史时，可以在任何 SVN I/O 前检查稳定能力标记：

```python
from pathlib import Path

from pysvnlite import CAPABILITIES, SVNRepo

if "bounded_verbose_log_v1" not in CAPABILITIES:
    raise RuntimeError("当前 pysvnlite 不支持有界 verbose 日志")

repo = SVNRepo("svn+ssh://svn.company.com/project", timeout=120)
entries = repo.iter_log(
    limit=100,
    revision="HEAD:1",
    verbose=True,
    max_output_bytes=512 * 1024 * 1024,
    spool_dir=Path("D:/customsvn3-spool"),
)
for entry in entries:
    print(entry.revision, len(entry.changed_paths))
```

`log()` 仍保持原签名默认值和 `List[LogEntry]` 返回类型，同时接受
`max_output_bytes` 与 `spool_dir`。`iter_log()` 返回相同模型的 iterator，但一个
`LogEntry` 仍需保存该 revision 的全部 `changed_paths`。单 revision 可能包含海量路径时，
应使用路径级事件：

```python
from pysvnlite import LogEntryEnd, LogEntryStart, LogPathChangeEvent

events = repo.iter_log_events(
    limit=None,
    revision="500000:1",
    verbose=True,
    max_output_bytes=4 * 1024**3,
    spool_dir="D:/customsvn3-spool",
)
try:
    for event in events:
        if isinstance(event, LogEntryStart):
            begin_revision(event.revision)
        elif isinstance(event, LogPathChangeEvent):
            append_changed_path(event.revision, event.change)
        elif isinstance(event, LogEntryEnd):
            finish_revision(event)
finally:
    events.close()
```

事件顺序固定为 `LogEntryStart`、零到多个 `LogPathChangeEvent`、`LogEntryEnd`。
调用方可分批保存 path，而不必在 Python 中构造完整 path 列表。

实现会先把 SVN stdout 写入内存阈值有限、随后滚盘的 spool，再从 spool 增量解析 XML；
因此不会在网络读取期间提前产生事件。`max_output_bytes` 按原始 stdout 字节计数，首个
越界字节会终止 SVN 并抛出 `SVNOutputLimitError`，其基类仍是 `SVNCommandError`，
`category` 为 `output_limit`。`None` 保持兼容，表示不设置硬字节上限。

`spool_dir=None` 使用操作系统临时目录。大范围或单 revision 超大日志应显式指定有足够
空间的本地卷，并设置硬字节上限。`timeout` 仍只覆盖 SVN 子进程运行时间，不包含之后的
XML 解析。Windows 上会同时排空 stdout/stderr，避免 pipe 写满；直接 SVN 子进程会被回收，
但尚未声称覆盖所有 `ssh` / `plink` 后代进程组合。

`svn list` 默认不包含 `svn:externals`。为兼容已有调用，`list(ignore_externals=True)` 仍可使用，但不会向 SVN 传递额外选项。

## 2) 读取历史文件（二进制与 peg revision）

```python
from pathlib import Path
from pysvnlite import SVNRepo

repo = SVNRepo("svn+ssh://svn.company.com/project")
url = "svn+ssh://svn.company.com/project/assets/deleted.ma"

data = repo.cat(url, revision=120, peg=120)
Path("/tmp/deleted.ma").write_bytes(data)

info = repo.info(url, revision=120, peg=120)
print(info.last_changed_rev)
```

`revision` 是要读取内容的 operative revision；`peg` 用于确定历史中的对象。路径在 HEAD 已删除或改名时，应传入它仍然存在的 peg revision。`list`、`log`、`cat_to_file`、`blame` 与 `diff` 同样支持 `peg`。

目标文件名可以包含 `@`，调用方应传入原始 URL 或工作副本路径，无需手工追加尾随 `@`。`pysvnlite` 会在未显式传入 `peg` 时自动消歧；需要指定 peg revision 时使用独立参数：

```python
url = "svn+ssh://svn.company.com/project/assets/hero@lod2.ma"
current = repo.cat(url)
historical = repo.cat(url, revision=120, peg=120)
```

## 3) 工作副本提交

```python
from pathlib import Path
from pysvnlite import SVNRepo

wc = SVNRepo("/path/to/working-copy")
new_file = Path("/path/to/working-copy/new.txt")
new_file.write_text("hello\n", encoding="utf-8")

wc.add([new_file])
result = wc.commit(message="Add new.txt")
print(result.success, result.revision)
```

默认的 `fail_on_conflicts=True` 会在提交前检查文本冲突和 tree conflict。tree conflict 条目仍会同时保留其 `added`、`modified` 等内容状态，便于调用方展示完整摘要。

URL 形式的 `mkdir()` / `delete()` 会立即提交，因此必须且只能提供 `message` 或
`message_file` 之一；工作副本路径仍只产生本地调度变更：

```python
repo = SVNRepo("svn+ssh://svn.company.com/project")
repo.mkdir(
    ["svn+ssh://svn.company.com/project/assets/fbx"],
    parents=True,
    message="Create FBX asset directory",
)
repo.delete(
    ["svn+ssh://svn.company.com/project/assets/obsolete"],
    message_file="delete-message.txt",
)
```

同一次调用不能混合仓库 URL 与工作副本路径。缺少提交信息、同时提供两种提交信息，
或为工作副本操作提供提交信息时，会在调用 SVN 前抛出 `ValueError`。

## 4) 发布任意二进制制品

`svnpypi upload` 是 Python 包注册表入口，只接受标准 wheel / sdist。FBX、模型、
测试语料和其他任意文件应放在独立 SVN 路径，并直接使用 `pysvnlite`。下面是平铺目录的
幂等同步示例：本地新增文件会 add，本地删除文件会在提交前调度 delete，内容不变时
`revision` 为 `None`，不会生成新修订。

```python
import shutil
from pathlib import Path

from pysvnlite import SVNCommandError, SVNRepo

source_dir = Path("testdata")
working_copy = Path(".svn-assets/fbxkit-testdata")
repository_root = "svn+ssh://svn.company.com/project"
asset_url = f"{repository_root}/fbxkit-testdata"

remote = SVNRepo(repository_root, timeout=120)
try:
    remote.info(asset_url)
except SVNCommandError as exc:
    if exc.category != "not_found":
        raise
    remote.mkdir(
        [asset_url],
        parents=True,
        message="Create FBX test corpus",
    )

if (working_copy / ".svn").is_dir():
    wc = SVNRepo(working_copy, timeout=120)
    wc.update()
else:
    working_copy.parent.mkdir(parents=True, exist_ok=True)
    wc = SVNRepo.checkout(asset_url, working_copy, timeout=120)

source_files = {
    path.name: path
    for path in source_dir.iterdir()
    if path.is_file()
}
for target in working_copy.iterdir():
    if target.is_file() and target.name not in source_files:
        target.unlink()

copied = []
for name, source in source_files.items():
    target = working_copy / name
    shutil.copy2(source, target)
    copied.append(target)

if copied:
    wc.add(copied, force=True)
for target in copied:
    if target.suffix.lower() == ".fbx":
        wc.propset("svn:mime-type", "application/octet-stream", target)

result = wc.commit(
    message="Synchronize FBX test corpus",
    auto_delete_missing=True,
)
print(result.success, result.revision)
```

示例只同步工作副本根目录中的普通文件。递归镜像目录时必须明确排除 `.svn`，并先在临时
仓库验证删除集合。二进制文件应显式设置 `svn:mime-type=application/octet-stream`，
避免客户端自动属性或文本转换规则造成内容变化；发布后仍建议按 SHA256 复核检出文件。

## 5) 错误处理建议

`pysvnlite` 会把 `svn` 失败包装成 `SVNCommandError`。`timeout` 默认是 `None`，不会改变慢速 SVN 环境的现有行为；GUI、服务端或批处理任务可以按预算显式设置：

```python
from pysvnlite import SVNCommandError, SVNRepo

repo = SVNRepo(
    "svn+ssh://svn.company.com/python-packages/release",
    timeout=30,
)

try:
    repo.list()
except SVNCommandError as exc:
    if exc.is_timeout_error:
        print("SVN 查询超时，可以稍后重试")
    else:
        print(exc.category, exc.returncode, exc.stderr)
```

缺失或无法打开的本地 `file://` 仓库归类为 `not_found`；远端连接失败仍归类为
`network`，调用方不应对前者执行网络重试。
