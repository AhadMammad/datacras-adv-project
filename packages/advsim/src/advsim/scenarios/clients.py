"""Clients and their commercial frame (crm_db), plus per-advertiser setup in adserver_db, cdp_db and work_mgmt_db."""
from __future__ import annotations

from datetime import date, timedelta

from ..values import pools
from ..world import Advertiser, World
from . import audiences

CATEGORY_BY_INDUSTRY = {
    "Consumer Packaged Goods": "Personal Care", "Retail": "Retail", "Automotive": "Automotive",
    "Financial Services": "Financial Services", "Telecommunications": "Technology", "Travel & Hospitality": "Travel",
    "Pharmaceuticals": "Healthcare", "Technology": "Technology", "Quick Service Restaurants": "Food & Beverage",
    "Entertainment & Media": "Entertainment", "Beverages": "Food & Beverage", "Insurance": "Financial Services",
}
CLAUSES = ["payment", "confidentiality", "intellectual_property", "termination", "audit_rights",
           "liability_limitation", "service_level", "pricing"]
SLAS = [("creative_turnaround", "Creative turnaround", "business_days", 5),
        ("campaign_go_live", "Campaign go-live", "business_days", 3),
        ("reporting_delivery", "Weekly reporting delivery", "hours", 48),
        ("trafficking_response", "Trafficking response", "hours", 24)]
SERVICES = [("media_planning", "Media Planner", "mid_level", 165), ("media_buying", "Senior Media Buyer", "senior", 185),
            ("account_management", "Account Director", "principal", 240), ("strategy_consulting", "Strategist", "senior", 210),
            ("creative_services", "Art Director", "senior", 195), ("production", "Producer", "mid_level", 150)]


def build(w: World) -> None:
    rnd = w.rnd.child("clients")
    n = int(w.cfg.get_path("clients.advertisers", 30))
    groups = max(1, int(w.cfg.get_path("clients.holding_groups", 4)))
    holdings = []
    for _ in range(groups):
        holdings.append(new_advertiser(w, rnd, holding=None, onboard=date(w.start.year - 3, 1, 1)))
    for i in range(n - groups):
        parent = holdings[i % groups] if rnd.chance(0.55) else None
        onboard = rnd.date_between(date(w.start.year - 3, 1, 1), w.start + timedelta(days=60)) if rnd.chance(0.85) \
            else rnd.date_between(w.start, w.today - timedelta(days=60))
        new_advertiser(w, rnd, holding=parent, onboard=onboard)
    churn = float(w.cfg.get_path("clients.churn_rate", 0.08))
    for adv in rnd.sample([a for a in w.advertisers if a not in holdings], int(round(churn * n))):
        adv.churned = rnd.date_between(w.start + timedelta(days=90), w.today - timedelta(days=14))
        adv.row["account_status"] = "churned"
        adv.row["churn_date"] = adv.churned


def new_advertiser(w: World, rnd, holding: Advertiser | None, onboard: date) -> Advertiser:
    name = rnd.fake.company().replace(",", "")
    while any(a.label == name for a in w.advertisers):
        name = rnd.fake.company().replace(",", "")
    industry = holding.industry if holding and rnd.chance(0.6) else rnd.choice(pools.INDUSTRIES)
    domain = "".join(ch for ch in name.lower() if ch.isalnum())[:24] + ".com"
    budget = rnd.lognormal(float(w.cfg.get_path("clients.annual_media_budget", 1_500_000)), 0.7)
    adv = Advertiser(row={}, label=name, domain=domain, industry=industry, budget=budget, geo=w.geo())
    adv.team = [w.pick_person("Account Management")] + rnd.sample(w.people, 4)
    adv.cost_center = w.cost_centers.get("Account Management")
    ctx = w.ctx(onboard, label=name, domain=domain, industry=industry, geo=adv.geo, people=tuple(adv.team),
                scale=budget / 12, duration=365 * 3)
    adv.row = w.make("advertiser", {
        "legal_entity_name": f"{name} {rnd.choice(['Inc.', 'LLC', 'Corp.', 'Holdings Inc.'])}", "trading_name": name,
        "account_status": "active" if onboard <= w.today - timedelta(days=30) else "prospect",
        "account_tier": "platinum" if budget > 4e6 else "gold" if budget > 1.5e6 else "silver" if budget > 6e5 else "bronze",
        "holding_company_name": holding.label if holding else None, "onboarding_date": onboard,
        "registered_office_country": "USA", "incorporation_jurisdiction": "US", "preferred_currency": "USD",
        "time_zone": adv.geo[5], "primary_contact_name": rnd.fake.name(),
        "managing_agency_name": None, "is_agency_managed": True, "churn_date": None,
        "crm_account_code": f"001{rnd.int(10**11, 10**12 - 1)}", "erp_customer_number": f"C{rnd.int(100000, 999999)}",
        "iab_taxonomy_id": None}, ctx, rnd)
    adv.row["primary_contact_email"] = f"{adv.row['primary_contact_name'].split()[0].lower()}@{domain}"
    w.advertisers.append(adv)
    ctx = w.adv_ctx(adv, onboard, duration=365 * 3)

    if holding:
        w.make("advertiser_hierarchy", {
            "parent_advertiser_id": holding.id, "child_advertiser_id": adv.id, "primary_root_advertiser_id": holding.id,
            "hierarchy_code": f"AH-{w.next_seq('ah'):06d}", "hierarchy_type": "subsidiary", "hierarchy_level": 2,
            "hierarchy_name": f"{holding.label} > {name}", "hierarchy_path": f"/{holding.label}/{name}",
            "hierarchy_status": "active", "market_region": "North America", "change_reason": "initial_setup",
            "effective_start_date": onboard, "effective_end_date": None, "country_code": "USA", "currency_code": "USD",
            "is_primary_hierarchy": True, "industry_sector": industry}, ctx, rnd)

    lo, hi = w.cfg.get_path("clients.brands_per_advertiser", [1, 4])
    for i in range(rnd.int(lo, hi)):
        bname = f"{rnd.choice(pools.PRODUCT_WORDS)} {rnd.choice(pools.PRODUCT_NOUNS)}" if i else name.split()[0]
        brand = w.make("brand", {
            "brand_name": bname, "brand_code": f"BR{w.next_seq('brand'):05d}", "brand_status": "active",
            "primary_client_brand_advertiser_id": adv.id, "parent_brand_id": None,
            "brand_category": CATEGORY_BY_INDUSTRY.get(industry, "Other"), "annual_media_budget": round(budget / (i + 1.5), 2),
            "budget_currency": "USD", "primary_market_country": "USA", "launch_date": onboard - timedelta(days=rnd.int(200, 4000)),
            "discontinuation_date": None, "website_url": f"https://www.{domain}", "digital_advertising_enabled": True},
            ctx, rnd)
        adv.brands.append(brand)
        w.make("brand_guideline", {"brand_id": brand["brand_id"], "guideline_version": "1.0",
                                   "guideline_status": "active", "effective_date": onboard}, ctx, rnd)

    adv.msa = w.make("agreement", {
        "agreement_number": f"MSA-{w.next_seq('msa'):05d}", "agreement_type": "MSA", "agreement_status": "Active",
        "counterparty_type": "Client", "advertiser_id": adv.id, "supplier_id": None, "parent_agreement_id": None,
        "effective_date": onboard, "signed_date": onboard - timedelta(days=rnd.int(5, 30)),
        "expiry_date": onboard + timedelta(days=365 * 3), "currency_code": "USD",
        "total_committed_value": round(budget * 3, 2), "termination_date": None, "termination_reason": None}, ctx, rnd)
    ctx = w.adv_ctx(adv, onboard, duration=365 * 3)
    for k, clause in enumerate(rnd.sample(CLAUSES, rnd.int(4, len(CLAUSES)))):
        w.make("term", {"agreement_id": adv.msa["agreement_id"], "clause_type": clause, "sequence": k + 1,
                        "clause_title": clause.replace("_", " ").title(), "term_number": f"{k + 1}",
                        "approval_status": "approved", "effective_date": onboard, "sow_id": None,
                        "contract_insertion_order_id": None}, ctx, rnd)
    adv.relationship = w.make("agency_relationship", {
        "advertiser_id": adv.id, "agreement_id": adv.msa["agreement_id"], "relationship_code": f"AR-{w.next_seq('ar'):05d}",
        "relationship_status": "active", "relationship_type": rnd.weighted(["aor", "retainer", "project_based"], [5, 3, 2]),
        "aor_designation": rnd.weighted(["media_aor", "full_service_aor", "digital_aor"], [5, 2, 3]),
        "effective_start_date": onboard, "effective_end_date": None, "fee_currency_code": "USD",
        "estimated_annual_billings": round(budget, 2), "lead_account_director": adv.team[0],
        "primary_supplier_id": None}, ctx, rnd)
    ctx = w.adv_ctx(adv, onboard, duration=365 * 3)
    for person in adv.team:
        title, dept = w.roles[person]
        w.make("account_team", {
            "advertiser_id": adv.id, "assignment_code": f"AT-{w.next_seq('at'):06d}", "assignment_status": "active",
            "start_date": onboard, "end_date": None, "team_function": {"Creative": "creative", "Strategy": "strategy",
                                                                       "Analytics": "analytics"}.get(dept, "media" if "Media" in dept else "account_management"),
            "is_primary_contact": person == adv.team[0], "salesforce_team_member_code": f"005{rnd.int(10**11, 10**12 - 1)}",
            "managed_supplier_id": None}, ctx, rnd)

    adv.rate_card = w.make("contract_rate_card", {
        "agreement_id": adv.msa["agreement_id"], "advertiser_id": adv.id, "rate_card_number": f"RC-{w.next_seq('rc'):06d}",
        "version_number": "1.0", "rate_card_name": f"{name} Agency Services Rates", "rate_card_type": "agency_services",
        "contract_rate_card_status": "active", "pricing_model": "hourly", "unit_of_measure": "hour", "currency_code": "USD",
        "effective_start_date": onboard, "effective_end_date": onboard + timedelta(days=365 * 3),
        "supplier_id": None, "vendor_rate_card_id": None, "ad_channel_id": None, "brand_id": None}, ctx, rnd)
    for k, (svc, role, level, rate) in enumerate(SERVICES):
        w.make("rate_card_line", {
            "contract_rate_card_id": adv.rate_card["contract_rate_card_id"], "line_sequence_number": k + 1,
            "service_type": svc, "role_title": role, "seniority_level": level, "unit_rate": round(rate * rnd.uniform(0.9, 1.1), 2),
            "unit_of_measure": "hour", "line_status": "active", "currency_code": "USD", "effective_start_date": onboard,
            "effective_end_date": onboard + timedelta(days=365 * 3), "ad_channel_id": None, "ad_format_id": None}, ctx, rnd)

    for year in range(max(onboard.year, w.start.year), w.today.year + 1):
        sow_start = max(date(year, 1, 1), onboard)
        sow = w.make("sow", {
            "agreement_id": adv.msa["agreement_id"], "sow_advertiser_id": adv.id, "sow_client_advertiser_id": adv.id,
            "agency_relationship_id": adv.relationship["agency_relationship_id"],
            "contract_rate_card_id": adv.rate_card["contract_rate_card_id"], "sow_number": f"SOW-{year}{w.next_seq('sow'):05d}",
            "version_number": "1.0", "title": f"{name} {year} Media Services", "sow_type": "media_buy",
            "effective_start_date": sow_start, "effective_end_date": date(year, 12, 31),
            "media_budget_amount": round(budget, 2), "agency_fee_amount": round(budget * 0.08, 2),
            "total_contract_value": round(budget * 1.08, 2), "currency_code": "USD", "billing_model": "commission",
            "invoicing_frequency": "monthly", "brand_id": None}, ctx.with_(anchor=sow_start, duration=365), rnd)
        adv.sows[year] = sow
        yctx = w.adv_ctx(adv, sow_start, duration=365)
        for sla_type, sla_name, unit, target in rnd.sample(SLAS, 2):
            w.make("sla", {"agreement_id": adv.msa["agreement_id"], "sow_id": sow["sow_id"], "sla_type": sla_type,
                           "sla_code": f"SLA-{w.next_seq('sla'):05d}", "sla_name": f"{name} {sla_name}",
                           "measurement_unit": unit, "breach_threshold_unit": unit, "target_value": target,
                           "breach_threshold": target * 1.5, "effective_start_date": sow_start,
                           "effective_end_date": date(year, 12, 31), "contract_insertion_order_id": None,
                           "supplier_id": None}, yctx, rnd)
        for q in range(4):
            qs = date(year, q * 3 + 1, 1)
            if qs > w.today + timedelta(days=90):
                break
            target = budget * 0.1 / 4 * rnd.uniform(0.9, 1.15)
            w.make("revenue_target", {
                "advertiser_id": adv.id, "target_code": f"RT-{year}Q{q + 1}{w.next_seq('rt'):05d}",
                "target_name": f"{name} {year} Q{q + 1} fee income", "target_type": "fee_income",
                "target_period_type": "quarterly", "fiscal_year": year, "fiscal_quarter": f"Q{q + 1}",
                "period_start_date": qs, "period_end_date": (qs + timedelta(days=92)).replace(day=1) - timedelta(days=1),
                "target_amount": round(target, 2), "target_amount_usd": round(target, 2),
                "original_target_amount": round(target, 2), "currency_code": "USD", "sow_id": sow["sow_id"],
                "brand_id": None}, yctx.with_(anchor=qs, scale=target), rnd)

    if onboard + timedelta(days=365 * 3) < w.today + timedelta(days=120):
        exp = onboard + timedelta(days=365 * 3)
        w.make("renewal", {"agreement_id": adv.msa["agreement_id"], "renewal_number": f"REN-{w.next_seq('ren'):05d}",
                           "prior_term_start_date": onboard, "prior_term_end_date": exp, "new_term_start_date": exp,
                           "new_term_end_date": exp + timedelta(days=365 * 2), "notice_date": exp - timedelta(days=90),
                           "renewal_status": "renewed" if exp < w.today else "in_negotiation", "outcome": "renewed" if exp < w.today else None,
                           "negotiation_start_date": exp - timedelta(days=90), "negotiation_end_date": exp - timedelta(days=20)},
               ctx.with_(anchor=exp - timedelta(days=90)), rnd)

    adv.attribution_model = w.make("attribution_model", {
        "advertiser_id": adv.id, "model_code": f"AM-{w.next_seq('am'):05d}", "model_name": f"{name} Last Click 30/1",
        "model_type": rnd.weighted(["last_click", "position_based", "data_driven", "linear"], [5, 2, 2, 1]),
        "attribution_model_status": "active", "click_through_window_days": 30, "view_through_window_days": 1,
        "effective_start_date": onboard, "effective_end_date": None,
        "position_based_first_touch_weight": 0.4, "position_based_last_touch_weight": 0.4,
        "position_based_middle_touch_weight": 0.2}, ctx, rnd)
    ctx = w.adv_ctx(adv, onboard)
    for kind in ("conversion_tag", "retargeting_pixel"):
        adv.pixels.append(w.make("tracking_pixel", {
            "advertiser_id": adv.id, "pixel_code": f"PX{w.next_seq('px'):07d}", "pixel_type": kind,
            "pixel_name": f"{name} {'Purchase' if kind == 'conversion_tag' else 'Site Visit'} Tag",
            "deployment_status": "active", "deployment_environment": "web", "implementation_method": "javascript",
            "campaign_id": None, "flight_id": None, "line_item_id": None, "ad_id": None, "media_placement_id": None,
            "deployment_url": f"https://www.{domain}/checkout/confirmation" if kind == "conversion_tag" else f"https://www.{domain}/"},
            ctx, rnd))
    audiences.first_party(w, adv, onboard)
    return adv
