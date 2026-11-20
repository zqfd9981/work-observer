"""Locate prior reasoning by its actual content; do not treat matching as factual support."""

from work_observer.memory.service import _tokens

MAP_FIELDS = {
    "work_types": ("name", "problem", "tasks", "deliverables", "boundary", "next_check"),
    "ability_relations": ("task", "ability", "rationale", "transfer_limit"),
    "work_relations": ("source_text", "target_text", "rationale", "transfer_limit"),
    "comparisons": ("common_ground", "differences", "transfer_conditions", "unknowns"),
}


def map_content(result):
    value = result.get("work_map") or {}
    for key, fields in MAP_FIELDS.items():
        for row in value.get(key, []):
            text = []
            for field in fields:
                content = row.get(field, "")
                text.extend(content if isinstance(content, list) else [content])
            yield row, " ".join(text)


def finding_score(query, question, result):
    text = [question, *result.get("gaps", [])]
    text.extend(claim["text"] for claim in result.get("claims", []))
    text.extend(content for _, content in map_content(result))
    text.extend((result.get("work_map") or {}).get("unknowns", []))
    return len(query & _tokens(" ".join(text)))


def ranked_claims(result, query):
    """Carry both ends of a relevant saved relation or comparison ahead of unrelated claims."""
    scores = {
        index: len(query & _tokens(claim["text"]))
        for index, claim in enumerate(result.get("claims", []))
    }
    for row, text in map_content(result):
        score = len(query & _tokens(text))
        for index in row.get("claim_indices", []):
            if index in scores:
                scores[index] = max(scores[index], score)
    return sorted(
        enumerate(result.get("claims", [])),
        key=lambda pair: (
            -scores[pair[0]],
            pair[1].get("requirement") not in {"required", "preferred"},
            pair[0],
        ),
    )
