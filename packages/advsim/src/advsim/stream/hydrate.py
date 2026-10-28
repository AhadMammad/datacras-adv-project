"""Rebuild a World from the databases so the continuous simulation can extend what is there."""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import date, timedelta

from psycopg import sql
from psycopg.rows import dict_row

from ..rng import Rand
from ..scenarios.supply import CHANNELS, FORMATS
from ..sink.postgres import PgSink
from ..values import pools
from ..world import Advertiser, Campaign, LineItem, Supply, World

EVENT_TABLES = {"impression_event", "click_event", "conversion_event", "video_completion_event",
                "viewability_measurement", "delivery_pacing"}
SKIP = EVENT_TABLES | {"time_entry", "segment_membership"}  # high volume, not needed to extend the world
KIND_BY_CHANNEL = {code: kind for kind, (code, *_rest) in CHANNELS.items()}
KIND_BY_FORMAT = {f[0]: kind for kind, fs in FORMATS.items() for f in fs}


def load_rows(w: World, sink: PgSink, lookback: date) -> None:
    for db in w.s.systems:
        conn = sink.conn(db)
        for t in w.s.systems[db].tables:
            if t.name in SKIP:
                continue
            q = sql.SQL("SELECT * FROM {}").format(sql.Identifier(t.schema, t.name))
            with conn.cursor(row_factory=dict_row) as cur:
                rows = cur.execute(q).fetchall()
            pk = t.pk.name
            for r in rows:
                r["_adv"] = r.get("advertiser_id")
                r["_campaign"] = r.get("campaign_id")
                w.reg.add(t.name, pk, r)
                for cols in t.uniques:
                    w.reg.claim(t.name, ",".join(cols), tuple(r[c] for c in cols))
        conn.rollback()
    w.reg.new_rows.clear()


def by(rows: list[dict], key: str) -> dict:
    out = defaultdict(list)
    for r in rows:
        out[r.get(key)].append(r)
    return out


def hydrate(w: World, sink: PgSink, profile_seed: int) -> None:
    t0 = time.time()
    load_rows(w, sink, w.today - timedelta(days=60))
    R = w.reg.rows
    rnd = Rand(profile_seed, "org")
    n = int(w.cfg.get_path("org.employees", 60))
    names: set[str] = set()
    while len(names) < n:
        names.add(rnd.fake.name())
    w.people = sorted(names)
    for p in w.people:
        w.roles[p] = (rnd.choice(pools.JOB_TITLES), rnd.choice(pools.DEPARTMENTS))

    for cc in R["cost_center"]:
        w.cost_centers["root" if cc["parent_cost_center_id"] is None else cc["cost_center_name"]] = cc
    w.gl = {g["account_code"]: g for g in R["gl_account"]}
    for ch in R["ad_channel"]:
        if ch["channel_code"] in KIND_BY_CHANNEL:
            w.channels[KIND_BY_CHANNEL[ch["channel_code"]]] = ch
    kind_of_channel = {ch["ad_channel_id"]: k for k, ch in w.channels.items()}
    for f in R["ad_format"]:
        k = KIND_BY_FORMAT.get(f["format_code"])
        if k:
            w.formats.setdefault(k, []).append(f)
    w.specs = {s["ad_format_id"]: s for s in R["spec"] if s["ad_format_id"]}

    pubs = by(R["publisher"], "supplier_id")
    techs = by(R["tech_partner"], "supplier_id")
    props = by(R["publisher_property"], "publisher_id")
    places = by(R["placement"], "publisher_property_id")
    vrc = by(R["vendor_rate_card"], "supplier_id")
    vagr = by([a for a in R["agreement"] if a["supplier_id"]], "supplier_id")
    for s in R["supplier"]:
        kind = {"publisher": "publisher", "tech_platform": "tech", "production": "production"}.get(s["vendor_type"], "data")
        sup = Supply(s, kind, rate_card=(vrc.get(s["supplier_id"]) or [None])[0], agreement=(vagr.get(s["supplier_id"]) or [None])[0])
        if pubs.get(s["supplier_id"]):
            sup.publisher = pubs[s["supplier_id"]][0]
            for p in props.get(sup.publisher["publisher_id"], []):
                p["_kind"] = kind_of_channel.get(p["ad_channel_id"], "display")
                p["_domain"] = (p.get("property_url") or "https://www.example.com").split("//")[-1].removeprefix("www.")
                sup.properties.append(p)
                for pl in places.get(p["publisher_property_id"], []):
                    pl["_kind"] = p["_kind"]
                    sup.placements.append(pl)
            sup.channel_kinds = sorted({p["_kind"] for p in sup.properties})
        if techs.get(s["supplier_id"]):
            sup.tech = techs[s["supplier_id"]][0]
            sup.tech["_label"] = (s.get("trading_name") or "").split(" ", 1)[-1]
        w.supply.append(sup)

    tax = {t["taxonomy_id"]: t for t in R["taxonomy"]}
    for t in R["taxonomy"]:
        t["_dtype"] = t.get("data_type")
    w.taxonomy = R["taxonomy"]
    w.personas = R["persona"]

    brands = by(R["brand"], "primary_client_brand_advertiser_id")
    msas = by([a for a in R["agreement"] if a["advertiser_id"] and a["agreement_type"] == "MSA"], "advertiser_id")
    rels = by(R["agency_relationship"], "advertiser_id")
    sows = by(R["sow"], "sow_advertiser_id")
    rcs = by(R["contract_rate_card"], "advertiser_id")
    ams = by(R["attribution_model"], "advertiser_id")
    pixels = by(R["tracking_pixel"], "advertiser_id")
    sups = by(R["suppression_list"], "advertiser_id")
    adv_by_id = {}
    segs_by_name = {s["audience_segment_name"]: s for s in R["segment"]}
    for a in R["advertiser"]:
        label = a.get("trading_name") or a["legal_entity_name"]
        email = a.get("primary_contact_email") or ""
        domain = email.split("@")[-1] if "@" in email else "".join(ch for ch in label.lower() if ch.isalnum())[:24] + ".com"
        sow_rows = sows.get(a["advertiser_id"], [])
        budget = float(max((s["media_budget_amount"] or 0 for s in sow_rows), default=0) or w.cfg.get_path("clients.annual_media_budget", 1_500_000))
        adv = Advertiser(a, label, domain, rnd.choice(pools.INDUSTRIES), budget, w.geo(),
                         brands=brands.get(a["advertiser_id"], []), msa=(msas.get(a["advertiser_id"]) or [None])[0],
                         relationship=(rels.get(a["advertiser_id"]) or [None])[0],
                         sows={s["effective_start_date"].year: s for s in sow_rows if s["effective_start_date"]},
                         rate_card=(rcs.get(a["advertiser_id"]) or [None])[0],
                         attribution_model=(ams.get(a["advertiser_id"]) or [None])[0],
                         pixels=[p for p in pixels.get(a["advertiser_id"], []) if p["pixel_type"] == "conversion_tag"],
                         segments=[s for n_, s in segs_by_name.items() if n_.startswith(label + " ")],
                         suppression=(sups.get(a["advertiser_id"]) or [None])[0],
                         team=rnd.sample(w.people, 5), cost_center=w.cost_centers.get("Account Management"),
                         churned=a.get("churn_date"))
        if a["account_status"] == "churned" and not adv.churned:
            adv.churned = w.today
        w.advertisers.append(adv)
        adv_by_id[a["advertiser_id"]] = adv
    w.segments = [s for s in R["segment"] if s.get("data_source_tier") == "third_party"] or R["segment"]

    hydrate_campaigns(w, adv_by_id, tax)
    w.fill.pending.clear()
    print(f"hydrated {sum(len(v) for v in R.values()):,} rows, {len(w.advertisers)} advertisers, "
          f"{len(w.campaigns)} recent campaigns, {sum(len(c.line_items) for c in w.campaigns)} line items "
          f"in {time.time() - t0:.1f}s", flush=True)


def hydrate_campaigns(w: World, adv_by_id: dict, tax: dict) -> None:
    R = w.reg.rows
    since = w.today - timedelta(days=45)
    flights = by(R["flight"], "campaign_id")
    lis = by(R["line_item"], "campaign_id")
    ads = by(R["ad"], "line_item_id")
    buys = by(R["buy"], "plan_line_id")
    io_lines = by(R["io_line"], "line_item_id")
    pacing = by(R["pacing_rule"], "line_item_id")
    acts = by(R["activation"], "line_item_id")
    instr = by(R["trafficking_instruction"], "media_placement_id")
    cios = by(R["contract_insertion_order"], "campaign_id")
    plans = by(R["plan"], "campaign_id")
    fbs = by([f for f in R["finance_budget"] if f["campaign_id"]], "campaign_id")
    inits = by(R["initiative"], "campaign_id")
    cbs = by(R["creative_brief"], "campaign_id")
    blines = by(R["budget_line"], "io_line_id")
    kpis = by(R["performance_kpi_target"], "line_item_id")
    sup_by_id = {s.supplier["supplier_id"]: s for s in w.supply}
    kind_by_channel_type = {"display": "display", "video": "video", "ctv": "ctv", "native": "native", "audio": "audio",
                            "social": "social", "dooh": "dooh"}
    for c in R["campaign"]:
        if not c["end_date"] or c["end_date"] < since or c["advertiser_id"] not in adv_by_id:
            continue
        adv = adv_by_id[c["advertiser_id"]]
        brand = w.reg.get(c["brand_id"]) or (adv.brands[0] if adv.brands else None)
        if not brand or not cios.get(c["campaign_id"]):
            continue
        camp = Campaign(c, adv, brand, c["start_date"], c["end_date"], float(c["budget_amount"] or 0), c["campaign_status"],
                        flights=flights.get(c["campaign_id"], []), client_io=cios[c["campaign_id"]][0],
                        plan=(plans.get(c["campaign_id"]) or [None])[0], initiative=(inits.get(c["campaign_id"]) or [None])[0],
                        finance_budget=(fbs.get(c["campaign_id"]) or [None])[0], creative_brief=(cbs.get(c["campaign_id"]) or [None])[0])
        for li in lis.get(c["campaign_id"], []):
            buy = (buys.get(li["plan_line_id"]) or [None])[0]
            sup = sup_by_id.get(li["supplier_id"])
            if not buy or not sup or not sup.publisher:
                continue
            placement = w.reg.get(buy["media_placement_id"])
            item = LineItem(li, kind_by_channel_type.get(li["channel_type"], "display"), w.reg.get(li["flight_id"]), camp, sup,
                            placement, float(li["rate_amount"] or 8), float(li["gross_cost"] or 0), li["start_date"], li["end_date"],
                            ads=ads.get(li["line_item_id"], []), deal=w.reg.get(li["programmatic_deal_id"]),
                            io=w.reg.get(li["media_insertion_order_id"]), plan_line=w.reg.get(li["plan_line_id"]), buy=buy,
                            io_line=(io_lines.get(li["line_item_id"]) or [None])[0],
                            pacing_rule=(pacing.get(li["line_item_id"]) or [None])[0],
                            trafficking_order=w.reg.get(li["trafficking_order_id"]),
                            instruction=(instr.get(placement["media_placement_id"]) or [None])[0] if placement else None,
                            activation=(acts.get(li["line_item_id"]) or [None])[0],
                            kpi_target=(kpis.get(li["line_item_id"]) or [None])[0])
            item.assets = [w.reg.get(a["asset_id"]) for a in item.ads if a.get("asset_id") and w.reg.get(a["asset_id"])]
            if item.activation:
                item.segment = w.reg.get(item.activation["activation_segment_id"])
            if item.io_line:
                item.budget_line = (blines.get(item.io_line["io_line_id"]) or [None])[0]
            if None in (item.flight, item.placement, item.io, item.plan_line, item.io_line, item.pacing_rule,
                        item.trafficking_order, item.instruction):
                continue
            camp.line_items.append(item)
        w.campaigns.append(camp)
