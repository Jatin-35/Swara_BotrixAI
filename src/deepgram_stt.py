"""Deepgram STT handler for PALUCK Technologies Warranty/AMC Voice Bot.

Drop-in replacement for SonioxSTTHandler. Same public interface:
  - write_audio(pcm_audio: bytes)   — sync, queue PCM16 chunks
  - start_async()                   — async, open Deepgram WS session
  - stop_async()                    — async, graceful shutdown
  - on_recognized / on_recognizing  — Azure-compatible callbacks

Uses Deepgram streaming API directly via websockets (no SDK required).
Language detection via Unicode script analysis (Devanagari vs. Roman).

Audio expected: PCM 16-bit signed, 8 kHz, mono (after mulaw→PCM conversion).
"""

import asyncio
import json
import re
from typing import Callable, Optional
from urllib.parse import urlencode

import websockets


# ---------------------------------------------------------------------------
# Language detection — Unicode script analysis
# ---------------------------------------------------------------------------

_DEVANAGARI = re.compile(r'[\u0900-\u097F]')
_ROMAN      = re.compile(r'[a-zA-Z]')


def _detect_language(transcript: str) -> str:
    hd = bool(_DEVANAGARI.search(transcript))
    hr = bool(_ROMAN.search(transcript))
    if hd and hr: return "HINGLISH"
    if hd:        return "HINDI"
    if hr:        return "ENGLISH"
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# Azure-compatible event wrappers (identical to SonioxSTTHandler — drop-in)
# ---------------------------------------------------------------------------

class _RecognizingEvent:
    def __init__(self, text: str):
        self.result = type("_R", (), {"text": text})()


class _RecognizedEvent:
    def __init__(self, text: str, language: str = "hi"):
        self.result = type("_R", (), {
            "text":     text,
            "reason":   "RecognizedSpeech",
            "language": language,
        })()


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------

class DeepgramSTTHandler:
    """Deepgram Speech-to-Text handler.

    Identical public surface to SonioxSTTHandler:
      • write_audio(pcm_audio)  — feed raw PCM16 chunks (8 kHz, mono)
      • start_async()           — connect to Deepgram WS, spin up tasks
      • stop_async()            — graceful shutdown

    Deepgram params:
      model=nova-2, language=hi, encoding=linear16,
      sample_rate=8000, channels=1, interim_results=true,
      smart_format=true, punctuate=true,
      utterance_end_ms=1800, vad_events=true
    """

    _URL_BASE = "wss://api.deepgram.com/v1/listen"

    _PARAMS = {
        "model":            "nova-2",
        "language":         "hi",
        "encoding":         "linear16",
        "sample_rate":      8000,
        "channels":         1,
        "interim_results":  "true",
        "smart_format":     "true",
        "punctuate":        "true",
        "endpointing":      "500",   # flush via speech_final after 500ms silence (safe for Hindi mid-clause pauses)
        "utterance_end_ms": "1000",  # fallback for noisy rooms; 1000ms is minimum useful value
        "vad_events":       "true",
    }

    def __init__(
        self,
        api_key:        str,
        on_recognized:  Optional[Callable] = None,
        on_recognizing: Optional[Callable] = None,
    ):
        self.api_key        = api_key
        self.on_recognized  = on_recognized
        self.on_recognizing = on_recognizing

        self.audio_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1000)
        self.is_running   = False
        self._ws          = None  # websockets connection

        # Buffer for is_final=True segments until speech_final or UtteranceEnd
        self._final_buffer: list[str] = []

        # True after speech_final flush so the trailing UtteranceEnd is ignored
        self._speech_final_fired: bool = False

        # VAD-driven finalization debounce
        self._debounce_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start_async(self):
        """Connect to Deepgram and start background send/receive tasks."""
        url = f"{self._URL_BASE}?{urlencode(self._PARAMS)}"
        print("🔵 Connecting to Deepgram STT...")
        try:
            self._ws = await websockets.connect(
                url,
                additional_headers={"Authorization": f"Token {self.api_key}"},
                ping_interval=10,
                ping_timeout=20,
            )
            self.is_running = True
            print("✅ Deepgram STT connected (nova-2, hi, linear16 8kHz)")

            asyncio.create_task(self._stream_audio_task(), name="deepgram_audio")
            asyncio.create_task(self._receive_events_task(), name="deepgram_events")
            print("✅ Deepgram STT ready for audio")

        except Exception as e:
            print(f"❌ Error connecting to Deepgram: {e}")
            self.is_running = False
            raise

    async def stop_async(self):
        """Gracefully close the Deepgram WS session."""
        print("🛑 Stopping Deepgram STT...")
        self.is_running = False
        self._cancel_debounce()

        if self._ws:
            try:
                await self._ws.send(json.dumps({"type": "CloseStream"}))
                await self._ws.close()
            except Exception as e:
                print(f"ℹ️  Deepgram close: {e}")
            self._ws = None

        print("✅ Deepgram STT stopped")

    # ------------------------------------------------------------------
    # Audio ingestion — sync, safe to call from any coroutine
    # ------------------------------------------------------------------

    def write_audio(self, pcm_audio: bytes):
        """Push a PCM16 audio chunk onto the send queue (non-blocking)."""
        if self.is_running:
            try:
                self.audio_queue.put_nowait(pcm_audio)
            except asyncio.QueueFull:
                pass  # drop chunk to avoid unbounded memory growth

    # ------------------------------------------------------------------
    # VAD-driven finalization
    # ------------------------------------------------------------------

    def speech_end_signal(self, debounce_ms: int = 200):
        """
        Called when VAD detects end of speech.
        Starts a debounce timer — if no new speech arrives within debounce_ms,
        sends Finalize to Deepgram so UtteranceEnd fires immediately instead of
        waiting for utterance_end_ms.
        """
        if not self.is_running or self._ws is None:
            return
        # Cancel any existing debounce timer
        self._cancel_debounce()
        loop = asyncio.get_event_loop()
        self._debounce_task = loop.create_task(self._debounce_finalize(debounce_ms))

    def speech_start_signal(self):
        """
        Called when VAD detects new speech (INTERRUPT).
        Cancels any pending debounce timer so we don't prematurely finalize
        a mid-sentence pause.
        """
        self._cancel_debounce()

    async def finalize(self):
        """Send Finalize to Deepgram — forces immediate UtteranceEnd flush."""
        if not self.is_running or self._ws is None:
            return
        try:
            await self._ws.send(json.dumps({"type": "Finalize"}))
            print("⚡ Deepgram Finalize sent (VAD-driven)")
        except Exception as e:
            print(f"⚠️ Deepgram Finalize error: {e}")

    def _cancel_debounce(self):
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
        self._debounce_task = None

    async def _debounce_finalize(self, debounce_ms: int):
        try:
            await asyncio.sleep(debounce_ms / 1000)
            await self.finalize()
        except asyncio.CancelledError:
            pass  # speech resumed before timer fired

    # ------------------------------------------------------------------
    # Background task: drain audio queue → Deepgram WS
    # ------------------------------------------------------------------

    async def _stream_audio_task(self):
        try:
            while self.is_running and self._ws:
                try:
                    chunk = await asyncio.wait_for(self.audio_queue.get(), timeout=0.1)
                    await self._ws.send(chunk)
                except asyncio.TimeoutError:
                    continue
                except websockets.exceptions.ConnectionClosed:
                    break
                except Exception as e:
                    if self.is_running:
                        print(f"❌ Deepgram audio stream error: {e}")
                    break
        except Exception as e:
            if self.is_running:
                print(f"❌ Deepgram audio task fatal: {e}")

    # ------------------------------------------------------------------
    # Background task: receive Deepgram events → callbacks
    # ------------------------------------------------------------------

    async def _receive_events_task(self):
        try:
            async for msg in self._ws:
                if not self.is_running:
                    break

                data = json.loads(msg)
                event_type = data.get("type")

                if event_type == "Results":
                    alts = data.get("channel", {}).get("alternatives", [])
                    if not alts:
                        continue
                    transcript = alts[0].get("transcript", "").strip()
                    if not transcript:
                        continue

                    is_final    = data.get("is_final", False)
                    speech_final = data.get("speech_final", False)

                    if not is_final:
                        # Interim result → on_recognizing
                        if self.on_recognizing:
                            try:
                                self.on_recognizing(_RecognizingEvent(transcript))
                            except Exception as e:
                                print(f"❌ on_recognizing error: {e}")
                    else:
                        # Accumulate final segment
                        self._final_buffer.append(transcript)
                        if speech_final:
                            # Fast path: endpointing silence detected → flush immediately.
                            # The UtteranceEnd that follows will be ignored.
                            self._speech_final_fired = True
                            self._flush_recognized()

                elif event_type == "UtteranceEnd":
                    if self._speech_final_fired:
                        # Already flushed on speech_final — ignore this trailing UtteranceEnd
                        self._speech_final_fired = False
                    elif self._final_buffer:
                        # Fallback: noisy room where speech_final never fired
                        self._flush_recognized()

                elif event_type == "Error":
                    print(f"❌ Deepgram error: {data.get('message', data)}")

        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            if self.is_running:
                print(f"❌ Deepgram receive error: {e}")
        finally:
            # Flush any remaining buffer on session end
            if self._final_buffer:
                self._flush_recognized()
            self.is_running = False
            print("ℹ️  Deepgram session finished")

    # ------------------------------------------------------------------
    # Internal: flush accumulated finals → on_recognized callback
    # ------------------------------------------------------------------

    def _flush_recognized(self):
        utterance = " ".join(self._final_buffer).strip()
        self._final_buffer.clear()
        if not utterance:
            return

        language = _detect_language(utterance)
        print(f"\n✅ Utterance complete [{language}]: '{utterance}'")

        if self.on_recognized:
            try:
                self.on_recognized(_RecognizedEvent(utterance, language=language))
            except Exception as e:
                print(f"❌ on_recognized error: {e}")
