#!/usr/bin/env python3
"""
BTC Short-Term Pattern Analysis with Volatility Percentile
Re-analyzes patterns using both momentum_percentile and volatility_percentile
"""

import psycopg2
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Tuple
import json

def get_db_connection():
    """Get PostgreSQL connection"""
    return psycopg2.connect(
        host='localhost',
        database='rec_io_db',
        user='rec_io_user',
        password='rec_io_password'
    )

def load_btc_data(limit: int = None):
    """Load BTC price history with momentum and volatility percentiles"""
    conn = get_db_connection()
    
    query = """
    SELECT 
        timestamp,
        open,
        high,
        low,
        close,
        momentum,
        momentum_percentile,
        volatility,
        volatility_percentile
    FROM historical_data.btc_price_history
    WHERE momentum_percentile IS NOT NULL 
      AND volatility_percentile IS NOT NULL
      AND timestamp >= '2020-08-25'
    ORDER BY timestamp
    """
    
    if limit:
        query += f" LIMIT {limit}"
    
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # Calculate forward returns
    df['return_2min'] = (df['close'].shift(-2) - df['close']) / df['close'] * 100
    df['return_5min'] = (df['close'].shift(-5) - df['close']) / df['close'] * 100
    df['return_10min'] = (df['close'].shift(-10) - df['close']) / df['close'] * 100
    
    # Calculate price trends
    df['trend_5min'] = (df['close'] - df['close'].shift(5)) / df['close'].shift(5) * 100
    df['trend_10min'] = (df['close'] - df['close'].shift(10)) / df['close'].shift(10) * 100
    
    # Calculate high-low range
    df['range_5min'] = ((df['high'].rolling(5).max() - df['low'].rolling(5).min()) / df['close'].rolling(5).mean()) * 100
    
    # Calculate candlestick sequences
    df['is_green'] = df['close'] > df['open']
    df['green_ratio_5min'] = df['is_green'].rolling(5).sum() / 5
    
    return df

def analyze_pattern(df: pd.DataFrame, name: str, conditions: Dict) -> Dict:
    """Analyze a specific pattern and return statistics"""
    mask = pd.Series(True, index=df.index)
    
    for col, condition in conditions.items():
        if isinstance(condition, dict):
            if 'min' in condition:
                mask &= df[col] >= condition['min']
            if 'max' in condition:
                mask &= df[col] <= condition['max']
            if 'gt' in condition:
                mask &= df[col] > condition['gt']
            if 'lt' in condition:
                mask &= df[col] < condition['lt']
        elif isinstance(condition, list):
            # Range condition
            mask &= (df[col] >= condition[0]) & (df[col] <= condition[1])
    
    subset = df[mask].copy()
    
    if len(subset) == 0:
        return {
            'name': name,
            'sample_size': 0,
            'conditions': conditions
        }
    
    # Remove rows where forward returns are NaN (end of dataset)
    subset = subset[subset['return_2min'].notna() & subset['return_5min'].notna()]
    
    if len(subset) == 0:
        return {
            'name': name,
            'sample_size': 0,
            'conditions': conditions
        }
    
    results = {
        'name': name,
        'sample_size': len(subset),
        'conditions': conditions,
        '2min': {
            'positive_rate': (subset['return_2min'] > 0).mean() * 100,
            'avg_return': subset['return_2min'].mean(),
            'median_return': subset['return_2min'].median(),
            'win_rate_01pct': (subset['return_2min'] > 0.1).mean() * 100,
            'win_rate_02pct': (subset['return_2min'] > 0.2).mean() * 100,
        },
        '5min': {
            'positive_rate': (subset['return_5min'] > 0).mean() * 100,
            'avg_return': subset['return_5min'].mean(),
            'median_return': subset['return_5min'].median(),
            'win_rate_01pct': (subset['return_5min'] > 0.1).mean() * 100,
            'win_rate_02pct': (subset['return_5min'] > 0.2).mean() * 100,
        },
        '10min': {
            'positive_rate': (subset['return_10min'] > 0).mean() * 100,
            'avg_return': subset['return_10min'].mean(),
            'median_return': subset['return_10min'].median(),
            'win_rate_01pct': (subset['return_10min'] > 0.1).mean() * 100,
            'win_rate_02pct': (subset['return_10min'] > 0.2).mean() * 100,
        }
    }
    
    return results

def main():
    print("=" * 80)
    print("BTC SHORT-TERM PATTERN ANALYSIS WITH VOLATILITY PERCENTILE")
    print("=" * 80)
    print(f"Analysis started: {datetime.now()}\n")
    
    # Load data
    print("Loading BTC historical data...")
    df = load_btc_data()
    print(f"Loaded {len(df):,} rows")
    print(f"Date range: {df['timestamp'].min()} to {df['timestamp'].max()}\n")
    
    # Remove rows without forward returns
    df = df[df['return_2min'].notna() & df['return_5min'].notna() & df['return_10min'].notna()]
    print(f"Rows with complete forward return data: {len(df):,}\n")
    
    results = []
    
    # ===== ORIGINAL PATTERNS WITH VOLATILITY PERCENTILE FILTERS =====
    
    print("Analyzing original patterns with volatility percentile filters...\n")
    
    # 1. High Volatility + Strong Downward Trend (Mean Reversion)
    results.append(analyze_pattern(df, 
        "High Volatility (90th+) + Strong Downward Trend (Mean Reversion)",
        {
            'volatility_percentile': {'gt': 90},
            'trend_5min': {'lt': -0.2},
            'range_5min': {'gt': 1.0}
        }))
    
    # 2. High Volatility + Strong Trend (either direction)
    results.append(analyze_pattern(df,
        "High Volatility (90th+) + Strong Trend (Continuation)",
        {
            'volatility_percentile': {'gt': 90},
            'trend_5min': {'gt': 0.2}  # Upward trend
        }))
    
    results.append(analyze_pattern(df,
        "High Volatility (90th+) + Strong Downward Trend (Continuation)",
        {
            'volatility_percentile': {'gt': 90},
            'trend_5min': {'lt': -0.2}  # Downward trend
        }))
    
    # 3. High Volatility + Low Momentum (Oversold)
    results.append(analyze_pattern(df,
        "High Volatility (90th+) + Low Momentum (≤5th percentile) - Oversold",
        {
            'volatility_percentile': {'gt': 90},
            'momentum_percentile': {'lt': 5}
        }))
    
    # ===== NEW PATTERNS USING VOLATILITY PERCENTILE =====
    
    print("Analyzing new patterns using volatility percentile combinations...\n")
    
    # Extreme Volatility + Low Momentum
    results.append(analyze_pattern(df,
        "Extreme Volatility (95th+) + Low Momentum (≤10th percentile)",
        {
            'volatility_percentile': {'gt': 95},
            'momentum_percentile': {'lt': 10}
        }))
    
    # Extreme Volatility + High Momentum (Overbought)
    results.append(analyze_pattern(df,
        "Extreme Volatility (95th+) + High Momentum (≥90th percentile) - Overbought",
        {
            'volatility_percentile': {'gt': 95},
            'momentum_percentile': {'gt': 90}
        }))
    
    # Moderate Volatility + Extreme Momentum
    results.append(analyze_pattern(df,
        "Moderate Volatility (50th-75th) + Extreme Low Momentum (≤5th percentile)",
        {
            'volatility_percentile': [50, 75],
            'momentum_percentile': {'lt': 5}
        }))
    
    # Low Volatility + High Momentum (Breakout potential)
    results.append(analyze_pattern(df,
        "Low Volatility (≤25th) + High Momentum (≥80th percentile) - Breakout",
        {
            'volatility_percentile': {'lt': 25},
            'momentum_percentile': {'gt': 80}
        }))
    
    # High Volatility + Neutral Momentum (Volatility expansion)
    results.append(analyze_pattern(df,
        "High Volatility (90th+) + Neutral Momentum (40th-60th percentile)",
        {
            'volatility_percentile': {'gt': 90},
            'momentum_percentile': [40, 60]
        }))
    
    # ===== VOLATILITY PERCENTILE BUCKETS =====
    
    print("Analyzing volatility percentile buckets with momentum...\n")
    
    # Low volatility buckets
    for vol_bucket in [(0, 10), (10, 25), (25, 50)]:
        for mom_bucket in [(-99, -80), (-20, 20), (80, 99)]:
            vol_name = f"Vol {vol_bucket[0]}-{vol_bucket[1]}th"
            mom_name = f"Mom {mom_bucket[0]}-{mom_bucket[1]}"
            results.append(analyze_pattern(df,
                f"{vol_name} + Momentum {mom_name}",
                {
                    'volatility_percentile': list(vol_bucket),
                    'momentum_percentile': list(mom_bucket)
                }))
    
    # High volatility buckets
    for vol_bucket in [(75, 90), (90, 95), (95, 100)]:
        for mom_bucket in [(-99, -80), (-20, 20), (80, 99)]:
            vol_name = f"Vol {vol_bucket[0]}-{vol_bucket[1]}th"
            mom_name = f"Mom {mom_bucket[0]}-{mom_bucket[1]}"
            results.append(analyze_pattern(df,
                f"{vol_name} + Momentum {mom_name}",
                {
                    'volatility_percentile': list(vol_bucket),
                    'momentum_percentile': list(mom_bucket)
                }))
    
    # ===== FILTER RESULTS =====
    
    # Filter to only meaningful patterns (sample size > 100, positive rate > 52% or < 48%)
    meaningful_results = []
    for r in results:
        if r['sample_size'] > 100:
            # Check if pattern shows edge (positive rate significantly different from 50%)
            if (r['2min']['positive_rate'] > 52 or r['2min']['positive_rate'] < 48 or
                r['5min']['positive_rate'] > 52 or r['5min']['positive_rate'] < 48):
                meaningful_results.append(r)
    
    # Sort by 2-minute positive rate (highest first)
    meaningful_results.sort(key=lambda x: x['2min']['positive_rate'], reverse=True)
    
    # ===== GENERATE REPORT =====
    
    print("\n" + "=" * 80)
    print("ANALYSIS RESULTS")
    print("=" * 80)
    
    print(f"\nTotal patterns analyzed: {len(results)}")
    print(f"Meaningful patterns (sample > 100, edge > 2%): {len(meaningful_results)}\n")
    
    print("TOP 20 PATTERNS BY 2-MINUTE POSITIVE RATE:\n")
    print(f"{'Pattern Name':<60} {'Sample':<10} {'2min%':<8} {'5min%':<8} {'2minAvg':<10} {'5minAvg':<10}")
    print("-" * 120)
    
    for i, r in enumerate(meaningful_results[:20], 1):
        print(f"{i:2d}. {r['name']:<58} {r['sample_size']:>8,}  {r['2min']['positive_rate']:>6.1f}%  {r['5min']['positive_rate']:>6.1f}%  {r['2min']['avg_return']:>8.3f}%  {r['5min']['avg_return']:>8.3f}%")
    
    # Save detailed results to JSON
    output_file = f"btc_pattern_analysis_with_volatility_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, 'w') as f:
        json.dump(meaningful_results, f, indent=2, default=str)
    
    print(f"\n\nDetailed results saved to: {output_file}")
    print(f"\nAnalysis completed: {datetime.now()}")

if __name__ == "__main__":
    main()

