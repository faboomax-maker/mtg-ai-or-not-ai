/* Plus cher ou moins cher ? — a card and its price, then a second card: is it worth more or less?
   Chain right answers; one mistake ends the run. Prices: docs/data/prix.json, made by
   pipeline/fetch_prices.py (Scryfall's Cardmarket trend price, refreshed every week).
   Registered in window.MTG.games; the hub (app.js) mounts it with { onExit }. */
(function () {
"use strict";
var A = window.Artifice, h = React.createElement;
var useState = React.useState, useEffect = React.useEffect, useRef = React.useRef;
var DATA_URL = "data/prix.json";
var REVEAL_MS = 650, NEXT_MS = 1100;            // price count-up, then the next pair
var BEST_KEY = "plus-cher-best-";

/* Difficulty: which cards (EDHREC rank: 1 = the most played in Commander, 0 = unranked) and how far
   apart the two prices are (ratio between the dearer and the cheaper, and a minimum gap in cents).
   Each mode is unlocked by a streak of UNLOCK in the one before it. */
var UNLOCK = 5;
var obscure = function (c) { return c.r === 0 || c.r > 3000; };
var MODES = {
  facile:     { name: "Facile", desc: "Des cartes connues, des prix bien différents.",
                pool: function (c) { return c.r > 0 && c.r <= 2500; }, ratio: [3, 30], gap: 50 },
  moyen:      { name: "Moyen", desc: "Des cartes moins jouées, des prix plus proches.",
                pool: function (c) { return c.r > 0 && c.r <= 12000; }, ratio: [1.6, 3], gap: 30 },
  hardcore:   { name: "Hardcore", desc: "Des cartes obscures que personne ne joue.",
                pool: obscure, ratio: [1.6, 3], gap: 30, icon: "skull", dark: true },
  impossible: { name: "Impossible", desc: "Des cartes obscures, des prix au coude à coude.",
                pool: obscure, ratio: [1.15, 1.6], gap: 20, icon: "candle", dark: true },
};
var ORDER = ["facile", "moyen", "hardcore", "impossible"];
/** The mode before m (whose streak unlocks it), or null for the first one. */
function prevMode(m) { var i = ORDER.indexOf(m); return i > 0 ? ORDER[i - 1] : null; }
function unlocked(m) { var p = prevMode(m); return !p || getBest(p) >= UNLOCK; }

/* ------------------------------------------------------------------ data */
var dataPromise = null;
function loadData() {
  if (!dataPromise) dataPromise = fetch(DATA_URL, { cache: "no-cache" })
    .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(function (d) {
      var all = d.cards.map(function (x) { return { n: x[0], id: x[1], c: x[2], r: x[3], s: x[4], cn: x[5] }; });
      all.sort(function (a, b) { return a.c - b.c; });
      var pools = {};
      ORDER.forEach(function (m) { pools[m] = all.filter(MODES[m].pool); });
      return { generated: d.generated, pools: pools };
    })
    .catch(function (e) { dataPromise = null; throw e; });
  return dataPromise;
}

function image(c) { return "https://cards.scryfall.io/normal/front/" + c.id[0] + "/" + c.id[1] + "/" + c.id + ".jpg"; }
function scryfall(c) { return "https://scryfall.com/card/" + c.s + "/" + encodeURIComponent(c.cn); }
function euros(cents) { return (cents / 100).toLocaleString("fr-FR", { style: "currency", currency: "EUR" }); }
function preload(c) { if (c) { var i = new Image(); i.src = image(c); } }

/** First index in the (price-sorted) pool whose price is >= cents. */
function lowerBound(pool, cents) {
  var lo = 0, hi = pool.length;
  while (lo < hi) { var mid = (lo + hi) >> 1; if (pool[mid].c < cents) lo = mid + 1; else hi = mid; }
  return lo;
}

/** A card to compare with `a`: dearer or cheaper within the mode's ratio, not seen yet; or null. */
function pickNext(pool, a, mode, seen) {
  var m = MODES[mode], r0 = m.ratio[0], r1 = m.ratio[1];
  var ranges = [
    [Math.max(a.c * r0, a.c + m.gap), a.c * r1],               // dearer
    [a.c / r1, Math.min(a.c / r0, a.c - m.gap)],               // cheaper
  ].map(function (r) { return [lowerBound(pool, Math.ceil(r[0])), lowerBound(pool, Math.floor(r[1]) + 1)]; })
   .filter(function (r) { return r[1] > r[0]; });
  for (var tries = 0; tries < 40 && ranges.length; tries++) {
    var r = ranges[Math.floor(Math.random() * ranges.length)];
    var c = pool[r[0] + Math.floor(Math.random() * (r[1] - r[0]))];
    if (!seen[c.id]) return c;
  }
  return null;
}

/** A fresh pair: a random first card that has a partner. */
function freshPair(pool, mode, seen) {
  for (var tries = 0; tries < 60; tries++) {
    var a = pool[Math.floor(Math.random() * pool.length)];
    if (seen[a.id]) continue;
    var b = pickNext(pool, a, mode, seen);
    if (b) return [a, b];
  }
  return null;
}

function getBest(mode) { try { return parseInt(localStorage.getItem(BEST_KEY + mode), 10) || 0; } catch (e) { return 0; } }
function setBest(mode, n) { try { localStorage.setItem(BEST_KEY + mode, String(n)); } catch (e) { /* private mode */ } }

/* ------------------------------------------------------------------ pieces */
function Card(p) {
  var c = p.card;
  return h("figure", { className: "pc-card" + (p.state ? " is-" + p.state : "") },
    h("div", { className: "pc-card__img" },
      h("img", { key: c.id, src: image(c), alt: c.n, loading: "eager", decoding: "async" })),
    h("figcaption", { className: "pc-card__price" }, p.children));
}

/** The hidden price, counted up from 0 once revealed. */
function CountUp(p) {
  var s = useState(0), v = s[0], setV = s[1];
  useEffect(function () {
    var t0 = performance.now(), id;
    function step(now) {
      var k = Math.min(1, (now - t0) / REVEAL_MS);
      setV(Math.round(p.cents * (1 - Math.pow(1 - k, 3))));
      if (k < 1) id = requestAnimationFrame(step);
    }
    id = requestAnimationFrame(step);
    return function () { cancelAnimationFrame(id); };
  }, [p.cents]);
  return h("span", { className: "pc-price title-md" }, euros(v));
}

/* ------------------------------------------------------------------ screens */
function Intro(p) {
  return h("div", { className: "pc-intro" },
    h("header", { className: "bar" },
      h(A.Button, { variant: "secondary", icon: "arrow-left", "aria-label": "Tous les jeux", onClick: p.onExit }),
      h("span"), h("span")),
    h("div", null,
      h("p", { className: "ar-eyebrow eyebrow pc-eyebrow" }, h(A.Badge, { tone: "brass", icon: false }, "Nouveau"), " Cote des cartes"),
      h("h1", { className: "title-xl" }, "Plus cher ou moins cher ?")),
    h("p", { className: "flavor" }, "Une carte et son prix. La suivante vaut-elle plus, ou moins ? Enchaîne sans te tromper."),
    h("div", { className: "pc-modes", role: "group", "aria-label": "Difficulté" }, ORDER.map(function (m) {
      var best = getBest(m), md = MODES[m], open = unlocked(m), before = prevMode(m);
      return h("button", { key: m, type: "button", className: "pc-mode" + (open ? "" : " is-locked"),
                           disabled: !p.data || !open, onClick: function () { p.onStart(m); } },
        h("span", { className: "pc-mode__head" },
          md.icon ? h(A.Icon, { name: md.icon, size: 20 }) : null,
          h("span", { className: "title-sm" }, md.name)),
        h("span", { className: "pc-mode__desc caption" }, md.desc),
        h("span", { className: "pc-mode__best label" },
          !open ? "Verrouillé · fais " + UNLOCK + " d'affilée en " + MODES[before].name :
          best ? "Record : " + best : "Pas encore de record"));
    })),
    h("div", { className: "push" },
      p.error ? h("p", { className: "error caption" }, p.error) :
      !p.data ? h("p", { className: "meta caption" }, "Chargement des prix…") :
      h("p", { className: "meta caption" }, "Prix Cardmarket (tendance) via ",
        h("a", { href: "https://scryfall.com", target: "_blank", rel: "noopener" }, "Scryfall"),
        ", mis à jour le " + new Date(p.data.generated).toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" }) + "."),
      h("p", { className: "legal caption" },
        "Contenu de fan non officiel, autorisé par la ",
        h("a", { href: "https://company.wizards.com/fancontentpolicy", target: "_blank", rel: "noopener" }, "Fan Content Policy"),
        ". Non approuvé par Wizards. Images des cartes : Scryfall. ©Wizards of the Coast LLC.")));
}

function Play(p) {
  var pool = p.data.pools[p.mode];
  var seen = useRef({});
  var s1 = useState(function () {
    var pair = freshPair(pool, p.mode, seen.current);
    pair.forEach(function (c) { seen.current[c.id] = true; });
    return pair;
  }), pair = s1[0], setPair = s1[1];
  var s2 = useState(0), streak = s2[0], setStreak = s2[1];
  var s3 = useState(null), result = s3[0], setResult = s3[1];     // null | { ok, guess }
  var s4 = useState(null), upcoming = s4[0], setUpcoming = s4[1];
  var t = useRef(null);
  var a = pair[0], b = pair[1];

  useEffect(function () { return function () { clearTimeout(t.current); }; }, []);
  useEffect(function () {                     // the card after b, chosen now so its image can load
    var n = pickNext(pool, b, p.mode, seen.current);
    setUpcoming(n); preload(n);
  }, [b.id]);
  useEffect(function () {
    function onKey(e) {
      if (e.key === "ArrowLeft") answer("less");
      else if (e.key === "ArrowRight") answer("more");
    }
    window.addEventListener("keydown", onKey);
    return function () { window.removeEventListener("keydown", onKey); };
  });

  function answer(guess) {
    if (result) return;
    var ok = guess === (b.c > a.c ? "more" : "less");
    setResult({ ok: ok, guess: guess });
    t.current = setTimeout(function () {
      if (!ok) { p.onOver({ streak: streak, a: a, b: b, guess: guess }); return; }
      setStreak(streak + 1);
      var next = upcoming && !seen.current[upcoming.id] ? [b, upcoming] : freshPair(pool, p.mode, seen.current);
      if (!next) { p.onOver({ streak: streak + 1, a: a, b: b, guess: guess, finished: true }); return; }
      next.forEach(function (c) { seen.current[c.id] = true; });
      setResult(null); setPair(next);
    }, REVEAL_MS + NEXT_MS - (ok ? 0 : 300));
  }

  return h("div", { className: "pc-play" },
    h("header", { className: "bar" },
      h(A.Button, { variant: "secondary", icon: "close", "aria-label": "Quitter la partie", onClick: p.onQuit }),
      h("p", { className: "title-sm pc-streak", "aria-live": "polite" },
        h(A.Icon, { name: "crown", size: 20 }), " ", streak),
      h("span", { className: "pc-mode-tag label" }, MODES[p.mode].name)),
    h("main", { className: "pc-board" },
      h("div", { className: "pc-pair" },
        h(Card, { card: a }, h("span", { className: "pc-price title-md" }, euros(a.c))),
        h("span", { className: "pc-vs label", "aria-hidden": "true" }, "vs"),
        h(Card, { card: b, state: result ? (result.ok ? "ok" : "ko") : null },
          result ? h(CountUp, { cents: b.c }) : h("span", { className: "pc-price pc-price--hidden title-md" }, "? €"))),
      h("p", { className: "pc-question body" },
        h("strong", null, b.n), " vaut-elle plus ou moins que ", h("strong", null, a.n), " ?"),
      h("div", { className: "pc-answers" },
        h(A.Button, { variant: "secondary", size: "lg", icon: "arrow-left", disabled: !!result,
                      className: result && result.guess === "less" ? "is-picked" : null,
                      onClick: function () { answer("less"); } }, "Moins cher"),
        h(A.Button, { variant: "primary", size: "lg", iconEnd: "arrow-right", disabled: !!result,
                      className: result && result.guess === "more" ? "is-picked" : null,
                      onClick: function () { answer("more"); } }, "Plus cher")),
      h("p", { className: "pc-verdict label", role: "status" },
        result ? (result.ok ? "Bien vu !" : "Raté !") : " ")));
}

function share(mode, n) {
  var text = "J'ai enchaîné " + n + " bonne" + (n > 1 ? "s" : "") + " réponse" + (n > 1 ? "s" : "") +
    " en mode " + MODES[mode].name + " sur « Plus cher ou moins cher ? ». Tu fais mieux ?";
  var url = location.href.split("#")[0] + "#plus-cher";
  if (navigator.share) return navigator.share({ title: "Plus cher ou moins cher ?", text: text, url: url })
    .then(function () { return "shared"; }, function () { return null; });
  if (navigator.clipboard) return navigator.clipboard.writeText(text + " " + url).then(function () { return "copied"; }, function () { return "failed"; });
  return Promise.resolve("failed");
}

function Over(p) {
  var o = p.over, s = useState(null), status = s[0], setStatus = s[1];
  return h("div", { className: "pc-over" },
    h("header", { className: "bar" },
      h(A.Button, { variant: "secondary", icon: "arrow-left", "aria-label": "Retour au choix de la difficulté", onClick: p.onHome }),
      h("span"), h("span")),
    h(A.Panel, { as: "section", className: "pc-score", "aria-labelledby": "pc-score" },
      h("p", { className: "ar-eyebrow eyebrow" }, o.finished ? "Plus aucune carte à comparer !" : "Série terminée · " + MODES[p.mode].name),
      h("p", { id: "pc-score", className: "pc-score__n" }, o.streak),
      h("p", { className: "body" }, o.streak > 1 ? "bonnes réponses d'affilée" : "bonne réponse"),
      p.record ? h(A.Badge, { tone: "success", icon: "crown" }, "Nouveau record !") :
        h("p", { className: "caption pc-score__best" }, p.best ? "Record : " + p.best : "Pas encore de record"),
      p.unlocked ? h("p", { className: "pc-unlock body-strong", role: "status" },
        h(A.Icon, { name: MODES[p.unlocked].icon || "crown", size: 20 }), "Mode " + MODES[p.unlocked].name + " débloqué !") : null),
    o.finished ? null : h(A.Panel, { title: "La carte qui t'a eu", headingLevel: 2 },
      h("div", { className: "pc-recap" },
        [o.a, o.b].map(function (c, i) {
          return h("a", { key: c.id, className: "pc-recap__card", href: scryfall(c), target: "_blank", rel: "noopener" },
            h("img", { src: image(c), alt: c.n, loading: "lazy" }),
            h("span", { className: "pc-recap__price title-sm" + (i ? " is-wrong" : "") }, euros(c.c)));
        })),
      h("p", { className: "caption pc-recap__text" },
        o.b.n + " vaut " + euros(o.b.c) + ", " + (o.b.c > o.a.c ? "plus" : "moins") + " que " + o.a.n + " (" + euros(o.a.c) + ").")),
    h("div", { className: "pc-actions" },
      p.unlocked ? h(A.Button, { variant: "primary", size: "lg", block: true, icon: MODES[p.unlocked].icon || "arrow-right",
                                 onClick: function () { p.onNext(p.unlocked); } }, "Essayer le mode " + MODES[p.unlocked].name) : null,
      h(A.Button, { variant: p.unlocked ? "secondary" : "primary", size: "lg", block: true, icon: "replay", onClick: p.onReplay }, "Rejouer"),
      h(A.Button, { variant: "secondary", size: "lg", block: true, icon: "share",
                    onClick: function () { share(p.mode, o.streak).then(setStatus); } }, "Partager mon score"),
      status === "copied" ? h("p", { className: "caption meta", role: "status" }, "Copié, il n'y a plus qu'à coller.") :
      status === "failed" ? h("p", { className: "caption meta", role: "status" }, "Le partage n'est pas disponible ici.") : null,
      h(A.Button, { variant: "ghost", size: "md", onClick: p.onHome }, "Changer de difficulté")));
}

/* ------------------------------------------------------------------ game */
function Game(p) {
  var s1 = useState("intro"), screen = s1[0], setScreen = s1[1];
  var s2 = useState(null), data = s2[0], setData = s2[1];
  var s3 = useState(null), error = s3[0], setError = s3[1];
  var s4 = useState("facile"), mode = s4[0], setMode = s4[1];
  var s5 = useState(null), over = s5[0], setOver = s5[1];
  var s6 = useState(0), run = s6[0], setRun = s6[1];
  var s7 = useState({ best: 0, record: false, unlocked: null }), best = s7[0], setBestState = s7[1];

  useEffect(function () {
    loadData().then(setData).catch(function () { setError("Les prix ne sont pas encore disponibles. Reviens un peu plus tard."); });
  }, []);
  useEffect(function () { window.scrollTo(0, 0); }, [screen]);
  // Hardcore and Impossible: the dark Charnier theme, like the hardcore mode of « IA ou vraie carte ? »
  useEffect(function () {
    var dark = screen !== "intro" && !!MODES[mode].dark;
    if (dark) document.documentElement.setAttribute("data-theme", "charnier");
    else document.documentElement.removeAttribute("data-theme");
  }, [screen, mode]);
  useEffect(function () { return function () { document.documentElement.removeAttribute("data-theme"); }; }, []);

  function start(m) {
    if (!data || !freshPair(data.pools[m], m, {})) { setError("Pas assez de cartes pour ce mode."); return; }
    setMode(m); setRun(run + 1); setScreen("play");
  }
  function end(o) {
    var prev = getBest(mode), record = o.streak > prev;
    if (record) setBest(mode, o.streak);
    var next = ORDER[ORDER.indexOf(mode) + 1];
    setBestState({ best: Math.max(prev, o.streak), record: record && o.streak > 0,
                   unlocked: next && prev < UNLOCK && o.streak >= UNLOCK ? next : null });
    setOver(o); setScreen("over");
  }

  var body;
  if (screen === "intro") body = h(Intro, { data: data, error: error, onStart: start, onExit: p.onExit });
  else if (screen === "play") body = h(Play, { key: run, data: data, mode: mode, onOver: end, onQuit: function () { setScreen("intro"); } });
  else body = h(Over, { over: over, mode: mode, best: best.best, record: best.record, unlocked: best.unlocked,
                        onNext: function (m) { start(m); },
                        onReplay: function () { start(mode); }, onHome: function () { setScreen("intro"); } });
  return h("div", { className: "app pc", "data-screen": screen }, body);
}

window.MTG.games.push({
  id: "plus-cher",
  title: "Plus cher ou moins cher ?",
  pitch: "Une carte, son prix. La suivante vaut-elle plus ou moins ? Enchaîne les bonnes réponses.",
  icon: "crown",
  details: "4 difficultés à débloquer · prix mis à jour chaque semaine",
  isNew: true,
  order: 3,
  component: Game,
  lastResult: function () {
    var parts = ORDER.filter(getBest).map(function (m) { return MODES[m].name + " " + getBest(m); });
    return parts.length ? "Tes records : " + parts.join(" · ") : null;
  },
});
})();
