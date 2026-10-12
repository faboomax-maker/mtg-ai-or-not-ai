/* Plus cher ou moins cher ? — a card and its value, then a second card: is it worth more or less?
   Chain right answers; one mistake ends the run. Two variants of the same game, swapped by a button
   on the home screen (the screen flips over):
     prix : Cardmarket trend price, in euros;
     pop  : « Plus ou moins populaire ? », Commander popularity (EDHREC rank, 1 = the most played).
   Data: docs/data/prix.json, made by pipeline/fetch_prices.py (Scryfall, refreshed every day).
   Registered in window.MTG.games; the hub (app.js) mounts it with { onExit }. */
(function () {
"use strict";
var A = window.Artifice, h = React.createElement;
var useState = React.useState, useEffect = React.useEffect, useRef = React.useRef;
var DATA_URL = "data/prix.json";
var REVEAL_MS = 650, NEXT_MS = 1100;            // value count-up, then the next pair
var FLIP_MS = 300;                              // each half of the screen flip
var VARIANT_KEY = "plus-cher-variant";
var UNLOCK = 5;                                 // a streak of 5 unlocks the next mode
var ORDER = ["facile", "moyen", "hardcore", "impossible"];

function pick(list) { return list[Math.floor(Math.random() * list.length)]; }
function euros(cents) { return (cents / 100).toLocaleString("fr-FR", { style: "currency", currency: "EUR" }); }
function rankText(r) { return "n° " + r.toLocaleString("fr-FR"); }
function fmtDate(d) { return new Date(d).toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" }); }

/* ---------------------------------------------------------------- variants
   Each variant: the value compared (val, lower first in the pools), whether b is the « more » answer,
   its texts, its jokes and its four modes. A mode: which cards (EDHREC rank r: 1 = the most played in
   Commander, 0 = unranked), the ratio between the two values and a minimum gap (in the value's units). */
var obscure = function (c) { return c.r === 0 || c.r > 3000; };
var VARIANTS = {
  prix: {
    title: "Plus cher ou moins cher ?", eyebrow: "Cote des cartes",
    flavor: "Une carte et son prix. La suivante vaut-elle plus, ou moins ? Enchaîne sans te tromper.",
    source: "Prix Cardmarket (tendance) via ", loading: "Chargement des prix…",
    val: function (c) { return c.c; }, fmt: euros, hidden: "? €",
    isMore: function (a, b) { return b.c > a.c; },
    less: "Moins cher", more: "Plus cher",
    question: function (a, b) { return [h("strong", { key: 1 }, b.n), " vaut-elle plus ou moins que ", h("strong", { key: 2 }, a.n), " ?"]; },
    recap: function (a, b) { return b.n + " vaut " + euros(b.c) + ", " + (b.c > a.c ? "plus" : "moins") + " que " + a.n + " (" + euros(a.c) + ")."; },
    best: "plus-cher-best-",
    switchTo: "pop", switchLabel: "Le fric, c'est surfait", switchHint: "Passer à « Plus ou moins populaire ? »",
    modes: {
      facile:     { name: "Facile", desc: "Des cartes connues, des prix bien différents.",
                    pool: function (c) { return c.r > 0 && c.r <= 2500; }, ratio: [3, 30], gap: 50 },
      moyen:      { name: "Moyen", desc: "Des cartes moins jouées, des prix plus proches.",
                    pool: function (c) { return c.r > 0 && c.r <= 12000; }, ratio: [1.6, 3], gap: 30 },
      hardcore:   { name: "Hardcore", desc: "Des cartes obscures que personne ne joue.",
                    pool: obscure, ratio: [1.6, 3], gap: 30, icon: "skull", dark: true },
      impossible: { name: "Impossible", desc: "Des cartes obscures, des prix au coude à coude.",
                    pool: obscure, ratio: [1.15, 1.6], gap: 20, icon: "candle", dark: true },
    },
    hits: ["Flair de trader.", "Le marché, c'est toi.", "Hype détectée.", "Bien vu !", "Tu sens la spéculation."],
    misses: ["Ton binder pleure.", "Spéculation ratée.", "Tu as acheté au plus haut.", "Raté !", "Cardmarket rigole."],
    special: function (a, b, ok, ratio) {
      if (!ok && ratio >= 10) return "Tu viens d'échanger un Ragavan contre un Shock.";
      if (b.c < 20) return "Bulk. Elle finira dans une boîte à chaussures.";
      if (b.c >= 5000) return "Double sleeve, toploader, coffre-fort.";
      return null;
    },
    quips: ["Même un bot de draft aurait fait mieux.", "Tu achètes tes cartes au poids, avoue.",
            "Ton binder est fier de toi. Un peu.", "Tu regardes Cardmarket aux toilettes, c'est ça ?",
            "Arrête de spéculer et va jouer.", "Tu bosses chez Cardmarket ou tu es juste malade ?"],
    share: function (mode, n) {
      return "J'ai fait " + n + " d'affilée en mode " + mode + " sur « Plus cher ou moins cher ? ». " +
        "Mes cartes, elles, ont perdu 40 % depuis que je les ai achetées. Tu fais mieux ?";
    },
  },
  pop: {
    title: "Plus ou moins populaire ?", eyebrow: "Popularité EDHREC",
    flavor: "Une carte et son rang sur EDHREC (n° 1 = la plus jouée en Commander). La suivante est-elle plus jouée, ou moins ? Enchaîne sans te tromper.",
    source: "Classement Commander d'EDHREC via ", loading: "Chargement du classement…",
    val: function (c) { return c.r; }, fmt: rankText, hidden: "n° ?",
    isMore: function (a, b) { return b.r < a.r; },             // more popular = a smaller rank
    less: "Moins jouée", more: "Plus jouée",
    question: function (a, b) { return [h("strong", { key: 1 }, b.n), " est-elle plus ou moins jouée que ", h("strong", { key: 2 }, a.n), " ?"]; },
    recap: function (a, b) {
      return b.n + " est " + rankText(b.r) + " sur EDHREC, " + (b.r < a.r ? "plus" : "moins") + " jouée que " + a.n + " (" + rankText(a.r) + ").";
    },
    best: "plus-pop-best-",
    switchTo: "prix", switchLabel: "Retour au capitalisme", switchHint: "Repasser à « Plus cher ou moins cher ? »",
    modes: {
      facile:     { name: "Facile", desc: "Des staples contre des cartes de niche.",
                    pool: function (c) { return c.r > 0 && c.r <= 3000; }, ratio: [4, 60], gap: 100 },
      moyen:      { name: "Moyen", desc: "Des cartes plus proches au classement.",
                    pool: function (c) { return c.r > 0 && c.r <= 12000; }, ratio: [2, 4], gap: 100 },
      hardcore:   { name: "Hardcore", desc: "Des cartes que seul leur propriétaire connaît.",
                    pool: function (c) { return c.r > 3000; }, ratio: [2, 4], gap: 200, icon: "skull", dark: true },
      impossible: { name: "Impossible", desc: "Des inconnues au coude à coude au classement.",
                    pool: function (c) { return c.r > 3000; }, ratio: [1.15, 1.6], gap: 150, icon: "candle", dark: true },
    },
    hits: ["Tu lis EDHREC au petit-déj.", "Staple détectée.", "Le méta, c'est toi.", "Bien vu !", "Netdecker confirmé."],
    misses: ["Ta pile de jank applaudit.", "Raté, c'est une staple.", "Ton deck Commander est un musée.", "Raté !", "EDHREC a honte de toi."],
    special: function (a, b, ok, ratio) {
      if (!ok && ratio >= 10) return "Tu viens de mettre un Sol Ring dans le sideboard.";
      if (b.r <= 100) return "Dans tous les decks. Même ceux qui n'en ont pas besoin.";
      if (b.r >= 20000) return "Jouée par trois personnes, dont son illustrateur.";
      return null;
    },
    quips: ["Tu n'as jamais ouvert EDHREC de ta vie, avoue.", "Ton deck, c'est 99 cartes que personne ne joue.",
            "Tu connais le méta. Un peu.", "Tu netdecks, avoue.",
            "Tu ES l'algorithme d'EDHREC.", "Touche de l'herbe. Et du carton."],
    share: function (mode, n) {
      return "J'ai fait " + n + " d'affilée en mode " + mode + " sur « Plus ou moins populaire ? ». " +
        "Mon deck, lui, n'est joué que par moi. Tu fais mieux ?";
    },
  },
};

function getBest(v, mode) { try { return parseInt(localStorage.getItem(VARIANTS[v].best + mode), 10) || 0; } catch (e) { return 0; } }
function setBest(v, mode, n) { try { localStorage.setItem(VARIANTS[v].best + mode, String(n)); } catch (e) { /* private mode */ } }
function prevMode(m) { var i = ORDER.indexOf(m); return i > 0 ? ORDER[i - 1] : null; }
function unlocked(v, m) { var p = prevMode(m); return !p || getBest(v, p) >= UNLOCK; }

/** The line under the cards once b's value is shown: a special case, or a random reaction. */
function reaction(V, a, b, ok) {
  var x = V.val(a), y = V.val(b), ratio = Math.max(x, y) / Math.min(x, y);
  return V.special(a, b, ok, ratio) || pick(ok ? V.hits : V.misses);
}
/** The verdict on a final streak. */
function quip(V, n) { return V.quips[n === 0 ? 0 : n <= 2 ? 1 : n <= 5 ? 2 : n <= 9 ? 3 : n <= 19 ? 4 : 5]; }

/* ------------------------------------------------------------------ data */
var dataPromise = null;
function loadData() {
  if (!dataPromise) dataPromise = fetch(DATA_URL, { cache: "no-cache" })
    .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(function (d) {
      var all = d.cards.map(function (x) { return { n: x[0], id: x[1], c: x[2], r: x[3], s: x[4], cn: x[5] }; });
      var pools = {};                              // pools[variant][mode], sorted by the variant's value
      Object.keys(VARIANTS).forEach(function (v) {
        var V = VARIANTS[v];
        var sorted = all.filter(function (c) { return V.val(c) > 0; })
          .sort(function (a, b) { return V.val(a) - V.val(b); });
        pools[v] = {};
        ORDER.forEach(function (m) { pools[v][m] = sorted.filter(V.modes[m].pool); });
      });
      return { generated: d.generated, pools: pools };
    })
    .catch(function (e) { dataPromise = null; throw e; });
  return dataPromise;
}

function image(c, size) { return "https://cards.scryfall.io/" + (size || "normal") + "/front/" + c.id[0] + "/" + c.id[1] + "/" + c.id + ".jpg"; }
function scryfall(c) { return "https://scryfall.com/card/" + c.s + "/" + encodeURIComponent(c.cn); }
function preload(c) { if (c) { var i = new Image(); i.src = image(c); } }

/** First index in the pool (sorted by val) whose value is >= x. */
function lowerBound(pool, val, x) {
  var lo = 0, hi = pool.length;
  while (lo < hi) { var mid = (lo + hi) >> 1; if (val(pool[mid]) < x) lo = mid + 1; else hi = mid; }
  return lo;
}

/** A card to compare with `a`: higher or lower value within the mode's ratio, not seen yet; or null. */
function pickNext(V, pool, a, mode, seen) {
  var m = V.modes[mode], r0 = m.ratio[0], r1 = m.ratio[1], x = V.val(a);
  var ranges = [
    [Math.max(x * r0, x + m.gap), x * r1],                     // higher
    [x / r1, Math.min(x / r0, x - m.gap)],                     // lower
  ].map(function (r) { return [lowerBound(pool, V.val, Math.ceil(r[0])), lowerBound(pool, V.val, Math.floor(r[1]) + 1)]; })
   .filter(function (r) { return r[1] > r[0]; });
  for (var tries = 0; tries < 40 && ranges.length; tries++) {
    var r = ranges[Math.floor(Math.random() * ranges.length)];
    var c = pool[r[0] + Math.floor(Math.random() * (r[1] - r[0]))];
    if (!seen[c.id]) return c;
  }
  return null;
}

/** A fresh pair: a random first card that has a partner. */
function freshPair(V, pool, mode, seen) {
  for (var tries = 0; tries < 60 && pool.length; tries++) {
    var a = pool[Math.floor(Math.random() * pool.length)];
    if (seen[a.id]) continue;
    var b = pickNext(V, pool, a, mode, seen);
    if (b) return [a, b];
  }
  return null;
}

/* ------------------------------------------------------------------ pieces */
function Card(p) {
  var c = p.card;
  return h("figure", { className: "pc-card" + (p.state ? " is-" + p.state : "") },
    h("button", { type: "button", className: "pc-card__img", "aria-label": "Agrandir " + c.n,
                  onClick: function () { p.onZoom(c); } },
      h("img", { key: c.id, src: image(c), alt: c.n, loading: "eager", decoding: "async" })),
    h("figcaption", { className: "pc-card__price" }, p.children));
}

/** A card shown full screen, in the large Scryfall size; a tap anywhere (or Escape) closes it. */
function Zoom(p) {
  var c = p.card;
  useEffect(function () {
    function onKey(e) { if (e.key === "Escape" || e.key === "Enter" || e.key === " ") { e.preventDefault(); p.onClose(); } }
    window.addEventListener("keydown", onKey);
    return function () { window.removeEventListener("keydown", onKey); };
  }, []);
  return h("div", { className: "pc-zoom", role: "dialog", "aria-modal": "true", "aria-label": c.n, onClick: p.onClose },
    h("img", { className: "pc-zoom__img", src: image(c, "large"), alt: c.n }),
    h("p", { className: "pc-zoom__hint caption" }, "Touche pour fermer"));
}

/** The hidden value, counted up from 0 once revealed. */
function CountUp(p) {
  var s = useState(0), v = s[0], setV = s[1];
  useEffect(function () {
    var t0 = performance.now(), id;
    function step(now) {
      var k = Math.min(1, (now - t0) / REVEAL_MS);
      setV(Math.round(p.value * (1 - Math.pow(1 - k, 3))));
      if (k < 1) id = requestAnimationFrame(step);
    }
    id = requestAnimationFrame(step);
    return function () { cancelAnimationFrame(id); };
  }, [p.value]);
  return h("span", { className: "pc-price title-md" }, p.fmt(v));
}

/* ------------------------------------------------------------------ screens */
function Intro(p) {
  var v = p.variant, V = VARIANTS[v];
  return h("div", { className: "pc-intro" },
    h("header", { className: "bar" },
      h(A.Button, { variant: "secondary", icon: "arrow-left", "aria-label": "Tous les jeux", onClick: p.onExit }),
      h("span"), h("span")),
    h("div", null,
      h("p", { className: "ar-eyebrow eyebrow pc-eyebrow" }, V.eyebrow),
      h("h1", { className: "title-xl" }, V.title)),
    h("p", { className: "flavor" }, V.flavor),
    h("div", { className: "pc-modes", role: "group", "aria-label": "Difficulté" }, ORDER.map(function (m) {
      var best = getBest(v, m), md = V.modes[m], open = unlocked(v, m), before = prevMode(m);
      return h("button", { key: m, type: "button", className: "pc-mode" + (open ? "" : " is-locked"),
                           disabled: !p.data || !open, onClick: function () { p.onStart(m); } },
        h("span", { className: "pc-mode__head" },
          md.icon ? h(A.Icon, { name: md.icon, size: 20 }) : null,
          h("span", { className: "title-sm" }, md.name)),
        h("span", { className: "pc-mode__desc caption" }, md.desc),
        h("span", { className: "pc-mode__best label" },
          !open ? "Verrouillé · fais " + UNLOCK + " d'affilée en " + V.modes[before].name :
          best ? "Record : " + best : "Pas encore de record"));
    })),
    h("div", { className: "push" },
      h("button", { type: "button", className: "pc-switch", onClick: p.onSwitch, disabled: p.flipping },
        h(A.Icon, { name: "swipe", size: 22 }),
        h("span", { className: "pc-switch__text" },
          h("span", { className: "pc-switch__label body-strong" }, V.switchLabel),
          h("span", { className: "pc-switch__hint caption" }, V.switchHint))),
      p.error ? h("p", { className: "error caption" }, p.error) :
      !p.data ? h("p", { className: "meta caption" }, V.loading) :
      h("p", { className: "meta caption" }, V.source,
        h("a", { href: "https://scryfall.com", target: "_blank", rel: "noopener" }, "Scryfall"),
        ", mis à jour le " + fmtDate(p.data.generated) + "."),
      h("p", { className: "legal caption" },
        "Contenu de fan non officiel, autorisé par la ",
        h("a", { href: "https://company.wizards.com/fancontentpolicy", target: "_blank", rel: "noopener" }, "Fan Content Policy"),
        ". Non approuvé par Wizards. Images des cartes : Scryfall. ©Wizards of the Coast LLC.")));
}

function Play(p) {
  var V = VARIANTS[p.variant], pool = p.data.pools[p.variant][p.mode];
  var nextMode = ORDER[ORDER.indexOf(p.mode) + 1] || null;
  var seen = useRef({});
  var s1 = useState(function () {
    var pair = freshPair(V, pool, p.mode, seen.current);
    pair.forEach(function (c) { seen.current[c.id] = true; });
    return pair;
  }), pair = s1[0], setPair = s1[1];
  var s2 = useState(0), streak = s2[0], setStreak = s2[1];
  var s3 = useState(null), result = s3[0], setResult = s3[1];     // null | { ok, guess, msg }
  var s4 = useState(null), upcoming = s4[0], setUpcoming = s4[1];
  var s5 = useState(null), zoom = s5[0], setZoom = s5[1];
  var t = useRef(null);
  var a = pair[0], b = pair[1];

  useEffect(function () { return function () { clearTimeout(t.current); }; }, []);
  useEffect(function () {                     // the card after b, chosen now so its image can load
    var n = pickNext(V, pool, b, p.mode, seen.current);
    setUpcoming(n); preload(n);
  }, [b.id]);
  useEffect(function () {
    function onKey(e) {
      if (zoom) return;
      if (e.key === "ArrowLeft") answer("less");
      else if (e.key === "ArrowRight") answer("more");
    }
    window.addEventListener("keydown", onKey);
    return function () { window.removeEventListener("keydown", onKey); };
  });

  function answer(guess) {
    if (result || zoom) return;
    var ok = guess === (V.isMore(a, b) ? "more" : "less");
    setResult({ ok: ok, guess: guess, msg: reaction(V, a, b, ok) });
    t.current = setTimeout(function () {
      if (!ok) { p.onOver({ streak: streak, a: a, b: b, guess: guess }); return; }
      setStreak(streak + 1); p.onProgress(streak + 1);
      var next = upcoming && !seen.current[upcoming.id] ? [b, upcoming] : freshPair(V, pool, p.mode, seen.current);
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
      h("span", { className: "pc-mode-tag label" }, V.modes[p.mode].name)),
    h("main", { className: "pc-board" },
      h("div", { className: "pc-pair" },
        h(Card, { card: a, onZoom: setZoom }, h("span", { className: "pc-price title-md" }, V.fmt(V.val(a)))),
        h("span", { className: "pc-vs label", "aria-hidden": "true" }, "vs"),
        h(Card, { card: b, onZoom: setZoom, state: result ? (result.ok ? "ok" : "ko") : null },
          result ? h(CountUp, { value: V.val(b), fmt: V.fmt }) : h("span", { className: "pc-price pc-price--hidden title-md" }, V.hidden))),
      h("p", { className: "pc-question body" }, V.question(a, b)),
      h("div", { className: "pc-answers" },
        h(A.Button, { variant: "secondary", size: "lg", icon: "arrow-left", disabled: !!result,
                      className: result && result.guess === "less" ? "is-picked" : null,
                      onClick: function () { answer("less"); } }, V.less),
        h(A.Button, { variant: "primary", size: "lg", iconEnd: "arrow-right", disabled: !!result,
                      className: result && result.guess === "more" ? "is-picked" : null,
                      onClick: function () { answer("more"); } }, V.more)),
      h("p", { className: "pc-verdict label" + (result ? "" : " is-hint"), role: "status" },
        result ? result.msg : "Touche une carte pour la lire en grand."),
      // from a streak of UNLOCK on, the next mode can be started right away (the record is kept)
      nextMode && streak >= UNLOCK ? h(A.Button, { variant: "ghost", size: "md", iconEnd: V.modes[nextMode].icon || "arrow-right",
                                                   className: "pc-skip", disabled: !!result,
                                                   onClick: function () { p.onSkip(nextMode, streak); } },
        "Trop facile ? Passer au mode " + V.modes[nextMode].name) : null),
    zoom ? h(Zoom, { card: zoom, onClose: function () { setZoom(null); } }) : null);
}

function share(V, mode, n) {
  var text = V.share(V.modes[mode].name, n);
  var url = location.href.split("#")[0] + "#plus-cher";
  if (navigator.share) return navigator.share({ title: V.title, text: text, url: url })
    .then(function () { return "shared"; }, function () { return null; });
  if (navigator.clipboard) return navigator.clipboard.writeText(text + " " + url).then(function () { return "copied"; }, function () { return "failed"; });
  return Promise.resolve("failed");
}

function Over(p) {
  var V = VARIANTS[p.variant], o = p.over, s = useState(null), status = s[0], setStatus = s[1];
  var md = V.modes[p.mode], next = p.unlocked ? V.modes[p.unlocked] : null;
  return h("div", { className: "pc-over" },
    h("header", { className: "bar" },
      h(A.Button, { variant: "secondary", icon: "arrow-left", "aria-label": "Retour au choix de la difficulté", onClick: p.onHome }),
      h("span"), h("span")),
    h(A.Panel, { as: "section", className: "pc-score", "aria-labelledby": "pc-score" },
      h("p", { className: "ar-eyebrow eyebrow" }, o.finished ? "Plus aucune carte à comparer !" : "Série terminée · " + md.name),
      h("p", { id: "pc-score", className: "pc-score__n" }, o.streak),
      h("p", { className: "body" }, o.streak > 1 ? "bonnes réponses d'affilée" : "bonne réponse"),
      h("p", { className: "flavor pc-quip" }, quip(V, o.streak)),
      p.record ? h(A.Badge, { tone: "success", icon: "crown" }, "Nouveau record !") :
        h("p", { className: "caption pc-score__best" }, p.best ? "Record : " + p.best : "Pas encore de record"),
      next ? h("p", { className: "pc-unlock body-strong", role: "status" },
        h(A.Icon, { name: next.icon || "crown", size: 20 }), "Mode " + next.name + " débloqué !") : null),
    o.finished ? null : h(A.Panel, { title: "La carte qui t'a eu", headingLevel: 2 },
      h("div", { className: "pc-recap" },
        [o.a, o.b].map(function (c, i) {
          return h("a", { key: c.id, className: "pc-recap__card", href: scryfall(c), target: "_blank", rel: "noopener" },
            h("img", { src: image(c), alt: c.n, loading: "lazy" }),
            h("span", { className: "pc-recap__price title-sm" + (i ? " is-wrong" : "") }, V.fmt(V.val(c))));
        })),
      h("p", { className: "caption pc-recap__text" }, V.recap(o.a, o.b))),
    h("div", { className: "pc-actions" },
      next ? h(A.Button, { variant: "primary", size: "lg", block: true, icon: next.icon || "arrow-right",
                           onClick: function () { p.onNext(p.unlocked); } }, "Essayer le mode " + next.name) : null,
      h(A.Button, { variant: next ? "secondary" : "primary", size: "lg", block: true, icon: "replay", onClick: p.onReplay }, "Rejouer"),
      h(A.Button, { variant: "secondary", size: "lg", block: true, icon: "share",
                    onClick: function () { share(V, p.mode, o.streak).then(setStatus); } }, "Partager mon score"),
      status === "copied" ? h("p", { className: "caption meta", role: "status" }, "Copié, il n'y a plus qu'à coller.") :
      status === "failed" ? h("p", { className: "caption meta", role: "status" }, "Le partage n'est pas disponible ici.") : null,
      h(A.Button, { variant: "ghost", size: "md", onClick: p.onHome }, "Changer de difficulté")));
}

/* ------------------------------------------------------------------ game */
function savedVariant() { try { return VARIANTS[localStorage.getItem(VARIANT_KEY)] ? localStorage.getItem(VARIANT_KEY) : "prix"; } catch (e) { return "prix"; } }
function reducedMotion() { return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches; }

function Game(p) {
  var s1 = useState("intro"), screen = s1[0], setScreen = s1[1];
  var s2 = useState(null), data = s2[0], setData = s2[1];
  var s3 = useState(null), error = s3[0], setError = s3[1];
  var s4 = useState("facile"), mode = s4[0], setMode = s4[1];
  var s5 = useState(null), over = s5[0], setOver = s5[1];
  var s6 = useState(0), run = s6[0], setRun = s6[1];
  var s7 = useState({ best: 0, record: false, unlocked: null }), best = s7[0], setBestState = s7[1];
  var s8 = useState(savedVariant), variant = s8[0], setVariant = s8[1];
  var s9 = useState(null), flip = s9[0], setFlip = s9[1];          // null | "out" | "in"
  var flipT = useRef([]), startBest = useRef(0);
  var V = VARIANTS[variant];

  useEffect(function () {
    loadData().then(setData).catch(function () { setError("Les données ne sont pas encore disponibles. Reviens un peu plus tard."); });
    return function () { flipT.current.forEach(clearTimeout); };
  }, []);
  useEffect(function () { window.scrollTo(0, 0); }, [screen]);
  // Hardcore and Impossible: the dark Charnier theme, like the hardcore mode of « IA ou vraie carte ? »
  useEffect(function () {
    var dark = screen !== "intro" && !!V.modes[mode].dark;
    if (dark) document.documentElement.setAttribute("data-theme", "charnier");
    else document.documentElement.removeAttribute("data-theme");
  }, [screen, mode, variant]);
  useEffect(function () { return function () { document.documentElement.removeAttribute("data-theme"); }; }, []);

  /** The other variant; the screen flips over (half turn out, swap, half turn in). */
  function switchVariant() {
    var to = V.switchTo;
    try { localStorage.setItem(VARIANT_KEY, to); } catch (e) { /* private mode */ }
    if (reducedMotion()) { setVariant(to); return; }
    setFlip("out");
    flipT.current = [
      setTimeout(function () { setVariant(to); setFlip("in"); window.scrollTo(0, 0); }, FLIP_MS),
      setTimeout(function () { setFlip(null); }, 2 * FLIP_MS),
    ];
  }
  function start(m) {
    if (!data || !freshPair(V, data.pools[variant][m], m, {})) { setError("Pas assez de cartes pour ce mode."); setScreen("intro"); return; }
    startBest.current = getBest(variant, m);
    setMode(m); setRun(run + 1); setScreen("play");
  }
  /** A streak reached during the run: kept as the record at once (it unlocks the next mode). */
  function progress(n) { if (n > getBest(variant, mode)) setBest(variant, mode, n); }
  function end(o) {
    var prev = startBest.current, record = o.streak > prev;
    if (record) setBest(variant, mode, o.streak);
    var next = ORDER[ORDER.indexOf(mode) + 1];
    setBestState({ best: Math.max(prev, o.streak), record: record && o.streak > 0,
                   unlocked: next && prev < UNLOCK && o.streak >= UNLOCK ? next : null });
    setOver(o); setScreen("over");
  }

  var body;
  if (screen === "intro") body = h(Intro, { variant: variant, data: data, error: error, flipping: !!flip,
                                            onStart: start, onExit: p.onExit, onSwitch: switchVariant });
  else if (screen === "play") body = h(Play, { key: run, variant: variant, data: data, mode: mode, onOver: end,
                                               onProgress: progress, onSkip: function (m, n) { progress(n); start(m); },
                                               onQuit: function () { setScreen("intro"); } });
  else body = h(Over, { variant: variant, over: over, mode: mode, best: best.best, record: best.record, unlocked: best.unlocked,
                        onNext: function (m) { start(m); },
                        onReplay: function () { start(mode); }, onHome: function () { setScreen("intro"); } });
  return h("div", { className: "app pc pc--" + variant + (flip ? " is-flip-" + flip : ""), "data-screen": screen }, body);
}

window.MTG.games.push({
  id: "plus-cher",
  title: "Plus cher ou moins cher ?",
  pitch: "Une carte, son prix. La suivante vaut-elle plus ou moins ? Et en bonus : plus ou moins populaire ?",
  icon: "crown",
  details: "2 variantes · 4 difficultés à débloquer · données mises à jour chaque jour",
  order: 3,
  component: Game,
  lastResult: function () {
    var parts = [];
    Object.keys(VARIANTS).forEach(function (v) {
      var r = ORDER.filter(function (m) { return getBest(v, m); })
        .map(function (m) { return VARIANTS[v].modes[m].name + " " + getBest(v, m); });
      if (r.length) parts.push((v === "prix" ? "Prix : " : "Popularité : ") + r.join(", "));
    });
    return parts.length ? "Tes records · " + parts.join(" · ") : null;
  },
});
})();
