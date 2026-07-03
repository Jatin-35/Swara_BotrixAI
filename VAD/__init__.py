"""
VAD Package - Voice Activity Detection
Provides Silero VAD integration for high-accuracy speech detection.
"""
from .silero_vad import SileroVADDetector, get_vad_detector, preload_model

__all__ = ['SileroVADDetector', 'get_vad_detector', 'preload_model']
