"""Money flow (erp_db), derived from planned delivery: client billing, vendor invoices, payables,
payments, reconciliations and vendor scorecards."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from ..world import Campaign, LineItem, World, money, month_end
from .org import COMPANY

TERMS_DAYS = {"net_15": 15, "net_30": 30, "net_45": 45, "net_60": 60, "prepaid": 0}


def build(w: World) -> None:
    rnd = w.rnd.child("finance")
    for camp in w.campaigns:
        media_month(w, camp, rnd)
    retainers(w, rnd)
    evaluations(w, rnd)


def months_with_delivery(li: LineItem) -> dict[date, list]:
    out = defaultdict(list)
    for d, day in li.daily.items():
        out[d.replace(day=1)].append(day)
    return out


def media_month(w: World, camp: Campaign, rnd) -> None:
    lag = w.cfg.get_path("finance.invoice_lag_days", [2, 6])
    adv = camp.adv
    terms = adv.row.get("credit_terms") or "net_30"
    by_month: dict[date, list[tuple[LineItem, list]]] = defaultdict(list)
    for li in camp.line_items:
        for m, days in months_with_delivery(li).items():
            by_month[m].append((li, days))
    for m, items in sorted(by_month.items()):
        me = month_end(m)
        inv_date = me + timedelta(days=rnd.int(*lag))
        if inv_date > w.today:
            continue
        ctx = w.adv_ctx(adv, inv_date, entities={"campaign": camp.id, "brand": camp.brand["brand_id"],
                                                 "contract_insertion_order": camp.client_io["contract_insertion_order_id"],
                                                 "plan": camp.plan["plan_id"]})
        subtotal = sum(sum(d.spend for d in days) for _, days in items)
        client_invoice(w, camp, m, me, inv_date, subtotal, items, terms, ctx, rnd)
        vendor_side(w, camp, m, me, inv_date, items, ctx, rnd)


def client_invoice(w: World, camp: Campaign, m: date, me: date, inv_date: date, subtotal: float, items, terms: str,
                   ctx, rnd) -> None:
    due = inv_date + timedelta(days=TERMS_DAYS.get(terms, 30))
    pay_lag = rnd.int(*w.cfg.get_path("finance.payment_lag_days", [25, 65]))
    paid_on = inv_date + timedelta(days=pay_lag)
    disputed = rnd.chance(float(w.cfg.get_path("finance.dispute_rate", 0.06)))
    paid = paid_on <= w.today and not disputed
    status = "paid" if paid else "disputed" if disputed else "overdue" if due < w.today else "sent"
    cc = w.cost_centers.get("Media Buying") or w.cost_centers["root"]
    inv = w.make("client_invoice", {
        "invoice_number": f"INV-{inv_date.year}{w.next_seq('inv'):06d}", "invoice_date": inv_date, "due_date": due,
        "billing_period_start_date": m, "billing_period_end_date": me, "invoice_type": "media", "invoice_status": status,
        "currency_code": "USD", "subtotal_amount": money(subtotal), "tax_amount": 0.0, "discount_amount": 0.0,
        "adjustment_amount": None, "total_amount": money(subtotal), "amount_paid": money(subtotal) if paid else 0.0,
        "amount_outstanding": 0.0 if paid else money(subtotal), "payment_terms": terms if terms in w.s.code_values("client_invoice", "payment_terms") else "net_30",
        "payment_received_date": paid_on if paid else None, "cost_center_id": cc["cost_center_id"],
        "sent_timestamp": rnd.ts_on(inv_date), "dispute_date": inv_date + timedelta(days=rnd.int(5, 20)) if disputed else None,
        "dispute_reason": "Delivery discrepancy against client ad server report" if disputed else None,
        "revenue_recognition_date": me, "buy_id": None, "delivery_pacing_id": None, "milestone_id": None,
        "performance_kpi_target_id": None, "_created": rnd.ts_on(inv_date)}, ctx.with_(scale=subtotal), rnd)
    ictx = ctx.with_(entities={"client_invoice": inv["client_invoice_id"]})
    for n, (li, days) in enumerate(items, start=1):
        spend = sum(d.spend for d in days)
        imps = sum(d.impressions for d in days)
        w.make("invoice_line", {
            "client_invoice_id": inv["client_invoice_id"], "line_number": n, "billing_status": "billed",
            "service_category": "media_cost", "service_description": li.row["line_item_name"], "unit_of_measure": "cpm",
            "quantity": round(imps / 1000, 4), "unit_rate": round(li.cpm, 4), "line_amount": money(spend),
            "line_total": money(spend), "commission_percentage": 15, "commission_amount": money(spend * 0.15),
            "discount_amount": 0.0, "discount_percentage": 0, "tax_amount": 0.0, "currency_code": "USD",
            "service_start_date": max(m, li.start), "service_end_date": min(me, li.end), "budget_line_id": li.budget_line["budget_line_id"],
            "buy_id": li.buy["buy_id"], "io_line_id": li.io_line["io_line_id"], "media_insertion_order_id": li.io["media_insertion_order_id"],
            "media_placement_id": li.placement["media_placement_id"], "plan_line_id": li.plan_line["plan_line_id"],
            "programmatic_deal_id": li.deal["programmatic_deal_id"] if li.deal else None,
            "dispute_flag": disputed, "delivery_confirmed_flag": True, "delivery_confirmation_date": me,
            "revenue_recognition_category": "recognized", "revenue_recognition_date": me, "click_event_id": None,
            "viewability_measurement_id": None, "delivery_pacing_id": None, "reconciliation_id": None,
            "revenue_recognition_id": None}, ictx.with_(scale=spend), rnd)
    w.make("revenue_recognition", {
        "client_invoice_id": inv["client_invoice_id"], "revenue_type": "commission", "recognition_method": "point_in_time",
        "recognition_status": "completed", "recognition_start_date": m, "recognition_end_date": me,
        "total_contract_value": money(subtotal), "recognized_amount_to_date": money(subtotal * 0.15),
        "deferred_revenue_amount": 0.0, "unbilled_revenue_amount": 0.0, "percentage_complete": 100,
        "currency_code": "USD", "fiscal_year": me.year, "fiscal_period": me.month, "fiscal_quarter": (me.month - 1) // 3 + 1,
        "gl_account_id": w.gl["4200"]["gl_account_id"], "sap_fi_posting_date": me, "is_active": False,
        "delivery_pacing_id": None, "milestone_id": None, "performance_kpi_target_id": None}, ictx.with_(scale=subtotal * 0.15), rnd)
    if paid:
        payment(w, "inbound", subtotal, paid_on, ctx, rnd, client_invoice_id=inv["client_invoice_id"],
                payer_name=camp.adv.row["legal_entity_name"], payee_name="Agency Holdings US")


def vendor_side(w: World, camp: Campaign, m: date, me: date, inv_date: date, items, ctx, rnd) -> None:
    sigma = float(w.cfg.get_path("finance.vendor_variance_sigma", 0.025))
    by_sup: dict = defaultdict(list)
    for li, days in items:
        by_sup[li.supply.supplier["supplier_id"]].append((li, days))
    for sid, lis in by_sup.items():
        sup = lis[0][0].supply
        delivered = sum(sum(d.spend for d in days) for _, days in lis)
        if delivered <= 0:
            continue
        variance = rnd.normal(0, sigma)
        gross = delivered * (1 + variance)
        received = inv_date if w.fill.live else inv_date + timedelta(days=rnd.int(3, 15))
        if received > w.today:
            continue
        io = lis[0][0].io
        net = gross * 0.85
        tol = 2.0
        within = abs(variance) * 100 <= tol
        age = (w.today - received).days
        pay_due = received + timedelta(days=45)
        paid = age > rnd.int(30, 60) and within or age > 75
        vstatus = "paid" if paid else "approved" if within and age > 10 else "disputed" if not within and age > 5 else "received"
        vctx = ctx.with_(entities={"supplier": sid, "media_insertion_order": io["media_insertion_order_id"]}, scale=gross)
        vinv = w.make("invoice", {
            "supplier_id": sid, "vendor_reference_number": f"{sup.supplier['trading_name'][:3].upper()}-{received:%y%m}-{rnd.int(1000, 9999)}",
            "number": f"VI{w.next_seq('vinv'):08d}", "invoice_type": "media", "invoice_status": vstatus, "issue_date": received - timedelta(days=2),
            "received_date": received, "billing_period_start": m, "billing_period_end": me, "currency_code": "USD",
            "gross_amount": round(gross, 4), "agency_discount_amount": round(gross * 0.15, 4), "net_amount": round(net, 4),
            "tax_amount": 0.0, "total_payable_amount": round(net, 4), "delivered_spend_amount": round(delivered, 4),
            "io_authorized_amount": io["authorized_spend_amount"], "approved_billing_amount": round(min(gross, delivered * 1.02) * 0.85, 4),
            "variance_amount": round(gross - delivered, 4), "variance_percentage": round(variance * 100, 4),
            "discrepancy_reason_code": None if within else ("delivery_shortfall" if variance < 0 else "overbilling"),
            "delivery_data_source": "cm360", "payment_terms": "net_45", "payment_due_date": pay_due,
            "payment_date": received + timedelta(days=rnd.int(30, 60)) if paid else None, "reconciliation_date": received + timedelta(days=rnd.int(3, 10)) if age > 10 else None,
            "reconciliation_period_start": m, "reconciliation_period_end": me, "dispute_raised_date": received + timedelta(days=4) if not within else None,
            "dispute_resolution_date": None, "dispute_resolution_notes": None, "line_item_id": lis[0][0].id if len(lis) == 1 else None,
            "flight_id": None, "production_job_id": None, "_created": rnd.ts_on(received)}, vctx.with_(anchor=received), rnd)
        rec = w.make("reconciliation", {
            "reconciliation_number": f"REC-{me.year}-{w.next_seq('rec'):06d}", "invoice_id": vinv["invoice_id"],
            "io_line_id": lis[0][0].io_line["io_line_id"], "supplier_id": sid, "period_start_date": m, "period_end_date": me,
            "adserver_delivered_amount": round(delivered, 4), "vendor_invoiced_amount": round(gross, 4),
            "io_authorized_amount": io["authorized_spend_amount"], "approved_billing_amount": vinv["approved_billing_amount"],
            "variance_amount": round(gross - delivered, 4), "variance_pct": round(variance * 100, 4), "tolerance_threshold_pct": tol,
            "within_tolerance_flag": within, "adserver_source": "CM360", "currency_code": "USD",
            "reconciliation_status": "closed" if paid else "approved" if within else "disputed",
            "resolution_status": "resolved" if paid or within else "pending_vendor",
            "discrepancy_reason_code": vinv["discrepancy_reason_code"], "credit_note_amount": None, "credit_note_number": None,
            "resolution_date": vinv["reconciliation_date"], "line_item_id": vinv["line_item_id"], "flight_id": None,
            "_created": rnd.ts_on(received + timedelta(days=2))}, vctx.with_(anchor=received + timedelta(days=2)), rnd)
        pay_status = "paid" if paid else "scheduled" if vstatus == "approved" else "disputed" if vstatus == "disputed" else "open"
        payable = w.make("vendor_payable", {
            "vendor_invoice_id": vinv["invoice_id"], "reconciliation_id": rec["reconciliation_id"], "supplier_id": sid,
            "payable_document_number": f"AP{received:%Y}{w.next_seq('ap'):07d}", "invoice_date": vinv["issue_date"],
            "posting_date": received, "due_date": pay_due, "gross_amount": money(gross), "net_amount": money(net),
            "discount_amount": 0.0, "tax_amount": 0.0, "withholding_tax_amount": 0.0, "currency_code": "USD",
            "payment_status": pay_status, "payment_terms": "net_45", "payment_date": vinv["payment_date"],
            "payment_method": "ach" if rnd.chance(0.7) else "wire_transfer", "fiscal_year": received.year, "fiscal_period": received.month,
            "gl_account_id": w.gl["2100"]["gl_account_id"], "sap_fi_document_number": f"51{rnd.int(10**7, 10**8 - 1)}",
            "mediaocean_payable_reference": f"MO-{rnd.int(10**8, 10**9 - 1)}", "approved_by": "ap.automation",
            "reconciliation_status": "matched" if within else "discrepancy", "io_line_id": lis[0][0].io_line["io_line_id"],
            "dispute_date": vinv["dispute_raised_date"], "dispute_reason": "Invoice exceeds delivered spend" if not within and variance > 0 else None,
            "production_job_id": None, "video_completion_event_id": None, "viewability_measurement_id": None,
            "delivery_pacing_id": None, "performance_kpi_target_id": None, "_created": rnd.ts_on(received)},
            vctx.with_(anchor=received), rnd)
        if paid:
            payment(w, "outbound", net, vinv["payment_date"], vctx, rnd, invoice_id=vinv["invoice_id"],
                    vendor_payable_id=payable["vendor_payable_id"], supplier_id=sid, reconciliation_id=rec["reconciliation_id"],
                    payer_name="Agency Holdings US", payee_name=sup.supplier["legal_name"])
        for li, days in lis:
            spend = sum(d.spend for d in days)
            imps = sum(d.impressions for d in days)
            planned_cost = li.budget * len(days) / ((li.end - li.start).days + 1)
            planned_imps = int(planned_cost / li.cpm * 1000)
            w.make("media_cost_reconciliation", {
                "reconciliation_document_number": f"REC-MC{me.year}{w.next_seq('mcr'):07d}", "line_item_id": li.id,
                "vendor_invoice_id": vinv["invoice_id"], "vendor_payable_id": payable["vendor_payable_id"],
                "reconciliation_id": rec["reconciliation_id"], "io_line_id": li.io_line["io_line_id"],
                "budget_line_id": li.budget_line["budget_line_id"], "billing_period_start_date": m, "billing_period_end_date": me,
                "planned_impressions": planned_imps, "delivered_impressions": imps, "impression_variance": imps - planned_imps,
                "impression_variance_percentage": round(max(-999, min(999, (imps - planned_imps) / planned_imps * 100)), 2) if planned_imps else None,
                "planned_cost_amount": money(planned_cost), "billed_cost_amount": money(spend * (1 + variance)),
                "reconciled_amount": money(spend), "planned_cpm": round(li.cpm, 2), "actual_cpm": round(spend / imps * 1000, 2) if imps else None,
                "variance_amount": money(spend * variance), "variance_percentage": round(variance * 100, 2), "currency_code": "USD",
                "reconciliation_status": "approved" if within else "in_dispute", "dispute_flag": not within,
                "variance_reason_code": None if within else ("under_delivery" if imps < planned_imps else "rate_discrepancy"),
                "click_event_id": None, "conversion_event_id": None, "video_completion_event_id": None,
                "viewability_measurement_id": None, "delivery_pacing_id": None, "performance_kpi_target_id": None,
                "_created": rnd.ts_on(received + timedelta(days=3))}, vctx.with_(anchor=received + timedelta(days=3), scale=spend), rnd)


def payment(w: World, direction: str, amount: float, on: date, ctx, rnd, **refs) -> dict:
    payer, payee = refs.pop("payer_name"), refs.pop("payee_name")
    return w.make("payment", {
        "direction": direction, "amount": money(amount), "functional_currency_amount": money(amount), "currency_code": "USD",
        "exchange_rate": 1.0, "payment_date": on, "value_date": on + timedelta(days=1), "payment_status": "reconciled" if on < w.today - timedelta(days=5) else "cleared",
        "payment_type": "invoice_payment", "payment_method": "ach" if rnd.chance(0.6) else "wire", "channel": "bank_transfer",
        "reference_number": f"PAY{on:%Y%m%d}{w.next_seq('pay'):06d}", "sap_payment_document_number": f"15{rnd.int(10**7, 10**8 - 1)}",
        "clearing_document_number": f"CLR{rnd.int(10**7, 10**8 - 1)}", "payer_name": payer, "payee_name": payee,
        "fiscal_year": on.year, "fiscal_period": on.month, "is_reversal": False, "original_payment_id": None,
        "approval_status": "approved", "reconciliation_status": "fully_reconciled", "reconciliation_date": on + timedelta(days=2),
        "_created": rnd.ts_on(on), **refs}, ctx.with_(anchor=on, scale=amount), rnd)


def retainers(w: World, rnd) -> None:
    """Monthly agency fee invoices per advertiser (SOW fee / 12)."""
    for adv in w.advertisers:
        for m in w.months():
            me = month_end(m)
            inv_date = me + timedelta(days=3)
            sow = adv.sows.get(m.year)
            if not sow or inv_date > w.today or adv.row["onboarding_date"] > me or (adv.churned and adv.churned < m):
                continue
            fee = float(sow["agency_fee_amount"] or 0) / 12
            if fee <= 0:
                continue
            ctx = w.adv_ctx(adv, inv_date, scale=fee, entities={"campaign": None, "plan": None, "buy": None})
            due = inv_date + timedelta(days=30)
            paid_on = inv_date + timedelta(days=rnd.int(20, 45))
            paid = paid_on <= w.today
            inv = w.make("client_invoice", {
                "invoice_number": f"INV-{inv_date.year}{w.next_seq('inv'):06d}", "invoice_date": inv_date, "due_date": due,
                "billing_period_start_date": m, "billing_period_end_date": me, "invoice_type": "retainer",
                "invoice_status": "paid" if paid else "overdue" if due < w.today else "sent", "currency_code": "USD",
                "subtotal_amount": money(fee), "tax_amount": 0.0, "discount_amount": 0.0, "adjustment_amount": None,
                "total_amount": money(fee), "amount_paid": money(fee) if paid else 0.0, "amount_outstanding": 0.0 if paid else money(fee),
                "payment_terms": "net_30", "payment_received_date": paid_on if paid else None, "dispute_date": None,
                "dispute_reason": None, "sent_timestamp": rnd.ts_on(inv_date), "contract_insertion_order_id": None,
                "milestone_id": None, "delivery_pacing_id": None, "performance_kpi_target_id": None,
                "_created": rnd.ts_on(inv_date)}, ctx, rnd)
            w.make("invoice_line", {
                "client_invoice_id": inv["client_invoice_id"], "line_number": 1, "billing_status": "billed",
                "service_category": "agency_fee", "service_description": f"Agency services retainer {m:%B %Y}",
                "unit_of_measure": "flat_fee", "quantity": 1, "unit_rate": round(fee, 4), "line_amount": money(fee),
                "line_total": money(fee), "commission_amount": 0.0, "commission_percentage": 0, "discount_amount": 0.0,
                "tax_amount": 0.0, "currency_code": "USD", "service_start_date": m, "service_end_date": me,
                "dispute_flag": False, "revenue_recognition_category": "recognized", "revenue_recognition_date": me,
                "buy_id": None, "campaign_id": None, "click_event_id": None, "viewability_measurement_id": None,
                "delivery_pacing_id": None, "media_placement_id": None, "programmatic_deal_id": None,
                "io_line_id": None, "reconciliation_id": None, "revenue_recognition_id": None}, ctx, rnd)
            w.make("revenue_recognition", {
                "client_invoice_id": inv["client_invoice_id"], "revenue_type": "retainer", "recognition_method": "straight_line",
                "recognition_status": "completed", "recognition_start_date": m, "recognition_end_date": me,
                "total_contract_value": money(float(sow["agency_fee_amount"])), "recognized_amount_to_date": money(fee),
                "deferred_revenue_amount": 0.0, "unbilled_revenue_amount": 0.0, "percentage_complete": 100, "currency_code": "USD",
                "fiscal_year": me.year, "fiscal_period": me.month, "fiscal_quarter": (me.month - 1) // 3 + 1,
                "gl_account_id": w.gl["4100"]["gl_account_id"], "is_active": False, "campaign_id": None,
                "delivery_pacing_id": None, "milestone_id": None, "performance_kpi_target_id": None,
                "media_insertion_order_id": None, "media_placement_id": None, "plan_id": None}, ctx, rnd)
            if paid:
                payment(w, "inbound", fee, paid_on, ctx, rnd, client_invoice_id=inv["client_invoice_id"],
                        payer_name=adv.row["legal_entity_name"], payee_name="Agency Holdings US")


def evaluations(w: World, rnd) -> None:
    """Quarterly scorecards for publishers that delivered in a completed quarter."""
    delivered: dict = defaultdict(lambda: defaultdict(float))
    for camp in w.campaigns:
        for li in camp.line_items:
            for d, day in li.daily.items():
                q = (d.year, (d.month - 1) // 3 + 1)
                delivered[li.supply.supplier["supplier_id"]][q] += day.impressions
    sups = {s.supplier["supplier_id"]: s for s in w.supply}
    for sid, quarters in delivered.items():
        for (year, q), imps in quarters.items():
            qs = date(year, (q - 1) * 3 + 1, 1)
            qe = month_end(date(year, q * 3, 1))
            if qe + timedelta(days=20) > w.today:
                continue
            ctx = w.ctx(qe + timedelta(days=15), entities={"supplier": sid}, label=sups[sid].supplier["trading_name"])
            score = rnd.uniform(6.2, 9.6)
            w.make("performance_evaluation", {
                "evaluation_number": f"VPE-{year}-{w.next_seq('vpe'):06d}", "supplier_id": sid,
                "evaluation_period_start_date": qs, "evaluation_period_end_date": qe, "evaluation_cycle": f"Q{q}",
                "evaluation_year": year, "evaluation_date": qe + timedelta(days=15), "evaluation_status": "completed",
                "vendor_category": "media_publisher", "actual_delivered_units": int(imps), "io_committed_units": int(imps * rnd.uniform(0.95, 1.08)),
                "overall_scorecard_rating": round(score, 2), "scorecard_rating_scale": "0-10",
                "preferred_vendor_tier": "tier_1" if score > 8.5 else "tier_2" if score > 7 else "tier_3",
                "campaign_id": None, "sow_id": None, "brand_id": None, "agency_relationship_id": None,
                "production_job_id": None, "initiative_id": None}, ctx, rnd)
