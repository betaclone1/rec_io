#!/usr/bin/env python3
"""
Chunked Master Probability Table Generator
Breaks the full table generation into 10 chunks with fault tolerance
"""

import os
import sys
import json
import time
import psycopg2
import numpy as np
from scipy.interpolate import griddata
from typing import Tuple, List, Dict
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing as mp

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.util.probability_calculator import ProbabilityCalculator
from backend.core.time_eastern import merge_psycopg2_connect_kwargs

class ChunkedMasterTableGenerator:
    def __init__(self, symbol: str = "btc"):
        self.symbol = symbol
        self.fingerprint_table_prefix = f"{symbol}_fingerprint_directional_momentum"
        
        # Database connection
        self.db_config = merge_psycopg2_connect_kwargs(
            {
                "host": "localhost",
                "database": "rec_io_db",
                "user": "rec_io_user",
                "password": "",
            }
        )
        
        # Generation parameters (practical range)
        self.ttc_range = (0, 900)  # 0-15 minutes
        self.buffer_range = (0, 1500)  # 0-1500 points
        self.momentum_range = (-30, 30)  # -30 to +30 (61 buckets total)
        
        # Chunk configuration
        self.num_chunks = 10
        self.chunk_progress_file = f"chunk_progress_{symbol}.json"
        
    def calculate_chunk_parameters(self) -> List[Dict]:
        """Calculate the parameters for each of the 10 chunks"""
        total_ttc = self.ttc_range[1] - self.ttc_range[0] + 1  # 901
        total_buffer = self.buffer_range[1] - self.buffer_range[0] + 1  # 1501
        total_momentum = self.momentum_range[1] - self.momentum_range[0] + 1  # 62
        
        # Each chunk will handle a subset of TTC values
        ttc_per_chunk = total_ttc // self.num_chunks
        remainder = total_ttc % self.num_chunks
        
        chunks = []
        start_ttc = self.ttc_range[0]
        
        for i in range(self.num_chunks):
            # Distribute remainder across first few chunks
            chunk_ttc_size = ttc_per_chunk + (1 if i < remainder else 0)
            end_ttc = start_ttc + chunk_ttc_size - 1
            
            chunk = {
                'chunk_id': i,
                'ttc_start': start_ttc,
                'ttc_end': end_ttc,
                'buffer_start': self.buffer_range[0],
                'buffer_end': self.buffer_range[1],
                'momentum_start': self.momentum_range[0],
                'momentum_end': self.momentum_range[1],
                'status': 'pending',
                'start_time': None,
                'end_time': None,
                'rows_generated': 0,
                'error': None
            }
            
            chunks.append(chunk)
            start_ttc = end_ttc + 1
            
        return chunks
    
    def create_master_table(self):
        """Create the master lookup table if it doesn't exist"""
        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor()
        
        try:
            # Drop table if exists
            cursor.execute("DROP TABLE IF EXISTS analytics.master_probability_lookup_btc")
            
            # Create table
            create_table_sql = """
            CREATE TABLE analytics.master_probability_lookup_btc (
                ttc_seconds INTEGER NOT NULL,
                buffer_points INTEGER NOT NULL,
                momentum_bucket INTEGER NOT NULL,
                prob_within_positive NUMERIC(5,2) NOT NULL,
                prob_within_negative NUMERIC(5,2) NOT NULL,
                PRIMARY KEY (ttc_seconds, buffer_points, momentum_bucket)
            );
            """
            cursor.execute(create_table_sql)
            
            # Create indexes for fast lookups
            cursor.execute("CREATE INDEX idx_master_lookup_ttc ON analytics.master_probability_lookup_btc(ttc_seconds)")
            cursor.execute("CREATE INDEX idx_master_lookup_buffer ON analytics.master_probability_lookup_btc(buffer_points)")
            cursor.execute("CREATE INDEX idx_master_lookup_momentum ON analytics.master_probability_lookup_btc(momentum_bucket)")
            
            conn.commit()
            print("Master table created successfully")
            
        except Exception as e:
            conn.rollback()
            print(f"Error creating table: {e}")
            raise
        finally:
            cursor.close()
            conn.close()
    
    def load_fingerprint_data(self, momentum_bucket: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Load fingerprint data for a specific momentum bucket"""
        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor()
        
        try:
            # Format table name
            if momentum_bucket < 0:
                table_name = f"{self.fingerprint_table_prefix}_-{abs(momentum_bucket):02d}"
            else:
                table_name = f"{self.fingerprint_table_prefix}_{momentum_bucket:03d}"
            
            # Query with proper quoting for table names with hyphens
            query = f'SELECT * FROM analytics."{table_name}" ORDER BY "time_to_close"'
            cursor.execute(query)
            
            data = cursor.fetchall()
            if not data:
                raise ValueError(f"No data found for momentum bucket {momentum_bucket}")
            
            # Get column names
            column_names = [desc[0] for desc in cursor.description]
            
            # Parse TTC values (convert "XXm TTC" to seconds)
            ttc_values = []
            for row in data:
                ttc_str = row[0]  # time_to_close column
                if 'm TTC' in ttc_str:
                    minutes = int(ttc_str.replace('m TTC', ''))
                    seconds = minutes * 60
                    ttc_values.append(seconds)
                else:
                    ttc_values.append(0)
            
            # Parse move percentages and separate positive/negative
            positive_move_percentages = []
            negative_move_percentages = []
            positive_columns = []
            negative_columns = []
            
            for col in column_names[1:]:  # Skip time_to_close
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
                    # Extract percentage from neg_X_XX format
                    percent_str = col.replace('neg_', '').replace('_', '.')
                    try:
                        percent = float(percent_str)
                        negative_move_percentages.append(percent)
                        negative_columns.append(col)
                    except ValueError:
                        continue
            
            # Sort move percentages
            positive_move_percentages = sorted(positive_move_percentages)
            negative_move_percentages = sorted(negative_move_percentages)
            
            # Create data matrices
            positive_data = []
            negative_data = []
            
            for row in data:
                pos_row = []
                neg_row = []
                for col in positive_columns:
                    col_idx = column_names.index(col)
                    pos_row.append(float(row[col_idx]))
                for col in negative_columns:
                    col_idx = column_names.index(col)
                    neg_row.append(float(row[col_idx]))
                positive_data.append(pos_row)
                negative_data.append(neg_row)
            
            return (np.array(ttc_values), np.array(positive_move_percentages), 
                   np.array(negative_move_percentages), np.array(positive_data), 
                   np.array(negative_data))
            
        except Exception as e:
            print(f"Error loading fingerprint data for momentum {momentum_bucket}: {e}")
            raise
        finally:
            cursor.close()
            conn.close()
    
    def interpolate_probabilities(self, ttc_seconds: int, buffer_points: int, momentum_bucket: int) -> Tuple[float, float]:
        """Interpolate both positive and negative probabilities for a given combination"""
        try:
            # Load fingerprint data for this momentum bucket
            ttc_values, pos_move_percentages, neg_move_percentages, pos_data, neg_data = self.load_fingerprint_data(momentum_bucket)
            
            # Calculate move percentage
            # Note: We'll use a placeholder current_price of 100000 for calculation
            # The actual current_price doesn't matter since we're calculating move_percentage
            current_price = 100000
            move_percent = (buffer_points / current_price) * 100
            
            # Clamp move_percent to available range
            move_percent = min(move_percent, max(pos_move_percentages[-1], neg_move_percentages[-1]))
            
            # Create interpolation points for positive data
            pos_interp_points = []
            pos_interp_values = []
            for i, ttc in enumerate(ttc_values):
                for j, move_pct in enumerate(pos_move_percentages):
                    pos_interp_points.append([ttc, move_pct])
                    pos_interp_values.append(pos_data[i, j])
            
            # Create interpolation points for negative data
            neg_interp_points = []
            neg_interp_values = []
            for i, ttc in enumerate(ttc_values):
                for j, move_pct in enumerate(neg_move_percentages):
                    neg_interp_points.append([ttc, move_pct])
                    neg_interp_values.append(neg_data[i, j])
            
            # Convert to numpy arrays
            pos_interp_points = np.array(pos_interp_points)
            pos_interp_values = np.array(pos_interp_values)
            neg_interp_points = np.array(neg_interp_points)
            neg_interp_values = np.array(neg_interp_values)
            
            # Interpolate positive probability
            point = np.array([[ttc_seconds, move_percent]])
            try:
                pos_prob = griddata(pos_interp_points, pos_interp_values, point, method='linear')[0]
            except:
                pos_prob = griddata(pos_interp_points, pos_interp_values, point, method='nearest')[0]
            
            # Interpolate negative probability
            try:
                neg_prob = griddata(neg_interp_points, neg_interp_values, point, method='linear')[0]
            except:
                neg_prob = griddata(neg_interp_points, neg_interp_values, point, method='nearest')[0]
            
            # Handle NaN values
            if np.isnan(pos_prob):
                pos_prob = 0.0
            if np.isnan(neg_prob):
                neg_prob = 0.0
            
            # Calculate prob_within values
            prob_within_positive = 100.0 - pos_prob
            prob_within_negative = 100.0 - neg_prob
            
            return prob_within_positive, prob_within_negative
            
        except Exception as e:
            print(f"Error interpolating for ttc={ttc_seconds}, buffer={buffer_points}, momentum={momentum_bucket}: {e}")
            return 0.0, 0.0
    
    def generate_chunk(self, chunk_params: Dict) -> Dict:
        """Generate a single chunk of the master table"""
        chunk_id = chunk_params['chunk_id']
        print(f"Starting chunk {chunk_id}: TTC {chunk_params['ttc_start']}-{chunk_params['ttc_end']}")
        
        # Update chunk status
        chunk_params['status'] = 'running'
        chunk_params['start_time'] = time.time()
        self.save_chunk_progress()
        
        conn = psycopg2.connect(**self.db_config)
        cursor = conn.cursor()
        
        try:
            rows_generated = 0
            batch_size = 1000
            batch_data = []
            
            # Generate all combinations for this chunk
            for ttc in range(chunk_params['ttc_start'], chunk_params['ttc_end'] + 1):
                for buffer in range(chunk_params['buffer_start'], chunk_params['buffer_end'] + 1):
                    for momentum in range(chunk_params['momentum_start'], chunk_params['momentum_end'] + 1):
                        try:
                            prob_pos, prob_neg = self.interpolate_probabilities(ttc, buffer, momentum)
                            
                            batch_data.append((ttc, buffer, momentum, prob_pos, prob_neg))
                            rows_generated += 1
                            
                            # Insert batch when it reaches batch_size
                            if len(batch_data) >= batch_size:
                                self.insert_batch(cursor, batch_data)
                                batch_data = []
                                
                                # Update progress every 1000 rows
                                if rows_generated % 1000 == 0:
                                    chunk_params['rows_generated'] = rows_generated
                                    self.save_chunk_progress()
                                    print(f"Chunk {chunk_id}: Generated {rows_generated} rows")
                                    
                        except Exception as e:
                            print(f"Error processing ttc={ttc}, buffer={buffer}, momentum={momentum}: {e}")
                            continue
            
            # Insert remaining batch
            if batch_data:
                self.insert_batch(cursor, batch_data)
            
            conn.commit()
            
            # Update chunk status
            chunk_params['status'] = 'completed'
            chunk_params['end_time'] = time.time()
            chunk_params['rows_generated'] = rows_generated
            self.save_chunk_progress()
            
            print(f"Chunk {chunk_id} completed: {rows_generated} rows generated")
            return chunk_params
            
        except Exception as e:
            conn.rollback()
            chunk_params['status'] = 'failed'
            chunk_params['error'] = str(e)
            chunk_params['end_time'] = time.time()
            self.save_chunk_progress()
            print(f"Chunk {chunk_id} failed: {e}")
            raise
        finally:
            cursor.close()
            conn.close()
    
    def insert_batch(self, cursor, batch_data: List[Tuple]):
        """Insert a batch of data into the master table"""
        insert_sql = """
        INSERT INTO analytics.master_probability_lookup_btc 
        (ttc_seconds, buffer_points, momentum_bucket, prob_within_positive, prob_within_negative)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (ttc_seconds, buffer_points, momentum_bucket) 
        DO UPDATE SET 
            prob_within_positive = EXCLUDED.prob_within_positive,
            prob_within_negative = EXCLUDED.prob_within_negative
        """
        cursor.executemany(insert_sql, batch_data)
    
    def save_chunk_progress(self):
        """Save chunk progress to file"""
        with open(self.chunk_progress_file, 'w') as f:
            json.dump(self.chunks, f, indent=2)
    
    def load_chunk_progress(self):
        """Load chunk progress from file"""
        if os.path.exists(self.chunk_progress_file):
            with open(self.chunk_progress_file, 'r') as f:
                self.chunks = json.load(f)
        else:
            self.chunks = self.calculate_chunk_parameters()
            self.save_chunk_progress()
    
    def run_chunked_generation(self):
        """Run the chunked generation process"""
        print("Starting chunked master table generation...")
        
        # Create master table
        self.create_master_table()
        
        # Load or initialize chunk progress
        self.load_chunk_progress()
        
        # Identify chunks that need to be run
        pending_chunks = [chunk for chunk in self.chunks if chunk['status'] in ['pending', 'failed']]
        
        if not pending_chunks:
            print("All chunks are already completed!")
            return
        
        print(f"Found {len(pending_chunks)} chunks to process")
        
        # Process chunks sequentially (for now, can be parallelized later)
        for chunk in pending_chunks:
            try:
                self.generate_chunk(chunk)
            except Exception as e:
                print(f"Chunk {chunk['chunk_id']} failed: {e}")
                continue
        
        # Final status report
        completed = [chunk for chunk in self.chunks if chunk['status'] == 'completed']
        failed = [chunk for chunk in self.chunks if chunk['status'] == 'failed']
        
        print(f"\nGeneration complete!")
        print(f"Completed chunks: {len(completed)}")
        print(f"Failed chunks: {len(failed)}")
        
        if failed:
            print("Failed chunks:")
            for chunk in failed:
                print(f"  Chunk {chunk['chunk_id']}: {chunk['error']}")
    
    def resume_failed_chunks(self):
        """Resume only the failed chunks"""
        self.load_chunk_progress()
        failed_chunks = [chunk for chunk in self.chunks if chunk['status'] == 'failed']
        
        if not failed_chunks:
            print("No failed chunks to resume")
            return
        
        print(f"Resuming {len(failed_chunks)} failed chunks...")
        
        for chunk in failed_chunks:
            # Reset chunk status
            chunk['status'] = 'pending'
            chunk['error'] = None
            chunk['rows_generated'] = 0
            
            try:
                self.generate_chunk(chunk)
            except Exception as e:
                print(f"Chunk {chunk['chunk_id']} failed again: {e}")
                continue

if __name__ == "__main__":
    generator = ChunkedMasterTableGenerator("btc")
    
    # Check command line arguments
    if len(sys.argv) > 1 and sys.argv[1] == "resume":
        generator.resume_failed_chunks()
    else:
        generator.run_chunked_generation()
