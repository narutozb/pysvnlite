# 使用示例

示例使用测试仓库 URL 和路径。写操作会修改工作副本或提交远端。方法签名、返回模型与异常见 [API 参考](api-reference.md)。

## 目录与日志

```python
from pysvnlite import SVNRepo

repo = SVNRepo("https://svn.example.com/project/trunk", timeout=30)

for entry in repo.list():
    print(entry.kind, entry.name)

for entry in repo.log(limit=5, verbose=True):
    print(entry.revision, entry.author, entry.message, entry.changed_paths)

page1 = repo.log(limit=50)
page2 = []
if page1 and page1[-1].revision > 0:
    page2 = repo.log(limit=50, revision=f"{page1[-1].revision - 1}:0")
```

`revision` 对应 `svn log -r`，支持修订范围和 SVN 日期语法。`verbose=True` 返回变更路径。
`list` 默认不包含 `svn:externals`；`ignore_externals` 参数保留兼容，但不传递给原生 SVN。

## 有界日志

```python
from pathlib import Path
from pysvnlite import SVNRepo

repo = SVNRepo("https://svn.example.com/project", timeout=120)
spool_dir = Path(".svn-log-spool").resolve()
spool_dir.mkdir(parents=True, exist_ok=True)

entries = repo.iter_log(
    limit=100,
    revision="HEAD:1",
    verbose=True,
    max_output_bytes=512 * 1024 * 1024,
    spool_dir=spool_dir,
)
try:
    for entry in entries:
        print(entry.revision, len(entry.changed_paths))
finally:
    entries.close()
```

`log()` 返回列表，`iter_log()` 按修订返回 `LogEntry`。单个修订的变更路径仍保存在该模型中。
`iter_log_events()` 按路径返回事件，适用于单个修订包含大量变更路径的情况：

```python
from pysvnlite import LogEntryEnd, LogEntryStart, LogPathChangeEvent

events = repo.iter_log_events(
    limit=100,
    verbose=True,
    max_output_bytes=512 * 1024 * 1024,
    spool_dir=spool_dir,
)
try:
    for event in events:
        if isinstance(event, LogEntryStart):
            print("begin", event.revision)
        elif isinstance(event, LogPathChangeEvent):
            print("path", event.revision, event.change.path)
        elif isinstance(event, LogEntryEnd):
            print("end", event.revision, event.changed_paths_count)
finally:
    events.close()
```

事件顺序为 `LogEntryStart`、零到多个 `LogPathChangeEvent`、`LogEntryEnd`。
SVN 输出先写入内存缓冲，超过阈值后滚盘，捕获完成后再增量解析 XML。

- `max_output_bytes` 限制原始 stdout 字节数；超限终止 SVN 并抛出 `SVNOutputLimitError`。
- `max_output_bytes=None` 不设置硬上限。
- `spool_dir=None` 使用系统临时目录；指定目录需已存在、可写且有足够空间。
- `timeout` 包含等待 SVN 准备输出的时间，不包含捕获后的 XML 解析。

`bounded_verbose_log_v1`、spool 和输出预算不是原生 SVN 的 RAM 上限。
[SVN 1.14.5](https://github.com/apache/subversion/blob/1.14.5/subversion/svn/log-cmd.c#L494-L652) 会先在进程内组装一个修订的 XML，再写入 stdout。
路径级事件和 `limit=1` 均不能拆分这个内部缓冲；尚未输出的数据不受字节预算限制。
示例预算仅展示参数用法，不代表已验证对应规模的单修订峰值内存。

## 历史文件

```python
from pathlib import Path
from pysvnlite import SVNRepo

repo = SVNRepo("https://svn.example.com/project", timeout=30)
url = "https://svn.example.com/project/assets/deleted.bin"

repo.cat_to_file(url, Path("deleted.bin"), revision=120, peg=120)
info = repo.info(url, revision=120, peg=120)
print(info.last_changed_rev)
```

`revision` 指定内容修订，`peg` 定位历史对象。HEAD 中已删除或改名的路径使用其仍存在时的 `peg`。
`cat()` 返回 `bytes`；`cat_to_file()` 流式写入临时文件，成功后原子替换目标。

文件名中间的 `@` 会自动添加空 peg 消歧：

```python
url = "https://svn.example.com/project/assets/model@lod2.bin"
current = repo.cat(url)
historical = repo.cat(url, revision=120, peg=120)
```

0.2.3 起修复了末尾字面量 `@` 的 `Path` 输入，包括 `SVNRepo(Path(...))` 的默认读取目标。
`status()` 从 0.2.4 起使用同一字面路径规则；不支持历史 peg 查询，字符串末尾 `@` 保留空 peg 语义。
字符串兼容旧的末尾空 peg 写法；原始字符串或 URL 本身以 `@` 结尾时，显式传入 `peg=""` 或数字修订：

```python
path = Path("working-copy/asset.txt@")
current = repo.cat(path, peg="")
historical = repo.cat(str(path), revision=120, peg=120)
```

上例的显式 peg 写法也适用于 0.2.2；写入方法不承诺相同的 `@` 消歧行为。

### 内容读取预算

0.2.3 起支持可选的内容读取预算：

```python
repo.cat_to_file(
    url, Path("bounded.bin"), revision=120, peg=120,
    max_output_bytes=16 * 1024 * 1024,
)
```

`cat` 和 `cat_to_file` 接受非负整数预算，`None` 保留无限制行为，0 只允许空内容。
恰好达到预算可成功；捕获期间超限抛出 `SVNOutputLimitError` 并终止进程，不返回截断结果。
启用预算时使用有界内存缓冲与滚盘；文件下载在捕获成功后复制到同目录临时文件并原子替换，可能同时占用两份受预算限制的磁盘空间。失败保留旧目标并清理临时文件。

## 工作副本提交

```python
from pathlib import Path
from pysvnlite import SVNRepo

working_copy = Path("working-copy").resolve()
wc = SVNRepo(working_copy, timeout=30)
new_file = working_copy / "new.txt"
new_file.write_text("hello\n", encoding="utf-8")

wc.add([new_file])
result = wc.commit(message="Add new.txt", paths=[new_file])
if not result.success:
    raise RuntimeError("Commit failed")
print(result.revision)
```

`fail_on_conflicts=True` 默认阻止存在文本冲突或树冲突的提交。
`revision=None` 可能表示没有新提交，也可能表示客户端回显未解析出修订号；成功状态以 `result.success` 为准。

0.2.3 起将显式 `paths` 的状态摘要、冲突检查、自动 add/delete/revert 限定于所选目标；相对路径以进程工作目录为基准，空列表保留默认目标行为。
自动准备递归处理所选子树，`depth` 仍只限制最终 SVN 提交。浅层提交需关闭自动开关，显式准备文件清单。
准备操作会修改工作副本，后续提交失败不会自动撤销；0.2.2 使用部分路径提交时需关闭 `add_unversioned` / `auto_delete_missing`，避免修改未选中的路径。

URL 形式的 `mkdir()` / `delete()` 立即提交，且必须提供 `message` 或 `message_file` 中的一项：

```python
repo = SVNRepo("https://svn.example.com/project", timeout=30)
repo.mkdir(
    ["https://svn.example.com/project/assets"],
    parents=True,
    message="Create asset directory",
)
repo.delete(
    ["https://svn.example.com/project/assets/obsolete"],
    message="Remove obsolete assets",
)
```

工作副本形式仅调度本地变更，不接受提交信息。同一次调用不能混合 URL 和工作副本路径；无效参数组合抛出 `ValueError`。

## 二进制文件

向已有工作副本复制文件、设置 MIME 类型并提交：

```python
import shutil
from pathlib import Path
from pysvnlite import SVNRepo

source = Path("data/sample.bin")
working_copy = Path("working-copy").resolve()
target = working_copy / source.name
wc = SVNRepo(working_copy, timeout=120)

shutil.copy2(source, target)
wc.add([target], force=True)
wc.propset("svn:mime-type", "application/octet-stream", target)
result = wc.commit(message="Update binary file", paths=[target])
if not result.success:
    raise RuntimeError("Commit failed")
print(result.revision)
```

二进制文件的内容完整性可通过源文件与检出文件的 SHA256 比较验证。

## 错误与超时

```python
from pysvnlite import SVNCommandError, SVNRepo

repo = SVNRepo("https://svn.example.com/project", timeout=30)
try:
    repo.list()
except SVNCommandError as exc:
    print(exc.category, exc.returncode, str(exc))
```

`timeout=None` 不限制执行时间；超时分类为 `timeout`。进程清理不回滚已完成的提交。
缺失或无法打开的本地 `file://` 仓库归类为 `not_found`，远端连接失败归类为 `network`。
