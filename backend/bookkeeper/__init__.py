"""
User-level bookkeeping: QuickBooks Online, Mercury Bank, and jobs that align with Kalshi/account_sync.

Layout:
  bookkeeper.py — CLI: QBO chart/transfers, Kalshi vs QBO reconcile (journal entry)
  kalshi_portfolio_balance.py — GET Kalshi v2 /portfolio/balance (prod credentials)
  quickbooks/ — OAuth + QBO v3 REST (quickbooks_online_rest.py); see quickbooks/dotenv.example
  mercury/    — Mercury API (see mercury/dotenv.example)
  jobs/       — workers / schedulers (future)
"""
