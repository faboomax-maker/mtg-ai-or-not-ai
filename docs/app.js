"use strict";
/* IA ou vraie carte ? — the quiz, built with the Artifice design system (window.Artifice, React 18).
   Left = IA, right = Vraie. Two modes: normal (recent cards) and hardcore (mostly commons from every
   era, a timer per card, Charnier theme). With the game server (deck.api), the answers are only
   revealed by the server after each answer, which also times them and keeps the top 10s. Without
   it, the answers are sealed in the deck and the game is played in the browser (no leaderboard). */

var A = window.Artifice, h = React.createElement;
var useState = React.useState, useRef = React.useRef, useEffect = React.useEffect;
var ROUND = 10, VERDICT_MS = 1200;
var DECKS = { normal: "data/cards.json", hardcore: "data/hardcore.json" };
var MODE_NAME = { normal: "Normal", hardcore: "Hardcore" };

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

function post(api, path, data) {
  return fetch(api + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) })
    .then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) throw new Error(d.error || "HTTP " + r.status);
        return d;
      });
    });
}

/** Hardcore time limit of card i (0-based): 10 s for the first, 5 s for the last (as on the server). */
function limitMs(i, n) { return Math.round(10000 - 5000 * i / Math.max(1, n - 1)); }

/** A game: the cards, and how an answer is judged (server or sealed deck). */
function newGame(mode, deck) {
  var byImg = {};
  deck.cards.forEach(function (c) { byImg[c.img] = c; });
  function card(img) { return { id: img, src: deck.img + img, data: byImg[img] }; }
  if (deck.api) {
    return post(deck.api, "/start", { mode: mode }).then(function (g) {
      return {
        mode: mode, api: deck.api, id: g.game, cards: g.cards.map(card),
        limits: mode === "hardcore" ? (g.limits || g.cards.map(function (_, i) { return limitMs(i, g.cards.length); })) : null,
        judge: function (index, side) {
          return post(deck.api, "/answer", { game: g.game, index: index, answer: side }).then(function (r) {
            return { truth: r.truth, ok: r.correct, timeout: r.timeout, secret: r.secret };
          });
        },
      };
    });
  }
  var cards = shuffle(deck.cards.slice()).slice(0, Math.min(ROUND, deck.cards.length)).map(function (c) { return card(c.img); });
  return Promise.resolve({
    mode: mode, api: null, cards: cards,
    limits: mode === "hardcore" ? cards.map(function (_, i) { return limitMs(i, cards.length); }) : null,
    judge: function (index, side) {
      return unseal(cards[index].data).then(function (secret) {
        var truth = secret.real ? "real" : "ai";
        return { truth: truth, ok: side === truth, timeout: side === "timeout", secret: secret };
      });
    },
  });
}

/* Card as large as the screen allows: the rules text must stay readable. */
function cardWidth(timer) {
  var byHeight = (window.innerHeight - (timer ? 350 : 300)) * 63 / 88;
  return Math.round(Math.max(240, Math.min(460, byHeight)));
}

function seconds(ms) {
  return (ms / 1000).toLocaleString("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + " s";
}

/* ------------------------------------------------------------ leaderboard */
function Leaderboard(p) {
  var rows = (p.board && p.board[p.mode]) || [];
  return h("div", { className: "board" },
    p.switchable ? h("div", { className: "board__modes", role: "group", "aria-label": "Mode du classement" },
      ["normal", "hardcore"].map(function (m) {
        return h(A.Button, { key: m, variant: "secondary", size: "md", className: m === p.mode ? "is-on" : null,
                             "aria-pressed": m === p.mode, onClick: function () { p.onMode(m); } }, MODE_NAME[m]);
      })) : null,
    p.board === undefined ? h("p", { className: "caption board__empty" }, "Chargement du classement…") :
    !rows.length ? h("p", { className: "caption board__empty" },
      p.board ? "Personne encore. La première place t'attend." : "Le classement ouvre bientôt.") :
    h("ol", { className: "board__list" }, rows.map(function (r, i) {
      var mine = p.highlight && p.highlight === i + 1;
      return h("li", { key: i, className: "board__row" + (mine ? " is-mine" : "") },
        h("span", { className: "board__rank label" }, i + 1),
        h("span", { className: "board__name body" }, r.name),
        h("span", { className: "board__score label" }, r.score + " / " + r.total),
        h("span", { className: "board__time caption" }, seconds(r.ms)));
    })));
}

function loadBoard(decks) {
  var api = ["normal", "hardcore"].map(function (m) { return decks[m] && decks[m].api; }).filter(Boolean)[0];
  var url = api ? api + "/leaderboard" : "data/leaderboard.json";
  return fetch(url, { cache: "no-cache" }).then(function (r) { return r.ok ? r.json() : null; })
    .catch(function () { return null; });
}

/* ---------------------------------------------------------------- screens */
function Intro(p) {
  var s = useState("normal"), boardMode = s[0], setBoardMode = s[1];
  var normal = p.decks.normal, hard = p.decks.hardcore;
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
          h("span", null, "Glisse, touche les boutons ou utilise les flèches.")),
        h("li", null, h("span", { className: "ic-m" }, h(A.Icon, { name: "hourglass" })),
          h("span", null, h("strong", null, "Hardcore : "), "des cartes communes de toutes les époques, et un sablier qui fond de 10 à 5 secondes.")))),
    h(A.Panel, { title: "Classement", headingLevel: 2 },
      h(Leaderboard, { board: p.board, mode: boardMode, onMode: setBoardMode, switchable: true })),
    h("div", { className: "push" },
      p.error ? h("p", { className: "error caption" }, p.error) : null,
      h(A.Button, { variant: "primary", size: "lg", block: true, disabled: !(normal && normal.cards.length) || p.busy,
                    onClick: function () { p.onStart("normal"); } }, "Jouer"),
      h(A.Button, { variant: "secondary", size: "lg", block: true, icon: "skull", disabled: !(hard && hard.cards.length) || p.busy,
                    onClick: function () { p.onStart("hardcore"); } }, hard ? "Mode hardcore" : "Mode hardcore (bientôt)"),
      p.meta ? h("p", { className: "meta caption" }, p.meta) : null,
      h("p", { className: "legal caption" },
        "Vraies cartes via ", h("a", { href: "https://scryfall.com", target: "_blank", rel: "noopener" }, "Scryfall"),
        ". Contenu de fan non officiel, autorisé par la ",
        h("a", { href: "https://company.wizards.com/fancontentpolicy", target: "_blank", rel: "noopener" }, "Fan Content Policy"),
        ". Non approuvé par Wizards. Des parties des éléments utilisés sont la propriété de Wizards of the Coast. ©Wizards of the Coast LLC.")));
}

/* The hourglass of a hardcore card: counts down `limit` ms while `running`, then calls onExpire. */
function Timer(p) {
  var s = useState(p.limit), left = s[0], setLeft = s[1];
  var fired = useRef(false);
  useEffect(function () {
    if (!p.running) return;
    var start = performance.now();
    var id = setInterval(function () {
      var rest = Math.max(0, p.limit - (performance.now() - start));
      setLeft(rest);
      if (rest <= 0 && !fired.current) { fired.current = true; clearInterval(id); p.onExpire(); }
    }, 100);
    return function () { clearInterval(id); };
  }, [p.running]);
  var secs = Math.ceil(left / 1000), low = left <= 3000;
  return h("div", { className: "timer" + (low ? " is-low" : ""), role: "timer", "aria-label": "Temps restant" },
    h(A.Icon, { name: "hourglass", size: 20 }),
    h("div", { className: "timer__track", "aria-hidden": "true" },
      h("div", { className: "timer__fill", style: { width: (100 * left / p.limit) + "%" } })),
    h("span", { className: "timer__secs label" }, secs + " s"));
}

function Round(p) {
  var g = p.game, cards = g.cards;
  var s1 = useState(0), i = s1[0], setI = s1[1];
  var s2 = useState([]), res = s2[0], setRes = s2[1];
  var s3 = useState(null), verdict = s3[0], setVerdict = s3[1];
  var s4 = useState(cardWidth(!!g.limits)), width = s4[0], setWidth = s4[1];
  var s5 = useState(false), waiting = s5[0], setWaiting = s5[1];
  var t = useRef(null), shownAt = useRef(performance.now()), answered = useRef(-1);
  useEffect(function () {
    function onResize() { setWidth(cardWidth(!!g.limits)); }
    window.addEventListener("resize", onResize);
    return function () { clearTimeout(t.current); window.removeEventListener("resize", onResize); };
  }, []);
  useEffect(function () { shownAt.current = performance.now(); }, [i]);

  function onAnswer(side, card, idx) {
    if (answered.current >= idx) return;                    // (timer and swipe at the same time)
    answered.current = idx;
    var ms = performance.now() - shownAt.current;
    setWaiting(true);
    g.judge(idx, side).then(function (j) {
      setWaiting(false);
      var next = res.concat([{ id: card.id, src: card.src, truth: j.truth, answer: side === "timeout" ? (j.truth === "ai" ? "real" : "ai") : side,
                               ok: j.ok, timeout: j.timeout, ms: ms, card: card.data, secret: j.secret }]);
      setRes(next);
      setVerdict({ correct: j.ok, truth: j.truth, src: card.src, index: idx + 1, total: cards.length, timeout: j.timeout });
      t.current = setTimeout(function () {
        setVerdict(null);
        if (idx + 1 >= cards.length) p.onEnd(next); else setI(idx + 1);
      }, VERDICT_MS);
    }).catch(function (e) { p.onError("Le serveur de jeu ne répond pas : " + e.message); });
  }

  var overlay = verdict ? h("div", { className: "verdict-wrap" },
    verdict.timeout ? h("p", { className: "timeout label" }, h(A.Icon, { name: "hourglass", size: 18 }), "Temps écoulé") : null,
    h(A.Verdict, verdict)) : null;

  return h(React.Fragment, null,
    h("header", { className: "bar" },
      h(A.Button, { variant: "secondary", icon: "close", "aria-label": "Quitter la partie", onClick: p.onQuit }),
      h("h1", { className: "title-sm" }, g.mode === "hardcore" ? "Hardcore" : "IA ou vraie carte ?"),
      h("span")),
    h(A.RoundProgress, { current: Math.min(res.length + (verdict ? 0 : 1), cards.length), total: cards.length,
                         results: res.map(function (r) { return r.ok; }) }),
    g.limits ? h(Timer, { key: i, limit: g.limits[i], running: !verdict && !waiting && answered.current < i,
                          onExpire: function () { onAnswer("timeout", cards[i], i); } }) : null,
    // the next card waits under the current one (first card of the stack), seen while swiping
    h("main", { className: "play",
                style: { "--next-card": cards[i + 1] ? 'url("' + cards[i + 1].src + '")' : "none" } },
      h(A.SwipeDeck, { cards: cards, current: i, locked: !!verdict || waiting, onAnswer: onAnswer, cardWidth: width,
                       overlay: overlay, hint: g.limits ? null : undefined })));
}

/* What each card really was: set, artist, Scryfall; for AI cards, where the art comes from. */
function Details(p) {
  return h(A.Panel, { title: "Les cartes", headingLevel: 2 },
    h("ol", { className: "details" }, p.items.map(function (r) {
      var s = r.secret || {}, info;
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
        h("span", { className: "name body-strong" }, r.card ? r.card.name : ""),
        h(A.Badge, { tone: r.truth }, r.truth === "ai" ? "IA" : "Vraie"),
        info);
    })));
}

/* Save the score: asks the server whether it enters the top 10, then a name. */
function SaveScore(p) {
  var g = p.game;
  var s1 = useState(null), result = s1[0], setResult = s1[1];
  var s2 = useState(""), name = s2[0], setName = s2[1];
  var s3 = useState(null), error = s3[0], setError = s3[1];
  var s4 = useState(false), busy = s4[0], setBusy = s4[1];
  var s5 = useState(null), saved = s5[0], setSaved = s5[1];
  useEffect(function () {
    if (!g.api) return;
    try { setName(localStorage.getItem("quiz-name") || ""); } catch (e) { /* private mode */ }
    post(g.api, "/result", { game: g.id }).then(setResult).catch(function (e) { setError(e.message); });
  }, []);

  if (!g.api) return h(A.Panel, { title: "Classement", headingLevel: 2 },
    h("p", { className: "caption" }, "Le classement n'est pas encore ouvert pour ce jeu de cartes."));

  function submit(ev) {
    ev.preventDefault();
    setBusy(true); setError(null);
    try { localStorage.setItem("quiz-name", name.trim()); } catch (e) { /* private mode */ }
    post(g.api, "/submit", { game: g.id, name: name }).then(function (r) { setSaved(r); p.onBoard(r.leaderboard); })
      .catch(function (e) { setError(e.message === "name not allowed" ? "Ce pseudo n'est pas accepté." :
                                      /name/.test(e.message) ? "1 à 16 lettres, chiffres ou espaces." : e.message); })
      .then(function () { setBusy(false); });
  }

  var body;
  if (saved) body = h(Leaderboard, { board: saved.leaderboard, mode: g.mode, highlight: saved.rank });
  else if (!result) body = h("p", { className: "caption" }, error || "Calcul du classement…");
  else if (!result.qualifies) body = h(React.Fragment, null,
    h("p", { className: "caption" }, "Pas dans le top 10 cette fois. Temps : " + seconds(result.ms) + "."),
    h(Leaderboard, { board: p.board, mode: g.mode }));
  else body = h("form", { className: "save", onSubmit: submit },
    h("p", { className: "body" }, "Tu entres dans le top 10 ", h("strong", null, MODE_NAME[g.mode]),
      " : " + result.score + " / " + result.total + " en " + seconds(result.ms) + "."),
    h(A.TextField, { label: "Ton pseudo", value: name, maxLength: 16, autoComplete: "nickname", required: true,
                     error: error, onChange: function (e) { setName(e.target.value); } }),
    h(A.Button, { type: "submit", variant: "primary", size: "lg", block: true, disabled: busy || !name.trim() }, "Enregistrer"));
  return h(A.Panel, { title: "Classement", headingLevel: 2 }, body);
}

function Score(p) {
  var s = useState(null);
  var score = p.items.filter(function (r) { return r.ok; }).length;
  var ms = p.items.reduce(function (t, r) { return t + r.ms; }, 0);
  return h("div", { className: "scroll" },
    h(A.ScoreSummary, { score: score, total: p.items.length, items: p.items, shareStatus: s[0],
      onReplay: p.onReplay,
      onShare: function () { A.shareScore(score, p.items.length, location.href).then(s[1]); } }),
    h("p", { className: "total-time caption" }, h(A.Icon, { name: "hourglass", size: 16 }), "Temps total : " + seconds(ms)),
    h(SaveScore, { game: p.game, board: p.board, onBoard: p.onBoard }),
    h(Details, { items: p.items }),
    h(A.Button, { variant: "ghost", size: "md", onClick: p.onHome }, "Accueil"));
}

function App() {
  var s1 = useState("intro"), screen = s1[0], setScreen = s1[1];
  var s2 = useState({}), decks = s2[0], setDecks = s2[1];
  var s3 = useState(null), meta = s3[0], setMeta = s3[1];
  var s4 = useState(null), error = s4[0], setError = s4[1];
  var s5 = useState(null), game = s5[0], setGame = s5[1];
  var s6 = useState([]), items = s6[0], setItems = s6[1];
  var s7 = useState(0), round = s7[0], setRound = s7[1];
  var s8 = useState(undefined), board = s8[0], setBoard = s8[1];
  var s9 = useState(false), busy = s9[0], setBusy = s9[1];

  useEffect(function () {
    var get = function (url) {
      return fetch(url, { cache: "no-cache" }).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; });
    };
    Promise.all([get(DECKS.normal), get(DECKS.hardcore)]).then(function (d) {
      var found = { normal: d[0], hardcore: d[1] };
      if (found.normal && !found.normal.img) found.normal.img = "img/";         // (older single-deck layout)
      setDecks(found);
      if (!d[0] && !d[1]) setError("Impossible de charger les cartes.");
      else if (d[0]) setMeta(d[0].count + " cartes en réserve · tirage du " + d[0].generated);
      loadBoard(found).then(setBoard);
    });
  }, []);

  // hardcore: the Charnier theme on the whole page, while playing and on the score screen
  useEffect(function () {
    var hard = screen !== "intro" && game && game.mode === "hardcore";
    if (hard) document.documentElement.setAttribute("data-theme", "charnier");
    else document.documentElement.removeAttribute("data-theme");
    var tc = document.querySelector('meta[name="theme-color"]');
    if (tc) tc.setAttribute("content", hard ? "#0c0505" : "#15100d");
  }, [screen, game]);

  function start(mode) {
    setBusy(true); setError(null);
    newGame(mode, decks[mode]).then(function (g) { setGame(g); setRound(round + 1); setScreen("round"); })
      .catch(function (e) { setError("Le serveur de jeu ne répond pas (" + e.message + "). Réessaie dans un instant."); })
      .then(function () { setBusy(false); });
  }
  function home() { setScreen("intro"); loadBoard(decks).then(setBoard); }

  return h("div", { className: "app", "data-screen": screen },
    screen === "intro" ? h(Intro, { onStart: start, decks: decks, meta: meta, error: error, board: board, busy: busy }) :
    screen === "round" ? h(Round, { key: round, game: game, onQuit: home,
                                    onError: function (m) { setError(m); setScreen("intro"); },
                                    onEnd: function (r) { setItems(r); setScreen("score"); } }) :
    h(Score, { items: items, game: game, board: board, onBoard: setBoard, onHome: home,
               onReplay: function () { start(game.mode); } }));
}

ReactDOM.createRoot(document.getElementById("root")).render(h(App));
