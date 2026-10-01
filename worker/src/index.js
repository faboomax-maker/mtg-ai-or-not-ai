/* IA ou vraie carte ? — game server (Cloudflare Worker + D1).
 *
 * The public decks (docs/data/*.json) carry no answers: this Worker holds them. It deals a
 * game, reveals each card only once it has been answered, times the answers itself and keeps
 * the top 10 of each mode, also committed to docs/data/leaderboard.json in the repo.
 *
 * Bindings: DB (D1). Secrets: ADMIN_TOKEN (deck uploads from CI), GH_TOKEN (commits the
 * leaderboard file). Vars: GH_REPO ("owner/name"), ALLOWED_ORIGINS (comma-separated).
 */

const ROUND = 20;
const VERDICT_MS = 300;               // the page shows the verdict at least this long before the next card
const GRACE_MS = 2500;                // network and rendering slack on the hardcore timer
const MODES = ["normal", "hardcore"];
const TOP = 10;

/** Hardcore time limit of card i (0-based): from FIRST_MS for the first card down to LAST_MS for
 *  the last (the page uses the same values, docs/app.js). */
const FIRST_MS = 6000, LAST_MS = 6000;   // the same time for every card
function limitMs(i, n) {
  return Math.round(FIRST_MS - (FIRST_MS - LAST_MS) * i / Math.max(1, n - 1));
}

const SCHEMA = [
  "CREATE TABLE IF NOT EXISTS decks (mode TEXT PRIMARY KEY, data TEXT NOT NULL, updated TEXT)",
  "CREATE TABLE IF NOT EXISTS games (id TEXT PRIMARY KEY, mode TEXT, cards TEXT, answers TEXT, " +
    "created INTEGER, submitted INTEGER DEFAULT 0, ip TEXT)",
  "CREATE INDEX IF NOT EXISTS games_ip ON games (ip, created)",
  "CREATE TABLE IF NOT EXISTS scores (id INTEGER PRIMARY KEY AUTOINCREMENT, mode TEXT, name TEXT, " +
    "score INTEGER, total INTEGER, ms INTEGER, at TEXT)",
];
let schemaReady = false;

async function ensureSchema(env) {
  if (schemaReady) return;
  await env.DB.batch(SCHEMA.map((s) => env.DB.prepare(s)));
  schemaReady = true;
}

/* ------------------------------------------------------------------ http */
function cors(req, env) {
  const origin = req.headers.get("Origin") || "";
  const allowed = (env.ALLOWED_ORIGINS || "").split(",").map((s) => s.trim()).filter(Boolean);
  return {
    "Access-Control-Allow-Origin": allowed.includes(origin) ? origin : allowed[0] || "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Vary": "Origin",
  };
}

function json(data, req, env, status = 200) {
  return new Response(JSON.stringify(data), {
    status, headers: { "Content-Type": "application/json; charset=utf-8", ...cors(req, env) },
  });
}

class HttpError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

async function body(req) {
  try { return await req.json(); } catch { throw new HttpError(400, "invalid JSON"); }
}

async function ipHash(req) {
  const ip = req.headers.get("CF-Connecting-IP") || "?";
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode("mtg-quiz:" + ip));
  return [...new Uint8Array(buf).slice(0, 8)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/* ----------------------------------------------------------------- decks */
// decks kept in memory (one query and one JSON parse less per answer); re-read after a minute,
// or at once when a card is missing (a new deck was uploaded meanwhile)
const deckCache = new Map();

async function deckKey(env, mode, img) {
  const hit = deckCache.get(mode);
  if (hit && Date.now() - hit.at < 60000 && (!img || hit.key[img])) return hit.key;
  const row = await env.DB.prepare("SELECT data FROM decks WHERE mode = ?").bind(mode).first();
  if (!row) throw new HttpError(404, "no deck for this mode yet");
  const key = JSON.parse(row.data);     // {img: {real, set, artist, url, art_from}}
  deckCache.set(mode, { key, at: Date.now() });
  return key;
}

function requireAdmin(req, env) {
  const auth = req.headers.get("Authorization") || "";
  if (!env.ADMIN_TOKEN || auth !== "Bearer " + env.ADMIN_TOKEN) throw new HttpError(401, "unauthorized");
}

/** CI: the answers of a mode's deck, to add cards to it. */
async function readDeck(req, env) {
  requireAdmin(req, env);
  const mode = new URL(req.url).searchParams.get("mode");
  if (!MODES.includes(mode)) throw new HttpError(400, "unknown mode");
  const row = await env.DB.prepare("SELECT data FROM decks WHERE mode = ?").bind(mode).first();
  return { mode, key: row ? JSON.parse(row.data) : {} };
}

async function uploadDeck(req, env) {
  requireAdmin(req, env);
  const { mode, key } = await body(req);
  if (!MODES.includes(mode) || !key || typeof key !== "object") throw new HttpError(400, "mode and key required");
  await env.DB.prepare("INSERT OR REPLACE INTO decks (mode, data, updated) VALUES (?, ?, ?)")
    .bind(mode, JSON.stringify(key), new Date().toISOString()).run();
  deckCache.delete(mode);
  return { ok: true, mode, cards: Object.keys(key).length };
}

/* ------------------------------------------------------------------ game */
function shuffle(a) {
  for (let i = a.length - 1; i > 0; i--) {
    const j = crypto.getRandomValues(new Uint32Array(1))[0] % (i + 1);
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

async function start(req, env) {
  const { mode } = await body(req);
  if (!MODES.includes(mode)) throw new HttpError(400, "unknown mode");
  const ip = await ipHash(req);
  const recent = await env.DB.prepare("SELECT COUNT(*) AS n FROM games WHERE ip = ? AND created > ?")
    .bind(ip, Date.now() - 10 * 60 * 1000).first();
  if (recent && recent.n >= 40) throw new HttpError(429, "too many games, try again later");
  const key = await deckKey(env, mode);
  const cards = shuffle(Object.keys(key)).slice(0, ROUND);
  const id = crypto.randomUUID();
  const now = Date.now();
  // old unfinished games are useless after an hour
  await env.DB.batch([
    env.DB.prepare("DELETE FROM games WHERE created < ?").bind(now - 60 * 60 * 1000),
    env.DB.prepare("INSERT INTO games (id, mode, cards, answers, created, ip) VALUES (?, ?, ?, '[]', ?, ?)")
      .bind(id, mode, JSON.stringify(cards), now, ip),
  ]);
  return { game: id, mode, cards, limits: mode === "hardcore" ? cards.map((_, i) => limitMs(i, cards.length)) : null };
}

async function loadGame(env, id) {
  const g = await env.DB.prepare("SELECT * FROM games WHERE id = ?").bind(String(id || "")).first();
  if (!g) throw new HttpError(404, "unknown or expired game");
  return { ...g, cards: JSON.parse(g.cards), answers: JSON.parse(g.answers) };
}

async function answer(req, env) {
  const { game, index, answer } = await body(req);
  if (!["ai", "real", "timeout"].includes(answer)) throw new HttpError(400, "answer must be ai, real or timeout");
  const g = await loadGame(env, game);
  const i = g.answers.length;
  if (index !== i || i >= g.cards.length) throw new HttpError(409, "not the card in play");
  const now = Date.now();
  const shown = i === 0 ? g.created : g.answers[i - 1].t + VERDICT_MS;
  const elapsed = Math.max(0, now - shown);
  const secret = (await deckKey(env, g.mode, g.cards[i]))[g.cards[i]];
  if (!secret) throw new HttpError(410, "this deck was replaced, start a new game");
  const truth = secret.real ? "real" : "ai";
  const late = g.mode === "hardcore" && elapsed > limitMs(i, g.cards.length) + GRACE_MS;
  const ok = answer === truth && !late;
  g.answers.push({ a: answer, ok, t: now, ms: elapsed });
  await env.DB.prepare("UPDATE games SET answers = ? WHERE id = ?").bind(JSON.stringify(g.answers), g.id).run();
  return { index: i, truth, correct: ok, timeout: answer === "timeout" || late, secret };
}

/* ----------------------------------------------------------- leaderboard */
const NAME_RE = /^[\p{L}\p{N} _.'’-]{1,16}$/u;
const BLOCKED = ["nazi", "hitler", "nigger", "nigga", "fuck", "shit", "cunt", "pute", "salope", "connard", "enculé", "pd"];

function cleanName(name) {
  const n = String(name || "").normalize("NFC").replace(/\s+/g, " ").trim();
  if (!NAME_RE.test(n)) throw new HttpError(400, "name: 1 to 16 letters, digits, spaces, _ . ' -");
  const low = n.toLowerCase();
  if (BLOCKED.some((w) => low.split(/[^\p{L}]+/u).includes(w) || (w.length > 4 && low.includes(w)))) {
    throw new HttpError(400, "name not allowed");
  }
  return n;
}

async function top(env, mode) {
  const { results } = await env.DB.prepare(
    "SELECT name, score, total, ms, at FROM scores WHERE mode = ? ORDER BY score DESC, ms ASC, id ASC LIMIT ?"
  ).bind(mode, TOP).all();
  return results;
}

async function leaderboard(env) {
  const out = {};
  for (const m of MODES) out[m] = await top(env, m);
  return out;
}

/** Would this result enter the mode's top 10? */
async function qualifies(env, mode, score, ms) {
  const rows = await top(env, mode);
  if (rows.length < TOP) return true;
  const last = rows[rows.length - 1];
  return score > last.score || (score === last.score && ms < last.ms);
}

async function commitLeaderboard(env, board) {
  if (!env.GH_TOKEN || !env.GH_REPO) return;
  const url = `https://api.github.com/repos/${env.GH_REPO}/contents/docs/data/leaderboard.json`;
  const headers = {
    "Authorization": "Bearer " + env.GH_TOKEN, "Accept": "application/vnd.github+json",
    "User-Agent": "mtg-quiz-worker", "X-GitHub-Api-Version": "2022-11-28",
  };
  const content = JSON.stringify({ updated: new Date().toISOString(), ...board }, null, 2) + "\n";
  const b64 = btoa(String.fromCharCode(...new TextEncoder().encode(content)));
  for (let attempt = 0; attempt < 3; attempt++) {           // another commit may land meanwhile
    const cur = await fetch(url + "?ref=main", { headers });
    const sha = cur.ok ? (await cur.json()).sha : undefined;
    const r = await fetch(url, {
      method: "PUT", headers,
      body: JSON.stringify({ message: "Classement mis à jour", content: b64, sha, branch: "main" }),
    });
    if (r.ok) return;
    if (r.status !== 409 && r.status !== 422) { console.log("leaderboard commit failed", r.status, await r.text()); return; }
  }
}

async function submit(req, env, ctx) {
  const { game, name } = await body(req);
  const g = await loadGame(env, game);
  if (g.submitted) throw new HttpError(409, "already submitted");
  if (g.answers.length < g.cards.length) throw new HttpError(409, "game not finished");
  const player = cleanName(name);
  const score = g.answers.filter((a) => a.ok).length;
  const ms = g.answers.reduce((s, a) => s + Math.min(a.ms, 120000), 0);
  await env.DB.prepare("UPDATE games SET submitted = 1 WHERE id = ?").bind(g.id).run();
  if (!(await qualifies(env, g.mode, score, ms))) {
    return { entered: false, score, total: g.cards.length, ms, leaderboard: await leaderboard(env) };
  }
  const at = new Date().toISOString().slice(0, 10);
  await env.DB.prepare("INSERT INTO scores (mode, name, score, total, ms, at) VALUES (?, ?, ?, ?, ?, ?)")
    .bind(g.mode, player, score, g.cards.length, ms, at).run();
  // only the top 10 is kept
  await env.DB.prepare(
    "DELETE FROM scores WHERE mode = ? AND id NOT IN (SELECT id FROM scores WHERE mode = ? " +
    "ORDER BY score DESC, ms ASC, id ASC LIMIT ?)"
  ).bind(g.mode, g.mode, TOP).run();
  const board = await leaderboard(env);
  ctx.waitUntil(commitLeaderboard(env, board));
  const rank = board[g.mode].findIndex((r) => r.name === player && r.score === score && r.ms === ms) + 1;
  return { entered: rank > 0, rank: rank || null, score, total: g.cards.length, ms, leaderboard: board };
}

/** Result of a finished game (score, time, would it enter the top 10), before asking a name. */
async function result(req, env) {
  const { game } = await body(req);
  const g = await loadGame(env, game);
  if (g.answers.length < g.cards.length) throw new HttpError(409, "game not finished");
  const score = g.answers.filter((a) => a.ok).length;
  const ms = g.answers.reduce((s, a) => s + Math.min(a.ms, 120000), 0);
  return { score, total: g.cards.length, ms, qualifies: !g.submitted && (await qualifies(env, g.mode, score, ms)) };
}

/* ---------------------------------------------------------------- router */
export default {
  async fetch(req, env, ctx) {
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors(req, env) });
    const path = new URL(req.url).pathname;
    try {
      await ensureSchema(env);
      if (req.method === "GET" && path === "/leaderboard") return json(await leaderboard(env), req, env);
      if (req.method === "GET" && path === "/health") return json({ ok: true }, req, env);
      if (req.method === "GET" && path === "/admin/deck") return json(await readDeck(req, env), req, env);
      if (req.method === "POST") {
        if (path === "/start") return json(await start(req, env), req, env);
        if (path === "/answer") return json(await answer(req, env), req, env);
        if (path === "/result") return json(await result(req, env), req, env);
        if (path === "/submit") return json(await submit(req, env, ctx), req, env);
        if (path === "/admin/deck") return json(await uploadDeck(req, env), req, env);
      }
      throw new HttpError(404, "not found");
    } catch (e) {
      const status = e instanceof HttpError ? e.status : 500;
      if (status === 500) console.log(e && e.stack || e);
      return json({ error: status === 500 ? "server error" : e.message }, req, env, status);
    }
  },
};
