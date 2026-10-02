# Personal OAuth Analytics Mutations

## Task 1: OAuth credential lifecycle

**Acceptance criteria:**
- [ ] OAuth requests the full `analytics.edit` scope.
- [ ] Refresh credentials are stored through the OS keyring.
- [ ] Status and disconnect do not expose secret material.

**Verification:**
- [ ] Focused credential tests pass.

**Dependencies:** None

**Files likely touched:** `pyproject.toml`, `analytics_mcp/mutations/auth.py`,
`tests/mutation_auth_test.py`

**Estimated scope:** Medium

## Task 2: Confirmation-gated key-event tools

**Acceptance criteria:**
- [ ] Inputs are validated and previews bind exact mutation arguments.
- [ ] Confirmation tokens expire and cannot be replayed or tampered with.
- [ ] Create/delete key-event operations produce sanitized audit records.

**Verification:**
- [ ] Focused mutation-tool tests pass.

**Dependencies:** Task 1

**Files likely touched:** `analytics_mcp/mutations/confirmation.py`,
`analytics_mcp/mutations/tools.py`, `tests/mutation_tools_test.py`

**Estimated scope:** Medium

## Checkpoint: Core behavior

- [ ] Existing tests pass.
- [ ] Mutation tests pass.

## Task 3: Separate MCP entry point

**Acceptance criteria:**
- [ ] New executable exposes personal read and allowlisted mutation tools.
- [ ] Existing read-only and AgentCore coordinators are unchanged.

**Verification:**
- [ ] Coordinator contract tests pass.
- [ ] Both console scripts start after editable install.

**Dependencies:** Tasks 1-2

**Files likely touched:** `analytics_mcp/mutations/coordinator.py`,
`analytics_mcp/mutations/server.py`, `pyproject.toml`

**Estimated scope:** Medium

## Task 4: Operator documentation

**Acceptance criteria:**
- [ ] OAuth client setup and authorization are documented.
- [ ] Claude Desktop and Claude Code configurations are documented.
- [ ] Security and non-production verification guidance is explicit.

**Verification:**
- [ ] Commands and JSON examples match the implemented entry point.

**Dependencies:** Task 3

**Files likely touched:** `README.md`

**Estimated scope:** Small

## Checkpoint: Complete

- [ ] Full tests pass.
- [ ] Black formatting check passes.
- [ ] Diff and security review are complete.
