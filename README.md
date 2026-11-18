# Work Observer · 工作观察

一个以招聘原文为依据的单用户研究 Agent：把企业业务背景、工作任务与交付物、责任、能力和工具联系起来，并保留证据、版本、人工纠正和研究过程。

**当前版本 0.4.0，2026-11-19。** 已从 CLI MVP/G5 扩展为中文工作台、完整业务 API 与可部署/演示版本。完整需求和实际验收见[验收台账](docs/完整产品验收清单.md)，不是只交付持续研究。原 README 全文保留为[历史记录](docs/README-MVP历史.md)。

## 启动

```powershell
uv sync --locked
uv run --locked work-observer db-init
uv run --locked work-observer serve
```

打开 **http://127.0.0.1:8765**。升级已有库会先用 SQLite backup API 备份并核对旧表旧列行值；不删除或重建历史。按 `Ctrl+C` 停止。现有 `.env` 继续使用，首次配置参考 `.env.example`，不要覆盖已有配置或提交密钥。

当前正式资料仍为 **15 个岗位、7 份正文、8 份摘要**，发布时间未知则为空。BOSS 因 code 37 明确暂停；页面、研究、人工资料与本地任务都不解除暂停。多日无人采集和认证恢复没有通过验收。

## 可以实际操作的能力

| 工作台 | 业务结果 |
| --- | --- |
| 岗位与公司 | SQL筛选、未知条件单列、原文与来源SHA、观察历史、两个详情版本的确定性差异 |
| 补充资料 | 文本/JSON、最多20行CSV预览与逐行保存；截图原图归档、明确同意后的单次视觉草稿、人工核对后入库 |
| 岗位画像 | 六类证据判断、必备/加分/未知、领域多标签、向招聘方核实的问题、人工领域纠正与版本过时提示 |
| 研究工作台 | 一个Agent规划→查询/检索/统计/历史/必要公开补查→引用判断与缺口；保存过程、暂停/恢复、原预算和正文版本不重置 |
| 知识与偏好 | 明确输入、版本修订、撤回；知识候选采纳后召回；忘记清理关联派生研究/画像/知识/报告/通知 |
| 个人匹配 | 保存明确条件，逐条展示符合、不符、待核实及原因，不虚构用户履历 |
| 检索与评测 | 别名、来源标签、范围/历史截止；完整正文分母的字面统计；固定基线与候选配对、护栏、显式启用与回退 |
| 观察与更新 | 观察规则版本、有限持久任务、默认关闭的每日时段、运行失败与更新摘要、本地未读收件箱/后续问题 |
| CLI与接口 | 共用业务服务；浏览器底部“接口说明”和 `/api/openapi.json` 提供与实际路由同步的合同 |
| 部署与恢复 | 私有单用户访问模式、签名会话/Bearer、同源写保护、完整备份到新目录恢复、独立wheel及容器配置 |

研究可把有原文依据的认识或检索别名提出为候选，读取固定评测反馈；不能自行启用策略、改门槛、扩大采集权限或改代码。模型与公开搜索有数量/时间/上下文上限，费用不明则保持未知。引用可核验不等于语义必然正确。

## 无私有资料的演示

```powershell
uv run --locked work-observer demo-init --directory data/demo
uv run --locked work-observer serve --db data/demo/app.db --reports-dir data/demo/reports
```

生成4个原创合成岗位、5份快照，含一个岗位的两版正文，不读正式资料、不联网。资料明确标 `synthetic`，不能当作真实市场样本。没有模型时勾选“仅整理证据”，明确不声称完成模型分析；固定检索评测和版本演示仍可离线运行。参见[面试演示与设计取舍](docs/面试演示与设计取舍.md)。

## 常用命令

```powershell
uv run --locked work-observer status
uv run --locked work-observer research --question "这些岗位的任务、交付物和能力要求有什么不同？" --detail detail --save
uv run --locked work-observer research-runs
uv run --locked work-observer product profiles analyze --id <岗位ID>
uv run --locked work-observer product retrieval run --term Python --term RAG
uv run --locked work-observer product statistics run --term Python
uv run --locked work-observer product inbox unread
uv run --locked work-observer backup data/backups/完整备份
uv run --locked work-observer restore data/backups/完整备份 data/restored
```

`product <业务> [操作]` 使用位置参数；完整例子及字段见[使用与部署](docs/完整产品使用与部署.md)和[API合同](docs/API合同.md)。时段默认关闭，只有显式启动 `worker` 才处理；当前暂停来源仍在网络前拦截。没有建立系统定时任务或应用自动化。

## 验证与边界

当前真实研究、官方正文、画像、视觉抽取及候选评测反馈均分别留有本机证据。失败和预算耗尽保留原状态，没有用模拟替代真实成功。新增原始资料、数据库、报告、截图和密钥不提交到公开仓库。最终检查与实际结果统一记录于[完整验收台账](docs/完整产品验收清单.md)。

```powershell
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv pip check
uv build --wheel
```

本机和独立安装包已验证；当前主机没有Docker环境，容器构建及具体服务器的HTTPS/代理/磁盘权限需在目标环境验收。提供部署配置不表示已公网发布。当前产品是单用户、单机有界执行，不是多租户服务或全市场数据平台；不投递、不联系招聘者、不推送仓库、不对外发布真实资料。

## 设计与历史

- [完整需求—现状—验收](docs/完整产品验收清单.md)
- [当前架构与模块边界](docs/架构与模块设计.md)
- [数据库原八表](docs/数据库字段定义.md) / [研究与产品增量字段](docs/研究与产品增量字段.md)
- [资料导入与OCR验收](docs/资料导入与OCR验收.md) / [持续研究验收](docs/持续研究使用与验收.md)
- [MVP使用与验收](docs/MVP使用与验收.md) / [G5页面历史验收](docs/本地页面使用与验收.md)
- [长期业务规划](docs/长期规划.md) / [长期架构设计](docs/长期架构设计.md)

继续使用Python/uv、SQLite/SQLAlchemy/Alembic、Starlette/Uvicorn和原有来源适配。SQL负责筛选统计，有限检索负责证据，单Agent负责调查选择；业务事实、派生知识和研究检查点分开。没有以“完整产品”为理由恢复暂停来源或强行堆入多Agent、独立向量库与通用调度平台。
