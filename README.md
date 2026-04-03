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
```

### Option 1: Claude Code 환경변수 (recommended — cleanest)

Claude Code의 환경변수로 모델을 직접 지정하면 gateway는 그대로 통과시킵니다.

```bash
# Sonnet / Opus / Haiku 각각 다른 모델 매핑
ANTHROPIC_BASE_URL=http://localhost:8080 \
ANTHROPIC_DEFAULT_SONNET_MODEL=llama3 \
ANTHROPIC_DEFAULT_OPUS_MODEL=qwen2.5:72b \
ANTHROPIC_DEFAULT_HAIKU_MODEL=phi3:mini \
claude

# 하나만 지정
ANTHROPIC_BASE_URL=http://localhost:8080 \
ANTHROPIC_DEFAULT_SONNET_MODEL=llama3 \
claude
```

| 환경변수 | 설명 |
|---------|------|
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | Claude Code 기본 모델 (Sonnet) 대체 |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | Claude Code Opus 모델 대체 |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | Claude Code Haiku 모델 대체 |

### Option 2: --model-map (다중 모델 라우팅)

```bash
python anthropic-gateway.py -t http://localhost:11434/v1 \
  --model-map '{"claude-3-5-sonnet-20241022": "llama3", "claude-3-opus-20240229": "qwen2.5:72b"}' \
  -p 8080
ANTHROPIC_BASE_URL=http://localhost:8080 claude
```

### Option 3: --model (모든 요청을 하나의 모델로)

```bash
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
