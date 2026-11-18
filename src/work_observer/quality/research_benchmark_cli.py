"""业务研究评测独立本机CLI；不执行模型或修改默认方法。"""

import argparse
import json
from pathlib import Path

from work_observer.quality.research_benchmark import ResearchBenchmarkService
from work_observer.quality.service import read_json, write_json
from work_observer.research.store import ResearchStore
from work_observer.storage.repository import Repository


def main():
    parser = argparse.ArgumentParser(
        description="锁定业务问题、登记权威研究结果、盲审及配对；无网络/模型"
    )
    parser.add_argument("--db", type=Path, default=Path("data/app.db"))
    parser.add_argument("--checkpoints", type=Path)
    commands = parser.add_subparsers(dest="action", required=True)
    create = commands.add_parser("preregister")
    create.add_argument("protocol", type=Path)
    listing = commands.add_parser("overview")
    listing.add_argument("--id")
    tasks = commands.add_parser("development-tasks")
    tasks.add_argument("id")
    for action in ("open", "seal", "close", "report"):
        command = commands.add_parser(action)
        command.add_argument("id")
        command.add_argument("phase", choices=["development", "holdout"])
        if action == "seal":
            command.add_argument("--record-missing", action="store_true")
    register = commands.add_parser("register")
    register.add_argument("id")
    register.add_argument("task_id")
    register.add_argument("arm", choices=["baseline", "candidate"])
    register.add_argument("source_id")
    packet = commands.add_parser("packet")
    packet.add_argument("id")
    packet.add_argument("packet_id")
    packet.add_argument("--output", type=Path)
    review = commands.add_parser("review")
    review.add_argument("id")
    review.add_argument("packet_id")
    review.add_argument("review", type=Path)
    args = parser.parse_args()
    repo = Repository(args.db)
    store = ResearchStore(
        args.checkpoints or args.db.parent / "checkpoints.db", str(args.db.resolve())
    )
    try:
        service = ResearchBenchmarkService(store, repo)
        if args.action == "preregister":
            result = service.preregister(**read_json(args.protocol))
        elif args.action == "overview":
            result = service.overview(args.id)
        elif args.action == "development-tasks":
            result = service.development_tasks(args.id)
        elif args.action == "open":
            result = service.open_phase(args.id, args.phase)
        elif args.action == "register":
            result = service.register(args.id, args.task_id, args.arm, args.source_id)
        elif args.action == "seal":
            result = service.seal_phase(args.id, args.phase, record_missing=args.record_missing)
        elif args.action == "packet":
            result = service.blind_packet(args.id, args.packet_id)
            if args.output:
                write_json(args.output, result)
                result = {
                    "packet_id": args.packet_id,
                    "written": str(args.output.resolve()),
                    "notice": "显式导出副本由操作人独立保管；不要交给可识别arm的审核者。",
                }
        elif args.action == "review":
            result = service.submit_review(args.id, args.packet_id, read_json(args.review))
        elif args.action == "close":
            result = service.close_phase(args.id, args.phase)
        else:
            result = service.paired_report(args.id, args.phase)
        print(json.dumps(result, ensure_ascii=True, indent=2))
    finally:
        store.close()
        repo.close()


if __name__ == "__main__":
    main()
