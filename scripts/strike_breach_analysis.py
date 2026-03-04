#!/usr/bin/env python3
"""
Strike Breach Analysis
Analyzes how often the price at the next hour (HH:00:00) breaches 
the immediate strike range defined at HH:05:00
"""

import psycopg2
import sys
from datetime import datetime, timedelta
from collections import defaultdict

def get_postgresql_connection():
    """Get PostgreSQL connection"""
    try:
        return psycopg2.connect(
            host="localhost",
            database="rec_io_db",
            user="rec_io_user",
            password="rec_io_password"
        )
    except Exception as e:
        print(f"Failed to connect to PostgreSQL: {e}")
        return None

def calculate_strikes(price, strike_spacing):
    """
    Calculate immediate strikes above and below a price.
    
    Returns: (lower_strike, upper_strike)
    """
    # Lower strike: floor to nearest strike spacing
    lower_strike = int((price // strike_spacing) * strike_spacing)
    
    # Upper strike: ceiling to nearest strike spacing
    upper_strike = int(((price // strike_spacing) + 1) * strike_spacing)
    
    return lower_strike, upper_strike

def analyze_strike_breaches(symbol="BTC", strike_spacing=250, months_back=12):
    """
    Main analysis function
    
    Args:
        symbol: "BTC" or "ETH"
        strike_spacing: Strike spacing in dollars (250 for BTC, 20 for ETH)
        months_back: Number of months to look back (default 12)
    """
    conn = get_postgresql_connection()
    if not conn:
        print("❌ Failed to connect to database")
        return
    
    cursor = conn.cursor()
    
    table_name = f"{symbol.lower()}_price_history"
    
    # Calculate date cutoff (past N months)
    cutoff_date = datetime.now() - timedelta(days=months_back * 30)
    
    print(f"🔍 Analyzing {symbol} strike breaches (past {months_back} months)...")
    print(f"📅 Date range: {cutoff_date.strftime('%Y-%m-%d')} to present")
    print("=" * 60)
    
    # Get all prices at HH:05:00 (5 minutes past each hour) within date range
    query = f"""
        SELECT 
            timestamp,
            close as price
        FROM historical_data.{table_name}
        WHERE EXTRACT(MINUTE FROM timestamp) = 5
          AND EXTRACT(SECOND FROM timestamp) = 0
          AND timestamp >= %s
        ORDER BY timestamp
    """
    
    cursor.execute(query, (cutoff_date,))
    five_min_prices = cursor.fetchall()
    
    print(f"📊 Found {len(five_min_prices)} instances at HH:05:00 (past {months_back} months)")
    
    if len(five_min_prices) == 0:
        print("❌ No data found at HH:05:00")
        conn.close()
        return
    
    # Statistics
    total_instances = 0
    breaches = 0
    breaches_above = 0
    breaches_below = 0
    within_range = 0
    
    # For detailed analysis
    breach_details = []
    
    print("\n🔎 Processing each instance...")
    
    for idx, (timestamp, price) in enumerate(five_min_prices):
        if price is None:
            continue
        
        # Calculate strikes
        lower_strike, upper_strike = calculate_strikes(price, strike_spacing)
        
        # Get the next hour (HH:00:00 of the next hour)
        # If current is 10:05:00, we want 11:00:00
        next_hour = timestamp.replace(minute=0, second=0) + timedelta(hours=1)
        
        # Query for the price at the next hour
        next_hour_query = f"""
            SELECT close
            FROM historical_data.{table_name}
            WHERE timestamp = %s
        """
        
        cursor.execute(next_hour_query, (next_hour,))
        result = cursor.fetchone()
        
        if result is None or result[0] is None:
            # No data for next hour, skip
            continue
        
        next_hour_price = result[0]
        total_instances += 1
        
        # Check if price is outside strike range
        is_breach = False
        breach_type = None
        
        if next_hour_price < lower_strike:
            is_breach = True
            breach_type = "below"
            breaches_below += 1
        elif next_hour_price > upper_strike:
            is_breach = True
            breach_type = "above"
            breaches_above += 1
        else:
            within_range += 1
        
        if is_breach:
            breaches += 1
            breach_details.append({
                'timestamp': timestamp,
                'price_at_05': price,
                'lower_strike': lower_strike,
                'upper_strike': upper_strike,
                'next_hour': next_hour,
                'next_hour_price': next_hour_price,
                'breach_type': breach_type,
                'breach_amount': lower_strike - next_hour_price if breach_type == "below" else next_hour_price - upper_strike
            })
        
        # Progress indicator
        if (idx + 1) % 1000 == 0:
            print(f"  Processed {idx + 1}/{len(five_min_prices)} instances...")
    
    conn.close()
    
    # Calculate statistics
    breach_percentage = (breaches / total_instances * 100) if total_instances > 0 else 0
    above_percentage = (breaches_above / total_instances * 100) if total_instances > 0 else 0
    below_percentage = (breaches_below / total_instances * 100) if total_instances > 0 else 0
    within_percentage = (within_range / total_instances * 100) if total_instances > 0 else 0
    
    # Print results
    print("\n" + "=" * 60)
    print(f"📈 RESULTS - {symbol} (Past {months_back} Months)")
    print("=" * 60)
    print(f"Total instances analyzed: {total_instances:,}")
    print(f"\nBreach Statistics:")
    print(f"  Total breaches: {breaches:,} ({breach_percentage:.2f}%)")
    print(f"  Breaches above upper strike: {breaches_above:,} ({above_percentage:.2f}%)")
    print(f"  Breaches below lower strike: {breaches_below:,} ({below_percentage:.2f}%)")
    print(f"  Stayed within range: {within_range:,} ({within_percentage:.2f}%)")
    
    # Additional statistics
    if breach_details:
        breach_amounts = [d['breach_amount'] for d in breach_details]
        avg_breach = sum(breach_amounts) / len(breach_amounts)
        max_breach = max(breach_amounts)
        min_breach = min(breach_amounts)
        
        print(f"\nBreach Amount Statistics:")
        print(f"  Average breach amount: ${avg_breach:,.2f}")
        print(f"  Maximum breach amount: ${max_breach:,.2f}")
        print(f"  Minimum breach amount: ${min_breach:,.2f}")
        
        # Show some examples
        print(f"\n📋 Sample Breaches (first 10):")
        for i, detail in enumerate(breach_details[:10]):
            print(f"  {i+1}. {detail['timestamp']}: Price ${detail['price_at_05']:,.2f} → "
                  f"Strikes [${detail['lower_strike']:,}, ${detail['upper_strike']:,}] → "
                  f"Next hour: ${detail['next_hour_price']:,.2f} ({detail['breach_type']} by ${detail['breach_amount']:,.2f})")
    
    print("\n" + "=" * 60)
    print("✅ Analysis complete")
    
    return {
        'symbol': symbol,
        'total_instances': total_instances,
        'breaches': breaches,
        'breach_percentage': breach_percentage,
        'breaches_above': breaches_above,
        'breaches_below': breaches_below,
        'within_range': within_range,
        'avg_breach': avg_breach if breach_details else 0
    }

if __name__ == "__main__":
    # Run for both BTC and ETH
    print("=" * 60)
    print("STRIKE BREACH ANALYSIS - PAST 12 MONTHS")
    print("=" * 60)
    print()
    
    # BTC Analysis
    btc_results = analyze_strike_breaches(symbol="BTC", strike_spacing=250, months_back=12)
    
    print("\n\n")
    
    # ETH Analysis
    eth_results = analyze_strike_breaches(symbol="ETH", strike_spacing=20, months_back=12)
    
    # Summary comparison
    print("\n\n" + "=" * 60)
    print("📊 SUMMARY COMPARISON (Past 12 Months)")
    print("=" * 60)
    print(f"{'Metric':<30} {'BTC':<20} {'ETH':<20}")
    print("-" * 70)
    print(f"{'Total Instances':<30} {btc_results['total_instances']:<20,} {eth_results['total_instances']:<20,}")
    print(f"{'Breach Rate':<30} {btc_results['breach_percentage']:<20.2f}% {eth_results['breach_percentage']:<20.2f}%")
    print(f"{'Breaches Above':<30} {btc_results['breaches_above']:<20,} {eth_results['breaches_above']:<20,}")
    print(f"{'Breaches Below':<30} {btc_results['breaches_below']:<20,} {eth_results['breaches_below']:<20,}")
    print(f"{'Stayed Within Range':<30} {btc_results['within_range']:<20,} {eth_results['within_range']:<20,}")
    print(f"{'Avg Breach Amount':<30} ${btc_results['avg_breach']:<19.2f} ${eth_results['avg_breach']:<19.2f}")
    print("=" * 60)








