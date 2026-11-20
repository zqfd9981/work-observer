"""Arrange source-bound follow-ups after saving an answer; never reopen its execution."""

from work_observer.collection.service import error_code


def arrange_proposals(service, identity, source_step, result):
    proposals = result.get("investigation_proposals", [])[:2]
    if not proposals:
        return
    outcomes = []
    for index, proposal in enumerate(proposals):
        outcome = {"proposal_index": index}
        try:
            current = service.get(identity)
            if current["state"] == "invalidated":
                return
            if current["scope_version"] != source_step["scope_version"]:
                outcomes.append({**outcome, "state": "deferred", "reason": "scope_changed"})
                continue
            question = proposal["question"].strip()
            key = f"{result['run_id']}:proposal:{index}"
            existing = next(
                (
                    step
                    for step in current["steps"]
                    if step.get("key") == key
                    or (
                        step["scope_version"] == current["scope_version"]
                        and step["question"] == question
                    )
                ),
                None,
            )
            if existing:
                outcomes.append({**outcome, "state": "existing", "step_id": existing["id"]})
                continue
            used = service.usage(current)
            pending = [
                step
                for step in current["steps"]
                if step["state"] == "queued" and not step["run_id"] and not step["offline"]
            ]
            calls = min(
                8,
                current["budget"]["max_calls"]
                - used["reserved_calls"]
                - sum(step["max_calls"] for step in pending),
            )
            seconds = min(
                120,
                current["budget"]["max_seconds"]
                - used["reserved_seconds"]
                - sum(step["timeout"] for step in pending),
            )
            reason = (
                "round_limit"
                if len(current["steps"]) >= current["budget"]["max_rounds"]
                else "call_budget"
                if calls < 3
                else "time_budget"
                if seconds < 30
                else None
            )
            if reason:
                outcomes.append({**outcome, "state": "deferred", "reason": reason})
                continue
            updated = service.add(
                identity,
                question,
                revision=current["revision"],
                kind=proposal["kind"],
                max_calls=calls,
                timeout=seconds,
                approach=source_step.get("approach", "standard"),
                coverage_mode=source_step.get("coverage_mode", "all"),
                reply_to_step_id=source_step["id"],
                origin="agent",
                completion=proposal["completion"],
                evidence_needed=proposal["evidence_needed"],
                key=key,
            )
            planned = next(step for step in updated["steps"] if step.get("key") == key)
            outcomes.append({**outcome, "state": "queued", "step_id": planned["id"]})
        except Exception as exc:
            outcomes.append({**outcome, "state": "deferred", "reason": error_code(exc)})
    with service.store.lock, service.store.db:
        current = service.get(identity)
        if current["state"] == "invalidated":
            return
        source = next(step for step in current["steps"] if step["id"] == source_step["id"])
        source["proposal_outcomes"] = outcomes
        service._write(current)
