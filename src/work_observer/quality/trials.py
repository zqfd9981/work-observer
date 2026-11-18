"""有限本地检索试用CLI，与页面共用服务，不启动模型/网络。"""

import argparse
import json
from pathlib import Path

from work_observer.quality.releases import LocalRetrievalTrialService
from work_observer.research.store import ResearchStore
from work_observer.storage.repository import Repository


def main():
    parser = argparse.ArgumentParser(description="有限本地检索试用；默认检索保持")
    parser.add_argument("--db", type=Path, default=Path("data/app.db"))
    command = parser.add_subparsers(dest="action", required=True)
    command.add_parser("list")
    shadow = command.add_parser("shadow")
    shadow.add_argument("bundle_id")
    shadow.add_argument("--job", action="append", required=True)
    shadow.add_argument("--term", action="append", required=True)
    shadow.add_argument("--max-uses", type=int, default=10)
    shadow.add_argument("--expires-hours", type=int, default=4)
    shadow.add_argument("--source-run-id")
    review = command.add_parser("review")
    review.add_argument("id")
    review.add_argument("--reviewer", required=True)
    review.add_argument("--decision", choices=["approve", "reject", "pending"], default="pending")
    review.add_argument("--reason", required=True)
    review.add_argument("--reviewer-kind", choices=["human", "agent_assisted"], default="human")
    review.add_argument("--independent-labels-confirmed", action="store_true")
    search = command.add_parser("search")
    search.add_argument("id")
    search.add_argument("--term", action="append", required=True)
    search.add_argument("--request-key", required=True)
    rollback = command.add_parser("rollback")
    rollback.add_argument("id")
    rollback.add_argument("--reason", required=True)
    feedback = command.add_parser("feedback")
    feedback.add_argument("id")
    feedback.add_argument("--request-key", required=True)
    feedback.add_argument("--rating", choices=["pass", "fail", "unknown"], default="unknown")
    feedback.add_argument("--note", required=True)
    feedback.add_argument("--reviewer-kind", choices=["human", "agent_assisted"], default="human")
    args = parser.parse_args()
    repo = Repository(args.db)
    store = ResearchStore(args.db.parent / "checkpoints.db", str(args.db.resolve()))
    try:
        svc = LocalRetrievalTrialService(store, repo)
        if args.action == "list":
            result = {"bundles": svc.bundles(), "trials": svc.list()}
        elif args.action == "shadow":
            result = svc.shadow(
                args.bundle_id,
                args.job,
                args.term,
                max_uses=args.max_uses,
                expires_hours=args.expires_hours,
                source_run_id=args.source_run_id,
            )
        elif args.action == "review":
            result = svc.review(
                args.id,
                args.reviewer,
                args.decision,
                args.reason,
                reviewer_kind=args.reviewer_kind,
                labels_independent_confirmed=args.independent_labels_confirmed,
            )
        elif args.action == "search":
            result = svc.search(args.id, args.term, request_key=args.request_key)
        elif args.action == "rollback":
            result = svc.rollback(args.id, args.reason)
        else:
            result = svc.feedback(
                args.id, args.request_key, args.rating, args.note, reviewer_kind=args.reviewer_kind
            )
        print(json.dumps(result, ensure_ascii=True, indent=2))
    finally:
        store.close()
        repo.close()


if __name__ == "__main__":
    main()
