# Master Probability Lookup Table System Proposal

## Executive Summary

This proposal outlines the implementation of a **pre-computed probability lookup table system** that will eliminate live probability calculations in our trading platform, dramatically reducing CPU usage and improving system performance. The system will generate a comprehensive lookup table containing all possible probability combinations for our trading parameters, enabling instant database queries instead of computationally expensive real-time calculations.

## Current System Performance Issues

### Problem Statement
Our current system experiences high CPU usage (93%+ on 2-core DigitalOcean droplets) due to:
- **Live probability calculations** using `scipy.interpolate.griddata` every second
- **CSV file I/O operations** for fingerprint data loading
- **Memory-intensive operations** loading all fingerprint data into RAM
- **1-second pipeline cycles** in `unified_production_coordinator.py`

### Current Performance Metrics
- **CPU Usage:** 36.6% on 10-core local system, 93%+ on 2-core remote
- **Memory Usage:** 170MB for probability calculations
- **Calculation Time:** ~50-100ms per probability calculation
- **Data Storage:** 2.6 million rows across 61 CSV files

## Proposed Solution: Master Probability Lookup Table

### Concept Overview
Generate a **pre-computed lookup table** containing all possible probability combinations for:
- **TTC (Time to Close):** 0-3600 seconds (1 hour window)
- **Buffer Points:** 0-2000 points (BTC-specific, expandable)
- **Momentum Score:** -30 to +30 buckets

### Technical Specifications

#### Parameter Ranges
```
TTC Range: 0-3600 seconds (3,601 values)
Buffer Range: 0-2000 points (2,001 values)  
Momentum Range: -30 to +30 (61 values)
Total Combinations: 3,601 × 2,001 × 61 = 439,500,000
```

#### Database Schema
```sql
CREATE TABLE analytics.master_probability_lookup_btc (
    ttc_seconds INTEGER NOT NULL,
    buffer_points INTEGER NOT NULL,
    momentum_bucket INTEGER NOT NULL,
    prob_positive DECIMAL(5,2) NOT NULL,
    prob_negative DECIMAL(5,2) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ttc_seconds, buffer_points, momentum_bucket)
);

-- Indexes for fast lookups
CREATE INDEX idx_master_probability_lookup_btc_ttc ON analytics.master_probability_lookup_btc (ttc_seconds);
CREATE INDEX idx_master_probability_lookup_btc_buffer ON analytics.master_probability_lookup_btc (buffer_points);
CREATE INDEX idx_master_probability_lookup_btc_momentum ON analytics.master_probability_lookup_btc (momentum_bucket);
CREATE INDEX idx_master_probability_lookup_btc_composite ON analytics.master_probability_lookup_btc (ttc_seconds, buffer_points, momentum_bucket);
```

#### Table Size Estimation
- **Rows:** 439,500,000
- **Row Size:** ~50 bytes (ttc + buffer + momentum + prob_positive + prob_negative + overhead)
- **Total Size:** ~22 GB
- **Index Size:** ~8 GB (estimated)
- **Total Storage:** ~30 GB

## Implementation Plan

### Phase 1: Table Generation
Generate the complete lookup table using cloud computing resources.

#### Generation Script: `backend/util/master_probability_table_generator.py`
```python
class MasterProbabilityTableGenerator:
    def __init__(self, symbol: str = "btc"):
        self.symbol = symbol.lower()
        self.ttc_range = range(0, 3601)      # 0-3600 seconds
        self.buffer_range = range(0, 2001)   # 0-2000 points
        self.momentum_range = range(-30, 31) # -30 to +30
        self.total_combinations = 439,500,000
        
    def calculate_probability_for_combination(self, ttc: int, buffer: int, momentum: int):
        """Calculate probability for specific TTC, buffer, momentum combination"""
        # Uses existing PostgreSQL probability calculator
        # Converts buffer points to percentage for calculation
        # Returns (prob_positive, prob_negative)
        
    def generate_master_table(self, batch_size: int = 10000):
        """Generate complete lookup table with progress tracking"""
        # Batch processing for database efficiency
        # Progress logging and error handling
        # Estimated time: 8-32 days depending on compute power
```

#### Performance Test Results
**Test Configuration:**
- **Range:** 30 TTC values × 101 buffer values × 11 momentum values = 33,330 combinations
- **Generation Time:** 28 minutes 53 seconds
- **Generation Rate:** 20 combinations/second
- **Lookup Performance:** 0.081ms per lookup (12,406 lookups/second)

**Extrapolated to Full Table:**
- **Generation Time:** 439,500,000 ÷ 20 = 6,100 hours = **254 days** (single core)
- **Cloud Generation:** 8-32 days depending on instance size

### Phase 2: System Integration
Replace live probability calculations with database lookups.

#### New Probability Calculator: `backend/util/probability_calculator_lookup.py`
```python
class ProbabilityCalculatorLookup:
    def __init__(self, symbol: str = "btc"):
        self.symbol = symbol.lower()
        self.table_name = f"master_probability_lookup_{self.symbol}"
        
    def calculate_strike_probabilities(self, current_price: float, ttc_seconds: float, 
                                     strikes: List[float], momentum_score: float = 0.0):
        """Get pre-computed probabilities from lookup table"""
        # Calculate buffer points for each strike
        # Query lookup table for each combination
        # Return formatted results identical to current calculator
        
    def _get_probability_from_lookup(self, ttc: int, buffer: int, momentum: int):
        """Single lookup query to master table"""
        query = f"""
        SELECT prob_positive, prob_negative 
        FROM analytics.{self.table_name}
        WHERE ttc_seconds = %s AND buffer_points = %s AND momentum_bucket = %s
        """
        # Returns (prob_positive, prob_negative) tuple
```

#### Integration Points
1. **`unified_production_coordinator.py`**
   - Replace `ProbabilityCalculatorPostgreSQL` with `ProbabilityCalculatorLookup`
   - No other changes required - same interface

2. **`active_trade_supervisor.py`**
   - Continue reading from `btc_live_probabilities.json`
   - File generation now uses lookup table instead of live calculation

3. **`main.py` FastAPI endpoints**
   - No changes required - same JSON output format

### Phase 3: Performance Optimization
Implement caching and batch operations for maximum efficiency.

#### Caching Strategy
```python
class ProbabilityCache:
    def __init__(self, cache_size: int = 10000):
        self.cache = {}
        self.cache_size = cache_size
        
    def get_probability(self, ttc: int, buffer: int, momentum: int):
        """Get probability with LRU caching"""
        key = (ttc, buffer, momentum)
        if key in self.cache:
            return self.cache[key]
        
        # Database lookup
        result = self._database_lookup(ttc, buffer, momentum)
        
        # Cache management
        if len(self.cache) >= self.cache_size:
            self.cache.pop(next(iter(self.cache)))
        self.cache[key] = result
        
        return result
```

## Cost Analysis

### Cloud Generation Options

#### Google Cloud Platform (Recommended)
| Instance Type | vCPUs | Rate (combinations/sec) | Time | Cost/Hour | Total Cost |
|---------------|-------|-------------------------|------|-----------|------------|
| n2-standard-8 | 8 | 160 | 32 days | $0.1975 | $151 |
| n2-standard-16 | 16 | 320 | 16 days | $0.395 | $151 |
| n2-standard-32 | 32 | 640 | 8 days | $0.79 | $151 |
| n2-standard-60 | 60 | 1,200 | 4.25 days | $16.35 | $1,667 |

#### Cost-Effective Recommendation
- **Instance:** n2-standard-32 (32 vCPUs)
- **Time:** 8 days
- **Cost:** $151
- **Risk:** Low (stable instance type)

### Alternative Options

#### AWS EC2
- **c5.9xlarge:** 36 vCPUs, $1.53/hour
- **Estimated Cost:** $294 (8 days)

#### Azure
- **Standard_D32s_v3:** 32 vCPUs, $1.376/hour  
- **Estimated Cost:** $264 (8 days)

## Performance Benefits

### Expected Improvements
1. **CPU Usage Reduction:** 80-90% reduction in probability calculation CPU
2. **Response Time:** 0.081ms vs 50-100ms (600x faster)
3. **Memory Usage:** Eliminate fingerprint data loading (170MB savings)
4. **Scalability:** Support for higher-frequency trading operations
5. **Reliability:** No calculation failures or interpolation errors

### System Impact
- **`unified_production_coordinator.py`:** CPU usage drops from 36.6% to ~5-10%
- **Remote Server Compatibility:** 2-core droplets become viable
- **Real-time Performance:** Sub-millisecond probability lookups
- **Data Consistency:** Identical results to current system

## Risk Assessment

### Technical Risks
1. **Table Generation Failure:** Mitigated by batch processing and checkpointing
2. **Database Performance:** Mitigated by proper indexing and query optimization
3. **Data Accuracy:** Mitigated by thorough testing against current system

### Operational Risks
1. **Cloud Cost Overruns:** Mitigated by instance monitoring and time limits
2. **Generation Time:** Mitigated by parallel processing and progress tracking
3. **System Integration:** Mitigated by maintaining identical interfaces

## Implementation Timeline

### Week 1: Preparation
- Finalize table generation script
- Set up cloud environment
- Create backup and rollback procedures

### Week 2-3: Table Generation
- Deploy to Google Cloud
- Monitor generation progress
- Validate data integrity

### Week 4: Integration
- Deploy lookup calculator
- Test system integration
- Performance validation

### Week 5: Optimization
- Implement caching
- Fine-tune database queries
- Final performance testing

## Success Metrics

### Performance Targets
- **CPU Usage:** <10% for probability calculations
- **Lookup Time:** <1ms per probability
- **System Stability:** 99.9% uptime
- **Data Accuracy:** 100% match with current system

### Business Impact
- **Remote Deployment:** Viable on 2-core droplets
- **Trading Frequency:** Support for higher-frequency operations
- **System Reliability:** Reduced calculation failures
- **Scalability:** Foundation for multi-symbol expansion

## Conclusion

The master probability lookup table system represents a **fundamental performance optimization** that will transform our trading platform's computational efficiency. With an investment of ~$151 and 8 days of generation time, we can achieve:

- **600x faster** probability calculations
- **80-90% reduction** in CPU usage
- **Complete compatibility** with existing systems
- **Foundation for future scaling**

This proposal provides a clear path to resolving our current performance bottlenecks while maintaining system accuracy and reliability.

---

**Next Steps:**
1. External review and approval
2. Cloud environment setup
3. Table generation deployment
4. System integration testing
5. Performance validation and optimization
