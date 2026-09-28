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
  cp -r "${SCRIPT_DIR}/bin" "${AGENTS_DIR}/"
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
    cp -r "${TMP_DIR}/band/bin" "${AGENTS_DIR}/"
    cp "${TMP_DIR}/band/hooks.json" "${AGENTS_DIR}/"
  else
    echo "Error: 'git' is required to fetch Band." >&2
    exit 1
  fi
fi

chmod -R u+rw "${AGENTS_DIR}"
chmod +x "${AGENTS_DIR}/bin/band"

echo "✅ Band harness successfully installed at ${AGENTS_DIR}"
echo ""
echo "Launcher: sh .agents/bin/band  (uses \$BAND_PYTHON, python3, python, or 'uv run --no-project python')"
echo ""
echo "Security & Verification Gates:"
echo "  🛡️ PreToolUse Gate:  sh .agents/bin/band --guard (protects state.json & pipelines)"
echo "  🛑 Stop Hook:        sh .agents/bin/band --hook  (validates stage claims & FSM)"
echo ""
echo "Next steps:"
echo "  1. Run 'sh .agents/bin/band --init' (or /band-install) to wire hooks into .agents/hooks.json"
echo "     and .claude/settings.json (Claude Code), and link skills into .claude/skills/"
echo "  2. Run 'sh .agents/bin/band --doctor' to verify environment readiness"
echo "  3. Start task intent with /intent <task-slug>"

