"""
PPT 测评校准工具 - Case 库版后端。

核心抽象：每个 case 是一份独立 PPT（多页 HTML 集合），盲测时从库中任选 2 个做对比。

API：
  GET  /api/health                  健康检查 + 依赖状态
  GET  /api/library                 列出所有 case（含 _library.json 元信息 + 实际文件数）
  GET  /api/case/<id>               获取单 case 元信息
  GET  /api/case/<id>/input         获取 case 的输入描述
  GET  /api/case/<id>/pages         返回该 case 的所有页（每页 URL）
  GET  /api/case/<id>/page/<n>      返回单页 HTML 文本（text/html）
  POST /api/compare/select          记录用户盲测选择 {case_a, case_b, chosen, confidence}
  GET  /api/results                 返回所有人工盲测结果
  POST /api/reset                   清空盲测结果
  POST /api/case/upload             上传新 case（multipart: case_id, files[]）

匿名化机制：
  前端在请求时附 ?seed=<random>，服务端用 hash(seed + case_id) 生成 6 位 code。
  同一 seed 下，case_id ↔ code 映射稳定。
  前端只在 UI 显示 code，从不显示真实 case_id。
"""

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from flask import Flask, Response, abort, jsonify, request
from werkzeug.utils import secure_filename

import render_pptx

TOOLS_DIR = Path(__file__).parent
WORKSPACE_DIR = TOOLS_DIR.parent
CASES_DIR = WORKSPACE_DIR / "cases"
RESULTS_DIR = WORKSPACE_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)
HUMAN_RESULTS_PATH = RESULTS_DIR / "human_results.json"
LIBRARY_PATH = CASES_DIR / "_library.json"

app = Flask(__name__, static_folder=str(TOOLS_DIR / "static"))
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200MB 上传限制

# ---------- case 库管理 ----------

def load_library() -> dict:
    """读取 _library.json 索引。如果不存在，自动从 cases/ 目录扫描重建。"""
    if LIBRARY_PATH.exists():
        return json.loads(LIBRARY_PATH.read_text(encoding="utf-8"))
    # 兜底扫描
    cases = []
    for case_dir in sorted(CASES_DIR.iterdir()):
        if not case_dir.is_dir() or case_dir.name.startswith("_") or case_dir.name.startswith("."):
            continue
        html_files = sorted(case_dir.glob("*.html"))
        if html_files:
            cases.append({
                "case_id": case_dir.name,
                "source": "html",
                "page_count": len(html_files),
                "input": "",
                "tags": [],
            })
    return {"version": "1", "cases": cases}


def save_library(library: dict):
    LIBRARY_PATH.write_text(json.dumps(library, ensure_ascii=False, indent=2), encoding="utf-8")


def get_case_meta(case_id: str) -> Optional[dict]:
    """从 _library.json 找 case 元信息，找不到返回 None。"""
    for c in load_library().get("cases", []):
        if c["case_id"] == case_id:
            return c
    return None


def get_case_dir(case_id: str) -> Optional[Path]:
    """校验 case_id 防止路径穿越，返回目录或 None。"""
    if not re.match(r"^[A-Za-z0-9_\-]+$", case_id):
        return None
    d = CASES_DIR / case_id
    return d if d.is_dir() else None


def list_html_pages(case_id: str) -> List[Path]:
    """列出 case 目录下所有 HTML 文件，按文件名排序。"""
    case_dir = get_case_dir(case_id)
    if not case_dir:
        return []
    return sorted(case_dir.glob("*.html"))


def get_next_case_id() -> str:
    """根据 cases/ 现有目录返回下一个 case-XXX。"""
    existing = []
    for d in CASES_DIR.iterdir():
        if d.is_dir() and d.name.startswith("case-"):
            m = re.match(r"case-(\d+)", d.name)
            if m:
                existing.append(int(m.group(1)))
    n = max(existing, default=0) + 1
    return f"case-{n:03d}"


# ---------- 匿名化 ----------

def anonymous_code(case_id: str, seed: str) -> str:
    """用 hash(seed + case_id) 生成 6 位大写字母数字 code。"""
    h = hashlib.sha256(f"{seed}::{case_id}".encode()).hexdigest().upper()
    return h[:6]


# ---------- 健康检查 ----------

@app.route("/api/health", methods=["GET"])
def api_health():
    """健康检查 + 依赖状态。"""
    lo_ok, lo_msg = render_pptx.check_libreoffice()
    pymupdf_ok, pymupdf_msg = render_pptx.check_pymupdf()
    return jsonify({
        "libreoffice": {"available": lo_ok, "message": lo_msg if not lo_ok else "OK"},
        "pymupdf": {"available": pymupdf_ok, "message": pymupdf_msg if not pymupdf_ok else "OK"},
        "case_count": len(load_library().get("cases", [])),
    })


# ---------- case 库 API ----------

@app.route("/api/library", methods=["GET"])
def api_library():
    """返回所有 case 列表 + 匿名化映射。

    返回结构：
      cases: [{code, page_count, input, tags, first_page_title}, ...]  ← UI 展示用
      code_to_case: {code: case_id, ...}  ← 前端反查用（不展示在 UI 上）
    """
    seed = request.args.get("seed", "default-seed")
    cases = load_library().get("cases", [])
    enriched = []
    code_to_case = {}
    for c in cases:
        pages = list_html_pages(c["case_id"])
        if not pages:
            continue
        code = anonymous_code(c["case_id"], seed)
        enriched.append({
            "code": code,
            "page_count": len(pages),
            "input": c.get("input", ""),
            "tags": c.get("tags", []),
            "first_page_title": _peek_first_title(pages[0]),
        })
        code_to_case[code] = c["case_id"]
    return jsonify({
        "cases": enriched,
        "total": len(enriched),
        "seed": seed,
        "code_to_case": code_to_case,
    })


def _peek_first_title(html_path: Path) -> str:
    """从首页 HTML 提取第一个 h1/title 用于 UI 提示。"""
    try:
        text = html_path.read_text(encoding="utf-8", errors="ignore")
        # 优先匹配 h1.r-title（WPS AIPPT 标准结构）
        m = re.search(r'<h1[^>]*class=["\']r-title["\'][^>]*>([^<]+)<', text)
        if m:
            return m.group(1).strip()[:30]
        m = re.search(r'<title>([^<]+)</title>', text)
        if m:
            return m.group(1).strip()[:30]
        m = re.search(r'<h1[^>]*>([^<]+)<', text)
        if m:
            return m.group(1).strip()[:30]
    except Exception:
        pass
    return html_path.name[:30]


@app.route("/api/case/<case_id>/input", methods=["GET"])
def api_case_input(case_id):
    """返回 case 的输入描述（input 字段）。"""
    meta = get_case_meta(case_id)
    if not meta:
        abort(404, f"case {case_id} not in library")
    return jsonify({"case_id": case_id, "input": meta.get("input", "")})


@app.route("/api/case/<case_id>/pages", methods=["GET"])
def api_case_pages(case_id):
    """返回 case 所有页 URL 列表。"""
    pages = list_html_pages(case_id)
    if not pages:
        abort(404, f"case {case_id} has no HTML pages")
    return jsonify({
        "case_id": case_id,
        "pages": [
            {"page": i + 1, "url": f"/api/case/{case_id}/page/{i + 1}"}
            for i in range(len(pages))
        ],
        "page_count": len(pages),
    })


@app.route("/api/case/<case_id>/page/<int:page_num>", methods=["GET"])
def api_case_page(case_id, page_num):
    """返回单页 HTML 文本。"""
    pages = list_html_pages(case_id)
    if not pages:
        abort(404, f"case {case_id} not found")
    if page_num < 1 or page_num > len(pages):
        abort(404, f"page {page_num} out of range (1-{len(pages)})")
    return Response(pages[page_num - 1].read_text(encoding="utf-8"), mimetype="text/html")


# ---------- 盲测选择 API ----------

def _load_human_results() -> dict:
    if HUMAN_RESULTS_PATH.exists():
        data = json.loads(HUMAN_RESULTS_PATH.read_text(encoding="utf-8"))
        # 向后兼容旧数据结构（selections → comparisons）
        if "selections" in data and "comparisons" not in data:
            data["comparisons"] = data.pop("selections")
        data.setdefault("comparisons", [])
        return data
    return {"comparisons": [], "metadata": {"created_at": datetime.now().isoformat()}}


def _save_human_results(data: dict):
    data.setdefault("metadata", {})
    data["metadata"]["updated_at"] = datetime.now().isoformat()
    data["metadata"]["total"] = len(data.get("comparisons", []))
    HUMAN_RESULTS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@app.route("/api/compare/select", methods=["POST"])
def api_compare_select():
    """
    记录用户盲测选择。

    Body: {case_a: "case-003", case_b: "case-004", chosen: "case-003" | "case-004", confidence: 1-5, anon_a, anon_b}

    注：前端用匿名 code 选择，但提交时需把 code 映射回 case_id（前端在 /api/library 已拿到 code→input 映射，
    但不能拿到 code→case_id 映射以保持匿名）。
    解决：前端在 library 返回时同时拿到 case_id 与 code 的映射，提交时前端做 code→case_id 反查。
    """
    payload = request.get_json(force=True)
    case_a = payload.get("case_a")
    case_b = payload.get("case_b")
    chosen = payload.get("chosen")
    confidence = payload.get("confidence")

    if not (case_a and case_b and chosen in (case_a, case_b)):
        abort(400, "invalid payload: case_a, case_b, chosen (must equal case_a or case_b) required")
    if not get_case_meta(case_a) or not get_case_meta(case_b):
        abort(404, "case_a or case_b not in library")

    data = _load_human_results()
    data["comparisons"].append({
        "case_a": case_a,
        "case_b": case_b,
        "chosen": chosen,
        "confidence": confidence,
        "timestamp": datetime.now().isoformat(),
    })
    _save_human_results(data)
    return jsonify({"ok": True, "total": len(data["comparisons"])})


@app.route("/api/results", methods=["GET"])
def api_results():
    return jsonify(_load_human_results())


@app.route("/api/reset", methods=["POST"])
def api_reset():
    data = {"comparisons": [], "metadata": {"created_at": datetime.now().isoformat()}}
    _save_human_results(data)
    return jsonify({"ok": True, "total": 0})


# ---------- 上传 case ----------

ALLOWED_HTML_EXT = {".html", ".htm"}


@app.route("/api/case/upload", methods=["POST"])
def api_case_upload():
    """
    上传新 case。
    Form: case_id (可选，不传自动生成), files[] (多个 .html)
    """
    files = request.files.getlist("files")
    if not files:
        abort(400, "no files uploaded")
    case_id = request.form.get("case_id", "").strip()
    if not case_id:
        case_id = get_next_case_id()
    if not re.match(r"^[A-Za-z0-9_\-]+$", case_id):
        abort(400, "invalid case_id (alphanumeric, dash, underscore only)")
    case_dir = CASES_DIR / case_id
    if case_dir.exists():
        abort(409, f"case {case_id} already exists")
    case_dir.mkdir(parents=True)

    saved = []
    for f in files:
        if not f.filename:
            continue
        ext = Path(f.filename).suffix.lower()
        if ext not in ALLOWED_HTML_EXT:
            continue
        # 用 secure_filename 处理中文文件名（保持原中文）
        # secure_filename 对中文会转 ASCII，所以保留原名
        safe_name = Path(f.filename).name
        target = case_dir / safe_name
        f.save(target)
        saved.append(safe_name)

    if not saved:
        import shutil
        shutil.rmtree(case_dir)
        abort(400, "no valid .html files uploaded")

    # 更新 library
    lib = load_library()
    lib.setdefault("cases", []).append({
        "case_id": case_id,
        "source": "html",
        "page_count": len(saved),
        "input": request.form.get("input", ""),
        "tags": [],
        "created_at": datetime.now().isoformat(),
    })
    save_library(lib)

    return jsonify({"ok": True, "case_id": case_id, "page_count": len(saved), "files": saved})


# ---------- 根路由 ----------

@app.route("/")
def index():
    return app.send_static_file("../compare.html") if False else Response(
        (TOOLS_DIR / "compare.html").read_text(encoding="utf-8"),
        mimetype="text/html",
    )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    print(f"📂 cases/  → {CASES_DIR}")
    print(f"📊 results/ → {RESULTS_DIR}")
    print(f"📚 library: {len(load_library().get('cases', []))} cases")
    print(f"🚀 Starting on http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)
