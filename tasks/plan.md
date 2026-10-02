# Implementation Plan: Personal OAuth Analytics Mutations

## Overview

Add a separate local stdio MCP entry point to the existing fork. It reuses the
read tool contracts with personal OAuth credentials and exposes a small,
confirmation-gated set of GA4 key-event mutations. The deployed AgentCore server
stays read-only.

## Architecture Decisions

- Keep one repository/package but use separate coordinators and console scripts.
- Use installed-application OAuth with `analytics.edit` and OS keyring storage.
- Keep mutation authorization in code: exact previews are short-lived and
  single-use, followed by a native macOS confirmation dialog.
- Expose key-event create/delete first; add other Admin API writes separately.

## Task List

### Phase 1: Authentication Foundation

- [ ] Add OAuth dependencies and credential-store implementation.
- [ ] Add authorization, status, and disconnect tools with unit tests.

### Checkpoint: Authentication

- [ ] OAuth unit tests pass without network or browser access.
- [ ] Existing read-only tests remain green.

### Phase 2: Safe Key-Event Mutations

- [ ] Add property/event validation and preview-token confirmation.
- [ ] Add list, prepare-create, create, prepare-delete, and delete tools.
- [ ] Add local audit logging with credential redaction.

### Checkpoint: Mutations

- [ ] Mutation tests cover expiry, tampering, replay, and API failures.
- [ ] Existing AgentCore and read-only coordinator behavior is unchanged.

### Phase 3: Integration

- [ ] Add the separate coordinator and console entry point.
- [ ] Document Google OAuth client, Claude Desktop, and Claude Code setup.

### Checkpoint: Complete

- [ ] Full tests and lint pass.
- [ ] Package installs and both console scripts start.
- [ ] Changes pass code and security review.

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
