# 轻量 MVP 使用与验收

> 本文是R01–R09 CLI历史验收；2026-11-19当前版本0.4.0已继续交付画像、记忆、持久研究、公开补查、评测、页面/API及部署。最新使用与边界见[完整产品使用与部署](完整产品使用与部署.md)，不再用本文历史“尚未交付”描述当前能力。

日期：2026 年 11 月 18 日。已按当前 R01–R09 完成 CLI 版本，G1–G4 合并实施。继续使用 Python/uv、现有依赖、SQLite 和既有八张表；未新增前端、HTTP 服务、调度、向量库或研究检查点。

本文件保留 CLI 阶段的交付记录。随后 G5 已增加本地页面和必要 HTTP 入口，可用 `uv run --locked work-observer serve` 启动，详见 [本地页面使用与验收](本地页面使用与验收.md)。以下命令与数据语义继续有效。

## 1. 启动与查看

在项目根目录的 PowerShell 运行：

```powershell
$env:PYTHONUTF8 = "1"
uv sync --locked
uv run --locked work-observer --help
uv run --locked work-observer source-status
uv run --locked work-observer jobs --city 上海
uv run --locked work-observer jobs --detail detail
uv run --locked work-observer jobs --detail list_only
uv run --locked work-observer companies --name 上海
```

已有本地库无需重新初始化；新机器才需要 `uv run --locked work-observer db-init`。当前迁移仍是 `e7b4c1a20618`，本次没有迁移或回填正式库。未来升级旧库前，应先用 SQLite backup API 备份，包括 WAL 已提交内容；不要用删除数据库代替升级。

查询 JSON 的 `jobs[].id` 是内部岗位 ID，`company_id` 是内部公司 ID；后续命令使用它们。`companies` 输出中的 `identity_status=unverified` 表示公司主体尚未核实，同名记录不自动归并。

```powershell
uv run --locked work-observer job --id <内部岗位ID>
uv run --locked work-observer company --id <内部公司ID>
uv run --locked work-observer history --job-id <内部岗位ID>
```

`job` 保留完整原文、各字段组来源以及人工补充资料链接。`history` 保留观察时间、本地处理时间、版本、来源类型和原文；均不输出 `security_id/lid` 等访问上下文。公司与岗位查询不会调用模型或招聘源。

## 2. 筛选语义

```powershell
uv run --locked work-observer jobs --city 上海 --company 上海 --keyword Agent
uv run --locked work-observer jobs --salary-min 20000 --salary-max 40000 --salary-unit month
uv run --locked work-observer jobs --education 本科 --experience "3-5年" --detail detail
uv run --locked work-observer jobs --source manual --limit 20 --offset 0
```

- 所有明确条件由参数化 SQL 处理；条件之间为 AND。城市、公司、学历和经验按原文子串匹配，暂不推断学历高低或个人资历是否满足要求。
- 关键词在标题、来源技能标签及 JD 正文中匹配，英文不区分大小写。摘要未命中且缺正文时，全文条件记为未知。
- 薪资按 CNY、相同周期的区间相交筛选，单位为元；`month/year/day/hour` 不混算，不推算年包。周期不同或金额无法识别记为未知。
- `counts.matched`、`unknown`、`excluded` 在分页前计算。候选输出同时包含匹配和未知，各行用 `match_status` 区分；未知不等于满足条件。已知不匹配优先于另一个条件未知。
- `candidate_details` 是匹配与未知候选中的正文数。`truncated` 提醒分页，不能用本页数量代替总体统计。

来源时间均为 UTC ISO 8601；例如 `2026-11-18T14:04:19+00:00` 对应北京时间当日 22:04:19。发现、收到详情、来源首次获取、发布时间与本地归档各自独立。`source_published_at=null` 始终表示不知道；`response_origin=unknown` 不等于实时。

## 3. 人工补录

准备自己的 UTF-8 文本或 JSON。JSON 格式模板在 `configs/manual-jd.example.json`，先替换其中内容再使用，不要把模板当成真实岗位。最少三个字段：`title`、`company`、`description`。

```powershell
uv run --locked work-observer import-jd --file C:\资料\我的JD.txt --title "真实岗位名称" --company "来源公司名" --external-id my-jd-001
uv run --locked work-observer import-jd --file C:\资料\我的JD.json
uv run --locked work-observer import-jd --file C:\资料\补充JD.json --external-id supplement-001 --related-job-id <原岗位内部ID>
```

可选字段：`external_id`、`related_job_id`、`city`、`salary`、`education`、`experience`、`job_url`、`source_published_at`、`source_published_raw`、`note`。未知字段留空或省略；不接收认证字段。发布时间必须明确且含时区，不用文件时间或导入时间代替。仅提供链接会被拒绝；附带链接会去掉查询参数与片段。

人工资料使用 `source=manual`、`mode=manual`、`transport=manual`、`response_origin=manual`，导入时间是取得这份人工资料的时间，不证明网站在此刻更新。稳定 `external_id` 对应同一人工岗位；同 ID、同正文复用版本，同 ID 的新正文保存新版本。相同 ID 若标题或公司不同会报身份冲突。无 ID 时以输入内容指纹去重，修改内容可能形成另一个岗位，建议持续维护时提供稳定 ID。

关联已有平台岗位时，人工内容成为独立资料记录，原岗位的来源原文与正文完整度不被悄悄改写；原岗位 `manual_supplements` 可跳转查看补充记录。标题、薪资等不得让模型补造。人工导入允许与 live 或 replay 共存，但 live 与 replay 仍必须分库。

## 4. 原文检索、比较与研究

```powershell
uv run --locked work-observer search --term Python --term RAG --city 上海
uv run --locked work-observer search --term 智能体 --job-id <内部岗位ID>
uv run --locked work-observer source --id <检索结果中的document_id>
uv run --locked work-observer compare --job-id <岗位A内部ID> --job-id <岗位B内部ID> --save
uv run --locked work-observer research --question "这些岗位分别需要完成什么工作，要求哪些能力和工具？" --city 上海 --detail detail --save
```

`search` 的重复关键词按 OR 匹配，返回全部范围的岗位命中数和有限片段。别名可直接分别传入，例如 `--term Agent --term 智能体`；当前没有语义检索或向量检索。`source` 检查原始文件 SHA-256，给出 `verified/missing_or_changed`，只展示业务内容和版本，不打印原始访问参数。模型判断可能仍有解释误差，引用有效不等于自动证明语义正确，重要结论应对照原文。

一个研究 Agent 先用 `query_jobs` 读取固定 SQL 范围，再自主使用 `search_evidence` 或 `read_job` 调查，最后用 `finish_research` 返回结构化判断。可比较任务、责任、能力与工具；每条判断有必备、加分或未明确性质标签以及有效引用。`compare` 接收 2–5 个不同岗位，有正文的指定岗位都必须有被引用的证据；缺失正文会单列缺口。

默认最多 10 次模型请求、180 秒，每次响应只接受一个受限函数调用；`research` 可用 `--max-calls 2..12 --timeout 1..300` 调整。最多研究 20 个候选，超过时明确提醒收窄条件；读取单岗位最多 8 个 700 字符片段。每条片段保留全长与位置，未覆盖全部正文时不能断定后文没有某项要求。超时、无凭据、额度不足、协议错误、越界和预算耗尽均明确失败或未完成，并保留已取得的证据；不会降级为虚假的模型成功。

模型只接触本次范围内的摘要和按需检索片段；不能执行任意 SQL、改写岗位、扩大采集范围或恢复来源。使用本地 `.env` 中已有 `WO_MODEL_BASE_URL/WO_MODEL_NAME/WO_MODEL_API_KEY`，支持 Responses 及 Chat Completions。密钥不进入产品输出和研究文件。公开搜索不是本地研究的必要条件，本版研究 Agent 没有联网搜索工具，也不要求配置 Tavily。

模型不可用时仍可运行：

```powershell
uv run --locked work-observer research --question "整理可核对资料" --detail detail --offline --save
uv run --locked work-observer compare --job-id <岗位A内部ID> --job-id <岗位B内部ID> --offline
```

`offline` 明确为 `evidence_only`，只给 SQL 范围、原文和缺口，**不声称已完成模型比较**。没有任何正文时返回 `insufficient_evidence`，不消耗模型调用。

## 5. 结果保存与再次查看

```powershell
uv run --locked work-observer reports
uv run --locked work-observer report --id <保存时返回的report_id>
```

只有 `--save` 才保存，每次产生新的 `reports/<report_id>.json` 与 `.md`；可用 `--reports-dir` 指定位置。JSON 冻结问题、候选筛选条件与统计、岗位摘要、分析、工具轨迹、版本与文档指纹、引用原文及位置；Markdown 提供可跳转引用。后续 JD 改变不会改写已有结果，查看无需再次调用模型。失败运行可按用户的 `--save` 要求保存诊断，状态始终保留。

这是简单结果文件，不是长期知识或记忆系统。业务知识和长期记忆未来仍归业务库；本次没有预建记忆表、独立研究数据库或检查点库。

## 6. 当前真实验收

| 需求 | 已验证结果 |
| --- | --- |
| R01 查看 | 正式库 15 个岗位及公司可查；7 份完整来源正文，8 份摘要；公司身份可区分 |
| R02 筛选 | SQL 条件、薪资单位与未知分类、分页前计数已有自动化检查；真实库按完整度筛选得到 7/8 |
| R03 有限获取 | 原有有界采集和详情适配保留；本地风险暂停在启动来源前返回 `SOURCE_PAUSED_USE_LOCAL_DATA`，本次没有平台请求 |
| R04 补录 | 真实 JD 的人工副本在独立验收库导入两次，只增加 1 个人工岗位、1 份版本；原平台岗位不变 |
| R05 比较 | 两份真实 JD 经当前已配置模型比较成功，4 次调用、10 条带引用判断；不是回放或模拟模型结果 |
| R06 检索 | 7 份正文共核对 9 个片段；Python/RAG 字面检索命中 4 个岗位，所有片段可回到版本与原始文档 |
| R07 Agent | 真实比较经过 query → read → read → finish（4 次调用）；另一真实研究经过 query → search → finish（3 次调用），取得 9 条带引用判断；自动化覆盖越界、伪造引用、超时和数量边界 |
| R08 保存 | 真实研究结果已保存并重新读取，所引原文逐条对照快照及原始文档指纹 |
| R09 可信 | 正式库所有未知发布时间保持为空；八张业务表全部行值指纹及来源暂停文件在验收前后保持一致 |

本地真实结果：`reports/9336f74e1e654f93a3e2c2679d121145.json` / `.md`（比较）与 `reports/f0b3c269a1be4cb48ca2d6c2e241e100.json` / `.md`（检索研究）；验收摘要：`data/mvp-verification/acceptance.public.json`。所有引用均已核对版本片段和原始文件指纹；报告中没有配置密钥值。这些结果及真实资料均被 Git 忽略，不加入公开仓库。正式库 SQLite backup API 备份保存在 `data/backups/mvp-2026-11-18T145309.768584_0000/app.db`；人工验收库为 `data/mvp-verification/manual-verification.db`，其多出的人工岗位不代表新增市场样本。真实 CLI 的导入、公司查看、来源核对、结果再次查看及暂停采集反馈也已试跑。

自动化命令：

最终结果：**95 项测试通过**（原 71 项加 24 项 MVP 检查），Ruff 及格式检查通过，49 个已安装依赖的一致性检查通过。隔离测试只用于机制验证；上述两次模型研究使用本地实际配置与真实 JD，不用模拟结果冒充。

```powershell
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv pip check
```

当前限制：招聘源仍因 code 37 本地暂停，8 份详情仍待补全；已有“招聘中”状态也是历史观察。公开搜索的旧连接结果只属于历史证据，本次未复验；本次模型成功不保证未来额度或可用性。自动认证、全量复查、定时、个人条件智能匹配、语义检索、长期记忆、前端和 HTTP API 均未交付。
