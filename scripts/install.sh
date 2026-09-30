#!/usr/bin/env bash
# Install everything the PR-UX Assurance Agent needs on Linux, macOS or Git Bash.
# Windows PowerShell users: run scripts/install.ps1 instead.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/install.sh [options]

Always installed: Python virtual environment (.venv), Python packages from
requirements.txt, Playwright Chromium, and .env copied from .env.example.

Options:
  --with-evaluation     DeepEval advisory judge (requirements-evaluation.txt)
  --with-ollama         Ollama local model runtime (advisory judge, Requirements Alchemist)
  --pull-model          download qwen2.5:7b into Ollama (about 4.7 GB; implies --with-ollama)
  --with-k6             k6 for browser journeys and load profiles
  --with-lighthouse     Lighthouse CI (@lhci/cli, needs Node.js and npm)
  --with-observability  check Docker, create observability/.env, pull the Grafana stack images
  --all                 every optional component except --pull-model
  --system-deps         also install OS packages Playwright Chromium needs (Linux, uses sudo)
  --test                run the test suite after installing
  -h, --help            show this help

Environment: PYTHON=<python 3.10+ executable>, VENV_DIR=<virtual environment path>.
EOF
}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${VENV_DIR:-$ROOT/.venv}"
WITH_EVALUATION=0 WITH_OLLAMA=0 PULL_MODEL=0 WITH_K6=0 WITH_LIGHTHOUSE=0 WITH_OBSERVABILITY=0
SYSTEM_DEPS=0 RUN_TESTS=0
OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:7b}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-evaluation) WITH_EVALUATION=1 ;;
    --with-ollama) WITH_OLLAMA=1 ;;
    --pull-model) WITH_OLLAMA=1; PULL_MODEL=1 ;;
    --with-k6) WITH_K6=1 ;;
    --with-lighthouse) WITH_LIGHTHOUSE=1 ;;
    --with-observability) WITH_OBSERVABILITY=1 ;;
    --all) WITH_EVALUATION=1; WITH_OLLAMA=1; WITH_K6=1; WITH_LIGHTHOUSE=1; WITH_OBSERVABILITY=1 ;;
    --system-deps) SYSTEM_DEPS=1 ;;
    --test) RUN_TESTS=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

log() { printf '\n==> %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) PLATFORM=windows ;;
  Darwin) PLATFORM=macos ;;
  *) PLATFORM=linux ;;
esac

find_python() {
  local candidate
  for candidate in "${PYTHON:-}" python3.14 python3.13 python3.12 python3.11 python3.10 python3 python; do
    [[ -n "$candidate" ]] && have "$candidate" || continue
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

install_python() {
  if [[ $PLATFORM == macos ]] && have brew; then
    brew install python@3.13
  elif [[ $PLATFORM == linux && $SYSTEM_DEPS == 1 ]] && have apt-get; then
    sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip
  fi
}

venv_python() {
  if [[ -x "$VENV_DIR/bin/python" ]]; then
    echo "$VENV_DIR/bin/python"
  elif [[ $PLATFORM == windows && -f "$VENV_DIR/Scripts/python.exe" ]]; then
    echo "$VENV_DIR/Scripts/python.exe"
  fi
  return 0
}

install_with_brew_or_hint() {
  local command=$1 brew_package=$2 hint=$3
  if have "$command"; then
    echo "$command is already installed"
  elif have brew; then
    brew install "$brew_package"
  elif [[ $PLATFORM == windows ]] && have winget; then
    winget install --id "$4" -e --accept-source-agreements --accept-package-agreements
  else
    warn "$command is not installed. $hint"
  fi
}

log "Python 3.10+"
PY="$(find_python || true)"
if [[ -z "$PY" ]]; then
  install_python || true
  PY="$(find_python || true)"
fi
[[ -n "$PY" ]] || die "Python 3.10 or newer is required. Install it from https://www.python.org/downloads/ (Debian/Ubuntu: sudo apt install python3 python3-venv, or re-run with --system-deps), then set PYTHON=<path> if it is not on PATH."
echo "Using $PY ($("$PY" --version 2>&1))"

log "Virtual environment: $VENV_DIR"
if [[ $PLATFORM != windows && -f "$VENV_DIR/Scripts/python.exe" && ! -x "$VENV_DIR/bin/python" ]]; then
  die "$VENV_DIR is a Windows virtual environment. Run scripts/install.ps1 from PowerShell, or set VENV_DIR=.venv-linux to create a separate one here."
fi
VPY="$(venv_python)"
if [[ -z "$VPY" ]]; then
  "$PY" -m venv "$VENV_DIR" || die "Could not create the virtual environment. On Debian/Ubuntu install python3-venv."
  VPY="$(venv_python)"
fi
"$VPY" -m pip install --upgrade pip

log "Python packages"
"$VPY" -m pip install -r "$ROOT/requirements.txt"
if [[ $WITH_EVALUATION == 1 ]]; then
  "$VPY" -m pip install -r "$ROOT/requirements-evaluation.txt"
fi

log "Playwright Chromium"
if [[ $SYSTEM_DEPS == 1 && $PLATFORM == linux ]]; then
  "$VPY" -m playwright install --with-deps chromium
else
  "$VPY" -m playwright install chromium
fi

log "Configuration"
if [[ -f "$ROOT/.env" ]]; then
  echo ".env already exists; left unchanged"
else
  cp "$ROOT/.env.example" "$ROOT/.env"
  echo "Created .env from .env.example. Set STAGE_PASSWORD (and OPENAI_API_KEY for live LLM runs) before running."
fi

if [[ $WITH_OLLAMA == 1 ]]; then
  log "Ollama"
  if have ollama; then
    echo "ollama is already installed"
  elif [[ $PLATFORM == linux ]]; then
    curl -fsSL https://ollama.com/install.sh | sh
  else
    install_with_brew_or_hint ollama ollama "Install it from https://ollama.com/download" Ollama.Ollama
  fi
  if [[ $PULL_MODEL == 1 ]]; then
    have ollama || die "Ollama is not available on PATH; cannot pull $OLLAMA_MODEL."
    ollama pull "$OLLAMA_MODEL"
  fi
fi

if [[ $WITH_K6 == 1 ]]; then
  log "k6"
  install_with_brew_or_hint k6 k6 "Install it from https://grafana.com/docs/k6/latest/set-up/install-k6/" GrafanaLabs.k6
fi

if [[ $WITH_LIGHTHOUSE == 1 ]]; then
  log "Lighthouse CI"
  if have lhci; then
    echo "lhci is already installed"
  elif have npm; then
    npm install -g @lhci/cli
  else
    warn "npm is not installed. Install Node.js LTS from https://nodejs.org, then run: npm install -g @lhci/cli"
  fi
fi

if [[ $WITH_OBSERVABILITY == 1 ]]; then
  log "Observability stack"
  if [[ ! -f "$ROOT/observability/.env" ]]; then
    printf 'GRAFANA_ADMIN_PASSWORD=%s\n' "$("$VPY" -c 'import secrets; print(secrets.token_urlsafe(18))')" \
      > "$ROOT/observability/.env"
    echo "Created observability/.env with a random Grafana admin password (read it from that file)."
  fi
  if have docker && docker compose version >/dev/null 2>&1; then
    docker compose -f "$ROOT/observability/compose.yaml" --env-file "$ROOT/observability/.env" pull
  else
    warn "Docker with the compose plugin is not installed. Install Docker Desktop or Docker Engine: https://docs.docker.com/get-docker/"
  fi
fi

log "Verifying"
"$VPY" -c "import flask, playwright, pydantic, openai, mcp, langgraph, numpy, jinja2, openpyxl; print('Python packages import correctly')"
if [[ $RUN_TESTS == 1 ]]; then
  (cd "$ROOT" && "$VPY" -m pytest -q)
fi

cat <<EOF

PR-UX Assurance Agent is installed.
Next steps:
  1. Edit .env and set STAGE_PASSWORD (OPENAI_API_KEY is optional; replay mode works without it).
  2. $VPY -m agent ingest
  3. $VPY -m agent run --all --start-stage
EOF
