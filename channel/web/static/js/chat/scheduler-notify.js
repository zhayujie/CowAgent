/* Cross-session notifications for scheduled runs.
   Split out of console.js. These are classic scripts sharing one global
   scope; see channel/web/README.md before changing the load order. */

// ---- Cross-session scheduler notifications -------------------------------
//
// startPolling() above only watches the *currently open* session, so a
// scheduled task firing into any other session (the common case for reminders)
// would never surface. This second loop polls the global runs ledger instead:
// "any scheduled execution since I last checked?" It runs independent of which
// session is active and fires a forced notification (see
// forceScheduledNotification) for web/desktop scheduled deliveries the user
// isn't currently watching. The message body itself is already persisted to the
// session history, so clicking the notification just jumps there and loads it.
let schedulerNotifySince = Math.floor(Date.now() / 1000);  // ignore pre-load history
let schedulerNotifyStarted = false;

function startSchedulerNotifyPolling() {
    if (schedulerNotifyStarted) return;  // one loop process-wide
    schedulerNotifyStarted = true;

    function tick() {
        // Explicit empty agent_id=: a scheduled task can belong to ANY Agent, so
        // this must query the whole-team ledger. The global fetch() override
        // (see above) auto-injects the *active* Agent's id into every '/' URL
        // that lacks agent_id=, which would wrongly scope this poll to whatever
        // Agent the user has selected and hide other Agents' runs. Pre-supplying
        // agent_id= (empty -> whole team on the backend) opts out of that.
        fetch(`/api/scheduler/runs?since=${schedulerNotifySince}&limit=20&agent_id=`)
            .then(r => r.json())
            .then(data => {
                if (data && data.status === 'success' && Array.isArray(data.runs)) {
                    // Oldest first so notifications arrive in execution order and
                    // schedulerNotifySince advances monotonically.
                    const runs = data.runs.slice().sort(
                        (a, b) => (a.started_at || 0) - (b.started_at || 0)
                    );
                    for (const run of runs) {
                        if (run.started_at && run.started_at > schedulerNotifySince) {
                            schedulerNotifySince = run.started_at;
                        }
                        maybeNotifyScheduledRun(run);
                    }
                }
            })
            .catch(() => { /* transient; keep polling */ })
            .finally(() => setTimeout(tick, 10000));
    }
    tick();
}

// Kick off the scheduler-notification poll once the whole script has evaluated.
// Calling it from the top-level startup block earlier in the file would read
// this loop's ``let`` state (schedulerNotifyStarted, declared just above) before
// its declaration ran — a temporal-dead-zone crash that also aborted every
// top-level statement after it, cascading into unrelated "before initialization"
// errors (_sessCfg, sessionPanelOpen, ...). Deferring to window load runs it
// after all declarations are initialized.
if (typeof window !== 'undefined') {
    window.addEventListener('load', () => requestAuthGatedStart(startSchedulerNotifyPolling));
}

// Scheduler deliveries stream over a request id shaped ``scheduler_<taskid>_<hex>``
// (see integration._generate_request_id). Used to keep the SSE done handler from
// double-notifying alongside the global runs poller.
function isSchedulerRequest(requestId) {
    return typeof requestId === 'string' && requestId.startsWith('scheduler_');
}

function maybeNotifyScheduledRun(run) {
    // Only client-delivered tasks: WeChat/Feishu etc. already push into the IM
    // app, so re-notifying in the console would be noise.
    const channel = run.channel_type || '';
    if (channel && channel !== 'web') return;
    // Skip failed runs — nothing was delivered to the session to jump to.
    if (run.status && run.status !== 'done') return;
    const sid = run.session_id;
    if (!sid) return;
    markSessionUnread(sid, run.agent_id || '');

    // Manual "run now": route the notification back to the tab the user clicked
    // in. Only the originating tab has _manualRunOrigin[task_id] set, so other
    // tabs stay silent (they'd otherwise steal focus to a random tab that also
    // has this session open). If NO tab owns it (e.g. triggered from desktop or
    // a reloaded tab), fall through and let cross-tab dedup pick a single tab.
    if (run.trigger === 'manual' && run.task_id) {
        const anyTabOwns = _someTabOwnsManualRun(run.task_id);
        const iOwn = !!_manualRunOrigin[run.task_id];
        if (anyTabOwns && !iOwn) return;   // another tab owns it
    }

    // Dedupe by run id across ALL open tabs (claimScheduledRunNotify persists to
    // localStorage + broadcasts), so multiple tabs don't each pop the same run.
    if (!claimScheduledRunNotify(run.run_id)) return;
    // Always force a notification, even for the currently-open session and for
    // manual "run now": a scheduled execution should announce itself wherever
    // the user is. The /poll loop deliberately skips notifying for scheduler
    // pushes, so this is the single source (no double-fire).

    const label = t('notify_task_done');
    const snippet = firstLineSnippet(run.output_preview || '');
    const title = run.task_name || sessionTitleOf(sid) || label;
    const body = snippet ? `${label}: ${snippet}` : label;
    forceScheduledNotification(title, body, sid, run.agent_id || '');
}

