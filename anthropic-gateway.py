#!/usr/bin/env python3
"""
anthropic-gateway.py - OpenAI-compatible API → Anthropic API format converter

Allows Claude Code (or any Anthropic SDK client) to connect to any OpenAI-compatible LLM
(e.g., local LLMs, vLLM, Ollama, LiteLLM, OpenRouter, Together AI, etc.)

Usage:
    python anthropic-gateway.py --port 8080 --target http://localhost:11434/v1 --model llama3

    Claude Code:
        ANTHROPIC_BASE_URL=http://localhost:8080 claude

Requirements:
    pip install flask requests
"""

import argparse
import json
import re
import sys
import time
import uuid
from pathlib import Path

try:
    from flask import Flask, request, Response, jsonify
    import requests
except ImportError:
    print("Install dependencies: pip install flask requests")
    sys.exit(1)

app = Flask(__name__)

# Global config
CONFIG = {
    "target_url": "",
    "target_api_key": None,
    "default_model": None,
    "max_tokens": 4096,
    "verbose": False,
}

# System prompt extraction patterns
SYSTEM_PROMPT_PATTERNS = [
    r"<system-definitions>.*?</system-definitions>",
    r"<system>.*?</system>",
    r"<instructions>.*?</instructions>",
    r"<context>.*?</context>",
]


def log(msg):
    if CONFIG["verbose"]:
        print(f"[gateway] {msg}", file=sys.stderr)


def convert_messages(messages, system_prompt=None):
    """Convert Anthropic messages format to OpenAI format."""
    openai_messages = []

    if system_prompt:
        openai_messages.append({"role": "system", "content": system_prompt})

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        # Handle content as string or list of blocks
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        tool_name = block.get("name", "")
                        tool_input = json.dumps(block.get("input", {}))
                        text_parts.append(f"[Tool Call: {tool_name}({tool_input})]")
                    elif block.get("type") == "tool_result":
                        result_content = block.get("content", "")
                        if isinstance(result_content, list):
                            result_content = " ".join(
                                b.get("text", "") for b in result_content if b.get("type") == "text"
                            )
                        text_parts.append(f"[Tool Result: {result_content}]")
                    elif block.get("type") == "image":
                        # Skip images or convert to description
                        source = block.get("source", {})
                        if source.get("type") == "base64":
                            text_parts.append(f"[Image: {source.get('media_type', 'image')}]")
                else:
                    text_parts.append(str(block))
            content = "\n".join(text_parts)

        # Map roles
        if role == "assistant":
            openai_messages.append({"role": "assistant", "content": str(content)})
        elif role == "user":
            openai_messages.append({"role": "user", "content": str(content)})
        else:
            openai_messages.append({"role": role, "content": str(content)})

    return openai_messages


def convert_tools(tools):
    """Convert Anthropic tool definitions to OpenAI function format."""
    if not tools:
        return None

    openai_tools = []
    for tool in tools:
        if tool.get("type") == "function" or "name" in tool:
            schema = tool.get("input_schema", {})
            openai_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.get("name", ""),
                        "description": tool.get("description", ""),
                        "parameters": schema,
                    },
                }
            )

    return openai_tools if openai_tools else None


def extract_system_from_messages(messages):
    """Extract Claude-style system prompts embedded in messages."""
    full_text = json.dumps(messages)
    extracted = []
    for pattern in SYSTEM_PROMPT_PATTERNS:
        matches = re.findall(pattern, full_text, re.DOTALL)
        extracted.extend(matches)
    return "\n\n".join(extracted) if extracted else None


def parse_anthropic_request(data):
    """Parse Anthropic API request and convert to OpenAI format."""
    messages = data.get("messages", [])
    system_prompt = data.get("system", "")

    # Also try extracting from messages
    extracted = extract_system_from_messages(messages)
    if extracted and not system_prompt:
        system_prompt = extracted

    # Remove system messages from the list (they're passed separately in OpenAI)
    filtered_messages = [m for m in messages if m.get("role") != "system"]

    openai_messages = convert_messages(filtered_messages, system_prompt)

    # Build OpenAI request
    model = data.get("model", CONFIG["default_model"]) or CONFIG["default_model"] or "gpt-3.5-turbo"

    # Apply model mapping (Claude model → target model)
    model_map = CONFIG.get("model_map", {})
    if model in model_map:
        original_model = model
        model = model_map[model]
        log(f"Model mapped: {original_model} → {model}")
    elif CONFIG["default_model"] and model not in model_map:
        # If default model set and no mapping found, use default
        model = CONFIG["default_model"]
        log(f"Using default model: {model}")

    openai_request = {
        "model": model,
        "messages": openai_messages,
        "max_tokens": data.get("max_tokens", CONFIG["max_tokens"]),
        "temperature": data.get("temperature", 1.0),
        "top_p": data.get("top_p", 1.0),
        "stream": data.get("stream", False),
    }

    # Add stop sequences
    if data.get("stop_sequences"):
        openai_request["stop"] = data["stop_sequences"]

    # Convert tools
    tools = convert_tools(data.get("tools"))
    if tools:
        openai_request["tools"] = tools
        # Force tool choice if present
        if data.get("tool_choice"):
            tc = data["tool_choice"]
            if isinstance(tc, dict) and tc.get("type") == "auto":
                openai_request["tool_choice"] = "auto"
            elif isinstance(tc, dict) and tc.get("type") == "any":
                openai_request["tool_choice"] = "required"
            elif isinstance(tc, dict) and tc.get("name"):
                openai_request["tool_choice"] = {"type": "function", "function": {"name": tc["name"]}}

    return openai_request


def convert_openai_response_to_anthropic(openai_response, model):
    """Convert OpenAI API response to Anthropic format."""
    choice = openai_response.get("choices", [{}])[0]
    message = choice.get("message", {})
    content = message.get("content", "")
    finish_reason = choice.get("finish_reason", "stop")

    # Map finish reasons
    reason_map = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use"}
    anthropic_stop = reason_map.get(finish_reason, "end_turn")

    response = {
        "id": openai_response.get("id", f"msg_{uuid.uuid4().hex[:24]}"),
        "type": "message",
        "role": "assistant",
        "content": [],
        "model": model,
        "stop_reason": anthropic_stop,
        "stop_sequence": None,
        "usage": {
            "input_tokens": openai_response.get("usage", {}).get("prompt_tokens", 0),
            "output_tokens": openai_response.get("usage", {}).get("completion_tokens", 0),
        },
    }

    # Handle tool calls
    tool_calls = message.get("tool_calls")
    if tool_calls:
        for tc in tool_calls:
            func = tc.get("function", {})
            response["content"].append(
                {
                    "type": "tool_use",
                    "id": tc.get("id", f"toolu_{uuid.uuid4().hex[:24]}"),
                    "name": func.get("name", ""),
                    "input": json.loads(func.get("arguments", "{}")),
                }
            )
        # Add any content text before tool calls
        if content:
            response["content"].insert(0, {"type": "text", "text": content})
    else:
        response["content"] = [{"type": "text", "text": content}]

    return response


def convert_openai_stream_chunk(line, model):
    """Convert OpenAI SSE chunk to Anthropic SSE format."""
    if not line.startswith("data: "):
        return None

    data_str = line[6:].strip()
    if data_str == "[DONE]":
        return "event: message_stop\ndata: {\"type\": \"message_stop\"}"

    try:
        chunk = json.loads(data_str)
    except json.JSONDecodeError:
        return None

    choices = chunk.get("choices", [])
    if not choices:
        return None

    choice = choices[0]
    delta = choice.get("delta", {})
    finish_reason = choice.get("finish_reason")

    msg_id = chunk.get("id", f"msg_{uuid.uuid4().hex[:24]}")

    events = []

    # Start event (first chunk)
    if "role" in delta:
        events.append(
            f"event: message_start\ndata: {json.dumps({'type': 'message_start', 'message': {'id': msg_id, 'type': 'message', 'role': 'assistant', 'content': [], 'model': model, 'stop_reason': None, 'stop_sequence': None, 'usage': {'input_tokens': 0, 'output_tokens': 0}}})}"
        )

    # Content block start (first text delta)
    if "content" in delta or "tool_calls" in delta:
        if delta.get("tool_calls"):
            tc = delta["tool_calls"][0]
            func = tc.get("function", {})
            input_str = func.get("arguments", "")
            tool_input = {}
            if input_str:
                try:
                    tool_input = json.loads(input_str)
                except json.JSONDecodeError:
                    tool_input = {"raw": input_str}

            events.append(
                f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'tool_use', 'id': tc.get('id', f'toolu_{uuid.uuid4().hex[:24]}'), 'name': func.get('name', ''), 'input': {}}})}"
            )
            if input_str:
                events.append(
                    f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'input_json_delta', 'partial_json': input_str}}})}"
                )
        else:
            events.append(
                f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}})}"
            )
            text = delta.get("content", "")
            if text:
                events.append(
                    f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': text}}})}"
                )

    # Finish reason
    if finish_reason:
        events.append("event: content_block_stop\ndata: {\"type\": \"content_block_stop\", \"index\": 0}")
        reason_map = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use"}
        stop = reason_map.get(finish_reason, "end_turn")
        events.append(
            f"event: message_delta\ndata: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': stop, 'stop_sequence': None}, 'usage': {'output_tokens': 0}})}"
        )
        events.append("event: message_stop\ndata: {\"type\": \"message_stop\"}")

    return "\n".join(events) if events else None


def make_target_request(openai_request):
    """Send request to target OpenAI-compatible API."""
    url = CONFIG["target_url"]
    if not url.endswith("/chat/completions"):
        url = url.rstrip("/") + "/chat/completions"

    headers = {"Content-Type": "application/json"}
    if CONFIG["target_api_key"]:
        headers["Authorization"] = f"Bearer {CONFIG['target_api_key']}"

    log(f"→ {openai_request['model']} | messages: {len(openai_request['messages'])} | stream: {openai_request.get('stream', False)}")

    resp = requests.post(url, json=openai_request, headers=headers, timeout=300, stream=openai_request.get("stream", False))
    return resp


# --- Anthropic API endpoints ---


@app.route("/v1/messages", methods=["POST"])
def messages():
    """Anthropic Messages API → OpenAI Chat Completions."""
    data = request.get_json(force=True)
    log(f"← /v1/messages | model: {data.get('model', 'default')}")

    openai_request = parse_anthropic_request(data)
    model = openai_request["model"]

    if openai_request.get("stream"):
        return Response(
            stream_anthropic_response(openai_request, model),
            content_type="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
        )
    else:
        resp = make_target_request(openai_request)
        if resp.status_code != 200:
            error_body = resp.text
            try:
                error_json = resp.json()
                error_msg = error_json.get("error", {}).get("message", error_body)
            except Exception:
                error_msg = error_body
            return jsonify(
                {
                    "type": "error",
                    "error": {"type": "api_error", "message": f"Target API error ({resp.status_code}): {error_msg}"},
                }
            ), resp.status_code

        anthropic_resp = convert_openai_response_to_anthropic(resp.json(), model)
        return jsonify(anthropic_resp)


def stream_anthropic_response(openai_request, model):
    """Stream converted SSE events."""
    resp = make_target_request(openai_request)
    if resp.status_code != 200:
        yield f"event: error\ndata: {json.dumps({'type': 'error', 'error': {'type': 'api_error', 'message': f'Target API error: {resp.status_code}'}})}"
        return

    msg_id = f"msg_{uuid.uuid4().hex[:24]}"
    # Send message_start
    yield f"event: message_start\ndata: {json.dumps({'type': 'message_start', 'message': {'id': msg_id, 'type': 'message', 'role': 'assistant', 'content': [], 'model': model, 'stop_reason': None, 'stop_sequence': None, 'usage': {'input_tokens': 0, 'output_tokens': 0}}})}"

    for line in resp.iter_lines(decode_unicode=True):
        if not line:
            continue
        converted = convert_openai_stream_chunk(line, model)
        if converted:
            for event_line in converted.split("\n"):
                yield event_line + "\n\n"


@app.route("/v1/complete", methods=["POST"])
def complete():
    """Anthropic Complete API (legacy) → OpenAI Chat Completions."""
    data = request.get_json(force=True)
    prompt = data.get("prompt", "")
    model = data.get("model", CONFIG["default_model"]) or "gpt-3.5-turbo"

    openai_request = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": data.get("max_tokens_to_sample", CONFIG["max_tokens"]),
        "temperature": data.get("temperature", 1.0),
        "stream": data.get("stream", False),
    }

    resp = make_target_request(openai_request)
    if resp.status_code != 200:
        return jsonify({"type": "error", "error": {"type": "api_error", "message": resp.text}}), resp.status_code

    openai_resp = resp.json()
    text = openai_resp.get("choices", [{}])[0].get("message", {}).get("content", "")

    return jsonify(
        {
            "completion": text,
            "stop_reason": "stop_sequence" if data.get("stop_sequences") else "max_tokens",
            "model": model,
        }
    )


@app.route("/", methods=["GET"])
def health():
    return jsonify(
        {
            "service": "anthropic-gateway",
            "target": CONFIG["target_url"],
            "model": CONFIG["default_model"],
            "status": "ok",
        }
    )


def main():
    parser = argparse.ArgumentParser(description="OpenAI-compatible → Anthropic API Gateway")
    parser.add_argument("--port", "-p", type=int, default=8080, help="Gateway port (default: 8080)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Gateway host (default: 0.0.0.0)")
    parser.add_argument("--target", "-t", required=True, help="Target OpenAI-compatible API URL (e.g., http://localhost:11434/v1)")
    parser.add_argument("--api-key", "-k", help="Target API key (Bearer token)")
    parser.add_argument("--model", "-m", default=None, help="Default model (overrides client model)")
    parser.add_argument("--model-map", type=str, default=None, help='Model mapping JSON file or inline JSON, e.g. \'{"claude-3-5-sonnet-20241022": "llama3", "claude-3-opus-20240229": "qwen2.5:72b"}\'')
    parser.add_argument("--max-tokens", type=int, default=4096, help="Default max tokens (default: 4096)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()

    CONFIG["target_url"] = args.target
    CONFIG["target_api_key"] = args.api_key
    CONFIG["default_model"] = args.model
    CONFIG["max_tokens"] = args.max_tokens
    CONFIG["verbose"] = args.verbose

    # Load model mapping
    model_map = {}
    if args.model_map:
        try:
            if Path(args.model_map).exists():
                with open(args.model_map) as f:
                    model_map = json.load(f)
                log(f"Loaded model map from file: {args.model_map}")
            else:
                model_map = json.loads(args.model_map)
                log(f"Loaded inline model map: {len(model_map)} entries")
        except Exception as e:
            print(f"[gateway] Warning: Failed to parse model map: {e}", file=sys.stderr)
    CONFIG["model_map"] = model_map

    print(f"""
╔══════════════════════════════════════════════╗
║       Anthropic Gateway                      ║
║       OpenAI API → Anthropic API             ║
╠══════════════════════════════════════════════╣
║  Target:  {args.target:<37s}║
║  Model:   {(args.model or 'client-specified'):<37s}║
║  Port:    {str(args.port):<37s}║
╚══════════════════════════════════════════════╝

Usage with Claude Code:
    ANTHROPIC_BASE_URL=http://localhost:{args.port} claude

Usage with Anthropic SDK:
    client = Anthropic(base_url="http://localhost:{args.port}")

Supported endpoints:
    POST /v1/messages  (Messages API)
    POST /v1/complete  (Legacy Complete API)
""")

    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
