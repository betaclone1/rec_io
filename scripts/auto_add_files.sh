#!/bin/bash

# Script to automatically add all untracked files that aren't ignored by .gitignore
# This ensures all new files are tracked unless specifically ignored

echo "Auto-adding untracked files..."

# Get all untracked files
untracked_files=$(git ls-files --others --exclude-standard)

if [ -n "$untracked_files" ]; then
    echo "Adding untracked files:"
    echo "$untracked_files"
    
    # Add all untracked files
    echo "$untracked_files" | xargs git add
    
    echo "All untracked files have been added to staging."
    echo "Run 'git status' to see what's been staged."
else
    echo "No untracked files to add."
fi
