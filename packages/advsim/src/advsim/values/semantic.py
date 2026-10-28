"""Name-driven realistic values for one column, given the row context.

Each function returns a candidate value (or MISSING when it has no opinion). The generic
filler then enforces the column's type, precision and CHECK constraints, falling back to a
constraint-derived value when the candidate does not fit.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta

from advgen.model import Column

from ..rng import UTC, Rand
from . import pools

MISSING = object()


def words(name: str) -> str:
    return name.replace("_", " ")


def has(name: str, pattern: str) -> bool:
    return re.search(pattern, name) is not None


# ---------------------------------------------------------------- booleans
def bool_prob(name: str) -> float:
    if has(name, r"(^is_active$|_active$|enabled|compliant|verified|eligible|honored|^ssl|billable|"
                  r"delivery_confirmed|digital_advertising|programmatic_eligible|is_taxable)"):
        return 0.85
    if has(name, r"(fraud|invalid|dispute|breach|churn|conflict|reversal|blocked|makegood|make_good|threat|"
                  r"risk|stretch|exclusiv|confidential|house|backup|posting_blocked|alert_sent|scope_change|"
                  r"pricing_model_change|added_value|sequential_liability|cost_pool)"):
        return 0.07
    if has(name, "consent"):
        return 0.75
    if has(name, r"(auto_renewal|renewal_option|negotiat|required|tracking|vpaid|dayparting|optimization)"):
        return 0.5
    if has(name, "primary"):
        return 0.4
    return 0.35


# ---------------------------------------------------------------- integers / numerics
def number(c: Column, ctx, rnd: Rand, maxv: float, scale_digits: int):
    n = c.name
    s = ctx.scale
    is_int = scale_digits == 0
    if has(n, r"(^|_)fiscal_year$|_year$|^year$"):
        return ctx.anchor.year
    if has(n, r"fiscal_period$"):
        return ctx.anchor.month
    if has(n, r"fiscal_quarter$"):
        return (ctx.anchor.month - 1) // 3 + 1
    if has(n, r"latitude"):
        return ctx.geo[2] + rnd.uniform(-0.2, 0.2)
    if has(n, r"longitude"):
        return ctx.geo[3] + rnd.uniform(-0.2, 0.2)
    if has(n, r"(version|revision)(_number)?$|amendment_count"):
        return rnd.skewed([1, 2, 3, 4])
    if has(n, r"(variance|delta|change_amount|adjustment|lift|growth|recommended_\w+_adjustment)") and not is_int:
        if has(n, r"(pct|percent|percentage)$"):
            return rnd.normal(0, 4)
        return rnd.normal(0, s * 0.03)
    if has(n, r"(impression_variance)"):
        return int(rnd.normal(0, 20_000))
    if has(n, r"(pct|percent|percentage)$|_percentage_"):
        return percent(n, rnd)
    # rates, prices and ratios
    if has(n, r"cpm"):
        return rnd.uniform(4, 32)
    if has(n, r"cpc"):
        return rnd.uniform(0.4, 4.5)
    if has(n, r"cpa"):
        return rnd.uniform(18, 140)
    if has(n, r"(ctr$|click_through_rate)"):
        return rnd.uniform(0.0008, 0.012) if maxv < 10 and scale_digits >= 4 else rnd.uniform(0.08, 1.2)
    if has(n, r"roas"):
        return rnd.uniform(2, 8)
    if has(n, r"(fx_rate|exchange_rate)"):
        return pools.FX_TO_USD.get(ctx.currency, 1.0)
    if has(n, r"commission_rate"):
        return rnd.uniform(0.10, 0.17) if maxv < 10 or scale_digits >= 4 else rnd.uniform(10, 17)
    if has(n, r"win_rate"):
        return rnd.uniform(12, 42)
    if has(n, r"(invalid_traffic_rate)"):
        return rnd.uniform(0.4, 3.5)
    if has(n, r"(accuracy|fulfillment|adherence|measurability)_rate"):
        return rnd.uniform(88, 100)
    if has(n, r"viewability_rate|viewab\w*_rate"):
        return rnd.uniform(52, 82)
    if has(n, r"billing_rate"):
        return rnd.uniform(110, 360)
    if has(n, r"(base_rate|unit_rate|rate_amount|net_rate|overage_rate|contracted_rate|^rate$|minimum_rate|maximum_rate|bid_price)"):
        return rnd.uniform(4, 30)
    if has(n, r"weight$") and maxv < 10:
        return rnd.uniform(0.2, 0.4)
    if has(n, r"weight$"):
        return rnd.int(10, 60)
    if has(n, r"(score|rating)"):
        if has(n, "fraud"):
            return abs(rnd.normal(0, 8))
        if has(n, "probability"):
            return rnd.uniform(20, 95)
        return rnd.uniform(0.6 * min(maxv, 10), min(maxv, 10)) if maxv < 100 or has(n, "rating") else rnd.uniform(60, 100)
    if has(n, r"(threshold|tolerance)"):
        return rnd.uniform(2, 15)
    if has(n, r"(grp|trp)"):
        return rnd.uniform(40, 420)
    if has(n, r"frequency$"):
        return rnd.uniform(1.5, 6)
    # counts and volumes
    if has(n, r"impressions?(_count)?$|impression_goal|impression_count|units_delivered|contracted_units|units$"):
        return rnd.lognormal(s / 12 * 1000 / 12, 0.5)
    if has(n, r"click"):
        return rnd.lognormal(max(s / 40, 50), 0.6)
    if has(n, r"conversion"):
        return rnd.lognormal(max(s / 600, 5), 0.7)
    if has(n, r"(views?|reach|visitors|population|_size$|size_estimate|audience_size)"):
        return rnd.lognormal(250_000, 1.0)
    if has(n, r"minimum_conversions"):
        return rnd.choice([300, 500, 1000])
    if has(n, r"(minimum_paths)"):
        return rnd.choice([1000, 2500, 5000])
    if has(n, r"(frequency_cap|cap_limit|frequency_cap_count)"):
        return rnd.int(2, 12)
    if has(n, r"(_count|count_|_total$)"):
        return rnd.skewed(range(0, 30), 1.1)
    if has(n, r"_days$|days_"):
        if has(n, "notice"):
            return rnd.choice([30, 60, 90])
        if has(n, r"(payment|terms)"):
            return rnd.weighted([30, 45, 60, 90], [5, 2, 2, 1])
        if has(n, r"(window|lookback)"):
            return rnd.choice([7, 14, 30, 90])
        return rnd.int(2, 30)
    if has(n, r"_years$"):
        return rnd.int(2, 7)
    if has(n, r"hours"):
        if has(n, "logged"):
            return rnd.weighted([0.5, 1, 1.5, 2, 3, 4, 6, 8], [2, 4, 2, 4, 3, 3, 1, 1])
        return rnd.uniform(4, 160) if not is_int else rnd.int(4, 72)
    if has(n, r"(_ms$|latency)"):
        return rnd.int(40, 900)
    if has(n, r"(seconds|duration)"):
        return rnd.choice([6, 15, 15, 30, 30, 60])
    if has(n, r"(width|height|pixels)"):
        return rnd.choice([250, 300, 360, 480, 640, 720, 1080])
    if has(n, r"(position_x|position_y)"):
        return rnd.int(0, 1200)
    if has(n, r"(priority|rank|level|tier|order)"):
        return rnd.int(1, 5)
    if has(n, r"(number|sequence|seq)$"):
        return rnd.int(1, 20)
    # money
    if has(n, r"(amount|cost|price|spend|budget|fee|value|revenue|billings|payable|paid|outstanding|"
              r"cap|bonus|penalty|total|subtotal|tax|discount|commitment|allocated|committed)"):
        return money(n, ctx, rnd)
    if is_int:
        return rnd.int(1, 100)
    return rnd.uniform(0, min(maxv, 100))


def percent(n: str, rnd: Rand) -> float:
    for pat, lo, hi in ((r"commission", 10, 17), (r"discount", 0, 15), (r"markup", 5, 20),
                        (r"viewab|in_view", 48, 82), (r"completion", 55, 92), (r"fte_allocation", 25, 100),
                        (r"overhead", 5, 25), (r"(tolerance|threshold|alert)", 5, 15), (r"sov", 5, 30),
                        (r"coverage", 60, 100), (r"ownership", 51, 100), (r"pacing", 80, 100),
                        (r"(fraud|ivt)", 0, 4)):
        if has(n, pat):
            return rnd.uniform(lo, hi)
    return rnd.uniform(5, 95)


def money(n: str, ctx, rnd: Rand) -> float:
    s = ctx.scale
    for pat, factor in ((r"tax", 0.07), (r"discount", 0.03), (r"withholding", 0.01), (r"penalty", 0.02),
                        (r"(fee|bonus)", 0.12), (r"liability_cap", 2.0), (r"daily", 1 / 30), (r"weekly", 1 / 4.3),
                        (r"conversion_value", None), (r"(annual|estimated_annual|total_contract|total_committed)", 4.0)):
        if has(n, pat):
            if factor is None:
                return rnd.lognormal(65, 0.8)
            return rnd.lognormal(s * factor, 0.35)
    return rnd.lognormal(s, 0.35)


# ---------------------------------------------------------------- dates
PAST_ONLY = re.compile(r"(approv|signed|accept|submi|request|receiv|issue|posting|entry|sent|paid|payment_date|"
                       r"resolution|resolved|reconciliation_date|clearing|value_date|actual|completion|completed|"
                       r"last_|fire_|qa_|live|acknowledg|closed|execution|decision|verification|dispute|churn|"
                       r"termination|discontinu|notice_date|measurement|pitch_win|ingestion)")


def date_value(n: str, ctx, rnd: Rand) -> date:
    a = ctx.anchor
    dur = ctx.duration
    if has(n, r"(end|expir|valid_to|finish|through|until)"):
        return a + timedelta(days=dur)
    if has(n, r"(start|effective|begin|launch|onboarding|go_live|valid_from|air_start|incorporat)"):
        return a
    if has(n, r"(approv|signed|accept|submi|request|issue|kickoff|award|pitch_win|brief|negotiation)"):
        return a - timedelta(days=rnd.int(1, 21))
    if has(n, r"(due|deadline)"):
        return a + timedelta(days=rnd.int(14, 45))
    if has(n, r"(next_|renewal|review)"):
        return a + timedelta(days=rnd.int(60, 365))
    if has(n, r"(last_|reviewed)"):
        return a + timedelta(days=rnd.int(0, 90))
    if has(n, r"(payment|paid|resolution|resolved|reconcil|clearing|value_date|posting|gl_)"):
        return a + timedelta(days=rnd.int(20, 65))
    if has(n, r"(churn|discontinu|termination|closed|cancel|dispute|rejection)"):
        return a + timedelta(days=rnd.int(30, 200))
    return a + timedelta(days=rnd.int(-10, 20))


def as_ts(d: date, rnd: Rand) -> datetime:
    return rnd.ts_on(d)


# ---------------------------------------------------------------- text
def text(c: Column, table: str, ctx, rnd: Rand):
    n = c.name
    f = rnd.fake
    if has(n, r"email"):
        person = ctx.person(rnd)
        domain = ctx.domain or "example.com"
        return f"{person.split()[0].lower()}.{person.split()[-1].lower()}@{domain}"
    if has(n, r"phone"):
        return "+1" + f.numerify("##########").lstrip("0").rjust(10, "2")
    if has(n, r"(ip_address_hash|hashed|_hash$|fingerprint|user_identifier|deduplication_key|audience_identifier|device_id)"):
        return hashlib.sha256(str(rnd.r.getrandbits(64)).encode()).hexdigest()[:32]
    if has(n, r"ip_address"):
        return f.ipv4_public()
    if has(n, r"user_agent"):
        return rnd.choice(pools.USER_AGENTS)
    if has(n, r"(^|_)browser"):
        return rnd.weighted(pools.BROWSERS)
    if has(n, r"(operating_system|os_type)"):
        return rnd.weighted(pools.OPERATING_SYSTEMS)
    if has(n, r"(_url|_uri|website|link)$|^url$|_url_"):
        base = ctx.domain or f.domain_name()
        return f"https://www.{base}/{rnd.choice(['', 'campaign/', 'lp/', 'promo/', 'docs/'])}{f.slug()}"
    if has(n, r"(site_domain|domain$)"):
        return ctx.domain or f.domain_name()
    if has(n, r"(time_zone|timezone)"):
        return ctx.geo[5]
    if has(n, r"(geo_city|_city$|^city$)"):
        return ctx.geo[0]
    if has(n, r"(geo_region|_region$|state)") and not has(n, "status"):
        return ctx.geo[1]
    if has(n, r"postal|zip"):
        return ctx.geo[4] + f.numerify("##")
    if has(n, r"(language|locale)"):
        return rnd.weighted(["en-US", "en-GB", "es-US", "fr-CA"], [0.85, 0.05, 0.07, 0.03]) if "-" in (c.checks[0].pattern if c.checks else "-") else "en"
    if has(n, r"(country)"):
        return "US"
    if has(n, r"(industry|sector)"):
        return ctx.industry or rnd.choice(pools.INDUSTRIES)
    if has(n, r"(content_category|iab_category|brand_safety_category|conflict_category|product_category|sub_category)"):
        return rnd.choice(pools.CONTENT_CATEGORIES)
    if has(n, r"(ad_size|ad_unit_size)"):
        return rnd.choice(pools.AD_SIZES)
    if has(n, r"(geo_targeting|geographic_scope|geography_scope|operating_markets|geo$)"):
        return rnd.choice(pools.GEO_TARGETS)
    if has(n, r"(device_targeting)"):
        return rnd.choice(pools.DEVICE_TARGETS)
    if has(n, r"(daypart)"):
        return rnd.choice(pools.DAYPARTS)
    if has(n, r"(^|_)(owner|contact|director|manager|presenter|evaluator|signatory_name|approved_by|requested_by|"
              r"payee_name|payer_name|approval_authority|escalation_contact|assignee|reviewer|lead|_by$|"
              r"account_director|name_of_)") and not has(n, r"(email|phone|_id$|title)"):
        if has(n, r"(payee|payer)"):
            return ctx.label or f.company()
        return ctx.person(rnd)
    if has(n, r"signatory_title|role_title|job_title|^role$"):
        return rnd.choice(pools.JOB_TITLES)
    if has(n, r"(department|team$|practice_group|responsible_team|owning_)"):
        return rnd.choice(pools.DEPARTMENTS)
    if has(n, r"(notes|comment|message|feedback)"):
        return rnd.choice(pools.NOTES)
    if has(n, r"(reason|cause|trigger)"):
        return rnd.choice(pools.REASONS)
    if has(n, r"(description|summary|_text$|criteria|scope|terms$|requirements|clause|methodology|provision|"
              r"policy|specifications|context|exclusions|inclusions|message|instructions|definition|rule$)"):
        return rnd.choice(pools.DESCRIPTIONS)
    if has(n, r"(version$|_version)"):
        return f"{rnd.int(1, 4)}.{rnd.int(0, 9)}"
    if has(n, r"(legal_entity_name|holding_company|trading_name|incumbent_agency|managing_agency)"):
        return ctx.label or f.company()
    if has(n, r"(_name|title|tagline|label)$"):
        return f"{ctx.label + ' ' if ctx.label else ''}{entity_word(table)} {rnd.choice(pools.PRODUCT_WORDS)}".strip()
    if has(n, r"(code|number|reference|_ref$|_key$|identifier|document)"):
        prefix = "".join(w[0] for w in n.split("_") if w)[:3].upper()
        return f"{prefix}-{rnd.int(100000, 999999)}"
    if has(n, r"(segments?|segment_ids|audience)"):
        return ", ".join(rnd.sample(["Auto Intenders", "Sports Fans", "Young Parents", "Foodies",
                                     "Business Travelers", "Gamers", "Home Improvers"], 2))
    if has(n, r"(algorithm|vast_version|vpaid_version)"):
        return rnd.choice(["4.2", "4.1", "3.0", "2.0"])
    if has(n, r"(source|system|platform|server)"):
        return rnd.choice(["CM360", "The Trade Desk", "Prisma", "Salesforce", "SAP S/4HANA", "Manual"])
    return f"{words(n).capitalize()} {rnd.choice(pools.PRODUCT_WORDS)}"


def entity_word(table: str) -> str:
    return words(table).title()


def now_utc() -> datetime:
    return datetime.now(UTC)
