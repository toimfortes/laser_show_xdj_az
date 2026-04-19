# Multi-Provider Destructive Review — Final Report

## Panel Summary
- R1 finding counts: A=12, B=13, C=14, D=20
- R2 scoring: each reviewer scored the other three (3 external votes per R1 finding)
- Minimum viable panel: 4/4 valid (no provider failed)
- Synthesizer: Reviewer A (fewest R1 findings)

## Confirmed Findings (4/4 unanimous — author + 3 external AGREE/EXTEND)

### [CRITICAL] Success criteria are not measurable
- Raised by: A3+B1+C1+D1
- Anchors: L71-82, L117-121, L146-154, L186-189
- Rationale: Both subprojects define completion with subjective language such as “materially smaller” and “primarily a command shell,” but provide no numeric thresholds, bounded responsibility mix, or complexity targets for sign-off.
- Remediation: Add concrete exit criteria for each host file and each split package.

### [CRITICAL] Import migration and compatibility strategy is missing
- Raised by: A4+B2+C3+D2+B10+D20
- Anchors: L53-75, L124-176, L205-208, L233-240
- Rationale: The plan moves symbols across modules without stating whether callers get re-exports, a one-shot cutover, a deprecation window, or explicit test-import updates. That leaves import breakage and stale mocks unmanaged.
- Remediation: Define one migration contract, list affected import sites, and state how tests transition.

### [HIGH] Subproject A is claimed as a prerequisite without a named dependency
- Raised by: A1+B4+C2+D4
- Anchors: L10-14, L84-85, L249-252
- Rationale: The plan says the later CLI extraction depends on cleaner `runtime_context` boundaries, but never identifies the specific API, type, or call path that creates that dependency.
- Remediation: Name the blocking interface explicitly, or drop the mandatory sequencing claim.

### [HIGH] `runtime_context.py` rationale is internally inconsistent
- Raised by: A2
- Anchors: L10, L30-38
- Rationale: The document calls `runtime_context.py` “already functionally cohesive” while also diagnosing multiple mixed responsibilities inside it. That contradiction weakens the stated reason for doing this split first.
- Remediation: Reconcile the diagnosis and state one consistent reason for Subproject A.

### [HIGH] `showplan` public API and entrypoints are undefined
- Raised by: A5+B5+C9+D7
- Anchors: L85-111, L160-175
- Rationale: Seven new modules are proposed, but the plan never says what is public, what stays internal, how `showplan/__init__.py` behaves, or which entrypoints `cli.py` should call.
- Remediation: Define the stable `showplan` facade and the permitted import surface.

### [CRITICAL] The “dependency inversion” claim is not achieved by the proposed split
- Raised by: A6+B3+C8+D3
- Anchors: L47-52, L120-123
- Rationale: Moving code from `ui/cli.py` into peer modules does not itself invert dependency direction; `cli.py` still orchestrates and calls concrete domain code. The architectural claim is stronger than the described change.
- Remediation: Either restate this as structural extraction only, or specify the actual inversion boundary.

### [HIGH] Verification strategy cannot prove behavior stability
- Raised by: A7+A8+B8+C6+C10+D8+D9
- Anchors: L113-115, L134-139, L151, L189, L202-213
- Rationale: Existing tests plus unspecified “representative” flows do not prove equivalence for outputs, artifacts, or cross-module behavior. No golden files, snapshots, named smoke commands, or explicit before/after baselines are required.
- Remediation: Require golden-output and end-to-end regression checks for each delivery slice.

### [HIGH] “Domain logic” is not defined at the CLI seam
- Raised by: A9+B6+D6
- Anchors: L16, L83, L95, L119-123, L176-183
- Rationale: The plan repeatedly says domain logic moves out of `ui/cli.py`, but never provides a rule for borderline cases such as validation, config loading, persistence, formatting, and startup checks.
- Remediation: Add a written inclusion/exclusion rule for CLI-layer versus domain-layer code.

### [MEDIUM] Non-goals conflict with the stated architectural problem
- Raised by: A10+B12+C11+D13
- Anchors: L23, L30-33, L95-99, L103-123
- Rationale: The plan says re-architecting is out of scope while simultaneously framing the problem as an architectural dependency issue. That leaves the allowed degree of boundary change unclear.
- Remediation: Clarify what architectural change is in scope and what remains explicitly deferred.

### [HIGH] Rollback and per-slice revert policy are absent
- Raised by: A11+B13+C14+D12
- Anchors: L141-152, L215-241
- Rationale: The delivery plan defines phases and slices, but not the atomic rollback unit, stop conditions, or recovery path if one extraction slice regresses behavior mid-stream.
- Remediation: Add a revert procedure and failure criteria for every slice.

### [HIGH] Singleton/global coupling rules are contradictory and underspecified
- Raised by: B7+C4+D10+D16
- Anchors: L70-75, L110, L130, L140-144
- Rationale: Helpers are told not to depend on shared globals, yet singleton accessors remain in the host module and are not enumerated. That makes purity a convention rather than an enforceable boundary.
- Remediation: Enumerate retained accessors and enforce no-import or dependency-injection rules for extracted helpers.

### [MEDIUM] Phase-2 delivery slices do not cleanly align with target modules
- Raised by: D18
- Anchors: L160-174, L223-229
- Rationale: The seven proposed `showplan` modules and the five delivery slices use different names and groupings, leaving it unclear which modules ship together and how progress maps to the target design.
- Remediation: Map each delivery slice directly to target modules, or state the intended grouped shipments.

## Majority Findings (3/4 agreement — one dissent)

### [HIGH] Module-level state, constants, and ownership are not fully inventoried
- Raised by: C5+D11
- Anchors: L87-111, L124-144
- Rationale: The plan focuses on function moves but not on who owns registries, constants, maps, caches, or lock-like state after the split. That leaves hidden coupling and relocation work undefined.
- Remediation: Add an ownership inventory for module-level data in both host files.
- Dissent: A said the `cli.py` constants concern is speculative without source evidence.

### [HIGH] Sequencing and parallelism are over-constrained without enough justification
- Raised by: A12+B11+C13+D5
- Anchors: L149-157, L175-176, L215-231, L225-229, L249-252
- Rationale: The plan fixes serial ordering for slices and subprojects while providing little evidence that the work cannot be reordered or partially parallelized, especially where files appear disjoint.
- Remediation: Mark independent slices as parallelizable unless a named dependency blocks them.
- Dissent: A argued some serial order may be deliberate risk-based sequencing.

### [MEDIUM] Proposed split granularity and naming may over-fragment the design
- Raised by: B9+D14+D15
- Anchors: L128-139, L160-174, L176
- Rationale: The plan gives no LOC or cohesion estimates for the target files, so it may trade large modules for several tiny siblings with weak boundaries and repetitive naming.
- Remediation: Add estimated size/cohesion targets and merge any projected tiny modules before execution.
- Dissent: A said granularity is already adjustable and prefix reuse is minor.

### [LOW] Keeping `PlaybackContext` in the host file may limit scanability gains
- Raised by: C12
- Anchors: L57-66
- Rationale: If the main class remains where most logic already lives, extracting only helpers may not materially change how easy `runtime_context.py` is to understand.
- Remediation: Reassess whether `PlaybackContext` should move, or narrow the claimed benefit of Subproject A.
- Dissent: A viewed the host-retention choice as an acceptable high-level constraint.

## Split Findings (2/4 — manual review needed)

### [MEDIUM] Three separate `runtime_context_*` helper files may be one split too far
- Raised by: C7
- Anchors: L56-66, L128-139
- Rationale: One reviewer pair saw unnecessary fragmentation risk in the proposed helper breakdown, while two others viewed that concern as speculative or adjustable in execution.
- Remediation: Manually review expected per-file size before committing to three helper modules.

## NEW Findings Surfaced in Round 2 Only

### [HIGH] Thread-safety ownership for retained singletons is unspecified
- Raised by: 3 reviewers (B-R2, C-R2, D-R2)
- Anchor: L110, L130, L141-144
- Rationale: The plan retains shared singleton accessors but never states who owns concurrency guarantees after extraction.

### [HIGH] Circular-import prevention is absent
- Raised by: 4 reviewers (A-R2, B-R2, C-R2, D-R2)
- Anchor: L128-139, L160-174
- Rationale: New sibling modules are proposed on both splits, but no guardrails are defined to prevent cross-import cycles.

### [HIGH] Exception and exit-code behavior across the CLI/domain seam is undefined
- Raised by: 3 reviewers (A-R2, B-R2, D-R2)
- Anchor: L176, L198-199, L202-213
- Rationale: The plan never specifies which exceptions cross the seam, where they are translated, or how process exit codes remain stable.

## Top 10 Action Items (ordered by severity + confidence)

1. Replace qualitative success criteria with numeric exit criteria for both subprojects.
2. Publish an explicit import-migration contract, including shims or atomic cutover rules, affected callers, and test updates.
3. Either remove the “dependency inversion” claim or define the dependency graph and abstraction boundary that makes it true.
4. Name the concrete `runtime_context` API that blocks Subproject B, or allow parallel execution where no dependency exists.
5. Define the stable `showplan` public surface, including `__init__` exports and the exact entrypoints `cli.py` may call.
6. Add a written rule for what stays in `ui/cli.py` versus what moves into `showplan`.
7. Require golden/snapshot artifacts and named end-to-end CLI smoke commands for every extraction slice.
8. Add per-slice rollback rules, revert boundaries, and stop conditions before implementation starts.
9. Inventory retained singletons, module-level state/constants, their owners, thread-safety expectations, and the exception-to-exit-code contract.
10. Add circular-import guardrails and realign slice names, module granularity, and file naming with the target architecture.

## Panel Diagnostics

- Reviewer A dissent rate on others' findings: 10/47
- Reviewer B dissent rate: 1/46
- Reviewer C dissent rate: 0/45
- Reviewer D dissent rate: 0/39
- Known-blind-spot notes (from reviewer self-checks): Reviewers A and D both noted that the panel could not validate real file-size deltas or whether the plan risks freezing in known hazards such as duplicated control state, LangGraph ceremonial use, and ILDA safety gaps.
- Scoring convention: AGREE + EXTEND + NEW all count as agreement; DISAGREE counts as dissent.

## Not Covered
This panel reviewed only the refactor plan text. It did not inspect the existing source, import graph, test suite, runtime behavior, or downstream consumers, so it could not verify whether the claimed dependencies are real, whether constants/state actually exist where inferred, or whether current integrations already constrain the safest migration path.