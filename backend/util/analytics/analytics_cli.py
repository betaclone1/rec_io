#!/usr/bin/env python3
"""
Simple Analytics CLI
Run with: python3 analytics_cli.py
"""

import subprocess
import sys
import os
import time
import threading
from datetime import datetime

def print_header():
    print("=" * 60)
    print("🚀 ANALYTICS UPDATER - COMMAND LINE INTERFACE")
    print("=" * 60)
    print()

def print_symbols():
    symbols = ['btc', 'eth', 'sol', 'ada', 'dot', 'link', 'uni', 'matic', 'avax', 'atom']
    print("Available symbols:")
    for i, symbol in enumerate(symbols):
        print(f"  {i+1:2d}. {symbol.upper()}")
    print()

def get_symbol_selection():
    symbols = ['btc', 'eth', 'sol', 'ada', 'dot', 'link', 'uni', 'matic', 'avax', 'atom']
    
    print("Select symbols to process:")
    print("  - Enter numbers separated by spaces (e.g., '1 2 3' for BTC, ETH, SOL)")
    print("  - Enter 'all' for all symbols")
    print("  - Enter 'popular' for BTC, ETH, SOL")
    print("  - Enter 'q' to quit")
    print()
    
    while True:
        choice = input("Your selection: ").strip().lower()
        
        if choice == 'q':
            return None
        elif choice == 'all':
            return symbols
        elif choice == 'popular':
            return ['btc', 'eth', 'sol']
        else:
            try:
                indices = [int(x) - 1 for x in choice.split()]
                selected = [symbols[i] for i in indices if 0 <= i < len(symbols)]
                if selected:
                    return selected
                else:
                    print("❌ No valid symbols selected. Try again.")
            except (ValueError, IndexError):
                print("❌ Invalid input. Try again.")

def run_analytics(symbols):
    print(f"\n🚀 Starting analytics update for: {', '.join(symbols).upper()}")
    print("=" * 60)
    
    # Get the path to analytics_updater.py
    script_dir = os.path.dirname(os.path.abspath(__file__))
    updater_path = os.path.join(script_dir, "analytics_updater.py")
    
    try:
        # Start the process
        process = subprocess.Popen(
            [sys.executable, updater_path] + symbols,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        print("✅ Analytics process started successfully")
        print("📊 Monitoring progress... (Press Ctrl+C to stop)")
        print("-" * 60)
        
        # Monitor the process
        current_step = 0
        start_time = time.time()
        
        while process and process.poll() is None:
            output = process.stdout.readline()
            if output:
                line = output.strip()
                timestamp = datetime.now().strftime("%H:%M:%S")
                print(f"[{timestamp}] {line}")
                
                # Update progress based on output
                if "Step 1" in line or "Data validation" in line:
                    current_step = 1
                elif "Step 2" in line or "Data fetching" in line:
                    current_step = 2
                elif "Step 3" in line or "Profile generation" in line:
                    current_step = 3
                elif "Step 4" in line or "Momentum calculation" in line:
                    current_step = 4
                elif "Step 5" in line or "Price profile" in line:
                    current_step = 5
                elif "Step 6" in line or "Symbol profiler" in line:
                    current_step = 6
                elif "Step 7" in line or "Fingerprint generation" in line:
                    current_step = 7
                elif "Step 8" in line or "Lookup table generation" in line:
                    current_step = 8
                
                # Show progress
                if current_step > 0:
                    elapsed = time.time() - start_time
                    elapsed_str = f"{int(elapsed//60)}m {int(elapsed%60)}s"
                    print(f"📈 Progress: Step {current_step}/8 - Running for {elapsed_str}")
                
                # Show detailed progress
                if "PROGRESS:" in line:
                    print(f"📊 {line.replace('PROGRESS: ', '')}")
            
            time.sleep(0.1)
        
        # Process finished
        return_code = process.returncode if process else None
        
        print("-" * 60)
        if return_code == 0:
            print("🎉 Analytics update completed successfully!")
        else:
            print(f"❌ Analytics update failed with return code: {return_code}")
            
    except KeyboardInterrupt:
        print("\n⏹️ Stopping analytics update...")
        if process:
            process.terminate()
        print("✅ Process stopped")
    except Exception as e:
        print(f"❌ Error: {str(e)}")

def main():
    print_header()
    print_symbols()
    
    symbols = get_symbol_selection()
    if symbols is None:
        print("👋 Goodbye!")
        return
    
    print(f"\nSelected symbols: {', '.join(symbols).upper()}")
    confirm = input("Start analytics update? (y/n): ").strip().lower()
    
    if confirm in ['y', 'yes']:
        run_analytics(symbols)
    else:
        print("👋 Cancelled. Goodbye!")

if __name__ == "__main__":
    main()
