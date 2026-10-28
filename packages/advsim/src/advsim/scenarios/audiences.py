"""Audience data (cdp_db): taxonomy, shared third-party segments, profiles, personas, memberships."""
from __future__ import annotations

import hashlib
from datetime import date, timedelta

from ..world import Advertiser, World

TAXONOMY = {  # root: (data_type, children)
    "Demographic": ("demographic", ["Age 18-34", "Age 35-54", "Parents", "High Income Households", "Homeowners"]),
    "Interest": ("behavioral", ["Sports", "Travel", "Food & Dining", "Technology", "Fashion", "Fitness", "Gaming"]),
    "In-Market": ("behavioral", ["Auto Intenders", "Home Buyers", "Credit Card Seekers", "Vacation Planners",
                                 "Mobile Upgraders", "Grocery Shoppers"]),
    "Contextual": ("contextual", ["News Readers", "Streaming Viewers", "Podcast Listeners", "Recipe Browsers"]),
}
PERSONAS = ["Busy Suburban Parent", "Urban Young Professional", "Value-Seeking Shopper", "Tech Early Adopter",
            "Health-Conscious Millennial", "Weekend Adventurer", "Affluent Empty Nester", "Gen Z Gamer",
            "Small Business Owner", "Frequent Business Traveler", "Home Improvement Enthusiast", "Sports Superfan"]
ID_TYPES = ["hashed_email", "maid", "cookie_id", "device_id", "customer_id"]


def build(w: World) -> None:
    rnd = w.rnd.child("audiences")
    since = date(w.start.year - 1, 1, 1)
    ctx = w.ctx(since, duration=365 * 3, scale=40_000)
    data_suppliers = [s for s in w.supply if s.kind == "data"]

    leaves = []
    for i, (root, (dtype, children)) in enumerate(TAXONOMY.items()):
        r = w.make("taxonomy", {
            "taxonomy_code": f"T{i + 1:02d}", "category_name": root, "data_type": dtype, "taxonomy_level": 1,
            "path": root, "parent_taxonomy_id": None, "primary_replacement_taxonomy_id": None, "is_active": True,
            "effective_start_date": since, "effective_end_date": None}, ctx, rnd)
        w.taxonomy.append(r)
        for j, child in enumerate(children):
            leaf = w.make("taxonomy", {
                "taxonomy_code": f"T{i + 1:02d}_{j + 1:02d}", "category_name": child, "data_type": dtype,
                "taxonomy_level": 2, "path": f"{root} > {child}", "parent_taxonomy_id": r["taxonomy_id"],
                "primary_replacement_taxonomy_id": None, "is_active": True,
                "effective_start_date": since, "effective_end_date": None}, ctx, rnd)
            leaf["_dtype"] = dtype
            w.taxonomy.append(leaf)
            leaves.append(leaf)

    n = int(w.cfg.get_path("audiences.segments", 40))
    for i in range(n):
        leaf = leaves[i % len(leaves)]
        name = leaf["category_name"] if i < len(leaves) else f"{leaf['category_name']} - {rnd.choice(['Lookalike', 'High Propensity', 'Recent', 'Engaged'])} {i // len(leaves)}"
        sup = rnd.choice(data_suppliers) if data_suppliers else None
        seg = w.make("segment", {
            "audience_segment_name": name, "audience_segment_status": "active", "taxonomy_id": leaf["taxonomy_id"],
            "audience_segment_type": {"demographic": "demographic", "contextual": "contextual"}.get(leaf["_dtype"], "behavioral"),
            "data_source_tier": "third_party", "data_supplier_id": sup.supplier["supplier_id"] if sup else None,
            "size": int(rnd.lognormal(2_500_000, 0.9)), "master_agreement_id": sup.agreement["agreement_id"] if sup else None,
            "expiry_date": None}, ctx.with_(entities={"supplier": sup.supplier["supplier_id"] if sup else None}), rnd)
        w.segments.append(seg)
        members(w, seg, rnd)

    for seg in rnd.sample(w.segments, min(len(w.segments), 12)):
        tax = w.reg.get(seg["taxonomy_id"])
        if tax.get("_dtype") == "demographic":
            w.make("demographic_profile", {
                "profile_code": f"DP{w.next_seq('dp'):04d}", "profile_name": f"{seg['audience_segment_name']} Profile",
                "primary_demographic_audience_segment_id": seg["segment_id"], "taxonomy_id": seg["taxonomy_id"],
                "country_code": "USA"}, ctx, rnd)
        else:
            w.make("behavioral_profile", {
                "profile_name": f"{seg['audience_segment_name']} Behaviour", "profile_status": "active",
                "primary_behavioral_audience_segment_id": seg["segment_id"], "primary_taxonomy_id": seg["taxonomy_id"],
                "tertiary_behavioral_lookalike_seed_segment_audience_segment_id": None}, ctx, rnd)

    for i in range(int(w.cfg.get_path("audiences.personas", 12))):
        seg = rnd.choice(w.segments)
        w.personas.append(w.make("persona", {
            "persona_code": f"PERSONA_{i + 1:03d}", "persona_name": PERSONAS[i % len(PERSONAS)] + ("" if i < len(PERSONAS) else f" {i // len(PERSONAS) + 1}"),
            "persona_status": "active", "primary_audience_segment_id": seg["segment_id"],
            "taxonomy_id": seg["taxonomy_id"], "brand_id": None}, ctx, rnd))


def members(w: World, seg: dict, rnd) -> None:
    lo, hi = w.cfg.get_path("audiences.members_per_segment", [20, 60])
    ctx = w.ctx(w.start, duration=180)
    for _ in range(rnd.int(lo, hi)):
        idt = rnd.weighted(ID_TYPES, [4, 3, 2, 1, 1])
        start = rnd.date_between(w.start - timedelta(days=200), w.today)
        w.make("segment_membership", {
            "segment_id": seg["segment_id"], "identifier_type": idt,
            "audience_identifier": hashlib.sha256(f"{idt}:{rnd.r.getrandbits(48)}".encode()).hexdigest(),
            "membership_status": "active" if start > w.today - timedelta(days=180) else rnd.weighted(
                ["active", "expired", "suppressed"], [6, 3, 1]),
            "membership_start_date": start, "membership_expiry_date": start + timedelta(days=180)},
            ctx.with_(anchor=start), rnd)


def first_party(w: World, adv: Advertiser, anchor: date) -> None:
    """Customer and site-visitor segments plus a suppression list for one advertiser."""
    rnd = w.rnd
    ctx = w.adv_ctx(adv, anchor, scale=20_000)
    tax = next(t for t in w.taxonomy if t["category_name"] == "In-Market")
    for label in ("Customers", "Site Visitors (30d)"):
        seg = w.make("segment", {
            "audience_segment_name": f"{adv.label} {label}", "audience_segment_status": "active",
            "taxonomy_id": tax["taxonomy_id"], "audience_segment_type": "behavioral", "data_source_tier": "first_party",
            "creation_method": "rules_based" if label == "Customers" else "imported", "data_supplier_id": None,
            "size": int(rnd.lognormal(400_000, 0.8)), "expiry_date": None}, ctx, rnd)
        adv.segments.append(seg)
        members(w, seg, rnd)
    adv.suppression = w.make("suppression_list", {
        "list_code": f"SUP-{w.next_seq('suppression'):05d}", "list_name": f"{adv.label} Existing Customers",
        "list_status": "active", "segment_id": adv.segments[0]["segment_id"], "suppression_type": "converted_customer",
        "scope_level": "advertiser", "campaign_id": None, "flight_id": None, "brand_id": None,
        "effective_start_date": anchor, "effective_end_date": None, "archive_date": None}, ctx, rnd)
