#!/usr/bin/env python3
"""
Lookup Table Validation Test

Compares probability results between:
- NEW methodology: probability_lookup_btc_master_20250905 (local DB)
- OLD methodology: probability_lookup_btc (remote DB; set REC_PROD_DB_HOST or REC_PROD_SSH_HOST)

This simulates what would happen if we switched from the current production
system to the new methodology in our strike table generation system.
"""

import psycopg2
import random
import numpy as np
import pandas as pd
import argparse
from typing import Dict, List, Tuple, Optional
import sys
import os

# Add the project root to the path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from backend.core.prod_target import get_legacy_script_db_host

class LookupTableValidator:
    def __init__(self, symbol: str = "btc"):
        self.symbol = symbol.lower()
        
        # Local database configuration (NEW methodology)
        self.local_db_config = {
            'host': 'localhost',
            'database': 'rec_io_db',
            'user': 'rec_io_user',
            'password': 'rec_io_password'
        }
        
        # Remote server configuration (OLD methodology)
        self.remote_db_config = {
            'host': get_legacy_script_db_host(),
            'database': 'rec_io_db',
            'user': 'rec_io_user',
            'password': 'rec_io_password'
        }
        
        # Table names
        self.new_table = f"probability_lookup_{self.symbol}_master_20250905"  # Local DB
        self.old_table = f"probability_lookup_{self.symbol}"  # Remote DB
        
        # Parameter ranges
        self.ttc_range = (0, 3600)  # 0 to 60 minutes
        self.buffer_range = None  # Will be determined dynamically
        self.old_momentum_range = None  # Raw momentum values for old table
        self.new_momentum_range = None  # Percentile values for new table
        
        # Get parameter ranges
        self.get_parameter_ranges()
    
    def get_parameter_ranges(self):
        """Get the parameter ranges from both tables."""
        print(f"🔍 Getting parameter ranges for {self.symbol.upper()}...")
        
        # Get buffer range from new table (local)
        try:
            conn = psycopg2.connect(**self.local_db_config)
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT MIN(buffer_points), MAX(buffer_points)
                FROM analytics.{self.new_table}
            """)
            min_buffer, max_buffer = cursor.fetchone()
            conn.close()
            
            if min_buffer is not None and max_buffer is not None:
                self.buffer_range = (float(min_buffer), float(max_buffer))
                print(f"📊 Buffer range: {self.buffer_range[0]:.4f} to {self.buffer_range[1]:.4f}")
            else:
                print(f"❌ Could not determine buffer range")
                self.buffer_range = (0.0, 100.0)
                
        except Exception as e:
            print(f"❌ Error getting buffer range: {e}")
            self.buffer_range = (0.0, 100.0)
        
        # Get momentum range from old table (remote) - raw momentum values
        try:
            conn = psycopg2.connect(**self.remote_db_config)
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT MIN(momentum_bucket), MAX(momentum_bucket)
                FROM analytics.{self.old_table}
            """)
            min_momentum, max_momentum = cursor.fetchone()
            conn.close()
            
            if min_momentum is not None and max_momentum is not None:
                self.old_momentum_range = (int(min_momentum), int(max_momentum))
                print(f"📊 Old momentum range (raw values): {self.old_momentum_range[0]} to {self.old_momentum_range[1]}")
            else:
                print(f"❌ Could not determine old momentum range")
                self.old_momentum_range = (-30, 30)
                
        except Exception as e:
            print(f"❌ Error getting old momentum range: {e}")
            self.old_momentum_range = (-30, 30)
        
        # Get momentum range from new table (local) - percentile values
        try:
            conn = psycopg2.connect(**self.local_db_config)
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT MIN(momentum_bucket), MAX(momentum_bucket)
                FROM analytics.{self.new_table}
            """)
            min_momentum, max_momentum = cursor.fetchone()
            conn.close()
            
            if min_momentum is not None and max_momentum is not None:
                self.new_momentum_range = (int(min_momentum), int(max_momentum))
                print(f"📊 New momentum range (percentiles): {self.new_momentum_range[0]} to {self.new_momentum_range[1]}")
            else:
                print(f"❌ Could not determine new momentum range")
                self.new_momentum_range = (-99, 99)
                
        except Exception as e:
            print(f"❌ Error getting new momentum range: {e}")
            self.new_momentum_range = (-99, 99)
    
    def convert_momentum_to_percentile(self, raw_momentum: int) -> int:
        """Convert raw momentum value to percentile using momentum profile table."""
        try:
            # Convert integer raw momentum to decimal (e.g., 32 -> 0.3200)
            momentum_decimal = raw_momentum / 100.0
            
            # Find closest percentile in momentum profile table
            conn = psycopg2.connect(**self.local_db_config)
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT percentile FROM analytics.{self.symbol}_momentum_profile
                ORDER BY ABS(momentum_value - %s)
                LIMIT 1
            """, (momentum_decimal,))
            
            result = cursor.fetchone()
            conn.close()
            
            if result:
                return int(result[0])
            else:
                return raw_momentum  # Fallback
                    
        except Exception as e:
            print(f"❌ Error converting momentum {raw_momentum} to percentile: {e}")
            return raw_momentum  # Fallback
    
    def generate_random_parameters(self, num_samples: int) -> List[Dict]:
        """Generate random parameter combinations for testing."""
        samples = []
        
        for i in range(num_samples):
            # Random TTC (0-3600 seconds)
            ttc_seconds = random.randint(self.ttc_range[0], self.ttc_range[1])
            
            # Random buffer within range
            buffer_points = random.uniform(self.buffer_range[0], self.buffer_range[1])
            
            # Random raw momentum value (for old table)
            raw_momentum = random.randint(self.old_momentum_range[0], self.old_momentum_range[1])
            
            # Convert to percentile (for new table)
            momentum_percentile = self.convert_momentum_to_percentile(raw_momentum)
            
            samples.append({
                'sample_id': i + 1,
                'ttc_seconds': ttc_seconds,
                'buffer_points': buffer_points,
                'raw_momentum': raw_momentum,
                'momentum_percentile': momentum_percentile
            })
        
        return samples
    
    def query_lookup_table(self, table_name: str, db_config: Dict, ttc: int, buffer: float, momentum_percentile: int) -> Optional[Dict]:
        """Query a lookup table for probability values."""
        try:
            conn = psycopg2.connect(**db_config)
            cursor = conn.cursor()
            
            # Find the closest buffer point (since we might not have exact match)
            cursor.execute(f"""
                SELECT buffer_points, prob_within_positive, prob_within_negative
                FROM analytics.{table_name}
                WHERE ttc_seconds = %s AND momentum_bucket = %s
                ORDER BY ABS(buffer_points - %s)
                LIMIT 1
            """, (ttc, momentum_percentile, buffer))
            
            result = cursor.fetchone()
            conn.close()
            
            if result:
                actual_buffer, prob_up, prob_down = result
                return {
                    'actual_buffer': float(actual_buffer),
                    'prob_within_positive': float(prob_up),
                    'prob_within_negative': float(prob_down)
                }
            else:
                return None
                
        except Exception as e:
            print(f"❌ Error querying {table_name}: {e}")
            return None
    
    def run_validation_test(self, num_samples: int = 100) -> Dict:
        """Run the complete validation test."""
        print(f"🧪 Starting lookup table validation test for {self.symbol.upper()}")
        print(f"📊 Testing {num_samples} random parameter combinations")
        print(f"📋 NEW methodology: {self.new_table} (local DB)")
        print(f"📋 OLD methodology: {self.old_table} (remote server)")
        print()
        
        # Generate random samples
        samples = self.generate_random_parameters(num_samples)
        
        results = []
        successful_comparisons = 0
        failed_queries = 0
        
        for sample in samples:
            print(f"🔍 Sample {sample['sample_id']}: TTC={sample['ttc_seconds']}s, Buffer={sample['buffer_points']:.2f}, Raw Momentum={sample['raw_momentum']} → Percentile={sample['momentum_percentile']}")
            
            # Query NEW table (local DB) - use percentile
            new_result = self.query_lookup_table(
                self.new_table,
                self.local_db_config,
                sample['ttc_seconds'],
                sample['buffer_points'],
                sample['momentum_percentile']
            )
            
            # Query OLD table (remote DB) - use raw momentum value
            old_result = self.query_lookup_table(
                self.old_table,
                self.remote_db_config,
                sample['ttc_seconds'],
                sample['buffer_points'],
                sample['raw_momentum']
            )
            
            if new_result and old_result:
                # Calculate differences
                prob_up_diff = abs(new_result['prob_within_positive'] - old_result['prob_within_positive'])
                prob_down_diff = abs(new_result['prob_within_negative'] - old_result['prob_within_negative'])
                
                result = {
                    'sample_id': sample['sample_id'],
                    'ttc_seconds': sample['ttc_seconds'],
                    'buffer_points': sample['buffer_points'],
                    'raw_momentum': sample['raw_momentum'],
                    'momentum_percentile': sample['momentum_percentile'],
                    'new_prob_up': new_result['prob_within_positive'],
                    'new_prob_down': new_result['prob_within_negative'],
                    'old_prob_up': old_result['prob_within_positive'],
                    'old_prob_down': old_result['prob_within_negative'],
                    'prob_up_diff': prob_up_diff,
                    'prob_down_diff': prob_down_diff,
                    'max_diff': max(prob_up_diff, prob_down_diff),
                    'new_buffer': new_result['actual_buffer'],
                    'old_buffer': old_result['actual_buffer']
                }
                
                results.append(result)
                successful_comparisons += 1
                
                print(f"   NEW: UP={new_result['prob_within_positive']:.2f}%, DOWN={new_result['prob_within_negative']:.2f}%")
                print(f"   OLD: UP={old_result['prob_within_positive']:.2f}%, DOWN={old_result['prob_within_negative']:.2f}%")
                print(f"   DIFF: UP={prob_up_diff:.2f}%, DOWN={prob_down_diff:.2f}%")
                
            else:
                failed_queries += 1
                new_status = "✅" if new_result else "❌"
                old_status = "✅" if old_result else "❌"
                print(f"   ❌ Failed to query: NEW={new_status}, OLD={old_status}")
                if not new_result:
                    print(f"      NEW table missing: TTC={sample['ttc_seconds']}, Momentum={sample['momentum_percentile']}")
                if not old_result:
                    print(f"      OLD table missing: TTC={sample['ttc_seconds']}, Momentum={sample['raw_momentum']}")
            
            print()
        
        # Analyze results
        if results:
            df = pd.DataFrame(results)
            
            # Calculate statistics
            avg_up_diff = df['prob_up_diff'].mean()
            avg_down_diff = df['prob_down_diff'].mean()
            max_up_diff = df['prob_up_diff'].max()
            max_down_diff = df['prob_down_diff'].max()
            avg_max_diff = df['max_diff'].mean()
            overall_max_diff = df['max_diff'].max()
            
            # Count samples within different thresholds
            within_1_percent = len(df[df['max_diff'] <= 1.0])
            within_5_percent = len(df[df['max_diff'] <= 5.0])
            within_10_percent = len(df[df['max_diff'] <= 10.0])
            
            # Print results
            print("=" * 80)
            print(f"🎯 LOOKUP TABLE VALIDATION REPORT - {self.symbol.upper()}")
            print("=" * 80)
            print()
            print("📊 Test Summary:")
            print(f"   Total Samples: {num_samples}")
            print(f"   Successful Comparisons: {successful_comparisons}")
            print(f"   Failed Queries: {failed_queries}")
            print(f"   Success Rate: {(successful_comparisons/num_samples)*100:.1f}%")
            print()
            print("📈 Probability Differences:")
            print(f"   Average UP Difference: {avg_up_diff:.3f}%")
            print(f"   Average DOWN Difference: {avg_down_diff:.3f}%")
            print(f"   Maximum UP Difference: {max_up_diff:.3f}%")
            print(f"   Maximum DOWN Difference: {max_down_diff:.3f}%")
            print(f"   Average Maximum Difference: {avg_max_diff:.3f}%")
            print(f"   Overall Maximum Difference: {overall_max_diff:.3f}%")
            print()
            print("🎯 Accuracy Assessment:")
            print(f"   Within 1%: {within_1_percent} samples ({(within_1_percent/len(df))*100:.1f}%)")
            print(f"   Within 5%: {within_5_percent} samples ({(within_5_percent/len(df))*100:.1f}%)")
            print(f"   Within 10%: {within_10_percent} samples ({(within_10_percent/len(df))*100:.1f}%)")
            print()
            
            # Overall assessment
            if avg_max_diff <= 1.0:
                print("✅ VALIDATION PASSED: New methodology shows minimal differences")
                print("   - Safe to deploy for live trading")
            elif avg_max_diff <= 5.0:
                print("⚠️ VALIDATION CAUTION: New methodology shows moderate differences")
                print("   - Consider reviewing specific parameter ranges")
            else:
                print("❌ VALIDATION FAILED: New methodology shows significant differences")
                print("   - Do not deploy without further analysis")
            
            print("=" * 80)
            
            return {
                'success': True,
                'stats': {
                    'total_samples': num_samples,
                    'successful_comparisons': successful_comparisons,
                    'failed_queries': failed_queries,
                    'success_rate': (successful_comparisons/num_samples)*100,
                    'avg_up_diff': avg_up_diff,
                    'avg_down_diff': avg_down_diff,
                    'max_up_diff': max_up_diff,
                    'max_down_diff': max_down_diff,
                    'avg_max_diff': avg_max_diff,
                    'overall_max_diff': overall_max_diff,
                    'within_1_percent': within_1_percent,
                    'within_5_percent': within_5_percent,
                    'within_10_percent': within_10_percent
                },
                'results': results,
                'dataframe': df
            }
        else:
            print("❌ No successful comparisons - cannot analyze results")
            return {
                'success': False,
                'stats': {'error': 'No successful comparisons'},
                'results': [],
                'dataframe': None
            }

def main():
    parser = argparse.ArgumentParser(description='Validate lookup table differences between old and new methodologies')
    parser.add_argument('symbol', help='Symbol to test (e.g., btc, eth)')
    parser.add_argument('--samples', type=int, default=100, help='Number of random samples to test')
    
    args = parser.parse_args()
    
    validator = LookupTableValidator(args.symbol)
    results = validator.run_validation_test(args.samples)
    
    if results['success']:
        print(f"\n🎉 Validation completed successfully!")
        print(f"📊 Tested {results['stats']['successful_comparisons']} parameter combinations")
        print(f"📈 Average difference: {results['stats']['avg_max_diff']:.3f}%")
    else:
        print(f"\n❌ Validation failed: {results['stats']['error']}")

if __name__ == "__main__":
    main()