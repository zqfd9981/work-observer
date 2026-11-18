"""授权可分发的合成岗位；只创建全新演示目录，不读取正式资料。"""

import json
from pathlib import Path

from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.memory.service import MemoryService
from work_observer.research.store import ResearchStore
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.repository import Repository

DEMO_JOBS = [
    {
        "external_id": "demo-app",
        "title": "合成演示·智能体应用工程师",
        "company": "合成·青禾软件",
        "city": "上海",
        "salary": "20-30K",
        "education": "本科",
        "experience": "1-3年",
        "description": (
            "【合成演示资料，不是真实招聘】\n业务背景：为企业内部客服搭建知识问答应用。\n"
            "职责：实现检索增强问答与工具调用；交付可部署的服务接口和回归评测集，协助产品确认答案质量。\n"
            "任职要求：必备Python编程、HTTP接口设计与SQL数据查询能力。\n"
            "加分：使用过Docker，能设计离线评测。\n工具：Python、PostgreSQL、Docker。\n"
            "未知：用工主体、具体绩效指标、当前招聘状态。"
        ),
    },
    {
        "external_id": "demo-platform",
        "title": "合成演示·执行平台工程师",
        "company": "合成·青禾软件",
        "city": "北京",
        "salary": "30-45K",
        "description": (
            "【合成演示资料，不是真实招聘】\n背景：建设内部AI任务执行平台。\n"
            "职责：设计任务状态机、重试、限流和降级；交付执行引擎与运行诊断页面，独立承担平台上线与可靠性。\n"
            "必备：Python后端开发、分布式任务与故障诊断能力。\n"
            "加分：有Kubernetes运维经验。工具采用Python、Redis、Kubernetes。\n"
            "未说明：具体学历与用工形式。"
        ),
    },
    {
        "external_id": "demo-config",
        "title": "合成演示·平台实施顾问",
        "company": "合成·远岚服务",
        "city": "上海",
        "salary": "180-240元/天",
        "description": (
            "【合成演示资料，不是真实招聘】\n"
            "工作：配置低代码工作流、整理客户知识库、编写使用手册并培训使用者；交付通过客户验收的配置方案。\n"
            "必备：客户沟通、需求整理和文档表达。加分：了解Python。\n"
            "使用可视化工作流工具；没有要求负责执行引擎开发。\n用工主体与是否外包未披露。"
        ),
    },
    {
        "external_id": "demo-unknown",
        "title": "合成演示·AI工程方向待核实",
        "company": "合成·示例组织",
        "description": (
            "【合成演示资料，不是真实招聘】\n这是刻意保留信息缺口的岗位样例，只说明招募AI开发方向。"
            "任务、交付物、工具、学历、地点、薪资与用工形式未提供；不得补造。"
        ),
    },
]


def create_demo(destination):
    root = Path(destination).resolve()
    if root.exists():
        raise ProbeError("DEMO_DESTINATION_EXISTS")
    root.mkdir(parents=True)
    path = root / "app.db"
    upgrade(path)
    repo = Repository(path)
    try:
        archive = RawArchive(root / "raw")
        ids = []
        for values in DEMO_JOBS:
            jd = ManualJD(
                **values, data_kind="synthetic", note="项目内原创可分发合成资料，非市场观察"
            )
            ids.append(import_jd(repo, archive, jd)["job_id"])
        changed = {
            **DEMO_JOBS[0],
            "description": DEMO_JOBS[0]["description"]
            + "\n【合成版本修改】新增职责：维护线上评测集和告警面板。",
        }
        import_jd(repo, archive, ManualJD(**changed, data_kind="synthetic"))
        MemoryService(repo).create(
            "preference", "合成演示偏好：优先查看需要独立开发和上线的工作，不将此当成真实用户履历。"
        )
        store = ResearchStore(root / "checkpoints.db", str(path))
        store.close()
        (root / "demo-manifest.json").write_text(
            json.dumps(
                {"data_kind": "synthetic", "job_ids": ids, "network_calls": 0},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return {
            "database": str(path),
            "raw_directory": str(root / "raw"),
            "reports_dir": str(root / "reports"),
            "jobs": len(ids),
            "data_kind": "synthetic",
            "network_calls": 0,
            "note": "演示数据已标合成。离线研究只整理证据；"
            "配置模型后可真实调用，不假装已有模型结果。",
        }
    finally:
        repo.close()
