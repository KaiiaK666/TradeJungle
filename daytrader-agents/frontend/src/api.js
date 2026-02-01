const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export async function getConfig() {
  const r = await fetch(`${API_BASE}/api/config`);
  return r.json();
}

export async function getState() {
  const r = await fetch(`${API_BASE}/api/state?limit_posts=200&limit_trades=200`);
  return r.json();
}

export async function getPnL() {
  const r = await fetch(`${API_BASE}/api/pnl`);
  return r.json();
}

export async function getResearch() {
  const r = await fetch(`${API_BASE}/api/research`);
  return r.json();
}

export async function getMarkets() {
  const r = await fetch(`${API_BASE}/api/markets`);
  return r.json();
}
