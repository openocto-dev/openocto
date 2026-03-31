"""Interactive setup wizard for first-time OpenOcto configuration."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import click
import yaml

from openocto.config import USER_CONFIG_DIR, USER_CONFIG_PATH, MODELS_DIR


# Available TTS voices for the wizard
TTS_VOICES_EN = [
    ("en_US-lessac-high",      "Lessac (female, US, high quality) ~109 MB  ⭐ recommended"),
    ("en_US-ryan-high",        "Ryan (male, US, high quality) ~115 MB"),
    ("en_GB-cori-high",        "Cori (female, GB, high quality) ~109 MB"),
    ("en_US-ljspeech-high",    "LJSpeech (female, US, high quality) ~109 MB"),
    ("en_US-hfc_female-medium","HFC Female (US, medium) ~60 MB"),
    ("en_US-hfc_male-medium",  "HFC Male (US, medium) ~60 MB"),
    ("en_GB-jenny_dioco-medium","Jenny (female, GB, medium) ~60 MB"),
    ("en_US-amy-medium",       "Amy (female, US, medium) ~60 MB  — current default"),
]

WAKE_WORD_OPTIONS = [
    ("hey_octo_v0.1",    "Hey Octo!       ⭐ recommended"),
    ("hey_jarvis_v0.1",  "Hey Jarvis      (built-in)"),
    ("alexa_v0.1",       "Alexa           (built-in)"),
    ("hey_mycroft_v0.1", "Hey Mycroft     (built-in)"),
]

SILERO_SPEAKERS_RU = [
    ("xenia",   "Xenia    (female)  ⭐ recommended"),
    ("baya",    "Baya     (female)"),
    ("kseniya", "Kseniya  (female)"),
    ("eugene",  "Eugene   (male)"),
]

# Available AI backends for the wizard
AI_BACKENDS = [
    ("claude", "Claude API (requires ANTHROPIC_API_KEY)"),
    ("claude-proxy", "Claude via subscription (local proxy, no API key)"),
    ("openai", "OpenAI (requires OPENAI_API_KEY)"),
]

# Env var names for each backend
BACKEND_ENV_KEYS: dict[str, str] = {
    "claude": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def run_setup(from_step: int = 1) -> None:
    """Run the interactive setup wizard, optionally starting from a specific step."""
    click.echo()
    click.secho("🐙 Welcome to OpenOcto!", fg="cyan", bold=True)
    click.secho("   Your personal AI voice assistant.\n", fg="cyan")

    if from_step > 1:
        click.secho(f"   ⏩ Starting from step {from_step}/7\n", fg="yellow")

    # Load existing config values as defaults for skipped steps
    existing = _load_existing_config()

    # Step 1: AI backend
    if from_step <= 1:
        backend, api_key = _step_ai_backend()
    else:
        backend = existing.get("ai", {}).get("default_backend", "claude")
        api_key = ""
        click.secho(f"  ⏩ [1/7] AI: {backend}", fg="yellow")

    # Step 2: Whisper model size
    if from_step <= 2:
        model_size = _step_whisper_model()
    else:
        model_size = existing.get("stt", {}).get("model_size", "small")
        click.secho(f"  ⏩ [2/7] STT: whisper-{model_size}", fg="yellow")

    # Step 3: TTS voices
    if from_step <= 3:
        voice_en, voice_ru, primary_lang = _step_tts_voices()
    else:
        primary_lang = existing.get("language", "en")
        tts = existing.get("tts", {})
        voice_en = tts.get("models", {}).get("en", TTS_VOICES_EN[0][0])
        voice_ru = tts.get("models", {}).get("ru", SILERO_SPEAKERS_RU[0][0])
        click.secho(f"  ⏩ [3/7] Voice: lang={primary_lang}, en={voice_en}, ru={voice_ru}", fg="yellow")  # noqa: E501

    # Step 4: Audio devices
    if from_step <= 4:
        input_device, output_device = _step_audio_devices()
    else:
        audio = existing.get("audio", {})
        input_device = audio.get("input_device")
        output_device = audio.get("output_device")
        click.secho(f"  ⏩ [4/7] Audio: in={input_device}, out={output_device}", fg="yellow")

    # Step 5: Microphone calibration
    if from_step <= 5:
        mic_gain = _step_mic_calibration(input_device)
    else:
        mic_gain = existing.get("vad", {}).get("mic_gain")
        click.secho(f"  ⏩ [5/7] Mic gain: {mic_gain or 'auto'}", fg="yellow")

    # Step 6: Wake word
    if from_step <= 6:
        wakeword_enabled, wakeword_model = _step_wakeword()
    else:
        ww = existing.get("wakeword", {})
        wakeword_enabled = ww.get("enabled", False)
        wakeword_model = ww.get("model", "")
        click.secho(f"  ⏩ [6/7] Wake word: enabled={wakeword_enabled}, model={wakeword_model}", fg="yellow")

    click.echo()

    # Step 7: Write config
    _write_config(backend, api_key, model_size, voice_en, voice_ru, primary_lang,
                  input_device, output_device, wakeword_enabled, wakeword_model, mic_gain)

    # Download models
    _step_download_models(model_size, voice_en, voice_ru, primary_lang,
                          wakeword_enabled, wakeword_model)

    # Done
    click.echo()
    click.secho("🎉 Setup complete!", fg="green", bold=True)
    click.echo()

    click.echo("  To start later, run:")
    click.secho("    openocto start", fg="yellow")
    click.echo()

    if click.confirm("  Launch OpenOcto now?", default=True):
        click.echo()
        import asyncio
        from openocto.config import load_config
        from openocto.app import OpenOctoApp

        config = load_config()
        app = OpenOctoApp(config)
        asyncio.run(app.run())


def _load_existing_config() -> dict:
    """Load current user config as a plain dict (for use as defaults in skipped steps)."""
    if USER_CONFIG_PATH.exists():
        with open(USER_CONFIG_PATH) as f:
            return yaml.safe_load(f) or {}
    return {}


def _step_ai_backend() -> tuple[str, str]:
    """Step 1: Choose AI backend and optionally enter API key."""
    click.secho("🤖 [1/7] AI Brain", bold=True)
    click.echo()

    for i, (key, desc) in enumerate(AI_BACKENDS, 1):
        click.echo(f"  {i}. {desc}")
    click.echo(f"  {len(AI_BACKENDS) + 1}. ⏭  Skip (configure later)")
    click.echo()

    choice = click.prompt(
        "  Choose",
        type=click.IntRange(1, len(AI_BACKENDS) + 1),
        default=1,
    )

    if choice > len(AI_BACKENDS):
        click.secho("  ⏭  Skipped. Configure later in ~/.openocto/config.yaml\n", fg="yellow")
        return "claude", ""

    backend, _ = AI_BACKENDS[choice - 1]
    api_key = ""

    env_var = BACKEND_ENV_KEYS.get(backend)
    if env_var:
        existing = os.environ.get(env_var, "")
        if existing:
            click.secho(f"  ✅ {env_var} already set in environment", fg="green")
            api_key = existing
        else:
            api_key = click.prompt(
                f"  🔑 Enter your API key ({env_var})",
                default="",
                show_default=False,
                hide_input=True,
            )
            if not api_key:
                click.secho(f"  ⚠️  Skipped. Set {env_var} before running.\n", fg="yellow")
    elif backend == "claude-proxy":
        click.secho("  ✅ No API key needed — uses your Claude subscription via local proxy.", fg="green")

    click.echo()
    return backend, api_key


def _step_tts_voices() -> tuple[str, str, str]:
    """Step 3: Choose language and TTS voices. Returns (voice_en, voice_ru, primary_lang)."""
    click.secho("🗣️  [3/7] Voice & Language", bold=True)
    click.echo()

    # Detect system locale for smart default
    import locale
    sys_locale = (locale.getdefaultlocale()[0] or "en").lower()
    if sys_locale.startswith("ru"):
        default_lang = 2
    else:
        default_lang = 1

    click.echo("  🌍 Primary language:")
    click.echo("    1. 🇺🇸  English")
    click.echo("    2. 🇷🇺  Russian")
    click.echo("    3. 🌐  Both (bilingual — auto-detect)")
    click.echo()
    lang_choice = click.prompt("  Choose", type=click.IntRange(1, 3), default=default_lang)
    click.echo()

    primary_lang = {1: "en", 2: "ru", 3: "auto"}[lang_choice]

    # Defaults
    voice_en = TTS_VOICES_EN[0][0]
    voice_ru = SILERO_SPEAKERS_RU[0][0]

    if lang_choice in (1, 3):
        click.echo("  🔊 English voice:")
        for i, (key, desc) in enumerate(TTS_VOICES_EN, 1):
            click.echo(f"    {i}. {desc}")
        click.echo()
        choice = click.prompt("  Choose", type=click.IntRange(1, len(TTS_VOICES_EN)), default=1)
        voice_en = TTS_VOICES_EN[choice - 1][0]
        click.echo()

    if lang_choice in (2, 3):
        click.echo("  🔊 Russian voice (Silero TTS):")
        for i, (key, desc) in enumerate(SILERO_SPEAKERS_RU, 1):
            click.echo(f"    {i}. {desc}")
        click.echo()
        choice = click.prompt("  Choose", type=click.IntRange(1, len(SILERO_SPEAKERS_RU)), default=1)
        voice_ru = SILERO_SPEAKERS_RU[choice - 1][0]
        click.echo()

    return voice_en, voice_ru, primary_lang


def _step_audio_devices() -> tuple[int | None, int | None]:
    """Step 4: Choose microphone and output device."""
    click.secho("🔊 [4/7] Audio Devices", bold=True)
    click.echo()

    import sounddevice as sd

    devices = sd.query_devices()
    inputs = [(i, d) for i, d in enumerate(devices) if d["max_input_channels"] > 0]
    outputs = [(i, d) for i, d in enumerate(devices) if d["max_output_channels"] > 0]

    default_in = sd.default.device[0]
    default_out = sd.default.device[1]

    def _device_label(idx, d) -> str:
        tag = ""
        if idx == default_in and idx == default_out:
            tag = " [default in+out]"
        elif idx == default_in:
            tag = " [default input]"
        elif idx == default_out:
            tag = " [default output]"
        return f"{d['name']}{tag}"

    # --- Microphone ---
    click.echo("  🎤 Microphone (input):")
    click.echo(f"    0. System default")
    for n, (i, d) in enumerate(inputs, 1):
        click.echo(f"    {n}. {_device_label(i, d)}")
    click.echo()

    mic_choice = click.prompt("  Choose microphone", type=click.IntRange(0, len(inputs)), default=0)
    input_device = None if mic_choice == 0 else inputs[mic_choice - 1][0]
    if input_device is not None:
        click.secho(f"  ✅ Microphone: {inputs[mic_choice - 1][1]['name']}", fg="green")
    else:
        click.secho("  ✅ Microphone: system default", fg="green")
    click.echo()

    # --- Speaker ---
    click.echo("  🔈 Speaker (output):")
    click.echo(f"    0. System default")
    for n, (i, d) in enumerate(outputs, 1):
        click.echo(f"    {n}. {_device_label(i, d)}")
    click.echo()

    spk_choice = click.prompt("  Choose speaker", type=click.IntRange(0, len(outputs)), default=0)
    output_device = None if spk_choice == 0 else outputs[spk_choice - 1][0]
    if output_device is not None:
        click.secho(f"  ✅ Speaker: {outputs[spk_choice - 1][1]['name']}", fg="green")
    else:
        click.secho("  ✅ Speaker: system default", fg="green")
    click.echo()

    if input_device is not None or output_device is not None:
        click.secho(
            "  💡 Tip: if using a Bluetooth speaker for output — choose the\n"
            "     built-in microphone for input to preserve A2DP audio quality.",
            fg="cyan",
        )
        click.echo()

    return input_device, output_device


def _step_mic_calibration(input_device: int | None) -> float | None:
    """Step 5: Calibrate microphone gain by recording a test phrase."""
    click.secho("🔬 [5/7] Microphone Calibration", bold=True)
    click.echo()
    click.echo("  Calibrates microphone gain for accurate voice recognition.")
    click.echo("  Say any phrase in your normal voice when prompted.")
    click.echo()

    if not click.confirm("  Start calibration?", default=True):
        click.secho("  ⏭  Skipped. Auto-gain will be used.\n", fg="yellow")
        return None

    import numpy as np
    import sounddevice as sd

    sample_rate = 16000
    duration = 3.0  # seconds
    blocksize = 1280

    click.echo()
    click.secho("  🎤 Speak now... (3 seconds)", fg="cyan", bold=True)

    try:
        audio = sd.rec(
            int(sample_rate * duration),
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
            device=input_device,
            blocksize=blocksize,
        )
        sd.wait()
    except Exception as e:
        click.secho(f"  ⚠️  Recording error: {e}", fg="yellow")
        click.secho("  Auto-gain will be used.\n", fg="yellow")
        return None

    peak = int(np.abs(audio).max())
    rms = float(np.sqrt(np.mean(audio.astype(np.float32) ** 2)))

    click.echo(f"  📊 Peak level: {peak} / 32767")
    click.echo(f"  📊 RMS: {rms:.0f}")

    if peak < 50:
        click.secho("  ⚠️  No audio detected. Check your microphone connection.", fg="yellow")
        click.secho("  Auto-gain will be used.\n", fg="yellow")
        return None

    # Calculate gain: target peak ~0.5 in float32 (16384 in int16)
    target_peak = 16384
    gain = round(target_peak / peak, 1)
    gain = max(1.0, min(gain, 100.0))  # clamp to sane range

    if gain < 1.5:
        click.secho("  ✅ Microphone is great! No gain needed.", fg="green")
        gain = 1.0
    elif gain < 5.0:
        click.secho(f"  ✅ Microphone OK. Gain: x{gain}", fg="green")
    else:
        click.secho(f"  ⚠️  Microphone is quiet. Gain: x{gain}", fg="yellow")
        click.echo("  💡 Tip: try increasing microphone volume in your OS settings.")

    click.echo()
    return gain


def _step_wakeword() -> tuple[bool, str]:
    """Step 4: Choose wake word."""
    click.secho("🎙️  [6/7] Wake Word", bold=True)
    click.echo()
    click.echo("  The assistant listens in the background and responds to a trigger phrase.")
    click.echo("  Without wake word — hold Space to record (push-to-talk).")
    click.echo()

    if not click.confirm("  Enable wake word mode?", default=True):
        click.secho("  ⏭  Push-to-talk mode. Hold [Space] to record.\n", fg="yellow")
        return False, ""

    click.echo()
    click.echo("  Trigger phrase:")
    for i, (key, desc) in enumerate(WAKE_WORD_OPTIONS, 1):
        click.echo(f"    {i}. {desc}")
    click.echo()

    choice = click.prompt("  Choose", type=click.IntRange(1, len(WAKE_WORD_OPTIONS)), default=1)
    wakeword_model = WAKE_WORD_OPTIONS[choice - 1][0]
    click.echo()

    _ensure_openwakeword()
    return True, wakeword_model


def _ensure_openwakeword() -> None:
    """Check openwakeword is installed; offer to install if missing."""
    try:
        import openwakeword  # noqa: F401
        return
    except ImportError:
        pass

    click.echo()
    click.secho("  ⚠️  Wake word requires the openwakeword package (~50 MB).", fg="yellow")
    click.echo()

    if not click.confirm("  Install now?", default=True):
        click.secho(
            "  Install manually before running:\n"
            "    pip install openocto[wakeword]",
            fg="yellow",
        )
        return

    import subprocess
    import sys

    click.echo("  ⬇️  Installing openwakeword...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "openwakeword"],
    )
    if result.returncode == 0:
        click.secho("  ✅ openwakeword installed!", fg="green")
    else:
        click.secho(
            "  ⚠️  Installation failed. Try manually:\n"
            "    pip install openocto[wakeword]",
            fg="yellow",
        )


def _step_whisper_model() -> str:
    """Step 2: Choose Whisper model size."""
    click.secho("🎤 [2/7] Speech Recognition", bold=True)
    click.echo()

    models = [
        ("tiny",   "75 MB",  "⚡ Fastest, lower accuracy"),
        ("base",   "142 MB", "⚡ Fast, decent accuracy"),
        ("small",  "466 MB", "⭐ Recommended — great balance"),
        ("medium", "1.5 GB", "🏆 Best accuracy, slower"),
    ]

    for i, (name, size, desc) in enumerate(models, 1):
        click.echo(f"  {i}. {name:8s} [{size:>6s}]  {desc}")
    click.echo()

    choice = click.prompt("  Choose", type=click.IntRange(1, 4), default=3)
    model_size = models[choice - 1][0]
    click.echo()
    return model_size


def _write_config(backend: str, api_key: str, model_size: str, voice_en: str, voice_ru: str,
                  primary_lang: str, input_device, output_device,
                  wakeword_enabled: bool, wakeword_model: str,
                  mic_gain: float | None = None) -> None:
    """Step 6: Write user config file."""
    click.secho("💾 [7/7] Saving configuration", bold=True)

    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    tts_config: dict = {"models": {"en": voice_en, "ru": voice_ru}}
    if primary_lang in ("ru", "auto"):
        tts_config["engines"] = {"ru": "silero"}

    audio_config: dict = {}
    if input_device is not None:
        audio_config["input_device"] = input_device
    if output_device is not None:
        audio_config["output_device"] = output_device

    config: dict = {
        "language": primary_lang,
        "ai": {"default_backend": backend},
        "stt": {"model_size": model_size, "language": primary_lang},
        "tts": tts_config,
    }
    if audio_config:
        config["audio"] = audio_config

    if mic_gain is not None:
        config.setdefault("vad", {})["mic_gain"] = mic_gain

    if wakeword_enabled and wakeword_model:
        config["wakeword"] = {"enabled": True, "model": wakeword_model}

    # Store API key in config if provided
    if api_key:
        env_var = BACKEND_ENV_KEYS.get(backend, "")
        if backend == "claude":
            config["ai"]["claude"] = {"api_key": api_key}
        elif env_var:
            config["ai"].setdefault("providers", {})
            config["ai"]["providers"][backend] = {"api_key": api_key}

    # Merge with existing config if present
    if USER_CONFIG_PATH.exists():
        with open(USER_CONFIG_PATH) as f:
            existing = yaml.safe_load(f) or {}
        # Deep merge: existing values are preserved, wizard values override
        from openocto.config import _deep_merge
        config = _deep_merge(existing, config)

    with open(USER_CONFIG_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    click.secho(f"  ✅ Config saved to {USER_CONFIG_PATH}", fg="green")
    click.echo()


def _models_status(model_size: str, voice_en: str, voice_ru: str, primary_lang: str,
                   wakeword_enabled: bool, wakeword_model: str) -> dict[str, bool]:
    """Check which models are already downloaded."""
    from openocto.utils.model_downloader import WHISPER_MODELS, SILERO_VAD, SILERO_TTS_MODELS, WAKE_WORD_MODELS
    from openocto.config import MODELS_DIR

    status = {
        "whisper": (MODELS_DIR / "whisper" / WHISPER_MODELS[model_size]["filename"]).exists(),
        "vad": (MODELS_DIR / "vad" / SILERO_VAD["filename"]).exists(),
    }
    if primary_lang in ("en", "auto"):
        status["piper_en"] = (MODELS_DIR / "piper" / f"{voice_en}.onnx").exists()
    if primary_lang in ("ru", "auto"):
        status["silero_ru"] = (MODELS_DIR / "silero_tts" / SILERO_TTS_MODELS["ru"]["filename"]).exists()
    if wakeword_enabled and wakeword_model:
        info = WAKE_WORD_MODELS.get(wakeword_model, {})
        if not info.get("builtin", False):
            status["wakeword"] = (MODELS_DIR / "wakeword" / info.get("filename", "")).exists()
    return status


def _ensure_torch(primary_lang: str) -> None:
    """Check torch is installed when Silero is selected; offer to install if missing."""
    if primary_lang not in ("ru", "auto"):
        return

    try:
        import torch  # noqa: F401
        return
    except ImportError:
        pass

    click.echo()
    click.secho("  ⚠️  Silero TTS requires PyTorch (~200 MB, CPU-only).", fg="yellow")
    click.echo("      Without it, Russian voice synthesis will not work.")
    click.echo()

    if not click.confirm("  Install PyTorch now?", default=True):
        click.secho(
            "  Install manually before running:\n"
            "    pip install torch --index-url https://download.pytorch.org/whl/cpu",
            fg="yellow",
        )
        return

    import subprocess
    import sys

    click.echo("  ⬇️  Installing PyTorch (CPU)...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "torch",
         "--index-url", "https://download.pytorch.org/whl/cpu"],
    )
    if result.returncode == 0:
        click.secho("  ✅ PyTorch installed!", fg="green")
    else:
        click.secho(
            "  ⚠️  Installation failed. Try manually:\n"
            "    pip install torch --index-url https://download.pytorch.org/whl/cpu",
            fg="yellow",
        )


def _step_download_models(model_size: str, voice_en: str, voice_ru: str, primary_lang: str,
                          wakeword_enabled: bool = False, wakeword_model: str = "") -> None:
    """Download missing models, skip already downloaded ones."""
    from openocto.utils.model_downloader import (
        get_whisper_model, get_piper_model, get_silero_vad_model,
        get_silero_tts_model, get_wake_word_model, WAKE_WORD_MODELS,
    )

    status = _models_status(model_size, voice_en, voice_ru, primary_lang, wakeword_enabled, wakeword_model)
    missing = [k for k, exists in status.items() if not exists]

    if not missing:
        click.secho("  ✅ All models already downloaded", fg="green")
        _ensure_torch(primary_lang)
        return

    labels = {
        "whisper": f"Whisper ({model_size})",
        "piper_en": f"🇺🇸 English voice ({voice_en})",
        "silero_ru": "🇷🇺 Russian voice — Silero TTS (~50 MB)",
        "vad": "VAD (voice activity detection)",
        "wakeword": f"🎙️  Wake word model ({wakeword_model})",
    }

    click.secho("📦 Models to download:", bold=True)
    for key, exists in status.items():
        click.echo(f"  {'✅' if exists else '⬇️ '} {labels[key]}")
    click.echo()

    if not click.confirm("  Download missing models now?", default=True):
        click.secho("  ⚠️  Models will download automatically on first run.", fg="yellow")
        _ensure_torch(primary_lang)
        return

    click.echo()

    try:
        if not status["whisper"]:
            click.echo(f"  ⬇️  Downloading Whisper {model_size} model...")
            get_whisper_model(model_size)

        if not status.get("piper_en"):
            click.echo(f"  ⬇️  Downloading English voice ({voice_en})...")
            get_piper_model(voice_en)

        if not status.get("silero_ru"):
            click.echo("  ⬇️  Downloading Russian Silero TTS model...")
            get_silero_tts_model("ru")

        if not status["vad"]:
            click.echo("  ⬇️  Downloading VAD model...")
            get_silero_vad_model()

        if not status.get("wakeword", True):
            info = WAKE_WORD_MODELS.get(wakeword_model, {})
            if not info.get("builtin", False):
                click.echo(f"  ⬇️  Downloading wake word model ({wakeword_model})...")
                get_wake_word_model(wakeword_model)

        click.secho("  ✅ All models ready!", fg="green")

    except Exception as e:
        click.secho(f"  ⚠️  Model download failed: {e}", fg="yellow")
        click.secho("  Models will download automatically on first run.", fg="yellow")

    _ensure_torch(primary_lang)
