# ppt-evaluator

一个专业的 PPT 测评 Agent Skill，对 HTML 格式演示文稿做多维度加权评分与改进建议。

包含两部分：
1. **SKILL 本身**：AI 测评（单份 + A/B 盲测）
2. **tools/**：本地校准工具（人工盲测 Case 库 + AI vs 人工对比分析）

## 核心理念

**Case 库 + 任意对比**：
- 每份 PPT 是一份独立 case（不再是 A/B 两个变体）
- 盲测时从库中任选 2 个 case 做对比，**跨主题、跨场景**
- 所有跑过人工盲测的 case 都进入基测集，持续累积校准数据

## 功能

### AI 测评（Skill 部分）
- **单份测评**：7 维加权评分（10 分制）+ 改进清单
- **A/B 盲测**：两份 PPT 背对背对比，AI 评分二选一 + 人工确认，支持全文级和单页级
- **版面合规检查**：爆版（溢出边界）、叠版（元素遮挡）自动扣分
- **版式多样性评估**：检查全文版式丰富度，避免千篇一律
- **支持 HTML、多页 HTML、PPTX 三种输入格式**（PPTX 走 LibreOffice 渲染为每页 PNG）

### 本地校准工具（tools/）
- **Case 库管理**：每个 case 一份多页 HTML，UI 上传或手动放置
- **人工盲测界面**：本地 Flask 服务，从库中任选 2 个 case 对比，6 位匿名 code 隐去真实身份
- **AI vs 人工对比分析**：计算一致率、分维度准确率、分歧 case 清单
- **可视化报告**：Markdown 报告 + HTML 图表（echarts）

## 7 维评分模型

| 维度 | 权重 | 评什么 |
|------|------|--------|
| 内容质量 | 20% | 信息密度、准确性、逻辑连贯 |
| 结构逻辑 | 16% | 叙事线、页间衔接、金字塔结构 |
| 视觉设计 | 20% | 配色、留白、可读性、视觉层次 |
| 表达传达 | 16% | 标题力、要点精炼、说服力 |
| 技术规范 | 8% | HTML 结构、响应式、无错乱 |
| 版面合规 | 10% | 爆版、叠版（扣分制） |
| 版式多样性 | 10% | 全文版式丰富度、内容匹配度 |

## 安装

```bash
# 方式一：克隆到 Claude Code skills 目录
git clone https://github.com/Cherise0801/xuxu-ppt-evaluator.git ~/.claude/skills/ppt-evaluator

# 方式二：npx 一键安装（支持 55+ Agent 工具）
npx skills add Cherise0801/xuxu-ppt-evaluator
```

## 使用 Skill

```
/ppt-eval        # 单份测评
/ppt-blind       # A/B 盲测
/ppt-rubric      # 查看/调整评分维度
```

## 使用本地校准工具

详见 [tools/README.md](tools/README.md)。

```bash
# 1. 安装依赖
pip install flask pymupdf
# PPTX 支持需额外安装 LibreOffice（详见 tools/README.md）

# 2. 启动人工盲测界面
python tools/server.py
# → 浏览器打开 http://127.0.0.1:5050

# 3. 在 UI 中选 2 个 case 做盲测（点选卡片）

# 4. 跑 AI 测评（用本 Skill /ppt-blind），结果整理为 results/ai_results.json

# 5. 对比分析
python tools/analyze.py
# → 生成 report.md / report.html / summary.json
```

## Case 库结构

```
ppt-evaluator/
├── SKILL.md              # 主指令 + 三命令路由
├── references/           # 评分细则 + 盲测协议
├── templates/            # 报告模板
├── evals/                # 自测用例 + 断言
├── tools/                # 本地校准工具
│   ├── server.py
│   ├── compare.html
│   ├── analyze.py
│   └── ...
├── cases/                # Case 库
│   ├── _library.json     # 索引
│   ├── case-003/         # 多页 HTML case
│   │   ├── 第1页.html
│   │   └── ...
│   ├── case-004/         # 另一份 PPT
│   │   └── ...
│   └── case-XXX.pptx     # PPTX case
└── results/              # 输出结果
    ├── human_results.json
    ├── ai_results.json
    ├── report.md
    └── report.html
```

## 自测

```bash
# 查看自测用例
cat evals/evals.json

# 启动服务并访问示例 case
python tools/server.py
# → 浏览器打开 http://127.0.0.1:5050
# → 试试 cases/case-003（基层政府年度述职报告）和 case-004（汇报规范指南）
```

## 设计参考

- 评分模型参考 [PPT-Eval](https://arxiv.org/html/2606.31154) 的 rubric 部分给分 + 自然语言反馈
- 盲测机制参考 [skill-creator](https://github.com/anthropics/skills) 的 comparator 模式
- Case 库与匿名化机制设计自 [Anthropic Agent Skills](https://www.anthropic.com/news/agent-skills) 开放标准

## License

MIT
