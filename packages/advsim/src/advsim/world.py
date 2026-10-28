"""The simulated agency: shared state and helpers used by every scenario.

A World holds the registry of generated rows plus typed handles on the business objects that
later scenarios need (advertisers with their contracts, suppliers, campaigns with their line
items...). Backfill builds a World from scratch; the stream engine rebuilds one from the
databases and keeps extending it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .config import Settings
from .lifecycle import Lifecycles
from .registry import Registry
from .rng import UTC, Rand
from .schema import Schema
from .values import pools
from .values.generic import Ctx, Filler

KINDS = ("display", "video", "ctv", "native", "audio", "social", "dooh")


@dataclass
class Advertiser:
    row: dict
    label: str
    domain: str
    industry: str
    budget: float                      # annual media budget (USD)
    geo: tuple
    brands: list[dict] = field(default_factory=list)
    msa: dict | None = None
    relationship: dict | None = None
    sows: dict[int, dict] = field(default_factory=dict)  # year -> sow
    rate_card: dict | None = None
    attribution_model: dict | None = None
    pixels: list[dict] = field(default_factory=list)
    segments: list[dict] = field(default_factory=list)
    suppression: dict | None = None
    team: list[str] = field(default_factory=list)
    cost_center: dict | None = None
    churned: date | None = None

    @property
    def id(self):
        return self.row["advertiser_id"]


@dataclass
class Supply:
    supplier: dict
    kind: str                           # publisher | tech | production | data
    publisher: dict | None = None
    tech: dict | None = None
    properties: list[dict] = field(default_factory=list)
    placements: list[dict] = field(default_factory=list)   # catalog placements (media.placement)
    rate_card: dict | None = None
    agreement: dict | None = None
    channel_kinds: list[str] = field(default_factory=list)


@dataclass
class LineItem:
    row: dict
    kind: str
    flight: dict
    campaign: "Campaign"
    supply: Supply
    placement: dict                     # media_placement
    cpm: float
    budget: float
    start: date
    end: date
    ads: list[dict] = field(default_factory=list)
    assets: list[dict] = field(default_factory=list)
    deal: dict | None = None
    segment: dict | None = None
    io: dict | None = None
    plan_line: dict | None = None
    buy: dict | None = None
    io_line: dict | None = None
    pacing_rule: dict | None = None
    trafficking_order: dict | None = None
    instruction: dict | None = None
    activation: dict | None = None
    kpi_target: dict | None = None
    budget_line: dict | None = None
    daily: dict = field(default_factory=dict)  # date -> DayDelivery (real, unsampled counts)

    @property
    def id(self):
        return self.row["line_item_id"]


@dataclass
class Campaign:
    row: dict
    adv: Advertiser
    brand: dict
    start: date
    end: date
    budget: float
    status: str
    flights: list[dict] = field(default_factory=list)
    line_items: list[LineItem] = field(default_factory=list)
    ios: dict = field(default_factory=dict)      # supplier_id -> media_insertion_order
    client_io: dict | None = None
    plan: dict | None = None
    initiative: dict | None = None
    finance_budget: dict | None = None
    creative_brief: dict | None = None

    @property
    def id(self):
        return self.row["campaign_id"]


class World:
    def __init__(self, settings: Settings, schema: Schema, start: date, today: date, seed: int) -> None:
        self.cfg = settings.profile
        self.dq = settings.dq
        self.s = schema
        self.reg = Registry()
        self.lc = Lifecycles(schema, settings.lifecycles)
        self.fill = Filler(schema, self.reg, self.lc, settings.column_rules,
                           self.cfg.get_path("fill.optional", 0.8), self.cfg.get_path("fill.ref", 0.55))
        self.seed = seed
        self.rnd = Rand(seed, "world")
        self.start = start
        self.today = today
        self.now = datetime.now(UTC)
        self.people: list[str] = []
        self.roles: dict[str, tuple[str, str]] = {}
        self.cost_centers: dict[str, dict] = {}
        self.gl: dict[str, dict] = {}
        self.channels: dict[str, dict] = {}       # kind -> ad_channel row
        self.formats: dict[str, list[dict]] = {}  # kind -> ad_format rows
        self.specs: dict = {}                     # ad_format_id -> spec row
        self.supply: list[Supply] = []
        self.taxonomy: list[dict] = []
        self.segments: list[dict] = []
        self.personas: list[dict] = []
        self.advertisers: list[Advertiser] = []
        self.campaigns: list[Campaign] = []
        self.seq: dict[str, int] = {}
        self.seq_floor = 0  # stream sessions start numbering high to avoid colliding with backfilled codes

    # ------------------------------------------------------------ helpers
    def ctx(self, anchor: date, **kw) -> Ctx:
        kw.setdefault("people", tuple(self.people) or ("Alex Morgan",))
        return Ctx(anchor=anchor, today=self.today, **kw)

    def adv_ctx(self, adv: Advertiser, anchor: date, **kw) -> Ctx:
        ents = {"advertiser": adv.id}
        if adv.relationship:
            ents["agency_relationship"] = adv.relationship["agency_relationship_id"]
        if adv.msa:
            ents["agreement"] = adv.msa["agreement_id"]
        if adv.sows.get(anchor.year):
            ents["sow"] = adv.sows[anchor.year]["sow_id"]
        if adv.attribution_model:
            ents["attribution_model"] = adv.attribution_model["attribution_model_id"]
        if adv.cost_center:
            ents["cost_center"] = adv.cost_center["cost_center_id"]
        ents.update(kw.pop("entities", {}))
        kw.setdefault("people", tuple(adv.team) or tuple(self.people))
        return self.ctx(anchor, entities=ents, label=adv.label, domain=adv.domain, industry=adv.industry,
                        geo=adv.geo, scale=kw.pop("scale", adv.budget / 12), **kw)

    def make(self, table: str, values: dict, ctx: Ctx, rnd: Rand | None = None) -> dict:
        return self.fill.make(table, values, ctx, rnd or self.rnd)

    def next_seq(self, key: str) -> int:
        self.seq[key] = self.seq.get(key, self.seq_floor) + 1
        return self.seq[key]

    def pick_person(self, dept: str | None = None) -> str:
        if dept:
            cands = [p for p, (_, d) in self.roles.items() if d == dept]
            if cands:
                return self.rnd.choice(cands)
        return self.rnd.choice(self.people)

    def geo(self) -> tuple:
        return self.rnd.weighted(pools.US_GEO, pools.GEO_WEIGHTS)

    def months(self) -> list[date]:
        out, d = [], self.start.replace(day=1)
        while d <= self.today:
            out.append(d)
            d = (d + timedelta(days=32)).replace(day=1)
        return out

    def status(self, table: str, start: date | None, end: date | None) -> str:
        from .lifecycle import phase_of
        return self.lc.status(table, phase_of(start, end, self.today), self.rnd)


def month_end(d: date) -> date:
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def money(v: float) -> float:
    return round(v, 2)
