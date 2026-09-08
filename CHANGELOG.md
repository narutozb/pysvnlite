# 变更日志

## 0.2.1 - 2026-09-08

- 整理首页和导航，新增独立安装、升级、离线、旧捆绑版迁移与维护发布指南。
- 补充完整 SVNRepo 方法签名、返回模型、异常与 CommitResult 处理边界。
- 修正空日志分页、跨平台示例路径、未定义事件处理函数及提交结果检查；同步删除示例默认要求人工确认删除。
- 明确 revision=None 不足以判断未提交，原始错误字段需脱敏，日志事件不是实时网络流。
- 新增文档链接、Python 示例语法和 API 签名一致性测试；运行时 API、源码与依赖不变。

## 0.2.0 - 2026-09-07

- 从 `svnpypi v0.1.7` 完整拆出 SVN 封装、解析器、模型和对应测试，作为独立 GitHub/PyPI 项目维护；保留已有导入方式和 Python >=3.9 兼容性。
- 增加 `py.typed`，使依赖本库的项目可以直接检查类型。
- 对应原项目 Issue #20：`run_svn` 的常规 checkout/co 调用与 `SVNRepo.checkout` 在原生客户端报告成功后核对预期 `.svn`；路径不符时抛出 `SVNCommandError`，保留原始输出和错误目录供排查。
- 记录 Windows ACP936 / TortoiseSVN 1.14.5 中文绝对路径误解码的实测限制，不修改系统 locale，也不自动删除或搬移错误生成的目录。
- 迁移并强化独立 CI、真实本地 SVN 测试、发布标签保护、构建内容白名单与隔离导入检查；构建包不包含 AI 文件或 svnpypi 源码。

拆分前历史见 [svnpypi v0.1.7 变更日志](https://github.com/narutozb/svnpypi/blob/v0.1.7/CHANGELOG.md)。
