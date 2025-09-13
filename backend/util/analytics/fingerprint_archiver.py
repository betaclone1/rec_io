#!/usr/bin/env python3
"""
FINGERPRINT ARCHIVER
Creates dated zip archives of fingerprint files from a specified directory.
"""

import os
import zipfile
import glob
from datetime import datetime
from pathlib import Path
import argparse

def find_fingerprint_files(directory):
    """
    Find all fingerprint files in the specified directory.
    
    Args:
        directory (str): Path to directory containing fingerprint files
        
    Returns:
        list: List of file paths that match fingerprint patterns
    """
    fingerprint_patterns = [
        "*fingerprint*.csv",
        "*fingerprint*.json",
        "*fingerprint*.txt"
    ]
    
    fingerprint_files = []
    for pattern in fingerprint_patterns:
        files = glob.glob(os.path.join(directory, pattern))
        fingerprint_files.extend(files)
    
    return sorted(fingerprint_files)

def create_archive(files, output_dir, archive_name=None, symbol=None):
    """
    Create a zip archive of the specified files.
    
    Args:
        files (list): List of file paths to archive
        output_dir (str): Directory to save the archive
        archive_name (str, optional): Custom archive name
        symbol (str, optional): Symbol name (e.g., 'btc', 'eth')
        
    Returns:
        str: Path to the created archive file
    """
    if not files:
        print("❌ No fingerprint files found to archive")
        return None
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Generate archive name with timestamp if not provided
    if not archive_name:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if symbol:
            archive_name = f"{symbol}_fingerprint_archive_{timestamp}.zip"
        else:
            archive_name = f"fingerprint_archive_{timestamp}.zip"
    
    # Ensure .zip extension
    if not archive_name.endswith('.zip'):
        archive_name += '.zip'
    
    archive_path = os.path.join(output_dir, archive_name)
    
    print(f"📦 Creating archive: {archive_path}")
    print(f"📁 Found {len(files)} fingerprint files to archive")
    
    with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file_path in files:
            # Get just the filename for the archive
            filename = os.path.basename(file_path)
            print(f"  📄 Adding: {filename}")
            zipf.write(file_path, filename)
    
    # Get archive size
    archive_size = os.path.getsize(archive_path)
    size_mb = archive_size / (1024 * 1024)
    
    print(f"✅ Archive created successfully!")
    print(f"📊 Archive size: {size_mb:.2f} MB")
    print(f"📁 Archive location: {archive_path}")
    
    return archive_path

def main():
    parser = argparse.ArgumentParser(description="Archive fingerprint files with timestamp")
    parser.add_argument(
        "directory", 
        help="Directory containing fingerprint files to archive"
    )
    parser.add_argument(
        "--output", "-o",
        default="archives",
        help="Output directory for archives (default: 'archives')"
    )
    parser.add_argument(
        "--name", "-n",
        help="Custom archive name (without .zip extension)"
    )
    parser.add_argument(
        "--list-only", "-l",
        action="store_true",
        help="List fingerprint files without creating archive"
    )
    parser.add_argument(
        "--symbol", "-s",
        help="Symbol name for archive (e.g., 'btc', 'eth'). Auto-detected from directory if not specified."
    )
    
    args = parser.parse_args()
    
    # Check if input directory exists
    if not os.path.exists(args.directory):
        print(f"❌ Error: Directory '{args.directory}' does not exist")
        return 1
    
    # Find fingerprint files
    print(f"🔍 Scanning directory: {args.directory}")
    fingerprint_files = find_fingerprint_files(args.directory)
    
    if not fingerprint_files:
        print("❌ No fingerprint files found in the specified directory")
        print("   Looking for files matching: *fingerprint*.csv, *fingerprint*.json, *fingerprint*.txt")
        return 1
    
    print(f"📋 Found {len(fingerprint_files)} fingerprint files:")
    for file_path in fingerprint_files:
        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        size_kb = file_size / 1024
        print(f"  📄 {filename} ({size_kb:.1f} KB)")
    
    if args.list_only:
        print("\n📋 List-only mode: No archive created")
        return 0
    
    # Extract symbol from command line argument or directory path
    symbol = args.symbol
    if not symbol and args.directory:
        # Get the last directory name as the symbol
        dir_parts = args.directory.rstrip('/').split('/')
        if dir_parts:
            potential_symbol = dir_parts[-1]
            # Check if it looks like a symbol (lowercase, 3-4 chars)
            if potential_symbol.islower() and len(potential_symbol) in [3, 4]:
                symbol = potential_symbol
    
    # Create archive
    archive_path = create_archive(fingerprint_files, args.output, args.name, symbol)
    
    if archive_path:
        print(f"\n🎉 Fingerprint archive completed successfully!")
        return 0
    else:
        print(f"\n❌ Failed to create archive")
        return 1

if __name__ == "__main__":
    exit(main()) 