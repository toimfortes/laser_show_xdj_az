# Multi-Provider Destructive Review — Cycle 2 Report

## Panel Summary
- **Cycle:** 2
- **R1 counts:** A=6, B=7, C=9, D=16
- **Synthesizer:** Reviewer A (Gemini)
- **Status:** All 4 providers valid (unanimity/majority thresholds met)

## Cycle-1 Prior-Art Closure Verdicts

| # | Prior finding | Consensus verdict | Notes |
|---|---------------|-------------------|-------|
| 1 | Unmeasurable success criteria | PARTIAL | LOC targets added but counting methodology remains undefined (A4/B1/C2/D1). |
| 2 | Import migration absent | CLOSED | Hardened for Subproject A; gap remains in Subproject B (B2/D15). |
| 3 | Dependency inversion claim | CLOSED | Explicitly disclaimed in L261; narrowed to "structural extraction." |
| 4 | Prerequisite without named API | CLOSED | `PlaybackContext` and `showplan` facade named. |
| 5 | runtime_context rationale | CLOSED | Context-specific extraction logic accepted. |
| 6 | showplan public API | PARTIAL | Function names provided, but signatures and module owners missing (B3/C3/D11). |
| 7 | Verification stability | PARTIAL | "Canonical" anchors named but not bound to specific file paths (A5/B5/C1/D2). |
| 8 | "Domain logic" heuristic | CLOSED | Logic-boundary rules (Section 8) accepted. |
| 9 | Non-goals contradiction | CLOSED | Re-architecting vs. Extraction distinction clarified. |
| 10 | Per-slice rollback | CLOSED | Policy defined in Section 10. |
| 11 | Singleton enumeration | CLOSED | `PlaybackContext` singletons identified. |
| 12 | Slice↔module mapping | CLOSED | Section 9 provides clear sequencing. |
| 13 | Circular-import guardrails | PARTIAL | Paradox regarding leaf modules and shared types remains (A3/D9). |
| 14 | Thread-safety ownership | PARTIAL | Responsibility assigned but "lock-coupling" creates new risks (A2/D8). |
| 15 | Exception/exit-code semantics | PARTIAL | Contract present but lacks baseline inventory (A6/B7/C8/D6). |

## Confirmed Cycle-2 Findings (4/4 unanimous)

### [HIGH] Undefined LOC Counting Methodology
- **Raised by:** A4, B1, C2, D1
- **Anchors:** Lines 228, 316, 317
- **Rationale:** Numeric budgets (e.g., "1500 LOC or less") and the "70% landing" metric are unenforceable without a specific counting tool (e.g., `cloc`) and rules for comments/docstrings.
- **Remediation:** Specify a standard counting tool and exclusions (e.g., logical lines excluding blank/comment lines).

### [HIGH] Verification Anchors Unbound to Fixtures
- **Raised by:** A5, B5, C1, D2
- **Anchors:** Lines 303-306, 364-367
- **Rationale:** Terms like "canonical small-room show plan" are subjective; without specific YAML/JSON file paths and serialization formats, the golden baseline is uncheck-able.
- **Remediation:** Explicitly list the fixture file paths and define the serialization/normalization rules for golden comparison.

### [HIGH] Facade Signature and Ownership Gaps
- **Raised by:** B3, C3, D11
- **Anchors:** Lines 225, 269-276
- **Rationale:** The `showplan` facade lists function names but omits parameter/return types and fails to assign `resolve_show_sections` to an owning module.
- **Remediation:** Provide full type signatures for facade entrypoints and assign every public function to a specific submodule.

### [HIGH] Thread-Safety via "Lock-Coupling"
- **Raised by:** A2, D8
- **Anchors:** Lines 162-164, 217-224
- **Rationale:** Extracted helpers rely on callers to hold locks, creating "lock-coupling" where helpers are silently unsafe if reused elsewhere.
- **Remediation:** Encapsulate locking within helpers or use immutable snapshots to ensure standalone thread safety.

### [HIGH] Circular-Import Guardrail Paradox
- **Raised by:** A3, B6, C6, D9
- **Anchors:** Lines 257-259, 300-306
- **Rationale:** Forbidding leaf modules from importing the facade while allowing sibling imports forces code duplication or introduces cross-subproject cycles (e.g., `showplan` -> `platform`).
- **Remediation:** Create a `showplan/base.py` for shared types/constants that all siblings can safely import.

### [HIGH] Exit-Code and Exception Mapping Absence
- **Raised by:** A6, B7, C8, D6
- **Anchors:** Lines 265-272, 311-312
- **Rationale:** The plan promises stable failure semantics but fails to inventory current exit codes or define how domain exceptions map to CLI errors.
- **Remediation:** Inventory current non-zero exit codes and define a mapping from `ShowplanError` types to `ClickException` exit codes.

### [HIGH] Import-Smoke and Re-export Contradictions
- **Raised by:** D3, D5
- **Anchors:** Lines 168, 189-193, 306, 342
- **Rationale:** Subproject A contradicts itself on whether helpers are internal or re-exported, and "import-smoke" tests lack success criteria (e.g., symbol presence vs. runtime side-effects).
- **Remediation:** Resolve re-export visibility rules and define the assertion logic for import-smoke tests.

### [MEDIUM] Structural-Equivalence Undefined
- **Raised by:** C4, D16
- **Anchors:** Lines 343, 235
- **Rationale:** The requirement for "structural-equivalence" for `PlaybackContext.snapshot()` is named but never defined (e.g., deep dict equality vs. schema match).
- **Remediation:** Define the assertion as deep dictionary equality with a specific mask for non-deterministic fields like timestamps.

## Majority Findings (3/4)

### [CRITICAL] Logic Ownership Paradox
- **Raised by:** A1, B, C (Dissent: Claude)
- **Anchors:** Lines 121-122, 225
- **Rationale:** "Section-scope resolution" is assigned to Platform in Subproject A but listed as a Domain entrypoint in Subproject B.
- **Remediation:** Assign section resolution logic to exactly one package (Platform state vs. Domain planning).
- **Dissent:** Claude argued these may be complementary layers, but majority ruled it a boundary violation.

### [HIGH] Facade without Architectural Inversion
- **Raised by:** D4, A, C (Dissent: Codex)
- **Anchors:** Line 261, 264-277
- **Rationale:** The "facade" is a flat function registry mirroring submodules 1-to-1, failing to provide an actual abstraction boundary.
- **Remediation:** Define Protocol-based interfaces or data contracts in `showplan` to decouple CLI from module structure.
- **Dissent:** Codex argued structural narrowing is sufficient for this scope.

### [MEDIUM] Subjective "80-LOC" Escape Hatch
- **Raised by:** C5, A, D (Dissent: Codex)
- **Anchors:** Lines 229-230
- **Rationale:** The minimum-LOC rule is bypassed by "one cohesive responsibility," a subjective term that allows gaming.
- **Remediation:** Replace "cohesive responsibility" with a structural limit (e.g., "module exports ≤ 1 public class").

### [MEDIUM] Rollback Policy Thresholds
- **Raised by:** D7, A, C (Dissent: Codex)
- **Anchors:** Lines 401-405
- **Rationale:** Rollback triggers are boolean but lack quantitative thresholds (e.g., how many CI failures trigger a revert).
- **Remediation:** Add time-bound or quantitative triggers (e.g., ">1 failed CI run on smoke suite").

## Split Findings (2/4)

- **B4/D10 (80-LOC Brittleness):** Split on whether a hard LOC floor is a useful hardening tool or a brittle trap. Manual review required.
- **D17 (Cue-Recipe Re-arch):** Split on whether reorganizing cue-recipe logic constitutes "re-architecting" (prohibited) or "structural extraction."

## Top 8 Action Items
1. Resolve the ownership paradox for section resolution between `platform/` and `showplan/`.
2. Define a mandatory LOC counting methodology and baseline (e.g., `cloc` logical lines).
3. Bind all golden/snapshot anchors to specific fixture file paths and serialization schemas.
4. Enumerate full type signatures and owning modules for all `showplan` facade entrypoints.
5. Create a `showplan/base.py` or `types.py` to house shared domain types and prevent circular paths.
6. Encapsulate thread-safety locks within helpers or mandate the use of immutable snapshots.
7. Provide a baseline inventory of CLI exit codes and an exception-to-code mapping table.
8. Resolve the visibility contradiction for Subproject A helper re-exports.

## Cycle-1 → Cycle-2 Trajectory
7 of 15 items were CLOSED, but 8 remain PARTIAL, primarily due to "ghost hardening"—naming mechanisms (LOC budgets, canonical anchors, facades) without operational definitions. While structural mapping is improved, the plan's verification layer is still aspirational. One new CRITICAL ownership conflict (A1) surfaced regarding section resolution, and the "lock-coupling" thread-safety model (A2) remains a significant regression risk.

## Panel Diagnostics
- **Dissent Rates:** Codex (B) was the primary dissenter on abstraction requirements and rollback triggers; Claude (D) dissented on the logic ownership critical.
- **Known Gaps:** Build-system impacts and hardware-specific timing under lock-hold were not assessed.

## Not Covered
This review did not assess the actual content of the logic being moved, only the architectural boundaries and verification metadata. Hardware-in-the-loop dependencies and the performance impact of deep-dict structural-equivalence assertions on large shows were excluded from scope.
