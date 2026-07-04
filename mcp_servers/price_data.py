import sys
import logging
from typing import Optional
import json
from datetime import datetime, timedelta
import yfinance as yf
import pandas as pd
from mcp.server.fastmcp import FastMCP

# Setup logging to stderr so it doesn't interfere with stdio JSON-RPC transport
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("mcp_price_data")

mcp = FastMCP("price_data")

@mcp.tool()
def get_historical_prices(
    ticker: str, 
    start_date: str, 
    end_date: str, 
    as_of_date: Optional[str] = None
) -> str:
    """
    Fetches historical closing prices and volume for a ticker.
    Enforces the lookahead bias limit: if as_of_date is provided, 
    it strictly filters out any price data after that date.
    
    :param ticker: One of JNJ, NVO, PFE, AMGN, GSK
    :param start_date: ISO date (YYYY-MM-DD) for start of price history
    :param end_date: ISO date (YYYY-MM-DD) for end of price history
    :param as_of_date: Optional ISO date (YYYY-MM-DD) limiting the visible history
    :return: JSON string with list of dates, closing prices, and volumes
    """
    ticker = ticker.upper().strip()
    
    # 1. Determine effective end date to prevent lookahead bias
    effective_end = end_date
    if as_of_date:
        # Parse and compare dates
        try:
            dt_end = datetime.strptime(end_date, "%Y-%m-%d")
            dt_as_of = datetime.strptime(as_of_date, "%Y-%m-%d")
            if dt_end > dt_as_of:
                effective_end = as_of_date
                logger.info(f"Price query capped at as_of_date: {as_of_date} (was {end_date})")
        except ValueError as e:
            logger.error(f"Error parsing dates in price caps: {e}")
            if as_of_date:
                effective_end = as_of_date
                
    try:
        logger.info(f"Fetching yfinance history for {ticker} from {start_date} to {effective_end}")
        yf_ticker = yf.Ticker(ticker)
        
        # yfinance end_date is exclusive, so we add 1 day to effective_end to include it
        dt_eff_end = datetime.strptime(effective_end, "%Y-%m-%d")
        exclusive_end_str = (dt_eff_end + timedelta(days=1)).strftime("%Y-%m-%d")
        
        df = yf_ticker.history(start=start_date, end=exclusive_end_str)
        
        if df.empty:
            return json.dumps({
                "ticker": ticker,
                "message": f"No price data found for {ticker} between {start_date} and {effective_end}."
            })
            
        # Convert index to string dates and build history
        history = []
        for date, row in df.iterrows():
            history.append({
                "date": date.strftime("%Y-%m-%d"),
                "close": round(float(row["Close"]), 2),
                "volume": int(row["Volume"])
            })
            
        return json.dumps({
            "ticker": ticker,
            "start_date": start_date,
            "end_date": effective_end,
            "data_points": len(history),
            "prices": history
        }, indent=2)
        
    except Exception as e:
        logger.error(f"Error fetching historical prices for {ticker}: {e}")
        return json.dumps({
            "ticker": ticker,
            "error": str(e)
        })

@mcp.tool()
def get_forward_returns(
    ticker: str, 
    as_of_date: str, 
    forward_days: int = 5
) -> str:
    """
    Retrieves the actual stock price closing data and calculates forward return 
    from the as_of_date for N trading days.
    CRITICAL: This tool must ONLY be called by the backtest runner for scoring 
    and evaluation, NEVER by the orchestrator/agents for prediction.
    
    :param ticker: One of JNJ, NVO, PFE, AMGN, GSK
    :param as_of_date: ISO date (YYYY-MM-DD) which is the starting point of the return
    :param forward_days: Number of trading days forward to measure return (default 5)
    :return: JSON string with start price, end price, percentage return, and status
    """
    ticker = ticker.upper().strip()
    
    try:
        yf_ticker = yf.Ticker(ticker)
        
        # Fetch 30 days of data starting from as_of_date to ensure we get N trading days
        start_dt = datetime.strptime(as_of_date, "%Y-%m-%d")
        end_dt = start_dt + timedelta(days=45) # 45 calendar days is plenty for 5-10 trading days
        
        df = yf_ticker.history(start=as_of_date, end=end_dt.strftime("%Y-%m-%d"))
        
        if len(df) < 2:
            return json.dumps({
                "ticker": ticker,
                "as_of_date": as_of_date,
                "error": f"Insufficient trading days found after {as_of_date} to calculate returns."
            })
            
        # Get start closing price (first available trading day on/after as_of_date)
        start_date = df.index[0].strftime("%Y-%m-%d")
        start_price = round(float(df.iloc[0]["Close"]), 2)
        
        # Get price after N trading days (or the last available row if there are fewer than N)
        target_idx = min(forward_days, len(df) - 1)
        end_date = df.index[target_idx].strftime("%Y-%m-%d")
        end_price = round(float(df.iloc[target_idx]["Close"]), 2)
        
        # Calculate return
        forward_return = round(((end_price - start_price) / start_price) * 100, 2)
        
        return json.dumps({
            "ticker": ticker,
            "as_of_date": as_of_date,
            "trading_days_requested": forward_days,
            "trading_days_actual": target_idx,
            "start_date": start_date,
            "start_price": start_price,
            "end_date": end_date,
            "end_price": end_price,
            "forward_return_pct": forward_return
        }, indent=2)
        
    except Exception as e:
        logger.error(f"Error calculating forward returns for {ticker} as of {as_of_date}: {e}")
        return json.dumps({
            "ticker": ticker,
            "as_of_date": as_of_date,
            "error": str(e)
        })

if __name__ == "__main__":
    mcp.run()
