"""Flexible reader-facing layouts over the same evidence-checked research claims."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

POLICY = """
最终答复与内部研究记录分开。finish_research提供reader_answer时，用它安排读者真正看到的回答。
由你依据本轮问题选择一个主骨架，不要求用户选择，不增加工具调用或另开一个Agent：
先看最新一轮的表达要求：用户要求一句话、简短总结或只问一个聚焦的追问时，优先选brief。
reader_answer.mode描述这次怎样交付，不是研究主题；不要因为原项目是认知校准就每轮都选calibration。
简短追问可以用brief展示aggregation=calibration的判断，两个字段各司其职。
- calibration：核对用户明确说出的看法。第一段直接说明哪些成立、哪些应调整或仍不确定，
  再用最相关的两三点跨资料证据解释，必要时说明对求职准备的启示。
- overview：先给领域整体认识，再解释最重要的工作类型或分化条件，最后简短交代范围。
- comparison：围绕用户关心的标准比较，先给条件性结论；个人背景不足时不替用户强行选方向。
- brief：回答简单或聚焦的追问。只选一个精炼的核心判断放入一个paragraph，不附加理由或第二个判断。
  用户要求一句话时，claims.text就写一句能独立回答当前问题的话；核对细节可以留在其余claims中。
骨架是组织思路，可以省略不适用部分、调整篇幅，不必固定小标题；不强填共性、差异、例外。
常规回答通常三至五个自然段、总共约300–600字；简单追问一两句即可。用户明确要求详尽清单时再展开。
第一段只选一条直接结论，通常一两句，不超过约80字；岗位例子和长证据解释放在后面。
普通问题优先自然段，不必每段加标题；只有帮助理解复杂比较时才用少量短标题。
reader_answer通常只选择最重要的三四条判断，不需要展示所有研究发现。每段只讲一个重点，
同一理由不要在工作、交付、能力和认知校准中换个说法重复。一般只挑一两个有代表性的岗位解释，
其余具体公司、技术名词、学历年限等清单留在核对记录；只有本题问到这些条件时才进入主回答。
反例和差异必须针对本轮正在核实的同一个命题，不能用另一个问题的例外凑数；
例如“是否完全自主”与“需要哪些开发能力”是不同问题，自动化边界不直接证明技能门槛。
用户只问观点是否准确时，不自动扩写成完整岗位职责或任职资格报告。
claims.text本身写成自然、连贯、面向用户的解释，不把主结论藏在后面，不在多个维度重复同一观点。
任职资格的必备、优先、可选等性质要在文字里准确表达，不能依赖界面标签才能读懂。
claims可保留核对用的细节；reader_answer.paragraphs只选择最相关的claim_indices并按阅读顺序排列，
不要为了展示全部category或aggregation类型而塞入无关判断。引用、研究分类和执行记录由程序收起。
每个paragraph可引用一或两条claims，heading可为空；标题只作导航，不新增未经claims支持的事实。
同一判断只展示一次。建议与认识修正仍须写成有依据的inference/synthesis判断，不编造个人背景。
适用范围或未知若影响本题结论，在对应段落中简短说明；不逐项向用户复述内部缺资料清单。
无可用答案时reader_answer可为null；有可用答案时应提供。模式名称和内部字段名不写进正文。
"""


class ReaderParagraph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    heading: str = Field(max_length=60)
    claim_indices: list[StrictInt] = Field(min_length=1, max_length=2)


class ReaderAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["calibration", "overview", "comparison", "brief"]
    paragraphs: list[ReaderParagraph] = Field(min_length=1, max_length=6)


def checked_reader_answer(layout, claims):
    if layout is None:
        return None
    if layout.mode == "brief" and (
        len(layout.paragraphs) != 1 or len(layout.paragraphs[0].claim_indices) != 1
    ):
        raise ValueError("brief只展示一个paragraph、一个核心判断；理由和其他细节留在研究记录。")
    seen = set()
    for paragraph in layout.paragraphs:
        for index in paragraph.claim_indices:
            if not 0 <= index < len(claims):
                raise ValueError("reader_answer只能选择本轮claims中实际存在的下标。")
            if index in seen:
                raise ValueError("reader_answer不要重复展示同一判断，请合并重复段落。")
            seen.add(index)
    return layout.model_dump()
