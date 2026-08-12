#!/usr/bin/env python3
"""Map peekbank target words to CDI categories via the wordbank dataset on
Redivis (English (American) Words & Sentences form): semantic `category`
(animals, vehicles, colors-ish via descriptive_words, ...) and
`lexical_category` (nouns, predicates, function_words, other).

Reads slices/words.json (the peekbank word universe), writes
slices/word_categories.json {word: [category, lexical_category]}. Unmatched
words get no entry (the page treats them as "uncategorized").

Usage: .venv/bin/python scripts/build_word_categories.py
"""

import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for line in open(ROOT / ".secrets"):
    if "=" in line:
        k, v = line.strip().split("=", 1)
        os.environ.setdefault(k, v)

import redivis  # noqa: E402


def normalize(s):
    s = s.lower().strip()
    s = re.sub(r"\s*\(.*?\)\s*", "", s)   # "chicken (animal)" -> "chicken"
    s = s.replace("*", "")
    return s.strip()


def main():
    words = json.load(open(ROOT / "slices" / "words.json"))
    items = redivis.organization("datapages").dataset("wordbank:627v").query(
        "SELECT item_definition, category, lexical_category FROM items "
        "WHERE language = 'English (American)' AND form = 'WS' "
        "AND item_kind = 'word'").to_pandas_dataframe()

    # index CDI definitions by every normalized variant ("inside/in" -> both)
    index = {}
    for _, row in items.iterrows():
        for variant in normalize(row.item_definition).split("/"):
            variant = variant.strip()
            if variant and variant not in index:
                index[variant] = (row.category, row.lexical_category)

    # CDI has no "colors" category (they live in descriptive_words); the team
    # asked for one, so overlay it for the standard color terms
    COLORS = {"red", "blue", "green", "yellow", "orange", "purple", "pink",
              "brown", "black", "white", "gray", "grey"}

    mapping = {}
    for w in words:
        norm = normalize(w)
        hit = index.get(norm)
        if norm in COLORS:
            mapping[w] = ["colors", hit[1] if hit else "descriptive_words"]
        elif hit:
            mapping[w] = [hit[0], hit[1]]

    out = ROOT / "slices" / "word_categories.json"
    out.write_text(json.dumps(mapping, separators=(",", ":"), sort_keys=True))
    cats = sorted({v[0] for v in mapping.values()})
    print(f"{len(mapping)}/{len(words)} peekbank words matched to CDI items")
    print(f"categories: {cats}")


if __name__ == "__main__":
    main()
