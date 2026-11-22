"""Model-authored investigation briefs and a local, scoped LangGraph retrieval workflow.

Query rewriting is performed by the planning model. Retrieval remains lexical;
reciprocal-rank fusion is not a semantic reranker or an embedding implementation.
"""

from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context
from pydantic import BaseModel, ConfigDict, Field

from work_observer.research.question_scope import ScopeConstraint, ScopeRelease, narrow
from work_observer.retrieval.unified import UnifiedRetrieval
from work_observer.text_match import match_text


class Query(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    terms: list[str] = Field(min_length=1, max_length=5)
    reason: str = Field(min_length=1, max_length=200)
    required_terms: list[str] = Field(default_factory=list, max_length=3)


class InvestigationTask(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    intent: Literal["understand", "compare", "verify", "practice", "interview"]
    question: str = Field(min_length=1, max_length=600)
    completion: str = Field(min_length=1, max_length=300)
    queries: list[Query] = Field(min_length=1, max_length=2)
    retry_queries: list[Query] = Field(min_length=1, max_length=2)
    source_job_ids: list[str] = Field(default_factory=list, max_length=6)
    source_document_ids: list[str] = Field(default_factory=list, max_length=6)


class InvestigationBrief(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    objective: str = Field(min_length=1, max_length=1200)
    tasks: list[InvestigationTask] = Field(min_length=1, max_length=3)
    missing_context: list[str] = Field(max_length=4)
    constraints: list[ScopeConstraint] = Field(default_factory=list, max_length=4)
    released_constraints: list[ScopeRelease] = Field(default_factory=list, max_length=4)


class TaskOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    task_index: int = Field(ge=0, le=2, strict=True)
    status: Literal["answered", "partial", "needs_context"]
    answer: str = Field(min_length=1, max_length=1600)
    claim_indices: list[int] = Field(max_length=12)
    questions: list[str] = Field(max_length=3)


def execution_tools(definitions):
    from copy import deepcopy

    definitions = deepcopy(definitions)
    for definition in definitions:
        if definition["name"] == "finish_research":
            schema = definition["parameters"]
            outcome = TaskOutcome.model_json_schema()
            schema.setdefault("$defs", {})["TaskOutcome"] = outcome
            schema["properties"]["task_outcomes"] = {
                "type": "array", "minItems": 1, "maxItems": 3,
                "items": {"$ref": "#/$defs/TaskOutcome"},
            }
            schema["required"].append("task_outcomes")
            schema["properties"]["claims"]["minItems"] = 0
    return [*definitions, planning_tool()]


def outcomes(values, investigation, claims, evidence, *, application_plan=None):
    rows = [TaskOutcome.model_validate(value) for value in values]
    if sorted(row.task_index for row in rows) != list(range(len(investigation["tasks"]))):
        raise ValueError("请逐项回应当前调查任务，不遗漏或重复。")
    effective = investigation.get("effective_scope")
    if effective:
        references = [claim.evidence_ids for claim in claims]
        references.extend(action["evidence_ids"] for action in (
            application_plan or {}
        ).get("actions", []))
        for keys in references:
            for key in keys:
                item = evidence.get(key, {})
                if ((item.get("job_id") and item["job_id"] not in effective["job_ids"])
                        or (item.get("public_document_id") and item["public_document_id"]
                            not in effective["public_document_ids"])):
                    raise ValueError("本次回答不得引用明确条件之外的资料；不能因检索少就放宽范围。")
    for row in rows:
        if any(type(index) is not int or not 0 <= index < len(claims)
               for index in row.claim_indices):
            raise ValueError("任务须关联本次实际提交的判断序号（从0开始）。")
        intent = investigation["tasks"][row.task_index]["intent"]
        if (row.status == "answered" and investigation["tasks"][row.task_index].get(
            "retrieval_status",
        ) in {"comparison_targets_needed", "scope_has_no_matching_jobs"}):
            raise ValueError("比较对象尚未明确，不能把局部查询标成已完整回答。")
        if row.questions and intent != "interview":
            raise ValueError("面试题仅放在面试任务，其他未知写入该项回答。")
        if any(not value.strip() or len(value) > 600 or not any(c in value for c in "?？")
               for value in row.questions):
            raise ValueError("请提供600字以内、带问号的完整面试题。")
        if row.status == "answered" and intent in {"understand", "compare", "verify"}:
            sources = {source_key(evidence[key]) for index in row.claim_indices
                       for key in claims[index].evidence_ids if key in evidence}
            if len(sources) < (2 if intent == "compare" else 1):
                raise ValueError(
                    "已回答的解释或验证须关联原文；对比须保留两侧来源，否则标为部分回答。",
                )
            required = set(investigation["tasks"][row.task_index].get("required_source_keys", []))
            if required - sources:
                raise ValueError("比较的每一侧都须有对应原文，其他岗位或背景资料不能替代缺失一侧。")
    return [row.model_dump() for row in sorted(rows, key=lambda row: row.task_index)]


def planning_tool():
    schema = InvestigationBrief.model_json_schema()
    schema["required"] = list(schema["properties"])
    for definition in schema["$defs"].values():
        if definition.get("properties"):
            definition["required"] = list(definition["properties"])
    # Keep query validation in both the provider contract and local validation.
    schema["$defs"]["Query"]["properties"]["terms"]["items"].update(
        minLength=1, maxLength=100,
    )
    schema["$defs"]["Query"]["properties"]["required_terms"]["items"].update(
        minLength=1, maxLength=100,
    )
    schema["properties"]["missing_context"]["items"].update(minLength=1, maxLength=300)
    return {
        "type": "function", "name": "plan_investigation", "strict": True,
        "description": "理解用户原问题，拆分最多3项不同意图，改写检索查询并调查冻结原文。"
        "首次必须使用；可根据实际检索缺口整体调整一次，须保留尚未回答的用户要求。"
        "不改变范围，不保存认识或执行个人练习。",
        "parameters": schema,
    }


POLICY = """
本轮启用意图理解与调查编排。先用plan_investigation解释用户真正想解决的问题，
不要按关键词或页面入口直接归类。原问题和用户明确选中的上下文具有优先级。
将复合请求拆成最多3项：understand解释工作；compare保留两侧条件对比；verify用原文检验
一种认识及反例；practice设计最小验证；interview准备基于事实的面试解释或追问。
每项question补齐对话指代但不虚构公司、时间、岗位、经历或比较对象；completion说明怎样才算回答。
queries用资料可能采用的表达改写，retry_queries换一种表达或更具体的任务/交付物切入，
不能只是重复原词。程序会在冻结范围内分项检索、融合，并在无命中或对比不足两份来源时补查。
queries的required_terms指定这组查询不能丢掉的主题锚点，如问题是Agent记忆，填["记忆"]，
防止只因泛词Agent命中就混入其他工作线。每个锚点都须在片段正文出现，可用配置别名；
retry_queries可以换另一种主题表述，不得以删除关键限定来制造命中。没有锚点填[]。
source_job_ids/source_document_ids填写本项需要调查或比较的确切来源ID，只能选fixed_scope内的ID。
比较岗位时逐侧选岗位，比较资料时逐份选资料；对比两份其他资料不能替代所选岗位的一侧。
不明确时填[]并保留缺口；当范围中有多份岗位且未细分时，比较会逐侧检查这些岗位。
constraints提取用户明确的城市city、公司company、岗位名称role或岗位来源source条件，
source_text引用本次用户原话，value保留原名称，source值使用boss/manual。只是工作主题不要当岗位名称筛选。
程序会在已选范围内按保存的字段缩小检索范围；字段未知会单列，不冒充符合要求。
memory_recall是用本轮改写查询找回的旧认识、调查、研究与实验线索。它们与evidence分开，
不能用record_id当原文引用；相关预览可能省略末尾条件，需要时按read_tool读取完整记录。
检验旧认识或对比实验时，先保留其原问题、条件、负面观察和剩余未知，再查本轮原文，不自动采用旧结论。
continued_discussion.investigation中的约束默认沿用；本次明确换城市或公司时用新constraints覆盖对应字段，
本次明确放宽时用released_constraints的field和source_text记录，不能因没命中就取消原条件。
未说明的条件填[]。年份若指招聘发布时间而归档未保存，列missing_context，不伪装成按发布时间筛选。
查询只是定位，不证明相关或结论成立；收到候选原文后核对其主体、限定和反例。
个人资料仅支持用户自述，不能证明岗位职责；旧认识须查原文才能判断真伪。
缺少必要背景时在missing_context明确需要补什么，同时推进仍可调查的部分。
不得将用户请求的城市、岗位、时期悄悄忽略：与fixed_scope不符或无法筛定时列为缺口，
不擅自替换范围或假装已经过滤。首次规划后可以直接读原文；检索不足可改写规划一次，
须说明调整原因并保留完整用户目标，不能用缩减任务掩盖失败。
调整时保留已有tasks的question、intent和顺序，只修改查询、完成条件、目标解释与待补背景。
最终逐项回应所有意图：比较给两侧引用；验证分支持/挑战/未知；练习写预期、产物、检查方式，
不声称已执行；面试只能重组已读事实，区分工作理解与本人经历。无证据的建议和待补背景放gaps，
有个人应用计划工具时可提出一个最小练习，由用户决定是否保存。不要替用户执行或自动采用认识。
用户要求练习或进一步验证时，使用现有application_plan给可保存的最小设计，不只把练习写成文字。
没有个人背景时只设计理解验证，列出构造输入、待检验预期、产物、检查方式与未控制条件，
不据此判断个人适配；有背景也不虚构经验。没有练习或验证意图时application_plan填null。
finish_research用task_outcomes逐项回答当前任务，task_index和claim_indices均从0开始。
answer给该项可阅读的解释、对比、验证设计或面试问题；事实关联本次claims，推断标明推断。
questions只在interview任务填写最多3道完整面试题，其他任务填[]；题目会进入现有作答反馈流程。
缺资料用partial或needs_context，不把候选命中当已回答。完全无证据可提交空claims并写明缺口。
"""


class RetrievalState(TypedDict):
    task: dict
    batches: list
    attempts: list
    needs_retry: bool


def source_key(item):
    return item.get("public_document_id") or item.get("job_id") or item["document_id"]


def _fuse(batches):
    scores, items = {}, {}
    for batch in batches:
        seen = set()
        for rank, item in enumerate(batch, 1):
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            scores[item["id"]] = scores.get(item["id"], 0) + 1 / (60 + rank)
            items[item["id"]] = item
    ranked = sorted(items.values(), key=lambda item: (-scores[item["id"]], item["id"]))
    seen_sources, diverse, rest = set(), [], []
    for item in ranked:
        key = source_key(item)
        (rest if key in seen_sources else diverse).append(item)
        seen_sources.add(key)
    return [{**item, "retrieval": {**item.get("retrieval", {}),
                                  "fusion_score": scores[item["id"]]}}
            for item in [*diverse, *rest]]


def investigate(repository, brief, *, original_question, scope, project_id, as_of,
                aliases, personal_document_ids=(), previous=None, inherited_constraints=()):
    """No network/model work here. All branches share the same immutable SQL scope."""
    brief = InvestigationBrief.model_validate(brief)
    if previous and [(task.intent, task.question) for task in brief.tasks] != [
        (task["intent"], task["question"]) for task in previous["tasks"]
    ]:
        raise ValueError("补查时保留已识别的全部问题与意图，只调整查询和完成条件。")
    allowed_jobs = {job["id"] for job in scope["jobs"]}
    allowed_documents = set(scope["archived_public_ids"])
    for task in brief.tasks:
        if (set(task.source_job_ids) - allowed_jobs
                or set(task.source_document_ids) - allowed_documents):
            raise ValueError("调查对象须来自本轮冻结范围。")
        for query in [*task.queries, *task.retry_queries]:
            if any(not term.strip() or len(term) > 100
                   for term in [*query.terms, *query.required_terms]):
                raise ValueError("检索词须为1至100字。")
    if any(not value.strip() or len(value) > 300 for value in brief.missing_context):
        raise ValueError("待补背景须为1至300字。")
    narrowed = narrow(
        repository, brief.constraints, brief.released_constraints,
        original_question=original_question, scope=scope, as_of=as_of,
        inherited=inherited_constraints,
    )
    if previous and {row["field"]: match_text(row["value"]) for row in narrowed["constraints"]} != {
        row["field"]: match_text(row["value"]) for row in previous.get("constraints", [])
    }:
        raise ValueError("同轮补查保留用户原有范围条件，不能通过放宽范围制造命中。")
    effective_jobs = narrowed["effective_scope"]["job_ids"]
    effective_documents = narrowed["effective_scope"]["public_document_ids"]

    retrieval = UnifiedRetrieval(repository, alias_groups=aliases)
    personal_ids = set(personal_document_ids) & set(scope["archived_public_ids"])

    def query_key(row):
        return (tuple(sorted(match_text(t) for t in row["terms"])),
                tuple(sorted(match_text(t) for t in row.get("required_terms", []))))

    def targets(task):
        job_ids, document_ids = task["source_job_ids"], task["source_document_ids"]
        if task["intent"] == "compare" and not job_ids and not document_ids:
            if 1 < len(effective_jobs) <= 6:
                job_ids = sorted(effective_jobs)
            elif not allowed_jobs and 1 < len(set(effective_documents) - personal_ids) <= 6:
                document_ids = sorted(set(effective_documents) - personal_ids)
        return [("job", key) for key in job_ids] + [("document", key) for key in document_ids]

    def relevant_sources(task, items):
        explicit = {key for _, key in targets(task)}
        return {source_key(item) for item in items
                if item.get("public_document_id") not in personal_ids
                or source_key(item) in explicit}

    if previous:
        for task, old in zip(brief.tasks, previous["tasks"], strict=True):
            if {key for _, key in targets(task.model_dump())} != set(
                old.get("required_source_keys", []),
            ):
                raise ValueError("补查时保留原来的对比对象，不能换成更容易命中的来源。")

    def retrieve(state, *, retry=False):
        queries = state["task"]["retry_queries" if retry else "queries"]
        batches, attempts = list(state["batches"]), list(state["attempts"])
        seen = {query_key(row) for row in attempts}
        for query in queries:
            terms = list(dict.fromkeys(term.strip() for term in query["terms"]))
            key = query_key(query)
            if key in seen:
                continue
            seen.add(key)
            # Work evidence and personal evidence stay in separate recall channels.
            work_ids = [key for key in effective_documents if key not in personal_ids]
            result = retrieval.search(
                terms, filters=scope["filters"], job_ids=effective_jobs,
                public_document_ids=work_ids, project_id=project_id, as_of=as_of,
                include_knowledge=False, limit=10,
                required_terms=query["required_terms"],
            )
            batches.append(result["evidence"])
            attempts.append({"terms": terms, "reason": query["reason"],
                             "required_terms": query["required_terms"],
                             "stage": "retry" if retry else "primary", "channel": "work",
                             "candidates": len(result["evidence"]),
                             "excluded_integrity_ids": result["excluded_integrity_ids"]})
            # Recall each selected side independently so background documents cannot
            # crowd a target out of the pooled top-k before fusion.
            for kind, identity in targets(state["task"]):
                if kind == "document" and identity in personal_ids:
                    continue
                target_result = retrieval.search(
                    terms, filters=scope["filters"],
                    job_ids=[identity] if kind == "job" and identity in effective_jobs else [],
                    public_document_ids=[identity]
                    if kind == "document" and identity in effective_documents else [],
                    project_id=project_id, as_of=as_of, include_knowledge=False, limit=3,
                    required_terms=query["required_terms"],
                )
                batches.append(target_result["evidence"])
                attempts.append({"terms": terms, "reason": query["reason"],
                                 "required_terms": query["required_terms"],
                                 "stage": "retry" if retry else "primary", "channel": "work",
                                 "target_id": identity, "target_kind": kind,
                                 "candidates": len(target_result["evidence"]),
                                 "excluded_integrity_ids": target_result["excluded_integrity_ids"]})
            if state["task"]["intent"] in {"practice", "interview", "verify"} and personal_ids:
                personal = retrieval.search(
                    terms, job_ids=[],
                    public_document_ids=sorted(personal_ids & set(effective_documents)),
                    project_id=project_id, as_of=as_of, include_knowledge=False, limit=4,
                    required_terms=query["required_terms"],
                )
                batches.append(personal["evidence"])
                attempts.append({"terms": terms, "reason": query["reason"],
                                 "required_terms": query["required_terms"],
                                 "stage": "retry" if retry else "primary", "channel": "personal",
                                 "candidates": len(personal["evidence"]),
                                 "excluded_integrity_ids": personal["excluded_integrity_ids"]})
        return {"batches": batches, "attempts": attempts}

    def assess(state):
        sources = relevant_sources(state["task"],
                                   [item for batch in state["batches"] for item in batch])
        minimum = 2 if state["task"]["intent"] == "compare" else 1
        missing_targets = {key for _, key in targets(state["task"])} - sources
        return {"needs_retry": len(sources) < minimum or bool(missing_targets)}

    graph = StateGraph(RetrievalState)
    graph.add_node("retrieve", retrieve)
    graph.add_node("assess", assess)
    graph.add_node("retry", lambda state: retrieve(state, retry=True))
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "assess")
    graph.add_conditional_edges("assess", lambda state: "retry" if state["needs_retry"] else END)
    graph.add_edge("retry", END)
    runner = graph.compile()
    tasks, candidates = [], []
    for task in brief.tasks:
        with tracing_context(enabled=False):
            state = runner.invoke({"task": task.model_dump(), "batches": [], "attempts": [],
                                   "needs_retry": False})
        ranked = _fuse(state["batches"])
        candidates.append(ranked)
        tasks.append({**task.model_dump(), "attempts": state["attempts"],
                      "required_source_keys": [key for _, key in targets(task.model_dump())],
                      "candidate_sources": len({source_key(item) for item in ranked}),
                      "retried": any(row["stage"] == "retry" for row in state["attempts"])})
    # Round-robin across subquestions, then deduplicate under one context budget.
    evidence, seen, characters = [], set(), 0
    for rank in range(max(map(len, candidates), default=0)):
        for rows in candidates:
            if rank >= len(rows):
                continue
            item = rows[rank]
            if (item["id"] in seen or len(evidence) >= 10
                    or characters + len(item["quote"]) > 7000):
                continue
            evidence.append(item)
            seen.add(item["id"])
            characters += len(item["quote"])
    for task, rows in zip(tasks, candidates, strict=True):
        task["evidence_ids"] = [row["id"] for row in rows if row["id"] in seen]
        sources = relevant_sources(task, [row for row in rows if row["id"] in seen])
        task["source_coverage"] = [{
            "kind": kind, "id": key, "included": key in sources,
            "label": next((job.get("title") for job in scope["jobs"] if job["id"] == key), None)
            or next((doc.get("title") for doc in scope.get("public_document_titles", [])
                     if doc["id"] == key), "选中的资料"),
        } for kind, key in targets(task)]
        task["missing_source_keys"] = [row["id"] for row in task["source_coverage"]
                                       if not row["included"]]
        task["retrieval_status"] = (
            "no_work_evidence" if not sources else "comparison_needs_other_source"
            if task["intent"] == "compare" and (len(sources) < 2 or task["missing_source_keys"])
            else "target_evidence_missing" if task["missing_source_keys"]
            else "candidates_need_reading"
        )
        if (task["intent"] == "compare" and not task["required_source_keys"]
                and len(effective_jobs if allowed_jobs
                        else set(effective_documents) - personal_ids) > 6):
            task["retrieval_status"] = "comparison_targets_needed"
        if allowed_jobs and not effective_jobs and narrowed["constraints"]:
            task["retrieval_status"] = "scope_has_no_matching_jobs"
    return {
        **narrowed,
        "original_question": original_question, "objective": brief.objective, "tasks": tasks,
        "missing_context": brief.missing_context, "evidence": evidence,
        "context_characters": characters, "engine": "langgraph",
        "retrieval_mode": "model_queries_lexical_rrf",
        "scope": {"job_ids": [job["id"] for job in scope["jobs"]],
                  "public_document_ids": scope["archived_public_ids"], "as_of": as_of},
        "notice": "命中只表示待核对候选，不是语义相关性或问题已回答。对比两份来源不保证两侧齐全。"
        "无命中不代表不存在，可按目录读原文或调整一次查询；个人自述不证明岗位职责。",
    }
