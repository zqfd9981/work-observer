"""要求性质的窄词面护栏；否定某种措辞不等于真的提出了该优先条件。"""

import re

LEGACY_GUARD = "qualification-guard-v1"
PREVIOUS_GUARD = "qualification-guard-v2-local-negation"
MERGE_GUARD = "qualification-guard-v3-merge-negation"
DENIED_STATUS_GUARD = "qualification-guard-v4-denied-preference-status"
CURRENT_GUARD = "qualification-guard-v5-denied-qualification-rewrite"
KNOWN_GUARDS = {
    LEGACY_GUARD, PREVIOUS_GUARD, MERGE_GUARD, DENIED_STATUS_GUARD, CURRENT_GUARD
}


def guard_contract():
    """Seal the executable guard separately from the original model policy."""
    import hashlib
    import inspect
    import sys

    return {
        "version": CURRENT_GUARD,
        "sha256": hashlib.sha256(
            "\n".join(inspect.getsource(sys.modules[__name__]).splitlines()).encode()
        ).hexdigest(),
    }


def implementation(version):
    """Historical files preserve the checks and hashes of actual saved runs."""
    import sys

    from work_observer.connectors.mcp_probe import ProbeError
    from work_observer.research import requirements_v2, requirements_v3, requirements_v4

    if version in {LEGACY_GUARD, PREVIOUS_GUARD}:
        return requirements_v2
    if version == MERGE_GUARD:
        return requirements_v3
    if version == DENIED_STATUS_GUARD:
        return requirements_v4
    if version == CURRENT_GUARD:
        return sys.modules[__name__]
    raise ProbeError("RESEARCH_VALIDATION_INVALID")


def contract_for(version):
    if version == LEGACY_GUARD:
        return None
    return implementation(version).guard_contract()


def select_guard(store, identity, *, resume):
    from work_observer.connectors.mcp_probe import ProbeError

    if not resume:
        return guard_contract()
    run = store.get(identity)
    if (run.get("result") or {}).get("status") in {
        "completed",
        "evidence_only",
        "insufficient_evidence",
    }:
        raise ProbeError("RESEARCH_RUN_ALREADY_FINISHED")
    saved = store.load_checkpoint(identity) or {}
    recorded = run["input"].get("qualification_validation")
    result_contract = (saved.get("result") or {}).get("qualification_validation")
    if recorded is None and result_contract is None:
        return None  # Historical input/result shape and checks remain untouched.
    if (
        not isinstance(recorded, dict)
        or recorded != result_contract
        or recorded.get("version") not in KNOWN_GUARDS - {LEGACY_GUARD}
        or recorded != contract_for(recorded["version"])
    ):
        raise ProbeError("RESEARCH_VALIDATION_CHANGED_NEW_ROUND_REQUIRED")
    return recorded


PREFERRED_CUE = re.compile(r"加分|优先(?!级|顺序)|有则更好")
REQUIRED_CUE = re.compile(r"必备|必须具备|硬性资格|硬性要求|(?<![A-Za-z_])required(?![A-Za-z_])")
NEGATED_PREFIX = re.compile(
    r"(?:无|没有|不含|不包含|不包括|不存在|未出现|未使用|未见|并非|不是|非|不属于|"
    r"(?:不(?:应|该|能)?|不可)(?:视为|看作|当作|标为|列为|记为)|"
    r"未(?:明确)?(?:标注|标为|列为|写明|说明))"
    r"(?:任何|明确的|明确|所谓|一般)?[\s“\"「『]*"
    r"(?:(?:优先|加分)[\s”\"」』]*(?:[/／、或和及])[\s“\"「『]*)?$"
)
NEGATED_SUFFIX = re.compile(
    r"^[\s”\"」』]*(?:字样|措辞|标注|条件)?(?:均|都)?"
    r"(?:未出现|未使用|未见|不存在|没有出现|并不存在|不在该条|不在此项)"
)
FEEDBACK_NEGATED_REQUIRED_PREFIX = re.compile(
    r"(?:不(?:应|该|能)?|不可|不得)"
    r"(?:(?:将|把)[^，,。；;：:\n!?？！只仅]{1,16})?"
    r"(?:归为|归类为|提升为|升级为|拆出|并入|改写成)[\s“\"「『]*$"
)
DENIED_PREFERENCE_STATUS = re.compile(r"(?:并非|不是|非)仅(?:列为|作为)[\s“\"「『]*$")


def _markers(text, pattern, *, negative_prefix=None):
    return [
        match.group()
        for match in pattern.finditer(text)
        if not NEGATED_PREFIX.search(text[max(0, match.start() - 32) : match.start()])
        and not NEGATED_SUFFIX.search(text[match.end() : match.end() + 24])
        and not (
            negative_prefix
            and negative_prefix.search(text[max(0, match.start() - 32) : match.start()])
        )
    ]


def preferred_markers(text):
    """只返回未被局部明确否定的优先信号；不宣称判断了原文语义。"""
    return _markers(text, PREFERRED_CUE, negative_prefix=DENIED_PREFERENCE_STATUS)


def required_markers(text, *, contextual_negation=False):
    """只检查明确性质标记，不将一般的熟悉/使用措辞一律当作必备。"""
    return _markers(
        text,
        REQUIRED_CUE,
        negative_prefix=FEEDBACK_NEGATED_REQUIRED_PREFIX if contextual_negation else None,
    )
