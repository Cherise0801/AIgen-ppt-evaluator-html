"""
PPT 测评校准工具 - AI vs 人工对比分析（Case 库版）

用法：python analyze.py [--results ../results] [--output ../results]

读取：
  - results/human_results.json（人工盲测结果，由 server.py 收集）
  - results/ai_results.json（AI 测评结果，由本 Skill 的 /ppt-blind 导出）

输出：
  - results/report.md（Markdown 报告）
  - results/report.html（可视化 HTML 报告，含 echarts 图表）
  - results/summary.json（机器可读摘要）

新数据模型（Case 库版）：
  human_results.json:
    {
      "comparisons": [
        {"case_a": "case-003", "case_b": "case-004", "chosen": "case-003", "confidence": 4, "timestamp": "..."},
        ...
      ]
    }

  ai_results.json:
    {
      "skill_version": "1.0.0",
      "evaluations": [
        {
          "case_a": "case-003",
          "case_b": "case-004",
          "chosen": "case-003",                            # AI 推荐的 case
          "scores": {                                       # 两个 case 的 7 维评分
            "case-003": {"total": 8.5, "by_dim": {"内容质量": 8, ...}},
            "case-004": {"total": 7.2, "by_dim": {"内容质量": 7, ...}}
          },
          "confidence": 4,
          "reasoning": "...",
          "evaluator": "comate-1.0"
        }
      ]
    }
"""

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# 7 维评分维度顺序（用于报告和图表）
DIMENSIONS = ["内容质量", "结构逻辑", "视觉设计", "表达传达", "技术规范", "版面合规", "版式多样性"]


def load_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_pair(case_a: str, case_b: str) -> tuple:
    """规范化对 (a, b)：总是小的 case_id 在前，确保 (A,B) 和 (B,A) 算同一对。"""
    return tuple(sorted([case_a, case_b]))


def merge_results(human: dict, ai: dict) -> List[dict]:
    """
    合并人工和 AI 结果，按 (case_a, case_b) 对齐。

    返回：[{"pair": (case-003, case-004), "human": "case-003", "ai": "case-003", "match": bool, ...}, ...]
    """
    # 规范化人类结果（按对聚合）
    human_pairs: Dict[tuple, dict] = {}
    for s in human.get("comparisons", []):
        pair = normalize_pair(s["case_a"], s["case_b"])
        if pair not in human_pairs:
            human_pairs[pair] = {"pair": pair, "human_choices": [], "human_confidences": []}
        human_pairs[pair]["human_choices"].append(s.get("chosen"))
        human_pairs[pair]["human_confidences"].append(s.get("confidence"))

    # 规范化 AI 结果
    ai_pairs: Dict[tuple, dict] = {}
    for e in ai.get("evaluations", []):
        pair = normalize_pair(e["case_a"], e["case_b"])
        ai_pairs[pair] = {
            "pair": pair,
            "ai_chosen": e.get("chosen"),
            "ai_confidence": e.get("confidence"),
            "ai_scores": e.get("scores"),
            "ai_reasoning": e.get("reasoning"),
        }

    all_pairs = sorted(set(human_pairs.keys()) | set(ai_pairs.keys()))
    merged = []
    for pair in all_pairs:
        h = human_pairs.get(pair)
        a = ai_pairs.get(pair)
        # 多数选择（如果人多次评估同一对）
        human_chosen = None
        if h and h["human_choices"]:
            # 选最多的；同票选第一个
            from collections import Counter
            cnt = Counter(h["human_choices"])
            human_chosen = cnt.most_common(1)[0][0]
        merged.append({
            "pair": pair,
            "case_a": pair[0],
            "case_b": pair[1],
            "human": human_chosen,
            "human_votes": h["human_choices"] if h else [],
            "human_confidences": h["human_confidences"] if h else [],
            "ai": a["ai_chosen"] if a else None,
            "ai_confidence": a["ai_confidence"] if a else None,
            "ai_scores": a["ai_scores"] if a else None,
            "ai_reasoning": a["ai_reasoning"] if a else None,
            "match": (human_chosen is not None and a and a["ai_chosen"] == human_chosen),
        })
    return merged


def calc_overall_rate(merged: List[dict]) -> dict:
    """计算总一致率"""
    valid = [m for m in merged if m["match"] is not None]
    if not valid:
        return {"total": 0, "matched": 0, "rate": 0.0, "rate_pct": "0.0%"}
    matched = sum(1 for m in valid if m["match"])
    return {
        "total": len(valid),
        "matched": matched,
        "rate": matched / len(valid),
        "rate_pct": f"{(matched / len(valid) * 100):.1f}%",
    }


def calc_per_dim_rate(merged: List[dict]) -> List[dict]:
    """
    按维度拆分一致率。

    对每个 case 对，比较 AI 在某维度上倾向谁 vs 实际人选择谁。
    某 case 对选了 case-003：
      - 看 AI scores 中 case-003 vs case-004 在该维度的分
      - 如果 case-003 更高，AI 在该维度倾向 case-003（与人一致 → match）
    """
    valid = [m for m in merged if m["match"] is not None and m["ai_scores"]]
    if not valid:
        return []

    dim_stats = {d: {"match": 0, "total": 0} for d in DIMENSIONS}
    for m in valid:
        scores = m["ai_scores"]
        case_a = m["case_a"]
        case_b = m["case_b"]
        a_score = scores.get(case_a, {}).get("by_dim", {})
        b_score = scores.get(case_b, {}).get("by_dim", {})
        human_choice = m["human"]
        for d in DIMENSIONS:
            a_v = a_score.get(d)
            b_v = b_score.get(d)
            if a_v is None or b_v is None:
                continue
            dim_stats[d]["total"] += 1
            # AI 在该维度倾向谁（分数高的）
            ai_pref = case_a if a_v > b_v else (case_b if b_v > a_v else None)
            if ai_pref == human_choice:
                dim_stats[d]["match"] += 1
    return [
        {
            "dimension": d,
            "match": s["match"],
            "total": s["total"],
            "rate": s["match"] / s["total"] if s["total"] else 0,
            "rate_pct": f"{(s['match'] / s['total'] * 100):.1f}%" if s["total"] else "-",
        }
        for d, s in dim_stats.items()
    ]


def calc_per_case_stats(merged: List[dict]) -> List[dict]:
    """每个 case 的盲测统计（作为 / 败场数）。"""
    case_wins = {}
    case_total = {}
    for m in merged:
        if m["match"] is not None:
            for c in m["pair"]:
                case_total[c] = case_total.get(c, 0) + 1
        if m["human"]:
            case_wins[m["human"]] = case_wins.get(m["human"], 0) + 1
    return [
        {"case_id": c, "wins": case_wins.get(c, 0), "total": case_total.get(c, 0),
         "win_rate": f"{(case_wins.get(c, 0) / case_total[c] * 100):.1f}%" if case_total.get(c) else "-"}
        for c in sorted(case_total.keys())
    ]


def generate_markdown_report(merged: List[dict], overall: dict, per_dim: List[dict], per_case: List[dict], human: dict, ai: dict) -> str:
    """生成 Markdown 报告"""
    lines = []
    lines.append("# PPT 测评校准报告")
    lines.append("")
    lines.append(f"**生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**人工盲测总数**：{len(human.get('comparisons', []))} 次（覆盖 {overall.get('total', 0)} 个 case 对）")
    lines.append(f"**AI 测评总数**：{len(ai.get('evaluations', []))} 次")
    lines.append("")

    lines.append("## 1. 总一致率")
    lines.append("")
    lines.append(f"- 对齐 case 对：**{overall['total']}**")
    lines.append(f"- AI 选对了：**{overall['matched']}**")
    lines.append(f"- **一致率：{overall['rate_pct']}**")
    lines.append("")

    lines.append("## 2. 分维度一致率")
    lines.append("")
    lines.append("| 维度 | AI 倾向与人一致次数 | 有效总次数 | 一致率 |")
    lines.append("|------|---------------------|------------|--------|")
    for d in per_dim:
        lines.append(f"| {d['dimension']} | {d['match']} | {d['total']} | {d['rate_pct']} |")
    lines.append("")

    if per_case:
        lines.append("## 3. 各 case 表现（人工盲测维度）")
        lines.append("")
        lines.append("| Case | 胜场 | 参与对数 | 胜率 |")
        lines.append("|------|------|----------|------|")
        for c in per_case:
            lines.append(f"| {c['case_id']} | {c['wins']} | {c['total']} | {c['win_rate']} |")
        lines.append("")

    lines.append("## 4. 分歧 case 对")
    lines.append("")
    diverged = [m for m in merged if m["match"] is False]
    if not diverged:
        lines.append("无分歧。")
    else:
        for m in diverged:
            lines.append(f"### {m['case_a']} vs {m['case_b']}")
            lines.append(f"- 人工选择：**{m['human']}**（投票：{m['human_votes']}，信心度：{m['human_confidences']}）")
            lines.append(f"- AI 选择：**{m['ai']}**（信心度：{m['ai_confidence']}）")
            if m.get("ai_scores"):
                lines.append(f"- AI 评分：")
                for case_id, sc in m["ai_scores"].items():
                    dims = ", ".join(f"{k}={v}" for k, v in sc.get("by_dim", {}).items())
                    lines.append(f"  - {case_id}: total={sc.get('total')}, {dims}")
            if m.get("ai_reasoning"):
                lines.append(f"- AI 理由：{m['ai_reasoning']}")
            lines.append("")

    lines.append("## 5. 结论与建议")
    lines.append("")
    rate = overall["rate"]
    if rate >= 0.8:
        lines.append("✅ AI 测评与人工判断高度一致，模型评分可靠。")
    elif rate >= 0.6:
        lines.append("⚠️ AI 测评与人工判断中等一致，建议优化评分 prompt 或权重。")
    else:
        lines.append("❌ AI 测评与人工判断一致性偏低，需要重点优化：")
        lines.append("- 检查评分 rubric 是否清晰")
        lines.append("- 检查 SKILL.md 中提示词是否让 AI 关注人关注的维度")

    # 找出 AI 表现最差的维度
    if per_dim:
        worst = min(per_dim, key=lambda x: x["rate"] if x["total"] > 0 else 1.0)
        if worst["total"] > 0 and worst["rate"] < 0.6:
            lines.append(f"- 分维度看，**{worst['dimension']}** 一致率最低（{worst['rate_pct']}），AI 在此维度与人工判断分歧最大，建议重点优化。")

    return "\n".join(lines)


def generate_html_report(merged: List[dict], overall: dict, per_dim: List[dict], per_case: List[dict]) -> str:
    """生成可视化 HTML 报告（含 echarts 图表）。"""
    import html as htmllib

    md = generate_markdown_report(merged, overall, per_dim, per_case, {"comparisons": []}, {"evaluations": []})
    md_html = htmllib.escape(md)
    # 简单 markdown → html（标题/列表/表格）
    import re
    md_html = re.sub(r"^# (.+)$", r"<h1>\1</h1>", md_html, flags=re.MULTILINE)
    md_html = re.sub(r"^## (.+)$", r"<h2>\1</h2>", md_html, flags=re.MULTILINE)
    md_html = re.sub(r"^### (.+)$", r"<h3>\1</h3>", md_html, flags=re.MULTILINE)
    md_html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", md_html)
    md_html = re.sub(r"`([^`]+)`", r"<code>\1</code>", md_html)
    md_html = re.sub(r"^- (.+)$", r"<li>\1</li>", md_html, flags=re.MULTILINE)
    md_html = re.sub(r"((?:<li>.*</li>\n?)+)", r"<ul>\1</ul>", md_html)
    md_html = re.sub(r"^\| (.+) \|$", lambda m: "<tr>" + "".join(f"<td>{c.strip()}</td>" for c in m.group(1).split("|")) + "</tr>", md_html, flags=re.MULTILINE)
    md_html = re.sub(r"((?:<tr>.*</tr>\n?)+)", r"<table border=1 cellspacing=0 cellpadding=6>\1</table>", md_html)

    # 准备 echarts 数据
    dim_data = {
        "categories": [d["dimension"] for d in per_dim],
        "rates": [round(d["rate"] * 100, 1) for d in per_dim],
    }
    case_data = {
        "categories": [c["case_id"] for c in per_case],
        "wins": [c["wins"] for c in per_case],
        "totals": [c["total"] for c in per_case],
    }

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>PPT 测评校准报告</title>
<script src="../tools/static/echarts.min.js"></script>
<style>
  body {{ font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; max-width: 1100px; margin: 30px auto; padding: 0 20px; color: #1a1a1a; line-height: 1.6; }}
  h1 {{ border-bottom: 2px solid #2563eb; padding-bottom: 8px; }}
  h2 {{ margin-top: 32px; color: #1e40af; border-left: 4px solid #2563eb; padding-left: 10px; }}
  h3 {{ color: #374151; }}
  table {{ border-collapse: collapse; margin: 12px 0; }}
  th, td {{ border: 1px solid #e5e7eb; padding: 6px 12px; }}
  th {{ background: #f3f4f6; }}
  code {{ background: #f3f4f6; padding: 1px 6px; border-radius: 3px; font-size: 13px; }}
  .chart {{ width: 100%; height: 380px; margin: 20px 0; }}
  .summary-card {{ display: inline-block; background: #eff6ff; border: 1px solid #93c5fd; padding: 16px 24px; border-radius: 8px; margin: 8px 12px 8px 0; }}
  .summary-card .label {{ font-size: 12px; color: #6b7280; }}
  .summary-card .value {{ font-size: 28px; font-weight: 700; color: #1e40af; }}
</style></head>
<body>
<h1>🎯 PPT 测评校准报告</h1>
<div>
  <div class="summary-card"><div class="label">总一致率</div><div class="value">{overall['rate_pct']}</div></div>
  <div class="summary-card"><div class="label">case 对数</div><div class="value">{overall['total']}</div></div>
  <div class="summary-card"><div class="label">AI 选对数</div><div class="value">{overall['matched']}</div></div>
</div>

<div class="chart" id="dimChart"></div>
<div class="chart" id="caseChart"></div>

<h2>详细报告</h2>
<div style="background:#f9fafb; padding:16px; border-radius:6px;">{md_html}</div>

<script>
const dimData = {json.dumps(dim_data, ensure_ascii=False)};
const caseData = {json.dumps(case_data, ensure_ascii=False)};

const dimChart = echarts.init(document.getElementById('dimChart'));
dimChart.setOption({{
  title: {{text: '各维度一致率', left: 'center'}},
  tooltip: {{trigger: 'axis', formatter: '{{b}}: {{c}}%'}},
  grid: {{left: 80, right: 40, top: 60, bottom: 40}},
  xAxis: {{type: 'value', max: 100, axisLabel: {{formatter: '{{value}}%'}}}},
  yAxis: {{type: 'category', data: dimData.categories}},
  series: [{{
    type: 'bar',
    data: dimData.rates,
    itemStyle: {{
      color: function(p) {{
        if (p.value >= 80) return '#10b981';
        if (p.value >= 60) return '#f59e0b';
        return '#ef4444';
      }}
    }},
    label: {{show: true, position: 'right', formatter: '{{c}}%'}}
  }}]
}});

const caseChart = echarts.init(document.getElementById('caseChart'));
caseChart.setOption({{
  title: {{text: '各 case 胜场数（人工盲测）', left: 'center'}},
  tooltip: {{trigger: 'axis'}},
  legend: {{data: ['胜场', '参与对数'], top: 30}},
  grid: {{left: 60, right: 40, top: 80, bottom: 40}},
  xAxis: {{type: 'category', data: caseData.categories}},
  yAxis: {{type: 'value'}},
  series: [
    {{name: '胜场', type: 'bar', data: caseData.wins, itemStyle: {{color: '#3b82f6'}}}},
    {{name: '参与对数', type: 'bar', data: caseData.totals, itemStyle: {{color: '#94a3b8'}}}}
  ]
}});
</script>
</body></html>"""


def main():
    parser = argparse.ArgumentParser(description="AI vs 人工盲测对比分析")
    parser.add_argument("--results", default=str(Path(__file__).parent.parent / "results"),
                        help="results 目录路径")
    parser.add_argument("--output", default=None, help="输出目录（默认同 results）")
    args = parser.parse_args()

    results_dir = Path(args.results)
    output_dir = Path(args.output) if args.output else results_dir
    output_dir.mkdir(exist_ok=True)

    human = load_json(results_dir / "human_results.json")
    ai = load_json(results_dir / "ai_results.json")

    if not human:
        print("❌ human_results.json 不存在或为空，请先做人工盲测")
        return
    if not ai:
        print("❌ ai_results.json 不存在或为空，请先用本 Skill 跑 AI 测评")
        return

    # 兼容旧结构（selections → comparisons）
    if "selections" in human and "comparisons" not in human:
        human["comparisons"] = human.pop("selections")

    merged = merge_results(human, ai)
    overall = calc_overall_rate(merged)
    per_dim = calc_per_dim_rate(merged)
    per_case = calc_per_case_stats(merged)

    # 写报告
    md = generate_markdown_report(merged, overall, per_dim, per_case, human, ai)
    html = generate_html_report(merged, overall, per_dim, per_case)

    (output_dir / "report.md").write_text(md, encoding="utf-8")
    (output_dir / "report.html").write_text(html, encoding="utf-8")
    (output_dir / "summary.json").write_text(json.dumps({
        "overall": overall,
        "per_dim": per_dim,
        "per_case": per_case,
        "diverged_count": sum(1 for m in merged if m["match"] is False),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"✅ 报告生成完成：")
    print(f"   - {output_dir / 'report.md'}")
    print(f"   - {output_dir / 'report.html'}")
    print(f"   - {output_dir / 'summary.json'}")
    print()
    print(f"📊 总一致率：{overall['rate_pct']}（{overall['matched']}/{overall['total']}）")


if __name__ == "__main__":
    main()
