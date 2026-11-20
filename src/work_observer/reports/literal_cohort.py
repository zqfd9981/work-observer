"""Compare frozen literal mentions on the same eligible jobs, without reading current text."""


def compare_literal_cohort(before, after, left, right):
    shared = sorted(left.keys() & right.keys())
    terms = [term for term in before["terms"] if term in after["terms"]]
    matching = before.get("literal_matching")
    same_matching = bool(matching) and matching == after.get("literal_matching")
    selected, excluded = [], []
    for identity in shared:
        a, b = left[identity], right[identity]
        reasons = []
        for side, row in (("before", a), ("after", b)):
            if "literal_hits" not in row:
                reasons.append(side + "_hits_unrecorded")
            elif row["literal_hits"] is None:
                reasons.append(side + "_not_eligible")
        if a.get("source") and b.get("source") and any(
            a["source"].get(key) != b["source"].get(key)
            for key in ("data_kind", "response_origin")
        ):
            reasons.append("material_identity_changed")
        if reasons:
            excluded.append({"job_id": identity, "reasons": reasons})
        else:
            selected.append(identity)
    reasons = []
    if not shared:
        reasons.append("no_shared_jobs")
    elif not selected:
        reasons.append("no_common_eligible_jobs")
    if not same_matching:
        reasons.append("matching_changed_or_unrecorded")
    if not terms:
        reasons.append("no_common_terms")
    statistics = []
    if not reasons:
        for term in terms:
            a = {key for key in selected if term in left[key]["literal_hits"]}
            b = {key for key in selected if term in right[key]["literal_hits"]}
            statistics.append(
                {
                    "term": term,
                    "before": len(a),
                    "after": len(b),
                    "denominator": len(selected),
                    "newly_mentioned_job_ids": sorted(b - a),
                    "no_longer_mentioned_job_ids": sorted(a - b),
                }
            )
    return {
        "comparable": not reasons,
        "job_ids": selected,
        "shared_jobs": len(shared),
        "denominator": len(selected),
        "excluded": excluded,
        "statistics": statistics,
        "reasons": reasons,
        "uncompared_terms": {
            "before": [term for term in before["terms"] if term not in terms],
            "after": [term for term in after["terms"] if term not in terms],
        },
        "jobs": [
            {
                "job_id": key,
                "title": right[key]["fields"].get("title"),
                "before": {
                    "source": left[key]["source"],
                    "literal_hits": [term for term in terms if term in left[key]["literal_hits"]],
                },
                "after": {
                    "source": right[key]["source"],
                    "literal_hits": [term for term in terms if term in right[key]["literal_hits"]],
                },
            }
            for key in selected
        ],
        "notice": (
            "只比较两面板中都明确符合范围、都有可核验正文且资料性质一致的同一批岗位。"
            "使用当时冻结的逐岗字面命中，不用当前正文重算过去。画像或解释更新不改变这些字面计数。"
            "后来出现或不再提及某词不等于新增或取消职责、必备要求，不能外推市场趋势。"
        ),
    }
