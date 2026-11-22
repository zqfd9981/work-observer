"""Literal phrase ranking; no token model, embedding, or probability estimate."""

from math import log1p

from work_observer.text_match import match_text


def query_groups(terms, expand):
    """Count overlapping configured alias sets as one query concept."""
    groups = []
    for term in terms:
        variants = {match_text(value) for value in expand([term])}
        # An alias set may bridge more than one earlier group.
        remaining = []
        for group in groups:
            if variants & group:
                variants |= group
            else:
                remaining.append(group)
        groups = [*remaining, variants]
    return [sorted(group) for group in groups]


def rank_passages(evidence, groups):
    """Score the eligible passage corpus before limits, then diversify sources.

    BM25-style phrase frequencies saturate repetitions. Length uses normalized
    Unicode characters, not a language tokenizer; aliases use their maximum
    frequency so listing synonyms cannot multiply one concept's contribution.
    Statistics are local to this call and never change literal job counts.
    """
    if not evidence:
        return []
    lengths, frequencies = [], []
    for item in evidence:
        text = match_text(item["quote"])
        lengths.append(max(1, len(text)))
        frequencies.append([max((text.count(t) for t in group), default=0) for group in groups])
    count = len(evidence)
    average = sum(lengths) / count
    weights = [
        log1p((count - frequency + 0.5) / (frequency + 0.5))
        for frequency in (sum(row[i] > 0 for row in frequencies) for i in range(len(groups)))
    ]
    # Whole phrases repeat less informatively than tokenizer terms: use a low
    # saturation constant so a repeated generic label has little extra weight.
    k1 = 0.6
    for item, length, row in zip(evidence, lengths, frequencies, strict=True):
        norm = k1 * (0.25 + 0.75 * length / average)
        score = sum(
            weight * hits * (k1 + 1) / (hits + norm)
            for weight, hits in zip(weights, row, strict=True)
        )
        item["retrieval"].update(
            score=round(score, 8),
            ranking_method="phrase_bm25",
            matched_query_groups=sum(hits > 0 for hits in row),
            query_group_count=len(groups),
        )
    ranked = sorted(evidence, key=lambda item: (-item["retrieval"]["score"], item["id"]))
    seen, diversified = set(), []
    for item in ranked:
        source = (item.get("job_id"), item.get("public_document_id"))
        diversified.append((source in seen, item))
        seen.add(source)
    return [item for _, item in sorted(diversified, key=lambda row: row[0])]
