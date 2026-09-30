"""
PPT 测评校准工具 - 本地 Flask 服务

启动：python server.py [--port 5050] [--cases ../cases] [--results ../results]

功能：
- 提供两两对比界面（compare.html）
- 读取 cases/ 目录下的所有 case（每个 case 一个子目录，含 input.txt + a.html + b.html）
- 记录用户的人工盲测选择到 results/human_results.json
- 不暴露 a/b 的真实来源（自动匿名化为"方案 A"/"方案 B"），保证盲测公平
"""

import argparse
import json
import os
import random
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, abort

app = Flask(__name__, static_folder=None)

# 全局路径（启动时由 main() 注入）
BASE_DIR = None
CASES_DIR = None
RESULTS_DIR = None
HUMAN_RESULTS_FILE = None


# ============== 工具函数 ==============

def load_cases():
    """
    扫描 cases/ 目录，列出所有合法 case。

    每个 case 是 cases/<case_id>/ 子目录，至少包含：
      - input.txt：输入描述
      - a.html：方案 A（生成结果 1）
      - b.html：方案 B（生成结果 2）

    返回：[{"case_id": "case-001", "has_input": True}, ...]
    排序：按 case_id 字符串升序，确保每次跑顺序一致（不随机，避免主观偏好随位置漂移）
    """
    cases = []
    if not CASES_DIR.exists():
        return cases
    for entry in sorted(CASES_DIR.iterdir()):
        if not entry.is_dir():
            continue
        case_id = entry.name
        has_input = (entry / "input.txt").exists()
        has_a = (entry / "a.html").exists()
        has_b = (entry / "b.html").exists()
        if has_a and has_b:
            cases.append({
                "case_id": case_id,
                "has_input": has_input,
                "valid": True,
            })
    return cases


def read_input(case_id):
    """读取 case 的 input.txt 内容（给前端展示，不参与评分）"""
    path = CASES_DIR / case_id / "input.txt"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def read_html(case_id, variant):
    """读取 a.html 或 b.html 原始内容（给前端 iframe 渲染用）"""
    if variant not in ("a", "b"):
        abort(400, "variant must be 'a' or 'b'")
    path = CASES_DIR / case_id / f"{variant}.html"
    if not path.exists():
        abort(404, f"{variant}.html not found in {case_id}")
    return path.read_text(encoding="utf-8")


def load_human_results():
    """读取已有的人盲测结果（如果存在）"""
    if not HUMAN_RESULTS_FILE.exists():
        return {"selections": [], "metadata": {"created_at": datetime.now().isoformat()}}
    try:
        return json.loads(HUMAN_RESULTS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # 文件损坏时备份并重置
        backup = HUMAN_RESULTS_FILE.with_suffix(".json.bak")
        HUMAN_RESULTS_FILE.rename(backup)
        return {"selections": [], "metadata": {"created_at": datetime.now().isoformat()}}


def save_human_results(data):
    """保存人盲测结果"""
    HUMAN_RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    HUMAN_RESULTS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


# ============== 路由 ==============

@app.route("/")
def index():
    """主页：对比界面"""
    return send_from_directory(BASE_DIR, "compare.html")


@app.route("/api/cases", methods=["GET"])
def api_cases():
    """
    返回所有 case 列表。

    关键：这里只返回 case_id 和 has_input 标志，**不返回 a.html/b.html 的文件路径或内容**，
    前端只能通过 /api/render/<case_id>/<variant> 获取渲染内容，且 variant 只能是 a/b（无文件元信息）。
    """
    cases = load_cases()
    return jsonify({"cases": cases, "total": len(cases)})


@app.route("/api/case/<case_id>/input", methods=["GET"])
def api_case_input(case_id):
    """获取 case 的 input.txt（给前端展示给用户看的输入描述）"""
    return jsonify({"case_id": case_id, "input": read_input(case_id)})


@app.route("/api/case/<case_id>/render/<variant>", methods=["GET"])
def api_case_render(case_id, variant):
    """
    返回 a.html 或 b.html 原始内容，给 iframe 渲染。

    返回 text/html 响应，浏览器直接当 HTML 渲染。等价于"用户看到的跟 HTML 渲染出来的一样"。
    """
    html_content = read_html(case_id, variant)
    # 直接返回 HTML，前端用 <iframe src="..."> 加载
    from flask import Response
    return Response(html_content, mimetype="text/html")


@app.route("/api/select", methods=["POST"])
def api_select():
    """
    接收用户的人工盲测选择。

    Body: {"case_id": "case-001", "chosen": "A" | "B", "confidence": 1-5 (可选)}
    """
    payload = request.get_json(force=True)
    case_id = payload.get("case_id")
    chosen = payload.get("chosen")
    confidence = payload.get("confidence", None)

    if not case_id or chosen not in ("A", "B"):
        return jsonify({"error": "case_id and chosen (A|B) required"}), 400

    data = load_human_results()
    # 去重：如果该 case 已有选择，覆盖并记录
    data["selections"] = [s for s in data["selections"] if s["case_id"] != case_id]
    data["selections"].append({
        "case_id": case_id,
        "chosen": chosen,
        "confidence": confidence,
        "timestamp": datetime.now().isoformat(),
    })
    data["metadata"]["updated_at"] = datetime.now().isoformat()
    data["metadata"]["total"] = len(data["selections"])
    save_human_results(data)

    return jsonify({"ok": True, "total": len(data["selections"])})


@app.route("/api/results", methods=["GET"])
def api_results():
    """返回所有人盲测结果（前端可视化 + analyze.py 用）"""
    data = load_human_results()
    cases = load_cases()
    completed = {s["case_id"] for s in data["selections"]}
    pending = [c["case_id"] for c in cases if c["case_id"] not in completed]
    return jsonify({
        "selections": data["selections"],
        "metadata": data.get("metadata", {}),
        "pending_case_ids": pending,
        "completed_case_ids": sorted(completed),
        "progress": {
            "completed": len(completed),
            "total": len(cases),
            "percent": round(len(completed) / len(cases) * 100, 1) if cases else 0,
        }
    })


@app.route("/api/reset", methods=["POST"])
def api_reset():
    """清空所有人盲测结果（重置用）"""
    if HUMAN_RESULTS_FILE.exists():
        backup = HUMAN_RESULTS_FILE.with_suffix(f".json.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}")
        HUMAN_RESULTS_FILE.rename(backup)
    save_human_results({"selections": [], "metadata": {"created_at": datetime.now().isoformat(), "reset": True}})
    return jsonify({"ok": True, "message": "reset done"})


@app.route("/static/<path:filename>")
def static_files(filename):
    """暴露 static/ 目录（echarts 等本地依赖）"""
    return send_from_directory(BASE_DIR / "static", filename)


# ============== 启动 ==============

def main():
    global BASE_DIR, CASES_DIR, RESULTS_DIR, HUMAN_RESULTS_FILE

    parser = argparse.ArgumentParser(description="PPT 测评校准工具 - 本地服务")
    parser.add_argument("--port", type=int, default=5050, help="服务端口（默认 5050）")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="绑定地址（默认 127.0.0.1，本地访问）")
    parser.add_argument("--cases", type=str, default="../cases", help="cases 目录路径（相对于 tools/）")
    parser.add_argument("--results", type=str, default="../results", help="结果输出目录（相对于 tools/）")
    args = parser.parse_args()

    BASE_DIR = Path(__file__).parent.resolve()
    CASES_DIR = (BASE_DIR / args.cases).resolve()
    RESULTS_DIR = (BASE_DIR / args.results).resolve()
    HUMAN_RESULTS_FILE = RESULTS_DIR / "human_results.json"

    # 启动提示
    cases = load_cases()
    print(f"\n{'=' * 60}")
    print(f"  PPT 测评校准工具 - 本地服务")
    print(f"{'=' * 60}")
    print(f"  cases 目录：  {CASES_DIR}")
    print(f"  结果输出：    {HUMAN_RESULTS_FILE}")
    print(f"  加载到 {len(cases)} 个 case：")
    for c in cases:
        print(f"    - {c['case_id']}")
    print(f"\n  → 浏览器打开：http://{args.host}:{args.port}")
    print(f"{'=' * 60}\n")

    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
