#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL="${RA_LLM_MODEL:-qwen2.5:7b}"
PULL="${1:-}"

if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama is not installed. Install it from https://ollama.com/download" >&2
  exit 1
fi
if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "Virtual environment is missing. Run: python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt" >&2
  exit 1
fi

if ! curl --fail --silent http://127.0.0.1:11434/api/tags >/dev/null; then
  ollama serve >"$ROOT/.requirements-alchemist-ollama.log" 2>&1 &
  for _ in {1..20}; do
    curl --fail --silent http://127.0.0.1:11434/api/tags >/dev/null && break
    sleep 0.5
  done
fi
curl --fail --silent http://127.0.0.1:11434/api/tags >/dev/null || {
  echo "Ollama did not become ready at http://127.0.0.1:11434" >&2
  exit 1
}

if ! ollama list | awk 'NR > 1 {print $1}' | grep -Fxq "$MODEL"; then
  if [[ "$PULL" == "--pull" ]]; then
    ollama pull "$MODEL"
  else
    echo "Model '$MODEL' is not installed. Re-run with --pull or execute: ollama pull $MODEL" >&2
    exit 1
  fi
fi

export REQUIREMENTS_ALCHEMIST_CONFIG="$ROOT/config/requirements-alchemist.ollama.json"
export RA_LLM_PROVIDER="openai-compatible"
export RA_LLM_BASE_URL="http://127.0.0.1:11434/v1"
export RA_LLM_MODEL="$MODEL"

echo "Starting Requirements Alchemist with local Ollama model $MODEL"
echo "Open http://127.0.0.1:5070"
exec "$ROOT/.venv/bin/python" -m requirements_alchemist
