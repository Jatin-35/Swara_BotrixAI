"""
Interruption-Optimized VAD Service for Telephony
================================================
Production-ready configuration with balanced sensitivity.
ENHANCED WITH SPIKE DETECTION & FALSE INTERRUPT PREVENTION
"""

import asyncio
import websockets
import json
import numpy as np
import torch
import logging
from collections import deque
import time
from scipy import signal

# ==================== LOGGING SETUP ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== CONFIGURATION ====================
VAD_SAMPLE_RATE = 16000
VAD_CHUNK = 512             # 32ms chunks - optimal for interruption

# TELEPHONY-OPTIMIZED: Stricter thresholds to prevent spike-triggered false interrupts
START_THRESHOLD     = 0.75  # Raised from 0.65 — reduces spike false triggers
END_THRESHOLD       = 0.40  # When to consider speech ending
MIN_SILENCE_MS      = 150   # Wait after silence before resetting (ms)
GAIN_MULTIPLIER     = 1.0   # Removed 1.5x amplification — spikes are already loud
CONFIRMATION_FRAMES = 6     # Raised from 3 (~96ms) to 6 (~192ms) — spikes rarely sustain this long
MIN_SPEECH_MS       = 200   # NEW: Minimum sustained speech duration before firing INTERRUPT
SPIKE_ENERGY_RATIO  = 8.0   # NEW: If RMS jumps >8x in one chunk, treat as transient spike
SPIKE_COOLDOWN_MS   = 100   # NEW: After a spike, ignore VAD for this many ms

# Debug flags
DEBUG_AUDIO_STATS   = False
DEBUG_PROBABILITY   = False
DEBUG_STATE_CHANGES = False
DEBUG_TIMING        = False
DEBUG_BUFFER        = False

# Force CPU
device = torch.device("cpu")
print("\n" + "=" * 80)
print("🔧 DEVICE CONFIGURATION")
print("=" * 80)
print(f"✅ Using device: {device} (CPU is faster for VAD)")
print(f"📊 PyTorch version: {torch.__version__}")
print(f"🔢 NumPy version: {np.__version__}")
print("=" * 80 + "\n")

# Load Silero VAD model
print("=" * 80)
print("📥 LOADING SILERO VAD MODEL")
print("=" * 80)
logger.info("Loading from: snakers4/silero-vad")

model, utils = torch.hub.load(
    repo_or_dir='snakers4/silero-vad',
    model='silero_vad',
    force_reload=False,
    trust_repo=True
)
model = model.to(device)
model.eval()

print("✅ Model loaded successfully")
print(f"📦 Model type: {type(model)}")
print(f"🎯 Model device: {next(model.parameters()).device}")
print("=" * 80 + "\n")


def print_audio_stats(audio, label="Audio"):
    """Print detailed audio statistics for debugging."""
    if not DEBUG_AUDIO_STATS:
        return

    stats = {
        'min': np.min(audio),
        'max': np.max(audio),
        'mean': np.mean(audio),
        'std': np.std(audio),
        'rms': np.sqrt(np.mean(audio**2)),
        'length': len(audio)
    }

    print(f"🎵 {label} Stats:")
    print(f"   Length: {stats['length']} samples")
    print(f"   Range: [{stats['min']:.4f}, {stats['max']:.4f}]")
    print(f"   Mean: {stats['mean']:.4f}, Std: {stats['std']:.4f}")
    print(f"   RMS: {stats['rms']:.4f}")

    if stats['max'] >= 0.99 or stats['min'] <= -0.99:
        print(f"   ⚠️  WARNING: Possible clipping detected!")

    if stats['rms'] < 0.01:
        print(f"   🔇 Very quiet signal (RMS < 0.01)")

    return stats


class InterruptionVAD:
    """
    Production-ready interruption VAD with safety features.
    FIXED: Spike detection, sustained speech requirement, no amplification.
    """

    def __init__(
        self,
        model,
        sampling_rate=16000,
        start_threshold=START_THRESHOLD,
        end_threshold=END_THRESHOLD,
        min_silence_ms=MIN_SILENCE_MS,
        confirmation_frames=CONFIRMATION_FRAMES,
        min_speech_ms=MIN_SPEECH_MS,
        spike_energy_ratio=SPIKE_ENERGY_RATIO,
        spike_cooldown_ms=SPIKE_COOLDOWN_MS
    ):
        self.model = model
        self.sr = sampling_rate
        self.start_th = start_threshold
        self.end_th = end_threshold
        self.min_silence_samples = int(self.sr * min_silence_ms / 1000)
        self.confirmation_frames = confirmation_frames

        # FIX: Minimum sustained speech before firing INTERRUPT
        self.min_speech_samples = int(self.sr * min_speech_ms / 1000)

        # FIX: Spike detection config
        self.spike_energy_ratio = spike_energy_ratio
        self.spike_cooldown_samples = int(self.sr * spike_cooldown_ms / 1000)

        # State tracking
        self.in_speech = False
        self.last_voice_sample = 0
        self.sample_cursor = 0

        # Confirmation logic
        self.speech_frames = 0
        self.speech_start_sample = 0  # FIX: Track when candidate speech started

        # FIX: Spike detection state
        self.prev_rms = None           # Previous chunk RMS for ratio comparison
        self.spike_end_sample = 0      # Sample position when spike cooldown ends
        self.spikes_detected = 0       # Counter for logging

        # Buffers and stats
        self.prob_buffer = deque(maxlen=30)
        self.chunks_processed = 0
        self.max_prob_seen = 0.0
        self.interrupts_triggered = 0

        # Timing stats
        self.total_inference_time = 0.0
        self.max_inference_time = 0.0

    def reset(self):
        """Reset state for new conversation."""
        print(f"🔄 VAD reset: chunks={self.chunks_processed}, interrupts={self.interrupts_triggered}, spikes={self.spikes_detected}")
        logger.info(f"VAD reset: chunks={self.chunks_processed}, interrupts={self.interrupts_triggered}, spikes={self.spikes_detected}")

        self.in_speech = False
        self.last_voice_sample = 0
        self.sample_cursor = 0
        self.speech_frames = 0
        self.speech_start_sample = 0
        self.prev_rms = None
        self.spike_end_sample = 0
        self.spikes_detected = 0
        self.prob_buffer.clear()
        self.max_prob_seen = 0.0
        self.interrupts_triggered = 0
        self.total_inference_time = 0.0
        self.max_inference_time = 0.0

    def _is_spike(self, rms_energy):
        """
        Detect if current chunk is a transient spike rather than real speech.

        Real speech: energy ramps up gradually over multiple chunks.
        Shout/bang/noise spike: energy jumps suddenly by a large ratio in one chunk.

        Returns True if this chunk looks like a spike (should be ignored).
        """
        if self.prev_rms is None:
            # First chunk — no previous reference, can't detect spike
            self.prev_rms = rms_energy
            return False

        # Avoid division by near-zero
        ratio = rms_energy / (self.prev_rms + 1e-9)
        self.prev_rms = rms_energy

        if ratio > self.spike_energy_ratio:
            self.spikes_detected += 1
            # Set cooldown: ignore VAD output for next N samples
            self.spike_end_sample = self.sample_cursor + self.spike_cooldown_samples

            print(f"⚡ SPIKE DETECTED: energy jumped {ratio:.1f}x (threshold={self.spike_energy_ratio}x), "
                  f"total spikes={self.spikes_detected}")
            logger.warning(f"Spike detected: energy ratio={ratio:.1f}x, total={self.spikes_detected}")
            return True

        return False

    def _in_spike_cooldown(self):
        """Return True if we're still within the cooldown window after a spike."""
        return self.sample_cursor < self.spike_end_sample

    def process(self, chunk):
        """
        Process audio chunk and return event.

        Returns:
            "INTERRUPT" — human started speaking, stop the bot
            "END"       — speech ended
            None        — no event
        """
        self.sample_cursor += len(chunk)
        self.chunks_processed += 1

        if DEBUG_AUDIO_STATS and self.chunks_processed <= 5:
            print(f"\n{'=' * 80}")
            print(f"📦 CHUNK #{self.chunks_processed}")
            print(f"{'=' * 80}")
            print_audio_stats(chunk, f"Chunk #{self.chunks_processed}")

        # ── Step 1: RMS energy pre-filter ──────────────────────────────────
        rms_energy = np.sqrt(np.mean(chunk**2))

        if rms_energy < 0.01:
            # Truly silent — update prev_rms so the next real chunk
            # doesn't look like a sudden spike from silence
            self.prev_rms = rms_energy
            return None

        # ── Step 2: Spike detection ─────────────────────────────────────────
        # FIX: Check if this chunk is a sudden energy spike (shout, bang, etc.)
        if self._is_spike(rms_energy):
            # Reset speech confirmation — a spike doesn't count as speech frames
            self.speech_frames = 0
            self.speech_start_sample = 0
            return None

        # FIX: If we're in spike cooldown, suppress VAD to let the echo die down
        if self._in_spike_cooldown():
            return None

        # ── Step 3: VAD inference ───────────────────────────────────────────
        inference_start = time.time()

        with torch.no_grad():
            audio_tensor = torch.from_numpy(chunk).float()
            prob = self.model(audio_tensor, self.sr).item()

        inference_time = time.time() - inference_start
        self.total_inference_time += inference_time
        self.max_inference_time = max(self.max_inference_time, inference_time)

        self.prob_buffer.append(prob)
        self.max_prob_seen = max(self.max_prob_seen, prob)

        if DEBUG_PROBABILITY and prob > 0.5:
            logger.debug(f"High probability: {prob:.4f} (threshold={self.start_th})")

        if self.chunks_processed % 1000 == 0:
            avg_prob = sum(self.prob_buffer) / len(self.prob_buffer) if self.prob_buffer else 0
            print(f"📊 VAD Stats: chunks={self.chunks_processed}, interrupts={self.interrupts_triggered}, "
                  f"spikes={self.spikes_detected}, max_prob={self.max_prob_seen:.3f}, avg_prob={avg_prob:.3f}")
            logger.info(f"VAD Stats: chunks={self.chunks_processed}, interrupts={self.interrupts_triggered}, "
                        f"spikes={self.spikes_detected}, max_prob={self.max_prob_seen:.3f}")

        # ── Step 4: Speech state machine ────────────────────────────────────
        event = None

        if not self.in_speech:
            if prob >= self.start_th:
                self.speech_frames += 1

                # Mark when we first started seeing candidate speech
                if self.speech_frames == 1:
                    self.speech_start_sample = self.sample_cursor

                # FIX: Two-gate system
                # Gate 1: Enough consecutive frames (reduces noise false triggers)
                # Gate 2: Speech has been sustained long enough (reduces shout false triggers)
                if self.speech_frames >= self.confirmation_frames:
                    speech_duration_samples = self.sample_cursor - self.speech_start_sample
                    speech_duration_ms = speech_duration_samples / self.sr * 1000

                    if speech_duration_samples >= self.min_speech_samples:
                        # Both gates passed — this is real speech
                        self.in_speech = True
                        self.last_voice_sample = self.sample_cursor
                        self.interrupts_triggered += 1

                        print(f"⚠️  INTERRUPT TRIGGERED: prob={prob:.3f}, "
                              f"sustained={speech_duration_ms:.0f}ms, "
                              f"total_interrupts={self.interrupts_triggered}")
                        logger.info(f"INTERRUPT: prob={prob:.3f}, sustained={speech_duration_ms:.0f}ms, "
                                    f"total={self.interrupts_triggered}")

                        event = "INTERRUPT"
                    else:
                        # Gate 1 passed but not Gate 2 yet — keep waiting
                        if DEBUG_STATE_CHANGES:
                            logger.debug(f"Speech gate 1 passed, waiting for duration: "
                                         f"{speech_duration_ms:.0f}ms / {self.min_speech_samples / self.sr * 1000:.0f}ms")
            else:
                # Dropped below threshold — reset confirmation
                if self.speech_frames > 0:
                    if DEBUG_STATE_CHANGES:
                        logger.debug(f"Speech frames reset (was {self.speech_frames})")
                    self.speech_frames = 0
                    self.speech_start_sample = 0

        else:
            # Already in speech — use hysteresis to avoid choppy end detection
            hysteresis_threshold = self.end_th * 0.85

            if prob >= hysteresis_threshold:
                self.last_voice_sample = self.sample_cursor
            else:
                silence_duration = self.sample_cursor - self.last_voice_sample
                silence_ms = silence_duration / self.sr * 1000

                if silence_duration > self.min_silence_samples:
                    self.in_speech = False
                    self.speech_frames = 0
                    self.speech_start_sample = 0

                    print(f"🔇 Speech ended: silence={silence_ms:.0f}ms")
                    logger.debug(f"Speech ended: silence={silence_ms:.0f}ms")
                    event = "END"

        return event

    def get_stats(self):
        """Get VAD statistics."""
        avg_prob = sum(self.prob_buffer) / len(self.prob_buffer) if self.prob_buffer else 0
        avg_inference = self.total_inference_time / self.chunks_processed * 1000 if self.chunks_processed > 0 else 0

        return {
            'chunks_processed': self.chunks_processed,
            'max_prob': round(self.max_prob_seen, 4),
            'avg_prob': round(avg_prob, 4),
            'interrupts': self.interrupts_triggered,
            'spikes_detected': self.spikes_detected,
            'in_speech': self.in_speech,
            'avg_inference_ms': round(avg_inference, 2),
            'max_inference_ms': round(self.max_inference_time * 1000, 2)
        }


class VADService:
    """WebSocket VAD service optimized for telephony interruption."""

    def __init__(self):
        self.clients = {}
        self.stats = {
            'total_chunks_processed': 0,
            'total_interrupts': 0,
            'total_spikes': 0,
            'total_speech_segments': 0,
            'connections': 0,
            'active_connections': 0,
            'start_time': time.time()
        }

        print("🌐 VAD Service initialized")
        logger.info("VAD Service initialized")

    async def register_client(self, websocket):
        """Register new client with production VAD configuration."""
        client_id = id(websocket)

        print(f"✅ Client connected: {client_id} ({websocket.remote_address})")
        logger.info(f"New client connected: {client_id} ({websocket.remote_address})")

        self.clients[websocket] = {
            'vad': InterruptionVAD(model=model),
            'audio_cursor': 0.0,
            'audio_buffer': np.array([], dtype=np.float32),
            'id': client_id,
            'connected_at': time.time(),
            'chunks_received': 0,
            'bytes_received': 0
        }

        self.stats['connections'] += 1
        self.stats['active_connections'] = len(self.clients)

        config_msg = {
            'type': 'connected',
            'client_id': client_id,
            'config': {
                'device': 'cpu',
                'mode': 'interruption_optimized',
                'start_threshold': START_THRESHOLD,
                'end_threshold': END_THRESHOLD,
                'min_silence_ms': MIN_SILENCE_MS,
                'gain_multiplier': GAIN_MULTIPLIER,
                'confirmation_frames': CONFIRMATION_FRAMES,
                'min_speech_ms': MIN_SPEECH_MS,
                'spike_energy_ratio': SPIKE_ENERGY_RATIO,
                'spike_cooldown_ms': SPIKE_COOLDOWN_MS
            }
        }

        await websocket.send(json.dumps(config_msg))

    async def unregister_client(self, websocket):
        """Unregister client and log session stats."""
        if websocket in self.clients:
            client = self.clients[websocket]
            vad = client['vad']
            session_duration = time.time() - client['connected_at']

            print(f"👋 Client disconnected: {client['id']}, "
                  f"duration={session_duration:.1f}s, "
                  f"interrupts={vad.interrupts_triggered}, "
                  f"spikes={vad.spikes_detected}, "
                  f"chunks={vad.chunks_processed}")
            logger.info(f"Client disconnected: {client['id']}, duration={session_duration:.1f}s, "
                        f"interrupts={vad.interrupts_triggered}, spikes={vad.spikes_detected}")

            del self.clients[websocket]
            self.stats['active_connections'] = len(self.clients)

    async def process_audio_chunk(self, websocket, audio_data: list, sample_rate: int):
        """Process audio chunk for interruption detection."""
        if websocket not in self.clients:
            logger.warning("⚠️  Received audio for unregistered client")
            return

        client = self.clients[websocket]
        vad = client['vad']
        client['chunks_received'] += 1
        client['bytes_received'] += len(audio_data) * 2  # int16 = 2 bytes

        try:
            # Convert to float32
            audio_array = np.array(audio_data, dtype=np.int16)
            audio_float32 = audio_array.astype(np.float32) / 32768.0

            # FIX: GAIN_MULTIPLIER = 1.0, so this is effectively a no-op.
            # Spikes are already loud — amplifying them made false triggers worse.
            audio_gained = np.clip(audio_float32 * GAIN_MULTIPLIER, -1.0, 1.0)

            # Resample to 16kHz if needed
            if sample_rate == 8000:
                audio_resampled = signal.resample_poly(audio_gained, 2, 1)
            elif sample_rate == 48000:
                audio_resampled = signal.resample_poly(audio_gained, 1, 3)
            elif sample_rate != VAD_SAMPLE_RATE:
                num_samples = int(len(audio_gained) * VAD_SAMPLE_RATE / sample_rate)
                audio_resampled = signal.resample(audio_gained, num_samples)
            else:
                audio_resampled = audio_gained

            chunk_duration = len(audio_resampled) / VAD_SAMPLE_RATE
            client['audio_cursor'] += chunk_duration

            client['audio_buffer'] = np.concatenate([client['audio_buffer'], audio_resampled])

            vad_chunks_processed = 0
            while len(client['audio_buffer']) >= VAD_CHUNK:
                chunk = client['audio_buffer'][:VAD_CHUNK]
                client['audio_buffer'] = client['audio_buffer'][VAD_CHUNK:]
                vad_chunks_processed += 1

                event = vad.process(chunk)

                if event == "INTERRUPT":
                    self.stats['total_interrupts'] += 1

                    response = {
                        'type': 'interrupt',
                        'reason': 'vad_speech_start',
                        'audio_cursor': round(client['audio_cursor'], 3),
                        'confidence': round(vad.max_prob_seen, 4),
                        'vad_stats': vad.get_stats()
                    }

                    print(f"📤 Sending INTERRUPT to client {client['id']}: confidence={response['confidence']:.3f}")
                    await websocket.send(json.dumps(response))

                elif event == "END":
                    self.stats['total_speech_segments'] += 1

                    response = {
                        'type': 'speech_end',
                        'audio_cursor': round(client['audio_cursor'], 3),
                        'vad_stats': vad.get_stats()
                    }

                    print(f"📤 Sending SPEECH_END to client {client['id']}")
                    await websocket.send(json.dumps(response))

            self.stats['total_chunks_processed'] += vad_chunks_processed
            self.stats['total_spikes'] = sum(
                c['vad'].spikes_detected for c in self.clients.values()
            )

        except Exception as e:
            print(f"❌ Error processing audio for client {client['id']}: {e}")
            logger.error(f"Error processing audio for client {client['id']}: {e}", exc_info=True)

    def get_service_stats(self):
        """Get service-wide statistics."""
        uptime = time.time() - self.stats['start_time']
        return {
            **self.stats,
            'uptime_seconds': round(uptime, 1),
            'uptime_formatted': time.strftime('%H:%M:%S', time.gmtime(uptime))
        }


# Global service instance
vad_service = VADService()


async def handle_client(websocket):
    """Handle WebSocket client connection."""
    await vad_service.register_client(websocket)

    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                msg_type = data.get('type')

                if msg_type == 'audio_chunk':
                    audio_data = data.get('audio', [])
                    sample_rate = data.get('sample_rate', 8000)
                    await vad_service.process_audio_chunk(websocket, audio_data, sample_rate)

                elif msg_type == 'config':
                    client = vad_service.clients.get(websocket)
                    if client:
                        vad = client['vad']

                        if 'start_threshold' in data:
                            vad.start_th = data['start_threshold']
                        if 'end_threshold' in data:
                            vad.end_th = data['end_threshold']
                        if 'min_silence_ms' in data:
                            vad.min_silence_samples = int(VAD_SAMPLE_RATE * data['min_silence_ms'] / 1000)
                        # FIX: Allow runtime tuning of new spike params too
                        if 'spike_energy_ratio' in data:
                            vad.spike_energy_ratio = data['spike_energy_ratio']
                        if 'min_speech_ms' in data:
                            vad.min_speech_samples = int(VAD_SAMPLE_RATE * data['min_speech_ms'] / 1000)
                        if 'spike_cooldown_ms' in data:
                            vad.spike_cooldown_samples = int(VAD_SAMPLE_RATE * data['spike_cooldown_ms'] / 1000)

                        print(f"🎛️  Config updated for client {client['id']}: "
                              f"start_th={vad.start_th}, end_th={vad.end_th}, "
                              f"spike_ratio={vad.spike_energy_ratio}")
                        logger.info(f"Config updated for client {client['id']}: "
                                    f"start_th={vad.start_th}, end_th={vad.end_th}, "
                                    f"spike_ratio={vad.spike_energy_ratio}")

                        response = {
                            'type': 'config_updated',
                            'start_threshold': vad.start_th,
                            'end_threshold': vad.end_th,
                            'min_silence_ms': vad.min_silence_samples / vad.sr * 1000,
                            'spike_energy_ratio': vad.spike_energy_ratio,
                            'min_speech_ms': vad.min_speech_samples / vad.sr * 1000,
                            'spike_cooldown_ms': vad.spike_cooldown_samples / vad.sr * 1000
                        }
                        await websocket.send(json.dumps(response))

                elif msg_type == 'reset':
                    client = vad_service.clients.get(websocket)
                    if client:
                        client['vad'].reset()
                        client['audio_cursor'] = 0.0
                        client['audio_buffer'] = np.array([], dtype=np.float32)
                        client['chunks_received'] = 0
                        client['bytes_received'] = 0

                        await websocket.send(json.dumps({'type': 'reset_ok'}))

                elif msg_type == 'ping':
                    await websocket.send(json.dumps({'type': 'pong'}))

                elif msg_type == 'stats':
                    client = vad_service.clients.get(websocket)
                    response = {
                        'type': 'stats',
                        'service': vad_service.get_service_stats()
                    }
                    if client:
                        response['client'] = client['vad'].get_stats()

                    await websocket.send(json.dumps(response))

                else:
                    logger.warning(f"❓ Unknown message type: {msg_type}")

            except json.JSONDecodeError as e:
                print(f"❌ Invalid JSON received: {e}")
                logger.error(f"Invalid JSON received: {e}")

            except Exception as e:
                print(f"❌ Error handling message: {e}")
                logger.error(f"Error handling message: {e}", exc_info=True)

    except websockets.exceptions.ConnectionClosed as e:
        print(f"🔌 Connection closed: {e}")
        logger.info(f"Connection closed: {e}")

    except Exception as e:
        print(f"❌ Connection error: {e}")
        logger.error(f"Connection error: {e}", exc_info=True)

    finally:
        await vad_service.unregister_client(websocket)


async def main():
    """Start the VAD service."""
    port = 8765

    print(f"\n🚀 VAD Service starting on ws://0.0.0.0:{port}")
    print(f"⚙️  Config: start_th={START_THRESHOLD}, end_th={END_THRESHOLD}, "
          f"min_silence={MIN_SILENCE_MS}ms, min_speech={MIN_SPEECH_MS}ms, "
          f"spike_ratio={SPIKE_ENERGY_RATIO}x, gain={GAIN_MULTIPLIER}x")
    print(f"✅ Service ready. Waiting for connections...\n")
    logger.info(f"VAD Service starting on ws://0.0.0.0:{port}")

    async with websockets.serve(
        handle_client,
        "0.0.0.0",
        port,
        max_size=10**7,
        ping_interval=20,
        ping_timeout=10
    ):
        await asyncio.Future()


if __name__ == "__main__":
    import sys
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n👋 Shutting down gracefully")
        print(f"📊 Final stats: connections={vad_service.stats['connections']}, "
              f"chunks={vad_service.stats['total_chunks_processed']}, "
              f"interrupts={vad_service.stats['total_interrupts']}, "
              f"spikes={vad_service.stats['total_spikes']}")
        logger.info("Shutting down gracefully")
        sys.exit(0)
    except Exception as e:
        print(f"\n🔥 FATAL ERROR: {e}")
        logger.critical(f"FATAL ERROR: {e}", exc_info=True)
        sys.exit(1)