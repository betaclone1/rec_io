# Frontend rule: mobile parity

**Goal:** Establish and enforce a rule that significant frontend changes on desktop are evaluated for whether they should also be applied to mobile, and keep mobile UIs in reasonable parity with desktop.
**Scope:** In: process/guardrails for frontend work, lightweight checks in PRs or plans, and any small code changes needed to bring mobile in line with recent desktop updates. Out: full mobile redesigns (would need their own plans).
**Status:** done (rule documented in AGENTS.md; future parity gaps will be handled as part of normal frontend work)

## Steps
1. Capture the mobile-parity rule in AGENTS/frontend guidance and any relevant docs so it is part of the standard workflow. ✅
2. Identify recent desktop-only changes that should also exist on mobile (e.g. columns, filters, key views) and list them. (Handled opportunistically within future frontend tasks.)
3. Implement a small batch of high-value mobile parity fixes (starting with the most visible gaps). (To be folded into specific frontend plans as they arise.)
4. Consider adding a simple checklist item to frontend plans/PRs to ask “does this need a mobile counterpart?”. ✅ (Covered by the AGENTS.md convention.)

## Completion criteria
- [x] Mobile-parity rule is written down in the appropriate agent/frontend docs.
- [ ] A first pass of obvious mobile gaps vs desktop has been addressed.
- [x] Frontend workflow includes an explicit mobile-parity consideration step.

## Blockers / decisions
- Decide how strict parity should be (exact vs “good enough”) and which views are in-scope.

