# Windows 路径兼容性

## 子进程窗口

当前源码新增 `hide_window=False`，尚未包含在 PyPI 0.2.3 中。GUI 宿主可显式使用 `SVNRepo(target, hide_window=True)`；静态 checkout 和 run_svn、run_svn_bytes、run_svn_spooled、run_svn_to_file 也接受同名关键字参数。

Windows 启用时使用 CREATE_NO_WINDOW 与原有 CREATE_NEW_PROCESS_GROUP 的组合，保持非交互输入、输出捕获、超时和进程树清理。其他平台忽略窗口设置，默认 False 不改变既有行为。此选项不隐藏宿主自身的窗口，也不控制 SSH 客户端或其他外部程序的独立 GUI。

测试包含 pythonw 无父控制台宿主的真实临时 SVN 操作及进程标志、输出、清理检查；UE、Photoshop 和 PyInstaller 的具体宿主行为仍需下游验收，不等同于全部桌面环境的人工闪窗验证。

参考：[Microsoft 进程创建标志](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags)。

## 已知问题

在 Windows ACP936、Python 3.14、TortoiseSVN svn 1.14.5 环境中，中文绝对路径检出可能返回成功，却将工作副本创建到乱码目录。2026-09-07 的本地测试确认这是实际文件路径错误，调整 `LANG`、`LC_ALL`、`LC_CTYPE` 未能消除问题。

同一环境的 `svnadmin` 也存在中文绝对路径问题；以中文目录为工作目录、传入相对 ASCII 路径可正常建库。

## 检出检查

- `SVNRepo.checkout(url, dest)` 在成功返回前检查 `dest/.svn`。
- 文本入口 `run_svn()` 对识别到的 `checkout` / `co` 调用执行相同检查。
- 目标缺少 `.svn` 时抛出 `SVNCommandError`，`returncode=-1`；`stdout` 保留原始输出，`stderr` 包含预期路径。
- 错误创建的目录保留原状，不自动删除、改名或移动。

此检查仅验证工作副本路径，不修复原生客户端编码，也不验证全部内容和 externals。底层参数识别不覆盖所有 SVN 选项；需要检出路径检查时使用 `SVNRepo.checkout()`。

## 工作副本文件参数

[Issue #8](https://github.com/narutozb/pysvnlite/issues/8) 记录了 Windows ACP/OEMCP 936、TortoiseSVN 1.14.5 的另一个限制：遍历 ASCII 父目录能列出中文文件，但直接传入中文文件路径时，`status --xml` 可能返回错误目标或空状态，`info` 可能报 W155010/E200009。相对路径、正斜杠和 locale 环境变量未解决该报告中的问题。

只读排查可对比 `svn status --xml --verbose <ASCII父目录>`、`svn status --xml <文件>` 和 `svn info --xml <文件>` 的目标路径，并保留原始 XML。空状态不能单独证明文件无修改；这也不表示 Python 改坏了 argv。

库不自动将文件目标提交改成父目录提交。人工采用父目录操作前，需确认完整状态中没有其他待提交内容。检出 `.svn` 检查不覆盖这些文件参数问题。

## diff 编码

[Issue #9](https://github.com/narutozb/pysvnlite/issues/9) 报告同一客户端在读取百分号编码 URL 时，XML 路径正确，但原始 diff 标题中的中文已变成 `?`。该现象发生在 Python 解码之前，不能通过再次解码恢复。

`diff()` 返回原生 stdout 字节：标题路径使用客户端输出编码，正文块保留文件内容编码，整段输出不一定共享一种编码。`bytes` 契约不等于 Unicode 路径无损保证；原始字节中的 `?` 也不能单独作为故障判据。

只读诊断需对比同一 URL、revision 和 peg 的 XML 元数据及 diff 原始标题字节。库不猜测标题路径，不全局强制 CP936/UTF-8 解码，不修改系统代码页。
[SVN 1.14.5 diff 实现](https://github.com/apache/subversion/blob/1.14.5/subversion/svn/diff-cmd.c) 从命令行环境取得标题编码；当前 API 不提供强制 UTF-8 标题参数。

## 路径配置

受影响客户端的工作副本及其父目录使用 ASCII 路径。需要临时目录的程序将 `TEMP` / `TMP` 指向已有且可写的 ASCII 目录。URL 中的非 ASCII 路径段使用百分号编码；URL 编码与本地路径转换分别处理。

更换客户端后，使用临时仓库检查目标路径及 `info`、`status`、`add`、`commit`、`update` 的结果。上述实测范围不覆盖其他 Windows locale、客户端构建或远端认证方式。

参考：[Apache Subversion 命令行 API](https://subversion.apache.org/docs/api/latest/svn__cmdline_8h.html)。
