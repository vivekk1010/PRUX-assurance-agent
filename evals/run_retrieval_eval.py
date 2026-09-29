"""Offline retrieval evaluation using the deterministic hashing embedder."""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from rag.ingest import build_index
from rag.retriever import Retriever

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GOLD = Path(__file__).with_name("retrieval_gold.json")


def case_metrics(retrieved: list[str], relevant: list[str], k: int) -> dict[str, float]:
    top = retrieved[:k]
    relevant_set = set(relevant)
    matched = relevant_set.intersection(top)
    reciprocal_rank = next(
        (1.0 / rank for rank, chunk_id in enumerate(top, 1) if chunk_id in relevant_set),
        0.0,
    )
    return {
        f"hit@{k}": float(bool(matched)),
        f"recall@{k}": len(matched) / len(relevant_set) if relevant_set else 1.0,
        "mrr": reciprocal_rank,
    }


def evaluate(
    gold_path: Path = DEFAULT_GOLD,
    *,
    index_dir: Path | None = None,
    root: Path = ROOT,
    k: int | None = None,
) -> dict[str, Any]:
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    cutoff = int(k or gold.get("k", 3))

    temporary: tempfile.TemporaryDirectory[str] | None = None
    if index_dir is None:
        temporary = tempfile.TemporaryDirectory(prefix="prux-retrieval-eval-")
        index_dir = Path(temporary.name)
        build_index(
            root / "stories",
            root / "knowledge_base",
            index_dir,
            None,
            "hashing",
            "",
        )

    try:
        retriever = Retriever(index_dir)
        results = []
        for case in gold["cases"]:
            hits = retriever.search(
                case["query"],
                k=cutoff,
                filters=case.get("filters"),
                mode=case.get("mode", "hybrid"),
                min_score=case.get("min_score"),
            )
            retrieved = [hit.chunk.id for hit in hits]
            metrics = case_metrics(retrieved, case["relevant"], cutoff)
            results.append({
                "id": case["id"],
                "query": case["query"],
                "relevant": case["relevant"],
                "retrieved": retrieved,
                **metrics,
            })

        metric_names = [f"hit@{cutoff}", f"recall@{cutoff}", "mrr"]
        aggregate = {
            metric: sum(result[metric] for result in results) / len(results)
            if results else 0.0
            for metric in metric_names
        }
        return {
            "k": cutoff,
            "case_count": len(results),
            "metrics": aggregate,
            "cases": results,
            "minimum_hit_at_k": float(gold.get("minimum_hit_at_k", 0.0)),
        }
    finally:
        if temporary is not None:
            temporary.cleanup()


run_evaluation = evaluate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--index-dir", type=Path)
    parser.add_argument("-k", type=int)
    parser.add_argument("--json", action="store_true", help="Print the complete result as JSON")
    args = parser.parse_args()

    result = evaluate(args.gold, index_dir=args.index_dir, k=args.k)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        hit_name = f"hit@{result['k']}"
        recall_name = f"recall@{result['k']}"
        for case in result["cases"]:
            print(
                f"{case['id']}: hit={case[hit_name]:.0f} "
                f"recall={case[recall_name]:.3f} mrr={case['mrr']:.3f}"
            )
        metrics = result["metrics"]
        print(
            f"aggregate: Hit@{result['k']}={metrics[hit_name]:.3f} "
            f"Recall@{result['k']}={metrics[recall_name]:.3f} "
            f"MRR={metrics['mrr']:.3f}"
        )
    return int(
        result["metrics"][f"hit@{result['k']}"] < result["minimum_hit_at_k"]
    )


if __name__ == "__main__":
    raise SystemExit(main())
