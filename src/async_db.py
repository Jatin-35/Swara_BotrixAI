"""
Async Database Logging Wrapper
Makes all DB logging operations non-blocking for better performance
"""
import asyncio
from typing import Optional, Dict, Any

# Import the sync database module
import database as db_sync


class AsyncDatabaseLogger:
    """Async wrapper for database logging operations."""
    
    def __init__(self):
        self.executor = None  # Will use default ThreadPoolExecutor
    
    async def log_console(
        self,
        message: str,
        log_level: str = 'INFO',
        record_id: str = None,
        details: Dict[str, Any] = None
    ):
        """Log console message asynchronously (non-blocking)."""
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                self.executor,
                db_sync.log_console,
                message,
                log_level,
                record_id,
                details
            )
        except Exception as e:
            print(f"⚠️ Async log error (non-critical): {e}")
    
    async def log_conversation(
        self,
        record_id: str,
        speaker: str,
        message: str,
        message_type: str = 'speech',
        metadata: Dict[str, Any] = None
    ):
        """Log conversation message asynchronously (non-blocking)."""
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                self.executor,
                db_sync.log_conversation,
                record_id,
                speaker,
                message,
                message_type,
                metadata
            )
        except Exception as e:
            print(f"⚠️ Async conversation log error: {e}")
    
    async def update_call_status(self, record_id: str, status: str):
        """Update call status asynchronously."""
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                self.executor,
                db_sync.update_call_status,
                record_id,
                status
            )
        except Exception as e:
            print(f"⚠️ Async status update error: {e}")


# Singleton instance
async_db = AsyncDatabaseLogger()


# Convenience function for quick migration
async def log_to_supabase_async(
    message: str,
    level: str = "INFO",
    record_id: str = None,
    details: dict = None
):
    """Async version of log_to_supabase - fire and forget."""
    asyncio.create_task(
        async_db.log_console(message, level, record_id, details)
    )
