"""Campaigns end to end: brief (crm) -> campaign, plan, IOs, flights, line items, ads (media_ops)
-> activations (cdp), KPI targets (adserver), budgets and IO lines (erp), work (work_mgmt)."""
from __future__ import annotations

from datetime import date, timedelta

from ..values import pools
from ..world import Advertiser, Campaign, LineItem, World, money
from . import production
from .supply import publishers_for, tech

KIND_WEIGHTS = {"display": 0.32, "video": 0.2, "ctv": 0.12, "social": 0.15, "native": 0.09, "audio": 0.06, "dooh": 0.06}
OBJECTIVE = {  # campaign_type: (brief objective, primary kpi, flight objective, pacing goal)
    "brand_awareness": ("brand_awareness", "cpm", "awareness", "impressions"),
    "direct_response": ("sales_conversion", "cpa", "conversion", "conversions"),
    "performance": ("lead_generation", "cpa", "conversion", "conversions"),
    "seasonal": ("reach", "cpm", "awareness", "impressions"),
    "retention": ("retention", "roas", "retention", "conversions"),
    "always_on": ("consideration", "ctr", "consideration", "clicks"),
}
CHANNEL_TYPE = {"display": "display", "video": "video", "ctv": "ctv", "native": "native", "audio": "audio",
                "social": "social", "dooh": "dooh"}
PLACEMENT_CHANNEL = {"display": "display", "video": "video", "ctv": "video", "native": "display", "audio": "audio",
                     "social": "social", "dooh": "display"}
AD_TYPE = {"display": "banner", "video": "video", "ctv": "ctv", "native": "native", "audio": "audio",
           "social": "video", "dooh": "dooh"}
IO_MEDIA_CHANNEL = {"display": "display", "video": "video", "ctv": "CTV", "native": "native", "audio": "audio",
                    "social": "social", "dooh": "DOOH"}
LINE_STATUS = {"future": "approved", "current": "active", "past": "completed"}


def build(w: World) -> None:
    """Backfill: campaigns starting from two months before the window until ~6 weeks ahead."""
    rnd = w.rnd.child("campaigns")
    rate = float(w.cfg.get_path("campaigns.per_advertiser_per_month", 0.6))
    median = float(w.cfg.get_path("clients.annual_media_budget", 1_500_000))
    first = (w.start - timedelta(days=60)).replace(day=1)
    month = first
    horizon = w.today + timedelta(days=45)
    while month <= horizon:
        for adv in w.advertisers:
            onboard = adv.row["onboarding_date"]
            if onboard > month + timedelta(days=27) or (adv.churned and adv.churned < month):
                continue
            if adv.row["holding_company_name"] is None and any(
                    a.row["holding_company_name"] == adv.label for a in w.advertisers):
                continue  # holding companies buy through their subsidiaries
            k = rnd.poisson(rate * (adv.budget / median) ** 0.5)
            for _ in range(k):
                start = rnd.date_between(month, month + timedelta(days=27))
                if start > horizon:
                    continue
                create(w, adv, start, rnd)
        month = (month + timedelta(days=32)).replace(day=1)


def create(w: World, adv: Advertiser, start: date, rnd, brief_date: date | None = None) -> Campaign | None:
    if brief_date is None:
        brief_date = start - timedelta(days=rnd.int(*w.cfg.get_path("campaigns.lead_days", [14, 45])))
    if brief_date > w.today:
        return None
    year = start.year
    brand = rnd.choice(adv.brands)
    days = rnd.int(*w.cfg.get_path("campaigns.duration_days", [21, 120]))
    end = start + timedelta(days=days)
    budget = rnd.lognormal(float(w.cfg.get_path("campaigns.budget_median", 180_000)) *
                           (adv.budget / float(w.cfg.get_path("clients.annual_media_budget", 1_500_000))) ** 0.5, 0.5)
    ctype = rnd.weighted(list(OBJECTIVE), [4, 2, 2, 2, 1, 1])
    objective, kpi, flight_objective, pacing_goal = OBJECTIVE[ctype]
    theme = rnd.choice(pools.CAMPAIGN_THEMES)
    if start.month in (11, 12):
        theme = rnd.choice(["Holiday", "Black Friday", "Year End Clearance", "Q4 Push"])
    name = f"{brand['brand_name']} {theme} {year}"
    kinds = sorted(set(rnd.weighted(KIND_WEIGHTS) for _ in range(rnd.int(1, 3))))
    status = w.status("campaign", start, end)
    persona = rnd.choice(w.personas) if w.personas else None
    segment = rnd.choice(adv.segments + rnd.sample(w.segments, 3))

    ctx = w.adv_ctx(adv, brief_date, scale=budget, duration=days,
                    entities={"brand": brand["brand_id"], "persona": persona["persona_id"] if persona else None,
                              "segment": segment["segment_id"]})
    brief = w.make("client_brief", {
        "brief_number": f"BRF-{year}-{w.next_seq(f'brf{year}'):06d}", "title": f"{name} brief", "brief_type": "campaign",
        "brief_status": w.status("client_brief", start, end), "campaign_start_date": start, "campaign_end_date": end,
        "submission_date": brief_date, "approval_date": brief_date + timedelta(days=rnd.int(2, 7)),
        "budget_indication_amount": money(budget * rnd.uniform(0.9, 1.15)), "budget_currency_code": "USD",
        "campaign_objective": objective, "primary_kpi": kpi, "target_persona_id": persona["persona_id"] if persona else None,
        "initiative_id": None, "closed_date": end + timedelta(days=14) if end + timedelta(days=14) < w.today else None,
        "closure_reason": "completed" if end + timedelta(days=14) < w.today else None}, ctx, rnd)
    ctx = ctx.with_(entities={"client_brief": brief["client_brief_id"]})

    approved = brief_date + timedelta(days=rnd.int(5, 12))
    cpm_target = rnd.uniform(6, 18)
    row = w.make("campaign", {
        "campaign_code": f"CMP-{year}-{w.next_seq(f'cmp{year}'):05d}", "campaign_name": name, "campaign_status": status,
        "campaign_type": ctype, "start_date": start, "end_date": end, "go_live_date": start, "budget_amount": money(budget),
        "currency_code": "USD", "approval_status": "approved" if approved <= w.today else "pending",
        "approved_date": approved if approved <= w.today else None, "objective": objective.replace("_", " ").title(),
        "primary_kpi": kpi.upper(), "target_cpm": round(cpm_target, 2), "target_cpa": round(rnd.uniform(25, 90), 2),
        "target_ctr": round(rnd.uniform(0.08, 0.6), 2), "supplier_id": None, "viewability_standard": "mrc",
        "_created": w.rnd.ts_on(min(approved, w.today))}, ctx.with_(anchor=start), rnd)
    camp = Campaign(row, adv, brand, start, end, budget, status)
    w.campaigns.append(camp)
    ctx = ctx.with_(entities={"campaign": camp.id})
    for i, k in enumerate([kpi, "viewability"] + (["ctr"] if kpi != "ctr" else [])):
        w.make("campaign_kpi_target", {
            "kpi_type": k, "is_primary_kpi": i == 0, "parent_entity_type": "campaign", "flight_id": None,
            "line_item_id": None, "effective_start_date": start, "effective_end_date": end, "currency_code": "USD",
            "target_value": {"cpm": cpm_target, "cpa": 55, "roas": 4, "ctr": 0.25, "viewability": 70}.get(k, 1000)},
            ctx.with_(anchor=start), rnd)

    assets = production.for_campaign(w, camp, brief, brief_date, kinds, ctx)
    ctx = ctx.with_(entities={"initiative": camp.initiative["initiative_id"],
                              "creative_brief": camp.creative_brief["creative_brief_id"]})

    cc = w.cost_centers.get("Media Buying") or w.cost_centers["root"]
    camp.finance_budget = w.make("finance_budget", {
        "budget_number": f"FB{year}C{w.next_seq(f'fb{year}'):06d}", "budget_name": f"{name} media budget",
        "budget_type": "campaign", "budget_category": "project", "campaign_id": camp.id, "cost_center_id": cc["cost_center_id"],
        "gl_account_id": w.gl["5000"]["gl_account_id"], "approved_amount": money(budget), "allocated_amount": money(budget),
        "fiscal_year": year, "fiscal_period": start.month, "currency_code": "USD", "effective_start_date": start,
        "effective_end_date": end, "approval_status": "approved", "version": "original"}, ctx.with_(anchor=approved), rnd)
    ctx = ctx.with_(entities={"finance_budget": camp.finance_budget["finance_budget_id"]})

    camp.client_io = w.make("contract_insertion_order", {
        "io_number": f"IO-{year}{w.next_seq(f'cio{year}'):06d}", "io_name": f"{name} client IO", "campaign_id": camp.id,
        "master_service_agreement_id": adv.msa["agreement_id"], "brand_id": brand["brand_id"],
        "io_status": cio_status(w, start, end, status), "flight_start_date": start, "flight_end_date": end,
        "total_authorized_spend": money(budget), "currency_code": "USD", "io_submitted_date": brief_date + timedelta(days=3),
        "io_signed_date": approved if approved <= w.today else None, "io_approved_date": approved if approved <= w.today else None,
        "media_channel": IO_MEDIA_CHANNEL[kinds[0]], "rate_type": "CPM", "agency_commission_rate": 15,
        "supplier_id": None, "media_insertion_order_id": None}, ctx.with_(anchor=approved), rnd)
    ctx = ctx.with_(entities={"contract_insertion_order": camp.client_io["contract_insertion_order_id"]})

    camp.plan = w.make("plan", {
        "plan_number": f"MP-{year}-{w.next_seq(f'mp{year}'):06d}", "plan_name": f"{name} media plan",
        "plan_status": plan_status(w, start, end, status), "flight_start_date": start, "flight_end_date": end,
        "total_planned_budget": money(budget), "net_budget": money(budget * 0.85), "currency_code": "USD",
        "approval_status": "approved" if approved <= w.today else "pending", "approval_date": approved if approved <= w.today else None,
        "channel_mix": ", ".join(kinds), "target_cpm": round(cpm_target, 2), "is_programmatic": True}, ctx.with_(anchor=brief_date), rnd)
    ctx = ctx.with_(entities={"plan": camp.plan["plan_id"]})

    n_flights = rnd.int(*w.cfg.get_path("campaigns.flights", [1, 3]))
    n_flights = min(n_flights, max(1, days // 14))
    bounds = [start + timedelta(days=days * i // n_flights) for i in range(n_flights + 1)]
    dsp = tech(w, "DSP")
    adserver = tech(w, "Ad Server")
    line_seq = 0
    for fi in range(n_flights):
        fs = bounds[fi] if fi == 0 else bounds[fi] + timedelta(days=1)
        fe = bounds[fi + 1]
        fbudget = budget / n_flights
        fstatus = "cancelled" if status == "cancelled" and fe >= w.today else w.status("flight", fs, fe)
        flight = w.make("flight", {
            "campaign_id": camp.id, "flight_code": f"FL-{year}-{w.next_seq(f'fl{year}'):06d}",
            "flight_name": f"{name} Flight {fi + 1}", "flight_status": fstatus, "start_date": fs, "end_date": fe,
            "budget_allocated": money(fbudget), "budget_currency_code": "USD", "objective": flight_objective,
            "pacing_goal": pacing_goal, "pacing_type": "even", "media_insertion_order_id": None, "supplier_id": None,
            "target_impressions": int(fbudget / cpm_target * 1000)}, ctx.with_(anchor=fs, duration=(fe - fs).days), rnd)
        camp.flights.append(flight)
        fctx = ctx.with_(entities={"flight": flight["flight_id"]})
        torder = w.make("trafficking_order", {
            "campaign_id": camp.id, "flight_id": flight["flight_id"], "trafficking_order_number": f"TO-{w.next_seq('to'):08d}",
            "trafficking_status": traffic_status(w, fs, fe, status), "go_live_date": fs, "parent_trafficking_order_id": None,
            "tech_partner_id": adserver.tech["tech_partner_id"] if adserver else None, "trafficking_instruction_id": None,
            "submitted_timestamp": w.rnd.ts_on(fs - timedelta(days=4)) if fs - timedelta(days=4) <= w.today else None},
            fctx.with_(anchor=fs - timedelta(days=5)), rnd)
        n_li = rnd.int(*w.cfg.get_path("campaigns.line_items_per_flight", [2, 5]))
        shares = [rnd.uniform(0.5, 1.5) for _ in range(n_li)]
        for li_i in range(n_li):
            line_seq += 1
            kind = kinds[li_i % len(kinds)]
            li_budget = fbudget * shares[li_i] / sum(shares) * 0.97
            item = line_item(w, camp, flight, torder, kind, li_budget, fs, fe, line_seq, assets.get(kind, []),
                             segment, dsp, adserver, fctx, rnd)
            if item:
                camp.line_items.append(item)
    return camp


def line_item(w: World, camp: Campaign, flight: dict, torder: dict, kind: str, budget: float, fs: date, fe: date,
              seq: int, assets: list[dict], segment: dict, dsp, adserver, ctx, rnd) -> LineItem | None:
    pubs = publishers_for(w, kind)
    if not pubs:
        return None
    sup = rnd.choice(pubs)
    prop = rnd.choice([p for p in sup.properties if p["_kind"] == kind])
    catalog = rnd.choice([p for p in sup.placements if p["publisher_property_id"] == prop["publisher_property_id"]] or sup.placements)
    fmt = w.reg.get(catalog["ad_format_id"])
    year = fs.year
    cpm = float(w.cfg.get_path(f"delivery.cpm.{kind}", 8.0)) * rnd.lognormal(1.0, 0.18)
    imps = int(budget / cpm * 1000)
    programmatic = kind in ("display", "video", "ctv", "native") and rnd.chance(0.65)
    sid = sup.supplier["supplier_id"]
    ctx = ctx.with_(entities={"supplier": sid, "publisher": sup.publisher["publisher_id"],
                              "publisher_property": prop["publisher_property_id"], "ad_channel": w.channels[kind]["ad_channel_id"],
                              "ad_format": fmt["ad_format_id"], "vendor_rate_card": sup.rate_card["vendor_rate_card_id"],
                              "placement": catalog["placement_id"], "spec": w.specs[fmt["ad_format_id"]]["spec_id"],
                              "segment": segment["segment_id"]},
                    scale=budget, duration=(fe - fs).days)
    io = camp.ios.get(sid)
    if io is None:
        io = w.make("media_insertion_order", {
            "io_number": f"IO-8{year}{w.next_seq(f'mio{year}'):05d}", "version_number": 1, "io_name": f"{camp.row['campaign_name']} - {sup.supplier['trading_name']}",
            "plan_id": camp.plan["plan_id"], "io_status": mio_status(w, camp), "flight_start_date": camp.start,
            "flight_end_date": camp.end, "currency_code": "USD", "buying_method": "programmatic" if programmatic else "direct",
            "pricing_model": "cpm", "is_programmatic": programmatic, "authorized_spend_amount": 0.0,
            "contract_insertion_order_id": camp.client_io["contract_insertion_order_id"],
            "execution_date": camp.start - timedelta(days=7) if camp.start - timedelta(days=7) <= w.today else None},
            ctx.with_(anchor=camp.start - timedelta(days=10)), rnd)
        camp.ios[sid] = io
        if camp.client_io.get("media_insertion_order_id") is None:
            camp.client_io["media_insertion_order_id"] = io["media_insertion_order_id"]
            camp.client_io["supplier_id"] = sid
    io["authorized_spend_amount"] = money(float(io["authorized_spend_amount"] or 0) + budget)
    io["net_spend_amount"] = money(float(io["authorized_spend_amount"]) * 0.85)
    ctx = ctx.with_(entities={"media_insertion_order": io["media_insertion_order_id"]})

    deal = None
    if programmatic:
        deal = w.make("programmatic_deal", {
            "campaign_id": camp.id, "deal_code": f"DL-{w.next_seq('deal'):07d}", "deal_name": f"{sup.supplier['trading_name']} {kind.upper()} PMP",
            "deal_status": {"future": "pending_approval", "current": "active", "past": "expired"}[phase_of(w, fs, fe)],
            "deal_type": rnd.weighted(["pmp", "preferred_deal", "programmatic_guaranteed"], [5, 3, 2]),
            "start_date": fs, "end_date": fe, "floor_cpm": round(cpm * 0.7, 2), "budget_amount": money(budget),
            "currency_code": "USD", "dsp_tech_partner_id": dsp.tech["tech_partner_id"] if dsp else None,
            "impression_commitment": imps}, ctx.with_(anchor=fs - timedelta(days=7)), rnd)
        ctx = ctx.with_(entities={"programmatic_deal": deal["programmatic_deal_id"]})
    mp_status = {"future": "pending", "current": "active", "past": "inactive"}[phase_of(w, fs, fe)]
    placement = w.make("media_placement", {
        "media_insertion_order_id": io["media_insertion_order_id"], "placement_code": f"MP{w.next_seq('mpl'):07d}",
        "placement_name": f"{catalog['placement_name']} | {camp.row['campaign_code']}", "placement_status": mp_status,
        "media_catalog_placement_id": catalog["placement_id"], "media_ad_server_placement_id": catalog["placement_id"],
        "original_placement_media_placement_id": None, "ad_server_tech_partner_id": adserver.tech["tech_partner_id"] if adserver else None,
        "channel_type": PLACEMENT_CHANNEL[kind], "contracted_impressions": imps, "contracted_rate": round(cpm, 4),
        "contracted_value": money(budget), "net_contracted_value": money(budget * 0.85), "cpm_list_price": round(cpm * 1.2, 4),
        "currency_code": "USD", "flight_start_date": fs, "flight_end_date": fe, "effective_start_date": fs,
        "effective_end_date": fe, "rate_type": "cpm", "site_name": prop["property_name"], "asset_id": None,
        "primary_media_audience_segment_id": segment["segment_id"]}, ctx.with_(anchor=fs - timedelta(days=7)), rnd)
    ctx = ctx.with_(entities={"media_placement": placement["media_placement_id"]})
    plan_line = w.make("plan_line", {
        "plan_id": camp.plan["plan_id"], "line_number": seq, "line_name": f"{kind.upper()} - {sup.supplier['trading_name']}",
        "buying_status": {"future": "io_confirmed", "current": "live", "past": "live"}[phase_of(w, fs, fe)],
        "flight_start_date": fs, "flight_end_date": fe, "planned_spend": money(budget), "planned_net_spend": money(budget * 0.85),
        "planned_impressions": imps, "planned_cpm": round(cpm, 2), "currency_code": "USD", "buying_type": "cpm",
        "media_type": "digital", "country_code": "USA", "is_bonus": False, "is_makegood": False}, ctx.with_(anchor=fs - timedelta(days=14)), rnd)
    ctx = ctx.with_(entities={"plan_line": plan_line["plan_line_id"]})
    buy = w.make("buy", {
        "media_placement_id": placement["media_placement_id"], "plan_line_id": plan_line["plan_line_id"],
        "buy_number": f"BUY-{w.next_seq('buy'):07d}", "buy_status": {"future": "confirmed", "current": "confirmed", "past": "completed"}[phase_of(w, fs, fe)],
        "buy_type": "programmatic_rtb" if programmatic else "direct", "buy_date": fs - timedelta(days=5),
        "flight_start_date": fs, "flight_end_date": fe, "gross_buy_amount": money(budget), "net_buy_amount": money(budget * 0.85),
        "agency_commission_amount": money(budget * 0.15), "negotiated_rate": round(cpm, 4), "rate_basis": "cpm",
        "booked_units": imps, "currency_code": "USD", "cancellation_date": None, "cancellation_reason": None,
        "delivery_status": {"future": "not_started", "current": "in_delivery", "past": "fully_delivered"}[phase_of(w, fs, fe)]},
        ctx.with_(anchor=fs - timedelta(days=5)), rnd)
    ctx = ctx.with_(entities={"buy": buy["buy_id"]})
    w.make("schedule", {
        "campaign_id": camp.id, "schedule_number": f"SCH-{w.next_seq('sch'):07d}", "schedule_name": f"{plan_line['line_name']} schedule",
        "flight_start_date": fs, "flight_end_date": fe, "scheduled_impressions": imps, "cpm_rate": round(cpm, 2),
        "gross_cost": money(budget), "net_cost": money(budget * 0.85), "currency_code": "USD", "air_start_time": None,
        "air_end_time": None, "trafficking_instruction_id": None, "vehicle_name": prop["property_name"]}, ctx.with_(anchor=fs - timedelta(days=5)), rnd)
    instr = w.make("trafficking_instruction", {
        "campaign_id": camp.id, "instruction_number": f"TI-{w.next_seq('ti'):07d}",
        "instruction_status": "confirmed" if fs - timedelta(days=3) <= w.today else "sent", "instruction_type": "new",
        "delivery_start_date": fs, "delivery_end_date": fe, "parent_instruction_trafficking_instruction_id": None,
        "tech_partner_id": adserver.tech["tech_partner_id"] if adserver else None,
        "suppression_list_id": camp.adv.suppression["suppression_list_id"] if camp.adv.suppression else None,
        "click_through_url": f"https://www.{camp.adv.domain}/{camp.row['campaign_code'].lower()}"},
        ctx.with_(anchor=fs - timedelta(days=6)), rnd)
    ctx = ctx.with_(entities={"trafficking_instruction": instr["trafficking_instruction_id"],
                              "trafficking_order": torder["trafficking_order_id"]})
    li_phase = phase_of(w, fs, fe)
    if camp.status == "cancelled":
        delivery_status = "stopped"
    else:
        delivery_status = {"future": "scheduled", "past": "completed"}.get(li_phase) or rnd.weighted(
            ["delivering", "under_delivering", "over_delivering", "paused"], [8, 1.2, 0.6, 0.4])
    row = w.make("line_item", {
        "campaign_id": camp.id, "flight_id": flight["flight_id"], "line_item_code": f"LI-{year}-{w.next_seq(f'li{year}'):07d}",
        "line_item_name": f"{camp.brand['brand_name']} | {kind.upper()} | {prop['property_name']}", "line_sequence": seq,
        "delivery_status": delivery_status, "start_date": fs, "end_date": fe, "channel_type": CHANNEL_TYPE[kind],
        "ad_format": fmt["format_name"], "rate_type": "cpm", "rate_amount": round(cpm, 4), "gross_cost": money(budget),
        "net_cost": money(budget * 0.85), "agency_commission_rate": 15, "booked_impressions": imps,
        "booked_clicks": int(imps * float(w.cfg.get_path(f"delivery.ctr.{kind}", 0.001))), "currency_code": "USD",
        "is_programmatic": programmatic, "programmatic_deal_id": deal["programmatic_deal_id"] if deal else None,
        "vendor_publisher_id": sup.publisher["publisher_id"], "supplier_id": sid,
        "placement_type": "programmatic_guaranteed" if programmatic else "guaranteed",
        "trafficking_status": {"future": "ready_to_serve", "current": "live", "past": "completed"}[li_phase],
        "pacing_strategy": "even", "pacing_status": {"future": None, "past": "completed"}.get(li_phase, "on_track"),
        "creative_brief_id": camp.creative_brief["creative_brief_id"], "work_package_id": None},
        ctx.with_(anchor=fs - timedelta(days=4)), rnd)
    item = LineItem(row, kind, flight, camp, sup, placement, cpm, budget, fs, fe, deal=deal, segment=segment, io=io,
                    plan_line=plan_line, buy=buy, trafficking_order=torder, instruction=instr)
    ctx = ctx.with_(entities={"line_item": item.id})
    item.pacing_rule = w.make("pacing_rule", {
        "campaign_id": camp.id, "rule_name": f"{row['line_item_code']} even pacing", "pacing_type": "even",
        "parent_entity_type": "line_item", "daily_spend_cap": money(budget / max(1, (fe - fs).days) * 1.3),
        "daily_impression_goal": int(imps / max(1, (fe - fs).days)), "pacing_status": LINE_STATUS[li_phase] if li_phase != "future" else "draft",
        "effective_start_date": fs, "effective_end_date": fe, "currency_code": "USD", "timezone": "America/New_York"},
        ctx.with_(anchor=fs - timedelta(days=4)), rnd)
    w.make("budget_allocation", {
        "campaign_id": camp.id, "pacing_rule_id": item.pacing_rule["pacing_rule_id"], "planned_budget_amount": money(budget),
        "committed_spend": money(budget), "actual_spend": 0.0, "remaining_budget": money(budget), "currency_code": "USD",
        "channel_type": CHANNEL_TYPE[kind], "allocation_status": {"future": "draft", "current": "active", "past": "completed"}[li_phase],
        "effective_start_date": fs, "effective_end_date": fe, "budget_period_type": "flight"}, ctx.with_(anchor=fs - timedelta(days=4)), rnd)
    for dim in rnd.sample(["geo", "device", "audience", "daypart"], 2):
        w.make("targeting_rule", {"campaign_id": camp.id, "rule_name": f"{row['line_item_code']} {dim}",
                                  "parent_entity_type": "line_item", "targeting_operator": "include", "is_active": li_phase != "past",
                                  "effective_start_date": fs, "effective_end_date": fe,
                                  "segment_id": segment["segment_id"] if dim == "audience" else None}, ctx.with_(anchor=fs - timedelta(days=4)), rnd)
    lo, hi = w.cfg.get_path("campaigns.ads_per_line_item", [1, 3])
    for asset in rnd.sample(assets, min(len(assets), rnd.int(lo, hi))) if assets else []:
        ca = w.make("creative_assignment", {
            "line_item_id": item.id, "asset_id": asset["asset_id"], "start_date": fs, "end_date": fe,
            "trafficking_status": {"future": "ready_to_serve", "current": "live", "past": "completed"}[li_phase],
            "rotation_weight": round(100 / hi, 2), "impression_count": 0, "click_count": 0, "conversion_count": 0,
            "view_count": 0, "ctr": 0.0, "deliverable_tracker_id": None}, ctx.with_(anchor=fs - timedelta(days=3)), rnd)
        ad = w.make("ad", {
            "campaign_id": camp.id, "line_item_id": item.id, "creative_assignment_id": ca["creative_assignment_id"],
            "asset_id": asset["asset_id"], "ad_name": f"{asset['asset_name']} | {row['line_item_code']}",
            "ad_status": {"future": "approved", "current": "live", "past": "archived"}[li_phase] if camp.status != "cancelled" else "paused",
            "ad_type": AD_TYPE[kind], "format": asset["_format"]["format_name"], "go_live_date": fs, "end_date": fe,
            "landing_page_url": f"https://www.{camp.adv.domain}/{camp.row['campaign_code'].lower()}",
            "click_through_url": f"https://www.{camp.adv.domain}/{camp.row['campaign_code'].lower()}?utm_source={sup.supplier['trading_name'].split()[0].lower()}",
            "spec_id": w.specs[asset["_format"]["ad_format_id"]]["spec_id"], "tech_partner_id": adserver.tech["tech_partner_id"] if adserver else None,
            "rejection_reason": None}, ctx.with_(anchor=fs - timedelta(days=3)), rnd)
        item.ads.append(ad)
        item.assets.append(asset)
    item.kpi_target = w.make("performance_kpi_target", {
        "target_name": f"{row['line_item_code']} {'CPA' if 'conversion' in camp.row.get('objective', '').lower() else 'CPM'} target",
        "kpi_type": "CPM", "target_value": round(cpm, 4), "target_unit": "currency", "target_currency_code": "USD",
        "target_period_start_date": fs, "target_period_end_date": fe,
        "target_status": {"future": "draft", "current": "active", "past": "achieved"}[li_phase]}, ctx.with_(anchor=fs - timedelta(days=4)), rnd)
    if segment and kind in ("display", "video", "ctv", "native", "social"):
        item.activation = w.make("activation", {
            "activation_segment_id": segment["segment_id"], "activation_platform_audience_audience_segment_id": None,
            "campaign_id": camp.id, "flight_id": flight["flight_id"], "line_item_id": item.id,
            "tech_partner_id": dsp.tech["tech_partner_id"] if dsp else None,
            "activation_status": {"future": "Pending", "current": "Active", "past": "Expired"}[li_phase],
            "activation_type": "Prospecting" if segment["data_source_tier"] == "third_party" else "Retargeting",
            "activation_name": f"{segment['audience_segment_name']} -> {row['line_item_code']}", "effective_start_date": fs,
            "effective_end_date": fe, "activation_date": fs - timedelta(days=2) if fs - timedelta(days=2) <= w.today else None,
            "currency_code": "USD", "budget_line_id": None}, ctx.with_(anchor=fs - timedelta(days=2)), rnd)
    item.io_line = w.make("io_line", {
        "vendor_io_media_insertion_order_id": io["media_insertion_order_id"], "line_number": seq,
        "line_status": LINE_STATUS[li_phase] if camp.status != "cancelled" else "cancelled", "flight_start_date": fs,
        "flight_end_date": fe, "contracted_spend": money(budget), "contracted_units": imps, "rate": round(cpm, 6),
        "net_rate": round(cpm * 0.85, 6), "buying_type": "CPM", "currency_code": "USD", "actual_spend": 0.0,
        "actual_units_delivered": 0, "agency_commission_pct": 15, "media_placement_id": placement["media_placement_id"],
        "reconciliation_status": "unreconciled"}, ctx.with_(anchor=fs - timedelta(days=5)), rnd)
    item.budget_line = w.make("budget_line", {
        "finance_budget_id": camp.finance_budget["finance_budget_id"], "line_number": seq,
        "line_description": row["line_item_name"], "allocated_amount": money(budget), "committed_amount": money(budget),
        "actual_spend": 0.0, "currency_code": "USD", "cost_category": "media", "billing_category": "working_media",
        "channel_type": {"social": "digital", "native": "display"}.get(kind, kind) if kind != "dooh" else "dooh",
        "io_line_id": item.io_line["io_line_id"], "gl_account_id": w.gl["5100" if kind in ("video", "ctv") else "5000"]["gl_account_id"],
        "approval_status": "approved", "is_active": li_phase != "past", "is_billable": True}, ctx.with_(anchor=fs - timedelta(days=5)), rnd)
    return item


def phase_of(w: World, s: date, e: date) -> str:
    from ..lifecycle import phase_of as p
    return p(s, e, w.today)


def cio_status(w: World, s: date, e: date, cstatus: str) -> str:
    if cstatus == "cancelled":
        return "cancelled"
    return {"future": "executed", "current": "active", "past": "completed"}[phase_of(w, s, e)]


def mio_status(w: World, camp: Campaign) -> str:
    if camp.status == "cancelled":
        return "cancelled"
    return "executed" if camp.start - timedelta(days=7) <= w.today else "pending_approval"


def plan_status(w: World, s: date, e: date, cstatus: str) -> str:
    if cstatus == "cancelled":
        return "cancelled"
    return {"future": "approved", "current": "active", "past": "completed"}[phase_of(w, s, e)]


def traffic_status(w: World, s: date, e: date, cstatus: str) -> str:
    if cstatus == "cancelled":
        return "cancelled"
    return {"future": "ready_to_serve", "current": "live", "past": "completed"}[phase_of(w, s, e)]
