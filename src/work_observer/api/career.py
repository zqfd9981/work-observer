"""Job-seeker workspace routes; research execution reuses the existing project worker."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.routing import Route

from work_observer.research.career import CareerService
from work_observer.research.cohort_experiment import CohortCasesInput
from work_observer.research.retrieval_experiment import RetrievalComparisonInput
from work_observer.research.retrieval_suite import RetrievalSuiteInput
from work_observer.research.retry_experiment import RetryCasesInput
from work_observer.research.threshold_experiment import ThresholdCasesInput


class CareerGoalInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=150)
    goal: str = Field(min_length=1, max_length=1000)
    background: str = Field(default="", max_length=1500)
    constraints: str = Field(default="", max_length=500)
    job_ids: list[str] = Field(default_factory=list, max_length=6)


class CareerInput(CareerGoalInput):
    first_question: str = Field(default="", max_length=1000)
    first_question_job_ids: list[str] = Field(default_factory=list, max_length=6)
    resume_title: str = Field(default="个人简历", min_length=1, max_length=150)
    resume_text: str = Field(default="", max_length=20_000)
    material_title: str = Field(default="起始工作资料", max_length=150)
    material_text: str = Field(default="", max_length=20_000)


class CareerSearchQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    q: str = Field(min_length=1, max_length=200)
    scope: Literal["goal", "all"] = "goal"
    record_kind: Literal[
        "all", "story", "task", "insight", "question", "pitch", "discussion"
    ] = "all"
    records_offset: int = Field(default=0, ge=0)
    sources_offset: int = Field(default=0, ge=0)


class CareerGlobalSearchQuery(CareerSearchQuery):
    scope: Literal["all"] = "all"


class CareerReviewQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    q: str = Field(default="", max_length=200)
    goal_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    state: Literal["all", "selected", "parked"] = "selected"
    unknown: bool = False
    offset: int = Field(default=0, ge=0)


class CareerRelationsQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    q: str = Field(default="", max_length=200)
    goal_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    node_kind: Literal[
        "all", "business", "task", "deliverable", "responsibility", "ability", "tool"
    ] = "all"
    predicate: Literal["all", "supports", "requires", "produces", "contradicts"] = "all"
    state: Literal["all", "current", "historical"] = "all"
    offset: int = Field(default=0, ge=0)


class WorkRelationReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(pattern="^[a-f0-9]{32}$")
    step_id: str = Field(pattern="^[a-f0-9]{32}$")
    relation_index: int = Field(strict=True, ge=0)


class WorkRelationInquiryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(default="", max_length=150)
    question: str = Field(min_length=1, max_length=1500)
    relations: list[WorkRelationReference] = Field(min_length=2, max_length=2)
    include_sources: bool = True


class UnderstandingReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(pattern="^[a-f0-9]{32}$")
    note_id: str = Field(pattern="^[a-f0-9]{32}$")


class UnderstandingInquiryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(default="", max_length=150)
    question: str = Field(min_length=1, max_length=1500)
    why_matters: str = Field(default="", max_length=1000)
    next_evidence: str = Field(default="", max_length=1500)
    notes: list[UnderstandingReference] = Field(min_length=2, max_length=2)
    include_sources: bool = True


class StoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=150)
    situation: str = Field(min_length=1, max_length=1500)
    action: str = Field(min_length=1, max_length=2000)
    result: str = Field(min_length=1, max_length=1500)
    limits: str = Field(default="", max_length=1000)
    requirement_key: str = Field(default="", max_length=100)
    source_task_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")


class ResumeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=150)
    text: str = Field(min_length=1, max_length=20_000)


class ReuseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_project_id: str = Field(pattern="^[a-f0-9]{32}$")
    kind: Literal["story", "task", "insight", "question", "discussion"]
    record_id: str = Field(pattern="^[a-f0-9]{32}$")
    source_step_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")


class CareerMaterialInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=150)
    text: str = Field(min_length=1, max_length=20_000)
    source_name: str = Field(default="", max_length=500)


class CareerMaterialCreateInput(CareerMaterialInput):
    question_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")


class AttachMaterialInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str = Field(pattern="^[a-f0-9]{32}$")


class CareerMaterialRevisionInput(CareerMaterialInput):
    base_document_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")


class JobObservationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    description: str = Field(min_length=1, max_length=100_000)
    city: str = Field(default="", max_length=300)
    salary: str = Field(default="", max_length=300)
    education: str = Field(default="", max_length=300)
    experience: str = Field(default="", max_length=300)
    job_url: str = Field(default="", max_length=2000)
    source_published_at: str = Field(default="", max_length=80)
    source_published_raw: str = Field(default="", max_length=300)
    note: str = Field(default="", max_length=1000)
    data_kind: Literal["user_provided", "synthetic"] = "user_provided"


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


class SourcePassageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    public_document_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    document_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    snapshot_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    start: int = Field(strict=True, ge=0)
    end: int = Field(strict=True, ge=1)


class InsightInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    previous_view: str = Field(min_length=1, max_length=1500)
    observation: str = Field(min_length=1, max_length=2000)
    current_view: str = Field(min_length=1, max_length=1500)
    open_question: str = Field(default="", max_length=1000)
    task_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    question_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    source_step_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    source_claim_index: int | None = Field(default=None, ge=0)
    source_relation_index: int | None = Field(default=None, strict=True, ge=0)
    source_task_index: int | None = Field(default=None, strict=True, ge=0, le=2)
    replaces_insight_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")

    source_passage: SourcePassageInput | None = None
    source_passages: list[SourcePassageInput] = Field(default_factory=list, max_length=6)


class QuestionPassageNoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    relation: Literal["unclassified", "supports", "challenges", "conditions"] = "unclassified"
    user_note: str = Field(default="", max_length=1000)
    target_view: str = Field(default="", max_length=700)


class QuestionPassageInput(QuestionPassageNoteInput):
    passage: SourcePassageInput


class CapturePassageInput(QuestionPassageInput):
    goal_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    goal_title: str = Field(default="", max_length=150)
    question_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    question: str = Field(default="", max_length=1500)
    include_source: bool = True


class ConversationNoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    asked_question: str = Field(min_length=1, max_length=1500)
    answer: str = Field(min_length=1, max_length=12_000)
    wording: Literal["quoted", "paraphrased"] = "paraphrased"
    speaker: str = Field(default="", max_length=200)
    context: str = Field(default="", max_length=700)
    said_when: str = Field(default="", max_length=200)
    limits: str = Field(default="", max_length=1500)
    target_job_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    checklist_key: str = Field(default="", max_length=300)


class ResearchQuestionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=1500)
    why_matters: str = Field(default="", max_length=1000)
    next_evidence: str = Field(default="", max_length=1500)
    hypothesis_a: str = Field(default="", max_length=700)
    hypothesis_b: str = Field(default="", max_length=700)
    state: Literal["open", "answered", "parked"] = "open"
    conclusion: str = Field(default="", max_length=2000)
    source_step_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    source_gap_index: int | None = Field(default=None, strict=True, ge=0)
    conclusion_step_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    parent_question_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    source_insight_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    source_passage: SourcePassageInput | None = None
    material_ids: list[Annotated[str, Field(pattern="^[a-f0-9]{32}$")]] | None = Field(
        default=None, max_length=6
    )
    selected_job_ids: list[Annotated[str, Field(pattern="^[a-f0-9]{32}$")]] | None = Field(
        default=None, max_length=6
    )


class CareerFocusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")


class CareerResearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal[
        "role",
        "map",
        "gaps",
        "plan",
        "reflect",
        "interview",
        "teachback",
        "answer",
        "followup",
        "ask",
        "challenge",
        "pitch",
        "evidence",
    ]
    answer: str = Field(default="", max_length=2500)
    inquiry_answer: bool = False
    offline: bool = False
    allow_public: bool = False
    question_index: int = Field(default=0, ge=0, le=20)
    task_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    source_step_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    claim_review_index: int | None = Field(default=None, strict=True, ge=0)
    feedback_gap_index: int | None = Field(default=None, strict=True, ge=0)
    practice_task_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    experiment_ids: list[Annotated[str, Field(pattern="^[a-f0-9]{32}$")]] | None = Field(
        default=None, max_length=4
    )
    inherit_focus: bool = True
    autonomous: bool = False
    adaptive: bool = False
    question: str = Field(default="", max_length=1500)
    section: Literal["requirements", "stories", "experiments", "interview"] = "requirements"
    hypothesis_a: str = Field(default="", max_length=700)
    hypothesis_b: str = Field(default="", max_length=700)
    material_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    material_ids: list[Annotated[str, Field(pattern="^[a-f0-9]{32}$")]] | None = Field(
        default=None, max_length=6
    )
    story_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    insight_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    insight_ids: list[Annotated[str, Field(pattern="^[a-f0-9]{32}$")]] | None = Field(
        default=None, max_length=4
    )
    counter_insight_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    question_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    requirement_key: str = Field(default="", max_length=100)
    comparison_step_ids: list[Annotated[str, Field(pattern="^[a-f0-9]{32}$")]] = Field(
        default_factory=list, max_length=2
    )
    passage_ids: list[Annotated[str, Field(pattern="^[a-f0-9]{32}$")]] | None = Field(
        default=None, max_length=4
    )
    synthesis_question_ids: list[Annotated[str, Field(pattern="^[a-f0-9]{32}$")]] | None = Field(
        default=None, min_length=2, max_length=4
    )
    selected_job_ids: list[Annotated[str, Field(pattern="^[a-f0-9]{32}$")]] | None = Field(
        default=None, max_length=6
    )


class PitchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=150)
    text: str = Field(min_length=1, max_length=2500)
    story_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    source_step_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    question_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")


class TaskImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str = Field(pattern="^[a-f0-9]{32}$")
    action_indices: list[Annotated[int, Field(strict=True, ge=0, le=2)]] | None = Field(
        default=None, min_length=1, max_length=3
    )


class ExperimentComparisonRow(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    condition: str = Field(min_length=1, max_length=300)
    input: str = Field(default="", max_length=600)
    expected: str = Field(default="", max_length=600)
    observed: str = Field(default="", max_length=1000)


class ExperimentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=150)
    task_or_ability: str = Field(min_length=1, max_length=500)
    deliverable: str = Field(min_length=1, max_length=700)
    completion_check: str = Field(min_length=1, max_length=700)
    hypothesis: str = Field(default="", max_length=1500)
    question_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    previous_task_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    source_step_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    source_experiment_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    source_claim_index: int | None = Field(default=None, strict=True, ge=0)
    source_relation_index: int | None = Field(default=None, strict=True, ge=0)
    source_task_index: int | None = Field(default=None, strict=True, ge=0, le=2)
    requirement_key: str = Field(default="", max_length=100)
    design_change: str = Field(default="", max_length=1500)
    comparison_conditions: str = Field(default="", max_length=1000)
    comparison_rows: list[ExperimentComparisonRow] = Field(default_factory=list, max_length=8)


class RetryExperimentInput(RetryCasesInput):
    question_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    hypothesis: str = Field(default="", max_length=1500)
    save: bool = False


class RetrievalExperimentInput(RetrievalComparisonInput):
    question_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    source_step_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    previous_task_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    review_step_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    source_insight_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    hypothesis: str = Field(default="", max_length=1500)
    save: bool = False


class CohortExperimentInput(CohortCasesInput):
    question_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    hypothesis: str = Field(default="", max_length=1500)
    save: bool = False


class RetrievalSuiteExperimentInput(RetrievalSuiteInput):
    question_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    source_step_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    previous_task_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    hypothesis: str = Field(default="", max_length=1500)
    save: bool = False


class ThresholdExperimentInput(ThresholdCasesInput):
    question_id: str | None = Field(default=None, pattern="^[a-f0-9]{32}$")
    hypothesis: str = Field(default="", max_length=1500)
    save: bool = False


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
    comparison_conditions: str | None = Field(default=None, max_length=1000)
    comparison_rows: list[ExperimentComparisonRow] | None = Field(default=None, max_length=8)


def career_routes(*, repository, store, settings, response, read_json, busy, tasks,
                  credentials, import_lock):
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

    async def review(request):
        query = CareerReviewQuery.model_validate(dict(request.query_params))
        result = await run_in_threadpool(service().review, **query.model_dump())
        return response(result)

    async def create(request):
        data = CareerInput.model_validate(await read_json(request))
        return change(lambda: service().create(**data.model_dump()), 201)

    async def job_observation(request):
        from work_observer.storage.archive import RawArchive

        data = JobObservationInput.model_validate(await read_json(request))
        if busy():
            return response({"message": "请等正在进行的研究结束后再补入新JD，输入仍保留。"}, 409)

        def save():
            with import_lock:
                return service().observe_job(
                    request.path_params["id"], request.path_params["job_id"],
                    data.model_dump(), RawArchive(settings.raw_directory, credentials),
                )

        return await run_in_threadpool(lambda: change(save, 201))

    async def get(request):
        return change(lambda: detail(request.path_params["id"]))

    async def focus(request):
        data = CareerFocusInput.model_validate(await read_json(request))
        return change(lambda: service().focus_question(request.path_params["id"], data.question_id))

    async def search(request):
        identity = request.path_params.get("id")
        query_type = CareerSearchQuery if identity else CareerGlobalSearchQuery
        query = query_type.model_validate(dict(request.query_params))
        result = await run_in_threadpool(service().search, identity, **query.model_dump())
        return response(result)

    async def work_relations(request):
        query = CareerRelationsQuery.model_validate(dict(request.query_params))
        return response(await run_in_threadpool(service().work_relations, **query.model_dump()))

    async def relation_inquiry(request):
        data = WorkRelationInquiryInput.model_validate(await read_json(request))
        return change(lambda: service().relation_inquiry(**data.model_dump()), 201)

    async def understanding_inquiry(request):
        data = UnderstandingInquiryInput.model_validate(await read_json(request))
        return change(lambda: service().understanding_inquiry(**data.model_dump()), 201)

    async def capture_passage(request):
        data = CapturePassageInput.model_validate(await read_json(request))
        return change(lambda: service().capture_passage(**data.model_dump()), 201)

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
        values = data.model_dump(exclude={"source_passage"})
        if data.selected_job_ids is None:
            values.pop("selected_job_ids")
        if data.material_ids is None:
            values.pop("material_ids")
        if "parent_question_id" not in data.model_fields_set:
            values.pop("parent_question_id")
        if "source_gap_index" not in data.model_fields_set:
            values.pop("source_gap_index")
        if data.source_passage:
            values["source_passage"] = data.source_passage.model_dump(exclude_none=True)
        return change(
            lambda: service().save_question(
                request.path_params["id"], values, request.path_params.get("question_id")
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

    async def question_passage(request):
        identity, question_id = request.path_params["id"], request.path_params["question_id"]
        passage_id = request.path_params.get("passage_id")
        if request.method == "DELETE":
            return change(
                lambda: service().remove_question_passage(identity, question_id, passage_id)
            )
        schema = QuestionPassageNoteInput if passage_id else QuestionPassageInput
        values = schema.model_validate(await read_json(request)).model_dump(exclude_none=True)
        return change(
            lambda: service().save_question_passage(identity, question_id, values, passage_id),
            200 if passage_id else 201,
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
        data = CareerMaterialCreateInput.model_validate(await read_json(request))
        return change(
            lambda: service().add_material(request.path_params["id"], **data.model_dump()), 201
        )

    async def conversation_note(request):
        if busy():
            return response({"message": "请等本轮研究结束后再保存沟通回复，输入仍保留。"}, 409)
        data = ConversationNoteInput.model_validate(await read_json(request))
        return change(lambda: service().record_conversation(
            request.path_params["id"], request.path_params["question_id"], data.model_dump()
        ), 201)

    async def attach_material(request):
        if busy():
            return response({"message": "请等本轮研究结束后再加入材料。"}, 409)
        data = AttachMaterialInput.model_validate(await read_json(request))
        return change(
            lambda: service().attach_material(request.path_params["id"], **data.model_dump())
        )

    async def revise_material(request):
        if busy():
            return response({"message": "请等本轮研究结束后再更新资料，输入仍保留。"}, 409)
        data = CareerMaterialRevisionInput.model_validate(await read_json(request))
        return await run_in_threadpool(lambda: change(lambda: service().revise_material(
            request.path_params["id"], request.path_params["document_id"], **data.model_dump()
        )))

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
        return change(lambda: service().import_tasks(
            request.path_params["id"], data.step_id, data.action_indices
        ))

    async def experiment(request):
        data = ExperimentInput.model_validate(await read_json(request))
        return change(
            lambda: service().add_experiment(request.path_params["id"], data.model_dump()), 201
        )

    async def retrieval_experiment(request):
        data = RetrievalExperimentInput.model_validate(await read_json(request))
        return change(
            lambda: service().retrieval_experiment(request.path_params["id"], **data.model_dump()),
            201 if data.save else 200,
        )

    async def retrieval_record(request):
        return change(lambda: service().retrieval_experiment_record(
            request.path_params["id"], request.path_params["task_id"],
        ))

    async def retrieval_suite(request):
        data = RetrievalSuiteExperimentInput.model_validate(await read_json(request))
        return change(
            lambda: service().retrieval_suite(request.path_params["id"], **data.model_dump()),
            201 if data.save else 200,
        )

    async def retry_experiment(request):
        data = RetryExperimentInput.model_validate(await read_json(request))
        return change(
            lambda: service().retry_experiment(request.path_params["id"], **data.model_dump()),
            201 if data.save else 200,
        )

    async def cohort_experiment(request):
        data = CohortExperimentInput.model_validate(await read_json(request))
        return change(
            lambda: service().cohort_experiment(request.path_params["id"], **data.model_dump()),
            201 if data.save else 200,
        )

    async def threshold_experiment(request):
        data = ThresholdExperimentInput.model_validate(await read_json(request))
        return change(
            lambda: service().threshold_experiment(request.path_params["id"], **data.model_dump()),
            201 if data.save else 200,
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
        Route("/api/career/review", review),
        Route("/api/career/work-relations", work_relations),
        Route("/api/career/work-relations/inquiry", relation_inquiry, methods=["POST"]),
        Route("/api/career/understanding/inquiry", understanding_inquiry, methods=["POST"]),
        Route("/api/career/search", search),
        Route("/api/career/capture-passage", capture_passage, methods=["POST"]),
        Route("/api/career", create, methods=["POST"]),
        Route("/api/career/{id}", get),
        Route("/api/career/{id}/focus", focus, methods=["PATCH"]),
        Route("/api/career/{id}/jobs/{job_id}/observations", job_observation, methods=["POST"]),
        Route("/api/career/{id}/search", search),
        Route("/api/career/{id}/reuse", reuse, methods=["POST"]),
        Route("/api/career/{id}/materials", add_material, methods=["POST"]),
        Route("/api/career/{id}/materials/attach", attach_material, methods=["POST"]),
        Route("/api/career/{id}/materials/{document_id}/revisions", revise_material,
              methods=["POST"]),
        Route("/api/career/{id}/materials/{document_id}", remove_material, methods=["DELETE"]),
        Route("/api/career/{id}", update_goal, methods=["PATCH"]),
        Route("/api/career/{id}/resume", resume, methods=["PATCH"]),
        Route("/api/career/{id}/insights", insight, methods=["POST"]),
        Route("/api/career/{id}/insights/{insight_id}", edit_insight, methods=["PATCH"]),
        Route("/api/career/{id}/insights/{insight_id}/use", insight_use, methods=["POST"]),
        Route("/api/career/{id}/questions", question, methods=["POST"]),
        Route("/api/career/{id}/questions/{question_id}", question, methods=["PATCH"]),
        Route("/api/career/{id}/questions/{question_id}/passages",
              question_passage, methods=["POST"]),
        Route("/api/career/{id}/questions/{question_id}/conversation-notes",
              conversation_note, methods=["POST"]),
        Route("/api/career/{id}/questions/{question_id}/passages/{passage_id}",
              question_passage, methods=["PATCH", "DELETE"]),
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
        Route("/api/career/{id}/experiments/retry", retry_experiment, methods=["POST"]),
        Route("/api/career/{id}/experiments/retrieval", retrieval_experiment, methods=["POST"]),
        Route("/api/career/{id}/experiments/retrieval-suite", retrieval_suite, methods=["POST"]),
        Route("/api/career/{id}/tasks/{task_id}/retrieval-inputs", retrieval_record),
        Route("/api/career/{id}/experiments/cohorts", cohort_experiment, methods=["POST"]),
        Route("/api/career/{id}/experiments/thresholds", threshold_experiment, methods=["POST"]),
        Route("/api/career/{id}/tasks/{task_id}", update_task, methods=["PATCH"]),
    ]
