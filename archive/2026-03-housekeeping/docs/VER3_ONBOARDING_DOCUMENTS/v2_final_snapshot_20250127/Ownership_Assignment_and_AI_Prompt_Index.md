# Ownership Assignment & AI Prompt Index – REC.IO v2

## Purpose
Assign document and component ownership, and provide approved AI prompts for BMAD agents to update or regenerate documentation **without** violating operational safety rules.

> **🚨 CRITICAL SAFETY NOTICE:**  
> **NO AI AGENTS ARE PERMITTED TO PLACE LIVE TRADES FOR TESTING OR ANY OTHER PURPOSES.**  
> **NO AI AGENTS ARE PERMITTED TO ENABLE AUTOMATED TRADING FUNCTIONS FOR TESTING OR ANY OTHER PURPOSES.**  
> **NO AI AGENTS ARE PERMITTED AT ANY TIME TO PLACE LIVE TRADES OR ENABLE AUTOMATED TRADING FOR TESTING OR ANY OTHER PURPOSES.**
> All AI-assisted actions must be limited to documentation, code review, simulation, or analysis using safe datasets.

---

## 1. Ownership Assignment

| Document / Module | Owner | Notes |
|-------------------|-------|-------|
| **01_Architecture_Map/System_Overview.md** | Eric | Update after major architectural changes |
| **01_Architecture_Map/Component_Level_Documentation.md** | AI (Cursor) | Requires Eric’s review before publish |
| **02_Config/Port_and_Path_Configuration_Reference.md** | Eric defines rules → AI maintains | Update only from MASTER_PORT_MANIFEST.json |
| **03_Database_Schemas/Database_Schema_and_Migration_Plan.md** | AI | Update after schema changes |
| **04_Infrastructure/Deployment_Playbook.md** | AI | Update if deploy process changes |
| **04_Infrastructure/CI_CD_and_Container_Guide.md** | AI | Update when CI/CD pipeline changes |
| **05_Security/Secrets_Management_Policy.md** | Eric | Final approval required for any change |
| **05_Security/Disaster_Recovery_Plan.md** | Eric → AI formats | Must match live recovery process |
| **06_Strategy_and_Product_Logic/Trade_Strategy_Book.md** | Eric | AI may draft, Eric finalizes |
| **06_Strategy_and_Product_Logic/Feature_Roadmap.md** | Eric → AI updates | Update during planning sessions |
| **06_Strategy_and_Product_Logic/Known_Issues_and_Design_Constraints.md** | AI | Update quarterly |
| **06_Strategy_and_Product_Logic/Partner_Onboarding_Guide.md** | Eric | AI may draft, Eric approves |
| **Ownership Assignment & AI Prompt Index.md** | Eric & AI | Living document |

---

## 2. AI Prompt Index (Approved Prompts)

### 2.1 Architecture & Components
**Prompt:**  
"Update `System_Overview.md` in `/01_Architecture_Map/` to reflect the current deployed architecture as described in the latest `notes.md`. Ensure all service names, ports, and flows are accurate."

### 2.2 Port & Path Config
**Prompt:**  
"Regenerate `Port_and_Path_Configuration_Reference.md` from `MASTER_PORT_MANIFEST.json` and `config.json`, ensuring no hardcoded ports or paths are added."

### 2.3 Database Schema & Migration
**Prompt:**  
"Update `Database_Schema_and_Migration_Plan.md` to reflect any schema changes in `postgresql_schema.sql` and current legacy migration status."

### 2.4 Deployment Playbook
**Prompt:**  
"Rewrite `Deployment_Playbook.md` to match the current DigitalOcean deployment process, including rollback steps and health check procedures."

### 2.5 CI/CD Guide
**Prompt:**  
"Update `CI_CD_and_Container_Guide.md` to reflect changes in build, test, and deploy pipelines, ensuring compatibility with local-first development."

### 2.6 Security Docs
**Prompt:**  
"Review and update `Secrets_Management_Policy.md` to reflect current secrets handling practices, ensuring plaintext secrets and AI trade execution remain strictly prohibited."

**Prompt:**  
"Update `Disaster_Recovery_Plan.md` to match the current operational recovery procedures for DB failure, service crash, API outage, and broken deploy."

### 2.7 Strategy & Roadmap Docs
**Prompt:**  
"Update `Trade_Strategy_Book.md` to reflect current strategy parameters and add new strategies as approved by Eric."

**Prompt:**  
"Revise `Feature_Roadmap.md` with current priorities, ensuring v3 multi-strategy/multi-market architecture remains a top priority."

**Prompt:**  
"Update `Known_Issues_and_Design_Constraints.md` with latest technical debt, brittle areas, and v3 remediation plans."

**Prompt:**  
"Update `Partner_Onboarding_Guide.md` to reflect latest onboarding procedures, ensuring AI trade execution prohibition is clearly stated at the top."

---

## 3. Enforcement
- All AI agents must operate under these prompts or receive explicit written approval from Eric.
- AI agents may **never** deploy code changes directly to production.
- All generated content must be reviewed by a human owner before merging to `main`.

---

## 4. Review Schedule
- This document must be reviewed **quarterly** by Eric and BMAD leads.
- Update ownership if team structure changes.
