"""批量问答 — 用 QAEngine v3"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from qa.engine import QAEngine


def batch_answer(question_file: str, start: int, end: int, output_file: str = None):
    with open(question_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    qa = QAEngine()
    answered = 0
    failed = 0

    for idx, line in enumerate(lines):
        m = re.match(r"(\d+)\.\s*(.+)", line)
        if not m:
            continue
        num = int(m.group(1))
        if num < start or num > end:
            continue
        question = m.group(2).strip()

        print(f"[{answered+1}/{end-start+1}] Q{num}: {question[:60]}...")
        try:
            result = qa.ask_v2(question, top_k=15)
            answer = result["answer"].strip()
            answer = re.sub(r"\s*\[[\d,\s]+\]\s*$", "", answer)
            lines[idx] = f"{num}. {question}（{answer}）\n"
            answered += 1
        except Exception as e:
            print(f"  ✗ Error: {e}")
            failed += 1

    output_path = output_file or question_file
    with open(output_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    print(f"\nDone: {answered} answered, {failed} failed → {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python batch_qa.py <input.md> <start> <end> [output.md]")
        sys.exit(1)

    batch_answer(
        sys.argv[1],
        int(sys.argv[2]),
        int(sys.argv[3]),
        sys.argv[4] if len(sys.argv) > 4 else None,
    )
