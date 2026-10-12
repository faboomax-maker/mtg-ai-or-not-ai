"""« Est-ce légal ? » - checks every card of the situations against its Scryfall Oracle text.

Called by fetch_prices.py with the Scryfall "Oracle Cards" it has already downloaded. Reads
docs/games/legal/scenarios.json ("checks": {card name: [rules]}) and writes docs/data/legal-cards.json:
the image id of each card, and the situations whose cards all pass ("valid"). The game only shows
those: if Wizards changes a card's Oracle text, the situation disappears instead of showing a wrong
answer (and the workflow log says which rule failed).

A rule is a piece of Oracle text (case-insensitive; curly quotes and the minus sign normalized), or:
  type:<text>   in the type line          cost:<cost>  the exact mana cost ("cost:" = no mana cost)
  pt:<p>/<t>    power/toughness           loyalty:<n>  starting loyalty
  color:<C>     one of the card's colors
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path


def norm(s: str | None) -> str:
    return (s or "").replace("’", "'").replace("−", "-").replace("—", "-").lower()


def failures(card: dict, rules: list[str]) -> list[str]:
    bad = []
    for r in rules:
        if r.startswith("type:"):
            ok = norm(r[5:]) in norm(card.get("type_line"))
        elif r.startswith("cost:"):
            ok = (card.get("mana_cost") or "") == r[5:]
        elif r.startswith("pt:"):
            ok = f"{card.get('power')}/{card.get('toughness')}" == r[3:]
        elif r.startswith("loyalty:"):
            ok = str(card.get("loyalty")) == r[8:]
        elif r.startswith("color:"):
            ok = r[6:] in (card.get("colors") or [])
        else:
            ok = norm(r) in norm(card.get("oracle_text"))
        if not ok:
            bad.append(r)
    return bad


def build(cards: list[dict], scenarios: Path, out: Path) -> None:
    data = json.loads(scenarios.read_text(encoding="utf-8"))
    by_name: dict[str, dict] = {}
    for c in cards:                                   # one entry per name; paper cards first
        if c.get("name") in data["checks"] and (c["name"] not in by_name or by_name[c["name"]].get("digital")):
            by_name[c["name"]] = c
    result, ok_names = {}, set()
    for name, rules in data["checks"].items():
        c = by_name.get(name)
        if not c:
            print(f"Est-ce légal : carte introuvable : {name}")
            continue
        bad = failures(c, rules)
        if bad:
            print(f"Est-ce légal : {name} ne correspond plus au texte Oracle : {bad}")
        else:
            ok_names.add(name)
        result[name] = {"id": c["id"], "ok": not bad}

    valid = []
    for sc in data["scenarios"]:
        names = {st["card"]["n"] for st in sc.get("stack", [])}
        for side in ("opp", "you"):
            for zone in ("battlefield", "hand", "graveyard", "command", "exile"):
                v = sc[side].get(zone)
                if isinstance(v, list):
                    names.update(x["n"] for x in v)
        if names <= ok_names:
            valid.append(sc["id"])
        else:
            print(f"Est-ce légal : situation retirée ({sc['id']}) : {sorted(names - ok_names)}")
    out.write_text(json.dumps({"generated": dt.date.today().isoformat(), "cards": result, "valid": valid},
                              ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Est-ce légal : {len(ok_names)}/{len(data['checks'])} cartes vérifiées, "
          f"{len(valid)}/{len(data['scenarios'])} situations publiées -> {out}")
