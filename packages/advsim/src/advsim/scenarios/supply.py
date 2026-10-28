"""The supply side (media_ops_db vendor + inventory, plus vendor contracts in crm_db and specs in work_mgmt_db)."""
from __future__ import annotations

from datetime import date

from ..values import pools
from ..world import KINDS, Supply, World

CHANNELS = {  # kind: (code, name, ad_channel.channel_type, pricing)
    "display": ("DISP", "Programmatic Display", "display", "cpm"),
    "video": ("OLV", "Online Video", "video", "cpm"),
    "ctv": ("CTV", "Connected TV", "video", "cpm"),
    "native": ("NATV", "Native", "display", "cpm"),
    "audio": ("AUD", "Digital Audio", "audio", "cpm"),
    "social": ("SOC", "Paid Social", "social", "cpm"),
    "dooh": ("DOOH", "Digital Out-of-Home", "display", "cpm"),
}
FORMATS = {  # kind: [(code, name, category, width, height, seconds)]
    "display": [("D300250", "Medium Rectangle 300x250", "display", 300, 250, None),
                ("D72890", "Leaderboard 728x90", "display", 728, 90, None),
                ("D160600", "Wide Skyscraper 160x600", "display", 160, 600, None),
                ("D32050", "Mobile Banner 320x50", "display", 320, 50, None),
                ("D300600", "Half Page 300x600", "rich_media", 300, 600, None)],
    "video": [("V15PRE", "15s In-Stream Pre-roll", "video", 1280, 720, 15),
              ("V30PRE", "30s In-Stream Pre-roll", "video", 1280, 720, 30),
              ("V06BMP", "6s Bumper", "video", 1280, 720, 6)],
    "ctv": [("CTV15", "15s CTV Spot", "video", 1920, 1080, 15), ("CTV30", "30s CTV Spot", "video", 1920, 1080, 30)],
    "native": [("NINF", "Native In-Feed", "native", 1200, 627, None), ("NSPA", "Sponsored Article", "native", 1200, 627, None)],
    "audio": [("AUD30", "30s Audio Spot", "audio", None, None, 30), ("AUD15", "15s Audio Spot", "audio", None, None, 15)],
    "social": [("SFV", "Social Feed Video", "video", 1080, 1350, 15), ("SSTY", "Social Story", "video", 1080, 1920, 10)],
    "dooh": [("DOOH1080", "DOOH Landscape Screen", "display", 1920, 1080, 10)],
}
PUBLISHER_STYLES = [  # (suffix, publisher_type, kinds, property_type)
    ("Media", "digital", ["display", "native", "video"], "website"),
    ("Digital", "digital", ["display", "native"], "website"),
    ("Streaming", "ctv_ott", ["ctv", "video"], "ctv_app"),
    ("Audio Network", "digital", ["audio"], "mobile_app"),
    ("Social", "digital", ["social"], "mobile_app"),
    ("Outdoor", "dooh_network", ["dooh"], "website"),
    ("Publishing", "digital", ["display", "video"], "website"),
]
TECH = [("DSP", "dsp", "buyer"), ("Exchange", "ssp", "seller"), ("Ad Server", "ad_network", "intermediary"),
        ("Verify", "ad_network", "measurement"), ("Data Cloud", "ad_network", "data_provider")]


def build(w: World) -> None:
    rnd = w.rnd.child("supply")
    since = date(w.start.year - 2, 1, 1)
    ctx = w.ctx(since, duration=365 * 4, scale=250_000)

    for kind, (code, name, ctype, pricing) in CHANNELS.items():
        w.channels[kind] = w.make("ad_channel", {
            "channel_code": code, "channel_name": name, "channel_status": "active", "channel_type": ctype,
            "pricing_model": pricing, "currency_code": "USD", "effective_date": since, "expiration_date": None,
            "gl_account_id": w.gl["5100" if kind in ("video", "ctv") else "5000"]["gl_account_id"]}, ctx, rnd)
        w.formats[kind] = []
        for fcode, fname, cat, wd, ht, secs in FORMATS[kind]:
            fmt = w.make("ad_format", {
                "format_code": fcode, "format_name": fname, "format_category": cat, "format_status": "active",
                "width_pixels": wd, "height_pixels": ht, "duration_seconds": secs,
                "aspect_ratio": f"{wd}:{ht}" if wd else None, "effective_date": since, "deprecation_date": None,
                "retirement_date": None, "is_native_format": kind == "native"}, ctx, rnd)
            w.formats[kind].append(fmt)
            w.specs[fmt["ad_format_id"]] = w.make("spec", {
                "spec_code": f"SPEC-{fcode}", "spec_name": f"{fname} creative spec", "spec_status": "active",
                "ad_format_id": fmt["ad_format_id"], "publisher_id": None}, ctx, rnd)

    for i in range(int(w.cfg.get_path("supply.publishers", 18))):
        add_publisher(w, rnd, i)
    for i in range(int(w.cfg.get_path("supply.tech_partners", 8))):
        add_tech(w, rnd, i)
    for _ in range(int(w.cfg.get_path("supply.production_vendors", 5))):
        add_supplier(w, rnd, company(w, rnd, rnd.choice(["Studios", "Productions", "Creative Works", "Post"])),
                     "production", None, "digital", [])
    for _ in range(int(w.cfg.get_path("supply.data_suppliers", 3))):
        add_supplier(w, rnd, company(w, rnd, rnd.choice(["Data", "Insights", "Analytics"])), "research", None, "digital", [])


def supply_ctx(w: World):
    since = date(w.start.year - 2, 1, 1)
    return since, w.ctx(since, duration=365 * 4, scale=250_000)


def company(w: World, rnd, suffix: str) -> str:
    taken = {s.supplier.get("trading_name") for s in w.supply}
    while True:
        n = f"{rnd.fake.last_name()} {suffix}"
        if n not in taken:
            return n


def add_supplier(w: World, rnd, name: str, vendor_type: str, platform: str | None, channel: str, kinds: list[str]) -> Supply:
    since, ctx = supply_ctx(w)
    domain = name.lower().replace(" ", "") + ".com"
    onboard = w.today if w.fill.live else rnd.date_between(since, date(w.start.year, 3, 1))
    sctx = ctx.with_(label=name, domain=domain, anchor=onboard)
    row = w.make("supplier", {
        "legal_name": f"{name} LLC", "trading_name": name, "vendor_type": vendor_type,
        "platform_type": platform, "media_channel": channel, "onboarding_status": "active", "onboarding_date": onboard,
        "currency_code": "USD", "country_code": "USA", "contract_expiry_date": None}, sctx, rnd)
    sup = Supply(row, {"publisher": "publisher", "tech_platform": "tech", "production": "production"}.get(
        vendor_type, "data"), channel_kinds=kinds)
    agreement_type = {"publisher": "Vendor Media Supply", "tech_platform": "Technology License",
                      "production": "Production Services"}.get(vendor_type, "Vendor Media Supply")
    sup.agreement = w.make("agreement", {
        "agreement_number": f"VA-{w.next_seq('vendor_agreement'):05d}", "agreement_type": agreement_type,
        "agreement_status": "Active", "counterparty_type": "Vendor", "supplier_id": row["supplier_id"],
        "advertiser_id": None, "parent_agreement_id": None, "currency_code": "USD",
        "effective_date": onboard, "expiry_date": date(w.today.year + 1, 12, 31),
        "termination_date": None, "termination_reason": None}, sctx, rnd)
    w.supply.append(sup)
    return sup


def add_publisher(w: World, rnd, i: int) -> Supply:
    _, ctx = supply_ctx(w)
    suffix, ptype, kinds, prop_type = PUBLISHER_STYLES[i % len(PUBLISHER_STYLES)]
    name = company(w, rnd, suffix)
    sup = add_supplier(w, rnd, name, "publisher", "publisher_direct",
                       "ctv_ott" if "ctv" in kinds else "dooh" if "dooh" in kinds else "digital", kinds)
    domain = name.lower().replace(" ", "") + ".com"
    pctx = ctx.with_(label=name, domain=domain, anchor=sup.supplier["onboarding_date"],
                     entities={"supplier": sup.supplier["supplier_id"]})
    accreditation = w.make("accreditation", {"supplier_id": sup.supplier["supplier_id"],
                                             "accreditation_status": "active"}, pctx, rnd)
    base_cpm = rnd.uniform(4, 12) * (3 if "ctv" in kinds else 1)
    sup.publisher = w.make("publisher", {
        "supplier_id": sup.supplier["supplier_id"], "publisher_type": ptype, "accreditation_id": accreditation["accreditation_id"],
        "parent_publisher_id": None, "inventory_type": {"ctv": "video", "audio": "audio", "dooh": "ooh",
                                                         "social": "video", "native": "native"}.get(kinds[0], "display"),
        "base_cpm_rate": round(base_cpm, 2), "programmatic_enabled": True, "website_url": f"https://www.{domain}",
        "rate_currency_code": "USD"}, pctx, rnd)
    pctx = pctx.with_(entities={"publisher": sup.publisher["publisher_id"]})
    for j in range(rnd.int(*w.cfg.get_path("supply.properties_per_publisher", [1, 4]))):
        kind = kinds[j % len(kinds)]
        site = f"{rnd.choice(pools.SITE_TOPICS)}{rnd.choice(pools.SITE_WORDS)}"
        prop = w.make("publisher_property", {
            "property_code": f"PP{w.next_seq('property'):05d}", "property_name": f"{site.title()} ({name})",
            "property_status": "active", "property_type": prop_type, "ad_channel_id": w.channels[kind]["ad_channel_id"],
            "property_url": f"https://www.{site}.com", "currency_code": "USD", "country_code": "USA",
            "average_cpm": round(base_cpm * rnd.uniform(0.8, 1.3), 2), "floor_cpm": round(base_cpm * 0.6, 2),
            "programmatic_enabled": True}, pctx.with_(domain=f"{site}.com"), rnd)
        prop["_kind"] = kind
        prop["_domain"] = f"{site}.com"
        sup.properties.append(prop)
        for k in range(rnd.int(*w.cfg.get_path("supply.placements_per_property", [2, 5]))):
            fmt = rnd.choice(w.formats[kind])
            pl = w.make("placement", {
                "placement_code": f"PL{w.next_seq('placement'):06d}",
                "placement_name": f"{site.title()} {fmt['format_name']} #{k + 1}",
                "ad_channel_id": w.channels[kind]["ad_channel_id"], "publisher_property_id": prop["publisher_property_id"],
                "ad_format_id": fmt["ad_format_id"], "placement_status": "active",
                "cpm_floor_price": round(base_cpm * 0.6, 2), "floor_price_currency_code": "USD"}, pctx, rnd)
            pl["_kind"] = kind
            sup.placements.append(pl)
    year = w.today.year if w.fill.live else w.start.year
    sup.rate_card = w.make("vendor_rate_card", {
        "supplier_id": sup.supplier["supplier_id"], "advertiser_id": None,
        "rate_card_number": f"RC-V{w.next_seq('vrc'):05d}", "version": "v1.0",
        "rate_card_name": f"{name} {year} Rate Card", "rate_card_status": "active",
        "pricing_model": "cpm", "rate_unit": "per_mille", "base_rate": round(base_cpm, 2), "currency_code": "USD",
        "effective_start_date": date(year, 1, 1), "effective_end_date": date(year, 12, 31),
        "source_system_rate_card_vendor_rate_card_id": None}, pctx, rnd)
    return sup


def add_tech(w: World, rnd, i: int) -> Supply:
    _, ctx = supply_ctx(w)
    label, platform, role = TECH[i % len(TECH)]
    taken = {s.supplier.get("trading_name") for s in w.supply}
    name = f"{rnd.choice(pools.PRODUCT_WORDS)} {label}"
    while name in taken:
        name = f"{rnd.choice(pools.PRODUCT_WORDS)}{rnd.choice(pools.PRODUCT_WORDS).lower()} {label}"
    sup = add_supplier(w, rnd, name, "tech_platform", platform, "digital", list(KINDS))
    sup.tech = w.make("tech_partner", {
        "supplier_id": sup.supplier["supplier_id"], "platform_type": platform, "supply_chain_role": role,
        "contract_start_date": date(w.start.year - 1, 1, 1), "contract_end_date": date(w.today.year + 1, 12, 31),
        "fee_currency_code": "USD"}, ctx.with_(label=name), rnd)
    sup.tech["_label"] = label
    return sup


def publishers_for(w: World, kind: str) -> list[Supply]:
    return [s for s in w.supply if s.kind == "publisher" and any(p["_kind"] == kind for p in s.properties)]


def tech(w: World, label: str) -> Supply | None:
    cands = [s for s in w.supply if s.tech and s.tech["_label"] == label]
    return w.rnd.choice(cands) if cands else None
