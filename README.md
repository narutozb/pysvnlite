# pysvnlite

轻量、非交互的 Subversion 命令行封装和 XML 解析库。用于自动化脚本、资产历史查询与工作副本管理，不需要运行 SVN 包注册服务。

当前版本：**0.2.1**。本次为文档维护发布，保留 0.2.0 的 API 和运行时行为。

## 安装

要求 Python >=3.9 和 PATH 中可用的原生 `svn`。本库无第三方运行时依赖，包含 `py.typed`，不会安装 svnpypi CLI。生产请选择[仍受官方维护的 Python](https://devguide.python.org/versions/)。

在已激活的新虚拟环境中执行：

```bash
python -m pip install "pysvnlite==0.2.1"
python -c "from importlib.metadata import version; from pysvnlite import SVNRepo; print(version('pysvnlite'))"
```

**旧 svnpypi<=0.1.7 用户先看[安装与迁移](https://github.com/narutozb/pysvnlite/blob/main/docs/installation.md)。** 旧捆绑包与独立包拥有同名文件，普通升级或混装后卸载会破坏导入。推荐新环境；原地迁移必须先卸载再安装，不能只依赖 pip check。

## 只读示例

替换 URL 为你有读取权限的仓库；认证预先通过原生 SVN 配置。

```python
from pysvnlite import SVNRepo

repo = SVNRepo("https://svn.example.com/project/trunk", timeout=30)
for entry in repo.log(limit=10, verbose=True):
    print(entry.revision, entry.author, entry.changed_paths)
```

## API 范围

| 场景 | API |
| --- | --- |
| 元数据、目录、状态 | `info`、`list`、`status` |
| 历史与变更路径 | `log`、`iter_log`、`iter_log_events`、`changed_files_of_commit` |
| 历史文件、差异、逐行归属 | `cat`、`cat_to_file`、`diff`、`blame` |
| 工作副本管理 | `checkout`、`update`、`switch`、`add`、`delete`、`revert`、`commit` |
| 属性及其他操作 | `propset`、`propget`、`proplist`、`propdel`、`copy`、`move`、`mkdir`、`export`、`cleanup`、`resolve`、`lock`、`unlock` |

完整签名和返回模型见 [API 参考](https://github.com/narutozb/pysvnlite/blob/main/docs/api-reference.md)，组合用法见 [API 使用指南](https://github.com/narutozb/pysvnlite/blob/main/docs/basic-usage.md)。

## 安全与兼容边界

- 所有 SVN 调用添加 `--non-interactive`；凭据、ACL、证书和 SSH 配置由原生 SVN 管理。
- 写操作会修改工作副本或提交远端，先在临时测试仓库验证。库不提供自动回滚或事务。
- `timeout=None` 不设时限；日志的硬字节上限需要显式设置。事件在 SVN 输出捕获完毕后产生，不是网络实时流。
- `cat_to_file` 原子替换目标；失败保留旧文件。`cat` 会把整个文件读入内存。
- 检出路径保护检测预期 `.svn`，但不是原生编码补丁。部分 Windows / TortoiseSVN 中文绝对路径仍受限，见 [Windows 路径说明](https://github.com/narutozb/pysvnlite/blob/main/docs/windows-paths.md)。
- `SVNCommandError` 提供分类；`commit` 的普通非零退出可通过 `CommitResult.success` 返回，调用方必须检查。详见 API 参考。
- 网络认证、macOS 和全部 SSH 后代进程组合并未完整实测，不应从 CI 通过推断支持所有环境。

## 文档与维护

- [文档中心](https://github.com/narutozb/pysvnlite/blob/main/docs/README.md)
- [安装、离线和迁移](https://github.com/narutozb/pysvnlite/blob/main/docs/installation.md)
- [开发和 PyPI 发布](https://github.com/narutozb/pysvnlite/blob/main/docs/releasing.md)
- [中文变更日志](https://github.com/narutozb/pysvnlite/blob/main/CHANGELOG.md)

在开发虚拟环境、仓库根目录执行：

```bash
python -m pip install -e ".[dev,release]"
python -m ruff check src tests scripts
python -m mypy src scripts
python -m pytest -q
python scripts/release_pypi.py
```

脚本默认不上传。wheel / sdist 只包含本库及必要元数据，不含 AI 文件、测试、CI 或 svnpypi 源码；sdist 另允许 Hatchling 附带的 `.gitignore`。

本库从 [svnpypi v0.1.7](https://github.com/narutozb/svnpypi/tree/v0.1.7) 拆出，独立发行从 0.2.0 开始；保留 MIT 许可和作者信息。需要包注册 CLI 时另行安装 [svnpypi](https://github.com/narutozb/svnpypi)，两项目分别维护和发布。
