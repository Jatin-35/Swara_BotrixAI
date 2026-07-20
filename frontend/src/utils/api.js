const BASE_URL = import.meta.env.VITE_API_URL || "https://apivoiceagentservice-backend.botrixai.com/api";

console.log('📡 API Base URL:', BASE_URL);

export async function fetchExportData(dateFrom, dateTo, campaignId = null, callScope = null) {
  // A selected campaign overrides the date range — one run's data, not a date window.
  // callScope ("campaign" | "normal") narrows a date-range query instead — ignored
  // once campaignId is set, since that already implies "this one campaign's calls".
  let url;
  if (campaignId) {
    url = `${BASE_URL}/export?campaign_id=${campaignId}`;
  } else {
    url = `${BASE_URL}/export?start_date=${dateFrom}&end_date=${dateTo}`;
    if (callScope && callScope !== "both") {
      url += `&call_scope=${callScope}`;
    }
  }

  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }

  return response.json();
}

export async function fetchLeads(date = null) {
  let url = `${BASE_URL}/leads?limit=1000`;
  if (date) {
    url += `&date=${date}`;
  }
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  return response.json();
}

export async function refreshLeads(date = null) {
  const url = `${BASE_URL}/leads/refresh`;
  const body = date ? { date } : {};

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  return response.json();
}


export async function makeCall(phoneNumber, customerName = '', companyName = '', leadData = null) {
  const url = `${BASE_URL.replace(/\/api$/, '')}/api/make-call`;

  console.log('📞 makeCall() called with:', { phoneNumber, customerName, companyName, leadData });
  console.log('📡 Calling URL:', url);

  try {
    const payload = {
      to_number: phoneNumber,
      name: customerName,
      company_name: companyName
    };

    // Add lead_data if provided (for CRM context)
    if (leadData) {
      payload.lead_data = leadData;
      console.log('📊 Including lead data:', leadData);
    }
    console.log('📦 Request payload:', JSON.stringify(payload));

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload)
    });

    console.log('📨 Response status:', response.status, response.statusText);

    if (!response.ok) {
      const errorText = await response.text();
      console.error('❌ API Error Response:', errorText);
      throw new Error(`HTTP error! status: ${response.status} - ${errorText}`);
    }

    const result = await response.json();
    console.log('✅ API Response:', result);
    return result;
  } catch (error) {
    console.error('❌ makeCall() error:', error);
    console.error('   Error name:', error.name);
    console.error('   Error message:', error.message);

    // Check if it's a CORS error
    if (error.name === 'TypeError' && error.message.includes('fetch')) {
      console.error('🚫 Possible CORS error - check browser Network tab for details');
      throw new Error('Network error - possibly CORS blocked. Check console for details.');
    }

    throw error;
  }
}

export function getRecordingUrl(recordingPath) {
  if (!recordingPath) return null;
  // return `${BASE_URL}${recordingPath}`;
  return `${recordingPath}`;

}

export function downloadRecording(recordingUrl, filename = "recording.mp4") {
  const link = document.createElement("a");
  link.href = recordingUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

// ── Faber Lead Files API (Excel upload / history / working copy) ─────────────
// BASE_URL already ends in /api, so endpoints are `${BASE_URL}/lead-files/...`

export async function uploadLeadFile(file, uploadedBy = "") {
  const form = new FormData();
  form.append("file", file);
  if (uploadedBy) form.append("uploaded_by", uploadedBy);
  const res = await fetch(`${BASE_URL}/lead-files/upload`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
  return res.json();
}

export async function listLeadFiles() {
  const res = await fetch(`${BASE_URL}/lead-files`);
  if (!res.ok) throw new Error(`List failed: ${res.status}`);
  return res.json();
}

// Soft-delete: hides the file from the upload-history dropdown (data is preserved)
export async function deleteLeadFile(fileId) {
  const res = await fetch(`${BASE_URL}/lead-files/${fileId}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`Delete failed: ${res.status}`);
  return res.json();
}

export async function getLeadFileRows(fileId) {
  const res = await fetch(`${BASE_URL}/lead-files/${fileId}/rows`);
  if (!res.ok) throw new Error(`Rows failed: ${res.status}`);
  return res.json();
}

export async function updateLeadRow(rowId, fields) {
  const res = await fetch(`${BASE_URL}/lead-files/rows/${rowId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields),
  });
  if (!res.ok) throw new Error(`Update failed: ${res.status}`);
  return res.json();
}

// Returns the direct download URL — open it to download the .xlsx
// Optional `filename` overrides the download name (used by campaigns to name the
// file after the campaign, e.g. "<date> (<day>) <time> - <sheet> updated.xlsx").
export function leadFileDownloadUrl(fileId, version = "updated", filename = null) {
  let url = `${BASE_URL}/lead-files/${fileId}/download?version=${version}`;
  if (filename) url += `&filename=${encodeURIComponent(filename)}`;
  return url;
}

// ── Campaign API ─────────────────────────────────────────────────────────────
const CAMPAIGN_BASE = BASE_URL.replace(/\/api$/, "");

async function campaignFetch(path, method = "GET", body = null) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(`${CAMPAIGN_BASE}${path}`, opts);
  if (!res.ok) throw new Error(`Campaign API error ${res.status}`);
  return res.json();
}

export const campaignStart   = (body) => campaignFetch("/api/campaign/start",    "POST", body);
export const campaignPause   = ()     => campaignFetch("/api/campaign/pause",    "POST");
export const campaignResume  = ()     => campaignFetch("/api/campaign/resume",   "POST");
export const campaignStop    = ()     => campaignFetch("/api/campaign/stop",     "POST");
export const campaignAddLead = (body) => campaignFetch("/api/campaign/add-lead", "POST", body);
export const campaignStatus  = ()     => campaignFetch("/api/campaign/status");
export const campaignHistory = (limit = 200) => campaignFetch(`/api/campaign/history?limit=${limit}`);
export const campaignLeads   = (id)   => campaignFetch(`/api/campaign/${id}/leads`);
export const campaignLeadsRich = (id) => campaignFetch(`/api/campaign/${id}/leads-rich`);
export const campaignReportUrl = (id) => `${CAMPAIGN_BASE}/api/campaign/${id}/report.csv`;

// ── Koel Follow-Up Leads API ──────────────────────────────────────────────────
const KOEL_BASE = BASE_URL.replace(/\/api$/, "");

export const koelSync  = (sdate, edate, seg = "MM") =>
    fetch(`${KOEL_BASE}/api/koel/sync`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sdate, edate, seg }),
    }).then(r => r.json());

export const koelLeads = (sdate, edate, seg) => {
    const params = new URLSearchParams();
    if (sdate) params.set("sdate", sdate);
    if (edate) params.set("edate", edate);
    if (seg)   params.set("seg", seg);
    return fetch(`${KOEL_BASE}/api/koel/leads?${params}`).then(r => r.json());
};

export const koelCallStatus = (docket_id, call_status) =>
    fetch(`${KOEL_BASE}/api/koel/call-status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ docket_id, call_status }),
    }).then(r => r.json());

export const koelTodaySummary = (seg = null) => {
    const params = seg ? `?seg=${seg}` : "";
    return fetch(`${KOEL_BASE}/api/campaign/koel-today-summary${params}`).then(r => r.json());
};

export const campaignStartKoelToday = (seg = "MM") =>
    fetch(`${KOEL_BASE}/api/campaign/start-koel-today`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ seg }),
    }).then(r => r.json());

export const koelInterestedLeads = () =>
    fetch(`${KOEL_BASE}/api/koel/interested-leads`).then(r => r.json());