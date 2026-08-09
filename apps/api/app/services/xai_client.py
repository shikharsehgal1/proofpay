"""Real xAI / SpaceXAI Grok client. No mocked responses."""

from __future__ import annotations

import json
from typing import Any, Optional

from openai import AsyncOpenAI

from app.config import get_settings
from app.schemas import ExecutableContract


class XAINotConfigured(RuntimeError):
    """Raised when XAI_API_KEY is missing — never silently faked."""

    def __init__(self) -> None:
        super().__init__(
            "XAI_API_KEY is not configured. Set it in .env from https://console.x.ai. "
            "ProofPay will not return synthetic Grok responses."
        )


def require_xai() -> None:
    if not get_settings().xai_configured:
        raise XAINotConfigured()


def get_async_client() -> AsyncOpenAI:
    require_xai()
    s = get_settings()
    return AsyncOpenAI(api_key=s.xai_api_key, base_url=s.xai_base_url)


async def chat_text(
    system: str,
    user: str,
    *,
    model: Optional[str] = None,
    temperature: float = 0.2,
) -> str:
    client = get_async_client()
    s = get_settings()
    resp = await client.chat.completions.create(
        model=model or s.xai_model,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return resp.choices[0].message.content or ""


async def structured_contract(
    *,
    natural_language: str,
    repository_url: str,
    baseline_ref: str,
    title: str,
    reward_amount: float,
    reward_currency: str,
) -> ExecutableContract:
    """Compile natural-language bounty into an executable contract via structured outputs."""
    require_xai()
    client = get_async_client()
    s = get_settings()

    system = (
        "You are ProofPay's bounty contract compiler. "
        "Convert the creator's natural-language bounty into a precise executable evaluation contract. "
        "Prefer commands that work for a typical Python repo with pytest and a bench/ script. "
        "Hidden tests must not be inventable by candidates from the public repo alone — "
        "describe them as commands that ProofPay will run from protected evaluator assets. "
        "Do not invent impossible infrastructure. Be concrete and runnable."
    )
    user = json.dumps(
        {
            "title": title,
            "reward": f"{reward_amount} {reward_currency}",
            "natural_language": natural_language,
            "repository_url": repository_url,
            "baseline_ref": baseline_ref,
            "guidance": {
                "default_build": "pip install -e '.[dev]'",
                "default_visible_tests": "pytest -q tests/visible -q",
                "default_hidden_tests": "pytest -q /eval/hidden -q",
                "default_benchmark": "python /eval/bench.py --json",
            },
        },
        indent=2,
    )

    schema = ExecutableContract.model_json_schema()
    # xAI structured outputs: additionalProperties defaults false; clean schema
    def _strip_unsupported(obj: Any) -> Any:
        if isinstance(obj, dict):
            obj = {
                k: _strip_unsupported(v)
                for k, v in obj.items()
                if k not in ("title", "default", "$defs")
            }
            if obj.get("type") == "object" and "additionalProperties" not in obj:
                obj["additionalProperties"] = False
            return obj
        if isinstance(obj, list):
            return [_strip_unsupported(x) for x in obj]
        return obj

    clean_schema = _strip_unsupported(schema)

    try:
        completion = await client.beta.chat.completions.parse(
            model=s.xai_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format=ExecutableContract,
            temperature=0.1,
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise RuntimeError("Grok returned empty structured contract")
        parsed.repository_url = repository_url
        parsed.baseline_ref = baseline_ref
        return parsed
    except Exception:
        completion = await client.chat.completions.create(
            model=s.xai_model,
            temperature=0.1,
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": user
                    + "\n\nRespond with a single JSON object matching the executable contract schema.",
                },
            ],
            response_format={"type": "json_object"},
        )
        content = completion.choices[0].message.content or "{}"
        data = json.loads(content)
        data["repository_url"] = repository_url
        data["baseline_ref"] = baseline_ref
        return ExecutableContract.model_validate(data)



async def tool_loop(
    *,
    system: str,
    user: str,
    tools: list[dict[str, Any]],
    tool_executor,
    max_rounds: int = 12,
    model: Optional[str] = None,
) -> dict[str, Any]:
    """
    Run a Grok function-calling investigation loop.
    tool_executor(name: str, args: dict) -> str | dict
    Returns final message content + tool transcript. Never fabricates tool results.
    """
    client = get_async_client()
    s = get_settings()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    transcript: list[dict[str, Any]] = []

    for _ in range(max_rounds):
        resp = await client.chat.completions.create(
            model=model or s.xai_model,
            temperature=0.15,
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )
        msg = resp.choices[0].message
        tool_calls = msg.tool_calls or []
        if not tool_calls:
            return {
                "final": msg.content or "",
                "transcript": transcript,
                "messages": messages,
            }

        messages.append(
            {
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls
                ],
            }
        )
        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = await tool_executor(name, args)
            if not isinstance(result, str):
                result_str = json.dumps(result, default=str)
            else:
                result_str = result
            transcript.append({"tool": name, "args": args, "result": result_str[:50_000]})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_str[:50_000],
                }
            )

    return {
        "final": "Investigation stopped after max tool rounds.",
        "transcript": transcript,
        "messages": messages,
    }


async def generate_image_url(prompt: str) -> Optional[str]:
    """Generate an image via Grok Imagine. Returns URL or b64 data URI if available."""
    require_xai()
    client = get_async_client()
    s = get_settings()
    try:
        # OpenAI-compatible images API
        result = await client.images.generate(
            model=s.xai_imagine_image_model,
            prompt=prompt,
            n=1,
        )
        item = result.data[0]
        url = getattr(item, "url", None)
        if url:
            return url
        b64 = getattr(item, "b64_json", None)
        if b64:
            return f"data:image/png;base64,{b64}"
        return None
    except Exception as exc:
        raise RuntimeError(
            f"Imagine image generation failed (real API error, not simulated): {exc}"
        ) from exc
