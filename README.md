# Anthropic Gateway

OpenAI-compatible API → Anthropic API format converter.  
Allows Claude Code to connect to any OpenAI-compatible LLM (Ollama, vLLM, LiteLLM, OpenRouter, Together AI, etc.)

## Features

- ✅ `/v1/messages` (Anthropic Messages API) — full support
- ✅ `/v1/complete` (Legacy Complete API)
- ✅ Streaming (SSE) support
- ✅ Tool/Function calling conversion
- ✅ System prompt handling
- ✅ Multi-turn conversations

## Install

```bash
pip install flask requests
```

## Usage

```bash
# Ollama
python anthropic-gateway.py --target http://localhost:11434/v1 --model llama3

# vLLM
python anthropic-gateway.py --target http://localhost:8000/v1 --model meta-llama/Llama-3-8B

# OpenRouter
python anthropic-gateway.py --target https://openrouter.ai/api/v1 --api-key sk-or-xxx --model meta-llama/llama-3-8b-instruct

# Together AI
python anthropic-gateway.py --target https://api.together.xyz/v1 --api-key xxx --model meta-llama/Llama-3-8b-chat

# LiteLLM proxy
python anthropic-gateway.py --target http://localhost:4000/v1
```

## Claude Code

```bash
# Start gateway
python anthropic-gateway.py -t http://localhost:11434/v1 -p 8080

# Option 1: ANTHROPIC_DEFAULT_SONNET_MODEL (recommended — cleanest)
ANTHROPIC_BASE_URL=http://localhost:8080 \
ANTHROPIC_DEFAULT_SONNET_MODEL=llama3 \
claude

# Option 2: --model-map for multi-model routing
python anthropic-gateway.py -t http://localhost:11434/v1 \
  --model-map '{"claude-3-5-sonnet-20241022": "llama3"}' \
  -p 8080
ANTHROPIC_BASE_URL=http://localhost:8080 claude

# Option 3: --model (all requests use same model)
python anthropic-gateway.py -t http://localhost:11434/v1 -m llama3 -p 8080
ANTHROPIC_BASE_URL=http://localhost:8080 claude
```

## Anthropic Python SDK

```python
from anthropic import Anthropic

client = Anthropic(base_url="http://localhost:8080")
response = client.messages.create(
    model="llama3",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.content[0].text)
```

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--port, -p` | 8080 | Gateway listen port |
| `--host` | 0.0.0.0 | Gateway listen host |
| `--target, -t` | (required) | Target OpenAI-compatible API URL |
| `--api-key, -k` | None | Target API Bearer token |
| `--model, -m` | None | Default model (overrides client) |
| `--max-tokens` | 4096 | Default max tokens |
| `--verbose, -v` | false | Enable logging |

## How It Works

```
Claude Code ──(Anthropic API)──► Gateway ──(OpenAI API)──► Ollama/vLLM/OpenRouter
```

The gateway converts:
- Anthropic message format → OpenAI chat format
- Anthropic tool definitions → OpenAI function calling
- Anthropic SSE events → OpenAI SSE events
- System prompts handling
