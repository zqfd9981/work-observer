"""独立可操作命令；真实原文仅保存在用户指定的本机文件。"""

import argparse
import json

from work_observer.quality.service import (
    freeze,
    lock_suite,
    paired_evaluation,
    read_json,
    review_research,
    write_json,
)


def main():
    parser = argparse.ArgumentParser(description="Work Observer 真实研究质量基线")
    sub = parser.add_subparsers(dest="action", required=True)
    command = sub.add_parser("freeze", help="只读冻结资料库，目录必须不存在")
    command.add_argument("database")
    command.add_argument("directory")
    command = sub.add_parser("lock", help="锁定开发/验收问题及原文锚点")
    command.add_argument("directory")
    command.add_argument("cases")
    command.add_argument(
        "--label-origin", choices=["human", "agent_assisted"], default="agent_assisted"
    )
    command.add_argument("--reviewer")
    command.add_argument(
        "--independent-labels", action="store_true", help="人类明确声明标签独立于候选调参"
    )
    command = sub.add_parser("evaluate", help="同一冻结资料基线/候选配对，不启用策略")
    command.add_argument("directory")
    command.add_argument("aliases")
    command.add_argument("output")
    command.add_argument("--phase", choices=["development", "holdout"], default="development")
    command.add_argument("--baseline-aliases")
    command = sub.add_parser("review", help="提交逐项业务审核，不替代审核者判断")
    command.add_argument("directory")
    command.add_argument("case_id")
    command.add_argument("result")
    command.add_argument("judgments")
    command.add_argument("output")
    command.add_argument("--reviewer", required=True)
    command.add_argument("--reviewer-kind", choices=["human", "agent_assisted"], default="human")
    args = parser.parse_args()
    if args.action == "freeze":
        result = freeze(args.database, args.directory)
    elif args.action == "lock":
        suite = lock_suite(
            args.directory,
            read_json(args.cases),
            label_origin=args.label_origin,
            reviewer=args.reviewer,
            independent_labels=args.independent_labels,
        )
        result = {key: value for key, value in suite.items() if key != "cases"}
    elif args.action == "evaluate":
        result = paired_evaluation(
            args.directory,
            read_json(args.aliases),
            phase=args.phase,
            baseline_aliases=read_json(args.baseline_aliases) if args.baseline_aliases else None,
        )
        write_json(args.output, result)
        result = {key: value for key, value in result.items() if key != "cases"}
    else:
        result = review_research(
            args.directory,
            args.case_id,
            read_json(args.result),
            read_json(args.judgments),
            reviewer=args.reviewer,
            reviewer_kind=args.reviewer_kind,
        )
        write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
