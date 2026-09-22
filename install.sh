#!/usr/bin/env bash
set -euo pipefail

# Band - Agent Harness & Verification FSM Installer
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/jiva-studio/band/main/install.sh | bash
#   ./install.sh [target_directory]

TARGET_DIR="${1:-.}"
AGENTS_DIR="${TARGET_DIR}/.agents"

echo "🥁 Installing Band Agent Harness into: ${AGENTS_DIR}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" >/dev/null 2>&1 && pwd || echo "")"

if [[ -d "${SCRIPT_DIR}/band" && -d "${SCRIPT_DIR}/pipelines" ]]; then
  # Local source directory
  mkdir -p "${AGENTS_DIR}"
  cp -r "${SCRIPT_DIR}/band" "${AGENTS_DIR}/"
  cp -r "${SCRIPT_DIR}/pipelines" "${AGENTS_DIR}/"
  cp -r "${SCRIPT_DIR}/skills" "${AGENTS_DIR}/"
  cp "${SCRIPT_DIR}/hooks.json" "${AGENTS_DIR}/"
else
  # Remote curl execution
  TMP_DIR="$(mktemp -d)"
  trap 'rm -rf "${TMP_DIR}"' EXIT

  echo "==> Downloading latest Band release..."
  if command -v git >/dev/null 2>&1; then
    git clone --depth 1 https://github.com/jiva-studio/band.git "${TMP_DIR}/band" >/dev/null 2>&1
    mkdir -p "${AGENTS_DIR}"
    cp -r "${TMP_DIR}/band/band" "${AGENTS_DIR}/"
    cp -r "${TMP_DIR}/band/pipelines" "${AGENTS_DIR}/"
    cp -r "${TMP_DIR}/band/skills" "${AGENTS_DIR}/"
    cp "${TMP_DIR}/band/hooks.json" "${AGENTS_DIR}/"
  else
    echo "Error: 'git' is required to fetch Band." >&2
    exit 1
  fi
fi

chmod -R u+rw "${AGENTS_DIR}"

# Create ignore files for agents without active hooks support
for ignore_file in "${TARGET_DIR}/.cursorignore" "${TARGET_DIR}/.rooignore" "${TARGET_DIR}/.clineignore" "${TARGET_DIR}/.aiderignore"; do
  if [[ ! -f "${ignore_file}" ]] || ! grep -q "artifacts/state.json" "${ignore_file}" 2>/dev/null; then
    mkdir -p "$(dirname "${ignore_file}")"
    cat <<'EOF' >> "${ignore_file}"
# Band protected state and pipeline definitions
**/.agents/tasks/*/artifacts/state.json
**/.agents/pipelines/**
**/.agents/band/**
EOF
  fi
done

echo "✅ Band harness successfully installed at ${AGENTS_DIR}"
echo ""
echo "Security & Verification Gates Enabled:"
echo "  🛡️ PreToolUse Gate:  python3 -m band --guard (protects state.json & pipelines)"
echo "  🛑 Stop Hook:        python3 -m band --hook  (validates stage claims & FSM)"
echo ""
echo "Next steps:"
echo "  1. Review pipelines in .agents/pipelines/"
echo "  2. Register .agents/hooks.json with your agent runner"
echo "  3. Start a pipeline with: PYTHONPATH=.agents python3 -m band --start-pipeline .agents/tasks/<task-slug>/done.yaml"

