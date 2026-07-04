import sys
import logging
from typing import List, Optional
import requests
from mcp.server.fastmcp import FastMCP

# Setup logging to stderr so it doesn't interfere with stdio JSON-RPC transport
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("mcp_clinical_trials")

mcp = FastMCP("clinical_trials")

# Map tickers to known sponsor names in ClinicalTrials.gov
TICKER_SPONSORS = {
    "JNJ": ["Johnson & Johnson", "Janssen", "Actelion"],
    "NVO": ["Novo Nordisk"],
    "PFE": ["Pfizer"],
    "AMGN": ["Amgen"],
    "GSK": ["GlaxoSmithKline", "GSK"]
}

@mcp.tool()
def query_clinical_trials(ticker: str, as_of_date: Optional[str] = None) -> str:
    """
    Queries ClinicalTrials.gov API v2 for trials sponsored by the given company.
    Supports historical filtering to prevent lookahead bias in backtest mode.
    
    :param ticker: One of JNJ, NVO, PFE, AMGN, GSK
    :param as_of_date: Optional ISO date string (YYYY-MM-DD) for historical filtering
    :return: JSON string containing a list of clinical trials and their execution metrics
    """
    ticker = ticker.upper().strip()
    if ticker not in TICKER_SPONSORS:
        return f"Error: Ticker '{ticker}' is not supported. Supported: {list(TICKER_SPONSORS.keys())}"
        
    sponsors = TICKER_SPONSORS[ticker]
    all_studies = []
    
    # We will search for each sponsor name variation
    for sponsor in sponsors:
        url = "https://clinicaltrials.gov/api/v2/studies"
        params = {
            "query.spons": sponsor,
            "pageSize": 50,  # limit to recent 50 studies per sponsor variant
            "sort": "LastUpdatePostDate:desc"
        }
        
        if as_of_date:
            # Essie syntax for advanced date filtering
            params["filter.advanced"] = f"AREA[LastUpdatePostDate]RANGE[MIN, {as_of_date}]"
            
        try:
            logger.info(f"Querying ClinicalTrials.gov for {sponsor} with params {params}")
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                studies = data.get("studies", [])
                for study in studies:
                    protocol = study.get("protocolSection", {})
                    ident = protocol.get("identificationModule", {})
                    status_mod = protocol.get("statusModule", {})
                    sponsor_mod = protocol.get("sponsorCollaboratorsModule", {})
                    desc_mod = protocol.get("descriptionModule", {})
                    design_mod = protocol.get("designModule", {})
                    
                    nct_id = ident.get("nctId")
                    title = ident.get("officialTitle", ident.get("briefTitle", "Unknown Title"))
                    lead_sponsor = sponsor_mod.get("leadSponsor", {}).get("name", "Unknown Sponsor")
                    status = status_mod.get("overallStatus", "Unknown Status")
                    
                    # Dates
                    start_date = status_mod.get("startDateStruct", {}).get("date", "")
                    completion_date = status_mod.get("completionDateStruct", {}).get("date", "")
                    completion_type = status_mod.get("completionDateStruct", {}).get("type", "")
                    last_update = status_mod.get("lastUpdatePostDateStruct", {}).get("date", "")
                    
                    # Enrollment
                    enrollment = design_mod.get("enrollmentInfo", {}).get("count", 0)
                    enrollment_type = design_mod.get("enrollmentInfo", {}).get("type", "")
                    
                    # Description
                    summary = desc_mod.get("briefSummary", "")
                    
                    # Clean study info
                    study_info = {
                        "nct_id": nct_id,
                        "title": title,
                        "lead_sponsor": lead_sponsor,
                        "overall_status": status,
                        "start_date": start_date,
                        "completion_date": completion_date,
                        "completion_type": completion_type,
                        "last_update_posted": last_update,
                        "enrollment_count": enrollment,
                        "enrollment_type": enrollment_type,
                        "summary": summary[:200] + "..." if len(summary) > 200 else summary
                    }
                    all_studies.append(study_info)
            else:
                logger.error(f"ClinicalTrials API returned status {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"Error querying ClinicalTrials API for {sponsor}: {e}")
            
    # Remove duplicates by nct_id
    seen = set()
    unique_studies = []
    for s in all_studies:
        if s["nct_id"] not in seen:
            seen.add(s["nct_id"])
            unique_studies.append(s)
            
    # Sort again by last update posted desc
    unique_studies.sort(key=lambda x: x.get("last_update_posted", ""), reverse=True)
    
    # Return as JSON
    import json
    return json.dumps({
        "ticker": ticker,
        "as_of_date": as_of_date or "live",
        "total_trials_found": len(unique_studies),
        "trials": unique_studies[:50]  # Cap at 50 most relevant
    }, indent=2)

if __name__ == "__main__":
    mcp.run()
