/* Est-ce légal ? — game situations drawn as a small board (real card images), and one question:
   is this play allowed by the rules? Situations: games/legal/scenarios.json. Only the situations whose
   cards all match their current Oracle text are played (data/legal-cards.json, checked every day by
   pipeline/legal_check.py). Registered in window.MTG.games; the hub (app.js) mounts it with { onExit }. */
(function () {
"use strict";
var A = window.Artifice, h = React.createElement;
var useState = React.useState, useEffect = React.useEffect, useRef = React.useRef;
var ROUND = 10, BEST_KEY = "legal-best";        // + "-difficile" for the hard mode
var MODES = {
  facile:    { name: "Facile", desc: "Les grands classiques : split second, mal de l'invocation, taxe de commandant…" },
  difficile: { name: "Difficile", desc: "Les vrais cas limites : couches, dépendances, actions spéciales, coûts « sans payer »…", icon: "skull" },
};
var MANA_IMG = { W: 1, U: 1, B: 1, R: 1, G: 1 };   // games/guildes/img/mana/<w|u|b|r|g>.webp

function shuffle(a) {
  for (var i = a.length - 1; i > 0; i--) { var j = Math.floor(Math.random() * (i + 1)); var t = a[i]; a[i] = a[j]; a[j] = t; }
  return a;
}
function key(mode) { return mode === "difficile" ? BEST_KEY + "-difficile" : BEST_KEY; }
function getBest(mode) { try { return parseInt(localStorage.getItem(key(mode)), 10) || 0; } catch (e) { return 0; } }
function setBest(mode, n) { try { localStorage.setItem(key(mode), String(n)); } catch (e) { /* private mode */ } }
function modeOf(s) { return s.mode || "facile"; }
function roundSize(data, mode) { return Math.min(ROUND, data.scenarios.filter(function (s) { return modeOf(s) === mode; }).length); }

var dataPromise = null;
function loadData() {
  if (!dataPromise) dataPromise = Promise.all([
    fetch("games/legal/scenarios.json", { cache: "no-cache" }).then(function (r) { return r.json(); }),
    fetch("data/legal-cards.json", { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); }),
  ]).then(function (d) {
    var valid = {};
    d[1].valid.forEach(function (id) { valid[id] = true; });
    return { scenarios: d[0].scenarios.filter(function (s) { return valid[s.id]; }), cards: d[1].cards };
  }).catch(function (e) { dataPromise = null; throw e; });
  return dataPromise;
}

function image(cards, name, size) {
  var c = cards[name];
  if (!c) return "";
  return "https://cards.scryfall.io/" + (size || "normal") + "/front/" + c.id[0] + "/" + c.id[1] + "/" + c.id + ".jpg";
}

/* ------------------------------------------------------------------ text with mana symbols */
function ManaSym(p) {
  var s = p.s, st = useState(false), broken = st[0], setBroken = st[1];
  if (MANA_IMG[s] && !broken) return h("img", { className: "lg-sym lg-sym--img", src: "games/guildes/img/mana/" + s.toLowerCase() + ".webp",
                                                alt: "{" + s + "}", onError: function () { setBroken(true); } });
  return h("span", { className: "lg-sym lg-sym--" + (s === "T" ? "tap" : s.toLowerCase()), "aria-label": "{" + s + "}" }, s === "T" ? "↷" : s);
}
function Rich(p) {
  var parts = String(p.text || "").split(/(\{[^}]+\})/);
  return h(React.Fragment, null, parts.map(function (part, i) {
    var m = /^\{([^}]+)\}$/.exec(part);
    return m ? h(ManaSym, { key: i, s: m[1].toUpperCase() }) : part;
  }));
}

/* ------------------------------------------------------------------ the board */
function Card(p) {
  var c = p.card;
  return h("button", { type: "button", className: "lg-card lg-card--" + (p.size || "md") + (c.t ? " is-tapped" : ""),
                       onClick: function () { p.onZoom(c); }, "aria-label": c.n + (c.t ? " (engagée)" : "") + (c.f ? " (arrivée ce tour)" : "") + (c.note ? " — " + c.note : "") },
    c.fd ? h("span", { className: "lg-card__frame lg-card__back", "aria-hidden": "true" }, h("span", null, "Face cachée")) :
    h("span", { className: "lg-card__frame" }, h("img", { src: image(p.cards, c.n), alt: "", loading: "eager" })),
    c.f ? h("span", { className: "lg-card__new label" }, "Arrivée ce tour") : null,
    h("span", { className: "lg-card__name" }, c.n.split(",")[0]),
    c.note ? h("span", { className: "lg-card__note caption" }, h(Rich, { text: c.note })) : null);
}

function Row(p) {
  if (!p.list || !p.list.length) return p.empty ? h("p", { className: "lg-empty caption" }, p.empty) : null;
  return h("div", { className: "lg-row" }, p.list.map(function (c, i) {
    return h(Card, { key: i, card: c, cards: p.cards, size: p.size, onZoom: p.onZoom });
  }));
}

function Zone(p) {
  if (!p.list || !p.list.length) return null;
  return h("div", { className: "lg-zone" },
    h("p", { className: "lg-zone__label label" }, p.label),
    h(Row, { list: p.list, cards: p.cards, size: "sm", onZoom: p.onZoom }));
}

function Board(p) {
  var s = p.sc, cards = p.cards, z = p.onZoom;
  return h("section", { className: "lg-board", "aria-label": "Situation de jeu" },
    h("div", { className: "lg-side lg-side--opp" },
      h("p", { className: "lg-who label" }, "Adversaire",
        h("span", { className: "lg-life" }, "♥ " + s.opp.life),
        h("span", { className: "lg-hand" }, "✋ " + s.opp.hand)),
      h(Row, { list: s.opp.battlefield, cards: cards, onZoom: z, empty: "Aucun permanent" }),
      h(Zone, { label: "Son cimetière", list: s.opp.graveyard, cards: cards, onZoom: z })),
    h("div", { className: "lg-mid" },
      h("p", { className: "lg-phase label" }, s.phase),
      s.stack && s.stack.length ? h("div", { className: "lg-stack" },
        h("p", { className: "lg-zone__label label" }, "Pile"),
        s.stack.map(function (it, i) {
          return h("div", { key: i, className: "lg-stack__item" },
            h(Card, { card: it.card, cards: cards, size: "sm", onZoom: z }),
            h("span", { className: "lg-stack__label caption" }, it.label));
        })) : null),
    h("div", { className: "lg-side lg-side--you" },
      h(Row, { list: s.you.battlefield, cards: cards, onZoom: z, empty: "Aucun permanent" }),
      h("p", { className: "lg-who label" }, "Toi",
        h("span", { className: "lg-life" }, "♥ " + s.you.life),
        s.you.mana ? h("span", { className: "lg-mana" }, "Mana dispo : ", h(Rich, { text: s.you.mana })) :
                     h("span", { className: "lg-mana" }, "Pas de mana dispo"))),
    h("div", { className: "lg-zones" },
      h(Zone, { label: "Ta main", list: s.you.hand, cards: cards, onZoom: z }),
      h(Zone, { label: "Ton cimetière", list: s.you.graveyard, cards: cards, onZoom: z }),
      h(Zone, { label: "Exil", list: s.you.exile, cards: cards, onZoom: z }),
      h(Zone, { label: "Zone de commandement", list: s.you.command, cards: cards, onZoom: z })));
}

function Zoom(p) {
  useEffect(function () {
    function onKey(e) { if (e.key === "Escape" || e.key === "Enter" || e.key === " ") { e.preventDefault(); p.onClose(); } }
    window.addEventListener("keydown", onKey);
    return function () { window.removeEventListener("keydown", onKey); };
  }, []);
  return h("div", { className: "lg-zoom", role: "dialog", "aria-modal": "true", "aria-label": p.card.n, onClick: p.onClose },
    h("img", { className: "lg-zoom__img", src: image(p.cards, p.card.n, "large"), alt: p.card.n }),
    p.card.fd ? h("p", { className: "lg-zoom__note body" }, "Face cachée sur le champ de bataille (tu sais que c'est cette carte).") : null,
    p.card.note || p.card.f || p.card.t ? h("p", { className: "lg-zoom__note body" },
      [p.card.t ? "Engagée" : null, p.card.f ? "Arrivée ce tour" : null, p.card.note].filter(Boolean).join(" · ")) : null,
    h("p", { className: "lg-zoom__hint caption" }, "Touche pour fermer"));
}

/* ------------------------------------------------------------------ screens */
function quip(score, total) {
  var r = score / total;
  return r === 1 ? "Sans faute. Tu peux passer arbitre niveau 1, ou au moins arrêter de te faire avoir à la table." :
         r >= 0.7 ? "Solide. Ton playgroup a intérêt à relire ses cartes avant de jouer contre toi." :
         r >= 0.4 ? "Correct. Tu joues un peu « à la maison », avoue." :
                    "Ton style de jeu, c'est surtout « attends, je rembobine ».";
}

function Intro(p) {
  var best = getBest();
  return h("div", { className: "lg-intro" },
    h("header", { className: "bar" },
      h(A.Button, { variant: "secondary", icon: "arrow-left", "aria-label": "Tous les jeux", onClick: p.onExit }),
      h("span"), h("span")),
    h("div", null,
      h("p", { className: "ar-eyebrow eyebrow lg-eyebrow" }, h(A.Badge, { tone: "brass", icon: false }, "Nouveau"), " Règles du jeu"),
      h("h1", { className: "title-xl" }, "Est-ce légal ?")),
    h("p", { className: "flavor" }, "Une situation de jeu, un coup tenté. Les règles le permettent-elles ?"),
    h(A.Panel, { title: "Comment ça marche", headingLevel: 2 },
      h("ul", { className: "rules body" },
        h("li", null, h("span", { className: "ic-m" }, h(A.Icon, { name: "d20" })),
          h("span", null, "Jusqu'à " + ROUND + " situations tirées au hasard, en mode facile ou difficile.")),
        h("li", null, h("span", { className: "ic-m" }, h(A.Icon, { name: "info" })),
          h("span", null, "Touche une carte pour la lire en grand.")),
        h("li", null, h("span", { className: "ic-m" }, h(A.Icon, { name: "chalice" })),
          h("span", null, "En difficile, certaines questions demandent le résultat (force, endurance, blessures…).")),
        h("li", null, h("span", { className: "ic-m" }, h(A.Icon, { name: "check" })),
          h("span", null, "« Légal » veut dire permis par les règles du jeu, pas par les formats ni les listes de bannissement.")))),
    h("div", { className: "lg-modes", role: "group", "aria-label": "Difficulté" }, ["facile", "difficile"].map(function (m) {
      var md = MODES[m], n = p.data ? roundSize(p.data, m) : 0, best = getBest(m);
      return h("button", { key: m, type: "button", className: "lg-mode", disabled: !n, onClick: function () { p.onStart(m); } },
        h("span", { className: "lg-mode__head" }, md.icon ? h(A.Icon, { name: md.icon, size: 20 }) : null, h("span", { className: "title-sm" }, md.name)),
        h("span", { className: "lg-mode__desc caption" }, md.desc),
        h("span", { className: "lg-mode__best label" }, best ? "Record : " + best + " / " + n : n ? n + " situations" : "\u00a0"));
    })),
    h("div", { className: "push" },
      p.error ? h("p", { className: "error caption" }, p.error) :
      !p.data ? h("p", { className: "meta caption" }, "Chargement des situations…") : null,
      h("p", { className: "legal caption" },
        "Textes Oracle vérifiés chaque jour via ", h("a", { href: "https://scryfall.com", target: "_blank", rel: "noopener" }, "Scryfall"),
        ". Contenu de fan non officiel, autorisé par la ",
        h("a", { href: "https://company.wizards.com/fancontentpolicy", target: "_blank", rel: "noopener" }, "Fan Content Policy"),
        ". ©Wizards of the Coast LLC.")));
}

function Question(p) {
  var sc = p.sc, ans = p.answer, choice = sc.type === "choice";
  var ok = ans != null && ans === (choice ? sc.answer : sc.legal);
  var bottom = useRef(null);
  useEffect(function () { if (ans != null && bottom.current) bottom.current.scrollIntoView({ behavior: "smooth", block: "end" }); }, [ans]);
  return h("div", { className: "lg-play" },
    h("header", { className: "bar" },
      h(A.Button, { variant: "secondary", icon: "close", "aria-label": "Quitter", onClick: p.onQuit }),
      h("p", { className: "title-sm lg-count" }, "Situation " + (p.index + 1) + " / " + p.total),
      h("span", { className: "lg-score label" }, p.score + " ✓")),
    h(Board, { sc: sc, cards: p.cards, onZoom: p.onZoom }),
    h("div", { className: "lg-action" },
      h("p", { className: "lg-action__label label" }, "Le coup"),
      h("p", { className: "body lg-action__text" }, h(Rich, { text: sc.action })),
      choice ? h("p", { className: "body-strong lg-action__question" }, sc.question) : null),
    choice && ans == null ? h("div", { className: "lg-options" }, sc.options.map(function (o, i) {
      return h(A.Button, { key: i, variant: "secondary", size: "lg", onClick: function () { p.onAnswer(i); } }, o);
    })) :
    ans == null ? h("div", { className: "lg-answers" },
      h(A.Button, { variant: "secondary", size: "lg", icon: "cross", onClick: function () { p.onAnswer(false); } }, "Illégal"),
      h(A.Button, { variant: "primary", size: "lg", icon: "check", onClick: function () { p.onAnswer(true); } }, "Légal")) :
    h(A.Panel, { className: "lg-verdict" + (ok ? " is-ok" : " is-ko") },
      h("p", { className: "lg-verdict__head title-sm", role: "status" },
        h(A.Badge, { tone: ok ? "success" : "danger" }, ok ? "Bien vu" : "Raté"),
        choice ? " Réponse : " + sc.options[sc.answer] + (ok ? "." : " (tu as dit " + sc.options[ans] + ").") :
                 " C'est " + (sc.legal ? "légal." : "illégal.")),
      h("p", { className: "body lg-verdict__why" }, h(Rich, { text: sc.why })),
      h("p", { className: "caption lg-verdict__rule" }, sc.rule),
      h(A.Button, { variant: "primary", size: "lg", block: true, iconEnd: "arrow-right", onClick: p.onNext },
        p.index + 1 < p.total ? "Situation suivante" : "Voir mon score")),
    h("div", { ref: bottom }));
}

function End(p) {
  return h("div", { className: "lg-end" },
    h("header", { className: "bar" },
      h(A.Button, { variant: "secondary", icon: "arrow-left", "aria-label": "Tous les jeux", onClick: p.onExit }),
      h("span"), h("span")),
    h(A.Panel, { as: "section", className: "lg-endpanel" },
      h("p", { className: "ar-eyebrow eyebrow" }, "Ton score · " + MODES[p.mode].name),
      h("p", { className: "lg-endscore" }, p.score + " / " + p.total),
      h("p", { className: "flavor lg-quip" }, quip(p.score, p.total)),
      p.record ? h(A.Badge, { tone: "success", icon: "crown" }, "Nouveau record !") :
        h("p", { className: "caption meta" }, "Record en " + MODES[p.mode].name.toLowerCase() + " : " + getBest(p.mode) + " / " + p.total)),
    h("div", { className: "lg-endactions" },
      h(A.Button, { variant: "primary", size: "lg", block: true, icon: "replay", onClick: p.onReplay }, "Rejouer"),
      h(A.Button, { variant: "ghost", size: "md", onClick: p.onExit }, "Tous les jeux")));
}

function Game(p) {
  var s1 = useState("intro"), screen = s1[0], setScreen = s1[1];
  var s2 = useState(null), data = s2[0], setData = s2[1];
  var s3 = useState(null), error = s3[0], setError = s3[1];
  var s4 = useState([]), deck = s4[0], setDeck = s4[1];
  var s5 = useState(0), index = s5[0], setIndex = s5[1];
  var s6 = useState(null), answer = s6[0], setAnswer = s6[1];
  var s7 = useState(0), score = s7[0], setScore = s7[1];
  var s8 = useState(null), zoom = s8[0], setZoom = s8[1];
  var s9 = useState(false), record = s9[0], setRecord = s9[1];
  var s10 = useState("facile"), mode = s10[0], setMode = s10[1];

  useEffect(function () {
    loadData().then(setData).catch(function () { setError("Les situations sont en cours de vérification. Reviens un peu plus tard."); });
  }, []);
  useEffect(function () { window.scrollTo(0, 0); }, [screen, index]);
  // hard mode: the dark Charnier theme, like the other games' hard modes
  useEffect(function () {
    if (mode === "difficile" && screen !== "intro") document.documentElement.setAttribute("data-theme", "charnier");
    else document.documentElement.removeAttribute("data-theme");
  }, [mode, screen]);
  useEffect(function () { return function () { document.documentElement.removeAttribute("data-theme"); }; }, []);

  function start(m) {
    m = m || mode;
    // ?s=<id>: that situation only (to check one)
    var only = (/[?&]s=([\w-]+)/.exec(location.search) || [])[1];
    var pool = only ? data.scenarios.filter(function (x) { return x.id === only; }) : [];
    var ofMode = data.scenarios.filter(function (x) { return modeOf(x) === m; });
    setMode(m);
    setDeck(pool.length ? pool : shuffle(ofMode).slice(0, ROUND));
    setIndex(0); setAnswer(null); setScore(0); setScreen("play");
  }
  function onAnswer(v) {
    if (answer != null) return;
    setAnswer(v);
    var sc = deck[index];
    if (v === (sc.type === "choice" ? sc.answer : sc.legal)) setScore(score + 1);
  }
  function next() {
    if (index + 1 < deck.length) { setIndex(index + 1); setAnswer(null); return; }
    var prev = getBest(mode), rec = deck.length === roundSize(data, mode) && score > prev;   // (not in ?s= mode)
    if (rec) setBest(mode, score);
    setRecord(rec); setScreen("end");
  }

  var body;
  if (screen === "intro") body = h(Intro, { data: data, error: error, onStart: start, onExit: p.onExit });
  else if (screen === "play") body = h(Question, { sc: deck[index], cards: data.cards, index: index, total: deck.length,
                                                   score: score, answer: answer, onAnswer: onAnswer, onNext: next,
                                                   onZoom: setZoom, onQuit: function () { setScreen("intro"); } });
  else body = h(End, { score: score, total: deck.length, record: record, mode: mode, onReplay: function () { start(mode); }, onExit: p.onExit });
  return h("div", { className: "app lg" + (mode === "difficile" && screen !== "intro" ? " is-hard" : ""), "data-screen": screen }, body,
    zoom ? h(Zoom, { card: zoom, cards: data.cards, onClose: function () { setZoom(null); } }) : null);
}

window.MTG.games.push({
  id: "legal",
  title: "Est-ce légal ?",
  pitch: "Des situations de jeu, un coup tenté : les règles le permettent-elles ? Split second, échappée, taxe de commandant…",
  icon: "info",
  details: "Facile et difficile (couches, dépendances…) · explication et règle à chaque réponse",
  isNew: true,
  order: 6,
  component: Game,
  lastResult: function () {
    var f = getBest("facile"), d = getBest("difficile");
    return f || d ? "Tes records · Facile " + f + " · Difficile " + d : null;
  },
});
})();
