# Daily briefing

When the user runs **/daily-briefing**, do this:

1. Open **`.cursor/commands/daily-briefing.md`** and read it.
2. Execute **steps 1 through 8** in order. Run every command; do not skip or summarize.
3. After step 8, output the **briefing** using the **exact section template** at the end of that file (from "## At a glance" through "## VERIFY STATUS"). Fill each section from the results of the matching step. Every section must appear.
4. If a step fails (script error, SSH failure, fetch failure), write the failure in the relevant section and continue to the next step.

No optional steps. No "see also" in the middle of the workflow. The command file is the single source of truth.
