"""锁定模拟夹具上的基线/候选检索评测，以及显式策略版本切换。"""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from work_observer.collection.contracts import now
from work_observer.connectors.manual import ManualJD, import_jd
from work_observer.connectors.mcp_probe import ProbeError
from work_observer.retrieval.enhanced import RetrievalService
from work_observer.storage.archive import RawArchive
from work_observer.storage.database import upgrade
from work_observer.storage.models import JobSnapshot
from work_observer.storage.repository import Repository
from work_observer.tracking.fixtures import CASES, CONTRACT, DOCUMENTS, SUITE_VERSION
from work_observer.tracking.models import RetrievalStrategy, StrategyEvent, StrategyExperiment

BASELINE_ID = "literal-v1"


def config_hash(config):
    return hashlib.sha256(
        json.dumps(config, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def record(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def validate_aliases(value):
    if not isinstance(value, dict) or len(value) > 20:
        raise ProbeError("INVALID_STRATEGY_ALIASES")
    result = {}
    for key, terms in value.items():
        if (
            not isinstance(key, str)
            or not key.strip()
            or len(key) > 100
            or not isinstance(terms, list)
            or len(terms) > 8
            or any(
                not isinstance(term, str) or not term.strip() or len(term) > 100 for term in terms
            )
        ):
            raise ProbeError("INVALID_STRATEGY_ALIASES")
        result[key.strip()] = list(dict.fromkeys(term.strip() for term in terms))
    return result


class StrategyService:
    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def _baseline(session):
        baseline = session.get(RetrievalStrategy, BASELINE_ID)
        if baseline is None:
            baseline = RetrievalStrategy(
                id=BASELINE_ID,
                name="字面检索基线",
                config={"aliases": {}},
                status="active",
                created_at=now(),
            )
            session.add(baseline)
            session.flush()
        return baseline

    @staticmethod
    def _get(session, identity):
        row = session.get(RetrievalStrategy, identity)
        if row is None:
            raise ProbeError("STRATEGY_NOT_FOUND")
        return row

    def active_config(self):
        with Session(self.repository.engine) as session:
            row = session.scalar(
                select(RetrievalStrategy).where(RetrievalStrategy.status == "active")
            )
            return row.config if row else {"aliases": {}}

    def active(self):
        with Session(self.repository.engine) as session:
            row = session.scalar(
                select(RetrievalStrategy).where(RetrievalStrategy.status == "active")
            )
            return (
                record(row)
                if row
                else {
                    "id": BASELINE_ID,
                    "name": "字面检索基线",
                    "config": {"aliases": {}},
                    "status": "active",
                    "created_at": None,
                }
            )

    def create(self, name, aliases):
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ProbeError("INVALID_STRATEGY_NAME")
        config = {"aliases": validate_aliases(aliases)}
        with Session(self.repository.engine) as session, session.begin():
            self._baseline(session)
            row = RetrievalStrategy(
                id=uuid4().hex,
                name=name.strip(),
                config=config,
                status="candidate",
                created_at=now(),
            )
            session.add(row)
            session.flush()
            return record(row)

    def list(self):
        with Session(self.repository.engine) as session:
            return [
                record(row)
                for row in session.scalars(
                    select(RetrievalStrategy).order_by(RetrievalStrategy.created_at.desc())
                )
            ]

    def experiments(self):
        with Session(self.repository.engine) as session:
            return [
                record(row)
                for row in session.scalars(
                    select(StrategyExperiment)
                    .order_by(StrategyExperiment.created_at.desc())
                    .limit(100)
                )
            ]

    def events(self):
        with Session(self.repository.engine) as session:
            return [
                record(row)
                for row in session.scalars(
                    select(StrategyEvent).order_by(StrategyEvent.created_at.desc()).limit(100)
                )
            ]

    def evaluate(self, identity, case_ids=None):
        with Session(self.repository.engine) as session:
            strategy = self._get(session, identity)
            if strategy.status in {"rolled_back", "rejected", "active"}:
                raise ProbeError("STRATEGY_REQUIRES_NEW_CANDIDATE")
            aliases = strategy.config["aliases"]
        baseline = self.active()
        if case_ids is not None and (
            not isinstance(case_ids, list)
            or any(not isinstance(case, str) for case in case_ids)
            or not set(case_ids).issubset({case[0] for case in CASES})
        ):
            raise ProbeError("INVALID_EVALUATION_CASES")
        cases = [case for case in CASES if case_ids is None or case[0] in case_ids]
        contract = {**CONTRACT}
        contract.update(
            baseline_id=baseline["id"],
            baseline_config=baseline["config"],
            baseline_sha256=config_hash(baseline["config"]),
            candidate_sha256=config_hash({"aliases": aliases}),
            phase="paired_evaluation",
        )
        contract["suite_sha256"] = hashlib.sha256(
            json.dumps([DOCUMENTS, CASES, CONTRACT], ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        metrics = self._run(aliases, cases, baseline["config"]["aliases"])
        if len(cases) < CONTRACT["minimum_cases"]:
            status, reason = "insufficient", "固定问题的有效样本不足，保持现有策略。"
        elif (
            not metrics["source_version_guard"]
            or metrics["critical_regressions"]
            or not metrics["budget_guard"]
            or metrics["candidate_recall"] < CONTRACT["minimum_mean_recall"]
            or metrics["improvement"] < CONTRACT["minimum_improvement"]
        ):
            status, reason = "rejected", "未达到锁定召回改善门槛或关键护栏，保持现有策略。"
        else:
            status, reason = "accepted", "固定模拟夹具通过；可显式启用，真实资料效果仍须另行验证。"
        metrics["reason"] = reason
        with Session(self.repository.engine) as session, session.begin():
            strategy = self._get(session, identity)
            if strategy.status in {"rolled_back", "rejected", "active"}:
                raise ProbeError("STRATEGY_REQUIRES_NEW_CANDIDATE")
            if status == "rejected":
                strategy.status = "rejected"
            elif status == "accepted":
                strategy.status = "evaluated"
            experiment = StrategyExperiment(
                id=uuid4().hex,
                strategy_id=identity,
                suite_version=SUITE_VERSION,
                contract=contract,
                metrics=metrics,
                status=status,
                created_at=now(),
            )
            session.add(experiment)
            session.flush()
            return record(experiment)

    @staticmethod
    def _run(aliases, cases, baseline_aliases=None):
        rows, valid, budget = [], True, True
        with TemporaryDirectory(prefix="work-observer-eval-") as directory:
            root = Path(directory)
            upgrade(root / "synthetic.db")
            repository = Repository(root / "synthetic.db")
            try:
                archive = RawArchive(root / "raw")
                jobs, versions = {}, {}
                for identity, title, text in DOCUMENTS:
                    jobs[identity] = import_jd(
                        repository,
                        archive,
                        ManualJD(
                            title="模拟·" + title,
                            company="模拟评测公司",
                            external_id=identity,
                            description=text,
                            data_kind="synthetic",
                        ),
                    )["job_id"]
                with Session(repository.engine) as session:
                    versions = {
                        row.job_id: (row.id, row.payload["description"], row.first_document_id)
                        for row in session.scalars(
                            select(JobSnapshot).where(JobSnapshot.kind == "detail")
                        )
                    }
                baseline = RetrievalService(repository, alias_groups=baseline_aliases or {})
                candidate = RetrievalService(repository, alias_groups=aliases)
                for case_id, term, expected, critical in cases:
                    a = baseline.search([term], limit=CONTRACT["recall_at_k"], aliases=True)
                    b = candidate.search([term], limit=CONTRACT["recall_at_k"], aliases=True)
                    for result in (a, b):
                        budget &= (
                            result["context_characters"] <= CONTRACT["maximum_context_characters"]
                        )
                        for item in result["evidence"]:
                            snapshot, text, document = versions.get(
                                item["job_id"], (None, "", None)
                            )
                            valid &= (
                                snapshot == item["snapshot_id"]
                                and document == item["document_id"]
                                and text[item["start"] : item["end"]] == item["quote"]
                            )
                    a_hit = jobs[expected] in {item["job_id"] for item in a["evidence"]}
                    b_hit = jobs[expected] in {item["job_id"] for item in b["evidence"]}
                    rows.append(
                        {
                            "case_id": case_id,
                            "baseline_recall": float(a_hit),
                            "candidate_recall": float(b_hit),
                            "critical": critical,
                            "regression": critical and a_hit and not b_hit,
                        }
                    )
            finally:
                repository.close()
        baseline_mean = sum(row["baseline_recall"] for row in rows) / len(rows) if rows else 0
        candidate_mean = sum(row["candidate_recall"] for row in rows) / len(rows) if rows else 0
        return {
            "cases": rows,
            "case_count": len(rows),
            "baseline_recall": baseline_mean,
            "candidate_recall": candidate_mean,
            "improvement": candidate_mean - baseline_mean,
            "critical_regressions": [row["case_id"] for row in rows if row["regression"]],
            "source_version_guard": valid,
            "budget_guard": budget and len(rows) * 2 <= CONTRACT["maximum_searches"],
            "searches": len(rows) * 2,
            "external_calls": 0,
            "data_mode": "synthetic_test_only",
        }

    def activate(self, identity):
        with Session(self.repository.engine) as session, session.begin():
            self._baseline(session)
            row = self._get(session, identity)
            if row.status == "active":
                return record(row)
            if row.status in {"rolled_back", "rejected"}:
                raise ProbeError("STRATEGY_REQUIRES_NEW_CANDIDATE")
            experiment = session.scalar(
                select(StrategyExperiment)
                .where(StrategyExperiment.strategy_id == identity)
                .order_by(StrategyExperiment.created_at.desc())
                .limit(1)
            )
            if experiment is None or experiment.status != "accepted":
                raise ProbeError("STRATEGY_EVALUATION_NOT_ACCEPTED")
            previous = session.scalar(
                select(RetrievalStrategy).where(RetrievalStrategy.status == "active")
            )
            if (
                previous is None
                or previous.id != experiment.contract.get("baseline_id")
                or config_hash(previous.config) != experiment.contract.get("baseline_sha256")
                or config_hash(row.config) != experiment.contract.get("candidate_sha256")
            ):
                raise ProbeError("STRATEGY_BASELINE_CHANGED_REEVALUATE")
            if previous:
                previous.status = "superseded"
            row.status = "active"
            session.add(
                StrategyEvent(
                    id=uuid4().hex,
                    strategy_id=row.id,
                    previous_strategy_id=previous.id if previous else None,
                    action="activated",
                    reason="显式启用；固定模拟评测通过，不扩大来源或权限。",
                    created_at=now(),
                )
            )
            return record(row)

    def rollback(self, reason="人工回退", *, automatic=False, expected_identity=None):
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
            raise ProbeError("INVALID_ROLLBACK_REASON")
        with Session(self.repository.engine) as session, session.begin():
            baseline = self._baseline(session)
            current = session.scalar(
                select(RetrievalStrategy).where(RetrievalStrategy.status == "active")
            )
            if current is None or current.id == BASELINE_ID:
                raise ProbeError("STRATEGY_ALREADY_BASELINE")
            if expected_identity is not None and current.id != expected_identity:
                raise ProbeError("STRATEGY_ACTIVE_CHANGED_RECHECK")
            last = session.scalar(
                select(StrategyEvent)
                .where(StrategyEvent.strategy_id == current.id, StrategyEvent.action == "activated")
                .order_by(StrategyEvent.created_at.desc())
                .limit(1)
            )
            prior = (
                session.get(RetrievalStrategy, last.previous_strategy_id)
                if last and last.previous_strategy_id
                else baseline
            )
            current.status = "rolled_back"
            prior.status = "active"
            session.add(
                StrategyEvent(
                    id=uuid4().hex,
                    strategy_id=current.id,
                    previous_strategy_id=prior.id,
                    action="automatic_rollback" if automatic else "rolled_back",
                    reason=reason.strip(),
                    created_at=now(),
                )
            )
            return {
                "rolled_back": current.id,
                "active": record(prior),
                "reason": reason.strip(),
                "affected_strategy_ids": [current.id],
            }

    def monitor(self):
        """按锁定护栏复查；关键失败由程序立即回退，不接受模型自报评分。"""
        current = self.active()
        if current["id"] == BASELINE_ID:
            return {"status": "baseline", "active": current, "affected_strategy_ids": []}
        with Session(self.repository.engine) as session:
            experiment = session.scalar(
                select(StrategyExperiment)
                .where(StrategyExperiment.strategy_id == current["id"])
                .order_by(StrategyExperiment.created_at.desc())
                .limit(1)
            )
            baseline_config = experiment.contract.get("baseline_config", {"aliases": {}})
        metrics = self._run(current["config"]["aliases"], CASES, baseline_config["aliases"])
        failed = (
            not metrics["source_version_guard"]
            or metrics["critical_regressions"]
            or not metrics["budget_guard"]
        )
        with Session(self.repository.engine) as session, session.begin():
            event = StrategyExperiment(
                id=uuid4().hex,
                strategy_id=current["id"],
                suite_version=SUITE_VERSION,
                contract={**CONTRACT, "phase": "guard_monitor", "baseline_config": baseline_config},
                metrics=metrics,
                status="rejected" if failed else "accepted",
                created_at=now(),
            )
            session.add(event)
            session.flush()
            evaluation = record(event)
        if failed:
            rollback = self.rollback(
                "固定检索护栏失败，程序自动回退。",
                automatic=True,
                expected_identity=current["id"],
            )
            return {"status": "rolled_back", "evaluation": evaluation, **rollback}
        return {"status": "passed", "evaluation": evaluation, "affected_strategy_ids": []}
