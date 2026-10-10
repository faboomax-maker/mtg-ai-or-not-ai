/* Quelle guilde de Ravnica es-tu ? — questions, scoring grid and results.
   Each answer gives 1 point to a color (W white, U blue, B black, R red, G green).
   The two highest colors give the guild. A tie (between 2 to 5 colors) is settled by one or two
   extra questions (TIEBREAKS) that look like the others but only offer the tied colors' answers,
   in a random order. At most two are ever needed (5-way tie: one pick, then a 4-way tie). */
window.MTG = window.MTG || { games: [] };
window.MTG.guildesData = {
  COLORS: {
    W: { name: "Blanc", value: "la justice", hex: "#efe4c4", ink: "#3a2f17" },
    U: { name: "Bleu",  value: "la compréhension", hex: "#2f6fb5", ink: "#ffffff" },
    B: { name: "Noir",  value: "le pouvoir", hex: "#3b3139", ink: "#ffffff" },
    R: { name: "Rouge", value: "la liberté", hex: "#c4422f", ink: "#ffffff" },
    G: { name: "Vert",  value: "l'appartenance", hex: "#2f7d4f", ink: "#ffffff" },
  },
  ORDER: ["W", "U", "B", "R", "G"],

  // [question, [[answer, color] x 5]]
  QUESTIONS: [
    ["Ton projet de groupe part en vrille. Tu…", [
      ["Remotives tout le monde avec une bonne dose d'énergie", "R"],
      ["Répartis les rôles et fixes des échéances claires", "W"],
      ["Laisses les choses trouver leur rythme ; les gens finissent par suivre", "G"],
      ["Retravailles discrètement le plan pour qu'il fonctionne vraiment", "U"],
      ["T'assures que ta partie à toi se remarque", "B"]]],
    ["Un samedi de libre. Tu préfères…", [
      ["Randonner, jardiner ou être dehors", "G"],
      ["Avancer sur un projet perso qui pourrait rapporter", "B"],
      ["Aider un ami à déménager ou faire du bénévolat", "W"],
      ["Te plonger dans l'apprentissage d'un nouveau sujet", "U"],
      ["Dire oui à tout ce que tes amis proposent", "R"]]],
    ["Une règle au travail te semble absurde. Tu…", [
      ["Cherches à comprendre pourquoi elle existe avant de décider", "U"],
      ["Hausses les épaules ; ça ne vaut pas la peine de se battre", "G"],
      ["L'ignores", "R"],
      ["La respectes, et tu remontes le problème par les bons canaux", "W"],
      ["La respectes quand ça t'arrange", "B"]]],
    ["Quel compliment te touche le plus ?", [
      ["« Tu ne lâches jamais rien tant que tu n'as pas gagné. »", "B"],
      ["« Tu es tellement plein·e de vie. »", "R"],
      ["« Tu es brillant·e. »", "U"],
      ["« Tu es tellement ancré·e. »", "G"],
      ["« Je peux toujours compter sur toi. »", "W"]]],
    ["Un ami te ment pour ménager tes sentiments. Tu…", [
      ["Es blessé·e ; la confiance exige l'honnêteté", "W"],
      ["Lui dis tout de suite que ça t'énerve", "R"],
      ["Laisses passer ; c'est humain", "G"],
      ["T'en fiches, mais tu t'en souviendras", "B"],
      ["Te demandes pourquoi il pensait que tu ne pourrais pas encaisser", "U"]]],
    ["Qu'est-ce qui te fait le plus peur ?", [
      ["Perdre tes racines et tes liens", "G"],
      ["Ne jamais atteindre ton plein potentiel", "U"],
      ["Que la société sombre dans le chaos", "W"],
      ["Être coincé·e dans une vie ennuyeuse", "R"],
      ["Être impuissant·e", "B"]]],
    ["Tu reçois une grosse somme d'argent inattendue. Tu…", [
      ["La dépenses dans une expérience inoubliable", "R"],
      ["T'en sers pour prendre de l'avance", "B"],
      ["L'investis prudemment après t'être renseigné·e", "U"],
      ["En partages une partie avec ceux qui en ont besoin", "W"],
      ["La mets de côté et continues à vivre simplement", "G"]]],
    ["Dans un débat, tu…", [
      ["Appuies chaque argument par des preuves", "U"],
      ["Cherches un terrain d'entente", "W"],
      ["Joues pour gagner", "B"],
      ["Parles peu ; le temps te donnera raison", "G"],
      ["Parles avec ton cœur", "R"]]],
    ["Choisis où vivre :", [
      ["Un penthouse qui domine la ville", "B"],
      ["Une cabane dans les bois", "G"],
      ["Là où l'envie te prend, en déménageant souvent", "R"],
      ["Un endroit calme près d'une grande bibliothèque", "U"],
      ["Un quartier soudé avec une vraie vie de communauté", "W"]]],
    ["Pour les grandes décisions, tu te fies à…", [
      ["Ce qui est juste pour tout le monde", "W"],
      ["Ce qui a toujours fonctionné", "G"],
      ["Tes recherches et une liste de pour et de contre", "U"],
      ["Ton instinct", "R"],
      ["Ce qui t'avantage le plus", "B"]]],
    ["Ton rôle idéal dans une équipe :", [
      ["L'étincelle", "R"],
      ["Le stratège", "U"],
      ["Le soutien solide", "G"],
      ["Celui ou celle qui tranche les décisions difficiles", "B"],
      ["L'organisateur et médiateur", "W"]]],
    ["Le changement, c'est…", [
      ["Souvent inutile ; les choses sont comme elles doivent être", "G"],
      ["Acceptable s'il est juste et décidé ensemble", "W"],
      ["Une opportunité", "B"],
      ["Enthousiasmant quand c'est une amélioration", "U"],
      ["Le sel de la vie", "R"]]],
    ["Choisis une devise :", [
      ["« Il y a toujours une meilleure façon de faire. »", "U"],
      ["« Vis l'instant présent. »", "R"],
      ["« Ensemble, on est plus forts. »", "W"],
      ["« Chaque chose en son temps. »", "G"],
      ["« Quoi qu'il en coûte. »", "B"]]],
    ["Quelqu'un te fait du tort. Tu…", [
      ["Fais en sorte qu'il le regrette, tôt ou tard", "B"],
      ["Cherches à comprendre pourquoi pour que ça ne se reproduise pas", "U"],
      ["Le confrontes immédiatement", "R"],
      ["Veux une conséquence juste", "W"],
      ["Passes à autre chose ; tout finit par s'équilibrer", "G"]]],
    ["Tu aimerais qu'on se souvienne de toi pour…", [
      ["Avoir rendu ta communauté meilleure", "W"],
      ["Ce que tu as transmis aux autres", "G"],
      ["Ce que tu as construit et accompli", "B"],
      ["Une vie pleinement vécue", "R"],
      ["Une découverte ou une création", "U"]]],
  ],

  TIEBREAKS: [
    ["Au fond, qu'est-ce qui compte le plus pour toi ?", {
      W: "Que chacun soit traité de façon juste",
      U: "Comprendre comment les choses fonctionnent vraiment",
      B: "Avoir les cartes en main pour décider de ton destin",
      R: "Être libre de vivre comme tu l'entends",
      G: "Avoir un endroit et des gens auxquels appartenir" }],
    ["Si tu ne pouvais garder qu'une seule de ces qualités, ce serait…", {
      W: "Ton sens de l'équité",
      U: "Ta curiosité",
      B: "Ton ambition",
      R: "Ta spontanéité",
      G: "Ta loyauté envers les tiens" }],
  ],

  // key = the two colors in WUBRG order.
  // types: the personality profile; for two profiles, the one of the guild's stronger color
  // (both, joined by « ou », when the two colors are equal).
  GUILDS: {
    WU: { id: "azorius",  name: "Azorius",  text: "Tu crois que de bons systèmes font un monde meilleur. Loyal à la loi, logique, en gros t'es boring as fuck.", types: { U: "ISTJ", W: "ESTJ" } },
    UB: { id: "dimir",    name: "Dimir",    text: "Discret, malin, toujours trois coups d'avance. Tu en sais plus que tu n'en dis. Coquin, va.", types: { U: "INTJ", B: "ISTP" } },
    BR: { id: "rakdos",   name: "Rakdos",   text: "Tu vis pour l'intensité et tu ne t'excuses jamais d'en vouloir plus. ONE LIFE, AM I RIGHT?", types: "ESFP" },
    RG: { id: "gruul",    name: "Gruul",    text: "Sauvage et sincère. Tu fais confiance à ton instinct plutôt qu'aux règles, et tu détestes qu'on te dompte. Esprit Gigachad.", types: { R: "ESTP", G: "ENFP" } },
    WG: { id: "selesnya", name: "Selesnya", text: "L'harmonie et la communauté avant tout. Avec toi, les gens se sentent chez eux. Tranquille man, t'aurais pas une roulée à dépanne? Peace!", types: { G: "ISFJ", W: "ESFJ" } },
    WB: { id: "orzhov",   name: "Orzhov",   text: "Tu sais que l'ordre et le pouvoir vont de pair, et tu sais te servir des deux. Un grindset t'as peur.", types: "ENTJ" },
    UR: { id: "izzet",    name: "Izzet",    text: "Curieux, chaotique, brillant. Tes idées explosent parfois, et c'est ça le plus drôle. Une sorte de fou du bus mais en + smart.", types: { R: "ENTP", U: "INTP" } },
    BG: { id: "golgari",  name: "Golgari",  text: "Patient et pragmatique. Tout naît et tout disparaît, et tu prospères dans ce cycle. Te self-mill c'est carrément un loisir à ce stade.", types: "ISFP" },
    WR: { id: "boros",    name: "Boros",    text: "Passionné de justice. Quand quelque chose ne va pas, tu es le premier à agir. Gaab te first pack first pick.", types: "ENFJ" },
    UG: { id: "simic",    name: "Simic",    text: "Tu aimes la croissance et le progrès, toujours à te demander comment les choses pourraient évoluer. Mi-requin, mi-pieuvre, 100% gay.", types: { U: "INFJ", G: "INFP" } },
  },
};
