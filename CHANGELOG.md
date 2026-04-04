# Changelog

All notable changes to this project will be documented in this file.

## [0.1.1] — 2026-04-04

### Added
- **Wake word "Hi Octo"** — custom ONNX model trained with openWakeWord, auto-downloads from HuggingFace (`octo_v0.1`)
- **5-layer persistent memory** — summaries, conversation notes, user facts, semantic search (FTS5 + optional sqlite-vec)
- **Multi-user support** — user selection on start, `--user` flag, auto-select when only one user
- **CLI user management** — `openocto user list/add/delete/default`
- **Quick setup mode** — wizard with recommended defaults for fast onboarding
- **AI health check** — backend connectivity check at startup with friendly error messages
- **Windows ARM64 support** — prebuilt wheels for pywhispercpp, piper-phonemize, piper-tts on ARM64
- **Audio device by name** — config accepts device name substring instead of fragile numeric index
- **Wake word section in README** — configuration examples, link to openocto-wakeword training repo

### Fixed
- Questionary async conflict — `ask_async()` inside event loop
- Audio device fallback — graceful fallback to system default if configured device fails
- Wizard saves device names instead of indices
- `mic_gain` applied in audio callback before VAD and recording buffer
- Windows: `install.ps1` UTF-8 BOM, self-download, pip error handling
- Windows ARM64: proxy spawns `node.exe` directly (bypasses `cmd.exe` cp866 encoding)
- Windows ARM64: Silero VAD raw RMS fallback (ONNX produces near-zero probs on ARM64)
- Windows: mic calibration resolves default input device index correctly
- Wake word error cooldown to prevent re-triggering after AI failures

### Changed
- AI router signature: `send()` accepts `system_prompt: str` instead of `Persona` object
- Default AI backend changed to `claude-proxy` (no API key needed)
- Setup wizard uses `questionary.select` with arrow keys instead of `click.prompt` number input

## [0.1.0] — 2026-03-31

### Added
- **Complete voice pipeline** — Wake word → VAD → STT → AI → TTS → playback
- **Wake word detection** — OpenWakeWord integration (opt-in, `wakeword.enabled: true`)
- **VAD** — Silero VAD (ONNX), auto-gain with noise floor, mic calibration in wizard
- **STT** — whisper.cpp via pywhispercpp, hallucination filter (silence patterns, subtitles)
- **TTS** — Piper TTS (English) + Silero TTS (Russian), auto-detect language by Cyrillic ratio
- **AI Router** — Claude (Anthropic SDK), OpenAI-compatible (Ollama, OpenAI, any provider), fallback chain
- **Persona system** — YAML-based personas with voice config and system prompt
- **Push-to-talk** — hold Space to speak
- **Auto-listen** — short listen window after TTS response without wake word
- **Setup wizard** — 7-step interactive CLI: AI backend, Whisper model, TTS voices, audio devices, mic calibration, wake word
- **Installer scripts** — `install.sh` (macOS/Linux), `install.ps1` (Windows)
- **Persistent dialog history** — SQLite (`~/.openocto/history.db`), WAL mode, per-user per-persona
- **Configuration** — `config/default.yaml` + `~/.openocto/config.yaml` deep merge, env vars, CLI flags
- **Model downloader** — auto-download Whisper, Piper, Silero VAD, wake word models from HuggingFace
- Published to PyPI as `openocto-dev`
