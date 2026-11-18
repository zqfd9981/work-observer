"""要求性质的窄词面护栏；否定某种措辞不等于真的提出了该优先条件。"""

import re

PREFERRED_CUE = re.compile(r"加分|优先(?!级|顺序)|有则更好")
REQUIRED_CUE = re.compile(r"必备|必须具备|硬性资格|硬性要求|(?<![A-Za-z_])required(?![A-Za-z_])")
NEGATED_PREFIX = re.compile(
    r"(?:无|没有|不含|不包含|不包括|不存在|未出现|未使用|未见|并非|不是|非|不属于|"
    r"(?:不(?:应|该|能)?|不可)(?:视为|看作|当作|标为|列为|记为)|"
    r"未(?:明确)?(?:标注|标为|列为|写明|说明))"
    r"(?:任何|明确的|明确|所谓)?[\s“\"「『]*"
    r"(?:(?:优先|加分)[\s”\"」』]*(?:[/／、或和及])[\s“\"「『]*)?$"
)
NEGATED_SUFFIX = re.compile(
    r"^[\s”\"」』]*(?:字样|措辞|标注|条件)?(?:均|都)?"
    r"(?:未出现|未使用|未见|不存在|没有出现|并不存在|不在该条|不在此项)"
)


def _markers(text, pattern):
    return [
        match.group()
        for match in pattern.finditer(text)
        if not NEGATED_PREFIX.search(text[max(0, match.start() - 32) : match.start()])
        and not NEGATED_SUFFIX.search(text[match.end() : match.end() + 24])
    ]


def preferred_markers(text):
    """只返回未被局部明确否定的优先信号；不宣称判断了原文语义。"""
    return _markers(text, PREFERRED_CUE)


def required_markers(text):
    """只检查明确性质标记，不将一般的熟悉/使用措辞一律当作必备。"""
    return _markers(text, REQUIRED_CUE)
