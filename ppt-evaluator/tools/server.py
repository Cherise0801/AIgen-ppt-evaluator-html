"""
PPT 测评校准工具 - 本地 Flask 服务

启动：python server.py [--port 5050] [--cases ../cases] [--results ../results]

功能：
- 提供两两对比界面（compare.html）
- 读取 cases/ 目录下的所有 case（每个 case 一个子目录）
- 支持两种 variant 格式：HTML（直接渲染）和 PPTX（LibreOffice 转 PNG）
- 记录用户的人工盲测选择到 results/human_results.json
- 不暴露 a/b 的真实来源（自动匿名化为"方案 A"/"方案 B"），保证盲测公平

case 目录结构（混合格式）：
  cases/<case_id>/
    ├── input.txt            # 输入描述（必填，盲测时显示给用户）
    ├── a.html 或 a.pptx     # 方案 A（HTML 优先，没有 HTML 就用 PPTX）
    └── b.html 或 b.pptx     # 方案 B（同上）
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, abort, Response

# 允许从 tools/ 目录导入 render_pptx
sys.path.insert(0, str(Path(__file__).parent))
import render_pptx  # noqa: E402

app = Flask(__name__, static_folder=None)

# 全局路径（启动时由 main() 注入）
BASE_DIR = None
CASES_DIR = None
RESULTS_DIR = None
CACHE_DIR = None
HUMAN_RESULTS_FILE = None


# ============== 工具函数 ==============

def detect_variant_format(case_dir: Path, variant: str) -> str:
    """
    检测 variant 的格式：返回 "html" / "multi-html" / "pptx" / "missing"。

    优先级：
      1. a.html（单文件 HTML，权威）
      2. a/ 目录（多页 HTML 拼成的 PPT，每页一个独立 HTML 文件）
      3. a.pptx（PPTX，需 LibreOffice 渲染）
    """
    if (case_dir / f"{variant}.html").exists():
        return "html"
    if (case_dir / variant).is_dir() and any((case_dir / variant).glob("*.html")):
        return "multi-html"
    if (case_dir / f"{variant}.pptx").exists():
        return "pptx"
    return "missing"


def list_multi_html_pages(case_dir: Path, variant: str) -> list:
    """
    列出 a/ 或 b/ 目录下的所有 HTML 页面，按文件名排序。

    返回：[Path, Path, ...]（按页码顺序）
    """
    sub = case_dir / variant
    if not sub.is_dir():
        return []
    return sorted(sub.glob("*.html"))


def get_multi_html_pages(case_id: str, variant: str) -> list:
    """多 HTML 模式：返回 a/ 或 b/ 目录下所有 HTML 文件路径。"""
    if variant not in ("a", "b"):
        abort(400, "variant must be 'a' or 'b'")
    case_dir = CASES_DIR / case_id
    if not case_dir.exists():
        abort(404, f"case {case_id} not found")
    return list_multi_html_pages(case_dir, variant)


def load_cases():
    """
    扫描 cases/ 目录，列出所有合法 case。

    合法条件：A 和 B 都有（html 或 pptx 至少一种），input.txt 可选。
    返回：[{"case_id": "case-001", "has_input": True, "a_format": "html", "b_format": "pptx"}, ...]
    """
    cases = []
    if not CASES_DIR.exists():
        return cases
    for entry in sorted(CASES_DIR.iterdir()):
        if not entry.is_dir():
            continue
        case_id = entry.name
        has_input = (entry / "input.txt").exists()
        a_format = detect_variant_format(entry, "a")
        b_format = detect_variant_format(entry, "b")
        if a_format != "missing" and b_format != "missing":
            cases.append({
                "case_id": case_id,
                "has_input": has_input,
                "a_format": a_format,
                "b_format": b_format,
                "valid": True,
            })
    return cases


def read_input(case_id):
    """读取 case 的 input.txt 内容"""
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


def get_pptx_pages(case_id: str, variant: str) -> list:
    """
    获取 PPTX 的所有页 PNG 路径列表。

    返回：[Path, Path, ...]（按页码顺序）
    异常：LibreOffice 或 PyMuPDF 不可用时抛 RuntimeError。
    """
    if variant not in ("a", "b"):
        abort(400, "variant must be 'a' or 'b'")
    pptx_path = CASES_DIR / case_id / f"{variant}.pptx"
    if not pptx_path.exists():
        abort(404, f"{variant}.pptx not found in {case_id}")
    return render_pptx.render_pptx_to_pngs(pptx_path, variant, case_id)


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


@app.route("/api/health", methods=["GET"])
def api_health():
    """
    健康检查：返回依赖状态。

    前端启动时调用，根据 status 显示警告横幅（soft warning，不强制）。
    """
    lo_ok, lo_msg = render_pptx.check_libreoffice()
    pymupdf_ok, pymupdf_msg = render_pptx.check_pymupdf()
    # 统计有 PPTX 的 case 数
    pptx_case_count = sum(
        1 for c in load_cases()
        if c.get("a_format") == "pptx" or c.get("b_format") == "pptx"
    )
    needs_pptx_support = pptx_case_count > 0
    ready = (not needs_pptx_support) or (lo_ok and pymupdf_ok)
    return jsonify({
        "libreoffice": {"available": lo_ok, "message": lo_msg if not lo_ok else "OK"},
        "pymupdf": {"available": pymupdf_ok, "message": pymupdf_msg if not pymupdf_ok else "OK"},
        "pptx_case_count": pptx_case_count,
        "needs_pptx_support": needs_pptx_support,
        "ready": ready,
    })


@app.route("/api/cases", methods=["GET"])
def api_cases():
    """
    返回所有 case 列表。

    关键：只返回 case_id 和格式元信息，**不返回 a.html/b.html/a.pptx/b.pptx 的文件路径或内容**。
    前端只能通过 /api/case/<id>/render/<variant> 获取渲染内容，且 variant 只能是 a/b。
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
    返回 variant 的渲染信息。

    HTML：直接返回 text/html，前端用 <iframe> 渲染。
    PPTX：返回 JSON，前端根据 type 走缩略图网格 + 点击放大。

    返回格式：
      - HTML：text/html 响应（HTML 源码）
      - PPTX：application/json，包含 pages 列表（每页一个图片 URL）
    """
    if variant not in ("a", "b"):
        abort(400, "variant must be 'a' or 'b'")
    case_dir = CASES_DIR / case_id
    if not case_dir.exists():
        abort(404, f"case {case_id} not found")

    fmt = detect_variant_format(case_dir, variant)
    if fmt == "html":
        return Response(read_html(case_id, variant), mimetype="text/html")
    elif fmt == "multi-html":
        html_paths = get_multi_html_pages(case_id, variant)
        pages = [
            {"page": i + 1, "url": f"/api/case/{case_id}/page/{variant}/{i + 1}"}
            for i in range(len(html_paths))
        ]
        return jsonify({"type": "multi-html", "pages": pages, "page_count": len(html_paths)})
    elif fmt == "pptx":
        try:
            png_paths = get_pptx_pages(case_id, variant)
        except RuntimeError as e:
            return jsonify({"error": "pptx_render_failed", "message": str(e)}), 500
        # 构造 URL 列表（每页一个图片 URL）
        pages = [
            {"page": i + 1, "url": f"/api/case/{case_id}/page/{variant}/{i + 1}"}
            for i in range(len(png_paths))
        ]
        return jsonify({"type": "pptx", "pages": pages, "page_count": len(png_paths)})
    else:
        abort(404, f"{variant} file not found in {case_id}")


@app.route("/api/case/<case_id>/page/<variant>/<int:page_num>", methods=["GET"])
def api_case_page(case_id, variant, page_num):
    """
    统一分页端点。

    - PPTX 模式：返回该页的 PNG 图片（image/png）。
    - multi-html 模式：返回该页的 HTML 源码（text/html）。

    compare.html 同时支持 iframe（HTML）和 img（PNG）两种缩略图渲染。
    """
    if variant not in ("a", "b"):
        abort(400, "variant must be 'a' or 'b'")
    case_dir = CASES_DIR / case_id
    if not case_dir.exists():
        abort(404, f"case {case_id} not found")
    fmt = detect_variant_format(case_dir, variant)
    if fmt == "pptx":
        try:
            png_paths = get_pptx_pages(case_id, variant)
        except RuntimeError as e:
            return jsonify({"error": "pptx_render_failed", "message": str(e)}), 500
        if page_num < 1 or page_num > len(png_paths):
            abort(404, f"page {page_num} out of range (1-{len(png_paths)})")
        return send_file(png_paths[page_num - 1], mimetype="image/png")
    elif fmt == "multi-html":
        html_paths = get_multi_html_pages(case_id, variant)
        if page_num < 1 or page_num > len(html_paths):
            abort(404, f"page {page_num} out of range (1-{len(html_paths)})")
        return Response(html_paths[page_num - 1].read_text(encoding="utf-8"), mimetype="text/html")
    else:
        abort(404, f"{variant} not a paginated format in {case_id}")


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


# 修复 send_file 在最新 Flask 里的导入问题
from flask import send_file  # noqa: E402


# ============== 启动 ==============

def main():
    global BASE_DIR, CASES_DIR, RESULTS_DIR, CACHE_DIR, HUMAN_RESULTS_FILE

    parser = argparse.ArgumentParser(description="PPT 测评校准工具 - 本地服务")
    parser.add_argument("--port", type=int, default=5050, help="服务端口（默认 5050）")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="绑定地址（默认 127.0.0.1，本地访问）")
    parser.add_argument("--cases", type=str, default="../cases", help="cases 目录路径（相对于 tools/）")
    parser.add_argument("--results", type=str, default="../results", help="结果输出目录（相对于 tools/）")
    parser.add_argument("--cache", type=str, default="../.cache", help="PPTX 渲染缓存目录（相对于 tools/）")
    args = parser.parse_args()

    BASE_DIR = Path(__file__).parent.resolve()
    CASES_DIR = (BASE_DIR / args.cases).resolve()
    RESULTS_DIR = (BASE_DIR / args.results).resolve()
    CACHE_DIR = (BASE_DIR / args.cache).resolve()
    HUMAN_RESULTS_FILE = RESULTS_DIR / "human_results.json"

    # 注入 render_pptx 的缓存根目录
    render_pptx.set_cache_root(CACHE_DIR)

    # 启动提示
    cases = load_cases()
    lo_ok, lo_msg = render_pptx.check_libreoffice()
    pymupdf_ok, pymupdf_msg = render_pptx.check_pymupdf()
    pptx_count = sum(1 for c in cases if c.get("a_format") == "pptx" or c.get("b_format") == "pptx")

    print(f"\n{'=' * 60}")
    print(f"  PPT 测评校准工具 - 本地服务")
    print(f"{'=' * 60}")
    print(f"  cases 目录：  {CASES_DIR}")
    print(f"  结果输出：    {HUMAN_RESULTS_FILE}")
    print(f"  PPTX 缓存：   {CACHE_DIR}")
    print(f"  加载到 {len(cases)} 个 case（含 {pptx_count} 个 PPTX case）：")
    for c in cases:
        print(f"    - {c['case_id']}  (A={c['a_format']}, B={c['b_format']})")
    print(f"\n  依赖状态：")
    print(f"    LibreOffice: {'✓' if lo_ok else '✗'} {lo_msg if not lo_ok else ''}")
    print(f"    PyMuPDF:     {'✓' if pymupdf_ok else '✗'} {pymupdf_msg if not pymupdf_ok else ''}")
    if pptx_count > 0 and not (lo_ok and pymupdf_ok):
        print(f"\n  ⚠️  检测到 {pptx_count} 个 PPTX case 但 LibreOffice/PyMuPDF 不可用")
        print(f"     PPTX 渲染将失败，请按上面提示安装依赖")
    print(f"\n  → 浏览器打开：http://{args.host}:{args.port}")
    print(f"{'=' * 60}\n")

    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
