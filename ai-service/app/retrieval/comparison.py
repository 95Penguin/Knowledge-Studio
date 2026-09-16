import json
from pathlib import Path
from typing import Any

from app.retrieval.evaluation import evaluate


def compare_retrievers(
    retrievers: list[Any], questions_path: Path, output_dir: Path, top_k: int = 5
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    reports = []
    for retriever in retrievers:
        report = evaluate(retriever, questions_path, top_k=top_k)
        reports.append(report)
        result_path = output_dir / f"{retriever.retriever_name}.json"
        result_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    summary = {
        "questions": str(questions_path),
        "top_k": top_k,
        "retrievers": [_summary(report) for report in reports],
    }
    (output_dir / "comparison.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "comparison.md").write_text(_markdown(summary), encoding="utf-8")
    return summary


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "retriever": report["retriever"],
        "recall_at_1": report.get("recall_at_1"),
        "recall_at_3": report.get("recall_at_3"),
        "recall_at_5": report.get("recall_at_5"),
        "mrr": report["mrr"],
        "hit_count": report["hit_count"],
        "evaluated": report["questions_evaluated_for_recall"],
        "latency_ms": report["latency_ms"],
    }


def _markdown(summary: dict[str, Any]) -> str:
    rows = [
        "# SupportPilot 检索方案对比",
        "",
        f"评测集：`{summary['questions']}`  ",
        f"返回结果数：Top-{summary['top_k']}",
        "",
        "| 检索方案 | Recall@1 | Recall@3 | Recall@5 | MRR | 命中题数 | 平均延迟(ms) | P50 | P95 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in summary["retrievers"]:
        latency = item["latency_ms"]
        rows.append(
            f"| {item['retriever']} | {item['recall_at_1']:.4f} | "
            f"{item['recall_at_3']:.4f} | {item['recall_at_5']:.4f} | "
            f"{item['mrr']:.4f} | {item['hit_count']}/{item['evaluated']} | "
            f"{latency['average']:.3f} | {latency['p50']:.3f} | {latency['p95']:.3f} |"
        )
    rows.extend(
        [
            "",
            "> 延迟只统计单次检索调用，不包含模型首次加载、文档建索引和回答生成。",
            "",
        ]
    )
    return "\n".join(rows)
