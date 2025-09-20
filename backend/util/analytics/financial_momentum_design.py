#!/usr/bin/env python3
"""
Financial Momentum Calculation Design
Handles trading gaps and market open scenarios for financial symbols
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, Tuple

def calculate_financial_momentum(df: pd.DataFrame, index: int, symbol: str) -> Optional[float]:
    """
    Calculate momentum for financial symbols with gap-aware logic.
    
    Args:
        df: DataFrame with OHLCV data
        index: Current row index
        symbol: Symbol name (e.g., 'SPX')
        
    Returns:
        Momentum score or None if insufficient data
    """
    
    if index < 4:  # Need at least 4 minutes of data
        return None
    
    current_timestamp = df.loc[index, 'timestamp']
    current_price = df.loc[index, 'close']
    
    # Determine trading session context
    session_context = get_trading_session_context(current_timestamp)
    
    if session_context == 'market_open':
        return calculate_market_open_momentum(df, index, symbol)
    elif session_context == 'regular_hours':
        return calculate_regular_hours_momentum(df, index)
    else:  # market_close
        return calculate_regular_hours_momentum(df, index)

def get_trading_session_context(timestamp: pd.Timestamp) -> str:
    """Determine what part of trading session we're in"""
    time_of_day = timestamp.time()
    
    # Market open: 9:30 - 10:00 AM
    if pd.Timestamp('09:30:00').time() <= time_of_day <= pd.Timestamp('10:00:00').time():
        return 'market_open'
    # Market close: 3:30 - 4:00 PM  
    elif pd.Timestamp('15:30:00').time() <= time_of_day <= pd.Timestamp('16:00:00').time():
        return 'market_close'
    else:
        return 'regular_hours'

def calculate_market_open_momentum(df: pd.DataFrame, index: int, symbol: str) -> Optional[float]:
    """
    Calculate momentum during market open (9:30-10:00 AM).
    Blends overnight gap momentum with available intraday data.
    """
    
    current_price = df.loc[index, 'close']
    current_timestamp = df.loc[index, 'timestamp']
    
    # Get previous trading day's close
    prev_close = get_previous_close_price(df, index, symbol)
    if prev_close is None:
        return None
    
    # Calculate overnight gap momentum
    gap_momentum = ((current_price - prev_close) / prev_close) * 100
    
    # Calculate available intraday momentum components
    intraday_components = []
    weights = []
    
    # Try to get short-term momentum (1-4 minutes)
    for minutes_back, weight in [(1, 0.30), (2, 0.25), (3, 0.20), (4, 0.15)]:
        if index >= minutes_back:
            past_price = df.loc[index - minutes_back, 'close']
            momentum_component = ((current_price - past_price) / past_price) * 100
            intraday_components.append(momentum_component)
            weights.append(weight)
    
    # Try to get medium-term momentum (15m, 30m) - likely won't exist at market open
    for minutes_back, weight in [(15, 0.05), (30, 0.05)]:
        if index >= minutes_back and is_same_trading_session(df, index, index - minutes_back):
            past_price = df.loc[index - minutes_back, 'close']
            momentum_component = ((current_price - past_price) / past_price) * 100
            intraday_components.append(momentum_component)
            weights.append(weight)
    
    # Blend gap momentum with intraday momentum
    if not intraday_components:
        # Only gap momentum available (first few minutes after open)
        return gap_momentum * 0.5  # Scale down gap momentum
    else:
        # Blend gap momentum with intraday momentum
        intraday_momentum = sum(comp * weight for comp, weight in zip(intraday_components, weights))
        total_intraday_weight = sum(weights)
        
        # Weight gap momentum higher early in session, lower as session progresses
        minutes_since_open = get_minutes_since_market_open(current_timestamp)
        gap_weight = max(0.3, 0.8 - (minutes_since_open / 30.0) * 0.5)  # 0.8 -> 0.3 over 30 minutes
        intraday_weight = 1.0 - gap_weight
        
        # Normalize intraday momentum by actual weights used
        if total_intraday_weight > 0:
            normalized_intraday = intraday_momentum / total_intraday_weight
        else:
            normalized_intraday = 0
            
        final_momentum = (gap_momentum * gap_weight) + (normalized_intraday * intraday_weight)
        return final_momentum

def calculate_regular_hours_momentum(df: pd.DataFrame, index: int) -> Optional[float]:
    """
    Calculate momentum during regular trading hours.
    Uses standard momentum formula when sufficient data exists.
    """
    
    if index < 30:  # Need 30 minutes of lookback
        # Use partial momentum calculation
        return calculate_partial_momentum(df, index)
    
    # Standard momentum calculation (same as crypto)
    current_price = df.loc[index, 'close']
    
    # Check if all lookback periods are within same trading session
    if not all_lookbacks_same_session(df, index, [1, 2, 3, 4, 15, 30]):
        return calculate_partial_momentum(df, index)
    
    # Standard calculation
    P_now = current_price
    P_1m  = df.loc[index - 1, 'close']
    P_2m  = df.loc[index - 2, 'close']
    P_3m  = df.loc[index - 3, 'close']
    P_4m  = df.loc[index - 4, 'close']
    P_15m = df.loc[index - 15, 'close']
    P_30m = df.loc[index - 30, 'close']

    score = (
        ((P_now - P_1m)  / P_1m)  * 0.30 +
        ((P_now - P_2m)  / P_2m)  * 0.25 +
        ((P_now - P_3m)  / P_3m)  * 0.20 +
        ((P_now - P_4m)  / P_4m)  * 0.15 +
        ((P_now - P_15m) / P_15m) * 0.05 +
        ((P_now - P_30m) / P_30m) * 0.05
    ) * 100

    return round(score, 4)

def calculate_partial_momentum(df: pd.DataFrame, index: int) -> Optional[float]:
    """
    Calculate momentum with whatever valid lookback periods are available.
    Reweight the components proportionally.
    """
    
    if index < 1:
        return None
        
    current_price = df.loc[index, 'close']
    components = []
    weights = []
    
    # Try each lookback period
    lookback_configs = [(1, 0.30), (2, 0.25), (3, 0.20), (4, 0.15), (15, 0.05), (30, 0.05)]
    
    for minutes_back, weight in lookback_configs:
        if (index >= minutes_back and 
            is_same_trading_session(df, index, index - minutes_back)):
            
            past_price = df.loc[index - minutes_back, 'close']
            momentum_component = ((current_price - past_price) / past_price)
            components.append(momentum_component)
            weights.append(weight)
    
    if not components:
        return None
    
    # Normalize weights to sum to 1.0
    total_weight = sum(weights)
    normalized_weights = [w / total_weight for w in weights]
    
    # Calculate weighted momentum
    momentum = sum(comp * weight for comp, weight in zip(components, normalized_weights)) * 100
    return round(momentum, 4)

def get_previous_close_price(df: pd.DataFrame, current_index: int, symbol: str) -> Optional[float]:
    """
    Get the previous trading day's closing price.
    Looks backwards for the last price before market gap.
    """
    
    current_timestamp = df.loc[current_index, 'timestamp']
    
    # Look backwards for a significant time gap (> 30 minutes indicates overnight/weekend)
    for i in range(current_index - 1, max(0, current_index - 100), -1):
        past_timestamp = df.loc[i, 'timestamp']
        time_diff = (current_timestamp - past_timestamp).total_seconds() / 60  # minutes
        
        if time_diff > 30:  # Found a gap > 30 minutes
            return df.loc[i, 'close']
    
    return None

def is_same_trading_session(df: pd.DataFrame, index1: int, index2: int) -> bool:
    """
    Check if two indices are from the same trading session.
    Returns False if there's a significant gap between them.
    """
    
    if index1 < 0 or index2 < 0 or index1 >= len(df) or index2 >= len(df):
        return False
        
    timestamp1 = df.loc[index1, 'timestamp']
    timestamp2 = df.loc[index2, 'timestamp']
    
    # If timestamps are on different days, definitely different sessions
    if timestamp1.date() != timestamp2.date():
        return False
    
    # Check for gaps > 5 minutes (indicates session break)
    time_diff = abs((timestamp1 - timestamp2).total_seconds() / 60)
    return time_diff <= (abs(index1 - index2) * 1.5)  # Allow 1.5 minutes per index difference

def all_lookbacks_same_session(df: pd.DataFrame, current_index: int, lookback_periods: list) -> bool:
    """Check if all lookback periods are within the same trading session"""
    
    for period in lookback_periods:
        if current_index < period:
            continue
        if not is_same_trading_session(df, current_index, current_index - period):
            return False
    return True

def get_minutes_since_market_open(timestamp: pd.Timestamp) -> int:
    """Calculate minutes since 9:30 AM market open"""
    
    market_open = timestamp.replace(hour=9, minute=30, second=0, microsecond=0)
    if timestamp < market_open:
        return 0
    
    diff = (timestamp - market_open).total_seconds() / 60
    return int(diff)

# Example usage and testing
if __name__ == "__main__":
    # This would be integrated into the main momentum_generator_pg.py
    print("Financial Momentum Calculation Design")
    print("Key features:")
    print("- Gap-aware momentum for market opens")
    print("- Session-aware calculations")
    print("- Partial momentum when insufficient data")
    print("- Overnight gap integration")
