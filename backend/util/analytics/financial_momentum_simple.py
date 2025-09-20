#!/usr/bin/env python3
"""
Simple Financial Momentum Calculation
Uses overnight gap as substitute for missing deltas until live data accumulates
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Optional

def calculate_financial_momentum_simple(df: pd.DataFrame, index: int) -> Optional[float]:
    """
    Calculate momentum for financial symbols using gap substitution method.
    
    At market open:
    - All deltas (1m, 2m, 3m, 4m, 15m, 30m) use overnight gap
    - As live data accumulates, real deltas replace gap deltas
    - By 30 minutes after open, all deltas are live data
    
    Args:
        df: DataFrame with OHLCV data
        index: Current row index
        
    Returns:
        Momentum score or None if insufficient data
    """
    
    if index < 1:
        return None
    
    current_price = df.loc[index, 'close']
    current_timestamp = df.loc[index, 'timestamp']
    
    # Get overnight gap (if we're early in trading session)
    overnight_gap = get_overnight_gap_delta(df, index)
    
    # Calculate each momentum component
    deltas = []
    weights = [0.30, 0.25, 0.20, 0.15, 0.05, 0.05]  # 1m, 2m, 3m, 4m, 15m, 30m
    lookbacks = [1, 2, 3, 4, 15, 30]
    
    for i, (minutes_back, weight) in enumerate(zip(lookbacks, weights)):
        
        if index >= minutes_back and is_same_trading_session(df, index, index - minutes_back):
            # We have live data for this lookback period
            past_price = df.loc[index - minutes_back, 'close']
            delta = (current_price - past_price) / past_price
            
        elif overnight_gap is not None:
            # Use overnight gap as substitute
            delta = overnight_gap
            
        else:
            # No data available, skip this component
            continue
            
        deltas.append(delta * weight)
    
    if not deltas:
        return None
    
    # Sum weighted deltas and convert to percentage
    momentum = sum(deltas) * 100
    return round(momentum, 4)

def get_overnight_gap_delta(df: pd.DataFrame, current_index: int) -> Optional[float]:
    """
    Get overnight gap delta if we're early in the trading session.
    Returns None if we're well into the trading day.
    """
    
    current_timestamp = df.loc[current_index, 'timestamp']
    current_price = df.loc[current_index, 'close']
    
    # Only use gap substitution in first 30 minutes of trading
    if not is_early_trading_session(current_timestamp):
        return None
    
    # Find previous trading day's close
    prev_close = find_previous_close(df, current_index)
    if prev_close is None:
        return None
    
    # Calculate overnight gap delta
    gap_delta = (current_price - prev_close) / prev_close
    return gap_delta

def is_early_trading_session(timestamp: pd.Timestamp) -> bool:
    """
    Check if we're in the first 30 minutes of trading (9:30-10:00 AM).
    This is when we want to use gap substitution.
    """
    time_of_day = timestamp.time()
    
    return (pd.Timestamp('09:30:00').time() <= time_of_day <= pd.Timestamp('10:00:00').time())

def find_previous_close(df: pd.DataFrame, current_index: int) -> Optional[float]:
    """
    Find the previous trading day's closing price by looking for a significant time gap.
    """
    
    current_timestamp = df.loc[current_index, 'timestamp']
    
    # Look backwards for a gap > 30 minutes (indicates overnight/weekend break)
    for i in range(current_index - 1, max(0, current_index - 200), -1):
        past_timestamp = df.loc[i, 'timestamp']
        time_diff = (current_timestamp - past_timestamp).total_seconds() / 60  # minutes
        
        if time_diff > 30:  # Found overnight/weekend gap
            return df.loc[i, 'close']
    
    return None

def is_same_trading_session(df: pd.DataFrame, index1: int, index2: int) -> bool:
    """
    Check if two indices are from the same trading session.
    Returns False if there's a gap > 5 minutes between them.
    """
    
    if index1 < 0 or index2 < 0 or index1 >= len(df) or index2 >= len(df):
        return False
        
    timestamp1 = df.loc[index1, 'timestamp']
    timestamp2 = df.loc[index2, 'timestamp']
    
    # Different dates = different sessions
    if timestamp1.date() != timestamp2.date():
        return False
    
    # Check for gaps > 5 minutes
    time_diff = abs((timestamp1 - timestamp2).total_seconds() / 60)
    expected_diff = abs(index1 - index2) * 1.5  # Allow 1.5 minutes per index step
    
    return time_diff <= expected_diff

def fill_missing_momentum_financial(symbol: str, start_date: str = None, end_date: str = None):
    """
    Fill missing momentum values for financial symbols using gap substitution method.
    
    This would replace the existing fill_missing_momentum_in_db function for financial symbols.
    """
    
    print(f"Filling missing momentum for financial symbol {symbol} using gap substitution...")
    
    # Load data from database (using existing function)
    from momentum_generator_pg import load_data_from_db, update_momentum_in_db
    
    df = load_data_from_db(symbol, start_date, end_date)
    
    # Find rows where momentum is null
    mask = df['momentum'].isnull()
    indices = df[mask].index
    print(f"Found {len(indices)} rows with missing momentum.")
    
    if len(indices) == 0:
        print("No missing momentum values to fill.")
        return
    
    # Calculate momentum for missing rows using financial method
    calculated_indices = []
    for i in indices:
        momentum = calculate_financial_momentum_simple(df, i)
        if momentum is not None:
            df.at[i, 'momentum'] = momentum
            calculated_indices.append(i)
    
    # Update database
    update_momentum_in_db(symbol, df, calculated_indices, update_percentiles=True)
    print(f"Filled missing momentum for {len(calculated_indices)} rows using gap substitution method.")

# Example of how this works:
def example_momentum_progression():
    """
    Example showing how momentum calculation evolves through the morning:
    
    9:30 AM: momentum = gap * (0.30 + 0.25 + 0.20 + 0.15 + 0.05 + 0.05) = gap * 1.00
    9:31 AM: momentum = (1m_live * 0.30) + (gap * 0.70)  
    9:32 AM: momentum = (1m_live * 0.30) + (2m_live * 0.25) + (gap * 0.45)
    9:33 AM: momentum = (1m_live * 0.30) + (2m_live * 0.25) + (3m_live * 0.20) + (gap * 0.25)
    9:34 AM: momentum = (1m_live * 0.30) + (2m_live * 0.25) + (3m_live * 0.20) + (4m_live * 0.15) + (gap * 0.10)
    9:45 AM: momentum = (1-4m_live * 0.90) + (15m_live * 0.05) + (gap * 0.05)
    10:00 AM: momentum = all live data (1m, 2m, 3m, 4m, 15m, 30m)
    """
    
    print("Momentum Evolution Example:")
    print("9:30 AM: 100% gap momentum")
    print("9:31 AM: 30% live (1m), 70% gap") 
    print("9:32 AM: 55% live (1m+2m), 45% gap")
    print("9:33 AM: 75% live (1m+2m+3m), 25% gap")
    print("9:34 AM: 90% live (1m+2m+3m+4m), 10% gap")
    print("9:45 AM: 95% live (includes 15m), 5% gap")
    print("10:00 AM: 100% live data")

if __name__ == "__main__":
    example_momentum_progression()
