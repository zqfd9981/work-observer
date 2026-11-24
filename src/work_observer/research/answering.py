"""Readable answers composed entirely from evidence-checked claims."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

POLICY = """
finish_research的reader_answer是用户直接看到的完整答复，不是几句摘要。由你按本轮问题选择组织方式：
- calibration：先回答用户看法哪些成立、哪里不完整，再解释跨岗位证据和成立条件，给出认识修正。
- overview：先给整体理解，再解释工作类型、共性与分化条件，让读者理解为什么需要这些能力。
- comparison：按相同维度比较，给条件性结论；用户背景未知时不强行替他选方向。
- brief：仅在用户明确要求一句话、简短、只给结论时使用。聚焦追问不等于要求简短。
不要机械套模板，也不要为了简洁删除分析。普通研究应充分回答问题，不设三四条或几百字的上限。
先给直接结论，随后用有信息量的标题组织分析；让用户能看出证据、解释和行动之间的关系。
不能只列技术名词或复述JD：解释工作要解决什么问题、为什么需要某能力、产出是什么，
区分多个岗位共同出现的模式、方向差异及条件化例外。没有足够证据时直接承认。
核对认识时保留用户理解中成立的部分，再指出缺失环节及其影响，不把用户没说的话强加给他。
建议具体到可准备或检验的内容，并说明由哪些岗位任务推导；不编造个人背景或企业录用标准。
反例必须针对正在核对的同一命题，不用无关的人机边界凑数。跨JD共性引用至少两个独立岗位。
涉及比较、多个工作环节或认识对照时，优先提供真正的table，把差异放到相同列中比较。
表格服务理解，不把整篇回答塞成大表；通常三列、三至五行，单元格简明，表后解释最关键的含义。
用户问工作、能力、项目证据时，表格应分别覆盖这些维度；不要只列职责却漏掉能力解释。
每个单元格通常一两句，保留辨别方向所需的具体内容，不塞入整份JD或一长串技术名词。
开头用一条结论回应，把详细比较交给表格，不在表格之前堆三段重复总结。
需要多项建议或并列理由时用bullets/numbered；普通解释用paragraph。可用**关键短语**强调重点。
所有正文（含列表项、表格每个单元格）都来自claims，通过claim_indices/rows选择，不能在布局里另写事实。
每条claim可以是面向用户的一段解释或一个简短表格单元格；每个单元格都应能独立理解并有引用。
不要把同一事实在正文和表格重复一遍；标题和columns只是简短导航，不承担未经核实的结论。
paragraph/bullets/numbered用claim_indices，columns和rows填空数组；table用columns与rows，claim_indices填空。
table每行是与列数相同的claims下标数组。下标从0开始，每条判断只展示一次。
任职必备、优先、可选的性质必须在文字中准确表达；不要混写不同性质后用unspecified规避核对。
说明哪些是原文陈述，哪些是根据任务推导的建议或产出；推断用inference，不虚构效果和事实。
关键范围限制在相应解释中交代；最后简短说明样本边界，不把静态招聘样本说成全行业比例或趋势。
reader_answer仍沿用paragraphs字段装载各种内容块，每块含kind、heading、claim_indices、columns、rows。
heading可为空；brief只用一个paragraph和一个能独立回答的claim。其他模式按问题充分展开。
标题必须准确描述该块实际内容：“样本边界”只放资料范围、缺口和外推限制，不能放准备建议。
每次修改claims后重新逐格核对所有下标与标题；被删或移动的判断不能让布局错配到相邻条目。
仅在没有可用答案时reader_answer为null；内部模式名称、核对字段和执行记录不要写进答复。
"""


class ReaderParagraph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["paragraph", "bullets", "numbered", "table"] = "paragraph"
    heading: str = Field(max_length=60)
    claim_indices: list[StrictInt] = Field(max_length=12)
    columns: list[str] = Field(default_factory=list, max_length=4)
    rows: list[list[StrictInt]] = Field(default_factory=list, max_length=8)


class ReaderAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["calibration", "overview", "comparison", "brief"]
    paragraphs: list[ReaderParagraph] = Field(min_length=1, max_length=10)


def checked_reader_answer(layout, claims):
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
    return layout.model_dump()


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
