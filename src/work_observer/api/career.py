"""Job-seeker workspace routes; research execution reuses the existing project worker."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.routing import Route

from work_observer.research.career import CareerService


class CareerGoalInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=150)
    goal: str = Field(min_length=1, max_length=1000)
    background: str = Field(min_length=1, max_length=1500)
    constraints: str = Field(default="", max_length=500)
    job_ids: list[str] = Field(min_length=1, max_length=6)


class CareerInput(CareerGoalInput):
    resume_title: str = Field(default="个人简历", min_length=1, max_length=150)
    resume_text: str = Field(default="", max_length=20_000)


class CareerSearchQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    q: str = Field(min_length=1, max_length=200)
    scope: Literal["goal", "all"] = "goal"
    record_kind: Literal[
        "all", "story", "task", "insight", "question", "pitch", "discussion"
    ] = "all"
    records_offset: int = Field(default=0, ge=0)
    sources_offset: int = Field(default=0, ge=0)


class StoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=150)
    situation: str = Field(min_length=1, max_length=1500)
    action: str = Field(min_length=1, max_length=2000)
    result: str = Field(min_length=1, max_length=1500)
    limits: str = Field(default="", max_length=1000)
    requirement_key: str = Field(default="", max_length=100)


class ResumeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=150)
    text: str = Field(min_length=1, max_length=20_000)


class ReuseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_project_id: str = Field(pattern="^[a-f0-9]{32}$")
    kind: Literal["story", "task", "insight", "question"]
    record_id: str = Field(pattern="^[a-f0-9]{32}$")


class CareerMaterialInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=150)
    text: str = Field(min_length=1, max_length=20_000)
    source_name: str = Field(default="", max_length=500)


class AttachMaterialInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str = Field(pattern="^[a-f0-9]{32}$")


class InsightInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    previous_view: str = Field(min_length=1, max_length=1500)
    observation: str = Field(min_length=1, max_length=2000)
    current_view: str = Field(min_length=1, max_length=1500)
    open_question: str = Field(default="", max_length=1000)
    task_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    source_step_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    source_claim_index: int | None = Field(default=None, ge=0)
    replaces_insight_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")


class InsightUseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    use_for_research: bool = Field(strict=True)


class RequirementRecordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["story", "task", "material"]
    id: str = Field(pattern="^[a-f0-9]{32}$")


class RequirementEvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    requirement_key: str = Field(min_length=1, max_length=100)
    records: list[RequirementRecordInput] = Field(default_factory=list, max_length=3)
    relevance: str = Field(default="", max_length=1500)
    missing: str = Field(default="", max_length=1500)


class ResearchQuestionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=1500)
    why_matters: str = Field(default="", max_length=1000)
    next_evidence: str = Field(default="", max_length=1500)
    state: Literal["open", "answered", "parked"] = "open"
    conclusion: str = Field(default="", max_length=2000)
    source_step_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    conclusion_step_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")


class CareerResearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal[
        "role",
        "map",
        "gaps",
        "plan",
        "reflect",
        "interview",
        "answer",
        "followup",
        "ask",
        "challenge",
        "pitch",
        "evidence",
    ]
    answer: str = Field(default="", max_length=2500)
    offline: bool = False
    allow_public: bool = False
    question_index: int = Field(default=0, ge=0, le=20)
    task_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    source_step_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    inherit_focus: bool = True
    question: str = Field(default="", max_length=1500)
    section: Literal["requirements", "stories", "experiments", "interview"] = "requirements"
    hypothesis_a: str = Field(default="", max_length=700)
    hypothesis_b: str = Field(default="", max_length=700)
    material_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    story_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    insight_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    counter_insight_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    question_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    requirement_key: str = Field(default="", max_length=100)
    comparison_step_ids: list[Annotated[str, Field(pattern="^[a-f0-9]{32}$")]] = Field(
        default_factory=list, max_length=2
    )


class PitchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=150)
    text: str = Field(min_length=1, max_length=2500)
    story_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    source_step_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")


class TaskImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str = Field(pattern="^[a-f0-9]{32}$")


class ExperimentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=150)
    task_or_ability: str = Field(min_length=1, max_length=500)
    deliverable: str = Field(min_length=1, max_length=700)
    completion_check: str = Field(min_length=1, max_length=700)
    hypothesis: str = Field(default="", max_length=1500)
    question_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    previous_task_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    design_change: str = Field(default="", max_length=1500)


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=150)
    task_or_ability: str | None = Field(default=None, min_length=1, max_length=500)
    deliverable: str | None = Field(default=None, min_length=1, max_length=700)
    completion_check: str | None = Field(default=None, min_length=1, max_length=700)
    state: Literal["planned", "doing", "done"]
    outcome: str = Field(default="", max_length=4000)
    artifact: str = Field(default="", max_length=1000)
    hypothesis: str | None = Field(default=None, max_length=1500)
    artifact_title: str = Field(default="工作样本材料", max_length=150)
    artifact_text: str = Field(default="", max_length=20_000)
    design_change: str = Field(default="", max_length=1500)


def career_routes(*, repository, store, settings, response, read_json, busy, tasks):
    def service():
        return CareerService(store(), repository(), settings.raw_directory)

    def detail(identity):
        data = service().get(identity)
        task = tasks.get("project:" + identity)
        data["running"] = data["running"] or bool(task and not task.done())
        return data

    def change(action, status=200):
        try:
            return response(action(), status)
        except ValueError as error:
            return response({"message": str(error)}, 422)

    async def listing(request):
        return response(service().listing())

    async def create(request):
        data = CareerInput.model_validate(await read_json(request))
        return change(lambda: service().create(**data.model_dump()), 201)

    async def get(request):
        return change(lambda: detail(request.path_params["id"]))

    async def search(request):
        query = CareerSearchQuery.model_validate(dict(request.query_params))
        result = await run_in_threadpool(
            service().search, request.path_params["id"], **query.model_dump()
        )
        return response(result)

    async def update_goal(request):
        task = tasks.get("project:" + request.path_params["id"])
        if task and not task.done():
            return response({"message": "请等本轮研究结束后再调整目标，输入仍保留。"}, 409)
        data = CareerGoalInput.model_validate(await read_json(request))
        return change(lambda: service().update_goal(request.path_params["id"], **data.model_dump()))

    async def story(request):
        if busy():
            return response({"message": "请等当前研究结束后再保存经历，输入仍保留。"}, 409)
        data = StoryInput.model_validate(await read_json(request))
        return change(
            lambda: service().add_story(request.path_params["id"], data.model_dump()), 201
        )

    async def prepare(request):
        if busy():
            return response({"message": "已有研究正在进行，请稍后再开始。"}, 409)
        data = CareerResearchInput.model_validate(await read_json(request))
        return change(
            lambda: service().prepare(request.path_params["id"], **data.model_dump()), 201
        )

    async def end_step(request):
        task = tasks.get("project:" + request.path_params["id"])
        if task and not task.done():
            return response({"message": "请先暂停正在进行的这轮研究。"}, 409)
        return change(
            lambda: service().end_step(request.path_params["id"], request.path_params["step_id"])
        )

    async def resume(request):
        if busy():
            return response({"message": "请等本轮研究结束后再更新简历，输入仍保留。"}, 409)
        data = ResumeInput.model_validate(await read_json(request))
        return change(lambda: service().set_resume(request.path_params["id"], **data.model_dump()))

    async def insight(request):
        data = InsightInput.model_validate(await read_json(request))
        return change(
            lambda: service().add_insight(request.path_params["id"], data.model_dump()), 201
        )

    async def edit_insight(request):
        data = InsightInput.model_validate(await read_json(request))
        return change(
            lambda: service().add_insight(
                request.path_params["id"], data.model_dump(), request.path_params["insight_id"]
            )
        )

    async def insight_use(request):
        data = InsightUseInput.model_validate(await read_json(request))
        return change(
            lambda: service().use_insight(
                request.path_params["id"], request.path_params["insight_id"], data.use_for_research
            )
        )

    async def question(request):
        data = ResearchQuestionInput.model_validate(await read_json(request))
        return change(
            lambda: service().save_question(
                request.path_params["id"], data.model_dump(), request.path_params.get("question_id")
            ),
            200 if request.path_params.get("question_id") else 201,
        )

    async def requirement_evidence(request):
        data = RequirementEvidenceInput.model_validate(await read_json(request))
        return change(
            lambda: service().save_requirement_evidence(
                request.path_params["id"], data.model_dump()
            )
        )

    async def pitch(request):
        data = PitchInput.model_validate(await read_json(request))
        return change(
            lambda: service().save_pitch(
                request.path_params["id"], data.model_dump(), request.path_params.get("pitch_id")
            ),
            200 if request.path_params.get("pitch_id") else 201,
        )

    async def edit_story(request):
        if busy():
            return response({"message": "请等当前研究结束后再修改经历，输入仍保留。"}, 409)
        data = StoryInput.model_validate(await read_json(request))
        return change(
            lambda: service().add_story(
                request.path_params["id"], data.model_dump(), request.path_params["story_id"]
            )
        )

    async def reuse(request):
        if busy():
            return response({"message": "请等本轮研究结束后再带入经历或作品材料。"}, 409)
        data = ReuseInput.model_validate(await read_json(request))
        return change(lambda: service().reuse(request.path_params["id"], **data.model_dump()))

    async def add_material(request):
        if busy():
            return response({"message": "请等本轮研究结束后再补充资料，输入仍保留。"}, 409)
        data = CareerMaterialInput.model_validate(await read_json(request))
        return change(
            lambda: service().add_material(request.path_params["id"], **data.model_dump()), 201
        )

    async def attach_material(request):
        if busy():
            return response({"message": "请等本轮研究结束后再加入材料。"}, 409)
        data = AttachMaterialInput.model_validate(await read_json(request))
        return change(
            lambda: service().attach_material(request.path_params["id"], **data.model_dump())
        )

    async def remove_material(request):
        if busy():
            return response({"message": "请等本轮研究结束后再调整资料。"}, 409)
        return change(
            lambda: service().remove_material(
                request.path_params["id"], request.path_params["document_id"]
            )
        )

    async def remove_story(request):
        if busy():
            return response({"message": "请等当前研究结束后再移出经历。"}, 409)
        return change(
            lambda: service().remove_story(
                request.path_params["id"], request.path_params["story_id"]
            )
        )

    async def import_tasks(request):
        data = TaskImport.model_validate(await read_json(request))
        return change(lambda: service().import_tasks(request.path_params["id"], data.step_id))

    async def experiment(request):
        data = ExperimentInput.model_validate(await read_json(request))
        return change(
            lambda: service().add_experiment(request.path_params["id"], data.model_dump()), 201
        )

    async def update_task(request):
        data = TaskUpdate.model_validate(await read_json(request))
        if data.artifact_text.strip() and busy():
            return response({"message": "请等本轮研究结束后再保存作品材料，输入仍保留。"}, 409)
        return change(
            lambda: service().update_task(
                request.path_params["id"], request.path_params["task_id"], **data.model_dump()
            )
        )

    return [
        Route("/api/career", listing),
        Route("/api/career", create, methods=["POST"]),
        Route("/api/career/{id}", get),
        Route("/api/career/{id}/search", search),
        Route("/api/career/{id}/reuse", reuse, methods=["POST"]),
        Route("/api/career/{id}/materials", add_material, methods=["POST"]),
        Route("/api/career/{id}/materials/attach", attach_material, methods=["POST"]),
        Route("/api/career/{id}/materials/{document_id}", remove_material, methods=["DELETE"]),
        Route("/api/career/{id}", update_goal, methods=["PATCH"]),
        Route("/api/career/{id}/resume", resume, methods=["PATCH"]),
        Route("/api/career/{id}/insights", insight, methods=["POST"]),
        Route("/api/career/{id}/insights/{insight_id}", edit_insight, methods=["PATCH"]),
        Route("/api/career/{id}/insights/{insight_id}/use", insight_use, methods=["POST"]),
        Route("/api/career/{id}/questions", question, methods=["POST"]),
        Route("/api/career/{id}/questions/{question_id}", question, methods=["PATCH"]),
        Route("/api/career/{id}/requirement-evidence", requirement_evidence, methods=["POST"]),
        Route("/api/career/{id}/pitches", pitch, methods=["POST"]),
        Route("/api/career/{id}/pitches/{pitch_id}", pitch, methods=["PATCH"]),
        Route("/api/career/{id}/stories", story, methods=["POST"]),
        Route("/api/career/{id}/stories/{story_id}", edit_story, methods=["PATCH"]),
        Route("/api/career/{id}/stories/{story_id}", remove_story, methods=["DELETE"]),
        Route("/api/career/{id}/prepare", prepare, methods=["POST"]),
        Route("/api/career/{id}/steps/{step_id}", end_step, methods=["DELETE"]),
        Route("/api/career/{id}/tasks", import_tasks, methods=["POST"]),
        Route("/api/career/{id}/experiments", experiment, methods=["POST"]),
        Route("/api/career/{id}/tasks/{task_id}", update_task, methods=["PATCH"]),
    ]
