"""
Bedrock requirement profiling — compact tiered extraction for large docs.

All MD/JSON docs use deterministic tier extract → batched Bedrock labelling
(story-aggregated primary items by default). Secondary tiers are regex-labelled
when excluded from agent extraction.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from ..agent.bedrock_agent import profile_requirement_items_with_agent
from ..agent.cache import (
    fingerprint_paths,
    fingerprint_strings,
    load_cached_profiles,
    save_cached_profiles,
)
from ..agent.config import (
    requirement_force_compact,
    requirement_label_batch_char_limit,
    requirement_label_batch_size,
    requirement_label_concurrency,
)
from ..agent.context import get_source_fingerprint
from ..agent.schemas import RequirementItemCompact, ScenarioProfileOut
from .extract import (
    RequirementItem,
    extract_items_for_agent,
    extract_items_from_doc,
)
from .profile import RequirementProfile, _item_to_requirement_profile


def _is_md_doc(doc: dict) -> bool:
    return str(doc.get("_source_file", "")).lower().endswith(".md")


def _doc_needs_compact(doc: dict) -> bool:
    """Large docs, non-MD JSON, or force-compact always use batched labelling."""
    if requirement_force_compact():
        return True
    if not _is_md_doc(doc):
        return True
    from ..agent.config import (
        requirement_compact_byte_limit,
        requirement_compact_item_limit,
        requirement_compact_line_limit,
    )
    from .extract import doc_byte_count, doc_line_count

    items = extract_items_for_agent(doc)
    return (
        doc_line_count(doc) > requirement_compact_line_limit()
        or doc_byte_count(doc) > requirement_compact_byte_limit()
        or len(items) > requirement_compact_item_limit()
    )


def _merge_agent_labels(
    items: List[RequirementItem],
    labels: Dict[str, ScenarioProfileOut],
) -> List[RequirementProfile]:
    return [_item_to_requirement_profile(item, labels.get(item.item_id)) for item in items]


def _items_cache_key(items: List[RequirementItem]) -> str:
    payload = [f"{i.item_id}|{i.verbatim_text}" for i in sorted(items, key=lambda x: x.item_id)]
    return fingerprint_strings(payload)


def _compact_item_for_labelling(item: RequirementItem) -> RequirementItemCompact:
    text = item.verbatim_text
    max_chars = 1200
    if len(text) > max_chars:
        text = text[:max_chars] + " …"
    return RequirementItemCompact(
        item_id=item.item_id,
        unit_id=item.unit_id,
        source_file=item.doc_file,
        source_section=item.source_section,
        verbatim_text=text,
    )


def _chunk_items_for_labelling(items: List[RequirementItem]) -> List[List[RequirementItem]]:
    max_items = requirement_label_batch_size()
    max_chars = requirement_label_batch_char_limit()
    chunks: List[List[RequirementItem]] = []
    current: List[RequirementItem] = []
    current_chars = 0
    for item in items:
        item_chars = len(item.verbatim_text)
        if current and (
            len(current) >= max_items
            or current_chars + item_chars > max_chars
        ):
            chunks.append(current)
            current = []
            current_chars = 0
        current.append(item)
        current_chars += item_chars
    if current:
        chunks.append(current)
    return chunks


def _label_one_batch(chunk: List[RequirementItem]) -> Dict[str, ScenarioProfileOut]:
    compact = [_compact_item_for_labelling(item) for item in chunk]
    batch = profile_requirement_items_with_agent(compact)
    return {profile.scenario_id: profile for profile in batch.profiles}


def _label_items_batched(
    items: List[RequirementItem],
    *,
    cache_fingerprint: Optional[str] = None,
) -> List[RequirementProfile]:
    if not items:
        return []

    fp = cache_fingerprint or _items_cache_key(items)
    cached = load_cached_profiles("requirements_compact", fp)
    if cached is not None:
        labels = {k: ScenarioProfileOut.model_validate(v) for k, v in cached.items()}
        return _merge_agent_labels(items, labels)

    batch_size = requirement_label_batch_size()
    chunks = _chunk_items_for_labelling(items)
    all_labels: Dict[str, ScenarioProfileOut] = {}
    workers = min(requirement_label_concurrency(), len(chunks))

    if workers <= 1:
        for chunk in chunks:
            all_labels.update(_label_one_batch(chunk))
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_label_one_batch, chunk) for chunk in chunks]
            for future in as_completed(futures):
                all_labels.update(future.result())

    save_cached_profiles(
        "requirements_compact",
        fp,
        {k: v.model_dump() for k, v in all_labels.items()},
    )
    return _merge_agent_labels(items, all_labels)


def profile_requirements_agent(
    docs: List[dict],
    *,
    source: Optional[str | Path] = None,
) -> List[RequirementProfile]:
    """Profile requirements via Bedrock with compact aggregated extraction."""
    bedrock_items: List[RequirementItem] = []

    folder_fp = get_source_fingerprint("requirements")
    if not folder_fp and source is not None:
        from ..agent.cache import collect_paths_from_source
        folder_fp = fingerprint_paths(collect_paths_from_source(source))

    for doc in docs:
        bedrock_items.extend(extract_items_for_agent(doc))

    if not bedrock_items:
        return []

    return _label_items_batched(bedrock_items, cache_fingerprint=folder_fp)


def requirement_profiling_strategy(docs: Iterable[dict]) -> str:
    """Human-readable strategy label for integrity report."""
    doc_list = list(docs)
    if not doc_list:
        return "none"
    agent_items = sum(len(extract_items_for_agent(d)) for d in doc_list)
    full_items = sum(len(extract_items_from_doc(d)) for d in doc_list)
    parts = ["compact_aggregated_primary"]
    if requirement_force_compact():
        parts.append("force_compact")
    if agent_items != full_items:
        parts.append(f"bedrock_{agent_items}_of_{full_items}")
    else:
        parts.append(f"items_{agent_items}")
    return "_".join(parts)
