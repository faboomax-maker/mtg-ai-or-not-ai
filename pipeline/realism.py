"""Checks and fixes that make AI cards match the real cards of their set.

Everything here is learned from the set's real cards (printed text) rather than
left to the LLM: reminder texts, "enters the battlefield" wording, collector
number ranges by colour, plausible artist names.
"""
from __future__ import annotations

import random
import re
from collections import Counter

# ------------------------------------------------------------ reminder texts
PAREN = re.compile(r"\s*\(([^()]*)\)")


def _clause(text: str, end: int) -> str:
    """The clause right before position `end`: 'Flying', 'venture into the dungeon'."""
    start = max(text.rfind(sep, 0, end) for sep in ("\n", ". ", ", ", ": ", "—", ")"))
    clause = text[start + 1:end].strip(" .,:—•\n")
    return re.sub(r"\s+", " ", clause).lower()


def _last_keyword(clause: str, keywords) -> str | None:
    """The keyword that ends the clause (the one a reminder text right after it explains)."""
    best, pos = None, -1
    for kw in keywords:
        for m in re.finditer(rf"\b{re.escape(kw.lower())}\w*", clause):   # explore(s), venture(d)
            # the reminder explains the keyword only if it closes the clause
            # ("create a Treasure token", "scry 2"), not one mentioned earlier in it
            if m.start() > pos and len(clause[m.end():].split()) <= 3:
                best, pos = kw.lower(), m.start()
    return best


def rarity_class(rarity: str) -> str:
    return "low" if rarity in ("common", "uncommon") else "high"


def reminder_texts(pool: list[dict]) -> tuple[dict[str, str], dict[str, str], dict]:
    """({clause: reminder}, {keyword: reminder}, {(keyword, rarity class): share of cards
    printing that keyword's reminder}) from the printed text of a set's cards."""
    by_clause: dict[str, Counter] = {}
    by_keyword: dict[str, Counter] = {}
    seen, reminded = Counter(), Counter()
    for c in pool:
        text = c.get("oracle_text") or ""
        cls = rarity_class(c.get("rarity", ""))
        for kw in {k.lower() for k in c.get("keywords") or []}:
            seen[kw, cls] += 1
        explained = set()
        for m in PAREN.finditer(text):
            rem, clause = m.group(1).strip(), _clause(text, m.start())
            if not clause:
                continue
            by_clause.setdefault(clause, Counter())[rem] += 1
            # parametrised reminders (Ward {2}, Kicker {1}{R}) are only reused by clause
            if re.search(r"[{\d]|\b(?:two|three|four|five|six|seven|x)\b", clause):
                continue                         # "scry 2" / "mill three": number-specific
            line = text[text.rfind("\n", 0, m.start()) + 1:m.start()].lower()
            kws = [k.lower() for k in c.get("keywords") or []]
            # "(To behold a Dragon, ...)" names its keyword; otherwise the keyword must close
            # the clause right before the parenthesis ("create a Treasure token", "Menace")
            named = [k for k in kws if re.search(rf"\b{re.escape(k[:5])}", rem.lower())]
            if named:
                kw = named[0] if re.search(rf"\b{re.escape(named[0][:5])}", line) else None
            else:
                kw = _last_keyword(clause, kws)
            if kw:
                by_keyword.setdefault(kw, Counter())[rem] += 1
                explained.add(kw)
        for kw in explained:
            reminded[kw, cls] += 1
    pick = lambda d: {k: v.most_common(1)[0][0] for k, v in d.items()}
    rates = {key: reminded[key] / n for key, n in seen.items() if n}
    return pick(by_clause), pick(by_keyword), rates


def add_missing_reminders(text: str, rarity: str, by_keyword: dict, rates: dict,
                          by_clause: dict | None = None) -> str:
    """Add the set's reminder text after a keyword the set usually explains at this rarity
    (e.g. explore on commons), when the LLM left it out."""
    cls = rarity_class(rarity)
    for kw, rem in by_keyword.items():
        if rates.get((kw, cls), 0) < 0.5 or rem in text:
            continue
        m = re.search(rf"\b{re.escape(kw)}\w*", PAREN.sub(lambda p: " " * len(p.group(0)), text), re.I)
        if not m:
            continue
        end = min([i for i in (text.find(".", m.end()), text.find("\n", m.end())) if i != -1]
                  or [len(text)])
        end += 1 if end < len(text) and text[end] == "." else 0
        if not text[end:].lstrip(" ").startswith("("):
            # exact wording for this phrase if the set prints it ("...on that creature...")
            rem = (by_clause or {}).get(_clause(text, end), rem)
            text = f"{text[:end]} ({rem}){text[end:]}"
    return text


# --------------------------------------------------------------- templating
# Rules wording that changed over time: (date the new wording was first printed, old, new)
ERA_TERMS = [
    ("2017-04-28", r"\btarget creature or player\b", "any target"),                # Amonkhet
    ("2021-04-23", r"\bconverted mana cost\b", "mana value"),                        # Strixhaven
]


def fix_templating(text: str, released_at: str = "") -> str:
    """Printed-card templating the LLM often gets wrong: 'Draw a card', not 'You draw a card';
    and the wording of the set's era ('any target' since 2017, 'mana value' since 2021)."""
    text = re.sub(r"(^|\n|[.:] |, | and | then |— |• )[Yy]ou (draw|create|scry|surveil|investigate)\b",
                  lambda m: m.group(1) + (m.group(2) if m.group(1) in (", ", " and ", " then ")
                                          else m.group(2).capitalize()),
                  text)
    for since, old, new in ERA_TERMS:
        if released_at and released_at >= since:
            text = re.sub(old, new, text)
        elif released_at and new == "mana value":
            text = re.sub(r"\bmana value\b", "converted mana cost", text)
    return text


def misused_keywords(text: str, abilities: set[str], actions: set[str], ability_words: set[str]) -> list[str]:
    """Keyword actions/ability words written as a standalone keyword line ('Connive 1')."""
    bad = []
    for line in PAREN.sub("", text).split("\n"):
        line = line.strip().rstrip(".")
        if not line or re.search(r"[.:—]", line):
            continue                               # a sentence or an activated ability
        for part in line.split(", "):
            head = re.sub(r"(\s*\{[^}]*\})+.*$|\s+(\d+|x)$", "", part.strip().lower())
            if head and head not in abilities and (head in actions or head in ability_words):
                bad.append(part.strip())
    return bad


def too_simple(text: str, rarity: str, type_line: str) -> bool:
    """Rares and mythics are distinctive designs, not one short line."""
    core = PAREN.sub("", text or "").strip()
    return rarity in ("rare", "mythic") and "Planeswalker" not in type_line and len(core) < 70


# ------------------------------------------------------------------- names
OVERUSED = {"insight", "whisper", "whisperer", "whispers", "echo", "echoes", "arcane", "ethereal",
            "azure", "azurewing", "tempest", "veil", "mystic", "enigma", "celestial", "luminous",
            "eldritch", "shimmering", "radiant", "arcanist"}
STOP = {"the", "of", "and", "a", "an", "to", "in", "from", "for", "with"}


def name_words(name: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", name.lower().replace("'s", "")) if w not in STOP and len(w) > 2}


def name_problem(name: str, used_words: set[str]) -> str | None:
    words = name_words(name)
    if words & OVERUSED:
        return f"overused AI word {sorted(words & OVERUSED)}"
    if words & used_words:
        return f"word already used in another AI name {sorted(words & used_words)}"
    return None


# -------------------------------------------------------------- art briefs
CLICHES = re.compile(r"\b(hood(?:ed)?|cloak(?:ed)?|silhouett\w*|from behind|back to the viewer|"
                     r"facing away|faceless|neon)\b", re.I)
GLOW = re.compile(r"\b(?:softly |brightly |faintly |eerily )?(?:glowing|luminous|luminescent|"
                  r"shimmering|ethereal|radiant|bioluminescent)\s+", re.I)


def art_problem(brief: str) -> str | None:
    m = CLICHES.search(brief or "")
    return f"cliché in art brief ({m.group(0)!r})" if m else None


def tone_down(brief: str) -> str:
    """Drop the 'glowing/luminous/ethereal' adjectives image models overdo."""
    return GLOW.sub("", brief)


def fix_reminders(text: str, by_clause: dict, by_keyword: dict) -> str:
    """Replace the LLM's reminder texts by the set's real ones; drop those we can't verify."""
    out, last = [], 0
    for m in PAREN.finditer(text):
        clause = _clause(text, m.start())
        kw = _last_keyword(clause, by_keyword)
        rem = by_clause.get(clause) or (by_keyword[kw] if kw else None)
        out.append(text[last:m.start()])
        if rem:
            out.append(f" ({rem})")
        last = m.end()
    out.append(text[last:])
    return "".join(out)


# ------------------------------------------------------------------ wording
def uses_old_wording(pool: list[dict]) -> bool | None:
    """True if the set says 'enters the battlefield', False if just 'enters', None if unknown."""
    old = sum("enters the battlefield" in (c.get("oracle_text") or "") for c in pool)
    new = sum(bool(re.search(r"\benters(?! the battlefield)\b", PAREN.sub("", c.get("oracle_text") or "")))
              for c in pool)
    if not old and not new:
        return None
    return old >= new


def _self_name(name: str, type_line: str) -> str:
    return name.split(",")[0] if "Legendary" in type_line else name


def fix_wording(text: str, name: str, type_line: str, old: bool | None) -> str:
    """Put 'enters (the battlefield)' and self-references in the set's era wording
    (outside reminder text, which keeps its own printed wording)."""
    if old is None:
        return text
    parts = re.split(r"(\([^()]*\))", text)
    kind = next((k for k in ("creature", "artifact", "enchantment", "land", "planeswalker")
                 if k in type_line.lower()), "permanent")
    for i in range(0, len(parts), 2):          # even parts are outside parentheses
        p = parts[i]
        if old:
            p = re.sub(r"\benters\b(?! the battlefield)", "enters the battlefield", p)
            p = re.sub(rf"\b[Tt]his {kind}\b", _self_name(name, type_line), p)
        else:
            p = p.replace("enters the battlefield", "enters")
            if "Legendary" not in type_line:     # since 2024: "this creature", not the card name
                n = re.escape(name)
                p = re.sub(rf"(^|\n|[.!?] |• |— ){n}\b", rf"\g<1>This {kind}", p)
                p = re.sub(rf"\b{n}\b", f"this {kind}", p)
        parts[i] = p
    return "".join(parts)


# -------------------------------------------------------- collector numbers
GROUP_ORDER = "WUBRGMAL"


def color_group(colors: list[str] | str, type_line: str) -> str:
    """Printed order inside a set: W, U, B, R, G, multicolour, artifacts/colourless, lands."""
    cols = [c for c in (colors if isinstance(colors, list) else list(colors)) if c in "WUBRG"]
    if "Land" in type_line and "Creature" not in type_line:
        return "L"
    if len(cols) > 1:
        return "M"
    if cols:
        return cols[0]
    return "A"


def number_in_group(pool: list[dict], group: str, taken: set[str], size: int | None) -> str:
    """A free collector number inside the range where the set prints this colour group."""
    nums = sorted(int(c["collector_number"]) for c in pool
                  if str(c.get("collector_number") or "").isdigit()
                  and color_group(c.get("colors") or [], c["type_line"]) == group
                  and (not size or int(c["collector_number"]) <= size))
    if nums:   # ignore the odd outliers (10% on each side) that stretch a colour's range
        k = len(nums) // 10
        lo, hi = nums[k], nums[-1 - k]
    else:
        lo, hi = 1, size or 250
    free = [n for n in range(lo, hi + 1) if str(n) not in taken]
    return str(random.choice(free or range(lo, hi + 1)))


# ------------------------------------------------------------ artist names
# Ordinary names from many backgrounds, like the real credits (Chris Rahn, Anna Pavleeva...).
FIRST = ["Adam", "Alexandre", "Aleksi", "Ana", "Andrea", "Anton", "Ben", "Bruno", "Camille", "Carlos",
         "Chen", "Dan", "Daniela", "David", "Diego", "Dmitry", "Emma", "Eric", "Fernanda", "Filip",
         "Greg", "Hana", "Igor", "Ivan", "Jakub", "James", "Jana", "Javier", "Jesper", "Joanna",
         "Jonas", "Julia", "Kai", "Karl", "Katarzyna", "Kevin", "Laura", "Leon", "Lucas", "Maciej",
         "Marco", "Maria", "Marta", "Matt", "Mike", "Min-jun", "Nadia", "Nikolai", "Olga", "Oscar",
         "Pablo", "Paul", "Pedro", "Rafael", "Rebecca", "Ricardo", "Robin", "Ryan", "Sara", "Sam",
         "Sergey", "Sofia", "Steve", "Taylor", "Tomas", "Victor", "Yuki", "Zoltan"]
LAST = ["Alvarez", "Andersen", "Baranov", "Becker", "Bianchi", "Borges", "Brandt", "Carter", "Castro",
        "Costa", "Dąbrowski", "Duarte", "Eriksson", "Fischer", "Fonseca", "Garcia", "Gomez", "Hansen",
        "Hayes", "Holm", "Ivanova", "Jensen", "Kaminski", "Kim", "Kowalski", "Kuznetsov", "Lang",
        "Lee", "Lindqvist", "Lopes", "Martins", "Meyer", "Miller", "Moreau", "Nakamura", "Nguyen",
        "Novak", "Oliveira", "Park", "Petrov", "Pham", "Quinn", "Reyes", "Rossi", "Santos", "Sato",
        "Schmidt", "Silva", "Sokolov", "Stone", "Szabo", "Tanaka", "Torres", "Varga", "Vasquez",
        "Walsh", "Weber", "Wright", "Yamada", "Zhang", "Zielinski"]


def artist_name(real_artists: set[str], used: set[str]) -> str:
    """A plausible illustrator name: not a real Magic artist, no first or last name reused."""
    used_parts = {p for n in used for p in n.lower().split()}
    for _ in range(500):
        first, last = random.choice(FIRST), random.choice(LAST)
        name = f"{first} {last}"
        if (name.lower() not in real_artists and first.lower() not in used_parts
                and last.lower() not in used_parts):
            used.add(name)
            return name
    name = f"{random.choice(FIRST)} {random.choice(LAST)}"
    used.add(name)
    return name


# ------------------------------------------------------------ art direction
def art_focus(type_line: str) -> str:
    """Composition brief by card type, like the art descriptions Wizards gives its artists."""
    t = type_line.lower()
    if "land" in t and "creature" not in t:
        return "a landscape of a specific place in this world, no main character"
    if "equipment" in t or ("artifact" in t and "creature" not in t):
        return "the object itself, in use or on display, in a telling setting"
    if "instant" in t or "sorcery" in t:
        return "a single dramatic moment showing the spell's effect on specific characters"
    if "enchantment" in t:
        return "the enchantment's lasting effect on a place or on characters"
    if "planeswalker" in t:
        return "the planeswalker, three-quarter view facing the viewer, casting magic"
    return random.choice([
        "the creature, medium shot, facing the viewer, in action",
        "the creature in its habitat, full body, dynamic pose",
        "close portrait of the creature with a telling background detail",
        "the creature confronting a foe, seen from a low angle",
    ])
