"""Audio settings routes — microphone calibration + output device selection."""

from __future__ import annotations

import asyncio
import logging

import numpy as np
import aiohttp_jinja2
from aiohttp import web

from openocto import __version__
from openocto.config import USER_CONFIG_PATH, USER_CONFIG_DIR

logger = logging.getLogger(__name__)

routes = web.RouteTableDef()

SAMPLE_RATE = 16000
CHUNK_SIZE = 1280  # 80ms, same as pipeline

# Short sine-wave beep played when testing output device (440 Hz, 0.5s)
def _make_test_tone(sample_rate: int = 44100, duration: float = 0.5, freq: float = 440.0) -> np.ndarray:
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    wave = (np.sin(2 * np.pi * freq * t) * 0.5).astype(np.float32)
    # Fade in/out to avoid clicks
    fade = int(sample_rate * 0.02)
    wave[:fade] *= np.linspace(0, 1, fade)
    wave[-fade:] *= np.linspace(1, 0, fade)
    return wave


def _chunk_analysis(audio_i16: np.ndarray, vad) -> list[dict]:
    """Analyze audio in chunks, return per-chunk RMS and Silero prob."""
    vad.reset()
    results = []
    for i in range(0, len(audio_i16) - CHUNK_SIZE, CHUNK_SIZE):
        chunk = audio_i16[i:i + CHUNK_SIZE]
        rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))

        _ = vad.is_speech(chunk)
        prob = vad.last_prob

        results.append({
            "time": round((i + CHUNK_SIZE) / SAMPLE_RATE, 2),
            "rms": round(rms),
            "prob": round(prob, 3),
        })
    return results


def _get_audio_devices() -> tuple[list[dict], list[dict]]:
    """Return (input_devices, output_devices) lists for dropdowns."""
    import sounddevice as sd
    inputs, outputs = [], []
    try:
        for idx, d in enumerate(sd.query_devices()):
            entry = {"index": idx, "name": d["name"]}
            if d["max_input_channels"] > 0:
                inputs.append(entry)
            if d["max_output_channels"] > 0:
                outputs.append(entry)
    except Exception:
        pass
    return inputs, outputs


@routes.get("/audio")
@aiohttp_jinja2.template("calibration.html")
async def audio_page(request: web.Request) -> dict:
    from openocto.audio.capture import _resolve_device

    octo = request.app["octo"]
    config = octo._config

    input_devices, output_devices = _get_audio_devices()

    cfg_in = cfg_out = None
    if config and config.audio:
        cfg_in = getattr(config.audio, "input_device", None)
        cfg_out = getattr(config.audio, "output_device", None)

    return {
        "page": "calibration",
        "version": __version__,
        "input_devices": input_devices,
        "output_devices": output_devices,
        "current_device_index": _resolve_device(cfg_in, kind="input"),
        "current_output_index": _resolve_device(cfg_out, kind="output"),
        "current": {
            "mic_gain": config.vad.mic_gain,
            "rms_speech_threshold": config.vad.rms_speech_threshold,
            "silence_duration": config.vad.silence_duration,
            "threshold": config.vad.threshold,
        },
    }


@routes.get("/calibration")
async def calibration_redirect(request: web.Request) -> web.Response:
    raise web.HTTPMovedPermanently("/audio")


# ── Recording & analysis ──────────────────────────────────────────────────


@routes.post("/api/calibration/record")
async def api_record(request: web.Request) -> web.Response:
    """Record audio from microphone and return per-chunk analysis."""
    import sounddevice as sd
    from openocto.audio.capture import _resolve_device

    data = await request.json()
    duration = min(float(data.get("duration", 3)), 10)

    # Device priority: explicit index from UI > config > system default
    device_index = data.get("device_index")
    if device_index is not None:
        cfg_device = int(device_index)
    else:
        octo = request.app["octo"]
        cfg_device = None
        if octo._config and octo._config.audio:
            cfg_device = _resolve_device(
                getattr(octo._config.audio, "input_device", None), kind="input"
            )

    def _record():
        samples = int(duration * SAMPLE_RATE)
        try:
            rec = sd.rec(
                samples,
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                device=cfg_device,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Cannot open microphone: {exc}. "
                "Check that a recording device is connected and permissions are granted."
            ) from exc
        sd.wait()
        return rec.flatten()

    try:
        audio = await asyncio.to_thread(_record)
    except RuntimeError as exc:
        logger.warning("Calibration recording failed: %s", exc)
        return web.json_response({"error": str(exc)}, status=503)

    octo = request.app["octo"]
    from openocto.vad.silero import SileroVAD
    vad = SileroVAD(octo._config.vad)
    chunks = _chunk_analysis(audio, vad)

    rms_values = [c["rms"] for c in chunks]
    prob_values = [c["prob"] for c in chunks]

    return web.json_response({
        "duration": duration,
        "chunks": chunks,
        "stats": {
            "rms_mean": round(np.mean(rms_values)),
            "rms_median": round(np.median(rms_values)),
            "rms_p95": round(np.percentile(rms_values, 95)),
            "rms_p99": round(np.percentile(rms_values, 99)),
            "rms_max": round(max(rms_values)),
            "prob_mean": round(float(np.mean(prob_values)), 3),
            "prob_max": round(float(max(prob_values)), 3),
        },
    })


@routes.post("/api/calibration/analyze")
async def api_analyze(request: web.Request) -> web.Response:
    """Given silence and speech stats, recommend optimal thresholds."""
    data = await request.json()
    silence_stats = data.get("silence", {})
    speech_stats = data.get("speech", {})

    silence_rms_max = silence_stats.get("rms_p99", 100)
    speech_rms_p25 = speech_stats.get("rms_p25", 5000)
    silence_prob_max = silence_stats.get("prob_max", 0.05)
    speech_prob_mean = speech_stats.get("prob_mean", 0.7)

    rms_threshold = max(
        int((silence_rms_max + speech_rms_p25) / 2),
        int(silence_rms_max * 1.5),
    )
    silero_threshold = round(
        max(0.15, min(0.7, (silence_prob_max + speech_prob_mean) / 2)), 2,
    )

    return web.json_response({
        "recommended": {
            "rms_speech_threshold": rms_threshold,
            "threshold": silero_threshold,
            "silence_duration": 1.5,
        },
        "analysis": {
            "silence_rms_max": silence_rms_max,
            "speech_rms_p25": speech_rms_p25,
            "rms_gap_ratio": round(speech_rms_p25 / max(silence_rms_max, 1), 1),
            "silence_prob_max": silence_prob_max,
            "speech_prob_mean": speech_prob_mean,
        },
    })


@routes.post("/api/calibration/save")
async def api_save(request: web.Request) -> web.Response:
    """Save calibrated VAD settings to user config."""
    import yaml
    from openocto.config import _deep_merge

    data = await request.json()

    vad_update = {}
    for key in ("rms_speech_threshold", "threshold", "silence_duration", "mic_gain"):
        if key in data:
            vad_update[key] = data[key]

    if not vad_update:
        return web.json_response({"ok": False, "error": "No values to save"}, status=400)

    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config: dict = {}
    if USER_CONFIG_PATH.exists():
        with open(USER_CONFIG_PATH) as f:
            config = yaml.safe_load(f) or {}

    config = _deep_merge(config, {"vad": vad_update})
    with open(USER_CONFIG_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    octo = request.app["octo"]
    for key, val in vad_update.items():
        if hasattr(octo._config.vad, key):
            setattr(octo._config.vad, key, val)
    if octo._vad:
        if "threshold" in vad_update:
            octo._vad._threshold = vad_update["threshold"]
        if "rms_speech_threshold" in vad_update:
            octo._vad._rms_threshold = vad_update["rms_speech_threshold"]
        if "silence_duration" in vad_update:
            octo._vad._silence_duration = vad_update["silence_duration"]
        if "mic_gain" in vad_update:
            octo._vad._mic_gain = vad_update["mic_gain"]

    logger.info("Calibration saved: %s", vad_update)
    return web.json_response({"ok": True, "saved": vad_update})


# ── Output device ─────────────────────────────────────────────────────────


@routes.post("/api/audio/test-output")
async def api_test_output(request: web.Request) -> web.Response:
    """Play a short test tone through the selected output device."""
    import sounddevice as sd

    data = await request.json()
    device_index = data.get("device_index")
    device = int(device_index) if device_index is not None else None

    tone = _make_test_tone()

    def _play():
        try:
            sd.play(tone, samplerate=44100, device=device, blocking=True)
        except Exception as exc:
            raise RuntimeError(f"Cannot open output device: {exc}") from exc

    try:
        await asyncio.to_thread(_play)
    except RuntimeError as exc:
        logger.warning("Output test failed: %s", exc)
        return web.json_response({"ok": False, "error": str(exc)}, status=503)

    return web.json_response({"ok": True})


@routes.post("/api/audio/save-output")
async def api_save_output(request: web.Request) -> web.Response:
    """Save selected output device to user config."""
    import yaml
    from openocto.config import _deep_merge

    data = await request.json()
    device_index = data.get("device_index")  # int or null

    USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config: dict = {}
    if USER_CONFIG_PATH.exists():
        with open(USER_CONFIG_PATH) as f:
            config = yaml.safe_load(f) or {}

    config = _deep_merge(config, {"audio": {"output_device": device_index}})
    with open(USER_CONFIG_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    # Hot-reload on running app
    octo = request.app["octo"]
    if octo._config and octo._config.audio:
        octo._config.audio.output_device = device_index

    logger.info("Output device saved: %s", device_index)
    return web.json_response({"ok": True})
