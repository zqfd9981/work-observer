"""有界真实 HTTP 检查；不沿用聊天或 Codex 的登录令牌。"""

import json

import httpx
from jsonschema import ValidationError, validate

from work_observer.config import Settings, validate_url
from work_observer.evidence import Evidence


async def post(client, url, key, payload, evidence, name):
    evidence.save(f"{name}.request.json", payload)
    response = await client.post(
        url,
        headers={"Authorization": f"Bearer {key}"},
        json=payload,
    )
    try:
        body = response.json()
    except ValueError:
        body = {"non_json_response": response.text}
    evidence.save(f"{name}.json", {"status_code": response.status_code, "body": body})
    if not response.is_success:
        code = {
            401: "AUTH_REQUIRED",
            403: "FORBIDDEN",
            429: "RATE_LIMIT_OR_QUOTA",
            400: "INVALID_REQUEST",
            404: "ENDPOINT_OR_MODEL_NOT_FOUND",
            422: "INVALID_REQUEST",
        }.get(response.status_code, "HTTP_ERROR")
        return None, {"status": "failed", "error_code": code, "http_status": response.status_code}
    return body, None


async def probe_search(settings: Settings, evidence: Evidence):
    if settings.search_provider == "openai":
        return await probe_openai_search(settings, evidence)
    key = settings.tavily_api_key.get_secret_value()
    if not key:
        return {"status": "missing_config", "required": ["TAVILY_API_KEY"]}
    payload = {
        "query": "上海 AI Agent 应用开发 企业 产品 官方资料",
        "search_depth": "basic",
        "max_results": 3,
        "include_answer": False,
        "include_raw_content": False,
        "include_usage": True,
    }
    async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
        body, error = await post(
            client, "https://api.tavily.com/search", key, payload, evidence, "search.tavily"
        )
    if error:
        return error
    results = body.get("results") if isinstance(body, dict) else None
    if not isinstance(results, list) or not results:
        return {"status": "failed", "error_code": "EMPTY_OR_UNEXPECTED_SEARCH"}
    if not all(isinstance(r, dict) and r.get("url") and r.get("content") for r in results):
        return {"status": "failed", "error_code": "INCOMPLETE_SEARCH_RESULT"}
    return {"status": "passed", "results_received": len(results), "usage": body.get("usage")}


async def probe_openai_search(settings: Settings, evidence: Evidence):
    key = settings.model_api_key.get_secret_value()
    missing = [
        name
        for name, value in [
            ("WO_MODEL_BASE_URL", settings.model_base_url),
            ("WO_MODEL_NAME", settings.model_name),
            ("WO_MODEL_API_KEY", key),
        ]
        if not value
    ]
    if missing:
        return {"status": "missing_config", "provider": "openai", "required": missing}
    url = validate_url(settings.model_base_url) + "/responses"
    payload = {
        "model": settings.model_name,
        "store": False,
        "max_output_tokens": 1600,
        "input": (
            "仅执行一次网页搜索：MiniMax 官方 Agent 产品主页。"
            "返回一个官网来源链接及一句中文说明并引用，不再补查。"
        ),
        "tools": [{"type": "web_search", "search_context_size": "low"}],
        "tool_choice": {"type": "web_search"},
        "max_tool_calls": 1,
        "include": ["web_search_call.action.sources"],
    }
    if settings.model_name.startswith(("gpt-5", "gpt-6")):
        payload["reasoning"] = {"effort": "low"}
    async with httpx.AsyncClient(timeout=90, follow_redirects=False) as client:
        body, error = await post(client, url, key, payload, evidence, "search.openai")
    if error:
        return {**error, "provider": "openai"}
    if not isinstance(body, dict) or body.get("status") != "completed":
        return {"status": "failed", "provider": "openai", "error_code": "RESPONSE_INCOMPLETE"}
    output = body.get("output", [])
    calls = [item for item in output if item.get("type") == "web_search_call"]
    sources = [
        s
        for call in calls
        for s in call.get("action", {}).get("sources", [])
        if isinstance(s, dict) and s.get("url", "").startswith(("https://", "http://"))
    ]
    citations = [
        a
        for item in output
        if item.get("type") == "message"
        for part in item.get("content", [])
        for a in part.get("annotations", [])
        if a.get("type") == "url_citation" and a.get("url")
    ]
    if len(calls) > 1:
        return {
            "status": "failed",
            "provider": "openai",
            "error_code": "SEARCH_CALL_LIMIT_EXCEEDED",
        }
    if (
        not calls
        or not sources
        or not citations
        or any(c.get("status") != "completed" for c in calls)
    ):
        return {"status": "failed", "provider": "openai", "error_code": "NO_VERIFIED_WEB_SEARCH"}
    return {
        "status": "passed",
        "provider": "openai",
        "search_calls": len(calls),
        "results_received": len({s["url"] for s in sources}),
        "citations_received": len(citations),
        "usage": body.get("usage"),
    }


async def probe_model(settings: Settings, evidence: Evidence):
    key = settings.model_api_key.get_secret_value()
    missing = [
        name
        for name, value in [
            ("WO_MODEL_BASE_URL", settings.model_base_url),
            ("WO_MODEL_NAME", settings.model_name),
            ("WO_MODEL_API_KEY", key),
        ]
        if not value
    ]
    if missing:
        return {"status": "missing_config", "required": missing}
    responses = settings.model_api == "responses"
    url = validate_url(settings.model_base_url) + (
        "/responses" if responses else "/chat/completions"
    )
    schema = {
        "type": "object",
        "properties": {"status": {"type": "string", "enum": ["连接成功"]}},
        "required": ["status"],
        "additionalProperties": False,
    }
    base = {"model": settings.model_name}
    if responses:
        base.update(max_output_tokens=1024, store=False)
        if settings.model_name.startswith(("gpt-5", "gpt-6")):
            base["reasoning"] = {"effort": "low"}
    else:
        base["max_completion_tokens"] = 1024
        if settings.model_name.startswith("gpt-6"):
            base["reasoning_effort"] = "none"
    structured = {
        **base,
        "messages": [{"role": "user", "content": "用 JSON 返回 status 为“连接成功”。"}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "connection_probe",
                "strict": True,
                "schema": schema,
            },
        },
    }
    if responses:
        structured = {
            **base,
            "input": "用 JSON 返回 status 为“连接成功”。",
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "connection_probe",
                    "strict": True,
                    "schema": schema,
                }
            },
        }
    result = {
        "status": "failed",
        "api": settings.model_api,
        "model": settings.model_name,
        "structured_output": False,
        "tool_calling": False,
    }
    async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
        body, error = await post(client, url, key, structured, evidence, "model.structured")
        if error:
            return {**result, **error}
        if responses and body.get("status") != "completed":
            return {**result, "error_code": "RESPONSE_INCOMPLETE"}
        try:
            if responses:
                text = "".join(
                    part["text"]
                    for item in body["output"]
                    if item.get("type") == "message"
                    for part in item["content"]
                    if part.get("type") == "output_text"
                )
            else:
                text = body["choices"][0]["message"]["content"]
            validate(json.loads(text), schema)
        except (KeyError, IndexError, TypeError, ValueError, ValidationError):
            return {**result, "error_code": "UNEXPECTED_MODEL_OUTPUT"}
        result["structured_output"] = True
        result["structured_usage"] = body.get("usage")
        # 仅要求产生工具调用，不执行任何外部操作。
        tool_payload = {
            **base,
            "messages": [{"role": "user", "content": "请调用 connection_probe 确认连接。"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "connection_probe",
                        "description": "确认连接，不执行外部操作",
                        "parameters": schema,
                        "strict": True,
                    },
                }
            ],
            "tool_choice": {"type": "function", "function": {"name": "connection_probe"}},
        }
        if responses:
            tool_payload = {
                **base,
                "input": "请调用 connection_probe 确认连接，status 填写“连接成功”。",
                "tools": [
                    {
                        "type": "function",
                        "name": "connection_probe",
                        "description": "确认连接，不执行外部操作",
                        "parameters": schema,
                        "strict": True,
                    }
                ],
                "tool_choice": {"type": "function", "name": "connection_probe"},
            }
        body, error = await post(client, url, key, tool_payload, evidence, "model.tools")
        if error:
            return {**result, "status": "partial", "error_code": error["error_code"]}
        if responses and body.get("status") != "completed":
            return {**result, "status": "partial", "error_code": "RESPONSE_INCOMPLETE"}
        try:
            if responses:
                call = next(item for item in body["output"] if item.get("type") == "function_call")
            else:
                call = body["choices"][0]["message"]["tool_calls"][0]["function"]
            if call["name"] != "connection_probe":
                raise ValueError("unexpected function")
            validate(json.loads(call["arguments"]), schema)
        except (KeyError, IndexError, TypeError, ValueError, ValidationError, StopIteration):
            return {**result, "status": "partial", "error_code": "UNEXPECTED_TOOL_CALL"}
    result.update(status="passed", tool_calling=True, tool_usage=body.get("usage"))
    return result
