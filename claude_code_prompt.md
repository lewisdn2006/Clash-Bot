# Claude Code Prompt — Session Tracking Fix

No changes to any Python files are needed for this update.

The fix is entirely in the Cloudflare Worker. The worker now looks up the
currently-open session in D1 on every incoming update and routes all database
writes to that session, regardless of what session_id the bot sends. This means
even if a ghost session is created server-side while the bot keeps running with
an old session_id, all battles, loot, and log entries continue accumulating in
the correct session.

No changes are required to bot_reporter.py, AutomationWorker.py, Autoclash.py,
or any other Python file. The Python side is correct as-is.
