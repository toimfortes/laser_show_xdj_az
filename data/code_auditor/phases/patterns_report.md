# Audit Phase: patterns

- Target: `.`
- Findings: 3
- Duration: 134ms

## Findings (Top 50)

- **info** `src/photonic_synesthesia/graph/nodes/dmx_output.py:154` (PAT): DMX universe created as 512 bytes; should be 513 (start code + 512 channels).
- **info** `src/photonic_synesthesia/graph/nodes/dmx_output.py:147` (PAT): Exception caught without variable binding — use 'except Exception as exc:' and log exc_info.
- **info** `src/photonic_synesthesia/graph/nodes/dmx_output.py:161` (PAT): Exception caught without variable binding — use 'except Exception as exc:' and log exc_info.
