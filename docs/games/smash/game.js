/* Smash or Pass — well-known Magic characters, swiped like on Tinder (right: Smash, left: Pass).
   After each swipe, what the other players answered. For now these percentages are fixed mock
   numbers (field `smash` below); real votes can replace them later without touching the screens.
   Art: Scryfall's art crop of one of the character's cards (Scryfall id below).
   Registered in window.MTG.games; the hub (app.js) mounts it with { onExit }. */
(function () {
"use strict";
var A = window.Artifice, h = React.createElement;
var useState = React.useState, useEffect = React.useEffect, useRef = React.useRef;
var ROUND = 15, LAST_KEY = "smash-last", THRESHOLD = 90;

/* n: shown name · card: the card the art comes from · id: its Scryfall id · smash: mock % of Smash */
var CHARACTERS = [
  { n: "Jace Beleren", card: "Jace, the Mind Sculptor", id: "c8817585-0d32-4d56-9142-0d29512e86a9", smash: 46,
    quip: "Télépathe. Il connaissait ta réponse avant toi." },
  { n: "Liliana Vess", card: "Liliana of the Veil", id: "efbb7256-9337-4183-8bda-a419f3f2c501", smash: 84,
    quip: "Un pacte avec quatre démons. Red flag ou green flag ?" },
  { n: "Chandra Nalaar", card: "Chandra, Torch of Defiance", id: "40cb22c8-cb03-45c9-bb0e-b8cabdcc43cd", smash: 71,
    quip: "Brûlante. Au sens propre. Prévoir un extincteur." },
  { n: "Gideon Jura", card: "Gideon, Ally of Zendikar", id: "187e887c-c39d-4d25-a506-cdc95fc70316", smash: 77,
    quip: "Invulnérable. Sauf quand ça compte vraiment." },
  { n: "Nissa Revane", card: "Nissa, Who Shakes the World", id: "f857bbe4-5619-4733-a0c7-69700f2ef4f3", smash: 58,
    quip: "Parle aux forêts. Ne répond pas à tes messages." },
  { n: "Ajani Goldmane", card: "Ajani Goldmane", id: "2d911053-a026-4b20-ba2d-dbcc367c1413", smash: 39,
    quip: "Câlins garantis. Litière à prévoir." },
  { n: "Teferi", card: "Teferi, Hero of Dominaria", id: "5d10b752-d9cb-419d-a5c4-d4ee1acb655e", smash: 52,
    quip: "A fait disparaître tout son pays pour le protéger. Imagine ce qu'il ferait de ton appart." },
  { n: "Nicol Bolas", card: "Nicol Bolas, Dragon-God", id: "c5408607-af8f-48fe-bc40-32828d1976de", smash: 14,
    quip: "Te promet le monde. Le garde pour lui." },
  { n: "Sorin Markov", card: "Sorin Markov", id: "e25b3a89-3a99-4e02-bf0c-a3cf450da1a1", smash: 81,
    quip: "Vampire, plusieurs milliers d'années, toujours célibataire. Pose-toi la question." },
  { n: "Elspeth Tirel", card: "Elspeth, Sun's Champion", id: "a91d9163-c1f2-4eae-acab-5dabbc71d7d4", smash: 66,
    quip: "Revenue des Enfers. Pas pour toi, mais quand même." },
  { n: "Karn", card: "Karn Liberated", id: "4b0c6662-4dde-40a2-97e0-0318478c0367", smash: 21,
    quip: "Golem en argent. Très stable émotionnellement. Trop." },
  { n: "Garruk Wildspeaker", card: "Garruk Wildspeaker", id: "08cf7ee6-ba30-42cd-a5b3-fd2fe7252f11", smash: 49,
    quip: "Barbe, hache, chemise ouverte. Maudit, mais personne n'est parfait." },
  { n: "Vraska", card: "Vraska, Golgari Queen", id: "a36d3ea7-0f18-4865-b47b-755673db065e", smash: 63,
    quip: "Un regard et tu es pétrifié. C'est ça, le coup de foudre ?" },
  { n: "Ral Zarek", card: "Ral Zarek", id: "3bdd2b4b-5ba3-4984-8d48-c4c1d75dd177", smash: 55,
    quip: "Électrique. Les cheveux aussi." },
  { n: "Kaya", card: "Kaya, Ghost Assassin", id: "e969921c-251a-4469-9578-e243d37dc9a7", smash: 60,
    quip: "Traverse les murs. Et les relations." },
  { n: "Tamiyo", card: "Tamiyo, the Moon Sage", id: "b9398926-13b9-47b8-b66b-1ab9d06bb704", smash: 57,
    quip: "Elle note tout dans ses parchemins. Ta réponse aussi." },
  { n: "Narset", card: "Narset, Parter of Veils", id: "4e6e5c63-b6e5-4756-bf23-6c6f8669442d", smash: 50,
    quip: "Une seule carte piochée par tour. Un peu possessive ?" },
  { n: "Ugin", card: "Ugin, the Spirit Dragon", id: "9c017fa9-7021-417a-9c2e-3df409644fcf", smash: 23,
    quip: "Dragon esprit, très sage, très vieux. Très, très vieux." },
  { n: "Emrakul", card: "Emrakul, the Aeons Torn", id: "249db4d4-2542-47ee-a216-e13ffbc2319c", smash: 6,
    quip: "Annihilateur 6. Au premier rendez-vous, c'est toi qui sacrifies." },
  { n: "Elesh Norn", card: "Elesh Norn, Grand Cenobite", id: "78c2bfef-06a5-4c7f-8283-ea3fb673b7a1", smash: 18,
    quip: "Veut te rendre parfait. Avec un peu de métal." },
  { n: "Urza", card: "Urza, Lord High Artificer", id: "7b7a348a-51f7-4dc5-8fe7-1c70fea5e050", smash: 27,
    quip: "A rasé une île entière pour gagner une dispute avec son frère." },
  { n: "Yawgmoth", card: "Yawgmoth, Thran Physician", id: "b5a79f5d-d0df-4799-ac3a-84305e3af0c9", smash: 9,
    quip: "Médecin. Ne lui demande pas d'où viennent les Phyrexians." },
  { n: "Oko", card: "Oko, Thief of Crowns", id: "3462a3d0-5552-49fa-9eb7-100960c55891", smash: 62,
    quip: "Dis « Pass » et tu finis en élan 3/3." },
  { n: "Sheoldred", card: "Sheoldred, the Apocalypse", id: "d67be074-cdd4-41d9-ac89-0a0456c4e4b2", smash: 31,
    quip: "Chaque carte que tu pioches te coûte 2 points de vie. Relation toxique." },
  { n: "Atraxa", card: "Atraxa, Praetors' Voice", id: "d0d33d52-3d28-4635-b985-51e126289259", smash: 24,
    quip: "Quatre couleurs, quatre ailes. Ajoute des marqueurs à tout, toi compris." },
  { n: "Edgar Markov", card: "Edgar Markov", id: "a577ba08-0aa8-45be-aa83-d5078770127c", smash: 47,
    quip: "Le grand-père de Sorin. Tu peux encore changer d'avis." },
  { n: "Niv-Mizzet", card: "Niv-Mizzet, Parun", id: "86c5c337-d25f-4c3e-9762-09ed0c2d36d7", smash: 19,
    quip: "Génie, dragon, et il le sait. Il te le rappelle à chaque carte piochée." },
  { n: "Krenko", card: "Krenko, Mob Boss", id: "824b2d73-2151-4e5e-9f05-8f63e2bdcaa9", smash: 11,
    quip: "Ne vient jamais seul. Ses potes doublent à chaque tour." },
  { n: "Olivia Voldaren", card: "Olivia Voldaren", id: "561d616c-df11-4144-acec-f9fe47efa5c7", smash: 78,
    quip: "Te transforme en vampire, puis te met dans sa collection." },
  { n: "Avacyn", card: "Avacyn, Angel of Hope", id: "74e5dcec-ef1d-4461-bb23-61d98ff082dd", smash: 72,
    quip: "Ange gardien. A un peu pété les plombs à Innistrad, mais qui ne l'a jamais fait ?" },
  { n: "Le Monstre de Gitrog", card: "The Gitrog Monster", id: "40489e28-878d-44a2-847f-07beef1aa0f8", smash: 4,
    quip: "Une grenouille géante qui mange tes terrains. Elle a de beaux yeux, quand même." },
  { n: "Xenagos", card: "Xenagos, the Reveler", id: "edfd90ee-a142-4a80-b383-802bbee2cef1", smash: 42,
    quip: "Dieu de la fête. Ne se souviendra pas de ton prénom." },
  { n: "Ashiok", card: "Ashiok, Nightmare Weaver", id: "599c3c9f-dfb7-4357-9d9c-9a1a4616b103", smash: 35,
    quip: "Pas de visage, que des cauchemars. Au moins, pas de prise de tête." },
  { n: "Karlach", card: "Karlach, Fury of Avernus", id: "775480ed-f574-40cb-bd9b-21102eaaff63", smash: 76,
    quip: "Un cœur infernal qui chauffe. Câlins à tes risques et périls." },
  { n: "Minsc & Boo", card: "Minsc & Boo, Timeless Heroes", id: "928036c9-11b8-493e-b9f2-8fbd3487cd19", smash: 52,
    quip: "Un rôdeur et son hamster géant miniature de l'espace. Deux pour le prix d'un." },
];

function shuffle(a) {
  for (var i = a.length - 1; i > 0; i--) { var j = Math.floor(Math.random() * (i + 1)); var t = a[i]; a[i] = a[j]; a[j] = t; }
  return a;
}
function art(id) { return "https://cards.scryfall.io/art_crop/front/" + id[0] + "/" + id[1] + "/" + id + ".jpg"; }
function getLast() { try { return JSON.parse(localStorage.getItem(LAST_KEY)) || null; } catch (e) { return null; } }
function setLast(v) { try { localStorage.setItem(LAST_KEY, JSON.stringify(v)); } catch (e) { /* private mode */ } }

/** What the others answered, said from the player's side. */
function verdict(c, smash) {
  var same = smash ? c.smash : 100 - c.smash;
  return same >= 80 ? "Comme presque tout le monde." :
         same >= 50 ? "Comme la majorité." :
         same >= 20 ? "Tu fais partie des " + same + " %." :
                      "Seulement " + same + " % des joueurs sont d'accord avec toi. Assume.";
}
function profile(rate, agree) {
  var taste = rate >= 80 ? "Tu smashes tout ce qui bouge, Phyrexians compris." :
              rate >= 55 ? "Cœur d'artichaut, mais tu as tes limites." :
              rate >= 30 ? "Exigeant. Le multivers entier doit faire ses preuves." :
                           "Personne ne trouve grâce à tes yeux. Même pas Sorin.";
  var crowd = agree >= ROUND * 0.8 ? "Tes goûts sont ceux de tout le monde." :
              agree >= ROUND * 0.5 ? "Tu votes souvent comme les autres." :
                                     "Tes goûts sont… uniques. On ne juge pas.";
  return { taste: taste, crowd: crowd };
}

/* ------------------------------------------------------------------ screens */
function Intro(p) {
  var last = getLast();
  return h("div", { className: "sp-intro" },
    h("header", { className: "bar" },
      h(A.Button, { variant: "secondary", icon: "arrow-left", "aria-label": "Tous les jeux", onClick: p.onExit }),
      h("span"), h("span")),
    h("div", null,
      h("p", { className: "ar-eyebrow eyebrow sp-eyebrow" }, h(A.Badge, { tone: "brass", icon: false }, "Nouveau"), " Personnages de Magic"),
      h("h1", { className: "title-xl" }, "Smash or Pass")),
    h("p", { className: "flavor" }, "Les planeswalkers et légendes du multivers défilent. À toi de trancher."),
    h(A.Panel, { title: "Comment ça marche", headingLevel: 2 },
      h("ul", { className: "rules body" },
        h("li", null, h("span", { className: "ic-m" }, h(A.Icon, { name: "swipe" })),
          h("span", null, "Glisse à droite pour Smash, à gauche pour Pass (ou utilise les boutons).")),
        h("li", null, h("span", { className: "ic-m" }, h(A.Icon, { name: "heart" })),
          h("span", null, "Après chaque choix, tu vois ce qu'ont répondu les autres joueurs.")),
        h("li", null, h("span", { className: "ic-m" }, h(A.Icon, { name: "d20" })),
          h("span", null, ROUND + " personnages par partie, tirés au hasard parmi " + CHARACTERS.length + ".")))),
    h("div", { className: "push" },
      last ? h("p", { className: "meta caption" }, "Ta dernière partie : " + last.smash + " Smash sur " + last.total) : null,
      h(A.Button, { variant: "primary", size: "lg", block: true, onClick: p.onStart }, "Commencer"),
      h("p", { className: "legal caption" },
        "Illustrations via ", h("a", { href: "https://scryfall.com", target: "_blank", rel: "noopener" }, "Scryfall"),
        ". Contenu de fan non officiel, autorisé par la ",
        h("a", { href: "https://company.wizards.com/fancontentpolicy", target: "_blank", rel: "noopener" }, "Fan Content Policy"),
        ". ©Wizards of the Coast LLC.")));
}

/** The top card of the stack: follows the finger, flies away past THRESHOLD px. */
function SwipeCard(p) {
  var c = p.character;
  var s = useState({ dx: 0, dy: 0, drag: false, gone: 0 }), st = s[0], set = s[1];
  var start = useRef(null), done = useRef(false);

  useEffect(function () { done.current = false; set({ dx: 0, dy: 0, drag: false, gone: 0 }); }, [c.id]);
  useEffect(function () {   // the buttons and the arrow keys throw the card the same way
    if (p.fling && p.fling.id === c.id) fling(p.fling.dir);
  }, [p.fling]);

  function fling(dir) {
    if (done.current) return;
    done.current = true;
    set({ dx: dir * window.innerWidth * 1.2, dy: 40, drag: false, gone: dir });
    setTimeout(function () { p.onVote(dir > 0); }, 220);
  }
  function down(e) {
    if (done.current) return;
    start.current = { x: e.clientX, y: e.clientY };
    e.currentTarget.setPointerCapture(e.pointerId);
    set({ dx: 0, dy: 0, drag: true, gone: 0 });
  }
  function move(e) {
    if (!start.current) return;
    set({ dx: e.clientX - start.current.x, dy: (e.clientY - start.current.y) * 0.3, drag: true, gone: 0 });
  }
  function up() {
    if (!start.current) return;
    start.current = null;
    if (Math.abs(st.dx) > THRESHOLD) fling(st.dx > 0 ? 1 : -1);
    else set({ dx: 0, dy: 0, drag: false, gone: 0 });
  }

  var k = Math.max(-1, Math.min(1, st.dx / THRESHOLD));
  var style = { transform: "translate(" + st.dx + "px," + st.dy + "px) rotate(" + (st.dx / 18) + "deg)",
                transition: st.drag ? "none" : "transform 220ms ease-out" };
  return h("div", { className: "sp-card is-top", style: style, onPointerDown: down, onPointerMove: move, onPointerUp: up,
                    onPointerCancel: up, role: "img", "aria-label": c.n },
    h("img", { src: art(c.id), alt: "", draggable: false }),
    h("span", { className: "sp-stamp sp-stamp--smash", style: { opacity: Math.max(0, k) } }, "Smash"),
    h("span", { className: "sp-stamp sp-stamp--pass", style: { opacity: Math.max(0, -k) } }, "Pass"),
    h("div", { className: "sp-card__name" },
      h("p", { className: "title-lg" }, c.n),
      h("p", { className: "caption" }, c.card)));
}

/** What the others answered about the character just swiped. */
function Result(p) {
  var c = p.vote.c, smash = p.vote.smash;
  return h("div", { className: "sp-result", role: "status", key: c.id },
    h("p", { className: "sp-result__head" },
      h(A.Badge, { tone: smash ? "success" : "danger", icon: false }, smash ? "Smash" : "Pass"),
      h("span", { className: "title-sm" }, " " + c.n)),
    h("div", { className: "sp-bar", "aria-label": c.smash + " % Smash, " + (100 - c.smash) + " % Pass" },
      h("span", { className: "sp-bar__smash", style: { width: c.smash + "%" } }, c.smash >= 12 ? c.smash + " %" : ""),
      h("span", { className: "sp-bar__pass", style: { width: (100 - c.smash) + "%" } }, c.smash <= 88 ? (100 - c.smash) + " %" : "")),
    h("p", { className: "body sp-result__say" }, verdict(c, smash), " ", h("em", null, c.quip)));
}

function Play(p) {
  var c = p.deck[p.index], next = p.deck[p.index + 1];
  var s = useState(null), fl = s[0], setFling = s[1];
  var cur = useRef(c.id); cur.current = c.id;
  useEffect(function () {
    function onKey(e) {
      if (e.key === "ArrowRight") setFling({ dir: 1, id: cur.current });
      else if (e.key === "ArrowLeft") setFling({ dir: -1, id: cur.current });
    }
    window.addEventListener("keydown", onKey);
    return function () { window.removeEventListener("keydown", onKey); };
  }, []);
  return h("div", { className: "sp-play" },
    h("header", { className: "bar" },
      h(A.Button, { variant: "secondary", icon: "close", "aria-label": "Quitter", onClick: p.onQuit }),
      h("p", { className: "title-sm sp-count" }, (p.index + 1) + " / " + p.deck.length),
      h("span", { className: "sp-score label", "aria-label": p.smashes + " Smash" }, p.smashes + " ♥")),
    h("div", { className: "sp-stack" },
      next ? h("div", { className: "sp-card is-next", "aria-hidden": "true" }, h("img", { src: art(next.id), alt: "" })) : null,
      h(SwipeCard, { key: c.id, character: c, fling: fl, onVote: p.onVote })),
    h("div", { className: "sp-actions" },
      h("button", { type: "button", className: "sp-btn sp-btn--pass", "aria-label": "Pass", onClick: function () { setFling({ dir: -1, id: c.id }); } },
        h(A.Icon, { name: "cross", size: 30 }), h("span", { className: "label" }, "Pass")),
      h("button", { type: "button", className: "sp-btn sp-btn--smash", "aria-label": "Smash", onClick: function () { setFling({ dir: 1, id: c.id }); } },
        h(A.Icon, { name: "heart", size: 30 }), h("span", { className: "label" }, "Smash"))),
    p.last ? h(Result, { vote: p.last }) : h("p", { className: "caption sp-hint" }, "Glisse la carte, ou utilise les flèches du clavier."));
}

function End(p) {
  var smashes = p.votes.filter(function (v) { return v.smash; }).length;
  var agree = p.votes.filter(function (v) { return v.smash === (v.c.smash >= 50); }).length;
  var rate = Math.round(smashes * 100 / p.votes.length), pr = profile(rate, agree);
  return h("div", { className: "sp-end" },
    h("header", { className: "bar" },
      h(A.Button, { variant: "secondary", icon: "arrow-left", "aria-label": "Tous les jeux", onClick: p.onExit }),
      h("span"), h("span")),
    h(A.Panel, { as: "section", className: "sp-endpanel" },
      h("p", { className: "ar-eyebrow eyebrow" }, "Ton bilan"),
      h("p", { className: "sp-endscore" }, smashes + " Smash"),
      h("p", { className: "caption meta" }, "sur " + p.votes.length + " personnages · d'accord avec la majorité " + agree + " fois"),
      h("p", { className: "flavor sp-quip" }, pr.taste),
      h("p", { className: "body sp-quip" }, pr.crowd)),
    h("ul", { className: "sp-recap" }, p.votes.map(function (v) {
      return h("li", { key: v.c.id, className: v.smash ? "is-smash" : "is-pass" },
        h("img", { src: art(v.c.id), alt: "" }),
        h("span", { className: "body" }, v.c.n),
        h("span", { className: "label" }, v.smash ? "Smash" : "Pass"));
    })),
    h("div", { className: "sp-endactions" },
      h(A.Button, { variant: "primary", size: "lg", block: true, icon: "replay", onClick: p.onReplay }, "Rejouer"),
      h(A.Button, { variant: "ghost", size: "md", onClick: p.onExit }, "Tous les jeux")));
}

function Game(p) {
  var s1 = useState("intro"), screen = s1[0], setScreen = s1[1];
  var s2 = useState([]), deck = s2[0], setDeck = s2[1];
  var s3 = useState(0), index = s3[0], setIndex = s3[1];
  var s4 = useState([]), votes = s4[0], setVotes = s4[1];

  useEffect(function () { window.scrollTo(0, 0); }, [screen]);
  // preload the next pictures so a swipe never shows an empty card
  useEffect(function () {
    deck.slice(index + 1, index + 3).forEach(function (c) { var i = new Image(); i.src = art(c.id); });
  }, [deck, index]);

  function start() { setDeck(shuffle(CHARACTERS.slice()).slice(0, ROUND)); setIndex(0); setVotes([]); setScreen("play"); }
  function vote(smash) {
    var all = votes.concat([{ c: deck[index], smash: smash }]);
    setVotes(all);
    if (index + 1 < deck.length) { setIndex(index + 1); return; }
    setLast({ smash: all.filter(function (v) { return v.smash; }).length, total: all.length });
    setScreen("end");
  }

  var body;
  if (screen === "intro") body = h(Intro, { onStart: start, onExit: p.onExit });
  else if (screen === "play") body = h(Play, { deck: deck, index: index, last: votes[votes.length - 1] || null,
                                               smashes: votes.filter(function (v) { return v.smash; }).length,
                                               onVote: vote, onQuit: function () { setScreen("intro"); } });
  else body = h(End, { votes: votes, onReplay: start, onExit: p.onExit });
  return h("div", { className: "app sp", "data-screen": screen }, body);
}

window.MTG.games.push({
  id: "smash",
  title: "Smash or Pass",
  pitch: "Jace, Liliana, Nicol Bolas, Emrakul… Glisse à droite ou à gauche, et compare-toi aux autres joueurs.",
  icon: "heart",
  details: ROUND + " personnages · résultats des autres joueurs",
  isNew: true,
  order: 7,
  component: Game,
  lastResult: function () { var l = getLast(); return l ? "Dernière partie : " + l.smash + " Smash sur " + l.total : null; },
});
})();
