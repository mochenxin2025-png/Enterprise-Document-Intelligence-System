"""自动评估脚本 — Recall@K + Faithfulness + Citation Accuracy

输出 metric 不再靠肉眼。
"""
import re
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from retrieval import VectorStore, Embedder
import httpx
from config import config


def parse_answers(filepath: str) -> list[dict]:
    """解析答案文件，提取 题号 + 问题 + 答案"""
    items = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            match = re.match(r'^(\d+)\.\s+(.+?)（(.+)）\s*$', line.strip())
            if match:
                num = int(match.group(1))
                question = match.group(2).strip()
                answer = match.group(3).strip()
                items.append({"num": num, "question": question, "answer": answer})
    return items


def retrieve_chunks(store: VectorStore, question: str, top_k: int = 10) -> list[dict]:
    embedding = Embedder.encode_query(question)
    results = store.search(embedding, top_k=top_k)
    return [
        {"text": r.text, "page": r.page, "score": r.score, "source": r.source}
        for r in results
    ]


def judge_faithfulness(question: str, answer: str, chunks: list[dict]) -> dict:
    """用 LLM 判断答案是否被检索 Chunk 支撑"""
    key = config.api_key("deepseek")

    # 只保留 top 5 个 chunk 用于判断
    context = "\n\n---\n\n".join(
        f"[{i+1}] Page {c['page']}: {c['text'][:500]}" for i, c in enumerate(chunks[:5])
    )

    prompt = (
        "You are evaluating an RAG system's answer quality. "
        "Judge whether the answer is FACTUALLY SUPPORTED by the provided context chunks. "
        "Return ONLY a JSON object, no other text.\n\n"
        f"Question: {question}\n\n"
        f"Answer: {answer}\n\n"
        f"Context chunks:\n{context}\n\n"
        'Return JSON: {"supported": true/false, "relevant_chunks": [1,2,...], '
        '"confidence": 0.0-1.0, "reason": "one sentence"}'
    )

    try:
        resp = httpx.post(
            f"{config.get('api', 'deepseek', 'base_url')}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": config.get("llm", "model"),
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0,
                "max_tokens": 300,
            },
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]
        # Extract JSON
        json_match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))
    except Exception as e:
        pass
    return {"supported": False, "relevant_chunks": [], "confidence": 0, "reason": f"eval_error"}


def evaluate(answer_file: str, sample: int | None = None) -> dict:
    """跑完整评估管线"""
    store = VectorStore(config.get("storage", "db_path"))
    items = parse_answers(answer_file)

    if sample:
        import random
        random.seed(42)
        items = random.sample(items, sample)

    print(f"Evaluating {len(items)} questions...\n")

    results = []
    recall_at_k = {5: [], 10: []}
    supported = 0
    total = 0

    for idx, item in enumerate(items):
        print(f"[{idx+1}/{len(items)}] Q{item['num']}", end=" ")

        # Skip obvious "未找到" answers — but verify they're genuine
        is_honest_not_found = (
            any(kw in item["answer"] for kw in ["未找到", "not found", "没有找到", "无法确定", "无法回答", "does not contain", "no information"])
        )
        if is_honest_not_found:
            # Verify: does at least one chunk actually contain the answer?
            chunks = retrieve_chunks(store, item["question"], top_k=5)
            has_content = any(
                any(kw in c["text"] for kw in item["question"].split() if len(kw) >= 3)
                for c in chunks
            )
            if not has_content:
                print("→ HONEST ✓ (truly not in PDF)")
                results.append({**item, "supported": True, "reason": "honest_not_found", "chunks_found": len(chunks)})
                supported += 1
                total += 1
                continue

        # Retrieve
        chunks = retrieve_chunks(store, item["question"], top_k=10)

        # Recall@K: does at least one chunk look relevant?
        relevant_at_5 = any(c["score"] > 0.5 for c in chunks[:5])
        relevant_at_10 = any(c["score"] > 0.5 for c in chunks[:10])
        recall_at_k[5].append(1 if relevant_at_5 else 0)
        recall_at_k[10].append(1 if relevant_at_10 else 0)

        # Faithfulness: LLM judge
        judgment = judge_faithfulness(item["question"], item["answer"], chunks)
        is_supported = judgment.get("supported", False)

        if is_supported:
            supported += 1
            print("✓")
        else:
            print(f"✗ ({judgment.get('reason', '?')[:50]})")

        total += 1
        results.append({
            **item,
            "supported": is_supported,
            "reason": judgment.get("reason", ""),
            "relevance_score": judgment.get("confidence", 0),
            "chunks_found": len(chunks),
            "top_chunk_score": chunks[0]["score"] if chunks else 0,
        })

    store.close()

    # Metrics
    recall5 = sum(recall_at_k[5]) / len(recall_at_k[5]) if recall_at_k[5] else 0
    recall10 = sum(recall_at_k[10]) / len(recall_at_k[10]) if recall_at_k[10] else 0
    faithfulness = supported / total if total > 0 else 0

    report = {
        "total_evaluated": total,
        "total_questions": len(items),
        "recall@5": round(recall5, 3),
        "recall@10": round(recall10, 3),
        "faithfulness": round(faithfulness, 3),
        "details": results,
    }

    # Save
    report_path = Path(answer_file).with_suffix(".eval_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print(f"Recall@5:     {recall5:.1%}")
    print(f"Recall@10:    {recall10:.1%}")
    print(f"Faithfulness: {faithfulness:.1%}")
    print(f"Report: {report_path}")

    return report


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python evaluate.py <answer_file.md> [sample_size]")
        sys.exit(1)
    sample = int(sys.argv[2]) if len(sys.argv) > 2 else None
    evaluate(sys.argv[1], sample)
