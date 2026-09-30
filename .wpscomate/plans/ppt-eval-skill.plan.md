# PPT 测评 Skill 设计方案

## 项目概述
做一个名为 `ppt-evaluator` 的 Agent Skill，对 HTML 格式 PPT + 文本内容做多维度加权评分 + 改进清单，支持背对背 A/B 盲测（两份 PPT 盲选），带 evals 自测，最终上传 GitHub。

## 技术选型
- **形态**：纯指令式 Skill（SKILL.md + references/ + templates/），无外部脚本依赖，最大化可分发性。解析 HTML 用模型自带能力，不引入 python-pptx（输入是 HTML 不是 pptx）。
- **评分模型**：多维度加权平均（Rubric 风格，参考 PPT-Eval 的部分给分 + 自然语言反馈）。
- **盲测**：参考 skill-creator 的 comparator 机制，AI 先评 + 人确认双轨。
- **规范**：遵循 Anthropic Agent Skills 标准（YAML frontmatter + 渐进式加载 + <500 行 SKILL.md）。

## 功能与信息架构
三个核心命令：
- `/ppt-eval` 单份测评：输入 HTML+文本 → 多维加权评分 + 改进清单
- `/ppt-blind` A/B 盲测：两份 PPT 隐去标识 → AI 评分二选一 + 人确认。**支持两种粒度**：
  - 全文 PPT 对比（整份 A vs 整份 B）
  - 单页 PPT 对比（A 的某页 vs B 的对应页）
- `/ppt-rubric` 查看/调整评分维度与权重

## 评分维度（6 维，默认权重）
| 维度 | 权重 | 评什么 | 计分方式 |
|------|------|--------|----------|
| 内容质量 | 22% | 信息密度、准确性、逻辑连贯 | 1-5 分 |
| 结构逻辑 | 18% | 叙事线、页间衔接、金字塔结构 | 1-5 分 |
| 视觉设计 | 22% | 版式、配色、留白、可读性 | 1-5 分 |
| 表达传达 | 18% | 标题力、要点精炼、说服力 | 1-5 分 |
| 技术规范 | 10% | HTML 结构、响应式、无错乱 | 1-5 分 |
| 版面合规 | 10% | 爆版（溢出边界）、叠版（元素遮挡重叠） | **扣分制**：基础 5 分，每处爆版/叠版扣 1 分，最低 0 分 |

> 版面合规为硬性扣分项：基础满分 5 分，每发现一处爆版或叠版问题扣 1 分，扣完为止。该维度采用扣分制而非主观打分，确保版面硬伤被严格惩罚。

## 架构设计
```
ppt-evaluator/
├── SKILL.md              # 主指令 + 三命令路由
├── references/
│   ├── rubric.md         # 6 维评分细则 + 1-5 分锚点 + 版面合规扣分规则
│   ├── blind-test.md     # A/B 盲测协议（全文级 + 单页级两种粒度）
│   └── examples.md       # 测评报告示例
├── templates/
│   ├── score-report.md   # 单份评分报告模板
│   ├── blind-full.md     # 全文盲测报告模板
│   └── blind-page.md     # 单页盲测报告模板
├── evals/
│   └── evals.json        # 自测用例 + 断言
└── README.md             # GitHub 仓库说明
```

## 实施步骤
见 todo items。