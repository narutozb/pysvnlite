# Issue 填写例文

首例取自 [0.2.3 的历史报告](https://github.com/narutozb/pysvnlite/issues/15)，仅说明该版本的行为，不代表当前源码状态。其余为填写示例，尖括号内容必须替换为实际证据，不应直接作为新报告提交。

## 信息采集

在实际运行程序的 Python 环境执行，避免把另一环境的版本写入报告：

```bash
python -c "import sys, pysvnlite; from importlib.metadata import version; print(sys.version); print(version('pysvnlite')); print(pysvnlite.__file__)"
svn --version --quiet
```

仅源码安装需要在对应源码目录补充：

```bash
git rev-parse HEAD
git status --short
```

导入路径、文件列表和日志提交前须脱敏。PyPI 用户不必提供 Git SHA；源码有未提交修改时说明范围，不把它当作干净提交的结果。

## 例一：已发布包的缺陷

**标题**：`[Bug] 0.2.3：status 无法读取含 @ 的字面文件路径`

- 发现基线：PyPI `pysvnlite==0.2.3`，非 editable 安装。
- 环境：Windows、Python 3.14.4、SVN 1.14.5；临时 `file://` 仓库。
- 预期：返回指定文件的 `unversioned` 状态。
- 实际：库调用抛出含 `E200009` 的异常；原生命令追加空 peg 后返回 `unversioned`。
- 已验证范围：仅上述版本和环境；最后正常版本未知。

最小复现只创建一次性本地仓库：

```python
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from pysvnlite import SVNCommandError, SVNRepo


def run(*args):
    return subprocess.run(
        [str(arg) for arg in args], check=True, timeout=30,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout


with tempfile.TemporaryDirectory(prefix="status-example-") as directory:
    root = Path(directory)
    repository, working = root / "repo", root / "wc"
    run("svnadmin", "create", repository)
    run("svn", "--non-interactive", "checkout", repository.as_uri(), working)
    asset = working / "asset@version.txt"
    asset.write_bytes(b"fixture")

    try:
        items = SVNRepo(asset, timeout=30).status(depth="empty")
        print("library:", [item.wc_status for item in items])
    except SVNCommandError as error:
        print("library:", type(error).__name__)
        print("E200009:", "E200009" in error.stderr)

    xml = run("svn", "--non-interactive", "status", "--xml",
              "--depth", "empty", "--", f"{asset}@")
    status = ET.fromstring(xml).find("./target/entry/wc-status")
    print("native:", status.get("item") if status is not None else None)
```

原始报告保留 0.2.3；以后源码通过此用例，应追加验证 SHA 和结果，不把报告版本改为“最新 main”。

## 例二：Main 源码上的问题

**标题**：`[Bug] 源码状态对象遗漏仅属性冲突的信息`

```text
发现基线
- 安装来源：源码 editable 安装，分支 main
- 完整提交 SHA：<发现时的 40 位提交 SHA>
- 包版本：<该 Python 环境报告的版本>
- 工作区：干净；未提交修改：无

环境与复现
- <操作系统、Python、原生 SVN 客户端及版本>
- 在临时仓库建立两个工作副本，提交同一文件和初始属性。
- 第二个副本修改该属性并提交；第一个副本修改同一属性，再 update --accept postpone。
- 对同一文件比较库 status 和原生 status --xml 的属性状态。

预期与实际
- 预期：结构化对象能区分属性冲突，不改写原生内容状态。
- 实际：<对象字段及 XML 中 item/props 的脱敏输出>
- 复现脚本：<可运行的最小脚本>
- 原生对照：<相同目标、深度及选项的命令>
- 受影响版本：只确认上述 SHA，其他提交未知。
```

若工作区不干净，将“干净”改为实际修改情况，附最小脱敏差异。该结果不代表所填写 SHA 的未修改源码也有问题。

## 例三：通用能力需求

**标题**：`[Enhancement] 为精确批量目标提供原生 --targets 支持`

```text
使用场景
- 当前安装：<精确版本/来源，或源码 SHA 与修改情况>
- 提交大量精确路径时遇到系统命令行长度限制。
- 已有绕行：缩小每批路径，但不能用多次 commit 代替一次原子提交。

建议范围
- 评估接受原生 targets 文件的显式接口，现有 paths 调用保持兼容。
- 不自动提交父目录，不自动拆分 commit，不猜测文件编码或路径。
- 原生依据：<该客户端 svn help commit 的 --targets 说明及官方实现链接>

验收条件
- 临时仓库中，预检、自动准备和提交针对同一目标集合。
- 一次成功提交只产生一个修订，不带入未选择的文件。
- 特殊路径、文件编码、冲突及失败后的状态有明确测试和文档。
- 尚待确认：<不确定的原生行为与维护成本>
```

需求报告不等于已验证的接口设计；计划发布版本由维护者评估后填写。

## 例四：固定版本的文档问题

**标题**：`[Docs] 补充文件下载预算的边界示例`

```text
页面与基线
- 文档：<使用完整提交 SHA 的 docs/api-reference.md 永久链接>
- 对应包版本/标签：<实际版本或标签，源码文档可注明未发布>

问题
- 希望增加 cat_to_file(max_output_bytes=...) 的示例，说明预算超限时旧目标文件的状态。

建议与依据
- 使用临时文件展示预算等于内容大小和小于内容大小两种情况。
- 记录成功/异常类型及目标字节；保持原生 bytes，不进行全局转码。
- 已验证结果：<实际版本、测试脚本及输出；未验证则明确注明>
```

## 维护者复测记录

复测以回复追加，保留最初基线。修复起点记录在 PR，不用发现版本代替：

```text
发现基线：<原 issue 的版本或 SHA>
修复起点：<基准分支> @ <分支创建时完整 SHA>
合并目标：<main 或登记的维护分支>
验证提交/工作区：<本次 SHA；是否含未提交修改>
验证环境及用例：<环境、命令或回归测试>
对照结果：<原版本失败/未复现；本次通过/失败/跳过>
结论：<已定位修复提交，或暂不能复现且原因未知>
发布归属：未发布；或 <实际标签与 PyPI 版本>
```

main 无法复现并不足以判定原报告无效；没有定位原因时，不把“未复现”写成“已修复”。完整流程见 [维护策略](maintenance-policy.md)。
