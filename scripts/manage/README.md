# Manage scripts

Monitors list, master users, user registration, and related tests.

- **manage_monitors_list.sh** — Create table, list, add, update-status, update-auto-trade, delete, show. See docs/MONITORS_LIST_INFRASTRUCTURE.md.
- **manage_master_users.sh** — Master user management.
- **user_registration_system.sh** — User registration (includes monitors_list table creation).
- **test_monitors_list_table.py** — Test script for monitors list table.

Run from project root, e.g. `./scripts/manage/manage_monitors_list.sh list user_0001`.
