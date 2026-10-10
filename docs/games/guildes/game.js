/* Quelle guilde de Ravnica es-tu ? — a 15-question personality quiz (data in data.js).
   Registered in window.MTG.games; the hub (app.js) mounts it with { onExit }. */
(function () {
"use strict";
var A = window.Artifice, h = React.createElement;
var useState = React.useState, useEffect = React.useEffect, useRef = React.useRef;
var D = window.MTG.guildesData, Q = D.QUESTIONS, C = D.COLORS;
var PICK_MS = 180;                                   // the picked answer stays lit this long
var LAST_KEY = "guildes-last";

/* ------------------------------------------------------------------ scoring */
function tally(answers) {
  var s = { W: 0, U: 0, B: 0, R: 0, G: 0 };
  answers.forEach(function (c) { if (c) s[c]++; });
  return s;
}

/** The two guild colors, or { ask: [colors] } when a tie needs the extra question.
    `picks` are the answers already given to that question, in order. */
function decide(scores, picks) {
  var sel = [], k = 0;
  while (sel.length < 2) {
    var rest = D.ORDER.filter(function (c) { return sel.indexOf(c) < 0; });
    var top = Math.max.apply(null, rest.map(function (c) { return scores[c]; }));
    var cand = rest.filter(function (c) { return scores[c] === top; });
    if (cand.length <= 2 - sel.length) { sel = sel.concat(cand); continue; }
    if (picks[k] && cand.indexOf(picks[k]) >= 0) { sel.push(picks[k++]); continue; }
    return { ask: cand };
  }
  sel.sort(function (a, b) { return D.ORDER.indexOf(a) - D.ORDER.indexOf(b); });
  return { pair: sel, guild: D.GUILDS[sel.join("")] };
}

function remember(guild) { try { localStorage.setItem(LAST_KEY, guild.name); } catch (e) { /* private mode */ } }
function lastGuild() { try { return localStorage.getItem(LAST_KEY); } catch (e) { return null; } }

/* ------------------------------------------------------------------ emblem */
/* The result's crest: a shield split between the guild's two colors, with its initial.
   An original design (not the official guild symbol). To show your own image instead,
   give the guild a `symbol: "games/guildes/img/<id>.svg"` in data.js. */
function Emblem(p) {
  var g = p.guild, a = C[p.pair[0]], b = C[p.pair[1]], id = "em-" + g.id;
  if (g.symbol) return h("img", { className: "emblem emblem--img", src: g.symbol, alt: "Symbole " + g.name, width: 168, height: 168 });
  var shield = "M80 8 L146 30 V82 C146 124 116 150 80 164 C44 150 14 124 14 82 V30 Z";
  return h("svg", { className: "emblem", viewBox: "0 0 160 172", width: 168, height: 180, role: "img", "aria-label": "Blason " + g.name },
    h("defs", null,
      h("clipPath", { id: id + "-clip" }, h("path", { d: shield })),
      h("linearGradient", { id: id + "-shine", x1: 0, y1: 0, x2: 0, y2: 1 },
        h("stop", { offset: 0, stopColor: "#fff", stopOpacity: .22 }),
        h("stop", { offset: .55, stopColor: "#fff", stopOpacity: 0 }))),
    h("g", { clipPath: "url(#" + id + "-clip)" },
      h("rect", { x: 0, y: 0, width: 160, height: 172, fill: a.hex }),
      h("path", { d: "M0 172 L160 0 L160 172 Z", fill: b.hex }),
      h("rect", { x: 0, y: 0, width: 160, height: 172, fill: "url(#" + id + "-shine)" })),
    h("path", { d: shield, fill: "none", stroke: "var(--brass)", strokeWidth: 7, strokeLinejoin: "round" }),
    h("path", { d: shield, fill: "none", stroke: "var(--brass-edge)", strokeWidth: 1.5, strokeLinejoin: "round", transform: "translate(80 86) scale(.9) translate(-80 -86)" }),
    h("circle", { cx: 80, cy: 84, r: 30, fill: "var(--surface-raised)", stroke: "var(--brass)", strokeWidth: 4 }),
    h("text", { x: 80, y: 85, textAnchor: "middle", dominantBaseline: "central", fill: "var(--brass-ink)",
                style: { font: "700 34px var(--font-display)" } }, g.name.charAt(0)));
}

function Chip(p) {
  var c = C[p.color];
  return h("span", { className: "chip label", style: { "--chip": c.hex, "--chip-ink": c.ink } }, c.name);
}

/* ------------------------------------------------------------------ screens */
function Intro(p) {
  var last = lastGuild();
  return h("div", { className: "gq-intro" },
    h("header", { className: "bar" },
      h(A.Button, { variant: "secondary", icon: "arrow-left", "aria-label": "Tous les jeux", onClick: p.onExit }),
      h("span"), h("span")),
    h("div", null,
      h("p", { className: "ar-eyebrow eyebrow" }, h(A.Badge, { tone: "brass", icon: false }, "Nouveau"), " Quiz de personnalité"),
      h("h1", { className: "title-xl" }, "Quelle guilde de Ravnica es-tu ?")),
    h("p", { className: "flavor" }, "Dix guildes, deux couleurs chacune. Quinze questions pour savoir où est ta place."),
    h(A.Panel, { title: "Comment ça marche", headingLevel: 2 },
      h("ul", { className: "rules body" },
        h("li", null, h("span", { className: "ic-m" }, h(A.Icon, { name: "heart" })),
          h("span", null, "Choisis la réponse qui te ressemble le plus, même si plusieurs te parlent.")),
        h("li", null, h("span", { className: "ic-m" }, h(A.Icon, { name: "d20" })),
          h("span", null, "Fie-toi à ton premier instinct.")),
        h("li", null, h("span", { className: "ic-m" }, h(A.Icon, { name: "chalice" })),
          h("span", null, "Tes deux couleurs dominantes désignent ta guilde.")))),
    h("div", { className: "push" },
      last ? h("p", { className: "meta caption" }, "La dernière fois, tu étais ", h("strong", null, last), ".") : null,
      h(A.Button, { variant: "primary", size: "lg", block: true, onClick: p.onStart }, "Commencer")));
}

/** A list of answers as big buttons; 1-5 on the keyboard pick them too. */
function Choices(p) {
  var s = useState(null), lit = s[0], setLit = s[1];
  var t = useRef(null), latest = useRef(null);
  function choose(i) {
    if (lit !== null) return;
    setLit(i);
    t.current = setTimeout(function () { p.onPick(p.items[i].value); }, PICK_MS);
  }
  latest.current = choose;
  useEffect(function () {
    function onKey(e) {
      if (e.altKey || e.ctrlKey || e.metaKey) return;
      var n = parseInt(e.key, 10);
      if (n >= 1 && n <= p.items.length) latest.current(n - 1);
    }
    window.addEventListener("keydown", onKey);
    return function () { window.removeEventListener("keydown", onKey); clearTimeout(t.current); };
  }, []);
  return h("ol", { className: "choices" }, p.items.map(function (it, i) {
    var on = lit === i || (lit === null && p.selected === it.value);
    return h("li", { key: i },
      h("button", { type: "button", className: "choice body" + (on ? " is-on" : ""), "aria-pressed": on,
                    onClick: function () { choose(i); } },
        it.color ? h("span", { className: "choice__key choice__key--color", "aria-hidden": "true",
                               style: { background: it.color, borderColor: "rgba(0,0,0,.35)" } }) :
        h("span", { className: "choice__key label", "aria-hidden": "true" }, String.fromCharCode(65 + i)),
        h("span", { className: "choice__text" }, it.label)));
  }));
}

function Question(p) {
  var i = p.index, q = Q[i];
  return h("div", { className: "gq-play" },
    h("header", { className: "bar" },
      h(A.Button, { variant: "secondary", icon: "arrow-left",
                    "aria-label": i ? "Question précédente" : "Retour", onClick: p.onBack }),
      h("p", { className: "title-sm gq-count" }, "Question " + (i + 1) + " / " + Q.length),
      i ? h(A.Button, { variant: "ghost", icon: "close", "aria-label": "Quitter le quiz", onClick: p.onQuit }) : h("span")),
    h("div", { className: "gq-progress", role: "progressbar", "aria-valuemin": 0, "aria-valuemax": Q.length, "aria-valuenow": i },
      h("div", { className: "gq-progress__fill", style: { width: (100 * i / Q.length) + "%" } })),
    h("main", { className: "gq-question" },
      h("h2", { className: "title-lg gq-question__title" }, q[0]),
      h(Choices, { key: i, selected: p.selected, onPick: p.onPick,
                   items: q[1].map(function (a) { return { label: a[0], value: a[1] }; }) })));
}

function Tiebreak(p) {
  return h("div", { className: "gq-play" },
    h("header", { className: "bar" },
      h(A.Button, { variant: "secondary", icon: "arrow-left", "aria-label": "Question précédente", onClick: p.onBack }),
      h("p", { className: "title-sm gq-count" }, "Départage"),
      h(A.Button, { variant: "ghost", icon: "close", "aria-label": "Quitter le quiz", onClick: p.onQuit })),
    h("div", { className: "gq-progress" }, h("div", { className: "gq-progress__fill", style: { width: "100%" } })),
    h("main", { className: "gq-question" },
      h("h2", { className: "title-lg gq-question__title" }, D.TIEBREAK),
      h(Choices, { key: p.colors.join(""), onPick: p.onPick, items: p.colors.map(function (c) {
        var v = C[c].value;
        return { color: C[c].hex, value: c, label: v.charAt(0).toUpperCase() + v.slice(1) };
      }) })));
}

function share(guild) {
  var text = "Je suis " + guild.name + " ! " + guild.text + " Et toi, quelle guilde de Ravnica es-tu ?";
  var url = location.href.split("#")[0] + "#guildes";
  if (navigator.share) return navigator.share({ title: "Quelle guilde de Ravnica es-tu ?", text: text, url: url })
    .then(function () { return "shared"; }, function () { return null; });
  if (navigator.clipboard) return navigator.clipboard.writeText(text + " " + url).then(function () { return "copied"; }, function () { return "failed"; });
  return Promise.resolve("failed");
}

function Result(p) {
  var r = p.result, g = r.guild, scores = p.scores, max = Math.max.apply(null, D.ORDER.map(function (c) { return scores[c]; }));
  var s = useState(null), status = s[0], setStatus = s[1];
  useEffect(function () { remember(g); window.scrollTo(0, 0); }, []);
  return h("div", { className: "gq-result" },
    h("header", { className: "bar" },
      h(A.Button, { variant: "secondary", icon: "arrow-left", "aria-label": "Tous les jeux", onClick: p.onExit }),
      h("span"), h("span")),
    h("section", { className: "gq-hero", "aria-labelledby": "gq-guild" },
      h("div", { className: "gq-hero__emblem" }, h(Emblem, { guild: g, pair: r.pair })),
      h("p", { className: "ar-eyebrow eyebrow" }, "Ta guilde"),
      h("h1", { id: "gq-guild", className: "title-xl" }, g.name),
      h("p", { className: "gq-chips" }, h(Chip, { color: r.pair[0] }), h("span", { "aria-hidden": "true" }, "+"), h(Chip, { color: r.pair[1] })),
      h("p", { className: "flavor gq-hero__text" }, g.text)),
    h(A.Panel, { title: "Tes couleurs", headingLevel: 2 },
      h("ul", { className: "bars" }, D.ORDER.map(function (c) {
        var mine = r.pair.indexOf(c) >= 0;
        return h("li", { key: c, className: "bars__row" + (mine ? " is-mine" : "") },
          h("span", { className: "bars__name label" }, C[c].name),
          h("span", { className: "bars__track", "aria-hidden": "true" },
            h("span", { className: "bars__fill", style: { width: (max ? 100 * scores[c] / max : 0) + "%", background: C[c].hex } })),
          h("span", { className: "bars__n label" }, scores[c]));
      }))),
    h(A.Panel, { title: "Profils de personnalité proches", headingLevel: 2 },
      h("p", { className: "gq-types" }, g.types.map(function (t) { return h(A.Badge, { key: t, tone: "neutral", icon: false }, t); })),
      h("p", { className: "caption gq-note" }, "Correspondance pour le fun avec les profils à quatre lettres, pas un test sérieux.")),
    h("div", { className: "gq-actions" },
      h(A.Button, { variant: "primary", size: "lg", block: true, icon: "share",
                    onClick: function () { share(g).then(setStatus); } }, "Partager ma guilde"),
      status === "copied" ? h("p", { className: "caption meta", role: "status" }, "Copié, il n'y a plus qu'à coller.") :
      status === "failed" ? h("p", { className: "caption meta", role: "status" }, "Le partage n'est pas disponible ici.") : null,
      h(A.Button, { variant: "secondary", size: "lg", block: true, icon: "replay", onClick: p.onReplay }, "Refaire le quiz"),
      h(A.Button, { variant: "ghost", size: "md", onClick: p.onExit }, "Tous les jeux")),
    h("p", { className: "legal caption" },
      "Contenu de fan non officiel, autorisé par la ",
      h("a", { href: "https://company.wizards.com/fancontentpolicy", target: "_blank", rel: "noopener" }, "Fan Content Policy"),
      ". Ravnica et ses guildes sont la propriété de Wizards of the Coast. ©Wizards of the Coast LLC."));
}

/* ------------------------------------------------------------------ game */
function Game(p) {
  var s1 = useState("intro"), screen = s1[0], setScreen = s1[1];
  var s2 = useState([]), answers = s2[0], setAnswers = s2[1];
  var s3 = useState(0), index = s3[0], setIndex = s3[1];
  var s4 = useState([]), picks = s4[0], setPicks = s4[1];

  useEffect(function () { window.scrollTo(0, 0); }, [screen, index]);

  var scores = tally(answers), outcome = screen === "end" ? decide(scores, picks) : null;

  function start() { setAnswers([]); setPicks([]); setIndex(0); setScreen("quiz"); }
  function answer(color) {
    var next = answers.slice(); next[index] = color;
    setAnswers(next);
    if (index + 1 < Q.length) setIndex(index + 1);
    else { setPicks([]); setScreen("end"); }
  }
  function back() {
    if (screen === "end") { if (picks.length) setPicks(picks.slice(0, -1)); else { setIndex(Q.length - 1); setScreen("quiz"); } }
    else if (index > 0) setIndex(index - 1);
    else setScreen("intro");
  }

  var body;
  if (screen === "intro") body = h(Intro, { onStart: start, onExit: p.onExit });
  else if (screen === "quiz") body = h(Question, { index: index, selected: answers[index], onPick: answer, onBack: back,
                                                   onQuit: function () { setScreen("intro"); } });
  else if (outcome.ask) body = h(Tiebreak, { colors: outcome.ask, onBack: back, onQuit: function () { setScreen("intro"); },
                                            onPick: function (c) { setPicks(picks.concat([c])); } });
  else body = h(Result, { result: outcome, scores: scores, onReplay: start, onExit: p.onExit });
  return h("div", { className: "app gq", "data-screen": screen }, body);
}

window.MTG.games.push({
  id: "guildes",
  title: "Quelle guilde es-tu ?",
  pitch: "Quinze questions pour découvrir à quelle guilde de Ravnica tu appartiens.",
  icon: "chalice",
  details: "Quiz de personnalité · 2 minutes",
  isNew: true,
  order: 2,
  component: Game,
  lastResult: function () { var g = lastGuild(); return g ? "Ta dernière guilde : " + g : null; },
});
})();
