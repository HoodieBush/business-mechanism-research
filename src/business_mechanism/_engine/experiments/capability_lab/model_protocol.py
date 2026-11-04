"""Bounded structured submissions; preserve API evidence without credentials.

Function calling is a transport contract, not an experiment-selection treatment.
No automatic retry, narrative JSON extraction, or repair of truncated output.
"""
from __future__ import annotations

import copy
import json
import time
import urllib.error
import urllib.request

from model_credentials import load_api_key
from token_budget import SharedTokenBudget, TokenBudgetStop


ROLE_SCHEMA = {"type": "object", "properties": {
    "heating": {"type": "array", "items": {"type": "string"}},
    "utensils": {"type": "array", "items": {"type": "string"}}},
    "required": ["heating", "utensils"],
    "additionalProperties": {"type": "array", "items": {"type": "string"}}}
GROUNDING_SCHEMA = {"type": "object", "properties": {
    "role_patterns": ROLE_SCHEMA, "premises": {"type": "string"},
    "catalog_roles": {"type":"object","additionalProperties": {
        "type":"array","items":{"type":"string","enum":["heating","utensils"]}}}},
    "required": ["role_patterns", "premises", "catalog_roles"], "additionalProperties": False}
CANDIDATE_SCHEMA = {"type": "object", "properties": {
    "role_patterns": ROLE_SCHEMA, "expression": {"type": "string"},
    "parameters": {"type": "object", "additionalProperties": {
        "type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}},
    "rationale": {"type": "string"}},
    "required": ["role_patterns", "expression", "parameters", "rationale"],
    "additionalProperties": False}
ACTION_SCHEMA = {"type": "object", "properties": {
    "tool": {"type": "string"}, "args": {"type": "object"}},
    "required": ["tool", "args"], "additionalProperties": False}


def generation_request(payload, config):
    """Apply model defaults before admission; normalize explicit thinking mode.

    DeepSeek ignores ordinary sampling penalties/temperature in thinking mode
    and rejects forced tool selection. Keep automatic selection and validate the
    actual returned submission instead. Per-call overrides remain explicit.
    """
    payload = {**copy.deepcopy(config.get("generation_options", {})),
               **copy.deepcopy(payload)}
    if (payload.get("thinking") or {}).get("type") == "enabled":
        for name in ("temperature", "presence_penalty", "frequency_penalty"):
            payload.pop(name, None)
        if isinstance(payload.get("tool_choice"), dict) or payload.get("tool_choice") == "required":
            payload["tool_choice"] = "auto"
    return payload


def structured_request(payload, config, name, schema):
    payload = copy.deepcopy(payload)
    protocol = config.get("structured_output", "json_object")
    if protocol == "function_call":
        payload.pop("response_format", None)
        payload["messages"][0]["content"] += (
            f"\n输出协议：必须调用 API 函数 {name} 提交本轮输出；将完整研究输出放在函数参数中，不在 content 中输出 JSON 或报告。")
        payload["tools"] = [{"type": "function", "function": {
            "name": name, "description": "提交本轮结构化研究输出。",
            "parameters": copy.deepcopy(schema)}}]
        payload["tool_choice"] = {"type": "function", "function": {"name": name}}
    elif protocol == "json_object":
        payload["response_format"] = {"type": "json_object"}
    else:
        raise ValueError("unknown structured_output protocol")
    return generation_request(payload, config)


def decode_submission(raw, config, name):
    choice = raw["choices"][0]
    if choice.get("finish_reason") == "length":
        raise ValueError("truncated output (finish_reason=length)")
    message = choice["message"]
    if config.get("structured_output", "json_object") == "function_call":
        calls = message.get("tool_calls") or []
        if not calls and config.get("plain_json_fallback",False):
            # The proxy can ignore named tool_choice. Accept only an entire JSON
            # object; never search narrative text or repair a truncated object.
            content=message.get("content") or ""
        elif len(calls) != 1 or calls[0].get("type") != "function":
            raise ValueError("expected exactly one function submission")
        else:
            function = calls[0]["function"]
            if function["name"] != name:
                raise ValueError("unexpected submission function")
            content = function["arguments"]
    else:
        content = message.get("content") or ""
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError("submission must be a JSON object")
    return value


def submission_transport(raw):
    return "function_call" if raw["choices"][0]["message"].get("tool_calls") else "plain_json_content"


def request_model(config, payload):
    """Return an auditable record even when transport/envelope decoding fails."""
    payload = generation_request(payload, config)
    record = {"request": copy.deepcopy(payload), "cache_hit": False}
    key = load_api_key(config)
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    def redact(text):
        return text.replace(key, "[REDACTED]") if key else text
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if config.get("bypass_proxy", True) else urllib.request.build_opener()
    req = urllib.request.Request(config["base_url"].rstrip("/") + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode(), headers=headers)
    budget = SharedTokenBudget(config['token_budget_pointer']) if config.get('token_budget_pointer') else SharedTokenBudget()
    if config['base_url'].rstrip('/') != budget.auth['base_url']:
        raise TokenBudgetStop('shared reported-cost admission stop: route is outside authorization')
    reservation = budget.reserve(payload, {'model': payload.get('model')})
    record['token_budget'] = reservation
    start = time.monotonic()
    try:
        with opener.open(req, timeout=config.get("request_timeout_seconds", 90)) as response:
            record["http_status"] = getattr(response, "status", 200)
            request_id = (getattr(response, "headers", {}).get("X-Request-ID")
                          or getattr(response, "headers", {}).get("X-Oneapi-Request-Id"))
            if request_id:
                record["provider_request_id"] = redact(request_id)
            body = redact(response.read().decode("utf-8", errors="replace"))
        try:
            raw=json.loads(body)
            if not isinstance(raw,dict):
                raise ValueError("API envelope must be an object")
            record["response"] = raw
        except ValueError as error:
            record.update(error_type="response_envelope", error=str(error), response_body=body)
    except urllib.error.HTTPError as error:
        record.update(error_type="http", http_status=error.code,
            error=redact(str(error)), response_body=redact(error.read().decode("utf-8", errors="replace")))
        request_id = error.headers.get("X-Request-ID") or error.headers.get("X-Oneapi-Request-Id")
        if request_id:
            record["provider_request_id"] = redact(request_id)
        if error.headers.get("Retry-After"):
            record["retry_after"] = error.headers.get("Retry-After")
    except (OSError, urllib.error.URLError) as error:
        record.update(error_type="transport", error=redact(type(error).__name__ + ": " + str(error)))
    record["elapsed_seconds"] = round(time.monotonic() - start, 3)
    try:
        record['token_budget'] = budget.settle(reservation, record.get('response',{}).get('usage'),
                                              record.get('provider_request_id'))
    except TokenBudgetStop as error:
        error.request_sent = True
        raise
    return record


def usage_summary(records):
    """API token counts are provider-reported; reused local cache costs no call."""
    def all_attempts(records):
        for record in records:
            yield from all_attempts(record.get("previous_attempts",[]))
            yield record
    records=list(all_attempts(records))
    summary = {"records": len(records), "api_calls": 0, "cache_hits": 0,
        "calls_with_reported_usage": 0, "calls_without_reported_usage": 0,
        "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
        "cached_prompt_tokens": 0, "reasoning_tokens": 0}
    for record in records:
        if record.get("cache_hit"):
            summary["cache_hits"] += 1
            continue
        summary["api_calls"] += 1
        usage = record.get("response", {}).get("usage")
        if not usage:
            summary["calls_without_reported_usage"] += 1
            continue
        summary["calls_with_reported_usage"] += 1
        for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
            summary[field] += usage.get(field, 0)
        summary["cached_prompt_tokens"] += usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
        summary["reasoning_tokens"] += usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0)
    return summary


def append_feedback(messages, raw, feedback):
    """Preserve real function-call history and acknowledge every returned call."""
    message=raw["choices"][0]["message"]
    assistant={"role":"assistant","content":message.get("content") or ""}
    if "reasoning_content" in message:
        assistant["reasoning_content"] = message["reasoning_content"]
    calls=message.get("tool_calls") or []
    if calls:
        assistant["tool_calls"]=[{k:call[k] for k in ("id","type","function")} for call in calls]
    messages.append(assistant)
    if calls:
        for call in calls:
            messages.append({"role":"tool","tool_call_id":call["id"],
                "content":json.dumps(feedback,ensure_ascii=False)})
    else:
        messages.append({"role":"user","content":json.dumps(feedback,ensure_ascii=False)})
