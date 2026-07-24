#!/usr/bin/env bash
# Install Python deps into ./vendor (no interactive prompts).
# Called by install.sh; safe to run standalone.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENDOR="${ROOT}/vendor"
REQ="${ROOT}/requirements.txt"

if ! command -v python3 >/dev/null 2>&1; then
  echo "error: python3 not found" >&2
  exit 1
fi

if ! python3 -m pip --version >/dev/null 2>&1 && ! command -v pip3 >/dev/null 2>&1; then
  echo "error: pip not found (install python3-pip)" >&2
  exit 1
fi

mkdir -p "${VENDOR}"

echo "==> Installing Python packages into ${VENDOR}"
echo "    requirements: ${REQ}"
echo

# Prefer python3 -m pip; stream output live (no quiet flags)
if python3 -m pip --version >/dev/null 2>&1; then
  python3 -m pip install --upgrade --disable-pip-version-check \
    -r "${REQ}" -t "${VENDOR}"
else
  pip3 install --upgrade --disable-pip-version-check \
    -r "${REQ}" -t "${VENDOR}"
fi

echo
echo "==> Done. Dependencies installed into ${VENDOR}"
