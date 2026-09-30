# ppt-evaluator

一个专业的 PPT 测评 Agent Skill，对 HTML 格式演示文稿做多维度加权评分与改进建议。

## 功能

- **单份测评**：7 维加权评分（10 分制）+ 改进清单
- **A/B 盲测**：两份 PPT 背对背对比，AI 评分二选一 + 人工确认，支持全文级和单页级
- **版面合规检查**：爆版（溢出边界）、叠版（元素遮挡）自动扣分
- **版式多样性评估**：检查全文版式丰富度，避免千篇一律

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

## 使用

```
/ppt-eval        # 单份测评
/ppt-blind       # A/B 盲测
/ppt-rubric      # 查看/调整评分维度
```

## 输入格式

支持两种方式提供 HTML PPT：
- 直接粘贴 HTML 代码
- 提供本地 `.html` 文件路径

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
└── README.md
```

## 自测

```bash
# 运行自测用例（需配合 skill-creator 或手动验证）
cat evals/evals.json
```

## 设计参考

- 评分模型参考 [PPT-Eval](https://arxiv.org/html/2606.31154) 的 rubric 部分给分 + 自然语言反馈
- 盲测机制参考 [skill-creator](https://github.com/anthropics/skills) 的 comparator 模式
- 格式遵循 [Anthropic Agent Skills](https://www.anthropic.com/news/agent-skills) 开放标准

## License

MIT
