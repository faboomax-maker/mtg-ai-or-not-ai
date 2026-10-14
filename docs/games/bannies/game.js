/* Carte bannie ? — a card; in which formats is it banned: Modern, Legacy, Duel Commander, or nowhere?
   Data: docs/data/bannies.json, from Scryfall's legalities, refreshed every day (pipeline/bannies.py),
   with "decoys": cards legal everywhere that look like they could be banned.
   Registered in window.MTG.games; the hub (app.js) mounts it with { onExit }. */
(function () {
"use strict";
var A = window.Artifice, h = React.createElement;
var useState = React.useState, useEffect = React.useEffect, useRef = React.useRef;
var ROUND = 10, BEST_KEY = "bannies-best";
var FORMATS = [{ bit: 1, name: "Modern" }, { bit: 2, name: "Legacy" }, { bit: 4, name: "Duel Commander" }];

function shuffle(a) {
  for (var i = a.length - 1; i > 0; i--) { var j = Math.floor(Math.random() * (i + 1)); var t = a[i]; a[i] = a[j]; a[j] = t; }
  return a;
}
function getBest() { try { return parseInt(localStorage.getItem(BEST_KEY), 10) || 0; } catch (e) { return 0; } }
function setBest(n) { try { localStorage.setItem(BEST_KEY, String(n)); } catch (e) { /* private mode */ } }
function image(id, size) { return "https://cards.scryfall.io/" + (size || "normal") + "/front/" + id[0] + "/" + id[1] + "/" + id + ".jpg"; }
function fmtDate(d) { return new Date(d).toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" }); }

var dataPromise = null;
function loadData() {
  if (!dataPromise) dataPromise = fetch("data/bannies.json", { cache: "no-cache" })
    .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .catch(function (e) { dataPromise = null; throw e; });
  return dataPromise;
}

/** A round: 5 to 7 banned cards, the cards banned in only 1 or 2 formats twice as likely (that's
    where one ticks too many or too few), then decoys taken in turn from each kind: ex-banned,
    banned elsewhere, same mechanic as a banned card, "suspicious". */
var KINDS = ["debannie", "ailleurs", "cousine", "suspecte"];
function weightedPick(list, n) {
  var bag = [];
  list.forEach(function (c) { var w = c[2] === 7 ? 1 : 2; for (var i = 0; i < w; i++) bag.push(c); });
  var out = [], seen = {};
  shuffle(bag).forEach(function (c) { if (out.length < n && !seen[c[0]]) { seen[c[0]] = 1; out.push(c); } });
  return out;
}
function newRound(d) {
  var nb = Math.min(d.banned.length, 5 + Math.floor(Math.random() * 3));
  var banned = weightedPick(d.banned, nb);
  var pools = Array.isArray(d.decoys) ? { suspecte: d.decoys } : d.decoys, decoys = [], seen = {};
  var lists = KINDS.map(function (k) { return shuffle((pools[k] || []).slice()); });
  for (var turn = shuffle([0, 1, 2, 3]), i = 0; decoys.length < ROUND - nb && i < 400; i++) {
    var l = lists[turn[i % 4]], c = l && l.shift();
    if (c && !seen[c[0]]) { seen[c[0]] = 1; decoys.push(c); }
  }
  return shuffle(banned.concat(decoys)).map(function (c) { return { n: c[0], id: c[1], mask: c[2], why: c[3] || "" }; });
}

function quip(score) {
  return score === ROUND ? "Sans faute. Tu lis les annonces de bannissement comme d'autres lisent leur horoscope." :
         score >= 7 ? "Solide. Tu as déjà perdu un deck à cause d'un ban, ça se sent." :
         score >= 4 ? "Moyen. Vérifie quand même ta liste avant le prochain tournoi." :
                      "Ton deck est probablement illégal dans trois formats, et tu ne le sais même pas.";
}

/* ------------------------------------------------------------------ screens */
function Intro(p) {
  var best = getBest();
  return h("div", { className: "bn-intro" },
    h("header", { className: "bar" },
      h(A.Button, { variant: "secondary", icon: "arrow-left", "aria-label": "Tous les jeux", onClick: p.onExit }),
      h("span"), h("span")),
    h("div", null,
      h("p", { className: "ar-eyebrow eyebrow bn-eyebrow" }, h(A.Badge, { tone: "brass", icon: false }, "Nouveau"), " Listes de bannissement"),
      h("h1", { className: "title-xl" }, "Carte bannie ?")),
    h("p", { className: "flavor" }, "Une carte : est-elle bannie en Modern, en Legacy, en Duel Commander… ou nulle part ?"),
    h(A.Panel, { title: "Comment ça marche", headingLevel: 2 },
      h("ul", { className: "rules body" },
        h("li", null, h("span", { className: "ic-m" }, h(A.Icon, { name: "check" })),
          h("span", null, "Coche tous les formats où elle est bannie, ou « Nulle part ».")),
        h("li", null, h("span", { className: "ic-m" }, h(A.Icon, { name: "skull" })),
          h("span", null, "Méfie-toi : la moitié des cartes ont juste l'air d'être bannies.")),
        h("li", null, h("span", { className: "ic-m" }, h(A.Icon, { name: "d20" })),
          h("span", null, ROUND + " cartes par partie, toutes avec un cadre moderne (après Mirrodin).")))),
    h("div", { className: "push" },
      p.error ? h("p", { className: "error caption" }, p.error) :
      !p.data ? h("p", { className: "meta caption" }, "Chargement des listes…") :
      h("p", { className: "meta caption" }, (best ? "Ton record : " + best + " / " + ROUND + " · " : "") +
        "Listes à jour du " + fmtDate(p.data.generated)),
      h(A.Button, { variant: "primary", size: "lg", block: true, disabled: !p.data, onClick: p.onStart }, "Commencer"),
      h("p", { className: "legal caption" },
        "Légalités via ", h("a", { href: "https://scryfall.com", target: "_blank", rel: "noopener" }, "Scryfall"),
        ". En Duel Commander, seule la liste des cartes bannies du deck compte ici, pas celle des commandants. Contenu de fan non officiel, autorisé par la ",
        h("a", { href: "https://company.wizards.com/fancontentpolicy", target: "_blank", rel: "noopener" }, "Fan Content Policy"),
        ". ©Wizards of the Coast LLC.")));
}

function Question(p) {
  var c = p.card, picked = p.picked, done = p.result != null;
  var bottom = useRef(null);
  useEffect(function () { if (done && bottom.current) bottom.current.scrollIntoView({ behavior: "smooth", block: "end" }); }, [done]);
  function toggle(bit) {
    if (done) return;
    p.onPick(bit === 0 ? (picked === 0 ? null : 0) : ((picked || 0) ^ bit) || null);
  }
  function chip(bit, label) {
    var on = bit === 0 ? picked === 0 : picked != null && (picked & bit) !== 0;
    var truth = bit === 0 ? c.mask === 0 : (c.mask & bit) !== 0;
    var cls = "bn-chip" + (on ? " is-on" : "") + (done ? (truth ? " is-true" : " is-false") : "");
    return h("button", { key: label, type: "button", className: cls, "aria-pressed": on, disabled: done, onClick: function () { toggle(bit); } },
      h("span", { className: "bn-chip__box", "aria-hidden": "true" }, on ? "✓" : ""),
      h("span", { className: "bn-chip__label" }, label),
      done ? h("span", { className: "bn-chip__truth caption" }, bit === 0 ? (truth ? "Légale partout" : "") : truth ? "Bannie" : "Légale") : null);
  }
  return h("div", { className: "bn-play" },
    h("header", { className: "bar" },
      h(A.Button, { variant: "secondary", icon: "close", "aria-label": "Quitter", onClick: p.onQuit }),
      h("p", { className: "title-sm bn-count" }, "Carte " + (p.index + 1) + " / " + p.total),
      h("span", { className: "bn-score label" }, p.score + " ✓")),
    h("button", { type: "button", className: "bn-card", onClick: p.onZoom, "aria-label": "Agrandir " + c.n },
      h("img", { src: image(c.id), alt: c.n })),
    h("p", { className: "bn-q title-sm" }, "Où ", h("strong", null, c.n), " est-elle bannie ?"),
    h("div", { className: "bn-chips", role: "group", "aria-label": "Formats" },
      FORMATS.map(function (f) { return chip(f.bit, f.name); }), chip(0, "Nulle part")),
    !done ? h(A.Button, { variant: "primary", size: "lg", block: true, disabled: picked == null, onClick: p.onValidate }, "Valider") :
    h(A.Panel, { className: "bn-verdict" },
      h("p", { className: "bn-verdict__head title-sm", role: "status" },
        h(A.Badge, { tone: p.result ? "success" : "danger" }, p.result ? "Bien vu" : "Raté"),
        c.mask ? " Bannie en " + FORMATS.filter(function (f) { return c.mask & f.bit; }).map(function (f) { return f.name; }).join(", ") + "."
               : " Légale partout. C'était un piège."),
      !c.mask && c.why ? h("p", { className: "body bn-why" }, c.why + ".") : null,
      h(A.Button, { variant: "primary", size: "lg", block: true, iconEnd: "arrow-right", onClick: p.onNext },
        p.index + 1 < p.total ? "Carte suivante" : "Voir mon score")),
    h("div", { ref: bottom }));
}

function End(p) {
  return h("div", { className: "bn-end" },
    h("header", { className: "bar" },
      h(A.Button, { variant: "secondary", icon: "arrow-left", "aria-label": "Tous les jeux", onClick: p.onExit }),
      h("span"), h("span")),
    h(A.Panel, { as: "section", className: "bn-endpanel" },
      h("p", { className: "ar-eyebrow eyebrow" }, "Ton score"),
      h("p", { className: "bn-endscore" }, p.score + " / " + ROUND),
      h("p", { className: "flavor bn-quip" }, quip(p.score)),
      p.record ? h(A.Badge, { tone: "success", icon: "crown" }, "Nouveau record !") :
        h("p", { className: "caption meta" }, "Record : " + getBest() + " / " + ROUND)),
    h("div", { className: "bn-endactions" },
      h(A.Button, { variant: "primary", size: "lg", block: true, icon: "replay", onClick: p.onReplay }, "Rejouer"),
      h(A.Button, { variant: "ghost", size: "md", onClick: p.onExit }, "Tous les jeux")));
}

function Game(p) {
  var s1 = useState("intro"), screen = s1[0], setScreen = s1[1];
  var s2 = useState(null), data = s2[0], setData = s2[1];
  var s3 = useState(null), error = s3[0], setError = s3[1];
  var s4 = useState([]), deck = s4[0], setDeck = s4[1];
  var s5 = useState(0), index = s5[0], setIndex = s5[1];
  var s6 = useState(null), picked = s6[0], setPicked = s6[1];    // null | 0 (nowhere) | bit mask
  var s7 = useState(null), result = s7[0], setResult = s7[1];
  var s8 = useState(0), score = s8[0], setScore = s8[1];
  var s9 = useState(false), zoom = s9[0], setZoom = s9[1];
  var s10 = useState(false), record = s10[0], setRecord = s10[1];

  useEffect(function () {
    loadData().then(setData).catch(function () { setError("Les listes ne sont pas encore disponibles. Reviens un peu plus tard."); });
  }, []);
  useEffect(function () { window.scrollTo(0, 0); }, [screen, index]);
  useEffect(function () {
    if (!zoom) return;
    function onKey(e) { if (e.key === "Escape") setZoom(false); }
    window.addEventListener("keydown", onKey);
    return function () { window.removeEventListener("keydown", onKey); };
  }, [zoom]);

  function start() { setDeck(newRound(data)); setIndex(0); setPicked(null); setResult(null); setScore(0); setScreen("play"); }
  function validate() {
    var ok = picked === deck[index].mask;
    setResult(ok);
    if (ok) setScore(score + 1);
  }
  function next() {
    if (index + 1 < deck.length) { setIndex(index + 1); setPicked(null); setResult(null); return; }
    var rec = score > getBest();
    if (rec) setBest(score);
    setRecord(rec); setScreen("end");
  }

  var body;
  if (screen === "intro") body = h(Intro, { data: data, error: error, onStart: start, onExit: p.onExit });
  else if (screen === "play") body = h(Question, { card: deck[index], index: index, total: deck.length, score: score,
                                                   picked: picked, result: result, onPick: setPicked, onValidate: validate,
                                                   onNext: next, onZoom: function () { setZoom(true); },
                                                   onQuit: function () { setScreen("intro"); } });
  else body = h(End, { score: score, record: record, onReplay: start, onExit: p.onExit });
  return h("div", { className: "app bn", "data-screen": screen }, body,
    zoom && screen === "play" ? h("div", { className: "bn-zoom", role: "dialog", "aria-modal": "true", onClick: function () { setZoom(false); } },
      h("img", { src: image(deck[index].id, "large"), alt: deck[index].n }),
      h("p", { className: "caption" }, "Touche pour fermer")) : null);
}

window.MTG.games.push({
  id: "bannies",
  title: "Carte bannie ?",
  pitch: "Bannie en Modern, en Legacy, en Duel Commander… ou nulle part ? La moitié des cartes sont des pièges.",
  icon: "skull",
  details: ROUND + " cartes · listes à jour chaque jour",
  isNew: true,
  order: 6,
  component: Game,
  lastResult: function () { var b = getBest(); return b ? "Ton record : " + b + " / " + ROUND : null; },
});
})();
