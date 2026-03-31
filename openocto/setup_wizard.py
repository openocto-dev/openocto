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
        click.secho(f"   ⏩ Starting from step {from_step}/8\n", fg="yellow")

    # Load existing config values as defaults for skipped steps
    existing = _load_existing_config()

    # Step 1: Create user
    if from_step <= 1:
        user_name = _step_create_user()
    else:
        click.secho("  ⏩ [1/8] User: (already created)", fg="yellow")

    # Step 2: AI backend
    if from_step <= 2:
        backend, api_key = _step_ai_backend()
    else:
        backend = existing.get("ai", {}).get("default_backend", "claude")
        api_key = ""
        click.secho(f"  ⏩ [2/8] AI: {backend}", fg="yellow")

    # Step 3: Whisper model size
    if from_step <= 3:
        model_size = _step_whisper_model()
    else:
        model_size = existing.get("stt", {}).get("model_size", "small")
        click.secho(f"  ⏩ [3/8] STT: whisper-{model_size}", fg="yellow")

    # Step 4: TTS voices
    if from_step <= 4:
        voice_en, voice_ru, primary_lang = _step_tts_voices()
    else:
        primary_lang = existing.get("language", "en")
        tts = existing.get("tts", {})
        voice_en = tts.get("models", {}).get("en", TTS_VOICES_EN[0][0])
        voice_ru = tts.get("models", {}).get("ru", SILERO_SPEAKERS_RU[0][0])
        click.secho(f"  ⏩ [4/8] Voice: lang={primary_lang}, en={voice_en}, ru={voice_ru}", fg="yellow")  # noqa: E501

    # Step 5: Audio devices
    if from_step <= 5:
        input_device, output_device = _step_audio_devices()
    else:
        audio = existing.get("audio", {})
        input_device = audio.get("input_device")
        output_device = audio.get("output_device")
        click.secho(f"  ⏩ [5/8] Audio: in={input_device}, out={output_device}", fg="yellow")

    # Step 6: Microphone calibration
    if from_step <= 6:
        mic_gain, vad_threshold, rms_threshold = _step_mic_calibration(input_device)
    else:
        vad = existing.get("vad") or {}
        mic_gain = vad.get("mic_gain")
        vad_threshold = vad.get("threshold", 0.3)
        rms_threshold = vad.get("rms_speech_threshold", 300)
        click.secho(f"  ⏩ [6/8] Mic gain: {mic_gain or 'auto'}, RMS threshold: {rms_threshold}", fg="yellow")

    # Step 7: Wake word
    if from_step <= 7:
        wakeword_enabled, wakeword_model = _step_wakeword()
    else:
        ww = existing.get("wakeword", {})
        wakeword_enabled = ww.get("enabled", False)
        wakeword_model = ww.get("model", "")
        click.secho(f"  ⏩ [7/8] Wake word: enabled={wakeword_enabled}, model={wakeword_model}", fg="yellow")

    click.echo()

    # Step 8: Write config
    _write_config(backend, api_key, model_size, voice_en, voice_ru, primary_lang,
                  input_device, output_device, wakeword_enabled, wakeword_model,
                  mic_gain, vad_threshold, rms_threshold)

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


def _step_create_user() -> str:
    """Step 1: Create the default user in HistoryStore."""
    click.secho("👤 [1/8] Who are you?", bold=True)
    click.echo()

    import getpass
    system_user = getpass.getuser().capitalize()

    name = click.prompt("  Your name", default=system_user)

    from openocto.history import HistoryStore
    store = HistoryStore()
    existing = store.get_user_by_name(name)
    if existing:
        click.secho(f"  ✅ Welcome back, {name}!", fg="green")
    else:
        store.create_user(name, is_default=True)
        click.secho(f"  ✅ User \"{name}\" created!", fg="green")
    store.close()

    click.echo()
    return name


def _step_ai_backend() -> tuple[str, str]:
    """Step 2: Choose AI backend and optionally enter API key."""
    click.secho("🤖 [2/8] AI Brain", bold=True)
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
    click.secho("🗣️  [4/8] Voice & Language", bold=True)
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
    click.secho("🔊 [5/8] Audio Devices", bold=True)
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


def _record_chunk(input_device, duration: float, sample_rate: int = 16000) -> "np.ndarray | None":
    """Record audio for calibration. Returns int16 array or None on error."""
    import numpy as np
    import sounddevice as sd

    # Use device native sample rate to avoid PortAudio errors
    try:
        info = sd.query_devices(input_device, "input")
        native_sr = int(info["default_samplerate"])
        max_ch = int(info["max_input_channels"])
    except Exception:
        native_sr = sample_rate
        max_ch = 1

    if max_ch == 0:
        click.secho("  ⚠️  Selected device has no input channels.", fg="yellow")
        return None

    channels = min(1, max_ch)
    try:
        audio = sd.rec(
            int(native_sr * duration),
            samplerate=native_sr,
            channels=channels,
            dtype="int16",
            device=input_device,
        )
        sd.wait()
    except Exception as e:
        click.secho(f"  ⚠️  Recording error: {e}", fg="yellow")
        return None

    audio = audio.flatten()

    # Resample to 16000 if needed
    if native_sr != sample_rate:
        from math import gcd
        from scipy.signal import resample_poly
        g = gcd(native_sr, sample_rate)
        audio_f = resample_poly(audio.astype("float32"), sample_rate // g, native_sr // g)
        audio = np.clip(audio_f, -32768, 32767).astype("int16")

    return audio


def _step_mic_calibration(input_device: int | None) -> tuple[float | None, float, int]:
    """Step 6: Calibrate mic — record silence + speech, set gain, VAD threshold, RMS threshold.

    Returns (mic_gain, vad_threshold, rms_speech_threshold).
    mic_gain=None means auto-gain is sufficient.
    """
    click.secho("🔬 [6/8] Microphone Calibration", bold=True)
    click.echo()
    click.echo("  Records silence and speech to calibrate VAD sensitivity.")
    click.echo()

    if not click.confirm("  Start calibration?", default=True):
        click.secho("  ⏭  Skipped. Defaults will be used.\n", fg="yellow")
        return None, 0.5, 300

    import numpy as np
    from openocto.utils.model_downloader import get_silero_vad_model

    # Load VAD model for threshold calibration
    try:
        import onnxruntime as ort
        model_path = get_silero_vad_model()
        session = ort.InferenceSession(str(model_path))
        sr_arr = np.array(16000, dtype=np.int64)
        state = np.zeros((2, 1, 128), dtype=np.float32)
        V5_WINDOW = 512

        def vad_probs(audio_int16: np.ndarray) -> list[float]:
            nonlocal state
            state = np.zeros((2, 1, 128), dtype=np.float32)
            audio_f = audio_int16.astype(np.float32) / 32768.0
            probs = []
            for offset in range(0, len(audio_f), V5_WINDOW):
                w = audio_f[offset:offset + V5_WINDOW]
                if len(w) < V5_WINDOW:
                    w = np.pad(w, (0, V5_WINDOW - len(w)))
                out, state = session.run(None, {"input": w.reshape(1, -1), "state": state, "sr": sr_arr})
                probs.append(float(out.flat[0]))
            return probs

        vad_available = True
    except Exception:
        vad_available = False

    # --- Phase 1: silence ---
    click.echo()
    click.secho("  🔇 Phase 1/2 — stay quiet... (2 seconds)", fg="yellow", bold=True)
    silence_audio = _record_chunk(input_device, duration=2.0)

    if silence_audio is None or int(np.abs(silence_audio).max()) < 10:
        click.secho("  ⚠️  No audio detected. Check microphone.\n", fg="yellow")
        return None, 0.5, 300

    # --- Phase 2: speech ---
    click.echo()
    click.secho("  🎤 Phase 2/2 — get ready to speak!", fg="cyan", bold=True)
    for i in range(3, 0, -1):
        click.echo(f"     {i}...", nl=False)
        import time; time.sleep(1)
    click.echo()
    click.secho("  🔴 Recording — speak now! (3 seconds)", fg="red", bold=True)
    speech_audio = _record_chunk(input_device, duration=3.0)

    if speech_audio is None:
        click.secho("  ⚠️  Recording failed.\n", fg="yellow")
        return None, 0.5, 300

    # --- Compute gain ---
    speech_peak = int(np.abs(speech_audio).max())
    click.echo()
    click.echo(f"  📊 Speech peak: {speech_peak} / 32767")

    if speech_peak < 50:
        click.secho("  ⚠️  Speech too quiet. Check microphone volume.\n", fg="yellow")
        return None, 0.5, 300

    target_peak = 16384  # 0.5 in float32
    gain = round(target_peak / speech_peak, 1)
    gain = max(1.0, min(gain, 100.0))
    mic_gain: float | None = None if gain < 1.5 else gain

    # --- Compute VAD threshold ---
    vad_threshold = 0.3  # safe default
    if vad_available:
        def apply_gain(a: np.ndarray) -> np.ndarray:
            f = a.astype(np.float32) / 32768.0
            if mic_gain is not None:
                return np.clip(f * mic_gain, -1.0, 1.0)
            peak = np.abs(f).max()
            if peak > 0.005:
                return np.clip(f * (0.5 / peak), -1.0, 1.0)
            return f

        silence_gained = (apply_gain(silence_audio) * 32768).astype(np.int16)
        speech_gained = (apply_gain(speech_audio) * 32768).astype(np.int16)

        silence_probs = vad_probs(silence_gained)
        speech_probs = vad_probs(speech_gained)

        noise_max = max(silence_probs) if silence_probs else 0.0
        speech_max = max(speech_probs) if speech_probs else 0.0

        click.echo(f"  📊 VAD silence max: {noise_max:.3f}  |  speech max: {speech_max:.3f}")

        if speech_max < 0.2:
            click.secho("  ⚠️  VAD couldn't detect speech. Using default threshold 0.3.", fg="yellow")
        else:
            # Threshold = midpoint between noise ceiling and speech floor
            speech_min = float(np.percentile(speech_probs, 25))
            threshold = round((noise_max + speech_min) / 2, 2)
            threshold = max(0.1, min(threshold, 0.7))
            vad_threshold = threshold
            click.secho(f"  ✅ VAD threshold set to {vad_threshold}", fg="green")

    # --- Compute RMS speech threshold ---
    silence_rms = float(np.sqrt(np.mean(silence_audio.astype(np.float32) ** 2)))
    speech_rms = float(np.sqrt(np.mean(speech_audio.astype(np.float32) ** 2)))
    # Midpoint between silence and speech, with a margin above silence
    rms_threshold = int(silence_rms + (speech_rms - silence_rms) * 0.4)
    rms_threshold = max(100, min(rms_threshold, 2000))
    click.echo(f"  📊 RMS silence: {silence_rms:.0f}  |  speech: {speech_rms:.0f}  |  threshold: {rms_threshold}")

    if mic_gain is None:
        click.secho("  ✅ Microphone level is good. Auto-gain enabled.", fg="green")
    else:
        click.secho(f"  ✅ Mic gain: x{mic_gain}", fg="green")

    click.echo()
    return mic_gain, vad_threshold, rms_threshold


def _step_wakeword() -> tuple[bool, str]:
    """Step 4: Choose wake word."""
    click.secho("🎙️  [7/8] Wake Word", bold=True)
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
    click.secho("🎤 [3/8] Speech Recognition", bold=True)
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
                  mic_gain: float | None = None, vad_threshold: float = 0.3,
                  rms_threshold: int = 300) -> None:
    """Step 6: Write user config file."""
    click.secho("💾 [8/8] Saving configuration", bold=True)

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

    vad_config: dict = {"threshold": vad_threshold, "rms_speech_threshold": rms_threshold}
    if mic_gain is not None:
        vad_config["mic_gain"] = mic_gain
    config["vad"] = vad_config

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
