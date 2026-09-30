# ppt-evaluator

一个专业的 PPT 测评 Agent Skill，对 HTML 格式演示文稿做多维度加权评分与改进建议。

包含两部分：
1. **SKILL 本身**：AI 测评（单份 + A/B 盲测）
2. **tools/**：本地校准工具（人工盲测界面 + AI vs 人工对比分析）

## 功能

### AI 测评（Skill 部分）
- **单份测评**：7 维加权评分（10 分制）+ 改进清单
- **A/B 盲测**：两份 PPT 背对背对比，AI 评分二选一 + 人工确认，支持全文级和单页级
- **版面合规检查**：爆版（溢出边界）、叠版（元素遮挡）自动扣分
- **版式多样性评估**：检查全文版式丰富度，避免千篇一律

### 本地校准工具（tools/）
- **人工盲测界面**：本地 Flask 服务，两两对比 + 自动渲染 + 进度可视化
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
git clone https://github.com/你的用户名/ppt-evaluator.git ~/.claude/skills/ppt-evaluator

# 方式二：npx 一键安装（支持 55+ Agent 工具）
npx skills add 你的用户名/ppt-evaluator
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
# 1. 准备 cases（每个 case 一个子目录，含 input.txt + a.html + b.html）
ls cases/case-001/

# 2. 启动人工盲测界面
pip install flask
python tools/server.py
# → 浏览器打开 http://127.0.0.1:5050

# 3. 跑 AI 测评（用本 Skill），结果整理为 results/ai_results.json

# 4. 对比分析
python tools/analyze.py
# → 生成 report.md / report.html / summary.json
```

## 仓库结构

```
ppt-evaluator/
├── SKILL.md              # 主指令 + 三命令路由
├── references/
│   ├── rubric.md         # 7 维评分细则 + 1-10 分锚点
│   ├── blind-test.md     # A/B 盲测协议（全文级 + 单页级）
│   └── examples.md       # 测评报告示例
├── templates/
│   ├── score-report.md   # 单份评分报告模板
│   ├── blind-full.md     # 全文盲测报告模板
│   └── blind-page.md     # 单页盲测报告模板
├── evals/
│   └── evals.json        # 自测用例 + 断言
├── tools/                # 本地校准工具
│   ├── server.py         # Flask 启动 + 渲染
│   ├── compare.html      # 两两对比界面
│   ├── analyze.py        # AI vs 人工对比分析
│   ├── static/           # 静态依赖（echarts）
│   └── README.md
├── cases/                # 用户放 case 的目录（含示例 case-001）
├── results/              # 输出结果（human_results.json / ai_results.json / 报告）
└── README.md
```

## 自测

```bash
# 查看自测用例
cat evals/evals.json

# 启动服务并访问示例 case
python tools/server.py
# → 浏览器打开 http://127.0.0.1:5050
# → 试试 cases/case-001
```

## 设计参考

- 评分模型参考 [PPT-Eval](https://arxiv.org/html/2606.31154) 的 rubric 部分给分 + 自然语言反馈
- 盲测机制参考 [skill-creator](https://github.com/anthropics/skills) 的 comparator 模式
- 格式遵循 [Anthropic Agent Skills](https://www.anthropic.com/news/agent-skills) 开放标准

## License

MIT
