# Grok科研检索 Skill 配置说明

## 1. 环境变量

脚本从终端环境变量读取以下配置，不在代码或文档中写入真实 key：

- `GROK_API_KEY`
- `GROK_BASE_URL`
- `GROK_MODEL`

说明：

- `GROK_API_KEY` 缺失时，脚本会 fallback 读取 `XAI_API_KEY`
- `GROK_BASE_URL` 必须显式配置，且不会在代码中写死
- `GROK_MODEL` 缺失时默认使用 `grok-4.20-fast`

## 2. 安全约束

- 不要把 API key 写入任何代码、README、SKILL.md、日志或检索报告
- 不要打印完整 API key
- 检索结果一律视为候选信息，不直接当事实使用
- 候选文献进入论文前，必须人工核验 DOI、期刊、年份、作者和 BibTeX

统一提醒：

`候选文献，需人工核验 DOI、期刊、年份和 BibTeX`

## 3. 输出目录

- 检索报告：`outputs/Grok检索报告/`
- 候选文献表：`outputs/Grok检索报告/候选文献表/`

脚本会自动创建目录，并使用“主题 + 时间戳”命名文件，不覆盖已有报告。

## 4. 第三方中转站推荐用法

如果你当前使用的是第三方中转站 OpenAI-compatible API，默认推荐显式使用：

```bash
python .claude/skills/grok-research-search/scripts/grok_search.py "你的检索问题" --mode literature --max-items 10 --backend raw
```

原因：

- 第三方中转站可能对 OpenAI SDK 的请求方式更敏感
- `raw` 后端更接近已手动验证通过的 `curl` 请求
- 当前脚本支持 `text/event-stream` 与非流式 JSON 响应

如无特殊需要，不建议把第三方中转站默认跑在 `sdk` 后端。

## 5. 安全测试命令

以下命令不会发起真实长检索：

```bash
python .claude/skills/grok-research-search/scripts/grok_search.py --help
```

```bash
python -m py_compile .claude/skills/grok-research-search/scripts/grok_search.py
```

```bash
python .claude/skills/grok-research-search/scripts/grok_search.py --diagnose
```

诊断说明：

- `--diagnose` 主要用于检查环境变量、`/models` 可达性和 `/chat/completions` 的基本响应
- 如果 `--diagnose` 中出现 `/models: HTTP 200`、`/chat/completions: HTTP 200`，但 `chat content is OK: no` 或 `chat content preview` 为空，这不一定表示主链路失败
- 对第三方中转站，更重要的判断标准是：真实检索命令能否成功落地 markdown 报告和 CSV
- 只要真实检索可以正常生成报告和候选文献表，就可以继续使用

## 6. 未来手动检索命令示例

以下命令会在你准备好时发起真实 API 调用，请手动决定是否执行：

```bash
python .claude/skills/grok-research-search/scripts/grok_search.py "recent SCI papers on tool wear prediction domain adaptation" --mode literature --max-items 5 --backend raw
```

```bash
python .claude/skills/grok-research-search/scripts/grok_search.py "KNN reliability estimation for forecasting and regression" --mode related_work --max-items 10 --backend raw
```

## 7. 输出内容说明

每次检索会落地两类文件：

- 一个 markdown 检索报告
- 一个 CSV 候选文献表

如果第三方中转站未提供实时联网检索能力，报告中会注明：

`本次结果来自模型回答，需人工核验，不保证实时联网检索`
