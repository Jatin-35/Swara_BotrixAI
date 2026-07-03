"""
Campaign Manager — automated outbound calling engine.

Single active campaign at a time.  Pure asyncio, no Celery/Redis.
State machine: idle → running ⇄ paused → completed / stopped.
Retry logic: up to 3 attempts with increasing back-off (10 min, 30 min).
Persists progress to Supabase via database.py (best-effort).
"""

import sys, asyncio
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
from datetime import datetime
from typing import Optional, Dict, Any, List, Callable

import database as db

# ── States ────────────────────────────────────────────────────────────────────
IDLE      = "idle"
RUNNING   = "running"
PAUSED    = "paused"
STOPPED   = "stopped"
COMPLETED = "completed"

# ── Retry config ──────────────────────────────────────────────────────────────
MAX_RETRIES  = 3
RETRY_DELAYS = [60, 120, 180]   # seconds: 1 min, 2 min, 3 min


class CampaignManager:

    def __init__(self):
        self.state: str                   = IDLE
        self.leads_queue: asyncio.Queue   = asyncio.Queue()
        self.retry_queue: asyncio.Queue   = asyncio.Queue()

        # Progress counters
        self.total:   int = 0
        self.called:  int = 0
        self.failed:  int = 0
        self.skipped: int = 0

        # Runtime config (set on start)
        self.delay_seconds:  int                      = 30
        self.max_concurrent: int                      = 2
        self._semaphore: Optional[asyncio.Semaphore]  = None

        # Retry config (per campaign)
        self.retry_on_busy:      bool = True
        self.retry_on_no_answer: bool = True
        self.retry_delay_seconds: int = 60    # default 1 min

        # Control events
        self._pause_event: asyncio.Event = asyncio.Event()
        self._pause_event.set()          # set = NOT paused
        self._stop_event:  asyncio.Event = asyncio.Event()

        # Background tasks
        self._worker_task:  Optional[asyncio.Task] = None
        self._retry_tasks:  List[asyncio.Task]     = []
        self._generation:   int                    = 0   # incremented on each reset

        # Metadata
        self.current_lead:  Optional[Dict] = None
        self.started_at:    Optional[str]  = None
        self.completed_at:  Optional[str]  = None
        self.campaign_id:   Optional[int]  = None
        self.campaign_name: str            = ""
        self.filters_used:  Dict           = {}

        # Per-lead tracking log
        self._leads_log: List[Dict] = []

        # Injected at startup by streaming_cube.py to avoid circular import
        self._call_fn: Optional[Callable] = None

        # Optional callback: called when a lead permanently fails (all retries exhausted)
        self.on_lead_permanently_failed: Optional[Callable] = None

    # ── Per-lead log helpers ──────────────────────────────────────────────────

    def _log_add(self, lead: Dict):
        _ld = lead.get("details") or lead.get("lead_data") or {}
        entry = {
            "index":             len(self._leads_log) + 1,
            "name":              lead.get("name", "Unknown"),
            "phone":             lead.get("phone_number", ""),
            "status":            "pending",
            "attempt":           lead.get("_attempt", 0),
            "call_started_at":   None,
            "call_completed_at": None,
            "error":             None,
            "record_id":         None,
            "lead_file_row_id":  _ld.get("lead_file_row_id"),
        }
        self._leads_log.append(entry)
        # Persist to DB (best-effort) — written again with final status on _log_update
        if self.campaign_id:
            try:
                db.upsert_campaign_lead(
                    campaign_id=self.campaign_id,
                    phone=entry["phone"],
                    name=entry["name"],
                    attempt=entry["attempt"],
                    status="pending",
                    lead_file_row_id=entry["lead_file_row_id"],
                )
            except Exception as e:
                print(f"⚠️ campaign_lead insert failed (non-critical): {e}")

    def _log_update(self, phone: str, attempt: int, **kwargs):
        for entry in reversed(self._leads_log):
            if entry["phone"] == phone and entry["attempt"] <= attempt:
                entry.update({"attempt": attempt, **kwargs})
                # Persist to DB (best-effort)
                if self.campaign_id:
                    try:
                        db.upsert_campaign_lead(
                            campaign_id=self.campaign_id,
                            phone=phone,
                            name=entry.get("name", ""),
                            attempt=attempt,
                            status=entry.get("status", "pending"),
                            call_started_at=entry.get("call_started_at"),
                            call_completed_at=entry.get("call_completed_at"),
                            error=entry.get("error"),
                            record_id=entry.get("record_id"),
                            lead_file_row_id=entry.get("lead_file_row_id"),
                        )
                    except Exception as e:
                        print(f"⚠️ campaign_lead upsert failed (non-critical): {e}")
                return

    def get_leads_log(self) -> List[Dict]:
        return list(self._leads_log)

    # ── Dependency injection ──────────────────────────────────────────────────

    def set_call_function(self, fn: Callable):
        """Inject make_cube_outbound_call from streaming_cube.py at startup."""
        self._call_fn = fn
        print("[Campaign] call function registered")

    # ── Read-only helpers ─────────────────────────────────────────────────────

    @property
    def remaining(self) -> int:
        return self.leads_queue.qsize() + self.retry_queue.qsize()

    def get_status(self) -> Dict[str, Any]:
        return {
            "state":          self.state,
            "total":          self.total,
            "called":         self.called,
            "failed":         self.failed,
            "skipped":        self.skipped,
            "remaining":      self.remaining,
            "current_lead":   {
                "name":  self.current_lead.get("name", ""),
                "phone": self.current_lead.get("phone_number", ""),
            } if self.current_lead else None,
            "delay_seconds":  self.delay_seconds,
            "max_concurrent": self.max_concurrent,
            "started_at":     self.started_at,
            "completed_at":   self.completed_at,
            "campaign_id":    self.campaign_id,
            "campaign_name":  self.campaign_name,
            "lead_file_id":   (self.filters_used or {}).get("lead_file_id"),
        }

    # ── Public controls ───────────────────────────────────────────────────────

    async def start(
        self,
        leads:               List[Dict],
        name:                str,
        filters:             Dict,
        delay_seconds:       int  = 30,
        max_concurrent:      int  = 2,
        retry_on_busy:       bool = True,
        retry_on_no_answer:  bool = True,
        retry_delay_seconds: int  = 60,
    ) -> Dict[str, Any]:
        """Load leads and start the background worker."""
        if self.state in (RUNNING, PAUSED):
            return {"success": False, "error": f"Campaign already {self.state}. Stop it first."}

        if not self._call_fn:
            return {"success": False, "error": "Call function not initialised — server restart may be needed."}

        if not leads:
            return {"success": False, "error": "No leads provided."}

        self._reset()

        self.delay_seconds       = delay_seconds
        self.max_concurrent      = max_concurrent
        self.campaign_name       = name
        self.filters_used        = filters
        self.retry_on_busy       = retry_on_busy
        self.retry_on_no_answer  = retry_on_no_answer
        self.retry_delay_seconds = retry_delay_seconds
        self._semaphore          = asyncio.Semaphore(max_concurrent)

        # Pre-filter valid leads (skip invalid numbers) so the total is known up-front.
        valid_leads = []
        for lead in leads:
            phone  = lead.get("phone_number", "") or ""
            digits = ''.join(filter(str.isdigit, phone))
            if len(digits) < 10:
                self.skipped += 1
                continue
            valid_leads.append({**lead, "_attempt": 0})
        self.total = len(valid_leads)

        if self.total == 0:
            return {"success": False, "error": "No leads with valid phone numbers found."}

        # Persist the campaign record FIRST so campaign_id is set before any lead
        # is logged — otherwise the pending rows (gated on campaign_id) never reach
        # the DB until they dispatch, and the live campaign table (which reads
        # campaign_leads) would show rows trickling in instead of the full list.
        try:
            self.campaign_id = db.create_campaign(
                name=name,
                filters=filters,
                total=self.total,
                delay_seconds=delay_seconds,
                max_concurrent=max_concurrent,
            )
        except Exception as e:
            print(f"⚠️ Campaign DB create failed (non-critical): {e}")

        # Now queue + log every valid lead (campaign_id is set → pending rows persist).
        for queued in valid_leads:
            await self.leads_queue.put(queued)
            self._log_add(queued)

        self.state      = RUNNING
        self.started_at = datetime.now().isoformat()
        self._pause_event.set()
        self._stop_event.clear()

        self._worker_task = asyncio.create_task(self._worker())

        print(
            f"🚀 Campaign '{name}' started — "
            f"{self.total} leads, delay={delay_seconds}s, concurrency={max_concurrent}"
        )
        return {"success": True, "campaign_id": self.campaign_id, "total": self.total, "skipped": self.skipped}

    def pause(self) -> Dict[str, Any]:
        if self.state != RUNNING:
            return {"success": False, "error": f"Cannot pause — campaign is {self.state}"}
        self._pause_event.clear()
        self.state = PAUSED
        self._sync_progress()
        print("⏸  Campaign paused")
        return {"success": True}

    def resume(self) -> Dict[str, Any]:
        if self.state != PAUSED:
            return {"success": False, "error": f"Cannot resume — campaign is {self.state}"}
        self.state = RUNNING
        self._pause_event.set()
        self._sync_progress()
        print("▶️  Campaign resumed")
        return {"success": True}

    def stop(self) -> Dict[str, Any]:
        if self.state not in (RUNNING, PAUSED):
            return {"success": False, "error": f"Cannot stop — campaign is {self.state}"}
        self._stop_event.set()
        self._pause_event.set()   # unblock worker if paused
        self.state = STOPPED
        self._sync_progress()
        print("⏹  Campaign stopped")
        return {"success": True}

    async def add_lead(self, lead: Dict) -> Dict[str, Any]:
        """Add a single lead to the active campaign queue on the fly."""
        if self.state not in (RUNNING, PAUSED):
            return {"success": False, "error": f"No active campaign — state is {self.state}"}
        phone  = lead.get("phone_number", "") or ""
        digits = ''.join(filter(str.isdigit, phone))
        if len(digits) < 10:
            return {"success": False, "error": f"Invalid phone number: {phone}"}
        queued = {**lead, "_attempt": 0}
        await self.leads_queue.put(queued)
        self._log_add(queued)
        self.total += 1
        self._sync_progress()
        print(f"➕ Lead added to running campaign: {lead.get('name', 'Unknown')} ({phone})")
        return {"success": True, "message": f"Lead added — queue size now {self.leads_queue.qsize()}"}

    # ── Internal reset ────────────────────────────────────────────────────────

    def _reset(self):
        """Tear down any previous run and clear all counters."""
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
        for t in self._retry_tasks:
            if not t.done():
                t.cancel()
        self._retry_tasks.clear()

        self.leads_queue  = asyncio.Queue()
        self.retry_queue  = asyncio.Queue()
        self.total        = 0
        self.called       = 0
        self.failed       = 0
        self.skipped      = 0
        self.current_lead = None
        self.started_at   = None
        self.completed_at = None
        self.campaign_id  = None
        self._leads_log   = []
        self._generation += 1   # invalidates any stale worker from previous run

        self._pause_event = asyncio.Event()
        self._pause_event.set()
        self._stop_event  = asyncio.Event()

    # ── Background worker ─────────────────────────────────────────────────────

    async def _worker(self):
        """Main asyncio loop — fires leads in parallel batches of max_concurrent."""
        my_generation = self._generation
        print(f"👷 Campaign worker started — batch_size={self.max_concurrent}, delay={self.delay_seconds}s")
        try:
            while not self._stop_event.is_set():

                if self._generation != my_generation:
                    print("👷 Stale worker detected — exiting")
                    return

                await self._pause_event.wait()
                if self._stop_event.is_set():
                    break

                # Collect a batch (retry queue has priority over main queue)
                batch = []
                for _ in range(self.max_concurrent):
                    lead = None
                    try:
                        lead = self.retry_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        try:
                            lead = self.leads_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                    if lead is None:
                        break
                    batch.append(lead)

                if not batch:
                    pending = [t for t in self._retry_tasks if not t.done()]
                    if pending:
                        await asyncio.sleep(0.5)
                        continue
                    break  # both queues empty, no pending retries — done

                self.current_lead = batch[0]
                print(f"📦 Firing batch of {len(batch)} call(s)")

                # Fire the whole batch simultaneously
                await asyncio.gather(*[self._dispatch_call(lead) for lead in batch])

                self.current_lead = None
                self._sync_progress()

                # Delay before next batch (skip if nothing left)
                if not self._stop_event.is_set() and self.remaining > 0:
                    await asyncio.sleep(self.delay_seconds)

        except asyncio.CancelledError:
            print("👷 Campaign worker cancelled")
        except Exception as e:
            print(f"❌ Campaign worker error: {e}")
        finally:
            if self.state == RUNNING:
                self.state        = COMPLETED
                self.completed_at = datetime.now().isoformat()
                print(
                    f"✅ Campaign completed — "
                    f"called={self.called}, failed={self.failed}, skipped={self.skipped}"
                )
            self._sync_progress()
            self.current_lead = None

    # ── Call dispatch ─────────────────────────────────────────────────────────

    async def _dispatch_call(self, lead: Dict):
        """Fire a single outbound call and handle success / failure."""
        phone   = lead.get("phone_number", "")
        name    = lead.get("name", "Customer") or "Customer"
        attempt = lead.get("_attempt", 0)

        # Support nested lead_data / details for CRM context
        lead_data = lead.get("details") or lead.get("lead_data") or {}

        print(f"📞 Campaign calling: {name} ({phone}) — attempt {attempt + 1}/{MAX_RETRIES}")
        call_start = datetime.now().isoformat()
        self._log_update(phone, attempt, status="calling", call_started_at=call_start)

        try:
            result = await self._call_fn(
                to_number=phone,
                name=name,
                lead_data=lead_data,
                campaign_db_id=self.campaign_id,
            )

            if result and result.get("success"):
                self.called += 1
                # Capture the Cube record_id so the campaign row can bridge to the
                # real call outcome (disposition/installation_status) that post-call
                # analysis writes to the calls + lead_file_rows tables.
                self._log_update(phone, attempt, status="initiated",
                                 record_id=result.get("record_id"),
                                 call_completed_at=datetime.now().isoformat())
                print(f"✅ Campaign call initiated: {name} ({phone}) — record_id={result.get('record_id')}")
            else:
                error = result.get("error", "unknown") if result else "no response"
                print(f"⚠️  Campaign call failed: {name} ({phone}) — {error}")
                await self._handle_failed_call(lead, attempt, error)

        except Exception as e:
            print(f"❌ Campaign dispatch exception for {phone}: {e}")
            await self._handle_failed_call(lead, attempt, str(e))

    async def _handle_failed_call(self, lead: Dict, attempt: int, error: str):
        """Retry if attempts remain and retry config allows it, else mark failed."""
        phone = lead.get('phone_number', '')

        # Determine failure reason from error string
        err_lower  = (error or '').lower()
        is_busy      = 'busy' in err_lower
        is_no_answer = any(k in err_lower for k in ('no_answer', 'no answer', 'not_connected', 'timeout'))

        # Check if this failure type should be retried
        should_retry = (
            (is_busy      and self.retry_on_busy) or
            (is_no_answer and self.retry_on_no_answer) or
            # generic failure — retry if at least one retry type is enabled
            (not is_busy and not is_no_answer and (self.retry_on_busy or self.retry_on_no_answer))
        )

        if should_retry and attempt < MAX_RETRIES - 1:
            retry_delay = RETRY_DELAYS[attempt] if attempt < len(RETRY_DELAYS) else RETRY_DELAYS[-1]
            print(
                f"🔄 Retry {attempt + 1}/{MAX_RETRIES} scheduled for "
                f"{phone} in {retry_delay}s (reason: {error!r})"
            )
            self._log_update(phone, attempt, status="retry_pending",
                             error=f"retry in {retry_delay}s — {error}",
                             call_completed_at=datetime.now().isoformat())
            task = asyncio.create_task(
                self._delayed_retry(lead, attempt + 1, retry_delay)
            )
            self._retry_tasks.append(task)
        else:
            self.failed += 1
            self._log_update(phone, attempt, status="failed",
                             error=error, call_completed_at=datetime.now().isoformat())
            print(
                f"Permanently failed after {attempt + 1} attempt(s): "
                f"{phone} (retry_on_busy={self.retry_on_busy}, "
                f"retry_on_no_answer={self.retry_on_no_answer}, error={error!r})"
            )
            if self.on_lead_permanently_failed:
                try:
                    self.on_lead_permanently_failed(lead)
                except Exception:
                    pass

    async def _delayed_retry(self, lead: Dict, new_attempt: int, delay: int):
        """Sleep then push lead back into the retry queue."""
        await asyncio.sleep(delay)
        if not self._stop_event.is_set():
            await self.retry_queue.put({**lead, "_attempt": new_attempt})
            print(
                f"🔄 Lead re-queued: {lead.get('phone_number')} "
                f"(attempt {new_attempt + 1})"
            )

    # ── DB sync ───────────────────────────────────────────────────────────────

    def _sync_progress(self):
        """Persist current counters to Supabase (best-effort, never raises)."""
        if not self.campaign_id:
            return
        try:
            db.update_campaign_progress(
                campaign_id=self.campaign_id,
                called=self.called,
                failed=self.failed,
                skipped=self.skipped,
                remaining=self.remaining,
                state=self.state,
            )
        except Exception as e:
            print(f"⚠️ Campaign progress sync failed (non-critical): {e}")


# ── Campaign Registry — max 2 simultaneous campaigns ─────────────────────────
MAX_SIMULTANEOUS_CAMPAIGNS = 2

class CampaignRegistry:
    """
    Manages multiple campaigns. Up to MAX_SIMULTANEOUS_CAMPAIGNS run at once.
    Extra campaigns queue up and auto-start when a slot opens.
    """

    def __init__(self):
        self._campaigns: Dict[int, CampaignManager] = {}
        self._active_ids: List[int]                  = []   # currently running/paused
        self._pending:    List[int]                   = []   # waiting for a slot
        self._next_id:    int                          = 1
        self._call_fn:    Optional[Callable]           = None

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _running_count(self) -> int:
        return sum(
            1 for cid in self._active_ids
            if self._campaigns.get(cid) and
               self._campaigns[cid].state in (RUNNING, PAUSED)
        )

    def _first_active(self) -> Optional['CampaignManager']:
        for cid in self._active_ids:
            mgr = self._campaigns.get(cid)
            if mgr and mgr.state in (RUNNING, PAUSED):
                return mgr
        return None

    # ── Dependency injection ──────────────────────────────────────────────────

    def set_call_function(self, fn: Callable):
        self._call_fn = fn
        for mgr in self._campaigns.values():
            mgr.set_call_function(fn)
        print(f"[Campaign] CampaignRegistry: call function registered")

    # ── Start ─────────────────────────────────────────────────────────────────

    async def start(
        self,
        leads:               List[Dict],
        name:                str,
        filters:             Dict,
        delay_seconds:       int  = 30,
        max_concurrent:      int  = 2,
        retry_on_busy:       bool = True,
        retry_on_no_answer:  bool = True,
        retry_delay_seconds: int  = 60,
    ) -> Dict[str, Any]:
        if not self._call_fn:
            return {"success": False, "error": "Call function not initialised — server restart may be needed."}
        if not leads:
            return {"success": False, "error": "No leads provided."}

        cid = self._next_id
        self._next_id += 1

        mgr = CampaignManager()
        mgr.set_call_function(self._call_fn)
        self._campaigns[cid] = mgr

        start_args = dict(
            leads=leads, name=name, filters=filters,
            delay_seconds=delay_seconds, max_concurrent=max_concurrent,
            retry_on_busy=retry_on_busy, retry_on_no_answer=retry_on_no_answer,
            retry_delay_seconds=retry_delay_seconds,
        )

        # Slot available — start immediately
        if self._running_count() < MAX_SIMULTANEOUS_CAMPAIGNS:
            result = await mgr.start(**start_args)
            if result.get("success"):
                self._active_ids.append(cid)
                asyncio.create_task(self._watch(cid))
            return {**result, "campaign_id": cid, "status": "running"}

        # No slot — queue as pending
        mgr.state = "pending"
        mgr.campaign_name = name
        mgr._pending_start_args = start_args
        self._pending.append(cid)
        running_names = [
            self._campaigns[i].campaign_name
            for i in self._active_ids
            if self._campaigns.get(i) and self._campaigns[i].state in (RUNNING, PAUSED)
        ]
        print(f"⏳ Campaign '{name}' queued as pending (id={cid}). Running: {running_names}")
        return {
            "success": True, "campaign_id": cid, "status": "pending",
            "message": (
                f"Max {MAX_SIMULTANEOUS_CAMPAIGNS} campaigns already running. "
                f"'{name}' queued — will auto-start when a slot opens."
            ),
        }

    async def _watch(self, cid: int):
        """Watch a campaign and free its slot when done, then start next pending."""
        mgr = self._campaigns.get(cid)
        if not mgr:
            return
        while mgr.state in (RUNNING, PAUSED):
            await asyncio.sleep(5)

        # Remove from active list
        if cid in self._active_ids:
            self._active_ids.remove(cid)
        print(f"✅ Campaign {cid} ('{mgr.campaign_name}') ended — state={mgr.state}. "
              f"Slots free: {MAX_SIMULTANEOUS_CAMPAIGNS - self._running_count()}/{MAX_SIMULTANEOUS_CAMPAIGNS}")

        # Auto-start next pending if slot available
        if self._pending and self._running_count() < MAX_SIMULTANEOUS_CAMPAIGNS:
            next_id  = self._pending.pop(0)
            next_mgr = self._campaigns.get(next_id)
            if next_mgr and hasattr(next_mgr, '_pending_start_args'):
                args = next_mgr._pending_start_args
                print(f"▶️  Auto-starting pending campaign {next_id}: '{args['name']}'")
                result = await next_mgr.start(**args)
                if result.get("success"):
                    self._active_ids.append(next_id)
                    asyncio.create_task(self._watch(next_id))

    # ── Controls ──────────────────────────────────────────────────────────────

    def _get_mgr(self, campaign_id: int = None) -> Optional[CampaignManager]:
        if campaign_id:
            return self._campaigns.get(campaign_id)
        return self._first_active()

    def pause(self, campaign_id: int = None) -> Dict[str, Any]:
        mgr = self._get_mgr(campaign_id)
        if not mgr:
            return {"success": False, "error": "No active campaign"}
        return mgr.pause()

    def resume(self, campaign_id: int = None) -> Dict[str, Any]:
        mgr = self._get_mgr(campaign_id)
        if not mgr:
            return {"success": False, "error": "No active campaign"}
        return mgr.resume()

    def stop(self, campaign_id: int = None) -> Dict[str, Any]:
        mgr = self._get_mgr(campaign_id)
        if not mgr:
            return {"success": False, "error": "No active campaign"}
        result = mgr.stop()
        if campaign_id and campaign_id in self._pending:
            self._pending.remove(campaign_id)
            mgr.state = STOPPED
        return result

    async def add_lead(self, lead: Dict, campaign_id: int = None) -> Dict[str, Any]:
        mgr = self._get_mgr(campaign_id)
        if not mgr:
            return {"success": False, "error": "No active campaign — specify campaign_id"}
        return await mgr.add_lead(lead)

    # ── Status ────────────────────────────────────────────────────────────────

    def get_status(self, campaign_id: int = None) -> Dict[str, Any]:
        mgr = self._campaigns.get(campaign_id) if campaign_id else self._first_active()
        base = {
            "active_campaigns":  self._running_count(),
            "max_campaigns":     MAX_SIMULTANEOUS_CAMPAIGNS,
            "pending_campaigns": len(self._pending),
            "active_ids":        [i for i in self._active_ids if self._campaigns.get(i) and self._campaigns[i].state in (RUNNING, PAUSED)],
        }
        if not mgr:
            return {
                "state": IDLE, "total": 0, "called": 0, "failed": 0,
                "skipped": 0, "remaining": 0, "current_lead": None,
                "delay_seconds": 30, "max_concurrent": 2,
                "started_at": None, "completed_at": None,
                "campaign_id": campaign_id, "campaign_name": "",
                **base,
            }
        return {**mgr.get_status(), **base}

    def get_all_status(self) -> List[Dict[str, Any]]:
        result = []
        for cid, mgr in self._campaigns.items():
            s = mgr.get_status()
            s["campaign_id"] = cid
            s["slot_status"] = (
                "running" if cid in self._active_ids else
                "pending" if cid in self._pending else
                mgr.state
            )
            result.append(s)
        return result


# ── Module-level singleton — import this everywhere ───────────────────────────
campaign_manager = CampaignRegistry()

# Backward-compat: keep old name too
campaign_registry = campaign_manager
