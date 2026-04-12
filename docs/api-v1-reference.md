# OpenOcto JSON API v1

Public, versioned JSON API for external clients — mobile apps, scripts,
home automation. Pure JSON in, pure JSON out, Bearer-token auth.

This is **not** the same as the routes documented in
[api-reference.md](api-reference.md) — those are internal form-action
handlers backing the htmx-based web admin UI. Don't use them from a
mobile app: they return HTTP 302 redirects with flash messages in the
URL, which is great for browsers and useless for everything else.

The two surfaces share the same business logic (HistoryStore,
PersonaManager, AIRouter, SkillRegistry); only the HTTP layer is
duplicated. That separation is intentional.

---

## Base URL

```
http://<host>:8080/api/v1
```

The port matches `web.port` in the OpenOcto config (default `8080`).
Replace `<host>` with `localhost`, the Pi's LAN IP, or `openocto.local`
once mDNS is added.

---

## Authentication

Every request must include a Bearer token in the `Authorization` header:

```
Authorization: Bearer <your-token>
```

Tokens are stored in `~/.openocto/api-token` (chmod 600, generated on
first use). Get yours with:

```bash
openocto api token
```

To rotate the token (revokes the old one immediately):

```bash
openocto api token --reset
```

The API token is **separate** from the MCP token — they can be rotated
independently.

### Error response

When the token is missing or invalid:

```http
HTTP/1.1 401 Unauthorized
Content-Type: application/json

{
  "error": "unauthorized",
  "message": "Missing or invalid Bearer token"
}
```

---

## Versioning

The version is in the URL path (`/api/v1/...`). Breaking changes will
ship as `/api/v2/...` while v1 keeps responding to deployed clients.
Don't strip the `/v1` segment from your client.

---

## Error format

All error responses share the same shape:

```json
{
  "error": "<machine-readable code>",
  "message": "<human-readable explanation>"
}
```

Common codes:

| Code                  | HTTP | Meaning                                  |
|-----------------------|------|------------------------------------------|
| `unauthorized`        | 401  | Missing or invalid Bearer token          |
| `bad_request`         | 400  | Invalid input (missing field, bad type)  |
| `not_found`           | 404  | Resource doesn't exist                   |
| `service_unavailable` | 503  | A subsystem (history store, AI) is down  |
| `ai_failed`           | 502  | The AI backend raised an exception       |

---

## Status

### `GET /api/v1/status`

System and runtime info. Use this as a health check.

**Response 200:**

```json
{
  "version": "0.1.1",
  "active_user_id": 1,
  "active_persona": "octo",
  "ai_backend": "claude-proxy",
  "skills": [
    "get_current_time", "convert_units", "get_weather",
    "manage_notes_and_facts", "manage_timers",
    "file_operations", "launch_app_or_url", "media_player"
  ],
  "history_available": true
}
```

**Example:**

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8080/api/v1/status
```

---

## Users

### `GET /api/v1/users`

List all users plus the currently active id.

**Response 200:**

```json
{
  "users": [
    {"id": 1, "name": "Dmitry", "is_default": true},
    {"id": 2, "name": "Anna",   "is_default": false}
  ],
  "active_user_id": 1
}
```

### `POST /api/v1/users`

Create a new user.

**Request:**

```json
{
  "name": "Anna",
  "is_default": false
}
```

| Field        | Type    | Required | Notes                               |
|--------------|---------|----------|-------------------------------------|
| `name`       | string  | yes      | Display name, must be unique        |
| `is_default` | bool    | no       | If true, becomes the default user   |

**Response 201:**

```json
{ "id": 3, "name": "Anna" }
```

**Errors:** `400` if name is missing or already exists.

### `POST /api/v1/users/{id}/activate`

Switch the *currently active* user (the one whose history and persona
voice commands operate on). Doesn't change the default.

**Response 200:** `{"active_user_id": 2, "name": "Anna"}`

**Errors:** `404` if user doesn't exist.

### `POST /api/v1/users/{id}/default`

Set the user as the default — they'll be auto-selected on next start.

**Response 200:** `{"default_user_id": 2}`

### `DELETE /api/v1/users/{id}`

Delete a user and all their data (messages, facts, summaries).

**Response 200:** `{"deleted": true, "id": 2}`

**Errors:** `400` if you try to delete the currently active user.

---

## Personas

### `GET /api/v1/personas`

List installed personas plus the currently active one.

**Response 200:**

```json
{
  "personas": [
    {"name": "octo",   "display_name": "Octo"},
    {"name": "hestia", "display_name": "Hestia"}
  ],
  "active_persona": "octo"
}
```

### `POST /api/v1/personas/{name}/activate`

Switch the active persona. The next message and TTS will use this
persona's voice and system prompt.

**Response 200:** `{"active_persona": "hestia"}`

**Errors:** `404` if the persona name doesn't exist.

---

## Messages

### `GET /api/v1/messages`

Fetch messages for a user+persona pair.

**Query parameters:**

| Param      | Type  | Default        | Description                                |
|------------|-------|----------------|--------------------------------------------|
| `user_id`  | int   | active user    | Whose messages to fetch                    |
| `persona`  | str   | active persona | Which persona's history                    |
| `limit`    | int   | `50`           | Max number of messages to return           |
| `after_id` | int   | (none)         | Return only messages with `id > after_id` — used for incremental polling |

When `after_id` is set, the response contains only newer messages — use
this for long-poll / incremental sync from a mobile client. When omitted,
returns the most recent `limit` messages oldest-first.

**Response 200:**

```json
{
  "user_id": 1,
  "persona": "octo",
  "messages": [
    {
      "id": 99,
      "role": "user",
      "content": "What time is it?",
      "created_at": "2026-04-13 15:30:00"
    },
    {
      "id": 100,
      "role": "assistant",
      "content": "It's 15:30, Moscow time.",
      "created_at": "2026-04-13 15:30:01"
    }
  ]
}
```

### `POST /api/v1/messages`

Send a message to the assistant. The AI router will call any matching
skills (tool use) before returning. This is a fully synchronous request
— it returns when the assistant has produced its full reply.

**Request:**

```json
{
  "content": "Запусти фильм из папки Видео",
  "user_id": 1,
  "persona": "octo"
}
```

| Field     | Type   | Required | Description                            |
|-----------|--------|----------|----------------------------------------|
| `content` | string | yes      | The user's message                     |
| `user_id` | int    | no       | Defaults to active user                |
| `persona` | string | no       | Defaults to active persona             |

**Response 200:**

```json
{
  "user_msg_id": 101,
  "assistant_msg_id": 102,
  "role": "assistant",
  "content": "Запустил GOAT 2026 в полный экран. Приятного просмотра!"
}
```

**Errors:**
- `400` — empty content
- `502` — `ai_failed` if the AI backend raises
- `503` — no AI router or no history store

> **Note:** unlike the web chat endpoint, this one does **not** trigger
> TTS playback. The reply is text only. If you want voice on the
> physical device, use the voice pipeline (push-to-talk or wake word)
> on the Pi itself.

### `DELETE /api/v1/messages`

Clear chat history for a user (and optionally a specific persona).

**Query parameters:**

| Param     | Type | Notes                                      |
|-----------|------|--------------------------------------------|
| `user_id` | int  | Defaults to active user                    |
| `persona` | str  | If omitted, clears history for all personas|

**Response 200:** `{"deleted": 47}`

---

## Memory — Facts

Long-term facts about the user. Used by the assistant for context.

### `GET /api/v1/memory/facts`

**Query parameters:** `user_id` (defaults to active user).

**Response 200:**

```json
{
  "facts": [
    {"id": 1, "category": "preferences", "text": "Likes coffee in the morning"},
    {"id": 2, "category": "general",     "text": "Lives in Moscow"}
  ]
}
```

### `POST /api/v1/memory/facts`

Add a fact.

**Request:**

```json
{
  "text": "Allergic to peanuts",
  "category": "health",
  "user_id": 1
}
```

| Field      | Type   | Required | Default     |
|------------|--------|----------|-------------|
| `text`     | string | yes      |             |
| `category` | string | no       | `"general"` |
| `user_id`  | int    | no       | active user |

**Response 201:**

```json
{ "id": 42, "text": "Allergic to peanuts", "category": "health" }
```

### `DELETE /api/v1/memory/facts/{id}`

Deactivate a fact (soft delete — kept in DB but hidden from the AI
context).

**Response 200:** `{"deleted": true, "id": 42}`

---

## Memory — Notes

Short-term notes the AI can resolve when they're done (e.g. "buy milk
tomorrow").

### `GET /api/v1/memory/notes`

**Query parameters:** `user_id` (defaults to active user).

**Response 200:**

```json
{
  "notes": [
    {"id": 1, "text": "Remind to call mom"},
    {"id": 2, "text": "Buy milk on the way home"}
  ]
}
```

### `POST /api/v1/memory/notes/{id}/resolve`

Mark a note as resolved (hidden from AI context).

**Response 200:** `{"resolved": true, "id": 1}`

---

## Quick start example

```bash
# 1. Get a token (one-time)
TOKEN=$(openocto api token | grep -A1 'token:' | tail -1 | tr -d ' ')

# 2. Health check
curl -H "Authorization: Bearer $TOKEN" \
     http://localhost:8080/api/v1/status

# 3. Send a message
curl -X POST -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"content": "Какая температура процессора?"}' \
     http://localhost:8080/api/v1/messages

# 4. Poll for new messages since id 100
curl -H "Authorization: Bearer $TOKEN" \
     "http://localhost:8080/api/v1/messages?after_id=100"
```

---

## Compatibility & stability

- **v1 is a stable contract.** Field renames and removals are breaking
  changes and will only happen in v2. New optional fields may be added
  to responses without bumping the version.
- **`id` fields are stable across restarts** — they're SQLite primary
  keys, safe to persist on the client.
- **`created_at` is a SQLite text timestamp** in `YYYY-MM-DD HH:MM:SS`
  format, server local time. Treat it as opaque if you don't need to
  parse it.

---

## See also

- [api-reference.md](api-reference.md) — internal HTTP routes used by the
  web admin UI (form actions, dashboard polling, WebSocket events). Not
  for mobile clients.
- [openocto/web/routes/api_v1.py](../openocto/web/routes/api_v1.py) —
  source of truth for the JSON API. If this doc and the code disagree,
  the code wins.
