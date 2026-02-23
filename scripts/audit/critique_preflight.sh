#!/usr/bin/env bash
set -euo pipefail

# Wrapper referenced by docs/reference/critique_implementation.md.
# This keeps invocation consistent across repos and supports namespaced artifacts.

TAG="${AGENT_TAG:-}"

if [[ -n "${TAG}" ]]; then
  python scripts/audit/critique_preflight.py --agent-tag "${TAG}"
else
  python scripts/audit/critique_preflight.py
fi

