#
#  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

"""Safe query decomposition and rank-based retrieval fusion for regular chat.

This module deliberately contains no product names, document types, or metadata
rules. Decomposition only rewrites an information need into independently
searchable questions. The caller keeps its existing document scope and invokes
the ordinary retriever for every question.
"""

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_MAX_QUERY_CHARS = 240
_DEFAULT_MAX_SUBQUESTIONS = 3
_DEFAULT_PLANNER_TIMEOUT_SECONDS = 15.0
_RRF_K = 60

_DECOMPOSITION_PROMPT = """You are a retrieval query planner.
Decide whether the user's information need must be searched as multiple independent
questions. Split only when separate subjects, objects, documents, time periods, or
requested aspects each need their own evidence. A normal single-focus question must
not be split.

Rules:
1. Do not answer the question and do not add facts that are absent from it.
2. Every sub-question must be self-contained and directly searchable in a document
   corpus. Repeat the necessary subject and constraints instead of using pronouns.
3. Preserve identifiers, model names, numbers, units, and limiting conditions exactly.
4. Do not perform terminology expansion or replace the user's words with guessed
   synonyms.
5. Produce at most {max_subquestions} sub-questions.
6. For a single-focus question, return an empty list.

Return JSON only:
{{"sub_questions": ["...", "..."]}}
"""


@dataclass(frozen=True)
class RetrievalTask:
    query: str
    is_original: bool = False


def _normalize_for_comparison(text: str) -> str:
    return re.sub(r"[\W_]+", "", text or "", flags=re.UNICODE).casefold()


def validate_subquestions(question: str, payload, max_subquestions: int = _DEFAULT_MAX_SUBQUESTIONS) -> list[RetrievalTask]:
    """Validate planner output; invalid or non-decomposed output means old-path fallback."""
    if not isinstance(payload, dict):
        return []
    raw = payload.get("sub_questions")
    if not isinstance(raw, list):
        return []

    original_key = _normalize_for_comparison(question)
    tasks = []
    seen = {original_key}
    for item in raw:
        if not isinstance(item, str):
            continue
        query = " ".join(item.split()).strip()
        key = _normalize_for_comparison(query)
        if not query or len(query) > _MAX_QUERY_CHARS or not key or key in seen:
            continue
        seen.add(key)
        tasks.append(RetrievalTask(query=query))
        if len(tasks) >= max(2, max_subquestions):
            break

    # One rewritten query is not decomposition. Keeping the original retrieval is
    # safer and avoids paying for two near-identical searches.
    return tasks if len(tasks) >= 2 else []


async def plan_retrieval_tasks(
    chat_mdl,
    question: str,
    max_subquestions: int = _DEFAULT_MAX_SUBQUESTIONS,
    timeout_seconds: float = _DEFAULT_PLANNER_TIMEOUT_SECONDS,
) -> list[RetrievalTask]:
    """Plan independent retrieval tasks, returning ``[]`` on every failure.

    An empty result is intentional: callers must continue through the unchanged
    single-query retrieval path. Decomposition can therefore improve recall but
    can never become a prerequisite for answering.
    """
    if not question or chat_mdl is None:
        return []
    max_subquestions = min(4, max(2, int(max_subquestions)))
    try:
        from rag.prompts.generator import gen_json

        result = await asyncio.wait_for(
            gen_json(
                _DECOMPOSITION_PROMPT.format(max_subquestions=max_subquestions),
                f"Question: {question}\nOutput:",
                chat_mdl,
                gen_conf={"temperature": 0.0},
                max_retry=2,
                raise_on_error=True,
            ),
            timeout=max(1.0, float(timeout_seconds)),
        )
        return validate_subquestions(question, result, max_subquestions)
    except Exception:  # Planner failure must not block retrieval.
        logger.warning("Query decomposition failed; using the original retrieval path", exc_info=True)
        return []


def _chunk_key(chunk: dict) -> tuple:
    if chunk.get("chunk_id"):
        return ("chunk_id", str(chunk["chunk_id"]))
    return (
        "content",
        str(chunk.get("doc_id") or ""),
        str(chunk.get("content_with_weight") or ""),
    )


def _document_id(chunk: dict) -> str:
    return str(chunk.get("doc_id") or "")


def _task_context(task: RetrievalTask) -> dict:
    return {"query": task.query, "is_original": task.is_original}


def _merge_task_contexts(target: dict, source: dict) -> None:
    contexts = target.setdefault("retrieval_tasks", [])
    for context in source.get("retrieval_tasks") or []:
        if context not in contexts:
            contexts.append(context)


def merge_task_results(task_results: list[dict], top_n: int, tasks: list[RetrievalTask]) -> dict:
    """Fuse independently ranked results with RRF and protected sub-question coverage.

    Similarity scores from different queries are not calibrated against each other,
    so they are never used for cross-query ordering. RRF consumes only local ranks.
    """
    if top_n <= 0 or not task_results or not tasks:
        return {"total": 0, "chunks": [], "doc_aggs": []}
    if len(tasks) != len(task_results):
        raise ValueError("tasks and task_results must have the same length")

    candidates = {}
    ranked_keys: list[list[tuple]] = []
    for task, result in zip(tasks, task_results):
        local_keys = []
        local_seen = set()
        for rank, raw_chunk in enumerate(result.get("chunks") or [], start=1):
            key = _chunk_key(raw_chunk)
            if key in local_seen:
                continue
            local_seen.add(key)
            local_keys.append(key)
            if key not in candidates:
                chunk = dict(raw_chunk)
                chunk["retrieval_tasks"] = [_task_context(task)]
                candidates[key] = {"chunk": chunk, "rrf": 0.0, "best_rank": rank}
            else:
                _merge_task_contexts(candidates[key]["chunk"], {"retrieval_tasks": [_task_context(task)]})
                candidates[key]["best_rank"] = min(candidates[key]["best_rank"], rank)
            candidates[key]["rrf"] += 1.0 / (_RRF_K + rank)
        ranked_keys.append(local_keys)

    selected_keys = []
    selected_set = set()
    selected_doc_ids = set()

    def select(key) -> bool:
        if key in selected_set or key not in candidates or len(selected_keys) >= top_n:
            return False
        selected_set.add(key)
        selected_keys.append(key)
        doc_id = _document_id(candidates[key]["chunk"])
        if doc_id:
            selected_doc_ids.add(doc_id)
        return True

    # Protect one result per planned sub-question. Prefer a document that has not
    # yet been represented, then fall back to another chunk from an already
    # selected document when the branch has no alternative document.
    # The original-query safety search participates only in the fill phase.
    for task, keys in zip(tasks, ranked_keys):
        if task.is_original:
            continue
        unseen_document_key = next(
            (
                key
                for key in keys
                if key not in selected_set
                and _document_id(candidates[key]["chunk"])
                and _document_id(candidates[key]["chunk"]) not in selected_doc_ids
            ),
            None,
        )
        if unseen_document_key is not None and select(unseen_document_key):
            continue
        next((key for key in keys if select(key)), None)

    fused_keys = sorted(
        candidates,
        key=lambda key: (-candidates[key]["rrf"], candidates[key]["best_rank"], str(key)),
    )
    for key in fused_keys:
        if len(selected_keys) >= top_n:
            break
        select(key)

    selected = []
    for key in selected_keys:
        chunk = candidates[key]["chunk"]
        chunk["fusion_score"] = candidates[key]["rrf"]
        selected.append(chunk)

    doc_aggs = {}
    for chunk in selected:
        doc_name = str(chunk.get("docnm_kwd") or "")
        doc_id = _document_id(chunk)
        aggregation_key = ("doc_id", doc_id) if doc_id else ("doc_name", doc_name)
        if aggregation_key not in doc_aggs:
            doc_aggs[aggregation_key] = {"doc_name": doc_name, "doc_id": doc_id, "count": 0}
        doc_aggs[aggregation_key]["count"] += 1

    return {
        "total": len(selected),
        "chunks": selected,
        "doc_aggs": list(doc_aggs.values()),
    }


async def retrieve_and_merge_tasks(
    question: str,
    sub_tasks: list[RetrievalTask],
    top_n: int,
    rerank_candidates_count: int,
    retrieve_task: Callable[[RetrievalTask, int], Awaitable[dict]],
) -> dict:
    """Retrieve sub-questions plus the original safety query, then rank-fuse them."""
    if not sub_tasks or top_n <= 0:
        return {"total": 0, "chunks": [], "doc_aggs": []}

    tasks = list(sub_tasks) + [RetrievalTask(query=question, is_original=True)]
    semaphore = asyncio.Semaphore(min(4, len(tasks)))

    async def bounded_retrieve(task: RetrievalTask):
        # Sub-questions need enough local candidates to survive de-duplication; the
        # original query retains the user's configured Top N as a complete safety net.
        task_top_n = top_n if task.is_original else min(top_n, 8)
        task_top_n = min(max(1, rerank_candidates_count), max(1, task_top_n))
        async with semaphore:
            try:
                return await retrieve_task(task, task_top_n)
            except Exception:  # One failed branch must not cancel siblings.
                logger.warning("Retrieval task failed: %r", task.query, exc_info=True)
                return {"total": 0, "chunks": [], "doc_aggs": []}

    results = await asyncio.gather(*(bounded_retrieve(task) for task in tasks))
    return merge_task_results(results, top_n, tasks)
