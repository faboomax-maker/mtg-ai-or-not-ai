"use strict";

const $ = (id) => document.getElementById(id);
const state = { pool: [], deck: [], i: 0, score: 0, streak: 0, best: 0, history: [], answered: false };

/* ---------------------------------------------------------------- data */
async function loadPool() {
  const res = await fetch("data/cards.json", { cache: "no-cache" });
  if (!res.ok) throw new Error("data/cards.json introuvable");
  const data = await res.json();
  state.pool = data.cards;
  const label = data.generated === "demo" ? "jeu de démonstration" : `généré le ${data.generated}`;
  $("pool-info").textContent = `${data.count} cartes disponibles · ${label}`;
}

async function unseal(card) {
  const bytes = Uint8Array.from(atob(card.s), (c) => c.charCodeAt(0));
  const key = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(card.img)));
  const out = bytes.map((b, i) => b ^ key[i % key.length]);
  return JSON.parse(new TextDecoder().decode(out));
}

/* ------------------------------------------------------------- symbols */
const MANA_BG = { W: "#f8f3d6", U: "#a9d3ef", B: "#c9c0bd", R: "#f2a58c", G: "#9bd3ae", C: "#d8d3cf" };

function symbol(raw) {
  const s = raw.toUpperCase();
  if (s === "T") return '<span class="ms ms-T" title="Engager">↷</span>';
  if (s === "Q") return '<span class="ms ms-T" title="Dégager">↶</span>';
  if ("WUBRGC".includes(s) && s.length === 1) return `<span class="ms ms-${s}">${s}</span>`;
  if (s === "S") return '<span class="ms ms-S">❄</span>';
  if (s.includes("/")) {
    const [a, b] = s.split("/");
    if (b === "P") return `<span class="ms ms-${a}">φ</span>`;
    const ca = MANA_BG[a] || "#d3cdc8", cb = MANA_BG[b] || "#d3cdc8";
    return `<span class="ms ms-H" style="--a:${ca};--b:${cb}">${/\d/.test(a) ? a : ""}</span>`;
  }
  return `<span class="ms ms-N">${s}</span>`;
}

const esc = (t) => t.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const withSymbols = (t) => esc(t).replace(/\{([^}]+)\}/g, (_, s) => symbol(s));

function rulesHTML(text) {
  if (!text) return "";
  return text.split("\n").map((line) =>
    `<p>${withSymbols(line).replace(/\(([^)]*)\)/g, "<i>($1)</i>")}</p>`).join("");
}

/* ---------------------------------------------------------------- card */
function frameClass(c) {
  const col = c.colors || [];
  if (col.length > 1) return "M";
  if (col.length === 1) return col[0];
  return /Land/.test(c.type_line) ? "L" : "C";
}

function setSymbol(c) {
  if (!c.set_icon) return `<span class="gem ${c.rarity}"></span>`;
  const url = `sets/${encodeURIComponent(c.set_icon)}.svg`;
  return `<span class="set"><span class="set-glyph ${c.rarity}" style="--icon:url('${url}')"></span></span>`;
}

function renderCard(c) {
  if (c.card) {  // full card rendered by Magic Set Editor (same frame for real and AI cards)
    return `<div class="card-wrap"><img class="card-img" src="img/${c.img}" alt="${esc(c.name)}"></div>`;
  }
  const cost = (c.mana_cost || "").match(/\{[^}]+\}/g) || [];
  const flavor = c.flavor_text
    ? `<p class="flavor${c.oracle_text ? "" : " solo"}">${esc(c.flavor_text).replace(/\n/g, "<br>")}</p>` : "";
  const corner = c.power != null && c.toughness != null
    ? `<div class="pt">${esc(c.power)}/${esc(c.toughness)}</div>`
    : c.loyalty ? `<div class="loyalty">${esc(c.loyalty)}</div>` : "";
  return `
  <div class="card-wrap">
    <article class="card ${frameClass(c)}" aria-label="${esc(c.name)}">
      <div class="frame">
        <div class="bar"><span class="name">${esc(c.name)}</span>
          <span class="cost">${cost.map((m) => symbol(m.slice(1, -1))).join("")}</span></div>
        <div class="art" style="background-image:url('img/${c.img}')" role="img" aria-label="Illustration"></div>
        <div class="bar"><span class="type">${esc(c.type_line)}</span>${setSymbol(c)}</div>
        <div class="textbox">${rulesHTML(c.oracle_text)}${flavor}</div>
        ${corner}
      </div>
    </article>
  </div>`;
}

function fitText(box) {
  let size = 1.15;           // short texts are printed larger, like on real cards
  box.style.fontSize = size + "em";
  while (box.scrollHeight > box.clientHeight + 1 && size > 0.55) {
    size -= 0.04;
    box.style.fontSize = size.toFixed(2) + "em";
  }
}

/* ---------------------------------------------------------------- game */
function shuffle(a) {
  for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
  return a;
}

function start(len) {
  const deck = shuffle([...state.pool]);
  Object.assign(state, { deck: len ? deck.slice(0, len) : deck, i: 0, score: 0, streak: 0, best: 0, history: [] });
  $("start").hidden = true; $("end").hidden = true; $("game").hidden = false; $("hud").hidden = false;
  show();
}

function show() {
  const c = state.deck[state.i];
  state.answered = false;
  $("card-slot").innerHTML = renderCard(c);
  const box = $("card-slot").querySelector(".textbox");
  if (box) document.fonts.ready.then(() => fitText(box));
  $("choices").hidden = false; $("verdict").hidden = true;
  $("progress").textContent = `${state.i + 1} / ${state.deck.length}`;
  $("score").textContent = state.score; $("streak").textContent = state.streak;
  const next = state.deck[state.i + 1];
  if (next) new Image().src = `img/${next.img}`;
}

async function answer(saysReal) {
  if (state.answered) return;
  state.answered = true;
  const c = state.deck[state.i];
  const secret = await unseal(c);
  const good = secret.real === saysReal;
  if (good) { state.score++; state.streak++; state.best = Math.max(state.best, state.streak); }
  else state.streak = 0;
  state.history.push({ name: c.name, real: secret.real, good });

  const stamp = document.createElement("div");
  stamp.className = "stamp " + (secret.real ? "real" : "ai");
  stamp.textContent = secret.real ? "VRAIE" : "IA";
  $("card-slot").querySelector(".card-wrap").appendChild(stamp);

  const t = $("verdict-title");
  t.className = "verdict-title " + (good ? "ok" : "ko");
  t.textContent = good ? "Bien vu !" : "Raté…";
  $("verdict-detail").innerHTML = secret.real
    ? `Vraie carte${secret.set ? " · " + esc(secret.set) : ""}${secret.artist ? " · illustration de " + esc(secret.artist) : ""}` +
      (secret.url ? ` · <a href="${esc(secret.url)}" target="_blank" rel="noopener">voir sur Scryfall</a>` : "")
    : (secret.art_from
        ? `Carte inventée par une IA (nom et texte). Illustration de ${esc(secret.artist || "?")}, ` +
          `empruntée à la vraie carte « ${esc(secret.art_from)} ».`
        : "Carte inventée par une IA : texte, nom et illustration.") +
      (secret.set ? ` Le symbole de set (${esc(secret.set)}) a été emprunté pour brouiller les pistes.` : "");
  $("score").textContent = state.score; $("streak").textContent = state.streak;
  $("choices").hidden = true; $("verdict").hidden = false;
  $("btn-next").textContent = state.i + 1 < state.deck.length ? "Carte suivante" : "Voir le résultat";
  $("btn-next").focus();
}

function next() {
  if (!state.answered) return;
  state.i++;
  if (state.i < state.deck.length) show(); else finish();
}

function finish() {
  const n = state.deck.length, pct = Math.round((100 * state.score) / n);
  $("game").hidden = true; $("end").hidden = false; $("hud").hidden = true;
  $("final-score").textContent = `${state.score} / ${n}`;
  $("final-msg").textContent =
    pct >= 90 ? `Planeswalker confirmé ! Meilleure série : ${state.best}.` :
    pct >= 70 ? `Très bon œil. Meilleure série : ${state.best}.` :
    pct >= 50 ? `Pas mal, mais l'IA vous a eu plusieurs fois. Meilleure série : ${state.best}.` :
                `L'IA vous a bien piégé… Meilleure série : ${state.best}.`;
  $("recap").innerHTML = state.history.map((h) =>
    `<li><span class="mark ${h.good ? "ok" : "ko"}">${h.good ? "✓" : "✗"}</span>${esc(h.name)}
     <span class="tag">${h.real ? "vraie" : "IA"}</span></li>`).join("");
}

/* -------------------------------------------------------------- wiring */
document.querySelectorAll("[data-len]").forEach((b) => b.addEventListener("click", () => start(+b.dataset.len)));
$("btn-real").addEventListener("click", () => answer(true));
$("btn-ai").addEventListener("click", () => answer(false));
$("btn-next").addEventListener("click", next);
$("btn-again").addEventListener("click", () => { $("end").hidden = true; $("start").hidden = false; });
document.addEventListener("keydown", (e) => {
  if ($("game").hidden) return;
  if (!state.answered && (e.key === "ArrowLeft" || e.key.toLowerCase() === "v")) answer(true);
  else if (!state.answered && (e.key === "ArrowRight" || e.key.toLowerCase() === "i")) answer(false);
  else if (state.answered && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); next(); }
});
window.addEventListener("resize", () => { const b = document.querySelector(".textbox"); if (b) fitText(b); });

loadPool().catch((err) => {
  $("pool-info").textContent = `Erreur : ${err.message}. Lancez le pipeline puis servez le dossier docs/ via un serveur web.`;
  document.querySelectorAll("[data-len]").forEach((b) => (b.disabled = true));
});
