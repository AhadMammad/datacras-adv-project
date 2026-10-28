"""Random strings matching the (simple) regexes used in the model's CHECK constraints.

Generalises advgen.emit_smoke.regex_sample (shortest match) to random matches, using the
same parse tree from Python's own regex parser.
"""
from __future__ import annotations

import re
import re._constants as C
import re._parser as P
import string
from functools import lru_cache

from ..rng import Rand

DIGITS = string.digits
UPPER = string.ascii_uppercase
LOWER = string.ascii_lowercase
MAX_EXTRA = 6  # unbounded repeats (+, *) add at most this many items


@lru_cache(maxsize=None)
def parsed(pattern: str):
    return P.parse(pattern)


def charset(items) -> str:
    """Expand a character class parse into the concrete printable characters it allows."""
    negate = items and items[0][0] is C.NEGATE
    chars = set()
    for op, av in items[1:] if negate else items:
        if op is C.LITERAL:
            chars.add(chr(av))
        elif op is C.RANGE:
            chars.update(chr(c) for c in range(av[0], av[1] + 1))
        elif op is C.CATEGORY:
            chars.update({C.CATEGORY_DIGIT: DIGITS, C.CATEGORY_SPACE: " ",
                          C.CATEGORY_WORD: UPPER + LOWER + DIGITS + "_"}.get(av, LOWER))
    if negate:
        return "".join(ch for ch in LOWER + DIGITS if ch not in chars)
    return "".join(sorted(chars))


def sample(pattern: str, rnd: Rand) -> str:
    def gen(items) -> str:
        out = []
        for op, av in items:
            if op is C.LITERAL:
                out.append(chr(av))
            elif op is C.ANY:
                out.append(rnd.choice(LOWER))
            elif op is C.IN:
                out.append(rnd.choice(charset(av)))
            elif op in (C.MAX_REPEAT, C.MIN_REPEAT, C.POSSESSIVE_REPEAT):
                lo, hi, sub = av
                hi = lo + MAX_EXTRA if hi is C.MAXREPEAT else hi
                n = rnd.int(lo, max(lo, min(hi, lo + MAX_EXTRA)))
                out.extend(gen(sub) for _ in range(n))
            elif op is C.SUBPATTERN:
                out.append(gen(av[-1]))
            elif op is C.BRANCH:
                out.append(gen(rnd.choice(av[1])))
            elif op is C.CATEGORY:
                out.append(rnd.choice(DIGITS if av is C.CATEGORY_DIGIT else LOWER))
            elif op is C.AT:
                continue
            else:
                raise ValueError(f"unsupported regex op {op} in {pattern!r}")
        return "".join(out)

    for _ in range(20):
        s = gen(parsed(pattern))
        if re.search(pattern, s):
            return s
    raise ValueError(f"could not sample {pattern!r}")
