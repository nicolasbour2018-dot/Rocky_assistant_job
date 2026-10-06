"""G2: compare two runs of ``count.py`` (before and after a change of rules) on the same offers (see README.md).

Prints the rank correlation, the offers that cross the threshold and the biggest moves. Standard library only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

THRESHOLD = 50


def _ranks(values: list[float]) -> list[float]:
    """Average ranks (ties share their mean rank)."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        for position in range(start, end + 1):
            ranks[order[position]] = (start + end) / 2
        start = end + 1
    return ranks


def spearman(left: list[float], right: list[float]) -> float:
    a, b = _ranks(left), _ranks(right)
    mean_a, mean_b = sum(a) / len(a), sum(b) / len(b)
    covariance = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b, strict=True))
    spread = (sum((x - mean_a) ** 2 for x in a) * sum((y - mean_b) ** 2 for y in b)) ** 0.5
    return covariance / spread if spread else 1.0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--top", type=int, default=15)
    args = parser.parse_args()
    before: dict[str, Any] = json.loads(args.before.read_text())
    after: dict[str, Any] = json.loads(args.after.read_text())
    ids = sorted(set(before["offers"]) & set(after["offers"]), key=int)
    old = [int(before["offers"][i]["display"]) for i in ids]
    new = [int(after["offers"][i]["display"]) for i in ids]
    up = [i for i, o, n in zip(ids, old, new, strict=True) if o < THRESHOLD <= n]
    down = [i for i, o, n in zip(ids, old, new, strict=True) if n < THRESHOLD <= o]
    moved = sum(1 for o, n in zip(old, new, strict=True) if o != n)
    print(f"# {before['rules_version']} → {after['rules_version']} : {len(ids)} offres")
    print()
    print(f"- corrélation de rang (Spearman) : {spearman(old, new):.2f}")
    print(f"- scores changés : {moved} ; moyenne {sum(old) / len(old):.1f} → {sum(new) / len(new):.1f}")
    print(f"- passent au-dessus du seuil ({THRESHOLD}) : {len(up)} ; passent dessous : {len(down)}")
    top_old = set(sorted(ids, key=lambda i: -int(before["offers"][i]["display"]))[: args.top])
    top_new = sorted(ids, key=lambda i: -int(after["offers"][i]["display"]))[: args.top]
    print(f"- {args.top} premières communes aux deux classements : {len(top_old & set(top_new))}")
    print()
    print("Plus fortes hausses :")
    print()
    print("| Id | Lieu | Avant | Après | Lieu (après) |")
    print("|---|---|---|---|---|")
    rises = sorted(ids, key=lambda i: int(before["offers"][i]["display"]) - int(after["offers"][i]["display"]))
    for i in rises[: args.top]:
        item = after["offers"][i]
        print(
            f"| {i} | {item['location'] or '—'} | {before['offers'][i]['display']} | {item['display']} "
            f"| {item['location_detail']} |"
        )
    if down:
        print()
        print("Passent sous le seuil :", ", ".join(down))


if __name__ == "__main__":
    main()
