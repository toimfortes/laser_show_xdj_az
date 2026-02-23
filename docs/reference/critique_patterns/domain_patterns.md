# Domain Patterns Reference (V104)

This file is the canonical reference for domain-specific critique patterns used by
auditors. Plans and audits that claim alignment with “standard patterns” must
compare against this file row-by-row.

Status:
- This is a starter catalog for the AI Orchestrator repo. Extend it as the
  codebase evolves.

## Security

Good patterns:
- Parameterized subprocess execution (`create_subprocess_exec`, `subprocess.run([...])`)
- Path validation using `Path.resolve()` + `relative_to()` for traversal prevention
- Token or local-only dashboard controls for network services

Bad patterns (flag if present in scope):
- `shell=True` in subprocess execution (unless explicitly constrained and justified)
- `allow_origins=["*"]` with `allow_credentials=True` on CORS
- Unrestricted filesystem browsing APIs

Suggested evidence commands:
- `rg -n "shell=True" -S .`
- `rg -n "allow_origins=\\[\\\"\\*\\\"\\]" -S ai_orchestrator/dashboard`
- `rg -n "/api/browse" -S ai_orchestrator/dashboard`

## Reliability / Concurrency

Good patterns:
- Concurrency bounding (semaphores) around external process invocation
- Timeouts and cancellation cleanup that kills subprocesses
- Circuit breaker with persistence for flaky external dependencies

Bad patterns:
- `asyncio.wait_for(...)` around a coroutine that spawns subprocesses, without
  `CancelledError` cleanup in the subprocess owner
- Fire-and-forget background tasks without lifecycle management

Suggested evidence commands:
- `rg -n "asyncio\\.wait_for\\(" -S ai_orchestrator`
- `rg -n "except asyncio\\.CancelledError" -S ai_orchestrator/cli_adapters`

## Configuration / Contracts

Good patterns:
- Single source of truth for runtime dependencies (`pyproject.toml`)
- Config-driven command execution using argv lists (non-shell)
- Explicit typed config models (Pydantic v2)

Bad patterns:
- Duplicate/conflicting dependency sources (`requirements.txt` vs `pyproject.toml`) drifting
- Hardcoded model IDs in code paths that should be config-driven

Suggested evidence commands:
- `rg -n "dependencies\\s*=\\s*\\[" pyproject.toml`
- `rg -n "requirements\\.txt" -S .`

