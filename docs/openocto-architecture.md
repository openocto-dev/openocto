# OpenOcto — Architecture Document

## Project Overview

**OpenOcto** — an open-source constructor for personal AI assistants with voice control. A Python core providing fully local voice processing (wake word, VAD, STT, TTS), a persona system, and integration with AI backends (OpenClaw, Claude, Ollama, and others).

**Key principles:**
- Fully local voice processing — no audio data leaves the device
- Cross-platform: macOS, Windows, Linux
- Modular architecture — every component is replaceable
- Persona system — character, voice, prompt, and avatar as a single package
- AI provider agnostic
- OpenClaw as an optional agentic backend
- Open-source (BSL 1.1 License)

**Mascot:** 🐙

**Author:** [Rocket Dev](https://rocketdev.io)

---

## High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                      OpenOcto Core (Python)                      │
│                                                                  │
│  ┌──────────────┐                                                │
│  │ Persona      │ Loads: wake word model, voice config,          │
│  │ Manager      │ system prompt, activation sounds               │
│  └──────┬───────┘                                                │
│         │ active persona                                         │
│         ▼                                                        │
│  ┌─────────────┐   ┌──────────┐   ┌──────────────────────┐      │
│  │ Audio Input  │──▶│ Wake Word│──▶│ Recording + VAD      │      │
│  │ (sounddevice)│   │(OpenWake │   │ (Silero VAD)         │      │
│  │              │   │  Word)   │   │ Stops after 3-4s     │      │
│  └─────────────┘   └──────────┘   │ silence              │      │
│                                    └──────────┬───────────┘      │
│                                               │ audio chunk      │
│                                               ▼                  │
│                                    ┌──────────────────────┐      │
│                                    │ STT (whisper.cpp)    │      │
│                                    │ Local transcription  │      │
│                                    └──────────┬───────────┘      │
│                                               │ text             │
│  ┌─────────────┐                              ▼                  │
│  │ Audio Output │◀──────────────── ┌──────────────────────┐      │
│  │ (sounddevice)│   audio stream   │ TTS Engine           │      │
│  │ speakers     │◀──────────────── │ (Piper / Silero TTS) │      │
│  └─────────────┘                   └──────────┬───────────┘      │
│                                               ▲ AI response      │
│  ┌────────────────────────────────────────────┘                  │
│  │              AI Backend Router                                │
│  │  ┌───────────┐ ┌──────────┐ ┌──────┐ ┌───────┐               │
│  │  │ OpenClaw  │ │ Claude / │ │Ollama│ │ Gonka │               │
│  │  │ Gateway   │ │ OpenAI   │ │local │ │       │               │
│  │  │ (agents)  │ │ (API)    │ │(LLM) │ │       │               │
│  │  └───────────┘ └──────────┘ └──────┘ └───────┘               │
│  └───────────────────────────────────────────────────────────────│
│                                                                  │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │  Web UI Layer                                             │   │
│  │  ┌─────────────────┐  ┌────────────────┐                 │   │
│  │  │  Setup Wizard    │  │ Dashboard      │                 │   │
│  │  │  (first run)     │  │ (monitoring)   │                 │   │
│  │  │  localhost:3000   │  │ localhost:3000  │                 │   │
│  │  └─────────────────┘  └────────────────┘                 │   │
│  └───────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │  REST API (for mobile app & external integrations)        │   │
│  │  localhost:8080                                            │   │
│  └───────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
         ▲                    ▲                    ▲
         │ WebSocket          │ REST API           │ MQTT
         │                    │                    │
   ┌─────┴──────┐    ┌───────┴────────┐   ┌──────┴───────┐
   │  Telegram   │    │ OpenOcto       │   │ Home         │
   │  Bot        │    │ Mobile App     │   │ Assistant    │
   │  (free)     │    │ (iOS/Android)  │   │              │
   └────────────┘    └────────────────┘   └──────────────┘
```

---

## Component Details

### 1. Persona Manager

The central component that loads and manages the active persona.

**Responsibilities:**
- Load persona from directory (yaml + prompt + voice + avatar)
- Switch personas on the fly (via Web UI or voice command)
- Configure wake word model for the selected persona
- Pass system prompt to AI backend
- Select TTS voice for the persona

**Implementation:**
```python
from dataclasses import dataclass
from pathlib import Path
import yaml

@dataclass
class Persona:
    name: str
    display_name: str
    description: str
    wakeword_model: str
    wakeword_threshold: float
    voice_engine: str
    voice_model: str
    voice_params: dict
    system_prompt: str
    personality: dict
    skills: list[str]
    sounds_dir: Path | None

class PersonaManager:
    def __init__(self, personas_dir: Path):
        self.personas_dir = personas_dir
        self.personas: dict[str, Persona] = {}
        self.active_persona: Persona | None = None
        self._load_all()

    def _load_all(self):
        for persona_dir in self.personas_dir.iterdir():
            if persona_dir.is_dir() and (persona_dir / "persona.yaml").exists():
                self.personas[persona_dir.name] = self._load_persona(persona_dir)

    def _load_persona(self, persona_dir: Path) -> Persona:
        config = yaml.safe_load((persona_dir / "persona.yaml").read_text())
        system_prompt = (persona_dir / "system_prompt.md").read_text()

        return Persona(
            name=config["name"],
            display_name=config["display_name"],
            description=config["description"],
            wakeword_model=config["wakeword"],
            wakeword_threshold=config.get("wakeword_threshold", 0.5),
            voice_engine=config["voice"]["engine"],
            voice_model=config["voice"]["model"],
            voice_params=config["voice"],
            system_prompt=system_prompt,
            personality=config.get("personality", {}),
            skills=config.get("skills", []),
            sounds_dir=persona_dir / "sounds" if (persona_dir / "sounds").exists() else None,
        )

    def activate(self, name: str):
        if name not in self.personas:
            raise ValueError(f"Persona '{name}' not found")
        self.active_persona = self.personas[name]
        return self.active_persona

    def list_personas(self) -> list[dict]:
        return [
            {
                "name": p.name,
                "display_name": p.display_name,
                "description": p.description,
            }
            for p in self.personas.values()
        ]
```

---

### 2. Audio Capture Layer

**Library:** `sounddevice` (PortAudio wrapper)

**Specifications:**
- Sample rate: 16000 Hz (required by OpenWakeWord and Whisper)
- Channels: 1 (mono)
- Dtype: int16
- Chunk size: 1280 samples (80ms) — optimal for OpenWakeWord

```python
import sounddevice as sd
import numpy as np

SAMPLE_RATE = 16000
CHANNELS = 1
BLOCKSIZE = 1280  # 80ms chunks

stream = sd.InputStream(
    samplerate=SAMPLE_RATE,
    channels=CHANNELS,
    dtype='int16',
    blocksize=BLOCKSIZE,
    callback=audio_callback
)
```

**Platform-specific:**
- macOS: microphone permission via system dialog
- Windows: usually works out of the box
- Linux: may require PulseAudio or PipeWire

---

### 3. Wake Word Detection

**Library:** `openwakeword` v0.6+

**Integration with Persona Manager:**
The wake word model is loaded from the active persona's configuration. Each persona can have its own model or use a shared one with a custom threshold.

```python
import openwakeword
from openwakeword.model import Model as OWWModel

class WakeWordDetector:
    def __init__(self):
        self.model: OWWModel | None = None
        self.model_name: str = ""
        self.threshold: float = 0.5
        self.cooldown: float = 2.0
        self._last_detection: float = 0

    def load_for_persona(self, persona: Persona):
        self.model_name = persona.wakeword_model
        self.threshold = persona.wakeword_threshold
        self.model = OWWModel(
            wakeword_models=[self.model_name],
            inference_framework="tflite"
        )

    def detect(self, audio_chunk: np.ndarray) -> bool:
        if self.model is None:
            return False
        prediction = self.model.predict(audio_chunk)
        score = prediction.get(self.model_name, 0)
        now = time.time()
        if score > self.threshold and (now - self._last_detection) > self.cooldown:
            self._last_detection = now
            return True
        return False
```

**Pre-installed models:**
- `hey_jarvis_v0.1` — for Octo persona (default)
- Custom models for Hestia, Metis, etc. — trained on synthetic data

---

### 4. Voice Activity Detection (VAD)

**Library:** `silero-vad` (via ONNX Runtime)

```python
class SileroVAD:
    def __init__(self, threshold=0.5, silence_duration=3.5):
        self.threshold = threshold
        self.silence_duration = silence_duration
        self.silence_start = None
        self.session = onnxruntime.InferenceSession("silero_vad.onnx")

    def is_speech(self, audio_chunk: np.ndarray) -> bool:
        audio_float = audio_chunk.astype(np.float32) / 32768.0
        result = self.session.run(None, {"input": audio_float})
        return result[0] > self.threshold

    def should_stop_recording(self, audio_chunk: np.ndarray) -> bool:
        if self.is_speech(audio_chunk):
            self.silence_start = None
            return False
        if self.silence_start is None:
            self.silence_start = time.time()
        return (time.time() - self.silence_start) >= self.silence_duration

    def reset(self):
        self.silence_start = None
```

---

### 5. Speech-to-Text (STT)

**Library:** `pywhispercpp` (Python bindings for whisper.cpp)

**Recommended models:**

| Hardware | Model | Speed (30s audio) | Accuracy |
|----------|-------|-------------------|----------|
| Mac Mini M4 | `medium` | ~2-3 sec | High |
| Mac Mini M1/M2 | `small` | ~2-3 sec | Good |
| x86 CPU (modern) | `small` | ~3-5 sec | Good |
| Low-end | `base` | ~1-2 sec | Medium |

```python
from pywhispercpp.model import Model as WhisperModel

class STTEngine:
    def __init__(self, model_size="small", language="auto", n_threads=4):
        self.model = WhisperModel(model_size, n_threads=n_threads)
        self.language = language

    def transcribe(self, audio_data: np.ndarray) -> str:
        audio_float = audio_data.astype(np.float32) / 32768.0
        segments = self.model.transcribe(
            audio_float,
            language=self.language if self.language != "auto" else None,
        )
        return " ".join([seg.text for seg in segments]).strip()
```

---

### 6. Text-to-Speech (TTS)

**Integration with Persona Manager:**
The TTS engine and voice are determined by the active persona. Each persona can use a different voice and speech speed.

**Primary:** `piper-tts`
**Alternative:** `silero-tts`

```python
class TTSEngine:
    """Factory that creates the right TTS backend for a persona."""

    @staticmethod
    def for_persona(persona: Persona):
        if persona.voice_engine == "piper":
            return PiperTTS(
                model=persona.voice_model,
                length_scale=persona.voice_params.get("length_scale", 1.0),
                sentence_silence=persona.voice_params.get("sentence_silence", 0.3),
            )
        elif persona.voice_engine == "silero":
            return SileroTTS(
                language=persona.voice_params.get("language", "ru"),
                speaker=persona.voice_params.get("speaker", "baya"),
            )
        else:
            raise ValueError(f"Unknown TTS engine: {persona.voice_engine}")
```

---

### 7. AI Backend Router

An abstraction that routes requests to the selected AI provider. Adds the system prompt from the active persona.

```python
from abc import ABC, abstractmethod

class AIBackend(ABC):
    @abstractmethod
    async def send(self, text: str, system_prompt: str) -> str: ...

    @abstractmethod
    async def send_streaming(self, text: str, system_prompt: str, on_sentence) -> None: ...

class ClaudeBackend(AIBackend):
    async def send(self, text, system_prompt):
        # Anthropic API call
        ...

class OllamaBackend(AIBackend):
    async def send(self, text, system_prompt):
        # Local Ollama API call
        ...

class OpenClawBackend(AIBackend):
    async def send(self, text, system_prompt):
        # WebSocket to OpenClaw Gateway
        ...

class AIRouter:
    def __init__(self, config):
        self.backends = {
            "claude": ClaudeBackend(config.claude),
            "openai": OpenAIBackend(config.openai),
            "ollama": OllamaBackend(config.ollama),
            "openclaw": OpenClawBackend(config.openclaw),
            "gonka": GonkaBackend(config.gonka),
        }
        self.active_backend: str = config.default_backend

    def get_backend(self) -> AIBackend:
        return self.backends[self.active_backend]

    async def send(self, text: str, persona: Persona) -> str:
        backend = self.get_backend()
        return await backend.send(text, persona.system_prompt)

    async def send_streaming(self, text: str, persona: Persona, on_sentence):
        backend = self.get_backend()
        await backend.send_streaming(text, persona.system_prompt, on_sentence)
```

---

### 8. REST API (for Mobile App & Integrations)

A FastAPI server providing an HTTP API for the mobile app and external integrations.

```python
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="OpenOcto API", version="0.1.0")

# --- Personas ---

@app.get("/api/personas")
async def list_personas():
    return persona_manager.list_personas()

@app.get("/api/personas/active")
async def get_active_persona():
    p = persona_manager.active_persona
    return {"name": p.name, "display_name": p.display_name}

@app.post("/api/personas/{name}/activate")
async def activate_persona(name: str):
    persona_manager.activate(name)
    # Reconfigure wake word, TTS, etc.
    return {"status": "ok", "active": name}

# --- Commands ---

@app.post("/api/command")
async def send_command(body: CommandRequest):
    """Send a text command to the assistant (from mobile app)."""
    response = await ai_router.send(body.text, persona_manager.active_persona)
    return {"response": response}

# --- Status ---

@app.get("/api/status")
async def get_status():
    return {
        "state": state_machine.state.value,
        "persona": persona_manager.active_persona.name,
        "backend": ai_router.active_backend,
        "uptime": get_uptime(),
    }

# --- WebSocket for real-time updates ---

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    # Stream state changes, notifications, etc.
    async for event in event_bus.subscribe():
        await ws.send_json(event)
```

---

### 9. State Machine

```
                    ┌──────────────────────┐
                    │      LISTENING       │◀──────────────────────┐
                    │  (wake word active)  │                       │
                    └──────────┬───────────┘                       │
                    wake word detected                              │
                    ┌──────────▼───────────┐                       │
                    │     RECORDING        │                       │
                    │  (VAD monitoring)    │                       │
                    └──────────┬───────────┘                       │
                    silence > threshold                            │
                    ┌──────────▼───────────┐                       │
                    │   TRANSCRIBING       │                       │
                    │  (whisper.cpp)       │                       │
                    └──────────┬───────────┘                       │
                    transcription ready                            │
                    ┌──────────▼───────────┐                       │
                    │    PROCESSING        │                       │
                    │  (AI Backend)        │                       │
                    └──────────┬───────────┘                       │
                    response received                              │
                    ┌──────────▼───────────┐                       │
                    │    SPEAKING          │───── barge-in ────────┘
                    │  (TTS playback)      │
                    └──────────┬───────────┘
                    playback complete → back to LISTENING
```

The state machine publishes events via the event bus, consumed by the Web UI and REST API (for the mobile app).

---

## Project Structure

```
openocto/
├── README.md
├── LICENSE                        # BSL 1.1
├── pyproject.toml
├── setup.py
├── config/
│   ├── default.yaml               # Default configuration
│   └── example.yaml               # Example config with comments
├── personas/                      # Persona packages
│   ├── octo/
│   │   ├── persona.yaml
│   │   ├── system_prompt.md
│   │   ├── avatar.png
│   │   └── sounds/
│   ├── hestia/
│   │   ├── persona.yaml
│   │   ├── system_prompt.md
│   │   └── avatar.png
│   ├── metis/
│   ├── nestor/
│   ├── sofia/
│   └── argus/
├── openocto/                      # Python package
│   ├── __init__.py
│   ├── __main__.py                # Entry point: python -m openocto
│   ├── config.py                  # Config loader
│   ├── state_machine.py           # Main state machine
│   ├── event_bus.py               # Event publishing for UI/API
│   ├── persona/
│   │   ├── __init__.py
│   │   └── manager.py             # Persona loading & switching
│   ├── audio/
│   │   ├── __init__.py
│   │   ├── capture.py             # Audio input
│   │   └── player.py              # Audio output + queue
│   ├── wakeword/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── openwakeword.py
│   ├── vad/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── silero.py
│   ├── stt/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── whisper_cpp.py
│   ├── tts/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── piper.py
│   │   └── silero.py
│   ├── ai/
│   │   ├── __init__.py
│   │   ├── router.py              # AI Backend Router
│   │   ├── claude.py
│   │   ├── openai.py
│   │   ├── ollama.py
│   │   ├── openclaw.py            # OpenClaw Gateway bridge
│   │   └── gonka.py
│   ├── api/
│   │   ├── __init__.py
│   │   └── server.py              # FastAPI REST API
│   ├── integrations/
│   │   ├── __init__.py
│   │   ├── telegram.py            # Telegram bot (free remote)
│   │   └── homeassistant.py       # Home Assistant bridge
│   └── utils/
│       ├── __init__.py
│       ├── sounds.py
│       └── model_downloader.py
├── web/                           # React web UI
│   ├── package.json
│   ├── src/
│   │   ├── App.tsx
│   │   ├── pages/
│   │   │   ├── SetupWizard.tsx    # First-run wizard
│   │   │   ├── Dashboard.tsx      # Status & monitoring
│   │   │   └── PersonaEditor.tsx  # Persona management
│   │   └── components/
│   │       ├── PersonaCard.tsx
│   │       ├── VoiceSelector.tsx
│   │       └── StatusIndicator.tsx
│   └── public/
│       └── personas/             # Persona avatars for web
├── mobile/                        # React Native app (Phase 3)
│   ├── package.json
│   ├── ios/
│   ├── android/
│   └── src/
│       ├── App.tsx
│       ├── screens/
│       │   ├── DashboardScreen.tsx
│       │   ├── CommandScreen.tsx
│       │   ├── PersonaScreen.tsx
│       │   └── SettingsScreen.tsx
│       └── services/
│           ├── api.ts             # REST API client
│           ├── websocket.ts       # Real-time updates
│           └── notifications.ts   # Push notifications
├── models/                        # Downloaded models (gitignored)
├── sounds/                        # Default activation sounds
├── tests/
├── scripts/
│   ├── install_models.py
│   └── test_microphone.py
├── Dockerfile
└── docs/
    ├── SETUP.md
    ├── CONFIGURATION.md
    ├── PERSONAS.md                # How to create custom personas
    ├── MOBILE_APP.md
    └── CONTRIBUTING.md
```

---

## Configuration

**`config/default.yaml`:**
```yaml
# OpenOcto Configuration

# Active persona
persona: "octo"

# Language
language: "en"

# Audio I/O
audio:
  input_device: null
  output_device: null
  sample_rate: 16000
  blocksize: 1280

# Voice Activity Detection
vad:
  engine: "silero"
  threshold: 0.5
  silence_duration: 3.5
  max_recording_duration: 60
  pre_speech_buffer: 0.3

# Speech-to-Text
stt:
  engine: "whisper.cpp"
  model_size: "small"
  language: "auto"
  n_threads: 4
  use_gpu: true

# AI Backend
ai:
  default_backend: "claude"
  claude:
    api_key: "${ANTHROPIC_API_KEY}"
    model: "claude-sonnet-4-20250514"
  openai:
    api_key: "${OPENAI_API_KEY}"
    model: "gpt-4o"
  ollama:
    base_url: "http://localhost:11434"
    model: "llama3:8b"
  openclaw:
    gateway_url: "ws://127.0.0.1:18789"
  gonka:
    base_url: "https://api.gonka.ai"
    model: "qwen3-235b"

# Web UI
web:
  enabled: true
  port: 3000

# REST API (for mobile app)
api:
  enabled: true
  port: 8080
  # Authentication for remote access
  auth:
    enabled: false
    token: "${OPENOCTO_API_TOKEN}"

# Integrations
integrations:
  telegram:
    enabled: false
    bot_token: "${TELEGRAM_BOT_TOKEN}"
    allowed_users: []
  homeassistant:
    enabled: false
    url: "http://homeassistant.local:8123"
    token: "${HASS_TOKEN}"

# Logging
logging:
  level: "INFO"
  file: null
```

---

## Dependencies

**`pyproject.toml`:**
```toml
[project]
name = "openocto"
version = "0.1.0"
description = "Open-source personal AI assistant constructor with voice control and persona system"
license = {text = "BSL-1.1"}
requires-python = ">=3.10"

dependencies = [
    "sounddevice>=0.4.6",
    "numpy>=1.24",
    "openwakeword>=0.6.0",
    "onnxruntime>=1.16",
    "pywhispercpp>=1.2.0",
    "piper-tts>=1.2.0",
    "websockets>=12.0",
    "pyyaml>=6.0",
    "click>=8.0",
    "fastapi>=0.104",
    "uvicorn>=0.24",
    "httpx>=0.25",
]

[project.optional-dependencies]
silero-tts = ["torch>=2.0", "silero-tts>=0.5"]
telegram = ["python-telegram-bot>=20.0"]
dev = ["pytest>=7.0", "pytest-asyncio>=0.21"]

[project.scripts]
openocto = "openocto.__main__:main"
```

---

## Latency Optimization

| Stage | Target | Optimization |
|-------|--------|-------------|
| Wake word | Real-time | OpenWakeWord in audio callback |
| VAD silence | 3.5s (configurable) | Balance responsiveness vs comfort |
| STT | <3s for 10s audio | `small` model on Apple Silicon |
| AI response | 1-5s | Streaming response |
| TTS | <1s per sentence | Piper real-time; sentence-level streaming |
| **Total perceived** | **~5-8s** | Stream TTS as AI responds |

---

## Mobile App Architecture

```
┌─────────────────────────────────────────┐
│         OpenOcto Mobile App             │
│         (React Native)                  │
│                                         │
│  ┌─────────────────────────────────┐    │
│  │ Screens                         │    │
│  │ ├── Dashboard (status, quick    │    │
│  │ │   actions, media control)     │    │
│  │ ├── Command (text & voice input)│    │
│  │ ├── Personas (switch, browse)   │    │
│  │ ├── Notifications (history)     │    │
│  │ └── Settings (connection, auth) │    │
│  └──────────────┬──────────────────┘    │
│                 │                        │
│  ┌──────────────▼──────────────────┐    │
│  │ Services                        │    │
│  │ ├── REST API client             │    │
│  │ │   (commands, status, config)  │    │
│  │ ├── WebSocket client            │    │
│  │ │   (real-time state updates)   │    │
│  │ └── Push notification handler   │    │
│  └──────────────┬──────────────────┘    │
│                 │                        │
│  ┌──────────────▼──────────────────┐    │
│  │ Connection Layer                │    │
│  │ ├── Local (same WiFi)           │    │
│  │ │   http://192.168.x.x:8080    │    │
│  │ ├── Tailscale (remote)          │    │
│  │ │   http://mac-mini:8080       │    │
│  │ └── WireGuard (alternative)     │    │
│  └─────────────────────────────────┘    │
└─────────────────────────────────────────┘
```

---

## Security

- **All audio data is processed locally.** Wake word, VAD, STT, TTS — nothing leaves the device.
- **The only external connection** is the API to the AI provider (text only). With Ollama — fully offline.
- **REST API is token-protected** for remote access.
- **Tailscale/WireGuard** for secure access from the mobile app.
- **No telemetry, analytics, or audio logging** by default.

---

## Roadmap

### Phase 1 — MVP
- [ ] Wake word → VAD → STT → AI → TTS pipeline
- [ ] Standalone mode (direct AI API)
- [ ] CLI interface (`openocto start`)
- [ ] Default persona (Octo)
- [ ] YAML config

### Phase 2 — Personas & Wizard
- [ ] Persona Manager
- [ ] 6 built-in personas
- [ ] Setup Wizard (React, localhost:3000)
- [ ] Web Dashboard
- [ ] REST API (FastAPI)
- [ ] OpenClaw Gateway integration

### Phase 3 — Mobile App
- [ ] React Native app
- [ ] Push notifications
- [ ] Voice commands from app
- [ ] Status dashboard
- [ ] Tailscale integration

### Phase 4 — Ecosystem
- [ ] Persona marketplace
- [ ] Community personas & skills
- [ ] Speaker ID
- [ ] Multi-room audio
- [ ] Home Assistant integration
- [ ] Kids mode
- [ ] Sound monitoring (YAMNet)

---

## Quick Start

```bash
# Install
pip install openocto

# Interactive setup (opens browser wizard)
openocto setup

# Or quick start
openocto start --persona octo --ai ollama

# Say "Hey Octo!" and ask anything
```

---

**Project:** OpenOcto 🐙
**Author:** [Rocket Dev](https://rocketdev.io)
**License:** BSL 1.1
