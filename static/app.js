// ── Token management ──────────────────────────────────────────────────────────
const TOKEN_KEY = "mrcp_token";
const API_BASE_URL = (window.MRCP_API_BASE_URL || "").replace(/\/$/, "");

function getToken()       { return localStorage.getItem(TOKEN_KEY); }
function setToken(t)      { localStorage.setItem(TOKEN_KEY, t); }
function removeToken()    { localStorage.removeItem(TOKEN_KEY); }

function requireAuth() {
  if (!getToken()) window.location.href = "/";
}
function logout() {
  removeToken();
  window.location.href = "/";
}

// ── API helper ────────────────────────────────────────────────────────────────
async function api(method, path, body = null, auth = true) {
  const headers = { "Content-Type": "application/json" };
  if (auth) {
    const tok = getToken();
    if (!tok) { window.location.href = "/"; return; }
    headers["Authorization"] = "Bearer " + tok;
  }
  const opts = { method, headers };
  if (body) opts.body = JSON.stringify(body);

  const res = await fetch(API_BASE_URL + path, opts);
  if (res.status === 401 && auth) { removeToken(); window.location.href = "/"; return; }

  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Request failed");
  return data;
}

// ── Alert helpers ─────────────────────────────────────────────────────────────
function showAlert(id, msg, type = "danger") {
  const el = document.getElementById(id);
  if (!el) return;
  el.className = "alert alert-" + type;
  el.textContent = msg;
  el.classList.remove("hidden");
}
function hideAlert(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add("hidden");
}

// ── Formatting helpers ────────────────────────────────────────────────────────
function scoreBadgeClass(score, total) {
  if (!total) return "badge-warning";
  const p = score / total;
  return p >= 0.7 ? "badge-success" : p >= 0.5 ? "badge-warning" : "badge-danger";
}

function formatDate(iso) {
  return new Date(iso).toLocaleString("en-GB", {
    day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

function formatDuration(secs) {
  if (!secs) return "No limit";
  const m = Math.floor(secs / 60), s = secs % 60;
  return m ? `${m}m${s ? " " + s + "s" : ""}` : `${s}s`;
}

function escapeHtml(str) {
  if (!str) return "";
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function gradeLabel(pct) {
  if (pct >= 80) return "Excellent";
  if (pct >= 70) return "Good Pass";
  if (pct >= 60) return "Pass";
  if (pct >= 50) return "Borderline";
  return "Needs Improvement";
}
