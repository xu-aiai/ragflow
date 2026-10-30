import pytest

from common.retrieval_tasks import RetrievalTask, merge_task_results, retrieve_and_merge_tasks, validate_subquestions


def _chunk(chunk_id, similarity, doc_name, doc_id=None):
    return {
        "chunk_id": chunk_id,
        "similarity": similarity,
        "doc_id": doc_id or f"doc-{doc_name}",
        "docnm_kwd": doc_name,
        "content_with_weight": chunk_id,
    }


def test_validates_generic_subquestions_without_business_rules():
    tasks = validate_subquestions(
        "Compare A and B maintenance intervals",
        {"sub_questions": ["What is A's maintenance interval?", "What is B's maintenance interval?"]},
    )

    assert tasks == [
        RetrievalTask(query="What is A's maintenance interval?"),
        RetrievalTask(query="What is B's maintenance interval?"),
    ]


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"sub_questions": "not-a-list"},
        {"sub_questions": ["only one rewrite"]},
        {"sub_questions": ["same question", "same question"]},
    ],
)
def test_invalid_or_non_decomposed_plans_fall_back(payload):
    assert validate_subquestions("original question", payload) == []


def test_drops_original_duplicates_and_caps_task_count():
    tasks = validate_subquestions(
        "original question",
        {
            "sub_questions": [
                "Original question!",
                "first aspect",
                "second aspect",
                "third aspect",
                "fourth aspect",
            ]
        },
        max_subquestions=3,
    )

    assert [task.query for task in tasks] == ["first aspect", "second aspect", "third aspect"]


def test_merge_guarantees_one_distinct_chunk_per_subquestion():
    tasks = [
        RetrievalTask(query="question a"),
        RetrievalTask(query="question b"),
        RetrievalTask(query="original", is_original=True),
    ]
    first = {"chunks": [_chunk(f"a{i}", 1.0 - i / 100, "manual-a") for i in range(5)]}
    # Deliberately much lower raw similarities: cross-query selection must still
    # preserve this branch instead of treating those scores as calibrated.
    second = {"chunks": [_chunk(f"b{i}", 0.1 - i / 100, "manual-b") for i in range(5)]}
    original = {"chunks": [_chunk(f"o{i}", 0.99 - i / 100, "manual-o") for i in range(5)]}

    merged = merge_task_results([first, second, original], top_n=4, tasks=tasks)

    assert merged["chunks"][0]["chunk_id"] == "a0"
    assert merged["chunks"][1]["chunk_id"] == "b0"
    assert {chunk["docnm_kwd"] for chunk in merged["chunks"]} >= {"manual-a", "manual-b"}


def test_rrf_rewards_chunks_supported_by_multiple_queries():
    tasks = [
        RetrievalTask(query="question a"),
        RetrievalTask(query="question b"),
        RetrievalTask(query="original", is_original=True),
    ]
    shared = _chunk("shared", 0.2, "shared-manual")
    first = {"chunks": [_chunk("a0", 0.9, "manual-a"), shared]}
    second = {"chunks": [_chunk("b0", 0.8, "manual-b"), shared]}
    original = {"chunks": [shared, _chunk("o1", 0.99, "manual-o")]}

    merged = merge_task_results([first, second, original], top_n=3, tasks=tasks)

    assert [chunk["chunk_id"] for chunk in merged["chunks"]] == ["a0", "b0", "shared"]
    shared_contexts = merged["chunks"][2]["retrieval_tasks"]
    assert {item["query"] for item in shared_contexts} == {"question a", "question b", "original"}


def test_merge_deduplicates_shared_coverage_and_uses_next_distinct_chunk():
    tasks = [RetrievalTask(query="question a"), RetrievalTask(query="question b")]
    shared = _chunk("shared", 0.9, "shared-manual")
    first = {"chunks": [shared, _chunk("a1", 0.8, "manual-a")]}
    second = {"chunks": [shared, _chunk("b1", 0.7, "manual-b")]}

    merged = merge_task_results([first, second], top_n=2, tasks=tasks)

    assert [chunk["chunk_id"] for chunk in merged["chunks"]] == ["shared", "b1"]


def test_subquestion_coverage_prefers_an_unseen_document():
    tasks = [RetrievalTask(query="question a"), RetrievalTask(query="question b")]
    first = {"chunks": [_chunk("a0", 0.9, "manual-a", "doc-a")]}
    second = {
        "chunks": [
            _chunk("a1", 0.95, "manual-a", "doc-a"),
            _chunk("b0", 0.8, "manual-b", "doc-b"),
        ]
    }

    merged = merge_task_results([first, second], top_n=2, tasks=tasks)

    assert [chunk["chunk_id"] for chunk in merged["chunks"]] == ["a0", "b0"]


def test_same_filename_documents_are_aggregated_by_document_id():
    tasks = [RetrievalTask(query="question a"), RetrievalTask(query="question b")]
    first = {"chunks": [_chunk("a0", 0.9, "manual.docx", "doc-a")]}
    second = {"chunks": [_chunk("b0", 0.8, "manual.docx", "doc-b")]}

    merged = merge_task_results([first, second], top_n=2, tasks=tasks)

    assert merged["doc_aggs"] == [
        {"doc_name": "manual.docx", "doc_id": "doc-a", "count": 1},
        {"doc_name": "manual.docx", "doc_id": "doc-b", "count": 1},
    ]


def test_fused_chunks_expose_rrf_score_separately_from_local_similarity():
    tasks = [RetrievalTask(query="question a"), RetrievalTask(query="question b")]
    shared = _chunk("shared", 0.2, "manual")

    merged = merge_task_results(
        [{"chunks": [shared]}, {"chunks": [shared]}],
        top_n=1,
        tasks=tasks,
    )

    assert merged["chunks"][0]["similarity"] == 0.2
    assert merged["chunks"][0]["fusion_score"] == pytest.approx(2 / 61)


@pytest.mark.asyncio
async def test_retrieves_subquestions_and_original_safety_query():
    sub_tasks = [RetrievalTask(query="question a"), RetrievalTask(query="question b")]
    calls = []

    async def fake_retrieve(task, task_top_n):
        calls.append((task.query, task.is_original, task_top_n))
        return {"chunks": [_chunk(task.query, 0.5, task.query)]}

    merged = await retrieve_and_merge_tasks(
        "original question",
        sub_tasks,
        top_n=12,
        rerank_candidates_count=64,
        retrieve_task=fake_retrieve,
    )

    assert set(calls) == {
        ("question a", False, 8),
        ("question b", False, 8),
        ("original question", True, 12),
    }
    assert merged["total"] == 3


@pytest.mark.asyncio
async def test_one_failed_branch_does_not_cancel_original_or_siblings():
    sub_tasks = [RetrievalTask(query="failing question"), RetrievalTask(query="working question")]

    async def fake_retrieve(task, _task_top_n):
        if task.query == "failing question":
            raise RuntimeError("temporary backend failure")
        return {"chunks": [_chunk(task.query, 0.5, task.query)]}

    merged = await retrieve_and_merge_tasks(
        "original question",
        sub_tasks,
        top_n=4,
        rerank_candidates_count=64,
        retrieve_task=fake_retrieve,
    )

    assert {chunk["chunk_id"] for chunk in merged["chunks"]} == {"working question", "original question"}
