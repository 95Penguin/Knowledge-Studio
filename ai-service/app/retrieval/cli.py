import argparse
import json
from pathlib import Path

from app.retrieval.bm25 import BM25Index
from app.retrieval.comparison import compare_retrievers
from app.retrieval.dense import (
    DEFAULT_MODEL,
    DEFAULT_MODEL_REVISION,
    DenseIndex,
    SentenceTransformerE5Encoder,
)
from app.retrieval.evaluation import evaluate
from app.retrieval.hybrid import RRFHybridRetriever
from app.retrieval.reranker import (
    DEFAULT_RERANKER_MODEL,
    DEFAULT_RERANKER_REVISION,
    BGERerankerScorer,
    RerankingRetriever,
)


def _build(args: argparse.Namespace) -> None:
    chunks = [
        json.loads(line)
        for line in args.chunks.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    index = BM25Index.build(chunks, k1=args.k1, b=args.b)
    index.save(args.output)
    print(
        json.dumps(
            {
                "index": str(args.output),
                "documents": len(index.documents),
                "terms": len(index.postings),
                "average_document_length": round(index.average_document_length, 2),
                "k1": index.k1,
                "b": index.b,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _search(args: argparse.Namespace) -> None:
    results = BM25Index.load(args.index).search(args.query, top_k=args.top_k)
    print(json.dumps([result.to_dict() for result in results], ensure_ascii=False, indent=2))


def _evaluate(args: argparse.Namespace) -> None:
    report = evaluate(BM25Index.load(args.index), args.questions, top_k=args.top_k)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {key: value for key, value in report.items() if key != "details"}
    summary["report"] = str(args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _dense_encoder(args: argparse.Namespace) -> SentenceTransformerE5Encoder:
    return SentenceTransformerE5Encoder(
        model_name=args.model,
        model_revision=args.model_revision,
        batch_size=args.batch_size,
    )


def _dense_build(args: argparse.Namespace) -> None:
    chunks = [
        json.loads(line)
        for line in args.chunks.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    index = DenseIndex.build(chunks, _dense_encoder(args))
    index.save(args.output)
    print(
        json.dumps(
            {
                "index": str(args.output),
                "documents": len(index.documents),
                **index.retriever_parameters,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _dense_search(args: argparse.Namespace) -> None:
    index = DenseIndex.load(args.index, _dense_encoder(args))
    results = index.search(args.query, top_k=args.top_k)
    print(json.dumps([result.to_dict() for result in results], ensure_ascii=False, indent=2))


def _dense_evaluate(args: argparse.Namespace) -> None:
    index = DenseIndex.load(args.index, _dense_encoder(args))
    report = evaluate(index, args.questions, top_k=args.top_k)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {key: value for key, value in report.items() if key != "details"}
    summary["report"] = str(args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _hybrid_retriever(args: argparse.Namespace) -> RRFHybridRetriever:
    lexical = BM25Index.load(args.bm25_index)
    dense = DenseIndex.load(args.dense_index, _dense_encoder(args))
    return RRFHybridRetriever(
        lexical,
        dense,
        candidate_k=args.candidate_k,
        rrf_k=args.rrf_k,
        lexical_weight=args.lexical_weight,
        dense_weight=args.dense_weight,
    )


def _hybrid_search(args: argparse.Namespace) -> None:
    results = _hybrid_retriever(args).search(args.query, top_k=args.top_k)
    print(json.dumps([result.to_dict() for result in results], ensure_ascii=False, indent=2))


def _hybrid_evaluate(args: argparse.Namespace) -> None:
    report = evaluate(_hybrid_retriever(args), args.questions, top_k=args.top_k)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {key: value for key, value in report.items() if key != "details"}
    summary["report"] = str(args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _reranking_retriever(args: argparse.Namespace) -> RerankingRetriever:
    scorer = BGERerankerScorer(
        model_name=args.reranker_model,
        model_revision=args.reranker_revision,
        batch_size=args.reranker_batch_size,
        max_length=args.reranker_max_length,
    )
    return RerankingRetriever(_hybrid_retriever(args), scorer, rerank_k=args.rerank_k)


def _rerank_search(args: argparse.Namespace) -> None:
    results = _reranking_retriever(args).search(args.query, top_k=args.top_k)
    print(json.dumps([result.to_dict() for result in results], ensure_ascii=False, indent=2))


def _rerank_evaluate(args: argparse.Namespace) -> None:
    report = evaluate(_reranking_retriever(args), args.questions, top_k=args.top_k)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {key: value for key, value in report.items() if key != "details"}
    summary["report"] = str(args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _compare(args: argparse.Namespace) -> None:
    encoder = _dense_encoder(args)
    lexical = BM25Index.load(args.bm25_index)
    dense = DenseIndex.load(args.dense_index, encoder)
    hybrid = RRFHybridRetriever(
        lexical,
        dense,
        candidate_k=args.candidate_k,
        rrf_k=args.rrf_k,
        lexical_weight=args.lexical_weight,
        dense_weight=args.dense_weight,
    )
    scorer = BGERerankerScorer(
        model_name=args.reranker_model,
        model_revision=args.reranker_revision,
        batch_size=args.reranker_batch_size,
        max_length=args.reranker_max_length,
    )
    reranked = RerankingRetriever(hybrid, scorer, rerank_k=args.rerank_k)
    summary = compare_retrievers(
        [lexical, dense, hybrid, reranked],
        args.questions,
        args.output_dir,
        top_k=args.top_k,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _weight_experiment(args: argparse.Namespace) -> None:
    encoder = _dense_encoder(args)
    lexical = BM25Index.load(args.bm25_index)
    dense = DenseIndex.load(args.dense_index, encoder)
    retrievers = [dense]
    retrievers.extend(
        RRFHybridRetriever(
            lexical,
            dense,
            candidate_k=args.candidate_k,
            rrf_k=args.rrf_k,
            lexical_weight=1.0,
            dense_weight=weight,
        )
        for weight in args.dense_weights
    )
    summary = compare_retrievers(
        retrievers, args.questions, args.output_dir, top_k=args.top_k
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _add_model_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--model-revision", default=DEFAULT_MODEL_REVISION)
    parser.add_argument("--batch-size", type=int, default=8)


def _add_hybrid_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--bm25-index", type=Path, required=True)
    parser.add_argument("--dense-index", type=Path, required=True)
    parser.add_argument("--candidate-k", type=int, default=20)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--lexical-weight", type=float, default=1.0)
    parser.add_argument("--dense-weight", type=float, default=1.0)
    _add_model_arguments(parser)


def _add_reranker_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--rerank-k", type=int, default=10)
    parser.add_argument("--reranker-model", default=DEFAULT_RERANKER_MODEL)
    parser.add_argument("--reranker-revision", default=DEFAULT_RERANKER_REVISION)
    parser.add_argument("--reranker-batch-size", type=int, default=4)
    parser.add_argument("--reranker-max-length", type=int, default=512)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SupportPilot lexical retrieval baseline")
    subparsers = parser.add_subparsers(required=True)

    build = subparsers.add_parser("build", help="Build an Okapi BM25 index")
    build.add_argument("--chunks", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--k1", type=float, default=1.5)
    build.add_argument("--b", type=float, default=0.75)
    build.set_defaults(handler=_build)

    search = subparsers.add_parser("search", help="Search an existing BM25 index")
    search.add_argument("--index", type=Path, required=True)
    search.add_argument("--query", required=True)
    search.add_argument("--top-k", type=int, default=5)
    search.set_defaults(handler=_search)

    evaluation = subparsers.add_parser("evaluate", help="Evaluate Recall@K")
    evaluation.add_argument("--index", type=Path, required=True)
    evaluation.add_argument("--questions", type=Path, required=True)
    evaluation.add_argument("--output", type=Path, required=True)
    evaluation.add_argument("--top-k", type=int, default=5)
    evaluation.set_defaults(handler=_evaluate)

    dense_build = subparsers.add_parser("dense-build", help="Build a multilingual dense index")
    dense_build.add_argument("--chunks", type=Path, required=True)
    dense_build.add_argument("--output", type=Path, required=True)
    _add_model_arguments(dense_build)
    dense_build.set_defaults(handler=_dense_build)

    dense_search = subparsers.add_parser("dense-search", help="Search a dense index")
    dense_search.add_argument("--index", type=Path, required=True)
    dense_search.add_argument("--query", required=True)
    dense_search.add_argument("--top-k", type=int, default=5)
    _add_model_arguments(dense_search)
    dense_search.set_defaults(handler=_dense_search)

    dense_evaluation = subparsers.add_parser(
        "dense-evaluate", help="Evaluate dense Recall@K"
    )
    dense_evaluation.add_argument("--index", type=Path, required=True)
    dense_evaluation.add_argument("--questions", type=Path, required=True)
    dense_evaluation.add_argument("--output", type=Path, required=True)
    dense_evaluation.add_argument("--top-k", type=int, default=5)
    _add_model_arguments(dense_evaluation)
    dense_evaluation.set_defaults(handler=_dense_evaluate)

    hybrid_search = subparsers.add_parser("hybrid-search", help="Search with BM25 + dense RRF")
    hybrid_search.add_argument("--query", required=True)
    hybrid_search.add_argument("--top-k", type=int, default=5)
    _add_hybrid_arguments(hybrid_search)
    hybrid_search.set_defaults(handler=_hybrid_search)

    hybrid_evaluation = subparsers.add_parser(
        "hybrid-evaluate", help="Evaluate BM25 + dense RRF Recall@K"
    )
    hybrid_evaluation.add_argument("--questions", type=Path, required=True)
    hybrid_evaluation.add_argument("--output", type=Path, required=True)
    hybrid_evaluation.add_argument("--top-k", type=int, default=5)
    _add_hybrid_arguments(hybrid_evaluation)
    hybrid_evaluation.set_defaults(handler=_hybrid_evaluate)

    rerank_search = subparsers.add_parser("rerank-search", help="RRF retrieval with reranking")
    rerank_search.add_argument("--query", required=True)
    rerank_search.add_argument("--top-k", type=int, default=5)
    _add_hybrid_arguments(rerank_search)
    _add_reranker_arguments(rerank_search)
    rerank_search.set_defaults(handler=_rerank_search)

    rerank_evaluation = subparsers.add_parser(
        "rerank-evaluate", help="Evaluate RRF + cross-encoder reranking"
    )
    rerank_evaluation.add_argument("--questions", type=Path, required=True)
    rerank_evaluation.add_argument("--output", type=Path, required=True)
    rerank_evaluation.add_argument("--top-k", type=int, default=5)
    _add_hybrid_arguments(rerank_evaluation)
    _add_reranker_arguments(rerank_evaluation)
    rerank_evaluation.set_defaults(handler=_rerank_evaluate)

    comparison = subparsers.add_parser(
        "compare", help="Evaluate and compare all four retrieval strategies"
    )
    comparison.add_argument("--questions", type=Path, required=True)
    comparison.add_argument("--output-dir", type=Path, required=True)
    comparison.add_argument("--top-k", type=int, default=5)
    _add_hybrid_arguments(comparison)
    _add_reranker_arguments(comparison)
    comparison.set_defaults(handler=_compare)

    weight_experiment = subparsers.add_parser(
        "weight-experiment", help="Compare dense-only with weighted RRF variants"
    )
    weight_experiment.add_argument("--questions", type=Path, required=True)
    weight_experiment.add_argument("--output-dir", type=Path, required=True)
    weight_experiment.add_argument("--top-k", type=int, default=5)
    weight_experiment.add_argument(
        "--dense-weights", type=float, nargs="+", default=[2.0, 4.0, 8.0]
    )
    _add_hybrid_arguments(weight_experiment)
    weight_experiment.set_defaults(handler=_weight_experiment)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
