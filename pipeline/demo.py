"""Tiny offline demo dataset so the site works right after cloning.

Six classic real cards (text only, placeholder art) + six hand-written fakes.
Run the real pipeline (fetch_real -> generate_fake -> build) to replace it.
"""
from __future__ import annotations

import random
import secrets
import shutil
from urllib.parse import quote

from build import seal
from common import DOCS, normalize_image, save_json
from placeholder import gradient_jpeg


def card(name, cost, type_line, text, rarity, colors, flavor=None, pt=None):
    p, t = (pt.split("/") if pt else (None, None))
    return {"name": name, "mana_cost": cost, "type_line": type_line, "oracle_text": text,
            "flavor_text": flavor, "power": p, "toughness": t, "loyalty": None,
            "rarity": rarity, "colors": list(colors)}


REAL = [
    card("Lightning Bolt", "{R}", "Instant", "Lightning Bolt deals 3 damage to any target.", "common", "R"),
    card("Llanowar Elves", "{G}", "Creature — Elf Druid", "{T}: Add {G}.", "common", "G", pt="1/1"),
    card("Serra Angel", "{3}{W}{W}", "Creature — Angel", "Flying, vigilance", "uncommon", "W", pt="4/4"),
    card("Counterspell", "{U}{U}", "Instant", "Counter target spell.", "uncommon", "U"),
    card("Giant Growth", "{G}", "Instant", "Target creature gets +3/+3 until end of turn.", "common", "G"),
    card("Doom Blade", "{1}{B}", "Instant", "Destroy target nonblack creature.", "common", "B"),
]
FAKE = [
    card("Emberwake Duelist", "{1}{R}", "Creature — Human Warrior",
         "First strike\nWhenever you cast an instant or sorcery spell, this creature gets +1/+0 until end of turn.",
         "uncommon", "R", "\"Steel is patient. Fire is not.\"", "2/1"),
    card("Tidecaller's Rebuke", "{1}{U}", "Instant",
         "Return target nonland permanent to its owner's hand. Scry 1.", "common", "U",
         "The sea gives back everything, eventually."),
    card("Mossback Sentinel", "{3}{G}", "Creature — Plant Elemental",
         "Reach\nWhen this creature enters, you gain 3 life.", "common", "G", pt="3/5"),
    card("Gravewhisper Toll", "{2}{B}", "Sorcery",
         "Each opponent sacrifices a creature. You draw a card.", "uncommon", "B"),
    card("Dawnbreak Vigil", "{1}{W}", "Enchantment",
         "When this enchantment enters, create a 1/1 white Soldier creature token.\nCreatures you control get +0/+1.",
         "common", "W", "—Captain Ilsa Marrow"),
    card("Clockwork Harrier", "{3}", "Artifact Creature — Construct",
         "Flying\n{1}: This creature gets +1/-1 until end of turn.", "common", "", pt="1/3"),
]


def main() -> None:
    img_dir = DOCS / "img"
    shutil.rmtree(img_dir, ignore_errors=True)
    out = []
    pool = [(c, True) for c in REAL] + [(c, False) for c in FAKE]
    random.shuffle(pool)
    for c, is_real in pool:
        name = secrets.token_hex(8) + ".jpg"
        normalize_image(gradient_jpeg(random.randint(1, 10**9)), img_dir / name)
        secret = {"real": is_real}
        if is_real:
            secret.update(set="Carte classique (démo)", artist=None,
                          url="https://scryfall.com/search?q=" + quote(f'!"{c["name"]}"'))
        out.append({**c, "img": name, "s": seal(secret, name)})
    save_json(DOCS / "data" / "cards.json", {"generated": "demo", "count": len(out), "cards": out})
    print(f"Demo data written: {len(out)} cards")


if __name__ == "__main__":
    main()
