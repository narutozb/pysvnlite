# 安装与迁移

适用于 pysvnlite 0.2.2。要求 Python >=3.9、pip、PATH 中可用的 `svn`。运行时不依赖第三方 Python 包；`svnadmin` 仅用于本地集成测试。

## 新环境

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install "pysvnlite==0.2.2"
.\.venv\Scripts\python.exe -c "from pysvnlite import SVNRepo"
```

Linux / macOS：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install "pysvnlite==0.2.2"
.venv/bin/python -c "from pysvnlite import SVNRepo"
```

后续命令在该环境中运行。确认 `svn --version --quiet` 可用，再使用授权 URL 验证 `svn --non-interactive list <repo-url>`。认证、证书和 SSH agent 由 SVN 管理，不要将密码放入 URL 或命令参数。

## 从独立 0.2.x 升级

```bash
python -m pip install --upgrade "pysvnlite==0.2.2"
```

0.2.2 保持现有 API，修复超时后的进程树回收和管道阻塞。若同时使用 svnpypi，检查其依赖范围仍允许本版本，并执行两者的实际导入与业务测试。

## 从旧捆绑发行包迁移

独立发行从 0.2.0 开始。此前 `svnpypi<=0.1.7` 直接拥有 `pysvnlite/` 文件；不要将旧发行包与独立库混装或直接普通升级。pip 卸载旧包时会删除同名文件，产生元数据完整但导入失败的环境。

推荐新建虚拟环境。原地迁移或修复前先停止依赖该解释器的任务，之后执行：

```bash
python -m pip uninstall -y svnpypi pysvnlite
python -m pip install "pysvnlite==0.2.2"
```

若仍需包注册 CLI，再安装 `svnpypi==0.2.2`。不要降级安装旧捆绑版到同一环境。旧项目若仅使用 SVN API，其依赖声明应改为 pysvnlite，而不是继续安装 svnpypi 获取底层库。

## 验证

```bash
python -m pip check
python -c "from importlib.metadata import version; from pysvnlite import SVNRepo; print(version('pysvnlite'))"
```

本库未提供顶层 `__version__`，版本查询使用发行元数据。`pip check` 只检查依赖，不能证明模块文件完整，必须执行实际导入。

## 离线安装

在联网环境收集 wheel，将目录传到目标环境：

```bash
python -m pip download --only-binary=:all: --no-deps --dest wheelhouse "pysvnlite==0.2.2"
python -m pip install --no-index --find-links wheelhouse "pysvnlite==0.2.2"
```

本库无第三方运行时依赖，所以此处收集 wheel 时可用 `--no-deps`。该建议不适用于 svnpypi 或开发 / 发布 extra。SVN 原生客户端仍需单独安装和配置。

中文路径支持边界见 [Windows 路径说明](windows-paths.md)，开发与构建环境见[维护与发布](releasing.md)。
