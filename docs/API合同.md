> 0.16.0更新（2026-11-19）：新标准研究修正否定误拦并记录检查版本，旧v5轮保持原检查和预算；项目可明确按新口径重查。标准执行合同为v6，提示/工具保持，不启用实验提示；无新增真实调用或质量收益证明，Goal继续。见[0.16阶段验收](版本化标准检查与0.16阶段验收.md)。

> 0.15.0更新（2026-11-19）：13次真实配对调用未证明收益，v8候选返工未完，已撤回新提示。当前v9只修显式反馈的必备否定误拦；原失败保留，重放不是新真实成功，标准默认不变。Goal继续。见[0.15阶段验收](资格否定误拦与0.15真实复验.md)。

> 0.14.0更新（2026-11-19）：拒绝复核可显式带入项目内补查，累计原预算，隔离旧结论与派生背景，离线预览可转模型。仅工程验证，无新增真实调用或方法收益证明；浏览器读取因网址识别限制被停止，仍待验。Goal继续。见[0.14阶段验收](项目内复核补查与0.14阶段验收.md)。

> 0.13.0更新（2026-11-19）：直接研究可明确参照拒绝意见新建一轮，锁复核版本、预算另计并联动遗忘。真实5调用生成16判断，仍有优先能力升必备，已保存Agent拒绝；606测试通过，默认不变，Goal继续。见[0.13阶段验收](复核反馈补查与0.13阶段验收.md)。

> 0.8.0更新（2026-11-19）：显式来源分项试验及原文定位/未知/恢复已接通；3题35次真实调用只完成1份候选，2份未完，尚未证明整体收益。默认仍标准方法，Goal未完成。见[0.8阶段验收](来源分项试验与0.8阶段验收.md)。旧段落按历史阶段理解。

> 0.7.0更新（2026-11-19）：完整画像审核与固定业务题组匿名比较、遗忘及备份已接通；33次真实调用仍有职责边界失败，未获人类批准或证明方法收益。当前分级证据见[0.7阶段验收](真实研究闭环与0.7阶段验收.md)。以下旧段落按历史阶段理解。

> 0.6.0更新（2026-11-19）：日常研究串行流程、保历史补查、递归来源资格与局部人审试用已增量实现；真实语义质量和长期运行仍未验收。当前操作与分级证据见[0.6阶段验收](日常研究与受限试用阶段验收.md)。以下旧版本段落作为阶段历史保留。

> 0.5.0阶段更新（2026-11-19）：已增量实现持久多轮项目与有界调查、分层/冲突/有效期记忆、统一原文检索、领域关系、业务质量审核、领域观察和资料核对。当前仍为Alpha；真实质量复验保留待审与失败，未宣称整体成熟。最新操作、分级证据与剩余实质缺口统一见[持久研究项目与阶段验收](持久研究项目与阶段验收.md)。以下0.4及更早状态按历史阶段理解。

# Work Observer HTTP API 合同

2026-11-20认知延续增量（源码已实现，尚未进入当前8776进程）：

- `GET /api/knowledge/research/{id}`读取已完成且来源有效的地图及其结构化保存状态；`POST`只接受地图条目索引、目标定义及可选前版ID，从原研究提取候选，不接受客户端重写结论或证据。
- `GET /api/updates/reports/{id}`增加动态`research_impact`：直接引用旧版本的判断、通过知识/记忆/研究背景关联的下游研究、原项目及步骤定位。返回完整关联计数及最近50轮；这些是待复核关联，不是语义错误裁决。关联文本不另存副本，已遗忘研究不再展示。
- `POST /api/updates/reports/{id}/followup`的`{note,run_id?}`：省略`run_id`仍保存待补查；指定报告中可继续的关联研究时，将问题保存回原项目，绑定原步骤、沿用方法/当前资料范围和累计预算，不启动模型。同一报告/原轮/说明的重试复用已存步骤。
- 定义的文字/版本变更与来源有效性变化分别在`domain_definitions_changed`和`definition_validity_changed`中表示，避免将来源失效当成工作类型定义被修订。
- 观察面板的`include_archived:true`可同时冻结每个来源最近的归档版本；`public_document_ids`可限定至多20个版本，显式提供该列表即启用归档观察。该操作不访问网页。归档来源数与岗位分母分开；未观察过的旧面板不能作为“零资料”基线。
- 比较报告的`archived_changes`区分网页正文、用户修订、提取结果、换行、原始文件/元数据、归档不可用及观察范围变化；复用`PublicDocumentService.compare`，不把资料变化解释为岗位职责变化。`archived_documents`/`public_document_ids`可用于建立只有归档资料的新研究。
- `research_impact.runs[].document_updates`明确原研究限定的旧归档及同来源较晚版本。用户保存对应复核问题时，沿用既有范围修订服务替换这些版本，保留`scope_history`与旧回答，不增加其他来源；重复保存不再次改范围或重置预算。旧判断只作为历史对照，须读取当前原文后再说明修订。
- 新地图合同`work-map-v3-work-relations`以`work_relations`连接business/task/deliverable/responsibility/ability/tool；每条保留两端表述、predicate方向、依据判断、解释性质及适用边界。新Agent不重复输出旧`ability_relations`；历史地图仍按原字段读取、展示和保存，不改原报告。旧合同的未完研究继续受既有方法指纹约束，不能带着旧预算静默改用新合同。
- `POST /api/knowledge/research/{id}`可用`work_relation_index`（0–17）保存本轮原生关系；与`work_type_index`、旧`ability_relation_index`三选一。方向及内容从原研究读取，客户端不能另填。派生关系的`scope.evidence_scope`区分job、work_material与public_context；公开背景不证明岗位个人责任/必备资格，用户资料不证明实际执行。来源范围、既有审核、冲突及失效机制保持有效。
- 岗位画像补充分类改用已保存、已采纳且在当前资料范围内有效的工作类型定义，不再自动提供旧五类。`classification_definitions`保留本次使用的定义及边界，候选附`definition_id`/`definition_version`；没有有效定义时保持未分类，核实问题仍可生成。定义/范围变化会使旧缓存过时，旧画像内容不改写。
- `GET /api/profiles/{id}`的`classification_options`供画像页使用同一组当前有效定义；人工归类复用`POST /api/knowledge/jobs/{id}/domains`。命令`product profiles correct`可用`{domain_ids,reason}`走同一服务；旧`domains`参数仅保留既有纠正兼容。分类采用的定义进入原研究依赖，遗忘其来源时连同派生画像及复制了定义名称的纠正清理，原始JD保持。

对应命令共用上述服务：`work-observer product research-knowledge get --id RUN_ID`；`product research-knowledge save --id RUN_ID --file INPUT.json`；`product updates report --id REPORT_ID`；`product updates followup --id REPORT_ID --file INPUT.json`。结构化文件字段与同名API相同，使用`--db`指定独立数据目录。

2026 年 11 月 18 日。实现入口为 `api/web.py`、`api/product.py` 与 `api/operations.py`。以下接口复用 CLI 和业务服务，页面可以直接完成对应操作。接口不提供自由 SQL、任意本机文件读取、来源解锁、认证恢复、投递或消息发送。

## 请求与访问

默认地址 `http://127.0.0.1:8765`。JSON 写请求使用 `Content-Type: application/json`，请求体最多 512000 字节，页面自动携带 `x-wo-token`。默认仅接受本机地址及同源请求。部署访问配置启用后，还需通过工作空间登录或服务端配置的 Bearer 令牌认证；密钥不放在查询参数、岗位或研究资料中。

成功返回业务 JSON；参数结构错误为 422，未找到记录一般为 404，研究忙或状态不允许为 409，其他业务拒绝通常为 400。错误格式为 `{"error_code":"稳定错误码","message":"中文提示"}`。具体字段校验以相应 Pydantic 输入类型为准，未知字段会被拒绝。时间为含时区 ISO 8601，内部统一 UTC。

## 资料与原文

| 方法与路径 | 输入与返回 |
| --- | --- |
| `GET /api/overview` | 岗位、完整正文、公司数量；来源本地暂停状态；模型配置状态；活动研究 ID |
| `GET /api/jobs` | 查询参数：`city/company/keyword/education/experience/salary_min/salary_max/salary_unit/detail/source/limit/offset`；返回 `jobs`、分页前 `counts`、筛选口径 |
| `GET /api/jobs/{id}` | 当前业务字段、公司关联、完整正文、人工补充；不返回内部访问参数 |
| `GET /api/jobs/{id}/history` | 已保存观察与内容版本，区分原始取得、本地处理和来源类型 |
| `GET /api/companies?name=...` | 公司摘要；未核实身份明确标记 |
| `GET /api/companies/{id}` | 公司及相关岗位 |
| `GET /api/sources/{id}` | 招聘或人工资料的版本与文件完整性；不输出原始文件路径 |
| `GET /api/search?term=Python&term=RAG` | 兼容原字面检索；可选 `city/company` |
| `POST /api/import` | `ManualJD` JSON，至少 `title/company/description`；返回导入批次、岗位与去重数量 |
| `GET /api/public-documents/{id}` | 已归档公开网页的元数据、纯文本正文、引用片段及完整性；只读归档，不发网络请求 |

同一薪资周期才做区间筛选，学历与经验采用原文字面条件。`matched/unknown/excluded` 分开，未知不默认符合。`source_published_at=null` 表示未知，不用导入或采集时间替代。人工资料的 `data_kind=user_provided/synthetic` 区分用户提供与演示模拟，不能把演示资料计作真实市场样本。

## 研究、恢复与导出

创建研究示例：

```json
{
  "question": "这些岗位分别承担什么任务，需要哪些能力与工具？",
  "filters": {"city": "上海", "detail": "detail"},
  "job_ids": null,
  "offline": false,
  "max_calls": 10,
  "timeout": 180,
  "allow_public": false
}
```

`question` 最多 4000 字符；指定岗位 1–20 个；模型调用 2–12 次，执行时长 1–300 秒。`allow_public` 默认关闭，仅按研究工具网关的数量与网址范围开放公开资料调查。它不开放招聘源，也不解除暂停。

| 方法与路径 | 行为 |
| --- | --- |
| `POST /api/research` | 返回 202 和 `{id,state}`；保存持久研究记录后异步执行 |
| `GET /api/research` | 研究历史摘要，不返回模型上下文或检查点 |
| `GET /api/research/{id}` | `state/result/progress/resumable/saved/error_code`；进度包含计划、工具轨迹和累计调用 |
| `POST /api/research/{id}/cancel` | 停止正在执行的研究，保留中断检查点 |
| `POST /api/research/{id}/resume` | 继续可恢复研究；沿用冻结范围、原文、方法配置和累计预算，不通过恢复重置次数 |
| `POST /api/research/{id}/save` | 显式导出 JSON/Markdown；同次研究重复保存返回同一 `report_id` |
| `GET /api/reports` | 已导出的研究列表 |
| `GET /api/reports/{id}` | 读取冻结结果，无模型调用 |
| `GET /api/reports/{id}/download/{json或md}` | 下载对应格式 |

运行状态与分析状态分开。运行可为 `running/finished/interrupted/failed`；结果状态可为 `completed/evidence_only/insufficient_evidence/incomplete/failed`。`finished` 只表示执行结束，不能单凭它认定研究成功。离线 `evidence_only` 没有模型判断。研究结果保留计划、样本口径、判断、缺口、来源引用、轨迹、复盘和已知用量；费用未知时保留为空。

引用片段至少含 `id/quote/start/end/full_text_length/source/observed_at`。招聘正文额外关联 `job_id/snapshot_id/document_id` 与文件指纹；公开搜索证据标明 `search_answer/search_excerpt`，不能冒充原始网页全文；归档网页使用 `public_document` 和 `public_document_id`。公开网页不能自动证明某个岗位与公司产品之间的关系，仍需原文支持或明确标为推断。

## 业务记忆、画像与个人条件

| 方法与路径 | 输入与行为 |
| --- | --- |
| `GET /api/memories` | 当前偏好、纠正、待采纳知识；历史可用对应查询选项查看 |
| `POST /api/memories` | 偏好或纠正：`{kind,content,job_id?}`；知识：`{kind:"knowledge",source_run_id,claim_index,job_id?}`，服务端从已完成研究取内容和原始引用 |
| `POST /api/memories/{id}/revise` | `{content}`，创建新版本并替代旧版本 |
| `POST /api/memories/{id}/withdraw` | 停止默认召回，保留变更历史 |
| `POST /api/memories/{id}/activate` | 显式采纳知识候选并重新核对引用；不把派生结论变成独立来源 |
| `DELETE /api/memories/{id}` | 忘记整条偏好/纠正的所有版本并清理关联可删除派生上下文；知识请使用撤回 |
| `GET /api/profiles/{job_id}` | 已保存岗位画像及有效性/版本信息 |
| `POST /api/profiles/{job_id}` | `{offline:false}`，分析或复用有效缓存；离线仅整理证据 |
| `POST /api/profiles/{job_id}/correction` | `{domains:[...],reason:"..."}`，岗位范围领域纠正 |
| `GET /api/preferences` | 结构化个人条件及版本；未设置时返回空条件，不虚构履历 |
| `POST /api/preferences` | `cities/salary_min/salary_max/salary_unit/employment_types/desired_tasks` |
| `POST /api/matches` | `{filters:{...},preferences:{...}}`；明确条件不符、目标不符与待核实信息分别呈现 |

自然语言偏好不会被自动解释为硬性筛选条件。人工纠正只影响其作用域，不推广到全公司。知识引用失效或岗位版本改变后，不默认把旧知识当作当前判断。

“忘记”会把个人记忆版本链的内容替换为 `[已忘记]`，停止召回，删除采用这些版本的可重建画像；关联研究结果与完整检查点清空、状态标为 `invalidated`，不能继续恢复，需重新发起研究。当前报告目录里关联 JSON/Markdown 导出一并清理，原始岗位与公开原文保留。下载到其他目录的副本和既有备份不自动覆盖。历史查看和下载的 `audit` 字段提示记忆已更新/撤回、来源当前版本变化、原文完整性变化或方法已回退；这些提示不重写旧报告中的来源事实。

## 增强检索与统计

`POST /api/retrieval` 输入：

```json
{"terms":["Agent","后端可靠性"],"filters":{"city":"上海"},"job_ids":null,"as_of":null,"aliases":true}
```

返回 `retrieval` 与 `statistics`。前者包含 `expanded_terms/evidence/tag_only_hits/sample/context_characters`；后者包含 `sample/statistics/match_mode/interpretation`。每项统计给出字面命中岗位数 `literal_jobs`、明确分母 `denominator`、占比 `ratio`、未知范围命中数 `unknown_scope_literal_jobs`。分母为完整范围内**明确匹配且有详情正文**的去重岗位，不是检索前几条；零分母时占比为空。

字面出现不表示必备要求，同义扩展仅用于召回。来源标签命中和正文引用分开；只有标签没有正文时不伪造正文证据。检索总上下文最多 7000 字符，单片段最多 700 字符，重叠片段保留真实字符位置。历史 `as_of` 必须含时区，同时限制来源观察与本地处理时间；筛选字段从当时版本重建，后入库的旧回放也不能进入过去研究。版本未保存的发布时间保持未知。

## 策略评测、显式启用与回退

| 方法与路径 | 行为 |
| --- | --- |
| `GET /api/strategies` | 策略、实验、事件、当前配置和可编辑候选模板 |
| `POST /api/strategies` | `{name,aliases:{"Agent":["智能体"]}}`，创建不可变候选配置 |
| `POST /api/strategies/{id}/evaluate` | 运行完整锁定模拟问题集；不允许客户端修改门槛、答案或挑选测试问题 |
| `POST /api/strategies/{id}/activate` | 已通过且评测基线仍等于当前活动配置时显式启用 |
| `POST /api/strategies/monitor` | 固定护栏复查；关键回归、来源版本或预算护栏失败时程序自动回退 |
| `POST /api/strategies/rollback` | `{reason}`，显式切回上一稳定配置并记录原因 |

初始配置为 `literal-v1`，纯字面检索、空别名表。别名模板只有创建候选、实际评测接受并显式启用后才影响默认检索。评测锁定当前活动策略 ID、配置及指纹，候选与其在同一固定模拟资料上配对执行检索，计算 Recall@3，校验关键案例、原文位置、来源版本、上下文与调用预算。结果为 `accepted/rejected/insufficient`，保留逐例指标和夹具指纹。

这批可分发夹具全部为 `synthetic_test_only`，只验证检索机制，不证明真实市场召回改善、模型语义质量或新增采集能力。活动基线已变化时拒绝旧评测直接启用；被拒绝或回退的版本需新候选，不能重新直接启用。检查/回退返回 `affected_strategy_ids`，调用方可据此标记采用相关方法的旧报告；来源原文和历史实验不删除。

## 观察配置、任务和收件箱

| 方法与路径 | 输入与行为 |
| --- | --- |
| `GET /api/operations` | 观察配置、任务、计划和收件箱 |
| `POST /api/watchsets` | `{name,spec}`，保存 `WatchsetSpec` 及版本 |
| `POST /api/schedules` | `{watchset_id,hour,minute,enabled,schedule_id?}`，持久计划配置；默认不启用 |
| `POST /api/tasks` | `{watchset_id}`，创建持久采集任务 |
| `POST /api/tasks/{id}/run` | 有界异步执行，返回 202；招聘源暂停仍在联网前阻止 |
| `POST /api/tasks/{id}/retry` | 按任务规则重试，不解除来源暂停 |
| `POST /api/operations/tick` | 检查计划到期并创建幂等任务，不等于已成功采集 |
| `POST /api/inbox/followup` | `{question,source_run_id?}`，保存后续研究问题 |
| `POST /api/inbox/{id}/read` | 标为已读 |
| `POST /api/inbox/{id}/resolve` | 处理完成，保留记录 |

采集任务失败、来源暂停和资料没有变化是不同结果。保存计划不会恢复招聘认证或清除 code 37 停止；实际调度还需要独立运行相应执行入口。研究、业务库知识、公开原文与运行检查点各自承担不同职责，不互相冒充来源事实。

## 0.4补充：动态合同、只读入口及CSV/截图

`GET /api/openapi.json`按实际路由和Pydantic模型生成机器合同，`GET /api/docs`提供不依赖外部CDN的中文说明。当前50个路径；方法/字段/引用覆盖有自动检查。部署模式需要Bearer或签名Cookie；本机页面写操作用`x-wo-token`，Bearer无需浏览器CSRF令牌。所有错误保留`error_code`及中文`message`，不会返回凭据、原始请求或任意本机路径。

新增直接只读入口：`GET /api/watchsets?history=1`、`/api/schedules`、`/api/tasks`、`/api/tasks/{id}`、`/api/inbox?unread=1`、`/api/collection-runs`、`/api/collection-runs/{id}`。`GET /api/jobs/{id}/compare-history`比较最近两个不同详情版本；不足时明确`insufficient_history`，不会把list/detail差异称为企业修改。

| 方法与路径 | 输入与结果 |
| --- | --- |
| `POST /api/imports/csv/preview` | `{csv_text}`，UTF-8/BOM、20行/500KB；逐行草稿/错误，不写岗位 |
| `POST /api/imports/csv/commit` | `{rows:[{row_number,jd}]}`，用户核对后的选中行；逐行独立保存，部分失败保留成功 |
| `POST /api/import-assets?data_kind=synthetic` | `image/png`/`image/jpeg`/`image/webp`原始字节，最多5MB，只归档图片；普通用户资料用`user_provided` |
| `GET /api/import-assets/{id}/image` | 已归档原图，核对SHA后按图片类型返回；不接受URL或本机路径 |
| `POST /api/import-assets/{id}/extract` | `{allow_model:true}`，显式同意后固定一次视觉请求；仅返回可编辑草稿，不自动创建岗位 |
| `POST /api/import` | 保存图文核对结果时携带有效`import_asset_id`、`ocr_reviewed:true`与相同`data_kind`；来源保留原图关联与核对性质 |
| `DELETE /api/memories/{id}` | 只忘记偏好/纠正，清理版本链及相关派生闭包；原JD保留，独立下载/备份不自动改写 |

视觉读取失败或未同意不会发送模型；不能据OCR填入未知字段或发布时间。图片人工转录与视觉草稿人工核对分别标`image_manual_review`/`ocr_manual_review`，均不冒充直接平台原文。CSV/API/CLI的资料身份和去重共用原人工导入服务。

研究结果可含`knowledge_candidates`、`strategy_candidate.evaluation`；Agent只能提出本地候选并读取固定反馈，不能直接启用或更改门槛/来源。引用可用本次返回的`citation_key`（E1等），程序只按精确映射回链不可变快照ID，不模糊纠正不存在的引用。


## 0.5新增合同

具体字段以运行中的`/api/openapi.json`为准，extra=forbid拒绝未定义字段，所有写入继续同源/令牌保护。

| 路径 | 主要操作 |
| --- | --- |
| `/api/projects`、`/{id}` | 创建/查看、PATCH修订范围目标、DELETE忘记整个项目 |
| `/api/projects/{id}/steps`、`/steps/{step_id}/review` | 带revision追问、调查；accept/wait/retry须说明 |
| `/api/projects/{id}/run`、`/pause` | 有限执行/暂停；人审与资料等待不自循环 |
| `/api/retrieval/unified` | 岗位、公文、历史截止与项目范围统一检索 |
| `/api/knowledge/domains`、`/relations`及`/{id}/review` | 定义版本、关系正反例候选和显式审核 |
| `/api/knowledge/collection`、`/jobs/{id}/domains` | 完整集合及人工领域纠正 |
| `/api/quality/runs/{id}`、`/reviews` | 原结果SHA绑定、六维业务核对和逐claim支持性 |
| `/api/updates/captures`、`/compare`、`/reports/{id}`及`/followup` | 冻结、归因、查看与幂等后续问题 |
| `/api/data-quality/duplicates/scan`、`/review`、`/reviews` | 只提疑似，关联不删除原资料/改变分母 |
| `/api/data-quality/screenshot-targets`、`/regions`及`/regions/{id}/withdraw` | 人工bbox、精确正文span与原图SHA |

项目默认36调用/900秒/6轮/4公开请求；硬上限72/1800/12/8，单步12调用/300秒。`source_key`保证上游报告重试、备份恢复后不重复造项目；复用键但目标/范围不同报冲突。过时revision不能覆盖新修改。项目运行须从项目入口恢复。

记忆新增范围/项目/主体/有效期/origin；冲突通过accept/reject明确处理。Agent评审不能人工批准；引用存在/执行结束不是业务质量通过。遗忘恢复未完或报告目录不符时API返回503并不提供派生内容。模型工具无这些HTTP写权限、任意文件/SQL、来源恢复或发布能力。
