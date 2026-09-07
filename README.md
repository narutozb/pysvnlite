# pysvnlite

轻量、非交互的 Subversion 命令行封装和 XML 解析库，适合自动化脚本、资产历史查询和工作副本管理。

要求 Python >=3.9，并在 PATH 中提供原生 `svn` 客户端。库本身没有第三方运行时依赖，也不安装 `svnpypi` CLI。

```bash
python -m pip install pysvnlite
```

```python
from pysvnlite import SVNRepo

repo = SVNRepo("https://svn.example.com/project/trunk", timeout=30)
for entry in repo.log(limit=10, verbose=True):
    print(entry.revision, entry.author, entry.changed_paths)
```

## 能力与边界

- `info/log/list/status/blame` 等结构化读取，返回类型化模型。
- 工作副本检出、更新、增删、属性、提交、冲突检查；URL `mkdir/delete` 支持提交信息。
- 历史 peg revision、二进制读取、原子文件下载。
- 可选超时，有界日志滚盘、增量 XML 与路径事件；通过 `CAPABILITIES` 检查 `bounded_verbose_log_v1`。
- 所有 SVN 调用添加 `--non-interactive`；认证、ACL、传输安全和凭据缓存由原生 SVN 管理。
- 不提供服务端、Web UI、依赖解析器或自动删除策略。

完整示例见 [API 使用指南](https://github.com/narutozb/pysvnlite/blob/main/docs/basic-usage.md)，平台限制见 [Windows 路径说明](https://github.com/narutozb/pysvnlite/blob/main/docs/windows-paths.md)。

## 从旧版 svnpypi 迁移

本库从 `narutozb/svnpypi` 的 `v0.1.7`（提交 `ce6191be4122eb54bbfbbed16bad46413f222e62`）拆出，保留 MIT 许可和作者信息。独立发行从 `0.2.0` 开始，`from pysvnlite import SVNRepo` 等现有导入保持不变。

**不要对旧捆绑版本直接执行普通升级。** 本机已验证：从 `svnpypi 0.1.7` 直接升级时，pip 先安装新依赖，再卸载旧包，会删除新库的同名文件并导致导入失败。`pip check` 仅检查元数据，不能证明文件完整。旧 `svnpypi<=0.1.7` 曾直接拥有 `pysvnlite/` 文件；不要混装或在拆分后降级安装旧发行包。推荐新建虚拟环境；需要原地迁移时，先卸载旧发行包，再重新安装：

```bash
python -m pip uninstall -y svnpypi pysvnlite
python -m pip install "pysvnlite==0.2.0"
python -m pip check
```

仍需要包注册 CLI 时，最后安装 `svnpypi>=0.2.0`，由其依赖声明安装本库。维护人员应先发布本库，再发布依赖它的 `svnpypi`。

## 开发与发布

```bash
python -m pip install -e ".[dev,release]"
python -m ruff check src tests scripts
python -m mypy src scripts
python -m pytest -q
python scripts/release_pypi.py
```

测试仅写入临时 `file://` SVN 仓库；缺少 `svn` 或 `svnadmin` 时集成测试跳过。CI 覆盖 Linux Python 3.9/3.12/3.14 与 Windows Python 3.12。Python 3.9 仅保留兼容性，生产使用仍受官方维护的运行时。

发布脚本默认不上传，检查 wheel/sdist 内容白名单、`py.typed`、Twine 元数据，并通过 `python -I -S` 从临时安装目录导入，避免本机环境掩盖漏包。AI 文件、测试、CI、发布脚本和 `svnpypi` 源码均不进入构建包；sdist 允许 Hatchling 为重建附带的 `.gitignore`。

正式上传必须具有干净工作区、完整检查和已原样推送的 annotated 标签：

```bash
git tag -a v0.2.0 -m "pysvnlite 0.2.0"
git push origin v0.2.0
python scripts/release_pypi.py --upload --repository pypi --confirm-version 0.2.0
```

首次发布建议先用独立的 TestPyPI 凭据验证：`python scripts/release_pypi.py --upload --repository testpypi`。正式 PyPI token 不能用于 TestPyPI。只在隐藏密码提示中输入 token，不写入源码、命令行或日志。
