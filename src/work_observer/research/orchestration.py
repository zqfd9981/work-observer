"""Model-authored investigation briefs and a local, scoped LangGraph retrieval workflow.

Query rewriting is performed by the planning model. Retrieval remains lexical;
reciprocal-rank fusion is not a semantic reranker or an embedding implementation.
"""

from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context
from pydantic import BaseModel, ConfigDict, Field

from work_observer.retrieval.unified import UnifiedRetrieval
from work_observer.text_match import match_text


class Query(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    terms: list[str] = Field(min_length=1, max_length=5)
    reason: str = Field(min_length=1, max_length=200)


class InvestigationTask(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    intent: Literal["understand", "compare", "verify", "practice", "interview"]
    question: str = Field(min_length=1, max_length=600)
    completion: str = Field(min_length=1, max_length=300)
    queries: list[Query] = Field(min_length=1, max_length=2)
    retry_queries: list[Query] = Field(min_length=1, max_length=2)


class InvestigationBrief(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    objective: str = Field(min_length=1, max_length=1200)
    tasks: list[InvestigationTask] = Field(min_length=1, max_length=3)
    missing_context: list[str] = Field(max_length=4)


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


def outcomes(values, investigation, claims, evidence):
    rows = [TaskOutcome.model_validate(value) for value in values]
    if sorted(row.task_index for row in rows) != list(range(len(investigation["tasks"]))):
        raise ValueError("请逐项回应当前调查任务，不遗漏或重复。")
    for row in rows:
        if any(type(index) is not int or not 0 <= index < len(claims)
               for index in row.claim_indices):
            raise ValueError("任务须关联本次实际提交的判断序号（从0开始）。")
        intent = investigation["tasks"][row.task_index]["intent"]
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
    return [row.model_dump() for row in sorted(rows, key=lambda row: row.task_index)]


def planning_tool():
    schema = InvestigationBrief.model_json_schema()
    # Keep query validation in both the provider contract and local validation.
    schema["$defs"]["Query"]["properties"]["terms"]["items"].update(
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
                aliases, personal_document_ids=(), previous=None):
    """No network/model work here. All branches share the same immutable SQL scope."""
    brief = InvestigationBrief.model_validate(brief)
    if previous and [(task.intent, task.question) for task in brief.tasks] != [
        (task["intent"], task["question"]) for task in previous["tasks"]
    ]:
        raise ValueError("补查时保留已识别的全部问题与意图，只调整查询和完成条件。")
    for task in brief.tasks:
        for query in [*task.queries, *task.retry_queries]:
            if any(not term.strip() or len(term) > 100 for term in query.terms):
                raise ValueError("检索词须为1至100字。")
    if any(not value.strip() or len(value) > 300 for value in brief.missing_context):
        raise ValueError("待补背景须为1至300字。")

    retrieval = UnifiedRetrieval(repository, alias_groups=aliases)
    personal_ids = set(personal_document_ids) & set(scope["archived_public_ids"])

    def retrieve(state, *, retry=False):
        queries = state["task"]["retry_queries" if retry else "queries"]
        batches, attempts = list(state["batches"]), list(state["attempts"])
        seen = {tuple(sorted(match_text(t) for t in row["terms"])) for row in attempts}
        for query in queries:
            terms = list(dict.fromkeys(term.strip() for term in query["terms"]))
            key = tuple(sorted(match_text(t) for t in terms))
            if key in seen:
                continue
            seen.add(key)
            # Work evidence and personal evidence stay in separate recall channels.
            work_ids = [key for key in scope["archived_public_ids"] if key not in personal_ids]
            result = retrieval.search(
                terms, filters=scope["filters"], job_ids=[job["id"] for job in scope["jobs"]],
                public_document_ids=work_ids, project_id=project_id, as_of=as_of,
                include_knowledge=False, limit=10,
            )
            batches.append(result["evidence"])
            attempts.append({"terms": terms, "reason": query["reason"],
                             "stage": "retry" if retry else "primary", "channel": "work",
                             "candidates": len(result["evidence"]),
                             "excluded_integrity_ids": result["excluded_integrity_ids"]})
            if state["task"]["intent"] in {"practice", "interview", "verify"} and personal_ids:
                personal = retrieval.search(
                    terms, job_ids=[], public_document_ids=sorted(personal_ids),
                    project_id=project_id, as_of=as_of, include_knowledge=False, limit=4,
                )
                batches.append(personal["evidence"])
                attempts.append({"terms": terms, "reason": query["reason"],
                                 "stage": "retry" if retry else "primary", "channel": "personal",
                                 "candidates": len(personal["evidence"]),
                                 "excluded_integrity_ids": personal["excluded_integrity_ids"]})
        return {"batches": batches, "attempts": attempts}

    def assess(state):
        work_sources = {source_key(item) for batch in state["batches"] for item in batch
                        if item.get("public_document_id") not in personal_ids}
        minimum = 2 if state["task"]["intent"] == "compare" else 1
        return {"needs_retry": len(work_sources) < minimum}

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
        sources = {source_key(row) for row in rows if row["id"] in seen
                   and row.get("public_document_id") not in personal_ids}
        task["retrieval_status"] = (
            "no_work_evidence" if not sources else "comparison_needs_other_source"
            if task["intent"] == "compare" and len(sources) < 2 else "candidates_need_reading"
        )
    return {
        "original_question": original_question, "objective": brief.objective, "tasks": tasks,
        "missing_context": brief.missing_context, "evidence": evidence,
        "context_characters": characters, "engine": "langgraph",
        "retrieval_mode": "model_queries_lexical_rrf",
        "scope": {"job_ids": [job["id"] for job in scope["jobs"]],
                  "public_document_ids": scope["archived_public_ids"], "as_of": as_of},
        "notice": "命中只表示待核对候选，不是语义相关性或问题已回答。对比两份来源不保证两侧齐全。"
        "无命中不代表不存在，可按目录读原文或调整一次查询；个人自述不证明岗位职责。",
    }
