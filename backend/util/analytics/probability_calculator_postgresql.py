import pandas as pd
import numpy as np
import os
import json
import time
import threading
import fcntl
from typing import List, Dict, Tuple, Optional, Union, Sequence, Callable
from scipy.interpolate import griddata
from datetime import datetime
import pytz
import glob
import psycopg2
from .fingerprint_generator_directional import get_fingerprint_dir, get_fingerprint_filename

# Add backend to path for imports
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.util.paths import get_project_root, get_data_dir


def safe_write_json(data: dict, filepath: str, timeout: float = 0.1):
    """Write JSON data with atomic file operations for better performance"""
    try:
        # Create temporary file in same directory for atomic write
        temp_filepath = filepath + '.tmp'
        with open(temp_filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        # Atomic rename operation
        os.replace(temp_filepath, filepath)
        return True
    except Exception as write_error:
        # Clean up temp file if it exists
        try:
            if os.path.exists(temp_filepath):
                os.remove(temp_filepath)
        except:
            pass
        print(f"Error writing JSON to {filepath}: {write_error}")
        return False


class ProbabilityCalculatorPostgreSQL:
    """
    Calculates strike probabilities using directional fingerprint data interpolation from PostgreSQL.
    Handles both positive and negative price movements separately.
    Supports momentum-based fingerprint hot-swapping.
    """
    
    def __init__(self, symbol="btc"):
        """
        Initialize the calculator with momentum-based directional fingerprint data only from PostgreSQL.
        Raises an error if no momentum fingerprints are found.
        """
        self.symbol = symbol.lower()
        self.momentum_fingerprints = {}
        self.current_momentum_bucket = None
        self.load_momentum_fingerprints = True
        self.conn = None
        self._connect_to_database()
        self._load_all_momentum_fingerprints()
        if not self.momentum_fingerprints:
            raise RuntimeError("No momentum fingerprints found! The system cannot operate without them.")
        
        # Initialize with the lowest available fingerprint to ensure attributes are set
        available_buckets = list(self.momentum_fingerprints.keys())
        if available_buckets:
            default_bucket = min(available_buckets)
            fingerprint_data = self.momentum_fingerprints[default_bucket]
            self.ttc_values = fingerprint_data['ttc_values']
            self.positive_move_percentages = fingerprint_data['positive_move_percentages']
            self.negative_move_percentages = fingerprint_data['negative_move_percentages']
            self.positive_interp_points = fingerprint_data['positive_interp_points']
            self.positive_interp_values = fingerprint_data['positive_interp_values']
            self.negative_interp_points = fingerprint_data['negative_interp_points']
            self.negative_interp_values = fingerprint_data['negative_interp_values']
            self.current_momentum_bucket = default_bucket
            self.last_used_momentum_bucket = default_bucket
    
    def _connect_to_database(self):
        """Establish connection to PostgreSQL database."""
        try:
            self.conn = psycopg2.connect(
                host=os.getenv('DB_HOST', 'localhost'),
                database=os.getenv('DB_NAME', 'rec_io_db'),
                user=os.getenv('DB_USER', 'rec_io_user'),
                password=os.getenv('DB_PASSWORD', 'rec_io_password'),
                port=os.getenv('DB_PORT', '5432')
            )
        except Exception as e:
            raise RuntimeError(f"Failed to connect to PostgreSQL: {e}")
    
    def _load_all_momentum_fingerprints(self):
        """Load all momentum-based directional fingerprints from PostgreSQL for hot-swapping."""
        try:
            cursor = self.conn.cursor()
            
            # Query for all momentum fingerprint tables for this symbol
            query = f"""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'analytics' 
            AND table_name LIKE '{self.symbol}_fingerprint_directional_momentum_%'
            ORDER BY table_name
            """
            
            cursor.execute(query)
            momentum_tables = cursor.fetchall()
            
            print(f"Found {len(momentum_tables)} momentum fingerprint tables for {self.symbol.upper()}")
            
            # Load each momentum fingerprint
            for row in momentum_tables:
                table_name = row[0]
                momentum_bucket = self._extract_momentum_bucket(table_name)
                if momentum_bucket is not None:
                    print(f"Loading momentum bucket {momentum_bucket} from {table_name}")
                    self._load_momentum_fingerprint_from_db(table_name, momentum_bucket)
            
            cursor.close()
            print(f"Successfully loaded {len(self.momentum_fingerprints)} momentum fingerprints for {self.symbol.upper()}")
            
        except Exception as e:
            raise RuntimeError(f"Failed to load momentum fingerprints: {e}")
    
    def _extract_momentum_bucket(self, table_name: str) -> Optional[int]:
        """Extract momentum bucket number from table name."""
        try:
            # Extract the momentum number from table name like "btc_fingerprint_directional_momentum_010"
            parts = table_name.split('_')
            if len(parts) >= 4 and parts[-1].isdigit():
                return int(parts[-1])
            elif len(parts) >= 4 and parts[-1].startswith('-') and parts[-1][1:].isdigit():
                return int(parts[-1])
            return None
        except:
            return None
    
    def _load_momentum_fingerprint_from_db(self, table_name: str, momentum_bucket: int):
        """Load a specific momentum fingerprint from PostgreSQL into cache."""
        try:
            cursor = self.conn.cursor()
            
            # Query the fingerprint data
            query = f'SELECT * FROM analytics."{table_name}" ORDER BY "time_to_close"'
            df = pd.read_sql_query(query, self.conn)
            
            if df.empty:
                print(f"Empty fingerprint table: {table_name}")
                return
            
            # Set the time_to_close as index
            df.set_index('time_to_close', inplace=True)
            
            # Parse TTC values (convert "XXm TTC" to seconds)
            ttc_values = []
            for idx in df.index:
                if 'm TTC' in idx:
                    minutes = int(idx.replace('m TTC', ''))
                    seconds = minutes * 60
                    ttc_values.append(seconds)
                else:
                    ttc_values.append(0)
            
            # Parse move percentages and separate positive/negative
            positive_move_percentages = []
            negative_move_percentages = []
            positive_columns = []
            negative_columns = []
            
            for col in df.columns:
                if col.startswith('pos_'):
                    # Extract percentage from pos_X_XX format
                    percent_str = col.replace('pos_', '').replace('_', '.')
                    try:
                        percent = float(percent_str)
                        positive_move_percentages.append(percent)
                        positive_columns.append(col)
                    except ValueError:
                        continue
                elif col.startswith('neg_'):
                    # Extract percentage from neg_X_XX format (negative)
                    percent_str = col.replace('neg_', '').replace('_', '.')
                    try:
                        percent = float(percent_str)  # Keep as positive, like CSV calculator
                        negative_move_percentages.append(percent)
                        negative_columns.append(col)
                    except ValueError:
                        continue
            
            # Sort the TTC values and move percentages along with the data matrix for stable interpolation
            ttc_sorted_indices = np.argsort(ttc_values)
            positive_sorted_indices = np.argsort(positive_move_percentages)
            negative_sorted_indices = np.argsort(negative_move_percentages)
            
            ttc_values = np.array(ttc_values)[ttc_sorted_indices]
            positive_move_percentages = np.array(positive_move_percentages)[positive_sorted_indices]
            negative_move_percentages = np.array(negative_move_percentages)[negative_sorted_indices]
            
            # Extract positive and negative probability matrices
            positive_data = df[positive_columns].values
            negative_data = df[negative_columns].values
            
            # Sort the data manually to avoid numpy indexing issues
            positive_probability_matrix = np.zeros((len(ttc_sorted_indices), len(positive_sorted_indices)))
            negative_probability_matrix = np.zeros((len(ttc_sorted_indices), len(negative_sorted_indices)))
            
            for i, ttc_idx in enumerate(ttc_sorted_indices):
                for j, pos_idx in enumerate(positive_sorted_indices):
                    positive_probability_matrix[i, j] = float(positive_data[ttc_idx][pos_idx])
                for j, neg_idx in enumerate(negative_sorted_indices):
                    negative_probability_matrix[i, j] = float(negative_data[ttc_idx][neg_idx])
            
            # Create interpolation points for positive and negative
            positive_interp_points = []
            positive_interp_values = []
            negative_interp_points = []
            negative_interp_values = []
            
            for i, ttc in enumerate(ttc_values):
                for j, move_pct in enumerate(positive_move_percentages):
                    positive_interp_points.append([ttc, move_pct])
                    positive_interp_values.append(positive_probability_matrix[i, j])
                    
                    negative_interp_points.append([ttc, move_pct])
                    negative_interp_values.append(negative_probability_matrix[i, j])
            
            positive_interp_points = np.array(positive_interp_points)
            positive_interp_values = np.array(positive_interp_values)
            negative_interp_points = np.array(negative_interp_points)
            negative_interp_values = np.array(negative_interp_values)
            
            # Store in cache
            self.momentum_fingerprints[momentum_bucket] = {
                'ttc_values': ttc_values,
                'positive_move_percentages': positive_move_percentages,
                'negative_move_percentages': negative_move_percentages,
                'positive_interp_points': positive_interp_points,
                'positive_interp_values': positive_interp_values,
                'negative_interp_points': negative_interp_points,
                'negative_interp_values': negative_interp_values
            }
            
            cursor.close()
            
        except Exception as e:
            print(f"Failed to load momentum fingerprint {momentum_bucket} from {table_name}: {e}")
    
    def _get_momentum_bucket(self, momentum_score: float) -> int:
        """Convert momentum score to bucket number."""
        # Clamp momentum to valid range (-30 to +30)
        momentum_score = max(-30, min(30, momentum_score))
        # Convert to bucket number (0.02 -> 2, -0.03 -> -3, etc.)
        return int(round(momentum_score * 100))
    
    def _switch_to_momentum_fingerprint(self, momentum_score: float):
        """Switch to the appropriate momentum fingerprint based on score with caching."""
        momentum_bucket = self._get_momentum_bucket(momentum_score)
        available_buckets = list(self.momentum_fingerprints.keys())
        if not available_buckets:
            raise RuntimeError("No momentum fingerprints available! The system cannot operate.")
        # Find the closest available bucket
        closest_bucket = min(available_buckets, key=lambda x: abs(x - momentum_bucket))
        
        # Return early if already using the correct bucket (caching optimization)
        if self.current_momentum_bucket == closest_bucket:
            return
            
        # Switch to new fingerprint (only happens when momentum changes significantly)
        fingerprint_data = self.momentum_fingerprints[closest_bucket]
        self.ttc_values = fingerprint_data['ttc_values']
        self.positive_move_percentages = fingerprint_data['positive_move_percentages']
        self.negative_move_percentages = fingerprint_data['negative_move_percentages']
        self.positive_interp_points = fingerprint_data['positive_interp_points']
        self.positive_interp_values = fingerprint_data['positive_interp_values']
        self.negative_interp_points = fingerprint_data['negative_interp_points']
        self.negative_interp_values = fingerprint_data['negative_interp_values']
        self.current_momentum_bucket = closest_bucket
        self.last_used_momentum_bucket = closest_bucket
    
    def interpolate_directional_probability(self, ttc_seconds: float, move_percent: float, direction: str = 'both') -> Union[float, Tuple[float, float]]:
        """
        Interpolate probability for given TTC and move percentage.
        
        Args:
            ttc_seconds: Time to close in seconds
            move_percent: Move percentage (e.g., 0.5 for 0.5%)
            direction: 'positive', 'negative', or 'both'
            
        Returns:
            Interpolated probability (0-100) or tuple of (positive_prob, negative_prob)
        """
        ttc_seconds = max(self.ttc_values[0], min(ttc_seconds, self.ttc_values[-1]))

        # Clamp to max fingerprint range
        move_percent = min(move_percent, self.positive_move_percentages[-1])

        point = np.array([[ttc_seconds, move_percent]])
        
        try:
            pos_prob = griddata(self.positive_interp_points, self.positive_interp_values, point, method='linear')[0]
            neg_prob = griddata(self.negative_interp_points, self.negative_interp_values, point, method='linear')[0]
        except:
            pos_prob = griddata(self.positive_interp_points, self.positive_interp_values, point, method='nearest')[0]
            neg_prob = griddata(self.negative_interp_points, self.negative_interp_values, point, method='nearest')[0]
        
        if direction == 'positive':
            return float(pos_prob)
        elif direction == 'negative':
            return float(neg_prob)
        else:
            return (float(pos_prob), float(neg_prob))
    
    def calculate_strike_probabilities(
        self, 
        current_price: float, 
        ttc_seconds: float, 
        strikes: Sequence[Union[float, int]],
        momentum_score: Optional[float] = None
    ) -> List[Dict]:
        """
        Calculate directional probabilities for a list of strikes.
        Tracks the last-used momentum bucket for reporting.
        """
        # Switch to appropriate momentum fingerprint if score provided
        if momentum_score is not None and self.load_momentum_fingerprints:
            self._switch_to_momentum_fingerprint(momentum_score)
        # Track the last-used bucket
        self.last_used_momentum_bucket = self.current_momentum_bucket
        results = []
        for strike in strikes:
            buffer = abs(current_price - strike)
            move_percent = (buffer / current_price) * 100
            is_above = strike > current_price
            result_tuple = self.interpolate_directional_probability(ttc_seconds, move_percent, 'both')
            if isinstance(result_tuple, tuple):
                pos_prob, neg_prob = result_tuple
            else:
                # If it's not a tuple, it's a single value
                pos_prob = neg_prob = result_tuple
            if is_above:
                prob_beyond = pos_prob
                prob_within = 100 - pos_prob
                direction = "above"
            else:
                prob_beyond = neg_prob
                prob_within = 100 - neg_prob
                direction = "below"
            result = {
                "strike": float(strike),
                "buffer": float(buffer),
                "move_percent": round(move_percent, 2),
                "prob_beyond": round(prob_beyond, 2),
                "prob_within": round(prob_within, 2),
                "direction": direction,
                "positive_prob": round(pos_prob, 2),
                "negative_prob": round(neg_prob, 2)
            }
            results.append(result)
        return results
    
    def __del__(self):
        """Clean up database connection."""
        if self.conn:
            self.conn.close()


# Global calculator instance for performance
_directional_calculator_postgresql_instance = None


def get_probability_calculator_postgresql(symbol="btc") -> ProbabilityCalculatorPostgreSQL:
    """Get or create the global directional calculator instance."""
    global _directional_calculator_postgresql_instance
    if _directional_calculator_postgresql_instance is None:
        _directional_calculator_postgresql_instance = ProbabilityCalculatorPostgreSQL(symbol)
    return _directional_calculator_postgresql_instance


def calculate_strike_probabilities_postgresql(
    current_price: float, 
    ttc_seconds: float, 
    strikes: Sequence[Union[float, int]],
    momentum_score: Optional[float] = None
) -> List[Dict]:
    """
    Main function to calculate directional strike probabilities using PostgreSQL data.
    
    Args:
        current_price: Current BTC price
        ttc_seconds: Time to close in seconds  
        strikes: List of strike prices
        momentum_score: Current momentum score for fingerprint selection
        
    Returns:
        List of dictionaries with directional strike probability data
    """
    calculator = get_probability_calculator_postgresql()
    return calculator.calculate_strike_probabilities(current_price, ttc_seconds, strikes, momentum_score)


# Live directional probability writer
_live_directional_writer_postgresql_running = False
_live_directional_writer_postgresql_thread = None


def start_live_directional_probability_writer_postgresql(
    output_path: Optional[str] = None,
    update_interval: int = 5,  # seconds
    current_price_getter: Optional[Callable[[], float]] = None,
    ttc_getter: Optional[Callable[[], float]] = None
):
    """
    Start a background thread that continuously writes live directional probability data to JSON using PostgreSQL.
    
    Args:
        output_path: Path to write the JSON file. If None, uses default path.
        update_interval: How often to update the file (seconds)
        current_price_getter: Function that returns current BTC price
        ttc_getter: Function that returns current TTC in seconds
    """
    global _live_directional_writer_postgresql_running, _live_directional_writer_postgresql_thread
    
    if _live_directional_writer_postgresql_running:
        print("Live directional probability writer is already running")
        return
    
    if output_path is None:
        # Default path for live directional probability data
        output_path = os.path.join(
            os.path.dirname(__file__), 
            '..', 'data', 'live_directional_probabilities_postgresql.json'
        )
    
    def writer_loop():
        """Background loop that writes live directional probability data."""
        calculator = get_probability_calculator_postgresql()
        
        while _live_directional_writer_postgresql_running:
            try:
                # Get current price and TTC
                current_price = None
                ttc_seconds = None
                
                if current_price_getter:
                    try:
                        current_price = current_price_getter()
                    except Exception as e:
                        print(f"[LiveDirectionalProbWriter] Error getting current price: {e}")
                        current_price = None
                
                if ttc_getter:
                    try:
                        ttc_seconds = ttc_getter()
                    except Exception as e:
                        print(f"[LiveDirectionalProbWriter] Error getting ttc_seconds: {e}")
                        ttc_seconds = None
                
                # If we have both values, calculate probabilities
                if current_price is not None and ttc_seconds is not None:
                    # Generate a range of strikes around current price
                    strikes = []
                    for i in range(-50, 51):  # -50 to +50 strikes
                        strike = current_price + (i * 100)  # $100 intervals
                        strikes.append(strike)
                    
                    # Calculate directional probabilities
                    probabilities = calculator.calculate_strike_probabilities(
                        current_price, ttc_seconds, strikes
                    )
                    
                    # Prepare output data
                    output_data = {
                        "timestamp": datetime.now(pytz.UTC).isoformat(),
                        "current_price": current_price,
                        "ttc_seconds": ttc_seconds,
                        "probabilities": probabilities
                    }
                    
                    # Write to file
                    try:
                        with open(output_path, 'w') as f:
                            json.dump(output_data, f, indent=2)
                    except Exception as e:
                        print(f"[LiveDirectionalProbWriter] Error writing to file: {e}")
                
                time.sleep(update_interval)
                
            except Exception as e:
                print(f"[LiveDirectionalProbWriter] Error in writer loop: {e}")
                time.sleep(update_interval)
    
    _live_directional_writer_postgresql_running = True
    _live_directional_writer_postgresql_thread = threading.Thread(target=writer_loop, daemon=True)
    _live_directional_writer_postgresql_thread.start()
    print(f"Started live directional probability writer to {output_path}")


def stop_live_directional_probability_writer_postgresql():
    """Stop the live directional probability writer thread."""
    global _live_directional_writer_postgresql_running
    _live_directional_writer_postgresql_running = False
    print("Stopped live directional probability writer")


def generate_btc_live_probabilities_postgresql_json(
    current_price: float,
    ttc_seconds: float,
    momentum_score: float = 0.0,
    step: int = 250,
    num_steps: int = 10,
    output_dir: str = None
):
    """
    Generate btc_live_probabilities_postgresql.json in backend/data/live_probabilities/.
    - current_price: current BTC price
    - ttc_seconds: time to close in seconds
    - momentum_score: momentum score for fingerprint selection
    - step: strike step size (default $250)
    - num_steps: number of steps above and below (default 10)
    - output_dir: override output directory (default None)
    """
    from backend.util.paths import get_data_dir
    import json
    
    # Round current price to nearest $250
    base_strike = int(round(current_price / step) * step)
    strikes = [base_strike + (i * step) for i in range(-num_steps, num_steps + 1)]
    calculator = get_probability_calculator_postgresql("btc")
    probabilities = calculator.calculate_strike_probabilities(
        current_price, ttc_seconds, strikes, momentum_score
    )
    # Get the fingerprint table used
    fingerprint_table = None
    if hasattr(calculator, 'current_momentum_bucket') and calculator.current_momentum_bucket is not None:
        fingerprint_table = f"btc_fingerprint_directional_momentum_{calculator.current_momentum_bucket:03d}"
    output = {
        "timestamp": datetime.now(pytz.UTC).isoformat(),
        "current_price": current_price,
        "base_strike": base_strike,
        "ttc_seconds": ttc_seconds,
        "momentum_score": momentum_score,
        "strikes": strikes,
        "probabilities": probabilities,
        "fingerprint_table": fingerprint_table
    }
    if output_dir is None:
        output_dir = os.path.join(get_data_dir(), "live_data", "live_probabilities")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "btc_live_probabilities_postgresql.json")
    safe_write_json(output, output_path)
    print(f"[BTC PROB EXPORT] Wrote {output_path}")


if __name__ == "__main__":
    # Example usage
    calculator = ProbabilityCalculatorPostgreSQL()
    
    # Test with some sample data
    current_price = 50000.0
    ttc_seconds = 300.0  # 5 minutes
    strikes = [49500, 50000, 50500, 51000]
    
    results = calculator.calculate_strike_probabilities(current_price, ttc_seconds, strikes)
    
    print("Directional Strike Probabilities (PostgreSQL):")
    for result in results:
        print(f"Strike: ${result['strike']:,.0f}")
        print(f"  Direction: {result['direction']}")
        print(f"  Prob Beyond: {result['prob_beyond']}%")
        print(f"  Prob Within: {result['prob_within']}%")
        print(f"  Positive Prob: {result['positive_prob']}%")
        print(f"  Negative Prob: {result['negative_prob']}%")
        print()
