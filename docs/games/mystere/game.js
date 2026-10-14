/* Carte mystère — one card a day, hidden letter by letter (like Spellify). Each guess (a letter, a
   number, a mana or tap symbol, or the card's name) uses one of the 13 tries; a letter shows up
   everywhere on the card. Find the name before the tries run out.
   Cards: docs/data/mystere.json, a schedule {Paris date: sealed card} made by pipeline/mystere.py.
   A tutorial (5 steps on an example card) opens on the first visit, then from the "?" button.
   Registered in window.MTG.games; the hub (app.js) mounts it with { onExit }. */
(function () {
"use strict";
var A = window.Artifice, h = React.createElement;
var useState = React.useState, useEffect = React.useEffect, useRef = React.useRef, useMemo = React.useMemo;
var useLayoutEffect = React.useLayoutEffect;
var DATA_URL = "data/mystere.json", NAMES_URL = "data/prix.json";
var TRIES = 13;
var SAVE_KEY = "mystere-", STATS_KEY = "mystere-stats";
var SYMBOLS = ["W", "U", "B", "R", "G", "C", "X", "T"];
var SYMBOL_NAME = { W: "Blanc", U: "Bleu", B: "Noir", R: "Rouge", G: "Vert", C: "Incolore", X: "X", T: "Engager" };
var MANA_IMG = { W: 1, U: 1, B: 1, R: 1, G: 1 };   // games/guildes/img/mana/<w|u|b|r|g>.webp, when present
var ROWS = ["AZERTYUIOP", "QSDFGHJKLM", "WXCVBN"];  // French keyboard

/* ------------------------------------------------------------------ dates */
function parisDate(d) {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Paris", year: "numeric", month: "2-digit", day: "2-digit" }).format(d || new Date());
}
function longDate(iso) {
  return new Date(iso + "T12:00:00").toLocaleDateString("fr-FR", { day: "numeric", month: "long" });
}
/** Milliseconds until the next Paris midnight. */
function untilMidnight() {
  var now = new Date(), parts = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Paris", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" })
    .formatToParts(now).reduce(function (o, p) { o[p.type] = +p.value || 0; return o; }, {});
  return ((23 - parts.hour) * 3600 + (59 - parts.minute) * 60 + (60 - parts.second)) * 1000;
}
function clock(ms) {
  var s = Math.max(0, Math.floor(ms / 1000));
  return [Math.floor(s / 3600), Math.floor(s / 60) % 60, s % 60].map(function (n) { return String(n).padStart(2, "0"); }).join(":");
}

/* ------------------------------------------------------------------ data */
function unseal(blob, date) {
  var bytes = Uint8Array.from(atob(blob), function (c) { return c.charCodeAt(0); });
  return crypto.subtle.digest("SHA-256", new TextEncoder().encode(date)).then(function (buf) {
    var key = new Uint8Array(buf);
    return JSON.parse(new TextDecoder().decode(bytes.map(function (b, i) { return b ^ key[i % key.length]; })));
  });
}

/** Today's card (or the latest one scheduled before today). */
function loadToday() {
  return fetch(DATA_URL, { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(function (d) {
      var today = parisDate(), dates = Object.keys(d.days || {}).filter(function (k) { return k <= today; }).sort();
      var date = dates[dates.length - 1];
      if (!date) throw new Error("no card");
      return unseal(d.days[date], date).then(function (card) { return { date: date, card: card }; });
    });
}

var namesPromise = null;     // every card name (from the price file), for the name suggestions
function loadNames() {
  if (!namesPromise) namesPromise = fetch(NAMES_URL).then(function (r) { return r.ok ? r.json() : { cards: [] }; })
    .then(function (d) { return d.cards.map(function (c) { return c[0]; }).sort(); })
    .catch(function () { namesPromise = null; return []; });
  return namesPromise;
}

function norm(s) { return s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]/g, ""); }

/** A text -> tokens: { s: symbol } for {W}, {2}…; { c: char, k: key } for a letter or digit; { c } otherwise. */
function tokens(text) {
  var out = [], re = /\{([^}]+)\}|([\s\S])/g, m;
  while ((m = re.exec(text || ""))) {
    if (m[1]) out.push({ s: m[1].toUpperCase() });
    else {
      var ch = m[2], up = ch.toUpperCase();
      out.push(/[A-Z0-9]/.test(up) ? { c: ch, k: up } : { c: ch });
    }
  }
  return out;
}
/** The key that reveals a symbol: the digit for generic mana, else the symbol key {W}. */
function symKey(s) { return /^\d$/.test(s) ? s : "{" + s + "}"; }

/** Every key that appears somewhere on the card. */
function keysOf(card) {
  var set = {};
  [card.n, card.m, card.t, card.o, card.p, card.h, card.l].forEach(function (f) {
    tokens(f == null ? "" : String(f)).forEach(function (t) { if (t.k) set[t.k] = 1; if (t.s) set[symKey(t.s)] = 1; });
  });
  return set;
}

/* ------------------------------------------------------------------ save & stats */
/** Which version of the card of the day: its full image (a new render = a new game), else none. */
function version(card) { return card.img ? card.img.f : ""; }
function loadSave(date) { try { return JSON.parse(localStorage.getItem(SAVE_KEY + date)) || null; } catch (e) { return null; } }
function save(date, state) { try { localStorage.setItem(SAVE_KEY + date, JSON.stringify(state)); } catch (e) { /* private mode */ } }
function loadStats() {
  try { return JSON.parse(localStorage.getItem(STATS_KEY)) || { played: 0, won: 0, streak: 0, best: 0, last: null }; }
  catch (e) { return { played: 0, won: 0, streak: 0, best: 0, last: null }; }
}
function recordStats(date, won, v) {
  var s = loadStats();
  if (s.last === date && (s.lastV || "") === (v || "")) return s;
  s.lastV = v || "";
  var yesterday = parisDate(new Date(new Date(date + "T12:00:00Z").getTime() - 864e5));
  s.played++; if (won) s.won++;
  s.streak = won ? (s.lastWon === yesterday ? s.streak + 1 : 1) : 0;
  s.best = Math.max(s.best, s.streak); s.last = date; if (won) s.lastWon = date;
  try { localStorage.setItem(STATS_KEY, JSON.stringify(s)); } catch (e) { /* private mode */ }
  return s;
}

/* ------------------------------------------------------------------ jokes */
function winQuip(n) {
  return n <= 4 ? "Tu as triché, ou tu as vraiment lu toutes les cartes de Magic ?" :
         n <= 7 ? "Propre. Le Spike en toi jubile." :
         n <= 10 ? "Pas mal. Ton binder approuve." :
                   "Sur le fil. Comme ta dernière game à 1 point de vie.";
}
var LOSE_QUIPS = ["Treize essais, et rien. Retourne lire tes cartes.", "Tu peux toujours dire que tu joues en Pauper.",
                  "Même ton deck précon la connaissait.", "La carte rigole encore."];

/* ------------------------------------------------------------------ pieces */
function Sym(p) {
  var s = p.s;
  if (p.hidden) return h("span", { className: "my-sym is-hidden", "aria-label": "symbole caché" }, "?");
  if (MANA_IMG[s]) return h(ManaImg, { s: s });
  return h("span", { className: "my-sym my-sym--" + (s === "T" ? "tap" : "text"), title: SYMBOL_NAME[s] || s, "aria-label": SYMBOL_NAME[s] || s },
    s === "T" ? "↷" : s);
}
function ManaImg(p) {
  var st = useState(false), broken = st[0], setBroken = st[1];
  if (broken) return h("span", { className: "my-sym my-sym--" + p.s.toLowerCase(), "aria-label": SYMBOL_NAME[p.s] }, p.s);
  return h("img", { className: "my-sym my-sym--img", src: "games/guildes/img/mana/" + p.s.toLowerCase() + ".webp", alt: SYMBOL_NAME[p.s],
                    onError: function () { setBroken(true); } });
}

/** A line of card text with the unguessed letters, digits and symbols hidden. Words never break. */
function Masked(p) {
  var toks = tokens(p.text == null ? "" : String(p.text)), out = [], word = [], key = 0, paren = 0;
  function flush() { if (word.length) { out.push(h("span", { key: key++, className: "my-word" }, word)); word = []; } }
  toks.forEach(function (t) {
    if (t.s) { word.push(h(Sym, { key: key++, s: t.s, hidden: !p.all && !p.known[symKey(t.s)] })); return; }
    if (t.c === "\n") { flush(); out.push(h("br", { key: key++ })); return; }
    if (t.c === " ") { flush(); out.push(" "); return; }
    if (t.c === "(") paren++;
    var it = p.italic && paren > 0 ? " is-it" : "";        // reminder text, in italics as printed
    if (t.c === ")") paren = Math.max(0, paren - 1);
    if (t.k && !p.all && !p.known[t.k]) word.push(h("span", { key: key++, className: "my-slot" + it, "aria-label": "lettre cachée" }));
    else word.push(h("span", { key: key++, className: (t.k ? "my-ch is-found" : "my-ch") + it }, t.c));
  });
  flush();
  return h(p.as || "span", { className: p.className }, out);
}

/* The Magic Set Editor version (pipeline/render_mystere.py): the blank M15 card (frame, blurred art)
   with the hidden text laid over it at the frame's places; the real card once the game is over.
   Add ?boxes to the address to see the text boxes (to adjust them in style.css). */
var SHOW_BOXES = /[?&]boxes\b/.test(location.search);

/** Shrinks the font of an element (in container width units) until its content fits its box. */
function useFit(ref, deps, max, min, oneLine) {
  useLayoutEffect(function () {
    var el = ref.current;
    if (!el) return;
    var size = max;
    el.style.fontSize = size + "cqw";
    for (var i = 0; i < 40 && size > min; i++) {
      var over = oneLine ? el.scrollWidth > el.clientWidth + 1 : el.scrollHeight > el.clientHeight + 1;
      if (!over) break;
      size = Math.max(min, size - 0.1);
      el.style.fontSize = size + "cqw";
    }
  }, deps);
}

function Box(p) {
  var ref = useRef(null);
  useFit(ref, [p.sig, p.width], p.max, p.min, p.oneLine);
  return h("div", { ref: ref, className: "my-box my-box--" + p.kind + (SHOW_BOXES ? " is-debug" : "") },
    h(Masked, { className: "my-box__in", text: p.text, known: p.known, all: false, italic: p.kind === "text" }));
}

/** A blurred copy of one area of the card (left, top, width, height in % of the card), drawn on top
    of it: the set symbol at the end of the type line and the set code at the bottom left. */
var HIDE_SET = [81.6, 55.4, 12.8, 7.2], HIDE_CODE = [3.6, 92.2, 18.6, 6.2];
function Blurred(p) {
  var b = p.box, e = [b[0] - 0.3 * b[2], b[1] - 0.3 * b[3], 1.6 * b[2], 1.6 * b[3]];   // the inner copy is 30 % larger on each side
  return h("div", { className: "my-hide" + (SHOW_BOXES ? " is-debug" : ""), "aria-hidden": "true",
    style: { left: b[0] + "%", top: b[1] + "%", width: b[2] + "%", height: b[3] + "%" } },
    h("div", { className: "my-hide__img", style: {
      backgroundImage: "url(" + p.src + ")",
      backgroundSize: (10000 / e[2]) + "% " + (10000 / e[3]) + "%",
      backgroundPosition: (e[0] * 100 / (100 - e[2])) + "% " + (e[1] * 100 / (100 - e[3])) + "%" } }));
}

function MseCard(p) {
  var c = p.card, known = p.known, done = p.reveal;
  var sig = Object.keys(known).sort().join("");            // re-fit the text when letters appear
  var s = useState(0), width = s[0], setWidth = s[1];
  var root = useRef(null);
  useEffect(function () {                     // re-fit on resize
    function onResize() { setWidth(root.current ? root.current.clientWidth : 0); }
    onResize(); window.addEventListener("resize", onResize);
    return function () { window.removeEventListener("resize", onResize); };
  }, []);
  var pt = c.p != null && c.h != null ? c.p + "/" + c.h : null;
  var size = c.size || [750, 1046];
  return h("article", { ref: root, className: "my-mse" + (done ? " is-revealed" : "") + (pt ? " has-pt" : ""), "aria-label": "Carte mystère",
                        style: { aspectRatio: size[0] + " / " + size[1] } },
    h("img", { className: "my-mse__img", src: "img/mystere/" + c.img.b, alt: "" }),
    h("img", { className: "my-mse__img my-mse__full", src: "img/mystere/" + c.img.f, alt: done ? c.n : "", loading: done ? "eager" : "lazy" }),
    done ? null : h(React.Fragment, null,
      // the set gives the card away: its symbol and the set code at the bottom are blurred
      h(Blurred, { src: "img/mystere/" + c.img.b, box: HIDE_SET }),
      h(Blurred, { src: "img/mystere/" + c.img.b, box: HIDE_CODE }),
      h(Box, { kind: "name", text: c.n, known: known, sig: sig, width: width, max: 5.0, min: 2.8, oneLine: true }),
      c.m ? h(Box, { kind: "cost", text: c.m, known: known, sig: sig, width: width, max: 4.8, min: 3.4, oneLine: true }) : null,
      h(Box, { kind: "type", text: c.t, known: known, sig: sig, width: width, max: 4.6, min: 2.8, oneLine: true }),
      h(Box, { kind: "text", text: c.o, known: known, sig: sig, width: width, max: 5.4, min: 2.6 }),
      pt ? h(Box, { kind: "pt", text: pt, known: known, sig: sig, width: width, max: 5.0, min: 3.2, oneLine: true }) : null));
}

function CardView(p) {
  if (p.card.img) return h(MseCard, p);
  var c = p.card, known = p.known, all = p.reveal;
  var art = "https://cards.scryfall.io/art_crop/front/" + c.id[0] + "/" + c.id[1] + "/" + c.id + ".jpg";
  var stats = c.p != null && c.h != null ? c.p + "/" + c.h : c.l != null ? String(c.l) : null;
  return h("article", { className: "my-card" + (all ? " is-revealed" : ""), "aria-label": "Carte mystère" },
    h("header", { className: "my-card__head" },
      h(Masked, { as: "h2", className: "my-card__name", text: c.n, known: known, all: all }),
      h(Masked, { className: "my-card__cost", text: c.m, known: known, all: all })),
    h("div", { className: "my-card__art" }, h("img", { src: art, alt: all ? "Illustration de " + c.n : "", loading: "eager" })),
    h(Masked, { as: "p", className: "my-card__type", text: c.t, known: known, all: all }),
    h(Masked, { as: "p", className: "my-card__text", text: c.o, known: known, all: all, italic: true }),
    stats ? h(Masked, { className: "my-card__pt", text: stats, known: known, all: all }) : null);
}

function Pips(p) {
  return h("div", { className: "my-pips", role: "img", "aria-label": (TRIES - p.used) + " essais restants sur " + TRIES },
    Array.from({ length: TRIES }, function (_, i) {
      var g = p.guesses[i];
      return h("span", { key: i, className: "my-pip" + (g ? (g.ok ? " is-hit" : " is-miss") : "") });
    }));
}

function Keyboard(p) {
  function key(k, label, extra) {
    var g = p.state[k];
    return h("button", { key: k, type: "button", disabled: !!g || p.disabled,
                         className: "my-key" + (extra || "") + (g ? (g === "hit" ? " is-hit" : " is-miss") : ""),
                         "aria-label": k.length > 1 ? "Symbole " + (SYMBOL_NAME[k.slice(1, -1)] || k) : k,
                         onClick: function () { p.onKey(k); } }, label);
  }
  return h("div", { className: "my-kb", role: "group", "aria-label": "Clavier" },
    ROWS.map(function (row, i) {
      return h("div", { key: i, className: "my-kb__row" }, row.split("").map(function (ch) { return key(ch, ch); }));
    }),
    h("div", { className: "my-kb__row my-kb__row--digits" }, "1234567890".split("").map(function (ch) { return key(ch, ch, " my-key--small"); })),
    h("div", { className: "my-kb__row my-kb__row--syms" }, SYMBOLS.map(function (s) {
      return key("{" + s + "}", h(Sym, { s: s }), " my-key--sym");
    })));
}

/** The name field, with suggestions from every card name once 2 letters are typed. */
/** The name field, with suggestions from every card name once 2 letters are typed. On a phone the
    virtual keyboard would hide a field at the bottom of the page: while typing, the field and its
    suggestions move to the top of the screen (a panel over the page), and come back afterwards. */
function NameGuess(p) {
  var s1 = useState(""), value = s1[0], setValue = s1[1];
  var s2 = useState([]), names = s2[0], setNames = s2[1];
  var s3 = useState(false), open = s3[0], setOpen = s3[1];
  var input = useRef(null);
  var q = norm(value);
  var sugg = useMemo(function () {
    if (q.length < 2 || !names.length) return [];
    var starts = [], has = [];
    for (var i = 0; i < names.length && starts.length < 6; i++) {
      var n = norm(names[i]);
      if (n.indexOf(q) === 0) starts.push(names[i]); else if (has.length < 6 && n.indexOf(q) > 0) has.push(names[i]);
    }
    return starts.concat(has).slice(0, 6);
  }, [q, names]);
  useEffect(function () {                      // the panel opened: keep the focus in its field
    if (open && input.current) input.current.focus();
  }, [open]);
  function close() { setOpen(false); if (input.current) input.current.blur(); }
  function submit(name) {
    if (!norm(name)) return;
    p.onGuess(name); setValue(""); close();
  }
  var keep = function (e) { e.preventDefault(); };   // a tap on a suggestion must not close the keyboard first
  return h(React.Fragment, null,
    open ? h("div", { className: "my-name__scrim", onMouseDown: keep, onClick: close }) : null,
    h("form", { className: "my-name" + (open ? " is-open" : ""), onSubmit: function (e) { e.preventDefault(); submit(value); } },
      open ? h("p", { className: "my-name__title label" }, "Quelle est cette carte ?") : null,
      h("div", { className: "my-name__row" },
        h("input", { ref: input, className: "my-name__input", type: "text", value: value, placeholder: "Le nom de la carte…",
                     autoComplete: "off", autoCapitalize: "words", spellCheck: false, enterKeyHint: "go",
                     disabled: p.disabled, "aria-label": "Proposer le nom de la carte",
                     onFocus: function () { setOpen(true); loadNames().then(setNames); },
                     onKeyDown: function (e) { if (e.key === "Escape") close(); },
                     onChange: function (e) { setValue(e.target.value); } }),
        h(A.Button, { type: "submit", variant: "primary", size: "md", disabled: p.disabled || !norm(value), onMouseDown: keep }, "Deviner"),
        open ? h(A.Button, { variant: "ghost", size: "md", icon: "close", "aria-label": "Fermer", onMouseDown: keep, onClick: close }) : null),
      open && sugg.length ? h("ul", { className: "my-sugg", role: "listbox" }, sugg.map(function (n) {
        return h("li", { key: n }, h("button", { type: "button", className: "my-sugg__item body", onMouseDown: keep,
                                                  onClick: function () { submit(n); } }, n));
      })) : null,
      open ? h("p", { className: "my-name__hint caption" }, "Attention : une mauvaise réponse coûte un essai.") : null));
}

function share(date, guesses, won) {
  var grid = guesses.map(function (g) { return g.name ? (g.ok ? "🏆" : "🟥") : g.ok ? "🟩" : "⬛"; }).join("");
  var text = "Carte mystère du " + longDate(date) + " : " + (won ? "trouvée en " + guesses.length + "/" + TRIES : "perdue") + "\n" + grid;
  var url = location.href.split("#")[0] + "#mystere";
  if (navigator.share) return navigator.share({ title: "Carte mystère", text: text, url: url }).then(function () { return "shared"; }, function () { return null; });
  if (navigator.clipboard) return navigator.clipboard.writeText(text + "\n" + url).then(function () { return "copied"; }, function () { return "failed"; });
  return Promise.resolve("failed");
}

function Countdown() {
  var s = useState(untilMidnight()), ms = s[0], setMs = s[1];
  useEffect(function () { var id = setInterval(function () { setMs(untilMidnight()); }, 1000); return function () { clearInterval(id); }; }, []);
  return h("p", { className: "caption my-next" }, "Prochaine carte dans ", h("strong", null, clock(ms)));
}

function End(p) {
  var s = useState(null), status = s[0], setStatus = s[1];
  var st = p.stats, c = p.card;
  return h(A.Panel, { as: "section", className: "my-end", "aria-labelledby": "my-end-title" },
    h("p", { className: "ar-eyebrow eyebrow" }, p.won ? "Trouvée !" : "Perdu"),
    h("h2", { id: "my-end-title", className: "title-lg" }, p.won ? "En " + p.guesses.length + " essai" + (p.guesses.length > 1 ? "s" : "") : c.n),
    h("p", { className: "flavor my-end__quip" }, p.won ? winQuip(p.guesses.length) : p.quip),
    h("div", { className: "my-stats" },
      [["Parties", st.played], ["Victoires", st.played ? Math.round(100 * st.won / st.played) + " %" : "–"],
       ["Série", st.streak], ["Record", st.best]].map(function (x) {
        return h("div", { key: x[0], className: "my-stat" }, h("span", { className: "my-stat__n title-md" }, x[1]), h("span", { className: "caption" }, x[0]));
      })),
    h("div", { className: "my-end__actions" },
      h(A.Button, { variant: "primary", size: "lg", block: true, icon: "share", onClick: function () { share(p.date, p.guesses, p.won).then(setStatus); } }, "Partager"),
      status === "copied" ? h("p", { className: "caption my-meta", role: "status" }, "Copié, il n'y a plus qu'à coller.") :
      status === "failed" ? h("p", { className: "caption my-meta", role: "status" }, "Le partage n'est pas disponible ici.") : null,
      h("a", { className: "my-link label", href: "https://scryfall.com/card/" + c.s + "/" + encodeURIComponent(c.cn), target: "_blank", rel: "noopener" },
        "Voir " + c.n + " sur Scryfall")),
    h(Countdown));
}

/* ------------------------------------------------------------------ tutorial */
/* Shown once (first visit), then from the "?" button: five steps on a small example card. */
var TUTO_KEY = "mystere-tuto";
var TUTO_CARD = { n: "Lightning Bolt", m: "{R}", t: "Instant", o: "Lightning Bolt deals 3 damage to any target." };
var TUTO_STEPS = [
  { title: "Une carte par jour", known: {},
    text: "Chaque jour, une vraie carte de Magic est cachée : chaque lettre, chiffre et symbole de mana est remplacé par une case vide. À toi de trouver son nom." },
  { title: "Propose une lettre", known: { L: 1 },
    text: "Tape une lettre au clavier : si elle est sur la carte, elle apparaît partout d'un coup, dans le nom, le type et le texte. Ici, le L." },
  { title: "Chiffres et symboles aussi", known: { L: 1, "3": 1, "{R}": 1 },
    text: "Les chiffres et les symboles de mana (blanc, bleu, noir, rouge, vert, incolore, X, engager) se proposent de la même façon, avec les touches sous le clavier." },
  { title: "Devine le nom", known: { L: 1, T: 1, "3": 1, "{R}": 1, I: 1, G: 1, N: 1 },
    text: "Quand tu penses avoir trouvé, tape le nom dans le champ en bas de la page (il propose les noms des cartes). Tu gagnes aussi si toutes les lettres du nom sont révélées." },
  { title: "13 essais, pas un de plus", known: null, pips: [1, 0, 1, 1, 0, 1, 1],
    text: "Chaque lettre, chiffre ou symbole proposé, qu'il soit sur la carte ou non, et chaque nom proposé utilise un essai. Doré : trouvé, rouge : raté. Au 13e essai sans la bonne réponse, c'est perdu. Nouvelle carte chaque jour à minuit." },
];
function tutoSeen() { try { return !!localStorage.getItem(TUTO_KEY); } catch (e) { return true; } }
function setTutoSeen() { try { localStorage.setItem(TUTO_KEY, "1"); } catch (e) { /* private mode */ } }

function Tutorial(p) {
  var s = useState(0), i = s[0], setI = s[1];
  var step = TUTO_STEPS[i], last = i === TUTO_STEPS.length - 1;
  var closeBtn = useRef(null);
  useEffect(function () {
    if (closeBtn.current) closeBtn.current.focus();
    function onKey(e) {
      if (e.key === "Escape") p.onClose();
      else if (e.key === "ArrowRight") setI(function (n) { return Math.min(n + 1, TUTO_STEPS.length - 1); });
      else if (e.key === "ArrowLeft") setI(function (n) { return Math.max(n - 1, 0); });
      else return;
      e.stopPropagation(); e.preventDefault();
    }
    window.addEventListener("keydown", onKey, true);      // before the game's own keyboard
    return function () { window.removeEventListener("keydown", onKey, true); };
  }, []);
  var c = TUTO_CARD, k = step.known || {};
  var demo = step.pips ?
    h("div", { className: "my-tuto__pips" }, h(Pips, { guesses: step.pips.map(function (ok) { return { ok: !!ok }; }), used: step.pips.length }),
      h("p", { className: "label" }, (TRIES - step.pips.length) + " essais restants")) :
    h("div", { className: "my-tuto__card", "aria-hidden": "true" },
      h("div", { className: "my-tuto__head" },
        h(Masked, { className: "my-tuto__name", text: c.n, known: k }),
        h(Masked, { className: "my-tuto__cost", text: c.m, known: k })),
      h(Masked, { as: "p", className: "my-tuto__type", text: c.t, known: k }),
      h(Masked, { as: "p", className: "my-tuto__text", text: c.o, known: k }));
  return h("div", { className: "my-tuto", role: "dialog", "aria-modal": "true", "aria-labelledby": "my-tuto-title",
                    onClick: function (e) { if (e.target === e.currentTarget) p.onClose(); } },
    h("div", { className: "my-tuto__panel" },
      h("div", { className: "my-tuto__bar" },
        h("p", { className: "ar-eyebrow eyebrow" }, "Comment jouer · " + (i + 1) + " / " + TUTO_STEPS.length),
        h("button", { ref: closeBtn, type: "button", className: "my-tuto__x", "aria-label": "Fermer le tutoriel", onClick: p.onClose },
          h(A.Icon, { name: "close", size: 20 }))),
      h("h2", { id: "my-tuto-title", className: "title-sm" }, step.title),
      demo,
      h("p", { className: "body my-tuto__say" }, step.text),
      h("div", { className: "my-tuto__dots", "aria-hidden": "true" },
        TUTO_STEPS.map(function (_, n) { return h("span", { key: n, className: n === i ? "is-on" : "" }); })),
      h("div", { className: "my-tuto__nav" },
        i > 0 ? h(A.Button, { variant: "ghost", size: "md", icon: "arrow-left", onClick: function () { setI(i - 1); } }, "Précédent") : h("span"),
        last ? h(A.Button, { variant: "primary", size: "md", onClick: p.onClose }, "C'est parti") :
               h(A.Button, { variant: "primary", size: "md", iconEnd: "arrow-right", onClick: function () { setI(i + 1); } }, "Suivant"))));
}

/* ------------------------------------------------------------------ game */
function Game(p) {
  var s1 = useState(null), day = s1[0], setDay = s1[1];
  var s2 = useState(null), error = s2[0], setError = s2[1];
  var s3 = useState([]), guesses = s3[0], setGuesses = s3[1];      // [{ k, ok } | { name, ok }]
  var s4 = useState(null), flash = s4[0], setFlash = s4[1];
  var s5 = useState(loadStats), stats = s5[0], setStats = s5[1];
  var quip = useRef(LOSE_QUIPS[Math.floor(Math.random() * LOSE_QUIPS.length)]);
  var s6 = useState(function () { return !tutoSeen(); }), tuto = s6[0], setTuto = s6[1];
  function closeTuto() { setTutoSeen(); setTuto(false); }

  useEffect(function () {
    loadToday().then(function (d) {
      setDay(d);
      // a new render of the card (new images) starts a fresh game; ?reset too (for tests)
      if (/[?&]reset\b/.test(location.search)) { try { localStorage.removeItem(SAVE_KEY + d.date); } catch (e) {} }
      var saved = loadSave(d.date);
      if (saved && saved.guesses && (saved.v || "") === version(d.card)) setGuesses(saved.guesses);
    }).catch(function () { setError("La carte du jour n'est pas encore disponible. Reviens un peu plus tard."); });
  }, []);

  var card = day && day.card;
  var present = useMemo(function () { return card ? keysOf(card) : {}; }, [card]);
  var known = {}, keyState = {};
  guesses.forEach(function (g) { if (g.k) { known[g.k] = true; keyState[g.k] = g.ok ? "hit" : "miss"; } });
  var nameKeys = card ? tokens(card.n).filter(function (t) { return t.k; }) : [];
  var won = !!card && (guesses.some(function (g) { return g.name && g.ok; }) ||
                       (nameKeys.length > 0 && nameKeys.every(function (t) { return known[t.k]; })));
  var lost = !won && guesses.length >= TRIES;
  var done = won || lost;

  useEffect(function () {                      // keyboard: letters and digits
    function onKey(e) {
      if (tuto || done || !card || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.target && /input|textarea/i.test(e.target.tagName)) return;
      var k = e.key.toUpperCase();
      if (/^[A-Z0-9]$/.test(k)) { e.preventDefault(); guessKey(k); }
    }
    window.addEventListener("keydown", onKey);
    return function () { window.removeEventListener("keydown", onKey); };
  });
  useEffect(function () { if (done && day) setStats(recordStats(day.date, won, version(day.card))); }, [done]);

  function commit(next) { setGuesses(next); save(day.date, { v: version(day.card), guesses: next }); }
  function guessKey(k) {
    if (done || keyState[k]) return;
    var ok = !!present[k];
    commit(guesses.concat([{ k: k, ok: ok }]));
    setFlash(ok ? null : { miss: true, text: (k.length > 1 ? "Pas de symbole " + SYMBOL_NAME[k.slice(1, -1)] : "Pas de " + k) + " sur cette carte." });
  }
  function guessName(name) {
    if (done) return;
    var ok = norm(name) === norm(card.n);
    commit(guesses.concat([{ name: name, ok: ok }]));
    setFlash(ok ? null : { miss: true, text: "Non, ce n'est pas « " + name + " »." });
  }

  var body;
  if (error) body = h("p", { className: "error body my-error" }, error);
  else if (!card) body = h("p", { className: "caption my-meta" }, "Chargement de la carte du jour…");
  else body = h(React.Fragment, null,
    h("div", { className: "my-top" },
      h("p", { className: "label my-left" }, done ? " " : (TRIES - guesses.length) + " essai" + (TRIES - guesses.length > 1 ? "s" : "") + " restant" + (TRIES - guesses.length > 1 ? "s" : "")),
      h(Pips, { guesses: guesses, used: guesses.length })),
    h(CardView, { card: card, known: known, reveal: done }),
    done ? h(End, { card: card, date: day.date, guesses: guesses, won: won, stats: stats, quip: quip.current }) :
    h(React.Fragment, null,
      h("p", { className: "my-flash caption" + (flash && flash.miss ? " is-miss" : ""), role: "status" },
        flash ? flash.text : "Une lettre, un chiffre ou un symbole : il apparaît partout sur la carte."),
      h(Keyboard, { state: keyState, onKey: guessKey, disabled: done }),
      h(NameGuess, { onGuess: guessName, disabled: done })));

  return h("div", { className: "app my", "data-screen": done ? "end" : "play" },
    h("header", { className: "bar" },
      h(A.Button, { variant: "secondary", icon: "arrow-left", "aria-label": "Tous les jeux", onClick: p.onExit }),
      h("h1", { className: "title-sm" }, "Carte mystère"),
      h("button", { type: "button", className: "my-help", "aria-label": "Comment jouer", onClick: function () { setTuto(true); } }, "?")),
    day ? h("p", { className: "my-date caption" }, "Carte du " + longDate(day.date)) : null,
    body,
    tuto ? h(Tutorial, { onClose: closeTuto }) : null);
}

window.MTG.games.push({
  id: "mystere",
  title: "Carte mystère",
  pitch: "Une carte par jour, cachée lettre par lettre. Lettres, chiffres, symboles de mana : 13 essais pour trouver son nom.",
  icon: "d20",
  details: "Une nouvelle carte chaque jour à minuit",
  order: 4,
  component: Game,
  lastResult: function () {
    var today = parisDate(), sv = loadSave(today);
    if (!sv || !sv.guesses || !sv.guesses.length) return "La carte du jour t'attend.";
    var st = loadStats();
    if (st.last === today) return st.lastWon === today ? "Carte du jour trouvée · série de " + st.streak : "Carte du jour ratée. Revanche demain.";
    return "Partie du jour en cours : " + sv.guesses.length + "/" + TRIES + " essais";
  },
});
})();
