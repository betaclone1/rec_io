# PostgreSQL and host options (2026-10-21)

```yaml
doc_id: PG_AND_HOST_OPTIONS
status: owner_instinct_overrides_managed_default
not_executed: true
reversibility: tier_2_data_store
owner_priority: high_level_architecture_first
chief_question: where PostgreSQL lives once processes leave the single droplet
working_assumption: self_managed_postgresql_on_its_own_lean_droplet
managed_option: priced_alternative_below
cloud_switch: hold
aurora: reject_for_this_workload
baseline: AUDIT_V3_BASELINE.md
direction: V4_DIRECTION.md
prices_checked: 2026-10-21
owner_note_date: 2026-10-21
postgres_role: backbone
upgrade_policy: serious handling of updates and deprecations; thorough test before traffic cutover; impact unconfirmed until that test
```

Owner instinct, stated before the detail pass: Postgres can run on a lean droplet of its own. The in-repo database work is enough that a DigitalOcean or AWS managed database is a premium they do not need to pay. Later sessions fill in size, networking, and restore drills. Nothing here authorizes creating droplets or changing production.

---

## Working assumption

One small DigitalOcean droplet runs PostgreSQL and nothing else. Ingest, trading, and backtest hosts connect to it over the private network. Redis stays on the trading host. Cycle packages stay files, not rows.

The repo already owns the parts that justify this:

| Already built | Where |
|---------------|--------|
| Versioned schema changes | `scripts/migrations/`, `scripts/db/run_migration.py`, `system.schema_migrations` |
| Drift check against the schema reference | `scripts/db/check_db_schema_drift.py` |
| Nightly logical dump to Google Drive, 14 copies | `scripts/backup/create_compressed_db_backup.sh`, `scripts/gdrive/upload-db-backup.js`, cron in `docs/PRODUCTION_HOST.md` |
| Whole-machine snapshots, 5 copies | `scripts/do/auto_backup_snapshot.py` |
| Tenant RLS, roles, Eastern session timezone | `backend/core/config/database.py`, `backend/core/tenant_context.py` |

There is no Patroni, repmgr, pgBackRest, or streaming replica in the current tree. The only replication write-up is an archived v2 note. Recovery on this design is restore a dump or a droplet snapshot. That is the trade for skipping the managed premium: about **$37/month** versus a single 4 GiB managed node ($61 vs a $24 Basic 4 GiB droplet), and about **$98/month** versus a managed node plus standby ($122). At a 4.7 GB database those dollars buy automated failover, 7-day point-in-time recovery, and vendor patching.

A sensible lean size is the Basic **4 GiB / 2 vCPU / 80 GiB** droplet at **$24/month** ([droplet pricing](https://www.digitalocean.com/pricing/droplets)). The 2 GiB / $12 plan is the same RAM class the managed 2 GiB node was called tight for, once every app process holds a connection. Disk on the $24 plan holds the 4.7 GB database with room for WAL and dumps. Postgres listens on the VPC address. Port 5432 stays off the public interface.

PostgreSQL is a backbone of the system. Any major upgrade, minor update, or deprecation that lands with the new database droplet is handled seriously. The 14 → 17 jump is **not** pre-judged as low impact. The owner rarely uses schema `public`; that is a hint, not a clearance.

**Gate:** the implementing agent confirms behavior on the new major and runs a thorough test pass before any production traffic moves. That pass covers dump/restore onto PostgreSQL 17, grants, RLS, `NOTIFY`, connection settings, migrations, and every other change the release notes introduce that this codebase can hit. A fresh PostgreSQL 15+ cluster revokes `CREATE` on schema `public` from ordinary users. That is one check, not the whole check. Ubuntu 22.04’s default packages are 14, so the new host uses the PostgreSQL apt repository.

Community support for PostgreSQL 14 ends on **2026-11-12**. As of this note (2026-10-21) that date has not arrived. Production is still 14.18.

The managed price table below stays as the alternative if a failover requirement shows up. It is no longer the default.

AWS RDS for PostgreSQL is the credible alternative if the move to AWS happens for reasons outside this cost comparison. Aurora is the wrong product at this size.

A larger all-in-one droplet does not fix the problem. The live host is CPU-bound with memory to spare, and Postgres is sharing those cores with ingest and trading.

---

## What the database actually is

From the 2026-10-21 read-only audit (`AUDIT_V3_BASELINE.md` §2):

| Fact | Value | Why it matters |
|------|--------|----------------|
| Engine on the droplet | PostgreSQL 14.18 | Community end of life **2026-11-12** ([versioning policy](https://www.postgresql.org/support/versioning/)) |
| Database size | 4,675 MB | A small OLTP database. Not a warehouse |
| Historical files | 26 GB under `backend/data/historical_data` | Object storage or disk, not Postgres |
| Redis | 61 MB, loopback, 206 keys | Not a sizing problem |
| RAM | 15 GiB, ~12 GiB available | The box is not memory-bound |
| Load | 7.28 / 9.31 / 9.44 on 8 vCPU | The box is CPU-bound |
| Disk | 310 GB filesystem, 16% used | Matches the published Basic **8 vCPU / 16 GiB / 320 GiB** droplet. SKU was not read from the API |
| Listen | Postgres on `0.0.0.0:5432` | Private networking is an operational fix, not a scale fix |
| Writers | Many supervisor processes, one tenant trading (`0001`) | Connection count matters more than disk |
| Session time zone | App sets `America/New_York` per connection | Survives a managed move. Repo note: custom `rec.*` GUCs are the PG 14 caveat; PG 15+ does not need `custom_variable_classes` (`docs/MASTER_DB_SCHEMA_REFERENCE.md`) |
| Backups today | Nightly `pg_dump` to Drive, droplet snapshots | Managed backups replace the dump as the database backup. Drive can remain a second copy |

Backtests already read sealed cycle packages, not live trade tables. The backtest host should keep doing that. It should not run sweeps against the primary.

---

## Options

### A. Incumbent: Postgres on the app droplet

List price of the matching Basic droplet is **$96/month** (8 vCPU, 16 GiB, 320 GiB SSD, 6 TB transfer). [Droplet pricing](https://www.digitalocean.com/pricing/droplets), checked 2026-10-21. That price includes the CPU that is already saturated. Postgres patching, major upgrades, and failover are manual. The public `5432` bind stays until someone closes it. A CPU-Optimized 8 vCPU / 16 GiB droplet is **$168/month** and still mixes ingest, trading, and the database on one kernel.

### B. Priced alternative: DigitalOcean Managed PostgreSQL

Official prices, [Managed Databases](https://www.digitalocean.com/pricing/managed-databases) and [PostgreSQL pricing](https://docs.digitalocean.com/products/databases/postgresql/details/pricing/) (docs last verified 30 Sep 2026):

| Plan | Shape | Monthly |
|------|--------|---------|
| Standard 2 GiB | 1 vCPU, 30 GiB disk | $30.45 |
| Standard 4 GiB | 2 vCPU, 60 GiB disk | $60.90 |
| Standby | Same size as the primary | Same price again |
| Standard extra disk | | $0.215 / GiB-month |
| Advanced entry | 8 GiB / 2 vCPU | $130, plus the same again for a standby |

Fit: **4 GiB / 2 vCPU**. The 2 GiB plan is tight once `shared_buffers` and a connection from each trading and ingest process are in RAM. The database is under 5 GB, so 60 GiB of disk is enough without extra storage. A 16 GiB managed node ($244) buys RAM the workload does not use.

What you gain operationally, from [DO create docs](https://docs.digitalocean.com/products/databases/postgresql/how-to/create/) and [limits](https://docs.digitalocean.com/products/databases/postgresql/details/limits/):

- Daily backups and point-in-time recovery (PITR window is 7 days).
- Private VPC. Trusted sources replace `0.0.0.0:5432`. Database traffic does not count against droplet bandwidth.
- Standby failover. DO states **99.95%** monthly uptime with a standby and **99.5%** without.
- New Standard clusters: PostgreSQL 15, 16, 17, 18. **Choose 17** (community support through 2029-11-08 on DO’s table). Skip 14. Skip 18 until the app has been run on 17.
- Major upgrade is a dump/restore or managed upgrade, done once, off the trading CPU.

**Date constraint.** [Plan change note](https://docs.digitalocean.com/notes/2026/dbaas-plan-changes/), effective **2026-10-15** for accounts that have never created a PostgreSQL or MySQL cluster, and **2026-11-30** for every account:

- New **Standard** clusters cannot be larger than 4 GiB and cannot add a standby or a read-only node.
- Existing clusters are left as they are.
- Advanced Edition gained Basic shared-CPU plans from 8 GiB to 64 GiB on 2026-10-15. Those prices were not on the note.

This production database is on the droplet, not a managed cluster. If this team has never created a managed Postgres or MySQL cluster, Standard standbys may already be unavailable. Then the HA choice is Advanced (entry **$130**, standby another **$130**) or a single Standard node at **$60.90** and an accepted failover gap. Confirm in the DO control panel before treating $122 as the HA price.

### C. AWS RDS for PostgreSQL

Use this if the platform moves to AWS. Do not run a hybrid (droplets in NYC, RDS in `us-east-1`) for the trading path. The extra network hop is paid on every order and every strike read, and you operate two clouds.

List-price anchors (third-party reads of the AWS price list, not the interactive calculator widget):

| Piece | us-east-1 on-demand | Source date |
|-------|---------------------|-------------|
| `db.t4g.medium` Single-AZ (2 vCPU, 4 GiB, burstable) | $0.065/hour ≈ $47 / 730 h | [FactualMinds](https://www.factualminds.com/tools/aws-rds-pricing-calculator/), 2026-10-17 |
| `db.t4g.medium` Multi-AZ | $0.129/hour ≈ $94 | [startup advisor cache](https://github.com/awslabs/startups/blob/main/advisor/plugins/aws-startup-advisor/skills/migration-to-aws/references/shared/pricing-cache.md), 2026-05-20, Multi-AZ column |
| `db.m7g.large` Single-AZ (2 vCPU, 8 GiB, not burstable) | $0.168/hour ≈ $123 | [cloud-credits.org](https://cloud-credits.org/prices/rds/db-m7g-large), 2026-10-14 |
| `db.m7g.large` Multi-AZ | $0.337/hour ≈ $246 | same |
| gp3 storage | $0.115 / GB-month Single-AZ, $0.230 Multi-AZ | [getfinops calculator](https://tools.getfinops.cloud/rds-cost-calculator/), price list 2026-09-19 |
| T instance CPU credits above baseline | $0.075 per vCPU-hour | [AWS RDS PostgreSQL pricing](https://aws.amazon.com/rds/postgresql/pricing/) |

A fair RDS twin of the DO 4 GiB plan is **`db.m7g.large` or `db.t4g.medium`, 20–50 GiB gp3, PostgreSQL 17**. Storage on 50 GiB gp3 is about **$6/month** Single-AZ at $0.115. Multi-AZ doubles the instance and the storage.

`db.t4g.medium` is cheaper and is the wrong default for a CPU-sensitive trading database: T instances bill extra when CPU stays above the baseline, and this system already runs hot. Prefer `db.m7g.large` if the database is on AWS.

RDS standard support for PostgreSQL 14 runs through **2027-02-28**, then paid Extended Support ([RDS calendar](https://docs.aws.amazon.com/AmazonRDS/latest/PostgreSQLReleaseNotes/postgresql-release-calendar.html)). That is not a reason to stay on 14. Community fixes stop on 2026-11-12.

What AWS adds, and what it costs in attention: Multi-AZ across availability zones, IAM, longer backup retention, a deeper instance catalog. A private RDS instance usually wants a VPC, and anything in a private subnet that still calls Kalshi, Intuit, or Drive needs a NAT gateway or VPC endpoints. That line item is easy to omit from a droplet-to-RDS comparison. Region choice for a full move is `us-east-1` (cheapest, close to typical US exchange edges) unless latency measurements say otherwise. NYC droplets to `us-east-1` are not free of milliseconds.

### D. Aurora PostgreSQL

Reject for this workload. Aurora bills instance hours plus storage that scales with data, and Aurora Standard also bills I/O per request ([AWS pricing page](https://aws.amazon.com/rds/postgresql/pricing/) describes per-request I/O for Aurora). The database is 4.7 GB with modest I/O. Aurora’s floor is built for a larger working set and for readers you do not have. Revisit if the hot database passes tens of gigabytes or the trading tier needs several read endpoints.

### E. Self-managed Postgres on a second droplet or an EC2 instance

Cheapest sticker (a $24–$48 droplet, or a small EC2) and the worst operations: you still patch, you still fail over by hand, and you still take the `pg_dump`. Use only as a short bridge if managed networking blocks a cutover. Do not make it the v4 design.

---

## Money, same job

Illustrative list prices for **database only**, 730-hour month, no tax, no reserved-instance discount. HA means one standby or RDS Multi-AZ.

| Placement | Approx. monthly | Failover |
|-----------|-----------------|----------|
| Leave it on the current droplet | $0 extra on the ~$96 droplet | Manual. Droplet snapshot is the whole machine |
| DO Standard 4 GiB, no standby | $61 | DO 99.5% SLA. Restore from backup |
| DO Standard 4 GiB + standby | $122 | DO 99.95% SLA. Only if the account can still create it |
| DO Advanced 8 GiB + standby | $260 | Use if Standard standby is already closed |
| RDS `db.t4g.medium` Single-AZ + 50 GB gp3 | ~$53 | Single AZ |
| RDS `db.m7g.large` Single-AZ + 50 GB gp3 | ~$129 | Single AZ |
| RDS `db.m7g.large` Multi-AZ + 50 GB gp3 | ~$258 | Automatic |

The database line is small next to a second and third droplet. CPU-Optimized 4 vCPU / 8 GiB is **$84/month**; Basic 4 vCPU / 8 GiB is **$48/month** ([droplet pricing](https://www.digitalocean.com/pricing/droplets)). Two Basic app droplets plus a $122 HA database is on the order of **$220/month** versus **$96** today, and it is the shape that gets ingest off the trading cores. Two CPU-Optimized 4 vCPU boxes plus that database is on the order of **$290**. Buying one CPU-Optimized 8 vCPU / 16 GiB monolith at **$168** keeps the contention.

Spaces for the 26 GB archive, when that host exists: **$5/month** includes 250 GiB and 1 TB outbound. Transfer from NYC Spaces to NYC droplets via the VPC resolver is not counted as Spaces outbound. [Spaces pricing](https://docs.digitalocean.com/products/spaces/details/pricing/), docs last verified 13 Jul 2026. Cold storage at $0.007/GiB is for data you rarely read. Backtests read packages. Keep them on Standard Spaces.

---

## How this sits on the process split

```yaml
postgres: one lean droplet, PostgreSQL only, VPC-only listen. All app hosts connect privately.
redis: trading host, loopback or VPC-only. Do not put it in another region.
live_ingest_host: market watchdog, CF Benchmarks, Pyth, 15m strike generator, snapshot publisher. Writes live_state to Redis and durable rows to Postgres.
trading_host: AES, ATS, trade manager, trade executor, maker and taker agents, account sync, lifecycle consumer, monitor manager, position risk, main_app, read_api, switchboard.
archive: cycle packages and other historical files on Spaces (or the ingest host disk until Spaces exists). Drive dump remains the offsite database copy until managed backups are proven.
backtest_host: reads packages. No standing connection pool into the primary. Can be powered off.
hourly_processes: out of the v4 push (V4_DIRECTION.md).
```

One database. Not a trading database plus an ingest database. The hot working set is one catalog (`users_0001`, `live_data`, `system`) with foreign keys and triggers across it. Splitting schemas across servers would be a rewrite. A read replica is optional later for the UI and is not required to start.

`live_data` price rings and `analytics` fingerprint tables are the parts that could move to files later. They are not a reason to run two Primaries now.

---

## What would change the verdict

| Condition | Then |
|-----------|------|
| The owner’s AWS reasons are binding (account, compliance, other systems already there) | RDS `db.m7g.large`, PostgreSQL 17, gp3, Multi-AZ if failover has to be automatic. Move droplets in the same change. No hybrid. |
| Standard standby is already blocked and Advanced HA at ~$260 is refused | Single Standard 4 GiB node at $61, plus a rehearsed restore. Say so explicitly. Trading stops if that node is down. |
| Hot database grows past ~50 GB or ingest and trading need different failure domains | Revisit a replica first. A second primary still waits on a schema split that does not exist. |
| A required extension or superuser setting is missing on DO managed | RDS or a self-managed node. Check `rec.tenant_pg_schema` and RLS on a throwaway cluster before cutover. |
| Cycle data becomes a product with lifecycle tiers and many readers | S3 (or Spaces Cold for sealed months) beside the OLTP database. Still not Aurora. |

---

## Independent of the cloud choice

Upgrade off PostgreSQL 14 before **2026-11-12**. That date is closer than the host split. Target **17**. Take the dump from the droplet, restore into the managed major, run migrations there, then point `REC_DB_HOST` at the private endpoint. Do not restore with `init_database()` as the migration path.

Close public `5432` when the app hosts are the only clients. Until the managed cutover, that is a firewall change on the current droplet, separate from this recommendation and not done here.
