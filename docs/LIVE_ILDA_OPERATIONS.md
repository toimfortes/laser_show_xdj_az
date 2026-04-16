# Live ILDA Operations

This document describes the current production-ready software path for ILDA-capable lasers in this repo.

## Output Modes

The file-playback path supports three ILDA modes:

- `memory`
  - Preview only.
  - Generates ILDA frames in-process for the browser/control plane.
  - Does not write `.ild` files and does not stream to hardware.

- `ild`
  - Generates ILDA frames and writes a `.ild` file.
  - Good for offline inspection, archival, or downstream tools.

- `ether_dream`
  - Streams ILDA frames live to an Ether Dream DAC over TCP.
  - Includes startup reachability preflight in live validation paths.
  - Includes reconnect-on-fault handling in the ILDA output node.

## Recommended Commands

Preview only:

```bash
photonic run-file "/path/to/track.mp3" --web --ilda-transport memory
```

Generate a `.ild` file while running the browser control plane:

```bash
photonic run-file "/path/to/track.mp3" --web --ilda-transport ild
```

Write to a custom `.ild` path:

```bash
photonic run-file "/path/to/track.mp3" \
  --web \
  --ilda-transport ild \
  --ilda-export-path /tmp/show.ild
```

Stream live to an Ether Dream DAC:

```bash
photonic run-file "/path/to/track.mp3" \
  --web \
  --ilda-transport ether_dream \
  --ether-dream-host 192.168.1.50 \
  --ether-dream-port 7765
```

## Control-Plane Visibility

When the control plane is running, the runtime summary exposes:

- ILDA transport type
- Ether Dream host when relevant
- transport fault state
- hardware warnings for unverified laser profiles

The live diagnostics API also exposes the current ILDA transport state via:

- `GET /api/live/state`

## Safety and Commissioning

The repo intentionally fails closed for unverified live laser profiles unless explicitly overridden.

Current CX338B profile status:

- primary control surface: `ILDA`
- fallback surface: `DMX adapter`
- software profile: present
- exact hardware commissioning: still required

If a laser profile is marked as requiring commissioning or inferred adapter data, live startup should not be treated as fully verified hardware operation until the real unit is commissioned.

Explicit override for testing only:

```bash
export PHOTONIC_RUNTIME_FLAGS__ALLOW_UNVERIFIED_LASER_PROFILES=true
```

That override should only be used deliberately and with conservative overhead-only assumptions.

## Current Software Guarantees

The software path now includes:

- per-track show plans with autosave
- progressive-house ILDA grammar
- internal ILDA frame generation
- `.ild` export
- Ether Dream live streaming
- startup reachability checks for Ether Dream in live validation
- reconnect behavior after Ether Dream transport faults
- control-plane diagnostics for ILDA transport health

## Remaining Non-Software Blockers

These are the main items still outside pure software implementation:

- verify the exact CX338B channel chart and adapter behavior from the real manual/unit
- commission safe projection zones for the real venue/use case
- verify DAC/network topology on the actual festival machine
- verify the projector's real-world scan/safety behavior under your intended looks

Until those are complete, the repo should be treated as software-production-ready with hardware commissioning still pending.
