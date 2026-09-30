"""
PPT 测评校准工具 - AI vs 人工对比分析

用法：python analyze.py [--results ../results] [--output ../results]

读取：
  - results/human_results.json（人工盲测结果，由 server.py 收集）
  - results/ai_results.json（AI 测评结果，由本 Skill 的 /ppt-blind 导出）

输出：
  - results/report.md（Markdown 报告）
  - results/report.html（可视化 HTML 报告，含 echarts 图表）
  - results/summary.json（机器可读摘要）

ai_results.json 期望结构：
{
  "skill_version": "1.0.0",
  "evaluations": [
    {
      "case_id": "case-001",
      "chosen": "A" | "B",                  # AI 推荐的方案
      "scores": {                            # 7 维加权评分
        "A": {"total": 8.5, "by_dim": {"内容质量": 8, "结构逻辑": 9, ...}},
        "B": {"total": 7.2, "by_dim": {"内容质量": 7, "结构逻辑": 8, ...}}
      },
      "confidence": 1-5,                     # AI 推荐的信心度（可选）
      "reasoning": "..."                     # AI 的判断理由（可选）
    }
  ]
}
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

# 7 维评分维度顺序（用于报告和图表）
DIMENSIONS = ["内容质量", "结构逻辑", "视觉设计", "表达传达", "技术规范", "版面合规", "版式多样性"]


def load_json(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def merge_results(human: dict, ai: dict) -> list:
    """
    合并人工和 AI 结果，按 case_id 对齐。

    返回：[{"case_id": "case-001", "human": "A"|"B", "ai": "A"|"B", "match": bool, "human_confidence": int, "ai_confidence": int, "ai_scores": {...}}, ...]
    """
    human_map = {s["case_id"]: s for s in human.get("selections", [])}
    ai_map = {e["case_id"]: e for e in ai.get("evaluations", [])}

    all_case_ids = sorted(set(human_map.keys()) | set(ai_map.keys()))
    merged = []
    for cid in all_case_ids:
        h = human_map.get(cid)
        a = ai_map.get(cid)
        merged.append({
            "case_id": cid,
            "human": h.get("chosen") if h else None,
            "human_confidence": h.get("confidence") if h else None,
            "ai": a.get("chosen") if a else None,
            "ai_confidence": a.get("confidence") if a else None,
            "ai_scores": a.get("scores") if a else None,
            "ai_reasoning": a.get("reasoning") if a else None,
            "match": (h and a) and (h.get("chosen") == a.get("chosen")),
        })
    return merged


def calc_overall_rate(merged: list) -> dict:
    """计算总一致率"""
    valid = [m for m in merged if m["match"] is not None and (m["match"] is True or m["match"] is False)]
    if not valid:
        return {"total": 0, "matched": 0, "rate": 0.0, "rate_pct": "0.0%"}
    matched = sum(1 for m in valid if m["match"])
    return {
        "total": len(valid),
        "matched": matched,
        "rate": matched / len(valid),
        "rate_pct": f"{(matched / len(valid) * 100):.1f}%",
    }


def calc_per_dim_rate(merged: list) -> list:
    """
    按维度拆分一致率：

    对每个维度，比较 AI 评分（高分者为人选择）vs 实际人选择。
    比如某 case 选了 A：
      - 看 AI 评分中哪个维度 A 比 B 分高（这些维度 AI 倾向 A）
      - 统计这些维度中"AI 倾向 A"且"人选 A"的比例
    """
    valid = [m for m in merged if m["match"] is not None and m["ai_scores"]]
    if not valid:
        return []

    # 思路：每个 case，每个维度，AI 是否倾向"人选择"的那个
    dim_stats = {d: {"match": 0, "total": 0} for d in DIMENSIONS}
    for m in valid:
        scores = m["ai_scores"]
        a = scores.get("A", {}).get("by_dim", {})
        b = scores.get("B", {}).get("by_dim", {})
        human_choice = m["human"]
        for d in DIMENSIONS:
            a_score = a.get(d)
            b_score = b.get(d)
            if a_score is None or b_score is None:
                continue
            dim_stats[d]["total"] += 1
            # AI 在该维度倾向谁
            ai_pref = "A" if a_score > b_score else ("B" if b_score > a_score else None)
            # 如果该维度 AI 倾向"人选择"，算 match
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


def calc_confidence_accuracy(merged: list) -> list:
    """按信心度（人工）分组，计算一致率"""
    groups = {}
    for m in merged:
        if m["match"] is None or m["human_confidence"] is None:
            continue
        c = m["human_confidence"]
        if c not in groups:
            groups[c] = {"match": 0, "total": 0}
        groups[c]["total"] += 1
        if m["match"]:
            groups[c]["match"] += 1
    return [
        {
            "confidence": c,
            "match": g["match"],
            "total": g["total"],
            "rate": g["match"] / g["total"] if g["total"] else 0,
            "rate_pct": f"{(g['match'] / g['total'] * 100):.1f}%" if g["total"] else "-",
        }
        for c, g in sorted(groups.items())
    ]


def find_disagreements(merged: list) -> list:
    """列出 AI 和人判断不一致的 case"""
    return [m for m in merged if m["match"] is False]


def generate_markdown(overall, per_dim, confidence, disagreements, human_meta, ai_meta):
    """生成 Markdown 报告"""
    lines = []
    lines.append("# PPT 测评校准报告\n")
    lines.append(f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append(f"> 人工盲测样本：{overall['total']} 个 case\n")
    if ai_meta:
        lines.append(f"> AI 测评版本：{ai_meta.get('skill_version', 'unknown')}\n")
    lines.append("\n---\n\n")

    # 1. 总览
    lines.append("## 1. 总体一致率\n\n")
    lines.append(f"| 指标 | 数值 |\n|------|------|\n")
    lines.append(f"| 比对的 case 总数 | {overall['total']} |\n")
    lines.append(f"| AI 与人判断一致 | {overall['matched']} |\n")
    lines.append(f"| **一致率** | **{overall['rate_pct']}** |\n\n")

    # 评级
    rate = overall["rate"]
    if rate >= 0.85:
        grade = "✅ 优秀（AI 测评可信度高）"
    elif rate >= 0.70:
        grade = "⚠️ 良好（AI 测评基本可信，仍有提升空间）"
    elif rate >= 0.50:
        grade = "⚠️ 一般（AI 测评与人工判断存在较大分歧）"
    else:
        grade = "❌ 较差（AI 测评需要优化）"
    lines.append(f"**评级**：{grade}\n\n")

    # 2. 分维度一致率
    lines.append("## 2. 分维度一致率\n\n")
    lines.append("> 统计每个维度上，AI 评分倾向的方案是否与人工选择一致。\n\n")
    lines.append("| 维度 | 一致 case | 总 case | 一致率 |\n|------|-----------|---------|--------|\n")
    for d in per_dim:
        if d["total"] > 0:
            lines.append(f"| {d['dimension']} | {d['match']} | {d['total']} | {d['rate_pct']} |\n")
    lines.append("\n")
    # 找出最弱维度
    if per_dim:
        worst = min(per_dim, key=lambda x: x["rate"] if x["total"] else 1.0)
        if worst["total"] > 0:
            lines.append(f"**最弱维度**：{worst['dimension']}（一致率 {worst['rate_pct']}）— AI 在该维度上的判断与人工分歧最大，建议重点优化\n\n")

    # 3. 信心度 vs 准确率
    lines.append("## 3. 信心度 vs 准确率\n\n")
    if confidence:
        lines.append("> 按人工评分时的信心度分组，看 AI 在不同信心度 case 上的一致率。\n\n")
        lines.append("| 信心度 | 一致 | 总数 | 一致率 |\n|--------|------|------|--------|\n")
        for c in confidence:
            lines.append(f"| {c['confidence']} | {c['match']} | {c['total']} | {c['rate_pct']} |\n")
        lines.append("\n")
    else:
        lines.append("_（人工盲测时未提供信心度数据）_\n\n")

    # 4. 分歧 case 清单
    lines.append("## 4. 分歧 case 清单\n\n")
    if disagreements:
        lines.append(f"共 {len(disagreements)} 个 AI 与人工判断不一致的 case：\n\n")
        lines.append("| Case ID | 人选择 | AI 选择 | AI 推荐理由 |\n|---------|--------|---------|-------------|\n")
        for d in disagreements:
            reason = (d.get("ai_reasoning") or "")[:80] + ("..." if d.get("ai_reasoning") and len(d["ai_reasoning"]) > 80 else "")
            lines.append(f"| {d['case_id']} | {d['human']} | {d['ai']} | {reason} |\n")
        lines.append("\n")
    else:
        lines.append("🎉 没有分歧 case\n\n")

    # 5. 优化建议
    lines.append("## 5. 优化建议\n\n")
    if per_dim:
        sorted_dims = sorted([d for d in per_dim if d["total"] > 0], key=lambda x: x["rate"])
        lines.append(f"1. **重点优化**：{sorted_dims[0]['dimension']}（一致率 {sorted_dims[0]['rate_pct']}）— 该维度的评分锚点或权重可能需要调整\n")
        if len(sorted_dims) > 1:
            lines.append(f"2. **次要关注**：{sorted_dims[1]['dimension']}（一致率 {sorted_dims[1]['rate_pct']}）\n")
        if overall["rate"] < 0.7:
            lines.append("3. **整体校准**：一致率偏低，建议在 `references/rubric.md` 中重新审视评分锚点\n")
    lines.append("4. **收集更多样本**：当前样本量较少，结果可能有偶然性，建议积累 30+ case 再下结论\n")
    lines.append("5. **关注分歧 case**：手动 review 第 4 节列出的 case，理解为什么 AI 和人判断不同\n")

    return "".join(lines)


def generate_html(overall, per_dim, confidence, disagreements, human_meta, ai_meta):
    """生成 HTML 可视化报告"""
    # 转成 JSON 字符串嵌入
    chart_data = {
        "overall": overall,
        "per_dim": per_dim,
        "confidence": confidence,
        "disagreement_count": len(disagreements),
    }
    chart_data_json = json.dumps(chart_data, ensure_ascii=False)

    # 分歧 case 列表
    disagree_html = ""
    for d in disagreements:
        reason = (d.get("ai_reasoning") or "").replace("<", "&lt;").replace(">", "&gt;")
        disagree_html += f"<tr><td>{d['case_id']}</td><td>{d['human']}</td><td>{d['ai']}</td><td>{reason}</td></tr>"

    # echarts 引用本地 static
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>PPT 测评校准报告</title>
<script src="../tools/static/echarts.min.js"></script>
<style>
  body {{ font-family: -apple-system, sans-serif; background: #f5f7fa; color: #303133; margin: 0; padding: 24px; }}
  h1, h2 {{ color: #303133; }}
  .card {{ background: white; border-radius: 8px; padding: 20px; margin-bottom: 16px; box-shadow: 0 2px 4px rgba(0,0,0,0.06); }}
  .summary {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }}
  .stat {{ text-align: center; padding: 16px; background: #f5f7fa; border-radius: 6px; }}
  .stat .num {{ font-size: 32px; font-weight: 700; color: #409eff; }}
  .stat .label {{ color: #606266; font-size: 12px; margin-top: 4px; }}
  .chart {{ width: 100%; height: 320px; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #ebeef5; }}
  th {{ background: #fafbfc; color: #606266; font-weight: 600; }}
</style>
</head>
<body>
<h1>📊 PPT 测评校准报告</h1>
<p>生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>

<div class="card">
  <h2>总体一致率</h2>
  <div class="summary">
    <div class="stat"><div class="num" id="overall-rate">-</div><div class="label">一致率</div></div>
    <div class="stat"><div class="num" id="overall-total">-</div><div class="label">比对 case 总数</div></div>
    <div class="stat"><div class="num" id="overall-match">-</div><div class="label">一致数</div></div>
    <div class="stat"><div class="num" id="disagree-count">-</div><div class="label">分歧数</div></div>
  </div>
</div>

<div class="card">
  <h2>分维度一致率</h2>
  <div id="chart-dim" class="chart"></div>
</div>

<div class="card">
  <h2>信心度 vs 准确率</h2>
  <div id="chart-conf" class="chart"></div>
</div>

<div class="card">
  <h2>分歧 case 清单（{len(disagreements)} 个）</h2>
  <table>
    <tr><th>Case ID</th><th>人选择</th><th>AI 选择</th><th>AI 理由</th></tr>
    {disagree_html if disagree_html else '<tr><td colspan="4" style="text-align:center;color:#909399;">🎉 无分歧</td></tr>'}
  </table>
</div>

<script>
const DATA = {chart_data_json};
const chartDim = echarts.init(document.getElementById('chart-dim'));
const chartConf = echarts.init(document.getElementById('chart-conf'));

// 总览数字
document.getElementById('overall-rate').textContent = DATA.overall.rate_pct;
document.getElementById('overall-total').textContent = DATA.overall.total;
document.getElementById('overall-match').textContent = DATA.overall.matched;
document.getElementById('disagree-count').textContent = DATA.disagreement_count;

// 分维度柱状图
chartDim.setOption({{
  title: {{ text: '每个维度上 AI 与人工判断一致率', left: 'left', textStyle: {{ fontSize: 14, fontWeight: 'normal' }} }},
  tooltip: {{ trigger: 'axis', formatter: '{{b}}: {{c}}' }},
  grid: {{ left: 60, right: 30, top: 50, bottom: 30 }},
  xAxis: {{ type: 'category', data: DATA.per_dim.map(d => d.dimension) }},
  yAxis: {{ type: 'value', max: 100, axisLabel: {{ formatter: '{{value}}%' }} }},
  series: [{{
    type: 'bar',
    data: DATA.per_dim.map(d => ({{
      value: parseFloat(d.rate_pct),
      itemStyle: {{ color: parseFloat(d.rate_pct) >= 70 ? '#67c23a' : (parseFloat(d.rate_pct) >= 50 ? '#e6a23c' : '#f56c6c') }}
    }})),
    label: {{ show: true, position: 'top', formatter: '{{c}}%' }}
  }}]
}});

// 信心度折线图
chartConf.setOption({{
  title: {{ text: '不同信心度下 AI 的一致率', left: 'left', textStyle: {{ fontSize: 14, fontWeight: 'normal' }} }},
  tooltip: {{ trigger: 'axis' }},
  grid: {{ left: 60, right: 30, top: 50, bottom: 30 }},
  xAxis: {{ type: 'category', name: '信心度', data: DATA.confidence.map(c => '信心度 ' + c.confidence) }},
  yAxis: {{ type: 'value', max: 100, axisLabel: {{ formatter: '{{value}}%' }} }},
  series: [{{
    type: 'line',
    data: DATA.confidence.map(c => parseFloat(c.rate_pct)),
    label: {{ show: true, formatter: '{{c}}%' }},
    itemStyle: {{ color: '#409eff' }}
  }}]
}});
</script>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="AI vs 人工盲测对比分析")
    parser.add_argument("--results", type=str, default="../results", help="结果目录（相对于 tools/）")
    parser.add_argument("--output", type=str, default=None, help="报告输出目录（默认同 results/）")
    args = parser.parse_args()

    tools_dir = Path(__file__).parent.resolve()
    results_dir = (tools_dir / args.results).resolve()
    output_dir = (tools_dir / (args.output or args.results)).resolve()

    human = load_json(results_dir / "human_results.json")
    ai = load_json(results_dir / "ai_results.json")

    if not human or not human.get("selections"):
        print("❌ 未找到 human_results.json 或无人工盲测数据，请先运行 server.py 收集人工盲测结果")
        return
    if not ai or not ai.get("evaluations"):
        print("⚠️ 未找到 ai_results.json 或无 AI 测评数据")
        print("   请先用本 Skill 的 /ppt-blind 跑 AI 测评，把结果导出为 results/ai_results.json")
        return

    # 1. 合并
    merged = merge_results(human, ai)
    # 2. 各项指标
    overall = calc_overall_rate(merged)
    per_dim = calc_per_dim_rate(merged)
    confidence = calc_confidence_accuracy(merged)
    disagreements = find_disagreements(merged)
    # 3. 生成报告
    md = generate_markdown(overall, per_dim, confidence, disagreements, human.get("metadata", {}), ai.get("metadata", {}))
    html = generate_html(overall, per_dim, confidence, disagreements, human.get("metadata", {}), ai.get("metadata", {}))
    # 4. summary
    summary = {
        "generated_at": datetime.now().isoformat(),
        "overall": overall,
        "per_dim": per_dim,
        "confidence_accuracy": confidence,
        "disagreements": [{"case_id": d["case_id"], "human": d["human"], "ai": d["ai"]} for d in disagreements],
    }
    # 写入
    (output_dir / "report.md").write_text(md, encoding="utf-8")
    (output_dir / "report.html").write_text(html, encoding="utf-8")
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # 终端摘要
    print(f"\n{'=' * 60}")
    print(f"  校准分析完成")
    print(f"{'=' * 60}")
    print(f"  比对 case 总数：{overall['total']}")
    print(f"  AI 与人判断一致：{overall['matched']}")
    print(f"  一致率：{overall['rate_pct']}")
    print(f"  分歧 case 数：{len(disagreements)}")
    print(f"\n  报告输出：")
    print(f"    - {output_dir / 'report.md'}")
    print(f"    - {output_dir / 'report.html'}")
    print(f"    - {output_dir / 'summary.json'}")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
