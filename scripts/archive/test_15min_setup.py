#!/usr/bin/env python3
"""
Test script for 15-minute master probability table setup.

This script validates that all components are working correctly before
deploying to Google Cloud for the full table generation.
"""

import os
import sys
import time
import logging

# Add backend to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.util.master_probability_table_generator_15min import MasterProbabilityTableGenerator15Min
from backend.util.probability_calculator_lookup_15min import ProbabilityCalculatorLookup15Min
from backend.util.probability_calculator_postgresql import ProbabilityCalculatorPostgreSQL

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_generator_creation():
    """Test that the generator can be created and configured."""
    logger.info("Testing generator creation...")
    
    try:
        generator = MasterProbabilityTableGenerator15Min("btc")
        logger.info(f"✅ Generator created successfully")
        logger.info(f"📊 Total combinations: {generator.total_combinations:,}")
        logger.info(f"📊 TTC range: {len(generator.ttc_range)} values")
        logger.info(f"📊 Buffer range: {len(generator.buffer_range)} values")
        logger.info(f"📊 Momentum range: {len(generator.momentum_range)} values")
        return True
    except Exception as e:
        logger.error(f"❌ Generator creation failed: {e}")
        return False

def test_table_creation():
    """Test that the lookup table can be created."""
    logger.info("Testing table creation...")
    
    try:
        generator = MasterProbabilityTableGenerator15Min("btc")
        success = generator.create_lookup_table()
        
        if success:
            logger.info("✅ Table creation successful")
            return True
        else:
            logger.error("❌ Table creation failed")
            return False
    except Exception as e:
        logger.error(f"❌ Table creation error: {e}")
        return False

def test_single_calculation():
    """Test a single probability calculation."""
    logger.info("Testing single probability calculation...")
    
    try:
        generator = MasterProbabilityTableGenerator15Min("btc")
        
        # Test a simple case
        ttc = 300  # 5 minutes
        buffer = 500  # $500 buffer
        momentum = 0  # Neutral momentum
        
        prob_positive, prob_negative = generator.calculate_probability_for_combination(ttc, buffer, momentum)
        
        logger.info(f"✅ Single calculation successful")
        logger.info(f"📊 TTC: {ttc}s, Buffer: {buffer}, Momentum: {momentum}")
        logger.info(f"📊 Prob+: {prob_positive:.4f}%, Prob-: {prob_negative:.4f}%")
        return True
    except Exception as e:
        logger.error(f"❌ Single calculation failed: {e}")
        return False

def test_lookup_calculator():
    """Test the lookup calculator."""
    logger.info("Testing lookup calculator...")
    
    try:
        calculator = ProbabilityCalculatorLookup15Min("btc")
        logger.info("✅ Lookup calculator created successfully")
        
        # Test a calculation
        result = calculator.calculate_strike_probabilities(
            current_price=120000,
            ttc_seconds=300,
            strikes=[120500],
            momentum_score=0.0
        )
        
        if result:
            logger.info(f"✅ Lookup calculation successful: {result}")
            return True
        else:
            logger.error("❌ Lookup calculation returned empty result")
            return False
    except Exception as e:
        logger.error(f"❌ Lookup calculator test failed: {e}")
        return False

def test_performance_comparison():
    """Compare performance between live and lookup calculators."""
    logger.info("Testing performance comparison...")
    
    try:
        # Create test case
        test_case = {
            'current_price': 120000,
            'ttc_seconds': 300,
            'strikes': [120500, 119500],
            'momentum_score': 0.0
        }
        
        # Test live calculator
        start_time = time.time()
        live_calculator = ProbabilityCalculatorPostgreSQL()
        live_result = live_calculator.calculate_strike_probabilities(**test_case)
        live_time = (time.time() - start_time) * 1000
        
        # Test lookup calculator
        start_time = time.time()
        lookup_calculator = ProbabilityCalculatorLookup15Min("btc")
        lookup_result = lookup_calculator.calculate_strike_probabilities(**test_case)
        lookup_time = (time.time() - start_time) * 1000
        
        logger.info(f"✅ Performance comparison successful")
        logger.info(f"📊 Live calculator: {live_time:.3f}ms")
        logger.info(f"📊 Lookup calculator: {lookup_time:.3f}ms")
        logger.info(f"📊 Speed improvement: {live_time/lookup_time:.1f}x faster")
        
        # Compare results
        if live_result and lookup_result:
            live_prob = live_result[0]['prob_within']
            lookup_prob = lookup_result[0]['prob_within']
            difference = abs(live_prob - lookup_prob)
            
            logger.info(f"📊 Live result: {live_prob:.4f}%")
            logger.info(f"📊 Lookup result: {lookup_prob:.4f}%")
            logger.info(f"📊 Difference: {difference:.4f}%")
            
            if difference < 0.01:
                logger.info("✅ Results match within tolerance")
                return True
            else:
                logger.warning("⚠️ Results differ significantly")
                return False
        else:
            logger.error("❌ One or both calculators returned empty results")
            return False
            
    except Exception as e:
        logger.error(f"❌ Performance comparison failed: {e}")
        return False

def test_small_batch():
    """Test generating a small batch of data."""
    logger.info("Testing small batch generation...")
    
    try:
        generator = MasterProbabilityTableGenerator15Min("btc")
        
        # Create a small test batch
        batch_data = []
        for ttc in range(300, 301):  # Just 1 TTC value
            for buffer in range(0, 101, 50):  # 3 buffer values
                for momentum in range(-1, 2):  # 3 momentum values
                    prob_positive, prob_negative = generator.calculate_probability_for_combination(ttc, buffer, momentum)
                    batch_data.append((ttc, buffer, momentum, prob_positive, prob_negative))
        
        # Insert the batch
        success = generator.generate_batch(batch_data, f"master_probability_lookup_btc_15min")
        
        if success:
            logger.info(f"✅ Small batch generation successful: {len(batch_data)} combinations")
            return True
        else:
            logger.error("❌ Small batch generation failed")
            return False
            
    except Exception as e:
        logger.error(f"❌ Small batch test failed: {e}")
        return False

def main():
    """Run all tests."""
    logger.info("🚀 Starting 15-minute master probability table setup tests")
    
    tests = [
        ("Generator Creation", test_generator_creation),
        ("Table Creation", test_table_creation),
        ("Single Calculation", test_single_calculation),
        ("Lookup Calculator", test_lookup_calculator),
        ("Performance Comparison", test_performance_comparison),
        ("Small Batch Generation", test_small_batch),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        logger.info(f"\n{'='*50}")
        logger.info(f"Running test: {test_name}")
        logger.info(f"{'='*50}")
        
        try:
            if test_func():
                logger.info(f"✅ {test_name}: PASSED")
                passed += 1
            else:
                logger.error(f"❌ {test_name}: FAILED")
        except Exception as e:
            logger.error(f"❌ {test_name}: ERROR - {e}")
    
    logger.info(f"\n{'='*50}")
    logger.info(f"Test Results: {passed}/{total} tests passed")
    logger.info(f"{'='*50}")
    
    if passed == total:
        logger.info("🎉 All tests passed! Ready for cloud deployment.")
        logger.info("Next steps:")
        logger.info("1. Update PROJECT_ID in deploy_15min_table_generation.sh")
        logger.info("2. Update database credentials in the deployment script")
        logger.info("3. Run: ./scripts/deploy_15min_table_generation.sh")
    else:
        logger.error("❌ Some tests failed. Please fix issues before deployment.")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
