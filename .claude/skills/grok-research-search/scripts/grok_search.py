#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_MODEL = "grok-4.20-fast"
MANUAL_VERIFY_NOTE = "候选文献，需人工核验 DOI、期刊、年份和 BibTeX"
NO_LIVE_SEARCH_NOTE = "本次结果来自模型回答，需人工核验，不保证实时联网检索"
MODE_DESCRIPTIONS = {
    "literature": "科研文献检索与候选参考文献整理",
    "related_work": "related work 候选检索与分组整理",
    "method": "方法进展、变体和近期工作检索",
    "api": "最新信息、工具/API 变化和外部信息检索",
}
CSV_HEADERS = [
    "query",
    "mode",
    "title",
    "authors",
    "year",
    "venue",
    "doi",
    "url",
    "why_relevant",
    "verification_notes",
    "risk_flag",
    "manual_verify_note",
]


class ConfigError(RuntimeError):
    """Raised when required environment variables are missing."""


class RequestError(RuntimeError):
    """Raised when a backend request fails."""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        response_preview: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_preview = response_preview


def safe_preview(text: str, limit: int = 500) -> str:
    return text.strip().replace("\r", " ").replace("\n", " ")[:limit]


def is_cloudflare_waf_block(status_code: Optional[int], response_preview: str) -> bool:
    lowered = (response_preview or "").lower()
    return status_code == 403 and ("1010" in lowered or "cloudflare" in lowered)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="使用第三方中转站的 OpenAI-compatible Grok API 生成科研检索报告和候选文献 CSV。"
    )
    parser.add_argument("query", nargs="?", help="检索 query，建议写清主题、用途和时间范围。")
    parser.add_argument(
        "--mode",
        choices=sorted(MODE_DESCRIPTIONS.keys()),
        default="literature",
        help="检索模式。",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=12,
        help="候选文献最大条目数，默认 12。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="报告输出目录，默认写入仓库内 `outputs/Grok检索报告/`。",
    )
    parser.add_argument(
        "--backend",
        choices=["auto", "sdk", "raw"],
        default="auto",
        help="请求后端。默认 auto，优先使用 raw HTTP。",
    )
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="诊断环境变量与原始 HTTP 可达性，不需要 query。",
    )
    parser.add_argument(
        "--ascii-filenames",
        action="store_true",
        help="使用纯英文/ASCII slug 文件名。默认允许保留中文文件名。",
    )
    return parser.parse_args()


def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def default_output_dir() -> Path:
    return repo_root() / "outputs" / "Grok检索报告"


def load_config() -> Dict[str, str]:
    api_key = os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY")
    base_url = os.getenv("GROK_BASE_URL")
    model = os.getenv("GROK_MODEL") or DEFAULT_MODEL

    if not api_key:
        raise ConfigError(
            "缺少环境变量 `GROK_API_KEY`。如果你只配置了 `XAI_API_KEY`，也可作为 key fallback 使用。"
        )
    if not base_url:
        raise ConfigError(
            "缺少环境变量 `GROK_BASE_URL`。当前使用第三方中转站 API，必须显式提供 base_url。"
        )

    return {
        "api_key": api_key,
        "base_url": base_url.rstrip("/"),
        "model": model,
    }


def ensure_output_dirs(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_dir = output_dir / "候选文献表"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    return candidate_dir


def looks_like_mojibake(text: str) -> bool:
    if not text:
        return False
    if re.search(r"[\u4e00-\u9fff]", text):
        return False
    suspicious_markers = ("Ã", "Â", "â", "ã", "å", "æ", "ç", "è", "é", "ï")
    marker_hits = sum(text.count(marker) for marker in suspicious_markers)
    return marker_hits >= 2


def ascii_slug(text: str, limit: int = 48) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_only = ascii_only.lower()
    ascii_only = re.sub(r"[^a-z0-9]+", "_", ascii_only)
    ascii_only = re.sub(r"_+", "_", ascii_only).strip("._")
    return ascii_only[:limit].rstrip("._") or "untitled"


def safe_filename(text: str, limit: int = 48, *, ascii_only: bool = False) -> str:
    normalized = unicodedata.normalize("NFKC", text).strip()
    if ascii_only:
        return ascii_slug(normalized, limit=limit)

    normalized = re.sub(r"\s+", "_", normalized)
    normalized = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", normalized)
    normalized = normalized.replace("\u3000", "_")
    normalized = re.sub(r"_+", "_", normalized).strip(" ._")
    normalized = normalized[:limit].rstrip(" ._")
    return normalized or "未命名主题"


def choose_filename_topic(result_topic: str, query: str) -> str:
    cleaned_result_topic = result_topic.strip()
    cleaned_query = query.strip()
    if not cleaned_result_topic:
        return cleaned_query or "未命名主题"
    if looks_like_mojibake(cleaned_result_topic):
        return cleaned_query or cleaned_result_topic
    return cleaned_result_topic


def unique_path(directory: Path, stem: str, suffix: str) -> Path:
    path = directory / f"{stem}{suffix}"
    if not path.exists():
        return path

    counter = 1
    while True:
        candidate = directory / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def build_messages(query: str, mode: str, max_items: int) -> List[Dict[str, str]]:
    schema_hint = {
        "topic": "string",
        "mode": mode,
        "summary": "string",
        "search_scope": "string",
        "realtime_search_used": "true | false | unknown",
        "search_capability_note": "string",
        "related_keywords": ["string"],
        "gaps_or_risks": ["string"],
        "recommended_followup": ["string"],
        "candidate_references": [
            {
                "title": "string",
                "authors": "string",
                "year": "string",
                "venue": "string",
                "doi": "string",
                "url": "string",
                "why_relevant": "string",
                "verification_notes": "string",
                "risk_flag": "string",
            }
        ],
    }
    mode_description = MODE_DESCRIPTIONS[mode]
    system_prompt = (
        "你是科研检索助手。你可能通过第三方中转站接入 Grok，但不保证一定具备实时联网搜索能力。"
        "请严禁把候选文献说成已核验事实。请只输出 JSON，不要输出 Markdown。"
    )
    user_prompt = f"""
任务：{mode_description}
检索 query：{query}
候选文献上限：{max_items}

请返回一个 JSON 对象，字段结构尽量遵循以下 schema：
{json.dumps(schema_hint, ensure_ascii=False, indent=2)}

要求：
1. 候选文献必须是“候选文献”，不可伪装为已核验正式参考文献。
2. 如果你没有实时联网搜索能力，或你不确定是否联网，请在 `realtime_search_used` 中写 `false` 或 `unknown`，并在 `search_capability_note` 中明确写：
   "{NO_LIVE_SEARCH_NOTE}"
3. 每条 candidate_references 都要给出 `verification_notes`，提醒人工核验 DOI、期刊、年份、BibTeX。
4. 如果某些信息不确定，可以留空，但不要编造确定性。
5. 输出必须是合法 JSON。
""".strip()
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def build_simple_messages(user_content: str) -> List[Dict[str, str]]:
    return [
        {"role": "system", "content": "You are a concise assistant. Reply with plain text only."},
        {"role": "user", "content": user_content},
    ]


def extract_json_block(text: str) -> Dict[str, Any]:
    text = text.strip()
    if not text:
        return {}

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return {}

    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}


def normalize_keywords(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def normalize_candidates(raw_candidates: Any, query: str, mode: str, max_items: int) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    if not isinstance(raw_candidates, list):
        return normalized

    for item in raw_candidates[: max(max_items, 0)]:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "query": query,
                "mode": mode,
                "title": str(item.get("title", "")).strip(),
                "authors": str(item.get("authors", "")).strip(),
                "year": str(item.get("year", "")).strip(),
                "venue": str(item.get("venue", "")).strip(),
                "doi": str(item.get("doi", "")).strip(),
                "url": str(item.get("url", "")).strip(),
                "why_relevant": str(item.get("why_relevant", "")).strip(),
                "verification_notes": str(item.get("verification_notes", "")).strip()
                or MANUAL_VERIFY_NOTE,
                "risk_flag": str(item.get("risk_flag", "")).strip(),
                "manual_verify_note": MANUAL_VERIFY_NOTE,
            }
        )
    return normalized


def extract_content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: List[str] = []
        for item in value:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    return ""


def prepare_result_from_content(content: str) -> Dict[str, Any]:
    data = extract_json_block(content)
    if data:
        data["_raw_content"] = content
        return data
    return {"_raw_content": content}


def resolve_chat_completions_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def resolve_models_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/models"):
        return normalized
    return f"{normalized}/models"


def raw_headers(api_key: str, *, accept: str = "text/event-stream") -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": accept,
        "User-Agent": "curl/8.5.0",
    }


def build_chat_payload(
    *,
    model: str,
    messages: List[Dict[str, str]],
    stream: bool,
    max_tokens: int = 4096,
) -> Dict[str, Any]:
    return {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": stream,
    }


def import_requests():
    try:
        import requests
    except ImportError as exc:
        raise RequestError("缺少 `requests` Python 包，无法使用 raw backend。") from exc
    return requests


def parse_sse_lines(lines: List[str]) -> Tuple[str, str]:
    parts: List[str] = []
    raw_lines: List[str] = []
    for raw_line in lines:
        if raw_line is None:
            continue
        line = raw_line.strip()
        if not line:
            continue
        raw_lines.append(line)
        if not line.startswith("data:"):
            continue
        payload = line[len("data:") :].strip()
        if payload == "[DONE]":
            break
        try:
            item = json.loads(payload)
        except json.JSONDecodeError:
            continue
        choice = ((item.get("choices") or [{}])[0]) if isinstance(item, dict) else {}
        delta = choice.get("delta") or {}
        if isinstance(delta.get("content"), str):
            parts.append(delta["content"])
            continue
        if isinstance(delta.get("reasoning_content"), str):
            continue
        message = choice.get("message") or {}
        content = extract_content_text(message.get("content"))
        if content:
            parts.append(content)
    return "".join(parts), "\n".join(raw_lines)


def parse_chat_response(response, *, stream_requested: bool) -> Tuple[str, str]:
    content_type = (response.headers.get("Content-Type") or "").lower()
    if stream_requested or "text/event-stream" in content_type:
        response.encoding = response.encoding or "utf-8"
        streamed_lines = list(response.iter_lines(decode_unicode=True))
        content, raw_text = parse_sse_lines(streamed_lines)
        if content or raw_text:
            return content, raw_text

    raw_text = response.text
    if raw_text.lstrip().startswith("data:"):
        content, parsed_raw_text = parse_sse_lines(raw_text.splitlines())
        if content or parsed_raw_text:
            return content, parsed_raw_text

    try:
        response_json = response.json()
    except ValueError:
        return raw_text, raw_text

    choice = ((response_json.get("choices") or [{}])[0]) if isinstance(response_json, dict) else {}
    message = choice.get("message") or {}
    content = extract_content_text(message.get("content"))
    if not content:
        delta = choice.get("delta") or {}
        content = extract_content_text(delta.get("content"))
    pretty_json = json.dumps(response_json, ensure_ascii=False)
    return content, pretty_json


def raise_for_http_error(status_code: int, preview: str) -> None:
    if is_cloudflare_waf_block(status_code, preview):
        raise RequestError(
            "手动 curl 可以通过，但 Python 请求被第三方中转站 Cloudflare/WAF 拦截。请尝试 raw backend、检查 headers，或联系中转站。",
            status_code=status_code,
            response_preview=preview,
        )
    raise RequestError(
        f"HTTP {status_code}。响应摘要：{preview or '无'}",
        status_code=status_code,
        response_preview=preview,
    )


def raw_post_chat(
    *,
    config: Dict[str, str],
    messages: List[Dict[str, str]],
    stream: bool,
    timeout: Tuple[int, int] = (30, 180),
) -> Tuple[str, str, int]:
    requests = import_requests()
    endpoint = resolve_chat_completions_url(config["base_url"])
    payload = build_chat_payload(model=config["model"], messages=messages, stream=stream)
    try:
        response = requests.post(
            endpoint,
            headers=raw_headers(config["api_key"]),
            json=payload,
            stream=stream,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise RequestError(f"raw backend 连接失败：{safe_preview(str(exc))}") from exc
    if response.status_code >= 400:
        preview = safe_preview(response.text)
        raise_for_http_error(response.status_code, preview)
    content, raw_text = parse_chat_response(response, stream_requested=stream)
    return content, raw_text, response.status_code


def raw_get_models_status(config: Dict[str, str], timeout: Tuple[int, int] = (30, 60)) -> Tuple[int, str]:
    requests = import_requests()
    endpoint = resolve_models_url(config["base_url"])
    try:
        response = requests.get(
            endpoint,
            headers=raw_headers(config["api_key"], accept="application/json"),
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise RequestError(f"raw backend 连接失败：{safe_preview(str(exc))}") from exc
    preview = safe_preview(response.text)
    if response.status_code >= 400:
        raise_for_http_error(response.status_code, preview)
    return response.status_code, preview


def call_search_api_sdk(config: Dict[str, str], query: str, mode: str, max_items: int) -> Dict[str, Any]:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RequestError("缺少 `openai` Python 包，无法使用 sdk backend。请改用 `--backend raw`。") from exc

    try:
        client = OpenAI(api_key=config["api_key"], base_url=config["base_url"])
        response = client.chat.completions.create(
            model=config["model"],
            messages=build_messages(query=query, mode=mode, max_items=max_items),
            temperature=0.2,
        )
    except Exception as exc:
        message = safe_preview(str(exc))
        if "1010" in message.lower() or "cloudflare" in message.lower():
            raise RequestError(
                "手动 curl 可以通过，但 Python 请求被第三方中转站 Cloudflare/WAF 拦截。请尝试 raw backend、检查 headers，或联系中转站。",
                response_preview=message,
            ) from exc
        raise RequestError(f"sdk backend 请求失败：{message or exc.__class__.__name__}") from exc

    content = ""
    if response.choices:
        content = response.choices[0].message.content or ""
    return prepare_result_from_content(content)


def call_search_api_raw(config: Dict[str, str], query: str, mode: str, max_items: int) -> Dict[str, Any]:
    messages = build_messages(query=query, mode=mode, max_items=max_items)
    first_error: Optional[RequestError] = None
    try:
        content, raw_text, _status = raw_post_chat(config=config, messages=messages, stream=True)
        return prepare_result_from_content(content or raw_text)
    except RequestError as exc:
        first_error = exc

    try:
        content, raw_text, _status = raw_post_chat(config=config, messages=messages, stream=False)
        return prepare_result_from_content(content or raw_text)
    except RequestError as exc:
        if first_error and is_cloudflare_waf_block(first_error.status_code, first_error.response_preview):
            raise first_error
        if is_cloudflare_waf_block(exc.status_code, exc.response_preview):
            raise exc
        first_summary = str(first_error) if first_error else "无"
        second_summary = str(exc)
        raise RequestError(
            "raw backend 请求失败。已尝试 stream=true 和 stream=false。"
            f" 第一次失败：{first_summary}；第二次失败：{second_summary}"
        ) from exc


def call_search_api(
    *,
    config: Dict[str, str],
    query: str,
    mode: str,
    max_items: int,
    backend: str,
) -> Dict[str, Any]:
    if backend == "sdk":
        return call_search_api_sdk(config=config, query=query, mode=mode, max_items=max_items)
    if backend in {"raw", "auto"}:
        return call_search_api_raw(config=config, query=query, mode=mode, max_items=max_items)
    raise RequestError(f"未知 backend：{backend}")


def run_diagnose(config: Dict[str, str]) -> int:
    print(f"GROK_API_KEY: present (length={len(config['api_key'])})")
    print(f"GROK_BASE_URL: {config['base_url']}")
    print(f"GROK_MODEL: {config['model']}")

    try:
        status_code, _preview = raw_get_models_status(config)
        print(f"/models: HTTP {status_code}")
    except RequestError as exc:
        print(f"/models: FAIL - {exc}")
        return 1

    try:
        content, _raw_text, status_code = raw_post_chat(
            config=config,
            messages=build_simple_messages("Say OK only."),
            stream=True,
            timeout=(30, 90),
        )
        ok_only = content.strip() == "OK"
        print(f"/chat/completions: HTTP {status_code}")
        print(f"chat content is OK: {'yes' if ok_only else 'no'}")
        if not ok_only:
            print(f"chat content preview: {safe_preview(content, limit=120)}")
        return 0
    except RequestError as first_error:
        print(f"/chat/completions stream=true: FAIL - {first_error}")
        try:
            content, _raw_text, status_code = raw_post_chat(
                config=config,
                messages=build_simple_messages("Say OK only."),
                stream=False,
                timeout=(30, 90),
            )
            ok_only = content.strip() == "OK"
            print(f"/chat/completions stream=false: HTTP {status_code}")
            print(f"chat content is OK: {'yes' if ok_only else 'no'}")
            if not ok_only:
                print(f"chat content preview: {safe_preview(content, limit=120)}")
            return 0
        except RequestError as second_error:
            print(f"/chat/completions stream=false: FAIL - {second_error}")
            return 1


def render_markdown(
    *,
    query: str,
    mode: str,
    config: Dict[str, str],
    result: Dict[str, Any],
    report_path: Path,
    csv_path: Path,
) -> str:
    topic = str(result.get("topic") or query).strip()
    summary = str(result.get("summary", "")).strip() or "模型未返回结构化摘要，请人工查看原始输出。"
    search_scope = str(result.get("search_scope", "")).strip() or "未提供"
    realtime_search_used = str(result.get("realtime_search_used", "unknown")).strip() or "unknown"
    capability_note = str(result.get("search_capability_note", "")).strip()
    if realtime_search_used.lower() in {"false", "unknown"} and not capability_note:
        capability_note = NO_LIVE_SEARCH_NOTE

    keywords = normalize_keywords(result.get("related_keywords"))
    risks = normalize_keywords(result.get("gaps_or_risks"))
    followup = normalize_keywords(result.get("recommended_followup"))
    candidates = normalize_candidates(result.get("candidate_references"), query, mode, 10_000)
    raw_content = str(result.get("_raw_content", "")).strip()

    lines: List[str] = []
    lines.append("# Grok科研检索报告")
    lines.append("")
    lines.append(f"- 检索主题：{topic}")
    lines.append(f"- 检索模式：{mode}（{MODE_DESCRIPTIONS[mode]}）")
    lines.append(f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 使用模型：{config['model']}")
    lines.append(f"- 报告文件：`{report_path}`")
    lines.append(f"- 候选文献表：`{csv_path}`")
    lines.append("")
    lines.append("## 核验提醒")
    lines.append("")
    lines.append(f"> {MANUAL_VERIFY_NOTE}")
    lines.append("")
    lines.append("## 核心结论摘要")
    lines.append("")
    lines.append(summary)
    lines.append("")
    lines.append("## 检索范围")
    lines.append("")
    lines.append(search_scope)
    lines.append("")
    lines.append("## 联网能力说明")
    lines.append("")
    lines.append(f"- realtime_search_used: `{realtime_search_used}`")
    lines.append(f"- 说明：{capability_note or '模型未明确说明联网状态，需人工核验。'}")
    lines.append("")
    lines.append("## 关键词扩展")
    lines.append("")
    if keywords:
        lines.extend([f"- {keyword}" for keyword in keywords])
    else:
        lines.append("- 无")
    lines.append("")
    lines.append("## 候选文献")
    lines.append("")
    if candidates:
        for index, item in enumerate(candidates, start=1):
            lines.append(f"### {index}. {item['title'] or '未提供标题'}")
            lines.append("")
            lines.append(f"- 作者：{item['authors'] or '待核验'}")
            lines.append(f"- 年份：{item['year'] or '待核验'}")
            lines.append(f"- 期刊/会议：{item['venue'] or '待核验'}")
            lines.append(f"- DOI：{item['doi'] or '待核验'}")
            lines.append(f"- URL：{item['url'] or '待补充'}")
            lines.append(f"- 相关性：{item['why_relevant'] or '待补充'}")
            lines.append(f"- 核验说明：{item['verification_notes']}")
            if item["risk_flag"]:
                lines.append(f"- 风险标记：{item['risk_flag']}")
            lines.append("")
    else:
        lines.append("- 模型未返回可解析的候选文献条目，请人工查看原始输出。")
        lines.append("")
    lines.append("## 风险与空白")
    lines.append("")
    if risks:
        lines.extend([f"- {risk}" for risk in risks])
    else:
        lines.append("- 无结构化风险说明，需人工补充。")
    lines.append("")
    lines.append("## 后续建议")
    lines.append("")
    if followup:
        lines.extend([f"- {item}" for item in followup])
    else:
        lines.append("- 逐条核验 DOI、期刊、年份、BibTeX 后再进入论文。")
    if raw_content:
        lines.append("")
        lines.append("## 原始模型输出")
        lines.append("")
        lines.append("```json")
        lines.append(raw_content)
        lines.append("```")
    return "\n".join(lines).rstrip() + "\n"


def write_csv(csv_path: Path, rows: List[Dict[str, str]]) -> None:
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in CSV_HEADERS})


def main() -> int:
    args = parse_args()

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2

    if args.diagnose:
        return run_diagnose(config)

    if not args.query:
        print("用法错误：缺少 query。若只做诊断，请使用 `--diagnose`。", file=sys.stderr)
        return 2

    output_dir = args.output_dir or default_output_dir()
    candidate_dir = ensure_output_dirs(output_dir)

    try:
        result = call_search_api(
            config=config,
            query=args.query,
            mode=args.mode,
            max_items=args.max_items,
            backend=args.backend,
        )
    except RequestError as exc:
        print(f"API 请求失败：{exc}", file=sys.stderr)
        return 1

    topic = str(result.get("topic") or args.query).strip()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename_topic = choose_filename_topic(topic, args.query)
    stem = f"{safe_filename(filename_topic, ascii_only=args.ascii_filenames)}_{timestamp}"
    report_path = unique_path(output_dir, stem, ".md")
    csv_path = unique_path(candidate_dir, stem, ".csv")

    rows = normalize_candidates(result.get("candidate_references"), args.query, args.mode, args.max_items)
    write_csv(csv_path, rows)
    report_markdown = render_markdown(
        query=args.query,
        mode=args.mode,
        config=config,
        result=result,
        report_path=report_path,
        csv_path=csv_path,
    )
    report_path.write_text(report_markdown, encoding="utf-8")

    print(f"检索报告已写入：{report_path}")
    print(f"候选文献表已写入：{csv_path}")
    print(MANUAL_VERIFY_NOTE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
