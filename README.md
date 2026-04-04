# OpenOcto 🐙

Open-source personal AI assistant constructor with voice control and persona system.

> Hold [Space] → speak → get a voice response. Fully local audio processing. Your voice never leaves the device.

## Features

- **Wake word detection** — say "Hi Octo" or "Hey Octo" to activate hands-free (powered by [openWakeWord](https://github.com/dscripka/openWakeWord))
- **Push-to-talk** voice input (hold Space)
- **Local STT** via [whisper.cpp](https://github.com/ggerganov/whisper.cpp) — auto-detects language (30+ languages supported)
- **Local TTS** via [piper-tts](https://github.com/rhasspy/piper) — natural voices in English, Spanish, French, and more
- **Pluggable AI backends** — Claude (native API), Claude Max Proxy (use your subscription), OpenAI, and any OpenAI-compatible provider
- **Persona system** — character, voice, and system prompt as a single package
- Cross-platform: macOS, Linux, Windows

## Quick Start

One command to install, configure, and download models:

**macOS / Linux:**
```bash
curl -sSL https://raw.githubusercontent.com/openocto-dev/openocto/main/install.sh | bash
```

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/openocto-dev/openocto/main/install.ps1 | iex
```

**Already cloned the repo?** Same script works locally:
```bash
./install.sh           # macOS / Linux
.\scripts\install.ps1          # Windows
```

The installer automatically detects whether you're inside the project or need to clone it, then:
1. Creates a virtual environment and installs dependencies
2. Launches the **setup wizard** — choose AI backend, enter API key, download models

After setup:
```bash
openocto start
```

> **macOS:** If prompted, grant microphone access and Accessibility permissions to your terminal app (System Settings → Privacy & Security).

## Usage

```
🐙 OpenOcto v0.1.0 | Persona: Octo | AI: claude
   Hold [Space] to speak, [Ctrl+C] to quit

You [en]: What's the capital of France?
Octo: The capital of France is Paris.

You [en]: What's the weather like in Tokyo?
Octo: I don't have access to real-time weather data, but you can check weather.com or ask me anything else.
```

### CLI Commands

```bash
openocto start                        # start assistant (auto-selects user if only one)
openocto start --user Dmitry          # start as a specific user (skips prompt)
openocto start --persona octo         # specify persona
openocto start --ai claude-proxy      # use Claude subscription (via proxy)
openocto start --ai openai            # use OpenAI
openocto setup                        # re-run the setup wizard
openocto config show                  # show resolved configuration
openocto user list                    # list all users
openocto user add "Anna"              # add a new user
openocto user add "Anna" --default    # add and set as default
openocto user delete "Anna"           # delete user and all their data
openocto user delete "Anna" -y        # delete without confirmation
openocto user default "Anna"          # set default user
openocto --version
```

#### Multi-user

If multiple users are set up, `openocto start` will prompt you to choose:

```
👤 Multiple users — who are you?
  1. Dmitry (last active)
  2. Anna

Enter number [1]:
```

To skip the prompt, pass `--user`:

```bash
openocto start --user Anna
```

Each user has their own conversation history per persona.

## Requirements

- **Python 3.10+**
- macOS (Apple Silicon or Intel), Linux, or Windows
- Microphone and speakers

### macOS (fresh install)

A clean macOS doesn't include Python or Git. Install them before running the installer:

```bash
# 1. Install Xcode Command Line Tools (includes Git)
xcode-select --install

# 2. Install Homebrew (package manager)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 3. Install Python
brew install python@3.13
```

### Linux (Debian/Ubuntu)

```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip git
```

## Configuration

OpenOcto looks for configuration in this order:
1. `config/default.yaml` (built-in defaults)
2. `~/.openocto/config.yaml` (your overrides — created by `openocto setup`)
3. Environment variables (`${ANTHROPIC_API_KEY}`, etc.)
4. CLI flags

Example `~/.openocto/config.yaml`:

```yaml
persona: "octo"

ai:
  default_backend: "claude"
  claude:
    model: "claude-opus-4-6"

stt:
  model_size: "medium"    # better accuracy on Apple Silicon M4

tts:
  models:
    en: "en_US-amy-medium"
```

### AI Backends

| Backend | Config key | API Key | Notes |
|---------|-----------|---------|-------|
| Claude (Anthropic API) | `claude` | `ANTHROPIC_API_KEY` | Native SDK, default |
| Claude Max Proxy | `claude-proxy` | Not needed | Uses Claude subscription |
| OpenAI | `openai` | `OPENAI_API_KEY` | OpenAI-compatible |
| Z.AI | `zai` | `ZAI_API_KEY` | OpenAI-compatible |

#### Claude Max Proxy (use your Claude subscription)

If you have a Claude Pro/Max subscription, you can use it instead of an API key:

```bash
# Install and start the proxy (requires Claude Code CLI to be authenticated)
npx claude-max-proxy

# In another terminal
openocto start --ai claude-proxy
```

The proxy runs at `http://localhost:3456/v1` and bridges OpenAI-format requests through your authenticated Claude session.

#### Adding custom providers

Any OpenAI-compatible provider can be added in `~/.openocto/config.yaml`:

```yaml
ai:
  default_backend: "gemini"
  providers:
    gemini:
      api_key: "${GEMINI_API_KEY}"
      model: "gemini-2.5-pro"
      base_url: "https://generativelanguage.googleapis.com/v1beta/openai"

    deepseek:
      api_key: "${DEEPSEEK_API_KEY}"
      model: "deepseek-chat"
      base_url: "https://api.deepseek.com/v1"

    ollama:
      model: "llama3:8b"
      base_url: "http://localhost:11434/v1"
      no_auth: true    # local services don't need an API key
```

### Whisper Models

| Model | Size | Speed (M2) | Accuracy |
|-------|------|------------|----------|
| `tiny` | 75MB | Very fast | Low |
| `base` | 142MB | Fast | Medium |
| `small` | 466MB | ~2s/10s audio | Good (default) |
| `medium` | 1.5GB | ~3s/10s audio | High |

## Wake Word

Enable hands-free activation in `~/.openocto/config.yaml`:

```yaml
wakeword:
  enabled: true
  model: octo_v0.1     # responds to "Hi Octo", "Hey Octo", "Ok Octo"
  threshold: 0.5       # lower = more sensitive (0.1–0.9)
```

The `octo_v0.1` model is downloaded automatically on first run from [openocto-dev/openocto-models](https://huggingface.co/openocto-dev/openocto-models).

You can also use any built-in openWakeWord model:

```yaml
wakeword:
  enabled: true
  model: alexa_v0.1    # built-in, no download needed
```

### Train your own wake word

Want a custom wake word? Use **[openocto-wakeword](https://github.com/openocto-dev/openocto-wakeword)** — a toolkit for training ONNX wake word models on **Apple Silicon (Mac M1/M2/M3/M4)**, no CUDA required.

## Personas

Personas live in the `personas/` directory. Each persona is a folder with:

```
personas/
└── octo/
    ├── persona.yaml       # name, voice config, personality
    └── system_prompt.md   # instructions for the AI
```

### Creating a Custom Persona

```yaml
# personas/mypersona/persona.yaml
name: "mypersona"
display_name: "My Persona"
description: "My custom assistant"

voice:
  engine: "piper"
  models:
    en: "en_US-amy-medium"
  length_scale: 1.0

personality:
  tone: "friendly"        # warm, professional, playful, serious
  verbosity: "balanced"   # brief, balanced, detailed
  formality: "informal"   # formal, informal, casual
```

```markdown
<!-- personas/mypersona/system_prompt.md -->
You are [Name], a helpful assistant.
Always respond in the same language the user speaks.
Keep responses concise — they will be spoken aloud.
```

```bash
openocto start --persona mypersona
```

## Testing the Microphone

```bash
openocto test mic
```

## Development

```bash
pip install -e ".[dev]"
python -m pytest tests/ -v
```

## Project Structure

```
openocto/
├── openocto/
│   ├── app.py              # Main orchestrator
│   ├── config.py           # Configuration loader (Pydantic)
│   ├── setup_wizard.py     # Interactive setup wizard
│   ├── event_bus.py        # Async pub/sub
│   ├── state_machine.py    # Pipeline state machine
│   ├── audio/              # Capture and playback
│   ├── stt/                # Speech-to-Text (whisper.cpp)
│   ├── tts/                # Text-to-Speech (piper-tts)
│   ├── vad/                # Voice Activity Detection (Silero)
│   ├── ai/                 # AI backends (Claude, OpenAI-compat)
│   ├── persona/            # Persona loader
│   └── utils/              # Model downloader, keyboard listener
├── personas/octo/          # Default persona
├── config/default.yaml     # Default configuration
├── install.sh              # macOS/Linux installer
├── install.ps1             # Windows installer
├── tests/                  # Unit tests
└── pyproject.toml
```

## Brand

"OpenOcto" name, logo, mascot, and persona character designs
are trademarks and copyrighted works of the OpenOcto project author.
All character artwork © 2026 OpenOcto Contributors. All rights reserved.
See [BRAND.md](BRAND.md) for usage guidelines.

## License

[Business Source License 1.1](LICENSE.md) — free for personal and non-commercial use. Converts to Apache 2.0 on 2030-03-30.

**Website:** [openocto.dev](https://openocto.dev)
**Maintainer:** Dmitry Rman ([@Dmitry-rman](https://github.com/Dmitry-rman))
