# pysvnlite

Python 的 Subversion 命令行封装与 XML 解析库，提供仓库查询、历史读取和工作副本管理 API。

当前版本：**0.2.2**。Python >=3.9，无第三方运行时依赖，包含类型标记 `py.typed`。

## 安装

系统需安装 Subversion，并将 `svn` 加入 `PATH`。

```bash
python -m pip install "pysvnlite==0.2.2"
svn --version --quiet
```

## 使用

```python
from pysvnlite import SVNRepo

repo = SVNRepo("https://svn.example.com/project/trunk", timeout=30)

for entry in repo.list():
    print(entry.kind, entry.name)

for entry in repo.log(limit=10, verbose=True):
    print(entry.revision, entry.author, entry.changed_paths)
```

## 功能

- 仓库查询：信息、目录、状态、属性。
- 历史读取：日志、路径变更、历史文件、差异、逐行归属。
- 工作副本：检出、更新、切换、添加、删除、还原、提交。
- 仓库操作：复制、移动、建目录、导出、锁定与解锁。
- 执行控制：结构化错误、可选超时、日志输出上限、文件原子下载。

## 行为约定

- SVN 调用使用 `--non-interactive`；认证、证书和 SSH 配置由原生客户端管理。
- `timeout=None` 表示不限时。超时后的进程清理不回滚已完成的远端提交。
- `commit` 的普通失败可返回 `CommitResult(success=False)`；前置操作和执行失败也可能抛出异常。
- `cat` 返回完整文件的 `bytes`；`cat_to_file` 下载成功后原子替换目标，失败保留原文件。
- 日志迭代器在捕获完成后解析输出；`max_output_bytes` 控制原始日志输出上限。

## 文档

- [安装与升级](https://github.com/narutozb/pysvnlite/blob/main/docs/installation.md)
- [使用示例](https://github.com/narutozb/pysvnlite/blob/main/docs/basic-usage.md)
- [API 参考](https://github.com/narutozb/pysvnlite/blob/main/docs/api-reference.md)
- [Windows 路径兼容性](https://github.com/narutozb/pysvnlite/blob/main/docs/windows-paths.md)
- [维护与发布](https://github.com/narutozb/pysvnlite/blob/main/docs/releasing.md)
- [变更日志](https://github.com/narutozb/pysvnlite/blob/main/CHANGELOG.md)

## 许可

[MIT License](https://github.com/narutozb/pysvnlite/blob/main/LICENSE)
