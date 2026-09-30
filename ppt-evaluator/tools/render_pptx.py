"""
PPTX → 每页 PNG 转换器

依赖：
- LibreOffice（必需）：`brew install --cask libreoffice` 或官网下载
  - macOS: `/Applications/LibreOffice.app/Contents/MacOS/soffice`
  - Linux: `soffice`（apt 装 libreoffice）
  - Windows: `soffice.exe`（PATH 里有）
- PyMuPDF：`pip install pymupdf`（~15MB，纯 Python，无需 Poppler）

工作流：
  1. 检测 LibreOffice 是否安装
  2. soffice --headless --convert-to pdf a.pptx → a.pdf
  3. PyMuPDF 打开 PDF，逐页渲染为 150 DPI PNG
  4. 缓存到 .cache/<case_id>/<variant>/page_NN.png，文件 mtime 变化才重转
"""

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

# 缓存根目录（启动时由 server.py 注入）
CACHE_ROOT: Optional[Path] = None

# LibreOffice 候选路径
SOFFICE_CANDIDATES = [
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",  # macOS
    "/usr/bin/soffice",  # Linux
    "/usr/local/bin/soffice",  # Linux alt
    "soffice",  # PATH 兜底
    "soffice.exe",  # Windows
]


def find_soffice() -> Optional[str]:
    """
    查找 LibreOffice 可执行文件路径。

    返回：找到则返回绝对路径或命令名，未找到返回 None。
    """
    for cand in SOFFICE_CANDIDATES:
        if os.path.isabs(cand) and os.path.exists(cand):
            return cand
        # PATH 里的命令（shutil.which 兜底）
        resolved = shutil.which(cand)
        if resolved:
            return resolved
    return None


def check_pymupdf():
    """
    检查 PyMuPDF 是否安装。

    返回：(bool, str)：第一个是是否可用，第二个是安装提示。
    """
    try:
        import fitz  # PyMuPDF
        return True, ""
    except ImportError:
        return False, "请运行：pip install pymupdf"


def check_libreoffice():
    """
    检查 LibreOffice 是否安装。

    返回：(bool, str)：第一个是是否可用，第二个是安装提示。
    """
    soffice = find_soffice()
    if soffice:
        return True, soffice
    return False, (
        "未检测到 LibreOffice。安装方式：\n"
        "  - macOS:   brew install --cask libreoffice\n"
        "  - Ubuntu:  sudo apt install -y libreoffice\n"
        "  - Windows: 官网下载 https://www.libreoffice.org/download\n"
        "安装后请重新启动服务。"
    )


def convert_pptx_to_pdf(pptx_path: Path, work_dir: Path, soffice: str) -> Path:
    """
    用 LibreOffice 把 PPTX 转 PDF。

    返回：PDF 路径。
    异常：subprocess 失败时抛 RuntimeError。
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    # LibreOffice 输出目录指定为 work_dir，文件名 = 原 stem + .pdf
    cmd = [
        soffice,
        "--headless",          # 无界面
        "--norestore",          # 不恢复上次会话
        "--nologo",             # 不显示 logo
        "--nodefault",          # 不启动默认服务
        "--nofirststartwizard",
        "--convert-to", "pdf",
        "--outdir", str(work_dir),
        str(pptx_path),
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,  # 2 分钟超时
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"LibreOffice 转换失败 (exit={proc.returncode})\n"
            f"stdout: {proc.stdout}\n"
            f"stderr: {proc.stderr}"
        )
    pdf_path = work_dir / (pptx_path.stem + ".pdf")
    if not pdf_path.exists():
        raise RuntimeError(
            f"LibreOffice 转换完成但未找到 PDF 文件：{pdf_path}\n"
            f"stdout: {proc.stdout}\n"
            f"stderr: {proc.stderr}"
        )
    return pdf_path


def render_pdf_to_pngs(pdf_path: Path, out_dir: Path, dpi: int = 150) -> List[Path]:
    """
    用 PyMuPDF 把 PDF 逐页渲染为 PNG。

    返回：PNG 文件路径列表（按页码顺序）。
    """
    import fitz  # PyMuPDF
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    # 预计算缩放矩阵：dpi / 72（PDF 默认 72 DPI）
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    png_paths = []
    for i, page in enumerate(doc, start=1):
        pix = page.get_pixmap(matrix=matrix, alpha=False)  # alpha=False 避免透明
        png_path = out_dir / f"page_{i:02d}.png"
        pix.save(png_path)
        png_paths.append(png_path)
    doc.close()
    return png_paths


def get_cache_key(pptx_path: Path) -> str:
    """根据文件路径 + mtime + 大小生成 cache key"""
    stat = pptx_path.stat()
    raw = f"{pptx_path.absolute()}|{stat.st_mtime}|{stat.st_size}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def render_pptx_to_pngs(pptx_path: Path, variant: str, case_id: str) -> List[Path]:
    """
    主入口：把 PPTX 转换为 PNG 列表（带缓存）。

    Args:
        pptx_path: PPTX 文件路径
        variant: "a" 或 "b"
        case_id: case 目录名

    Returns:
        PNG 文件路径列表（绝对路径），按页码顺序
    """
    if CACHE_ROOT is None:
        raise RuntimeError("CACHE_ROOT 未设置，请先调用 set_cache_root()")
    if not pptx_path.exists():
        raise FileNotFoundError(f"PPTX 文件不存在：{pptx_path}")

    # 1. 检查依赖
    soffice_ok, soffice_msg = check_libreoffice()
    if not soffice_ok:
        raise RuntimeError(f"LibreOffice 不可用：{soffice_msg}")
    pymupdf_ok, pymupdf_msg = check_pymupdf()
    if not pymupdf_ok:
        raise RuntimeError(f"PyMuPDF 不可用：{pymupdf_msg}")

    # 2. 缓存目录
    cache_key = get_cache_key(pptx_path)
    cache_dir = CACHE_ROOT / case_id / variant / cache_key
    cache_meta = cache_dir / "meta.json"

    # 3. 命中缓存
    if cache_meta.exists():
        # 检查所有 PNG 是否齐全
        existing = sorted(cache_dir.glob("page_*.png"))
        if existing:
            # 用 meta 记录的实际页数校验
            import json
            try:
                meta = json.loads(cache_meta.read_text(encoding="utf-8"))
                if meta.get("page_count") == len(existing):
                    return existing
            except Exception:
                pass  # meta 损坏，重转

    # 4. 转换 PPTX → PDF
    work_dir = cache_dir / "_work"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    pdf_path = convert_pptx_to_pdf(pptx_path, work_dir, soffice_msg)

    # 5. 渲染 PDF → PNG
    pngs = render_pdf_to_pngs(pdf_path, cache_dir, dpi=150)

    # 6. 写 meta
    import json
    cache_meta.write_text(
        json.dumps({
            "source_pptx": str(pptx_path.absolute()),
            "cache_key": cache_key,
            "page_count": len(pngs),
            "generated_at": __import__("datetime").datetime.now().isoformat(),
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 7. 清理 work_dir
    shutil.rmtree(work_dir, ignore_errors=True)

    return pngs


def set_cache_root(path: Path):
    """全局设置缓存根目录（由 server.py 在启动时调用）"""
    global CACHE_ROOT
    CACHE_ROOT = path
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)


# ============== CLI 模式（手动测试用） ==============

def main():
    """CLI 入口：手动测试转换"""
    import argparse
    parser = argparse.ArgumentParser(description="PPTX → PNG 转换测试")
    parser.add_argument("pptx", help="PPTX 文件路径")
    parser.add_argument("--cache", default="./.cache", help="缓存目录")
    parser.add_argument("--variant", default="a", help="variant 标识（a/b）")
    parser.add_argument("--case-id", default="manual", help="case id")
    args = parser.parse_args()

    set_cache_root(Path(args.cache).resolve())
    try:
        pngs = render_pptx_to_pngs(Path(args.pptx).resolve(), args.variant, args.case_id)
        print(f"\n✓ 转换完成，共 {len(pngs)} 页：")
        for p in pngs:
            print(f"  - {p}")
        print(f"\n  缓存目录：{CACHE_ROOT}")
    except Exception as e:
        print(f"\n❌ 转换失败：{e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
