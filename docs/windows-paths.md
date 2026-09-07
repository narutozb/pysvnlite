# Windows 中文路径兼容性

对应 [svnpypi Issue #20](https://github.com/narutozb/svnpypi/issues/20)。

## 实测结论

2026-09-07 在 Windows、系统 ACP936、Python 3.14、TortoiseSVN 的 svn 1.14.5 上复现：中文绝对目标路径的 checkout 返回 0，但工作副本被建在乱码同级目录。原生 `svnadmin` 也存在绝对中文路径问题；设中文目录为 cwd 并传相对 ASCII 参数可建库。

对照试验分别继承、移除 LANG/LC_ALL/LC_CTYPE，并尝试 C、系统中文 locale、.UTF-8 和 en_US.UTF-8，均未消除检出目标误解码。因此本库不把修改环境变量作为修复，也不对这些客户端承诺中文绝对路径支持。

这不是仅有终端显示乱码：检查真实路径下的 `.svn` 才能发现错误。

## 0.2.0 的处理

- `SVNRepo.checkout(url, dest)` 成功返回前检查 `dest/.svn`。
- 文本 runner `run_svn()` 对识别到的 checkout/co 命令、常用 SVN 选项、显式/隐式目标、多 URL 目标执行相同检查。
- 不符合预期时抛出 `SVNCommandError`，returncode 为 -1，stdout 保留客户端原始成功输出，stderr 明确给出预期路径和客户端兼容性提示。
- 不自动删除、改名或移动任何错误目录，避免破坏已有工作。

这是防止虚假成功的诊断保护，不是原生客户端字符转换补丁。底层 runner 不重新实现全部 SVN 参数解析；未知的新选项、二进制/滚盘 runner 和其他命令仍只保证原生命令执行语义。需要检出后置条件保证时使用 `SVNRepo.checkout`。`.svn` 存在也不代表所有内容或 externals 均已通过业务验收。

## 使用建议

受影响客户端使用完全 ASCII 的工作副本路径（包括父目录）。包注册 CLI 的临时目录同样应位于 ASCII 路径；在进程启动前将 TEMP/TMP 指向已有且可写的 ASCII 目录。URL 中文段使用正确的百分号编码，但这不能修复本地目标路径转换。

更换原生 SVN 客户端后，在临时仓库重新验证预期目录、`info/status/add/commit/update` 和内容，再扩大使用。不要只凭退出码或更改控制台编码判断修复完成。未验证所有 Windows locale、客户端构建、远端认证组合或 macOS。

原生字符转换机制参考 [Apache Subversion 命令行 API](https://subversion.apache.org/docs/api/latest/svn__cmdline_8h.html)；本机故障结论来自真实文件系统对照测试，并非由文档推断。
