# Spec: Personal OAuth Analytics Mutations

## Objective

Add a separate local stdio MCP server for one operator to read Google Analytics
data and manage GA4 key events through Claude Desktop or Claude Code. The server
authenticates interactively as the operator with the full `analytics.edit`
scope. The existing read-only server and AgentCore deployment remain unchanged.

## Tech Stack

- Python 3.10+
- Existing Google Analytics Admin/Data API clients and MCP SDK
- Google installed-application OAuth
- OS credential storage through `keyring` (macOS Keychain on macOS)

## Commands

- Install: `python -m pip install -e '.[dev]'`
- Focused tests: `python -m unittest discover -s tests -p '*_test.py'`
- Full tests: `python -m unittest discover -s . -p '*test*.py'`
- Lint: `nox -s lint`
- Run: `analytics-mutations-mcp`

## Project Structure

- `analytics_mcp/`: existing read-only MCP implementation
- `analytics_mcp/mutations/`: personal OAuth, confirmation, mutation tools, and
  the separate stdio coordinator
- `tests/`: unit tests for both existing and mutation behavior
- `grapevine/`: unchanged AgentCore deployment

## Code Style

Use existing async tool functions with synchronous Google API calls delegated
through `asyncio.to_thread`:

```python
async def list_key_events(property_id: int | str) -> list[dict]:
    def _sync_call():
        return client.list_key_events(parent=construct_property_rn(property_id))

    return await asyncio.to_thread(_sync_call)
```

Format with Black at 80 columns and use descriptive snake_case names.

## Testing Strategy

- Unit-test OAuth token serialization and credential-store behavior without
  opening a browser or contacting Google.
- Unit-test mutation validation, preview token integrity, expiry, replay
  prevention, and Google API request construction with fakes.
- Verify the separate coordinator exposes reads and allowlisted mutations while
  the existing coordinator's tool list is unchanged.
- Perform live OAuth and GA4 mutation verification manually against a
  non-production property.

## Boundaries

- Always: Validate model-provided IDs and event names; preview exact changes;
  require a short-lived one-use confirmation token; keep structured local audit
  records; request `analytics.edit`.
- Ask first: Add mutation categories beyond key-event management or support
  multiple users.
- Never: Store tokens in source/config files, log tokens, mutate without a valid
  confirmation token, or add mutation tools to the AgentCore server.

## Success Criteria

- `analytics-mutations-mcp` starts independently from `analytics-mcp`.
- The operator can authorize, inspect auth status, and disconnect.
- OAuth refresh credentials are stored through the OS credential store.
- Existing read tools are available with the personal OAuth credential.
- Key-event create/delete operations require an exact, expiring, one-use
  confirmation token and are audited.
- Automated tests and formatting checks pass.

## Open Questions

- None for the initial single-user implementation.
