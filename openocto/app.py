"""Main OpenOcto application orchestrator."""

from __future__ import annotations

import asyncio
import logging
import sys

import numpy as np

from openocto import __version__
from openocto.audio.capture import AudioCapture
from openocto.audio.player import AudioPlayer
from openocto.config import AppConfig
from openocto.event_bus import EventBus, EventType
from openocto.history import HistoryStore
from openocto.persona.manager import Persona, PersonaManager
from openocto.state_machine import State, StateMachine

logger = logging.getLogger(__name__)


class OpenOctoApp:
    """Main application — wires all components together and runs the main loop."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

        # Core infrastructure
        self._event_bus = EventBus()
        self._state_machine = StateMachine(self._event_bus)

        # Audio
        self._capture = AudioCapture(config.audio)
        self._player = AudioPlayer(config.audio)

        # Components initialized lazily (need model downloads)
        self._stt = None
        self._tts_engines: dict[str, object] = {}
        self._ai_router = None
        self._persona_manager = PersonaManager()
        self._persona: Persona | None = None
        self._wakeword = None
        self._vad = None

        # Persistent history
        self._history_store = HistoryStore()
        self._current_user_id: int | None = None

        # Processing lock (shared by PTT and wake word modes)
        self._processing = False
        self._loop: asyncio.AbstractEventLoop | None = None

    def _init_components(self) -> None:
        """Initialize heavy components (downloads models if needed)."""
        print("🔧 Initializing components...")

        # STT
        from openocto.stt.whisper_cpp import WhisperCppEngine
        self._stt = WhisperCppEngine(self._config.stt)

        # Persona
        self._persona = self._persona_manager.activate(self._config.persona)

        # TTS — pre-load models for all configured languages
        from openocto.tts.factory import create_tts_engine
        for lang, model_name in self._config.tts.models.items():
            try:
                self._tts_engines[lang] = create_tts_engine(lang, model_name, self._config.tts)
                engine_name = self._config.tts.engines.get(lang, self._config.tts.engine)
                logger.info("TTS loaded for lang=%s: engine=%s, model=%s", lang, engine_name, model_name)
            except RuntimeError as e:
                engine_name = self._config.tts.engines.get(lang, self._config.tts.engine)
                if engine_name == "silero":
                    print(f"\n⚠️  {e}\n")
                else:
                    logger.warning("Failed to load TTS for lang=%s: %s", lang, e)
            except Exception as e:
                logger.warning("Failed to load TTS for lang=%s: %s", lang, e)

        # Auto-start claude-max-proxy if needed
        if self._config.ai.default_backend == "claude-proxy":
            from openocto.utils.proxy import ensure_proxy
            print("🔌 Starting Claude proxy...")
            if not ensure_proxy():
                print("⚠️  Claude proxy not available. Install it with:")
                print("     npm install -g claude-max-api-proxy")
                print("   Falling back to other available backends.\n")

        # AI Router
        from openocto.ai.router import AIRouter
        self._ai_router = AIRouter(self._config.ai)

        # Wake word + VAD (only in wake word mode)
        if self._config.wakeword.enabled:
            try:
                from openocto.wakeword.openwakeword import OpenWakeWordDetector
                self._wakeword = OpenWakeWordDetector(self._config.wakeword)
                self._capture.set_chunk_callback(self._on_audio_chunk)

                from openocto.vad.silero import SileroVAD
                self._vad = SileroVAD(self._config.vad)
            except RuntimeError as e:
                print(f"\n⚠️  {e}\n")
                print("   Falling back to push-to-talk mode.\n")

        # Pick current user: last active → default → first → create new
        user = (
            self._history_store.get_last_active_user()
            or self._history_store.get_default_user()
        )
        if user is None:
            users = self._history_store.list_users()
            user = users[0] if users else None
        if user is None:
            uid = self._history_store.create_user("User", is_default=True)
            logger.info("Created default user (id=%d)", uid)
        else:
            uid = user["id"]
        self._current_user_id = uid
        logger.info("Active user: %s (id=%d)", user["name"] if user else "User", uid)

        print("✅ Ready!\n")

    def _detect_response_lang(self, text: str) -> str:
        """Detect language of AI response text by script."""
        if not text:
            return "en"
        cyrillic = sum(1 for c in text if "\u0400" <= c <= "\u04ff")
        return "ru" if cyrillic / len(text) > 0.2 else "en"

    def _get_tts(self, language: str):
        """Get TTS engine for the given language code."""
        if language in self._tts_engines:
            return self._tts_engines[language]
        prefix = language.split("_")[0]
        if prefix in self._tts_engines:
            return self._tts_engines[prefix]
        return next(iter(self._tts_engines.values())) if self._tts_engines else None

    # --- Wake word mode ---

    def _on_audio_chunk(self, chunk) -> None:
        """Called from audio thread for every chunk. Feeds wake word detector."""
        if self._wakeword and not self._processing and self._loop:
            if self._wakeword.process_chunk(chunk):
                asyncio.run_coroutine_threadsafe(
                    self._on_wake_word_detected(), self._loop
                )

    async def _await_and_record(self, max_duration: float = 60.0,
                                silence_after_speech: float = 3.0,
                                no_speech_timeout: float = 10.0) -> "np.ndarray | None":
        """Record audio with webrtcvad silence detection.

        Stops when ``silence_after_speech`` seconds of non-speech detected
        after the user started talking.  Gives up after ``no_speech_timeout``
        if no speech is detected at all.  Hard cap at ``max_duration``.
        """
        import torch
        from silero_vad import load_silero_vad, VADIterator

        model = load_silero_vad()
        vad_iter = VADIterator(
            model,
            threshold=0.5,
            sampling_rate=self._capture.sample_rate,
            min_silence_duration_ms=int(silence_after_speech * 1000),
            speech_pad_ms=30,
        )

        await self._state_machine.transition("start_recording")
        self._capture.start_recording()

        speech_detected = False
        speech_ended = False
        last_chunk_idx = -1
        window = 512  # silero-vad requires 512-sample chunks at 16kHz
        loop = asyncio.get_event_loop()
        t0 = loop.time()

        try:
            while True:
                now = loop.time()
                elapsed = now - t0

                if elapsed >= max_duration:
                    break

                if not speech_detected and elapsed >= no_speech_timeout:
                    self._capture.stop_recording()
                    print(" " * 60, end="\r")
                    vad_iter.reset_states()
                    await self._state_machine.transition("cancel")
                    return None

                if speech_ended:
                    break

                secs = int(elapsed)
                if speech_detected:
                    print(f"🎤 Recording... {secs}s ", end="\r", flush=True)
                else:
                    print(f"🎤 Listening... {secs}s ", end="\r", flush=True)

                # Feed new audio to VADIterator in 512-sample chunks
                while True:
                    result = self._capture.get_latest_chunk(after=last_chunk_idx)
                    if result is None:
                        break
                    chunk, last_chunk_idx = result

                    # Convert int16 → float32 [-1, 1]
                    audio_f32 = chunk.astype(np.float32) / 32768.0

                    for i in range(0, len(audio_f32) - window + 1, window):
                        frame = torch.from_numpy(audio_f32[i:i + window])
                        event = vad_iter(frame, return_seconds=True)
                        if event:
                            if "start" in event:
                                speech_detected = True
                            elif "end" in event:
                                speech_ended = True
                                break
                    if speech_ended:
                        break

                await asyncio.sleep(0.05)
        except Exception:
            self._capture.stop_recording()
            vad_iter.reset_states()
            raise

        vad_iter.reset_states()
        audio = self._capture.stop_recording()
        print(" " * 60, end="\r")

        if audio.size == 0:
            await self._state_machine.transition("cancel")
            return None

        return audio

    async def _on_wake_word_detected(self) -> None:
        """Triggered when wake word fires — beep, wait for speech, record."""
        if self._state_machine.state != State.IDLE or self._processing:
            return
        if self._player.is_playing:
            self._player.stop()

        self._player.beep(freq=880.0, duration=0.12)
        await asyncio.sleep(0.15)  # let beep finish before VAD starts

        try:
            audio = await self._await_and_record()
            if audio is None:
                return  # no speech detected — back to idle, wake word resumes
            await self._handle_audio(audio)
        except Exception as e:
            logger.exception("Wake word pipeline error")
            print(f"\n❌ Error: {e}")
            self._capture.stop_recording()
            self._state_machine.reset()

    async def _auto_listen(self) -> None:
        """After TTS finishes: beep + 5s window to speak without wake word.

        If no speech detected — silently returns to idle (wake word resumes).
        """
        if not (self._wakeword and self._config.wakeword.enabled):
            return
        if self._state_machine.state != State.IDLE or self._processing:
            return

        self._processing = True
        try:
            await asyncio.sleep(0.15)  # brief pause after TTS ends
            self._player.beep(freq=660.0, duration=0.10)  # lower pitch = "ready"
            await asyncio.sleep(0.15)

            audio = await self._await_and_record(no_speech_timeout=5.0)
            if audio is None:
                return  # no speech detected — wake word mode resumes
            await self._handle_audio(audio, silent=True)
        except Exception as e:
            logger.exception("Auto-listen error")
            print(f"\n❌ Error: {e}")
            self._capture.stop_recording()
            self._state_machine.reset()
        finally:
            self._processing = False

    # --- PTT mode ---

    def _on_ptt_press(self) -> None:
        """Called from keyboard thread when PTT key is pressed."""
        if self._player.is_playing:
            self._player.stop()
        if self._state_machine.state == State.IDLE and not self._processing:
            asyncio.ensure_future(self._start_recording())

    def _on_ptt_release(self) -> None:
        """Called from keyboard thread when PTT key is released."""
        if self._state_machine.state == State.RECORDING:
            asyncio.ensure_future(self._stop_recording())

    async def _start_recording(self) -> None:
        await self._state_machine.transition("start_recording")
        self._capture.start()
        print("🎤 Recording... (release [Space] to stop)", end="\r", flush=True)

    async def _stop_recording(self) -> None:
        self._capture.stop()
        audio = self._capture.get_recording()
        print(" " * 50, end="\r")  # clear the recording line

        if audio.size == 0:
            print("⚠️  No audio captured.")
            await self._state_machine.transition("cancel")
            return

        await self._handle_audio(audio)

    async def _handle_audio(self, audio, silent: bool = False) -> None:
        """Run the full pipeline: transcribe → AI → TTS.

        Args:
            silent: if True, silently cancel on empty transcription (auto-listen).
        """
        self._processing = True
        try:
            # Transcribe
            await self._state_machine.transition("stop_recording")
            result = await asyncio.to_thread(self._stt.transcribe, audio)
            await self._event_bus.publish(EventType.STT_RESULT, {"text": result.text, "language": result.language})

            if not result.text.strip():
                if not silent:
                    print("⚠️  Could not transcribe audio.")
                await self._state_machine.transition("cancel")
                return

            print(f"You [{result.language}]: {result.text}")
            await self._state_machine.transition("transcription_done")

            # Persist user message & load history
            persona_name = self._persona.name
            uid = self._current_user_id
            self._history_store.add_message(
                uid, persona_name, "user", result.text,
                language=result.language,
            )
            history = self._history_store.get_recent_messages(
                uid, persona_name, limit=self._config.ai.max_history,
            )

            # AI response
            response_chunks: list[str] = []
            got_first_chunk = False

            async def _spin() -> None:
                i = 0
                while True:
                    print(f"\rOcto: {'|/-\\'[i % 4]}", end="", flush=True)
                    i += 1
                    await asyncio.sleep(0.1)

            spinner = asyncio.create_task(_spin())

            async def on_chunk(chunk: str) -> None:
                nonlocal got_first_chunk
                if not got_first_chunk:
                    got_first_chunk = True
                    spinner.cancel()
                    print("\rOcto: ", end="", flush=True)
                response_chunks.append(chunk)
                print(chunk, end="", flush=True)

            response = await self._ai_router.send_streaming(
                result.text, history, self._persona, on_chunk
            )
            if not spinner.done():
                spinner.cancel()
            if not got_first_chunk:
                print("\rOcto: ", end="", flush=True)
            print()  # newline after streamed response

            # Persist assistant response
            self._history_store.add_message(
                uid, persona_name, "assistant", response,
                backend=self._ai_router.active_backend_name,
            )

            await self._event_bus.publish(EventType.AI_RESPONSE, {"text": response})
            await self._state_machine.transition("response_ready")

            # TTS — pick engine based on response language, not input language
            response_lang = self._detect_response_lang(response)
            tts = self._get_tts(response_lang)
            if tts and response.strip():
                audio_out = await asyncio.to_thread(tts.synthesize, response)
                await self._player.play_async_awaitable(audio_out.audio, audio_out.sample_rate)
            else:
                if not tts:
                    logger.warning("No TTS engine for language: %s", result.language)

            await self._state_machine.transition("speech_done")
            await self._event_bus.publish(EventType.TTS_FINISHED, {})

        except Exception as e:
            logger.exception("Pipeline error")
            print(f"\n❌ Error: {e}")
            self._state_machine.reset()
        finally:
            self._processing = False

        # Schedule auto-listen as a separate task so _processing is fully released first
        asyncio.ensure_future(self._auto_listen())

    async def run(self) -> None:
        """Main application loop."""
        self._loop = asyncio.get_running_loop()
        self._init_components()

        header = (
            f"🐙 OpenOcto v{__version__} | "
            f"Persona: {self._persona.display_name} | "
            f"AI: {self._ai_router.active_backend_name}"
        )

        if self._config.wakeword.enabled and self._wakeword:
            await self._run_wakeword_mode(header)
        else:
            await self._run_ptt_mode(header)

    async def _run_wakeword_mode(self, header: str) -> None:
        """Always-on microphone, wake word triggers recording."""
        self._capture.start_stream()
        print(header)
        wake_phrase = self._config.wakeword.model.replace("_v0.", " v0.").replace("_", " ").title().rsplit(" V0", 1)[0]
        print(f"   Say '{wake_phrase}' to activate | [Ctrl+C] to quit\n")
        try:
            while True:
                await asyncio.sleep(0.1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            self._capture.stop_stream()
            self._player.stop()
            print("\n👋 Goodbye!")

    async def _run_ptt_mode(self, header: str) -> None:
        """Push-to-talk: hold Space to record."""
        from openocto.utils.keyboard import AsyncPushToTalkListener
        from pynput import keyboard as kb
        listener = AsyncPushToTalkListener(
            on_press=self._on_ptt_press,
            on_release=self._on_ptt_release,
            ptt_key=kb.Key.space,
        )
        print(header)
        print("   Hold [Space] to speak | [Ctrl+C] to quit\n")
        listener.start()
        try:
            while True:
                await asyncio.sleep(0.1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            listener.stop()
            self._capture.stop()
            self._player.stop()
            print("\n👋 Goodbye!")
