# Critique Implementation Guide (v1.39)

## Core Philosophy
The forensic critique agent is not a reviewer; it is a **safety interlock**. Its job is to prove the plan is unsafe. It assumes the plan is flawed until proven otherwise by code evidence.

## Critique Vectors (Tiers)

### Tier 1: Structural & Inventory (The "Exists" Check)
- **V1 (File Existence):** Do the files listed in scope actually exist?
- **V4 (Inventory Gaps):** Are there files modified in the diffs that are missing from the Scope table?
- **V15 (Numeric Claims):** When the plan says "20 files" or "5 gates", is the count correct? Is the counting methodology disclosed? (See Rule R2)

### Tier 2: Content & Consistency (The "Matches" Check)
- **V16 (Signature Verification):** Do the function signatures in the plan match the code?
- **V27 (Type Assumption):** Does the plan assume a type (e.g. UUID) that is actually a String?
- **V105 (Boundary Composition):** Do *composed* integrations work end-to-end (request→callee, JWT→DB predicates, interface extension→implementers)? This is NOT “does each piece exist”; it is “do the pieces compose without missing fields, type breaks, or contract mismatch.”
- **V57 (Plan Self-Consistency):** Do different sections of the plan (Risk Register vs Timelines) agree on dates and owners?
- **V62 (Plan Lifecycle):** Is a "DONE" item actually done (date in past)? Is a "FAIL" item blocked? **Procedure (v1.25):** Read the verification command's implementation — if it contains placeholder comments (`TODO`, `goes here`, `future`), empty loops, or tautological branches (same output in both if/else), the gate is automatically **FAIL** regardless of its conclusion line. Self-assessed gates with unimplemented logic are invalid.

#### V105 Procedure (MANDATORY for any “wire/call/override/derive” plan step)
For each boundary the plan introduces or changes, the auditor MUST produce an **Integration Contract** block with:
1. Caller anchor (`file:line`) + verbatim planned call expression.
2. Callee anchor (`file:line`) + verbatim signature (including types/defaults).
3. A mapping table that proves every required callee arg has a source (request model fields, JWT-derived values, settings, DB reads).
4. A **type chain** for each mapped arg across the boundary, including any conversions (`UUID`→`str`, `str`→`UUID`, etc.). Any incompatible type assumption without an explicit conversion is **CRITICAL**.
5. Return/response model parity (caller expectation vs response_model vs actual return shape).

**Canonical template:** `scripts/audit/boundary_contract_template.md`.

Failure modes caught (systematic):
- request model exists AND callee exists BUT required args have no source (CRITICAL)
- “IDOR fix” introduces a new type mismatch (CRITICAL)
- response_model conflicts with proposed return type (CRITICAL)
- interface extension breaks implementers (V79/V105; HIGH/CRITICAL depending on call sites)

#### V106 (Route Reality): the “Ops Isn’t Exempt” Rule
Any plan claim of a URL path (including Phase 4 ops/webhook steps) MUST be proven by:
1. The route decorator (`@router.get/post/...`) path string
2. The router prefix (`APIRouter(prefix=...)`) if present
3. The mount prefix (`app.include_router(..., prefix=...)`) if present
4. The composed final path shown explicitly

Nonexistent “sounds-right” paths are **CRITICAL**.

Deterministic checker (recommended): `python scripts/audit/route_parity_check.py --plan-file <plan.md>`.

**Plan annotation rule (v1.39):** If a plan mentions a route that does not exist *yet*, it must be marked on the same line as `[NEW]`. Frontend-only routes must be marked `[FRONTEND]`. External third-party paths must be marked `[EXTERNAL]`. Route strings referenced for cleanup/analysis but not mounted in the live app must be marked `[DEAD]`. Missing routes without annotation are **CRITICAL** (prevents ambiguity between “existing” vs “planned”).

### Tier 3: Phase-Specific Requirements
#### **Required Inputs (Section 2)**
- **V90 (Input Completeness):** Verify all 6 mandatory inputs (Plan, Guide, Files, Functions, Decisions, Diffs) are present and evidenced. **Evidence anchor standard (v1.25):** Each "Confirmed Decision" must cite at least one external anchor: ADR number, commit hash, file path + line, or timestamped approval. Conversational references ("in-thread direction") are **insufficient** — they are not reproducibly verifiable by a third party.
- **V91 (Diff Accuracy):** Verify `git diff --stat` output matches the Target Files list. **Post-remediation mandate (v1.25):** After ANY round of plan edits that touch source files, re-run `git diff --name-only` and compare against the plan's §2.2 evidence. Files newly in diff but absent from the scope table are a HIGH finding. This check must be the LAST step before declaring a remediation round complete.

#### **Quick Reference (Section 1.1–1.9)**
- **V92 (Hostility Mode):** Verify `_verify_user_access` and sync-query removals are evidenced.
- **V93 (Evidence Quality):** Verify every section (1.1-1.9) has a command, output, analysis, and conclusion.

#### **Phase 1: Internal Codebase (Section 3)**
- **V94 (Pattern Inventory):** Verify at least 10 pattern IDs are queried and mapped.
- **V95 (Registry Freshness):** Verify `data/code_catalog.json` timestamp is within 24h. **Verification integrity (v1.25):** Read the freshness-check command itself — if both branches of a conditional produce the same output (e.g., `FRESHNESS_PASS` in both if and else), the check is a tautology and must be marked FAIL. The auditor must run their own independent freshness check, not trust the plan's embedded script.

#### **Phase 2: External Research (Section 4)**
- **V96 (Source Diversity):** Verify at least 5 distinct domains (Async, Security, Caching, etc.) have sources.
- **V97 (Query Match):** Verify search queries match the remediation scope. **Query-to-scope mapping mandate (v1.26):** The plan must contain a table mapping each web research query to: (1) the scope file(s) it covers, (2) the plan section(s) it informs, (3) a justification for why this query is relevant. Orphaned queries (mapping to zero plan sections) or uncovered scope files (not addressed by any query) are MEDIUM findings.

#### **Phase 3: Schema Verification (Section 5)**
- **V98 (Field Parity):** Verify all fields in 5.4 match `nl -ba` output for type and nullability.
- **V99 (Relationship Loading):** Verify loading strategy (selectinload) is specified for all relationships. **Source-first enumeration (v1.25):** Do NOT verify by checking only what the plan lists. Instead: (1) Run `grep -rn "relationship(" backend/database/ --include="*.py"` to independently enumerate ALL relationships from code. (2) For each relationship with `cascade="all, delete-orphan"`, verify the plan specifies a loading strategy. (3) Report uncovered cascade relationships as HIGH. Coverage of non-cascade relationships may be scoped with explicit justification, but cascade relationships MUST have 100% coverage. **Passive-delete exception (v1.29):** Before flagging a cascade relationship as missing `selectinload`, extract safety parameters (`cascade`, `passive_deletes`, `viewonly`, `ondelete`, `lazy`, `backref`). If `passive_deletes=True` is present on the write path, SQLAlchemy can delegate deletes to the database and avoid ORM child loading; in this case, `selectinload` is not mandatory. The plan MUST cite the exact line showing `passive_deletes=True` to claim this exception.

### Tier 4: Forensic & Behavioral (The "Works" Check) — CRITICAL ADDITIONS v1.23
... [existing V78-V82] ...

### Tier 5: Output & Governance
#### **Output Templates (Section 8)**
- **V100 (Template Alignment):** Verify report follows the `EXTENDED_SECTIONED_AUDIT` mode.
- **V101 (Quick Summary):** Verify Quick Audit Summary is present and consistent with STOP/GO.

#### **Red Flags (Section 15)**
- **V102 (Threshold Enforcement):** Verify BLOCK actions are triggered for any IDOR, hardcoded secret, or async-cascade risk. **Semantic consistency check (v1.25):** For every row in a Status/Action table, verify the pair is logically coherent: PASS+BLOCK is contradictory (if the check passed, why block?), FAIL+PROCEED is contradictory (if the check failed, why proceed?). Valid pairs: PASS+PROCEED, FAIL+BLOCK, WAIVER+PROCEED (with justification). Any contradictory pair is a HIGH finding.
- **V103 (Evidence Hooks):** Verify red flags are linked to concrete `rg` or `grep` evidence. **"Concrete" defined (v1.25):** (1) Command output must be COMPLETE — if `rg` finds N matches, all N must appear in the evidence block, not a subset. Truncated output is a MEDIUM finding. (2) Line citations must be DIRECT — referencing the actual predicate/statement, not a wrapper function 4-6 lines away. Indirect citations are a LOW finding. (3) Negative claims ("not in scope") must have disproving evidence (`rg` returning zero matches), not bare assertions. **Evidence-ledger parity mandate (v1.32):** If the plan contains receipt tables and the audit uses `evidence.jsonl` (or tagged equivalent), each receipt row must reconcile exactly on command, interpreter path, exit code, and verdict. Plan/evidence contradictions are CRITICAL.

#### **Domain-Specific Patterns (Section 12)**
- **V104 (Standard Alignment):** Verify patterns match `docs/reference/critique_patterns/domain_patterns.md`. **File-read mandate (v1.25):** The auditor MUST read `domain_patterns.md` and compare each rule against the plan's Section 12 table row-by-row. Claiming alignment without reading the reference file is a HIGH finding. Evidence must show both "good examples found" AND "bad examples absent" (negative grep).

### Tier 6: Execution Trace & Risk ... [existing Tier 4/5 vectors renamed/re-indexed] ...
These vectors catch the subtle, high-impact failures that static analysis misses.

#### **V78 (Instantiation Trace): The "Construction Rule"**
**Goal:** Catch "Container Hardcoding" where a plan claims to swap a component but the DI container explicitly instantiates the old one.
**Procedure:**
1. Locate the **DI Container** or Factory (`backend/config/container.py`).
2. Verify: Is the component injected via a dynamic registry/string, or explicitly instantiated (`OldClass()`)?
3. If explicitly instantiated, the plan **MUST** include a container code change. If the plan treats it as a config-only swap, mark as **CRITICAL**.

#### **V79 (Call-Site Parity): The "NotImplemented Manhunt"**
**Goal:** Catch runtime crashes where a replacement component fails to implement methods used by production code.
**Procedure:**
1. Grep the replacement file for `raise NotImplementedError` or `pass`.
2. For every unimplemented method found, grep the **entire codebase** for callers (`.method_name(`).
3. If a production caller exists for an unimplemented method, mark as **CRITICAL** (Guaranteed Crash).

#### **V80 (Inverse Relationship Graph): The "Hidden Backref Rule"**
**Goal:** Catch async crashes caused by cascade deletes on relationships defined via `backref` in *other* files.
**Procedure:**
1. Do NOT rely on the class body alone.
2. Run: `grep -rn "relationship.*ModelName\|backref.*model_name" backend/database/`.
3. Discover relationships defined on *other* models pointing *to* your target.
4. If *any* incoming relationship has `cascade="all, delete-orphan"`, verify the delete path uses `selectinload()`.

#### **V81 (Legacy Ghost Hunt): The "Incomplete Migration Rule"**
**Goal:** Catch partial security migrations where old patterns (e.g. `RoleChecker`) remain active alongside new ones (`require_admin`).
**Procedure:**
1. Identify the **Legacy Pattern** being replaced.
2. Grep the codebase for occurrences of the **Legacy Pattern**.
3. If the legacy pattern remains in active routes/modules, mark as **HIGH** (Inconsistent Enforcement).

#### **V82 (Quantitative Scope): The "Reality Check"**
**Goal:** Catch scope explosions where the plan underestimates the work by orders of magnitude, OR inflates counts with flawed methodology.
**Procedure:**
1. If the plan estimates a count (e.g., "~25 log sites"), run a regex count (`grep -c`) to verify.
2. If Actual Count differs from Plan Estimate by >1.5x in **either direction**, mark as **HIGH** (Scope/Budget Mismatch).
3. Explicitly document any methodology differences.
4. **Verify the plan's counting methodology** — `grep -r` includes binary `__pycache__` files and `.pyc` artifacts. Always use `grep -rl --include='*.py'` for file counts and `grep -r --include='*.py'` for line counts. Flag bare numbers without methodology disclosure (see Rule R2).
5. **Count reconciliation (v1.29):** For HIGH-impact numeric claims, run at least two structurally different counting methods and reconcile deltas (see Rule R17). Do not accept a single-method count when an alternative method disagrees materially.

### Tier 4: Execution Trace (Phase 4)
- **V83 (Identifier Trace):** Verify SET/READ/CONSUME locations for critical identifiers (user_id, document_id) are anchored to live source lines. **Lifecycle table mandate (v1.26):** The plan must contain an explicit table mapping each security-critical identifier through its lifecycle: SET (parameter binding), VALIDATE (type coercion/parse), READ (query predicate), CONSUME (response/logging). Each row must cite file:line. Missing lifecycle phases are a MEDIUM finding.
- **V84 (Exception Path Trace):** Verify exception handling and HTTP status codes match the actual code implementation. **Status code evidence mandate (v1.26, updated v1.28):** The plan must map every `raise HTTPException(...)` in scope files to a table showing: line number, status code, trigger condition, and handler context. Verification: `rg -n "raise HTTPException" <file>` — all matches must appear in the table. Missing exceptions are a HIGH finding. **Multi-line warning (v1.28):** Do NOT use `rg "HTTPException.*status_code="` — this single-line regex misses the common multi-line construction `raise HTTPException(\n    status_code=...)`. The correct pattern is `rg "raise HTTPException"` which catches both single-line and multi-line forms. See Rule R15 for the general principle.
- **V85 (State Transition Trace):** Verify document lifecycle states (PENDING/PROCESSING/COMPLETED) match the code setting them. **State-transition table mandate (v1.27):** The plan must contain: (1) a transition table mapping every FROM→TO state change to file:line and trigger condition, (2) a read-points table mapping every conditional branch on state to file:line and purpose, (3) identification of any enum values defined but never written to (dead states). Verification: `rg -n "StatusEnum\." <file>` — all matches must appear in either the transition or read-points table. Missing transitions are a HIGH finding; dead enum values are a LOW finding.

### Tier 5: Risk Assessment (Phase 5)
- **V87 (Risk Register Completeness):** Verify all FAIL gates and high-impact changes (>50 blast radius) are tracked in the Risk Register.
- **V88 (Mitigation Adequacy):** Verify all HIGH/CRITICAL risks have concrete mitigations, owners, and target dates.
- **V89 (Cross-Section Concordance):** Verify Risk Register, Remediation Timelines, and Decision Gates agree on status and dates (Rule 29). **Bidirectional proof mandate (v1.25):** A concordance cell claiming "YES" is an unverified assertion unless the auditor cites the EXACT text from BOTH referenced sections. Procedure: for each YES cell, (1) read the source section (e.g., §7 Risk Register), (2) read the target section (e.g., §10 Decision Gates), (3) confirm both say the same thing, (4) cite both line numbers. Any YES without dual citation is a MEDIUM finding. **Phantom/orphan detection (v1.28):** Beyond confirming text agreement, the auditor MUST verify the claimed content physically exists at the target. Failure modes: (a) **Phantom reference** — concordance claims a checkbox `[ ]` or `[x]` exists in §14 but the target section has no such checkbox (the item was never listed). (b) **Orphan mapping** — concordance maps an item to "Phase 1 (§9.1)" but §9.1 contains no entry for that item (the mapping points to a section that doesn't mention it). (c) **Semantic mismatch** — concordance maps a LOW risk to a Critical-only remediation phase. Procedure: for every non-N/A cell, `grep` the target section for the specific item identifier (R3, R11, etc.) — if zero matches, the cell is a phantom/orphan and must be changed to "N/A" with justification. Phantom/orphan references are a MEDIUM finding. **Post-edit line-number refresh (v1.28):** V89 dual-citation tables contain 20+ line-number citations that ALL drift simultaneously after any plan edit that inserts or deletes lines. After ANY plan edit, the V89 line-number refresh must be the FIRST remediation step (before fixing other findings), not the last. Procedure: `rg -n` each cited token (e.g., `RESOLVED (HIGH)`, `#14 RESOLVED`, `5.x PASS`, `[x] R3`) and update every line number in the dual-citation table. Stale V89 line numbers after a plan edit are a HIGH finding.

## Remediation Protocol (v1.25)

**Problem this solves:** Critique finds issues; remediation fixes them. But fixing one cell in a row while leaving adjacent cells stale introduces *new* contradictions. This happened when R13's status was changed to RESOLVED but its description still said "840+ dependents" — a number derived from a flawed `grep -r` that counted binary cache hits.

### Rule R1: Row-Level Re-verification (The "Whole Row" Rule)
When remediating ANY finding that touches a row in a table (Risk Register, Schema Table, Concordance Table, STOP/GO gate), you MUST re-verify **every claim in that row**, not just the cell you are fixing.

**Procedure:**
1. Identify all cells in the modified row.
2. For each cell containing a factual claim (count, status, line number, type), re-run the verification command that produced it.
3. If no verification command exists for a cell, create one.
4. Update ALL stale cells, not just the target finding.

**Example failure:** Changing `R13 | OPEN` → `R13 | RESOLVED` without re-checking the description "840+ dependents" left a false number in the plan.

### Rule R2: Numeric Methodology Disclosure (The "Show Your Work" Rule)
Every numeric claim in the plan MUST include its derivation methodology in parentheses or a footnote. Bare numbers without methodology are a MEDIUM finding.

**Required format:** `<number> (<methodology>)`

**Examples:**
- `16 importing files (grep -rl "from.*shared_context_loader import" backend/ | grep -v __pycache__ | wc -l)`
- `0 sync queries (rg "db\.query\(" backend/api/documents.py | wc -l)`
- `2707 lines (wc -l backend/api/client_documents.py)`

**Why:** "840+" was derived from `grep -r "shared_context_loader" backend/ | wc -l` which included binary `__pycache__` files. With methodology visible, any reviewer can spot the flaw instantly.

### Rule R3: Section-Scoped Re-anchor (The "Blast Radius of Fixes" Rule)
When a remediation changes the **conclusion** of any section (e.g., FAIL→PASS, STOP→GO, OPEN→RESOLVED), ALL downstream sections that reference that conclusion must be re-verified.

**Procedure:**
1. Grep the plan for all references to the changed section/item.
2. For each reference found, verify the downstream text is still accurate.
3. Pay special attention to: verification command output blocks (which capture point-in-time state), concordance tables, STOP/GO gate rows, and End-of-Plan checklists.

### Rule R4: Fresh-Read Mandate (The "No Stale Cache" Rule)
Before filing a finding, the critique agent MUST re-read the relevant plan section **and** source file at the exact moment of writing the finding. Findings based on earlier reads or cached data are invalid.

**Why:** Gemini reported "Section 10.3 says STOP" as C-1 when it had already been changed to GO. The finding was based on a stale read.

### Rule R5: Amendment Diff Audit
After any batch of remediation edits, before declaring the plan fixed:
1. Run `diff` between the pre-remediation and post-remediation plan.
2. For every changed line, verify: (a) the new content is factually correct, (b) no adjacent unchanged content is now contradicted by the change.
3. This is the remediation equivalent of a code review — you review your own fixes.

### Rule R6: Evidence Refresh After Remediation (The "Snapshot Decay" Rule) — v1.25
**Problem this solves:** Captured command outputs (git diff --stat, stat timestamps, grep counts) are point-in-time snapshots. After remediation edits that change the working tree, these snapshots go stale — but nobody re-runs them because §2 was "already verified."

**Procedure:**
1. After ANY remediation round that edits **any file** (source files, reference docs, prompts, templates, the plan itself), re-run `git diff --name-only` and compare against the plan's §2.2 captured diff evidence.
2. If new files appear in diff that are absent from the scope table, either add them to scope or document them as out-of-scope artifacts with classification (e.g., "plan-support artifact — DIRTY").
3. Re-run `stat` on any file whose timestamp is cited in the plan and verify the claim still holds.
4. This check MUST be the LAST step before declaring a remediation round complete — after all other fixes are applied.
5. **Post-commit refresh (v1.26):** After committing changes, ALL scope files become CLEAN and all diff stats become `0+/0-`. Re-run §2.2 evidence with the new commit hash and updated diff state. A committed plan with stale pre-commit diff evidence is a HIGH finding.
6. **Non-source file awareness (v1.27):** Remediation commonly edits reference documents (critique guides, prompt templates, pattern catalogs) that are not implementation targets but ARE tracked by git. These files MUST appear in §2.2's scope classification table with a "plan-support artifact" label. Failing to register them is a HIGH finding — it indicates the remediator is modifying the audit infrastructure without tracking the modifications.

**Why:** After M-7 remediation (12 `str(e)` fixes), three new files appeared in `git diff` (critique_result.md, critique_implementation.md, gemini prompt). The plan's §2.2 still showed only 2 dirty files. No rule triggered a refresh. After committing (29ca8e7a), §2 still showed pre-commit diff stats — nobody re-ran the evidence post-commit.

### Rule R7: Source-First Completeness Inversion (The "Enumerate From Code" Rule) — v1.25
**Problem this solves:** When a plan claims completeness ("all relationships documented", "all files covered", "all queries scoped"), the auditor verifies by checking items the plan lists — but never checks what the plan OMITS. A plan listing 2 of 181 relationships can claim "all covered" and pass review.

**Procedure:**
1. For any V-gate claiming completeness (V91 "all diffs", V99 "all relationships", V82 "all files"), the auditor MUST independently enumerate from source code, NOT from the plan.
2. Run the enumeration command (e.g., `grep -rn "relationship(" backend/database/`).
3. For each item found in code, check if it appears in the plan's table.
4. Report uncovered items. If coverage < 100% for mandatory items (cascade relationships, security-scoped queries), mark as HIGH.
5. The plan MAY scope coverage to a subset, but it must EXPLICITLY state the subset and justify exclusions. Silent omission is a finding.
6. **Cascade inventory format (v1.26):** When scoping V99 cascade coverage, the plan MUST present a per-file inventory table showing: file name, total cascades in that file, how many are in-scope, how many are out-of-scope, and notes. Summary counts without per-file breakdown are insufficient. The per-file counts MUST sum to the total. If `sum(file counts) != claimed total`, mark as HIGH.

**Why:** V99 checked 2 relationships the plan listed and found both correct. But 179 relationships (including 25+ cascades) were silently excluded. The plan said "PASS" for V99 at 1.1% coverage. A later fix claimed "47 out-of-scope" with a per-file list that only summed to 40 — 3 files (prenup.py, version_tracking_models.py, user_document_models.py) and 4 cascades were silently dropped.

### Rule R8: Anti-Self-Reference Gate (The "Placeholder Detector" Rule) — v1.25
**Problem this solves:** Verification gates that contain placeholder logic (`# TODO`, `# goes here`, `# future`) or tautological branches (same output in if/else) produce PASS conclusions from no-op checks. The auditor reads the conclusion, not the implementation.

**Procedure:**
1. For every gate that contains an embedded script or verification command, READ THE COMMAND IMPLEMENTATION, not just the output.
2. If the command contains: placeholder comments (`TODO`, `goes here`, `future logic`), empty loop bodies, or tautological branches (identical output in both if/else paths) — the gate is automatically **FAIL** regardless of its conclusion line.
3. For evidence anchors: "in-thread direction", "as discussed", "per agreement" without an external reference (ADR, commit, file:line, timestamp) are **bare assertions**, not evidence. Mark as MEDIUM.

**Why:** V62's lifecycle gate printed `PASS` from a script whose date-validation loop was `# (Future date validation logic goes here)`. V90's decisions cited "in-thread direction" — unreproducible by any third party.

### Rule R9: Semantic Column Consistency (The "PASS+BLOCK Detector" Rule) — v1.25
**Problem this solves:** Tables with Status and Action columns can contain logically contradictory pairs that no individual-cell check catches. PASS+BLOCK means "the check passed but we're blocking anyway" — this is either a mislabeled column or a logic error.

**Procedure:**
1. For every table with Status/Action (or equivalent verdict/response) columns, verify each row's pair is logically coherent.
2. Valid pairs: PASS+PROCEED, FAIL+BLOCK, WAIVER+PROCEED (with documented justification).
3. Contradictory pairs: PASS+BLOCK, FAIL+PROCEED. These are HIGH findings.
4. Also verify: if Status=PASS, the evidence must SUPPORT the pass (not just assert it). If Action=BLOCK, there must be a downstream propagation to STOP/GO gates.

**Why:** Every Red Flags row had Status=PASS + Action=BLOCK. This is semantically broken — if all checks passed, no blocks should fire. The contradiction was invisible because review checked columns independently, not as pairs.

### Rule R10: Bidirectional Concordance Proof (The "Show Both Sides" Rule) — v1.25
**Problem this solves:** Concordance tables claim "YES" (sections agree) but only cite one side. A YES cell verified against only §7 but not §10 is an unverified assertion about §10.

**Procedure:**
1. For every YES cell in a concordance table, the auditor must read BOTH referenced sections and cite the exact text/line from each.
2. For every N/A cell, verify the N/A classification matches the referenced section's actual scope (e.g., if §10 doesn't mention LOW risks, confirm §10's trigger threshold excludes LOW).
3. For alignment claims against reference files (V104 domain_patterns.md), the auditor MUST read the reference file — not just check if it exists. Compare each rule in the reference against the plan's table row-by-row.
4. Selective evidence (only showing good examples) is insufficient. Evidence must include BOTH "good examples found" AND "bad examples absent" (negative grep with zero matches).

**Why:** V89 concordance had 15 YES cells verified against §7 only — no one read §10 to confirm the other side matched. V104 cited `domain_patterns.md` but never read it.

### Rule R11: Enumeration-First Scoping (The "Scan Before You Write" Rule) — v1.25
**Problem this solves:** Plan authors build scope inventories from reference documents (audit findings, issue trackers, previous plans) instead of from the codebase. This inherits the source document's omissions. The plan then claims completeness over a subset, and critique agents verify the subset's accuracy (100% line-number accuracy!) while missing that the subset is only 50% of reality.

**Procedure:**
1. When a plan's scope involves "find and fix all instances of pattern X," the author MUST run the Done Gate / verification grep **BEFORE** writing the scope section — not after.
2. The scan results become the ground-truth inventory. Every match must appear in scope or be explicitly excluded with justification.
3. The scan command and total count MUST appear at the top of the scope section (per R2).
4. If the plan is derived from a reference document (audit finding, issue tracker), the author must STILL run the independent scan and reconcile differences.

**Why:** The error-leakage plan was built from the super-audit's M-8 finding rather than from `rg "detail=.*str\(e\)" backend/api/`. This inherited the audit's 50% coverage gap. The plan's own Done Gate commands would have caught this if run at authoring time instead of post-implementation.

### Rule R12: Post-Remediation Full-Plan Sweep (The "No Tunnel Vision" Rule) — v1.26
**Problem this solves:** After a critique round produces N findings, the remediator fixes exactly those N items and declares done. But the fixes may: (a) introduce new stale evidence elsewhere, (b) shift line numbers that are cited in unfixed sections, (c) leave pre-existing gaps untouched that were simply not caught in this round. The next audit round finds these as "new" findings that are actually stale leftovers.

**Procedure:**
1. After fixing all findings from a critique round, do NOT immediately declare the round complete.
2. Perform a FULL-PLAN sweep: scan every section header (§1–§16) and verify that no evidence block, line number citation, or numeric claim has been invalidated by the fixes you just applied.
3. Specifically check:
   - All line number citations (`:NNN`) in sections you did NOT edit — your edits to other sections may have shifted line numbers.
   - All `git diff --stat` / `git status` evidence blocks — your edits changed the working tree.
   - All numeric counts that reference source files — your edits may have changed the count.
   - All concordance/cross-reference tables — your edits may have changed the referenced content.
4. If this sweep finds issues, fix them BEFORE declaring the round complete.

**Why:** Codex Round 5 found 13 findings (7 HIGH) after Round 4's 9 fixes were applied. Root cause: the remediator fixed only the 9 specific findings without sweeping the plan for collateral damage. Six of the 13 findings were pre-existing gaps that were never caught because fix-scope tunnel vision skipped unfixed sections. The remaining 7 were stale evidence caused by the fixes themselves (shifted line numbers, changed diff stats, invalidated counts).

### Rule R13: All-Scope-Files Gate (The "No Primary-Only" Rule) — v1.27
**Problem this solves:** Per-file vectors (V83, V84, V85, V99, V103, V104) are run against the primary target file only. Secondary verification targets listed in the plan header are silently skipped. The resulting evidence covers 1 of N scope files while claiming completeness.

**Procedure:**
1. Every vector whose evidence depends on scanning a file (grep, rg, line citation) MUST be run against ALL files listed in the plan's scope header — primary AND secondary targets.
2. After building a vector's evidence table, cross-check: for each file in the plan header's "Target" / "Secondary Verification Targets" list, does at least one row in the evidence table reference that file?
3. If a scope file has zero rows for a vector, either: (a) add evidence rows for that file, or (b) document an explicit exclusion with justification (e.g., "documents.py has no cascade relationships — N/A for V99").
4. Silent omission of a scope file is a HIGH finding.

**Mechanical check:** `for file in <plan_header_targets>; do grep -q "$file" <vector_section> || echo "MISSING: $file in <vector>"; done`

**Authoring-time complement (v1.28):** R13 catches missing scope files at audit time. But the gap between "author adds a scope file" and "next audit catches the omission" can span multiple edit rounds. To prevent this:
1. When adding a new file to the plan's scope header (primary or secondary), the author MUST immediately grep the plan for all per-file vectors: `rg "V83|V84|V85|V97|V99|V103|V104|§15" <plan_file>`.
2. For each vector section found, add evidence rows for the new scope file or document an explicit N/A exclusion.
3. This sweep is mandatory BEFORE the next critique round — otherwise 5+ agents will independently flag the same omission as separate findings.
4. **Vector Matrix scaling (v1.29):** Maintain a "Vector Matrix" table in the plan that lists every per-file vector section and the files it must cover. When scope expands, update the matrix first, then execute each vector-file pair. A fixed list in prose is insufficient once vectors evolve.

**Why:** Codex Round 8 found 3 findings (7, 12, 13) caused by primary-target tunnel vision. V84 covered 12 HTTPExceptions from `client_documents.py` but missed 4 from `documents.py` (a secondary target listed in the plan header). V83 built exhaustive `user_id` lifecycle but left `document_id` structurally asymmetric. V85 was entirely missing because `DocumentProcessingStatus` lives in `documents.py`, which the remediator mentally filed as "secondary" and skipped. Codex Round 9 found the same pattern across 5 of 6 agents — R13 caught it at audit time, but the authoring-time complement would have prevented the 28-finding remediation cascade.

### Rule R98: Critique Your Corrections (The “Fixes Are New Claims” Rule) — v1.38
Any remediation edit that changes plan instructions (especially “IDOR fix”, “derive from JWT”, “override request field”, “call X from Y”) introduces NEW composed claims. These must be re-audited with V105 and V106 **before** declaring the remediation round complete.

**Procedure:**
1. List the exact new/changed claims introduced by the fix (delta list).
2. For each delta that crosses a boundary, add/update an Integration Contract block (V105).
3. Re-run route parity verification for any path changes (V106).
4. If any delta is unverified, verdict MUST remain STOP.

### Rule R14: Evidence Self-Containment (The "No Indirection" Rule) — v1.27
**Problem this solves:** A section makes an evidentiary claim ("47 out-of-scope cascades") but instead of embedding proof, it says "see §5.4." The auditor must now cross-reference two sections to verify one claim. This has three failure modes: (a) the referenced section may itself be stale, (b) the auditor may not follow the reference, (c) the claim may be a lossy summary of the referenced section.

**Procedure:**
1. Every section that makes a numeric, categorical, or factual claim MUST embed the proof inline — either as a command+output block or as a directly-verifiable table.
2. Cross-section references ("see §5.4", "per §15 output") are supplementary context, NOT evidence. They are permitted as navigation aids but MUST NOT be the sole evidence for a claim.
3. Per-row evidence in cross-reference tables (V89 concordance, V104 domain patterns) must be individual — each row must have its own positive evidence AND its own negative evidence. Bulk proof covering all rows at once (e.g., a single `rg` command whose output is claimed to cover 9 different patterns) is a MEDIUM finding.
4. Evidence freshness: every embedded command output block should include a timestamp or round identifier. Before declaring a remediation round complete, verify all evidence blocks are from the current round. Stale evidence from a previous round without explicit re-verification is a MEDIUM finding.

**Why:** Codex Round 8 found 3 findings (8, 11, 15) caused by evidence shortcuts. §15 claimed "47 out-of-scope cascades" citing §5.4 instead of embedding proof. V104 had bulk negative proof covering 9 patterns with 2 `rg` commands instead of per-row individual verification. V95's freshness check was from a previous round with no re-verification timestamp.

### Rule R15: Regex Methodology Validation (The "Test Your Pattern" Rule) — v1.28
**Problem this solves:** A verification command uses a regex pattern that looks correct but silently misses matches due to formatting assumptions. The most common failure: Python code constructs that span multiple lines (function calls with keyword arguments, raise statements, decorator chains) are missed by single-line regex patterns. The resulting count is reported with full R2 methodology disclosure, passes V82's 1.5x threshold (because nobody has the true count to compare against), and is accepted as fact.

**Procedure:**
1. When a vector's verification command uses a regex pattern, the author/auditor MUST run the regex against the actual codebase and manually inspect at least 5 matches to confirm the regex catches what it claims to catch.
2. For Python code patterns that commonly span multiple lines (`raise`, `return`, function calls with `keyword=`), prefer anchoring on the statement keyword (`raise HTTPException`, `return Response`) rather than trying to match the full construct on one line.
3. After running the regex, sanity-check the count: for a 2700-line file with extensive error handling, 16 exceptions is suspiciously low — 47 is more plausible. If the count seems low for the file size and complexity, try a broader pattern and compare.
4. **Cross-validate with a second pattern:** If feasible, run a structurally different regex that should produce the same count (e.g., `rg -c "status_code=" <file>` as a cross-check against `rg -c "raise HTTPException" <file>`). If counts diverge significantly, investigate.
5. A verification command whose regex demonstrably misses matches in the target codebase is a HIGH finding — the evidence is systematically incomplete.

**Why:** V84 used `rg "HTTPException.*status_code="` which matched 16 exceptions in a 2707-line file. The actual count was 47 — the regex missed 31 multi-line constructions of the form `raise HTTPException(\n    status_code=...)`. The methodology was disclosed per R2, the count wasn't flagged by V82 (no independent baseline), and 6 critique rounds accepted 16 as correct. The regex was never tested against the actual code output.

### Rule R16: Concordance Cell Existence Verification (The "Is It Really There?" Rule) — v1.28
**Problem this solves:** A concordance table maps items to target sections using shorthand (e.g., "Phase 1 (9.1)" for §9 column, "[ ]" for §14 column). The auditor verifies the mapping is logically coherent (OPEN items map to early phases) but never checks whether the target section actually contains the referenced item. The concordance claims a relationship that doesn't physically exist in the plan.

**Failure modes:**
- **Phantom reference:** Cell says `[ ]` for §14, implying an unchecked checkbox exists. But §14 only lists `[x]` items — no unchecked checkbox for this item was ever created. The `[ ]` is fiction.
- **Orphan mapping:** Cell says "Phase 1 (9.1)" for §9, implying the item has a §9.1 remediation entry. But §9.1 says "No open critical code defects" — the item isn't there. The phase assignment is fabricated.
- **Category mismatch:** Cell maps a LOW risk to "Phase 1: Critical" — the phase name contradicts the item's severity. Even if the item were listed there, the categorization would be wrong.

**Procedure:**
1. For every non-N/A cell in a concordance table, `grep` the target section for the specific item identifier (e.g., `R3`, `R11`, `Gate 5.5`).
2. If `grep` returns zero matches in the target section, the cell is a phantom or orphan. Change it to "N/A" with a justification parenthetical (e.g., "N/A (accepted risk)", "N/A (resolved in-plan)").
3. For phase/category mappings, verify the item's severity matches the phase's severity scope (don't map LOW items to a Critical-only phase).
4. For checkbox claims (`[ ]` or `[x]`), verify the checkbox physically exists in the target section — not just that the item's status is logically consistent with being unchecked/checked.
5. Phantom or orphan concordance cells are a MEDIUM finding.

**Why:** Codex Round 9 found 11 OPEN items mapped to "Phase 1 (9.1)" in the concordance table, but §9.1 contained only "No open critical code defects" — zero of the 11 items had entries there. The same table showed `[ ]` for §14 on OPEN items, but §14 had no unchecked checkboxes. R10's bidirectional proof mandate ("read both sections") should theoretically catch this, but in practice auditors confirmed the sections existed and the statuses were logically coherent without verifying the specific items were physically present.

### Rule R17: Count Reconciliation (The "Two Methods or It Didn't Happen" Rule) — v1.29
**Problem this solves:** Different commands that appear equivalent can return materially different counts. Without reconciliation, whichever command runs first becomes "truth," even when it is incomplete.

**Procedure:**
1. For every HIGH-impact numeric claim (scope count, exception count, route count, blast radius), run at least two structurally different methods (for example: `rg`, then parser/script-based or alternative regex).
2. Record both commands and both outputs.
3. If results differ by more than 10%, investigate and document why (multi-line construct miss, file inclusion mismatch, binary artifacts, etc.).
4. The plan must declare which method is canonical and why. "First command output" is not a valid tie-breaker.
5. Unreconciled numeric deltas are a MEDIUM finding; if they drive STOP/GO or resource estimates, escalate to HIGH.

### Rule R18: Command Confidence & Failure Handling (The "No Silent Command Failure" Rule) — v1.29
**Problem this solves:** Audits can accidentally treat failed commands as evidence, leading to false PASS states with no valid execution proof.

**Procedure:**
1. Every verification command in evidence blocks must include success confirmation (`exit 0` or explicit "command succeeded").
2. If a command fails, times out, or returns environment errors, mark the vector status as **UNVERIFIED** immediately.
3. Retry with a documented fallback command that measures the same claim.
4. Do not emit PASS until a successful rerun exists.
5. Findings produced from failed command output must be labeled LOW CONFIDENCE.

### Rule R19: Canonical Reconciliation Pass (The "Rebuild Before Closeout" Rule) — v1.29
**Problem this solves:** Per-finding fixes can leave plan summaries, totals, and status tables internally stale even when individual edits are correct.

**Procedure:**
1. Before closing a remediation round, rebuild canonical artifacts from source commands: scope inventory, per-vector counts, risk status totals, and concordance references.
2. Diff rebuilt artifacts against plan claims and summary tables.
3. Any mismatch reopens the round; no GO/APPROVE verdict is allowed until canonical artifacts and summaries match.
4. This reconciliation pass happens after all other edits, as the final gate.

### Rule R20: Artifact Namespace Isolation (The "No Shared Files in Parallel" Rule) — v1.30
**Problem this solves:** Parallel agents overwrite shared artifacts (`matter_map.json`, `evidence.jsonl`) and invalidate each other's findings. This creates nondeterministic results and false plan-vs-code mismatches.

**Procedure:**
1. Every parallel agent MUST use an isolated artifact namespace with a stable tag (CLI or agent ID), for example: `codex`, `claude`, `gemini`, `agent_1`.
2. Generate and use per-agent files:
   - `matter_map_<tag>.json`
   - `evidence_<tag>.jsonl`
   - `schemas/critique_spec_<tag>.json` (optional override; fallback to base spec if unchanged)
3. Run preflight with the same tag: `AGENT_TAG=<tag> scripts/audit/critique_preflight.sh`.
4. Reject any audit run where scope in `matter_map_<tag>.json._meta.scope_files` does not match that agent's manifest scope.
5. Never aggregate findings from agents that used shared artifact files.

**Why:** A 3-file manifest run was invalidated when `matter_map.json` was overwritten to 27 files during parallel critique, producing contradictory coverage findings. The issue was process-level artifact collision, not code drift.

### Rule R27: Spec-to-Plan Binding Verification (The "Are We Auditing the Right Plan?" Rule) — v1.31
**Problem this solves:** `critique_spec.json` is authored per-audit but often left over from a previous run. When the auditor loads the spec, it may contain scope, rules, and concordance edges for a DIFFERENT plan. Every downstream check inherits this misalignment silently — the audit is internally consistent but externally wrong.

**Procedure:**
1. Before ANY other check, read `critique_spec.json.plan_file`.
2. Compare it to the filename of the plan document being audited.
3. If they don't match, STOP. Record a **CRITICAL Finding** and do not proceed.
4. Also verify that `critique_spec.json.scope.primary` files are referenced in the plan's scope section. If the spec lists files the plan doesn't mention, the spec is stale.

**Why:** Codex caught that `critique_spec.json.plan_file` pointed to `lively-coalescing-goose.md` while the active plan was `super_audit_remaining_issues_remediation.md`. Ten rounds of Claude critique never checked this binding — every round loaded the spec but never verified it matched the plan being audited.

### Rule R28: Gate Exit-Code Semantics (The "Zero Matches Is Not Failure" Rule) — v1.31
**Problem this solves:** Done gates that prove a pattern was REMOVED expect zero matches from `rg`/`grep`. But `rg` returns exit code 1 when it finds zero matches. If the gate script uses `set -e` or checks `$?`, a successful remediation (zero matches) triggers a gate failure (exit 1). The gate is semantically inverted.

**Procedure:**
1. For every gate command, determine its **expected outcome**: "matches found" (pattern still present = FAIL) vs "zero matches" (pattern removed = PASS).
2. Run the gate command and record the exit code (`echo $?`).
3. If the gate expects zero matches but the command returns exit code 1 (which `rg` does on zero matches), verify the gate's logic handles this. Acceptable patterns:
   - `rg "pattern" || true` (suppress exit code)
   - `! rg "pattern"` (invert exit code)
   - Piped through `wc -l` and compared to 0
4. If the gate's logic doesn't handle exit-code inversion, record a **HIGH Finding: Defective Gate (Exit-Code Inversion)**.
5. For gates that only `echo` results without conditional tests, record a **MEDIUM Finding: Non-Assertive Gate** — the gate always "passes" regardless of input.

**Why:** Gates §8.7 and §8.8 used `rg` expecting zero matches. On successful remediation, `rg` returns exit 1 → the gate "fails" even though remediation succeeded. Ten rounds of critique tested gate regex accuracy but never ran the gates as automated scripts to check exit-code behavior.

### Rule R29: Source-Audit Finding Reconciliation (The "Account for Every Finding" Rule) — v1.31
**Problem this solves:** A plan says "this remediates findings from the super audit" but only references 3 of 45 finding IDs. The other 42 are silently dropped — not explicitly excluded, just never mentioned. The plan claims remediation completeness over a subset while the reader assumes it covers the full audit.

**Procedure:**
1. If the plan references a source audit, the auditor MUST locate the source audit document.
2. Enumerate ALL finding IDs from the source audit (e.g., `rg "^[A-Z]+-[0-9]+" <source_audit>` or manual extraction).
3. For each finding ID, search the plan for its occurrence.
4. Produce a reconciliation table showing: ID, description, plan section (or "—" if missing), status (ADDRESSED/EXCLUDED/MISSING).
5. Every finding must be either ADDRESSED (cited in a plan section) or EXCLUDED (explicitly listed with justification).
6. MISSING findings (neither addressed nor excluded) = **HIGH Finding: Unreconciled Source Finding**.
7. If the plan's header claims "remediates N findings" but the reconciliation shows a different addressed count = **MEDIUM Finding: Finding Count Drift**.

**Why:** The super audit remediation plan claimed to address the audit findings but only referenced 3 of 45 IDs. The other 42 findings were neither addressed nor explicitly excluded. No critique round ran a reconciliation — each round verified the 3 referenced findings were accurately described, achieving 100% accuracy over 7% coverage.

### Rule R30: Count-Type Precision (The "Files vs Matches" Rule) — v1.31
**Problem this solves:** The plan says "11 additional files contain DI patterns" but the methodology used `rg -c` which counts MATCHES, not files. The actual result was 11 matches across 8 files. The plan's claim of "11 files" is wrong — it's 8 files with 11 matches. This is a subtle but material error when the count drives scope decisions.

**Procedure:**
1. For every numeric claim about files, verify the methodology uses a file-counting command (`rg -l | wc -l`, `grep -rl | wc -l`), NOT a match-counting command (`rg -c`, `grep -c`).
2. For every numeric claim about matches/occurrences, verify the methodology uses a match-counting command, NOT a file-counting command.
3. If the claim type (files vs matches) doesn't match the methodology type, record a **MEDIUM Finding: Count-Type Conflation**.
4. For HIGH-impact counts (scope size, blast radius), always state BOTH: "N matches across M files."

**Why:** The plan claimed "11 additional files" but the `rg` command found 11 matches across 8 files. The word "files" in the plan was wrong — it should have said "matches" or "11 matches across 8 files." This numeric drift went undetected for 10 rounds because every critique verified the grep command output (11) but never checked whether "11" meant files or matches.

### Rule R31: Governance Placeholder Escalation (The "TBD Is Not an Owner" Rule) — v1.31
**Problem this solves:** Risk register rows with `Owner: TBD` pass Rule 64's "Owner present" check because `TBD` is textually non-empty. But TBD is a placeholder, not an assignment — no one is actually responsible for the risk. This creates governance theater: every risk has an "owner" but no one is accountable.

**Procedure:**
1. Scan all governance columns (Owner, Date, Gate, Responsible) for placeholder values: `TBD`, `TBC`, `TODO`, `To be determined`, `To be confirmed`, `N/A` (when used as a date or owner, not a genuine non-applicability), or blank.
2. Any placeholder in an Owner column = **CRITICAL Finding** (per Rule 64: "Missing Owner").
3. Any placeholder in a Date column = **HIGH Finding** (timeline without dates is aspirational, not planned).
4. Any placeholder in a Gate column = **HIGH Finding** (verification without a gate is unverifiable).
5. `TBD` in a description or justification column is acceptable (it's context, not governance).

**Why:** All risks in the super audit remediation plan had `Owner: TBD`. Ten rounds of critique classified this as "non-blocking" because the text `TBD` was present in the Owner field. Codex correctly flagged it as CRITICAL — a risk with no assigned owner has no one to escalate to, no one to approve mitigations, and no one accountable for resolution.

### Rule R32: Evidence-Ledger Parity (The "Receipt vs Artifact Must Match" Rule) — v1.32
**Problem this solves:** Plans claim passing receipts that contradict execution artifacts (`evidence.jsonl`). This creates fabricated GO states even when commands failed.

**Procedure:**
1. If the plan includes a receipt/evidence table, parse each mandatory gate row.
2. For each row, locate matching execution record(s) in `evidence.jsonl` (or namespaced artifact).
3. Reconcile exact values: command string, runtime path/interpreter, exit code, and pass/fail conclusion.
4. If the plan claims `rc=0` but evidence records non-zero (or vice versa), record **CRITICAL Finding: Evidence Contradiction**.
5. If a mandatory gate has no artifact record, record **CRITICAL Finding: Missing Mandatory Receipt**.

**Why:** A plan claimed GLOBAL gate `rc=0` and "56 passed" while `evidence.jsonl` recorded `rc=1`. Multiple rows were marked FIXED without matching receipts.

### Rule R33: Runtime Path Pinning (The "No Abstract Commands" Rule) — v1.32
**Problem this solves:** Audits pass with commands that only work in one shell context (e.g., bare `pytest`) and fail in reproducible project runtime.

**Procedure:**
1. For Python tooling gates (`python`, `pytest`, `mypy`, `ruff`, etc.), verify plan commands are runtime-pinned when required by project setup (e.g., `./venv312/bin/python -m pytest`).
2. Audit command history/evidence for unpinned invocations (bare `pytest`, bare `mypy`) when pinned execution is required.
3. If unpinned command results are used as proof, record **HIGH Finding: Environment-Assumption Gate**.
4. If the plan mandates pinned commands but receipts show unpinned executions, record **CRITICAL Finding: Protocol Violation**.

**Why:** Nine pytest receipts were collected via bare `pytest` while the plan protocol required venv-pinned interpreter.

### Rule R34: FIXED Status Proof Gate (The "No Receipt, No FIXED" Rule) — v1.32
**Problem this solves:** Matrix rows are marked `FIXED` based on intent or prior runs, not same-round, anchored gate success.

**Procedure:**
1. For every row labeled `FIXED`, require a same-round receipt with `exit=0` for its targeted gate.
2. Receipts must be anchored in the plan/report artifact and present in execution ledger.
3. If either condition is missing, downgrade row to `OPEN` and record **CRITICAL Finding: Unproven FIXED Status**.
4. GO is forbidden while any mandatory row is `FIXED` without proof.

**Why:** Several security rows were marked FIXED with no receipts despite STOP→GO criteria requiring anchored evidence.

### Rule R35: Receipt Hash Completeness (The "If It Isn't Hashed, It Didn't Happen" Rule) — v1.32
**Problem this solves:** Receipt rows can be edited post hoc when outputs are not integrity-bound.

**Procedure:**
1. Every mandatory receipt must include at minimum: command, cwd, timestamp/round id, exit code, `sha256(stdout)`, and `sha256(stderr)`.
2. Hashes must match ledger records; if hashes are omitted or unverifiable, record **HIGH Finding: Unanchored Receipt Integrity**.
3. A plan that promises hashes but omits them is automatically non-compliant.

**Why:** Receipts were presented without hashes, preventing forensic integrity checks.

### Rule R36: Double-Loop Closure (The "Code Then Contract" Rule) — v1.32
**Problem this solves:** Remediation updates code correctly but leaves plan contract stale (symbol drift, route over-claims, wrong mechanism text).

**Procedure:**
1. Loop A (Literal Reality): verify code, routes, symbols, and gate results.
2. Loop B (Contract Parity): verify plan wording exactly matches Loop A outputs.
3. Any mismatch (mechanism drift, route verb drift, status drift) keeps verdict at STOP.
4. This check is mandatory before final GO recommendation.

**Why:** Implementation changed to `expected_user_id` while plan still claimed `tenant_id` join; route claims included non-existent verbs.

### Rule R37: Evidence Write-Through Discipline (The "Ledger Before Receipt" Rule) — v1.32
**Problem this solves:** A remediating agent executes gates correctly in its session, then writes plan receipts from session memory. The receipts are factually correct (the gate did pass) but have no provenance chain — `evidence.jsonl` either has no entry, has a stale entry from a failed prior run, or has an entry collected with a different command/interpreter. The plan self-certifies its own success. A subsequent critique agent applying R32 (Evidence-Ledger Parity) detects the contradiction, but the damage is already done: the plan was presented as "ready for GO" when its evidence was fabricated.

**Root cause:** No forcing function exists between the agent's session context (where results live ephemerally) and the persistent ledger (where results must be proven). The agent conflates "I know it works" with "the artifact proves it works."

**Procedure (for plan authors and remediating agents):**
1. **Write-Through Rule:** When executing a gate command, the result MUST be appended to `evidence.jsonl` (or namespaced `evidence_<tag>.jsonl`) BEFORE writing any receipt in the plan. The flow is: execute → append to ledger → read back from ledger → populate plan receipt. NEVER write a plan receipt from session memory.
2. **Ledger Entry Format:** Each `evidence.jsonl` entry must contain:
   ```json
   {
     "type": "gate_receipt",
     "finding_id": "F2",
     "cmd": "./venv312/bin/python -m pytest backend/tests/test_strategy_portal.py",
     "cwd": "/home/user/project",
     "exit_code": 0,
     "stdout_sha256": "ce3b0cd433b3320c...",
     "stderr_sha256": "e3b0c44298fc1c14...",
     "timestamp": "2026-02-14T18:30:00Z",
     "git_sha": "a241efff",
     "interpreter": "./venv312/bin/python",
     "session_tag": "gemini_v8"
   }
   ```
3. **Command Exact Match:** The `cmd` field in `evidence.jsonl` MUST match the plan's Targeted Gate column character-for-character. If the plan says `./venv312/bin/python -m pytest ...`, the evidence MUST record `./venv312/bin/python -m pytest ...` — not bare `pytest`, not `python3 -m pytest`. Different command = different evidence.
4. **Supersession:** When re-running a gate (retry after fix), append a NEW entry — do not overwrite the old one. The old entry becomes historical context. The plan receipt must reference the LATEST entry. Stale entries with different exit codes are expected (they show the fix history) but must not be cited as proof.
5. **FIXED Gating:** A matrix row may ONLY be changed to `FIXED` when:
   - (a) The targeted gate has been executed using the exact pinned command,
   - (b) The result has been appended to `evidence.jsonl`,
   - (c) The plan receipt row has been populated by reading from `evidence.jsonl`, not from session memory,
   - (d) The sha256 hash in the plan matches the sha256 hash in the ledger.
6. **Anti-Pattern Detection:** The following patterns indicate R37 violation:
   - Plan receipt has no corresponding `evidence.jsonl` entry → self-certification
   - Plan receipt exit code differs from `evidence.jsonl` exit code → fabrication
   - Plan receipt command differs from `evidence.jsonl` command → interpreter drift
   - `evidence.jsonl` latest entry shows failure but plan says FIXED → stale evidence selected
   - Plan receipt hash column contains free text instead of sha256 → hash avoidance

**Why:** Gemini correctly implemented all 10 code fixes and executed gates successfully in its session. But `evidence.jsonl` contained only prior failed attempts (bare `pytest` → rc=4). The plan's receipt table claimed rc=0 with passing results — factually accurate for the session, but forensically fabricated because no ledger entry corroborated the claim. The GLOBAL gate receipt was the most egregious: `evidence.jsonl` recorded rc=1 while the plan claimed rc=0. The critique agent (Claude) caught this via R32, but the plan had already been presented as near-GO. R37 prevents this by requiring ledger-first evidence: you cannot write "FIXED" until the proof chain is complete.

### Rule R38: Stale Evidence Hygiene (The "Failed Runs Are Warnings, Not Proof" Rule) — v1.32
**Problem this solves:** After multiple remediation attempts, `evidence.jsonl` accumulates entries from failed runs (wrong interpreter, import errors, test failures). The remediating agent eventually fixes the issue and runs the gate successfully — but only appends the new success without addressing the stale failures. A critique agent reviewing `evidence.jsonl` sees a mix of failures and successes, with no clear signal about which entry is authoritative. If the agent reviews entries in order, the failures are encountered first and may override the later success.

**Procedure:**
1. When appending a successful gate entry that supersedes a prior failure, include a `supersedes` field:
   ```json
   { "supersedes": "line_2", "reason": "prior run used bare pytest (wrong interpreter)" }
   ```
2. Before declaring a remediation round complete, review `evidence.jsonl` for entries where `exit_code != 0`. For each failure, verify a superseding success entry exists. If a failure has no superseding success, it is an unresolved gate failure — the finding is NOT FIXED.
3. Critique agents reviewing `evidence.jsonl` must process entries in reverse chronological order and only accept the latest entry per gate as authoritative. Earlier entries are context, not proof.

**Why:** `evidence.jsonl` contained 9 pytest failures (rc=4, bare interpreter) and 2 py_compile successes. The failures were never superseded. The plan claimed all gates passed. The contradiction was invisible until a critique agent compared evidence.jsonl line-by-line against the plan.

### Rule R39: Receipt Row Atomicity (The "No Detached Hashes" Rule) — v1.33
**Problem this solves:** Receipt tables record hashes and pass/fail text but omit the literal command in the same row. This breaks reproducibility because an auditor cannot prove what generated the hash.

**Procedure:**
1. Every mandatory receipt row MUST include these fields in the same row: finding ID, exact command string, cwd, exit code, `sha256(stdout)`, `sha256(stderr)`, and timestamp.
2. If command text is omitted, abbreviated, or moved to another section, record **CRITICAL Finding: Non-Reproducible Receipt Row**.
3. A receipt row is invalid if any required field is inherited by implication ("same as above", "see matrix command").

**Why:** Friendly receipt tables omitted literal commands, forcing auditors to infer provenance from nearby text.

### Rule R40: Exit-Code Authority (The "Binary Verdict, Not Visual PASS" Rule) — v1.33
**Problem this solves:** Gate output can print `[PASS]` in stdout while the process exits non-zero. Visual success was accepted over shell truth.

**Procedure:**
1. Mandatory gate verdicts are determined by shell exit code only.
2. For each mandatory gate, capture and store the literal exit code from shell (`$?` or equivalent).
3. If stdout and exit code disagree, exit code wins and verdict is `STOP`.
4. GLOBAL gates (e.g., aggregate smoke/debug scripts) follow the same rule; textual summaries cannot override non-zero exit.

**Why:** A global debug script displayed successful checks in stdout but exited with failure.

### Rule R41: Ledger Literality (The "No Friendly Command Names" Rule) — v1.33
**Problem this solves:** `evidence.jsonl` entries used shorthand/friendly labels instead of the exact matrix command, preventing bit-for-bit reconciliation.

**Procedure:**
1. `evidence.jsonl.command` MUST be the exact executed shell command and MUST match the matrix targeted gate character-for-character.
2. Aliases such as "pytest ws auth", "global quick gate", or normalized command labels are prohibited as proof fields.
3. If the ledger command differs from the matrix command (even if semantically similar), record **CRITICAL Finding: Command Literality Violation**.
4. **ID Concordance:** The finding/gate ID in the plan receipt table (e.g., `F1`, `GLOBAL`) MUST match the `finding_id` or `id` field in `evidence.jsonl` character-for-character. ID aliases (e.g., `G` vs `GLOBAL`, `F11` vs `frontend_ws`) break automated reconciliation and are a **MEDIUM Finding: ID Concordance Drift** (FM-69).

**Why:** Command normalization hid interpreter drift and invalidated proof equality checks.

### Rule R42: Split-Stream Hash Schema (The "No Combined Digest" Rule) — v1.33
**Problem this solves:** A single combined output hash can hide stderr anomalies and cannot prove error-stream integrity.

**Procedure:**
1. Mandatory receipts require two distinct fields: `stdout_sha256` and `stderr_sha256`.
2. Combined or unlabeled hashes are non-compliant and must be treated as missing integrity data.
3. If a plan claims hash compliance with only one digest, record **HIGH Finding: Hash Schema Incompleteness**.

**Why:** Combined hashing allowed apparent success while critical stderr content remained unaudited.

### Rule R43: Post-Implementation Route Reconciliation (The "Path Reality Recheck" Rule) — v1.33
**Problem this solves:** Security fixes were implemented on literal routes, but plan text kept logical route names that do not exist in decorators.

**Procedure:**
1. After any implementation change touching API handlers, rerun route inventory:
   - `rg -n "@router\\.(get|post|put|patch|delete)" <file>`
2. Update plan contract text to use literal decorator verb/path pairs, not conceptual endpoint names.
3. If plan path claims do not match live decorators, record **HIGH Finding: Route Contract Drift**.

**Why:** A guard was implemented on `POST /submit` while the plan continued to claim `/update`.

### Rule R44: Full-Length Hash Integrity (The "No Cosmetic Truncation" Rule) — v1.33
**Problem this solves:** Both remediating and auditing agents truncate SHA-256 hashes to fit markdown table columns (e.g., `ce3b0cd433b33209...` or first-16-chars). This is a systematic LLM tendency — both Claude and Gemini independently committed this error in the same audit. A truncated hash is cryptographically useless: it cannot be independently verified, compared bit-for-bit, or used to detect tampering. Receipt tables with truncated hashes provide the *appearance* of forensic integrity while offering none of the *substance*.

**Procedure:**
1. Every SHA-256 hash in a receipt table, audit report, or `evidence.jsonl` entry MUST be the full 64-character hex string. No exceptions.
2. If markdown table columns are too narrow, use one of: (a) code blocks with line wrapping, (b) a dedicated wide column, (c) a separate hash appendix table referenced by finding ID. Do NOT truncate the hash to fit the layout.
3. Detection: run `rg -P '[a-f0-9]{8,62}\.{2,3}' <artifact>` to find ellipsis-truncated hashes. Also check any hash string with `length != 64` characters.
4. A receipt row with a truncated hash is treated as having NO hash — it fails R35 (Receipt Hash Completeness) in addition to R44.
5. Audit reports that truncate hashes while simultaneously flagging the plan for truncated hashes are a **self-contradicting audit** — the auditor is non-compliant with the same standard it enforces.

**Why:** Both Claude and Gemini truncated hashes to 16 characters in their audit reports while demanding full hashes from the plan. This double standard went undetected because no rule explicitly prohibited truncation in the auditor's own output — only in the plan's receipts. R44 closes this gap by applying full-length hash requirements to ALL artifacts (plans, reports, and ledgers) and ALL agents (authors, remediators, and auditors).

### Rule R45: Row-Atomic Receipt Design (The "No Header-Extracted Fields" Rule) — v1.33
**Problem this solves:** Agents factor common receipt metadata (cwd, timestamp, execution context, interpreter path) into section headers or "Execution Context" preambles to avoid repetition. This violates row atomicity: if a single receipt row is extracted for cross-reference, dispute, or re-audit, it loses its execution context. The DRY principle is a code maintenance heuristic; it does not apply to forensic evidence, where redundancy IS the integrity mechanism.

**Procedure:**
1. Every mandatory receipt row must be a self-contained proof record. Required columns: finding ID, exact command string, cwd, interpreter/runtime, exit code, `sha256(stdout)`, `sha256(stderr)`, timestamp.
2. Fields shared across rows (e.g., same cwd for all gates) MUST still appear in every row. Section headers may repeat this information as navigation context, but the per-row instance is authoritative.
3. Detection: if a receipt table is missing columns for cwd, timestamp, or command while the surrounding section header contains "Execution Context:", "Working Directory:", or "Date:", the table has header-extracted fields — this is a CRITICAL finding.
4. The "Execution Context" preamble pattern is explicitly prohibited as a substitute for per-row fields. It may exist as supplementary context but MUST NOT be the only place where cwd/timestamp/interpreter appear.

**Why:** Both Claude and Gemini independently applied DRY to receipt tables, factoring cwd, timestamp, and interpreter into section headers. This is a systematic LLM tendency — agents optimize for readability (avoid repetitive columns) at the expense of forensic utility (self-contained proof rows). R45 makes the counter-intuitive requirement explicit: in evidence tables, repetition is a feature, not a code smell.

### Rule R46: Gate Stability Proof (The "One Pass Is Not Enough" Rule) — v1.33
**Problem this solves:** A mandatory gate has a history of failures (rc=1 in `evidence.jsonl` from prior runs) but passes once (rc=0) in the current session. The agent accepts this single pass as proof. However, a gate that sometimes fails and sometimes passes is non-deterministic — the single pass proves the gate CAN succeed, not that it RELIABLY succeeds. Common causes: race conditions, network timeouts, transient resource locks, test ordering dependencies.

**Procedure:**
1. After executing each mandatory gate, check `evidence.jsonl` for prior entries with the same command. If ANY prior entry shows a different exit code (e.g., rc=1 previously, rc=0 now), the gate has mixed exit-code history.
2. Gates with mixed history require **3 consecutive passes** with all 3 receipts recorded in `evidence.jsonl`. The 3 runs MUST include at least one run separated by ≥30 seconds from the others (e.g., run 1, wait 30s, run 2, wait 30s, run 3). Same-second consecutive runs in the same shell session are insufficient — they do not test for environment sensitivity, resource contention, or timing-dependent failures. If temporal separation is impractical, the auditor MUST disclose "same-session limitation" and downgrade the stability proof to MEDIUM confidence. If any of the 3 runs fails, the gate is classified as non-deterministic.
3. Non-deterministic gates trigger one of two remediation paths: (a) fix the underlying flakiness (race condition, timeout, etc.) and re-prove with 3 passes, or (b) replace the gate with a deterministic alternative that tests the same property.
4. A flaky gate cannot produce GO. The plan verdict remains STOP until the gate is either stabilized or replaced.
5. **Aggregate gate independence:** Do NOT assume constituent gate success implies aggregate gate success. If F1-F10 individual gates all pass but the GLOBAL gate (e.g., `debug_everything.py`) has mixed history, the GLOBAL gate must be independently proven stable with 3 consecutive passes.

**Why:** `debug_everything.py --quick` returned rc=1 in `evidence.jsonl` but rc=0 on a later run. Neither Claude nor Gemini re-ran the GLOBAL gate — both assumed that since all constituent gates (F1-F10) passed individually, the aggregate must also pass. This assumption ignores integration-level failures (import ordering, resource contention, test isolation) that only manifest when all checks run together. R46 requires stability proof proportional to the gate's reliability history.

### Rule R47: Plan-as-Custody Authority (The "No Summary Downgrade" Rule) — v1.34
**Problem this solves:** Agents treat `evidence.jsonl` as the full proof artifact and the plan receipt table as a human-readable summary. This causes omission of per-row custody fields (`cwd`, timestamp, interpreter) from the plan, breaking chain-of-custody in the plan artifact itself.

**Procedure:**
1. The plan receipt table is a primary chain-of-custody artifact, not a summary view.
2. `evidence.jsonl` corroborates plan rows; it does not compensate for missing plan row fields.
3. If a required receipt field appears only in `evidence.jsonl` or section headers but not in the plan row, record **CRITICAL Finding: Artifact Presentation Bias / Summary Downgrade**.
4. Deterministic schema check: parse the plan receipt table header and require exact columns for command, cwd, interpreter/runtime, exit code, `sha256(stdout)`, `sha256(stderr)`, timestamp. Missing any required column is CRITICAL.

**Why:** In forensic workflows, the plan travels as the decision artifact. If plan rows are non-atomic, auditability is lost when JSONL context is absent.

### Rule R48: Minimum Report Structure Gate (The "No Rubber-Stamp" Rule) — v1.35
**Problem this solves:** An auditor declares APPROVED with zero findings and no per-agent finding tables. This is statistically improbable for any non-trivial plan and indicates either (a) interlocks were not executed, (b) findings were suppressed, or (c) the audit was superficial. This happened when Gemini produced a 26-line "APPROVED" report with no agent sections, no finding tables, and no interlock receipts — while the same plan had 4 CRITICALs and 6+ HIGHs detected by two other auditors.

**Procedure:**
1. A critique report MUST contain: (a) all 6 agent sections with `### Findings` tables (even if a table has zero rows), (b) a consolidated findings list, (c) per-interlock verification receipts from Step 1.
2. A report that declares APPROVED/GO with zero findings across ALL agents is automatically suspect. The auditor must verify: for each agent, is there positive verification evidence showing the finding class was checked and cleared? If not, the report is incomplete.
3. If the report lacks required structural sections, record **CRITICAL Finding: Incomplete Audit Execution** (FM-70).
4. Zero findings is valid ONLY when each agent section documents what was checked and why no finding was warranted (e.g., "Verified governance columns present: Phase, Owner, Rollback, Gate — no gap found").

**Why:** Gemini declared "100% literal parity" and "No forensic drift detected" with zero findings, while Claude found 25 and Codex found 11. The prompt required agent output format but had no enforcement that the report actually CONTAINS the required structure. A rubber-stamp APPROVED is worse than no audit — it creates false confidence.

### Rule R49: Severity Binding (The "No Subjective Downgrade" Rule) — v1.35
**Problem this solves:** An auditor finds a rule violation that the Severity Definitions table classifies as CRITICAL but rates it MEDIUM based on subjective judgment ("it's just a missing column," "low practical impact"). This undermines the deterministic severity framework — if auditors can override rule-defined severities, the severity table is advisory rather than binding.

**Procedure:**
1. When a finding matches a rule listed in the Severity Definitions table, the auditor MUST use the severity defined there. The table is binding, not advisory.
2. Auditor judgment applies ONLY to findings not covered by a specific rule in the severity table.
3. Downgrading a rule-defined severity requires explicit justification citing why the rule's classification is inapplicable to this specific instance — not why the impact seems low.
4. Any severity downgrade MUST be recorded as a separate finding: **INFO Finding: Severity Override** (FM-72) with the justification, so the override is transparent and auditable.
5. When in doubt, use the higher severity. Over-classification is correctable; under-classification masks risk.

**Why:** Claude rated an R47 violation (missing interpreter/runtime column) as MEDIUM. The Severity Definitions table explicitly lists R47 as CRITICAL. Codex correctly rated it CRITICAL. The subjective downgrade was invisible until the cross-auditor comparison revealed the discrepancy. R49 makes the severity table authoritative and requires transparency for any override.

### Rule R50: Receipt ID Concordance (The "Same Name, Same Gate" Rule) — v1.35
**Problem this solves:** The plan receipt table uses one ID for a gate (e.g., `G`) while `evidence.jsonl` uses a different ID for the same gate (e.g., `GLOBAL`). A script or auditor matching plan rows to ledger entries by ID finds zero matches, even though the same gate was executed. This is a subtler form of R41 (Ledger Literality) that applies to the identifier column rather than the command column.

**Procedure:**
1. For each row in the plan receipt table, extract the finding/gate ID (first column).
2. Search `evidence.jsonl` for an entry whose `finding_id`, `id`, or equivalent field matches that ID character-for-character.
3. If no exact match exists but a semantically equivalent entry exists (same command, different ID), record **MEDIUM Finding: ID Concordance Drift** (FM-69).
4. The plan author must choose one canonical ID per gate and use it consistently in: (a) the remediation matrix, (b) the receipt table, (c) `evidence.jsonl`, and (d) the critique report.

**Why:** The plan used "G" for the GLOBAL gate receipt but `evidence.jsonl` used "GLOBAL." Claude caught this as an H3 concordance finding. Codex and Gemini both missed it because their reconciliation checked command strings (which matched) but not IDs. R50 closes this gap by extending literality checking to the ID column.

### Rule R51: STOP-to-GO Exit Criteria (The "Dead End Prevention" Rule) — v1.35
**Problem this solves:** A plan declares STOP verdict due to an unresolved blocker (e.g., frontend dependency, flaky gate) but defines no conditions for transitioning to GO. Without exit criteria, STOP is a dead end — the plan blocks release indefinitely with no actionable path forward, no assigned owner, and no timeline. Stakeholders cannot distinguish "STOP because we need 2 more days" from "STOP because no one knows what to do."

**Procedure:**
1. Any plan with a STOP verdict MUST include a "GO Criteria" section listing:
   - (a) Specific, testable conditions that must be met for each OPEN/BLOCK item (e.g., "F11 transitions to FIXED when `rg 'token=.*strategy_tribunal' frontend/website/src` returns rc=0").
   - (b) For each OPEN item: an owner (name or role, not TBD), a target date or sprint, and an escalation path if the date slips.
   - (c) For flaky gates: either a fix plan with root-cause analysis or a replacement gate specification.
2. A STOP plan without GO criteria = **HIGH Finding: Terminal STOP** (FM-73).
3. GO criteria must be machine-verifiable where possible (gate commands, grep patterns, test commands) — not subjective ("when the team feels confident").

**Why:** The plan declared STOP due to F11 (frontend WebSocket dependency) but provided no owner, no target sprint, no deadline, and no definition of what "F11 done" looks like. Claude flagged this (H4: No GO criteria, H5: BLOCK lifecycle undefined). Codex and Gemini both missed it. Without R51, a STOP plan can persist indefinitely as an unfalsifiable blocker.

### Rule R52: Gate Coverage Verification (The "Defective Gate" Rule) — v1.36
**Problem this solves:** A gate passes (rc=0) but does not exercise the code path where the bug exists. The gate gives false confidence — the plan marks the finding as FIXED, the receipt shows rc=0, the evidence is consistent, but the bug is still in the code. This is more insidious than a failing gate because it passes all structural checks (R32-R47) while the underlying defect persists.

**Procedure:**
1. For each gate that returns rc=0, the auditor MUST verify that the gate's test suite actually exercises the remediated code path. A gate that tests unrelated functionality is a **defective gate** even if it passes.
2. **Cross-reference check:** If an independent code spot-check (Interlock 10) reveals a bug in a scope file, AND a gate for that file passes, the auditor MUST determine whether the gate's test coverage includes the buggy code path. If not, record **CRITICAL Finding: Defective Gate — False FIXED Status** (FM-74).
3. **Detection heuristic:** If a NameError, ImportError, or other guaranteed-crash bug exists in source code but the corresponding gate passes, the gate is defective by definition — a test that doesn't reach the crash site cannot prove the crash is fixed.
4. When a defective gate is found, the plan's FIXED status for that finding MUST be downgraded to **UNPROVEN** until either: (a) the test suite is extended to cover the affected code path, or (b) the bug is fixed and verified by a gate that does exercise it.
5. A defective gate does not invalidate the receipt (the gate genuinely passed) but it invalidates the FIXED inference. The receipt proves the gate ran; it does not prove the bug is gone.

**Why:** Gemini V11 discovered that `test_strategy_portal.py` passes (F2 gate rc=0) despite `and_` being missing from the import block in `strategy_portal.py:22` — a guaranteed NameError at 9 call sites. The test suite never exercises those 9 code paths, so the gate passes without testing the fix. Claude ran the same gate, confirmed rc=0, and accepted F2 as FIXED without questioning whether the gate tested the right thing. R52 closes this gap by requiring auditors to verify gate-to-bug-path coverage, not just gate exit codes.

### Rule R53: Line-Content Evidence (The "Show Your Work" Rule) — v1.37
**Problem this solves:** An auditor claims source code does or doesn't match the plan description, but the claim is based on reconstructed memory rather than the actual file. Example: Gemini V11 claimed `monitoring.py:581` still contained `await get_redis_client()` when the line actually reads `r = get_redis_client()` (no await). The claim was plausible but factually wrong (FM-76).

**Procedure:**
1. When a spot-check claims code does or does not match the plan, the agent MUST include the exact source line with line number as quoted evidence (e.g., `monitoring.py:581: r = get_redis_client()`).
2. Claims about file content without verbatim line quotation are automatically INVALID and cannot support findings above INFO.
3. If an auditor cannot quote the line from the tool output, the auditor MUST re-read the file rather than asserting from memory.

**Why:** Gemini V11 asserted a CRITICAL finding based on hallucinated file content. RULE 94 forces a grounding step that prevents this class of false positive.

### Rule R54: Gate Regex Anti-Comment (The "No Comment-ware" Rule) — v1.37
**Problem this solves:** An executor writes a gate regex and also writes a code comment that satisfies it, creating a non-discriminating gate. Example: Claude wrote `rg "token=.*strategy.tribunal"` as the F11 gate and added `// token=...strategy_tribunal` as a trailing comment on the same line. The regex matched the comment, not the functional code. Both Gemini V11 and Codex V12 caught this.

**Procedure:**
1. For each regex-based gate (e.g., `rg "pattern" <path>`), the auditor MUST run the gate and inspect what it matches.
2. If ANY match is in a code comment (`//`, `#`, `/* */`, `<!-- -->`) rather than functional code, the gate is defective (FM-74).
3. The executor MUST NOT add comments whose sole purpose is to satisfy a gate regex (Goodhart's Law: when the measure becomes the target, it ceases to be a good measure).

**Why:** Both Gemini and Codex independently identified this as a Goodhart's Law violation. RULE 95 prevents it.

### Rule R55: SQL Column Data Flow (The "SELECT Matches GET" Rule) — v1.37
**Problem this solves:** A remediation adds WHERE-clause scoping to a SQL query but omits the scoped column from the SELECT list. Downstream `.get("column")` returns `None`, silently defeating the scoping logic. Example: Codex V12 found `_load_financial_summary` had `WHERE user_id = :user_id` but the SELECT didn't include `user_id`, so `financial_summary.get("user_id")` always returned `None` (FM-75).

**Procedure:**
1. For any finding that adds WHERE-clause scoping (e.g., `AND user_id = :user_id`), verify the SELECT column list includes the scoped column.
2. Trace downstream: if application code calls `.get("column_name")` on the query result, verify that column is in the SELECT.
3. A WHERE-only fix without SELECT inclusion = **HIGH Finding: Silent Column Omission** (FM-75).

**Why:** Codex V12 traced the full data flow from SQL to application code and found this bug. It represents a class of errors where the security filter works at the database level but the application can't use the filtered data.

### Rule R56: Gate Replay Environment Parity (The "Same Machine" Rule) — v1.37
**Problem this solves:** An auditor replays a gate in a different execution environment (different Python version, missing PYTHONPATH, sandbox without project dependencies) and gets a different exit code. The auditor then files a CRITICAL finding based on the non-parity replay. Example: Codex V12 replayed the GLOBAL gate and got rc=1 (50 passed, 1 failed) while the same gate passes rc=0 (56 passed) in the project environment.

**Procedure:**
1. Gate replays MUST use the same interpreter path, PYTHONPATH, working directory, and virtual environment as the original evidence.
2. If the replay environment differs, the auditor MUST note the discrepancy.
3. Findings from non-parity replays cannot be classified above MEDIUM.

**Why:** Codex V12's GLOBAL rc=1 false positive was caused by environment differences, not by code bugs. RULE 97 prevents non-parity replays from triggering STOP verdicts.

### Rule R57: Mandatory Preflight Before PASS (The "No PASS Without Gate Replay" Rule) — v1.40
**Problem this solves:** Agents conclude "plan verified" from spot checks without replaying deterministic gate tooling, missing CRITICAL V105/V106 failures that preflight would catch immediately.

**Procedure:**
1. Before any PASS/GO recommendation, the auditor MUST run:
   - `python scripts/audit/plan_preflight.py --plan-file <plan.md>`
2. The critique report MUST include the command, exit code, and summarized failing vectors (if any).
3. If this command is not run, the critique cannot be classified as PASS; verdict is automatically FAIL-INCOMPLETE.

**Why:** A single preflight run catches missing Integration Contract blocks and route annotation violations that often evade manual, claim-by-claim review.

### Rule R58: Frontend Non-Exemption for V105/V106 (The "Frontend Still Has Boundaries" Rule) — v1.40
**Problem this solves:** "Frontend-only" framing is incorrectly treated as exempt from boundary and route reality checks, causing uncaught payload-contract mismatches and unannotated frontend routes.

**Procedure:**
1. If a plan is labeled "frontend-only", still run V105 and V106.
2. For any frontend route mention (e.g., `/consulting`), require `[FRONTEND]` annotation on the same line.
3. For any frontend payload submitted to backend APIs, require at least one Integration Contract block proving request-shape parity.
4. Missing `[FRONTEND]` annotation or missing frontend->backend Integration Contract is a CRITICAL finding.

**Why:** "No backend code change" increases contract risk at the interface, it does not reduce it.

### Rule R59: Value-Trace Requirement for Coercion Paths (The "Trace One Value End-to-End" Rule) — v1.40
**Problem this solves:** Architecture-level descriptions hide coercion bugs (especially booleans/dates/numbers) that only appear when tracing concrete values across parsing boundaries.

**Procedure:**
1. For each transformed input channel (CSV, query params, form text fields, env vars), trace at least one concrete value end-to-end.
2. Required chain format:
   - `raw input -> JS/TS type -> serialized JSON -> Python type -> domain model field`
3. Mandatory examples include a "false-like" boolean token, one date token, and one numeric token.
4. If any step relies on language truthiness/casting without explicit conversion rules, file HIGH or CRITICAL depending on impact.

**Why:** This catches `Boolean("false")` and `bool("false")` class bugs that static field tables miss.

### Rule R60: Line-Range Contradiction Check (The "Remove vs Keep Collision" Rule) — v1.40
**Problem this solves:** Plans often contain contradictory edit instructions across sections (e.g., remove lines X-Y while also preserving content inside X-Y).

**Procedure:**
1. For every instruction of the form "remove lines A-B", scan the plan for "keep/stays/preserve lines C-D" references to the same file.
2. If `(C-D)` overlaps `(A-B)` and no explicit carve-out is written, file HIGH finding for self-contradiction (V57).
3. Require either non-overlapping ranges or explicit carve-out wording in the removal instruction.

**Why:** Mechanical range overlap errors are frequent and can invalidate implementation steps even when all individual claims are true.

### Rule R61: Approximation Guard for Numeric Claims (The "No Tilde Without Method" Rule) — v1.40
**Problem this solves:** Unverified approximations (`~`, "about", "roughly") create false confidence and are not reproducible.

**Procedure:**
1. Any numeric claim using approximation markers (`~`, "about", "roughly", "approx") MUST include derivation methodology and source timestamp/context.
2. Prefer exact counts for plan-local arithmetic (e.g., line-estimate totals from table sums).
3. If approximation is unavoidable (external bundle size, API quota), cite source and capture date.
4. Bare approximations without method are ERROR.

**Why:** Numeric reproducibility is required for scope/risk governance and prevents silent drift.

### Rule R62: Contract Wording Completeness (The "Accepted Alias Coverage" Rule) — v1.40
**Problem this solves:** Plans describe one accepted key/path/value while code accepts multiple aliases, creating misleadingly narrow contracts.

**Procedure:**
1. When documenting required request fields, verify whether code accepts aliases/synonyms/fallback keys.
2. If aliases exist, the plan MUST either:
   - list accepted variants explicitly, or
   - state a deliberate normalization strategy and deprecation plan.
3. Omission of known accepted aliases is a MEDIUM finding (HIGH if it can break compatibility decisions).

**Why:** Accurate contract wording prevents accidental regressions during refactors.

### Rule R63: Mandatory Pre-Submission Self-Consistency Sweep (The "Author Must Re-Read" Rule) — v1.40
**Problem this solves:** Plans are submitted after isolated edits without a final coherence pass, leaving obvious contradictions and stale assertions.

**Procedure:**
1. Last step before submission MUST include:
   - `python scripts/audit/plan_preflight.py --plan-file <plan.md>`
   - `python scripts/audit/route_parity_check.py --plan-file <plan.md>`
2. Author/auditor must perform one full linear re-read of the plan and confirm:
   - no contradictory line-range instructions,
   - no unresolved placeholder TODO language in gates,
   - no stale numeric claims lacking methodology.
3. If the sweep is not evidenced, verdict cannot exceed FAIL-INCOMPLETE.

**Why:** One final mechanical sweep catches classes of mistakes that survive multi-agent spot checks.

## Execution Protocol

1. **Spawn Agents:** Divide the plan into logical sections (Scope, Data, Risks, etc.).
2. **Assign Vectors:** Assign specific Tier 1, 2, and 3 vectors to each agent.
3. **Mandate Evidence:** Every finding must be backed by a pasted code snippet or command output.
4. **Aggressive Cross-Referencing:** Agent 5 (Risks) must check Agent 6 (Timelines) findings.
5. **Evidence-Ledger Parity Pass:** Run Rules R32-R56 before any GO recommendation.
   - **5a. Forensic Lint:** Run `python scripts/forensic_lint.py <plan_file>` for automated mechanical checks (R50 ID concordance, R44 hash length, R46 stability proof, R37 command parity). Hard-fail = STOP.
6. **Consolidate:** Merge findings, deduplicate, and assign final severity.
   - Use a deterministic dedup key: `vector + file:line + target pattern`.
   - If multiple agents report the same issue, keep one canonical finding and preserve the highest justified severity.
   - Record which agent findings were merged, so traceability is retained without duplicate remediation work.
7. **Canonical Reconciliation:** Run Rules R19 and R36 before publishing the final verdict.
8. **Pre-PASS Hard Gates:** Run Rules R57-R63 before any PASS/GO recommendation (mandatory for frontend-only plans as well).

## Severity Definitions
- **CRITICAL:** Guaranteed runtime crash, data loss, blocking dependency failure, or forensic evidence contradiction (e.g. R32 contradiction, R33 protocol violation, R34 unproven FIXED, R37 self-certification/fabrication, R39 non-reproducible receipt row, R41 command literality violation, R44 truncated hashes, R45 header-extracted row fields, R47 summary downgrade of custody fields, R48 incomplete audit execution, R52 defective gate / false FIXED status, Rule 31 owner placeholder).
- **HIGH:** Security bypass, major scope error (>50%), compliance violation, or receipt-integrity breach without contradiction (e.g. R35 missing hashes, R38 stale evidence without supersession, R42 split-hash missing, R43 route contract drift, R46 flaky gate without stability proof, R51 terminal STOP without exit criteria, R54 comment-matched gate regex, R55 silent column omission, Rule 28 exit-code inversion, Rule 29 unreconciled source findings).
- **MEDIUM:** Data hygiene issue (orphaned rows), maintainability risk, or documentation ambiguity. Also: count-type conflation (Rule 30), R50 ID concordance drift, stale open questions (Rule 66 extension).
- **LOW/INFO:** Minor inconsistency, typo, or clarification request. Also: R49 severity override (INFO — transparency record), R53 spot-check without line quotation (INFO/INVALID), R56 non-parity replay (MEDIUM cap).
