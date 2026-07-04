import sys
import logging
from typing import Optional
import json
from datetime import datetime
import requests
from mcp.server.fastmcp import FastMCP

# Setup logging to stderr so it doesn't interfere with stdio JSON-RPC transport
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("mcp_usaspending")

mcp = FastMCP("usaspending")

# Mapping tickers to recipient search names in USAspending
TICKER_RECIPIENTS = {
    "JNJ": ["JOHNSON & JOHNSON", "JANSSEN"],
    "NVO": ["NOVO NORDISK"],
    "PFE": ["PFIZER"],
    "AMGN": ["AMGEN"],
    "GSK": ["GLAXOSMITHKLINE", "GSK SYSTEMS"]
}

# Approx annual revenues ($B) for context-level magnitude estimates
TICKER_REVENUES_BILLIONS = {
    "JNJ": 85.0,
    "NVO": 33.0,
    "PFE": 58.0,
    "AMGN": 28.0,
    "GSK": 38.0
}

@mcp.tool()
def query_government_contracts(ticker: str, as_of_date: Optional[str] = None) -> str:
    """
    Queries USAspending.gov API for federal contract awards to the company.
    Restricts awards by date to prevent lookahead bias in backtest mode.
    
    :param ticker: One of JNJ, NVO, PFE, AMGN, GSK
    :param as_of_date: Optional ISO date string (YYYY-MM-DD) for historical filtering
    :return: JSON string listing recent contract awards and size relative to company revenue
    """
    ticker = ticker.upper().strip()
    if ticker not in TICKER_RECIPIENTS:
        return f"Error: Ticker '{ticker}' is not supported. Supported: {list(TICKER_RECIPIENTS.keys())}"
        
    recipients = TICKER_RECIPIENTS[ticker]
    ref_date_str = as_of_date or "2026-07-01"
    
    url = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
    
    # We will search from 2018-01-01 up to the reference date
    time_period = {
        "start_date": "2018-01-01",
        "end_date": ref_date_str
    }
    
    all_awards = []
    
    for recipient in recipients:
        payload = {
            "filters": {
                "recipient_search_text": [recipient],
                "award_type_codes": ["A", "B", "C", "D"], # Contracts
                "time_period": [time_period]
            },
            "fields": [
                "Award ID", 
                "Recipient Name", 
                "Start Date", 
                "End Date", 
                "Award Amount", 
                "Description", 
                "Awarding Agency", 
                "Awarding Sub Agency"
            ],
            "limit": 30,
            "sort": "Award Amount",
            "order": "desc"
        }
        
        try:
            logger.info(f"Querying USAspending for {recipient} with payload filters {payload['filters']}")
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                for item in results:
                    award = {
                        "award_id": item.get("Award ID"),
                        "recipient": item.get("Recipient Name"),
                        "start_date": item.get("Start Date"),
                        "end_date": item.get("End Date"),
                        "amount": item.get("Award Amount", 0.0),
                        "description": item.get("Description", ""),
                        "agency": item.get("Awarding Agency"),
                        "sub_agency": item.get("Awarding Sub Agency")
                    }
                    all_awards.append(award)
            else:
                logger.error(f"USAspending API returned status {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"Error querying USAspending API for {recipient}: {e}")
            
    # Remove duplicate awards by award_id
    seen = set()
    unique_awards = []
    for a in all_awards:
        if a["award_id"] not in seen:
            seen.add(a["award_id"])
            unique_awards.append(a)
            
    # Sort by amount desc
    unique_awards.sort(key=lambda x: x.get("amount", 0.0), reverse=True)
    
    # Calculate sum and size relative to revenue
    total_amount = sum(a["amount"] for a in unique_awards)
    annual_rev = TICKER_REVENUES_BILLIONS.get(ticker, 10.0) * 1e9 # convert to dollars
    percentage_of_revenue = round((total_amount / annual_rev) * 100, 4)
    
    return json.dumps({
        "ticker": ticker,
        "as_of_date": ref_date_str,
        "company_estimated_annual_revenue_usd": annual_rev,
        "total_contracts_value_found_usd": total_amount,
        "percentage_of_annual_revenue": percentage_of_revenue,
        "contracts": unique_awards[:30] # Top 30 contract awards
    }, indent=2)

if __name__ == "__main__":
    mcp.run()
