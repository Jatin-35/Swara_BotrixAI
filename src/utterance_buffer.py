"""
Utterance Buffer Module for Voice Bot

This module provides intelligent utterance handling with:
1. Immediate LLM call on first utterance
2. INSTANT cancellation when new speech is detected (even partial/first token)
3. Combining cancelled + new utterances
4. Preventing duplicate/wasted responses

Flow:
1. User says "Hair fall है" → Send to LLM immediately
2. LLM processing... (takes 2-3s)
3. User STARTS speaking (even first word!) → CANCEL LLM instantly!
4. Wait for user to complete: "और बहुत ज्यादा बाल झड़ते हैं"
5. Combine: "Hair fall है और बहुत ज्यादा बाल झड़ते हैं"
6. Send combined to LLM
"""

import asyncio
import time
from typing import Callable, Optional, List
from dataclasses import dataclass


@dataclass
class UtteranceBufferConfig:
    """Configuration for utterance buffering behavior."""
    
    # Minimum words required to process (filters noise)
    min_words: int = 1
    
    # Log detailed debug information
    debug_logging: bool = True


class UtteranceBuffer:
    """
    Handles utterances with immediate LLM calls and INSTANT cancellation.
    
    Key features:
    - Sends to LLM immediately on first utterance
    - Cancels LLM as soon as ANY new speech is detected (even partial!)
    - Waits for complete utterance, then combines
    - Prevents duplicate/wasted responses
    """
    
    def __init__(self, config: Optional[UtteranceBufferConfig] = None):
        self.config = config or UtteranceBufferConfig()
        
        # Pending utterance (for combining if LLM is cancelled)
        self.pending_text: Optional[str] = None
        
        # LLM processing state
        self.pending_llm_task: Optional[asyncio.Task] = None
        self.is_processing: bool = False
        
        # Flag to track if we've cancelled due to new speech starting
        self.cancelled_for_new_speech: bool = False
        
        # Callback storage
        self._process_callback: Optional[Callable] = None
        self._callback_args: tuple = ()
        self._callback_kwargs: dict = {}
        
        # Statistics
        self.total_utterances: int = 0
        self.total_combines: int = 0
        self.total_cancellations: int = 0
    
    def _log(self, message: str):
        if self.config.debug_logging:
            print(message)
    
    def cancel_on_new_speech_detected(self) -> bool:
        """
        Called when PARTIAL/NEW speech is detected (even first token).
        Cancels any pending LLM request immediately.
        
        Returns True if cancellation happened.
        """
        if self.is_processing and self.pending_llm_task and not self.pending_llm_task.done():
            self.pending_llm_task.cancel()
            self.total_cancellations += 1
            self.cancelled_for_new_speech = True
            self._log(f"⚡ INSTANT CANCEL - New speech detected while LLM processing!")
            return True
        return False
    
    async def add_utterance(
        self, 
        text: str, 
        process_callback: Callable,
        *args,
        **kwargs
    ) -> bool:
        """
        Add a complete utterance and process it.
        
        If we previously cancelled due to new speech, this will combine
        the old + new utterances before sending.
        """
        # Validate utterance
        text = text.strip()
        if not text:
            return False
        
        word_count = len(text.split())
        if word_count < self.config.min_words:
            self._log(f"🔇 Utterance too short ({word_count} words): '{text[:30]}...'")
            return False
        
        self.total_utterances += 1
        
        # Store callback info
        self._process_callback = process_callback
        self._callback_args = args
        self._callback_kwargs = kwargs
        
        # DISABLED: Combining was causing issues with unrelated utterances being merged
        # Each utterance is now processed independently
        # The cancel feature still prevents wasted LLM calls
        self.cancelled_for_new_speech = True
        self.pending_text = None
        
        # If still processing (shouldn't happen often), cancel
        if self.is_processing and self.pending_llm_task and not self.pending_llm_task.done():
            self.pending_llm_task.cancel()
            self.total_cancellations += 1
            self._log(f"🔄 Cancelled pending request for new complete utterance")
            
            # Wait for cancellation
            try:
                await asyncio.wait_for(asyncio.shield(self.pending_llm_task), timeout=0.1)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
        
        # Store current text (in case we need to combine later)
        self.pending_text = text
        
        self._log(f"🚀 Processing: '{text[:60]}...'")
        
        # Start LLM processing
        self.is_processing = True
        
        try:
            self.pending_llm_task = asyncio.create_task(
                self._execute_callback(text)
            )
            await self.pending_llm_task
            
            # Successfully completed
            self.pending_text = None
            self.cancelled_for_new_speech = False
            
        except asyncio.CancelledError:
            self._log("⚠️ LLM processing was cancelled (user spoke again)")
            # Keep pending_text for combining with next utterance
        except Exception as e:
            self._log(f"❌ Error in LLM processing: {e}")
            self.pending_text = None
            self.cancelled_for_new_speech = False
        finally:
            self.is_processing = False
            self.pending_llm_task = None
        
        return True
    
    async def _execute_callback(self, text: str):
        """Execute the process callback with text."""
        try:
            await self._process_callback(
                text,
                *self._callback_args,
                **self._callback_kwargs
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._log(f"❌ Error in process callback: {e}")
            raise
    
    def clear(self):
        """Clear the buffer and cancel pending operations."""
        if self.pending_llm_task and not self.pending_llm_task.done():
            self.pending_llm_task.cancel()
        self.pending_text = None
        self.is_processing = False
        self.cancelled_for_new_speech = False
    
    def get_stats(self) -> dict:
        return {
            "total_utterances": self.total_utterances,
            "total_combines": self.total_combines,
            "total_cancellations": self.total_cancellations,
            "is_processing": self.is_processing
        }


def create_utterance_buffer(debug: bool = True) -> UtteranceBuffer:
    """Create an UtteranceBuffer with common settings."""
    config = UtteranceBufferConfig(debug_logging=debug)
    return UtteranceBuffer(config)
