# Boundary Contract Template (MANDATORY)

Use this template for *every* cross-module integration in a plan.

Definition: A "boundary" is any place where the plan composes facts across modules, e.g.
- request model -> service call
- JWT-derived identifiers -> request/body fields -> repository predicates
- route decorator paths -> include_router mounts -> final URL paths
- interface/port extension -> all implementers

If a plan proposes a boundary change without this contract block, the critique must be STOP.

---

### Integration Contract: <NAME>

**Why this boundary exists:** <one sentence>

**Caller (anchor):** `path/to/caller.py:LINE`  
**Callee (anchor):** `path/to/callee.py:LINE`

**Call expression (verbatim):**
```python
<paste the exact call site line(s) as planned>
```

**Callee signature (verbatim):**
```python
<paste def signature including types/defaults>
```

**Request/Source schema (verbatim, if applicable):**
```python
<paste request model fields / DTO fields / settings fields used as sources>
```

**Argument mapping + type chain (REQUIRED):**

| Arg | Required? | Source expression | Type@Source | Type@Callee | Conversion | Notes |
|---|---|---|---|---|---|---|
| `<arg>` | yes/no | `<expr>` | `<type>` | `<type>` | `<none|uuid.UUID()|str()|int()|...>` | `<optional>` |

**Missing required inputs (if any):**
- <arg>: <why missing> (CRITICAL)

**Incompatible types (if any):**
- <arg>: <source_type> -> <callee_type> (<why not safe>) (CRITICAL)

**Return/Response contract (REQUIRED):**
- **Return value shape:** <type/schema>
- **Caller expects:** <type/schema>
- **Response model (if API):** `path/to/api.py:LINE` + name
- **Mismatch?** yes/no (CRITICAL if yes)

**Failure modes / status codes (REQUIRED for API boundaries):**
| Failure | Trigger | Where raised | HTTP code (if any) | Caller behavior |
|---|---|---|---|---|
| `<name>` | `<condition>` | `path:line` | `<code>` | `<what happens>` |

**Verdict:** PASS / FAIL

