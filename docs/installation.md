# 安装与升级

## 环境要求

- Python >=3.9、pip。
- Subversion 客户端，`svn` 位于 `PATH`。
- 运行时无第三方 Python 依赖；`svnadmin` 仅用于本地集成测试。

## 安装

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install "pysvnlite==0.2.2"
```

Linux / macOS：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install "pysvnlite==0.2.2"
```

以下命令在已激活的虚拟环境中运行。

## 升级

```bash
python -m pip install --upgrade "pysvnlite==0.2.2"
```

## 验证

```bash
svn --version --quiet
python -m pip check
python -c "from importlib.metadata import version; from pysvnlite import SVNRepo; print(version('pysvnlite'))"
```

版本号通过 `importlib.metadata.version()` 查询。`pip check` 检查依赖关系，导入检查验证模块可用性。

SVN 认证、证书和 SSH agent 使用原生客户端配置。仓库 URL 和命令参数中不应包含密码。

## 离线安装

联网环境下载 wheel：

```bash
python -m pip download --only-binary=:all: --no-deps --dest wheelhouse "pysvnlite==0.2.2"
```

目标环境安装：

```bash
python -m pip install --no-index --find-links wheelhouse "pysvnlite==0.2.2"
```

Subversion 原生客户端需单独安装。开发和发布依赖见[维护与发布](releasing.md)，中文路径限制见 [Windows 路径兼容性](windows-paths.md)。
