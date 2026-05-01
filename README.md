# Grok 科研检索 Skill 

这个仓库是一个可复用的 `grok-research-search` skill ，面向需要通过第三方中转站 Grok API 做科研文献检索的使用者。你可以 clone 后配置自己的 `GROK_API_KEY`、`GROK_BASE_URL`、`GROK_MODEL`，然后用它生成结构化检索报告和候选文献 CSV。

## 这个仓库是做什么的

- 提供一个可直接复用的 Claude/Codex skill：`.claude/skills/grok-research-search/`
- 提供一个可独立运行的检索脚本：`.claude/skills/grok-research-search/scripts/grok_search.py`
- 输出 markdown 检索报告和 CSV 候选文献表
- 默认面向第三方中转站 OpenAI-compatible Grok API，推荐 `--backend raw`

## 如何配置环境变量

先复制示例文件：

```bash
cp .env.example .env
```

然后把 `.env` 中的占位符替换成你自己的配置：

```env
GROK_API_KEY=your_api_key_here
GROK_BASE_URL=https://your-proxy-domain.com/v1
GROK_MODEL=grok-4.20-fast
```

你也可以不使用 `.env`，而是直接在 shell 中导出环境变量。

## 如何安装依赖

推荐使用 `uv`：

```bash
uv pip install openai requests
```

说明：

- `requests` 是 `raw backend` 所需依赖
- `openai` SDK 不是必须依赖，但如果你需要 `sdk` 后端，可以一并安装
- 对第三方中转站，推荐优先使用 `raw backend`

## 如何运行检索

帮助命令：

```bash
python .claude/skills/grok-research-search/scripts/grok_search.py --help
```

诊断命令：

```bash
python .claude/skills/grok-research-search/scripts/grok_search.py --diagnose
```

真实检索示例：

```bash
python .claude/skills/grok-research-search/scripts/grok_search.py \
"recent SCI papers on tool wear prediction domain adaptation" \
--mode literature \
--max-items 5 \
--backend raw
```

## 输出文件在哪里

默认输出到：

- `outputs/Grok检索报告/`
- `outputs/Grok检索报告/候选文献表/`

脚本会自动创建目录，并使用“主题 + 时间戳”命名文件，避免覆盖旧报告。

## 如何在 Codex / Claude Code 中使用该 skill

仓库已经包含：

- `.claude/skills/grok-research-search/SKILL.md`
- `.claude/skills/grok-research-search/scripts/grok_search.py`
- `.claude/skills/grok-research-search/README_配置说明.md`
- `.claude/skills/grok-research-search/检索模板.md`

如果你的工具会自动读取项目内 `.claude/skills/`，可以直接在本仓库中使用。若需要迁移到其他项目，只复制 `.claude/skills/grok-research-search/` 和相关说明即可。

## 注意

检索结果只是候选文献，需人工核验 DOI、期刊、年份和 BibTeX。
