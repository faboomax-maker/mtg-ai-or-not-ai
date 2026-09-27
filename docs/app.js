"use strict";
/* IA ou vraie carte ? — the quiz, built with the Artifice design system (window.Artifice, React 18).
   Left = IA, right = Vraie. The answer of each card stays sealed in cards.json until it is played. */

var A = window.Artifice, h = React.createElement;
var useState = React.useState, useRef = React.useRef, useEffect = React.useEffect;
var ROUND = 10, VERDICT_MS = 1200;

/* ------------------------------------------------------------------ data */
function unseal(card) {
  var bytes = Uint8Array.from(atob(card.s), function (c) { return c.charCodeAt(0); });
  return crypto.subtle.digest("SHA-256", new TextEncoder().encode(card.img)).then(function (buf) {
    var key = new Uint8Array(buf);
    var out = bytes.map(function (b, i) { return b ^ key[i % key.length]; });
    return JSON.parse(new TextDecoder().decode(out));
  });
}

function shuffle(a) {
  for (var i = a.length - 1; i > 0; i--) { var j = Math.floor(Math.random() * (i + 1)); var t = a[i]; a[i] = a[j]; a[j] = t; }
  return a;
}

function newDeck(pool) {
  // opaque ids and URLs only: the file names are random, the truth stays sealed
  return shuffle(pool.slice()).slice(0, Math.min(ROUND, pool.length))
    .map(function (c) { return { id: c.img, src: "img/" + c.img, data: c }; });
}

/* Card as large as the screen allows: the rules text must stay readable. */
function cardWidth() {
  var byHeight = (window.innerHeight - 300) * 63 / 88;
  return Math.round(Math.max(240, Math.min(460, byHeight)));
}

/* ---------------------------------------------------------------- screens */
function Intro(p) {
  return h("div", { className: "intro" },
    h("div", null,
      h("p", { className: "ar-eyebrow eyebrow" }, "Quiz Magic"),
      h("h1", { className: "title-xl" }, "IA ou vraie carte ?")),
    h("p", { className: "flavor" },
      "Dix cartes. Wizards en a imprimé certaines, une machine a inventé les autres. À toi de trier."),
    h(A.Panel, { title: "Comment on joue", headingLevel: 2 },
      h("ul", { className: "rules body" },
        h("li", null, h("span", { className: "ic-ai" }, h(A.Icon, { name: "arrow-left" })),
          h("span", null, "À gauche : ", h("strong", null, "IA"))),
        h("li", null, h("span", { className: "ic-real" }, h(A.Icon, { name: "arrow-right" })),
          h("span", null, "À droite : ", h("strong", null, "vraie carte"))),
        h("li", null, h("span", { className: "ic-m" }, h(A.Icon, { name: "swipe" })),
          h("span", null, "Glisse, touche les boutons ou utilise les flèches.")))),
    h("div", { className: "push" },
      p.error ? h("p", { className: "error caption" }, p.error) : null,
      h(A.Button, { variant: "primary", size: "lg", block: true, onClick: p.onStart, disabled: !p.ready }, "Jouer"),
      p.meta ? h("p", { className: "meta caption" }, p.meta) : null,
      h("p", { className: "legal caption" },
        "Vraies cartes via ", h("a", { href: "https://scryfall.com", target: "_blank", rel: "noopener" }, "Scryfall"),
        ". Contenu de fan non officiel, autorisé par la ",
        h("a", { href: "https://company.wizards.com/fancontentpolicy", target: "_blank", rel: "noopener" }, "Fan Content Policy"),
        ". Non approuvé par Wizards. Des parties des éléments utilisés sont la propriété de Wizards of the Coast. ©Wizards of the Coast LLC.")));
}

function Round(p) {
  var cards = p.cards;
  var s1 = useState(0), i = s1[0], setI = s1[1];
  var s2 = useState([]), res = s2[0], setRes = s2[1];
  var s3 = useState(null), verdict = s3[0], setVerdict = s3[1];
  var s4 = useState(cardWidth()), width = s4[0], setWidth = s4[1];
  var t = useRef(null);
  useEffect(function () {
    function onResize() { setWidth(cardWidth()); }
    window.addEventListener("resize", onResize);
    return function () { clearTimeout(t.current); window.removeEventListener("resize", onResize); };
  }, []);

  function onAnswer(side, card, idx) {
    unseal(card.data).then(function (secret) {
      var truth = secret.real ? "real" : "ai", ok = side === truth;
      var next = res.concat([{ id: card.id, src: card.src, truth: truth, answer: side, ok: ok,
                               card: card.data, secret: secret }]);
      setRes(next);
      setVerdict({ correct: ok, truth: truth, src: card.src, index: idx + 1, total: cards.length });
      t.current = setTimeout(function () {
        setVerdict(null);
        if (idx + 1 >= cards.length) p.onEnd(next); else setI(idx + 1);
      }, VERDICT_MS);
    });
  }

  return h(React.Fragment, null,
    h("header", { className: "bar" },
      h(A.Button, { variant: "secondary", icon: "close", "aria-label": "Quitter la partie", onClick: p.onQuit }),
      h("h1", { className: "title-sm" }, "IA ou vraie carte ?"),
      h("span")),
    h(A.RoundProgress, { current: Math.min(res.length + (verdict ? 0 : 1), cards.length), total: cards.length,
                         results: res.map(function (r) { return r.ok; }) }),
    // the next card waits under the current one (first card of the stack), seen while swiping
    h("main", { className: "play",
                style: { "--next-card": cards[i + 1] ? 'url("' + cards[i + 1].src + '")' : "none" } },
      h(A.SwipeDeck, { cards: cards, current: i, locked: !!verdict, onAnswer: onAnswer, cardWidth: width,
                       overlay: verdict ? h(A.Verdict, verdict) : null })));
}

/* What each card really was: set, artist, Scryfall; for AI cards, where the art comes from. */
function Details(p) {
  return h(A.Panel, { title: "Les cartes", headingLevel: 2 },
    h("ol", { className: "details" }, p.items.map(function (r) {
      var s = r.secret, info;
      if (r.truth === "real") {
        info = [s.set, s.artist ? "illustration de " + s.artist : null].filter(Boolean).join(" · ");
        info = h("p", { className: "info caption" }, info,
          s.url ? h(React.Fragment, null, " · ", h("a", { href: s.url, target: "_blank", rel: "noopener" }, "Scryfall")) : null);
      } else {
        info = h("p", { className: "info caption" },
          "Texte et nom inventés par une IA.",
          s.art_from ? " Illustration de " + (s.artist || "?") + ", empruntée à « " + s.art_from + " »." : "",
          s.set ? " Symbole de " + s.set + " emprunté." : "");
      }
      return h("li", { key: r.id },
        h("span", { className: "name body-strong" }, r.card.name),
        h(A.Badge, { tone: r.truth }, r.truth === "ai" ? "IA" : "Vraie"),
        info);
    })));
}

function Score(p) {
  var s = useState(null);
  var score = p.items.filter(function (r) { return r.ok; }).length;
  return h("div", { className: "scroll" },
    h(A.ScoreSummary, { score: score, total: p.items.length, items: p.items, shareStatus: s[0],
      onReplay: p.onReplay,
      onShare: function () { A.shareScore(score, p.items.length, location.href).then(s[1]); } }),
    h(Details, { items: p.items }));
}

function App() {
  var s1 = useState("intro"), screen = s1[0], setScreen = s1[1];
  var s2 = useState(null), pool = s2[0], setPool = s2[1];
  var s3 = useState(null), meta = s3[0], setMeta = s3[1];
  var s4 = useState(null), error = s4[0], setError = s4[1];
  var s5 = useState([]), cards = s5[0], setCards = s5[1];
  var s6 = useState([]), items = s6[0], setItems = s6[1];
  var s7 = useState(0), game = s7[0], setGame = s7[1];

  useEffect(function () {
    fetch("data/cards.json", { cache: "no-cache" })
      .then(function (r) { if (!r.ok) throw new Error("data/cards.json introuvable"); return r.json(); })
      .then(function (d) {
        setPool(d.cards);
        setMeta(d.count + " cartes en réserve · " + (d.generated === "demo" ? "jeu de démonstration" : "tirage du " + d.generated));
      })
      .catch(function (e) { setError("Impossible de charger les cartes : " + e.message); });
  }, []);

  function start() { setCards(newDeck(pool)); setGame(game + 1); setScreen("round"); }

  return h("div", { className: "app", "data-screen": screen },
    screen === "intro" ? h(Intro, { onStart: start, ready: !!(pool && pool.length), meta: meta, error: error }) :
    screen === "round" ? h(Round, { key: game, cards: cards, onQuit: function () { setScreen("intro"); },
                                    onEnd: function (r) { setItems(r); setScreen("score"); } }) :
    h(Score, { items: items, onReplay: start }));
}

ReactDOM.createRoot(document.getElementById("root")).render(h(App));
