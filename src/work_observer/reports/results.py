"""按需保存不可覆盖的研究结果及原文片段；不写回来源事实。"""

import hashlib
import json
import re
from html import escape
from pathlib import Path
from uuid import uuid4

from work_observer.connectors.mcp_probe import ProbeError

CLAIM_BASIS_LABELS = {"direct": "原文明示", "synthesis": "研究归纳", "inference": "研究推断"}


def _memory_text(content):
    prefix = "个人应用背景（用户自述，结构化）：\n"
    if content.startswith(prefix):
        try:
            data = json.loads(content[len(prefix) :])
            if isinstance(data, dict) and all(
                isinstance(data.get(key), str) for key in ("background", "goal", "constraints")
            ):
                return (
                    f"个人应用背景（用户自述）：\n已有经历或能力：{data['background']}\n"
                    f"本次目标：{data['goal']}\n投入与限制："
                    + (data["constraints"] or "未说明，不作假设")
                )
        except (ValueError, TypeError):
            pass
    return content


FINDING_FACETS = {
    "work_task": "岗位建设与工作任务",
    "deliverable": "工作产出",
    "personal_coding_share": "个人编码分工",
    "independent_delivery": "独立端到端负责程度",
    "task_independence": "原文明示的独立子任务",
    "team_collaboration": "团队协作",
    "execution_safety": "执行安全与技术隔离",
    "release_authority": "上线决策与责任",
    "runtime_role": "平台运行中的角色",
    "human_control": "人工控制与接管",
    "qualification": "任职资格与强度",
    "tool_usage": "工具使用",
    "business_context": "岗位业务方向",
}
FINDING_STATES = {
    "stated": "登记为原文明示（语义待核）",
    "explicitly_denied": "登记为原文明示否定（语义待核）",
    "not_disclosed": "已读归档正文中未披露（待核实）",
    "unresolved": "尚不能判断（待核实）",
}
FINDING_ACTORS = {
    "job_holder": "招聘岗位承担者",
    "human_operator": "人工操作角色",
    "team": "团队",
    "system": "系统",
    "agent": "Agent",
    "unspecified": "主体未明确",
}


def _finding_actor(row):
    if "actor" not in row:
        return ""
    return "；主体：" + escape(str(FINDING_ACTORS.get(row["actor"], row["actor"])))


def _finding_facet(row):
    label = str(FINDING_FACETS.get(row["facet"], row["facet"]))
    return escape(label) if "actor" in row else label


def source_analysis_notes(result):
    """Only expose persisted analysis notices; do not infer comparability from bindings."""
    claim_count = len(result.get("claims") or [])
    for notes in (
        result.get("analysis_notes"),
        (result.get("source_binding_check") or {}).get("analysis_notes"),
    ):
        if isinstance(notes, list) and notes:
            return [
                note
                for note in notes
                if isinstance(note, dict)
                and type(note.get("index")) is int
                and 0 <= note["index"] < claim_count
            ]
    return []


def _render_analysis_notes(result, index):
    lines = []
    for note in source_analysis_notes(result):
        if note.get("index") != index:
            continue
        lines.extend(
            [
                "",
                "  多维分析提示（不表示同口径单维可比，也不表示语义通过）：",
                "  " + escape(str(note.get("notice", "仍须语义核对"))),
            ]
        )
        for side in note.get("sides", []):
            lines.append(
                f"  - 分项 {escape(str(side.get('finding_id', '待核')))}；"
                f"岗位 `{escape(str(side.get('job_id', '待核')))}`；"
                f"{_finding_facet(side) if 'facet' in side else '维度待核'}"
                f"{_finding_actor(side)}"
            )
    return lines


def _render_claim_sentences(claim):
    if "bindings" not in claim and "sentence_citations" not in claim:
        return []
    lines = [
        "",
        "  已声明的支持子集（不保证语义支持，仍需核对主体、范围与强度）：",
    ]
    for binding in claim.get("bindings", []):
        lines.append(
            "  - 分项 "
            + escape(str(binding.get("finding_id", "待核")))
            + "；原文分句："
            + escape("、".join(binding.get("sentence_ids", [])))
        )
    for cite in claim.get("sentence_citations", []):
        lines.append(
            f"  - {escape(str(cite.get('finding_id', '待核')))}；"
            f"{_finding_facet(cite) if 'facet' in cite else '维度待核'}"
            f"{_finding_actor(cite)}；岗位 `{escape(str(cite.get('job_id', '待核')))}`；"
            f"版本 `{escape(str(cite.get('snapshot_id', '待核')))}`；"
            f"原文字符 {cite.get('start', '?')}–{cite.get('end', '?')}"
        )
        for context in cite.get("context", []) or []:
            lines.extend(["", "    原文上下文（定位信息，仍需核对）："])
            lines.extend("    > " + escape(line) for line in context.get("text", "").splitlines())
        lines.append("")
        lines.extend("    > " + escape(line) for line in cite.get("text", "").splitlines())
    lines.append("")
    return lines


def _finding_quote_warning(row):
    from work_observer.research.source_first import source_quote_check

    if not row.get("citations"):
        return ""
    check = source_quote_check(row["citations"])
    if check["status"] == "covered":
        return ""
    if check["status"] == "incomplete":
        return (
            "部分原文单元未完整引用；后文可能含优先、否定或范围限定。"
            "请核对完整原文，不凭片段判定资格。"
        )
    return "完整原文单元的定位信息不足，请核对全文中的条件与限定。"


def _render_source_findings(result, labels):
    findings = result.get("source_findings", [])
    if not findings:
        return []
    lines = [
        "",
        "## 原文分项记录（试验，语义待核）",
        "",
        "以下为研究中的分项登记，不是人工审核通过。未知不等于没有职责；模型分析不能覆盖原文动作。",
    ]
    jobs = {job["id"]: job for job in result["scope"]["jobs"]}
    for job_id in dict.fromkeys(row["job_id"] for row in findings):
        job = jobs.get(job_id, {})
        lines.extend(["", f"### {job.get('title', job_id)} · {job.get('company', '公司待核')}", ""])
        active = [row for row in findings if row["job_id"] == job_id and row.get("active")]
        for unknown in (False, True):
            selected = [
                row
                for row in active
                if (row["state"] in {"not_disclosed", "unresolved"}) == unknown
            ]
            if not selected:
                continue
            lines.extend(["#### 待核实的维度" if unknown else "#### 有原文分句的登记", ""])
            for row in selected:
                lines.append(
                    f"- {_finding_facet(row)}："
                    f"{FINDING_STATES.get(row['state'], '状态待核')}（{row['id']}）"
                    f"{_finding_actor(row)}"
                )
                warning = _finding_quote_warning(row)
                if warning:
                    lines.append("  - 引用完整性待核：" + warning)
                for cite in row.get("citations", []):
                    label = labels.get(cite.get("evidence_id"))
                    reference = f"[{label}](#{label.lower()})" if label else "来源待定位"
                    lines.extend(
                        [
                            f"  - {reference}；原文字符 {cite['start']}–{cite['end']}；"
                            f"版本 `{cite.get('snapshot_id', '待核')}`",
                            "",
                            *["    > " + line for line in cite["text"].splitlines()],
                            "",
                        ]
                    )
    revisions = [row for row in findings if not row.get("active")]
    if revisions:
        lines.extend(["", "### 分项修订记录（历史保留，不作为活动结论）", ""])
        for row in revisions:
            replacement = next(
                (item for item in findings if item["id"] == row.get("superseded_by")), {}
            )
            lines.append(
                f"- {row['id']} → {row.get('superseded_by', '后续记录')}；"
                f"{_finding_facet(row)}{_finding_actor(row)}；原状态："
                f"{FINDING_STATES.get(row['state'], '待核')}；"
                f"修订说明（研究登记，待核）：{replacement.get('reason', '请核对原始记录')}"
            )
            warning = _finding_quote_warning(row)
            if warning:
                lines.append("  - 引用完整性待核：" + warning)
            if "actor" in row:
                lines.append(f"  - 原登记理由（待核）：{escape(row.get('reason', '未记录'))}")
                if replacement:
                    lines.append(
                        f"  - 更正后维度：{_finding_facet(replacement)}"
                        f"{_finding_actor(replacement)}"
                    )
                for cite in row.get("citations", []):
                    lines.extend(
                        [
                            "",
                            f"    原登记所引分句；字符 {cite.get('start', '?')}–"
                            f"{cite.get('end', '?')}；版本 "
                            f"`{escape(str(cite.get('snapshot_id', '待核')))}`：",
                        ]
                    )
                    for context in cite.get("context", []) or []:
                        lines.append("    原文上下文（定位信息，仍需核对）：")
                        lines.extend(
                            "    > " + escape(line) for line in context.get("text", "").splitlines()
                        )
                    lines.extend(
                        "    > " + escape(line) for line in cite.get("text", "").splitlines()
                    )
    return lines


def render(result):
    counts = result["scope"]["counts"]
    lines = [
        f"# {result['question']}",
        "",
        f"状态：{result['status']}；时间：{result['created_at']}",
        f"SQL 范围 {counts['scope_total']} 个；匹配 {counts['matched']} 个；"
        f"条件未知 {counts['unknown']} 个；候选完整正文 {counts['candidate_details']} 个。",
        "",
    ]
    if result["status"] == "completed":
        review = result.get("business_review") or {}
        labels = {"approved": "通过", "rejected": "未通过", "pending": "待继续核对"}
        source = {"human": "人工核对", "agent_assisted": "Agent辅助核对，非独立人审"}.get(
            review.get("reviewer_kind")
        )
        label = labels.get(review.get("status"), "未附核对记录") if source else "未附核对记录"
        lines.extend([f"核对状态：{label}" + (f"（{source}）" if source else "") + "。", ""])
        if review.get("note"):
            lines.extend(
                [
                    "核对说明（不是新的来源证据）：",
                    *["> " + escape(line) for line in review["note"].splitlines()],
                    "",
                ]
            )
        if label != "通过":
            lines.extend(["回答生成不表示质量核对通过；下文保留原回答及其引用。", ""])
    if result.get("submission_feedback") and result["status"] != "completed":
        feedback = result["submission_feedback"]
        lines.extend(["## 最近一次提交为何未通过", "", escape(feedback["notice"]), ""])
        for row in feedback["reasons"]:
            indices = "、".join(str(index + 1) for index in row.get("claim_indices", []))
            lines.append(
                "- " + escape(row["message"]) + (" 对应条目：" + indices if indices else "")
            )
        lines.extend(["", "### 未通过的提交（不作为当前认识）", ""])
        draft_labels = {
            item["id"]: f"E{index}" for index, item in enumerate(result.get("evidence", []), 1)
        }
        for row in feedback["draft_claims"]:
            lines.extend([f"条目 {row['index'] + 1}：" + escape(str(row["text"])), ""])
            lines.append(
                "待核对的引用："
                + " ".join(
                    f"[{draft_labels[key]}](#{draft_labels[key].lower()})"
                    if key in draft_labels
                    else "引用无法定位"
                    for key in row["evidence_ids"]
                )
            )
    lines.extend(["## 本次候选", ""])
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
    if result["scope"].get("source_note"):
        lines.extend(
            [
                result["scope"]["source_note"],
                ("归档资料范围：" if result["scope"].get("work_material_ids") else "公开资料范围：")
                + f"{result['scope'].get('archived_public_total', 0)}份归档正文。",
                "",
            ]
        )
    if result.get("question_scope") and result["scope"]["jobs"]:
        coverage = result["question_scope"]
        lines.extend(
            [
                "",
                f"本轮按问题选择资料，查阅了{coverage['read_job_fragments']}份岗位材料的片段；"
                f"范围内有{coverage['available_details']}份可用正文。",
                coverage["notice"],
                "",
            ]
        )
    feedback = result.get("review_feedback")
    if feedback:
        lines.extend(
            [
                "",
                "## 本轮参照的复核诊断（不是新证据）",
                "",
                "来源："
                + ("人类复核" if feedback["reviewer_kind"] == "human" else "Agent辅助复核，非人审"),
                "旧运行 `"
                + feedback["run_id"]
                + "`；复核 `"
                + feedback["review_id"]
                + "`。旧答案未作为本轮证据。",
                escape(feedback["note"]),
                "",
            ]
        )
    if result.get("qualification_validation"):
        lines.extend(
            [
                "",
                "本轮使用更新后的局部否定识别，恢复时保留本轮检查口径；词面检查不代替原文语义核对。",
                "",
            ]
        )
    if result.get("plan"):
        lines.extend(["", "## 调查计划", "", *[f"- {step}" for step in result["plan"]["steps"]]])
    if result.get("memory_used"):
        lines.extend(["", "## 本次使用的业务记忆（不是独立来源）", ""])
        lines.extend(
            f"- {item['kind']} / 版本 {item['version']}：{_memory_text(item['content'])}"
            for item in result["memory_used"]
        )
    evidence = {item["id"]: item for item in result["evidence"]}
    labels = {key: f"E{index}" for index, key in enumerate(evidence, 1)}
    from work_observer.reports.cognition import render_map, render_revisions

    if result.get("analysis_origin") == "developer_sample":
        lines.extend(["", "产出来源：开发分析样稿，非产品Agent运行，非独立人审。", ""])
    if result.get("archive_comparisons"):
        lines.extend(["", "## 所选归档版本对照", ""])
        kinds = {
            "user_text_revision": "用户修订正文",
            "archive_text_changed": "归档正文变化",
            "extraction_changed": "同一原始文件的文本提取结果变化",
            "metadata_only": "正文未变，说明变化",
            "raw_archive_changed": "响应变化，提取正文未变",
            "observed_again": "再次保存，正文未变",
            "line_endings_changed": "行内容相同，换行形式变化",
        }
        for row in result["archive_comparisons"]:
            references = " ".join(
                f"[{labels[key]}](#{labels[key].lower()})"
                for key in row["evidence_ids"]
                if key in labels
            )
            lines.extend(
                [
                    f"- {kinds.get(row['change_kind'], '变化类型待核对')}："
                    f"{row['earlier']['observed_at']} → "
                    f"{row['later']['observed_at']}。{references}",
                    "  程序核对：原始文件指纹"
                    + ("不同" if row["raw_changed"] else "相同")
                    + f"；提取正文 {row['earlier']['full_text_length']} → "
                    + f"{row['later']['full_text_length']} 字符。",
                    "  " + row["notice"],
                    "  程序差异范围："
                    + ("完整" if row["complete"] else "受展示上限限制，不能视为完整差异")
                    + "；引用仅为局部原文。",
                ]
            )
    lines.extend(render_map(result, labels))
    lines.extend(render_revisions(result, labels))
    if proposals := result.get("investigation_proposals"):
        lines.extend(
            [
                "",
                "## Agent提出的后续调查",
                "",
                "以下是原轮调查建议，不是已经取得的证据；当前安排状态请在所属研究中查看。",
            ]
        )
        for proposal in proposals:
            lines.extend(
                [
                    "",
                    "### " + escape(proposal["question"]),
                    "完成条件：" + escape(proposal["completion"]),
                    "所需证据：" + escape(proposal["evidence_needed"]),
                ]
            )
    lines.extend(_render_source_findings(result, labels))
    heading = (
        "样稿判断（开发分析，待核对）"
        if result.get("analysis_origin") == "developer_sample"
        else "判断（模型分析）"
    )
    lines.extend(["", "## " + heading, ""])
    if result["claims"]:
        lines.extend(["判断性质由模型标注，仍需核对原文；研究归纳不代表多个独立来源。", ""])
    if result.get("source_findings"):
        lines.extend(
            [
                "自由归纳与推断仍需语义审核，不能覆盖上述原文动作，也不能把个人分工未知改写为没有岗位任务。",
                "",
            ]
        )
    for index, claim in enumerate(result["claims"]):
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
            f"**{CLAIM_BASIS_LABELS.get(claim.get('basis'), '性质未标注')}** · "
            f"{claim['text']} {cites}"
        )
        lines.extend(_render_analysis_notes(result, index))
        lines.extend(_render_claim_sentences(claim))
    if plan := result.get("application_plan"):
        lines.extend(
            [
                "",
                "## 应用行动（研究建议，效果尚未验证）",
                "",
                f"目标：{plan['goal']}；采用第 {plan['background_version']} 版个人背景。",
                f"投入与限制：{plan['constraints'] or '未说明，不作假设'}",
                plan["notice"],
            ]
        )
        for index, action in enumerate(plan["actions"], 1):
            cites = " ".join(
                f"[{labels[key]}](#{labels[key].lower()})" for key in action["evidence_ids"]
            )
            lines.extend(
                [
                    "",
                    f"### {index}. {action['title']}",
                    f"针对任务或能力：{action['task_or_ability']}",
                    f"交付物（建议）：{action['deliverable']}",
                    f"完成检查（建议）：{action['completion_check']}",
                    cites,
                    *[f"- 需要确认的前提：{text}" for text in action["assumptions"]],
                ]
            )
        lines.extend(f"- 行动前待明确：{text}" for text in plan["open_questions"])
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
        if item.get("evidence_kind") == "work_material":
            lines.extend(
                [
                    f'<a id="{labels[key].lower()}"></a>',
                    f"### {labels[key]} · 粘贴工作资料 · {item['title']}",
                    f"来源说明：{item['publisher']}；保存于：{item['observed_at']}；来源发布时间未知。",
                    "通过粘贴取得原文，来源说明未经独立核实，内容不表示已执行。",
                    "",
                    *["> " + line for line in item["quote"].splitlines()],
                    "",
                ]
            )
            continue
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
                *(
                    [
                        "历史原文读取截止："
                        + "；".join(escape(str(value)) for value in item["historical_cutoffs"])
                        + "。仅表示当时已入库资料，不是当前岗位事实或网站发布时间。"
                    ]
                    if item.get("historical_cutoffs")
                    else []
                ),
                "",
                *["> " + line for line in item["quote"].splitlines()],
                "",
            ]
        )
    return "\n".join(lines) + "\n"


def save_result(result, directory=Path("reports")):
    from work_observer.reports.cognition import checked_map

    checked_map(result)
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


def list_results(directory=Path("reports"), limit=20, query="", status=""):
    terms = query.casefold().split()

    def texts(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for child in value.values():
                yield from texts(child)
        elif isinstance(value, list):
            for child in value:
                yield from texts(child)

    results = []
    if directory.exists():
        for path in sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            if not re.fullmatch(r"[a-f0-9]{32}", path.stem):
                continue
            result = read_result(path.stem, directory)
            if status and result["status"] != status:
                continue
            content = list(
                texts(
                    {
                        key: result.get(key)
                        for key in (
                            "question",
                            "claims",
                            "evidence",
                            "gaps",
                            "work_map",
                            "cognition_revisions",
                            "application_plan",
                        )
                    }
                )
            )
            searchable = "\n".join(content).casefold()
            if not all(term in searchable for term in terms):
                continue
            row = {key: result[key] for key in ("report_id", "question", "status", "created_at")}
            if terms:
                match = next(
                    (text for text in content if any(term in text.casefold() for term in terms)), ""
                )
                start = max(
                    0,
                    min(
                        (match.casefold().find(term) for term in terms if term in match.casefold()),
                        default=0,
                    )
                    - 45,
                )
                row["match_excerpt"] = (
                    ("…" if start else "")
                    + match[start : start + 180]
                    + ("…" if len(match) > start + 180 else "")
                )
            results.append(row)
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
    from work_observer.research.historical_sources import historical_evidence_ids
    from work_observer.storage.models import (
        Job,
        JobObservation,
        JobSnapshot,
        MemoryRecord,
        SourceDocument,
    )
    from work_observer.tracking.models import RetrievalStrategy

    historical = historical_evidence_ids(repository, result)
    memory_issues, changed_sources, affected_strategy, historical_sources = [], [], [], []
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
                elif item.get("id") in historical:
                    historical_sources.append(
                        {
                            "evidence_id": item["id"],
                            "cutoffs": item["historical_cutoffs"],
                            "current_version_differs": job.description_text != text,
                        }
                    )
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
        "historical_sources": historical_sources,
        "affected_strategy": affected_strategy,
        "stale_dependencies": not dependency_audit["eligible"],
        "dependency_issues": dependency_audit["issues"],
    }
