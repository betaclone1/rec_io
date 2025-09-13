#!/usr/bin/env python3
"""
Simple Analytics GUI
Double-click to run - no terminal commands needed!
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import subprocess
import threading
import time
import os
import sys
import json
from datetime import datetime
import psycopg2
import psutil

class AnalyticsGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Analytics Updater")
        self.root.geometry("800x600")
        
        # Check for orphaned processes on startup
        self.cleanup_orphaned_processes()
        
        # Process tracking
        self.process = None
        self.is_running = False
        self.is_paused = False
        self.logs = []
        
        # Database configuration
        self.db_config = {
            'host': 'localhost',
            'database': 'rec_io_db',
            'user': 'rec_io_user',
            'password': 'rec_io_password'
        }
        
        self.setup_ui()
        self.check_existing_progress()
        
    def setup_ui(self):
        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(3, weight=1)
        
        # Title
        title_label = ttk.Label(main_frame, text="🚀 Analytics Updater", font=("Arial", 16, "bold"))
        title_label.grid(row=0, column=0, columnspan=2, pady=(0, 20))
        
        # Symbol selection
        symbol_frame = ttk.LabelFrame(main_frame, text="Select Symbols", padding="10")
        symbol_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # Symbol checkboxes
        symbol_checkbox_frame = ttk.Frame(symbol_frame)
        symbol_checkbox_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.symbol_vars = {}
        symbols = ['btc', 'eth']
        
        for i, symbol in enumerate(symbols):
            var = tk.BooleanVar()
            self.symbol_vars[symbol] = var
            cb = ttk.Checkbutton(symbol_checkbox_frame, text=symbol.upper(), variable=var)
            cb.pack(side=tk.LEFT, padx=(0, 20))
        
        # Quick selection buttons
        symbol_button_frame = ttk.Frame(symbol_frame)
        symbol_button_frame.pack(fill=tk.X)
        
        ttk.Button(symbol_button_frame, text="Select All", command=self.select_all).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(symbol_button_frame, text="Select None", command=self.select_none).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(symbol_button_frame, text="Popular (BTC, ETH)", command=self.select_popular).pack(side=tk.LEFT)
        
        # Step selection
        step_frame = ttk.LabelFrame(main_frame, text="Select Steps to Run", padding="10")
        step_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # Step checkboxes
        step_checkbox_frame = ttk.Frame(step_frame)
        step_checkbox_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.step_vars = {}
        steps = [
            ("1. Update Price Logs", "update_price_logs"),
            ("2. Generate Momentum", "generate_momentum"),
            ("3. Generate Profiles", "generate_profiles"),
            ("4. Assign Percentiles", "assign_percentiles"),
            ("5. Verify Data", "verify_data"),
            ("6. Archive Fingerprints", "archive_fingerprints"),
            ("7. Generate Fingerprints", "generate_fingerprints"),
            ("8. Generate Lookup Tables", "generate_lookup_tables"),
            ("9. Create Master Tables", "create_master_lookup_tables")
        ]
        
        for i, (label, key) in enumerate(steps):
            var = tk.BooleanVar()
            self.step_vars[key] = var
            cb = ttk.Checkbutton(step_checkbox_frame, text=label, variable=var)
            cb.grid(row=i//2, column=i%2, sticky=tk.W, padx=(0, 20), pady=2)
        
        # Step selection buttons
        step_button_frame = ttk.Frame(step_frame)
        step_button_frame.pack(fill=tk.X)
        
        ttk.Button(step_button_frame, text="Select All Steps", command=self.select_all_steps).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(step_button_frame, text="Select None", command=self.select_no_steps).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(step_button_frame, text="Price Logs Only", command=self.select_price_logs_only).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(step_button_frame, text="Lookup Tables Only", command=self.select_lookup_only).pack(side=tk.LEFT)
        
        # Control buttons - organized into logical groups
        control_frame = ttk.Frame(main_frame)
        control_frame.grid(row=3, column=0, columnspan=2, pady=(0, 10))
        
        # Primary action buttons (left side)
        primary_frame = ttk.LabelFrame(control_frame, text="Primary Actions", padding="5")
        primary_frame.pack(side=tk.LEFT, padx=(0, 15))
        
        self.start_button = ttk.Button(primary_frame, text="🚀 Start Update", command=self.start_update)
        self.start_button.pack(side=tk.LEFT, padx=(0, 5))
        
        self.pause_button = ttk.Button(primary_frame, text="⏸️ Pause", command=self.pause_update, state=tk.DISABLED)
        self.pause_button.pack(side=tk.LEFT, padx=(0, 5))
        
        self.resume_button = ttk.Button(primary_frame, text="▶️ Resume", command=self.resume_update, state=tk.DISABLED)
        self.resume_button.pack(side=tk.LEFT, padx=(0, 5))
        
        self.stop_button = ttk.Button(primary_frame, text="⏹️ Stop", command=self.stop_update, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT)
        
        # Management buttons (right side)
        management_frame = ttk.LabelFrame(control_frame, text="Management", padding="5")
        management_frame.pack(side=tk.LEFT, padx=(0, 15))
        
        ttk.Button(management_frame, text="🔄 Reset Progress", command=self.reset_progress).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(management_frame, text="🗑️ Clear Logs", command=self.clear_logs).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(management_frame, text="📥 Export Logs", command=self.export_logs).pack(side=tk.LEFT)
        
        # Progress section
        progress_frame = ttk.LabelFrame(main_frame, text="Progress", padding="10")
        progress_frame.grid(row=4, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # Progress bar and label
        progress_info_frame = ttk.Frame(progress_frame)
        progress_info_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(progress_info_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill=tk.X, pady=(0, 5))
        
        self.progress_label = ttk.Label(progress_info_frame, text="Ready to start")
        self.progress_label.pack(anchor=tk.W)
        
        # Pipeline steps
        steps_frame = ttk.Frame(progress_frame)
        steps_frame.pack(fill=tk.X)
        
        self.step_labels = {}
        steps = [
            "1. Data Validation", "2. Data Fetch", "3. Profile Gen", "4. Momentum",
            "5. Price Profile", "6. Symbol Profile", "7. Fingerprints", "8. Lookup Tables", "9. Master Tables"
        ]
        
        for i, step in enumerate(steps):
            label = ttk.Label(steps_frame, text=step, foreground="gray")
            label.grid(row=i//4, column=i%4, padx=(0, 20), pady=2)
            self.step_labels[i+1] = label
        
        # Log section
        log_frame = ttk.LabelFrame(main_frame, text="Live Logs", padding="10")
        log_frame.grid(row=5, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=15, font=("Courier", 10))
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Status bar
        status_frame = ttk.Frame(main_frame)
        status_frame.grid(row=6, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(10, 0))
        
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(status_frame, textvariable=self.status_var, relief=tk.SUNKEN)
        status_bar.pack(fill=tk.X)
        
        # Initialize
        self.symbol_vars['btc'].set(True)
        self.symbol_vars['eth'].set(True)
        self.select_all_steps()  # Select all steps by default
        self.add_log("🚀 Analytics GUI loaded successfully!")
        self.add_log("Select symbols and click 'Start Update' to begin")
        self.add_log("⚠️ This will execute the REAL analytics pipeline!")
        
    def select_all(self):
        for var in self.symbol_vars.values():
            var.set(True)
    
    def select_none(self):
        for var in self.symbol_vars.values():
            var.set(False)
    
    def select_popular(self):
        self.select_none()
        self.symbol_vars['btc'].set(True)
        self.symbol_vars['eth'].set(True)
    
    def select_all_steps(self):
        for var in self.step_vars.values():
            var.set(True)
    
    def select_no_steps(self):
        for var in self.step_vars.values():
            var.set(False)
    
    def select_price_logs_only(self):
        self.select_no_steps()
        self.step_vars['update_price_logs'].set(True)
    
    def select_lookup_only(self):
        self.select_no_steps()
        self.step_vars['generate_lookup_tables'].set(True)
    
    def get_selected_steps(self):
        return [step for step, var in self.step_vars.items() if var.get()]
    
    def check_existing_progress(self):
        """Check for existing progress in the work_progress schema."""
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            # Check if work_progress schema exists and has data
            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.schemata 
                WHERE schema_name = 'work_progress'
            """)
            
            if cursor.fetchone()[0] == 0:
                conn.close()
                return
            
            # Check for any progress data
            cursor.execute("""
                SELECT table_name FROM information_schema.tables 
                WHERE table_schema = 'work_progress' 
                AND table_name LIKE 'ttc_progress_incremental'
            """)
            
            if not cursor.fetchall():
                conn.close()
                return
            
            # Get progress statistics
            cursor.execute("""
                SELECT 
                    status,
                    COUNT(*) as count,
                    SUM(rows_generated) as total_rows
                FROM work_progress.ttc_progress_incremental 
                GROUP BY status
            """)
            
            stats = {}
            total_ttc = 0
            total_rows = 0
            
            for row in cursor.fetchall():
                status, count, rows = row
                stats[status] = {
                    'count': count,
                    'rows': rows or 0
                }
                total_ttc += count
                total_rows += rows or 0
            
            if total_ttc > 0:
                completed_pct = (stats.get('completed', {}).get('count', 0) / total_ttc) * 100
                pending_pct = (stats.get('pending', {}).get('count', 0) / total_ttc) * 100
                
                if completed_pct > 0:
                    self.add_log(f"📊 Found existing progress: {completed_pct:.1f}% completed ({stats.get('completed', {}).get('count', 0)}/{total_ttc} TTC values)")
                    self.add_log(f"📊 Total rows generated: {total_rows:,}")
                    
                    # Ask user if they want to resume
                    response = messagebox.askyesno(
                        "Resume Progress", 
                        f"Found existing progress: {completed_pct:.1f}% completed\n\n"
                        f"Would you like to resume from where it left off?\n\n"
                        f"Click 'Yes' to resume\n"
                        f"Click 'No' to start fresh"
                    )
                    
                    if response:
                        self.add_log("✅ Will resume existing progress")
                    else:
                        self.add_log("🔄 Will start fresh (existing progress will be ignored)")
            
            conn.close()
            
        except Exception as e:
            self.add_log(f"⚠️ Could not check existing progress: {str(e)}")
    
    def get_selected_symbols(self):
        return [symbol for symbol, var in self.symbol_vars.items() if var.get()]
    
    def start_update(self):
        symbols = self.get_selected_symbols()
        if not symbols:
            messagebox.showerror("Error", "Please select at least one symbol")
            return
        
        steps = self.get_selected_steps()
        if not steps:
            messagebox.showerror("Error", "Please select at least one step to run")
            return
        
        self.is_running = True
        self.is_paused = False
        self.start_button.config(state=tk.DISABLED)
        self.pause_button.config(state=tk.NORMAL)
        self.resume_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.status_var.set("Starting analytics update...")
        
        self.add_log(f"🚀 Starting analytics update for: {', '.join(symbols).upper()}")
        self.add_log(f"📋 Selected steps: {', '.join(steps)}")
        
        # Start the process in a separate thread
        thread = threading.Thread(target=self.run_analytics, args=(symbols,))
        thread.daemon = True
        thread.start()
    
    def run_analytics(self, symbols):
        try:
            # Get selected steps
            selected_steps = self.get_selected_steps()
            
            # Get the path to analytics_updater.py
            script_dir = os.path.dirname(os.path.abspath(__file__))
            updater_path = os.path.join(script_dir, "analytics_updater.py")
            
            # Build command with selected steps
            command = [sys.executable, updater_path] + symbols
            
            # Add step selection arguments
            if selected_steps:
                command.extend(["--steps"] + selected_steps)
            
            # Start the process
            self.process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            self.add_log("✅ Analytics process started successfully")
            self.add_log(f"📋 Running steps: {', '.join(selected_steps)}")
            self.status_var.set("Analytics update running...")
            
            # Monitor the process
            current_step = 0
            while self.process and self.process.poll() is None:
                output = self.process.stdout.readline()
                if output:
                    line = output.strip()
                    self.add_log(line)
                    
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
                    elif "Step 9" in line or "Master lookup table creation" in line:
                        current_step = 9
                    
                    self.update_progress(current_step)
                    
                    # Show detailed progress
                    if "PROGRESS:" in line:
                        self.add_log(f"📊 {line.replace('PROGRESS: ', '')}")
                    
                    # Update UI in main thread
                    if self.is_paused:
                        self.root.after(0, lambda: self.status_var.set(f"Step {current_step}/8 - PAUSED"))
                    else:
                        self.root.after(0, lambda: self.status_var.set(f"Step {current_step}/8 - Running..."))
                
                time.sleep(0.1)
            
            # Process finished
            return_code = self.process.returncode if self.process else None
            self.process = None
            
            if return_code == 0:
                self.add_log("🎉 Analytics update completed successfully!")
                self.status_var.set("Completed successfully")
            else:
                self.add_log(f"❌ Analytics update failed with return code: {return_code}")
                self.status_var.set("Failed")
                
        except Exception as e:
            self.add_log(f"❌ Error: {str(e)}")
            self.status_var.set("Error occurred")
        finally:
            self.is_running = False
            self.root.after(0, self.reset_ui)
    
    def stop_update(self):
        if self.process:
            try:
                # Get the process ID
                pid = self.process.pid
                self.add_log(f"⏹️ Stopping analytics process (PID: {pid})")
                
                # Kill the main process and all its children
                import subprocess
                import signal
                
                # Use pkill to kill the entire process tree
                try:
                    # Kill all child processes of the analytics_updater
                    subprocess.run(['pkill', '-P', str(pid)], check=False)
                    self.add_log("✅ Killed child processes")
                    
                    # Kill the main process
                    self.process.terminate()
                    self.add_log("✅ Terminated main process")
                    
                    # Force kill if it doesn't terminate within 5 seconds
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.add_log("⚠️ Force killed main process")
                        
                except Exception as e:
                    self.add_log(f"⚠️ Error killing child processes: {str(e)}")
                    # Fallback: just terminate the main process
                    self.process.terminate()
                
                self.add_log("⏹️ Analytics update stopped by user")
                self.status_var.set("Stopped by user")
                
                # Reset pause state
                self.is_paused = False
                
            except Exception as e:
                self.add_log(f"❌ Error stopping process: {str(e)}")
                self.status_var.set("Error stopping process")
    
    def pause_update(self):
        """Pause the running analytics process"""
        if self.process and self.is_running and not self.is_paused:
            try:
                import signal
                import os
                
                # Send SIGSTOP to pause the process
                os.kill(self.process.pid, signal.SIGSTOP)
                
                self.is_paused = True
                self.pause_button.config(state=tk.DISABLED)
                self.resume_button.config(state=tk.NORMAL)
                self.status_var.set("Paused")
                self.add_log("⏸️ Analytics update paused")
                
            except Exception as e:
                self.add_log(f"❌ Error pausing process: {str(e)}")
                self.status_var.set("Error pausing process")
    
    def resume_update(self):
        """Resume the paused analytics process"""
        if self.process and self.is_running and self.is_paused:
            try:
                import signal
                import os
                
                # Send SIGCONT to resume the process
                os.kill(self.process.pid, signal.SIGCONT)
                
                self.is_paused = False
                self.pause_button.config(state=tk.NORMAL)
                self.resume_button.config(state=tk.DISABLED)
                self.status_var.set("Running...")
                self.add_log("▶️ Analytics update resumed")
                
            except Exception as e:
                self.add_log(f"❌ Error resuming process: {str(e)}")
                self.status_var.set("Error resuming process")
    
    def reset_progress(self):
        try:
            response = messagebox.askyesno(
                "Reset Progress",
                "This will reset ALL progress and start fresh.\n\n"
                "Are you sure you want to continue?"
            )
            if not response:
                return
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            # Reset all TTC values to pending status
            cursor.execute("""
                UPDATE work_progress.ttc_progress_incremental
                SET status = 'pending', started_at = NULL, completed_at = NULL,
                    rows_generated = 0, error_message = NULL
            """)
            
            # Clear ALL old progress reports for a completely fresh start
            cursor.execute("""
                DELETE FROM work_progress.ttc_progress_incremental 
                WHERE status = 'completed'
            """)
            
            conn.commit()
            conn.close()
            self.add_log("✅ Progress reset - all TTC values marked as pending")
            self.add_log("🗑️ Old progress reports cleared")
            self.add_log("🔄 Next run will start fresh")
        except Exception as e:
            self.add_log(f"❌ Error resetting progress: {str(e)}")
            messagebox.showerror("Error", f"Failed to reset progress: {str(e)}")
    
    def reset_ui(self):
        self.start_button.config(state=tk.NORMAL)
        self.pause_button.config(state=tk.DISABLED)
        self.resume_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.DISABLED)
        if not self.is_running:
            self.status_var.set("Ready")
    
    def update_progress(self, step):
        # Realistic progress calculation
        if step <= 6:
            progress = step * 2  # 2% per step = 12% total
        elif step == 7:
            progress = 12 + 8  # 20% for fingerprints
        elif step == 8:
            progress = 20 + 70  # 70% for lookup tables
        elif step == 9:
            progress = 90 + 10  # 10% for master table creation
        else:
            progress = 0
        
        self.progress_var.set(progress)
        
        # Update step labels
        for i in range(1, 10):
            label = self.step_labels[i]
            if i < step:
                label.config(foreground="green")
            elif i == step:
                label.config(foreground="orange")
            else:
                label.config(foreground="gray")
        
        # Update progress label
        if step > 0:
            self.progress_label.config(text=f"Step {step}/9 - {progress:.1f}% complete")
    
    def add_log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}\n"
        
        self.logs.append(log_entry)
        self.log_text.insert(tk.END, log_entry)
        self.log_text.see(tk.END)
        
        # Keep only last 1000 lines
        if len(self.logs) > 1000:
            self.logs = self.logs[-1000:]
    
    def clear_logs(self):
        self.log_text.delete(1.0, tk.END)
        self.logs = []
        self.add_log("🗑️ Logs cleared")
    
    def export_logs(self):
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"analytics_log_{timestamp}.txt"
            
            with open(filename, 'w') as f:
                f.writelines(self.logs)
            
            self.add_log(f"📥 Logs exported to: {filename}")
            messagebox.showinfo("Export", f"Logs exported to: {filename}")
        except Exception as e:
            messagebox.showerror("Export Error", f"Failed to export logs: {str(e)}")

    def cleanup_orphaned_processes(self):
        """
        Check for and kill any orphaned analytics processes on startup.
        This prevents multiple instances from running simultaneously.
        """
        try:
            import subprocess
            import psutil
            
            # Look for specific analytics subprocesses that we spawn
            killed_count = 0
            current_pid = os.getpid()
            
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    cmdline = proc.info['cmdline']
                    if cmdline and proc.info['pid'] != current_pid:
                        # Only target specific analytics subprocesses we spawn
                        cmdline_str = ' '.join(cmdline).lower()
                        if ('analytics_updater.py' in cmdline_str or 
                            'probability_lookup_generator.py' in cmdline_str):
                            proc.terminate()
                            killed_count += 1
                            print(f"   Killed process {proc.info['pid']}: {' '.join(cmdline[:3])}...")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            if killed_count > 0:
                print(f"⚠️ Killed {killed_count} orphaned analytics subprocesses on startup")
            else:
                print("✅ No orphaned analytics subprocesses found")
            
        except Exception as e:
            print(f"⚠️ Could not check for orphaned processes: {str(e)}")

def main():
    root = tk.Tk()
    app = AnalyticsGUI(root)
    
    # Add cleanup when window is closed
    def on_closing():
        if app.is_running:
            if app.is_paused:
                response = messagebox.askyesnocancel(
                    "Process Paused", 
                    "Analytics update is currently paused.\n\n"
                    "What would you like to do?\n\n"
                    "Yes = Resume and keep running\n"
                    "No = Stop the process\n"
                    "Cancel = Keep paused and close"
                )
                if response is True:  # Resume
                    app.resume_update()
                    root.after(1000, root.destroy)  # Give time to resume
                elif response is False:  # Stop
                    app.stop_update()
                    root.after(2000, root.destroy)  # Give time to stop
                else:  # Cancel - just close
                    root.destroy()
            else:
                response = messagebox.askyesno(
                    "Stop Running Process", 
                    "Analytics update is currently running.\n\n"
                    "Do you want to stop it before closing?"
                )
                if response:
                    app.stop_update()
                    # Wait a moment for processes to terminate
                    root.after(2000, root.destroy)
                else:
                    root.destroy()
        else:
            root.destroy()
    
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()
