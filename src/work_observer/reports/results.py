"""按需保存不可覆盖的研究结果及原文片段；不写回来源事实。"""

import hashlib
import json
import re
from pathlib import Path
from uuid import uuid4

from work_observer.connectors.mcp_probe import ProbeError


def render(result):
    counts = result["scope"]["counts"]
    lines = [
        f"# {result['question']}",
        "",
        f"状态：{result['status']}；时间：{result['created_at']}",
        f"SQL 范围 {counts['scope_total']} 个；匹配 {counts['matched']} 个；"
        f"条件未知 {counts['unknown']} 个；候选完整正文 {counts['candidate_details']} 个。",
        "",
        "## 本次候选",
        "",
    ]
    audit = result.get("audit") or {}
    if (
        audit.get("stale_memory")
        or audit.get("stale_knowledge")
        or audit.get("stale_dependencies")
        or audit.get("changed_sources")
        or audit.get("affected_strategy")
    ):
        lines.extend(["", "## 历史结果有效性提示", ""])
        if audit.get("stale_memory"):
            lines.append("- 本研究采用的偏好、纠正或知识已有更新、撤回或遗忘，请重新核对。")
        if audit.get("stale_knowledge"):
            lines.append("- 本研究参考的领域定义或关系已换版、撤回或失效，请按当前口径重新核对。")
        if audit.get("stale_dependencies"):
            lines.append("- 上游研究采用的偏好、纠正或知识已变化，派生认识需要重新核对。")
        if audit.get("changed_sources"):
            lines.append("- 部分来源或当前岗位版本已有变化；原报告仍按当时材料形成。")
        if audit.get("affected_strategy"):
            lines.append("- 本研究采用的检索策略已被替换或回退，不能据此声称当前方法仍有效。")
    for job in result["scope"]["jobs"]:
        lines.append(
            f"- {job['title']} · {job['company']} · `{job['id']}` · "
            f"{'有正文' if job['has_detail'] else '仅摘要'} · {job['match_status']}"
        )
    if result.get("plan"):
        lines.extend(["", "## 调查计划", "", *[f"- {step}" for step in result["plan"]["steps"]]])
    if result.get("memory_used"):
        lines.extend(["", "## 本次使用的业务记忆（不是独立来源）", ""])
        lines.extend(
            f"- {item['kind']} / 版本 {item['version']}：{item['content']}"
            for item in result["memory_used"]
        )
    lines.extend(["", "## 判断（模型分析）", ""])
    evidence = {item["id"]: item for item in result["evidence"]}
    labels = {key: f"E{index}" for index, key in enumerate(evidence, 1)}
    for claim in result["claims"]:
        cites = " ".join(
            f"[{labels[key]}](#{labels[key].lower()})" for key in claim["evidence_ids"]
        )
        category = {
            "business": "业务背景",
            "task": "任务",
            "deliverable": "交付物",
            "responsibility": "责任",
            "ability": "能力",
            "tool": "工具",
        }
        requirement = {"required": "必备", "preferred": "加分", "unspecified": "未明确性质"}
        lines.append(
            f"- {category[claim['category']]} / {requirement[claim['requirement']]}："
            f"{claim['text']} {cites}"
        )
    lines.extend(
        [
            "",
            "## 信息缺口与口径",
            "",
            *[f"- {gap}" for gap in result["gaps"]],
            "",
            "## 原文依据",
            "",
        ]
    )
    if result.get("review"):
        lines.extend(
            [
                "",
                "## 执行复盘",
                "",
                *[
                    f"- {check['name']}：{'通过' if check['passed'] else '待核对'}；"
                    f"{check['detail']}"
                    for check in result["review"]["checks"]
                ],
                *[f"- {note}" for note in result["review"]["limitations"]],
            ]
        )
    for key, item in evidence.items():
        if item.get("source") == "public_web":
            archived = item.get("evidence_kind") == "public_document"
            source_label = "归档公开正文" if archived else "公开搜索材料"
            lines.extend(
                [
                    f'<a id="{labels[key].lower()}"></a>',
                    f"### {labels[key]} · {source_label} · {item['title']}",
                    f"网址：{item['url']}；取得：{item['observed_at']}；发布时间：未知。",
                    f"材料类型：{item.get('evidence_kind', 'search_excerpt')}；"
                    + (
                        "已归档网页提取正文，不是招聘原文。"
                        if archived
                        else "搜索生成摘要或节选，不等于已核对网页全文。"
                    ),
                    "",
                    *["> " + line for line in item["quote"].splitlines()],
                    "",
                ]
            )
            continue
        lines.extend(
            [
                f'<a id="{labels[key].lower()}"></a>',
                f"### {labels[key]} · {item['title']} · {item['company']}",
                f"岗位 `{item['job_id']}`；版本 `{item['snapshot_id']}`；"
                f"文档 `{item['document_id']}`；字符 {item['start']}–{item['end']}。",
                f"来源 {item['source']}/{item['response_origin']}；模式 {item['mode']}；"
                f"取得 {item['observed_at']}；本地处理 {item['processed_at']}；"
                f"来源发布 {item['source_published_at'] or '未知'}。",
                "",
                *["> " + line for line in item["quote"].splitlines()],
                "",
            ]
        )
    return "\n".join(lines) + "\n"


def save_result(result, directory=Path("reports")):
    directory.mkdir(parents=True, exist_ok=True)
    identity = uuid4().hex
    payload = {**result, "report_id": identity}
    path = directory / f"{identity}.json"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    (directory / f"{identity}.md").write_text(render(payload), encoding="utf-8")
    return {
        "report_id": identity,
        "json": str(path.resolve()),
        "markdown": str(path.with_suffix(".md").resolve()),
    }


def read_result(identity, directory=Path("reports")):
    if not re.fullmatch(r"[a-f0-9]{32}", identity):
        raise ProbeError("INVALID_REPORT_ID")
    path = directory / f"{identity}.json"
    if not path.is_file():
        raise ProbeError("REPORT_NOT_FOUND")
    return json.loads(path.read_text(encoding="utf-8"))


def list_results(directory=Path("reports"), limit=20):
    results = []
    if directory.exists():
        for path in sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            if not re.fullmatch(r"[a-f0-9]{32}", path.stem):
                continue
            result = read_result(path.stem, directory)
            results.append(
                {key: result[key] for key in ("report_id", "question", "status", "created_at")}
            )
            if len(results) >= limit:
                break
    return results


def forget_reports(identities, directory=Path("reports")):
    """仅删除明确关联的当前导出产物，不碰来源、备份或目录外副本。"""
    directory = Path(directory).resolve()
    identities = list(dict.fromkeys(identities))
    if any(
        not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value)
        for value in identities
    ):
        raise ProbeError("INVALID_REPORT_ID")
    deleted, missing, targets = [], [], []
    for identity in identities:
        paths = [directory / f"{identity}.{extension}" for extension in ("json", "md")]
        # 不跟随链接删除其他目录的资料；先核对这一份的两个目标再改文件。
        if any(path.is_symlink() or path.resolve().parent != directory for path in paths):
            raise ProbeError("REPORT_PATH_DENIED")
        targets.append((identity, paths))
    for identity, paths in targets:
        found = False
        for path in paths:
            if path.is_file():
                path.unlink()
                found = True
        (deleted if found else missing).append(identity)
    return {
        "deleted_report_ids": deleted,
        "missing_report_ids": missing,
        "scope": "仅当前报告目录的关联JSON/Markdown；独立下载副本、备份与原始资料不自动删除。",
    }


def audit_result(result, repository):
    """核对引用、业务记忆与方法版本；保留历史原文，不重写旧判断。"""
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from work_observer.connectors.public_models import PublicDocument
    from work_observer.memory.service import MemoryService
    from work_observer.storage.models import (
        Job,
        JobObservation,
        JobSnapshot,
        MemoryRecord,
        SourceDocument,
    )
    from work_observer.tracking.models import RetrievalStrategy

    memory_issues, changed_sources, affected_strategy = [], [], []
    memory = MemoryService(repository)
    with Session(repository.engine) as session:
        for item in [*result.get("memory_used", []), *result.get("context_memory_used", [])]:
            identity = item.get("id")
            row = session.get(MemoryRecord, identity) if identity else None
            reason = (
                "missing"
                if row is None
                else row.status
                if row.status != "active"
                else "version_changed"
                if row.version != item.get("version")
                else None
            )
            if reason:
                memory_issues.append({"id": identity, "reason": reason})
            elif row:
                for validity_reason in memory.validity(identity)["reasons"]:
                    memory_issues.append({"id": identity, "reason": validity_reason})
        for item in result.get("evidence", []):
            reason, valid = None, True
            if item.get("public_document_id"):
                row = session.get(PublicDocument, item["public_document_id"])
                if row is None:
                    reason, valid = "public_document_missing", False
                else:
                    path = Path(row.path)
                    start, end = item.get("start"), item.get("end")
                    valid = (
                        path.is_file()
                        and path.stat().st_size <= 1_000_000
                        and hashlib.sha256(path.read_bytes()).hexdigest() == row.sha256
                        and type(start) is int
                        and type(end) is int
                        and 0 <= start < end <= len(row.text)
                        and row.text[start:end] == item.get("quote")
                        and item.get("id") == f"publicdoc:{row.id}:{start}:{end}"
                        and item.get("document_sha256") == row.sha256
                        and item.get("content_sha256") == row.text_sha256
                        and hashlib.sha256(row.text.encode("utf-8")).hexdigest() == row.text_sha256
                    )
                    if not valid:
                        reason = "public_source_integrity_or_quote_changed"
            elif item.get("snapshot_id"):
                snapshot = session.get(JobSnapshot, item["snapshot_id"])
                document = session.get(SourceDocument, item.get("document_id"))
                job = session.get(Job, item.get("job_id"))
                start, end = item.get("start"), item.get("end")
                text = snapshot.payload.get("description", "") if snapshot else ""
                observation = session.scalar(
                    select(JobObservation.id).where(
                        JobObservation.snapshot_id == item["snapshot_id"],
                        JobObservation.document_id == item.get("document_id"),
                        JobObservation.job_id == item.get("job_id"),
                    )
                )
                path = Path(document.path) if document else None
                valid = bool(
                    snapshot
                    and job
                    and document
                    and observation
                    and snapshot.job_id == job.id
                    and type(start) is int
                    and type(end) is int
                    and 0 <= start < end <= len(text)
                    and text[start:end] == item.get("quote")
                    and item.get("id") == f"{snapshot.id}:{start}:{end}"
                    and item.get("document_sha256", document.sha256) == document.sha256
                    and item.get("content_sha256", snapshot.content_sha256)
                    == snapshot.content_sha256
                    and path.is_file()
                    and hashlib.sha256(path.read_bytes()).hexdigest() == document.sha256
                )
                if not valid:
                    reason = "source_integrity_or_reference_changed"
                elif job.description_text != text:
                    reason = "job_current_version_changed"
            if reason:
                changed_sources.append(
                    {
                        "evidence_id": item.get("id"),
                        "reason": reason,
                        "retained_evidence_valid": valid,
                    }
                )
        strategy = result.get("strategy") or result.get("retrieval_strategy") or {}
        identity = strategy.get("id") if isinstance(strategy, dict) else None
        if identity:
            row = session.get(RetrievalStrategy, identity)
            status = row.status if row else "missing"
            # 尚无策略行时literal-v1是程序内置稳定配置，并非丢失记录。
            if row is None and identity == "literal-v1":
                status = "active"
            if status != "active":
                affected_strategy.append({"id": identity, "status": status})
            elif row and strategy.get("config_sha256"):
                fingerprint = hashlib.sha256(
                    json.dumps(row.config, sort_keys=True, ensure_ascii=False).encode()
                ).hexdigest()
                if fingerprint != strategy["config_sha256"]:
                    affected_strategy.append({"id": identity, "status": "configuration_changed"})
    from work_observer.knowledge.service import DomainKnowledgeService

    scope = result.get("scope") or {}
    knowledge_issues = DomainKnowledgeService(repository).audit_dependencies(
        result.get("knowledge_used", []),
        job_ids=[item["id"] for item in scope.get("jobs", [])],
        public_document_ids=scope.get("archived_public_ids", []),
        project_id=result.get("project_id"),
    )
    from work_observer.memory.dependencies import DependencyAudit

    dependency_audit = DependencyAudit(repository).result(result)
    return {
        "stale_memory": bool(memory_issues) or bool(result.get("stale_memory")),
        "memory_issues": memory_issues,
        "stale_knowledge": bool(knowledge_issues) or bool(result.get("stale_knowledge")),
        "knowledge_issues": knowledge_issues,
        "changed_sources": changed_sources,
        "affected_strategy": affected_strategy,
        "stale_dependencies": not dependency_audit["eligible"],
        "dependency_issues": dependency_audit["issues"],
    }
