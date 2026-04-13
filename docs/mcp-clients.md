# External MCP Servers — User Guide

OpenOcto can connect to any [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server and expose its tools as AI skills — without writing any skill code.

This turns OpenOcto into a **voice/chat front-end for your entire MCP ecosystem**: Notion, GitHub, Home Assistant, Linear, or any custom MCP server.

---

## How it works

OpenOcto already *serves* its built-in skills as an MCP server on port 8765 (so Claude CLI and other clients can call them). This feature adds the inverse: OpenOcto becomes an **MCP client** that connects to external servers.

When a server is connected:

1. OpenOcto calls `tools/list` and discovers its tool definitions.
2. Each tool is wrapped in an `MCPRemoteToolSkill` and registered in the shared `SkillRegistry`.
3. The AI router sees external tools alongside built-in skills — no difference from the LLM's perspective.
4. When the LLM calls an external tool, OpenOcto forwards the request to the remote MCP server via `tools/call`.

Tool names are prefixed with the server name to avoid collisions:
- Server `notion`, tool `create_page` → skill name `notion__create_page`

---

## Adding a server via web UI

1. Open the web admin: `http://localhost:8080/mcp`
2. Click **"Add Server"**
3. Fill in:
   - **Name** — unique identifier (e.g. `notion`). Used as tool prefix.
   - **URL** — the MCP server's HTTP endpoint (e.g. `https://mcp.notion.com/mcp`).
   - **Headers** — one per line: `Authorization: Bearer your-token-here`
   - **Tool allow-list** — leave blank to expose all tools; or list specific tool names (one per line).
4. Click **"Add server"**
5. Use **"Test"** to verify the connection before relying on it.

---

## Adding a server via CLI

```bash
# Add Notion MCP
openocto mcp-client add notion https://mcp.notion.com/mcp \
  --header "Authorization=Bearer ntn_xxxxxxxx"

# Add Home Assistant MCP (local)
openocto mcp-client add homeassistant http://192.168.1.10:8123/mcp \
  --header "Authorization=Bearer long_lived_access_token" \
  --allowlist "turn_light_on,turn_light_off,get_entity_state"

# Add GitHub MCP with specific tools only
openocto mcp-client add github https://api.githubcopilot.com/mcp/ \
  --header "Authorization=Bearer ghp_xxxxxxxx" \
  --allowlist "create_issue,list_issues,search_repositories"

# Add a local MCP server (no auth)
openocto mcp-client add myserver http://localhost:9999/mcp

# List all configured servers
openocto mcp-client list

# Test a connection
openocto mcp-client test notion

# Remove a server
openocto mcp-client remove notion
```

---

## Managing servers

### List

```bash
openocto mcp-client list
```

Output:
```
  [1] ✓ notion               https://mcp.notion.com/mcp (connected)
  [2] ✓ homeassistant        http://192.168.1.10:8123/mcp (connected)
  [3] ✗ github               https://api.githubcopilot.com/mcp/ (error)
```

### Test connection

```bash
openocto mcp-client test notion
# Connecting to https://mcp.notion.com/mcp ...
# ✓ Connected. 12 tool(s):
#   create_page                             Create a new Notion page
#   search_database                         Search a Notion database
#   ...
```

### Remove

```bash
openocto mcp-client remove notion
# Prompts for confirmation, then removes server and stored secrets
openocto mcp-client remove notion --yes  # skip confirmation
```

---

## Tool naming

External tools are prefixed `<server_name>__<tool_name>`:

| Server | Remote tool | Skill name in OpenOcto |
|--------|-------------|------------------------|
| `notion` | `create_page` | `notion__create_page` |
| `github` | `create_issue` | `github__create_issue` |
| `homeassistant` | `turn_light_on` | `homeassistant__turn_light_on` |

Names are sanitized: only `[a-z0-9_]`, max 64 characters (Anthropic tool name limit).

---

## Tool allow-list

If you don't want all tools from a server exposed to the AI (for security or noise reduction), specify an allow-list:

**Via web UI:** Enter one tool name per line in the "Tool allow-list" field.

**Via CLI:**
```bash
openocto mcp-client add ha http://192.168.1.10:8123/mcp \
  --allowlist "turn_light_on,turn_light_off"
```

Leave empty to allow all tools.

---

## Transport support

Currently only **HTTP transport** (Streamable HTTP, MCP 2024-11-05 spec) is supported.

If a server responds with SSE (`text/event-stream`) instead of JSON, you'll see:
```
Error: server returned SSE (text/event-stream). SSE responses are not supported.
```

SSE and stdio transports are planned for a future release.

---

## Security

### Bearer token storage

Headers (including `Authorization: Bearer ...` tokens) are stored in:

```
~/.openocto/mcp-secrets.yaml  (chmod 600)
```

The file is readable only by the owner. Do **not** commit it to git.

Server metadata (name, URL, transport, allow-list) is stored in:

```
~/.openocto/history.db  (chmod 600)
```

### What external tools can access

External MCP tool calls receive only the arguments the LLM sends. They do **not** automatically receive:
- User IDs or conversation history
- Tokens from other servers
- File system access beyond what the tool itself implements

The tool author controls what their server can do.

---

## Examples by server

### Notion

1. Create a Notion integration at https://www.notion.so/my-integrations
2. Get the internal integration token
3. Find your MCP endpoint (varies by Notion MCP implementation)

```bash
openocto mcp-client add notion https://mcp.notion.com/mcp \
  --header "Authorization=Bearer ntn_xxxxxxxxxx"
```

Voice: *"Окто, создай страницу в Notion с планом на неделю"*

### GitHub

Using Anthropic's reference MCP server for GitHub:

```bash
openocto mcp-client add github https://api.githubcopilot.com/mcp/ \
  --header "Authorization=Bearer ghp_your_personal_access_token"
```

Voice: *"Окто, создай issue в репозитории openocto-dev/openocto с заголовком 'Bug: ...' "*

### Home Assistant

With Home Assistant's built-in MCP support (HA 2024.11+):

```bash
openocto mcp-client add homeassistant \
  http://192.168.1.10:8123/api/mcp \
  --header "Authorization=Bearer <long-lived-access-token>"
```

Voice: *"Окто, включи свет в кухне"*

---

## Troubleshooting

**Server shows "error" status:**
- Check the URL — must be reachable from the Pi
- Verify the bearer token
- Run `openocto mcp-client test <name>` to see the exact error
- Check the server supports JSON responses (not SSE-only)

**Tools not appearing in AI responses:**
- The server must be `connected` (green badge in web UI)
- Run `openocto mcp-client test <name>` to confirm tools are listed
- Restart the web server or re-run `openocto start` after adding a new server

**"SSE responses not supported" error:**
- The remote server uses Server-Sent Events transport
- SSE support is planned but not yet implemented
- Check if the server has a JSON-mode option (some support both)

**Slow tool calls:**
- Increase `mcp_client.connect_timeout` in your config:
  ```yaml
  mcp_client:
    connect_timeout: 30.0
  ```

---

## Configuration reference

In `~/.openocto/config.yaml`:

```yaml
mcp_client:
  enabled: true        # set false to disable all external MCP connections
  connect_timeout: 10.0  # seconds per server connect attempt
```
