# tools/ - PPT 测评校准工具

本地运行的"人工盲测 + AI 测评"校准工具。给 Skill 自身做"自检"——看 AI 评分跟人判断是否一致。

## 核心理念

**Case 库**：每份 PPT 是一份独立 case（不再是 A/B 两个变体），存进 `cases/` 库。

**任意对比**：盲测时从库中任选 2 个 case 做对比，**不限于同一份输入的两个变体**——可以跨主题、跨场景。

**持续累积**：所有跑过人工盲测的 case 都进入基测 case 集，作为后续校准的 ground truth。

## 工作流

```
1. 准备 case（每个 case 一份多页 HTML PPT）
   cases/case-XXX/*.html  +  cases/_library.json 索引
2. 启动 server（python tools/server.py）
3. 浏览器打开 http://127.0.0.1:5050
4. 选 2 个 case 卡片 → 进入对比页 → 选 A/B + 信心度
5. 重复 N 轮盲测
6. 用本 Skill 跑 AI 测评 → 整理成 results/ai_results.json
7. 跑 analyze.py → 生成对比报告（report.md + report.html + summary.json）
```

## 安装与启动

```bash
# 基础依赖
pip install flask pymupdf

# PPTX 支持（可选，需先装 LibreOffice）
# macOS:   brew install --cask libreoffice
# Ubuntu:  sudo apt install -y libreoffice
# Windows: 官网下载 https://www.libreoffice.org/download

# 启动
cd tools/
python server.py --port 5050
# 浏览器打开 http://127.0.0.1:5050
```

## Case 库结构

```
cases/
├── _library.json              # 索引文件（自动维护，可手动编辑）
├── case-001/                  # 第一个 case
│   ├── 001.html
│   ├── 002.html
│   └── ...
├── case-002/                  # 第二个 case
│   ├── slide01.html
│   ├── slide02.html
│   └── ...
└── case-003.pptx              # 也支持 PPTX（需 LibreOffice）
```

### `_library.json` 格式

```json
{
  "cases": [
    {
      "case_id": "case-001",
      "input": "基层政府年度述职报告（含未来规划、工作回顾、成果呈现、问题剖析四大模块）",
      "tags": ["述职报告", "年度汇报"]
    },
    {
      "case_id": "case-002",
      "input": "汇报规范指南（教你如何做汇报）",
      "tags": ["汇报规范", "指南"]
    }
  ]
}
```

### 添加新 case 的两种方式

**方式 A：UI 上传**
- 主页右上角点 "📤 上传新 case"
- 填写输入描述
- 选择 HTML 文件（可多选）
- 自动生成 case_id

**方式 B：手动放文件**
```bash
mkdir cases/case-005
cp /path/to/*.html cases/case-005/

# 在 cases/_library.json 末尾加：
# {"case_id": "case-005", "input": "...", "tags": [...]}
```

## API 文档

| Method | Path | 说明 |
|--------|------|------|
| GET  | `/api/health` | 健康检查 + LibreOffice/PyMuPDF 状态 |
| GET  | `/api/library?seed=xxx` | 返回 case 列表 + 6 位匿名 code + code_to_case 映射 |
| GET  | `/api/case/<id>/pages` | 返回该 case 的所有页（每页 URL） |
| GET  | `/api/case/<id>/page/<n>` | 返回单页 HTML 文本（text/html） |
| POST | `/api/compare/select` | 记录选择 `{case_a, case_b, chosen, confidence}` |
| GET  | `/api/results` | 所有人盲测结果 |
| POST | `/api/reset` | 清空所有结果 |
| POST | `/api/case/upload` | 上传新 case（multipart） |

## 匿名化机制

盲测时 UI **不显示真实 case_id**，只显示 6 位十六进制 code（如 `85DAC9`）。

- **前端**：在请求 `/api/library?seed=xxx` 时生成随机 seed，服务端用 `hash(seed + case_id)` 生成 code
- **同一 seed** 下 code ↔ case_id 映射稳定（一次盲测过程内不混淆）
- **不同 seed** 下映射不同（不同盲测者互不干扰）
- **后端** `/api/library` 同时返回 `code_to_case` 映射（前端反查用，不展示在 UI 上）

## 盲测结果格式

`results/human_results.json`:
```json
{
  "comparisons": [
    {
      "case_a": "case-003",
      "case_b": "case-004",
      "chosen": "case-003",
      "confidence": 4,
      "timestamp": "2026-09-30T15:52:11.356371"
    }
  ]
}
```

## AI 测评结果格式

`results/ai_results.json`（由本 Skill 的 `/ppt-blind` 命令生成）:
```json
{
  "skill_version": "1.0.0",
  "evaluator": "claude-3.5-sonnet",
  "evaluations": [
    {
      "case_a": "case-003",
      "case_b": "case-004",
      "chosen": "case-003",
      "confidence": 3,
      "scores": {
        "case-003": {"total": 8.2, "by_dim": {"内容质量": 8, "...": "..."}},
        "case-004": {"total": 7.5, "by_dim": {"...": "..."}}
      },
      "reasoning": "case-003 信息密度更高"
    }
  ]
}
```

## 对比分析

```bash
python tools/analyze.py
# 输出：
#   results/report.md      - Markdown 报告
#   results/report.html    - 可视化报告（echarts 图表）
#   results/summary.json   - 机器可读摘要
```

报告内容：
1. **总一致率**：AI 选对的比例
2. **分维度一致率**：哪个维度 AI 和人分歧最大
3. **各 case 胜率**：哪些 case 在盲测中最常胜出
4. **分歧 case 对**：人和 AI 选得不一样的具体案例
5. **改进建议**：基于一致率给出自动诊断

## 注意事项

- 同一对 (case_a, case_b) 可以重复盲测——analyze.py 会投票取多数
- 上传新 case 时如果 case_id 重复，会自动加后缀（`case-005` → `case-005_2`）
- PPTX 渲染需要 LibreOffice + pymupdf；没装的话 PPTX case 会被跳过，HTML case 照常工作
- 匿名化是 UI 层的——`/api/results` 返回的是真实 case_id，方便分析
