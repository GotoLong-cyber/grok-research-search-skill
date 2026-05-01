---
name: grok-research-search
description: 使用第三方中转站 Grok API 进行科研检索、论文检索、参考文献候选检索、related work 检索、方法进展检索和最新信息检索。通过环境变量 GROK_API_KEY、GROK_BASE_URL 和 GROK_MODEL 配置 API，不写死官方 xAI 地址。适用于“检索论文”“查最新文献”“找相关工作”“查某个方法最近进展”“帮我找可模仿论文”“整理参考文献候选”等任务。只输出结构化检索报告和候选文献清单，不直接改论文正文，不替代人工核验。
---

# Grok Research Search

## 中文名

Grok科研检索

## 适用场景

- 检索论文
- 检索参考文献候选
- 检索 related work
- 检索某个方法的最近进展
- 检索最新信息与 discussion 支撑文献

## 使用前建议先读

- 仓库根目录 `README.md`
- `安全说明.md`
- `.claude/skills/grok-research-search/README_配置说明.md`
- `使用示例.md`

## 禁止事项

- 不写入 API key
- 不输出 key
- 不把检索结果直接当事实
- 不自动改论文正文
- 不自动加入最终参考文献
- 不覆盖已有报告

## 输出目录

- `outputs/Grok检索报告/`

## 候选文献表目录

- `outputs/Grok检索报告/候选文献表/`

## 使用脚本

- `scripts/grok_search.py`

## 执行步骤

1. 明确检索目标，先写清主题、时间范围、目标期刊/会议、使用目的和排除条件。
2. 如使用第三方中转站，默认优先使用 `--backend raw`。
3. 运行 `scripts/grok_search.py`，生成 markdown 检索报告和 CSV 候选文献表。
4. 回看报告中的检索范围、风险说明和候选文献理由。
5. 人工逐条核验 DOI、期刊、年份、作者、BibTeX，再决定是否进入论文草稿或正式参考文献库。

## 输出格式

- 检索主题
- 检索模式
- 核心结论摘要
- 关键词扩展
- 候选文献列表
- 风险与空白
- 后续核验建议
- 联网能力说明

## 强制提醒

检索结果必须标注：`候选文献，需人工核验 DOI、期刊、年份和 BibTeX`

## 参考材料

- `README_配置说明.md`
- `检索模板.md`
- 仓库根目录 `README.md`
