"""Treasury Fiscal Data allowlisted dataset adapter."""

from __future__ import annotations

import json
from typing import Literal

from us_gov_research.errors import SourceError
from us_gov_research.evidence import EvidenceRecord
from us_gov_research.http import GovernmentClient

from .common import evidence

TreasuryDataset = Literal[
    "debt_to_penny",
    "monthly_receipts_outlays",
    "interest_expense",
    "operating_cash_balance",
    "exchange_rates",
    "auctions",
]

DATASETS: dict[str, tuple[str, str, str]] = {
    "debt_to_penny": (
        "/v2/accounting/od/debt_to_penny",
        "Debt to the Penny",
        "https://fiscaldata.treasury.gov/datasets/debt-to-the-penny/",
    ),
    "monthly_receipts_outlays": (
        "/v1/accounting/mts/mts_table_1",
        "Monthly Treasury Statement — Summary of Receipts and Outlays",
        "https://fiscaldata.treasury.gov/datasets/monthly-treasury-statement/",
    ),
    "interest_expense": (
        "/v2/accounting/od/interest_expense",
        "Interest Expense on the Public Debt Outstanding",
        "https://fiscaldata.treasury.gov/datasets/interest-expense-debt-outstanding/",
    ),
    "operating_cash_balance": (
        "/v1/accounting/dts/operating_cash_balance",
        "Daily Treasury Statement — Operating Cash Balance",
        "https://fiscaldata.treasury.gov/datasets/daily-treasury-statement/",
    ),
    "exchange_rates": (
        "/v1/accounting/od/rates_of_exchange",
        "Treasury Reporting Rates of Exchange",
        "https://fiscaldata.treasury.gov/datasets/treasury-reporting-rates-exchange/",
    ),
    "auctions": (
        "/v1/accounting/od/auctions_query",
        "Treasury Securities Auctions Data",
        "https://fiscaldata.treasury.gov/datasets/treasury-securities-auctions-data/",
    ),
}


async def query_treasury_api(
    client: GovernmentClient,
    *,
    dataset: TreasuryDataset,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 5,
) -> list[EvidenceRecord]:
    """Query one approved Treasury Fiscal Data dataset."""

    endpoint, title, canonical_url = DATASETS[dataset]
    params: dict[str, object] = {
        "sort": "-record_date",
        "page[number]": 1,
        "page[size]": max(1, min(limit, 10)),
        "format": "json",
    }
    filters = []
    if start_date:
        filters.append(f"record_date:gte:{start_date}")
    if end_date:
        filters.append(f"record_date:lte:{end_date}")
    if filters:
        params["filter"] = ",".join(filters)
    payload = await client.get_json(
        "treasury",
        f"https://api.fiscaldata.treasury.gov/services/api/fiscal_service{endpoint}",
        params=params,
        headers={"Accept": "application/json"},
        ttl_seconds=3600 if not end_date else 604_800,
    )
    rows = payload.get("data", [])
    results = []
    for index, row in enumerate(rows if isinstance(rows, list) else []):
        if not isinstance(row, dict):
            continue
        record_date = row.get("record_date")
        results.append(
            evidence(
                source="treasury",
                title=f"{title} — {record_date}",
                canonical_url=canonical_url,
                document_id=f"{dataset}:{record_date}:{index}",
                published_at=record_date,
                excerpt=json.dumps(row, sort_keys=True, ensure_ascii=False),
                fields=row,
            )
        )
    if not results:
        raise SourceError("treasury", f"no {dataset} records matched the requested dates")
    return results
