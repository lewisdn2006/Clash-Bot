# Session Tracking Fix — Setup Guide

This update prevents the history page from ever showing a split session again.
If the Cloudflare worker silently creates a new session record while the Python
bot keeps running with its original session_id, all data will now be
automatically redirected to the open session instead of being written to the
wrong place.

Total time: about 2 minutes. No SQL changes. No Python changes.


PART 1 — No SQL changes needed
===============================

The schema_additions.sql file for this update contains only a harmless
SELECT 1 placeholder. Do not run it in the D1 console — there is nothing to
execute. The existing database schema is already correct for this fix.


PART 2 — Deploy the new worker.js
==================================

1. Open worker.js from this folder in Notepad or VS Code
2. Go to: https://dash.cloudflare.com
3. Click "Workers & Pages" in the left sidebar
4. Click on your worker: autoclash-monitor
5. Click "Edit Code" in the top right
6. Select all the existing code (Ctrl+A) and delete it
7. Copy all of worker.js (Ctrl+A then Ctrl+C in Notepad)
8. Click inside the Cloudflare editor and paste (Ctrl+V)
9. Click "Deploy" in the top right
10. Wait a few seconds for deployment to complete
11. Visit https://autoclash-monitor.lewisdn2006.workers.dev to confirm
    the monitor page loads correctly


PART 3 — No Python changes needed
===================================

bot_reporter.py and all other Python files are unchanged. The fix lives
entirely in the Cloudflare Worker.


PART 4 — What changed and how to verify it worked
===================================================

What changed in the worker:

  After the session-reset block in handleUpdate(), the worker now does one
  extra database lookup on every incoming POST from the bot:

    SELECT session_id FROM sessions WHERE ended_at IS NULL
    ORDER BY started_at DESC LIMIT 1

  It then uses that session_id (called activeSid internally) for all
  subsequent database writes — battles, account stats, loot totals, logs,
  capital battles, BB battles. The session_id the bot sends is still used
  to identify the bot, but data is always written to whatever session is
  currently open in D1.

  Edge case: if no open session exists at all (e.g. the bot starts sending
  data before it has sent a reset_session), the worker auto-creates a new
  session row so no data is ever lost.

How to verify it worked:

  The monitor page should load and show live data as normal — no visible
  change there. The fix only affects the history page.

  To confirm the fix is live, look at the history page after the bot has
  been running for a while. You should see a single RUNNING session with
  the correct battle count and loot totals accumulating in one place,
  rather than data splitting across two sessions.

  If a situation like the Session 29/30 split ever occurs again, the new
  session record will appear in history with 0 battles and immediately
  close (because the bot's data will be redirected to the older open
  session), making the ghost session obvious but harmless — a 0-battle
  blip rather than a confusing data split.
