# Personal OAuth Analytics Mutations

## Task 1: OAuth credential lifecycle

**Acceptance criteria:**
- [x] OAuth requests `analytics.edit` plus `analytics.readonly` for reports.
- [x] Refresh credentials are stored through the OS keyring.
- [x] Status and disconnect do not expose secret material.

**Verification:**
- [x] Focused credential tests pass.

**Dependencies:** None

**Files likely touched:** `pyproject.toml`, `analytics_mcp/mutations/auth.py`,
`tests/mutation_auth_test.py`

**Estimated scope:** Medium

## Task 2: Confirmation-gated key-event tools

**Acceptance criteria:**
- [x] Inputs are validated and previews bind exact mutation arguments.
- [x] Preview IDs expire and cannot be replayed or alter stored arguments.
- [x] Create/delete key-event operations produce sanitized audit records.

**Verification:**
- [x] Focused mutation-tool tests pass.

**Dependencies:** Task 1

**Files likely touched:** `analytics_mcp/mutations/confirmation.py`,
`analytics_mcp/mutations/tools.py`, `tests/mutation_tools_test.py`

**Estimated scope:** Medium

## Checkpoint: Core behavior

- [x] Existing tests pass.
- [x] Mutation tests pass.

## Task 3: Separate MCP entry point

**Acceptance criteria:**
- [x] New executable exposes personal read and allowlisted mutation tools.
- [x] Existing read-only and AgentCore coordinators are unchanged.

**Verification:**
- [x] Coordinator contract tests pass.
- [x] Personal console entry point installs and real stdio handshake passes.

**Dependencies:** Tasks 1-2

**Files likely touched:** `analytics_mcp/mutations/coordinator.py`,
`analytics_mcp/mutations/server.py`, `pyproject.toml`

**Estimated scope:** Medium

## Task 4: Operator documentation

**Acceptance criteria:**
- [x] OAuth client setup and authorization are documented.
- [x] Claude Desktop and Claude Code configurations are documented.
- [x] Security and non-production verification guidance is explicit.

**Verification:**
- [x] Commands and JSON examples match the implemented entry point.

**Dependencies:** Task 3

**Files likely touched:** `README.md`

**Estimated scope:** Small

## Checkpoint: Complete

- [x] Full tests pass: 26 package tests plus 14 deployment tests.
- [x] Black formatting check and `nox -s lint` pass.
- [x] Diff and security review findings addressed.

Live OAuth/GA4 verification requires the operator's Desktop OAuth client JSON
and a test property. GitHub issues are disabled in this fork; the PR contains
the specification and plan links.
