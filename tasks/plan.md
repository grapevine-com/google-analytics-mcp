# Implementation Plan: Personal OAuth Analytics Mutations

## Overview

Add a separate local stdio MCP entry point to the existing fork. It reuses the
read tool contracts with personal OAuth credentials and exposes a small,
confirmation-gated set of GA4 key-event mutations. The deployed AgentCore server
stays read-only.

## Architecture Decisions

- Keep one repository/package but use separate coordinators and console scripts.
- Use installed-application OAuth with `analytics.edit`, `analytics.readonly`,
  and OS keyring storage.
- Keep mutation authorization in code: exact previews are short-lived and
  single-use, followed by a native macOS confirmation dialog.
- Expose key-event create/delete first; add other Admin API writes separately.

## Task List

### Phase 1: Authentication Foundation

- [x] Add OAuth dependencies and credential-store implementation.
- [x] Add authorization, status, and disconnect tools with unit tests.

### Checkpoint: Authentication

- [x] OAuth unit tests pass without network or browser access.
- [x] Existing read-only tests remain green.

### Phase 2: Safe Key-Event Mutations

- [x] Add property/event validation and preview-token confirmation.
- [x] Add list, prepare-create, apply, and prepare-delete tools.
- [x] Add local audit logging with credential redaction.

### Checkpoint: Mutations

- [x] Mutation tests cover expiry, replay, cancellation, and audit failures.
- [x] Existing AgentCore and read-only coordinator behavior is unchanged.

### Phase 3: Integration

- [x] Add the separate coordinator and console entry point.
- [x] Document Google OAuth client, Claude Desktop, and Claude Code setup.

### Checkpoint: Complete

- [x] Full tests and lint pass (26 package tests plus 14 deployment tests).
- [x] Package installs and personal stdio protocol handshake passes.
- [x] Code and security review findings addressed with regression tests.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| LLM invokes unintended write | High | Exact preview plus one-use confirmation token |
| Refresh token disclosure | High | OS keyring only; never log credential material |
| Wrong GA4 property | High | Show property in preview and bind it into confirmation |
| OAuth scope is broader than tools | Medium | Allowlisted tool registry in a separate process |
| Duplicate write after retry | Medium | Consume confirmation before the API mutation |

## Open Questions

- Live verification requires the operator's OAuth client JSON and a
  non-production GA4 property; automated tests use fakes.

## Extension: Journey event-rule CRUD

1. Validate nested rule payloads/resource names, snapshot previews, and test
   create/update/delete request construction for both rule families.
2. Reuse the confirmed mutation lifecycle with explicit personal alpha clients
   and redacted event-rule audits. Add key-event counting-method updates.
3. Register all tools, document rule schemas/examples, verify with fake CRUD,
   real stdio schema validation, and read-only live discovery.
4. Review and commit/push to the existing personal-server PR.

No new dependencies or OAuth scopes. Existing tasks are complete; extension
tasks are tracked below in `tasks/todo.md`.

Extension completed: 45 tests pass, real stdio lists 27 tools, lint/dependency
checks pass, code review approved, and live read-only event-rule discovery
verified on both accessible properties.
