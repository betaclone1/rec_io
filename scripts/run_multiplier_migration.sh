#!/bin/bash

# Script to run multiplier column migration on remote database
# Remote database: 137.184.224.94

echo "Running multiplier column migration on remote database..."

# Connect to remote database and run the migration
psql -h 137.184.224.94 -U rec_io_user -d rec_io_db -f scripts/update_multiplier_column.sql

echo "Migration completed!"
