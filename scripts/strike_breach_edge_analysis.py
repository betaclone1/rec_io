#!/usr/bin/env python3
"""
Strike Breach Edge Analysis
Analyzes potential trading edges based on strike breach probabilities
"""

import psycopg2
from datetime import datetime, timedelta

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
    """Calculate immediate strikes above and below a price."""
    lower_strike = int((price // strike_spacing) * strike_spacing)
    upper_strike = int(((price // strike_spacing) + 1) * strike_spacing)
    return lower_strike, upper_strike

def analyze_edge_opportunities(symbol="BTC", strike_spacing=250, months_back=12):
    """
    Analyze potential edge opportunities
    
    Strategy ideas:
    1. Reverse trade: Bet on staying within range (YES lower + NO upper)
    2. Single-leg directional: Bet on breach direction
    3. Wider strikes: Use 2-3 strikes away instead of immediate
    """
    conn = get_postgresql_connection()
    if not conn:
        print("❌ Failed to connect to database")
        return
    
    cursor = conn.cursor()
    table_name = f"{symbol.lower()}_price_history"
    cutoff_date = datetime.now() - timedelta(days=months_back * 30)
    
    print(f"🔍 Analyzing {symbol} edge opportunities (past {months_back} months)...")
    print("=" * 60)
    
    # Get all prices at HH:05:00
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
    
    # Strategy 1: Reverse trade (bet on staying within range)
    # Market prices breach at ~90% ($0.80 cost), actual is ~67%
    # So staying within range: market prices at ~10%, actual is ~33%
    reverse_wins = 0
    reverse_total = 0
    
    # Strategy 2: Single-leg directional (bet on breach direction)
    # If breach happens, which direction is more likely?
    above_wins = 0
    below_wins = 0
    above_total = 0
    below_total = 0
    
    # Strategy 3: Wider strikes (2 strikes away)
    wider_breaches = 0
    wider_total = 0
    
    # Strategy 4: One-sided trades (bet on breach in one direction only)
    # NO on lower strike only (betting price goes below)
    no_lower_wins = 0
    no_lower_total = 0
    
    # YES on upper strike only (betting price goes above)
    yes_upper_wins = 0
    yes_upper_total = 0
    
    # Additional metrics
    breach_details = []
    
    print("\n🔎 Processing each instance...")
    
    for idx, (timestamp, price) in enumerate(five_min_prices):
        if price is None:
            continue
        
        lower_strike, upper_strike = calculate_strikes(price, strike_spacing)
        
        # Calculate wider strikes (2 strikes away)
        wider_lower = lower_strike - (strike_spacing * 2)
        wider_upper = upper_strike + (strike_spacing * 2)
        
        next_hour = timestamp.replace(minute=0, second=0) + timedelta(hours=1)
        
        next_hour_query = f"""
            SELECT close
            FROM historical_data.{table_name}
            WHERE timestamp = %s
        """
        
        cursor.execute(next_hour_query, (next_hour,))
        result = cursor.fetchone()
        
        if result is None or result[0] is None:
            continue
        
        next_hour_price = result[0]
        
        # Strategy 1: Reverse trade (bet on staying within range)
        # Cost: ~$0.20 (if breach is $0.80, staying within should be $0.20)
        # Payout: $1.00 if price stays within range
        reverse_total += 1
        if lower_strike <= next_hour_price <= upper_strike:
            reverse_wins += 1
        
        # Strategy 2: Single-leg directional
        if next_hour_price < lower_strike:
            below_total += 1
            below_wins += 1
        elif next_hour_price > upper_strike:
            above_total += 1
            above_wins += 1
        
        # Strategy 3: Wider strikes (2 strikes away)
        wider_total += 1
        if next_hour_price < wider_lower or next_hour_price > wider_upper:
            wider_breaches += 1
        
        # Strategy 4: One-sided trades
        no_lower_total += 1
        if next_hour_price < lower_strike:
            no_lower_wins += 1
        
        yes_upper_total += 1
        if next_hour_price > upper_strike:
            yes_upper_wins += 1
        
        breach_details.append({
            'timestamp': timestamp,
            'price_at_05': price,
            'next_hour_price': next_hour_price,
            'lower_strike': lower_strike,
            'upper_strike': upper_strike,
            'breached': next_hour_price < lower_strike or next_hour_price > upper_strike,
            'breach_direction': 'below' if next_hour_price < lower_strike else ('above' if next_hour_price > upper_strike else 'within')
        })
        
        if (idx + 1) % 1000 == 0:
            print(f"  Processed {idx + 1}/{len(five_min_prices)} instances...")
    
    conn.close()
    
    # Calculate statistics
    print("\n" + "=" * 60)
    print(f"📊 EDGE ANALYSIS - {symbol} (Past {months_back} Months)")
    print("=" * 60)
    
    # Strategy 1: Reverse trade (staying within range)
    reverse_win_rate = (reverse_wins / reverse_total * 100) if reverse_total > 0 else 0
    reverse_actual_prob = reverse_win_rate / 100
    breach_win_rate = 100 - reverse_win_rate
    
    print(f"\n1️⃣ TWO-LEG TRADES ANALYSIS")
    print(f"   Actual breach rate: {breach_win_rate:.2f}% ({reverse_total - reverse_wins:,}/{reverse_total:,})")
    print(f"   Actual staying within rate: {reverse_win_rate:.2f}% ({reverse_wins:,}/{reverse_total:,})")
    
    # New pricing structure
    breach_cost = 0.80
    breach_return = 1.00
    breach_profit = breach_return - breach_cost  # $0.20 profit on win
    
    staying_cost = 1.40
    staying_return = 2.00
    staying_profit = staying_return - staying_cost  # $0.60 profit on win
    
    print(f"\n   PRICING STRUCTURE:")
    print(f"      Breach bet: Costs ${breach_cost:.2f}, Returns ${breach_return:.2f} (Profit: ${breach_profit:.2f} on win)")
    print(f"      Staying within bet: Costs ${staying_cost:.2f}, Returns ${staying_return:.2f} (Profit: ${staying_profit:.2f} on win)")
    
    # Breach bet analysis
    # Expected value = (win_rate * profit) - (lose_rate * cost)
    breach_win_prob = breach_win_rate / 100
    breach_lose_prob = 1 - breach_win_prob
    breach_expected_value = (breach_win_prob * breach_profit) - (breach_lose_prob * breach_cost)
    breach_roi = (breach_expected_value / breach_cost) * 100
    
    # Staying within bet analysis
    staying_win_prob = reverse_win_rate / 100
    staying_lose_prob = 1 - staying_win_prob
    staying_expected_value = (staying_win_prob * staying_profit) - (staying_lose_prob * staying_cost)
    staying_roi = (staying_expected_value / staying_cost) * 100
    
    # Calculate implied probabilities from pricing
    # For breach: cost $0.80, return $1.00 means market thinks win prob = 0.80/1.00 = 80%
    breach_implied_prob = (breach_cost / breach_return) * 100
    # For staying: cost $1.40, return $2.00 means market thinks win prob = 1.40/2.00 = 70%
    staying_implied_prob = (staying_cost / staying_return) * 100
    
    breach_edge_pp = breach_win_rate - breach_implied_prob
    staying_edge_pp = reverse_win_rate - staying_implied_prob
    
    print(f"\n   BREACH BET (NO lower + YES upper):")
    print(f"      Market implied: {breach_implied_prob:.2f}% | Actual: {breach_win_rate:.2f}%")
    print(f"      Edge: {breach_edge_pp:+.2f}pp")
    print(f"      Expected value per bet: ${breach_expected_value:+.4f}")
    print(f"      Expected ROI: {breach_roi:+.2f}%")
    print(f"      Status: {'✅ POSITIVE' if breach_roi > 0 else '❌ NEGATIVE'}")
    
    print(f"\n   STAYING WITHIN BET (YES lower + NO upper):")
    print(f"      Market implied: {staying_implied_prob:.2f}% | Actual: {reverse_win_rate:.2f}%")
    print(f"      Edge: {staying_edge_pp:+.2f}pp")
    print(f"      Expected value per bet: ${staying_expected_value:+.4f}")
    print(f"      Expected ROI: {staying_roi:+.2f}%")
    print(f"      Status: {'✅ POSITIVE' if staying_roi > 0 else '❌ NEGATIVE'}")
    
    # Calculate total expected value over all instances
    total_breach_ev = breach_expected_value * reverse_total
    total_staying_ev = staying_expected_value * reverse_total
    print(f"\n   TOTAL EXPECTED VALUE (over {reverse_total:,} instances):")
    print(f"      Breach bet: ${total_breach_ev:+,.2f}")
    print(f"      Staying within bet: ${total_staying_ev:+,.2f}")
    
    # Strategy 2: Single-leg directional
    above_win_rate = (above_wins / above_total * 100) if above_total > 0 else 0
    below_win_rate = (below_wins / below_total * 100) if below_total > 0 else 0
    
    print(f"\n2️⃣ SINGLE-LEG DIRECTIONAL")
    print(f"   Breach above: {above_win_rate:.2f}% ({above_wins:,}/{above_total:,})")
    print(f"   Breach below: {below_win_rate:.2f}% ({below_wins:,}/{below_total:,})")
    print(f"   Note: If market prices breach at 50/50, actual is {above_win_rate:.2f}%/{below_win_rate:.2f}%")
    
    # Strategy 3: Wider strikes
    wider_breach_rate = (wider_breaches / wider_total * 100) if wider_total > 0 else 0
    print(f"\n3️⃣ WIDER STRIKES (2 strikes away = ${strike_spacing * 2} range)")
    print(f"   Breach rate: {wider_breach_rate:.2f}% ({wider_breaches:,}/{wider_total:,})")
    print(f"   vs Immediate strikes: ~67% breach rate")
    print(f"   Trade-off: Lower probability but potentially better pricing")
    
    # Strategy 4: One-sided trades
    no_lower_win_rate = (no_lower_wins / no_lower_total * 100) if no_lower_total > 0 else 0
    yes_upper_win_rate = (yes_upper_wins / yes_upper_total * 100) if yes_upper_total > 0 else 0
    
    print(f"\n4️⃣ ONE-SIDED TRADES")
    print(f"   NO on lower strike (bet price goes below): {no_lower_win_rate:.2f}% ({no_lower_wins:,}/{no_lower_total:,})")
    print(f"   YES on upper strike (bet price goes above): {yes_upper_win_rate:.2f}% ({yes_upper_wins:,}/{yes_upper_total:,})")
    print(f"   Note: Market likely prices each at ~45% (since total breach is ~90%)")
    print(f"   Actual: {no_lower_win_rate:.2f}% and {yes_upper_win_rate:.2f}%")
    
    # Summary
    print(f"\n" + "=" * 60)
    print("💡 KEY INSIGHTS")
    print("=" * 60)
    print(f"• Breach bet: Costs ${breach_cost:.2f}, Returns ${breach_return:.2f}")
    print(f"  - Market implied: {breach_implied_prob:.2f}% | Actual: {breach_win_rate:.2f}%")
    print(f"  - Edge: {breach_edge_pp:+.2f}pp | Expected ROI: {breach_roi:+.2f}%")
    print(f"  - Expected value per bet: ${breach_expected_value:+.4f}")
    print(f"• Staying within bet: Costs ${staying_cost:.2f}, Returns ${staying_return:.2f}")
    print(f"  - Market implied: {staying_implied_prob:.2f}% | Actual: {reverse_win_rate:.2f}%")
    print(f"  - Edge: {staying_edge_pp:+.2f}pp | Expected ROI: {staying_roi:+.2f}%")
    print(f"  - Expected value per bet: ${staying_expected_value:+.4f}")
    print(f"• Single-leg trades: Above {above_win_rate:.2f}% vs Below {below_win_rate:.2f}%")
    print(f"• Wider strikes breach {wider_breach_rate:.2f}% of the time")
    print(f"• One-sided: Lower breach {no_lower_win_rate:.2f}%, Upper breach {yes_upper_win_rate:.2f}%")
    
    return {
        'reverse_win_rate': reverse_win_rate,
        'breach_win_rate': breach_win_rate,
        'breach_roi': breach_roi,
        'staying_roi': staying_roi,
        'breach_edge_pp': breach_edge_pp,
        'staying_edge_pp': staying_edge_pp,
        'breach_expected_value': breach_expected_value,
        'staying_expected_value': staying_expected_value,
        'breach_implied_prob': breach_implied_prob,
        'staying_implied_prob': staying_implied_prob,
        'above_win_rate': above_win_rate,
        'below_win_rate': below_win_rate,
        'wider_breach_rate': wider_breach_rate,
        'no_lower_win_rate': no_lower_win_rate,
        'yes_upper_win_rate': yes_upper_win_rate
    }

if __name__ == "__main__":
    print("=" * 60)
    print("STRIKE BREACH EDGE ANALYSIS - PAST 12 MONTHS")
    print("=" * 60)
    print()
    
    # BTC Analysis
    btc_results = analyze_edge_opportunities(symbol="BTC", strike_spacing=250, months_back=12)
    
    print("\n\n")
    
    # ETH Analysis
    eth_results = analyze_edge_opportunities(symbol="ETH", strike_spacing=20, months_back=12)
    
    # Comparison
    print("\n\n" + "=" * 60)
    print("📊 COMPARISON SUMMARY")
    print("=" * 60)
    print(f"Pricing: Breach bet costs $0.80 (returns $1.00), Staying within costs $1.40 (returns $2.00)")
    print("=" * 60)
    print(f"{'Metric':<45} {'BTC':<25} {'ETH':<25}")
    print("-" * 95)
    print(f"{'Actual Breach Rate':<45} {btc_results['breach_win_rate']:<25.2f}% {eth_results['breach_win_rate']:<25.2f}%")
    print(f"{'Actual Staying Within Rate':<45} {btc_results['reverse_win_rate']:<25.2f}% {eth_results['reverse_win_rate']:<25.2f}%")
    print(f"{'Breach Bet - Market Implied':<45} {btc_results['breach_implied_prob']:<25.2f}% {eth_results['breach_implied_prob']:<25.2f}%")
    print(f"{'Breach Bet - Edge (pp)':<45} {btc_results['breach_edge_pp']:<25.2f} {eth_results['breach_edge_pp']:<25.2f}")
    print(f"{'Breach Bet - Expected ROI':<45} {btc_results['breach_roi']:<25.2f}% {eth_results['breach_roi']:<25.2f}%")
    print(f"{'Breach Bet - EV per bet':<45} ${btc_results['breach_expected_value']:<24.4f} ${eth_results['breach_expected_value']:<24.4f}")
    print(f"{'Staying Within - Market Implied':<45} {btc_results['staying_implied_prob']:<25.2f}% {eth_results['staying_implied_prob']:<25.2f}%")
    print(f"{'Staying Within - Edge (pp)':<45} {btc_results['staying_edge_pp']:<25.2f} {eth_results['staying_edge_pp']:<25.2f}")
    print(f"{'Staying Within - Expected ROI':<45} {btc_results['staying_roi']:<25.2f}% {eth_results['staying_roi']:<25.2f}%")
    print(f"{'Staying Within - EV per bet':<45} ${btc_results['staying_expected_value']:<24.4f} ${eth_results['staying_expected_value']:<24.4f}")
    print(f"{'Wider Strikes Breach Rate':<45} {btc_results['wider_breach_rate']:<25.2f}% {eth_results['wider_breach_rate']:<25.2f}%")
    print("=" * 60)
    print("\n💡 KEY TAKEAWAY:")
    print(f"   Breach bet: Market implies {btc_results['breach_implied_prob']:.0f}%, but actual is {btc_results['breach_win_rate']:.2f}% (BTC) / {eth_results['breach_win_rate']:.2f}% (ETH)")
    print(f"   Staying within bet: Market implies {btc_results['staying_implied_prob']:.0f}%, but actual is {btc_results['reverse_win_rate']:.2f}% (BTC) / {eth_results['reverse_win_rate']:.2f}% (ETH)")
    print("=" * 60)

