"""Ad delivery (adserver_db): a daily delivery plan per line item, then sampled event rows.

`plan` computes real (unsampled) daily volumes for every line item from its budget, CPM and
pacing, and rolls them up into the media_ops/erp/work_mgmt aggregates. `events_for_day` turns
one day of the plan into event rows; each stored impression stands for `sample_rate` real ones,
while delivery_pacing and viewability_measurement carry the real totals.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from .. import dq
from ..rng import UTC, Rand
from ..values import pools
from ..world import LineItem, World

# share of daily traffic per hour, US Eastern local time (shifted to UTC below)
DIURNAL_ET = [0.8, 0.5, 0.35, 0.3, 0.35, 0.6, 1.2, 2.2, 3.4, 4.4, 4.9, 5.1, 5.3, 5.2, 5.0, 5.0, 5.2, 5.6,
              6.1, 6.6, 6.9, 6.5, 4.8, 2.6]
UTC_OFFSET = 4
DEVICES = {  # kind -> {device_type: weight}
    "display": {"desktop": 0.38, "mobile": 0.52, "tablet": 0.1},
    "native": {"desktop": 0.3, "mobile": 0.62, "tablet": 0.08},
    "video": {"desktop": 0.35, "mobile": 0.5, "tablet": 0.08, "ctv": 0.07},
    "ctv": {"ctv": 0.85, "smart_tv": 0.15},
    "audio": {"mobile": 0.82, "desktop": 0.18},
    "social": {"mobile": 0.9, "desktop": 0.1},
    "dooh": {"other": 1.0},
}
IMPRESSION_TYPE = {"display": "display", "native": "native", "video": "video", "ctv": "video", "audio": "audio",
                   "social": "video", "dooh": "display"}
VIDEO_KINDS = ("video", "ctv", "social")
QUARTILES = [("start", 0), ("first_quartile", 25), ("midpoint", 50), ("third_quartile", 75), ("complete", 100)]


@dataclass
class Day:
    spend: float
    impressions: int
    clicks: int
    conversions: int
    viewable: int
    measurable: int
    video_complete: int


def hour_weights() -> list[float]:
    w = [0.0] * 24
    for h, v in enumerate(DIURNAL_ET):
        w[(h + UTC_OFFSET) % 24] = v
    return w


HOURS = hour_weights()


# ---------------------------------------------------------------- plan
def plan(w: World, end: datetime) -> None:
    rnd = w.rnd.child("delivery-plan")
    cfg = w.cfg
    sigma = float(cfg.get_path("delivery.pacing_noise", 0.18))
    weekday = cfg.get_path("delivery.weekday_factor", [1] * 7)
    q4 = float(cfg.get_path("delivery.q4_uplift", 1.25))
    cvr = float(cfg.get_path("delivery.cvr", 0.025))
    vtr = float(cfg.get_path("delivery.view_through_rate", 0.00004))
    vcr = float(cfg.get_path("delivery.video_completion", 0.72))
    for camp in w.campaigns:
        if camp.status in ("cancelled", "draft"):
            continue
        for li in camp.line_items:
            plan_line_item(w, li, end, rnd, sigma, weekday, q4, cvr, vtr, vcr)
    rollup(w)


def plan_line_item(w: World, li: LineItem, end: datetime, rnd: Rand, sigma, weekday, q4, cvr, vtr, vcr) -> None:
    days = (li.end - li.start).days + 1
    base = li.budget / days
    status = li.row["delivery_status"]
    bias = {"under_delivering": 0.72, "over_delivering": 1.08, "paused": 0.0}.get(status, 1.0)
    ctr = float(w.cfg.get_path(f"delivery.ctr.{li.kind}", 0.001)) * rnd.lognormal(1.0, 0.25)
    view = float(w.cfg.get_path(f"delivery.viewability.{li.kind}", 0.6))
    spent = 0.0
    d = li.start
    while d <= min(li.end, end.date()):
        frac = 1.0
        if d == end.date():
            frac = sum(HOURS[: end.hour]) / sum(HOURS)
        f = weekday[d.weekday()] * (q4 if d.month >= 10 else 1.0) * rnd.lognormal(1.0, sigma) * bias
        if status == "paused" and d < end.date() - timedelta(days=3):
            f = weekday[d.weekday()] * rnd.lognormal(1.0, sigma)
        spend = min(base * f * frac, max(0.0, li.budget * 1.02 - spent))
        spent += spend
        imps = int(spend / li.cpm * 1000)
        clicks = binomial(rnd, imps, ctr)
        conv = binomial(rnd, clicks, cvr) + binomial(rnd, imps, vtr)
        measurable = int(imps * rnd.uniform(0.9, 0.98)) if view > 0 else 0
        li.daily[d] = Day(round(spend, 4), imps, clicks, conv, int(measurable * view * rnd.lognormal(1.0, 0.05)),
                          measurable, int(imps * vcr * rnd.lognormal(1.0, 0.05)) if li.kind in VIDEO_KINDS else 0)
        d += timedelta(days=1)


def binomial(rnd: Rand, n: int, p: float) -> int:
    if n <= 0 or p <= 0:
        return 0
    return int(rnd.np.binomial(n, min(p, 1.0)))


def rollup(w: World) -> None:
    """Write delivered totals into the planning/finance rows that track actuals."""
    for camp in w.campaigns:
        camp_spend = 0.0
        for li in camp.line_items:
            spend = sum(d.spend for d in li.daily.values())
            imps = sum(d.impressions for d in li.daily.values())
            clicks = sum(d.clicks for d in li.daily.values())
            conv = sum(d.conversions for d in li.daily.values())
            camp_spend += spend
            li.io_line["actual_spend"] = round(spend, 2)
            li.io_line["actual_units_delivered"] = imps
            li.budget_line["actual_spend"] = round(spend, 2)
            li.budget_line["variance_amount"] = round(li.budget - spend, 2) if li.end < w.today else None
            for row in w.reg.rows["budget_allocation"]:
                if row["pacing_rule_id"] == li.pacing_rule["pacing_rule_id"]:
                    row["actual_spend"] = round(spend, 2)
                    row["remaining_budget"] = round(max(0.0, li.budget - spend), 2)
            n = max(1, len(li.ads))
            for ad in li.ads:
                ca = w.reg.get(ad["creative_assignment_id"])
                ca["impression_count"] = imps // n
                ca["click_count"] = clicks // n
                ca["conversion_count"] = conv // n
                ca["view_count"] = sum(d.video_complete for d in li.daily.values()) // n
                ca["ctr"] = round(clicks / imps, 6) if imps else 0.0
            if li.end < w.today and li.daily:
                ratio = spend / li.budget if li.budget else 0
                li.buy["delivery_status"] = "underdelivered" if ratio < 0.95 else "overdelivered" if ratio > 1.01 else "fully_delivered"
        fb = camp.finance_budget
        if fb:
            fb["spent_amount"] = round(camp_spend, 2)
            fb["remaining_amount"] = round(max(0.0, camp.budget - camp_spend), 2)


# ---------------------------------------------------------------- events
class EventWriter:
    """Builds event rows for one day; returns {table: [row dict]}."""

    def __init__(self, w: World, rnd: Rand) -> None:
        self.w = w
        self.rnd = rnd
        self.sample = max(1, int(w.cfg.get_path("delivery.sample_rate", 2000)))
        self.cap = int(w.cfg.get_path("delivery.max_events_per_day", 400000))
        self.dq = dq.Noise(w.dq, rnd)

    def day(self, d: date, line_items: list[LineItem], until: datetime | None = None) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {t: [] for t in ("impression_event", "click_event", "conversion_event",
                                                      "video_completion_event", "viewability_measurement", "delivery_pacing")}
        budget = self.cap
        for li in line_items:
            day = li.daily.get(d)
            if not day or day.impressions == 0:
                continue
            self.line_item_day(li, d, day, out, until)
            if sum(len(v) for v in out.values()) > budget:
                break
        self.dq.apply(out)
        return out

    def line_item_day(self, li: LineItem, d: date, day: Day, out: dict, until: datetime | None) -> None:
        rnd = self.rnd
        n_imp = rnd.poisson(day.impressions / self.sample)
        n_clk = min(n_imp, rnd.poisson(day.clicks / self.sample))
        n_conv = rnd.poisson(day.conversions / self.sample)
        camp = li.campaign
        adv = camp.adv
        static = self.static(li)
        start = datetime.combine(d, time(0), UTC)
        hours = rnd.np.choice(24, size=n_imp, p=[h / sum(HOURS) for h in HOURS]) if n_imp else []
        imps = []
        for h in hours:
            ts = start + timedelta(hours=int(h), seconds=rnd.int(0, 3599), microseconds=rnd.int(0, 999999))
            if until and ts >= until:
                continue
            imps.append(self.impression(li, ts, static))
        out["impression_event"].extend(imps)
        if not imps:
            return
        clicked = rnd.sample(imps, min(n_clk, len(imps)))
        clicks = [self.click(li, imp, static) for imp in clicked]
        out["click_event"].extend(clicks)
        for _ in range(n_conv):
            src = rnd.choice(clicks) if clicks and rnd.chance(0.8) else rnd.choice(imps)
            conv = self.conversion(li, src, static, "click_through" if src in clicks else "view_through")
            if conv["conversion_timestamp"] < (until or self.w.now):
                out["conversion_event"].append(conv)
        if li.kind in VIDEO_KINDS:
            out["video_completion_event"].extend(self.video(li, imp, static) for imp in imps)
        end_ts = min(start + timedelta(days=1) - timedelta(seconds=1), until or self.w.now)
        out["viewability_measurement"].append(self.viewability(li, d, day, end_ts, static))
        out["delivery_pacing"].append(self.pacing(li, d, day, end_ts))

    # ------------------------------------------------------------ static per line item
    def static(self, li: LineItem) -> dict:
        key = "_static"
        if key in li.row:
            return li.row[key]
        camp = li.campaign
        prop = self.w.reg.get(li.placement["media_catalog_placement_id"])
        pp = self.w.reg.get(prop["publisher_property_id"]) if prop else None
        s = {
            "campaign_id": camp.id, "flight_id": li.flight["flight_id"], "line_item_id": li.id,
            "advertiser_id": camp.adv.id, "brand_id": camp.brand["brand_id"],
            "contract_insertion_order_id": camp.client_io["contract_insertion_order_id"],
            "media_placement_id": li.placement["media_placement_id"], "publisher_id": li.supply.publisher["publisher_id"],
            "programmatic_deal_id": li.deal["programmatic_deal_id"] if li.deal else None,
            "segment_id": li.segment["segment_id"] if li.segment else None,
            "activation_id": li.activation["activation_id"] if li.activation else None,
            "trafficking_order_id": li.trafficking_order["trafficking_order_id"],
            "trafficking_instruction_id": li.instruction["trafficking_instruction_id"],
            "suppression_list_id": camp.adv.suppression["suppression_list_id"] if camp.adv.suppression else None,
            "site_domain": pp.get("_domain") if pp else f"{li.supply.supplier['trading_name'].lower().replace(' ', '')}.com",
            "ad_size": li.ads[0]["format"] if li.ads else None,
            "ad_server_source": "the_trade_desk" if li.deal else "google_campaign_manager_360",
            "devices": DEVICES[li.kind], "pixel": camp.adv.pixels[0]["tracking_pixel_id"] if camp.adv.pixels else None,
            "attribution_model_id": camp.adv.attribution_model["attribution_model_id"] if camp.adv.attribution_model else None,
            "content_category": self.rnd.choice(pools.CONTENT_CATEGORIES),
        }
        li.row[key] = s
        return s

    def ad(self, li: LineItem) -> tuple:
        if not li.ads:
            return None, None
        ad = self.rnd.choice(li.ads)
        return ad["ad_id"], ad["asset_id"]

    def geo(self) -> tuple:
        return self.rnd.weighted(pools.US_GEO, pools.GEO_WEIGHTS)

    def impression(self, li: LineItem, ts: datetime, s: dict) -> dict:
        rnd = self.rnd
        device = rnd.weighted(s["devices"])
        geo = self.geo()
        ad_id, asset_id = self.ad(li)
        viewable = li.kind not in ("audio", "dooh") and rnd.chance(float(self.w.cfg.get_path(f"delivery.viewability.{li.kind}", 0.6)))
        ingest = ts + timedelta(seconds=rnd.int(1, 90))
        user = hashlib.md5(f"u{rnd.int(1, 5_000_000)}".encode()).hexdigest()
        row = {
            "impression_event_id": rnd.uuid7(ts), "activation_id": s["activation_id"], "ad_id": ad_id,
            "advertiser_id": s["advertiser_id"], "asset_id": asset_id, "brand_id": s["brand_id"],
            "campaign_id": s["campaign_id"], "contract_insertion_order_id": s["contract_insertion_order_id"],
            "flight_id": s["flight_id"], "line_item_id": s["line_item_id"], "lookalike_model_id": None,
            "media_placement_id": s["media_placement_id"], "programmatic_deal_id": s["programmatic_deal_id"],
            "publisher_id": s["publisher_id"], "segment_id": s["segment_id"], "suppression_list_id": s["suppression_list_id"],
            "trafficking_instruction_id": s["trafficking_instruction_id"], "trafficking_order_id": s["trafficking_order_id"],
            "ad_position": rnd.weighted(["above_the_fold", "below_the_fold", "in_content", "sidebar"], [5, 2, 3, 1]) if li.kind in ("display", "native") else None,
            "ad_server_source": s["ad_server_source"], "ad_size": s["ad_size"],
            "audience_segment_ids": str(s["segment_id"]) if s["segment_id"] else None,
            "bid_price_cpm": round(li.cpm * rnd.uniform(0.85, 1.1), 4) if li.deal else None,
            "brand_safety_score": round(rnd.uniform(78, 100), 2), "browser": rnd.weighted(pools.BROWSERS) if device != "ctv" else None,
            "channel": {"desktop": "desktop_web", "mobile": "mobile_app" if rnd.chance(0.55) else "mobile_web", "tablet": "mobile_app",
                        "ctv": "ctv", "smart_tv": "ott", "other": "dooh"}[device],
            "consent_status": rnd.weighted({"granted": 0.78, "not_required": 0.12, "denied": 0.04, "unknown": 0.06}),
            "content_category": s["content_category"], "currency_code": "USD", "device_type": device,
            "event_source_system": "CM360" if s["ad_server_source"] == "google_campaign_manager_360" else "TTD",
            "fraud_score": round(abs(rnd.normal(0, 6)), 2), "frequency_cap_count": rnd.int(1, 6),
            "geo_city": geo[0], "geo_country_code": "USA", "geo_postal_code": geo[4] + rnd.fake.numerify("##"),
            "geo_region": geo[1], "impression_timestamp": ts, "impression_type": IMPRESSION_TYPE[li.kind],
            "ingestion_timestamp": ingest, "ip_address": rnd.fake.ipv4_public(),
            "latitude": round(geo[2] + rnd.uniform(-0.15, 0.15), 7), "longitude": round(geo[3] + rnd.uniform(-0.15, 0.15), 7),
            "media_cost": round(li.cpm / 1000, 4), "operating_system": rnd.weighted(pools.OPERATING_SYSTEMS),
            "page_url": f"https://www.{s['site_domain']}/{rnd.fake.slug()}" if li.kind in ("display", "native", "video") else None,
            "session_code": user[:12] + f"{ts:%H%M}", "site_domain": s["site_domain"], "supply_chain_object": None,
            "tcf_consent_string": None, "time_in_view_seconds": round(rnd.uniform(1, 30), 2) if viewable else 0,
            "user_agent": rnd.choice(pools.USER_AGENTS), "user_identifier": user,
            "video_duration_seconds": 15 if li.kind in VIDEO_KINDS else None,
            "video_player_size": rnd.weighted(["large", "medium", "fullscreen", "small"], [4, 3, 2, 1]) if li.kind in VIDEO_KINDS else None,
            "viewability_percentage": round(rnd.uniform(50, 100), 2) if viewable else round(rnd.uniform(0, 49), 2),
            "viewability_status": ("viewable" if viewable else "non_viewable") if li.kind not in ("audio", "dooh") else "not_measured",
        }
        self.audit(row, ingest, "cm360_ingest")
        row["_device"] = device
        return row

    def click(self, li: LineItem, imp: dict, s: dict) -> dict:
        rnd = self.rnd
        ts = imp["impression_timestamp"] + timedelta(seconds=rnd.int(2, 120))
        invalid = rnd.chance(0.03)
        row = {
            "click_event_id": rnd.uuid7(ts), "ad_id": imp["ad_id"], "asset_id": imp["asset_id"], "campaign_id": s["campaign_id"],
            "contract_insertion_order_id": s["contract_insertion_order_id"], "flight_id": s["flight_id"],
            "impression_event_id": imp["impression_event_id"], "line_item_id": s["line_item_id"],
            "media_placement_id": s["media_placement_id"], "publisher_id": s["publisher_id"], "segment_id": s["segment_id"],
            "tracking_pixel_id": None, "ad_server_name": "Campaign Manager 360", "attribution_window_hours": 720,
            "billing_status": "non_billable" if invalid else "billable", "click_fraud_score": round(rnd.uniform(60, 95) if invalid else abs(rnd.normal(0, 8)), 2),
            "click_interaction_type": rnd.weighted(["standard_click", "tap", "call_to_action", "video_overlay"], [5, 4, 1, 1]),
            "click_latency_ms": rnd.int(40, 700), "click_position_x": rnd.int(0, 300), "click_position_y": rnd.int(0, 250),
            "click_redirect_url": f"https://ad.doubleclick.example/clk;{rnd.int(10**8, 10**9)}",
            "click_source_platform": {"desktop_web": "web", "mobile_web": "mobile_web", "mobile_app": "mobile_app", "ctv": "ctv",
                                      "ott": "ctv", "dooh": "dooh"}[imp["channel"]],
            "click_timestamp": ts, "click_validation_status": rnd.choice(["invalid_bot", "invalid_datacenter", "suspicious"]) if invalid else "valid",
            "cpc_rate": None, "currency_code": "USD", "data_source_system": "CM360", "device_fingerprint": imp["user_identifier"][:16],
            "device_type": imp["device_type"], "geographic_city": imp["geo_city"], "geographic_country_code": "USA",
            "geographic_region": imp["geo_region"], "ip_address": imp["ip_address"],
            "ivt_detection_method": "general_ivt" if invalid else None, "referrer_url": imp["page_url"], "user_agent": imp["user_agent"],
        }
        self.audit(row, ts + timedelta(seconds=rnd.int(1, 60)), "cm360_ingest")
        return row

    def conversion(self, li: LineItem, src: dict, s: dict, kind: str) -> dict:
        rnd = self.rnd
        base = src.get("click_timestamp") or src["impression_timestamp"]
        ts = base + timedelta(minutes=int(rnd.lognormal(240, 1.4)))
        adv = li.campaign.adv
        value = round(rnd.lognormal(75, 0.7), 2)
        ctype = rnd.weighted(["purchase", "lead", "sign_up", "form_fill", "app_install"], [5, 2, 2, 1, 1])
        row = {
            "conversion_event_id": rnd.uuid7(ts), "advertiser_id": s["advertiser_id"], "asset_id": src.get("asset_id"),
            "attribution_model_id": s["attribution_model_id"], "brand_id": s["brand_id"], "campaign_id": s["campaign_id"],
            "click_event_id": src.get("click_event_id"), "contract_insertion_order_id": s["contract_insertion_order_id"],
            "flight_id": s["flight_id"], "impression_event_id": src.get("impression_event_id"), "line_item_id": s["line_item_id"],
            "lookalike_model_id": None, "media_placement_id": s["media_placement_id"], "programmatic_deal_id": s["programmatic_deal_id"],
            "segment_id": s["segment_id"], "tracking_pixel_id": s["pixel"], "attribution_type": kind,
            "attribution_window_days": 30 if kind == "click_through" else 1, "browser": rnd.weighted(pools.BROWSERS),
            "conversion_currency": "USD", "conversion_name": ctype.replace("_", " ").title(),
            "conversion_page_url": f"https://www.{adv.domain}/{'checkout/confirmation' if ctype == 'purchase' else 'thank-you'}",
            "conversion_quantity": rnd.skewed([1, 2, 3, 4]) if ctype == "purchase" else 1,
            "conversion_status": rnd.weighted({"confirmed": 0.9, "pending": 0.06, "rejected": 0.03, "fraud": 0.01}),
            "conversion_timestamp": ts, "conversion_type": ctype, "conversion_value": value if ctype == "purchase" else None,
            "data_source": "floodlight", "deduplication_key": hashlib.md5(f"{src.get('user_identifier')}{ts}".encode()).hexdigest()[:20],
            "device_type": {"smart_tv": "ctv", "other": "other"}.get(src.get("device_type"), src.get("device_type")) if src.get("device_type") in ("desktop", "mobile", "tablet", "ctv", "smart_tv", "other") else "other",
            "fraud_score": round(abs(rnd.normal(0, 5)), 2), "geo_city": src.get("geo_city") or src.get("geographic_city"),
            "geo_country": "USA", "geo_region": src.get("geo_region") or src.get("geographic_region"),
            "ip_address": src.get("ip_address"), "landing_page_url": f"https://www.{adv.domain}/",
            "operating_system": rnd.weighted(pools.OPERATING_SYSTEMS), "order_reference": f"ORD-{rnd.int(10**7, 10**8 - 1)}" if ctype == "purchase" else None,
            "product_category": adv.industry, "referrer_url": None, "user_identifier": src.get("user_identifier") or src.get("device_fingerprint"),
        }
        self.audit(row, ts + timedelta(minutes=rnd.int(1, 30)), "floodlight_ingest")
        return row

    def video(self, li: LineItem, imp: dict, s: dict) -> dict:
        rnd = self.rnd
        vcr = float(self.w.cfg.get_path("delivery.video_completion", 0.72))
        q = 4 if rnd.chance(vcr) else rnd.weighted([0, 1, 2, 3], [1, 2, 2, 2])
        quartile, pct = QUARTILES[q]
        dur = imp["video_duration_seconds"] or 15
        ts = imp["impression_timestamp"] + timedelta(seconds=dur * pct / 100)
        size = imp["video_player_size"] or "large"
        w_, h_ = {"small": (400, 225), "medium": (640, 360), "large": (1280, 720), "fullscreen": (1920, 1080)}[size]
        dev = imp["_device"]
        row = {
            "video_completion_event_id": rnd.uuid7(ts), "ad_id": imp["ad_id"], "asset_id": imp["asset_id"],
            "buy_id": li.buy["buy_id"], "campaign_id": s["campaign_id"], "flight_id": s["flight_id"],
            "impression_event_id": imp["impression_event_id"], "line_item_id": s["line_item_id"],
            "media_placement_id": s["media_placement_id"], "programmatic_deal_id": s["programmatic_deal_id"],
            "publisher_id": s["publisher_id"], "spec_id": None, "ad_server": "CM360", "browser": imp["browser"],
            "completion_percentage": pct, "completion_quartile": quartile,
            "connection_type": "wifi" if dev in ("ctv", "smart_tv", "desktop") else rnd.weighted(["wifi", "cellular"], [6, 4]),
            "content_category": imp["content_category"],
            "device_type": {"smart_tv": "ctv"}.get(dev, dev) if dev in ("desktop", "mobile", "tablet", "ctv", "smart_tv") else "other",
            "event_timestamp": ts, "geo_city": imp["geo_city"], "geo_country_code": "USA", "geo_region": imp["geo_region"],
            "ip_address_hashed": hashlib.sha256(imp["ip_address"].encode()).hexdigest()[:32], "operating_system": imp["operating_system"],
            "player_height_pixels": h_, "player_size": size, "player_width_pixels": w_, "session_code": imp["session_code"],
            "site_domain": imp["site_domain"], "skip_offset_seconds": 5 if li.kind == "video" else None,
            "time_to_completion_seconds": dur if q == 4 else None, "user_id_hashed": imp["user_identifier"], "vast_version": "4.2",
            "video_duration_seconds": dur, "video_format": "linear", "video_position": rnd.weighted(["pre_roll", "mid_roll", "post_roll"], [6, 3, 1]),
            "viewable_percentage": imp["viewability_percentage"], "vpaid_version": None,
        }
        self.audit(row, ts + timedelta(seconds=rnd.int(1, 90)), "cm360_ingest")
        return row

    def viewability(self, li: LineItem, d: date, day: Day, ts: datetime, s: dict) -> dict:
        rnd = self.rnd
        rate = day.viewable / day.measurable * 100 if day.measurable else 0
        env = {"ctv": "CTV", "dooh": "DOOH"}.get(li.kind, "web" if rnd.chance(0.6) else "in_app")
        row = {
            "viewability_measurement_id": rnd.uuid7(ts), "asset_id": li.assets[0]["asset_id"] if li.assets else None,
            "buy_id": li.buy["buy_id"], "campaign_id": s["campaign_id"], "flight_id": s["flight_id"], "impression_event_id": None,
            "line_item_id": s["line_item_id"], "media_placement_id": s["media_placement_id"],
            "programmatic_deal_id": s["programmatic_deal_id"], "publisher_id": s["publisher_id"], "sla_id": None, "spec_id": None,
            "supplier_id": li.supply.supplier["supplier_id"],
            "ad_format": {"native": "native", "video": "video", "ctv": "video", "social": "video"}.get(li.kind, "display"),
            "data_quality_score": round(rnd.uniform(85, 99), 2),
            "device_type": {"ctv": "CTV", "dooh": "DOOH", "audio": "mobile", "social": "mobile"}.get(li.kind, rnd.weighted(["desktop", "mobile", "tablet"], [4, 5, 1])),
            "environment": env, "guaranteed_viewability_threshold": 70.0, "in_view_percentage": round(min(100, rate), 2),
            "measurability_rate": round(day.measurable / day.impressions * 100, 2) if day.impressions else 0,
            "measurable_impression_count": day.measurable, "measurement_date": d,
            "measurement_method": "geometric", "measurement_status": "measured" if day.measurable else "unmeasurable",
            "measurement_timestamp": ts, "player_size_height": None, "player_size_width": None,
            "source_system": "Integral Ad Science" if rnd.chance(0.5) else "DoubleVerify",
            "time_in_view_seconds": round(rnd.uniform(4, 14), 2), "total_impression_count": day.impressions,
            "unmeasurable_reason": None if day.measurable else "Audio or out-of-home inventory",
            "video_quartile_reached": "100%" if li.kind in VIDEO_KINDS else "not_applicable", "viewability_rate": round(min(100, rate), 2),
            "viewability_standard": "MRC_video" if li.kind in VIDEO_KINDS else "MRC_display", "viewable_impression_count": day.viewable,
        }
        self.audit(row, ts + timedelta(hours=rnd.int(2, 8)), "verification_import")
        return row

    def pacing(self, li: LineItem, d: date, day: Day, ts: datetime) -> dict:
        rnd = self.rnd
        to_date = [x for k, x in li.daily.items() if k <= d]
        spend = sum(x.spend for x in to_date)
        imps = sum(x.impressions for x in to_date)
        clicks = sum(x.clicks for x in to_date)
        conv = sum(x.conversions for x in to_date)
        elapsed = ((d - li.start).days + 1) / ((li.end - li.start).days + 1)
        planned_spend = li.budget * elapsed
        planned_imps = int(planned_spend / li.cpm * 1000)
        ratio = spend / planned_spend if planned_spend else 1
        status = "completed" if d >= li.end else "under_delivering" if ratio < 0.9 else "over_delivering" if ratio > 1.1 else "on_pace"
        start = datetime.combine(d, time(0), UTC)
        row = {
            "delivery_pacing_id": rnd.uuid7(ts), "activation_id": li.activation["activation_id"] if li.activation else None,
            "buy_id": li.buy["buy_id"], "campaign_id": li.campaign.id, "deliverable_tracker_id": None, "flight_id": li.flight["flight_id"],
            "io_line_id": li.io_line["io_line_id"], "line_item_id": li.id, "media_insertion_order_id": li.io["media_insertion_order_id"],
            "media_placement_id": li.placement["media_placement_id"], "pacing_rule_id": li.pacing_rule["pacing_rule_id"],
            "plan_line_id": li.plan_line["plan_line_id"], "programmatic_deal_id": li.deal["programmatic_deal_id"] if li.deal else None,
            "segment_id": li.segment["segment_id"] if li.segment else None, "sla_id": None,
            "trafficking_order_id": li.trafficking_order["trafficking_order_id"],
            "actual_impressions": imps, "actual_spend_amount": round(spend, 4),
            "alert_severity": {"on_pace": "none", "completed": "none"}.get(status, "medium" if abs(1 - ratio) < 0.25 else "high"),
            "bid_win_rate": round(rnd.uniform(12, 38), 2) if li.deal else None,
            "click_through_rate": round(clicks / imps, 4) if imps else 0, "conversion_count": conv, "currency_code": "USD",
            "data_source_system": "the_trade_desk" if li.deal else "google_campaign_manager_360", "delivery_method": "even",
            "effective_cpa": round(min(spend / conv, 999999), 4) if conv else None,
            "effective_cpm": round(spend / imps * 1000, 4) if imps else None,
            "impression_pacing_percentage": round(min(100, imps / planned_imps * 100), 2) if planned_imps else 0,
            "inventory_availability_score": round(rnd.uniform(60, 98), 2), "measurement_timestamp": ts, "notes": None,
            "pacing_granularity": "daily", "pacing_period_end": ts, "pacing_period_start": start, "pacing_status": status,
            "pacing_variance_threshold": 10.0, "planned_impressions": planned_imps, "planned_spend_amount": round(planned_spend, 4),
            "quality_score": round(rnd.uniform(6, 10), 2),
            "recommended_bid_adjustment": round(max(-50, min(50, (1 - ratio) * 100)), 2) if status in ("under_delivering", "over_delivering") else None,
            "recommended_budget_adjustment": None, "source_record_reference": f"{li.row['line_item_code']}:{d:%Y%m%d}",
            "spend_pacing_percentage": round(min(100, ratio * 100), 2),
            "viewability_rate": round(day.viewable / day.measurable * 100, 2) if day.measurable else None,
        }
        self.audit(row, ts + timedelta(minutes=rnd.int(5, 90)), "pacing_job")
        return row

    @staticmethod
    def audit(row: dict, ts: datetime, actor: str) -> None:
        row["created_at"] = ts
        row["created_by"] = actor
        row["updated_at"] = ts
        row["updated_by"] = actor


def active_on(w: World, d: date) -> list[LineItem]:
    return [li for c in w.campaigns for li in c.line_items if li.start <= d <= li.end and d in li.daily]


def scaled_count(n: int, sample: int) -> int:
    return int(math.ceil(n / sample))
