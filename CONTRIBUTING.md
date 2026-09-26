# 贡献指南

接受中文或英文 issue 和 PR。本项目维护通用 SVN 封装与解析能力，不内置下游业务流程。

## 提交 Issue

先检索已有事项，再使用 [issue 模板](https://github.com/narutozb/pysvnlite/issues/new/choose)，一条报告聚焦一个问题：

- **缺陷**：精确版本与安装来源、环境、最小复现、预期及实际结果。源码安装补充完整提交 SHA 和未提交修改情况，不能只写“最新 main”。
- **需求**：说明场景、现有限制、兼容性及验收方式；较大变更先讨论。
- **文档**：提供固定版本的页面或提交链接、问题及依据。

相关时附相同目标和参数的原生 SVN 对照；未知项注明，不猜测。日志须脱敏，写入复现仅使用临时本地仓库。漏洞按 [安全政策](SECURITY.md)私下报告。

详见 [版本追踪规则](docs/maintenance-policy.md#issue-基线)和 [issue 例文](docs/issue-examples.md)。

## 提交 PR

1. 从 main 建立单一目的分支，外部贡献使用 fork。记录修复起点 SHA 和合并目标，以 `Refs #N` 关联问题。
2. 保持 SVN 原生语义和公共默认值，不猜测修订/编码、扩大目标或拆分原子提交。先补回归，再修复。
3. 按[修复交付与复测](docs/maintenance-policy.md#修复交付与复测)提供固定提交的安装、复现步骤及预期结果，记录实际测试与限制；更新必要文档，行为变化写入中文 CHANGELOG“未发布”，普通 PR 不改版本号。
4. 不混入无关改动、凭据或构建产物。贡献须符合 [MIT 许可](LICENSE)并保留作者归属。

## 本地验证

在虚拟环境中执行：

```bash
python -m pip install -e ".[dev,release]"
python -m ruff check src tests scripts
python -m mypy src scripts
python -m pytest -q
```

真实 SVN 测试需要 `svn`、`svnadmin`；跳过不算通过。纯文档修改至少运行 `python -m pytest tests/test_documentation.py -q` 和 `git diff --check`。分支、关闭条件与发布流程见 [维护策略](docs/maintenance-policy.md)及 [发布指南](docs/releasing.md)。
