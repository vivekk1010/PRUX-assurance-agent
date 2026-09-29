import json
import shutil
from pathlib import Path

from agent.config import get_settings
from evals.run_retrieval_eval import evaluate
from rag.freshness import check_freshness
from rag.ingest import build_index, chunk_markdown
from rag.retriever import FilterSpec, Retriever


def _index(tmp_path: Path):
    settings = get_settings()
    return build_index(
        settings.stories_dir,
        settings.knowledge_dir,
        tmp_path,
        None,
        "hashing",
        "",
    )


def test_chunks_have_stable_metadata_and_rule_ids():
    path = get_settings().knowledge_dir / "business_rules.md"
    first = chunk_markdown(path)
    second = chunk_markdown(path)
    reading = next(chunk for chunk in first if chunk.meta.get("rule_id") == "BR-META-02")
    assert reading.meta["doc_type"] == "business_rule"
    assert reading.meta["source_path"] == "knowledge_base/business_rules.md"
    assert reading.meta["content_hash"].startswith("sha256:")
    assert [(chunk.id, chunk.meta["content_hash"]) for chunk in first] == [
        (chunk.id, chunk.meta["content_hash"]) for chunk in second
    ]


def test_hybrid_search_filters_threshold_and_exact_lookup(tmp_path):
    store = _index(tmp_path)
    retriever = Retriever(tmp_path)

    assert retriever.search("BR-META-02", k=1)[0].chunk.meta["rule_id"] == "BR-META-02"
    assert retriever.search_exact_rules(["BR-META-02", "BR-NOT-THERE"])[0].score == 1.0
    assert retriever.lookup_rule("br-meta-02").id == "business_rules#br-meta-02-reading-time"

    filtered = retriever.search(
        "reading time",
        k=10,
        filters=FilterSpec(doc_types={"business_rule"}),
    )
    assert filtered
    assert {hit.chunk.meta["doc_type"] for hit in filtered} == {"business_rule"}
    assert retriever.search("reading time", k=3, min_score=1.01) == []

    # Original positional API remains valid.
    assert retriever.search("reading time", 3, "knowledge_base")
    assert any(chunk.meta["doc_type"] == "flow_test" for chunk in store.chunks)


def test_manifest_detects_source_changes(tmp_path):
    settings = get_settings()
    stories = tmp_path / "stories"
    knowledge = tmp_path / "knowledge_base"
    shutil.copytree(settings.stories_dir, stories)
    shutil.copytree(settings.knowledge_dir, knowledge)
    index = tmp_path / "index"

    store = build_index(stories, knowledge, index, None, "hashing", "")
    assert store.manifest["schema_version"] == 2
    assert store.manifest["chunk_count"] == len(store.chunks)
    assert check_freshness(index, stories, knowledge).fresh

    business_rules = knowledge / "business_rules.md"
    business_rules.write_text(
        business_rules.read_text(encoding="utf-8") + "\n", encoding="utf-8"
    )
    report = check_freshness(index, stories, knowledge)
    assert report.stale
    assert "knowledge_base/business_rules.md" in report.reasons[0]


def test_offline_retrieval_gold(tmp_path):
    _index(tmp_path)
    result = evaluate(index_dir=tmp_path)
    assert result["case_count"] >= 5
    assert result["metrics"]["hit@3"] == 1.0
    assert result["metrics"]["recall@3"] == 1.0
    assert result["metrics"]["mrr"] == 1.0


def test_manifest_and_chunks_are_json_portable(tmp_path):
    _index(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    chunks = json.loads((tmp_path / "chunks.json").read_text(encoding="utf-8"))
    assert chunks["schema_version"] == 2
    assert manifest["embedder"] == "hashing-512"
    assert all("content_hash" in chunk["meta"] for chunk in chunks["chunks"])
