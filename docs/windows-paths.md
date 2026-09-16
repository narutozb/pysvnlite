# Windows 路径兼容性

## 已知问题

在 Windows ACP936、Python 3.14、TortoiseSVN svn 1.14.5 环境中，中文绝对路径检出可能返回成功，却将工作副本创建到乱码目录。2026-09-07 的本地测试确认这是实际文件路径错误，调整 `LANG`、`LC_ALL`、`LC_CTYPE` 未能消除问题。

同一环境的 `svnadmin` 也存在中文绝对路径问题；以中文目录为工作目录、传入相对 ASCII 路径可正常建库。

## 检出检查

- `SVNRepo.checkout(url, dest)` 在成功返回前检查 `dest/.svn`。
- 文本入口 `run_svn()` 对识别到的 `checkout` / `co` 调用执行相同检查。
- 目标缺少 `.svn` 时抛出 `SVNCommandError`，`returncode=-1`；`stdout` 保留原始输出，`stderr` 包含预期路径。
- 错误创建的目录保留原状，不自动删除、改名或移动。

此检查仅验证工作副本路径，不修复原生客户端编码，也不验证全部内容和 externals。底层参数识别不覆盖所有 SVN 选项；需要检出路径检查时使用 `SVNRepo.checkout()`。

## 路径配置

受影响客户端的工作副本及其父目录使用 ASCII 路径。需要临时目录的程序将 `TEMP` / `TMP` 指向已有且可写的 ASCII 目录。URL 中的非 ASCII 路径段使用百分号编码；URL 编码与本地路径转换分别处理。

更换客户端后，使用临时仓库检查目标路径及 `info`、`status`、`add`、`commit`、`update` 的结果。上述实测范围不覆盖其他 Windows locale、客户端构建或远端认证方式。

参考：[Apache Subversion 命令行 API](https://subversion.apache.org/docs/api/latest/svn__cmdline_8h.html)。
