# tools/ - 本地校准工具

用于"人工盲测"和"AI vs 人工对比分析"的本地程序，不依赖任何外部服务。

支持三种 case 格式：
- **单文件 HTML**（直接 iframe 渲染）
- **多页 HTML 目录**（`a/` `b/` 子目录，每页一个 HTML，工具自动拼成"翻页 PPT"）
- **PPTX**（LibreOffice 转 PNG，需额外依赖）

## 工作流程

```
┌────────────────────────────────────────────────────────┐
│  1. 准备 cases（HTML 或 PPTX 均可，混用也行）           │
│     - 每个 case 一个子目录                             │
│     - 含 input.txt（输入描述）                          │
│     - 含 a.{html|pptx} 或 a/（方案 A）                 │
│     - 含 b.{html|pptx} 或 b/（方案 B）                 │
└────────────────────────────────────────────────────────┘
                          ↓
┌────────────────────────────────────────────────────────┐
│  2. 启动 server.py                                     │
│     python tools/server.py                             │
│     → 浏览器打开 http://127.0.0.1:5050                  │
│     → HTML 走 iframe，PPTX 走缩略图网格 + 点击放大      │
│     → 结果自动存到 results/human_results.json           │
└────────────────────────────────────────────────────────┘
                          ↓
┌────────────────────────────────────────────────────────┐
│  3. 跑 AI 测评（用本 Skill）                            │
│     - 用 /ppt-blind 对每对 case 跑一遍                  │
│     - 把结果整理为 results/ai_results.json              │
│     - 格式见本 README 下文                              │
└────────────────────────────────────────────────────────┘
                          ↓
┌────────────────────────────────────────────────────────┐
│  4. 对比分析                                            │
│     python tools/analyze.py                            │
│     → 生成 report.md / report.html / summary.json       │
│     → 包含：一致率、分维度准确率、分歧 case 清单        │
└────────────────────────────────────────────────────────┘
```

## case 目录结构

工具按以下优先级自动识别 case 格式：

| 优先级 | 方案 A 路径 | 方案 B 路径 | 工具识别 |
|--------|------------|------------|----------|
| 1 | `a.html` | `b.html` | 单文件 HTML（iframe 整页渲染） |
| 2 | `a/` 目录 | `b/` 目录 | 多页 HTML（缩略图网格 + 翻页灯箱） |
| 3 | `a.pptx` | `b.pptx` | PPTX（缩略图网格 + 灯箱） |

### 多页 HTML 模式说明

适用场景：用户用 AI 工具（如 WPS AIPPT）批量生成的"单页 HTML 拼成的 PPT"。每个 HTML 是独立幻灯片，工具按文件名排序拼成可翻页 PPT。

**目录结构**：
```
cases/case-001/
├── input.txt
├── a/
│   ├── 第1页.html
│   ├── 第2页.html
│   └── ...第N页.html
└── b/
    ├── 第1页.html
    └── ...
```

文件名按字典序排序，建议用 `第1页.html`、`第2页.html` 这种带前导零或前导数字的命名以保证顺序正确。

## 安装

### 基础依赖（HTML 模式必需）

```bash
pip install flask
```

### PPTX 渲染依赖（PPTX 模式必需）

```bash
# 1. PyMuPDF（PDF → PNG）
pip install pymupdf

# 2. LibreOffice（PPTX → PDF）
# macOS
brew install --cask libreoffice
# Ubuntu/Debian
sudo apt install -y libreoffice
# Windows：官网下载 https://www.libreoffice.org/download/
```

**PPTX 模式是可选的**：
- 没装 LibreOffice/PyMuPDF：HTML case 正常用，PPTX case 渲染会失败并在 UI 上提示
- 装好之后：无需改代码，server.py 启动时自动检测；首次访问 PPTX case 时转换并缓存到 `.cache/`

### 启动服务

```bash
python tools/server.py
# → 浏览器访问 http://127.0.0.1:5050
```

可选参数：
- `--port 5050`：自定义端口
- `--host 0.0.0.0`：允许局域网访问（默认 127.0.0.1）
- `--cases ../cases`：自定义 cases 目录
- `--results ../results`：自定义结果目录
- `--cache ../.cache`：自定义 PPTX 缓存目录

## 准备 cases

每个 case 是一个子目录，A 和 B 各自**至少一个** HTML 或 PPTX 文件：

```
cases/
├── case-001/                     # 纯 HTML case
│   ├── input.txt
│   ├── a.html
│   └── b.html
├── case-002/                     # 纯 PPTX case
│   ├── input.txt
│   ├── a.pptx
│   └── b.pptx
└── case-003/                     # 混合 case（A 用 PPTX，B 用 HTML）
    ├── input.txt
    ├── a.pptx
    └── b.html
```

**规则**：
- `a` 和 `b` 各自至少存在 `.html` 或 `.pptx` 中的一个
- HTML 优先：若 `a.html` 和 `a.pptx` 同时存在，使用 `a.html`
- `a.html` / `a.pptx` 是**同一输入下两个不同来源的生成结果**（如：同一 prompt，模型 A 生成 vs 模型 B 生成，或人做 vs AI 生成）
- 盲测时**不告诉用户**哪份是哪个来源

## 人工盲测界面

### HTML 模式
左 A 右 B 双栏布局，通过 iframe 渲染真实的 HTML PPT。

### PPTX 模式
左 A 右 B 双栏布局，每栏内是该 PPT 的**缩略图网格**（每页一张），点击缩略图弹出全屏灯箱查看大图，灯箱内可用 `←` / `→` 翻页、`Esc` 关闭。

### 通用
- 盲测选择按钮：**`←` 选 A，`→` 选 B，`Space` 跳过**
- 可选信心度（1-5），用于分析"人在不同信心度下 AI 一致率"
- 进度可视化（echarts 饼图 + 顶部进度条）
- 顶部告警横幅：检测到 PPTX case 但 LibreOffice 缺失时显示提示

## PPTX 渲染细节

**流程**：`a.pptx` → `soffice --headless --convert-to pdf` → `a.pdf` → PyMuPDF 逐页渲染 → `page_NN.png`（150 DPI）

**缓存**：转换结果缓存到 `tools/.cache/<case_id>/<variant>/<hash>/`，基于源文件 mtime + size 生成 hash。文件不变不重转。

**性能参考**（5 页 PPT）：
- 首次转换：~5-10 秒
- 缓存命中：~50 毫秒

**已知局限**：
- 复杂动画会丢失（PPT 转 PDF 时本就不保留）
- 部分特殊字体可能回退到默认字体
- 极复杂的 SmartArt 可能简化

## AI 测评结果格式

`results/ai_results.json`：

```json
{
  "skill_version": "1.0.0",
  "generated_at": "2026-09-30T10:00:00",
  "evaluations": [
    {
      "case_id": "case-001",
      "chosen": "A",
      "scores": {
        "A": {
          "total": 8.5,
          "by_dim": {
            "内容质量": 8,
            "结构逻辑": 9,
            "视觉设计": 8.5,
            "表达传达": 8.5,
            "技术规范": 9,
            "版面合规": 10,
            "版式多样性": 7
          }
        },
        "B": {
          "total": 7.2,
          "by_dim": { "...": "..." }
        }
      },
      "confidence": 4,
      "reasoning": "A 在视觉设计和表达传达上明显优于 B"
    }
  ]
}
```

## 对比分析输出

- `report.md`：Markdown 报告（GitHub 直接渲染）
- `report.html`：HTML 可视化报告（含 echarts 图表）
- `summary.json`：机器可读摘要

## 为什么需要这个工具

仅靠 AI 测评无法证明 Skill 的可信度。本工具用人工盲测作为 ground truth，反向验证 AI 测评的准确率：
- **总一致率**：AI 和人判断相同的比例
- **分维度准确率**：AI 在哪些维度上判断最准/最差
- **分歧 case 清单**：找出 AI 误判的 case，针对性优化

跑一批 case 就有了一批标注数据，越用 Skill 越准。
