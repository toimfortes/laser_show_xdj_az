# Autonomous Solver Workflow Implementation Plan (v1.0)

## 0) Quick Summary

- Objective: make the orchestrator solve issues end-to-end (not stop at reporting) while preserving explicit human control for risk.
- Problem statement: current flow can terminate after audit findings even when a clear remediation path exists.
- Target behavior: if findings exceed policy thresholds and execution is allowed, run `auditor -> solver -> reviewer -> verifier` automatically until green or budget exhausted.
- Success condition: deterministic gates pass and `codeauditor` reports zero blocking findings after the workflow changes are implemented.

## 1) Required Inputs (V90)

| Input | Status | Evidence Anchor |
|---|---|---|
| Plan | Present | `docs/implementation_plan_autonomous_solver_workflow.md` |
| Guide | Present | `docs/reference/critique_implementation.md` |
| Files | Present | `scripts/audit/plan_preflight.py`, `scripts/audit/route_parity_check.py`, `.ai_orchestrator/state.json` |
| Functions | Present | Orchestrator tool surface: `spawn_runs`, `await_runs`, `run_roundtable`, `consolidate_results`, `respond_to_gate` |
| Decisions | Present | User directive dated 2026-02-20: prioritize autonomous problem solving with explicit approval control |
| Diffs | Pending until implementation | To be captured with `git diff --name-only` and `git diff --stat` after code changes |

## 2) Scope and Ownership

| File | Role | Change Type |
|---|---|---|
| `.ai_orchestrator/state.json` | workflow state and policy fields | Extend schema-compatible state keys |
| `.ai_orchestrator/policy.json` [NEW] | execution mode + budgets + risk controls | New config artifact |
| `scripts/audit/orchestrator_policy.py` [NEW] | policy evaluation and mode resolution | New module |
| `scripts/audit/orchestrator_cycle.py` [NEW] | autonomous lifecycle executor | New module |
| `scripts/audit/orchestrator_checks.py` [NEW] | post-check gate evaluator | New module |
| `scripts/audit/orchestrator_events.py` [NEW] | structured event logging and summaries | New module |
| `README.md` | operator-facing usage and safety knobs | Documentation update |

Notes:
- Existing repo is already in a dirty state; this plan does not require reverting unrelated edits.
- File list above is implementation target scope for this workflow feature, not full-repo scope.

## 3) Execution Modes and Policy

### 3.1 Modes

| Mode | Behavior | Default Risk Level |
|---|---|---|
| `report_only` | audit and summarize only, no code changes | lowest |
| `auto_fix_safe` | apply low-risk remediations and re-verify | medium |
| `auto_solve_full` | iterative solve loop until pass or budget exhaustion | highest |

### 3.2 Core Policy Rules

1. If `critical > 0` or `high > 0` and mode is not `report_only`, spawn solver automatically.
2. Every solver iteration must end with verifier checks before completion.
3. Workflow is complete only when:
   - checks pass, or
   - max iterations/time budget reached with blocker report.
4. Risky operations remain blocked unless explicitly allowed by policy flags.

## 4) Integration Contracts (V105)

### Integration Contract: Mode Selection -> Workflow Authorization

**Why this boundary exists:** It prevents accidental autonomous edits when user intent is report-only.

**Caller (anchor):** `scripts/audit/orchestrator_cycle.py:[NEW]`  
**Callee (anchor):** `scripts/audit/orchestrator_policy.py:[NEW]`

**Call expression (verbatim):**
```python
policy = resolve_policy(user_mode, execution_lock, risk_flags, state)
```

**Callee signature (verbatim):**
```python
def resolve_policy(
    user_mode: str,
    execution_lock: bool,
    risk_flags: dict[str, bool],
    state: dict[str, object],
) -> dict[str, object]:
```

**Request/Source schema (verbatim, if applicable):**
```python
{
  "user_mode": "report_only|auto_fix_safe|auto_solve_full",
  "execution_lock": bool,
  "risk_flags": {"allow_dependency_upgrades": bool, "allow_destructive_ops": bool},
  "state": {"phase": str, "iteration": int}
}
```

**Argument mapping + type chain (REQUIRED):**

| Arg | Required? | Source expression | Type@Source | Type@Callee | Conversion | Notes |
|---|---|---|---|---|---|---|
| `user_mode` | yes | UI selection | `str` | `str` | none | enum-validated |
| `execution_lock` | yes | lock gate state | `bool` | `bool` | none | hard stop when true |
| `risk_flags` | yes | policy config | `dict[str, bool]` | `dict[str, bool]` | none | deny by default |
| `state` | yes | orchestrator snapshot | `dict[str, object]` | `dict[str, object]` | none | includes phase/iteration |

**Missing required inputs (if any):**
- none planned.

**Incompatible types (if any):**
- none planned.

**Return/Response contract (REQUIRED):**
- **Return value shape:** `dict[str, object]` including normalized mode, budgets, and hard stops.
- **Caller expects:** policy dict with actionable booleans (`can_execute`, `can_fix`, `can_escalate`).
- **Response model (if API):** not applicable.
- **Mismatch?** no.

**Failure modes / status codes (REQUIRED for API boundaries):**
| Failure | Trigger | Where raised | HTTP code (if any) | Caller behavior |
|---|---|---|---|---|
| invalid mode | unsupported mode string | `orchestrator_policy.py:[NEW]` | n/a | force `report_only` and log warning |
| locked execution | lock true | `orchestrator_policy.py:[NEW]` | n/a | no tool execution |

**Verdict:** PASS (planned)

### Integration Contract: Audit Result -> Solver Dispatch

**Why this boundary exists:** It enforces automatic remediation when blocking findings exist.

**Caller (anchor):** `scripts/audit/orchestrator_cycle.py:[NEW]`  
**Callee (anchor):** `scripts/audit/orchestrator_checks.py:[NEW]`

**Call expression (verbatim):**
```python
decision = decide_next_action(audit_summary, policy, iteration_state)
```

**Callee signature (verbatim):**
```python
def decide_next_action(
    audit_summary: dict[str, int | bool],
    policy: dict[str, object],
    iteration_state: dict[str, int | float],
) -> dict[str, object]:
```

**Request/Source schema (verbatim, if applicable):**
```python
{
  "audit_summary": {"critical": int, "high": int, "medium": int, "ci_pass": bool},
  "policy": {"mode": str, "can_fix": bool, "max_iterations": int},
  "iteration_state": {"iteration": int, "elapsed_seconds": float}
}
```

**Argument mapping + type chain (REQUIRED):**

| Arg | Required? | Source expression | Type@Source | Type@Callee | Conversion | Notes |
|---|---|---|---|---|---|---|
| `audit_summary` | yes | parsed `summary.json` | `dict[str, int | bool]` | `dict[str, int | bool]` | none | strict key check |
| `policy` | yes | resolved policy | `dict[str, object]` | `dict[str, object]` | none | contains mode/budgets |
| `iteration_state` | yes | runtime counters | `dict[str, int | float]` | `dict[str, int | float]` | none | limits infinite loops |

**Missing required inputs (if any):**
- none planned.

**Incompatible types (if any):**
- none planned.

**Return/Response contract (REQUIRED):**
- **Return value shape:** `{"action": "report|solve|stop", "reason": str}`.
- **Caller expects:** exact action enum plus reason.
- **Response model (if API):** not applicable.
- **Mismatch?** no.

**Failure modes / status codes (REQUIRED for API boundaries):**
| Failure | Trigger | Where raised | HTTP code (if any) | Caller behavior |
|---|---|---|---|---|
| malformed summary | missing severity keys | `orchestrator_checks.py:[NEW]` | n/a | stop with explicit error |
| budget exhausted | iteration/time exceeded | `orchestrator_checks.py:[NEW]` | n/a | stop and emit blocker report |

**Verdict:** PASS (planned)

### Integration Contract: Solver Output -> Reviewer/Verifier

**Why this boundary exists:** It prevents “patch generated” from being treated as “fix verified.”

**Caller (anchor):** `scripts/audit/orchestrator_cycle.py:[NEW]`  
**Callee (anchor):** `scripts/audit/orchestrator_events.py:[NEW]`

**Call expression (verbatim):**
```python
record_and_verify(run_result, checks_result, state)
```

**Callee signature (verbatim):**
```python
def record_and_verify(
    run_result: dict[str, object],
    checks_result: dict[str, object],
    state: dict[str, object],
) -> dict[str, object]:
```

**Request/Source schema (verbatim, if applicable):**
```python
{
  "run_result": {"status": str, "diff_files": list[str], "summary": str},
  "checks_result": {"ci_pass": bool, "critical": int, "high": int},
  "state": {"phase": str, "iteration": int}
}
```

**Argument mapping + type chain (REQUIRED):**

| Arg | Required? | Source expression | Type@Source | Type@Callee | Conversion | Notes |
|---|---|---|---|---|---|---|
| `run_result` | yes | solver run output | `dict[str, object]` | `dict[str, object]` | none | includes patch scope |
| `checks_result` | yes | verifier run output | `dict[str, object]` | `dict[str, object]` | none | gate input |
| `state` | yes | current lifecycle state | `dict[str, object]` | `dict[str, object]` | none | for phase transitions |

**Missing required inputs (if any):**
- none planned.

**Incompatible types (if any):**
- none planned.

**Return/Response contract (REQUIRED):**
- **Return value shape:** `{"phase": str, "done": bool, "blocker": str | None}`.
- **Caller expects:** authoritative gate transition object.
- **Response model (if API):** not applicable.
- **Mismatch?** no.

**Failure modes / status codes (REQUIRED for API boundaries):**
| Failure | Trigger | Where raised | HTTP code (if any) | Caller behavior |
|---|---|---|---|---|
| missing verification | solver ran but no checks | `orchestrator_events.py:[NEW]` | n/a | force FAIL and rerun checks |
| contradictory status | checks pass false but phase done true | `orchestrator_events.py:[NEW]` | n/a | mark semantic contradiction (HIGH) |

**Verdict:** PASS (planned)

## 5) ToT-Style Problem Solving Strategy

1. Cluster findings by root cause domain (typing, lint, tests, integration, policy).
2. Generate at least 2 remediation candidates per cluster (estimate: 2 to 3 candidates).
3. Score candidates on:
   - expected pass probability (estimate),
   - blast radius (changed files count),
   - reversibility (rollback cost estimate).
4. Use roundtable consensus to pick one candidate.
5. Implement, run checks, and keep only candidates that improve gate outcomes.

## 6) Phased Implementation

### Phase A: Policy Layer

- Implement mode parsing and lock enforcement in `orchestrator_policy.py` [NEW].
- Add policy config file `.ai_orchestrator/policy.json` [NEW] with mode, budgets, risk flags.
- Persist active policy and iteration counters in `.ai_orchestrator/state.json`.

Acceptance criteria:
- Invalid mode defaults to `report_only`.
- Lock state prevents execution even if mode is autonomous.

### Phase B: Autonomous Lifecycle Engine

- Implement `orchestrator_cycle.py` [NEW] with deterministic phase machine:
  `planning -> solving -> review -> post_checks -> complete`.
- Add mandatory transition rule: failing checks cannot transition directly to complete.
- Enforce iteration/time budget fail-closed behavior.

Acceptance criteria:
- Blocking findings trigger solve phase automatically outside `report_only`.
- Budget exhaustion produces blocker report and halts further edits.

### Phase C: Verification and Critique Hooks

- Implement `orchestrator_checks.py` [NEW] to normalize results and evaluate gate rules.
- Add contradiction detector for status/action mismatches (PASS+BLOCK, FAIL+PROCEED).
- Add post-fix delta validation hook (new claims must be re-validated).

Acceptance criteria:
- Every solver round ends with structured verifier output.
- Gate contradictions are hard failures.

### Phase D: Observability and Operator UX

- Implement `orchestrator_events.py` [NEW] event stream with compact phase summaries.
- Add operator documentation in `README.md` for mode selection and risk toggles.
- Add explicit completion contract text in docs.

Acceptance criteria:
- Operator can see exact reason for each transition.
- Final status always includes either pass evidence or blocker evidence.

## 7) Verification Plan (code_auditor + critique gates)

Run from repository root after implementation:

```bash
python scripts/audit/plan_preflight.py \
  --plan-file docs/implementation_plan_autonomous_solver_workflow.md \
  --check integration \
  --check routes

python scripts/audit/route_parity_check.py \
  --plan-file docs/implementation_plan_autonomous_solver_workflow.md \
  --project-root .

codeauditor audit \
  --project . \
  --sarif-out data/audit/photonic_audit.sarif \
  --enforce
```

Expected gate results:
- Preflight: PASS.
- Route parity: PASS (no unannotated missing route claims).
- Code auditor: CI pass true (critical/high/medium/low/info all zero) for this repo baseline.

## 8) Risk Register

| Risk ID | Severity | Description | Mitigation | Owner |
|---|---|---|---|---|
| ORC-1 | CRITICAL | autonomous mode executes risky changes without consent | lock gate + explicit risk flags default false | orchestrator owner |
| ORC-2 | HIGH | infinite remediation loop | max iteration and wall-time budgets | orchestrator owner |
| ORC-3 | HIGH | solver result treated as verified without checks | mandatory verifier before phase completion | orchestrator owner |
| ORC-4 | MEDIUM | stale findings after fixes | post-fix re-critique on delta list | reviewer owner |
| ORC-5 | MEDIUM | unclear operator state leads to wrong approvals | event log + transition reason text | UX owner |

## 9) Decision Gates (STOP/GO)

| Gate | Condition | Fail Action |
|---|---|---|
| G1 | policy resolved and lock semantics valid | STOP |
| G2 | integration contracts present for each new boundary | STOP |
| G3 | lifecycle transition rules prevent premature DONE | STOP |
| G4 | verifier runs after each solver iteration | STOP |
| G5 | deterministic checks and `codeauditor --enforce` pass | GO |

STOP/GO rule:
- Any FAIL in G1 to G4 is STOP.
- GO requires all gates PASS.

## 10) Post-Fix Re-Critique Protocol

After each remediation round:

1. Build a delta list of changed claims and touched files.
2. Re-run integration checks for all changed boundaries.
3. Re-run route parity if any path claim changed.
4. Re-run `codeauditor --enforce`.
5. Update decision gates only after all checks complete.

