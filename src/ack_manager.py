"""
Pre-loaded Acknowledgment Manager — multi-language.

Loads all WAV ack files from src/meera_acks/<lang>/*.wav into memory
at startup as raw PCM bytes. Returns instant audio — zero TTS latency.

Supported language folders: hi, en, ta, te, kn, ml, mr
Map Azure-style lang codes (hi-IN, ta-IN ...) to folder names via LANG_FOLDER_MAP.

Usage:
    manager = PreloadedAckManager()
    name, pcm = manager.get_random_ack('hi-IN')   # instant!
    await websocket.send_bytes(pcm)                # send to Cube
"""

import os
import wave
import random
from pathlib import Path


# Language code -> folder name under meera_acks/
# Supports Azure BCP-47 codes, Deepgram short codes, and Deepgram uppercase codes
LANG_FOLDER_MAP = {
    # Azure BCP-47
    "hi-IN":    "hi",
    "en-IN":    "en",
    # Deepgram short codes
    "hi":       "hi",
    "en":       "en",
    # Deepgram uppercase codes (from deepgram_stt._detect_language)
    "HINDI":    "hi",
    "ENGLISH":  "en",
    "HINGLISH": "hi",   # Hindi acks for Hinglish speakers
    "UNKNOWN":  "hi",   # fallback to Hindi
}


class PreloadedAckManager:
    """Manages pre-recorded acknowledgment audio for instant playback."""

    def __init__(self, ack_dir: str = None):
        if ack_dir is None:
            ack_dir = os.path.join(os.path.dirname(__file__), 'meera_acks')

        self.ack_dir = ack_dir
        # Dict: folder_name -> list of (name, pcm_bytes)
        self._acks: dict[str, list] = {}
        self._last_used: dict[str, str] = {}
        self._load_all()

    def _load_wav_as_pcm(self, wav_path: str) -> bytes:
        """Load WAV -> raw PCM bytes (strips WAV header)."""
        with wave.open(wav_path, 'rb') as wf:
            return wf.readframes(wf.getnframes())

    def _load_all(self):
        """Load all ack WAV files from disk into memory."""
        if not os.path.isdir(self.ack_dir):
            print(f"⚠️  Ack directory not found: {self.ack_dir}")
            print("   Run 'python src/generate_acks.py' to create ack audio files.")
            return

        total = 0
        for folder in sorted(os.listdir(self.ack_dir)):
            lang_dir = os.path.join(self.ack_dir, folder)
            if not os.path.isdir(lang_dir):
                continue

            acks = []
            for f in sorted(os.listdir(lang_dir)):
                if not f.endswith('.wav'):
                    continue
                try:
                    pcm  = self._load_wav_as_pcm(os.path.join(lang_dir, f))
                    name = Path(f).stem
                    dur  = len(pcm) / 16000
                    acks.append((name, pcm))
                    print(f"  ✅ meera_acks/{folder}/{f} -> {len(pcm):,} bytes ({dur:.2f}s)")
                    total += 1
                except Exception as e:
                    print(f"  ❌ meera_acks/{folder}/{f}: {e}")

            # Always include a silent option for natural variety
            acks.append(("silent", b""))
            self._acks[folder] = acks

        print(f"📢 PreloadedAckManager: {total} acks loaded across {len(self._acks)} languages")

    # ----------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------

    def get_random_ack(self, lang_code: str = 'hi-IN') -> tuple:
        """Return random (name, pcm_bytes) for the given language code.

        Args:
            lang_code: Azure-style code e.g. 'hi-IN', 'ta-IN', 'en-IN'
                       Also accepts short folder names like 'hi', 'ta'.

        Returns:
            (name, pcm_bytes) — pcm_bytes may be b'' for the silent option.
        """
        # Resolve to folder name
        folder = LANG_FOLDER_MAP.get(lang_code)
        if folder is None:
            # Prefix match e.g. 'hi' from 'hi-IN-something'
            folder = lang_code.split('-')[0].lower()
        if folder not in self._acks:
            folder = 'hi'  # last resort fallback to Hindi

        acks = self._acks.get(folder, self._acks.get('hi', [("none", b"")]))
        if not acks:
            return ("none", b"")

        last = self._last_used.get(folder)
        available = [a for a in acks if a[0] != last]
        if not available:
            available = acks

        chosen = random.choice(available)
        self._last_used[folder] = chosen[0]
        return chosen

    def get_ack_duration(self, pcm_bytes: bytes) -> float:
        """Duration in seconds (8kHz, 16-bit mono = 16000 bytes/sec)."""
        return len(pcm_bytes) / 16000 if pcm_bytes else 0.0

    def available_languages(self) -> list:
        """List of loaded language folder names."""
        return list(self._acks.keys())
