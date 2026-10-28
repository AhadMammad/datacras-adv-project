"""The agency itself: employees (actors and named contacts), cost centers and the chart of accounts (erp_db)."""
from __future__ import annotations

from datetime import date

from ..values import pools
from ..world import World

COMPANY = "US01"
CHART = "CAUS"

# code, name, type, financial statement, P&L class, balance sheet class
GL_ACCOUNTS = [
    ("1100", "Cash and Cash Equivalents", "asset", "balance_sheet", "not_applicable", "current_asset"),
    ("1200", "Accounts Receivable - Clients", "asset", "balance_sheet", "not_applicable", "current_asset"),
    ("1250", "Unbilled Media Receivables", "asset", "balance_sheet", "not_applicable", "current_asset"),
    ("1300", "Prepaid Media", "asset", "balance_sheet", "not_applicable", "current_asset"),
    ("2100", "Accounts Payable - Media Vendors", "liability", "balance_sheet", "not_applicable", "current_liability"),
    ("2150", "Accounts Payable - Production Vendors", "liability", "balance_sheet", "not_applicable", "current_liability"),
    ("2200", "Accrued Media Liabilities", "liability", "balance_sheet", "not_applicable", "current_liability"),
    ("2300", "Deferred Revenue", "liability", "balance_sheet", "not_applicable", "current_liability"),
    ("3000", "Retained Earnings", "equity", "equity", "not_applicable", "equity"),
    ("4000", "Media Billings Revenue", "revenue", "income_statement", "operating_revenue", "not_applicable"),
    ("4100", "Agency Fee Revenue", "revenue", "income_statement", "operating_revenue", "not_applicable"),
    ("4200", "Commission Revenue", "revenue", "income_statement", "operating_revenue", "not_applicable"),
    ("4300", "Production Revenue", "revenue", "income_statement", "operating_revenue", "not_applicable"),
    ("4400", "Performance Bonus Revenue", "revenue", "income_statement", "operating_revenue", "not_applicable"),
    ("5000", "Media Cost - Digital", "expense", "income_statement", "cost_of_sales", "not_applicable"),
    ("5050", "Media Cost - Programmatic", "expense", "income_statement", "cost_of_sales", "not_applicable"),
    ("5100", "Media Cost - CTV and Video", "expense", "income_statement", "cost_of_sales", "not_applicable"),
    ("5200", "Production Costs", "expense", "income_statement", "cost_of_sales", "not_applicable"),
    ("5300", "Ad Serving and Verification Fees", "expense", "income_statement", "cost_of_sales", "not_applicable"),
    ("5400", "Data and Audience Costs", "expense", "income_statement", "cost_of_sales", "not_applicable"),
    ("6000", "Salaries and Wages", "expense", "income_statement", "operating_expense", "not_applicable"),
    ("6100", "Freelance and Contractors", "expense", "income_statement", "operating_expense", "not_applicable"),
    ("6200", "Software and Subscriptions", "expense", "income_statement", "operating_expense", "not_applicable"),
    ("6300", "Travel and Entertainment", "expense", "income_statement", "operating_expense", "not_applicable"),
    ("6400", "Rent and Facilities", "expense", "income_statement", "operating_expense", "not_applicable"),
]


def build(w: World) -> None:
    rnd = w.rnd.child("org")
    n = int(w.cfg.get_path("org.employees", 60))
    names: set[str] = set()
    while len(names) < n:
        names.add(rnd.fake.name())
    w.people = sorted(names)
    for p in w.people:
        w.roles[p] = (rnd.choice(pools.JOB_TITLES), rnd.choice(pools.DEPARTMENTS))
    since = date(w.start.year - 2, 1, 1)
    ctx = w.ctx(since, scale=2_000_000, duration=365 * 5)

    root = w.make("cost_center", {
        "cost_center_code": "CC1000", "cost_center_name": "Agency Holdings US", "cost_center_status": "active",
        "cost_center_type": "administrative", "cost_center_category": "administration", "company_code": COMPANY,
        "controlling_area": "A000", "currency_code": "USD", "effective_start_date": since,
        "effective_end_date": None, "fiscal_year": str(w.start.year), "sap_co_cost_center_reference": "US01CC1000",
        "budget_owner_name": w.people[0]}, ctx, rnd)
    w.cost_centers["root"] = root
    depts = pools.DEPARTMENTS[: max(1, int(w.cfg.get_path("org.cost_centers", 12)) - 1)]
    for i, dept in enumerate(depts):
        billable = dept not in ("Finance", "Analytics")
        owner = w.pick_person(dept)
        w.cost_centers[dept] = w.make("cost_center", {
            "cost_center_code": f"CC{1100 + i * 10}", "cost_center_name": dept,
            "parent_cost_center_id": root["cost_center_id"], "cost_center_status": "active",
            "cost_center_type": "billable" if billable else "overhead",
            "cost_center_category": "production" if billable else "support", "billable_flag": billable,
            "company_code": COMPANY, "controlling_area": "A000", "currency_code": "USD",
            "effective_start_date": since, "effective_end_date": None, "fiscal_year": str(w.start.year),
            "owning_department": dept, "budget_owner_name": owner,
            "sap_co_cost_center_reference": f"US01CC{1100 + i * 10}"}, ctx, rnd)

    for code, name, typ, fs, pl, bs in GL_ACCOUNTS:
        w.gl[code] = w.make("gl_account", {
            "account_code": code, "account_name": name, "account_type": typ, "company_code": COMPANY,
            "chart_of_accounts": CHART, "financial_statement_category": fs, "pl_classification": pl,
            "balance_sheet_classification": bs, "gl_account_status": "active", "currency_code": "USD",
            "posting_blocked": False, "valid_from_date": since, "valid_to_date": None,
            "cost_center_applicable": typ in ("revenue", "expense"),
            "reconciliation_account": code in ("1200", "2100", "2150"),
            "open_item_management": code in ("1200", "2100", "2150", "2200")}, ctx, rnd)

    # annual overhead budgets per cost center
    for dept, cc in w.cost_centers.items():
        if dept == "root":
            continue
        for year in range(w.start.year, w.today.year + 1):
            amount = rnd.lognormal(900_000, 0.4)
            w.make("finance_budget", {
                "budget_number": f"FB{year}OH{cc['cost_center_code'][2:]}", "budget_name": f"FY{year} {dept} Operating Budget",
                "budget_type": "overhead", "budget_category": "operating", "cost_center_id": cc["cost_center_id"],
                "gl_account_id": w.gl["6000"]["gl_account_id"], "fiscal_year": year, "fiscal_period": None,
                "approved_amount": round(amount, 2), "allocated_amount": round(amount, 2),
                "spent_amount": round(amount * min(1.0, (w.today - date(year, 1, 1)).days / 365) * rnd.uniform(0.9, 1.05), 2),
                "currency_code": "USD", "effective_start_date": date(year, 1, 1), "effective_end_date": date(year, 12, 31),
                "approval_status": "approved", "version": "original", "campaign_id": None, "sow_id": None,
                "agreement_id": None, "client_brief_id": None, "initiative_id": None},
                ctx.with_(anchor=date(year, 1, 1), scale=amount), rnd)
