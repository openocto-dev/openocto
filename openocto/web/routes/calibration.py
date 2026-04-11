"""Microphone calibration routes — record, analyze, visualize, tune VAD."""

from __future__ import annotations

import asyncio
import logging

import numpy as np
import aiohttp_jinja2
from aiohttp import web

from openocto import __version__
from openocto.config import load_config, USER_CONFIG_PATH, USER_CONFIG_DIR

logger = logging.getLogger(__name__)

routes = web.RouteTableDef()

SAMPLE_RATE = 16000
CHUNK_SIZE = 1280  # 80ms, same as pipeline


def _chunk_analysis(audio_i16: np.ndarray, vad) -> list[dict]:
    """Analyze audio in chunks, return per-chunk RMS and Silero prob."""
    vad.reset()
    results = []
    for i in range(0, len(audio_i16) - CHUNK_SIZE, CHUNK_SIZE):
        chunk = audio_i16[i:i + CHUNK_SIZE]
        rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))

        # Run Silero inference (with gain applied internally)
        _ = vad.is_speech(chunk)
        prob = vad.last_prob

        results.append({
            "time": round((i + CHUNK_SIZE) / SAMPLE_RATE, 2),
            "rms": round(rms),
            "prob": round(prob, 3),
        })
    return results


@routes.get("/calibration")
@aiohttp_jinja2.template("calibration.html")
async def calibration_page(request: web.Request) -> dict:
    octo = request.app["octo"]
    config = octo._config

    return {
        "page": "calibration",
        "version": __version__,
        "current": {
            "mic_gain": config.vad.mic_gain,
            "rms_speech_threshold": config.vad.rms_speech_threshold,
            "silence_duration": config.vad.silence_duration,
            "threshold": config.vad.threshold,
        },
    }


@routes.post("/api/calibration/record")
async def api_record(request: web.Request) -> web.Response:
    """Record audio from microphone and return per-chunk analysis."""
    data = await request.json()
    duration = min(float(data.get("duration", 3)), 10)  # max 10s

    # Record in a thread to not block the event loop
    import sounddevice as sd

    # Resolve input device — prefer config, fall back to system default
    octo = request.app["octo"]
    cfg_device = None
    if octo._config and octo._config.audio:
        cfg_device = getattr(octo._config.audio, "input_device", None)

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
        return web.json_response(
            {"error": str(exc)},
            status=503,
        )

    # Analyze with VAD
    from openocto.vad.silero import SileroVAD
    vad = SileroVAD(octo._config.vad)
    chunks = _chunk_analysis(audio, vad)

    # Summary stats
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

    # RMS threshold: midpoint between silence max and speech low quartile,
    # but at least 1.5x silence max
    rms_threshold = max(
        int((silence_rms_max + speech_rms_p25) / 2),
        int(silence_rms_max * 1.5),
    )

    # Silero threshold: midpoint between silence max and speech mean,
    # clamped to [0.15, 0.7]
    silero_threshold = round(
        max(0.15, min(0.7, (silence_prob_max + speech_prob_mean) / 2)),
        2,
    )

    return web.json_response({
        "recommended": {
            "rms_speech_threshold": rms_threshold,
            "threshold": silero_threshold,
            "silence_duration": 2.5,
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

    # Hot-reload VAD config on the running app
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
