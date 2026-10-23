"""Reviewer 严格度评测脚本（工单 T-04 / 论文实验 E5）

用途
----
在构造好的评测集上量化 Reviewer 的判定质量：
    good 集（事实正确）→ 期望 pass  （被打回 = 误报 False Positive）
    bad  集（含实质错误）→ 期望打回  （被放行 = 漏报 False Negative）

核心指标
--------
误报率 FPR = good 集中被误判为"打回"的比例   ← 本工单主攻目标
漏报率 FNR = bad 集中被误判为"通过"的比例

用法
----
    # 基线测量（改动前）
    uv run --with pyyaml --with requests python scripts/eval_reviewer.py

    # 输出机器可读结果，供论文 CSV
    uv run --with pyyaml --with requests python scripts/eval_reviewer.py --json out.json

注意：本脚本会产生真实模型调用（60 次），按当前单价约 ¥0.1~0.3。
"""
import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.router import Router
from src.core.llm_client import LLMClient
from src.core.agents.reviewer_agent import ReviewerAgent
from src.core.contracts import Artifact, AgentMessage, TaskContext

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "tests",
                       "fixtures", "reviewer_eval_set.json")


def _extract_score(resp) -> int:
    """从响应中抽取审查评分。

    通过时评分写在 output_text（"审查通过，评分 4/5"）；
    打回时写在 issues 末项（"审查评分 1/5，低于交付标准"）。
    """
    import re

    for text in [resp.output_text or ""] + list(resp.issues or []):
        m = re.search(r"评分\s*(\d+)\s*/\s*5", text)
        if m:
            return int(m.group(1))
    return 0


def review_text(reviewer: ReviewerAgent, text: str) -> dict:
    """对单条文本执行审查，返回 {verdict, score, issues}"""
    artifact = Artifact.text_of(text, step=1)
    message = AgentMessage(
        task_id="eval", step=1, sender="orchestrator",
        receiver=reviewer.name, prompt="审查", artifacts=[artifact],
    )
    context = TaskContext(task_id="eval", user_input="", session_id="eval")

    resp = reviewer.execute(message, context)
    reviewer.drain_call_chain()   # 丢弃评测产生的调用链，避免干扰

    if resp.status == "SUCCESS":
        verdict = "pass"
    elif resp.status == "NEED_REVISION":
        verdict = "reject"
    else:
        verdict = "error"

    return {"verdict": verdict, "score": _extract_score(resp),
            "issues": resp.issues}


def run_eval(workers: int = 4, verbose: bool = True) -> dict:
    with open(FIXTURE, encoding="utf-8") as f:
        dataset = json.load(f)

    router = Router()
    client = LLMClient()
    reviewer = ReviewerAgent(router, client)

    def _run(item):
        text, label = item
        r = review_text(reviewer, text)
        if verbose:
            mark = {"pass": "PASS", "reject": "REJECT", "error": "ERROR"}[r["verdict"]]
            print(f"  [{label:4s}] {mark:6s} score={r['score']} | {text[:36]}")
        return {"label": label, "text": text, **r}

    items = [(t, "good") for t in dataset["good"]] + \
            [(t, "borderline") for t in dataset.get("borderline_good", [])] + \
            [(t, "bad") for t in dataset["bad"]]

    if verbose:
        print(f"评测集: good={len(dataset['good'])} "
              f"borderline={len(dataset.get('borderline_good', []))} "
              f"bad={len(dataset['bad'])}\n")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_run, items))

    good = [r for r in results if r["label"] == "good"]
    borderline = [r for r in results if r["label"] == "borderline"]
    bad = [r for r in results if r["label"] == "bad"]

    # 误报：正确文本（含边界正确）被打回
    fp_good = [r for r in good if r["verdict"] == "reject"]
    fp_border = [r for r in borderline if r["verdict"] == "reject"]
    fp = fp_good + fp_border
    # 漏报：错误文本被放行
    fn = [r for r in bad if r["verdict"] == "pass"]
    errors = [r for r in results if r["verdict"] == "error"]

    correct_pass = len(good) + len(borderline) - len(fp)
    correct_reject = len(bad) - len(fn)

    summary = {
        "total": len(results),
        "good_total": len(good),
        "borderline_total": len(borderline),
        "bad_total": len(bad),
        "false_positive": len(fp),
        "false_positive_good": len(fp_good),
        "false_positive_borderline": len(fp_border),
        "false_negative": len(fn),
        "errors": len(errors),
        "fpr": round(len(fp) / (len(good) + len(borderline)) * 100, 1)
               if (good or borderline) else 0.0,
        "fpr_borderline": round(len(fp_border) / len(borderline) * 100, 1)
                          if borderline else 0.0,
        "fnr": round(len(fn) / len(bad) * 100, 1) if bad else 0.0,
        "accuracy": round((correct_pass + correct_reject) / len(results) * 100, 1)
                    if results else 0.0,
    }

    if verbose:
        print("\n" + "=" * 62)
        print(f"误报率 FPR（全部正确文本被打回）: {summary['fpr']}%  "
              f"({len(fp)}/{len(good) + len(borderline)})")
        print(f"  其中边界样本误报率          : {summary['fpr_borderline']}%  "
              f"({len(fp_border)}/{len(borderline)})")
        print(f"  其中严谨样本误报率          : "
              f"{round(len(fp_good) / len(good) * 100, 1) if good else 0}%  "
              f"({len(fp_good)}/{len(good)})")
        print(f"漏报率 FNR（错误文本被放行）: {summary['fnr']}%  ({len(fn)}/{len(bad)})")
        print(f"总体准确率 Accuracy        : {summary['accuracy']}%")
        print(f"调用异常                   : {summary['errors']}")
        print("=" * 62)
        if fp:
            print("\n误报样本（应通过却被打回）:")
            for r in fp:
                print(f"  [{r['label']:10s}] {r['text'][:44]}...")
                print(f"    理由: {r['issues']}")
        if fn:
            print("\n漏报样本（应打回却被放行）:")
            for r in fn:
                print(f"  - {r['text'][:50]}...")

    return {"summary": summary, "details": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", help="把完整结果写入指定 JSON 文件")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    out = run_eval(workers=args.workers, verbose=not args.quiet)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"\n结果已写入 {args.json}")
