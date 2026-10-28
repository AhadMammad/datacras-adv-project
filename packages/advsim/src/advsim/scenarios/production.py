"""Project delivery and creative production for one campaign (work_mgmt_db).

client brief -> initiative -> work packages -> tasks -> assignments -> time entries
creative brief -> concept -> production job -> deliverables -> assets -> versions -> proofs
"""
from __future__ import annotations

from datetime import date, timedelta

from ..world import Campaign, World, money

WORK_PACKAGES = [  # (name, department, share of project span (start, end), tasks)
    ("Strategy & Planning", "Strategy", (0.0, 0.25), ["Audience research", "Channel strategy", "Media plan draft", "Client plan review"]),
    ("Creative Development", "Creative", (0.1, 0.45), ["Concept development", "Copywriting", "Design production", "Client creative review"]),
    ("Media Activation", "Ad Operations", (0.35, 0.55), ["Trafficking setup", "Tag QA", "Launch checks"]),
    ("Optimization & Reporting", "Analytics", (0.5, 1.0), ["Weekly optimization", "Mid-flight report", "Wrap report"]),
]
ASSET_TYPE = {"display": "image", "native": "image", "video": "video", "ctv": "video", "social": "video",
              "audio": "audio", "dooh": "image"}


def for_campaign(w: World, camp: Campaign, brief: dict, brief_date: date, kinds: list[str], ctx) -> dict[str, list[dict]]:
    """Create the project and creative work; returns approved assets per channel kind."""
    rnd = w.rnd
    span_start, span_end = brief_date, camp.end + timedelta(days=14)
    span = max(1, (span_end - span_start).days)

    def at(frac: float) -> date:
        return span_start + timedelta(days=int(span * frac))

    year = camp.start.year
    init = w.make("initiative", {
        "project_code": f"PRJ{year}{w.next_seq('prj'):05d}", "initiative_name": f"{camp.row['campaign_name']} Delivery",
        "start_date": span_start, "end_date": span_end, "parent_initiative_id": None,
        "initiative_status": {"future": "planning", "current": "in_flight", "past": "completed"}[phase(w, span_start, span_end)]
        if camp.status != "cancelled" else "cancelled"}, ctx.with_(anchor=span_start, duration=span), rnd)
    camp.initiative = init
    ctx = ctx.with_(entities={"initiative": init["initiative_id"]})
    pbrief = w.make("project_brief", {"title": f"{camp.row['campaign_name']} project brief", "client_brief_id": brief["client_brief_id"],
                                      "planned_start_date": span_start, "planned_end_date": span_end,
                                      "superseded_project_brief_id": None}, ctx.with_(anchor=brief_date), rnd)
    ctx = ctx.with_(entities={"project_brief": pbrief["project_brief_id"]})
    fee = camp.budget * rnd.uniform(0.06, 0.1)
    w.make("project_budget", {"total_approved_budget": money(fee), "currency_code": "USD",
                              "effective_start_date": span_start, "effective_end_date": span_end,
                              "revised_from_project_budget_id": None, "work_package_id": None}, ctx.with_(scale=fee), rnd)

    rate = 175.0
    for i, (wp_name, dept, (fs, fe), tasks) in enumerate(WORK_PACKAGES):
        ws, we = at(fs), at(fe)
        wp = w.make("work_package", {
            "work_package_name": wp_name, "wbs_code": f"{i + 1}", "parent_work_package_id": None,
            "planned_start_date": ws, "planned_end_date": we, "actual_start_date": ws if ws <= w.today else None,
            "actual_end_date": we if we < w.today else None,
            "work_package_status": status_by_dates(w, "work_package", ws, we, camp)}, ctx.with_(anchor=ws, scale=fee / 4), rnd)
        wctx = ctx.with_(entities={"work_package": wp["work_package_id"]})
        w.make("milestone", {"milestone_name": f"{wp_name} complete", "work_package_id": wp["work_package_id"],
                             "replanned_from_project_milestone_id": None,
                             "project_milestone_status": status_by_dates(w, "milestone", we, we, camp)},
               wctx.with_(anchor=we), rnd)
        rplan = w.make("resource_plan", {"planning_period_start_date": ws, "planning_period_end_date": we,
                                         "revised_from_resource_plan_id": None}, wctx.with_(anchor=ws), rnd)
        prev = None
        for k, tname in enumerate(tasks):
            ts = ws + timedelta(days=int((we - ws).days * k / len(tasks)))
            te = max(ts + timedelta(days=2), ws + timedelta(days=int((we - ws).days * (k + 1) / len(tasks))))
            task = w.make("task", {
                "task_name": tname, "work_package_id": wp["work_package_id"], "parent_task_id": None,
                "primary_predecessor_task_id": prev, "planned_start_date": ts, "planned_end_date": te,
                "actual_start_date": ts if ts <= w.today else None, "actual_end_date": te if te < w.today else None,
                "task_status": status_by_dates(w, "task", ts, te, camp)}, wctx.with_(anchor=ts, duration=(te - ts).days), rnd)
            prev = task["task_id"]
            tctx = wctx.with_(entities={"task": task["task_id"]})
            for person in rnd.sample([w.pick_person(dept)] + camp.adv.team, rnd.int(1, 2)):
                asg = w.make("assignment", {
                    "task_id": task["task_id"], "resource_plan_id": rplan["resource_plan_id"],
                    "reassigned_from_project_assignment_id": None, "start_date": ts, "end_date": te,
                    "assignment_status": "completed" if te < w.today else "active"}, tctx.with_(anchor=ts, people=(person,)), rnd)
                d = ts
                while d <= min(te, w.today):
                    hours = rnd.weighted([2, 4, 6, 8, 12, 16], [2, 4, 3, 3, 2, 1])
                    w.make("time_entry", {
                        "task_id": task["task_id"], "assignment_id": asg["assignment_id"], "entry_date": d,
                        "hours_logged": hours, "adjusted_time_entry_id": None,
                        "approval_status": w.status("time_entry", d, d + timedelta(days=7))},
                        tctx.with_(anchor=d, people=(person,), scale=hours * rate), rnd)
                    d += timedelta(days=7)
        w.make("deliverable_tracker", {"deliverable_name": f"{wp_name} sign-off", "milestone_id": None,
                                       "revision_of_deliverable_tracker_id": None,
                                       "deliverable_status": deliverable_status(w, we, camp)}, wctx.with_(anchor=we), rnd)

    # creative
    cb_date = at(0.08)
    guideline = w.reg.pick("brand_guideline", rnd, where=lambda r: r["brand_id"] == camp.brand["brand_id"])
    cbrief = w.make("creative_brief", {
        "brief_number": f"CB-{w.next_seq('cb'):08d}", "brief_name": f"{camp.row['campaign_name']} creative brief",
        "brand_id": camp.brand["brand_id"], "campaign_id": camp.id,
        "brand_guideline_id": guideline["brand_guideline_id"] if guideline else None,
        "creative_brief_status": {"future": "approved", "current": "in_production", "past": "completed"}[phase(w, cb_date, camp.start)]},
        ctx.with_(anchor=cb_date), rnd)
    camp.creative_brief = cbrief
    cctx = ctx.with_(entities={"creative_brief": cbrief["creative_brief_id"]})
    concept = w.make("concept", {"concept_code": f"CON-{w.next_seq('con'):06d}", "title": f"{camp.brand['brand_name']}: {rnd.fake.catch_phrase()}",
                                 "parent_concept_id": None, "concept_status": "approved" if cb_date + timedelta(days=10) <= w.today else "in_review"},
                       cctx.with_(anchor=cb_date + timedelta(days=5)), rnd)
    vendor = rnd.choice([s for s in w.supply if s.kind == "production"] or w.supply)
    job_start = cb_date + timedelta(days=7)
    job = w.make("production_job", {
        "job_number": f"PJ-{w.next_seq('pj'):06d}", "job_name": f"{camp.row['campaign_name']} production",
        "concept_id": concept["concept_id"], "supplier_id": vendor.supplier["supplier_id"],
        "job_status": job_status(w, job_start, camp.start), "primary_production_initiative_id": init["initiative_id"]},
        cctx.with_(anchor=job_start, scale=camp.budget * 0.04), rnd)
    jctx = cctx.with_(entities={"production_job": job["production_job_id"], "concept": concept["concept_id"]})
    assets: dict[str, list[dict]] = {}
    for kind in kinds:
        for fmt in rnd.sample(w.formats[kind], min(2, len(w.formats[kind]))):
            spec = w.specs[fmt["ad_format_id"]]
            ready = camp.start - timedelta(days=rnd.int(3, 10))
            dctx = jctx.with_(anchor=ready, entities={"spec": spec["spec_id"]})
            deliv = w.make("creative_deliverable", {
                "deliverable_code": f"CD-{w.next_seq('cd'):06d}", "deliverable_name": f"{camp.brand['brand_name']} {fmt['format_name']}",
                "ad_format_id": fmt["ad_format_id"], "asset_id": None,
                "deliverable_status": "delivered" if ready <= w.today else "in_production"}, dctx, rnd)
            asset = w.make("asset", {
                "asset_name": f"{camp.brand['brand_name']}_{fmt['format_code']}_{camp.start:%Y%m}", "asset_type": ASSET_TYPE[kind],
                "dam_asset_ref": f"DAM-{w.next_seq('dam'):08d}", "parent_asset_creative_asset_id": None,
                "advertiser_id": camp.adv.id, "brand_id": camp.brand["brand_id"]}, dctx, rnd)
            deliv["asset_id"] = asset["asset_id"]
            asset["_kind"] = kind
            asset["_format"] = fmt
            assets.setdefault(kind, []).append(asset)
            versions = rnd.int(1, 3)
            for v in range(1, versions + 1):
                vdate = ready - timedelta(days=(versions - v) * 3 + 2)
                final = v == versions
                ver = w.make("asset_version", {
                    "asset_id": asset["asset_id"], "version_number": v, "creative_deliverable_id": deliv["creative_deliverable_id"],
                    "version_status": ("approved" if final else "superseded") if vdate <= w.today else "in_review"},
                    dctx.with_(anchor=vdate), rnd)
                w.make("proof", {
                    "asset_version_id": ver["asset_version_id"], "proof_number": f"PRF-{w.next_seq('prf'):08d}",
                    "proof_name": f"{asset['asset_name']} v{v} proof", "creative_deliverable_id": deliv["creative_deliverable_id"],
                    "proof_status": ("approved" if final else "rejected") if vdate <= w.today else "in_review"},
                    dctx.with_(anchor=vdate), rnd)
    return assets


def phase(w: World, start: date, end: date) -> str:
    from ..lifecycle import phase_of
    return phase_of(start, end, w.today)


def status_by_dates(w: World, table: str, start: date, end: date, camp: Campaign) -> str:
    if camp.status == "cancelled" and end >= camp.start:
        values = w.s.code_values(table, w.s.status_col[table])
        return "cancelled" if "cancelled" in values else values[-1]
    return w.status(table, start, end)


def deliverable_status(w: World, due: date, camp: Campaign) -> str:
    if camp.status == "cancelled":
        return "cancelled"
    return "accepted" if due < w.today else "in_production" if due - timedelta(days=30) < w.today else "not_started"


def job_status(w: World, start: date, due: date) -> str:
    if due < w.today:
        return "delivered"
    if start > w.today:
        return "briefed"
    return w.rnd.weighted(["in-production", "internal-review", "client-review", "revisions", "approved"], [4, 2, 2, 1, 2])
