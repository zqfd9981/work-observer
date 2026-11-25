"""Readable answers composed entirely from evidence-checked claims."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from work_observer.reports.aggregation import source_key

POLICY = """
reader_answer是用户直接看到的完整答复。先完成研究归纳，再选择展示方式；不要把逐份JD摘抄拼成答案。
用户问一个行业/岗位领域的整体认识、跨JD共性与差异，或拿个人看法与市场要求对照时，选mode=industry。
industry必须按下列逻辑组织paragraphs，用purpose标出每块的作用；标题可以自然变化：
1. judgment：先给一条清楚的行业判断，回答这些样本共同揭示了什么工作逻辑或能力结构、关键分化是什么。
   必须是有至少两份不同岗位依据的synthesis/inference，不是“有的A有的B”或热门技术清单。
   明确限于已读招聘样本；同时点样本不能说明正在增长、替代或全市场占比，JD也不是企业全部实际工作。
2. common：归纳两至四条跨岗位共同模式，用bullets。每条至少引用两个不同岗位，并用aggregation=common、
   basis=synthesis。解释共同要完成的工作、为何需要该能力及怎样验证，不能只罗列框架、工具或岗位名字。
   不同岗位要求强度不同时保留条件，不把局部共性说成所有岗位必备；同岗多个片段只算一个来源。
3. difference：解释岗位为何分化、在哪些维度分化。用一张简短对照表，每行一个比较维度，
   例如“交付对象/效果如何验证/失败处理”，列比较有证据的两类工作，而不是每行一家公司/一份JD。
   行业分类是对样本的研究归纳，不说成官方固定岗位分类。比较双方必须都有原文依据。
   第一列只写短维度名（最多24字），其他列比较工作类型；不以长岗位名/公司名和职责摘要填充。
   每个表格单元格不超过80个字符（通常20–50字），只放短结论；解释放到普通段落，原文和逐岗细节留在研究详情。
4. calibration：用户明确表达了原有看法时必须有这一块，写清：
   你理解中成立的部分—缺失/误解—更准确的认识。
   承接用户真正说过的话，用aggregation=calibration、basis=synthesis/inference并保留市场引用。
   不捏造用户背景，也不要为了制造偏差强行否定正确认识。没有表达原看法时省略，不替用户编一个误解。
5. preparation：最后用numbered/bullets给两至四条有优先级的求职准备影响。
   每条说明“因为前面的哪项发现，
   所以该准备/取舍什么，用什么实际证据验证”，不能泛泛说加强学习、做项目、多实践，也不按每份JD再复述一遍。
   建议用inference并引用相应任务依据；不要建议一个求职者同时包揽全部岗位方向，不把推导建议伪装为统一录用标准。
6. scope可选：只补充会影响本题结论的资料缺口和外推限制。不可把准备建议放到范围标题下。
industry的judgment/common/difference/preparation不可缺省或倒序，calibration在difference后、preparation前。
每块只出现一次；judgment用一个paragraph和一条核心判断，其余部分把这条判断逐步讲透，而不是换词重复。
除industry外：calibration核对一个聚焦看法，overview解释局部主题，comparison比较指定对象，
brief仅用于用户明确要求一句话、简短或只给结论。聚焦追问本身不表示要求简短，
也不必每轮重复完整行业分析；沿着当前问题深入，保留与前文相关的依据和认识修正。
这些模式的purpose按内容填写，无法归入上述作用时用other；简短答复不强塞小标题或表格。
用户明确要逐份整理JD时可以逐份呈现，但不要把该形式当成行业观察默认答案。
所有正文（包括列表项和表格单元格）来自已有claims，布局只引用claim_indices/rows，不能另写未经引用的新事实。
claims是面向读者的分析单元，不必每份JD各写一组；主要篇幅用于解释归纳、对比和认识修正。
可用**关键短语**强调重点。表格每格仍是一个带依据的短claim，下标从0开始，每条判断只展示一次。
所有模式的表格每格最多80个字符，详细解释写在表外；短答或追问也不能退回大段JD表格。
claims.text和标题不要手写(E1,E2)、[E1]等引用编号；只在evidence_ids填写引用，页面会统一生成引用按钮。
paragraph/bullets/numbered使用claim_indices，columns和rows为空；table使用columns与rows，claim_indices为空。
table每行是与列数相同的claims下标数组，columns和heading只作简短导航。
任职资格的必备、优先、可选性质在文字中准确表达，不在一条claim里混写不同性质，
也不把任务自动推成统一资格；不因缩短表格删除会改变结论的限定，必要时移到表外解释。
每次修改claims后重新核对下标与标题，避免移删判断后引用到相邻条目。
reader_answer为null仅用于没有可用答案；内部字段、模式名和执行记录不要写进正文。
"""


class ReaderParagraph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    purpose: Literal[
        "judgment", "common", "difference", "calibration", "preparation", "scope", "other"
    ] = "other"
    kind: Literal["paragraph", "bullets", "numbered", "table"] = "paragraph"
    heading: str = Field(max_length=60)
    claim_indices: list[StrictInt] = Field(max_length=12)
    columns: list[str] = Field(default_factory=list, max_length=4)
    rows: list[list[StrictInt]] = Field(default_factory=list, max_length=8)


class ReaderAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["industry", "calibration", "overview", "comparison", "brief"]
    paragraphs: list[ReaderParagraph] = Field(min_length=1, max_length=10)


def checked_reader_answer(layout, claims, evidence=None):
    if layout is None:
        return None
    if layout.mode == "brief" and (
        len(layout.paragraphs) != 1
        or layout.paragraphs[0].kind != "paragraph"
        or len(layout.paragraphs[0].claim_indices) != 1
    ):
        raise ValueError("brief只展示一个paragraph、一个核心判断。")
    seen = set()
    for block in layout.paragraphs:
        if block.kind == "table":
            if (block.claim_indices or not 2 <= len(block.columns) <= 4 or not block.rows
                or any(not column.strip() or len(column) > 60 for column in block.columns)
                or any(len(row) != len(block.columns) for row in block.rows)):
                raise ValueError(
                    "table需要2至4个非空列名，每行引用数与列数相同，claim_indices留空。"
                )
            indices = [index for row in block.rows for index in row]
        else:
            if not block.claim_indices or block.columns or block.rows:
                raise ValueError("正文或列表需要claim_indices，columns和rows留空。")
            indices = block.claim_indices
        for index in indices:
            if not 0 <= index < len(claims):
                raise ValueError("reader_answer只能选择本轮claims中实际存在的下标。")
            if index in seen:
                raise ValueError("reader_answer不要重复展示同一判断，请合并重复内容。")
            seen.add(index)
        # Only new submissions have evidence here; preserve existing saved table content.
        if block.kind == "table" and (evidence is not None or layout.mode == "industry"):
            texts = [(claims[index].text if isinstance(claims[index], BaseModel)
                      else claims[index]["text"]) for index in indices]
            if any(len(text) > 80 for text in texts):
                raise ValueError("对照表每格最多80个字符；请重写为短结论，详细解释放到表外。")
    if layout.mode == "industry":
        _check_industry_answer(layout, claims, evidence)
    return layout.model_dump()


def _check_industry_answer(layout, claims, evidence):
    order = ["judgment", "common", "difference", "calibration", "preparation", "scope"]
    purposes = [block.purpose for block in layout.paragraphs]
    if (any(purpose not in order for purpose in purposes)
        or len(set(purposes)) != len(purposes)
        or purposes != sorted(purposes, key=order.index)
        or not {"judgment", "common", "difference", "preparation"} <= set(purposes)):
        raise ValueError(
            "行业观察先给判断，再共性、差异、认知对照（适用时）、求职影响，不能逐岗拼表。"
        )
    values = [claim.model_dump() if isinstance(claim, BaseModel) else claim for claim in claims]

    def sources(indices):
        return {source_key(evidence[key]) for index in indices
                for key in values[index].get("evidence_ids", []) if key in evidence} - {None}

    for block in layout.paragraphs:
        indices = ([index for row in block.rows for index in row]
                   if block.kind == "table" else block.claim_indices)
        if block.purpose == "judgment":
            if (block.kind != "paragraph" or len(indices) != 1
                or values[indices[0]].get("basis") not in {"synthesis", "inference"}):
                raise ValueError("行业判断要先给一条跨资料解释，不能用单份JD事实替代。")
        if block.purpose == "common":
            if block.kind != "bullets" or len(indices) < 2:
                raise ValueError("共性要归纳至少两个工作/能力模式，用简明列表解释。")
            if any(values[index].get("aggregation") != "common"
                   or values[index].get("basis") != "synthesis" for index in indices):
                raise ValueError("共性应是有跨岗位依据的synthesis/common判断，不能逐份复述。")
        if block.purpose == "difference" and (
            block.kind != "table" or any(len(values[row[0]]["text"]) > 24 for row in block.rows)
        ):
            raise ValueError("差异用简短对照表：第一列为24字以内的比较维度，其他列对照工作类型。")
        if block.purpose == "preparation" and (
            block.kind not in {"numbered", "bullets"} or len(indices) < 2
        ):
            raise ValueError("求职影响要给至少两条有依据、能实际准备和验证的建议。")
        if evidence is not None and block.purpose in {"judgment", "common", "difference"}:
            groups = [[index] for index in indices] if block.purpose == "common" else [indices]
            if any(len(sources(group)) < 2 for group in groups):
                raise ValueError(
                    "行业判断、每条共性和差异比较都须引用不同岗位；同岗多个片段只算一个来源。"
                )


def strict_schema(schema):
    """Responses strict mode requires every object field, including empty layout arrays."""
    if isinstance(schema, dict):
        schema.pop("default", None)
        if schema.get("type") == "object":
            schema["required"] = list(schema.get("properties", {}))
        for value in schema.values():
            strict_schema(value)
    elif isinstance(schema, list):
        for value in schema:
            strict_schema(value)
    return schema
