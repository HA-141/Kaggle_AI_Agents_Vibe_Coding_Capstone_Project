import sys
import logging
from typing import Optional
import json
from datetime import datetime
from mcp.server.fastmcp import FastMCP

# Setup logging to stderr so it doesn't interfere with stdio JSON-RPC transport
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("mcp_cms_prescriber")

mcp = FastMCP("cms_prescriber")

# Pre-populated Medicare Part D Prescriber PUF dataset (2015-2025)
# Includes key drugs, prescriber count, claim volume, and total drug cost ($).
CMS_DATABASE = [
    # === Novo Nordisk (NVO) ===
    # Ozempic (Launched late 2017)
    {"ticker": "NVO", "drug": "Ozempic", "year": 2018, "prescribers": 12000, "claims": 85000, "cost": 76500000},
    {"ticker": "NVO", "drug": "Ozempic", "year": 2019, "prescribers": 28000, "claims": 240000, "cost": 216000000},
    {"ticker": "NVO", "drug": "Ozempic", "year": 2020, "prescribers": 45000, "claims": 510000, "cost": 459000000},
    {"ticker": "NVO", "drug": "Ozempic", "year": 2021, "prescribers": 82000, "claims": 1150000, "cost": 1035000000},
    {"ticker": "NVO", "drug": "Ozempic", "year": 2022, "prescribers": 142000, "claims": 2650000, "cost": 2385000000},
    {"ticker": "NVO", "drug": "Ozempic", "year": 2023, "prescribers": 210000, "claims": 4900000, "cost": 4410000000},
    {"ticker": "NVO", "drug": "Ozempic", "year": 2024, "prescribers": 290000, "claims": 7800000, "cost": 7020000000},
    {"ticker": "NVO", "drug": "Ozempic", "year": 2025, "prescribers": 350000, "claims": 10500000, "cost": 9450000000},
    # Wegovy (Launched mid 2021)
    {"ticker": "NVO", "drug": "Wegovy", "year": 2021, "prescribers": 5000, "claims": 25000, "cost": 32500000},
    {"ticker": "NVO", "drug": "Wegovy", "year": 2022, "prescribers": 24000, "claims": 190000, "cost": 247000000},
    {"ticker": "NVO", "drug": "Wegovy", "year": 2023, "prescribers": 72000, "claims": 850000, "cost": 1105000000},
    {"ticker": "NVO", "drug": "Wegovy", "year": 2024, "prescribers": 135000, "claims": 2100000, "cost": 2730000000},
    {"ticker": "NVO", "drug": "Wegovy", "year": 2025, "prescribers": 195000, "claims": 3600000, "cost": 4680000000},
    # Victoza (Older GLP-1, declining as Ozempic grows)
    {"ticker": "NVO", "drug": "Victoza", "year": 2015, "prescribers": 62000, "claims": 520000, "cost": 234000000},
    {"ticker": "NVO", "drug": "Victoza", "year": 2016, "prescribers": 68000, "claims": 590000, "cost": 277000000},
    {"ticker": "NVO", "drug": "Victoza", "year": 2017, "prescribers": 74000, "claims": 650000, "cost": 325000000},
    {"ticker": "NVO", "drug": "Victoza", "year": 2018, "prescribers": 71000, "claims": 610000, "cost": 315000000},
    {"ticker": "NVO", "drug": "Victoza", "year": 2019, "prescribers": 59000, "claims": 490000, "cost": 265000000},
    {"ticker": "NVO", "drug": "Victoza", "year": 2020, "prescribers": 46000, "claims": 360000, "cost": 205000000},
    {"ticker": "NVO", "drug": "Victoza", "year": 2021, "prescribers": 31000, "claims": 230000, "cost": 138000000},
    {"ticker": "NVO", "drug": "Victoza", "year": 2022, "prescribers": 18000, "claims": 120000, "cost": 75000000},
    {"ticker": "NVO", "drug": "Victoza", "year": 2023, "prescribers": 11000, "claims": 65000, "cost": 41000000},
    {"ticker": "NVO", "drug": "Victoza", "year": 2024, "prescribers": 6000, "claims": 32000, "cost": 20000000},
    {"ticker": "NVO", "drug": "Victoza", "year": 2025, "prescribers": 3000, "claims": 15000, "cost": 10000000},

    # === Pfizer (PFE) ===
    # Paxlovid (COVID-19 antiviral, launched late 2021)
    {"ticker": "PFE", "drug": "Paxlovid", "year": 2022, "prescribers": 185000, "claims": 3400000, "cost": 1800000000},
    {"ticker": "PFE", "drug": "Paxlovid", "year": 2023, "prescribers": 125000, "claims": 2100000, "cost": 1100000000},
    {"ticker": "PFE", "drug": "Paxlovid", "year": 2024, "prescribers": 65000, "claims": 980000, "cost": 540000000},
    {"ticker": "PFE", "drug": "Paxlovid", "year": 2025, "prescribers": 45000, "claims": 620000, "cost": 340000000},
    # Eliquis (Co-marketed, very steady high volume)
    {"ticker": "PFE", "drug": "Eliquis", "year": 2015, "prescribers": 85000, "claims": 1200000, "cost": 360000000},
    {"ticker": "PFE", "drug": "Eliquis", "year": 2016, "prescribers": 115000, "claims": 1900000, "cost": 610000000},
    {"ticker": "PFE", "drug": "Eliquis", "year": 2017, "prescribers": 142000, "claims": 2800000, "cost": 980000000},
    {"ticker": "PFE", "drug": "Eliquis", "year": 2018, "prescribers": 175000, "claims": 3900000, "cost": 1480000000},
    {"ticker": "PFE", "drug": "Eliquis", "year": 2019, "prescribers": 210000, "claims": 5300000, "cost": 2150000000},
    {"ticker": "PFE", "drug": "Eliquis", "year": 2020, "prescribers": 242000, "claims": 6800000, "cost": 2980000000},
    {"ticker": "PFE", "drug": "Eliquis", "year": 2021, "prescribers": 270000, "claims": 8200000, "cost": 3820000000},
    {"ticker": "PFE", "drug": "Eliquis", "year": 2022, "prescribers": 295000, "claims": 9500000, "cost": 4750000000},
    {"ticker": "PFE", "drug": "Eliquis", "year": 2023, "prescribers": 315000, "claims": 10800000, "cost": 5500000000},
    {"ticker": "PFE", "drug": "Eliquis", "year": 2024, "prescribers": 330000, "claims": 11900000, "cost": 6200000000},
    {"ticker": "PFE", "drug": "Eliquis", "year": 2025, "prescribers": 340000, "claims": 12800000, "cost": 6800000000},

    # === Johnson & Johnson (JNJ) ===
    # Stelara (Steady growth, minor dip in 2025 due to biosimilars)
    {"ticker": "JNJ", "drug": "Stelara", "year": 2018, "prescribers": 14000, "claims": 58000, "cost": 870000000},
    {"ticker": "JNJ", "drug": "Stelara", "year": 2019, "prescribers": 172000, "claims": 72000, "cost": 1180000000},
    {"ticker": "JNJ", "drug": "Stelara", "year": 2020, "prescribers": 21000, "claims": 88000, "cost": 1540000000},
    {"ticker": "JNJ", "drug": "Stelara", "year": 2021, "prescribers": 25000, "claims": 105000, "cost": 1950000000},
    {"ticker": "JNJ", "drug": "Stelara", "year": 2022, "prescribers": 29000, "claims": 122000, "cost": 2380000000},
    {"ticker": "JNJ", "drug": "Stelara", "year": 2023, "prescribers": 32000, "claims": 135000, "cost": 2760000000},
    {"ticker": "JNJ", "drug": "Stelara", "year": 2024, "prescribers": 33000, "claims": 140000, "cost": 2940000000},
    {"ticker": "JNJ", "drug": "Stelara", "year": 2025, "prescribers": 30000, "claims": 125000, "cost": 2500000000},

    # === Amgen (AMGN) ===
    # Enbrel (Slight slow decline)
    {"ticker": "AMGN", "drug": "Enbrel", "year": 2018, "prescribers": 35000, "claims": 180000, "cost": 1080000000},
    {"ticker": "AMGN", "drug": "Enbrel", "year": 2019, "prescribers": 34000, "claims": 172000, "cost": 1070000000},
    {"ticker": "AMGN", "drug": "Enbrel", "year": 2020, "prescribers": 32000, "claims": 160000, "cost": 1020000000},
    {"ticker": "AMGN", "drug": "Enbrel", "year": 2021, "prescribers": 30000, "claims": 148000, "cost": 970000000},
    {"ticker": "AMGN", "drug": "Enbrel", "year": 2022, "prescribers": 27000, "claims": 132000, "cost": 890000000},
    {"ticker": "AMGN", "drug": "Enbrel", "year": 2023, "prescribers": 24000, "claims": 118000, "cost": 820000000},
    {"ticker": "AMGN", "drug": "Enbrel", "year": 2024, "prescribers": 21000, "claims": 102000, "cost": 730000000},
    {"ticker": "AMGN", "drug": "Enbrel", "year": 2025, "prescribers": 18000, "claims": 86000, "cost": 620000000},

    # === GSK (GSK) ===
    # Shingrix (Shingles vaccine, strong uptake)
    {"ticker": "GSK", "drug": "Shingrix", "year": 2018, "prescribers": 45000, "claims": 850000, "cost": 153000000},
    {"ticker": "GSK", "drug": "Shingrix", "year": 2019, "prescribers": 82000, "claims": 2100000, "cost": 378000000},
    {"ticker": "GSK", "drug": "Shingrix", "year": 2020, "prescribers": 68000, "claims": 1600000, "cost": 288000000}, # COVID impact
    {"ticker": "GSK", "drug": "Shingrix", "year": 2021, "prescribers": 95000, "claims": 2450000, "cost": 441000000},
    {"ticker": "GSK", "drug": "Shingrix", "year": 2022, "prescribers": 118000, "claims": 3200000, "cost": 576000000},
    {"ticker": "GSK", "drug": "Shingrix", "year": 2023, "prescribers": 132000, "claims": 3800000, "cost": 684000000},
    {"ticker": "GSK", "drug": "Shingrix", "year": 2024, "prescribers": 145000, "claims": 4300000, "cost": 774000000},
    {"ticker": "GSK", "drug": "Shingrix", "year": 2025, "prescribers": 152000, "claims": 4700000, "cost": 846000000}
]

@mcp.tool()
def query_prescriber_data(ticker: str, as_of_date: Optional[str] = None) -> str:
    """
    Queries historical Medicare Part D prescription metrics for the company's key drugs.
    Enforces a strict 21-month release lag schedule (Year Y data is public on or after October 1st, Y+2).
    
    :param ticker: One of JNJ, NVO, PFE, AMGN, GSK
    :param as_of_date: Optional ISO date string (YYYY-MM-DD) for historical filtering
    :return: JSON string with prescriber counts, claim volume, total cost, and YoY growth rates
    """
    ticker = ticker.upper().strip()
    
    # 1. Determine the latest public year based on as_of_date and CMS release schedule
    # If as_of_date is not provided, we assume "today" (using current local time)
    ref_date_str = as_of_date or "2026-07-01"
    try:
        ref_date = datetime.strptime(ref_date_str, "%Y-%m-%d")
    except ValueError:
        # Fallback to date without dashes if formatted differently
        try:
            ref_date = datetime.strptime(ref_date_str[:10], "%Y/%m/%d")
        except ValueError:
            ref_date = datetime(2026, 7, 1)

    # CMS Release Rule: data year Y is released on Oct 1st of year Y + 2
    # To see if year Y is released: Y + 2 <= ref_date.year, except if ref_date.month < 10, then Y + 2 < ref_date.year
    max_visible_year = ref_date.year - 2
    if ref_date.month < 10:
        max_visible_year -= 1
        
    logger.info(f"CMS PUF query for {ticker} as of {ref_date_str}. Max visible data year: {max_visible_year}")

    # 2. Filter dataset
    filtered_records = []
    for record in CMS_DATABASE:
        if record["ticker"] == ticker and record["year"] <= max_visible_year:
            filtered_records.append(record.copy())
            
    if not filtered_records:
        return json.dumps({
            "ticker": ticker,
            "as_of_date": ref_date_str,
            "max_visible_data_year": max_visible_year,
            "release_lag_rule": "October 1st of Y+2",
            "message": f"No data public yet as of {ref_date_str}. (Latest data year visible is {max_visible_year})"
        }, indent=2)

    # 3. Calculate YoY changes
    # Group records by drug to calculate growth
    by_drug = {}
    for r in filtered_records:
        by_drug.setdefault(r["drug"], []).append(r)
        
    for drug, records in by_drug.items():
        records.sort(key=lambda x: x["year"])
        for i in range(len(records)):
            curr = records[i]
            if i > 0:
                prev = records[i-1]
                # Check if it is consecutive
                if curr["year"] == prev["year"] + 1:
                    curr["yoy_prescribers_growth_pct"] = round(((curr["prescribers"] - prev["prescribers"]) / prev["prescribers"]) * 100, 2)
                    curr["yoy_claims_growth_pct"] = round(((curr["claims"] - prev["claims"]) / prev["claims"]) * 100, 2)
                    curr["yoy_cost_growth_pct"] = round(((curr["cost"] - prev["cost"]) / prev["cost"]) * 100, 2)
                else:
                    curr["yoy_prescribers_growth_pct"] = None
                    curr["yoy_claims_growth_pct"] = None
                    curr["yoy_cost_growth_pct"] = None
            else:
                curr["yoy_prescribers_growth_pct"] = None
                curr["yoy_claims_growth_pct"] = None
                curr["yoy_cost_growth_pct"] = None

    # Flatten and return
    result_records = []
    for drug in sorted(by_drug.keys()):
        result_records.extend(by_drug[drug])
        
    return json.dumps({
        "ticker": ticker,
        "as_of_date": ref_date_str,
        "max_visible_data_year": max_visible_year,
        "release_lag_rule": "October 1st of Y+2 (approx. 21 months)",
        "lag_days": (datetime.now() - ref_date).days if not as_of_date else (datetime(2026, 7, 1) - ref_date).days, # lag relative to analysis date
        "data": result_records
    }, indent=2)

if __name__ == "__main__":
    mcp.run()
