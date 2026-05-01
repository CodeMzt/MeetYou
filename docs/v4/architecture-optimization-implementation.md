# V4 Architecture Optimization Implementation Notes

Date: 2026-05-01

This note records the first implementation pass for the V4 architecture review.

## Protocol contract

- `subscription.start`, `subscription.update`, and `subscription.stop` are implemented as active Endpoint WebSocket frames.
- `delivery.inbox_item` has a manager fan-out path for direct endpoint delivery or thread subscription delivery.
- `tool.call.cancel` is represented in the protocol SDK and is handled by both Core-side frame handling and Endpoint Provider runtime cancellation.
- `/client/*` and `/client/ws` remain removed surfaces. Do not add removed-response compatibility handlers.

## Runtime behavior

- UI endpoint hello frames include a V4 protocol offer.
- UI connection state becomes `connected` only after `endpoint.hello.ack` and `subscription.ack`.
- UI confirmation and human-input responses use Runtime HTTP only; invalid raw action payloads are no longer sent over `/endpoint/ws`.
- Scheduler ticks repair missing `next_fire_at`, then query due jobs directly instead of scanning every job on each tick.
- ToolRouter records endpoint routing failures for unavailable transports, failed dispatch, and timeouts.

## Verification expectations

- Endpoint protocol tests cover subscription update/stop, inbox item delivery, and cancel frames.
- Main-branch CI runs full backend discovery and frontend build after the fast regression slice.
- Core deploy runs after successful CI or manual dispatch, then checks remote Core health before completing.
- `scripts/manual-acceptance.ps1 check` runs `scripts/v4_real_acceptance.py` unless `-SkipRealAcceptance` is provided.
