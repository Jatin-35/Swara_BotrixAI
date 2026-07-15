from builtins import print, len, str, Exception, ValueError
import sys, os
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
import re
import json
import base64
import asyncio
from fastapi import FastAPI, WebSocket, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse, Response
from fastapi.websockets import WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from dotenv import load_dotenv
import uvicorn
import struct  # For Cube binary protocol
import time
import azure.cognitiveservices.speech as speechsdk  # kept for any legacy refs
import threading
import concurrent.futures
import aiohttp
import audioop
from collections import deque
import io
import wave
from system_prompt import system_message, FLOW_PROMPTS
from ack_manager import PreloadedAckManager
import urllib.request
import urllib.parse
import random
from datetime import datetime, timedelta
import pytz
import xml.sax.saxutils as saxutils
import uuid  # For call session IDs
from pathlib import Path  # For call logging
from typing import Optional, Dict, Any  # For type hints
from dataclasses import dataclass        # For OutboundCallContext in concurrent registry
from deepgram_stt import DeepgramSTTHandler  # Deepgram STT integration
from utterance_buffer import UtteranceBuffer, UtteranceBufferConfig  # Utterance cancellation + combining
import database as db  # Database for call logs and conversation tracking
import websockets  # For VAD service WebSocket connection
import numpy as np  # For VAD audio processing
import asyncio, sys
from analysis_engine import sync_not_connected_call
from database import get_lead_by_phone, update_lead_status
import lead_files as lead_files_mod  # Faber Excel lead-list management (upload/history/edit/export)
from lead_knowledge import build_lead_context
from campaign_manager import campaign_manager
load_dotenv()

# Azure OpenAI Configuration
AZURE_OPENAI_API_KEY = "BV5Dezpb1ghuPZ2fizGQSu9vaPNVC8n4jG8HC6uxtBwGfTJxjWoDJQQJ99CFAC77bzfXJ3w3AAAAACOGYYQh"
AZURE_OPENAI_ENDPOINT = "https://voice-agents-agentic-resource.services.ai.azure.com/"
OPENAI_API_VERSION = "2024-12-01-preview"
AZURE_OPENAI_DEPLOYMENT = "gpt-4.1-mini"

# Deepgram STT Configuration
DEEPGRAM_API_KEY = "370d8eaa7147369c72e440934fd68994bc638485"

# Azure TTS Configuration
AZURE_SPEECH_KEY = "E7mHLG7UxtcWNew7wQlBrfg6F7I2Kjsxek5dsAaXL9qpxpUPilANJQQJ99CFACGhslBXJ3w3AAAYACOGAJEp"
AZURE_SPEECH_REGION = "centralindia"
AZURE_TTS_VOICE = "en-IN-Meera:DragonHDLatestNeural"

# Cube VoIP Configuration
CUBE_CLICK2CALL_URL = os.getenv('CUBE_CLICK2CALL_URL', 'https://cubesoftservices.com/QuickCallRHICL/Click2Call.php')
CUBE_CAMPAIGN_ID = os.getenv('CUBE_CAMPAIGN_ID', 'BotrixAI_Bot')
CUBE_DID = os.getenv('CUBE_DID', '08037367249')
CUBE_WEBSOCKET_PORT = int(os.getenv('CUBE_WEBSOCKET_PORT', '8040'))

# Cube Audio Configuration (as per Cube spec)
CUBE_SAMPLE_RATE = 8000  # Hz (Cube uses 8kHz telephony standard)
CUBE_BIT_DEPTH = 16  # bits
CUBE_CHANNELS = 1  # Mono
CUBE_CHUNK_SIZE = 3200  # bytes (200ms at 8kHz 16-bit mono)
CUBE_CHUNK_DELAY = 0.2  # seconds (200ms)

# ── Announcement mode (one-way broadcast) ────────────────────────────────────
# When True, every /swara_voicebot call simply plays a fixed pre-recorded clip
# once the line is up, then hangs up — NO STT / LLM / VAD / CLI-DNI / conversation.
# The outbound call record already exists (created at /make-call) and the
# /getCallStatus + recording webhooks fire independently, so call tracking stays intact.
ANNOUNCEMENT_MODE = True
ANNOUNCEMENT_PCM_PATH = os.path.join(os.path.dirname(__file__), "announcement", "announcement_8k_mono_s16le.pcm")
_announcement_pcm_cache = None  # lazily-loaded raw PCM bytes (8kHz / 16-bit / mono / LE)

def _load_announcement_pcm() -> bytes:
    """Load + cache the pre-converted announcement clip (Cube-format raw PCM)."""
    global _announcement_pcm_cache
    if _announcement_pcm_cache is None:
        with open(ANNOUNCEMENT_PCM_PATH, "rb") as _f:
            _announcement_pcm_cache = _f.read()
        print(f"📢 Announcement clip loaded: {len(_announcement_pcm_cache)} bytes "
              f"(~{len(_announcement_pcm_cache)/16000:.1f}s)")
    return _announcement_pcm_cache

# Cube Binary Protocol Message Types
CUBE_MSG_HANGUP = 0x00
CUBE_MSG_AUDIO = 0x10
CUBE_MSG_CLI_DNI = 0x20
CUBE_MSG_DTMF = 0x30

SYSTEM_MESSAGE = system_message


# STARTUP Date/Time Initialization - ULTRA OPTIMIZED
# Initialize all date/time data once at startup for maximum performance
IST_TIMEZONE = pytz.timezone('Asia/Kolkata')

# Helper function for logging to Supabase (explicit calls only)
async def log_to_supabase_async(message: str, level: str = "INFO", record_id: str = None, details: dict = None):
    """Async fire-and-forget logging to Supabase (non-blocking)."""
    from async_db import log_to_supabase_async as async_log
    asyncio.create_task(async_log(message, level, record_id, details))

def log_to_supabase(message: str, level: str = "INFO", record_id: str = None, details: dict = None):
    """Legacy sync wrapper - redirects to async version."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(log_to_supabase_async(message, level, record_id, details))
        else:
            # Fallback for non-async contexts
            if db:
                db.log_console(message, level, record_id, details)
    except Exception as e:
        print(f"⚠️ Logging error (non-critical): {e}")

def initialize_startup_datetime():
    """Initialize all date/time data once at startup."""
    print("🚀 Initializing startup date/time data...")
    
    # Get current time once at startup
    startup_now = datetime.now(IST_TIMEZONE)
    
    # Pre-calculate all common date/time values
    startup_tomorrow = startup_now + timedelta(days=1)
    startup_day_after_tomorrow = startup_now + timedelta(days=2)
    startup_next_week_start = startup_now + timedelta(days=7)
    startup_next_week_end = startup_now + timedelta(days=13)
    
    # Generate future dates for appointments
    startup_future_dates = []
    for i in range(7):
        future_date = startup_now + timedelta(days=i)
        startup_future_dates.append({
            'date': future_date.strftime('%Y-%m-%d'),
            'display': future_date.strftime('%B %d, %Y'),
            'day': future_date.strftime('%A'),
            'relative': 'Today' if i == 0 else f'Day {i+1}'
        })
    
    # Store all startup data globally
    global STARTUP_DATETIME_DATA
    STARTUP_DATETIME_DATA = {
        'startup_now': startup_now,
        'startup_date': startup_now.strftime('%Y-%m-%d'),
        'startup_datetime': startup_now.strftime('%B %d, %Y, %I:%M %p IST'),
        'startup_time': startup_now.strftime('%H:%M'),
        'startup_tomorrow': startup_tomorrow,
        'startup_day_after_tomorrow': startup_day_after_tomorrow,
        'startup_next_week_start': startup_next_week_start,
        'startup_next_week_end': startup_next_week_end,
        'startup_future_dates': startup_future_dates
    }
    
    print(f"✅ Startup date/time initialized: {STARTUP_DATETIME_DATA['startup_date']} {STARTUP_DATETIME_DATA['startup_time']} IST")
    return STARTUP_DATETIME_DATA

# Initialize startup data
STARTUP_DATETIME_DATA = initialize_startup_datetime()

def get_startup_system_message():
    """Generate system message with startup date/time data."""
    data = STARTUP_DATETIME_DATA
    
    # Create dynamic date section with startup data
    dynamic_date_section = f"""
Current Date Information (Startup Data)
- TODAY'S DATE: {data['startup_now'].strftime('%B %d, %Y (%A)')}
- CURRENT TIME: {data['startup_time']} IST
- For appointment scheduling, use the startup date: {data['startup_date']}
- Current date format: "{data['startup_now'].strftime('%B %d, %Y')}" or "{data['startup_now'].strftime('%dth %B, %Y')}"
- Current time format: "{data['startup_time']} IST" or "{data['startup_now'].strftime('%I:%M %p')} IST"
- For appointment booking, suggest dates starting from {data['startup_date']} onwards
- When user says "tomorrow" - it means {data['startup_tomorrow'].strftime('%B %d, %Y (%A)')}
- When user says "day after tomorrow" - it means {data['startup_day_after_tomorrow'].strftime('%B %d, %Y (%A)')}
- When user says "next week" - it means {data['startup_next_week_start'].strftime('%B %d')}-{data['startup_next_week_end'].strftime('%B %d, %Y')}

Available Appointment Dates (Startup Data):
{chr(10).join([f"- {d['display']} ({d['day']}) - {d['date']}" for d in data['startup_future_dates']])}

IMPORTANT: Use the startup date/time data provided above. All date operations should reference this startup data.
"""
    
    # Replace the static date section in system message
    updated_message = SYSTEM_MESSAGE.replace(
        """Current Date Information
- TODAY'S DATE: September 20, 2025 (Saturday)
- CURRENT TIME: 12:52 PM IST
- For appointment scheduling, use datetime.now() with IST timezone
- Current date format: "September 20, 2025" or "20th September, 2025"
- Current time format: "12:52 PM IST" or "12:52 IST"
- For appointment booking, suggest dates starting from current date onwards
- When user says "tomorrow" - it means September 21, 2025 (Sunday)
- When user says "day after tomorrow" - it means September 22, 2025 (Monday)
- When user says "next week" - it means September 27-October 3, 2025
- Use Python datetime library: from datetime import datetime, timedelta
- IST timezone: pytz.timezone('Asia/Kolkata') or datetime.now() + timedelta(hours=5, minutes=30)

IST Date/Time Utility Functions (Available in api_integration.py):
- get_current_ist_date(): Returns current date in "YYYY-MM-DD" format for API calls
- get_current_ist_datetime(): Returns current datetime in "September 20, 2025, 12:52 PM IST" format for display
- get_future_dates(): Returns next 7 days starting from today for appointment suggestions
- format_appointment_date(date): Converts API date format to display format
- get_ist_time(): Returns current IST time in HH:MM format

IMPORTANT: Always use these functions for date/time operations instead of hardcoded dates""",
        dynamic_date_section.strip()
    )
    
    return updated_message

# Generate startup system message once
STARTUP_SYSTEM_MESSAGE = get_startup_system_message()

# Pre-loaded acknowledgment audio — loads WAV files into memory at startup (0ms TTS latency)
print("📢 Loading pre-recorded acknowledgments...")
preloaded_ack_manager = PreloadedAckManager()

def get_current_ist_date():
    """Returns startup date in YYYY-MM-DD format for API calls."""
    return STARTUP_DATETIME_DATA['startup_date']

def get_current_ist_datetime():
    """Returns startup datetime in 'September 20, 2025, 12:52 PM IST' format for display."""
    return STARTUP_DATETIME_DATA['startup_datetime']

def get_current_ist_time():
    """Returns startup IST time in HH:MM format."""
    return STARTUP_DATETIME_DATA['startup_time']

def get_future_dates(days=7):
    """Returns startup future dates for appointment suggestions."""
    if days == 7:
        return STARTUP_DATETIME_DATA['startup_future_dates']
    else:
        # For custom days, generate from startup data
        startup_now = STARTUP_DATETIME_DATA['startup_now']
        dates = []
        for i in range(days):
            future_date = startup_now + timedelta(days=i)
            dates.append({
                'date': future_date.strftime('%Y-%m-%d'),
                'display': future_date.strftime('%B %d, %Y'),
                'day': future_date.strftime('%A'),
                'relative': 'Today' if i == 0 else f'Day {i+1}'
            })
        return dates

def format_appointment_date(date_str):
    """Converts API date format (YYYY-MM-DD) to display format."""
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        return date_obj.strftime('%B %d, %Y (%A)')
    except ValueError:
        return date_str

def get_dynamic_system_message():
    """Returns startup system message with pre-computed date/time information."""
    return STARTUP_SYSTEM_MESSAGE


def _apply_date_injection(raw_prompt: str) -> str:
    """Apply startup date/time injection to any flow prompt (same replacement as get_startup_system_message)."""
    data = STARTUP_DATETIME_DATA
    dynamic_date_section = f"""Current Date Information (Startup Data)
- TODAY'S DATE: {data['startup_now'].strftime('%B %d, %Y (%A)')}
- CURRENT TIME: {data['startup_time']} IST
- For appointment scheduling, use the startup date: {data['startup_date']}
- Current date format: "{data['startup_now'].strftime('%B %d, %Y')}" or "{data['startup_now'].strftime('%dth %B, %Y')}"
- Current time format: "{data['startup_time']} IST" or "{data['startup_now'].strftime('%I:%M %p')} IST"
- For appointment booking, suggest dates starting from {data['startup_date']} onwards
- When user says "tomorrow" - it means {data['startup_tomorrow'].strftime('%B %d, %Y (%A)')}
- When user says "day after tomorrow" - it means {data['startup_day_after_tomorrow'].strftime('%B %d, %Y (%A)')}
- When user says "next week" - it means {data['startup_next_week_start'].strftime('%B %d')}-{data['startup_next_week_end'].strftime('%B %d, %Y')}

Available Appointment Dates (Startup Data):
{chr(10).join([f"- {d['display']} ({d['day']}) - {d['date']}" for d in data['startup_future_dates']])}

IMPORTANT: Use the startup date/time data provided above. All date operations should reference this startup data."""
    return raw_prompt.replace(
        """Current Date Information
- TODAY'S DATE: September 20, 2025 (Saturday)
- CURRENT TIME: 12:52 PM IST
- For appointment scheduling, use datetime.now() with IST timezone
- Current date format: "September 20, 2025" or "20th September, 2025"
- Current time format: "12:52 PM IST" or "12:52 IST"
- For appointment booking, suggest dates starting from current date onwards
- When user says "tomorrow" - it means September 21, 2025 (Sunday)
- When user says "day after tomorrow" - it means September 22, 2025 (Monday)
- When user says "next week" - it means September 27-October 3, 2025
- Use Python datetime library: from datetime import datetime, timedelta
- IST timezone: pytz.timezone('Asia/Kolkata') or datetime.now() + timedelta(hours=5, minutes=30)

IST Date/Time Utility Functions (Available in api_integration.py):
- get_current_ist_date(): Returns current date in "YYYY-MM-DD" format for API calls
- get_current_ist_datetime(): Returns current datetime in "September 20, 2025, 12:52 PM IST" format for display
- get_future_dates(): Returns next 7 days starting from today for appointment suggestions
- format_appointment_date(date): Converts API date format to display format
- get_ist_time(): Returns current IST time in HH:MM format

IMPORTANT: Always use these functions for date/time operations instead of hardcoded dates""",
        dynamic_date_section,
    )

# Retry Configuration for Azure OpenAI API
class RetryConfig:
    """Configuration for Azure OpenAI API retry logic."""
    MAX_RETRIES = 3
    BASE_DELAY = 1.0  # Base delay in seconds
    MAX_DELAY = 8.0   # Maximum delay in seconds
    EXPONENTIAL_BASE = 2.0  # Exponential backoff base
    JITTER = True     # Add random jitter to prevent thundering herd

async def retry_with_exponential_backoff(func, *args, **kwargs):
    """Retry function with exponential backoff for Azure OpenAI API calls."""
    last_exception = None
    
    for attempt in range(RetryConfig.MAX_RETRIES + 1):
        try:
            print(f"🔄 Azure OpenAI API attempt {attempt + 1}/{RetryConfig.MAX_RETRIES + 1}")
            result = await func(*args, **kwargs)
            if attempt > 0:
                print(f"✅ Azure OpenAI API succeeded on attempt {attempt + 1}")
            return result
            
        except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionError) as e:
            last_exception = e
            error_msg = str(e).lower()
            
            # Check if it's a retryable error
            retryable_errors = [
                'connection timeout',
                'timeout',
                'connection error',
                'network error',
                'connection reset',
                'connection refused',
                'temporary failure',
                'service unavailable'
            ]
            
            is_retryable = any(error in error_msg for error in retryable_errors)
            
            if not is_retryable or attempt == RetryConfig.MAX_RETRIES:
                print(f"❌ Azure OpenAI API non-retryable error or max retries reached: {e}")
                break
            
            # Calculate delay with exponential backoff
            delay = min(
                RetryConfig.BASE_DELAY * (RetryConfig.EXPONENTIAL_BASE ** attempt),
                RetryConfig.MAX_DELAY
            )
            
            # Add jitter to prevent thundering herd
            if RetryConfig.JITTER:
                jitter = random.uniform(0, delay * 0.1)  # 10% jitter
                delay += jitter
            
            print(f"⏳ Azure OpenAI API retry in {delay:.2f}s (attempt {attempt + 1}/{RetryConfig.MAX_RETRIES + 1})")
            await asyncio.sleep(delay)
    
    # If all retries failed, raise the last exception
    raise last_exception

# Date/Time helper functions are defined above (lines 171-201)

# HTTP Session Manager for Azure OpenAI calls
class HTTPSessionManager:
    def __init__(self):
        self._session = None
        
    async def get_session(self):
        if self._session is None or self._session.closed:
            # Optimized connector settings
            connector = aiohttp.TCPConnector(
                limit=50,              # Reduced from 100 - adequate for voice bot
                limit_per_host=10,     # Reduced from 30 - better resource usage
                keepalive_timeout=60,  # Increased from 30 - better connection reuse
                enable_cleanup_closed=True,
                ttl_dns_cache=600,     # Increased from 300 - longer DNS cache
                force_close=False      # Enable connection pooling
            )
            timeout = aiohttp.ClientTimeout(
                total=10,
                connect=3,
                sock_read=5
            )
            self._session = aiohttp.ClientSession(
                connector=connector, 
                timeout=timeout
            )
        return self._session
    
    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

http_manager = HTTPSessionManager()

# Response Cache for TTS with TTL support
class ResponseCache:
    def __init__(self, max_size=100, ttl_seconds=3600):
        self.cache = {}
        self.access_order = deque()
        self.timestamps = {}  # Track when cached
        self.max_size = max_size
        self.ttl = ttl_seconds  # Time to live in seconds (default 1 hour)
    
    def get(self, key):
        if key in self.cache:
            # Check if expired
            if time.time() - self.timestamps.get(key, 0) > self.ttl:
                print(f"🗑️ Cache entry expired: {key[:30]}...")
                self.access_order.remove(key)
                del self.cache[key]
                del self.timestamps[key]
                return None
            
            # Update access order
            self.access_order.remove(key)
            self.access_order.append(key)
            return self.cache[key]
        return None
    
    def set(self, key, value):
        if key in self.cache:
            self.access_order.remove(key)
        elif len(self.cache) >= self.max_size:
            # Remove LRU item
            lru_key = self.access_order.popleft()
            del self.cache[lru_key]
            if lru_key in self.timestamps:
                del self.timestamps[lru_key]
        
        self.cache[key] = value
        self.timestamps[key] = time.time()
        self.access_order.append(key)

response_cache = ResponseCache()

# Performance Metrics for monitoring and optimization
class PerformanceMetrics:
    """Track performance metrics for optimization and monitoring."""
    def __init__(self):
        self.vad_triggers = 0
        self.vad_false_positives = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.total_responses = 0
        self.total_response_time = 0.0
        self.llm_calls = 0
        self.total_llm_time = 0.0
        self.tts_calls = 0
        self.total_tts_time = 0.0
        self.interruptions_handled = 0
    
    def record_vad_trigger(self, is_valid=True):
        """Record a VAD trigger event."""
        self.vad_triggers += 1
        if not is_valid:
            self.vad_false_positives += 1
    
    def record_cache_access(self, hit=True):
        """Record cache hit or miss."""
        if hit:
            self.cache_hits += 1
        else:
            self.cache_misses += 1
    
    def record_response(self, response_time):
        """Record response time."""
        self.total_responses += 1
        self.total_response_time += response_time
    
    def record_llm_call(self, duration):
        """Record LLM API call duration."""
        self.llm_calls += 1
        self.total_llm_time += duration
    
    def record_tts_call(self, duration):
        """Record TTS API call duration."""
        self.tts_calls += 1
        self.total_tts_time += duration
    
    def record_interruption(self):
        """Record successful interruption handling."""
        self.interruptions_handled += 1
    
    @property
    def avg_response_time(self):
        """Calculate average response time."""
        return self.total_response_time / self.total_responses if self.total_responses > 0 else 0.0
    
    @property
    def cache_hit_rate(self):
        """Calculate cache hit rate percentage."""
        total = self.cache_hits + self.cache_misses
        return (self.cache_hits / total * 100) if total > 0 else 0.0
    
    @property
    def vad_accuracy(self):
        """Calculate VAD accuracy (valid triggers / total triggers)."""
        return ((self.vad_triggers - self.vad_false_positives) / self.vad_triggers * 100) if self.vad_triggers > 0 else 100.0
    
    def log_stats(self):
        """Log performance statistics."""
        print(f"""
📊 =========== Performance Metrics ===========
🎤 VAD Stats:
   Total Triggers: {self.vad_triggers}
   False Positives: {self.vad_false_positives}
   Accuracy: {self.vad_accuracy:.1f}%

🗂️ Cache Stats:
   Hits: {self.cache_hits}
   Misses: {self.cache_misses}
   Hit Rate: {self.cache_hit_rate:.1f}%

⚡ Performance:
   Total Responses: {self.total_responses}
   Avg Response Time: {self.avg_response_time:.2f}s
   Interruptions Handled: {self.interruptions_handled}

🤖 API Calls:
   LLM Calls: {self.llm_calls} (avg: {self.total_llm_time/self.llm_calls if self.llm_calls > 0 else 0:.2f}s)
   TTS Calls: {self.tts_calls} (avg: {self.total_tts_time/self.tts_calls if self.tts_calls > 0 else 0:.2f}s)
============================================
        """)

metrics = PerformanceMetrics()



# Helper functions for API calls
def make_post_request(url, data=None, headers=None):
    """Make synchronous POST request using urllib."""
    if data:
        # Check if data is form data for OAuth token request
        if isinstance(data, dict) and 'grant_type' in data:
            # This is form data for OAuth token request
            data = urllib.parse.urlencode(data).encode('utf-8')
            if headers is None:
                headers = {}
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        else:
            # Regular JSON data
            data = json.dumps(data).encode('utf-8')
            if headers is None:
                headers = {}
            headers['Content-Type'] = 'application/json'
    
    req = urllib.request.Request(url, data=data, headers=headers or {})
    # Remove Expect: 100-continue header to prevent HTTP 417 errors
    req.add_header("Expect", "")
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read().decode('utf-8'))

def make_get_request(url, headers=None):
    """Make synchronous GET request using urllib."""
    req = urllib.request.Request(url, headers=headers or {})
    # Remove Expect: 100-continue header to prevent HTTP 417 errors
    req.add_header("Expect", "")
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read().decode('utf-8'))

# Async wrappers for API functions
async def async_make_post_request(url, data=None, headers=None):
    """Async wrapper for POST requests."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, make_post_request, url, data, headers)

async def async_make_get_request(url, headers=None):
    """Async wrapper for GET requests."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, make_get_request, url, headers)

# ========== CUBE VOIP AUDIO HELPERS ==========

async def send_cube_audio(websocket, audio_data: bytes, bot_speaking_flag: Optional[Dict] = None, 
                         interruption_state=None):
    """
    Send audio to Cube via binary WebSocket in ONE SHOT (update_cube.py approach).
    
    AUDIO QUALITY FIX (2026-01-09):
    - Changed from chunked streaming (3200-byte packets) to single-shot sending
    - Cube handles buffering and playback internally
    - Eliminates timing gaps and buffering issues between chunks
    
    Args:
        websocket: WebSocket connection to Cube
        audio_data: Raw PCM audio data (8kHz, 16-bit, mono)
        bot_speaking_flag: Dict with 'speaking' key for interruption handling
        interruption_state: InterruptionState object for tracking
    
    Returns:
        True if completed successfully, False if interrupted
    """
    if not audio_data:
        print("⚠️ No audio data to send")
        return False
    
    try:
        # ========== AUDIO FORMAT VALIDATION ==========
        assert len(audio_data) % 2 == 0, "❌ PCM must have even bytes (16-bit samples)"
        assert len(audio_data) > 0, "❌ PCM audio cannot be empty"
        
        total_bytes = len(audio_data)
        total_samples = total_bytes // 2
        bytes_per_second = 16000  # 8kHz * 16-bit = 16000 bytes/sec
        audio_duration = total_bytes / bytes_per_second
        
        print(f"📊 Audio: {total_bytes} bytes, {total_samples} samples, {audio_duration:.2f}s")
        print(f"   Format: 8kHz, 16-bit, Mono, Little-endian PCM (Cube-compliant)")
        
        # Set speaking flags
        if bot_speaking_flag:
            bot_speaking_flag['speaking'] = True
        if interruption_state:
            interruption_state.audio_stream_active = True
            interruption_state.reset_for_new_tts()
        
        # ========== SINGLE-SHOT AUDIO SEND ==========
        # Send entire audio buffer in ONE websocket call
        # Cube handles buffering and playback internally
        send_start_time = time.monotonic()
        await websocket.send_bytes(audio_data)
        send_elapsed = time.monotonic() - send_start_time
        print(f"📤 Audio sent to Cube in {send_elapsed*1000:.1f}ms (SINGLE-SHOT, {total_bytes} bytes)")
        
        # ========== WAIT FOR PLAYBACK COMPLETION ==========
        # Estimate when Cube finishes playing the audio
        # Add small buffer for network latency and Cube processing.
        # 0.2s (was 0.3s) — trims ~100ms of dead air between sentences. Cube
        # buffers audio internally, so this lower cushion is still safe.
        playback_buffer = 0.2  # 200ms buffer
        total_wait_time = audio_duration + playback_buffer
        
        print(f"⏳ Waiting {total_wait_time:.2f}s for Cube playback ({audio_duration:.2f}s audio + {playback_buffer}s buffer)")
        
        # Wait in small intervals to allow interruption checks
        wait_interval = 0.1  # 100ms intervals
        elapsed_wait = 0
        
        while elapsed_wait < total_wait_time:
            # Check for interruption during playback wait
            if bot_speaking_flag and not bot_speaking_flag['speaking']:
                print(f"⚠️ Interrupted during playback wait (after {elapsed_wait:.2f}s)")
                await send_cube_clear_event(websocket)
                return False
            
            if interruption_state and not interruption_state.audio_stream_active:
                print(f"⚠️ Interrupted by state during playback wait")
                await send_cube_clear_event(websocket)
                return False
            
            await asyncio.sleep(wait_interval)
            elapsed_wait += wait_interval
        
        # Completed normally without interruption
        print(f"✅ Audio playback completed ({audio_duration:.2f}s)")
        
        return True
        
    except WebSocketDisconnect:
        print("🔌 WebSocket disconnected during audio send")
        return False
    except asyncio.CancelledError:
        print("🛑 Audio send cancelled (interruption)")
        try:
            await send_cube_clear_event(websocket)
        except:
            pass
        raise
    except Exception as e:
        print(f"❌ Error sending audio to Cube: {e}")
        return False
    finally:
        # ========== GUARANTEED CLEANUP ==========
        # Ensure flags are always cleared, even in edge cases
        if bot_speaking_flag:
            bot_speaking_flag['speaking'] = False
        if interruption_state:
            interruption_state.audio_stream_active = False


async def send_cube_clear_event(websocket):
    """
    Send a clear event to Cube to stop any currently playing audio.
    
    IMPORTANT: Cube requires this as a BINARY WebSocket message, NOT text!
    The JSON must be converted to bytes before sending.
    
    Reference (from Cube documentation):
        let clearEvent = { "event": "clear" };
        let clearEventBuffer = Buffer.from(JSON.stringify(clearEvent));
        ws.send(clearEventBuffer);
    """
    try:
        clear_event = {"event": "clear"}
        clear_event_bytes = json.dumps(clear_event).encode('utf-8')
        await websocket.send_bytes(clear_event_bytes)
        print("🛑 Sent clear event to Cube (stop audio playback)")
        return True
    except Exception as e:
        print(f"❌ Error sending clear event: {e}")
        return False


def decode_cube_message(data: bytes) -> tuple:
    """Decode incoming Cube binary message.
    
    Args:
        data: Binary message from Cube server
    
    Returns:
        Tuple of (message_type, payload)
        - message_type: int (0x00, 0x10, 0x20, 0x30)
        - payload: bytes (audio data, DTMF digit, CLI/DNI JSON, etc.)
    """
    if len(data) < 1:
        return (None, None)
    
    msg_type = data[0]
    
    if msg_type == CUBE_MSG_AUDIO:
        # Audio data: [0x10][length_high][length_low][audio_data...]
        if len(data) < 3:
            return (CUBE_MSG_AUDIO, b'')
        length = struct.unpack('>H', data[1:3])[0]
        audio_data = data[3:3+length]
        return (CUBE_MSG_AUDIO, audio_data)
    
    elif msg_type in (CUBE_MSG_HANGUP, CUBE_MSG_CLI_DNI, CUBE_MSG_DTMF):
        # Other messages: [type][payload...]
        payload = data[1:]
        if msg_type == CUBE_MSG_CLI_DNI:
            try:
                # Expected format: JSON string (e.g., '{"CLI":"...","DNI":"..."}')
                cli_dni_json = payload.decode('utf-8', errors='ignore').strip()
                print(f"📠 CLI/DNI Raw: {cli_dni_json}")
                
                # Remove null bytes if present
                cli_dni_json = cli_dni_json.replace('\x00', '')
                
                # Try to parse just to verify it's valid JSON (optional context)
                data = json.loads(cli_dni_json)
                cli = data.get('CLI')
                dni = data.get('DNI')
                print(f"   Parsed CLI: {cli}, DNI: {dni}")
            except Exception as e: 
                print(f"⚠️ Failed to parse CLI/DNI: {e}")
                pass
        return (msg_type, payload)
    
    else:
        print(f"⚠️ Unknown Cube message type: 0x{msg_type:02X}")
        return (None, data)


async def cancel_ongoing_audio(websocket, stream_sid, interruption_state):
    """Cancel ongoing audio playback on Cube VoIP by sending clear event.
    
    This is the main interruption handler - stops bot audio immediately
    when user starts speaking.
    """
    try:
        if not interruption_state.audio_stream_active:
            return
        
        print("🛑 Canceling ongoing audio playback...")
        
        # Send Cube clear command to stop audio immediately
        # ✅ Cube only needs {"event":"clear"} - no streamSid!
        await send_cube_clear_event(websocket)
        
        # Cancel pending TTS task if exists
        if interruption_state.current_tts_task and not interruption_state.current_tts_task.done():
            interruption_state.current_tts_task.cancel()
            print("✅ TTS task cancelled")
        
        # Update state
        interruption_state.audio_stream_active = False
        interruption_state.current_tts_task = None
        
    except Exception as e:
        print(f"❌ Error canceling audio: {e}")


async def handle_vad_interruption(websocket, stream_sid, bot_speaking_flag, interruption_state):
    """Handle interruption triggered by Voice Activity Detection (VAD).
    
    This is called when audio energy indicates user is speaking, BEFORE speech
    recognition completes. Stops bot immediately for instant response.
    """
    try:
        print(f"🎤 VAD: User voice detected while bot speaking!")
        
        # Cancel audio immediately (this is the key to instant interruptions)
        await cancel_ongoing_audio(websocket, stream_sid, interruption_state)
        
        # Clear the bot speaking flag
        if bot_speaking_flag:
            bot_speaking_flag['speaking'] = False
        
        # Record VAD trigger
        interruption_state.record_vad_trigger()
        interruption_state.record_interruption("VAD triggered")
        
        print(f"⚡ Bot stopped via VAD (interruption #{interruption_state.interruption_count})")
        print(f"⏳ Waiting for speech recognition to provide complete text...")
        
        # Note: We don't send acknowledgment yet - wait for actual recognized text
        # The recognized_handler will process the text when it's ready
        
    except Exception as e:
        print(f"❌ Error in VAD interruption handling: {e}")



# Date/Time helper functions are defined above (lines 171-201)

# Simplified conversation state tracking
conversation_states = {}

# ========== INTERRUPTION HANDLING SYSTEM ==========
# Configuration for natural conversation interruptions

class VADConfig:
    """Voice Activity Detection (VAD) configuration for instant interruption detection.
    
    Supports two modes:
    1. Silero VAD Service (USE_VAD_SERVICE=True): High accuracy neural network-based detection
       - Runs as external WebSocket service on port 8765
       - GPU-accelerated, no false positives from coughs/throat clears
       - To start: cd VAD && python vad.py
       
    2. Energy-based fallback (USE_VAD_SERVICE=False): Simple energy threshold detection
       - Faster but less accurate
       - May trigger on loud noises
    
    IMPORTANT: Single-trigger-per-TTS limit prevents false positives from bot audio echo.
    Once VAD triggers during a TTS playback, it won't trigger again until TTS completes.
    """
    ENABLED = True  # Enable/disable VAD-based instant interruptions
    
    # Silero VAD Service Settings (HIGH ACCURACY)
    USE_VAD_SERVICE = False  # Use external VAD WebSocket service (disabled — not deployed; energy-based fallback used instead)
    # Read from environment for production flexibility (e.g., ws://vad-service:8765 in Docker/K8s)
    VAD_SERVICE_URL = os.getenv("VAD_SERVICE_URL", "ws://localhost:8765")
    SPEECH_THRESHOLD = 0.5  # Speech probability threshold (0.0-1.0)
    
    # Audio energy threshold for voice detection (0-32768, 16-bit PCM)
    # Higher = less sensitive (fewer false positives from noise)
    # Lower = more sensitive (catches quieter speech)
    # NOTE: 1600 is optimized for Indian PSTN - filters "hmm", throat clears, background speech
    ENERGY_THRESHOLD = 2000  # Telephony-safe (was 1200, too sensitive for PSTN)
    
    # Minimum consecutive chunks above threshold to trigger (debouncing)
    # 1 chunk = 20ms, so 5 chunks = 100ms
    # IMPORTANT: 100ms filters throat clears (50-80ms) while still detecting real speech (>120ms)
    MIN_CHUNKS_ABOVE_THRESHOLD = 5  # Require 100ms of continuous voice (was 4/80ms)
    
    # Energy variance threshold for spike detection (throat clear vs speech)
    # Throat clearing = sharp spike (high variance), Speech = stable energy (low variance)
    # If variance > threshold, it's likely a cough/throat clear, not speech
    ENERGY_VARIANCE_THRESHOLD = 2000  # Max allowed variance in smoothing window
    
    # Energy smoothing window (reduces jitter)
    SMOOTHING_WINDOW = 5  # Average over 5 chunks (100ms)
    
    # Noise gate (energy below this is always ignored)
    NOISE_GATE = 600  # Ignore very quiet audio
    
    # Cooldown after VAD trigger (prevents duplicate triggers)
    VAD_COOLDOWN = 0.7  # Seconds between VAD detections (raised to reduce false interrupts)
    
    # Minimum confidence to act on VAD interrupt (filters noise/echo false positives)
    VAD_MIN_CONFIDENCE = float(os.getenv("VAD_MIN_CONFIDENCE", "0.6"))
    
    # Single-trigger-per-TTS limit (prevents echo-based false positives)
    # Once VAD triggers during a TTS, it won't trigger again until TTS completes
    # Re-enabled to prevent multiple false positives from echo
    SINGLE_TRIGGER_PER_TTS = True

class InterruptionConfig:
    """Configuration for interruption detection and handling."""
    ENABLED = True  # Enable/disable interruption handling overall
    MIN_SPEECH_LENGTH = 3  # Minimum words to validate interruption (stricter - filters "hmm", "uh")
    INTERRUPTION_COOLDOWN = 0.3  # Seconds to wait before allowing another interruption
    CANCEL_DELAY = 0.0  # No delay needed with VAD (instant detection)
    ACKNOWLEDGE_INTERRUPTION = False  # DISABLED - Do not acknowledge being interrupted
    
    # Interruption acknowledgment phrases (when user interrupts bot)
    ACKNOWLEDGMENTS = [
        "Okay, I understand.",
        "I see.",
        "Good point.",
        "Makes sense.",
        "",
    ]
    
    # Utterance processing acknowledgments — language-aware
    ACKNOWLEDGE_UTTERANCE = False
    UTTERANCE_ACKNOWLEDGMENTS_EN = [
        "Sure, one moment.",
        "Sure. ",
        "Right away.",
        "Understood.", 
        "",      # silent
    ]
    UTTERANCE_ACKNOWLEDGMENTS_HI = [
        "",  # silent acknowledgment is more natural in Hindi
        "जी, एक moment।",
        "हाँ जी",
        "बिल्कुल जी।",
        "ठीक है।",   
    ]



class InterruptionState:
    """Tracks interruption state for a conversation session."""
    
    def __init__(self):
        self.last_interruption_time: float = 0
        self.current_tts_task: Optional[asyncio.Task] = None
        self.audio_stream_active: bool = False
        self.interrupted_response: Optional[str] = None
        self.interruption_count: int = 0
        
        # VAD-specific state (optimized with deque)
        self.energy_buffer = deque(maxlen=VADConfig.SMOOTHING_WINDOW)  # Auto-sized rolling buffer
        self.chunks_above_threshold: int = 0  # Consecutive chunks above threshold
        self.last_vad_trigger_time: float = 0  # When VAD last triggered
        self.pending_recognition: bool = False  # Waiting for speech recognition after VAD
        
        # Single-trigger-per-TTS tracking (prevents echo-based false positives)
        self.vad_triggered_this_tts: bool = False  # Has VAD triggered during current TTS?
    
    def can_interrupt(self) -> bool:
        """Check if enough time has passed since last interruption."""
        return (time.time() - self.last_interruption_time) >= InterruptionConfig.INTERRUPTION_COOLDOWN
    
    def can_vad_trigger(self) -> bool:
        """Check if VAD can trigger.
        
        Returns False if:
        1. Cooldown hasn't elapsed
        2. Single-trigger-per-TTS is enabled and already triggered during this TTS
        """
        # Check cooldown
        if (time.time() - self.last_vad_trigger_time) < VADConfig.VAD_COOLDOWN:
            return False
        
        # Check single-trigger-per-TTS limit
        if VADConfig.SINGLE_TRIGGER_PER_TTS and self.vad_triggered_this_tts:
            return False
        
        return True
    
    def record_interruption(self, interrupted_text: str):
        """Record an interruption event."""
        self.last_interruption_time = time.time()
        self.interrupted_response = interrupted_text
        self.interruption_count += 1
    
    def record_vad_trigger(self):
        """Record a VAD trigger event."""
        self.last_vad_trigger_time = time.time()
        self.pending_recognition = True
        self.chunks_above_threshold = 0  # Reset counter
        self.vad_triggered_this_tts = True  # Mark as triggered for this TTS
    
    def reset_for_new_tts(self):
        """Reset VAD state for a new TTS playback."""
        self.vad_triggered_this_tts = False
        self.chunks_above_threshold = 0
        self.energy_buffer.clear()
    
    def reset(self):
        """Reset full interruption state."""
        self.current_tts_task = None
        self.audio_stream_active = False
        self.interrupted_response = None
        self.energy_buffer.clear()
        self.chunks_above_threshold = 0
        self.pending_recognition = False
        self.vad_triggered_this_tts = False


# Function definitions for OpenAI function calling (date/time helpers only)
AVAILABLE_FUNCTIONS = [
    {
        "name": "get_current_ist_date",
        "description": "Get current date in YYYY-MM-DD format. Use this to get today's date.",
        "parameters": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "get_current_ist_datetime",
        "description": "Get current date and time in readable format for display to users. Use this when telling users what today's date is.",
        "parameters": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "get_future_dates",
        "description": "Get next N days starting from today. Use this to show available dates to users.",
        "parameters": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Number of days to get (default: 7)", "default": 7}
            },
            "required": []
        }
    },
    {
        "name": "format_appointment_date",
        "description": "Convert date format (YYYY-MM-DD) to readable format for display to users.",
        "parameters": {
            "type": "object",
            "properties": {
                "date_str": {"type": "string", "description": "Date in YYYY-MM-DD format (e.g., '2025-01-15')"}
            },
            "required": ["date_str"]
        }
    }
]

# Function mapping for execution
FUNCTION_MAPPING = {
    "get_current_ist_date": get_current_ist_date,
    "get_current_ist_datetime": get_current_ist_datetime,
    "get_future_dates": get_future_dates,
    "format_appointment_date": format_appointment_date,
}

# Thread Pool for TTS operations (auto-scaled based on CPU cores)
optimal_tts_workers = min(max(os.cpu_count() or 4, 4), 8)  # Between 4-8 workers

# ==================== POST-CALL ANALYSIS & CRM SYNC ====================
# Logic moved to analysis_engine.py as per user request

tts_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=optimal_tts_workers,
    thread_name_prefix="TTS"
)

async def _prewarm_azure_openai():
    """Pre-warm Azure OpenAI using the real system prompt with generic placeholder values.

    Sending the actual Faber system prompt at boot warms both TLS/routing AND
    primes Azure's KV cache for the static prompt tokens. Real calls share the
    same large static prefix so first-token latency drops significantly.
    """
    if not (AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT and OPENAI_API_VERSION):
        print("⏭️  Azure OpenAI pre-warm SKIPPED (missing config)")
        return

    warm_prompt = system_message \
        .replace("__CUSTOMER_NAME__", "Customer") \
        .replace("__PRODUCT__", "Chimney") \
        .replace("__DEALER_NAME__", "Dealer") \
        .replace("__PHONE_NUMBER__", "9999999999")

    url = (
        f"{AZURE_OPENAI_ENDPOINT}openai/deployments/"
        f"{AZURE_OPENAI_DEPLOYMENT}/chat/completions"
        f"?api-version={OPENAI_API_VERSION}"
    )
    headers = {"Content-Type": "application/json", "api-key": AZURE_OPENAI_API_KEY}
    data = {
        "messages": [
            {"role": "system", "content": warm_prompt},
            {"role": "user",   "content": "[DETECTED_LANGUAGE: HINDI] हाँ, मैं बोल रहा हूँ।"},
        ],
        "max_tokens": 50,
        "temperature": 0.0,
        "stream": True,
    }
    t0 = time.time()
    try:
        session = await http_manager.get_session()
        async with session.post(url, headers=headers, json=data,
                                timeout=aiohttp.ClientTimeout(total=20)) as resp:
            async for _ in resp.content.iter_chunked(1024):
                pass
        print(f"🔥 Azure OpenAI pre-warm complete ({time.time()-t0:.2f}s) — KV cache warm, first turn will be fast")
    except Exception as e:
        print(f"⚠️  Azure OpenAI pre-warm failed (non-fatal): {e}")


async def _faber_extract(transcript: str) -> dict:
    """Post-call extraction for Swara sale-announcement calls: sentiment,
    summary, and a standardized disposition.

    Self-contained (the main analysis engine is Paluck/CRM-shaped). Returns a
    dict with those keys; values may be None if the model can't determine.
    """
    if not (AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT):
        return {}
    _disp_list = ", ".join(f'"{d}"' for d in lead_files_mod.CONNECTED_DISPOSITIONS)
    sys_prompt = (
        "You analyze a Hindi/English/Hinglish sale-announcement call transcript for "
        "Swara The Fashion Street (a fashion retail store informing customers of a sale).\n"
        "Return STRICT JSON with exactly these keys:\n\n"
        '"sentiment": one of ["Happy","Neutral","Irate"]\n\n'
        '"summary": one-line English summary, max 20 words\n\n'
        f'"disposition": one of [{_disp_list}]\n'
        "  RULES (use the FIRST rule that matches):\n"
        "  - Interested - Will Visit  -> customer agreed or expressed intent to visit the store\n"
        "  - Not Interested           -> customer explicitly said they are not interested / declined\n"
        "  - Will Visit Later         -> customer is open but said they'll visit at a later, unspecified time\n"
        "  - Busy - Call Later        -> customer was busy / asked to be called back\n"
        "  - Wrong Number             -> customer says this is a wrong number / they never shopped at Swara\n"
        "  - Language Barrier         -> could not communicate due to language difference\n"
        "  - Other                    -> any scenario not covered above; always set disposition_reason\n\n"
        '"disposition_reason": short English phrase (max 5 words, dashboard display) explaining why Other was chosen. Set to null if disposition is not Other.\n\n'
        "Base everything ONLY on what the customer actually said. Do not infer or assume."
    )
    url = (
        f"{AZURE_OPENAI_ENDPOINT.rstrip('/')}/openai/deployments/"
        f"gpt-4.1/chat/completions?api-version={OPENAI_API_VERSION}"
    )
    headers = {"Content-Type": "application/json", "api-key": AZURE_OPENAI_API_KEY}
    data = {
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"Transcript:\n{transcript}"},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "max_tokens": 250,
    }
    try:
        session = await http_manager.get_session()
        async with session.post(url, headers=headers, json=data,
                                timeout=aiohttp.ClientTimeout(total=20)) as resp:
            body = await resp.json()
        content = body["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception as e:
        print(f"[lead_files] Faber extract failed (non-fatal): {e}")
        return {}


async def _faber_lead_writeback(record_id: str, conversation_history: list):
    """Post-call analysis: always writes to calls table; also writes to lead_file_rows if row exists."""
    try:
        transcript = "\n".join(
            f"{m['role']}: {m['content']}"
            for m in conversation_history
            if m.get("role") in ("user", "assistant") and m.get("content")
        )
        if not transcript.strip():
            return

        extracted = await _faber_extract(transcript)
        _disp         = extracted.get("disposition")
        _disp_why     = extracted.get("disposition_reason")
        _sentiment    = extracted.get("sentiment")
        _summary      = extracted.get("summary")

        # PRIMARY store: calls table — one row per call, never overwritten.
        # Runs for every call regardless of whether a lead_file_row exists.
        await asyncio.to_thread(
            db.update_call_analysis,
            record_id,
            disposition=_disp,
            disposition_reason=_disp_why,
            sentiment=_sentiment,
            call_summary=_summary,
        )

        # SECONDARY store: lead_file_rows — for Excel export of the latest call only.
        # Gated on row existing (non-Excel calls won't have one).
        row = await asyncio.to_thread(lead_files_mod.get_row_by_record, record_id)
        if row:
            await asyncio.to_thread(
                lead_files_mod.apply_call_result,
                record_id,
                transcript=transcript,
                sentiment=_sentiment,
                call_summary=_summary,
            )
            _disp_label = f"{_disp}: {_disp_why}" if _disp == "Other" and _disp_why else _disp
            if _disp_label:
                await asyncio.to_thread(lead_files_mod.apply_disposition, record_id, _disp_label)

        print(f"[lead_files] Voice BOT writeback done for record {record_id} "
              f"(sentiment={_sentiment}, disposition={_disp})")
    except Exception as e:
        print(f"[lead_files] writeback orchestration failed (non-fatal): {e}")


async def _mark_not_connected_row(record_id: str):
    """For a NOT-CONNECTED call launched from an Excel row: set disposition
    'No Response' and flip the row's call_status to terminal 'not_connected'
    (otherwise it stays stuck at 'initiated'). No-op for non-Excel calls.

    (The WhatsApp template fallback was removed for Swara — this keeps only the
    lead-file bookkeeping that the fallback used to also do.)
    """
    try:
        row = await asyncio.to_thread(lead_files_mod.get_row_by_record, record_id)
        if not row:
            return  # not an Excel-row call — nothing to do
        await asyncio.to_thread(lead_files_mod.apply_disposition, record_id, "No Response")
        await asyncio.to_thread(lead_files_mod.mark_not_connected, record_id)
        print(f"[lead_files] not-connected bookkeeping applied for record {record_id}")
    except Exception as e:
        print(f"[lead_files] not-connected bookkeeping failed (non-fatal): {e}")


async def _prewarm_tts():
    """Build the singleton Azure TTS synthesizer + open its internal WS at boot.

    The Azure Speech SDK opens an internal WebSocket to the service on the
    FIRST synthesis. Without this pre-warm, that ~1-2s handshake lands on the
    greeting of the very first call (see send_cube_greeting). Synthesizing a
    throwaway phrase here moves that one-time cost to server startup, so the
    first customer hears the greeting with no connection lag.
    """
    t0 = time.time()
    try:
        # Runs synthesize_speech_azure_sdk in the TTS thread pool — this both
        # creates the _tts_synthesizer singleton AND warms its Azure WS.
        await synthesize_speech_azure(
            "नमस्ते, मैं Priya बोल रही हूँ, Swara The Fashion Street \"पंडरी\" से। क्या आप दो minute available है?",
            "hi-IN",
        )
        print(f"🔥 Azure TTS pre-warm complete ({time.time()-t0:.2f}s) — greeting will be fast")
    except Exception as e:
        print(f"⚠️  Azure TTS pre-warm failed (non-fatal): {e}")



@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler for FastAPI app startup and shutdown."""
    print("🚀 Server starting up...")
    print("📱 Frontend available at: http://localhost:8000")
    print("🔧 Ready to accept calls from frontend interface")

    # Pre-warm all three external services concurrently so the first call has
    # no cold-start lag: OpenAI (LLM TLS/routing), TTS (Azure Speech WS), and
    # Deepgram (DNS + TLS). Each is non-fatal — failures only log a warning.
    asyncio.create_task(_prewarm_azure_openai())   # saves ~18s on first user turn
    asyncio.create_task(_prewarm_tts())            # saves ~1-2s on first greeting

    # Run DB migrations on every startup (idempotent — IF NOT EXISTS is safe)
    try:
        from database import _execute
        _execute("ALTER TABLE calls ADD COLUMN IF NOT EXISTS installation_status        TEXT")
        _execute("ALTER TABLE calls ADD COLUMN IF NOT EXISTS installation_status_reason TEXT")
        _execute("ALTER TABLE calls ADD COLUMN IF NOT EXISTS disposition                TEXT")
        _execute("ALTER TABLE calls ADD COLUMN IF NOT EXISTS disposition_reason         TEXT")
        _execute("ALTER TABLE calls ADD COLUMN IF NOT EXISTS sentiment                  TEXT")
        _execute("ALTER TABLE calls ADD COLUMN IF NOT EXISTS call_summary               TEXT")
        _execute("ALTER TABLE calls ADD COLUMN IF NOT EXISTS cube_status_raw            TEXT")
        _execute("ALTER TABLE calls ADD COLUMN IF NOT EXISTS campaign_db_id             BIGINT")
        _execute("ALTER TABLE campaign_leads ADD COLUMN IF NOT EXISTS record_id        TEXT")
        _execute("ALTER TABLE campaign_leads ADD COLUMN IF NOT EXISTS lead_file_row_id BIGINT")
        print("✅ DB migrations applied")
    except Exception as _me:
        print(f"⚠️  DB migration failed (non-fatal): {_me}")

    # Inject call function into campaign manager (avoids circular import at module level)
    campaign_manager.set_call_function(make_cube_outbound_call)

    # Reset any stale "in_campaign" leads from a previous server run → back to pending
    try:
        from database import _execute
        _execute("UPDATE koel_followup_leads SET call_status = 'pending', campaign_name = NULL WHERE call_status = 'in_campaign'")
        print("[Koel] Startup: stale in_campaign leads reset to pending")
    except Exception as _se:
        print(f"[Koel] Startup reset skipped: {_se}")

    # Register koel failed-lead callback
    def _on_lead_permanently_failed(lead: dict):
        docket_id = (lead.get("lead_data") or {}).get("docket_id")
        if docket_id:
            try:
                from koel_leads import update_koel_call_status
                update_koel_call_status(docket_id, "failed")
                print(f"[Koel] docket {docket_id} -> failed (all retries exhausted)")
            except Exception as _fe:
                print(f"[Koel] failed status update error: {_fe}")
    campaign_manager.on_lead_permanently_failed = _on_lead_permanently_failed

    yield

    print("🔄 Server shutting down...")
    # Gracefully stop any running campaign on shutdown
    if campaign_manager.state in ("running", "paused"):
        campaign_manager.stop()
    await http_manager.close()
    tts_executor.shutdown(wait=False)

app = FastAPI(lifespan=lifespan)

# Add CORS middleware - Allow all origins for debugging/development
# NOTE: In production, replace ["*"] with specific frontend domains
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=False,  # Must be False when using wildcard origins
    allow_methods=["*"],
    allow_headers=["*"],
)

# Validation
if not AZURE_OPENAI_API_KEY:
    raise ValueError('Missing Azure OpenAI API key. Please set AZURE_OPENAI_API_KEY in the .env file for GenAI functionality.')
if not AZURE_OPENAI_ENDPOINT:
    raise ValueError('Missing Azure OpenAI endpoint. Please set AZURE_OPENAI_ENDPOINT in the .env file.')
# Deepgram STT validation
if not DEEPGRAM_API_KEY:
    raise ValueError('Missing Deepgram API key. Please set DEEPGRAM_API_KEY in the .env file for STT.')

# Azure Speech TTS validation
if not AZURE_SPEECH_KEY:
    raise ValueError('Missing Azure Speech key. Please set AZURE_SPEECH_KEY in your .env file for TTS.')
# Sarvam not used - Azure STT only. SARVAM_API_KEY kept for optional future use.
# Cube configuration is optional - will use defaults if not provided

# =============================================================================
# CONCURRENT OUTBOUND CALL REGISTRY
# =============================================================================
# Cube never passes a phone number in the WebSocket URL, so we cannot directly
# tie an incoming /swara_voicebot WebSocket to the right outbound call.  This registry
# solves the problem for up to N concurrent outbound calls without any
# name/data shuffling.
#
# Life-cycle:
#   1. /make-call fires → register_outbound_call(phone, ctx)
#   2. WebSocket connects → claim_outbound_call(phone=None) → FIFO match
#   3. CLI/DNI arrives mid-call → claim_outbound_call(phone=real_phone)
#   4. Call ends or times-out → release_outbound_call(phone)
# =============================================================================

@dataclass
class OutboundCallContext:
    phone: str                    # 10-digit phone number
    name: str                     # customer name
    company_name: str             # company (may be empty string)
    lead_id: Optional[int]        # DB lead ID (known at make-call time)
    lead_data: dict               # full lead data dict for LLM personalisation
    created_at: float             # epoch seconds (for FIFO ordering)
    claimed: bool = False         # True once a WebSocket has claimed this entry
    claim_phone: str = ''         # actual phone used to claim (for debugging)

_outbound_lock = threading.Lock()           # protects _outbound_registry
_outbound_registry: dict[str, OutboundCallContext] = {}  # phone → ctx
_OUTBOUND_ENTRY_TTL = 120.0                 # seconds before an unclaimed entry expires


def register_outbound_call(
    phone: str,
    name: str,
    company_name: str,
    lead_id: Optional[int],
    lead_data: dict,
) -> None:
    """Register a pending outbound call.  Called from make_cube_outbound_call."""
    ctx = OutboundCallContext(
        phone=phone,
        name=name,
        company_name=company_name or '',
        lead_id=lead_id,
        lead_data=lead_data or {},
        created_at=time.time(),
    )
    with _outbound_lock:
        # Expire stale entries while we're here
        now = time.time()
        stale = [p for p, c in _outbound_registry.items()
                 if (now - c.created_at) > _OUTBOUND_ENTRY_TTL]
        for p in stale:
            print(f"⏱️ Outbound registry: expired stale entry for {p}")
            del _outbound_registry[p]
        _outbound_registry[phone] = ctx
    print(f"📝 Outbound registry: registered {phone} ({name}) — registry size={len(_outbound_registry)}")


def claim_outbound_call(phone: str = '') -> Optional[OutboundCallContext]:
    """
    Claim an outbound call context for a WebSocket session.

    Strategy:
      • If `phone` is provided and exists in registry → exact match (best case).
      • Otherwise → claim the oldest unclaimed entry within TTL (FIFO).

    Returns the claimed context or None if nothing matches.
    """
    with _outbound_lock:
        now = time.time()

        # --- Exact phone match ---
        if phone and phone in _outbound_registry:
            ctx = _outbound_registry[phone]
            if not ctx.claimed:
                ctx.claimed = True
                ctx.claim_phone = phone
                print(f"✅ Outbound registry: claimed {phone} ({ctx.name}) via exact-phone match")
                return ctx
            else:
                print(f"⚠️ Outbound registry: {phone} already claimed")
                return None

        # --- FIFO fallback (Cube sent no phone in the WebSocket URL) ---
        eligible = [
            ctx for ctx in _outbound_registry.values()
            if not ctx.claimed and (now - ctx.created_at) <= _OUTBOUND_ENTRY_TTL
        ]
        if not eligible:
            return None
        eligible.sort(key=lambda c: c.created_at)  # oldest first
        ctx = eligible[0]
        ctx.claimed = True
        ctx.claim_phone = ctx.phone  # best guess
        print(f"⚡ Outbound registry: claimed {ctx.phone} ({ctx.name}) via FIFO fallback — registry size={len(_outbound_registry)}")
        return ctx


def release_outbound_call(phone: str) -> None:
    """Remove a completed/failed call from the registry."""
    with _outbound_lock:
        if phone in _outbound_registry:
            del _outbound_registry[phone]
            print(f"🗑️ Outbound registry: released {phone} — registry size={len(_outbound_registry)}")


# Keep these for backward-compat (inbound calls still use them)
outbound_customer_names: dict = {}  # phone → customer_name
outbound_company_names: dict  = {}  # phone → company_name

async def check_vad_status_fast():
    """Quickly check VAD status for API responses (max 500ms)."""
    if not (VADConfig.ENABLED and VADConfig.USE_VAD_SERVICE):
        return {"enabled": False, "status": "disabled"}
    
    try:
        async with websockets.connect(
            VADConfig.VAD_SERVICE_URL, 
            ping_timeout=0.5, 
            open_timeout=0.5
        ) as ws:
            return {"enabled": True, "status": "connected", "url": VADConfig.VAD_SERVICE_URL}
    except Exception as e:
        return {"enabled": True, "status": "error", "error": str(e), "url": VADConfig.VAD_SERVICE_URL}


async def make_cube_outbound_call(to_number: str, campaign_id: str = None, did: str = None, name: str = "Customer", company_name: str = None, lead_data: dict =None, campaign_db_id: int = None):
    """
    Make an outbound call using Cube Click2Call API.
    Cube API expects GET with query params: Phoneno, Name, Remarks, CampaignID, Priority, Duplicate.
    
    Args:
        to_number: Phone number to call (e.g., "+919876543210")
        campaign_id: Cube campaign ID (defaults to CUBE_CAMPAIGN_ID)
        did: Cube DID number (unused by Click2Call GET; kept for API compatibility)
        name: Caller name for Cube (default "Customer")
    
    Returns:
        Dict with success status and call details
    """
    try:
        campaign = campaign_id or CUBE_CAMPAIGN_ID
        # Cube Click2Call requires exactly 10-digit number (no country code)
        # Remove all non-digits, then extract last 10 digits (removes country codes like +91, 91)
        clean_number = ''.join(filter(str.isdigit, to_number))
        
        if len(clean_number) < 10:
            return {"success": False, "error": "Phone number must have at least 10 digits"}
        
        # Extract only the last 10 digits (removes country codes like 91, +91)
        phoneno = clean_number[-10:]
        
        if len(phoneno) != 10:
            return {"success": False, "error": "Phone number must be exactly 10 digits"}

        # Cube API: GET with query params (same format as cube_sip.py / update_cube.py)
        params = {
            'Phoneno': phoneno,
            'Name': name,
            'Remarks': 'DefaultAiJ',
            'CampaignID': 'BotrixAI_Bot',
            'Priority': 0,
            'Duplicate': 2,
            'Company': '918071035148',
        }
        url = f"{CUBE_CLICK2CALL_URL}?{urllib.parse.urlencode(params)}"

        print(f"📞 Initiating Cube call to {phoneno} via Click2Call GET")
        print(f"   Original input: {to_number}, Using 10-digit: {phoneno}")
        print(f"   Customer Name: {name}")
        print(f"   Company Name: {company_name}")
        print(f"   Campaign: {campaign}")
        
        # Keep legacy dicts in sync (used for inbound-call name lookup)
        outbound_customer_names[phoneno] = name
        if company_name:
            outbound_company_names[phoneno] = company_name
            print(f"💾 Stored: outbound_customer_names['{phoneno}'] = '{name}', outbound_company_names['{phoneno}'] = '{company_name}'")
        else:
            print(f"💾 Stored customer name: outbound_customer_names['{phoneno}'] = '{name}'")

        response = await async_make_get_request(url)

        # Cube may return various shapes; treat as success if status is success or no error key
        if response is None:
            return {"success": False, "error": "No response from Cube API"}
        if isinstance(response, dict):
            # Check for Cube's actual success response formats:
            # 1. {'Click2Call': 'Success', 'Response': {...}}
            # 2. {'status': 'success', ...}
            is_success = (
                response.get('status') == 'success' or
                response.get('Click2Call') == 'Success' or
                response.get('Click2Call') == 'success'
            )
            
            
            if is_success:
                print(f"✅ Cube call initiated successfully! Response: {response}")

                # Mark koel follow-up lead as "called" if docket_id present
                if lead_data and lead_data.get("docket_id"):
                    try:
                        from koel_leads import update_koel_call_status
                        update_koel_call_status(lead_data["docket_id"], "called")
                        print(f"[Koel] docket {lead_data['docket_id']} -> called")
                    except Exception as _ke:
                        print(f"[Koel] status update failed: {_ke}")

                # Extract RecordId from Cube response
                record_id = response.get('Response', {}).get('RecordId') or response.get('RecordId')

                # Store call in database
                if record_id:
                    try:
                        call_id = db.create_call(
                            record_id=record_id,
                            phone_number=phoneno,
                            customer_name=name,
                            company_name=company_name,
                            campaign_id=campaign,
                            metadata={
                                'original_number': to_number,
                                'cube_response': response
                            },
                            campaign_db_id=campaign_db_id,
                        )
                        db.log_console(
                            f"Call initiated to {name} ({phoneno})",
                            log_level='INFO',
                            record_id=record_id,
                            details={'call_id': call_id, 'campaign': campaign}
                        )
                    except Exception as db_error:
                        print(f"⚠️ Database error (non-critical): {db_error}")
                
                # 🆕 UPDATE LEAD STATUS TO 'initiated' after Cube API success
                # Also register into the concurrent outbound registry so the WebSocket
                # can claim this context (with correct lead_id) without name shuffling.
                _resolved_lead_id = None
                try:
                    lead_info = get_lead_by_phone(phoneno)  # Direct import, not db.method
                    if lead_info:
                        _resolved_lead_id = lead_info['id']
                        update_lead_status(_resolved_lead_id, 'initiated')  # Direct import
                        print(f"✅ Lead status updated to 'initiated' for {phoneno} (lead_id={_resolved_lead_id})")
                        
                        # ⏰ SAFETY NET (250s): only acts if Cube's /getCallStatus webhook
                        # NEVER fired at all for this call (total webhook silence — outage
                        # or misconfig). The webhook is now the PRIMARY, real-time signal
                        # for not-connected detection (see cube_call_status_webhook); this
                        # replaces the old 60s "guess from our own lead status" watchdog,
                        # which caused false WhatsApp triggers when our own WebSocket/CLI-DNI
                        # registry claim was merely slow — not an actual not-connected call.
                        # By 250s any real conversation is long over (hard cutoff is 120s),
                        # so this is purely "did Cube ever talk to us at all?".
                        initiated_lead_id  = _resolved_lead_id
                        initiated_record_id = record_id  # Cube record_id captured at make-call time
                        async def reset_if_not_connected(lead_id_to_check, phone, rd):
                            await asyncio.sleep(250)
                            try:
                                flags = await asyncio.to_thread(db.get_cube_call_flags, rd) if rd else None
                                if flags and (flags.get("connected_at") or flags.get("disconnected_at")):
                                    print(f"✅ Safety net: Cube webhook already handled {rd} — no action")
                                    return

                                print(f"⏰ Safety net: Cube webhook NEVER fired for {rd} after 250s "
                                      f"— falling back to legacy lead-status check")
                                current_lead = get_lead_by_phone(phone)  # Direct import
                                if current_lead and current_lead.get('status') == 'initiated':
                                    print(f"⏰ Safety net: Lead {lead_id_to_check} still 'initiated' — assuming not answered")
                                    if rd:
                                        try:
                                            db.update_call_status(rd, 'not_connected')
                                        except Exception as db_wd_err:
                                            print(f"⚠️ Safety net: Could not update DB call status: {db_wd_err}")
                                    try:
                                        await asyncio.to_thread(
                                            sync_not_connected_call,
                                            phone, lead_id_to_check, rd, "not_answered"
                                        )
                                    except Exception as crm_wd_err:
                                        print(f"⚠️ Safety net: CRM sync failed: {crm_wd_err}")
                                    if rd:
                                        asyncio.create_task(_mark_not_connected_row(rd))
                                else:
                                    print(f"✅ Safety net: Lead {lead_id_to_check} already moved past 'initiated' "
                                          f"(status={current_lead.get('status') if current_lead else 'not found'})")
                            except Exception as wd_err:
                                print(f"⚠️ Safety net error: {wd_err}")

                        asyncio.create_task(reset_if_not_connected(initiated_lead_id, phoneno, record_id))
                        print(f"⏰ Safety net armed: will check Cube webhook status in 250s if untouched")
                except Exception as lead_err:
                    print(f"⚠️ Could not update lead status to initiated: {lead_err}")
                
                # ✅ REGISTER INTO CONCURRENT OUTBOUND REGISTRY
                # This must happen AFTER the lead lookup so we store the real lead_id.
                # The WebSocket handler will claim this entry (by phone or FIFO order).
                register_outbound_call(
                    phone=phoneno,
                    name=name,
                    company_name=company_name or '',
                    lead_id=_resolved_lead_id,
                    lead_data=lead_data or {},
                )
                print(f"📋 Registry entry created: phone={phoneno}, lead_id={_resolved_lead_id}, name={name}")

                # ── Faber lead-file linking ──────────────────────────────────
                # If this call was launched from a Faber Excel row, mark it as
                # handled by Voice BOT and bind the Cube record_id so post-call
                # analysis can write results back to that exact row.
                try:
                    _lf_row_id = (lead_data or {}).get('lead_file_row_id')
                    if _lf_row_id and record_id:
                        lead_files_mod.set_row_call(
                            int(_lf_row_id), 'initiated', called_by='VoiceBOT', record_id=record_id
                        )
                        print(f"[lead_files] Linked row {_lf_row_id} -> record {record_id} (Voice BOT)")
                except Exception as _lf_e:
                    print(f"[lead_files] row link failed (non-critical): {_lf_e}")

                # Check VAD status (fast)
                vad_status = await check_vad_status_fast()
                
                return {
                    "success": True,
                    "call_id": response.get('call_id') or record_id,
                    "record_id": record_id,
                    "message": f"Call initiated to {to_number}",
                    "vad_status": vad_status
                }
            # Extract error from common response keys
            err = (response.get('error') or response.get('message') or response.get('msg') or
                   response.get('reason') or response.get('Message'))
            if err:
                print(f"❌ Cube call failed: {err}")
                return {"success": False, "error": str(err)}
            # No success and no known error key: return summary so we don't show "Unknown error"
            print(f"❌ Cube call failed (unexpected response): {response}")
            return {"success": False, "error": f"Cube API returned: {response}"}
        # Non-dict response (e.g. string)
        print(f"❌ Cube call unexpected response type: {type(response)}")
        return {"success": False, "error": f"Unexpected API response: {response}"}

    except Exception as e:
        err_msg = str(e).strip() or "Connection or server error"
        print(f"❌ Error making Cube outbound call: {e}")
        return {"success": False, "error": err_msg}

@app.get("/")
async def index_page():
    """Serve the call initiator UI (index.html)."""
    html_path = Path(__file__).parent / "index.html"
    return FileResponse(str(html_path), media_type="text/html")


@app.get("/health")
async def health_page():
    """Server status / health check page."""
    return HTMLResponse("""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Faber VoiceBot — Server Status</title>
    <style>
        body { font-family: sans-serif; background: #0f172a; color: #e2e8f0; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
        .card { background: #1e293b; border-radius: 12px; padding: 40px 56px; text-align: center; box-shadow: 0 8px 32px rgba(0,0,0,0.4); }
        h1 { font-size: 1.8rem; margin-bottom: 8px; color: #38bdf8; }
        .badge { display: inline-block; background: #22c55e; color: #fff; border-radius: 999px; padding: 4px 16px; font-size: 0.85rem; font-weight: 600; margin-bottom: 24px; }
        p { color: #94a3b8; margin: 6px 0; font-size: 0.95rem; }
        code { background: #0f172a; padding: 2px 8px; border-radius: 4px; font-size: 0.85rem; color: #7dd3fc; }
    </style>
</head>
<body>
    <div class="card">
        <h1>🤖 Faber VoiceBot — Farishta</h1>
        <div class="badge">✅ Server Running</div>
        <p>Azure OpenAI &nbsp;|&nbsp; Deepgram STT &nbsp;|&nbsp; Azure TTS (Farishta) &nbsp;|&nbsp; Cube VoIP</p>
        <p style="margin-top:20px;">Call UI: <code>GET /</code></p>
        <p>WebSocket: <code>/amc_voicebot</code></p>
        <p>Make Call: <code>POST /make-call</code></p>
    </div>
</body>
</html>
""")

@app.post("/make-call")
async def make_call_endpoint(request: Request):
    """API endpoint to make outbound calls via Cube Click2Call (GET with query params).
    
    Accepts lead_data for personalization which is stored in database for WebSocket retrieval.
    """
    try:
        body = await request.json()
        print(f"📞 /make-call received body: {body}")
        
        to_number = body.get('to_number')
        campaign_id = body.get('campaign_id')  # Optional
        did = body.get('did')  # Optional
        name = body.get('name', 'Customer')  # Optional; Cube API Name field
        company_name = body.get('company_name')  # Optional; For LLM context
        lead_data = body.get('lead_data')  # Optional; Full lead data for personalization
        
        print(f"📞 Extracted: to_number={to_number}, name={name}, lead_data_present={bool(lead_data)}")
        
        if not to_number:
            print(f"❌ Missing to_number in request body: {body}")
            return {"success": False, "error": "Missing 'to_number' parameter"}
        
        # Extract only digits and validate for 10-digit Indian number
        clean = ''.join(filter(str.isdigit, to_number))
        if len(clean) < 10:
            return {"success": False, "error": "Phone number must have at least 10 digits"}
        
        # Extract last 10 digits (removes country codes like +91, 91)
        ten_digit_number = clean[-10:]
        if len(ten_digit_number) != 10:
            return {"success": False, "error": "Phone number must be exactly 10 digits"}
        
        # 🆕 DATABASE-FIRST: Save lead data to DB before making call
        # This ensures lead data persists even if server restarts
        if lead_data:
            print(f"💾 Saving lead data to database for {ten_digit_number}")
            try:
                lead_id = db.create_or_update_lead(
                    phone_number=ten_digit_number,
                    name=name,
                    lead_data=lead_data
                )
                print(f"✅ Lead saved to DB with ID: {lead_id}")
            except Exception as db_err:
                print(f"⚠️ Failed to save lead to DB (non-critical): {db_err}")
        
        print(f"📞 Attempting Cube call to: {ten_digit_number} (extracted from: {to_number})")
        # Pass the extracted 10-digit number to the function
        result = await make_cube_outbound_call(ten_digit_number, campaign_id, did, name=name, company_name=company_name, lead_data=lead_data)
        return result
        
    except Exception as e:
        err_msg = str(e).strip() or "Server error"
        print(f"❌ Error in make_call_endpoint: {e}")
        return {"success": False, "error": err_msg}

@app.get("/vad-status")
async def vad_status_endpoint():
    """Check status of VAD service connection."""
    vad_url = VADConfig.VAD_SERVICE_URL
    status = {
        "enabled": VADConfig.ENABLED,
        "use_service": VADConfig.USE_VAD_SERVICE,
        "service_url": vad_url,
        "connected": False,
        "error": None
    }
    
    if not (VADConfig.ENABLED and VADConfig.USE_VAD_SERVICE):
        return status

    try:
        # Try to connect to VAD service with short timeout
        async with websockets.connect(vad_url, ping_timeout=2) as ws:
            # Wait for welcome message
            welcome = await asyncio.wait_for(ws.recv(), timeout=2)
            welcome_data = json.loads(welcome)
            status["connected"] = True
            status["details"] = welcome_data
    except Exception as e:
        status["error"] = str(e)
        status["hint"] = "Check if VAD service is running on PORT 8765"
        
    return status


@app.get("/call-status")
async def call_status_endpoint():
    """Get Cube configuration status."""
    return {
        "cube_configured": bool(CUBE_CLICK2CALL_URL and CUBE_CAMPAIGN_ID and CUBE_DID),
        "cube_did": CUBE_DID,
        "cube_campaign_id": CUBE_CAMPAIGN_ID,
        "websocket_endpoint": f"ws://your-server:{CUBE_WEBSOCKET_PORT}/swara_voicebot"
    }



# Cube uses PCM natively - no mulaw conversion needed

# ── Singleton Azure TTS synthesizer ──────────────────────────────────────────
# Reused across all calls — the SDK keeps an internal WebSocket to Azure alive,
# saving ~100-200ms of connection overhead per synthesis call.
_tts_synthesizer = None
_tts_synthesizer_lock = threading.Lock()

def _create_tts_synthesizer():
    cfg = speechsdk.SpeechConfig(subscription=AZURE_SPEECH_KEY, region=AZURE_SPEECH_REGION)
    cfg.speech_synthesis_voice_name = AZURE_TTS_VOICE
    cfg.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Raw8Khz16BitMonoPcm
    )
    return speechsdk.SpeechSynthesizer(speech_config=cfg, audio_config=None)


def synthesize_speech_azure_sdk(text, language="hi-IN"):
    """Convert text to speech using Azure Speech SDK — reuses singleton synthesizer."""
    global _tts_synthesizer
    try:
        cache_key = f"{text}:{language}"
        cached_audio = response_cache.get(cache_key)
        if cached_audio:
            metrics.record_cache_access(hit=True)
            print("🎯 Using cached TTS response")
            return cached_audio
        metrics.record_cache_access(hit=False)

        with _tts_synthesizer_lock:
            if _tts_synthesizer is None:
                _tts_synthesizer = _create_tts_synthesizer()
            synth = _tts_synthesizer

        escaped_text = saxutils.escape(text)
        escaped_text = escaped_text.replace(
            'Faber',
            "<phoneme alphabet='ipa' ph='ˈfeɪbər'>Faber</phoneme>"
        )
        escaped_text = escaped_text.replace(
            'Amazon',
            "<emphasis level='strong'>Amazon</emphasis>"
        )
        escaped_text = escaped_text.replace(
            '[PAUSE]',
            "<break time='1500ms'/>"
        )
        ssml = (
            f"<speak version='1.0' xml:lang='hi-IN'>"
            f"<voice name='{AZURE_TTS_VOICE}'>"
            f"<prosody rate='1.1' pitch='+2%'>{escaped_text}</prosody>"
            f"</voice></speak>"
        )

        result = synth.speak_ssml_async(ssml).get()

        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            pcm_audio = result.audio_data
            if pcm_audio:
                audio_b64 = base64.b64encode(pcm_audio).decode('utf-8')
                response_cache.set(cache_key, audio_b64)
                print(f"✅ Azure TTS: {len(pcm_audio)} bytes cached")
                return audio_b64
        elif result.reason == speechsdk.ResultReason.Canceled:
            details = speechsdk.SpeechSynthesisCancellationDetails(result)
            print(f"❌ Azure TTS canceled: {details.reason} — {details.error_details}")
            # Auto-recover: recreate synthesizer
            with _tts_synthesizer_lock:
                _tts_synthesizer = _create_tts_synthesizer()
        return None

    except Exception as e:
        print(f"❌ Error with Azure TTS: {e}")
        import traceback
        traceback.print_exc()
        with _tts_synthesizer_lock:
            _tts_synthesizer = _create_tts_synthesizer()
        return None


async def synthesize_speech_azure(text, language="hi-IN"):
    """Async wrapper for Azure TTS with optimized thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(tts_executor, synthesize_speech_azure_sdk, text, language)


async def generate_tts_for_future(text: str, future: asyncio.Future, language="hi-IN"):
    """Synthesize TTS in the thread pool and resolve the future when done."""
    loop = asyncio.get_event_loop()
    audio_b64 = await loop.run_in_executor(tts_executor, synthesize_speech_azure_sdk, text, language)
    if not future.cancelled():
        future.set_result(audio_b64)


class AudioQueueManager:
    """Parallel TTS pipeline with Future-based ordering for Cube VoIP.

    LLM sentence 1 → Future₁ → TTS starts immediately in thread pool
    LLM sentence 2 → Future₂ → TTS starts immediately in thread pool
    Play queue:  await Future₁ → send_cube_audio → await Future₂ → send ...

    Sentences always play in order even if TTS for later sentences finishes first.
    """

    def __init__(self, websocket, stream_sid, bot_speaking_flag, interruption_state,
                 ack_done_event=None, on_first_audio=None, on_stt_close=None):
        self.websocket = websocket
        self.stream_sid = stream_sid
        self.bot_speaking_flag = bot_speaking_flag
        self.interruption_state = interruption_state
        self.ack_done_event = ack_done_event
        self.on_first_audio = on_first_audio   # → open_stt_gate()
        self.on_stt_close = on_stt_close        # → close_stt_gate()
        self.audio_queue: asyncio.Queue = asyncio.Queue()
        self.is_closed = False
        self._pre_roll_task = None
        self._play_task = asyncio.create_task(self._play_queue())

    async def add_future(self, future: asyncio.Future) -> bool:
        if self.is_closed:
            return False
        await self.audio_queue.put(future)
        return True

    async def mark_completed(self):
        if not self.is_closed:
            await self.audio_queue.put(None)  # sentinel

    async def clear(self):
        self.is_closed = True
        if self._play_task and not self._play_task.done():
            self._play_task.cancel()
        print("✅ AudioQueueManager cleared (interruption)")

    async def _play_queue(self):
        sentences_played = 0
        try:
            while True:
                item = await self.audio_queue.get()
                if item is None or self.is_closed:
                    break

                future: asyncio.Future = item
                try:
                    audio_b64 = await asyncio.wait_for(future, timeout=60)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    print("⚠️ TTS future timed out / cancelled — skipping sentence")
                    continue

                if not audio_b64 or self.is_closed:
                    continue

                # Wait for ack before the very first sentence
                if sentences_played == 0:
                    if self.ack_done_event and not self.ack_done_event.is_set():
                        print("⏳ Waiting for ack before first audio...")
                        await self.ack_done_event.wait()
                        print("✅ Ack done — streaming first sentence")

                pcm_audio = base64.b64decode(audio_b64)
                duration_seconds = len(pcm_audio) / 16000  # 8kHz * 2 bytes/sample
                buffer_time = 0.2
                total_wait_time = duration_seconds + buffer_time

                sentences_played += 1
                print(f"🎵 Processing sentence #{sentences_played}")

                # ── STT gate: CLOSE at start of every sentence (suppress echo) ──
                if self.on_stt_close:
                    asyncio.create_task(self.on_stt_close())

                # ── 1-second pre-roll: gate opens 1s before this sentence ends ──
                # Cancel previous sentence's pre-roll (it re-closed the gate already)
                if self.on_first_audio:
                    if self._pre_roll_task and not self._pre_roll_task.done():
                        self._pre_roll_task.cancel()
                    _pre_delay = max(0.0, total_wait_time - 1.0)
                    async def _pre_roll(delay=_pre_delay, cb=self.on_first_audio):
                        await asyncio.sleep(delay)
                        print(f"[AudioQueue] 1s pre-roll: starting STT before sentence ends")
                        await cb()
                    self._pre_roll_task = asyncio.create_task(_pre_roll())

                completed = await send_cube_audio(
                    self.websocket, pcm_audio,
                    self.bot_speaking_flag, self.interruption_state
                )
                if not completed:
                    print("🛑 AudioQueueManager: send_cube_audio interrupted")
                    break

        except asyncio.CancelledError:
            print("⚠️ AudioQueueManager._play_queue cancelled")
        except Exception as e:
            print(f"❌ AudioQueueManager._play_queue error: {e}")
        finally:
            self.is_closed = True
            if self.bot_speaking_flag:
                self.bot_speaking_flag['speaking'] = False
                print("🔕 Bot speaking flag CLEARED (AudioQueueManager natural end)")
            if self.interruption_state:
                self.interruption_state.audio_stream_active = False
            # Safety re-open: gate must never stay closed after bot finishes
            if self.on_first_audio:
                print("🔓 Bot finished speaking — firing stt_unblock (natural end)")
                try:
                    asyncio.create_task(self.on_first_audio())
                except Exception:
                    pass

async def run_synthesis_async(synthesizer, ssml):
    """Run speech synthesis in async executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(tts_executor, synthesizer.speak_ssml, ssml)

async def execute_function_call(function_name, arguments, websocket=None, stream_sid=None, bot_speaking_flag=None):
    """Execute a function call and return the result."""
    try:
        # Special handling for End Call (Hangup)
        if function_name == "end_call":
            if websocket:
                print(f"📞 Hanging up call per LLM request. Reason: {arguments.get('reason')}")
                try:
                    # Cube Protocol: Hangup is message type 0x00
                    # Format: [0x00][optional_reason_bytes]
                    msg_type = b'\x00'
                    reason_str = arguments.get('reason', 'Call ended by AI')
                    reason_bytes = reason_str.encode('utf-8')
                    
                    # Send binary message
                    await websocket.send_bytes(msg_type + reason_bytes)
                    print(f"✅ Hangup signal (0x00) sent to Cube with reason: {reason_str}")
                    
                    # Optional: Close socket gracefully after a brief moment
                    # await asyncio.sleep(0.5) 
                    # await websocket.close()
                    
                    return {"status": "success", "message": "Call ended successfully"}
                except Exception as e:
                    print(f"❌ Error sending hangup signal: {e}")
                    return {"error": f"Failed to hangup: {str(e)}"}
            else:
                print("⚠️ Cannot end call: WebSocket is None")
                return {"error": "No active connection to hang up"}

        if function_name not in FUNCTION_MAPPING:
            return {"error": f"Unknown function: {function_name}"}
        
        function = FUNCTION_MAPPING[function_name]
        print(f"🔧 Executing function: {function_name} with args: {arguments}")
        
        # Check if function is async or sync
        if asyncio.iscoroutinefunction(function):
            # Async function
            result = await function(**arguments)
        else:
            # Sync function - run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            # Create a lambda to pass arguments correctly
            sync_func = lambda: function(**arguments)
            result = await loop.run_in_executor(None, sync_func)
        
        print(f"✅ Function {function_name} completed: {result}")
        
        return result
        
    except Exception as e:
        print(f"❌ Error executing function {function_name}: {e}")
        return {"error": str(e)}

async def execute_parallel_functions(function_calls):
    """Execute multiple function calls in parallel for faster processing."""
    try:
        print(f"🚀 Executing {len(function_calls)} functions in parallel")
        
        # Prepare all function calls
        tasks = []
        for func_name, args in function_calls:
            if func_name in FUNCTION_MAPPING:
                function = FUNCTION_MAPPING[func_name]
                if asyncio.iscoroutinefunction(function):
                    tasks.append(function(**args))
                else:
                    # Wrap sync function in executor
                    loop = asyncio.get_event_loop()
                    sync_func = lambda f=function, a=args: f(**a)
                    tasks.append(loop.run_in_executor(None, sync_func))
            else:
                print(f"❌ Unknown function: {func_name}")
        
        # Execute all functions in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        parallel_results = {}
        for i, (func_name, _) in enumerate(function_calls):
            if i < len(results):
                result = results[i]
                if isinstance(result, Exception):
                    parallel_results[func_name] = {"error": str(result)}
                    print(f"❌ Function {func_name} failed: {result}")
                else:
                    parallel_results[func_name] = result
                    print(f"✅ Function {func_name} completed in parallel")
        
        print(f"🎯 Parallel execution completed: {len(parallel_results)} functions")
        return parallel_results
        
    except Exception as e:
        print(f"❌ Error in parallel function execution: {e}")
        return {"error": str(e)}


async def _make_azure_openai_request(messages, websocket=None, stream_sid=None, bot_speaking_flag=None):
    """Internal function to make Azure OpenAI API request."""
    headers = {
        "Content-Type": "application/json",
        "api-key": AZURE_OPENAI_API_KEY
    }
    
    data = {
        "messages": messages,
        "max_tokens": 150,         # Reduced for faster generation
        "temperature": 0.5,       # More focused responses
        "top_p": 0.7,            # More focused sampling
        "presence_penalty": 0.1,  # Reduce repetition
        "frequency_penalty": 0.1, # Reduce repetition
        "stream": False,          # Keep non-streaming for stability
        "functions": AVAILABLE_FUNCTIONS,
        "function_call": "auto"
    }
    
    url = f"{AZURE_OPENAI_ENDPOINT}openai/deployments/{AZURE_OPENAI_DEPLOYMENT}/chat/completions?api-version={OPENAI_API_VERSION}"
    
    # Set optimized timeout for faster requests
    timeout = aiohttp.ClientTimeout(total=15, connect=5, sock_read=10)
    session = await http_manager.get_session()
    
    async with session.post(url, headers=headers, json=data, timeout=timeout) as response:
        result = await response.json()
        
        if 'error' in result:
            print(f"❌ Azure OpenAI API Error: {result['error']}")
            return "I'm sorry, I'm experiencing technical difficulties. Please try again."
        
        if 'choices' not in result or not result['choices']:
            print(f"❌ Unexpected response structure: {result}")
            return "I'm sorry, I'm having trouble understanding. Please repeat."
        
        choice = result['choices'][0]
        message = choice['message']
        
        # Check if function call is requested
        if 'function_call' in message:
            function_name = message['function_call']['name']
            
            try:
                function_args = json.loads(message['function_call']['arguments'])
            except json.JSONDecodeError as e:
                print(f"❌ Invalid function arguments JSON: {e}")
                return "I'm having trouble processing your request. Please try again."
            
            function_result = await execute_function_call(function_name, function_args, websocket, stream_sid, bot_speaking_flag)
            
            # Add function result to conversation and get final response
            messages.append({
                "role": "assistant",
                "content": None,
                "function_call": message['function_call']
            })
            messages.append({
                "role": "function",
                "name": function_name,
                "content": json.dumps(function_result)
            })
            
            # Get final response from AI after function execution
            return await get_azure_openai_response(messages, websocket, stream_sid, bot_speaking_flag)
        
        return message['content']

async def get_azure_openai_response(messages, websocket=None, stream_sid=None, bot_speaking_flag=None):
    """Non-streaming fallback for function calls with retry logic."""
    try:
        # Use retry logic for Azure OpenAI API calls
        result = await retry_with_exponential_backoff(_make_azure_openai_request, messages, websocket, stream_sid, bot_speaking_flag)
        return result
        
    except Exception as e:
        print(f"❌ Error calling Azure OpenAI API after retries: {e}")
        return "I'm sorry, I'm experiencing technical difficulties. Please contact us again later."


# ========== STREAMING LLM FUNCTIONS ==========

async def get_azure_openai_stream(messages, websocket, stream_sid, bot_speaking_flag):
    """
    Generate response using streaming. Yields full sentences to TTS as soon as ready.
    Uses [HANGUP] tag detection for ending calls.
    NO function calling (CRM updates happen post-call).
    """
    headers = {
        "Content-Type": "application/json",
        "api-key": AZURE_OPENAI_API_KEY
    }
    data = {
        "messages": messages,
        "max_tokens": 150,
        "temperature": 0.5,
        "stream": True,
        # No functions in stream mode for pure speed/stability
    }
    url = f"{AZURE_OPENAI_ENDPOINT}openai/deployments/{AZURE_OPENAI_DEPLOYMENT}/chat/completions?api-version={OPENAI_API_VERSION}"
    
    buffer = ""
    sentence_endings = {'.', '!', '?', '।' , ','}
    hangup_detected = False
    
    # Generous timeouts
    timeout = aiohttp.ClientTimeout(total=90, connect=30, sock_read=60)
    session = await http_manager.get_session()
    
    try:
        async with session.post(url, headers=headers, json=data, timeout=timeout) as response:
            if response.status != 200:
                body = await response.text()
                print(f"❌ Azure OpenAI stream error: {response.status} {body}")
                if buffer.strip():
                    yield buffer
                return
                
            while True:
                line = await response.content.readline()
                if not line:
                    break
                line_text = line.decode('utf-8').strip()
                if line_text.startswith("data: ") and line_text != "data: [DONE]":
                    try:
                        chunk_json = json.loads(line_text[6:])
                        if chunk_json.get('choices'):
                            delta = chunk_json['choices'][0].get('delta', {})
                            content = delta.get('content', "") or ""
                            
                            if content:
                                buffer += content
                                
                                # Check for [HANGUP] tag
                                if "[HANGUP]" in buffer:
                                    hangup_detected = True
                                    # Remove tag from speech
                                    buffer = buffer.replace("[HANGUP]", "").strip()
                                
                                if any(p in content for p in sentence_endings) or hangup_detected:
                                    if buffer.strip():
                                        yield buffer
                                    buffer = ""
                                    
                                    if hangup_detected:
                                        # DEFER the hangup — do NOT send 0x00 now. The goodbye
                                        # sentence we just yielded is still being synthesized +
                                        # played by the AudioQueueManager. Firing 0x00 here (before
                                        # the goodbye, with more audio streaming after it) does NOT
                                        # drop the Cube call. Flag it; process_user_speech_parallel
                                        # sends 0x00 + CLOSES the socket AFTER the audio drains.
                                        print("📞 [HANGUP] detected — will hang up after goodbye audio drains")
                                        if bot_speaking_flag is not None:
                                            bot_speaking_flag['hangup'] = True
                                        return  # Stop generating further
                                            
                    except (json.JSONDecodeError, KeyError):
                        pass
        
        # Yield any remaining text buffer
        if buffer.strip():
            # Final check for tag in remaining buffer
            if "[HANGUP]" in buffer:
                hangup_detected = True
                buffer = buffer.replace("[HANGUP]", "").strip()
                
            if buffer:
                yield buffer
                
            if hangup_detected:
                print("📞 [HANGUP] detected at end of stream — will hang up after goodbye audio drains")
                if bot_speaking_flag is not None:
                    bot_speaking_flag['hangup'] = True
                
    except Exception as e:
        print(f"❌ Error in get_azure_openai_stream: {e}")
        if buffer.strip():
            yield buffer


async def _stream_llm_tokens(messages: list):
    """
    Yield raw LLM content tokens one by one (no sentence buffering).
    Yields str tokens normally; yields {"hangup": True} when [HANGUP] is detected.
    """
    headers = {
        "Content-Type": "application/json",
        "api-key": AZURE_OPENAI_API_KEY,
    }
    data = {
        "messages": messages,
        "max_tokens": 150,
        "temperature": 0.5,
        "stream": True,
    }
    url = (
        f"{AZURE_OPENAI_ENDPOINT}openai/deployments/{AZURE_OPENAI_DEPLOYMENT}"
        f"/chat/completions?api-version={OPENAI_API_VERSION}"
    )
    timeout = aiohttp.ClientTimeout(total=90, connect=30, sock_read=60)
    session = await http_manager.get_session()
    accumulated = ""
    try:
        async with session.post(url, headers=headers, json=data, timeout=timeout) as response:
            if response.status != 200:
                body = await response.text()
                print(f"❌ Azure OpenAI token stream error: {response.status} {body}")
                return
            while True:
                line = await response.content.readline()
                if not line:
                    break
                line_text = line.decode("utf-8").strip()
                if not line_text.startswith("data: ") or line_text == "data: [DONE]":
                    continue
                try:
                    chunk_json = json.loads(line_text[6:])
                    choices = chunk_json.get("choices")
                    if not choices:
                        continue
                    content = choices[0].get("delta", {}).get("content", "") or ""
                    if not content:
                        continue
                    accumulated += content
                    if "[HANGUP]" in accumulated:
                        clean = accumulated.replace("[HANGUP]", "").strip()
                        if clean:
                            yield clean
                        yield {"hangup": True}
                        return
                    yield content
                except (json.JSONDecodeError, KeyError):
                    pass
    except Exception as e:
        print(f"❌ Error in LLM token stream: {e}")


# ========== INTERRUPTION HANDLING FUNCTIONS ==========

# ========== INTERRUPTION HANDLING UTILITIES ==========

async def cancel_ongoing_audio(websocket, stream_sid, interruption_state):
    """Cancel ongoing audio playback on Cube stream (including streaming queue)."""
    try:
        if not interruption_state.audio_stream_active:
            return
        
        print("🛑 Canceling ongoing audio playback...")
        
        # Clear streaming audio queue if active
        if getattr(interruption_state, 'current_audio_manager', None):
            am = interruption_state.current_audio_manager
            interruption_state.current_audio_manager = None
            await am.clear()
            print("✅ Streaming audio queue cleared")
        
        # Send Cube clear command to stop audio immediately
        try:
            clear_event_bytes = json.dumps({"event": "clear"}).encode('utf-8')
            await websocket.send_bytes(clear_event_bytes)
            print("✅ Audio stream cleared (Cube binary)")
        except Exception as e:
            print(f"⚠️ Error sending clear command: {e}")
        
        if interruption_state.current_tts_task and not interruption_state.current_tts_task.done():
            interruption_state.current_tts_task.cancel()
            print("✅ TTS task cancelled")
        
        interruption_state.audio_stream_active = False
        interruption_state.current_tts_task = None
        
    except Exception as e:
        print(f"❌ Error canceling audio: {e}")


async def handle_vad_interruption(websocket, stream_sid, bot_speaking_flag, interruption_state):
    """Handle interruption triggered by Voice Activity Detection (VAD).
    
    This is called when audio energy indicates user is speaking, BEFORE speech
    recognition completes. Stops bot immediately for instant response.
    """
    try:
        print(f"🎤 VAD: User voice detected while bot speaking!")
        
        # Cancel audio immediately (this is the key to instant interruptions)
        await cancel_ongoing_audio(websocket, stream_sid, interruption_state)
        
        # Clear bot speaking flag immediately to stop any ongoing response
        if bot_speaking_flag is not None:
            bot_speaking_flag['speaking'] = False
            print("🔕 Bot speaking flag CLEARED due to VAD interruption")
        
        # Record VAD trigger
        interruption_state.record_vad_trigger()
        interruption_state.record_interruption("VAD triggered")
        
        print(f"⚡ Bot stopped via VAD (interruption #{interruption_state.interruption_count})")
        print(f"⏳ Waiting for speech recognition to provide complete text...")
        
        # Note: We don't send acknowledgment yet - wait for actual recognized text
        # The recognized_handler will process the text when it's ready
        
    except Exception as e:
        print(f"❌ Error in VAD interruption handling: {e}")


# ========== VAD (VOICE ACTIVITY DETECTION) UTILITIES ==========

def calculate_audio_energy(pcm_audio: bytes) -> float:
    """Calculate RMS energy of PCM audio for voice activity detection.
    
    Uses audioop.rms() which is C-optimized and ~10x faster than manual
    struct.unpack + Python loop. Production-safe for high concurrency (10-20 calls).
    
    Args:
        pcm_audio: PCM audio data (16-bit signed integers, little-endian)
        
    Returns:
        RMS energy level (0-32768 for 16-bit audio)
    """
    try:
        if len(pcm_audio) < 2:
            return 0.0
        
        # SHORT-CIRCUIT: Skip RMS calculation for silence/comfort noise packets
        # Twilio sometimes sends zeroed frames, comfort noise, or network padding
        # This saves CPU during silence (~50% of call duration is silence)
        if pcm_audio == b'\x00' * len(pcm_audio):
            return 0.0
        
        # OPTIONAL: Simple DC offset removal for telephony (removes low-frequency hum)
        # This is a lightweight filter that costs ~0.1ms but can improve VAD accuracy
        # Comment out if you don't need it
        try:
            # Remove DC bias using audioop (very fast, C-optimized)
            # This filters out constant low-frequency noise common in PSTN
            pcm_audio = audioop.bias(pcm_audio, 2, 0)  # 2 = 16-bit samples
        except:
            pass  # If bias removal fails, use original audio
        
        # Use C-optimized audioop.rms() instead of manual calculation
        # Second argument is sample width in bytes (2 = 16-bit audio)
        return float(audioop.rms(pcm_audio, 2))
    except Exception:
        # If calculation fails, return 0
        return 0.0


# ========== INTERRUPTION HANDLING UTILITIES ==========



async def handle_interruption(user_text, websocket, stream_sid, bot_speaking_flag, interruption_state):
    """Handle user interruption during bot speech."""
    try:
        # Check if interruption is valid
        word_count = len(user_text.split())
        if word_count < InterruptionConfig.MIN_SPEECH_LENGTH:
            print(f"🔇 Interruption too short ({word_count} words), ignoring")
            return False
        
        # ========== ALPHA CHARACTER CHECK (Solution 3) ==========
        # Filter non-speech sounds like "khhh", "hmm", "uh" that don't contain real words
        # Real speech contains alphabetic characters, not just sounds
        if not any(char.isalpha() for char in user_text):
            print(f"🔇 No alphabetic characters in '{user_text}', ignoring (likely noise)")
            return False
        
        if not interruption_state.can_interrupt():
            print(f"⏳ Interruption cooldown active, ignoring")
            return False
        
        print(f"🛑 INTERRUPTION DETECTED: '{user_text}'")
        
        # Add small delay for debouncing
        await asyncio.sleep(InterruptionConfig.CANCEL_DELAY)
        
        # Cancel ongoing audio
        await cancel_ongoing_audio(websocket, stream_sid, interruption_state)
        
        # Clear bot speaking flag immediately
        bot_speaking_flag['speaking'] = False
        print("🔕 Bot speaking flag CLEARED due to interruption")
        
        # Record the interruption
        interrupted_text = interruption_state.interrupted_response
        interruption_state.record_interruption(interrupted_text)
        
        # Optional: Send brief acknowledgment
        if InterruptionConfig.ACKNOWLEDGE_INTERRUPTION and InterruptionConfig.ACKNOWLEDGMENTS:
            import random
            ack = random.choice(InterruptionConfig.ACKNOWLEDGMENTS)
            if ack:  # Only if not empty string
                print(f"💬 Sending interruption acknowledgment: '{ack}'")
                # Send very brief acknowledgment (non-blocking)
                asyncio.create_task(
                    send_brief_acknowledgment(ack, websocket, stream_sid, bot_speaking_flag)
                )
                await asyncio.sleep(0.3)  # Brief pause for acknowledgment
        
        return True  # Interruption handled
        
    except Exception as e:
        print(f"❌ Error handling interruption: {e}")
        return False

def synthesize_acknowledgment_tts(text, language="hi-IN"):
    """Synthesize quick acknowledgment using Azure Speech SDK — reuses singleton synthesizer."""
    global _tts_synthesizer
    try:
        cache_key = f"ack:{text}:{language}"
        cached_audio = response_cache.get(cache_key)
        if cached_audio:
            print("🎯 Using cached acknowledgment TTS")
            return cached_audio

        with _tts_synthesizer_lock:
            if _tts_synthesizer is None:
                _tts_synthesizer = _create_tts_synthesizer()
            synth = _tts_synthesizer

        escaped_text = saxutils.escape(text)
        escaped_text = escaped_text.replace(
            'Faber',
            "<phoneme alphabet='ipa' ph='ˈfeɪbər'>Faber</phoneme>"
        )
        escaped_text = escaped_text.replace(
            'Amazon',
            "<emphasis level='strong'>Amazon</emphasis>"
        )
        escaped_text = escaped_text.replace(
            '[PAUSE]',
            "<break time='1500ms'/>"
        )
        ssml = (
            f"<speak version='1.0' xml:lang='hi-IN'>"
            f"<voice name='{AZURE_TTS_VOICE}'>"
            f"<prosody rate='0.9' pitch='+4%'>{escaped_text}</prosody>"
            f"</voice></speak>"
        )

        result = synth.speak_ssml_async(ssml).get()

        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            pcm_audio = result.audio_data
            if pcm_audio:
                audio_b64 = base64.b64encode(pcm_audio).decode('utf-8')
                response_cache.set(cache_key, audio_b64)
                print(f"✅ Acknowledgment TTS generated: '{text}'")
                return audio_b64
        elif result.reason == speechsdk.ResultReason.Canceled:
            details = speechsdk.SpeechSynthesisCancellationDetails(result)
            print(f"❌ Azure TTS ack canceled: {details.reason} — {details.error_details}")
            with _tts_synthesizer_lock:
                _tts_synthesizer = _create_tts_synthesizer()

        return None

    except Exception as e:
        print(f"❌ Error with acknowledgment TTS: {e}")
        import traceback
        traceback.print_exc()
        with _tts_synthesizer_lock:
            _tts_synthesizer = _create_tts_synthesizer()
        return None

async def synthesize_acknowledgment_async(text, language="hi-IN"):
    """Async wrapper for acknowledgment TTS."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(tts_executor, synthesize_acknowledgment_tts, text, language)

async def send_brief_acknowledgment(text, websocket, stream_sid, bot_speaking_flag):
    """Send very brief acknowledgment using Cube-compatible RAW PCM format.
    
    CUBE FORMAT: Decode and send raw PCM bytes (NOT JSON like Twilio!)
    
    IMPORTANT: Waits for acknowledgment to complete to prevent audio overlap!
    """
    try:
        # Use dedicated acknowledgment TTS (different voice)
        audio_b64 = await synthesize_acknowledgment_async(text, "hi-IN")
        if audio_b64:
            # ✅ CUBE FORMAT: Decode and send raw PCM bytes (NOT JSON!)
            pcm_audio = base64.b64decode(audio_b64)
            
            # Calculate audio duration for proper timing
            total_bytes = len(pcm_audio)
            bytes_per_second = 16000  # 8kHz * 16-bit = 16000 bytes/sec
            audio_duration = total_bytes / bytes_per_second
            
            # Send audio
            await websocket.send_bytes(pcm_audio)
            print(f"✅ Acknowledgment sent: '{text}' ({len(pcm_audio)} bytes, {audio_duration:.2f}s)")
            
            # ⚡ WAIT for acknowledgment to complete before returning
            # This prevents the main response from overlapping!
            playback_buffer = 0.2  # 200ms buffer for network latency
            total_wait = audio_duration + playback_buffer
            print(f"⏳ Waiting {total_wait:.2f}s for acknowledgment to complete...")
            await asyncio.sleep(total_wait)
            print(f"✅ Acknowledgment playback completed")
            
    except Exception as e:
        print(f"❌ Error sending acknowledgment: {e}")


async def send_ai_response(text, websocket, stream_sid, language="hi-IN", is_bot_speaking_flag=None, use_streaming=True, interruption_state=None):
    """Send AI response as audio using Cube one-shot sending."""
    try:
        print(f"🎤 Sending AI response: {text}")
        
        # Store the response text in interruption state (for tracking what might be interrupted)
        if interruption_state:
            interruption_state.interrupted_response = text
            # Reset VAD state for new TTS (enables fresh VAD trigger opportunity)
            interruption_state.reset_for_new_tts()
        
        # Set flag immediately
        if is_bot_speaking_flag is not None:
            is_bot_speaking_flag['speaking'] = True
            print("🔊 Bot speaking flag SET")
        
        # Mark audio as active for interruption handling
        if interruption_state:
            interruption_state.audio_stream_active = True
        
        # Generate TTS
        audio_b64 = await synthesize_speech_azure(text, language)
        if audio_b64:
            # Decode to PCM
            pcm_audio = base64.b64decode(audio_b64)
            
            # Send using reliable one-shot function
            await send_cube_audio(websocket, pcm_audio, is_bot_speaking_flag, interruption_state)
        else:
            print("❌ Failed to generate TTS audio")
            if is_bot_speaking_flag:
                is_bot_speaking_flag['speaking'] = False
            
    except Exception as e:
        print(f"❌ Error sending AI response: {e}")
        if is_bot_speaking_flag is not None:
            is_bot_speaking_flag['speaking'] = False
            print("🔕 Bot speaking flag CLEARED due to error")
        if interruption_state:
            interruption_state.audio_stream_active = False


async def trigger_speech_recognition_sarvam(conversation_history, websocket, stream_sid, speech_recognizer, bot_speaking_state, interruption_state=None, utterance_buffer=None):
    """Speech recognition with Azure STT and utterance buffering.
    
    The utterance buffer prevents duplicate LLM calls by:
    1. Sending to LLM immediately (no delay)
    2. If user speaks again while LLM is processing → Cancel LLM, combine, resend
    3. Ensures only ONE response per user "thought"
    """
    try:
        current_loop = asyncio.get_running_loop()
        
        # Create utterance buffer if not provided
        if utterance_buffer is None:
            config = UtteranceBufferConfig(
                debug_logging=True
            )
            utterance_buffer = UtteranceBuffer(config)
        
        async def safe_send_ack(ack, websocket, stream_sid, bot_speaking_state):
            """Safely send acknowledgment in background - handles shutdown gracefully."""
            try:
                await send_brief_acknowledgment(ack, websocket, stream_sid, bot_speaking_state)
            except Exception as e:
                # Ignore errors during shutdown (connection closed, etc.)
                if "closed" not in str(e).lower():
                    print(f"⚠️ Ack error: {e}")
        
        async def process_buffered_speech(text):
            """Process the utterance with PARALLEL acknowledgment for low latency."""
            # ⚡ PARALLEL EXECUTION: Start LLM immediately, send ack in background
            # This saves ~700-1200ms latency compared to sequential
            
            # Send acknowledgment in background (non-blocking)
            if InterruptionConfig.ACKNOWLEDGE_UTTERANCE and InterruptionConfig.UTTERANCE_ACKNOWLEDGMENTS:
                import random
                ack = random.choice(InterruptionConfig.UTTERANCE_ACKNOWLEDGMENTS)
                if ack:  # Only if not empty string
                    print(f"💬 Sending utterance acknowledgment (parallel): '{ack}'")
                    asyncio.create_task(safe_send_ack(ack, websocket, stream_sid, bot_speaking_state))
            
            # Start LLM processing immediately (don't wait for ack)
            await process_user_speech_parallel(
                text,
                conversation_history,
                websocket,
                stream_sid,
                bot_speaking_state,
                interruption_state
            )
        
        def recognized_handler(evt):
            # Azure STT provides events in Azure-compatible format
            if hasattr(evt, 'result') and hasattr(evt.result, 'text'):
                user_text = evt.result.text.strip()
            else:
                return
            
            if not user_text:
                return
            
            # Filter very short utterances
            if len(user_text.split()) < 1:
                print(f"🔇 Very short utterance: {user_text}")
                return
            
            print(f"🗣️ User said: {user_text}")
            
            # Check if this is after a VAD trigger (user interrupted the bot)
            if interruption_state and interruption_state.pending_recognition:
                print(f"✅ Speech recognized after VAD interruption: '{user_text}'")
                interruption_state.pending_recognition = False
                
                # Send acknowledgment now that we have the user's text
                if InterruptionConfig.ACKNOWLEDGE_INTERRUPTION and InterruptionConfig.ACKNOWLEDGMENTS:
                    import random
                    acknowledgment = random.choice(InterruptionConfig.ACKNOWLEDGMENTS)
                    if acknowledgment:  # Only if not empty string
                        print(f"💬 Sending interruption acknowledgment: '{acknowledgment}'")
                        asyncio.run_coroutine_threadsafe(
                            send_brief_acknowledgment(acknowledgment, websocket, stream_sid, bot_speaking_state),
                            current_loop
                        )
            
            # ALL utterances go through the buffer for cancel+combine support
            asyncio.run_coroutine_threadsafe(
                utterance_buffer.add_utterance(
                    user_text,
                    process_buffered_speech
                ),
                current_loop
            )
        
        def recognizing_handler(evt):
            if hasattr(evt, 'result') and hasattr(evt.result, 'text'):
                partial_text = evt.result.text.strip()
                if partial_text and len(partial_text) > 3:
                    # Print partial text
                    print(f"\r🎤 {partial_text[:80]}", end='', flush=True)
                    
                    # ⚡ INSTANT CANCEL: If LLM is processing, cancel only if SIGNIFICANT new speech detected
                    # We disabled the aggressive cancellation because it was killing the stream on trailing noise/echo
                    # if utterance_buffer.is_processing:
                    #     cancelled = utterance_buffer.cancel_on_new_speech_detected()
                    #     if cancelled:
                    #         print(f"\n⚡ Cancelled LLM - user is still speaking!")
        
        # Set up event handlers for Azure STT
        speech_recognizer.on_recognized = recognized_handler
        speech_recognizer.on_recognizing = recognizing_handler

        # Start Azure STT session (async)
        await speech_recognizer.start_async()
        print("🎤 Azure STT started (Hindi + English India, interruptions enabled)")

    except Exception as e:
        print(f"❌ Error starting Azure STT: {e}")

async def handle_user_interruption(user_text, conversation_history, websocket, stream_sid, bot_speaking_flag, interruption_state):
    """Handle user interruption during bot speech."""
    try:
        # Validate and handle the interruption
        interruption_handled = await handle_interruption(
            user_text, 
            websocket, 
            stream_sid, 
            bot_speaking_flag, 
            interruption_state
        )
        
        if not interruption_handled:
            print("⚠️ Interruption not valid, ignoring")
            return
        
        print(f"✅ Interruption handled, processing user input: '{user_text}'")
        
        # Process the interrupting speech normally
        await process_user_speech_parallel(
            user_text, 
            conversation_history, 
            websocket, 
            stream_sid, 
            bot_speaking_flag,
            interruption_state
        )
        
    except Exception as e:
        print(f"❌ Error handling user interruption: {e}")
        # Ensure flags are cleared on error
        if bot_speaking_flag:
            bot_speaking_flag['speaking'] = False
        if interruption_state:
            interruption_state.audio_stream_active = False


async def process_user_speech_parallel(user_text, conversation_history, websocket, stream_sid, bot_speaking_flag, interruption_state=None, ack_done_event=None, on_first_audio=None, on_stt_close=None):
    """
    Sentence-streaming pipeline for Cube (Azure TTS):
      LLM sentences ──► parallel Azure TTS futures ──► AudioQueueManager ──► Cube binary WS (one-shot per sentence)

    Each sentence fires TTS immediately in the thread pool. The AudioQueueManager
    awaits futures in order and delivers audio to Cube as each sentence is ready,
    so sentences 2 and 3 are often already synthesised before sentence 1 finishes playing.
    """
    try:
        start_time = time.time()
        print(f"🧠 Processing: {user_text}")
        conversation_history.append({"role": "user", "content": user_text})

        # ⚡ Fire DB log async — do NOT await (would block LLM by ~1s)
        async def _log_user_async():
            try:
                db.log_conversation(record_id=stream_sid, speaker='user', message=user_text, message_type='speech')
            except Exception as db_err:
                print(f"⚠️ DB log error (non-critical): {db_err}")
        asyncio.create_task(_log_user_async())

        if interruption_state:
            if interruption_state.audio_stream_active:
                print("🔄 Previous stream active — cancelling before new utterance")
                await cancel_ongoing_audio(websocket, stream_sid, interruption_state)
            interruption_state.reset_for_new_tts()
            interruption_state.audio_stream_active = True
            interruption_state.interrupted_response = ""
            print("✅ Interruption state initialised (audio_stream_active=True)")

        MAX_HISTORY = 12
        if len(conversation_history) > MAX_HISTORY:
            messages_for_llm = conversation_history[:1] + conversation_history[-(MAX_HISTORY - 1):]
            print(f"✂️ History trimmed: {len(conversation_history)} → {len(messages_for_llm)} messages")
        else:
            messages_for_llm = list(conversation_history)

        # ── Inject current IST date/time so LLM always has accurate date ──────
        _now_ist = datetime.now(IST_TIMEZONE)
        _date_context = {
            "role": "system",
            "content": (
                f"Current date: {_now_ist.strftime('%d %B %Y (%A)')}, "
                f"Time: {_now_ist.strftime('%I:%M %p')} IST. "
                f"Tomorrow: {(_now_ist + timedelta(days=1)).strftime('%d %B %Y (%A)')}. "
                f"Use this for any callback scheduling or date references."
            )
        }
        messages_for_llm = [messages_for_llm[0]] + [_date_context] + messages_for_llm[1:]

        full_response_text = ""
        loop = asyncio.get_event_loop()

        # ── AudioQueueManager — parallel TTS futures, ordered playback ───────
        audio_manager = AudioQueueManager(
            websocket, stream_sid, bot_speaking_flag, interruption_state,
            ack_done_event=ack_done_event,
            on_first_audio=on_first_audio,
            on_stt_close=on_stt_close,
        )
        if interruption_state:
            interruption_state.current_audio_manager = audio_manager

        # 500ms grace before VAD activates
        if bot_speaking_flag is not None:
            async def _enable_vad_after_grace():
                await asyncio.sleep(0.5)
                if interruption_state and interruption_state.audio_stream_active:
                    bot_speaking_flag['speaking'] = True
                    print("🔊 Bot speaking flag SET (0.5s grace) — VAD active")
            asyncio.create_task(_enable_vad_after_grace())

        # ── Stream LLM sentences → parallel Azure TTS → AudioQueueManager ────
        print("🌊 LLM streaming + Azure TTS sentence pipeline...")
        async for sentence in get_azure_openai_stream(messages_for_llm, websocket, stream_sid, bot_speaking_flag):
            if interruption_state and not interruption_state.audio_stream_active:
                print("🛑 Interrupted during LLM streaming")
                break
            full_response_text += sentence + " "
            tts_text = sentence.replace("**", "").replace("*", "").lstrip("#").strip()
            if tts_text:
                future = loop.create_future()
                added = await audio_manager.add_future(future)
                if added:
                    asyncio.create_task(generate_tts_for_future(tts_text, future, "hi-IN"))
                    print(f"🔊 TTS fired for: \"{tts_text[:60]}{'…' if len(tts_text) > 60 else ''}\"")

        # Signal end of sentences — play queue will drain then clean up
        await audio_manager.mark_completed()

        # Wait for the play queue to finish (natural end or interruption)
        if audio_manager._play_task:
            try:
                await audio_manager._play_task
            except asyncio.CancelledError:
                pass

        full_response_text = full_response_text.strip()
        conversation_history.append({"role": "assistant", "content": full_response_text})
        try:
            db.log_conversation(record_id=stream_sid, speaker='bot', message=full_response_text, message_type='speech')
        except Exception as db_err:
            print(f"⚠️ DB log error (non-critical): {db_err}")

        if interruption_state and interruption_state.audio_stream_active:
            interruption_state.interrupted_response = full_response_text

        # ── DEFERRED HANGUP ──────────────────────────────────────────────────
        # [HANGUP] in the LLM stream now sets bot_speaking_flag['hangup'] instead
        # of firing 0x00 mid-sentence. Execute the hangup HERE — AFTER the goodbye
        # audio has fully played — and CLOSE the WebSocket. Sending 0x00 alone
        # (socket left open, more audio after it) did NOT drop the Cube call;
        # closing the media socket is what actually terminates it.
        if bot_speaking_flag is not None and bot_speaking_flag.get('hangup'):
            try:
                await websocket.send_bytes(b'\x00')
                print("📞 Hangup 0x00 sent (after goodbye finished)")
            except Exception as _he:
                print(f"⚠️ Hangup 0x00 send error: {_he}")
            try:
                await asyncio.sleep(0.2)   # let the 0x00 flush over the wire
                await websocket.close()
                print("📞 WebSocket closed — Cube call terminated")
            except Exception as _ce:
                print(f"⚠️ WebSocket close error: {_ce}")

        total_time = time.time() - start_time
        print(f"⚡ Processing complete: {total_time:.2f}s")

    except Exception as e:
        err_str = str(e).lower()
        print(f"❌ Error in speech processing: {e}")
        if "getaddrinfo failed" in err_str or "cannot connect to host" in err_str:
            print("   💡 Hint: DNS or network issue — check internet, firewall, and Azure OpenAI host.")
        if bot_speaking_flag is not None:
            bot_speaking_flag['speaking'] = False
            print("🔕 Bot speaking flag CLEARED due to error")
        if interruption_state:
            interruption_state.audio_stream_active = False
            interruption_state.current_audio_manager = None




async def send_cube_greeting(websocket, conversation_history, bot_speaking_state, interruption_state, customer_name=None, call_id=None, greeting_protection=None):
    """Send greeting via Cube VoIP binary protocol.
    
    Args:
        customer_name: Customer name to include in greeting (optional)
        call_id: The call record ID for database logging
        greeting_protection: Dict to track greeting protection timing (optional)
    """
    try:
        print(f"👋 send_cube_greeting called with customer_name='{customer_name}', call_id='{call_id}'")
        
        # Build Swara The Fashion Street opening greeting (Priya) — Devanagari + English terms,
        # matching the [HINDI] default register; personalized if a real name is available.
        if customer_name and customer_name != "Customer":
            # Extract first name only (split by space and take first word)
            first_name = customer_name.strip().split()[0] if customer_name.strip() else customer_name
            greeting_text = f"नमस्ते {first_name} जी, मैं Priya बोल रही हूँ, Swara The Fashion Street \"पंडरी\" Raipur से। क्या मैं आपसे कुछ seconds बात कर सकती हूँ?"
            print(f"✅ Using personalized greeting with first_name='{first_name}'")
        else:
            greeting_text = "नमस्ते, मैं Priya बोल रही हूँ, Swara The Fashion Street \"पंडरी\" Raipur से। क्या मैं आपसे कुछ seconds बात कर सकती हूँ?"
            print(f"⚠️ Using generic greeting (customer_name was '{customer_name}')")

        print(f"🎤 Sending Cube greeting (Hindi+terms): {greeting_text}")
        
        # Generate PCM audio (8kHz, 16-bit)
        audio_b64 = await synthesize_speech_azure(greeting_text, "hi-IN")
        if audio_b64:
            # Decode from base64 to raw PCM bytes
            pcm_audio = base64.b64decode(audio_b64)
            
            # Add to conversation history IMMEDIATELY (so LLM knows we greeted, even if interrupted)
            conversation_history.append({"role": "assistant", "content": greeting_text})
            
            # Log greeting to database
            if call_id:
                try:
                    db.log_conversation(
                        record_id=call_id,
                        speaker='bot',
                        message=greeting_text,
                        message_type='speech',
                        metadata={'type': 'greeting', 'personalized': bool(customer_name and customer_name != "Customer")}
                    )
                except Exception as db_err:
                    print(f"⚠️ Database logging error for greeting (non-critical): {db_err}")
            
            # 🛡️ GREETING PROTECTION: Set timing when audio actually starts playing
            if greeting_protection is not None:
                # Calculate actual greeting duration from PCM audio
                # PCM format: 8kHz, 16-bit (2 bytes per sample), mono
                greeting_duration = len(pcm_audio) / (8000 * 2)  # bytes / (samples/sec * bytes/sample)
                current_time = time.time()
                greeting_protection['greeting_duration'] = greeting_duration
                greeting_protection['greeting_start_time'] = current_time
                greeting_protection['halfway_point'] = current_time + (greeting_duration * 0.5)
                greeting_protection['greeting_started'] = True
                print(f"🛡️ Greeting protection ACTIVE: {greeting_duration:.1f}s total, 50% at {greeting_duration * 0.5:.1f}s (starts now)")
            
            # Send via Cube binary protocol
            success = await send_cube_audio(websocket, pcm_audio, bot_speaking_state, interruption_state)
            
            if success:
                print("✅ Cube greeting sent successfully")
            else:
                print("⚠️ Cube greeting interrupted")
        else:
            print("❌ Failed to generate greeting audio")
            
    except Exception as e:
        print(f"❌ Error in Cube greeting: {e}")


# ==================== SCHEDULER FOR DAILY LEAD FETCH ====================
from fetch_leads import fetch_and_store_leads

async def scheduler_task():
    """Background task to fetch leads daily at 10:00 AM."""
    print("⏰ Scheduler started (Target: 10:00 AM daily)")
    while True:
        now = datetime.now()
        # If current time is 10:00 (within first minute)
        if now.hour == 10 and now.minute == 0:
            print("⏰ It's 10:00 AM! Running daily lead fetch...")
            try:
                await asyncio.to_thread(fetch_and_store_leads)
            except Exception as e:
                print(f"❌ Scheduled task failed: {e}")
            # Sleep for 61 seconds to avoid re-running in same minute
            await asyncio.sleep(61)
        else:
            # Sleep for 30 seconds before re-checking
            await asyncio.sleep(30)


# ==================== FASTAPI APP WITH LIFESPAN ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan handler for startup and shutdown events."""
    # Startup: Start background scheduler
    print("🚀 Server starting up...")
    scheduler = asyncio.create_task(scheduler_task())
    
    yield  # Application runs
    
    # Shutdown: Clean up resources
    print("🛑 Server shutting down...")
    scheduler.cancel()
    try:
        await scheduler
    except asyncio.CancelledError:
        pass
    print("✅ Scheduler stopped")

# ==================================================================================
# NOTE: FastAPI app was already created above at line ~952 with CORS ["*"] configured.
# All routes below will be registered on that same app instance.
# ================================================================================== 


# ── Call outcome classifier ────────────────────────────────────────────────────

def _detect_call_outcome(conversation_history: list) -> tuple:
    """
    Classify the call outcome from conversation history.
    Returns (outcome_label, conclusion_text).

    outcome_label: one of
      'Interested'  | 'Not Interested' | 'Callback Requested' |
      'Wrong Number'| 'Not Connected'  | 'Inconclusive'
    conclusion_text: last meaningful bot sentence (max 200 chars)
    """
    # Collect all bot messages
    bot_msgs = [m["content"] for m in conversation_history if m.get("role") == "assistant"]
    if not bot_msgs:
        return "Not Connected", ""

    last_bot = bot_msgs[-1].replace("[HANGUP]", "").strip()
    conclusion = last_bot[:200]

    # Join all bot messages for keyword search
    full_bot = " ".join(bot_msgs).lower()

    # Wrong number
    if any(k in full_bot for k in ["गलत number", "wrong number", "शायद गलत"]):
        return "Wrong Number", conclusion

    # Callback requested
    if any(k in full_bot for k in ["दोबारा call", "dobara call", "call back", "callback", "कल दोबारा", "kal dobara"]):
        return "Callback Requested", conclusion

    # Not interested
    if any(k in full_bot for k in ["कोई बात नहीं", "koi baat nahi", "not interested", "record update", "ज़रूरत हो तो"]):
        return "Not Interested", conclusion

    # Interested — team will call back
    if any(k in full_bot for k in [
        "team आपसे", "team connect", "shortly connect", "request register",
        "request kar", "plan initiate", "plan शुरू", "quotation", "appointment"
    ]):
        return "Interested", conclusion

    return "Inconclusive", conclusion


# ==================== ROUTES ====================

@app.websocket("/swara_voicebot")
async def handle_media_stream(websocket: WebSocket):
    """Cube VoIP WebSocket handler with Azure STT and interruption support."""
    print("🔌 Cube client connected")
    
    # =====================================================================
    # STEP 1 — Extract whatever Cube passes in the WebSocket URL (query params).
    #           For production outbound calls this is always empty {}.
    #           For local testing you can pass ?phone=...&name=...
    # =====================================================================
    query_params = websocket.query_params
    print(f"🔍 Query params: {dict(query_params)}")

    # Phone from URL (local testing / inbound calls with known CLI in URL)
    phone_number = (
        query_params.get('phone') or
        query_params.get('phone_number') or
        query_params.get('Phoneno', '')
    )
    if phone_number:
        # Normalize to 10 digits
        _clean = ''.join(filter(str.isdigit, phone_number))
        phone_number = _clean[-10:] if len(_clean) >= 10 else _clean
    print(f"📞 phone_number from query params: '{phone_number}'")

    # Name / company from URL (local testing)
    customer_name = (
        query_params.get('name') or
        query_params.get('customer_name') or
        query_params.get('Name', '')
    )
    company_name = (
        query_params.get('company') or
        query_params.get('company_name') or
        query_params.get('Company', '')
    )

    # =====================================================================
    # STEP 2 — Defer registry claim until CLI/DNI arrives.
    #
    #  ⚠️  DO NOT claim from the registry here using FIFO.
    #      With concurrent outbound calls the WebSocket connections arrive
    #      in non-deterministic order, so a FIFO grab at this point will
    #      assign the WRONG name/lead to this session.
    #
    #  The Cube CLI/DNI packet (0x20) carries the real caller phone number
    #  and arrives ~10-30 ms BEFORE the first audio chunk that triggers the
    #  greeting.  We do the exact-phone registry lookup there instead.
    #
    #  If phone_number IS already known (local-test URL param), we still
    #  do an exact-phone claim now — that is always safe.
    # =====================================================================
    _registry_lead_id   = None
    _registry_lead_data = {}

    if phone_number:
        # Exact-phone claim is always safe (no FIFO ambiguity)
        _outbound_ctx = claim_outbound_call(phone=phone_number)
        if _outbound_ctx:
            if not customer_name:
                customer_name = _outbound_ctx.name
            if not company_name:
                company_name = _outbound_ctx.company_name
            _registry_lead_id   = _outbound_ctx.lead_id
            _registry_lead_data = _outbound_ctx.lead_data
            print(f"✅ Outbound context claimed (exact-phone): phone={phone_number}, "
                  f"name='{customer_name}', company='{company_name}', "
                  f"lead_id={_registry_lead_id}")
        else:
            print(f"ℹ️ No registry entry for {phone_number} — treating as inbound call")
    else:
        # phone_number unknown at connect time (normal for production outbound calls).
        # Identity will be resolved when CLI/DNI packet arrives — see receive_from_cube().
        print(f"⏳ No phone in WebSocket URL — deferring identity to CLI/DNI packet")

    if customer_name:
        print(f"🎯 Initial customer_name: '{customer_name}' (may be updated by CLI/DNI)")
    else:
        print(f"⚠️ No customer name yet — generic greeting will be used until CLI/DNI resolves it")
    if company_name:
        print(f"🎯 Initial company_name:  '{company_name}'")


    
    await websocket.accept()

    # ========== ANNOUNCEMENT MODE (one-way broadcast) ==========
    # Play the fixed pre-recorded clip once the line is up, then hang up.
    # Skips ALL conversational handling below (CLI-DNI, STT, LLM, VAD, etc.).
    #
    # HANGUP TIMING: same clip every call, so its duration is known up front.
    # Rather than trust a tight byte-count wait (risky for a 30-47s blob —
    # if Cube's own playback buffer drains even slightly slower than our
    # math assumes, closing the socket "early" leaves the call stuck open;
    # closing the socket is what actually ends it, per the DEFERRED HANGUP
    # note elsewhere in this file), just wait clip-duration + a generous
    # fixed safety margin before hanging up — the same dumb sleep-then-close
    # pattern already proven by the CALL_MAX_DURATION auto-cutoff below.
    ANNOUNCEMENT_HANGUP_SAFETY_MARGIN = 5.0  # seconds, generous cushion past clip end
    if ANNOUNCEMENT_MODE:
        try:
            pcm = _load_announcement_pcm()
            clip_duration = len(pcm) / 16000  # 8kHz * 16-bit = 16000 bytes/sec
            # Small guard so Cube is ready to relay audio (avoids clipping the start).
            await asyncio.sleep(0.5)
            print(f"📢 Announcement: sending {len(pcm)} bytes (~{clip_duration:.1f}s clip)")
            await websocket.send_bytes(pcm)   # single-shot send
            wait_time = clip_duration + ANNOUNCEMENT_HANGUP_SAFETY_MARGIN
            print(f"📢 Announcement: waiting {wait_time:.1f}s ({clip_duration:.1f}s clip + "
                  f"{ANNOUNCEMENT_HANGUP_SAFETY_MARGIN:.1f}s safety margin) before hangup")
            await asyncio.sleep(wait_time)
            print("📢 Announcement finished — sending hangup")
            await websocket.send_bytes(b'\x00')      # Cube hangup signal
            await asyncio.sleep(0.2)                  # let the byte flush over the wire
        except WebSocketDisconnect:
            print("📢 Announcement: client disconnected mid-clip")
        except Exception as e:
            print(f"❌ Announcement mode error: {e}")
        finally:
            try:
                await websocket.close()
                print("📢 Announcement: WebSocket closed — call terminated")
            except Exception:
                pass
        return

    # ========== CALL ID LINKING ==========
    # Try to find existing call record (created by /api/make-call) using phone number
    # This ensures conversation is linked to the correct call record
    call_id = None
    call_record_created = False
    
    if phone_number:
        try:
            # Look up the most recent call for this phone number
            existing_call = db.get_call_by_phone(phone_number)
            if existing_call:
                call_id = existing_call.get('record_id')
                print(f"📞 Linked to existing call record: {call_id}")
        except Exception as e:
            print(f"⚠️ Error looking up call: {e}")
    
    # Fallback: Generate new UUID if no existing call found
    if not call_id:
        call_id = str(uuid.uuid4())
        print(f"📞 New Cube call (no prior record): {call_id}")
        
        # 🆕 ONLY create call record if we have a phone number
        # This prevents duplicate "unknown" entries
        if phone_number:
            try:
                db.create_call(
                    record_id=call_id,
                    phone_number=phone_number,
                    customer_name=customer_name,
                    company_name=company_name,
                    campaign_id=CUBE_CAMPAIGN_ID
                )
                call_record_created = True
                print(f"   ✅ Created new call record with phone: {phone_number}")
            except Exception as db_err:
                print(f"   ⚠️ Could not create call record: {db_err}")
        else:
            print(f"   ⏳ No phone number yet - waiting for CLI/DNI to create call record")
    else:
        call_record_created = True
        print(f"📞 Cube call connected: {call_id}")
    
    if phone_number:
        print(f"   Phone: {phone_number}")
    if customer_name:
            print(f"   Customer: {customer_name}")
    if company_name:
        print(f"   Company: {company_name}")
    
    # Update call status to 'connected'
    try:
        db.update_call_status(call_id, 'connected')
        log_to_supabase(
            f"Call connected: {customer_name} ({phone_number})",
            "INFO",
            record_id=call_id,
            details={"phone": phone_number, "customer": customer_name}
        )
    except Exception as db_err:
        print(f"⚠️ Database update error (non-critical): {db_err}")

    # 2-minute hard auto call cutoff — terminates the Cube call if it exceeds the limit.
    # Uses the SAME proven sequence as the normal hangup (0x00 hangup byte → close),
    # because a bare websocket.close() from this parallel task races the active
    # receive_from_cube() loop and can silently fail. Errors are logged, not swallowed.
    CALL_MAX_DURATION = 120  # seconds
    _call_cutoff_task: Optional[asyncio.Task] = None

    async def _auto_cutoff():
        await asyncio.sleep(CALL_MAX_DURATION)
        print(f"[AutoCut] {CALL_MAX_DURATION}s limit reached for {call_id} ({phone_number}) — terminating call")
        try:
            await websocket.send_bytes(b'\x00')   # Cube hangup signal
            await asyncio.sleep(0.2)               # let the byte flush over the wire
            print("[AutoCut] 0x00 hangup byte sent")
        except Exception as e:
            print(f"[AutoCut] 0x00 send failed: {e}")
        try:
            await websocket.close()
            print("[AutoCut] WebSocket closed — call terminated")
        except Exception as e:
            print(f"[AutoCut] WebSocket close failed: {e}")

    _call_cutoff_task = asyncio.create_task(_auto_cutoff())

    # Pass company name to system message for LLM context
    # NOTE: Use FULL company name (unlike customer name where we use first name only)
    _early_flow = (_registry_lead_data or {}).get('flow_type', 'FABER_INSTALL_FOLLOWUP')
    _raw_prompt = FLOW_PROMPTS.get(_early_flow, FLOW_PROMPTS['FABER_INSTALL_FOLLOWUP'])
    system_message_content = _apply_date_injection(_raw_prompt)
    print(f"🔀 Flow selected: {_early_flow}")
    
    # Replace {Customer_name} placeholder with actual customer name
    # Use first name only for natural conversation
    first_name = customer_name.split()[0] if customer_name and ' ' in customer_name else (customer_name or 'Customer')
    system_message_content = system_message_content.replace('{Customer_name}', first_name)
    print(f"📝 Replaced {{Customer_name}} with '{first_name}' in system message")
    
    # =====================================================================
    # LEAD LOOKUP & DYNAMIC PROMPT
    # =====================================================================
    # For outbound calls: lead_id and lead_data were pre-populated in the
    # registry at make-call time, so we seed from there directly — no extra
    # DB round-trip needed.
    # For inbound calls: _registry_lead_id is None, so we fall through to
    # the DB lookup below.
    # =====================================================================
    lead_id = _registry_lead_id   # may be None for inbound calls
    lead_data = {}                # safe default — populated below if phone_number is known

    if phone_number:
        try:
            lead_data = _registry_lead_data.copy() if _registry_lead_data else {}
            lead_source = "Registry" if lead_data else "None"

            # If registry didn't have a lead_id, do a DB lookup (inbound / edge case)
            if not lead_id:
                print(f"🔍 DB lookup for phone: {phone_number} (no registry lead_id)")
                lead_info = get_lead_by_phone(phone_number)
                if lead_info:
                    lead_id = lead_info['id']
                    lead_source = "Database"
                    print(f"🎯 LEAD MATCH FOUND IN DB: {lead_info.get('name')} (ID: {lead_id})")
                    if not customer_name and lead_info.get('name'):
                        customer_name = lead_info.get('name')
                    # If registry gave no lead_data, try to get it from DB
                    if not lead_data:
                        try:
                            lead_data_str = lead_info.get('lead_data', '{}')
                            lead_data = json.loads(lead_data_str) if lead_data_str else {}
                            print(f"   Parsed lead_data from DB — keys: {list(lead_data.keys())}")
                        except Exception as parse_err:
                            print(f"⚠️ Failed to parse lead_data from DB: {parse_err}")
                            lead_data = {}
                else:
                    print(f"⚠️ No lead found in database for phone: {phone_number}")
            else:
                print(f"✅ Using registry lead_id={lead_id} (no DB round-trip needed)")

            # Mark lead as 'connected' now that the WebSocket is live
            if lead_id:
                update_lead_status(lead_id, 'connected')
                print(f"✅ Lead status updated to 'connected' for lead_id={lead_id}")

            # INJECT CRM LEAD CONTEXT INTO PROMPT
            if lead_data and isinstance(lead_data, dict) and len(lead_data) > 0:
                lead_context = build_lead_context(lead_data, customer_name)
                system_message_content += lead_context

                crm_name         = lead_data.get('name', customer_name or 'Unknown')
                customer_type    = lead_data.get('customer_type', 'Unknown')
                lead_type        = lead_data.get('lead_type', 'Unknown')
                business_vertical = lead_data.get('business_vertical', '')
                print(f"📋 LEAD CONTEXT: Name={crm_name}, Type={customer_type}, "
                      f"LeadType={lead_type}, Vertical={business_vertical}, Source={lead_source}")
                print(f"✅ Injected CRM lead context for {crm_name} ({customer_type}/{lead_type})")
                print(f"📝 System message length after injection: {len(system_message_content)} chars")
            else:
                print(f"⚠️ No lead data available for personalisation "
                      f"(lead_data={bool(lead_data)}, phone={phone_number}, source={lead_source})")

        except Exception as e:
            print(f"⚠️ Error in lead lookup/injection: {e}")



    if company_name:
        system_message_content += f"\n\n**IMPORTANT**: The customer is calling from {company_name}. Use this context when relevant to the conversation."

    # ── Replace per-customer placeholders from lead_data ─────────────────────
    _ld = lead_data if isinstance(lead_data, dict) else {}

    # Helper: return value or dash if empty
    def _v(key, default='—'):
        return str(_ld.get(key) or default).strip() or default

    _flow_type    = _v('flow_type', 'FABER_INSTALL_FOLLOWUP')
    _cust_name    = _v('customer_name', customer_name or '—')
    _mach_type    = _v('machine_type', 'Genset')
    _dg_cap       = _v('dg_capacity', '—')
    _loc_short    = _v('location', '—')
    _loc_full     = _v('location_full', _loc_short)
    _agree_expiry = _v('agreement_expiry', '—')
    _warr_expiry  = _v('warranty_expiry', '—')
    _last_svc     = _v('last_service_month', '—')
    _svc_due      = _v('service_due_date', '—')
    _helpline     = _v('helpline_number', '+91 8130102683')
    _account_name = _v('account_name', _cust_name)
    _model_number = _v('model_number', '—')
    _koel_status  = _v('koel_status', '—')
    # Faber-specific placeholders
    _product      = _v('product', 'product')
    _dealer_name  = _v('dealer_name', 'the dealer')

    replacements = {
        '__CUSTOMER_NAME__':         _cust_name,
        '__MACHINE_TYPE__':          _mach_type,
        '__DG_CAPACITY__':           _dg_cap,
        '__INSTALL_LOCATION__':      _loc_short,
        '__INSTALL_LOCATION_FULL__': _loc_full,
        '__AGREEMENT_EXPIRY__':      _agree_expiry,
        '__WARRANTY_EXPIRY__':       _warr_expiry,
        '__LAST_SERVICE_MONTH__':    _last_svc,
        '__SERVICE_DUE_DATE__':      _svc_due,
        '__HELPLINE_NUMBER__':       _helpline,
        '__ACCOUNT_NAME__':          _account_name,
        '__MODEL_NUMBER__':          _model_number,
        '__KOEL_STATUS__':           _koel_status,
        '__FLOW_TYPE__':             _flow_type,
        '__PHONE_NUMBER__':          phone_number or '—',
        # Faber-specific placeholders
        '__PRODUCT__':               _product,
        '__DEALER_NAME__':           _dealer_name,
        # legacy placeholders kept for backward compatibility
        '__INSTALLATION_DATE__':     _agree_expiry,
    }
    for placeholder, value in replacements.items():
        system_message_content = system_message_content.replace(placeholder, value)

    print(
        f"📋 Placeholders replaced — flow={_flow_type}, customer={_cust_name}, "
        f"machine={_mach_type} {_dg_cap}, loc={_loc_short}, "
        f"expiry={_agree_expiry}, last_svc={_last_svc}, due={_svc_due}"
    )

    conversation_history = [{"role": "system", "content": system_message_content}]
    greeting_sent = False
    cli_dni_received = False  # Track if we've received CLI/DNI from Cube
    ten_digit_cli    = None   # Set when CLI/DNI packet arrives
    
    # 🛡️ GREETING PROTECTION: Track greeting state for VAD/STT gating
    greeting_protection = {
        'active': True,           # True = protection active (ignore VAD/STT)
        'greeting_queued': False, # True = greeting task has been queued
        'greeting_started': False, # True = greeting has started playing
        'greeting_start_time': 0, # Timestamp when greeting started
        'greeting_duration': 0,   # Total greeting duration in seconds
        'halfway_point': 0,       # Timestamp when 50% of greeting is done
        'protection_ended': False # True = 50% mark reached, resume normal processing
    }
    
    # Initialize Deepgram STT handler
    speech_recognizer = DeepgramSTTHandler(
        api_key=DEEPGRAM_API_KEY,
    )
    print(f"🎤 Deepgram STT initialized")
    
    audio_chunk_count = 0
    bot_speaking_state = {'speaking': False}
    
    # Initialize interruption state for this session
    interruption_state = InterruptionState()
    print(f"🎙️ Interruption handling: {'ENABLED' if InterruptionConfig.ENABLED else 'DISABLED'}")
    
    # VAD WebSocket connection (external service for GPU-accelerated speech detection)
    vad_ws = None
    vad_connected = False
    vad_speech_detected = False  # Flag set by background listener when speech is detected
    vad_listener = None  # Background task for VAD events
    
    async def connect_vad_service():
        """Connect to the external VAD WebSocket service with retry logic."""
        nonlocal vad_ws, vad_connected
        if not VADConfig.ENABLED or not VADConfig.USE_VAD_SERVICE:
            print("⚠️ VAD Service disabled by config")
            return
        
        max_retries = 3
        retry_delay = 2  # seconds
        
        for attempt in range(1, max_retries + 1):
            try:
                print(f"🧠 VAD Service: Connecting to {VADConfig.VAD_SERVICE_URL} (attempt {attempt}/{max_retries})...")
                vad_ws = await asyncio.wait_for(
                    websockets.connect(
                        VADConfig.VAD_SERVICE_URL,
                        ping_interval=20,
                        ping_timeout=20  # Increased timeout
                    ),
                    timeout=30  # Increased connection timeout (was 10s)
                )
                vad_connected = True
                print(f"✅ VAD Service: CONNECTED ({VADConfig.VAD_SERVICE_URL})")
                
                # Wait for welcome message
                welcome = await asyncio.wait_for(vad_ws.recv(), timeout=5)
                welcome_data = json.loads(welcome)
                if welcome_data.get('type') == 'connected':
                    device = welcome_data.get('device', 'cpu')
                    gpu = welcome_data.get('gpu_available', False)
                    mode = welcome_data.get('mode', 'unknown')
                    print(f"   └─ Device: {device} {'(GPU)' if gpu else '(CPU)'}, Mode: {mode}")
                return  # Success - exit the retry loop
                    
            except asyncio.TimeoutError:
                print(f"⚠️ VAD Service: Connection timeout (attempt {attempt}/{max_retries})")
            except ConnectionRefusedError:
                print(f"⚠️ VAD Service: Connection refused - is vad.py running? (attempt {attempt}/{max_retries})")
            except Exception as e:
                print(f"⚠️ VAD Service connection error: {type(e).__name__}: {e} (attempt {attempt}/{max_retries})")
            
            if attempt < max_retries:
                print(f"   Retrying in {retry_delay}s...")
                await asyncio.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
        
        # All retries failed
        print(f"❌ VAD Service: Failed to connect after {max_retries} attempts")
        print(f"   URL: {VADConfig.VAD_SERVICE_URL}")
        print("   Run 'cd VAD && python vad.py' to start the VAD service")
        print("   💡 Falling back to energy-based VAD (less accurate but functional)")
        vad_ws = None
        vad_connected = False
    
    async def vad_listener_task():
        """Background task that listens for VAD events and triggers interruptions."""
        nonlocal vad_ws, vad_connected, vad_speech_detected
        
        event_count = 0
        print("🎧 VAD listener task started (interruption-optimized)")
        
        while vad_connected and vad_ws is not None:
            try:
                # Wait for VAD event (blocking, but in separate task)
                message = await vad_ws.recv()
                data = json.loads(message)
                
                msg_type = data.get('type', 'unknown')
                
                # Log message types for debugging (not too spammy)
                if msg_type not in ('pong', 'connected'):
                    event_count += 1
                    if event_count <= 5 or event_count % 50 == 0:
                        print(f"📨 VAD message #{event_count}: type='{msg_type}'")
                
                # 🚨 INTERRUPT EVENT - Stop bot immediately!
                if msg_type == 'interrupt':
                    confidence = data.get('confidence', 0)
                    bot_speaking = bot_speaking_state['speaking']
                    stream_active = getattr(interruption_state, 'audio_stream_active', False) if interruption_state else False
                    print(f"🎙️ VAD: INTERRUPT received! (confidence: {confidence:.2f}, bot_speaking: {bot_speaking}, stream_active: {stream_active})")

                    # Cancel any pending finalize debounce — user is still speaking
                    if speech_recognizer and speech_recognizer.is_running:
                        speech_recognizer.speech_start_signal()
                    
                    # Check EITHER stream_active OR bot_speaking for more reliable interruption
                    # Both flags indicate bot is outputting audio that should be stopped
                    should_interrupt = stream_active or bot_speaking
                    
                    if should_interrupt:
                        # Check cooldown timer before triggering
                        if interruption_state and interruption_state.can_vad_trigger():
                            metrics.record_vad_trigger(is_valid=True)
                            print(f"🔊 SILERO VAD INTERRUPT! Stopping bot immediately! (bot_speaking={bot_speaking}, stream_active={stream_active})")
                            
                            # Force audio_stream_active to True for cancel_ongoing_audio to work
                            if interruption_state:
                                interruption_state.audio_stream_active = True
                            
                            # Handle interruption immediately
                            asyncio.create_task(
                                handle_vad_interruption(
                                    websocket,
                                    call_id,
                                    bot_speaking_state,
                                    interruption_state
                                )
                            )
                        else:
                            print(f"⏳ VAD: Cooldown active, skipping trigger (bot_speaking={bot_speaking}, stream_active={stream_active})")
                    else:
                        print(f"ℹ️ VAD: Neither bot_speaking nor stream_active - interrupt ignored (bot_speaking={bot_speaking}, stream_active={stream_active})")
                    
                    vad_speech_detected = True
                
                # Speech END event
                elif msg_type == 'speech_end':
                    print(f"🎙️ VAD: Speech END — starting finalize debounce")
                    vad_speech_detected = False

                    # VAD-driven STT finalization:
                    # Start a 500ms debounce timer. If user doesn't resume within
                    # that window, Deepgram gets a Finalize message and flushes
                    # immediately — saving ~600ms vs waiting for utterance_end_ms=1100.
                    if speech_recognizer and speech_recognizer.is_running:
                        speech_recognizer.speech_end_signal(debounce_ms=500)
                
                # Legacy vad_event support (backward compatibility)
                elif msg_type == 'vad_event':
                    vad_data = data.get('data', {})
                    if 'start' in vad_data:
                        stream_active = getattr(interruption_state, 'audio_stream_active', False) if interruption_state else False
                        if stream_active and interruption_state.can_vad_trigger():
                            metrics.record_vad_trigger(is_valid=True)
                            print(f"🔊 SILERO VAD TRIGGER! (legacy event)")
                            asyncio.create_task(
                                handle_vad_interruption(websocket, call_id, bot_speaking_state, interruption_state)
                            )
                        vad_speech_detected = True
                    elif 'end' in vad_data:
                        vad_speech_detected = False
                        
            except websockets.exceptions.ConnectionClosed:
                print("🔌 VAD Service disconnected")
                vad_connected = False
                break
            except Exception as e:
                if "close" not in str(e).lower():
                    print(f"⚠️ VAD listener error: {e}")
                await asyncio.sleep(0.1)
    
    audio_send_count = 0
    
    async def send_audio_to_vad(audio_bytes):
        """Send audio chunk to VAD service (fire-and-forget)."""
        nonlocal vad_ws, vad_connected, audio_send_count
        if not vad_connected or vad_ws is None:
            return
        
        try:
            # Convert PCM audio to list for JSON
            audio_int16 = np.frombuffer(audio_bytes, dtype=np.int16)
            audio_list = audio_int16.tolist()
            
            audio_send_count += 1
            if audio_send_count <= 3 or audio_send_count % 100 == 0:
                print(f"📤 Sending audio #{audio_send_count} to VAD ({len(audio_list)} samples)")
            
            # Send audio chunk (don't wait for response - listener handles that)
            await vad_ws.send(json.dumps({
                'type': 'audio_chunk',
                'audio': audio_list,
                'sample_rate': CUBE_SAMPLE_RATE  # Cube uses 8kHz PCM
            }))
        except Exception as e:
            if "close" not in str(e).lower():
                print(f"⚠️ VAD send error: {e}")
            vad_connected = False
    
    # Connect to VAD service if enabled
    if VADConfig.ENABLED and VADConfig.USE_VAD_SERVICE:
        await connect_vad_service()
        if vad_connected:
            vad_listener = asyncio.create_task(vad_listener_task())

    async def receive_from_cube():
        """Optimized audio receiving with minimal processing overhead."""
        nonlocal call_id, conversation_history, audio_chunk_count, greeting_sent, customer_name, company_name, cli_dni_received, phone_number, greeting_protection, lead_id, _registry_lead_id, _registry_lead_data
        current_loop = asyncio.get_running_loop()  # For run_coroutine_threadsafe
        try:
            # ========== CUBE BINARY PROTOCOL ==========
            # Cube sends binary PCM data, not JSON
            async for message in websocket.iter_bytes():
                # Handle empty messages
                if len(message) == 0:
                    continue
                
                # Get message type from first byte (if available)
                msg_type = message[0] if len(message) > 1 else CUBE_MSG_AUDIO
                
                # ========== CUBE MESSAGE TYPE HANDLING ==========
                if msg_type == CUBE_MSG_HANGUP:
                    log_to_supabase(
                        "Call Hangup Received from Cube", 
                        "INFO", 
                        record_id=call_id,
                        details={"audio_chunks_processed": audio_chunk_count}
                    )
                    print(f"📞 Cube hangup received for call {call_id}")
                    break  # Exit loop on hangup
                
                elif msg_type == CUBE_MSG_CLI_DNI:
                    # Cube sends CLI/DNI info (caller ID / dialed number) as JSON
                    # Format: {'cli': 'caller_phone', 'dni': 'dialed_number'}
                    try:
                        cli_dni_data = json.loads(message[1:].decode('utf-8'))
                        print(f"📋 CLI/DNI received: {cli_dni_data}")
                        
                        # ── FIX: Cube sends lowercase 'cli' key (not 'CLI') ──────────
                        # Accept all known key variants to be safe.
                        cli_phone = (
                            cli_dni_data.get('cli') or          # ← actual Cube key
                            cli_dni_data.get('CLI') or          # legacy / doc variant
                            cli_dni_data.get('phone') or
                            cli_dni_data.get('phone_number') or
                            cli_dni_data.get('Phoneno', '')
                        )
                        if cli_phone:
                            clean_cli = ''.join(filter(str.isdigit, str(cli_phone)))
                            if len(clean_cli) >= 10:
                                ten_digit_cli = clean_cli[-10:]
                                
                                # ==================================================
                                # STEP A — Resolve identity from outbound registry.
                                #
                                # Now that we have the real caller phone we can do
                                # an EXACT match in the registry — no FIFO guessing.
                                # This is the authoritative fix for name shuffling.
                                # ==================================================
                                if not customer_name or not _registry_lead_id:
                                    _cli_ctx = claim_outbound_call(phone=ten_digit_cli)
                                    if _cli_ctx:
                                        # Got the right context for THIS call
                                        if not customer_name:
                                            customer_name = _cli_ctx.name
                                        if not company_name:
                                            company_name = _cli_ctx.company_name
                                        if not _registry_lead_id:
                                            _registry_lead_id = _cli_ctx.lead_id
                                        if not _registry_lead_data:
                                            _registry_lead_data = _cli_ctx.lead_data
                                        lead_id = _registry_lead_id
                                        print(f"✅ CLI/DNI registry match: name='{customer_name}', "
                                              f"company='{company_name}', lead_id={lead_id}")
                                    else:
                                        print(f"ℹ️ No registry entry for {ten_digit_cli} — inbound call")
                                else:
                                    print(f"✅ Identity already resolved from WebSocket-time registry claim")

                                # ==================================================
                                # STEP B — Link / create the DB call record.
                                # ==================================================
                                try:
                                    existing_call = db.get_call_by_phone(ten_digit_cli)
                                    if existing_call:
                                        old_call_id = call_id
                                        new_call_id = existing_call.get('record_id')
                                        
                                        if old_call_id != new_call_id:
                                            print(f"🔄 Migrating conversation logs: {old_call_id} → {new_call_id}")
                                            try:
                                                db.update_conversation_record_id(old_call_id, new_call_id)
                                                print(f"✅ Conversation logs migrated successfully")
                                            except Exception as migrate_err:
                                                print(f"⚠️ Could not migrate conversation logs: {migrate_err}")
                                        
                                        call_id = new_call_id
                                        phone_number = ten_digit_cli
                                        call_record_created = True
                                        print(f"📞 CALL ID UPDATED: {old_call_id} → {call_id} (from CLI/DNI)")
                                    elif not call_record_created:
                                        phone_number = ten_digit_cli
                                        db.create_call(
                                            record_id=call_id,
                                            phone_number=phone_number,
                                            customer_name=customer_name,
                                            company_name=company_name,
                                            campaign_id=CUBE_CAMPAIGN_ID
                                        )
                                        call_record_created = True
                                        print(f"📞 Created call record with phone: {phone_number}")
                                    else:
                                        phone_number = ten_digit_cli
                                        print(f"📞 Updated phone number from CLI/DNI: {phone_number}")
                                except Exception as db_err:
                                    print(f"⚠️ Error linking call from CLI/DNI: {db_err}")
                                
                                # ==================================================
                                # STEP C — Lead lookup (inbound / fallback path).
                                # ==================================================
                                if not lead_id and phone_number:
                                    try:
                                        print(f"🔍 CLI/DNI: DB lead lookup for phone={phone_number}")
                                        cli_lead_info = get_lead_by_phone(phone_number)
                                        if cli_lead_info:
                                            lead_id = cli_lead_info['id']
                                            print(f"✅ CLI/DNI: lead_id={lead_id} resolved for {phone_number}")
                                            try:
                                                update_lead_status(lead_id, 'connected')
                                                print(f"✅ Lead status → 'connected' (lead_id={lead_id})")
                                            except Exception as ls_err:
                                                print(f"⚠️ Could not update lead status: {ls_err}")
                                        else:
                                            print(f"⚠️ No lead found for {phone_number} — post-call analysis skipped")
                                    except Exception as lead_lookup_err:
                                        print(f"⚠️ CLI/DNI: Lead lookup failed: {lead_lookup_err}")

                        # ==================================================
                        # STEP D — Patch system message with resolved identity
                        # ==================================================
                        # When phone_number was empty at connect time the lead-
                        # context block was skipped entirely. Now that CLI/DNI
                        # has given us the real phone + registry match, back-fill
                        # the system message so the LLM gets full CRM context
                        # (customer_type, lead_type, business_vertical, etc.)
                        # BEFORE the first greeting audio fires.
                        try:
                            # DB is primary — authoritative source for full Excel lead data.
                            # Registry (make-call payload) is fallback only.
                            _cli_lead_data = {}
                            if ten_digit_cli:
                                _db_lead = get_lead_by_phone(ten_digit_cli)
                                if _db_lead:
                                    raw = _db_lead.get('lead_data', {})
                                    _cli_lead_data = json.loads(raw) if isinstance(raw, str) else (raw or {})
                                    print(f"✅ CLI/DNI: DB lead fetched for {ten_digit_cli} — fields: {list(_cli_lead_data.keys())}")
                                else:
                                    print(f"⚠️ CLI/DNI: No DB lead for {ten_digit_cli} — using registry data")
                                    _cli_lead_data = _registry_lead_data.copy() if _registry_lead_data else {}

                            if _cli_lead_data and conversation_history:
                                # ── Re-select flow prompt if CLI/DNI resolves a different flow ──
                                _cli_flow = _cli_lead_data.get('flow_type', 'FABER_INSTALL_FOLLOWUP')
                                if _cli_flow != _early_flow:
                                    print(f"🔀 CLI/DNI: Switching flow {_early_flow} → {_cli_flow}")
                                # ALWAYS rebuild from a FRESH raw prompt so placeholders are intact.
                                # At WebSocket connect Cube sends no phone, so lead_data was empty and
                                # the initial fill already replaced __PRODUCT__/__DEALER_NAME__/etc. with
                                # defaults — destroying those tokens. Re-using that filled string here
                                # would make the replacements below no-ops. Starting from the unfilled
                                # template lets the real CLI/DNI values actually land.
                                _new_raw = FLOW_PROMPTS.get(_cli_flow, FLOW_PROMPTS['FABER_INSTALL_FOLLOWUP'])
                                patched_sys = _apply_date_injection(_new_raw)

                                # Resolve first name
                                _first = (customer_name.split()[0]
                                          if customer_name and ' ' in customer_name
                                          else (customer_name or 'Customer'))

                                # Remove stale empty lead-context block if present
                                _CTX_MARKER = "\n\n---\n**CRM LEAD CONTEXT"
                                if _CTX_MARKER in patched_sys:
                                    patched_sys = patched_sys[:patched_sys.index(_CTX_MARKER)]

                                # Inject full lead context
                                lead_context = build_lead_context(_cli_lead_data, customer_name)
                                patched_sys += lead_context

                                # Replace ALL placeholders with DB lead data
                                _cli_loc = _cli_lead_data.get('location', '—') or '—'
                                _cli_agree = _cli_lead_data.get('agreement_expiry', '—') or '—'
                                _cli_replacements = {
                                    '__CUSTOMER_NAME__':         _first,
                                    '__ACCOUNT_NAME__':          _cli_lead_data.get('account_name', _first) or _first,
                                    '__MACHINE_TYPE__':          _cli_lead_data.get('machine_type', 'Genset') or 'Genset',
                                    '__DG_CAPACITY__':           _cli_lead_data.get('dg_capacity', '—') or '—',
                                    '__INSTALL_LOCATION__':      _cli_loc,
                                    '__INSTALL_LOCATION_FULL__': _cli_lead_data.get('location_full', _cli_loc) or _cli_loc,
                                    '__AGREEMENT_EXPIRY__':      _cli_agree,
                                    '__WARRANTY_EXPIRY__':       _cli_lead_data.get('warranty_expiry', _cli_agree) or _cli_agree,
                                    '__LAST_SERVICE_MONTH__':    _cli_lead_data.get('last_service_month', '—') or '—',
                                    '__SERVICE_DUE_DATE__':      _cli_lead_data.get('service_due_date', '—') or '—',
                                    '__HELPLINE_NUMBER__':       _cli_lead_data.get('helpline_number', '+91 8130102683') or '+91 8130102683',
                                    '__MODEL_NUMBER__':          _cli_lead_data.get('model_number', '—') or '—',
                                    '__KOEL_STATUS__':           _cli_lead_data.get('koel_status', '—') or '—',
                                    '__PHONE_NUMBER__':          ten_digit_cli or phone_number or '—',
                                    '__INSTALLATION_DATE__':     _cli_agree,
                                    # Faber-specific — must be filled here because lead_data is
                                    # empty at WebSocket connect time (Cube never sends phone in URL)
                                    '__PRODUCT__':      _cli_lead_data.get('product', 'product') or 'product',
                                    '__DEALER_NAME__':  _cli_lead_data.get('dealer_name', 'the dealer') or 'the dealer',
                                }
                                for _ph, _val in _cli_replacements.items():
                                    patched_sys = patched_sys.replace(_ph, _val)
                                print(f"✅ CLI/DNI: All placeholders replaced — "
                                      f"customer={_first}, product={_cli_replacements['__PRODUCT__']}, "
                                      f"dealer={_cli_replacements['__DEALER_NAME__']}")

                                # Add company line if not already present
                                if company_name and f"calling from {company_name}" not in patched_sys:
                                    patched_sys += (
                                        f"\n\n**IMPORTANT**: The customer is calling from "
                                        f"{company_name}. Use this context when relevant."
                                    )

                                conversation_history[0]['content'] = patched_sys

                                ctype = _cli_lead_data.get('customer_type', 'Unknown')
                                ltype = _cli_lead_data.get('lead_type', 'Unknown')
                                vert  = _cli_lead_data.get('business_vertical', '')
                                print(f"✅ CLI/DNI: System-message patched — "
                                      f"Flow={_cli_flow}, Name={_first}, Type={ctype}/{ltype}, "
                                      f"Vertical={vert}, len={len(patched_sys)}")
                            else:
                                print(f"ℹ️ CLI/DNI: No lead data to patch into system message")
                        except Exception as patch_err:
                            print(f"⚠️ CLI/DNI: System-message patch failed (non-critical): {patch_err}")

                        # Mark that CLI/DNI has been received
                        cli_dni_received = True
                        log_to_supabase(
                            f"CLI/DNI processed: {cli_phone}",
                            "INFO",
                            record_id=call_id,
                            details={"cli_data": cli_dni_data}
                        )
                        print(f"✅ CLI/DNI processed — customer_name='{customer_name}', "
                              f"company_name='{company_name}', call_id='{call_id}'")
                    except Exception as e:
                        print(f"⚠️ Error parsing CLI/DNI: {e}")
                    continue  # Process next message
                
                elif msg_type == CUBE_MSG_DTMF:
                    dtmf_digit = chr(message[1]) if len(message) > 1 else ''
                    print(f"🔢 DTMF received: {dtmf_digit}")
                    continue  # Process next message
                
                # ========== AUDIO DATA PROCESSING ==========
                # Extract PCM audio (skip message type byte if present)
                if msg_type == CUBE_MSG_AUDIO and len(message) > 3:
                    pcm_audio = message[3:]  # Skip 3 bytes (Type + 2 bytes Length)
                else:
                    pcm_audio = message  # Entire message is audio
                
                # Skip tiny packets (noise/padding)
                if len(pcm_audio) < 100:
                    continue
                
                # ========== SEND GREETING ON FIRST AUDIO ==========
                # Wait for CLI/DNI if we don't have customer name yet (for outbound calls)
                if not greeting_sent:
                    greeting_sent = True
                    print(f"👋 First audio received - initializing Azure STT")
                    
                    # Initialize UtteranceBuffer for this call
                    if 'utterance_buffer' not in locals():
                        config = UtteranceBufferConfig(debug_logging=True)
                        utterance_buffer = UtteranceBuffer(config)

                    # ── STT GATE SETUP ────────────────────────────────────────────────
                    # stt_discard_until: time-based gate. While time.time() is less
                    # than this value, all final transcripts are silently discarded.
                    # 0.0 = open (always in the past), float('inf') = closed forever.
                    # AudioQueueManager closes the gate at each sentence start and
                    # re-opens it 1 second before each sentence ends (pre-roll).
                    stt_discard_until = {'value': 0.0}    # 0.0 = gate OPEN
                    detected_language = {'value': 'hi'}   # updated per utterance by on_recognized_handler

                    async def open_stt_gate():
                        """Open the STT gate — user transcripts flow to LLM."""
                        stt_discard_until['value'] = 0.0
                        print("[STT] Gate OPEN — accepting user transcripts")

                    async def close_stt_gate():
                        """Close the STT gate — discard all incoming transcripts."""
                        stt_discard_until['value'] = float('inf')
                        print("[STT] Gate CLOSED — discarding transcripts (bot speaking)")

                    # Define callback for processing buffered speech (async)
                    async def process_buffered_speech(text):
                        """LLM processing. Ack already fired by on_recognized_handler."""
                        # Inject language tag so LLM knows which language to respond in
                        lang_tag = f"[DETECTED_LANGUAGE: {detected_language['value']}] "
                        text = lang_tag + text
                        print(f"🚀 process_buffered_speech: '{text[:70]}...'")

                        # ⚡ LLM starts IMMEDIATELY — ack was already sent by on_recognized_handler.
                        # ack_done_event=None → AudioQueueManager never gates, fires as soon as TTS ready.
                        await process_user_speech_parallel(
                            text,
                            conversation_history,
                            websocket,
                            call_id,
                            bot_speaking_state,
                            interruption_state,
                            ack_done_event=None,
                            on_first_audio=open_stt_gate,
                            on_stt_close=close_stt_gate,
                        )

                    # Define callback for recognized speech (MUST BE SYNC!)
                    def on_recognized_handler(event):
                        """Handle complete utterances from Deepgram STT."""
                        try:
                            text = event.result.text.strip()
                            detected_language['value'] = getattr(event.result, 'language', 'hi') or 'hi'
                            print(f"🌐 Detected language: {detected_language['value']}")
                            if not text:
                                # Edge case: empty transcript after VAD interrupt
                                # Reset pending_recognition so bot doesn't get stuck forever
                                if interruption_state and interruption_state.pending_recognition:
                                    print("⚠️ Empty transcript after VAD interrupt — resetting pending_recognition")
                                    interruption_state.pending_recognition = False
                                    stt_discard_until['value'] = 0.0  # open gate so conversation can continue
                                return

                            # ── VAD INTERRUPTION PATH (checked BEFORE short-utterance filter) ──
                            # IMPORTANT: must happen before the word-count filter, because the
                            # user's response after a VAD interrupt might be very short ("हाँ",
                            # "हैलो") but it's still meaningful and must unblock the bot.
                            # Without this, pending_recognition stays True forever → bot silent.
                            if interruption_state and interruption_state.pending_recognition:
                                print(f"✅ Speech recognized after VAD interruption: '{text}'")
                                interruption_state.pending_recognition = False

                                # Close gate for this new LLM cycle (AudioQueueManager re-opens).
                                stt_discard_until['value'] = float('inf')
                                print(f"[STT] Gate CLOSED — discarding transcripts (VAD interrupt path)")

                                # ⚡ INSTANT ACK from memory (VAD path)
                                if InterruptionConfig.ACKNOWLEDGE_UTTERANCE:
                                    _vad_ack_name, _vad_ack_pcm = preloaded_ack_manager.get_random_ack(detected_language['value'])
                                    print(f"🎙️ VAD Ack selected: '{_vad_ack_name}' ({len(_vad_ack_pcm)} bytes)")
                                    if _vad_ack_pcm:
                                        async def _send_vad_ack(pcm=_vad_ack_pcm, name=_vad_ack_name):
                                            print(f"⚡ VAD Ack coroutine running: '{name}'")
                                            try:
                                                await websocket.send_bytes(pcm)
                                                print(f"⚡ VAD Ack sent: '{name}' ({len(pcm)/16000:.2f}s)")
                                            except Exception as e:
                                                print(f"⚠️ Ack send error: {e}")
                                        asyncio.ensure_future(_send_vad_ack(), loop=current_loop)
                                    else:
                                        print(f"🤫 Silent ack chosen (VAD path: '{_vad_ack_name}') — skipping audio")

                                print(f"📤 [VAD-interrupt path] Routing to utterance_buffer: '{text[:60]}'")
                                asyncio.run_coroutine_threadsafe(
                                    utterance_buffer.add_utterance(text, process_buffered_speech),
                                    current_loop
                                )
                                return  # Done — don't fall into the gate check below


                            print(f"🗣️ User said: {text}")

                            # ── TURN-TAKING GATE (time-based) ────────────────────────────
                            # If the gate is closed (stt_discard_until is in the future /
                            # infinity), discard the transcript silently — bot is speaking
                            # or processing and we don't want echo or double LLM calls.
                            if time.time() < stt_discard_until['value']:
                                print(f"[STT] Pre-roll discard: '{text[:60]}'")
                                return

                            # ── NORMAL PATH (gate open) ──────────────────────────────────
                            # Close the gate immediately so the next transcript doesn't
                            # trigger a second LLM call while this one is in flight.
                            stt_discard_until['value'] = float('inf')
                            print(f"[STT] Gate CLOSED — discarding transcripts (processing: '{text[:60]}')")

                            # ⚡ INSTANT ACK — fire immediately from memory (matches skills doc)
                            # Fires here in the sync STT callback — fastest possible path.
                            if InterruptionConfig.ACKNOWLEDGE_UTTERANCE:
                                _ack_name, _ack_pcm = preloaded_ack_manager.get_random_ack(detected_language['value'])
                                print(f"🎙️ Ack selected: '{_ack_name}' ({len(_ack_pcm)} bytes)")
                                if _ack_pcm:
                                    async def _send_ack(pcm=_ack_pcm, name=_ack_name):
                                        print(f"⚡ Ack coroutine running: '{name}'")
                                        try:
                                            await websocket.send_bytes(pcm)
                                            print(f"⚡ Ack sent: '{name}' ({len(pcm)/16000:.2f}s)")
                                        except Exception as e:
                                            print(f"⚠️ Ack send error: {e}")
                                    asyncio.ensure_future(_send_ack(), loop=current_loop)
                                else:
                                    print(f"🤫 Silent ack (normal path): '{_ack_name}'")

                            print(f"📤 Routing to utterance_buffer.add_utterance()")
                            asyncio.run_coroutine_threadsafe(
                                utterance_buffer.add_utterance(text, process_buffered_speech),
                                current_loop
                            )
                            print(f"📤 Utterance queued")
                        
                        except Exception as e:
                            import traceback
                            print(f"❌ Error in on_recognized_handler: {e}")
                            traceback.print_exc()
                    
                    # Define callback for partial recognition
                    def on_recognizing_handler(event):
                        """Handle partial transcriptions.

                        While the gate is closed (bot speaking / processing), partials
                        are silently discarded — we NEVER cancel the in-flight LLM just
                        because the user made a sound during the closed window.
                        """
                        if hasattr(event, 'result') and hasattr(event.result, 'text'):
                            partial_text = event.result.text.strip()
                            if partial_text and len(partial_text) > 3:
                                print(f"\r🎤 {partial_text[:80]}", end='', flush=True)

                                # Gate closed — ignore partials (echo / premature speech).
                                if time.time() < stt_discard_until['value']:
                                    return

                                if utterance_buffer.is_processing:
                                    cancelled = utterance_buffer.cancel_on_new_speech_detected()
                                    if cancelled:
                                        print(f"\n⚡ Cancelled LLM - user is still speaking!")

                    # Set the callbacks BEFORE starting the session
                    speech_recognizer.on_recognized = on_recognized_handler
                    speech_recognizer.on_recognizing = on_recognizing_handler
                    
                    # Start Deepgram STT session
                    await speech_recognizer.start_async()
                    print("✅ Deepgram STT session started")
                    
                    # ========== WAIT FOR CLI/DNI (Only if needed) ==========
                    # Customer name is already set from the outbound registry (claimed at WebSocket accept).
                    # Only wait for CLI/DNI if we still don't have a name (rare inbound edge-case).
                    # Always wait for CLI/DNI — needed for DB lead lookup and full placeholder injection.
                    if not cli_dni_received:
                        print("⏳ Waiting for CLI/DNI (max 4s) — needed for DB lead lookup...")
                        wait_start = time.monotonic()
                        max_wait = 4.0
                        while not cli_dni_received and (time.monotonic() - wait_start) < max_wait:
                            await asyncio.sleep(0.02)
                        if cli_dni_received:
                            elapsed = (time.monotonic() - wait_start) * 1000
                            print(f"✅ CLI/DNI received after {elapsed:.0f}ms, customer_name='{customer_name}'")
                        else:
                            print(f"⚠️ CLI/DNI timed out after 4s — proceeding with registry/generic data")
                    else:
                        print(f"⚡ CLI/DNI already received — skipping wait")
                    
                    # Send greeting asynchronously with customer name
                    print(f"🎯 About to send greeting with customer_name='{customer_name}', call_id='{call_id}'")
                    
                    # 🛡️ GREETING PROTECTION: Mark that greeting will be sent
                    # Actual timing will be set when greeting audio starts playing
                    greeting_protection['greeting_queued'] = True
                    print(f"🛡️ Greeting queued - VAD/STT will be disabled until 50% of greeting playback")
                    
                    asyncio.create_task(send_cube_greeting(
                        websocket, conversation_history, bot_speaking_state, interruption_state, 
                        customer_name=customer_name, call_id=call_id, greeting_protection=greeting_protection
                    ))
                
                # 🛡️ GREETING PROTECTION CHECK
                # Check if we should process audio (after 50% of greeting)
                protection_active = False
                if greeting_protection['active']:
                    if greeting_protection['greeting_started'] and greeting_protection['halfway_point'] > 0:
                        # Check if we've passed 50% mark
                        current_time = time.time()
                        if current_time >= greeting_protection['halfway_point']:
                            # 50% mark reached - disable protection
                            greeting_protection['active'] = False
                            greeting_protection['protection_ended'] = True
                            print(f"🔓 Greeting 50% complete - VAD/STT enabled")
                        else:
                            protection_active = True
                    else:
                        # Greeting hasn't started playing yet - keep protection active
                        protection_active = True
                
                # ========== VAD (VOICE ACTIVITY DETECTION) ==========
                # ⚡ SEND ALL AUDIO TO VAD - Continuous monitoring
                # 
                # The VAD service analyzes EVERY chunk and triggers 'interrupt' only when
                # it detects real human speech (probability > threshold).
                # 
                # Bot's TTS echo has very low prob (~0.001-0.03), well below threshold.
                # Real human voice has high prob (~0.6-0.9), well above threshold.
                #
                # This ensures VAD is always ready to detect the START of user speech,
                # not waiting for bot_speaking flag to be set first.
                #
                # 🛡️ GREETING PROTECTION: Skip VAD during first 50% of greeting
                
                if VADConfig.ENABLED and not protection_active:
                    if VADConfig.USE_VAD_SERVICE and vad_connected:
                        # Send EVERY chunk to VAD (fire-and-forget)
                        asyncio.create_task(send_audio_to_vad(pcm_audio))
                    elif bot_speaking_state['speaking']:
                        # Fallback: Energy-based VAD (only when bot is speaking)
                        # Fallback: Energy-based VAD (less accurate but works without service)
                        # Calculate audio energy for this chunk
                        energy = calculate_audio_energy(pcm_audio)
                        
                        # Add to smoothing buffer (deque auto-manages size)
                        interruption_state.energy_buffer.append(energy)
                        
                        # Calculate smoothed energy (average over window)
                        if len(interruption_state.energy_buffer) > 0:
                            smoothed_energy = sum(interruption_state.energy_buffer) / len(interruption_state.energy_buffer)
                        else:
                            smoothed_energy = energy
                        
                        # Check if energy is above threshold
                        if smoothed_energy > VADConfig.NOISE_GATE:  # Above noise gate
                            if smoothed_energy > VADConfig.ENERGY_THRESHOLD:  # Above voice threshold
                                interruption_state.chunks_above_threshold += 1
                                
                                # Voice detected for minimum duration?
                                if interruption_state.chunks_above_threshold >= VADConfig.MIN_CHUNKS_ABOVE_THRESHOLD:
                                    # ========== ENERGY VARIANCE CHECK ==========
                                    # Throat clearing = sharp spike (high variance)
                                    # Real speech = stable energy (low variance)
                                    if len(interruption_state.energy_buffer) >= 3:
                                        energy_variance = max(interruption_state.energy_buffer) - min(interruption_state.energy_buffer)
                                        if energy_variance > VADConfig.ENERGY_VARIANCE_THRESHOLD:
                                            # Likely throat clear / cough - ignore
                                            print(f"🔇 Spike detected (variance: {energy_variance:.0f}), likely throat clear - ignoring")
                                            interruption_state.chunks_above_threshold = 0
                                            continue  # Skip VAD trigger
                                    
                                    # Check cooldown
                                    if interruption_state.can_vad_trigger():
                                        # VAD TRIGGER! User is speaking!
                                        metrics.record_vad_trigger(is_valid=True)
                                        print(f"🔊 VAD TRIGGER! Energy: {smoothed_energy:.0f} (threshold: {VADConfig.ENERGY_THRESHOLD})")
                                        
                                        # Handle interruption immediately (async)
                                        asyncio.create_task(
                                            handle_vad_interruption(
                                                websocket,
                                                call_id,
                                                bot_speaking_state,
                                                interruption_state
                                            )
                                        )
                            else:
                                # Below voice threshold - reset counter
                                interruption_state.chunks_above_threshold = 0
                        else:
                            # Below noise gate - reset counter
                            interruption_state.chunks_above_threshold = 0
                
                # Feed audio to Deepgram STT
                # 🛡️ GREETING PROTECTION: Skip STT during first 50% of greeting
                if speech_recognizer and speech_recognizer.is_running and not protection_active:
                    speech_recognizer.write_audio(pcm_audio)
                elif protection_active:
                    # Silently discard audio during protection period
                    pass
                else:
                    print("⚠️ STT not running - skipping audio")
                
                audio_chunk_count += 1
                
                if audio_chunk_count % 200 == 0:
                    print(f"🎵 Chunks: {audio_chunk_count}")
                    
                
        except WebSocketDisconnect:
            print("🔌 Cube client disconnected")
            log_to_supabase("Cube client disconnected (WebSocket)", "INFO", record_id=call_id)
        except Exception as e:
            try:
                db.log_console(
                    f"Call failed with error: {str(e)}",
                    log_level='ERROR',
                    record_id=call_id,
                    details={'error': str(e)}
                )
                # Update call status to failed
                db.update_call_status(call_id, 'failed')
            except Exception as db_err:
                print(f"⚠️ Database update error (non-critical): {db_err}")

    # Start receiving audio from Cube (with cleanup)
    try:
        await receive_from_cube()
    finally:
        # ── UPDATE CALL STATUS — FIRST, before any cleanup ─────────────────────
        # This must run immediately once the WebSocket loop exits, NOT after
        # VAD/STT teardown below. speech_recognizer.stop_async() can hang for
        # minutes under load; if the status write waited behind it, a real
        # completed call could still look "initiated" when the independent
        # 250s safety-net timer (armed at call-start) checks in and wrongly
        # concludes the call never connected. Writing the status here, before
        # any teardown step that could block, closes that race.
        try:
            if len(conversation_history) > 2:
                final_call_status = 'completed'
            elif audio_chunk_count > 0:
                # WebSocket connected + audio received = person answered but dropped
                final_call_status = 'completed'
            else:
                # WebSocket connected but zero audio = Cube routing glitch, treat as not_connected
                final_call_status = 'not_connected'
            print(f"📞 Updating call status → '{final_call_status}' for {call_id}")
            db.update_call_status(call_id, final_call_status)

            # Mirror onto leads.status so the 250s safety net (which checks
            # lead.status, not calls.call_status) sees the real outcome too.
            if len(conversation_history) > 2 and phone_number:
                try:
                    db.update_all_leads_by_phone(phone_number, 'completed')
                except Exception as lead_complete_err:
                    print(f"⚠️ Could not update lead status to completed: {lead_complete_err}")
        except Exception as status_err:
            print(f"⚠️ Could not update call status: {status_err}")

        # Cancel 4-min cutoff timer if call ended before limit
        if _call_cutoff_task and not _call_cutoff_task.done():
            _call_cutoff_task.cancel()
            try:
                await _call_cutoff_task
            except asyncio.CancelledError:
                pass

        # Cleanup VAD connection
        if vad_listener is not None:
            vad_listener.cancel()
            try:
                await vad_listener
            except asyncio.CancelledError:
                pass
        if vad_ws is not None:
            try:
                await vad_ws.close()
            except:
                pass

            # Stop STT session
            if speech_recognizer:
                try:
                    await speech_recognizer.stop_async()
                except Exception as e:
                    print(f"⚠️ Error stopping STT: {e}")

            print("🧹 VAD & STT cleanup complete")

        # ANALYZE CALL FOR CRM
        # ── Last-chance lead lookup ──────────────────────────────────────────
        # For inbound calls where lead_id is still None after the call
        # (very rare edge-case — lead was not in DB at connect time).
        if not lead_id and phone_number:
            try:
                print(f"🔍 Post-call: Last-chance lead lookup for phone={phone_number}")
                late_lead = get_lead_by_phone(phone_number)
                if late_lead:
                    lead_id = late_lead['id']
                    print(f"✅ Post-call: lead_id={lead_id} resolved via last-chance lookup")
                else:
                    print(f"⚠️ Post-call: No lead found for phone={phone_number}")
            except Exception as late_lookup_err:
                print(f"⚠️ Post-call: Last-chance lead lookup failed: {late_lookup_err}")

        # Release the outbound registry slot so this phone can be called again
        if phone_number:
            release_outbound_call(phone_number)

        # ── Campaign lead outcome detection ───────────────────────────────────
        # Classify outcome from conversation history and persist to campaign_leads
        _call_phone = ten_digit_cli or phone_number
        if _call_phone and len(conversation_history) > 2:
            try:
                _outcome, _conclusion = _detect_call_outcome(conversation_history)
                print(f"📊 Call outcome: {_outcome} | conclusion: {_conclusion[:80]}")
                db.update_campaign_lead_outcome(
                    phone=_call_phone,
                    outcome=_outcome,
                    conclusion=_conclusion,
                )
            except Exception as _oc_err:
                print(f"⚠️ Outcome detection failed (non-critical): {_oc_err}")



        if phone_number and len(conversation_history) <= 2 and audio_chunk_count > 0:
            # ── SCENARIO 2: WebSocket connected, person answered but dropped <2 turns
            # The person DID pick up the call — log it as a dropped call so the
            # lead status reflects it (no LLM needed, nothing meaningful to analyse).
            print(f"📵 Short call detected ({len(conversation_history)} turns) — "
                  f"marking lead as 'dropped'")
            _drop_task = asyncio.create_task(
                asyncio.to_thread(
                    sync_not_connected_call,
                    phone_number,
                    lead_id,
                    call_id,
                    "dropped"
                )
            )

            def _on_drop_done(task, _call_id=call_id, _phone=phone_number):
                exc = task.exception() if not task.cancelled() else None
                if task.cancelled():
                    print(f"⚠️  Drop-sync task CANCELLED for call_id={_call_id}")
                elif exc:
                    print(f"❌ Drop-sync task FAILED for call_id={_call_id}: {exc}")
                else:
                    print(f"✅ Drop-sync task COMPLETED for call_id={_call_id}")

            _drop_task.add_done_callback(_on_drop_done)

        elif len(conversation_history) <= 2:
            print(f"⚠️ Skipping drop-sync: lead_id={lead_id}, phone={phone_number!r}, "
                  f"history_len={len(conversation_history)}, chunks={audio_chunk_count}")
            if not lead_id:
                print("   └─ Reason: lead_id is None (inbound call with no matching lead in DB)")
            if not phone_number:
                print("   └─ Reason: phone_number is empty (CLI/DNI never arrived or was not parsed)")
            print(f"   └─ Reason: conversation too short and no audio (pure system messages)")

        # ── Post-call analysis + writeback ────────────────────────────────────
        # Always writes installation_status/disposition/sentiment/summary to
        # the calls table. Also writes to lead_file_rows if this call came
        # from a Faber Excel row (for Excel export of the latest call).
        if phone_number and len(conversation_history) > 2:
            asyncio.create_task(_faber_lead_writeback(call_id, list(conversation_history)))

        # ── Not-connected bookkeeping: conversation never started ─────────────
        # Fires when there was no real conversation (not connected / picked up
        # but dropped before talking). No-op unless this call came from an Excel
        # row. Covers the case the 60s watchdog doesn't (the WebSocket connected,
        # so the watchdog saw the lead move past 'initiated').
        if len(conversation_history) <= 2:
            asyncio.create_task(_mark_not_connected_row(call_id))

        # ── UPDATE LEAD FINAL STATUS ─────────────────────────────────────────
        # Scenario 3 (normal call)  — lead→'completed' already handled at the top
        #                             of this finally block.
        # Scenario 2 (dropped)     — lead→'not_connected' handled inside sync_not_connected_call
        # For cases where neither ran (no lead_id, no phone), do best-effort here.
        try:
            if len(conversation_history) > 2:
                pass
            elif phone_number and not lead_id:
                # No lead_id available — do a phone-based fallback update
                lead_info = get_lead_by_phone(phone_number)
                if lead_info:
                    fallback_status = 'not_connected' if audio_chunk_count > 0 else 'pending'
                    update_lead_status(lead_info['id'], fallback_status)
                    print(f"✅ Lead status (fallback) → '{fallback_status}' for phone={phone_number}")
        except Exception as lead_err:
            print(f"⚠️ Could not update lead final status: {lead_err}")


@app.get("/api/leads")
async def get_leads_endpoint(limit: int = 100, offset: int = 0, date: str = None):
    """Get all fetched leads with their latest call status.

    PERFORMANCE FIX: Previously this made N+1 Supabase HTTP calls (1 for leads
    + 1 per lead for call status = ~100 calls = 5-6s blocking the event loop).
    Now it makes exactly 2 calls total and runs them in asyncio.to_thread() so
    the async event loop is never blocked.

    Args:
        limit: Max leads to return
        offset: Pagination offset
        date: Optional date filter in YYYY-MM-DD format (filters by CRM date_created)
    """
    if date:
        print(f"📊 GET /api/leads called (limit={limit}, offset={offset}, date={date})")
    else:
        print(f"📊 GET /api/leads called (limit={limit}, offset={offset})")

    try:
        # ── 1. Fetch leads (blocking I/O → run in thread) ──────────────────────
        leads = await asyncio.to_thread(
            db.get_all_leads, limit=limit, offset=offset, date_filter=date
        )

        if not leads:
            print("✅ Returning 0 leads")
            return {"success": True, "leads": [], "count": 0, "date_filter": date}

        # ── 2. Parse lead_data JSON for frontend ───────────────────────────────
        for lead in leads:
            raw = lead.get('lead_data')
            if raw:
                try:
                    lead['details'] = raw if isinstance(raw, dict) else json.loads(raw)
                except Exception:
                    lead['details'] = {}
            else:
                lead['details'] = {}

        # ── 3. Batch-fetch latest call status (ONE Supabase call for ALL leads) ─
        phone_numbers = [l['phone_number'] for l in leads if l.get('phone_number')]
        latest_calls_map = await asyncio.to_thread(
            db.get_latest_calls_for_phones, phone_numbers
        )

        # ── 4. Attach call status to each lead ─────────────────────────────────
        for lead in leads:
            raw_phone = lead.get('phone_number', '')
            digits = ''.join(filter(str.isdigit, raw_phone))
            key = digits[-10:] if len(digits) >= 10 else digits
            latest_call = latest_calls_map.get(key)
            if latest_call:
                lead['latest_call_status'] = latest_call.get('call_status', 'no_call')
                lead['latest_call'] = latest_call
            else:
                lead['latest_call_status'] = 'no_call'
                lead['latest_call'] = None

        print(f"✅ Returning {len(leads)} leads{' for date ' + date if date else ''}")
        return {"success": True, "leads": leads, "count": len(leads), "date_filter": date}

    except Exception as e:
        print(f"❌ Error in get_leads_endpoint: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/leads/refresh")
async def refresh_leads_endpoint(request: Request):
    """Manually trigger lead refresh from CRM API for a specific date.
    
    NOTE: This is for MANUAL sync only. The daily automatic sync at 10 AM
    uses yesterday's date by default (via scheduler_task).
    
    Request Body (REQUIRED):
    {
        "date": "2026-02-08"  // YYYY-MM-DD format - REQUIRED
    }
    """
    try:
        # Try to get date from request body
        target_date = None
        try:
            body = await request.json()
            target_date = body.get('date')
        except:
            target_date = None
        
        # Date is required for manual sync
        if not target_date:
            print("❌ POST /api/leads/refresh called - No date provided (required)")
            return {"success": False, "error": "Date is required. Please select a date to fetch leads."}
        
        print(f"🔄 POST /api/leads/refresh called - Fetching leads for date: {target_date}")
        
        # Run the lead fetch in a thread to not block
        await asyncio.to_thread(fetch_and_store_leads, target_date)
        
        # Get the count of leads after refresh
        lead_count = len(db.get_all_leads(limit=1000))
        
        print(f"✅ Lead refresh complete! Total leads in DB: {lead_count}")
        return {
            "success": True, 
            "message": f"Leads refreshed successfully for {target_date}",
            "date_fetched": target_date,
            "total_leads": lead_count
        }
    except Exception as e:
        print(f"❌ Error refreshing leads: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/make-call")
async def api_make_call_endpoint(request: Request):
    """Initiate outbound call via Cube Click2Call API.
    
    This endpoint is called by the React frontend.
    It reuses the working make_cube_outbound_call function.
    """
    print("📞 POST /api/make-call called")
    try:
        data = await request.json()
        print(f"📦 Raw request payload received: {json.dumps(data, indent=2)}")
        
        # 🆕 Updated parameter names to match frontend
        to_number = data.get('to_number') or data.get('phone_number')  # Support both for backward compatibility
        name = data.get('name') or data.get('customer_name', '') or 'Customer'
        company_name = data.get('company_name', '')
        lead_data = data.get('lead_data', {})  # NEW: Accept lead data from frontend
        
        # Debug: Check what frontend sent
        print(f"🔍 Parsed from request:")
        print(f"   to_number: {to_number}")
        print(f"   name: {name}")
        print(f"   company_name: {company_name}")
        print(f"   lead_data type: {type(lead_data)}")
        print(f"   lead_data value: {lead_data}")
        if lead_data:
            print(f"   lead_data keys: {list(lead_data.keys()) if isinstance(lead_data, dict) else 'N/A'}")
            print(f"   lead_data content: {json.dumps(lead_data, indent=2)}")
        else:
            print(f"   ⚠️ lead_data is empty or missing!")
        
        if not to_number:
            return {"success": False, "error": "Phone number is required"}
        
        # Extract only digits and validate
        clean = ''.join(filter(str.isdigit, str(to_number)))
        if len(clean) < 10:
            return {"success": False, "error": "Phone number must have at least 10 digits"}
        
        # Extract last 10 digits (removes country codes like +91, 91)
        ten_digit_number = clean[-10:]
        
        # 🆕 DATABASE-FIRST: Save lead data to DB before making call
        if lead_data and isinstance(lead_data, dict) and len(lead_data) > 0:
            print(f"💾 Saving lead data to database for {ten_digit_number}")
            try:
                lead_id = db.create_or_update_lead(
                    phone_number=ten_digit_number,
                    name=name,
                    lead_data=lead_data
                )
                print(f"✅ Lead saved to DB with ID: {lead_id}")
            except Exception as db_err:
                print(f"⚠️ Failed to save lead to DB (non-critical): {db_err}")
        
        print(f"📞 Initiating call to {ten_digit_number} (Original: {to_number})")
        print(f"   Name: {name}, Company: {company_name}")
        if lead_data and isinstance(lead_data, dict) and len(lead_data) > 0:
            print(f"   ✅ Lead Data received: Type={lead_data.get('customer_type')}, LeadType={lead_data.get('lead_type')}, Vertical={lead_data.get('business_vertical')}")
        else:
            print(f"   ⚠️ No valid lead_data received (empty or missing)")
        
        # Use the working make_cube_outbound_call function
        result = await make_cube_outbound_call(
            to_number=ten_digit_number,
            name=name,
            company_name=company_name,
            lead_data=lead_data  # NEW: Pass lead data
        )
        
        # Add the original phone_number to result for frontend display
        if result.get('success'):
            result['phone_number'] = to_number
            # Also include raw response for debugging
            result['response'] = result.get('cube_response', str(result))
        
        return result
            
    except Exception as e:
        print(f"❌ Error in api_make_call_endpoint: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@app.post("/api/webhook/recording")
async def recording_webhook(request: Request):
    """
    Webhook endpoint for telephony provider to send recording URLs.
    
    Expected payload:
    {
        "record_id": "BotrixAI_BoT:000270806497:38",  # Outbound Cube format — "CampaignName:Number:Sequence"
        "record_id": "CubeVOIP_IN98761",               # Inbound Cube format
        "recording_url": "https://example.com/recordings/abc123.mp3",
        "duration": 140,
        "status": "completed"
    }

    Matching strategy (3 tiers):
    1. cube_call_number from outbound record_id's trailing sequence number
       (e.g. "BotrixAI_BoT:000270806497:38" -> 38) — same approach as /getCallStatus
    2. Direct record_id match (backward compat)
    3. Duration + recency fuzzy match (inbound — CubeVOIP_IN has no shared key with UUID)
    """
    print("🎙️ POST /api/webhook/recording called")
    try:
        data = await request.json()
        print(f"   Webhook payload: {data}")
        
        webhook_record_id = data.get('record_id') or data.get('call_id') or data.get('recordId')
        recording_url = data.get('recording_url') or data.get('recordingUrl') or data.get('url')
        duration = data.get('duration')
        
        if not webhook_record_id:
            return {"success": False, "error": "record_id is required"}
        
        if not recording_url:
            return {"success": False, "error": "recording_url is required"}
        
        # ── GUARD: Reject Cube's ghost callbacks for un-answered calls ─────────
        # Cube sometimes fires a recording webhook immediately when a call is not
        # answered. These arrive with duration=0 and an empty URL. Storing them
        # would create a ghost 'completed' call row in DB with no CRM IDs.
        duration_int = int(duration) if duration is not None else None
        if not recording_url.strip() or recording_url.strip() == "''" or (duration_int is not None and duration_int == 0):
            print(f"   ⚠️ Ignoring ghost recording callback: url={recording_url!r}, duration={duration} — this is a Cube no-answer acknowledgment")
            return {"success": True, "message": "Ghost callback ignored (no-answer call)", "ignored": True}
        
        # ── TIER 1: Extract cube_call_number from Cube's "CampaignName:Number:Sequence"
        # record_id (e.g. "BotrixAI_BoT:000270806497:38") — same proven approach as
        # the /getCallStatus webhook: match on the trailing sequence number.
        cube_call_number = None
        try:
            if ":" in webhook_record_id:
                cube_call_number = int(webhook_record_id.split(":")[-1])
                print(f"   📊 Extracted cube_call_number: {cube_call_number} from {webhook_record_id}")
        except (ValueError, AttributeError) as e:
            print(f"   ⚠️ Could not extract cube_call_number from {webhook_record_id}: {e}")
        
        call = None
        match_method = None
        
        if cube_call_number:
            call = db.get_call_by_cube_number(cube_call_number)
            if call:
                match_method = f"cube_call_number={cube_call_number}"
        
        # ── TIER 2: Direct record_id match ────────────────────────────────────
        if not call:
            call = db.get_call_by_record_id(webhook_record_id)
            if call:
                match_method = f"direct record_id={webhook_record_id}"
                print(f"   ⚠️ Found call by direct record_id match (fallback)")
        
        # ── TIER 3: Duration + recency fuzzy match (inbound calls) ────────────
        # Inbound: DB has UUID record_id, Cube webhook sends "CubeVOIP_IN..."
        # No shared key exists — match by duration within last 5 minutes
        if not call and duration:
            print(f"   🔍 Trying duration+recency match (duration={duration}s) for inbound call...")
            call = db.get_call_by_duration_and_recency(int(duration), within_minutes=5)
            if call:
                match_method = f"duration+recency (duration={duration}s)"
                print(f"   ✅ Inbound call matched via duration+recency: {call['record_id']}")
        
        if not call:
            print(f"   ❌ Call not found for cube_call_number={cube_call_number}, "
                  f"record_id={webhook_record_id}, duration={duration}s")
            return {"success": False, "error": f"Call not found for record_id: {webhook_record_id}"}
        
        actual_record_id = call['record_id']
        print(f"   ✅ Matched call: {actual_record_id} (via {match_method})")
        
        try:
            db.update_recording_url(actual_record_id, recording_url, duration)
            print(f"   ✅ Recording URL stored for {actual_record_id}" + (f" (duration: {duration}s)" if duration else ""))
            
            if data.get('status') and duration_int and duration_int > 0:
                db.update_call_status(actual_record_id, data.get('status'))
            elif data.get('status') and not duration_int:
                # No duration info — update status cautiously only if not setting to completed
                if data.get('status') != 'completed':
                    db.update_call_status(actual_record_id, data.get('status'))
            
            return {
                "success": True,
                "message": "Recording URL stored successfully",
                "record_id": actual_record_id,
                "match_method": match_method,
                "cube_call_number": cube_call_number
            }
        except Exception as db_err:
            print(f"   ❌ Database error: {db_err}")
            return {"success": False, "error": f"Database error: {str(db_err)}"}
            
    except Exception as e:
        print(f"❌ Error in recording_webhook: {e}")
        return {"success": False, "error": str(e)}


# ==================== CUBE REAL-TIME CALL STATUS WEBHOOK ====================

@app.get("/getCallStatus")
async def cube_call_status_webhook(PhoneNo: str = None, Status: str = None, callId: str = None):
    """
    Real-time call-status webhook — Cube hits this directly (GET, query params)
    at each lifecycle stage of an outbound call:
        ?PhoneNo=...&Status=Calling&callId=...
        ?PhoneNo=...&Status=Connected&callId=...
        ?PhoneNo=...&Status=Not Connected&callId=...   (exact string TBD)
        ?PhoneNo=...&Status=Disconnected&callId=...

    callId is NOT a direct match for calls.record_id — Cube sends it as
    "CampaignName:Number:Sequence" (e.g. "BotrixAI_Bot:000270473693:737"),
    while our stored record_id is "Number:CampaignName:Sequence" (the order Click2Call
    returns it in). Match on the trailing sequence number (cube_call_number) instead,
    same proven approach already used by the recording webhook.

    This REPLACES the old 60s "guess from our own lead status" watchdog with the
    actual ground truth from Cube. The 250s task in make_cube_outbound_call is
    now only a safety net for total webhook silence (see there for details).
    """
    # Log the RAW value of every single hit — recognized or not — so we can see
    # every distinct status string Cube actually sends in production. repr()
    # surfaces exact casing/whitespace that print() alone would hide.
    print(f"📡 GET /getCallStatus — PhoneNo={PhoneNo!r}, Status={Status!r}, callId={callId!r}")
    try:
        await asyncio.to_thread(
            db.log_console,
            f"Cube call-status webhook: Status={Status!r}",
            'INFO',
            callId,
            {"status_raw": Status, "phone": PhoneNo, "call_id_param": callId},
        )
    except Exception as log_err:
        print(f"   ⚠️ Could not persist webhook log (non-critical): {log_err}")

    if not callId or not Status:
        return {"success": False, "error": "callId and Status are required"}

    try:
        # TIER 1: direct record_id match (works if Cube ever sends it in our order)
        call = db.get_call_by_record_id(callId)

        # TIER 2: match on trailing sequence number (handles Cube's swapped
        # "CampaignName:Number:Sequence" order — see docstring above)
        if not call and ":" in callId:
            try:
                cube_call_number = int(callId.split(":")[-1])
                call = db.get_call_by_cube_number(cube_call_number)
            except (ValueError, IndexError):
                pass

        if not call:
            print(f"   ⚠️ No call found for callId={callId} — ignoring (Status was {Status!r})")
            return {"success": True, "ignored": True, "reason": "unknown callId"}

        callId = call['record_id']  # use our stored record_id for all DB writes below

        # Cube sends inconsistent casing/wording across calls (seen in production:
        # "CALLING", "CONNECTED", "NOANSWER" all-caps, alongside "Calling", "Connected",
        # "Not Connected", "Disconnected" title-case). Normalize so both forms match.
        status_norm = (Status or "").strip().upper()

        if status_norm == "CALLING":
            pass  # no action needed — already logged as 'initiated' at Click2Call time

        elif status_norm == "CONNECTED":
            await asyncio.to_thread(db.mark_cube_connected, callId)

        elif status_norm == "DISCONNECTED":
            await asyncio.to_thread(db.mark_cube_disconnected, callId)
            # No fallback logic here — that's owned by the not-connected branch below.
            # If the call DID connect, our existing WebSocket pipeline (hangup
            # detection, post-call analysis, disposition writeback) already
            # handles everything else independently of this webhook.

        else:
            # Any status that isn't CALLING/CONNECTED/DISCONNECTED is treated as
            # not-connected — covers known values ("NOANSWER", "Not Connected")
            # AND any future/unmapped value Cube starts sending. The raw string
            # is stored as-is so the dashboard can show exactly what Cube said
            # instead of a generic label, and so new values are easy to spot.
            print(f"   📋 Status={Status!r} (normalized={status_norm!r}) for callId={callId} "
                  f"— treating as not-connected, storing raw status")

            # Only apply not_connected if the WebSocket hasn't already marked this call
            # as completed (i.e. real audio/conversation happened). Cube sometimes sends
            # a not-connected-shaped status late even for calls that actually connected.
            current_status = call.get('call_status', '')
            if current_status == 'completed':
                print(f"   ⚠️ Cube sent {Status!r} but call {callId} is already completed — ignoring")
            else:
                await asyncio.to_thread(db.update_call_status, callId, 'not_connected', Status)
                if call.get('phone_number'):
                    lead = await asyncio.to_thread(db.get_lead_by_phone, call['phone_number'])
                    if lead:
                        await asyncio.to_thread(db.update_lead_status, lead['id'], 'not_connected')
                asyncio.create_task(_mark_not_connected_row(callId))
                print(f"   📵 Cube confirmed not-connected ({Status!r}) for {callId}")

        return {"success": True, "status": Status, "callId": callId}

    except Exception as e:
        print(f"❌ Error in cube_call_status_webhook: {e}")
        return {"success": False, "error": str(e)}


@app.get("/api/cube-call-statuses-seen")
async def cube_call_statuses_seen(limit: int = 200):
    """
    Diagnostic: list every distinct Status value /getCallStatus has received,
    with counts and a recent example — so all the values Cube actually sends
    in production can be reviewed (e.g. to confirm the exact 'not connected'
    string, or spot any status we don't handle yet).
    """
    try:
        rows = await asyncio.to_thread(db.get_cube_status_distribution, limit)
        return {"success": True, "distinct_statuses": rows, "count": len(rows)}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ==================== KOEL FOLLOW-UP LEADS ====================

@app.post("/api/koel/sync")
async def koel_sync_endpoint(request: Request):
    """Fetch from Koel API and persist in DB."""
    from koel_leads import sync_koel_leads
    try:
        body = await request.json()
        sdate = body.get("sdate")
        edate = body.get("edate")
        seg   = body.get("seg", "MM")
        if not sdate or not edate:
            return {"success": False, "error": "sdate and edate are required"}
        result = sync_koel_leads(sdate, edate, seg)
        return {"success": True, **result}
    except Exception as e:
        print(f"[Koel Sync] Error: {e}")
        return {"success": False, "error": str(e)}


@app.get("/api/koel/leads")
async def koel_leads_endpoint(sdate: str = None, edate: str = None, seg: str = None):
    """Return persisted Koel follow-up leads from DB."""
    from koel_leads import get_koel_leads, ensure_koel_table
    try:
        ensure_koel_table()
        rows = get_koel_leads(sdate, edate, seg)
        leads = [dict(r) for r in rows]
        for lead in leads:
            for k, v in lead.items():
                if hasattr(v, 'isoformat'):
                    lead[k] = v.isoformat()
        return {"success": True, "leads": leads, "count": len(leads)}
    except Exception as e:
        print(f"[Koel Leads] Error: {e}")
        return {"success": False, "error": str(e), "leads": []}


@app.post("/api/koel/call-status")
async def koel_call_status_endpoint(request: Request):
    """Update call_status for a Koel lead."""
    from koel_leads import update_koel_call_status
    try:
        body = await request.json()
        docket_id   = body.get("docket_id")
        call_status = body.get("call_status")
        if not docket_id or not call_status:
            return {"success": False, "error": "docket_id and call_status required"}
        update_koel_call_status(docket_id, call_status)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/koel/interested-leads")
async def koel_interested_leads_endpoint():
    """Return all Koel leads marked as interested (post-call analytics)."""
    from koel_leads import get_interested_koel_leads, ensure_koel_table
    try:
        ensure_koel_table()
        leads = get_interested_koel_leads()
        return {"success": True, "leads": leads, "total": len(leads)}
    except Exception as e:
        return {"success": False, "error": str(e), "leads": [], "total": 0}


def _follow_up_is_today(follow_up_date_str: str, today) -> bool:
    """Check if a follow_up_date string (e.g. '01 Aug 2026') matches today."""
    if not follow_up_date_str:
        return False
    from datetime import datetime
    for fmt in ["%d %b %Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"]:
        try:
            return datetime.strptime(follow_up_date_str.strip(), fmt).date() == today
        except ValueError:
            continue
    return False


@app.get("/api/campaign/koel-today-summary")
async def koel_today_summary_endpoint(seg: str = None):
    """Return count of today's pending Koel follow-up leads (all segments by default)."""
    from koel_leads import get_koel_leads, ensure_koel_table
    from datetime import datetime
    today = datetime.now(IST_TIMEZONE).date()
    try:
        ensure_koel_table()
        all_leads   = get_koel_leads(seg=seg)  # fetch all, filter by follow_up_date below
        today_leads = [l for l in all_leads if _follow_up_is_today(l.get("follow_up_date", ""), today)]
        pending     = [l for l in today_leads if l.get("call_status") == "pending"]
        in_campaign = [l for l in today_leads if l.get("call_status") == "in_campaign"]
        return {"success": True, "today": today.isoformat(), "pending": len(pending), "in_campaign": len(in_campaign), "total": len(today_leads)}
    except Exception as e:
        return {"success": False, "error": str(e), "pending": 0, "total": 0}


@app.post("/api/campaign/start-koel-today")
async def campaign_start_koel_today(request: Request):
    """Auto-sync today's Koel follow-up leads and start a campaign for pending ones."""
    from koel_leads import sync_koel_leads, get_koel_leads, ensure_koel_table, update_koel_call_status
    from datetime import datetime
    try:
        body = await request.json()
        seg  = body.get("seg", "MM")
        today_dt = datetime.now(IST_TIMEZONE).date()
        today    = today_dt.isoformat()

        ensure_koel_table()

        # Smart sync: hit Koel API only when needed
        # Filter by follow_up_date = today (not sdate/edate which is the sync date)
        all_leads   = get_koel_leads(seg=seg)
        today_leads = [l for l in all_leads if _follow_up_is_today(l.get("follow_up_date", ""), today_dt)]
        has_pending     = any(l.get("call_status") == "pending"     for l in today_leads)
        has_in_campaign = any(l.get("call_status") == "in_campaign" for l in today_leads)

        if not today_leads or (not has_pending and not has_in_campaign):
            sync_result = sync_koel_leads(today, today, seg)
            all_leads   = get_koel_leads(seg=seg)
            today_leads = [l for l in all_leads if _follow_up_is_today(l.get("follow_up_date", ""), today_dt)]
        else:
            sync_result = {"total": len(today_leads), "skipped": "leads already in DB"}

        pending = [l for l in today_leads if l.get("call_status") == "pending"]

        if not pending:
            return {
                "success": False,
                "error": f"No pending leads for today ({today}). {len(all_leads)} leads in DB (already called or in campaign)."
            }

        def _koel_machine_type(genset_type: str) -> str:
            return "Genset" if (genset_type or "").strip().upper() == "PG" else "Machine"

        campaign_leads = []
        for lead in pending:
            phone = (lead.get("contact_no") or "").strip()
            if not phone or len("".join(filter(str.isdigit, phone))) < 10:
                continue
            _name = (lead.get("customer_name") or lead.get("account_name") or "Customer").strip()
            _mtype = _koel_machine_type(lead.get("genset_type"))
            _rating = (lead.get("rating") or "").strip()
            campaign_leads.append({
                "phone_number": phone,
                "name": _name,
                "lead_data": {
                    "flow_type":       "KOEL_FOLLOWUP",
                    "customer_name":   _name,
                    "account_name":    (lead.get("account_name") or _name).strip(),
                    "machine_type":    _mtype,
                    "dg_capacity":     f"{_rating} KVA" if _rating else "—",
                    "model_number":    (lead.get("model_number") or "—").strip(),
                    "koel_status":     (lead.get("koel_status") or "—").strip(),
                    "helpline_number": "+91 8130102683",
                    "docket_id":       lead.get("docket_id"),
                    "segment":         lead.get("segment"),
                    "warranty_expiry": lead.get("warranty_expiry") or "—",
                    "follow_up_date":  lead.get("follow_up_date"),
                }
            })

        if not campaign_leads:
            return {"success": False, "error": "No leads with valid phone numbers found for today."}

        campaign_name_str = f"Koel Follow-Up {today} ({seg})"

        # Mark leads as "in_campaign" so pending count drops immediately
        try:
            for lead in campaign_leads:
                did = lead["lead_data"].get("docket_id")
                if did:
                    update_koel_call_status(did, "in_campaign", campaign_name=campaign_name_str)
        except Exception as _qe:
            print(f"[Koel] in_campaign-mark failed: {_qe}")

        result = await campaign_manager.start(
            leads=campaign_leads,
            name=campaign_name_str,
            filters={},
            delay_seconds=30,
            max_concurrent=2,
        )
        if result.get("success"):
            result["synced"]        = sync_result["total"]
            result["pending_leads"] = len(campaign_leads)
        return result
    except Exception as e:
        print(f"[Koel Campaign] Error: {e}")
        return {"success": False, "error": str(e)}


# ==================== DATABASE API ENDPOINTS ====================


# =============================================================================
# FABER LEAD FILES — Excel upload / history / working copy / download
# =============================================================================
# The pristine uploaded .xlsx is preserved on disk; the editable working copy
# lives in the DB (lead_file_rows). See src/lead_files.py.

@app.post("/api/lead-files/upload")
async def lead_files_upload(file: UploadFile = File(...), uploaded_by: str = Form(None)):
    """Upload an Excel calling-list. Saves the pristine original + imports rows."""
    try:
        name = file.filename or "upload.xlsx"
        if not name.lower().endswith((".xlsx", ".xls")):
            return {"success": False, "error": "Please upload an .xlsx file"}
        content = await file.read()
        rec = await asyncio.to_thread(lead_files_mod.save_and_import, content, name, uploaded_by)
        return {"success": True, "file": rec}
    except Exception as e:
        print(f"❌ lead-files upload error: {e}")
        return {"success": False, "error": str(e)}


@app.get("/api/lead-files")
async def lead_files_list():
    """List uploaded files (history), newest first."""
    try:
        files = await asyncio.to_thread(lead_files_mod.list_files)
        return {"success": True, "files": files, "count": len(files)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.delete("/api/lead-files/{file_id}")
async def lead_files_delete(file_id: int):
    """Soft-delete a file (active=FALSE) — removes it from the upload-history
    dropdown but keeps campaign history, Excel downloads, and all row data intact."""
    try:
        f = await asyncio.to_thread(lead_files_mod.get_file, file_id)
        ok = await asyncio.to_thread(lead_files_mod.soft_delete_file, file_id)
        if not ok:
            return {"success": False, "error": "File not found"}
        _label = lead_files_mod.file_label(f)
        print(f"🗑  Calling list deleted: {_label}  (kept in DB — file #{file_id}, hidden from dropdown)")
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/lead-files/{file_id}/rows")
async def lead_files_rows(file_id: int):
    """Rows (working copy) for a file."""
    try:
        f = await asyncio.to_thread(lead_files_mod.get_file, file_id)
        if not f:
            return {"success": False, "error": "File not found"}
        rows = await asyncio.to_thread(lead_files_mod.get_rows, file_id)
        return {"success": True, "file": f, "rows": rows, "count": len(rows)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.patch("/api/lead-files/rows/{row_id}")
async def lead_files_update_row(row_id: int, request: Request):
    """Inline edit of a single row (only editable fields are applied)."""
    try:
        fields = await request.json()
        updated = await asyncio.to_thread(lead_files_mod.update_row, row_id, fields)
        if not updated:
            return {"success": False, "error": "Row not found"}
        return {"success": True, "row": updated}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/lead-files/{file_id}/download")
async def lead_files_download(file_id: int, version: str = "updated", filename: str = None):
    """Download the file. version=original → pristine upload; version=updated → working copy.

    Optional `filename` overrides the download name (campaigns use it to name the
    file after the campaign). Invalid filename chars (/ : * ? etc.) are sanitized.
    """
    try:
        if version == "original":
            res = await asyncio.to_thread(lead_files_mod.original_path, file_id)
            if not res:
                return {"success": False, "error": "Original file not found"}
            path, default_name = res
            return FileResponse(
                path,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                filename=filename_override(filename, default_name),
            )
        # updated working copy → build a fresh xlsx
        res = await asyncio.to_thread(lead_files_mod.export_updated_xlsx, file_id)
        if not res:
            return {"success": False, "error": "File not found"}
        data, default_name = res
        out_name = filename_override(filename, default_name)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{out_name}"'},
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


def filename_override(requested: str, default_name: str) -> str:
    """Sanitize a requested download filename; fall back to the default."""
    if not requested:
        return default_name
    # Strip filesystem-invalid chars AND control chars (\x00-\x1f incl. CR/LF/tab)
    # — the latter would otherwise allow HTTP header injection via Content-Disposition.
    safe = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', '-', requested).strip()
    if not safe:
        return default_name
    if not safe.lower().endswith(".xlsx"):
        safe += ".xlsx"
    return safe


@app.get("/api/export")
async def export_data_endpoint(start_date: str = None, end_date: str = None):
    """
    Format data for the frontend dashboard.
    Combines calls, leads, analytics, and transcripts.
    """
    try:
        # Get all calls (filtered by date) — last 500, newest first
        calls = db.get_all_calls(limit=500, start_date=start_date, end_date=end_date)
        
        # Format sessions for frontend
        sessions = []
        for call in calls:
             # Try to find associated lead info if available
            lead_info = {}
            if call.get('phone_number'):
                lead_data = db.get_lead_by_phone(call['phone_number'])
                if lead_data:
                    # Parse the JSON stored in lead_data column if it exists
                    # `leads` table has `lead_data` as TEXT (JSON)
                    import json
                    try:
                        raw_data = json.loads(lead_data['lead_data'])
                        lead_info = raw_data
                    except:
                        pass

            # Fix timestamps for JS — psycopg2 returns datetime objects, convert to ISO string first
            import datetime as _dt
            def _ts(val):
                if val is None:
                    return None
                if isinstance(val, (_dt.datetime, _dt.date)):
                    val = val.isoformat()
                if val.endswith('+00:00'):
                    return val.replace('+00:00', 'Z')
                if not val.endswith('Z') and '+' not in val[-6:] and val[-6:].count('-') == 0:
                    return val + 'Z'
                return val

            started_at = _ts(call.get('call_initiated_at'))
            ended_at   = _ts(call.get('call_ended_at'))

            # Use recording_duration_seconds as fallback for duration if call_duration_seconds is not available
            call_duration = call.get('call_duration_seconds')
            recording_duration = call.get('recording_duration_seconds')
            effective_duration = call_duration or recording_duration or 0
            
            # Determine call direction based on record_id format
            # Outbound: record_id starts with "000" (Cube format from /make-call)
            # Inbound: record_id is a UUID (WebSocket generated)
            record_id = call.get('record_id', '')
            if record_id.startswith('000'):
                call_direction = "Outbound"
            else:
                call_direction = "Inbound"

            # Fetch legacy lead_file_rows only if calls table has no analysis data
            _lf_row = None
            if not call.get('installation_status') and not call.get('disposition'):
                _lf_row = lead_files_mod.get_row_by_record(record_id) if record_id else None

            sessions.append({
                "session_id": record_id,
                "phone_number": call.get('phone_number'),
                "caller_name": call.get('customer_name') or lead_info.get('name'),
                "call_direction": call_direction,
                "started_at": started_at,
                "ended_at": ended_at,
                "duration_seconds": effective_duration,
                "status": call.get('call_status'),
                # Raw Status string Cube sent for the not-connected branch (e.g. "NOANSWER")
                "cube_status_raw": call.get('cube_status_raw'),
                "recording_url": call.get('recording_url'),
                "recording_duration_seconds": recording_duration,
                "firm_name": lead_info.get('firm_name') or call.get('company_name'),
                "rating": lead_info.get('rating'),
                "business_vertical": lead_info.get('business_vertical'),
                # Set when this call was fired by an automated campaign (drives the "Campaign" badge)
                "campaign_db_id": call.get('campaign_db_id'),
                # Post-call analysis — calls table first (new), fall back to lead_file_rows (legacy)
                "installation_status": call.get('installation_status') or (_lf_row or {}).get('installation_status'),
                "disposition": call.get('disposition') or (_lf_row or {}).get('disposition'),
            })

            
        # Fetch transcripts from database — keep in sync with the 500-call limit
        transcripts = db.get_all_transcripts(limit=500, start_date=start_date, end_date=end_date)
        print(f"📝 Fetched {len(transcripts)} transcripts for export")
        
        stats = db.get_call_stats(start_date=start_date, end_date=end_date)
        
        # Calculate summary for frontend
        total_calls = len(sessions)
        completed_calls = sum(1 for s in sessions if s.get('status') == 'completed')
        failed_calls = sum(1 for s in sessions if s.get('status') == 'failed')
        total_duration = sum(s.get('duration_seconds', 0) or 0 for s in sessions)
        # Average over calls that actually have a duration (i.e. connected),
        # not over total_calls — otherwise not-connected calls (duration=0)
        # dilute the average and it no longer reflects how long calls last.
        connected_durations = [s.get('duration_seconds', 0) or 0 for s in sessions if (s.get('duration_seconds') or 0) > 0]
        avg_duration = sum(connected_durations) / len(connected_durations) if connected_durations else 0
        
        # Count calls by status
        calls_by_status = {}
        for s in sessions:
            status = s.get('status', 'unknown')
            calls_by_status[status] = calls_by_status.get(status, 0) + 1
        
        # Count calls by direction
        calls_by_direction = {
            'Outbound': sum(1 for s in sessions if s.get('call_direction') == 'Outbound'),
            'Inbound': sum(1 for s in sessions if s.get('call_direction') != 'Outbound')
        }
        
        # Get unique callers
        unique_callers = len(set(s.get('phone_number') for s in sessions if s.get('phone_number')))
        
        return {
            "success": True,
            "data": {
                "call_sessions": sessions,
                "transcripts": transcripts,
                "total_call_sessions": len(sessions),
                "total_transcripts": len(transcripts),
                "analytics": {
                     "total_calls": stats['total_calls'],
                     "avg_duration": stats['average_duration_seconds'],
                     "total_customers": stats['total_calls'], # approximation
                     "success_rate": round((completed_calls / total_calls * 100) if total_calls > 0 else 0, 1)
                }
            },
            "summary": {
                "total_calls": total_calls,
                "completed_calls": completed_calls,
                "failed_calls": failed_calls,
                "inbound_calls": calls_by_direction.get('Inbound', 0),
                "outbound_calls": calls_by_direction.get('Outbound', 0),
                "unique_callers": unique_callers,
                "avg_duration_seconds": round(avg_duration, 2),
                "total_duration_seconds": total_duration,
                "calls_by_status": calls_by_status,
                "calls_by_direction": calls_by_direction
            }
        }
    except Exception as e:
        print(f"❌ Export API Error: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}



@app.get("/api/calls")
async def get_calls_endpoint(limit: int = 50, offset: int = 0):
    """Get all calls with pagination."""
    try:
        calls = db.get_all_calls(limit=limit, offset=offset)
        return {"success": True, "calls": calls, "count": len(calls)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/calls/recent")
async def get_recent_calls_endpoint(limit: int = 10):
    """Get most recent calls."""
    try:
        calls = db.get_recent_calls(limit=limit)
        return {"success": True, "calls": calls, "count": len(calls)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/calls/{record_id}")
async def get_call_details_endpoint(record_id: str):
    """Get detailed information about a specific call."""
    try:
        call = db.get_call_by_record_id(record_id)
        if not call:
            return {"success": False, "error": "Call not found"}
        
        # Get conversation for this call
        conversation = db.get_conversation(record_id)
        
        return {
            "success": True,
            "call": call,
            "conversation": conversation
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/calls/{record_id}/conversation")
async def get_conversation_endpoint(record_id: str):
    """Get conversation history for a specific call."""
    try:
        conversation = db.get_conversation(record_id)
        return {"success": True, "conversation": conversation, "count": len(conversation)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/stats")
async def get_stats_endpoint():
    """Get overall call statistics."""
    try:
        stats = db.get_call_stats()
        return {"success": True, "stats": stats}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/search")
async def search_calls_endpoint(phone: str = None, name: str = None):
    """Search calls by phone number or customer name."""
    try:
        calls = db.search_calls(phone_number=phone, customer_name=name)
        return {"success": True, "calls": calls, "count": len(calls)}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# CAMPAIGN ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/campaign/start")
async def campaign_start(request: Request):
    """
    Start an automated outbound calling campaign.

    Body:
    {
        "name": "April Fresh Leads",
        "leads": [ { "name": "...", "phone_number": "...", "details": {} }, ... ],
        "delay_seconds": 30,
        "max_concurrent": 2,
        "filters": {}
    }
    """
    try:
        body           = await request.json()
        leads          = body.get("leads", [])
        lead_file_id   = body.get("lead_file_id")
        name           = body.get("name", f"Campaign {datetime.now().strftime('%d %b %Y %H:%M')}")
        delay_seconds  = int(body.get("delay_seconds", 30))
        max_concurrent = int(body.get("max_concurrent", 2))
        filters        = body.get("filters", {})

        # Preferred path: source leads from an uploaded Faber Excel (lead_file).
        # Each row carries lead_file_row_id so the existing post-call writeback
        # pipeline links results back to that exact row (same as a manual Leads-page call).
        if lead_file_id and not leads:
            file_rows = await asyncio.to_thread(lead_files_mod.get_rows, int(lead_file_id))
            leads = [
                {
                    "name":         row.get("customer_name") or "Customer",
                    "phone_number": row.get("mobile") or "",
                    "details": {
                        "flow_type":        "SWARA_SALE_ANNOUNCEMENT",
                        "customer_name":    row.get("customer_name") or "",
                        "lead_file_row_id": row.get("id"),
                    },
                }
                for row in file_rows
            ]
            filters = {**filters, "lead_file_id": int(lead_file_id)}

        if not leads:
            return {"success": False, "error": "No leads provided (send 'leads' or 'lead_file_id')."}

        # Clamp to safe values
        delay_seconds  = max(90, min(delay_seconds, 180))
        max_concurrent = max(2, min(max_concurrent, 4))

        retry_on_busy       = bool(body.get("retry_on_busy",       True))
        retry_on_no_answer  = bool(body.get("retry_on_no_answer",  True))
        retry_delay_seconds = int(body.get("retry_delay_seconds",  600))
        retry_delay_seconds = max(60, min(retry_delay_seconds, 7200))

        result = await campaign_manager.start(
            leads=leads,
            name=name,
            filters=filters,
            delay_seconds=delay_seconds,
            max_concurrent=max_concurrent,
            retry_on_busy=retry_on_busy,
            retry_on_no_answer=retry_on_no_answer,
            retry_delay_seconds=retry_delay_seconds,
        )
        return result
    except Exception as e:
        print(f"❌ /api/campaign/start error: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/campaign/pause")
async def campaign_pause(campaign_id: int = None):
    """Pause a running campaign. Omit campaign_id to target the active one."""
    return campaign_manager.pause(campaign_id)


@app.post("/api/campaign/resume")
async def campaign_resume(campaign_id: int = None):
    """Resume a paused campaign."""
    return campaign_manager.resume(campaign_id)


@app.post("/api/campaign/stop")
async def campaign_stop(campaign_id: int = None):
    """Stop a campaign. Omit campaign_id to target the active one."""
    result = campaign_manager.stop(campaign_id)
    # Reset any "in_campaign" leads that weren't called → back to pending so they can be retried
    try:
        from datetime import datetime
        from database import _execute
        _execute(
            "UPDATE koel_followup_leads SET call_status = 'pending', campaign_name = NULL WHERE call_status = 'in_campaign' AND sdate = %s",
            (datetime.now(IST_TIMEZONE).date().isoformat(),)
        )
        print("[Koel] in_campaign leads reset to pending after campaign stop")
    except Exception as _re:
        print(f"[Koel] Reset-on-stop failed: {_re}")
    return result


@app.get("/api/campaign/status")
async def campaign_status(campaign_id: int = None):
    """Return live progress. Pass campaign_id for a specific campaign."""
    return {"success": True, **campaign_manager.get_status(campaign_id)}


@app.get("/api/campaign/all")
async def campaign_all_status():
    """Return status of every campaign (active, pending, completed)."""
    return {"success": True, "campaigns": campaign_manager.get_all_status()}


@app.post("/api/campaign/add-lead")
async def campaign_add_lead(request: Request):
    """
    Add a single lead to the currently running/paused campaign.

    Body:
    {
        "phone_number": "9876543210",
        "name": "Ramesh Kumar",
        "lead_data": { "product_name": "KirloStar DG", "price": "45000" }
    }
    """
    try:
        body = await request.json()
        if not body.get("phone_number"):
            return {"success": False, "error": "phone_number is required"}
        result = await campaign_manager.add_lead(body)
        return result
    except Exception as e:
        print(f"❌ /api/campaign/add-lead error: {e}")
        return {"success": False, "error": str(e)}


@app.get("/api/campaign/history")
async def campaign_history(limit: int = 20):
    """Return past campaign runs from the database."""
    try:
        history = db.get_campaign_history(limit=limit)
        return {"success": True, "campaigns": history, "count": len(history)}
    except Exception as e:
        print(f"❌ /api/campaign/history error: {e}")
        return {"success": False, "error": str(e)}


@app.get("/api/campaign/{campaign_id}/leads")
async def campaign_leads_detail(campaign_id: int):
    """Return per-lead log — in-memory first, DB fallback after restart."""
    mgr = campaign_manager._campaigns.get(campaign_id)
    if mgr:
        return {"success": True, "campaign_id": campaign_id,
                "campaign_name": mgr.campaign_name, "leads": mgr.get_leads_log()}
    # Fallback: load from DB
    try:
        rows = db.get_campaign_leads(campaign_id)
        if not rows:
            return {"success": False, "error": "Campaign not found", "leads": []}
        campaign = db.get_campaign(campaign_id)
        leads = [
            {
                "index":             i + 1,
                "name":              r.get("name", ""),
                "phone":             r.get("phone", ""),
                "status":            r.get("status", ""),
                "outcome":           r.get("outcome", ""),
                "conclusion":        r.get("conclusion", ""),
                "attempt":           r.get("attempt", 0),
                "call_started_at":   str(r["call_started_at"]) if r.get("call_started_at") else None,
                "call_completed_at": str(r["call_completed_at"]) if r.get("call_completed_at") else None,
                "error":             r.get("error"),
            }
            for i, r in enumerate(rows)
        ]
        return {"success": True, "campaign_id": campaign_id,
                "campaign_name": campaign.get("name", "") if campaign else "",
                "leads": leads}
    except Exception as e:
        return {"success": False, "error": str(e), "leads": []}


@app.get("/api/campaign/{campaign_id}/leads-rich")
async def campaign_leads_rich(campaign_id: int):
    """Campaign leads joined to their rich Excel row + live post-call outcome.

    Powers the Leads-page-style campaign table: product/dealer/asc from the
    uploaded Excel, plus disposition/installation_status/sentiment/call_status
    that post-call analysis writes back to lead_file_rows as each call finishes.
    """
    try:
        rows = await asyncio.to_thread(db.get_campaign_leads_enriched, campaign_id)
        campaign = await asyncio.to_thread(db.get_campaign, campaign_id)
        leads = [
            {
                "index":               i + 1,
                "name":                r.get("customer_name") or r.get("name") or "",
                "phone":               r.get("phone", ""),
                "attempt":             r.get("attempt", 0),
                "dispatch_status":     r.get("dispatch_status", ""),
                "record_id":           r.get("record_id"),
                "product_name":        r.get("product_name"),
                "dealer_name":         r.get("dealer_name"),
                "service_request_number": r.get("service_request_number"),
                "asc_name":            r.get("asc_name"),
                "remarks":             r.get("remarks"),
                "installation_status": r.get("installation_status"),
                "disposition":         r.get("disposition"),
                "sentiment":           r.get("sentiment"),
                "call_status":         r.get("row_call_status"),
                "error":               r.get("error"),
            }
            for i, r in enumerate(rows)
        ]
        return {"success": True, "campaign_id": campaign_id,
                "campaign_name": campaign.get("name", "") if campaign else "",
                "leads": leads}
    except Exception as e:
        print(f"❌ /api/campaign/{campaign_id}/leads-rich error: {e}")
        return {"success": False, "error": str(e), "leads": []}


@app.get("/api/campaign/{campaign_id}/report.csv")
async def campaign_report_csv(campaign_id: int):
    """Download CSV report — in-memory first, DB fallback after restart."""
    from fastapi.responses import StreamingResponse, PlainTextResponse
    import csv, io

    mgr = campaign_manager._campaigns.get(campaign_id)
    if mgr:
        log = mgr.get_leads_log()
        campaign_name = mgr.campaign_name
    else:
        # Fallback: load from DB
        try:
            rows = db.get_campaign_leads(campaign_id)
            campaign = db.get_campaign(campaign_id)
            if not rows and not campaign:
                return PlainTextResponse("Campaign not found", status_code=404)
            campaign_name = campaign.get("name", f"campaign_{campaign_id}") if campaign else f"campaign_{campaign_id}"
            log = [
                {
                    "index":             i + 1,
                    "name":              r.get("name", ""),
                    "phone":             r.get("phone", ""),
                    "status":            r.get("status", ""),
                    "outcome":           r.get("outcome", ""),
                    "conclusion":        r.get("conclusion", ""),
                    "attempt":           r.get("attempt", 0),
                    "call_started_at":   str(r["call_started_at"]) if r.get("call_started_at") else "",
                    "call_completed_at": str(r["call_completed_at"]) if r.get("call_completed_at") else "",
                    "error":             r.get("error") or "",
                }
                for i, r in enumerate(rows)
            ]
        except Exception as e:
            return PlainTextResponse(f"Error loading campaign: {e}", status_code=500)

    output = io.StringIO()
    fields = ["index", "name", "phone", "status", "outcome", "conclusion", "attempt", "call_started_at", "call_completed_at", "error"]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(log)
    output.seek(0)
    safe_name = campaign_name.replace(" ", "_").replace("/", "-")[:50]
    filename  = f"campaign_{campaign_id}_{safe_name}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


if __name__ == "__main__":
    print("🔥 Starting AI Voice Assistant Server with Cube VoIP + Azure STT...")
    print(f"📞 Cube DID: {CUBE_DID}")
    print(f"🌐 Cube Click2Call URL: {CUBE_CLICK2CALL_URL}")
    print(f"🎯 Cube Campaign ID: {CUBE_CAMPAIGN_ID}")
    print(f"🔌 WebSocket Endpoint: ws://your-server:{CUBE_WEBSOCKET_PORT}/swara_voicebot")
    print("🤖 Function Calling: ✅ ENABLED")
    print(f"🏥 Available Functions: {', '.join(FUNCTION_MAPPING.keys())}")
    print("⚡ Instant Acknowledgments: ✅ ENABLED - Location Queries Only")
    print("🎤 STT Provider: ✅ Azure Speech (Hindi + English India)")
    print("📝 Utterance Buffer: ✅ ENABLED (prevents duplicate LLM calls)")
    print("   └─ Mode: IMMEDIATE (no delay)")
    print("   └─ Cancel on New: Yes (cancels pending LLM if user speaks again)")
    print("   └─ Combines: Cancelled utterances into one")
    print("🌊 LLM Streaming: ✅ ENABLED - Real-time response generation")
    print(f"🎵 TTS Provider: ✅ Azure TTS — voice: {AZURE_TTS_VOICE} | region: {AZURE_SPEECH_REGION}")
    print(f"🎵 Audio Format: PCM {CUBE_SAMPLE_RATE}Hz, {CUBE_BIT_DEPTH}-bit, {CUBE_CHANNELS} channel")
    print(f"📦 Chunk Size: {CUBE_CHUNK_SIZE} bytes ({int(CUBE_CHUNK_DELAY * 1000)}ms)")
    print("🚀 Parallel Execution: ✅ ENABLED - Multiple functions run simultaneously")
    print("⚡ Latency Optimizations: ✅ ACTIVE - Reduced response times by 50-70%")
    print(f"🛑 Interruption Handling: {'✅ ENABLED - Natural conversation flow' if InterruptionConfig.ENABLED else '❌ DISABLED'}")
    if InterruptionConfig.ENABLED:
        print(f"   └─ Min Speech Length: {InterruptionConfig.MIN_SPEECH_LENGTH} words")
        print(f"   └─ Sarvam VAD-based: Yes")
        print(f"   └─ VAD Fallback: {'Yes' if VADConfig.ENABLED else 'No'}")
    print(f"🎤 VAD (Voice Activity Detection): {'✅ ENABLED - Instant interruptions (<100ms)' if VADConfig.ENABLED else '❌ DISABLED'}")
    if VADConfig.ENABLED:
        if VADConfig.USE_VAD_SERVICE:
            print(f"   └─ Mode: 🧠 SILERO VAD SERVICE (High accuracy)")
            print(f"   └─ Service URL: {VADConfig.VAD_SERVICE_URL}")
            print(f"   └─ Speech Threshold: {VADConfig.SPEECH_THRESHOLD}")
        else:
            print(f"   └─ Mode: ⚡ ENERGY-BASED (Fast, less accurate)")
            print(f"   └─ Energy Threshold: {VADConfig.ENERGY_THRESHOLD}")
            print(f"   └─ Detection Speed: ~{VADConfig.MIN_CHUNKS_ABOVE_THRESHOLD * 20}ms")
            print(f"   └─ Noise Gate: {VADConfig.NOISE_GATE}")
        print(f"   └─ Single-Trigger-Per-TTS: {'Yes (echo prevention)' if VADConfig.SINGLE_TRIGGER_PER_TTS else 'No'}")
    print("🔧 Cube Binary Protocol: ✅ ENABLED")
    print(f"   └─ Audio: 0x{CUBE_MSG_AUDIO:02X} | Hangup: 0x{CUBE_MSG_HANGUP:02X} | CLI/DNI: 0x{CUBE_MSG_CLI_DNI:02X} | DTMF: 0x{CUBE_MSG_DTMF:02X}")
    
    # Performance optimizations info
    print("\n⚡ Performance Optimizations:")
    print(f"   └─ TTS Workers: {optimal_tts_workers} (auto-scaled)")
    print(f"   └─ Cache TTL: {response_cache.ttl}s (1 hour)")
    print(f"   └─ Connection Pool: {50} total, {10} per host")
    print(f"   └─ VAD Buffer: deque-based (auto-sized)")
    print(f"   └─ Metrics: ✅ ENABLED\n")

    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        print("🪟 Windows optimizations applied (ProactorEventLoopPolicy for Cube)")
        
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=CUBE_WEBSOCKET_PORT,
        workers=1,
        access_log=False,
        log_level="info",
        reload=False,
        use_colors=True
    )  
