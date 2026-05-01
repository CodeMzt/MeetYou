## Summary

- 

## Verification

- [ ] Backend tests or focused Python checks passed.
- [ ] Frontend typecheck/tests/build passed when UI code changed.
- [ ] Real browser or Electron visual check completed when frontend behavior changed.
- [ ] Docs updated for protocol, config, startup, validation, or public behavior changes.

## V4 Boundary Checklist

- [ ] No `/client/*` or `/client/ws` runtime compatibility path added.
- [ ] No `source_client_id`, `target_client_id`, or Client-owned execution semantics added.
- [ ] Tool execution still flows through ToolRouter + ExecutionTarget.
- [ ] Scheduler remains the only system-level scheduling clock.
- [ ] Final assistant replies are persisted through MessageService.

## Privacy Checklist

- [ ] No real credentials, cookies, tokens, chat IDs, private hostnames, screenshots, or local runtime state committed.
- [ ] No personal local paths or usernames introduced in public docs, logs, or test artifacts.
