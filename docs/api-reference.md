# OpenOcto API Reference

Base URL: `http://<host>:8080` (default)

All JSON API endpoints return `Content-Type: application/json`.  
Authentication: none (local network only, no auth required).

---

## Status & Monitoring

### GET /api/status

Full system and application status. Primary endpoint for dashboards, mobile apps, and AI skills.

**Response:**
```json
{
  "timestamp": "2026-04-12T12:30:00",
  "system": {
    "hostname": "raspberrypi",
    "platform": "Linux aarch64",
    "cpu_percent": 12.3,
    "cpu_count": 4,
    "ram_total_gb": 7.9,
    "ram_used_gb": 2.4,
    "ram_percent": 30.4,
    "disk_total_gb": 58.0,
    "disk_used_gb": 28.7,
    "disk_free_gb": 26.8,
    "disk_percent": 51.7,
    "cpu_temp": 56.2
  },
  "app": {
    "pipeline_state": "idle",
    "active_user": "Dmitry",
    "active_persona": "octo",
    "ai_backend": "claude-proxy",
    "total_messages": 42,
    "user_messages": 21,
    "assistant_messages": 21,
    "total_users": 1,
    "fact_count": 5,
    "note_count": 2,
    "summary_count": 3,
    "persona_count": 1,
    "db_size_mb": 0.3,
    "models_size_mb": 150.0,
    "tts_langs": ["en", "ru"],
    "stt_engine": "whisper.cpp",
    "stt_model": "small",
    "wakeword_on": true,
    "memory_on": true,
    "daily_counts": [
      {"day": "2026-04-11", "count": 12},
      {"day": "2026-04-12", "count": 8}
    ]
  }
}
```

### GET /api/system-info

Lightweight system metrics only. Designed for frequent polling (dashboard polls every 5s).

**Response:**
```json
{
  "hostname": "raspberrypi",
  "platform": "Linux aarch64",
  "cpu_percent": 12.3,
  "cpu_count": 4,
  "ram_total_gb": 7.9,
  "ram_used_gb": 2.4,
  "ram_percent": 30.4,
  "disk_total_gb": 58.0,
  "disk_used_gb": 28.7,
  "disk_free_gb": 26.8,
  "disk_percent": 51.7,
  "cpu_temp": 56.2
}
```

---

## Chat

### POST /api/messages/send

Send a message to the AI assistant and receive a response.

**Request:**
```json
{
  "content": "What is the CPU temperature?",
  "user_id": 1,
  "persona": "octo",
  "tts": false
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| content | string | yes | User message text |
| user_id | int | no | User ID (defaults to active user) |
| persona | string | no | Persona name (defaults to active persona) |
| tts | boolean | no | Play response via TTS speaker (default: false) |

**Response:**
```json
{
  "role": "assistant",
  "content": "The CPU temperature is 56.2 degrees Celsius."
}
```

**Errors:**
- `400` — empty message or invalid JSON
- `503` — history store not available

### POST /api/messages/clear

Clear message history for the current user and persona.

**Request:** Form data with `user_id` (int), `persona` (string, optional).  
**Response:** HTTP redirect to `/messages`.

---

## Users

### POST /api/users

Create a new user.

**Request:** Form data with `name` (string, required).  
**Response:** HTTP redirect to `/users`.

### POST /api/users/{user_id}/default

Set a user as the default.

### POST /api/users/{user_id}/activate

Switch the active user for the current session.

### POST /api/users/{user_id}/delete

Delete a user and all their data (messages, facts, summaries).  
Cannot delete the currently active user.

---

## Memory

### POST /api/memory/facts

Add a fact about the user.

**Request:** Form data with `fact` (string), `category` (string, default: "personal").  
**Response:** HTTP redirect to `/memory`.

### POST /api/memory/facts/{fact_id}/delete

Delete a fact.

### POST /api/memory/notes/{note_id}/resolve

Mark a note as resolved.

---

## Personas

### POST /api/personas/{name}/activate

Switch the active persona.

### POST /api/personas/{name}/prompt

Save the system prompt for a persona.

**Request:** Form data with `content` (text).

---

## Configuration

### GET /api/config/raw

Get the raw YAML configuration file.

**Response:** Plain text YAML content.

### POST /api/config/raw

Save the raw YAML configuration file.

**Request:** Form data with `content` (YAML text).

### POST /api/config/section/{section}

Save a single configuration section.

**Sections:** `ai`, `stt`, `tts`, `vad`, `audio`, `wakeword`, `web`, `memory`, `general`.

---

## Settings

### POST /api/settings/language

Set the web UI language.

**Request:**
```json
{
  "lang": "ru"
}
```

**Values:** `"en"`, `"ru"`, `"system"` (auto-detect from browser).

---

## Calibration

### POST /api/calibration/record

Record audio from the microphone for calibration.

**Request:**
```json
{
  "duration": 3.0
}
```

**Response:**
```json
{
  "duration": 3.0,
  "chunks": [...],
  "stats": {
    "rms_mean": 120.5,
    "rms_median": 95.0,
    "rms_p95": 450.0,
    "rms_p99": 600.0,
    "rms_max": 800.0,
    "prob_mean": 0.05,
    "prob_max": 0.12
  }
}
```

### POST /api/calibration/analyze

Get recommended VAD thresholds from silence and speech recordings.

**Request:**
```json
{
  "silence": {"rms_mean": 50, "rms_p95": 120, "prob_max": 0.1},
  "speech": {"rms_mean": 400, "rms_p95": 800, "prob_max": 0.95}
}
```

### POST /api/calibration/save

Save calibrated VAD settings to config.

**Request:**
```json
{
  "rms_speech_threshold": 300,
  "threshold": 0.3,
  "silence_duration": 3.5
}
```

---

## Setup Wizard

### GET /api/wizard/ollama-models

List installed Ollama models.

**Response:**
```json
{
  "installed": true,
  "models": ["qwen3:4b", "llama3.2"]
}
```

### POST /api/wizard/save

Save the initial setup configuration.

**Request:**
```json
{
  "user_name": "Dmitry",
  "backend": "claude-proxy",
  "api_key": "",
  "ollama_model": "",
  "model_size": "small",
  "voice_en": "en_US-lessac-high",
  "voice_ru": "xenia",
  "primary_lang": "auto",
  "wakeword_enabled": true,
  "wakeword_model": "octo_v0.1",
  "calibration": null
}
```

---

## WebSocket

### WS /ws

Real-time pipeline state updates.

**Connection:** `ws://<host>:8080/ws`

**Initial message (server → client):**
```json
{"type": "state", "data": {"state": "idle"}}
```

**Event messages (server → client):**
```json
{"type": "state.changed", "data": {"from": "idle", "to": "recording", "trigger": "wakeword"}}
{"type": "stt.result", "data": {"text": "What time is it?", "language": "en"}}
{"type": "ai.chunk", "data": {"text": "It's"}}
{"type": "ai.response", "data": {"text": "It's 3 PM."}}
{"type": "tts.started", "data": {}}
{"type": "tts.finished", "data": {}}
{"type": "error", "data": {"message": "STT failed"}}
```

**Pipeline states:** `idle`, `recording`, `transcribing`, `processing`, `speaking`, `disconnected`.

**Keep-alive:** Server sends ping every 30 seconds.

---

## Legal

### GET /api/legal/terms-accepted

Check if terms of service have been accepted.

**Response:** `{"accepted": true}`

### POST /api/legal/accept-terms

Accept terms of service (sets a cookie valid for 1 year).

---

## Notes

- All endpoints are unauthenticated — designed for local network use only.
- Form data endpoints (POST with redirects) are used by the htmx-based web UI.
- JSON endpoints (POST/GET returning JSON) are for programmatic access (mobile app, scripts).
- The `/api/status` endpoint is the recommended single source of truth for system state.
- WebSocket at `/ws` provides real-time updates without polling.
