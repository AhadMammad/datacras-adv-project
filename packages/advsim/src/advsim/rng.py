"""Seeded randomness: one `Rand` per generation stream so runs are reproducible with --seed."""
from __future__ import annotations

import bisect
import itertools
import random
import uuid
from datetime import date, datetime, time, timedelta, timezone

import numpy as np
from faker import Faker

UTC = timezone.utc


class Rand:
    """Scalar helpers on `random.Random` (fast per call) plus a numpy Generator for vectorised work."""

    def __init__(self, seed: int, stream: str = "") -> None:
        mixed = (seed * 1_000_003) ^ (hash_str(stream) & 0xFFFFFFFF)
        self.r = random.Random(mixed)
        self.np = np.random.default_rng(mixed)
        self.fake = Faker("en_US")
        self.fake.seed_instance(mixed)

    def child(self, stream: str) -> "Rand":
        return Rand(self.r.getrandbits(32), stream)

    # ------------------------------------------------------------ scalars
    def chance(self, p: float) -> bool:
        return self.r.random() < p

    def uniform(self, lo: float, hi: float) -> float:
        return self.r.uniform(lo, hi)

    def int(self, lo: int, hi: int) -> int:
        return self.r.randint(lo, hi)

    def choice(self, seq):
        return seq[self.r.randrange(len(seq))]

    def sample(self, seq, k: int):
        return self.r.sample(list(seq), min(k, len(seq)))

    def weighted(self, options: dict | list, weights: list[float] | None = None):
        if isinstance(options, dict):
            options, weights = list(options), list(options.values())
        if weights is None:
            return self.choice(options)
        cum = list(itertools.accumulate(weights))
        return options[bisect.bisect_right(cum, self.r.random() * cum[-1])]

    def skewed(self, seq, s: float = 0.8):
        """Zipf-like pick: earlier entries are more common (lists are usually ordered by relevance)."""
        return self.weighted(list(seq), [1.0 / (i + 1) ** s for i in range(len(seq))])

    def lognormal(self, median: float, sigma: float = 0.6) -> float:
        return median * self.r.lognormvariate(0.0, sigma)

    def normal(self, mu: float, sigma: float) -> float:
        return self.r.gauss(mu, sigma)

    def poisson(self, lam: float) -> int:
        return int(self.np.poisson(lam)) if lam > 0 else 0

    # ------------------------------------------------------------ time
    def date_between(self, lo: date, hi: date) -> date:
        if hi <= lo:
            return lo
        return lo + timedelta(days=self.r.randint(0, (hi - lo).days))

    def ts_on(self, d: date, business_hours: bool = True) -> datetime:
        if business_hours:
            secs = self.r.randint(8 * 3600, 19 * 3600)
        else:
            secs = self.r.randint(0, 86399)
        return datetime.combine(d, time(0), UTC) + timedelta(seconds=secs)

    def uuid7(self, ts: datetime | None = None) -> uuid.UUID:
        return uuid7(ts or datetime.now(UTC), self.r.getrandbits(74))


def uuid7(ts: datetime, rand74: int) -> uuid.UUID:
    """RFC 9562 UUIDv7 with an explicit timestamp, so historical rows get time-ordered ids."""
    ms = int(ts.timestamp() * 1000) & ((1 << 48) - 1)
    rand_a = rand74 >> 62 & 0xFFF
    rand_b = rand74 & ((1 << 62) - 1)
    value = (ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return uuid.UUID(int=value)


def hash_str(s: str) -> int:
    """Stable (unlike hash()) small string hash."""
    h = 2166136261
    for ch in s.encode():
        h = ((h ^ ch) * 16777619) & 0xFFFFFFFF
    return h
