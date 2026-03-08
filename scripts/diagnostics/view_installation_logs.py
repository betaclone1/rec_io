#!/usr/bin/env python3
"""
Installation Log Viewer

This script provides a command-line interface to view and analyze
installation access logs from the system.installation_access_log table.
"""

import os
import sys
import argparse
from datetime import datetime, timedelta
from tabulate import tabulate

# Add the backend directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from util.installation_logger import InstallationLogger

def format_duration(seconds):
    """Format duration in seconds to human readable format."""
    if seconds is None:
        return "N/A"
    
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"

def format_timestamp(timestamp):
    """Format timestamp to readable format."""
    if timestamp is None:
        return "N/A"
    
    if isinstance(timestamp, str):
        return timestamp
    else:
        return timestamp.strftime("%Y-%m-%d %H:%M:%S")

def view_recent_installations(limit=10):
    """View recent installation access logs."""
    logger = InstallationLogger()
    installations = logger.get_recent_installations(limit)
    
    if not installations:
        print("No installation logs found.")
        return
    
    # Prepare data for tabulation
    table_data = []
    for inst in installations:
        table_data.append([
            inst['id'],
            inst['installer_user_id'],
            inst['installer_name'][:20] + "..." if len(inst['installer_name']) > 20 else inst['installer_name'],
            inst['installer_email'],
            inst['installer_ip_address'],
            format_timestamp(inst['connection_start']),
            format_duration(inst['clone_duration_seconds']),
            inst['tables_cloned'] or 0,
            inst['total_rows_cloned'] or 0,
            inst['status'],
            inst['schemas_accessed']
        ])
    
    headers = [
        "ID", "User ID", "Name", "Email", "IP", "Start Time", 
        "Duration", "Tables", "Rows", "Status", "Schemas"
    ]
    
    print(f"\n📊 Recent Installation Access Logs (Last {limit})")
    print("=" * 80)
    print(tabulate(table_data, headers=headers, tablefmt="grid"))

def view_installation_stats():
    """View installation statistics."""
    logger = InstallationLogger()
    stats = logger.get_installation_stats()
    
    if not stats:
        print("No installation statistics available.")
        return
    
    print("\n📈 Installation Statistics")
    print("=" * 40)
    print(f"Total Installations: {stats['total_installations']}")
    print(f"Successful: {stats['successful_installations']}")
    print(f"Failed: {stats['failed_installations']}")
    print(f"Success Rate: {stats['success_rate']:.1f}%")
    print(f"Recent Activity (30 days): {stats['recent_activity_30_days']}")

def view_failed_installations(limit=10):
    """View failed installation attempts."""
    logger = InstallationLogger()
    installations = logger.get_recent_installations(limit * 2)  # Get more to filter
    
    failed_installations = [inst for inst in installations if inst['status'] == 'failed'][:limit]
    
    if not failed_installations:
        print("No failed installation attempts found.")
        return
    
    # Prepare data for tabulation
    table_data = []
    for inst in failed_installations:
        table_data.append([
            inst['id'],
            inst['installer_user_id'],
            inst['installer_name'][:20] + "..." if len(inst['installer_name']) > 20 else inst['installer_name'],
            inst['installer_email'],
            inst['installer_ip_address'],
            format_timestamp(inst['connection_start']),
            inst['error_message'][:50] + "..." if inst['error_message'] and len(inst['error_message']) > 50 else inst['error_message'] or "N/A"
        ])
    
    headers = ["ID", "User ID", "Name", "Email", "IP", "Start Time", "Error"]
    
    print(f"\n❌ Failed Installation Attempts (Last {limit})")
    print("=" * 80)
    print(tabulate(table_data, headers=headers, tablefmt="grid"))

def view_installation_details(installation_id):
    """View detailed information about a specific installation."""
    logger = InstallationLogger()
    installations = logger.get_recent_installations(100)  # Get more to find the specific one
    
    installation = None
    for inst in installations:
        if inst['id'] == installation_id:
            installation = inst
            break
    
    if not installation:
        print(f"Installation with ID {installation_id} not found.")
        return
    
    print(f"\n🔍 Installation Details - ID: {installation_id}")
    print("=" * 50)
    print(f"User ID: {installation['installer_user_id']}")
    print(f"Name: {installation['installer_name']}")
    print(f"Email: {installation['installer_email']}")
    print(f"IP Address: {installation['installer_ip_address']}")
    print(f"User Agent: {installation['user_agent']}")
    print(f"Package Version: {installation['installation_package_version']}")
    print(f"Connection Start: {format_timestamp(installation['connection_start'])}")
    print(f"Connection End: {format_timestamp(installation['connection_end'])}")
    print(f"Duration: {format_duration(installation['clone_duration_seconds'])}")
    print(f"Status: {installation['status']}")
    print(f"Tables Cloned: {installation['tables_cloned'] or 0}")
    print(f"Total Rows Cloned: {installation['total_rows_cloned'] or 0}")
    print(f"Schemas Accessed: {installation['schemas_accessed']}")
    
    if installation['error_message']:
        print(f"Error Message: {installation['error_message']}")

def export_logs_to_csv(filename=None):
    """Export installation logs to CSV file."""
    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"installation_logs_{timestamp}.csv"
    
    logger = InstallationLogger()
    installations = logger.get_recent_installations(1000)  # Get all recent logs
    
    if not installations:
        print("No installation logs to export.")
        return
    
    import csv
    
    with open(filename, 'w', newline='') as csvfile:
        fieldnames = [
            'id', 'installer_user_id', 'installer_name', 'installer_email',
            'installer_ip_address', 'connection_start', 'connection_end',
            'clone_duration_seconds', 'tables_cloned', 'total_rows_cloned',
            'status', 'schemas_accessed', 'error_message', 'user_agent',
            'installation_package_version', 'created_at'
        ]
        
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        
        for inst in installations:
            writer.writerow(inst)
    
    print(f"✅ Installation logs exported to {filename}")

def main():
    parser = argparse.ArgumentParser(description="View installation access logs")
    parser.add_argument('--recent', '-r', type=int, default=10, 
                       help='Show recent installations (default: 10)')
    parser.add_argument('--stats', '-s', action='store_true',
                       help='Show installation statistics')
    parser.add_argument('--failed', '-f', type=int, default=10,
                       help='Show failed installations (default: 10)')
    parser.add_argument('--details', '-d', type=int,
                       help='Show details for specific installation ID')
    parser.add_argument('--export', '-e', type=str,
                       help='Export logs to CSV file')
    
    args = parser.parse_args()
    
    if args.stats:
        view_installation_stats()
    elif args.failed:
        view_failed_installations(args.failed)
    elif args.details:
        view_installation_details(args.details)
    elif args.export:
        export_logs_to_csv(args.export)
    else:
        view_recent_installations(args.recent)

if __name__ == "__main__":
    main()
