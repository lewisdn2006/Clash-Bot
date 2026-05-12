// Autoclash Monitor — Cloudflare Worker (D1 edition)
// Bindings required:
//   D1 database → name: DB (bind your autoclash-db D1 database here)
// KV binding (BOT_STATUS) can be removed once migrated.
//
// Routes:
//   GET  /                → Live monitor page
//   GET  /history         → Session history page
//   GET  /stats           → All-time stats page
//   GET  /api/status      → Live status JSON
//   GET  /api/history     → Session history JSON
//   GET  /api/stats       → All-time stats JSON
//   POST /update          → Bot posts updates here

const BOT_SECRET = 'clash-monitor-lewis123';

// SHA-256 hash of your admin password.
// To generate your hash, open your browser console and run:
//   crypto.subtle.digest('SHA-256',new TextEncoder().encode('yourpassword'))
//     .then(b=>[...new Uint8Array(b)].map(x=>x.toString(16).padStart(2,'0')).join('')).then(console.log)
// Replace the string below with the 64-character hex output.
const ADMIN_PASSWORD_HASH = '763f4a4703360f4e8011a55e19438926e1f551ce1085f94226be895da9106338';

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, X-Bot-Secret, X-Auth-Token',
};

const json = (data, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json', ...CORS },
  });

const html = (body) =>
  new Response(body, { headers: { 'Content-Type': 'text/html', ...CORS } });

// ─────────────────────────────────────────────────────────────────────────────
// Main handler
// ─────────────────────────────────────────────────────────────────────────────
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    if (request.method === 'OPTIONS') return new Response(null, { headers: CORS });

    // ── Bot update endpoint ──────────────────────────────────────────────────
    if (request.method === 'POST' && path === '/update') {
      if (request.headers.get('X-Bot-Secret') !== BOT_SECRET)
        return new Response('Unauthorized', { status: 401 });
      try {
        return await handleUpdate(request, env);
      } catch (e) {
        return new Response('Bad request: ' + e.message, { status: 400, headers: CORS });
      }
    }

    // ── Control panel: authenticate ─────────────────────────────────────────
    if (request.method === 'POST' && path === '/api/auth') {
      return await handleAuth(request, env);
    }

    // ── Control panel: issue command (pause/resume/stop/hard_reset) ──────────
    if (request.method === 'POST' && path === '/api/command') {
      return await handleCommand(request, env);
    }

    // ── Bot polls for pending commands ────────────────────────────────────────
    if (request.method === 'POST' && path === '/api/poll-command') {
      if (request.headers.get('X-Bot-Secret') !== BOT_SECRET)
        return new Response('Unauthorized', { status: 401 });
      return await handlePollCommand(request, env);
    }

    // ── API endpoints ────────────────────────────────────────────────────────
    if (request.method === 'GET') {
      if (path === '/api/status')      return await apiStatus(env);
      if (path === '/api/history')     return await apiHistory(env);
      if (path === '/api/stats')       return await apiStats(env);
      if (path === '/api/verbose-log') return await apiVerboseLog(request, env);
      if (path === '/api/screenshot')  return await apiScreenshot(request, env);
      if (path === '/api/command-log') return await apiCommandLog(request, env);

      // ── Pages ──────────────────────────────────────────────────────────────
      if (path === '/' || path === '/monitor') return html(PAGE_MONITOR);
      if (path === '/history')                 return html(PAGE_HISTORY);
      if (path === '/stats')                   return html(PAGE_STATS);
    }

    return new Response('Not found', { status: 404 });
  }
};

// ─────────────────────────────────────────────────────────────────────────────
// POST /update handler
// ─────────────────────────────────────────────────────────────────────────────
async function handleUpdate(request, env) {
  const body = await request.json();
  const db = env.DB;
  const now = Math.floor(Date.now() / 1000);
  const sid = body.session_id || 'unknown';

  // ── Session reset ──────────────────────────────────────────────────────────
  if (body.reset_session) {
    // Close any previously open session
    await db.prepare(`UPDATE sessions SET ended_at=? WHERE ended_at IS NULL`)
      .bind(now).run();
    // Open new session
    await db.prepare(`
      INSERT OR IGNORE INTO sessions (session_id, started_at)
      VALUES (?, ?)
    `).bind(sid, now).run();
    // Reset live status
    const resetMode = body.mode || 'home';
    await db.prepare(`
      UPDATE bot_status SET
        phase='Starting', message='Session started',
        current_account=NULL, session_id=?, session_start=datetime(?, 'unixepoch'),
        last_update=datetime(?, 'unixepoch'), version=?, mode=?
      WHERE id=1
    `).bind(sid, now, now, body.version || '1.0', resetMode).run();
    await db.prepare(`UPDATE sessions SET mode=? WHERE session_id=?`)
      .bind(resetMode, sid).run();
    return new Response('OK', { status: 200, headers: CORS });
  }

  // ── Route all writes to the currently-open session ─────────────────────────
  // If the bot's session_id doesn't match the open session (e.g. a session was
  // silently created server-side while Python kept running), all DB writes are
  // redirected to the open session so history stays accurate. This means if the
  // bot runs continuously without restarting, all data always goes to one session
  // regardless of any transient session_id mismatch.
  const openRow = await db.prepare(
    `SELECT session_id FROM sessions WHERE ended_at IS NULL ORDER BY started_at DESC LIMIT 1`
  ).first();
  let activeSid = sid;
  if (openRow) {
    activeSid = openRow.session_id;
  } else {
    // No open session exists — auto-create one so no data is ever lost
    await db.prepare(
      `INSERT OR IGNORE INTO sessions (session_id, started_at) VALUES (?, ?)`
    ).bind(sid, now).run();
    activeSid = sid;
  }

  // ── Update live status ─────────────────────────────────────────────────────
  await db.prepare(`
    UPDATE bot_status SET
      phase=COALESCE(?, phase),
      message=COALESCE(?, message),
      current_account=COALESCE(?, current_account),
      session_id=COALESCE(?, session_id),
      last_update=datetime(?, 'unixepoch'),
      version=COALESCE(?, version),
      mode=COALESCE(?, mode)
    WHERE id=1
  `).bind(
    body.phase || null,
    body.message || null,
    body.current_account || null,
    activeSid,
    now,
    body.version || null,
    body.mode || null
  ).run();

  // ── Upsert per-account stats within this session ───────────────────────────
  if (body.current_account) {
    await db.prepare(`
      INSERT INTO session_accounts (session_id, account, attacks, gold, elixir, dark, upgrades, last_seen)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(session_id, account) DO UPDATE SET
        attacks=excluded.attacks,
        gold=excluded.gold,
        elixir=excluded.elixir,
        dark=excluded.dark,
        upgrades=excluded.upgrades,
        last_seen=excluded.last_seen
    `).bind(
      activeSid,
      body.current_account,
      body.account_attacks ?? 0,
      body.account_gold ?? 0,
      body.account_elixir ?? 0,
      body.account_dark ?? 0,
      body.account_upgrades ?? 0,
      now
    ).run();
  }

  // ── Store individual battle ────────────────────────────────────────────────
  if (body.battle) {
    const b = body.battle;
    await db.prepare(`
      INSERT INTO battles (session_id, account, gold, elixir, dark_elixir, walls, stars, timestamp)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(
      activeSid,
      b.account || body.current_account || 'unknown',
      b.gold || 0, b.elixir || 0, b.dark_elixir || 0,
      b.walls || 0, b.stars || 0, now
    ).run();

    // Update session totals
    await db.prepare(`
      UPDATE sessions SET
        total_gold = total_gold + ?,
        total_elixir = total_elixir + ?,
        total_dark = total_dark + ?,
        total_battles = total_battles + 1,
        total_walls = total_walls + ?
      WHERE session_id = ?
    `).bind(b.gold||0, b.elixir||0, b.dark_elixir||0, b.walls||0, activeSid).run();
  }

  // ── Store capital raid battle ────────────────────────────────────────────────
  if (body.capital_battle) {
    const cb = body.capital_battle;
    await db.prepare(`
      INSERT INTO capital_battles (session_id, account, clan_name, districts, timestamp)
      VALUES (?, ?, ?, ?, ?)
    `).bind(activeSid, cb.account || 'unknown', cb.clan_name || '', cb.districts || 0, now).run();
    await db.prepare(`
      UPDATE sessions SET total_districts = total_districts + ? WHERE session_id = ?
    `).bind(cb.districts || 0, activeSid).run();
    if (body.mode) {
      await db.prepare(`UPDATE sessions SET mode=? WHERE session_id=?`).bind('capital', activeSid).run();
    }
  }

  // ── Store Builder Base battle ──────────────────────────────────────────────
  if (body.bb_battle) {
    const bb = body.bb_battle;
    await db.prepare(`
      INSERT INTO bb_battles (session_id, account, stars, timestamp)
      VALUES (?, ?, ?, ?)
    `).bind(activeSid, bb.account || 'unknown', bb.stars || 0, now).run();
    await db.prepare(`
      UPDATE sessions SET
        total_bb_battles = total_bb_battles + 1,
        total_bb_stars = total_bb_stars + ?
      WHERE session_id = ?
    `).bind(bb.stars || 0, activeSid).run();
    if (body.mode) {
      await db.prepare(`UPDATE sessions SET mode=? WHERE session_id=?`).bind('bb', activeSid).run();
    }
  }

  // ── Append log entry ───────────────────────────────────────────────────────
  if (body.log_message) {
    await db.prepare(`
      INSERT INTO log_entries (session_id, message, timestamp) VALUES (?, ?, ?)
    `).bind(activeSid, body.log_message, now).run();
    // Trim to last 200
    await db.prepare(`
      DELETE FROM log_entries WHERE id NOT IN (
        SELECT id FROM log_entries ORDER BY id DESC LIMIT 200
      )
    `).run();
  }

  // ── Store screenshot (on-demand only, keeps last 3) ─────────────────────────
  if (body.screenshot_data) {
    await db.prepare(`
      INSERT INTO screenshots (session_id, image_data, timestamp)
      VALUES (?, ?, ?)
    `).bind(activeSid, body.screenshot_data, now).run().catch(() => {});
    await db.prepare(`
      DELETE FROM screenshots WHERE id NOT IN (
        SELECT id FROM screenshots ORDER BY id DESC LIMIT 3
      )
    `).run().catch(() => {});
  }

  // ── Append verbose log batch ───────────────────────────────────────────────
  if (body.verbose_log_batch && Array.isArray(body.verbose_log_batch) && body.verbose_log_batch.length > 0) {
    const stmt = db.prepare(
      `INSERT INTO verbose_log_entries (session_id, message, timestamp) VALUES (?, ?, ?)`
    );
    const inserts = body.verbose_log_batch.map(msg => stmt.bind(activeSid, msg, now));
    await db.batch(inserts);
    // Trim to last 5000 rows
    await db.prepare(`
      DELETE FROM verbose_log_entries WHERE id NOT IN (
        SELECT id FROM verbose_log_entries ORDER BY id DESC LIMIT 5000
      )
    `).run();
  }

  return new Response('OK', { status: 200, headers: CORS });
}


// ─────────────────────────────────────────────────────────────────────────────
// POST /api/auth  — verify password, return session token
// ─────────────────────────────────────────────────────────────────────────────
async function handleAuth(request, env) {
  const db = env.DB;
  let body;
  try { body = await request.json(); } catch { return json({ error: 'Invalid JSON' }, 400); }

  const password = body.password || '';
  if (!password) return json({ error: 'Password required' }, 400);

  // Hash the submitted password using Web Crypto (available in Workers)
  const encoded = new TextEncoder().encode(password);
  const hashBuf = await crypto.subtle.digest('SHA-256', encoded);
  const hashHex = [...new Uint8Array(hashBuf)]
    .map(b => b.toString(16).padStart(2, '0')).join('');

  if (hashHex !== ADMIN_PASSWORD_HASH) {
    // Small delay to slow down brute force attempts
    await new Promise(r => setTimeout(r, 500));
    return json({ error: 'Invalid password' }, 401);
  }

  // Generate a random 32-byte token
  const tokenBytes = crypto.getRandomValues(new Uint8Array(32));
  const token = [...tokenBytes].map(b => b.toString(16).padStart(2, '0')).join('');

  const now = Math.floor(Date.now() / 1000);
  const expires = now + 7200; // 2 hours

  // Store token in D1
  await db.prepare(
    `INSERT INTO auth_sessions (token, created_at, expires_at) VALUES (?, ?, ?)`
  ).bind(token, now, expires).run();

  // Clean up expired sessions while we're here
  await db.prepare(`DELETE FROM auth_sessions WHERE expires_at < ?`).bind(now).run();

  return json({ token, expires_at: expires });
}

// ─────────────────────────────────────────────────────────────────────────────
// POST /api/command  — issue a command to the bot (requires auth token)
// ─────────────────────────────────────────────────────────────────────────────
async function handleCommand(request, env) {
  const db = env.DB;
  const token = request.headers.get('X-Auth-Token') || '';

  if (!token) return json({ error: 'Auth token required' }, 401);

  // Validate token
  const now = Math.floor(Date.now() / 1000);
  const session = await db.prepare(
    `SELECT * FROM auth_sessions WHERE token=? AND expires_at > ?`
  ).bind(token, now).first();

  if (!session) return json({ error: 'Invalid or expired token' }, 401);

  let body;
  try { body = await request.json(); } catch { return json({ error: 'Invalid JSON' }, 400); }

  const VALID_COMMANDS = ['hard_reset', 'pause', 'resume', 'stop', 'screenshot'];
  const command = body.command || '';
  if (!VALID_COMMANDS.includes(command)) {
    return json({ error: `Unknown command. Valid: ${VALID_COMMANDS.join(', ')}` }, 400);
  }

  // Cancel any existing pending commands first (only one at a time)
  await db.prepare(
    `UPDATE commands SET status='cancelled' WHERE status='pending'`
  ).run();

  // Insert new command
  await db.prepare(
    `INSERT INTO commands (command, issued_at, status) VALUES (?, ?, 'pending')`
  ).bind(command, now).run();

  return json({ ok: true, command, issued_at: now });
}

// ─────────────────────────────────────────────────────────────────────────────
// POST /api/poll-command  — bot calls this every 10s to check for commands
// ─────────────────────────────────────────────────────────────────────────────
async function handlePollCommand(request, env) {
  const db = env.DB;
  const now = Math.floor(Date.now() / 1000);

  // Find the oldest pending command
  const cmd = await db.prepare(
    `SELECT * FROM commands WHERE status='pending' ORDER BY issued_at ASC LIMIT 1`
  ).first();

  if (!cmd) return json({ command: null });

  // Acknowledge it immediately so it doesn't fire twice
  await db.prepare(
    `UPDATE commands SET status='acknowledged', ack_at=? WHERE id=?`
  ).bind(now, cmd.id).run();

  // Debug log so we can confirm the bot actually polled and received the command
  await db.prepare(
    `INSERT OR IGNORE INTO command_log (command_id, command, issued_at, ack_at) VALUES (?, ?, ?, ?)`
  ).bind(cmd.id, cmd.command, cmd.issued_at, now).run().catch(() => {});

  return json({ command: cmd.command, id: cmd.id, issued_at: cmd.issued_at });
}

// ─────────────────────────────────────────────────────────────────────────────
// GET /api/status
// ─────────────────────────────────────────────────────────────────────────────
async function apiStatus(env) {
  const db = env.DB;

  const status = await db.prepare(`SELECT * FROM bot_status WHERE id=1`).first();
  if (!status) return json({ phase: 'OFFLINE', message: 'No data yet', accounts: {}, log: [] });

  // Per-account data for current session
  const accs = await db.prepare(`
    SELECT * FROM session_accounts WHERE session_id=? ORDER BY last_seen DESC
  `).bind(status.session_id || 'unknown').all();

  // Last 50 log entries
  const logs = await db.prepare(`
    SELECT message, timestamp
    FROM log_entries WHERE session_id=?
    ORDER BY id DESC LIMIT 50
  `).bind(status.session_id || 'unknown').all();

  // Session totals
  const sess = await db.prepare(`
    SELECT * FROM sessions WHERE session_id=?
  `).bind(status.session_id || 'unknown').first();

  // Build accounts object
  const accounts = {};
  const currentAcc = status.current_account;
  for (const a of (accs.results || [])) {
    accounts[a.account] = {
      active: a.account === currentAcc,
      attacks: a.attacks,
      gold: a.gold,
      elixir: a.elixir,
      dark: a.dark,
      upgrades: a.upgrades,
      last_seen: a.last_seen,
    };
  }

  const totals = sess ? {
    gold: sess.total_gold,
    elixir: sess.total_elixir,
    dark: sess.total_dark,
    battles: sess.total_battles,
    upgrades: Object.values(accounts).reduce((s,a) => s+(a.upgrades||0), 0),
  } : { gold:0, elixir:0, dark:0, battles:0, upgrades:0 };

  const capitalTotals = sess ? { districts: sess.total_districts || 0 } : { districts: 0 };
  const bbTotals = sess ? { battles: sess.total_bb_battles || 0, stars: sess.total_bb_stars || 0 } : { battles: 0, stars: 0 };

  return json({
    phase: status.phase,
    message: status.message,
    current_account: status.current_account,
    session_start: status.session_start,
    last_update: status.last_update,
    version: status.version,
    mode: status.mode || 'home',
    accounts,
    totals,
    capital_totals: capitalTotals,
    bb_totals: bbTotals,
    log: (logs.results || []).map(l => ({ timestamp: l.timestamp, msg: l.message })),
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// GET /api/history
// ─────────────────────────────────────────────────────────────────────────────
async function apiHistory(env) {
  const db = env.DB;

  // Last 30 sessions
  const sessions = await db.prepare(`
    SELECT * FROM sessions ORDER BY started_at DESC LIMIT 30
  `).all();

  // For each session, get per-account breakdown
  const result = [];
  for (const s of (sessions.results || [])) {
    const accs = await db.prepare(`
      SELECT account, attacks, gold, elixir, dark, upgrades
      FROM session_accounts WHERE session_id=?
      ORDER BY attacks DESC
    `).bind(s.session_id).all();

    result.push({
      session_id: s.session_id,
      started_at: s.started_at,
      ended_at: s.ended_at,
      duration_seconds: s.ended_at ? (s.ended_at - s.started_at) : (Math.floor(Date.now()/1000) - s.started_at),
      still_running: !s.ended_at,
      mode: s.mode || 'home',
      total_gold: s.total_gold,
      total_elixir: s.total_elixir,
      total_dark: s.total_dark,
      total_battles: s.total_battles,
      total_walls: s.total_walls,
      total_districts: s.total_districts || 0,
      total_bb_battles: s.total_bb_battles || 0,
      total_bb_stars: s.total_bb_stars || 0,
      accounts: accs.results || [],
    });
  }

  return json(result);
}

// ─────────────────────────────────────────────────────────────────────────────
// GET /api/stats  (all-time per-account totals, for the stats page)
// ─────────────────────────────────────────────────────────────────────────────
async function apiStats(env) {
  const db = env.DB;

  // All-time per-account totals aggregated from battles table
  const accounts = await db.prepare(`
    SELECT
      account,
      COUNT(*) as attacks,
      SUM(gold) as total_gold,
      SUM(elixir) as total_elixir,
      SUM(dark_elixir) as total_dark,
      SUM(walls) as total_walls,
      SUM(CASE WHEN stars=0 THEN 1 ELSE 0 END) as s0,
      SUM(CASE WHEN stars=1 THEN 1 ELSE 0 END) as s1,
      SUM(CASE WHEN stars=2 THEN 1 ELSE 0 END) as s2,
      SUM(CASE WHEN stars=3 THEN 1 ELSE 0 END) as s3,
      MIN(timestamp) as first_battle,
      MAX(timestamp) as last_battle
    FROM battles
    GROUP BY account
    ORDER BY total_gold DESC
  `).all();

  // Overall totals
  const totals = await db.prepare(`
    SELECT
      COUNT(*) as total_battles,
      SUM(gold) as total_gold,
      SUM(elixir) as total_elixir,
      SUM(dark_elixir) as total_dark,
      SUM(walls) as total_walls,
      COUNT(DISTINCT account) as unique_accounts,
      MIN(timestamp) as first_ever,
      MAX(timestamp) as last_ever
    FROM battles
  `).first();

  // Battle rate over time (last 7 days, grouped by hour)
  const oneDayAgo = Math.floor(Date.now()/1000) - 86400*7;
  const timeline = await db.prepare(`
    SELECT
      strftime('%Y-%m-%d %H:00', datetime(timestamp, 'unixepoch', '+1 hour')) as hour,
      COUNT(*) as battles,
      SUM(gold) as gold
    FROM battles
    WHERE timestamp > ?
    GROUP BY hour
    ORDER BY hour ASC
  `).bind(oneDayAgo).all();

  return json({
    accounts: accounts.results || [],
    totals: totals || {},
    timeline: timeline.results || [],
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// GET /api/verbose-log  — authenticated endpoint, returns verbose log lines
// Query params: since_id=<last_row_id> (optional, returns only newer rows)
// ─────────────────────────────────────────────────────────────────────────────
async function apiVerboseLog(request, env) {
  const db = env.DB;
  const url = new URL(request.url);

  // Require auth token
  const token = request.headers.get('X-Auth-Token') || url.searchParams.get('token') || '';
  if (!token) return json({ error: 'Auth token required' }, 401);
  const now = Math.floor(Date.now() / 1000);
  const session = await db.prepare(
    `SELECT * FROM auth_sessions WHERE token=? AND expires_at > ?`
  ).bind(token, now).first();
  if (!session) return json({ error: 'Invalid or expired token' }, 401);

  // Get current session_id from bot_status
  const status = await db.prepare(`SELECT session_id FROM bot_status WHERE id=1`).first();
  const sid = status?.session_id || 'unknown';

  // Fetch rows newer than since_id, or last 200 on initial load
  const sinceId = parseInt(url.searchParams.get('since_id') || '0', 10);
  const rows = sinceId > 0
    ? await db.prepare(
        `SELECT id, message, timestamp FROM verbose_log_entries WHERE session_id=? AND id > ? ORDER BY id ASC LIMIT 500`
      ).bind(sid, sinceId).all()
    : await db.prepare(
        `SELECT id, message, timestamp FROM verbose_log_entries WHERE session_id=? ORDER BY id DESC LIMIT 200`
      ).bind(sid).all();

  const entries = rows.results || [];
  // If initial load (DESC order), reverse to chronological
  if (sinceId === 0) entries.reverse();

  return json({
    entries: entries.map(r => ({ id: r.id, msg: r.message, timestamp: r.timestamp })),
    last_id: entries.length > 0 ? entries[entries.length - 1].id : sinceId,
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// GET /api/screenshot  — returns the most recent screenshot (authenticated)
// ─────────────────────────────────────────────────────────────────────────────
async function apiScreenshot(request, env) {
  const db = env.DB;
  const url = new URL(request.url);
  const token = request.headers.get('X-Auth-Token') || url.searchParams.get('token') || '';
  if (!token) return json({ error: 'Auth token required' }, 401);
  const now = Math.floor(Date.now() / 1000);
  const session = await db.prepare(
    `SELECT * FROM auth_sessions WHERE token=? AND expires_at > ?`
  ).bind(token, now).first();
  if (!session) return json({ error: 'Invalid or expired token' }, 401);

  const row = await db.prepare(
    `SELECT id, image_data, timestamp FROM screenshots ORDER BY id DESC LIMIT 1`
  ).first();

  if (!row) return json({ image_data: null, timestamp: null });
  return json({ image_data: row.image_data, timestamp: row.timestamp });
}

// ─────────────────────────────────────────────────────────────────────────────
// GET /api/command-log  — returns recent command history (authenticated)
// Useful for debugging: shows when commands were issued and when bot acknowledged them.
// ─────────────────────────────────────────────────────────────────────────────
async function apiCommandLog(request, env) {
  const db = env.DB;
  const url = new URL(request.url);
  const token = request.headers.get('X-Auth-Token') || url.searchParams.get('token') || '';
  if (!token) return json({ error: 'Auth token required' }, 401);
  const now = Math.floor(Date.now() / 1000);
  const session = await db.prepare(
    `SELECT * FROM auth_sessions WHERE token=? AND expires_at > ?`
  ).bind(token, now).first();
  if (!session) return json({ error: 'Invalid or expired token' }, 401);

  const rows = await db.prepare(
    `SELECT * FROM command_log ORDER BY id DESC LIMIT 50`
  ).all();

  return json(rows.results || []);
}

// ─────────────────────────────────────────────────────────────────────────────
// SHARED CSS + NAV (injected into each page)
// ─────────────────────────────────────────────────────────────────────────────
const SHARED_CSS = `
<style>
:root {
  --bg: #0a0a0a; --bg2: #111; --bg3: #181818; --bg4: #222;
  --border: #2a2a2a; --border2: #333;
  --text: #e8e8e8; --text2: #888; --text3: #555;
  --gold: #c9a84c; --gold2: #e8c96a;
  --elixir: #c44dff; --dark: #8877ff;
  --green: #2aff8a; --red: #ff3b3b; --orange: #ff8c2a;
}
*{margin:0;padding:0;box-sizing:border-box;}
body{background:var(--bg);color:var(--text);font-family:'JetBrains Mono',monospace;min-height:100vh;overflow-x:hidden;}
body::before{content:'';position:fixed;inset:0;background-image:linear-gradient(rgba(201,168,76,0.03) 1px,transparent 1px),linear-gradient(90deg,rgba(201,168,76,0.03) 1px,transparent 1px);background-size:40px 40px;pointer-events:none;z-index:0;}
.container{position:relative;z-index:1;max-width:1400px;margin:0 auto;padding:24px;}

/* Nav */
nav{display:flex;align-items:center;justify-content:space-between;margin-bottom:32px;padding-bottom:20px;border-bottom:1px solid var(--border);}
.nav-left{display:flex;align-items:center;gap:16px;}
.logo{width:40px;height:40px;border:1px solid var(--gold);display:flex;align-items:center;justify-content:center;font-family:'Rajdhani',sans-serif;font-weight:700;font-size:18px;color:var(--gold);position:relative;flex-shrink:0;}
.logo::before{content:'';position:absolute;inset:3px;border:1px solid rgba(201,168,76,0.3);}
.site-title{font-family:'Rajdhani',sans-serif;font-weight:600;font-size:22px;letter-spacing:3px;text-transform:uppercase;}
.site-title span{color:var(--gold);}
.nav-links{display:flex;gap:4px;}
.nav-link{padding:6px 16px;font-size:11px;letter-spacing:1.5px;text-transform:uppercase;color:var(--text2);text-decoration:none;border:1px solid transparent;font-family:'JetBrains Mono',monospace;transition:all 0.2s;cursor:pointer;}
.nav-link:hover{color:var(--text);border-color:var(--border2);}
.nav-link.active{color:var(--gold);border-color:var(--gold);background:rgba(201,168,76,0.08);}
.nav-right{display:flex;align-items:center;gap:16px;}
.status-pill{display:flex;align-items:center;gap:8px;padding:6px 14px;border:1px solid var(--border2);background:var(--bg2);font-size:11px;letter-spacing:1.5px;text-transform:uppercase;color:var(--text2);}
.dot{width:7px;height:7px;border-radius:50%;background:var(--text3);}
.dot.online{background:var(--green);box-shadow:0 0 8px var(--green);animation:pulse 2s infinite;}
.dot.offline{background:var(--red);}
@keyframes pulse{0%,100%{opacity:1;}50%{opacity:0.4;}}

/* Cards */
.card{background:var(--bg2);border:1px solid var(--border);padding:20px;position:relative;overflow:hidden;animation:fadeIn 0.4s ease both;}
.card::before{content:'';position:absolute;top:0;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,var(--gold),transparent);opacity:0.4;}
.card-label{font-size:10px;letter-spacing:2px;text-transform:uppercase;color:var(--text3);margin-bottom:10px;font-family:'Rajdhani',sans-serif;font-weight:500;}
.card-value{font-family:'Rajdhani',sans-serif;font-size:36px;font-weight:700;line-height:1;}
.card-sub{font-size:11px;color:var(--text3);margin-top:6px;}
.gold{color:var(--gold2);}
.elixir{color:var(--elixir);}
.dark-e{color:var(--dark);}
.green{color:var(--green);}
.orange{color:var(--orange);}
.red{color:var(--red);}

/* Section title */
.section-title{font-family:'Rajdhani',sans-serif;font-size:11px;letter-spacing:2.5px;text-transform:uppercase;color:var(--text3);margin-bottom:16px;}

/* Table */
.tbl{width:100%;border-collapse:collapse;font-size:12px;}
.tbl th{padding:8px 12px;background:var(--bg3);color:var(--text3);font-size:10px;letter-spacing:2px;text-transform:uppercase;text-align:right;font-weight:400;white-space:nowrap;border-bottom:1px solid var(--border2);}
.tbl th:first-child{text-align:left;}
.tbl td{padding:9px 12px;border-bottom:1px solid var(--border);text-align:right;color:var(--text2);}
.tbl td:first-child{color:var(--gold);text-align:left;font-family:'Rajdhani',sans-serif;font-weight:600;font-size:13px;}
.tbl tr:hover td{background:rgba(255,255,255,0.02);}
.active-row td{background:rgba(201,168,76,0.04)!important;}
.pulse-dot{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--green);box-shadow:0 0 6px var(--green);animation:pulse 2s infinite;margin-right:8px;}

/* Log */
.log-feed{max-height:280px;overflow-y:auto;scrollbar-width:thin;scrollbar-color:var(--border2) transparent;}
.log-entry{display:flex;gap:12px;padding:3px 0;border-bottom:1px solid rgba(255,255,255,0.02);}
.log-time{color:var(--text3);white-space:nowrap;flex-shrink:0;font-size:10px;}
.log-msg{color:var(--text2);font-size:12px;}
.log-msg.err{color:var(--red);}
.log-msg.phase{color:var(--gold);}
.log-msg.ok{color:var(--green);}

/* Grid helpers */
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px;}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-bottom:16px;}
.grid4{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:16px;margin-bottom:16px;}
.span2{grid-column:span 2;}
.span3{grid-column:span 3;}
.span4{grid-column:span 4;}

/* Info bar */
.info-bar{display:flex;justify-content:space-between;padding:10px 16px;background:var(--bg2);border:1px solid var(--border);font-size:10px;color:var(--text3);letter-spacing:1px;text-transform:uppercase;margin-top:16px;}

/* Empty state */
.empty{text-align:center;padding:40px;color:var(--text3);font-size:12px;letter-spacing:1px;}

/* Fade */
@keyframes fadeIn{from{opacity:0;transform:translateY(8px);}to{opacity:1;transform:translateY(0);}}

/* History session cards */
.session-card{background:var(--bg2);border:1px solid var(--border);padding:20px;margin-bottom:12px;animation:fadeIn 0.4s ease both;cursor:pointer;transition:border-color 0.2s;}
.session-card:hover{border-color:var(--border2);}
.session-card.running{border-color:rgba(42,255,138,0.3);}
.session-card.running::before{content:'';position:absolute;top:0;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,var(--green),transparent);opacity:0.6;}
.session-card{position:relative;overflow:hidden;}
.session-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;}
.session-badge{padding:3px 10px;font-size:10px;letter-spacing:1.5px;text-transform:uppercase;font-family:'Rajdhani',sans-serif;font-weight:600;}
.badge-running{color:var(--green);border:1px solid rgba(42,255,138,0.4);background:rgba(42,255,138,0.06);}
.badge-done{color:var(--text3);border:1px solid var(--border);}
.mode-tag{padding:2px 8px;font-size:9px;letter-spacing:1.5px;text-transform:uppercase;font-family:'Rajdhani',sans-serif;font-weight:700;border:1px solid var(--border2);color:var(--text3);}
.mode-tag.home{border-color:rgba(201,168,76,0.4);color:var(--gold);}
.mode-tag.capital{border-color:rgba(196,77,255,0.4);color:var(--elixir);}
.mode-tag.bb{border-color:rgba(136,119,255,0.4);color:var(--dark);}
.session-meta{display:flex;gap:24px;flex-wrap:wrap;}
.session-meta-item{display:flex;flex-direction:column;gap:2px;}
.session-meta-label{font-size:9px;letter-spacing:2px;text-transform:uppercase;color:var(--text3);}
.session-meta-value{font-family:'Rajdhani',sans-serif;font-size:18px;font-weight:700;color:var(--text);}
.session-accounts{display:flex;gap:6px;flex-wrap:wrap;margin-top:12px;}
.acc-chip{padding:2px 8px;font-size:10px;border:1px solid var(--border2);color:var(--text3);}

/* Charts wrapper */
.chart-wrap{position:relative;height:260px;margin-top:8px;}

/* Stats page */
.stat-hero{font-family:'Rajdhani',sans-serif;font-size:48px;font-weight:800;line-height:1;}

@media(max-width:900px){.grid3,.grid4{grid-template-columns:1fr 1fr;}.span3,.span4{grid-column:span 2;}.grid2{grid-template-columns:1fr;}}
@media(max-width:600px){.grid2,.grid3,.grid4{grid-template-columns:1fr;}.span2,.span3,.span4{grid-column:span 1;}.site-title{font-size:16px;}.container{padding:12px;}.nav-links{display:none;}}
</style>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&family=Rajdhani:wght@400;600;700;800&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
`;

const NAV = (active) => `
<nav>
  <div class="nav-left">
    <div class="logo">AC</div>
    <span class="site-title">Auto<span>clash</span></span>
  </div>
  <div class="nav-links">
    <a class="nav-link${active==='monitor'?' active':''}" href="/">Monitor</a>
    <a class="nav-link${active==='history'?' active':''}" href="/history">History</a>
    <a class="nav-link${active==='stats'?' active':''}" href="/stats">Stats</a>
  </div>
  <div class="nav-right">
    <span id="last-update" style="font-size:11px;color:var(--text3);">Connecting...</span>
    <div class="status-pill">
      <div class="dot" id="status-dot"></div>
      <span id="status-text">OFFLINE</span>
    </div>
  </div>
</nav>`;

// ─────────────────────────────────────────────────────────────────────────────
// PAGE 1: Monitor (live)
// ─────────────────────────────────────────────────────────────────────────────
const PAGE_MONITOR = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Autoclash — Monitor</title>
${SHARED_CSS}
<style>
.status-bar{display:flex;align-items:center;gap:20px;padding:16px 20px;background:var(--bg2);border:1px solid var(--border);margin-bottom:16px;flex-wrap:wrap;}
.phase-badge{padding:5px 14px;border:1px solid var(--gold);font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--gold);white-space:nowrap;font-family:'Rajdhani',sans-serif;font-weight:600;}
.phase-badge.paused{border-color:var(--orange);color:var(--orange);}
.phase-badge.error{border-color:var(--red);color:var(--red);}
.phase-msg{font-size:13px;color:var(--text2);flex:1;}
.acc-badge{padding:5px 14px;background:var(--bg3);border:1px solid var(--border2);font-size:12px;color:var(--text);letter-spacing:1px;font-family:'Rajdhani',sans-serif;white-space:nowrap;}
.loot-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-bottom:16px;}
.loot-card{background:var(--bg2);border:1px solid var(--border);padding:20px;position:relative;overflow:hidden;}
.loot-card::after{content:attr(data-sym);position:absolute;right:16px;top:50%;transform:translateY(-50%);font-size:52px;opacity:0.05;font-family:'Rajdhani',sans-serif;font-weight:700;}
@media(max-width:700px){.loot-grid{grid-template-columns:1fr;}.status-bar{flex-direction:column;align-items:flex-start;}}

/* ── Control Panel ────────────────────────────────────────────── */
.control-panel{background:var(--bg2);border:1px solid var(--border);padding:20px;margin-bottom:16px;position:relative;overflow:hidden;}
.control-panel::before{content:'';position:absolute;top:0;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,var(--orange),transparent);opacity:0.5;}
.control-panel.locked .cp-buttons{display:none;}
.control-panel.locked .cp-auth{display:flex;}
.control-panel.unlocked .cp-auth{display:none;}
.control-panel.unlocked .cp-buttons{display:flex;}
.cp-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;}
.cp-title{font-family:'Rajdhani',sans-serif;font-size:11px;letter-spacing:2.5px;text-transform:uppercase;color:var(--text3);}
.cp-lock{display:flex;align-items:center;gap:8px;font-size:11px;color:var(--text3);letter-spacing:1px;}
.cp-lock-icon{font-size:14px;}
.cp-auth{display:none;align-items:center;gap:10px;flex-wrap:wrap;}
.cp-auth input{background:var(--bg3);border:1px solid var(--border2);color:var(--text);padding:8px 14px;font-family:'JetBrains Mono',monospace;font-size:12px;outline:none;width:200px;}
.cp-auth input:focus{border-color:var(--orange);}
.cp-auth-btn{padding:8px 20px;background:var(--orange);border:none;color:#000;font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase;cursor:pointer;transition:opacity 0.2s;}
.cp-auth-btn:hover{opacity:0.85;}
.cp-auth-err{color:var(--red);font-size:11px;letter-spacing:0.5px;}
.cp-buttons{display:none;gap:10px;flex-wrap:wrap;align-items:center;}
.cp-btn{padding:9px 20px;border:1px solid var(--border2);background:var(--bg3);color:var(--text2);font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:1px;text-transform:uppercase;cursor:pointer;transition:all 0.2s;}
.cp-btn:hover{border-color:var(--text2);color:var(--text);}
.cp-btn.danger{border-color:rgba(255,59,59,0.4);color:var(--red);}
.cp-btn.danger:hover{background:rgba(255,59,59,0.1);border-color:var(--red);}
.cp-btn.warn{border-color:rgba(255,140,42,0.4);color:var(--orange);}
.cp-btn.warn:hover{background:rgba(255,140,42,0.1);border-color:var(--orange);}
.cp-btn.success{border-color:rgba(42,255,138,0.4);color:var(--green);}
.cp-btn.success:hover{background:rgba(42,255,138,0.1);border-color:var(--green);}
.cp-btn:disabled{opacity:0.35;cursor:not-allowed;}
.cp-status{font-size:11px;color:var(--text3);letter-spacing:0.5px;margin-top:10px;min-height:16px;}
.cp-logout{background:none;border:none;color:var(--text3);font-size:10px;font-family:'JetBrains Mono',monospace;cursor:pointer;letter-spacing:1px;text-transform:uppercase;padding:0;}
.cp-logout:hover{color:var(--text2);}
.mode-badge{padding:4px 12px;font-size:10px;letter-spacing:2px;text-transform:uppercase;font-family:'Rajdhani',sans-serif;font-weight:700;border:1px solid var(--gold);color:var(--gold);}
.mode-badge.capital{border-color:var(--elixir);color:var(--elixir);}
.mode-badge.bb{border-color:var(--dark);color:var(--dark);}
.screenshot-panel{background:var(--bg2);border:1px solid var(--border);padding:20px;margin-top:16px;position:relative;overflow:hidden;}
.screenshot-panel::before{content:'';position:absolute;top:0;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,var(--green),transparent);opacity:0.4;}
.screenshot-img{width:100%;border:1px solid var(--border2);display:block;margin-top:12px;}
.cmdlog-panel{background:var(--bg2);border:1px solid var(--border);padding:20px;margin-top:16px;position:relative;overflow:hidden;}
.cmdlog-panel::before{content:'';position:absolute;top:0;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,var(--orange),transparent);opacity:0.4;}
.cmdlog-entry{display:flex;gap:12px;padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.02);font-size:11px;}
.cmdlog-command{color:var(--orange);font-weight:700;min-width:100px;flex-shrink:0;}
.cmdlog-meta{color:var(--text3);}

/* ── Verbose Log Panel ────────────────────────────────────────── */
.verbose-panel{background:var(--bg2);border:1px solid var(--border);padding:20px;margin-top:16px;position:relative;overflow:hidden;}
.verbose-panel::before{content:'';position:absolute;top:0;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,var(--elixir),transparent);opacity:0.4;}
.verbose-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;}
.verbose-count{font-size:10px;color:var(--text3);letter-spacing:1px;}
.verbose-feed{max-height:500px;overflow-y:auto;scrollbar-width:thin;scrollbar-color:var(--border2) transparent;}
.verbose-entry{display:flex;gap:10px;padding:2px 0;border-bottom:1px solid rgba(255,255,255,0.02);}
.verbose-time{color:var(--text3);white-space:nowrap;flex-shrink:0;font-size:10px;font-family:'JetBrains Mono',monospace;}
.verbose-msg{color:var(--text2);font-size:11px;font-family:'JetBrains Mono',monospace;}
.verbose-msg.err{color:var(--red);}
.verbose-msg.warn{color:var(--orange);}
.verbose-msg.ok{color:var(--green);}
</style>
</head>
<body>
<div class="container">
${NAV('monitor')}

<!-- Status bar -->
<div class="status-bar">
  <div class="phase-badge" id="phase-badge">—</div>
  <div class="mode-badge" id="mode-badge">—</div>
  <div class="phase-msg" id="phase-msg">Waiting for bot data...</div>
  <div class="acc-badge" id="acc-badge">No account</div>
</div>

<!-- Loot -->
<div class="loot-grid">
  <div class="loot-card" data-sym="G">
    <div class="card-label">Gold — Session Total</div>
    <div class="card-value gold" id="gold">—</div>
    <div class="card-sub" id="gold-sub">awaiting data</div>
  </div>
  <div class="loot-card" data-sym="E">
    <div class="card-label">Elixir — Session Total</div>
    <div class="card-value elixir" id="elixir">—</div>
    <div class="card-sub" id="elixir-sub">awaiting data</div>
  </div>
  <div class="loot-card" data-sym="D">
    <div class="card-label">Dark Elixir — Session Total</div>
    <div class="card-value dark-e" id="dark">—</div>
    <div class="card-sub" id="dark-sub">awaiting data</div>
  </div>
</div>

<!-- Stats row -->
<div class="grid4" style="margin-bottom:16px;">
  <div class="card">
    <div class="card-label">Battles</div>
    <div class="card-value green" id="battles">—</div>
    <div class="card-sub">this session</div>
  </div>
  <div class="card">
    <div class="card-label">Upgrades</div>
    <div class="card-value orange" id="upgrades">—</div>
    <div class="card-sub">walls + buildings</div>
  </div>
  <div class="card">
    <div class="card-label">Session Duration</div>
    <div class="card-value" id="duration">—</div>
    <div class="card-sub" id="duration-sub">since bot started</div>
  </div>
  <div class="card">
    <div class="card-label">Accounts Active</div>
    <div class="card-value" id="acc-count">—</div>
    <div class="card-sub">this session</div>
  </div>
</div>

<!-- Account table -->
<div class="card span4" style="margin-bottom:16px;">
  <div class="section-title">Per-Account Breakdown</div>
  <div id="acc-table"><div class="empty">No account data yet</div></div>
</div>

<!-- Control Panel -->
<div class="control-panel locked" id="control-panel">
  <div class="cp-header">
    <span class="cp-title">Control Panel</span>
    <div class="cp-lock">
      <span class="cp-lock-icon" id="cp-lock-icon">🔒</span>
      <span id="cp-lock-label">Locked — authenticate to unlock</span>
      <button class="cp-logout" id="cp-logout-btn" style="display:none" onclick="cpLogout()">Log out</button>
    </div>
  </div>

  <!-- Auth form (shown when locked) -->
  <div class="cp-auth" id="cp-auth">
    <input type="password" id="cp-password" placeholder="Enter password…" onkeydown="if(event.key==='Enter')cpAuthenticate()">
    <button class="cp-auth-btn" onclick="cpAuthenticate()">Unlock</button>
    <span class="cp-auth-err" id="cp-auth-err"></span>
  </div>

  <!-- Buttons (shown when unlocked) -->
  <div class="cp-buttons" id="cp-buttons">
    <button class="cp-btn success" onclick="cpCommand('resume')">▶ Resume</button>
    <button class="cp-btn warn" onclick="cpCommand('pause')">⏸ Pause</button>
    <button class="cp-btn warn" onclick="cpCommand('stop')">⏹ Stop Bot</button>
    <button class="cp-btn danger" onclick="cpCommand('hard_reset')">⚡ Hard Reset</button>
    <button class="cp-btn" onclick="cpRequestScreenshot()" id="screenshot-btn">📷 Screenshot</button>
    <button class="cp-btn" onclick="toggleCmdLog()" id="cmdlog-toggle-btn">📋 Cmd Log</button>
  </div>
  <div class="cp-status" id="cp-status"></div>
</div>

<!-- Log -->
<div class="card">
  <div class="section-title">Recent Log</div>
  <div class="log-feed" id="log-feed"><div class="empty">Waiting for log messages...</div></div>
</div>

<!-- Capital / BB extra stats (shown only in those modes) -->
<div class="grid2" id="capital-stats-row" style="display:none;margin-bottom:16px;">
  <div class="card">
    <div class="card-label">Districts Destroyed</div>
    <div class="card-value elixir" id="capital-districts">—</div>
    <div class="card-sub">this session</div>
  </div>
  <div class="card">
    <div class="card-label">Accounts Raided</div>
    <div class="card-value" id="capital-accounts">—</div>
    <div class="card-sub">this session</div>
  </div>
</div>
<div class="grid2" id="bb-stats-row" style="display:none;margin-bottom:16px;">
  <div class="card">
    <div class="card-label">BB Battles</div>
    <div class="card-value dark-e" id="bb-battles-count">—</div>
    <div class="card-sub">this session</div>
  </div>
  <div class="card">
    <div class="card-label">BB Stars</div>
    <div class="card-value" id="bb-stars">—</div>
    <div class="card-sub">this session</div>
  </div>
</div>

<!-- Screenshot panel (visible when authenticated) -->
<div class="screenshot-panel" id="screenshot-panel" style="display:none;">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
    <div class="section-title" style="margin-bottom:0;">Live Screenshot</div>
    <span style="font-size:10px;color:var(--text3);letter-spacing:1px;" id="screenshot-age">Never requested</span>
  </div>
  <div id="screenshot-placeholder" style="text-align:center;padding:32px;color:var(--text3);font-size:11px;border:1px dashed var(--border2);">
    Click &ldquo;Screenshot&rdquo; to capture the current game screen.
    The bot will send it within ~10 seconds.
  </div>
  <img id="screenshot-img" class="screenshot-img" style="display:none;" alt="Game screenshot" />
</div>

<!-- Command log debug panel (visible when authenticated) -->
<div class="cmdlog-panel" id="cmdlog-panel" style="display:none;">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
    <div class="section-title" style="margin-bottom:0;">Command Log</div>
    <span style="font-size:10px;color:var(--text3);letter-spacing:1px;">Last 50 commands</span>
  </div>
  <div id="cmdlog-feed"><div class="empty">No commands sent yet</div></div>
</div>

<!-- Verbose Log (visible when authenticated) -->
<div class="verbose-panel" id="verbose-panel" style="display:none;">
  <div class="verbose-header">
    <div class="section-title" style="margin-bottom:0;">Verbose Log</div>
    <span class="verbose-count" id="verbose-count">0 lines</span>
  </div>
  <div class="verbose-feed" id="verbose-feed"><div class="empty">Waiting for verbose log data...</div></div>
</div>

<div class="info-bar">
  <span>autoclash-monitor.lewisdn2006.workers.dev</span>
  <span id="refresh-label">Auto-refreshes every 10s</span>
  <span id="version">—</span>
</div>
</div>

<script>
const REFRESH = 10000;
function fmt(n){if(n==null||n==='—')return '—';if(n>=1e6)return(n/1e6).toFixed(2)+'M';if(n>=1e3)return(n/1e3).toFixed(1)+'K';return n.toLocaleString();}
function ago(iso){if(!iso)return'unknown';const d=Math.floor((Date.now()-new Date(iso).getTime())/1000);if(d<60)return d+'s ago';if(d<3600)return Math.floor(d/60)+'m ago';return Math.floor(d/3600)+'h '+Math.floor((d%3600)/60)+'m ago';}
function dur(iso){if(!iso)return'—';const d=Math.floor((Date.now()-new Date(iso).getTime())/1000);const h=Math.floor(d/3600),m=Math.floor((d%3600)/60),s=d%60;if(h>0)return h+'h '+m+'m';if(m>0)return m+'m '+s+'s';return s+'s';}
function durSecs(secs){const h=Math.floor(secs/3600),m=Math.floor((secs%3600)/60);if(h>0)return h+'h '+m+'m';return m+'m';}

function setOnline(ok){
  document.getElementById('status-dot').className='dot '+(ok?'online':'offline');
  document.getElementById('status-text').textContent=ok?'LIVE':'OFFLINE';
}

function renderAccTable(accounts, current){
  if(!accounts||!Object.keys(accounts).length){
    document.getElementById('acc-table').innerHTML='<div class="empty">No account data yet</div>';return;
  }
  const rows=Object.entries(accounts).map(([name,d])=>{
    const active=d.active||name===current;
    return \`<tr class="\${active?'active-row':''}">
      <td>\${active?'<span class="pulse-dot"></span>':''}\${name}</td>
      <td>\${d.attacks??0}</td>
      <td class="gold">\${fmt(d.gold??0)}</td>
      <td class="elixir">\${fmt(d.elixir??0)}</td>
      <td class="dark-e">\${fmt(d.dark??0)}</td>
      <td class="orange">\${d.upgrades??0}</td>
      <td>\${d.last_seen?ago(new Date(d.last_seen*1000).toISOString()):'—'}</td>
    </tr>\`;
  }).join('');
  document.getElementById('acc-table').innerHTML=\`
    <table class="tbl"><thead><tr>
      <th>Account</th><th>Attacks</th><th>Gold</th><th>Elixir</th><th>Dark</th><th>Upgrades</th><th>Last Seen</th>
    </tr></thead><tbody>\${rows}</tbody></table>\`;
}

function renderLog(entries){
  const feed=document.getElementById('log-feed');
  if(!entries||!entries.length){feed.innerHTML='<div class="empty">No log messages yet</div>';return;}
  feed.innerHTML=entries.slice().reverse().map(e=>{
    let cls='log-msg';
    const m=e.msg||'';
    if(/error|fail|fatal/i.test(m))cls+=' err';
    else if(/phase|===|starting|paused/i.test(m))cls+=' phase';
    else if(/complete|done|success/i.test(m))cls+=' ok';
    return \`<div class="log-entry"><span class="log-time">\${e.timestamp ? new Date(e.timestamp * 1000).toLocaleTimeString('en-GB') : ''}</span><span class="\${cls}">\${m}</span></div>\`;
  }).join('');
}

async function refresh(){
  try{
    const res=await fetch('/api/status');
    if(!res.ok)throw new Error('HTTP '+res.status);
    const d=await res.json();
    setOnline(true);
    const toUtcIso = s => s ? s.replace(' ','T')+'Z' : null;
    document.getElementById('last-update').textContent='Updated '+ago(toUtcIso(d.last_update));

    // Phase badge
    const pb=document.getElementById('phase-badge');
    pb.textContent=d.phase||'—';
    pb.className='phase-badge'+(d.phase==='PAUSED'?' paused':d.phase==='ERROR'?' error':'');
    document.getElementById('phase-msg').textContent=d.message||'—';
    document.getElementById('acc-badge').textContent=d.current_account||'No account';

    // Mode badge
    const mode=d.mode||'home';
    const modeLabels={home:'Home Village',capital:'Clan Capital',bb:'Builder Base'};
    const mb=document.getElementById('mode-badge');
    mb.textContent=modeLabels[mode]||mode.toUpperCase();
    mb.className='mode-badge'+(mode==='capital'?' capital':mode==='bb'?' bb':'');

    // Capital / BB extra stats
    document.getElementById('capital-stats-row').style.display=mode==='capital'?'':'none';
    document.getElementById('bb-stats-row').style.display=mode==='bb'?'':'none';
    if(mode==='capital'&&d.capital_totals){
      document.getElementById('capital-districts').textContent=d.capital_totals.districts??'—';
      document.getElementById('capital-accounts').textContent=Object.keys(d.accounts||{}).length||'—';
    }
    if(mode==='bb'&&d.bb_totals){
      document.getElementById('bb-battles-count').textContent=d.bb_totals.battles??'—';
      document.getElementById('bb-stars').textContent=d.bb_totals.stars??'—';
    }

    // Loot
    document.getElementById('gold').textContent=fmt(d.totals?.gold);
    document.getElementById('elixir').textContent=fmt(d.totals?.elixir);
    document.getElementById('dark').textContent=fmt(d.totals?.dark);

    // Stats
    document.getElementById('battles').textContent=d.totals?.battles??'—';
    document.getElementById('upgrades').textContent=d.totals?.upgrades??'—';
    document.getElementById('duration').textContent=dur(toUtcIso(d.session_start));
    document.getElementById('acc-count').textContent=d.accounts?Object.keys(d.accounts).length:'—';

    // Gold/hr sub-label
    if(d.session_start&&d.totals?.gold){
      const hrs=Math.max((Date.now()-new Date(toUtcIso(d.session_start)).getTime())/3600000,0.01);
      document.getElementById('gold-sub').textContent=fmt(Math.round(d.totals.gold/hrs))+'/hr';
      document.getElementById('elixir-sub').textContent=fmt(Math.round(d.totals.elixir/hrs))+'/hr';
      document.getElementById('dark-sub').textContent=fmt(Math.round(d.totals.dark/hrs))+'/hr';
    }

    renderAccTable(d.accounts, d.current_account);
    renderLog(d.log);
    document.getElementById('version').textContent='Bot v'+(d.version||'—');
  }catch(e){
    setOnline(false);
    document.getElementById('last-update').textContent='Failed to connect';
    document.getElementById('phase-msg').textContent='Cannot reach bot — '+e.message;
  }
}

refresh();
setInterval(refresh,REFRESH);

// ── Control Panel Auth ────────────────────────────────────────────────────────
let _cpToken = sessionStorage.getItem('cp_token') || null;
let _cpExpires = parseInt(sessionStorage.getItem('cp_expires') || '0');

function cpIsAuthenticated() {
  return _cpToken && Math.floor(Date.now()/1000) < _cpExpires;
}

function cpSetUnlocked(token, expires) {
  _cpToken = token;
  _cpExpires = expires;
  sessionStorage.setItem('cp_token', token);
  sessionStorage.setItem('cp_expires', String(expires));
  const panel = document.getElementById('control-panel');
  panel.classList.remove('locked');
  panel.classList.add('unlocked');
  document.getElementById('cp-lock-icon').textContent = '🔓';
  document.getElementById('cp-lock-label').textContent = 'Unlocked';
  document.getElementById('cp-logout-btn').style.display = '';
  document.getElementById('cp-status').textContent = '';
  // Show verbose log panel and kick off first poll
  showVerbosePanel(true);
  pollVerboseLog();
  // Show screenshot panel
  document.getElementById('screenshot-panel').style.display = '';
  // Show cmdlog panel if it was open
  if (_cmdLogVisible) document.getElementById('cmdlog-panel').style.display = '';
}

function cpSetLocked() {
  _cpToken = null;
  _cpExpires = 0;
  sessionStorage.removeItem('cp_token');
  sessionStorage.removeItem('cp_expires');
  const panel = document.getElementById('control-panel');
  panel.classList.add('locked');
  panel.classList.remove('unlocked');
  document.getElementById('cp-lock-icon').textContent = '🔒';
  document.getElementById('cp-lock-label').textContent = 'Locked — authenticate to unlock';
  document.getElementById('cp-logout-btn').style.display = 'none';
  document.getElementById('cp-password').value = '';
  // Hide verbose log panel and clear buffer
  showVerbosePanel(false);
  _verboseLines = [];
  _verboseLastId = 0;
  // Hide screenshot and cmdlog panels
  document.getElementById('screenshot-panel').style.display = 'none';
  document.getElementById('cmdlog-panel').style.display = 'none';
  _cmdLogVisible = false;
}

function cpLogout() {
  cpSetLocked();
}

async function cpAuthenticate() {
  const pwd = document.getElementById('cp-password').value;
  const errEl = document.getElementById('cp-auth-err');
  const btn = document.querySelector('.cp-auth-btn');
  if (!pwd) { errEl.textContent = 'Please enter a password'; return; }
  errEl.textContent = '';
  btn.textContent = 'Checking…';
  btn.disabled = true;
  try {
    const res = await fetch('/api/auth', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: pwd }),
    });
    const data = await res.json();
    if (!res.ok) {
      errEl.textContent = data.error || 'Authentication failed';
      document.getElementById('cp-password').value = '';
    } else {
      cpSetUnlocked(data.token, data.expires_at);
    }
  } catch(e) {
    errEl.textContent = 'Network error — try again';
  } finally {
    btn.textContent = 'Unlock';
    btn.disabled = false;
  }
}

async function cpCommand(cmd) {
  if (!cpIsAuthenticated()) { cpSetLocked(); return; }
  const statusEl = document.getElementById('cp-status');
  const labels = { hard_reset:'Hard Reset', pause:'Pause', resume:'Resume', stop:'Stop', screenshot:'Screenshot' };
  const confirmMessages = {
    hard_reset: 'Are you sure you want to hard reset the bot? This will close and relaunch the game.',
    stop: 'Are you sure you want to stop the bot?',
  };
  if (confirmMessages[cmd] && !confirm(confirmMessages[cmd])) return;
  statusEl.textContent = 'Sending ' + (labels[cmd]||cmd) + ' command…';
  document.querySelectorAll('.cp-btn').forEach(b => b.disabled = true);
  try {
    const res = await fetch('/api/command', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Auth-Token': _cpToken },
      body: JSON.stringify({ command: cmd }),
    });
    const data = await res.json();
    if (res.status === 401) {
      cpSetLocked();
      statusEl.textContent = 'Session expired — please re-authenticate';
      return;
    }
    if (!res.ok) {
      statusEl.textContent = 'Error: ' + (data.error || res.status);
      return;
    }
    if (cmd === 'screenshot') {
      statusEl.textContent = '✓ Screenshot requested — image will appear below within ~15 seconds';
      setTimeout(() => pollScreenshot(), 12000);
    } else {
      statusEl.textContent = '✓ ' + (labels[cmd]||cmd) + ' command sent — bot will act within 10 seconds';
    }
    setTimeout(() => { statusEl.textContent = ''; }, 10000);
    if (_cmdLogVisible) loadCmdLog();
  } catch(e) {
    statusEl.textContent = 'Network error — command not sent';
  } finally {
    document.querySelectorAll('.cp-btn').forEach(b => b.disabled = false);
  }
}

function cpRequestScreenshot() {
  cpCommand('screenshot');
}

// ── Screenshot polling ─────────────────────────────────────────────────────────
let _screenshotLastTs = 0;

async function pollScreenshot() {
  if (!_cpToken || !cpIsAuthenticated()) return;
  try {
    const res = await fetch(\`/api/screenshot?token=\${_cpToken}\`);
    if (!res.ok) return;
    const data = await res.json();
    if (data.image_data && data.timestamp !== _screenshotLastTs) {
      _screenshotLastTs = data.timestamp;
      const img = document.getElementById('screenshot-img');
      const placeholder = document.getElementById('screenshot-placeholder');
      img.src = 'data:image/jpeg;base64,' + data.image_data;
      img.style.display = '';
      placeholder.style.display = 'none';
      const age = Math.floor((Date.now()/1000) - data.timestamp);
      document.getElementById('screenshot-age').textContent = 'Taken ' + (age < 5 ? 'just now' : age + 's ago');
    }
  } catch(e) { console.error('[Screenshot] poll error:', e); }
}

// ── Command log debug panel ────────────────────────────────────────────────────
let _cmdLogVisible = false;

function toggleCmdLog() {
  _cmdLogVisible = !_cmdLogVisible;
  document.getElementById('cmdlog-panel').style.display = _cmdLogVisible ? '' : 'none';
  document.getElementById('cmdlog-toggle-btn').style.color = _cmdLogVisible ? 'var(--green)' : '';
  if (_cmdLogVisible) loadCmdLog();
}

async function loadCmdLog() {
  if (!_cpToken || !cpIsAuthenticated()) return;
  try {
    const res = await fetch(\`/api/command-log?token=\${_cpToken}\`);
    if (!res.ok) return;
    const rows = await res.json();
    const feed = document.getElementById('cmdlog-feed');
    if (!rows.length) { feed.innerHTML = '<div class="empty">No commands sent yet</div>'; return; }
    feed.innerHTML = rows.map(r => {
      const issuedAt = r.issued_at ? new Date(r.issued_at*1000).toLocaleTimeString('en-GB') : '—';
      const ackAt = r.ack_at ? new Date(r.ack_at*1000).toLocaleTimeString('en-GB') : 'Not acknowledged';
      const lag = (r.ack_at && r.issued_at) ? ((r.ack_at - r.issued_at) + 's lag') : '';
      return \`<div class="cmdlog-entry">
        <span class="cmdlog-command">\${r.command||'?'}</span>
        <span class="cmdlog-meta">Issued \${issuedAt} → Bot acked \${ackAt} \${lag}</span>
      </div>\`;
    }).join('');
  } catch(e) { console.error('[CmdLog] error:', e); }
}

// Restore auth state if token is still valid from this browser session
if (cpIsAuthenticated()) {
  cpSetUnlocked(_cpToken, _cpExpires);
}

// ── Verbose Log ───────────────────────────────────────────────────────────────
let _verboseLines = [];
let _verboseLastId = 0;
const MAX_VERBOSE_LINES = 1000;

function showVerbosePanel(show) {
  document.getElementById('verbose-panel').style.display = show ? '' : 'none';
}

function renderVerboseFeed() {
  const feed = document.getElementById('verbose-feed');
  if (!_verboseLines.length) {
    feed.innerHTML = '<div class="empty">No verbose log data yet — starts populating within 10 seconds</div>';
    return;
  }
  feed.innerHTML = _verboseLines.map(e => {
    let cls = 'verbose-msg';
    if (/error|fail|fatal/i.test(e.msg)) cls += ' err';
    else if (/warning|warn/i.test(e.msg)) cls += ' warn';
    else if (/complete|done|success|accepted|found/i.test(e.msg)) cls += ' ok';
    const timeStr = e.msg.substring(0, 10);
    const msgStr = e.msg.substring(10);
    return \`<div class="verbose-entry"><span class="verbose-time">\${timeStr}</span><span class="\${cls}">\${msgStr}</span></div>\`;
  }).join('');
  document.getElementById('verbose-count').textContent = _verboseLines.length + ' lines';
  feed.scrollTop = feed.scrollHeight;
}

async function pollVerboseLog() {
  if (!_cpToken || !cpIsAuthenticated()) return;
  try {
    const url = \`/api/verbose-log?since_id=\${_verboseLastId}&token=\${_cpToken}\`;
    const res = await fetch(url);
    if (res.status === 401) { cpSetLocked(); return; }
    if (!res.ok) return;
    const data = await res.json();
    if (data.entries && data.entries.length > 0) {
      _verboseLines.push(...data.entries);
      if (_verboseLines.length > MAX_VERBOSE_LINES) {
        _verboseLines = _verboseLines.slice(-MAX_VERBOSE_LINES);
      }
      _verboseLastId = data.last_id;
      renderVerboseFeed();
    }
  } catch(e) { /* silently ignore network errors */ }
}

setInterval(pollVerboseLog, REFRESH);
</script>
</body>
</html>`;

// ─────────────────────────────────────────────────────────────────────────────
// PAGE 2: History
// ─────────────────────────────────────────────────────────────────────────────
const PAGE_HISTORY = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Autoclash — History</title>
${SHARED_CSS}
</head>
<body>
<div class="container">
${NAV('history')}

<!-- Summary cards -->
<div class="grid4" style="margin-bottom:24px;">
  <div class="card">
    <div class="card-label">Total Sessions</div>
    <div class="card-value green" id="h-sessions">—</div>
    <div class="card-sub">all time</div>
  </div>
  <div class="card">
    <div class="card-label">Total Runtime</div>
    <div class="card-value" id="h-runtime">—</div>
    <div class="card-sub">across all sessions</div>
  </div>
  <div class="card">
    <div class="card-label">Avg Session Length</div>
    <div class="card-value" id="h-avg">—</div>
    <div class="card-sub">per session</div>
  </div>
  <div class="card">
    <div class="card-label">Bot Uptime</div>
    <div class="card-value gold" id="h-uptime">—</div>
    <div class="card-sub">% of tracked time</div>
  </div>
</div>

<!-- Activity chart -->
<div class="card" style="margin-bottom:16px;">
  <div class="section-title">Session Activity — Last 30 Sessions</div>
  <div class="chart-wrap"><canvas id="actChart"></canvas></div>
</div>

<!-- Session list -->
<div class="card">
  <div class="section-title">Session Log</div>
  <div id="sessions-list"><div class="empty">Loading...</div></div>
</div>

<div class="info-bar">
  <span>autoclash-monitor.lewisdn2006.workers.dev/history</span>
  <span>Last 30 sessions shown</span>
  <span id="h-loaded">—</span>
</div>
</div>

<script>
function fmt(n){if(n==null)return'—';if(n>=1e6)return(n/1e6).toFixed(2)+'M';if(n>=1e3)return(n/1e3).toFixed(1)+'K';return n.toLocaleString();}
function durSecs(s){if(!s)return'—';const h=Math.floor(s/3600),m=Math.floor((s%3600)/60);if(h>0)return h+'h '+m+'m';return m+'m';}
function fmtDate(ts){if(!ts)return'—';const d=new Date(ts*1000);return d.toLocaleDateString('en-GB',{day:'2-digit',month:'short'})+' '+d.toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit'});}

let actChart=null;

async function load(){
  const res=await fetch('/api/history');
  const sessions=await res.json();

  if(!sessions.length){
    document.getElementById('sessions-list').innerHTML='<div class="empty">No sessions recorded yet</div>';
    return;
  }

  // Summary stats
  const completed=sessions.filter(s=>!s.still_running);
  const totalSecs=sessions.reduce((a,s)=>a+s.duration_seconds,0);
  const avgSecs=completed.length?Math.floor(totalSecs/completed.length):0;

  // Uptime % — ratio of runtime to span from first to last session
  const first=sessions[sessions.length-1]?.started_at;
  const last=sessions[0]?.ended_at||Math.floor(Date.now()/1000);
  const span=last-first;
  const uptime=span>0?Math.round((totalSecs/span)*100):0;

  document.getElementById('h-sessions').textContent=sessions.length;
  document.getElementById('h-runtime').textContent=durSecs(totalSecs);
  document.getElementById('h-avg').textContent=durSecs(avgSecs);
  document.getElementById('h-uptime').textContent=uptime+'%';
  document.getElementById('h-loaded').textContent='Loaded '+sessions.length+' sessions';

  // Activity chart — battles per session
  const labels=sessions.map((_,i)=>'S'+(sessions.length-i)).reverse();
  const battles=sessions.map(s=>s.total_battles).reverse();
  const durations=sessions.map(s=>Math.round(s.duration_seconds/60)).reverse();

  if(actChart)actChart.destroy();
  actChart=new Chart(document.getElementById('actChart'),{
    type:'bar',
    data:{
      labels,
      datasets:[
        {label:'Battles',data:battles,backgroundColor:'rgba(42,255,138,0.5)',borderColor:'rgba(42,255,138,0.8)',borderWidth:1,yAxisID:'y'},
        {label:'Duration (min)',data:durations,type:'line',borderColor:'rgba(201,168,76,0.8)',backgroundColor:'rgba(201,168,76,0.1)',tension:0.3,yAxisID:'y2',pointRadius:3},
      ]
    },
    options:{
      responsive:true,maintainAspectRatio:false,
      plugins:{legend:{labels:{color:'#888',font:{family:'JetBrains Mono',size:11}}}},
      scales:{
        x:{ticks:{color:'#555',font:{size:10}},grid:{color:'#1a1a1a'}},
        y:{ticks:{color:'#888'},grid:{color:'#1a1a1a'},title:{display:true,text:'Battles',color:'#555',font:{size:10}}},
        y2:{position:'right',ticks:{color:'#888'},grid:{display:false},title:{display:true,text:'Duration (min)',color:'#555',font:{size:10}}},
      }
    }
  });

  // Session cards
  const html=sessions.map(s=>\`
    <div class="session-card \${s.still_running?'running':''}">
      <div class="session-header">
        <span style="font-family:'Rajdhani',sans-serif;font-size:14px;font-weight:700;letter-spacing:1px;color:var(--text2);">
          \${fmtDate(s.started_at)}
          \${s.ended_at?' → '+fmtDate(s.ended_at):''}
        </span>
        <div style="display:flex;gap:8px;align-items:center;">
          <span class="mode-tag \${s.mode||'home'}">\${s.mode==='capital'?'CAP':s.mode==='bb'?'BB':'HV'}</span>
          <span class="session-badge \${s.still_running?'badge-running':'badge-done'}">\${s.still_running?'● RUNNING':'DONE'}</span>
        </div>
      </div>
      <div class="session-meta">
        <div class="session-meta-item">
          <span class="session-meta-label">Duration</span>
          <span class="session-meta-value">\${durSecs(s.duration_seconds)}</span>
        </div>
        \${s.mode==='capital' ? \`
          <div class="session-meta-item"><span class="session-meta-label">Districts</span><span class="session-meta-value elixir">\${s.total_districts||0}</span></div>
        \` : s.mode==='bb' ? \`
          <div class="session-meta-item"><span class="session-meta-label">BB Battles</span><span class="session-meta-value dark-e">\${s.total_bb_battles||0}</span></div>
          <div class="session-meta-item"><span class="session-meta-label">Stars</span><span class="session-meta-value">\${s.total_bb_stars||0}</span></div>
        \` : \`
          <div class="session-meta-item"><span class="session-meta-label">Battles</span><span class="session-meta-value green">\${s.total_battles}</span></div>
          <div class="session-meta-item"><span class="session-meta-label">Gold</span><span class="session-meta-value gold">\${fmt(s.total_gold)}</span></div>
          <div class="session-meta-item"><span class="session-meta-label">Elixir</span><span class="session-meta-value elixir">\${fmt(s.total_elixir)}</span></div>
          <div class="session-meta-item"><span class="session-meta-label">Dark</span><span class="session-meta-value dark-e">\${fmt(s.total_dark)}</span></div>
          <div class="session-meta-item"><span class="session-meta-label">Walls</span><span class="session-meta-value orange">\${s.total_walls}</span></div>
        \`}
      </div>
      \${s.accounts.length?\`<div class="session-accounts">\${s.accounts.map(a=>\`<span class="acc-chip">\${a.account} (\${a.attacks}atk)</span>\`).join('')}</div>\`:''}
    </div>
  \`).join('');

  document.getElementById('sessions-list').innerHTML=html;
}

load();
</script>
</body>
</html>`;

// ─────────────────────────────────────────────────────────────────────────────
// PAGE 3: Stats (all-time, mirrors the GUI stats page)
// ─────────────────────────────────────────────────────────────────────────────
const PAGE_STATS = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Autoclash — Stats</title>
${SHARED_CSS}
<style>
.tabs{display:flex;gap:4px;margin-bottom:20px;flex-wrap:wrap;}
.tab{padding:6px 16px;font-size:11px;letter-spacing:1.5px;text-transform:uppercase;color:var(--text2);border:1px solid transparent;cursor:pointer;font-family:'JetBrains Mono',monospace;background:none;transition:all 0.2s;}
.tab:hover{color:var(--text);border-color:var(--border2);}
.tab.active{color:var(--gold);border-color:var(--gold);background:rgba(201,168,76,0.08);}
.panel{background:var(--bg2);border:1px solid var(--border);padding:24px;}
</style>
</head>
<body>
<div class="container">
${NAV('stats')}

<!-- Hero totals -->
<div class="grid4" style="margin-bottom:24px;" id="hero-cards">
  <div class="card"><div class="card-label">Total Battles</div><div class="stat-hero green" id="st-battles">—</div></div>
  <div class="card"><div class="card-label">Total Gold</div><div class="stat-hero gold" id="st-gold">—</div></div>
  <div class="card"><div class="card-label">Total Elixir</div><div class="stat-hero elixir" id="st-elixir">—</div></div>
  <div class="card"><div class="card-label">Total Dark</div><div class="stat-hero dark-e" id="st-dark">—</div></div>
</div>

<!-- Chart tabs -->
<div class="tabs">
  <button class="tab active" onclick="showTab('table',this)">Account Table</button>
  <button class="tab" onclick="showTab('loot',this)">Loot Chart</button>
  <button class="tab" onclick="showTab('stars',this)">Star Rates</button>
  <button class="tab" onclick="showTab('timeline',this)">Timeline</button>
</div>
<div class="panel" id="panel">
  <div class="empty">Loading...</div>
</div>

<div class="info-bar">
  <span>autoclash-monitor.lewisdn2006.workers.dev/stats</span>
  <span id="st-range">—</span>
  <span id="st-accounts">—</span>
</div>
</div>

<script>
let _data=null;
let _charts=[];

function fmt(n){if(n==null)return'—';if(n>=1e6)return(n/1e6).toFixed(2)+'M';if(n>=1e3)return(n/1e3).toFixed(1)+'K';return n.toLocaleString();}
function fmtDate(ts){if(!ts)return'—';return new Date(ts*1000).toLocaleDateString('en-GB',{day:'2-digit',month:'short',year:'2-digit'});}

const COLORS=['#c9a84c','#c44dff','#2aff8a','#ff8c2a','#8877ff','#ff3b3b','#4dc9f6','#e8c96a','#a8ff3e','#ff6b9d'];
function col(i){return COLORS[i%COLORS.length];}

function destroyCharts(){_charts.forEach(c=>c.destroy());_charts=[];}

function showTab(name,btn){
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  btn.classList.add('active');
  if(!_data)return;
  destroyCharts();
  const panel=document.getElementById('panel');

  if(name==='table'){
    const rows=_data.accounts.map((a,i)=>\`<tr>
      <td>\${a.account}</td>
      <td>\${a.attacks}</td>
      <td class="gold">\${fmt(a.total_gold)}</td>
      <td class="elixir">\${fmt(a.total_elixir)}</td>
      <td class="dark-e">\${fmt(a.total_dark)}</td>
      <td class="orange">\${a.total_walls}</td>
      <td>\${a.attacks>0?((a.s3/a.attacks)*100).toFixed(1)+'%':'—'}</td>
      <td>\${fmtDate(a.first_battle)} → \${fmtDate(a.last_battle)}</td>
    </tr>\`).join('');
    panel.innerHTML=\`<table class="tbl"><thead><tr>
      <th>Account</th><th>Attacks</th><th>Gold</th><th>Elixir</th><th>Dark</th><th>Walls</th><th>3★ Rate</th><th>Active Dates</th>
    </tr></thead><tbody>\${rows}</tbody></table>\`;
    return;
  }

  if(name==='loot'){
    panel.innerHTML='<div class="chart-wrap"><canvas id="lootChart"></canvas></div>';
    const c=new Chart(document.getElementById('lootChart'),{
      type:'bar',
      data:{
        labels:_data.accounts.map(a=>a.account),
        datasets:[
          {label:'Gold',data:_data.accounts.map(a=>a.total_gold),backgroundColor:'rgba(201,168,76,0.7)',stack:'s'},
          {label:'Elixir',data:_data.accounts.map(a=>a.total_elixir),backgroundColor:'rgba(196,77,255,0.7)',stack:'s'},
          {label:'Dark',data:_data.accounts.map(a=>a.total_dark),backgroundColor:'rgba(136,119,255,0.7)',stack:'s'},
        ]
      },
      options:{
        responsive:true,maintainAspectRatio:false,
        plugins:{legend:{labels:{color:'#888',font:{family:'JetBrains Mono',size:11}}}},
        scales:{
          x:{stacked:true,ticks:{color:'#888',font:{size:10}},grid:{color:'#1a1a1a'}},
          y:{stacked:true,ticks:{color:'#888',callback:v=>fmt(v)},grid:{color:'#1a1a1a'}},
        }
      }
    });
    _charts.push(c);return;
  }

  if(name==='stars'){
    panel.innerHTML='<div class="chart-wrap"><canvas id="starChart"></canvas></div>';
    const starColors=['#ff3b3b','#ff8c2a','#4dc9f6','#2aff8a'];
    const datasets=[0,1,2,3].map((star,i)=>({
      label:star+'★',
      data:_data.accounts.map(a=>[a.s0,a.s1,a.s2,a.s3][star]),
      backgroundColor:starColors[i]+'aa',
      borderColor:starColors[i],
      borderWidth:1,stack:'s',
    }));
    const c=new Chart(document.getElementById('starChart'),{
      type:'bar',
      data:{labels:_data.accounts.map(a=>a.account),datasets},
      options:{
        responsive:true,maintainAspectRatio:false,indexAxis:'y',
        plugins:{legend:{labels:{color:'#888',font:{size:11}}}},
        scales:{
          x:{stacked:true,ticks:{color:'#888'},grid:{color:'#1a1a1a'}},
          y:{stacked:true,ticks:{color:'#c9a84c',font:{family:'Rajdhani',size:13,weight:'700'}},grid:{display:false}},
        }
      }
    });
    _charts.push(c);return;
  }

  if(name==='timeline'){
    if(!_data.timeline.length){panel.innerHTML='<div class="empty">No timeline data yet — battles must be recorded first</div>';return;}
    panel.innerHTML='<div class="chart-wrap" style="height:300px"><canvas id="tlChart"></canvas></div>';
    const c=new Chart(document.getElementById('tlChart'),{
      type:'bar',
      data:{
        labels:_data.timeline.map(t=>t.hour.slice(5,16)),
        datasets:[
          {label:'Battles/hr',data:_data.timeline.map(t=>t.battles),backgroundColor:'rgba(42,255,138,0.4)',borderColor:'rgba(42,255,138,0.8)',borderWidth:1},
        ]
      },
      options:{
        responsive:true,maintainAspectRatio:false,
        plugins:{legend:{labels:{color:'#888',font:{size:11}}}},
        scales:{
          x:{ticks:{color:'#555',maxRotation:45,font:{size:9}},grid:{color:'#1a1a1a'}},
          y:{ticks:{color:'#888'},grid:{color:'#1a1a1a'},title:{display:true,text:'Battles',color:'#555',font:{size:10}}},
        }
      }
    });
    _charts.push(c);return;
  }
}

async function load(){
  const res=await fetch('/api/stats');
  _data=await res.json();
  const t=_data.totals;
  document.getElementById('st-battles').textContent=fmt(t.total_battles);
  document.getElementById('st-gold').textContent=fmt(t.total_gold);
  document.getElementById('st-elixir').textContent=fmt(t.total_elixir);
  document.getElementById('st-dark').textContent=fmt(t.total_dark);
  document.getElementById('st-range').textContent=t.first_ever?fmtDate(t.first_ever)+' → '+fmtDate(t.last_ever):'No data';
  document.getElementById('st-accounts').textContent=(t.unique_accounts||0)+' accounts tracked';
  showTab('table',document.querySelector('.tab.active'));
}
load();
</script>
</body>
</html>`;
