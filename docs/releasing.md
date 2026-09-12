# 维护与发布

此流程发布 pysvnlite 自身到 PyPI，不会将任意文件上传到业务 SVN。Python 兼容基线为 >=3.9，运行时实现只使用标准库。

## 开发环境

克隆本仓库后，在仓库根目录创建并激活独立虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,release]"
```

Linux / macOS 将激活命令改为 `. .venv/bin/activate`。禁止在其他业务应用的全局环境里更新发布工具。

```bash
python -m ruff check src tests scripts
python -m mypy src scripts
python -m pytest -q
python scripts/release_pypi.py
```

真实 SVN 测试仅使用临时 `file://` 仓库。缺少 svn / svnadmin 时相关测试跳过；发布前应在有工具的环境确认这些测试真正运行。CI 覆盖 Linux Python 3.9/3.12/3.14 和 Windows Python 3.12，但不代表所有原生客户端与远端认证组合通过。

文档变更也应运行测试：检查链接、Python 示例语法以及 API 参考与源码签名的一致性。新增或修改公开方法后同步更新 [API 参考](api-reference.md)。

## 制品约束

`scripts/release_pypi.py` 默认只检查和构建，不上传。流程读取 pyproject 的名称和版本，检查工作区，运行 Ruff/mypy/pytest，构建 sdist 和从 sdist 重建的 wheel，检查归档、Twine 元数据及隔离导入，最后输出 SHA256。

wheel 只含 pysvnlite、`py.typed` 与发行元数据。sdist 包含源码、pyproject、README、LICENSE、PKG-INFO，允许构建后端附带的 .gitignore；不含 AI 文件、测试、CI、发布脚本或 svnpypi 源码。Core Metadata 固定为 2.4，调整前必须验证完整发布链路。

本地未提交文档的预检可用 `--allow-dirty`。`--skip-checks` 仅供本地/TestPyPI 排障，不代表正式验收。

## TestPyPI

使用独立 TestPyPI 账户及其 token：

```bash
python scripts/release_pypi.py --upload --repository testpypi
```

在新的验证环境安装，并执行实际导入：

```bash
python -m pip install --index-url https://test.pypi.org/simple/ --no-deps "pysvnlite==0.2.2"
python -c "from importlib.metadata import version; from pysvnlite import SVNRepo; print(version('pysvnlite'))"
```

本库无运行时依赖，此处无需额外索引。TestPyPI 与正式 PyPI 的 token 不通用。

## 正式 PyPI

1. 将版本、中文 CHANGELOG、README 和安装示例统一到本次版本；旧历史记录保留原值。
2. 完整检查和 CI 通过后合并 main，确保工作区干净。
3. 创建 annotated 版本标签，原样推送到 origin；不要移动已发布标签。
4. 显式指定版本上传，之后从正式 PyPI 无缓存安装并检查哈希。

本次版本命令：

```bash
git tag -a v0.2.2 -m "pysvnlite 0.2.2"
git push origin v0.2.2
python scripts/release_pypi.py --upload --repository pypi --confirm-version 0.2.2
```

脚本拒绝生产上传使用 `--allow-dirty` 或 `--skip-checks`，并验证本地/远端 tag 对象一致且指向 HEAD。脚本不会暂停等待人工审核哈希；带 `--upload` 时检查通过即进入上传，务必先跑不上传的预检。

Twine 通常显示隐藏的 API token 提示；若询问用户名，填 `__token__`。不要把 token 写进命令、文件、Git 或日志。自动化可采用预先配置的 Trusted Publishing；现有 CI 仅检查，不自动发布。

PyPI 不允许覆盖同名同版本文件。发布后发现问题须新增版本，而不是重新上传替换 0.2.0 或移动其标签。

## 双项目发布顺序

两项目独立版本化，不需要每次同时发版。涉及两边时先发布 pysvnlite，并从 PyPI 验证；再验证消费它的 svnpypi，最后发布 CLI。文档补丁不需要无理由提高运行时依赖下限。

参考：[Twine 官方文档](https://twine.readthedocs.io/en/stable/)、[PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/)。
