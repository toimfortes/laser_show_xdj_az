# Audit Phase: types

- Target: `.`
- Findings: 12
- Duration: 31.3s

## Findings (Top 50)

- **high** `tests/unit/test_production_hardening.py:46` (dict-item): Dict entry 1 has incompatible type "int": "float"; expected "int": "int"
- **high** `tests/unit/test_production_hardening.py:69` (dict-item): Dict entry 1 has incompatible type "int": "float"; expected "int": "int"
- **high** `tests/unit/test_production_hardening.py:70` (dict-item): Dict entry 2 has incompatible type "int": "float"; expected "int": "int"
- **high** `tests/unit/test_production_hardening.py:197` (no-untyped-def): Function is missing a type annotation
- **high** `tests/unit/test_production_hardening.py:197`: Error code "no-untyped-def" not covered by "type: ignore" comment
- **high** `tests/unit/test_production_hardening.py:203` (method-assign): Cannot assign to a method
- **high** `tests/unit/test_production_hardening.py:204` (method-assign): Cannot assign to a method
- **high** `tests/unit/test_production_hardening.py:209` (func-returns-value): "assert_called" of "NonCallableMock" does not return a value (it only ever returns None)
- **high** `tests/unit/test_production_hardening.py:217` (no-untyped-def): Function is missing a type annotation
- **high** `tests/unit/test_production_hardening.py:217`: Error code "no-untyped-def" not covered by "type: ignore" comment
- **high** `tests/unit/test_production_hardening.py:221` (method-assign): Cannot assign to a method
- **high** `tests/unit/test_production_hardening.py:222` (method-assign): Cannot assign to a method
