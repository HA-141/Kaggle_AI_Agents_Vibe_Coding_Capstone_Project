import sys
import logging
from typing import Optional
import json
from datetime import datetime, timedelta
import requests
from mcp.server.fastmcp import FastMCP

# Setup logging to stderr so it doesn't interfere with stdio JSON-RPC transport
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("mcp_pubmed")

mcp = FastMCP("pubmed")

# Mapping tickers to search terms (drug brand names and generic names)
TICKER_DRUGS = {
    "JNJ": "Stelara OR ustekinumab OR Tremfya OR guselkumab OR Darzalex OR daratumumab",
    "NVO": "Ozempic OR semaglutide OR Wegovy OR Rybelsus OR Victoza OR liraglutide",
    "PFE": "Paxlovid OR Eliquis OR apixaban OR Ibrance OR palbociclib OR Prevnar",
    "AMGN": "Enbrel OR etanercept OR Prolia OR denosumab OR Otezla OR apremilast",
    "GSK": "Shingrix OR Trelegy OR Dovato OR Nucala OR mepolizumab OR Benlysta"
}

@mcp.tool()
def query_pubmed_trends(ticker: str, as_of_date: Optional[str] = None) -> str:
    """
    Queries PubMed E-utilities for month-over-month publication counts of the company's key drugs.
    Enforces a 14-day lag/buffer on publication dates to prevent lookahead bias.
    
    :param ticker: One of JNJ, NVO, PFE, AMGN, GSK
    :param as_of_date: Optional ISO date string (YYYY-MM-DD) for historical filtering
    :return: JSON string with month-over-month counts and momentum indicators (acceleration/deceleration)
    """
    ticker = ticker.upper().strip()
    if ticker not in TICKER_DRUGS:
        return f"Error: Ticker '{ticker}' is not supported. Supported: {list(TICKER_DRUGS.keys())}"
        
    search_term = TICKER_DRUGS[ticker]
    
    # 1. Establish the upper date limit (as_of_date minus 14 days buffer)
    ref_date_str = as_of_date or "2026-07-01"
    try:
        ref_date = datetime.strptime(ref_date_str, "%Y-%m-%d")
    except ValueError:
        try:
            ref_date = datetime.strptime(ref_date_str[:10], "%Y/%m/%d")
        except ValueError:
            ref_date = datetime(2026, 7, 1)
            
    upper_limit = ref_date - timedelta(days=14)
    logger.info(f"PubMed query for {ticker} as of {ref_date_str}. Upper date limit (with 14-day buffer): {upper_limit.strftime('%Y-%m-%d')}")
    
    # 2. Query PubMed for 6 consecutive 30-day windows leading up to upper_limit
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    history = []
    
    current_end = upper_limit
    for i in range(6):
        current_start = current_end - timedelta(days=30)
        
        start_str = current_start.strftime("%Y/%m/%d")
        end_str = current_end.strftime("%Y/%m/%d")
        
        params = {
            "db": "pubmed",
            "term": search_term,
            "mindate": start_str,
            "maxdate": end_str,
            "datetype": "pdat",
            "retmode": "json",
            "retmax": 0  # We only need the count
        }
        
        count = 0
        try:
            logger.info(f"Querying PubMed window {i+1}: {start_str} to {end_str}")
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                count = int(data.get("esearchresult", {}).get("count", 0))
            else:
                logger.error(f"PubMed API returned status {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"Error querying PubMed window {i+1}: {e}")
            
        history.append({
            "window_index": i + 1,
            "start_date": current_start.strftime("%Y-%m-%d"),
            "end_date": current_end.strftime("%Y-%m-%d"),
            "count": count
        })
        
        # Shift window back by 30 days
        current_end = current_start
        
    # Reverse history so it runs chronologically
    history.reverse()
    
    # 3. Analyze momentum (MoM changes and acceleration)
    mom_changes = []
    for i in range(len(history)):
        curr = history[i]
        if i > 0:
            prev = history[i-1]
            diff = curr["count"] - prev["count"]
            pct = round((diff / prev["count"] * 100), 2) if prev["count"] > 0 else 0.0
            curr["mom_change_count"] = diff
            curr["mom_change_pct"] = pct
        else:
            curr["mom_change_count"] = 0
            curr["mom_change_pct"] = 0.0
            
    # Calculate acceleration (change in change)
    for i in range(len(history)):
        curr = history[i]
        if i > 1:
            prev = history[i-1]
            accel = curr["mom_change_count"] - prev["mom_change_count"]
            curr["acceleration_count"] = accel
            curr["trend"] = "accelerating" if accel > 0 else ("decelerating" if accel < 0 else "stable")
        else:
            curr["acceleration_count"] = 0
            curr["trend"] = "stable"
            
    # Calculate key metrics
    recent_count = sum(h["count"] for h in history[-2:]) # Last 60 days
    previous_count = sum(h["count"] for h in history[-4:-2]) # Prior 60 days
    trend_60d_diff = recent_count - previous_count
    trend_60d_pct = round((trend_60d_diff / previous_count * 100), 2) if previous_count > 0 else 0.0
    
    overall_trend = "bullish" if trend_60d_diff > 10 and trend_60d_pct > 5 else (
        "bearish" if trend_60d_diff < -10 and trend_60d_pct < -5 else "neutral"
    )
    
    return json.dumps({
        "ticker": ticker,
        "as_of_date": ref_date_str,
        "search_term": search_term,
        "buffer_days": 14,
        "data_as_of_date": upper_limit.strftime("%Y-%m-%d"),
        "recent_60d_publications": recent_count,
        "previous_60d_publications": previous_count,
        "trend_60d_change_pct": trend_60d_pct,
        "implied_signal": overall_trend,
        "history": history
    }, indent=2)

if __name__ == "__main__":
    mcp.run()
