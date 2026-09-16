# 维护与发布

## 开发环境

在仓库根目录创建虚拟环境并安装开发依赖。以下命令使用 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,release]"
```

Linux / macOS 的激活命令为 `. .venv/bin/activate`。

## 检查与构建

```bash
python -m ruff check src tests scripts
python -m mypy src scripts
python -m pytest -q
python scripts/release_pypi.py
```

发布脚本默认不上传。检查包括工作区状态、Ruff、mypy、pytest、sdist 构建、从 sdist 构建 wheel、归档内容、Twine 元数据及隔离导入，输出文件 SHA256。

真实 SVN 测试使用临时 `file://` 仓库，缺少 `svn` / `svnadmin` 时跳过。CI 覆盖 Linux Python 3.9/3.12/3.14 和 Windows Python 3.12；远端认证方式另行验收。

文档测试检查链接、示例语法、包范围和 [API 参考](api-reference.md)与源码的一致性。

## 构建内容

- wheel：`pysvnlite` 源码、`py.typed`、发行元数据。
- sdist：源码、`pyproject.toml`、README、LICENSE、PKG-INFO，以及构建后端附带的 `.gitignore`。
- Core Metadata 固定为 2.4。

`--allow-dirty` 和 `--skip-checks` 仅用于本地或 TestPyPI 检查，正式 PyPI 上传禁止使用。

## TestPyPI

```bash
python scripts/release_pypi.py --upload --repository testpypi
```

使用 TestPyPI 专用 token。验证环境使用该索引安装待发布版本并检查实际导入：

```bash
python -m pip install --index-url https://test.pypi.org/simple/ --no-deps "pysvnlite==0.2.2"
python -c "from pysvnlite import SVNRepo"
```

示例版本号需与待发布版本一致。TestPyPI 与正式 PyPI 凭据不通用。

## 正式 PyPI

1. 更新 `pyproject.toml` 版本、CHANGELOG、README、安装示例和版本测试。
2. 完成完整检查与 CI，提交到 main，保持工作区干净。
3. 创建带注释的版本标签并原样推送到 origin。
4. 上传后从正式 PyPI 无缓存安装，检查导入和文件哈希。

以下命令读取 `pyproject.toml` 中的待发布版本。Windows 使用 UTF-8 输出，避免进度条字符编码错误：

```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$version = python -c "from pathlib import Path; from scripts.release_pypi import read_project_metadata; print(read_project_metadata(Path('pyproject.toml')).version)"
git tag -a "v$version" -m "pysvnlite $version"
git push origin "v$version"
python scripts/release_pypi.py --upload --repository pypi --confirm-version $version
```

脚本验证本地与远端 tag 对象一致且指向 HEAD。带 `--upload` 时，检查通过即上传。
已发布标签和同名同版本文件不可覆盖；后续改动使用新版本。

Twine 凭据使用隐藏输入、`TWINE_PASSWORD` 或预先配置的 Trusted Publishing；token 不进入命令参数、Git 或日志。现有 CI 仅检查，不自动发布。

参考：[Twine](https://twine.readthedocs.io/en/stable/)、[PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/)。
