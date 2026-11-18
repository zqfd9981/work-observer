"""可公开分发的固定模拟检索夹具；没有真实岗位、公司或个人资料。"""

SUITE_VERSION = "synthetic-retrieval-v1"
DOCUMENTS = (
    ("agent-cn", "智能体研发", "职责：构建智能体的工具调用链，维护业务应用。"),
    ("rag-cn", "知识库研发", "职责：实现检索增强生成流程，评估知识库回答。"),
    ("reliability", "服务工程", "职责：实现限流、重试和降级，保障后端服务。"),
    ("evaluation", "质量工程", "职责：维护评测集、回归测试和质量基准。"),
    ("python", "接口开发", "必备 Python，负责业务接口与数据处理。"),
    ("docker", "应用交付", "职责：维护 Docker 容器，交付可运行的软件。"),
)
# (固定问题编号, 字面查询, 应召回资料编号, 是否关键回归)
CASES = (
    ("agent-alias", "Agent", "agent-cn", False),
    ("rag-alias", "RAG", "rag-cn", False),
    ("reliability-alias", "后端可靠性", "reliability", False),
    ("evaluation-alias", "评估", "evaluation", False),
    ("python-direct", "Python", "python", True),
    ("docker-direct", "Docker", "docker", True),
)
CONTRACT = {
    "recall_at_k": 3,
    "minimum_cases": 6,
    "minimum_mean_recall": 0.8,
    "minimum_improvement": 0.15,
    "maximum_context_characters": 2100,
    "maximum_searches": 12,
    "critical_regression_allowed": False,
    "source_version_guard_required": True,
    "data_mode": "synthetic_test_only",
    "scope": "固定模拟夹具上的检索评测，不代表真实市场召回、语义质量或采集效果。",
}
