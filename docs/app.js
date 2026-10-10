"use strict";
/* The collection's hub: lists the games and mounts the one picked.
   Each game lives in docs/games/<id>/ and registers itself in window.MTG.games:
     { id, title, pitch, icon, details, isNew, order, component, lastResult? }
   `component` is a React component that receives { onExit } (back to the hub).
   The picked game is kept in the URL hash (#guildes, #ia-ou-vraie), so a game can be linked directly.
   To add a game: a folder in games/, its <script> (and <link>) in index.html, a push() here. */

window.MTG = window.MTG || { games: [] };

(function () {
  var A = window.Artifice, h = React.createElement;
  var useState = React.useState, useEffect = React.useEffect;

  function gameFromHash() {
    var id = decodeURIComponent(location.hash.replace(/^#\/?/, ""));
    return window.MTG.games.filter(function (g) { return g.id === id; })[0] || null;
  }

  function Tile(p) {
    var g = p.game, last = g.lastResult ? g.lastResult() : null;
    return h("li", null,
      h("button", { type: "button", className: "tile" + (g.isNew ? " is-new" : ""), onClick: p.onPick,
                    "aria-label": g.title + (g.isNew ? " (nouveau)" : "") },
        g.isNew ? h("span", { className: "tile__new label", "aria-hidden": "true" }, "Nouveau") : null,
        h("span", { className: "tile__icon", "aria-hidden": "true" }, h(A.Icon, { name: g.icon || "d20", size: 28 })),
        h("span", { className: "tile__text" },
          h("span", { className: "tile__head" }, h("span", { className: "tile__title title-sm" }, g.title)),
          h("span", { className: "tile__pitch body" }, g.pitch),
          g.details ? h("span", { className: "tile__details caption" }, g.details) : null,
          last ? h("span", { className: "tile__last caption" }, last) : null),
        h("span", { className: "tile__go", "aria-hidden": "true" }, h(A.Icon, { name: "arrow-right", size: 22 }))));
  }

  function Hub(p) {
    var games = window.MTG.games.slice().sort(function (a, b) {
      return (b.isNew ? 1 : 0) - (a.isNew ? 1 : 0) || (a.order || 0) - (b.order || 0);
    });
    return h("div", { className: "app" },
      h("div", { className: "hub" },
        h("div", null,
          h("p", { className: "ar-eyebrow eyebrow" }, "Mini-jeux Magic"),
          h("h1", { className: "title-xl" }, "À quoi on joue ?")),
        h("p", { className: "flavor" }, "Choisis ton jeu. D'autres arrivent bientôt."),
        h("ul", { className: "games" }, games.map(function (g) {
          return h(Tile, { key: g.id, game: g, onPick: function () { p.onPick(g); } });
        })),
        h("div", { className: "push" },
          h("p", { className: "legal caption" },
            "Contenu de fan non officiel, autorisé par la ",
            h("a", { href: "https://company.wizards.com/fancontentpolicy", target: "_blank", rel: "noopener" }, "Fan Content Policy"),
            ". Non approuvé par Wizards. Des parties des éléments utilisés sont la propriété de Wizards of the Coast. ©Wizards of the Coast LLC."))));
  }

  function App() {
    var s = useState(gameFromHash), game = s[0], setGame = s[1];
    useEffect(function () {
      function onHash() { setGame(gameFromHash()); window.scrollTo(0, 0); }
      window.addEventListener("hashchange", onHash);
      return function () { window.removeEventListener("hashchange", onHash); };
    }, []);
    useEffect(function () {
      document.title = game ? game.title + " · Mini-jeux Magic" : "Mini-jeux Magic";
    }, [game]);

    function pick(g) { location.hash = g.id; }
    function exit() {
      // back to the hub without leaving an empty "#" in the history
      if (history.replaceState) { history.pushState(null, "", location.pathname + location.search); setGame(null); window.scrollTo(0, 0); }
      else location.hash = "";
    }
    return game ? h(game.component, { key: game.id, onExit: exit }) : h(Hub, { onPick: pick });
  }

  // the games' scripts come after this one in index.html: mount once they are all registered
  document.addEventListener("DOMContentLoaded", function () {
    ReactDOM.createRoot(document.getElementById("root")).render(h(App));
  });
})();
