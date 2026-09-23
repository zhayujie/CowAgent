/* Scheduled task create/edit modal.
   Split out of console.js. These are classic scripts sharing one global
   scope; see channel/web/README.md before changing the load order. */

// =====================================================================
// Task Edit Modal
// =====================================================================
let currentEditingTask = null;
// Modal mode: 'edit' reuses /api/scheduler/update on an existing task;
// 'create' collects a brand-new task and posts to /api/scheduler/create.
let taskModalMode = 'edit';
// Recipients available for a hand-created cross-channel task, keyed by
// "instance_id:receiver" so the picker can resolve the full identity on save.
let taskRecipientMap = {};

// Two-step create picker state. `taskInstances` are the deliverable channel
// instances (step 1); `taskAllRecipients` is the full trusted directory that we
// filter down to the chosen instance (step 2).
let taskInstances = [];
let taskAllRecipients = [];
let selectedTaskInstanceId = '';

// Convert an ISO timestamp into the datetime-local value for a task zone.
function formatTaskDateTimeLocal(value, timeZone) {
    if (!value) return '';
    if (!timeZone) {
        // Legacy tasks store a naive server-local wall clock. Preserve those
        // exact digits instead of applying the browser's timezone.
        const parts = String(value).match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/);
        if (!parts) return '';
        return `${parts[1]}-${parts[2]}-${parts[3]}T${parts[4]}:${parts[5]}:${parts[6]}`;
    }

    const instant = new Date(value);
    if (isNaN(instant.getTime())) return '';
    const parts = new Intl.DateTimeFormat('en-US', {
        timeZone,
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
        hourCycle: 'h23',
    }).formatToParts(instant).reduce((result, part) => {
        result[part.type] = part.value;
        return result;
    }, {});
    return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}`;
}

// Return the UTC offset (in milliseconds) at a concrete instant.
function taskZoneOffsetMs(instant, timeZone) {
    const parts = new Intl.DateTimeFormat('en-US', {
        timeZone,
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
        hourCycle: 'h23',
    }).formatToParts(instant).reduce((result, part) => {
        result[part.type] = part.value;
        return result;
    }, {});
    const asUTC = Date.UTC(
        Number(parts.year), Number(parts.month) - 1, Number(parts.day),
        Number(parts.hour), Number(parts.minute), Number(parts.second)
    );
    return asUTC - instant.getTime();
}

// Interpret a datetime-local wall clock in an IANA zone and return UTC ISO.
function taskLocalTimeToUTC(value, timeZone) {
    const wallAsUTC = Date.parse(`${value}Z`);
    if (isNaN(wallAsUTC)) return null;

    if (!timeZone) {
        // datetime-local is already browser-local; toISOString gives an
        // explicit instant for backend validation without changing the input.
        return new Date(value).toISOString();
    }

    let instant = wallAsUTC;
    for (let i = 0; i < 2; i += 1) {
        const offset = taskZoneOffsetMs(new Date(instant), timeZone);
        instant = wallAsUTC - offset;
    }
    return new Date(instant).toISOString();
}
// Middle-truncate a long recipient id so the dropdown row's right-hand id stays
// on one line (e.g. "o9cq807...MYB0@im.wechat").
function truncateRecipientId(id, max) {
    const s = String(id || '');
    const limit = max || 22;
    if (s.length <= limit) return s;
    const head = Math.ceil((limit - 1) / 2);
    const tail = Math.floor((limit - 1) / 2);
    return s.slice(0, head) + '…' + s.slice(s.length - tail);
}

// Mirror the currently selected recipient's receiver into the hidden task field.
function updateRecipientPreview() {
    const el = document.getElementById('task-edit-recipient');
    const receiverInput = document.getElementById('task-edit-receiver');
    if (!el) return;
    const key = getDropdownValue(el);
    const r = taskRecipientMap[key];
    if (receiverInput) receiverInput.value = r ? r.receiver : '';
}

// Step 1: load the channel instances the console can deliver through, then wire
// the instance dropdown. Selecting an instance reveals + drives the recipient list.
// When editing, `preselect` restores the task's current instance + receiver so
// the two-step picker opens already pointing at them (still switchable).
function loadTaskInstances(preselect) {
    const instEl = document.getElementById('task-edit-instance');
    if (!instEl) return;
    const preInstance = (preselect && preselect.instanceId) || '';
    const preReceiver = (preselect && preselect.receiver) || '';
    selectedTaskInstanceId = preInstance;
    taskInstances = [];
    // Fetch instances and the full recipient directory in parallel; both feed
    // the two-step picker. The directory is shared across Agents.
    Promise.all([
        fetch('/api/scheduler/instances').then(r => r.json()).catch(() => null),
        fetch('/api/scheduler/recipients').then(r => r.json()).catch(() => null),
    ]).then(([instData, recData]) => {
        taskInstances = (instData && instData.status === 'success') ? (instData.instances || []) : [];
        taskAllRecipients = (recData && recData.status === 'success') ? (recData.recipients || []) : [];

        const options = taskInstances.map(i => ({
            value: i.instance_id,
            label: i.name || i.instance_id,
            // Right side shows the channel type (left is the instance name).
            hint: i.channel_label || i.channel_type || '',
        }));
        if (options.length === 0) {
            // No instances at all — leave the picker showing a placeholder and
            // the recipient step hidden. Save will block with a clear message.
            initDropdown(instEl, [], '', () => {}, { placeholder: t('task_instance_empty') });
            filterTaskRecipients('');
            return;
        }
        // Only preselect an instance we actually offer (it may have been removed).
        const initialInstance = options.some(o => o.value === preInstance) ? preInstance : '';
        selectedTaskInstanceId = initialInstance;
        initDropdown(instEl, options, initialInstance, (iid) => {
            selectedTaskInstanceId = iid;
            filterTaskRecipients(iid);
            // Ownership follows the delivery instance — repaint the header chip
            // live so switching the channel never leaves a stale Agent showing.
            refreshTaskOwnerChipFromInstance(iid);
        }, { placeholder: t('task_instance_placeholder') });
        // Restore the recipient too when editing; otherwise force an explicit
        // choice so the list is never silently scoped to an arbitrary instance.
        filterTaskRecipients(initialInstance, initialInstance ? preReceiver : '');
        // Sync the header chip to the initially-selected instance (edit mode).
        if (initialInstance) refreshTaskOwnerChipFromInstance(initialInstance);
    });
}

// Step 2: the recipient dropdown appears only after a channel is picked, listing
// that instance's contacts. The first is selected by default; each row shows the
// recipient's (truncated) unique id on the right. Empty instances show a hint.
function filterTaskRecipients(instanceId, preReceiver) {
    const el = document.getElementById('task-edit-recipient');
    const wrap = document.getElementById('task-edit-recipient-wrap');
    if (!el) return;
    taskRecipientMap = {};

    // The recipient step only exists once a channel is chosen.
    if (wrap) wrap.classList.toggle('hidden', !instanceId);

    const scoped = instanceId
        ? taskAllRecipients.filter(r => (r.instance_id || r.channel_type) === instanceId)
        : [];

    let preKey = '';
    const options = scoped.map(r => {
        const iid = r.instance_id || r.channel_type;
        const key = iid + ':' + r.receiver;
        taskRecipientMap[key] = r;
        if (preReceiver && r.receiver === preReceiver) preKey = key;
        // Fall back to the raw id when a channel gives us no nickname (common on
        // Feishu). The right-hand hint carries the unique id (truncated).
        const name = r.name || r.receiver;
        return { value: key, label: name, hint: truncateRecipientId(r.receiver) };
    });

    // With no recipients the picker is not selectable — render it disabled with
    // the "no recipients yet, message the agent first" text right in the control.
    el.classList.toggle('cfg-dropdown-disabled', options.length === 0);

    // Restore the task's current recipient when editing; else default to the
    // first so the common case needs no extra click.
    const selectValue = preKey || (options.length ? options[0].value : '');
    initDropdown(el, options, selectValue, () => updateRecipientPreview(), {
        placeholder: options.length ? t('task_recipient_placeholder') : t('task_recipient_empty_hint'),
    });
    updateRecipientPreview();
}

// Re-fetch the trusted directory and rebuild the recipient list for the current
// instance. Lets the user pull in a contact who just messaged the channel
// without reopening the modal. A brief spin gives visual feedback.
function refreshTaskRecipients() {
    if (!selectedTaskInstanceId) return;
    const btn = document.getElementById('task-recipient-refresh');
    const icon = btn ? btn.querySelector('i') : null;
    if (icon) icon.classList.add('fa-spin');
    fetch('/api/scheduler/recipients')
        .then(r => r.json())
        .then(data => {
            taskAllRecipients = (data && data.status === 'success') ? (data.recipients || []) : taskAllRecipients;
            filterTaskRecipients(selectedTaskInstanceId);
        })
        .catch(() => {})
        .finally(() => { if (icon) icon.classList.remove('fa-spin'); });
}

// Open the modal in "create" mode: blank fields, recipient picker visible,
// channel selector driven by the picker, no delete button.
function openTaskCreateModal() {
    taskModalMode = 'create';
    currentEditingTask = null;

    const overlay = document.getElementById('task-edit-modal-overlay');
    const titleEl = document.querySelector('#task-edit-modal-overlay h3');
    const subtitle = document.getElementById('task-edit-modal-subtitle');
    const deleteBtn = document.getElementById('task-edit-modal-delete');
    const ownerEl = document.getElementById('task-edit-owner');

    titleEl.textContent = t('task_add_title');
    subtitle.textContent = '';
    deleteBtn.classList.add('hidden');
    if (ownerEl) { ownerEl.classList.add('hidden'); ownerEl.innerHTML = ''; }

    // Reset fields to sensible defaults.
    document.getElementById('task-edit-name').value = '';
    document.getElementById('task-edit-enabled').checked = true;
    document.getElementById('task-edit-cron-expression').value = '';
    document.getElementById('task-edit-interval-seconds').value = '';
    document.getElementById('task-edit-once-time').value = '';
    document.getElementById('task-edit-content').value = '';
    document.getElementById('task-edit-receiver').value = '';

    // Schedule/action are custom dropdowns; seed them to defaults.
    initTaskScheduleDropdown('cron');
    initTaskActionDropdown('send_message');

    // The "channel" cell holds the instance picker in create mode; the read-only
    // channel-type is only for edit mode. The recipient picker appears under it
    // once a channel is chosen (handled by filterTaskRecipients).
    document.getElementById('task-edit-instance-wrap').classList.remove('hidden');
    document.getElementById('task-edit-channel-wrap').classList.add('hidden');

    // Two-step picker: choose the channel instance first, then a recipient
    // within it. The owning Agent is derived server-side from that instance
    // (an instance binds to one Agent).
    loadTaskInstances();
    filterTaskRecipients('');

    updateTaskScheduleFields();
    updateTaskActionLabel();
    overlay.classList.remove('hidden');
}

// The schedule-type and action-type pickers are custom cfg-dropdowns. These
// helpers (re)build their option lists in the current language and route the
// selection into the existing show/hide + label logic that used to hang off a
// native <select> change event.
function initTaskScheduleDropdown(value) {
    const el = document.getElementById('task-edit-schedule-type');
    if (!el) return;
    const opts = [
        { value: 'cron', label: t('task_schedule_cron') },
        { value: 'interval', label: t('task_schedule_interval') },
        { value: 'once', label: t('task_schedule_once') },
    ];
    initDropdown(el, opts, value || 'cron', () => updateTaskScheduleFields());
}

function initTaskActionDropdown(value) {
    const el = document.getElementById('task-edit-action-type');
    if (!el) return;
    const opts = [
        { value: 'send_message', label: t('task_action_send_message') },
        { value: 'agent_task', label: t('task_action_agent_task') },
    ];
    initDropdown(el, opts, value || 'send_message', () => updateTaskActionLabel());
}

// Edit mode only: the channel is frozen, so this just paints a single read-only
// cfg-dropdown showing the task's channel with a friendly label. No selection is
// possible (the control carries cfg-dropdown-disabled).
function loadTaskChannelOptions(selectedChannelType) {
    const el = document.getElementById('task-edit-channel-type');
    if (!el) return;
    const ct = selectedChannelType || 'web';
    const paint = (label) => initDropdown(el, [{ value: ct, label: label }], ct, () => {});
    // Web has no channel record; label it directly.
    if (ct === 'web') { paint('Web'); return; }
    fetch('/api/channels').then(r => r.json()).then(data => {
        let label = ct;
        if (data && data.status === 'success') {
            const ch = (data.channels || []).find(c => c.name === ct);
            if (ch) label = (typeof ch.label === 'object') ? (ch.label[currentLang] || ch.label.en || ch.name) : (ch.label || ch.name);
        }
        paint(label);
    }).catch(() => paint(ct));
}

// The owning Agent shown (read-only) in the task edit modal header. Hidden on a
// single-Agent install, where every task belongs to the one Agent anyway.
//
// Ownership follows the delivery channel instance: an IM task belongs to
// whichever Agent that instance is currently bound to. So while editing, picking
// a different instance must repaint this chip live (before save) — otherwise the
// header would still show the old Agent and read as stale/dirty data.
function renderTaskOwnerChip(agentId) {
    const el = document.getElementById('task-edit-owner');
    if (!el) return;
    const agent = agentId ? findAgent(agentId) : null;
    if (!multiAgentMode() || !agent) {
        el.classList.add('hidden');
        el.innerHTML = '';
        return;
    }
    el.innerHTML = `${agentAvatarHTML(agent, 20)}
        <span class="text-xs font-medium text-slate-600 dark:text-slate-300 truncate max-w-[120px]">${escapeHtml(agent.name || agent.id)}</span>`;
    el.classList.remove('hidden');
    el.classList.add('flex');
}

// Repaint the owner chip from a channel instance's current binding. An instance
// with no explicit binding (or a legacy single-instance channel) falls back to
// the default Agent, matching how the backend derives the effective owner.
function refreshTaskOwnerChipFromInstance(instanceId) {
    const inst = (taskInstances || []).find(i => i.instance_id === instanceId);
    const agentId = (inst && inst.agent_id) ? inst.agent_id : defaultAgentId;
    renderTaskOwnerChip(agentId);
}

function openTaskEditModal(task) {
    taskModalMode = 'edit';
    currentEditingTask = task;
    const overlay = document.getElementById('task-edit-modal-overlay');
    const titleEl = document.querySelector('#task-edit-modal-overlay h3');
    const subtitle = document.getElementById('task-edit-modal-subtitle');
    const deleteBtn = document.getElementById('task-edit-modal-delete');
    const nameInput = document.getElementById('task-edit-name');
    const enabledInput = document.getElementById('task-edit-enabled');
    const scheduleTypeSelect = document.getElementById('task-edit-schedule-type');
    const cronInput = document.getElementById('task-edit-cron-expression');
    const intervalInput = document.getElementById('task-edit-interval-seconds');
    const onceInput = document.getElementById('task-edit-once-time');
    const actionTypeSelect = document.getElementById('task-edit-action-type');
    const receiverInput = document.getElementById('task-edit-receiver');
    const contentInput = document.getElementById('task-edit-content');

    // Set title and subtitle
    titleEl.textContent = t('task_edit_title');
    subtitle.textContent = task.id;
    deleteBtn.classList.remove('hidden');

    // Show which Agent owns this task. Only meaningful with more than one Agent;
    // a solo install would just repeat the obvious. For an IM task the chip is
    // repainted from the picked instance once instances load (and again on every
    // switch); web/unbound tasks show the stored owner.
    renderTaskOwnerChip(task.agent_id);

    // Populate data
    nameInput.value = task.name || '';
    enabledInput.checked = task.enabled !== false;

    const schedule = task.schedule || {};
    initTaskScheduleDropdown(schedule.type || 'cron');

    // Clear all schedule type input values first to avoid stale data
    cronInput.value = '';
    intervalInput.value = '';
    onceInput.value = '';

    if (schedule.type === 'cron') {
        cronInput.value = schedule.expression || '';
    } else if (schedule.type === 'interval') {
        intervalInput.value = schedule.seconds || '';
    } else if (schedule.type === 'once') {
        if (schedule.run_at) {
            const timeInput = document.getElementById('task-edit-once-time');
            timeInput.value = formatTaskDateTimeLocal(
                schedule.run_at,
                schedule.timezone || ''
            );
        }
    }

    const action = task.action || {};
    initTaskActionDropdown(action.type || 'send_message');
    receiverInput.value = action.receiver || '';
    contentInput.value = action.content || action.task_description || '';

    // Channel/recipient presentation depends on the task's channel:
    //   - Web tasks target a chat session, not a switchable contact, so keep the
    //     read-only channel-type display and no picker.
    //   - IM tasks reuse the same two-step picker as create (instance + recipient),
    //     preselected to the task's current values, so the channel instance and the
    //     recipient can both be switched here just like when creating.
    const channelType = action.channel_type || 'web';
    if (channelType === 'web') {
        document.getElementById('task-edit-recipient-wrap').classList.add('hidden');
        document.getElementById('task-edit-instance-wrap').classList.add('hidden');
        document.getElementById('task-edit-channel-wrap').classList.remove('hidden');
        loadTaskChannelOptions(channelType);
    } else {
        document.getElementById('task-edit-channel-wrap').classList.add('hidden');
        document.getElementById('task-edit-instance-wrap').classList.remove('hidden');
        // filterTaskRecipients (called inside) toggles the recipient wrap visible.
        loadTaskInstances({
            instanceId: action.instance_id || action.channel_type || '',
            receiver: action.receiver || '',
        });
    }

    // Update UI
    updateTaskScheduleFields();
    updateTaskActionLabel();

    overlay.classList.remove('hidden');
}

function closeTaskEditModal() {
    document.getElementById('task-edit-modal-overlay').classList.add('hidden');
    currentEditingTask = null;
}

function updateTaskScheduleFields() {
    const scheduleType = getDropdownValue(document.getElementById('task-edit-schedule-type')) || 'cron';
    const cronWrap = document.getElementById('task-edit-cron-wrap');
    const intervalWrap = document.getElementById('task-edit-interval-wrap');
    const onceWrap = document.getElementById('task-edit-once-wrap');
    const cronHint = document.getElementById('task-edit-cron-hint');
    const intervalHint = document.getElementById('task-edit-interval-hint');
    
    cronWrap.classList.toggle('hidden', scheduleType !== 'cron');
    intervalWrap.classList.toggle('hidden', scheduleType !== 'interval');
    onceWrap.classList.toggle('hidden', scheduleType !== 'once');
    
    if (cronHint) cronHint.classList.toggle('hidden', scheduleType !== 'cron');
    if (intervalHint) intervalHint.classList.toggle('hidden', scheduleType !== 'interval');
}

function updateTaskActionLabel() {
    const actionType = getDropdownValue(document.getElementById('task-edit-action-type')) || 'send_message';
    const label = document.getElementById('task-edit-content-label');
    const content = document.getElementById('task-edit-content');
    
    if (actionType === 'send_message') {
        // A fixed-message task delivers this text verbatim, so both the label and
        // the placeholder read "Fixed Content".
        label.textContent = t('task_fixed_content');
        content.placeholder = t('task_fixed_content');
    } else {
        label.textContent = t('task_task_description');
        content.placeholder = t('task_task_description');
    }
}

function saveTaskEdit() {
    const nameInput = document.getElementById('task-edit-name');
    const enabledInput = document.getElementById('task-edit-enabled');
    const scheduleTypeSelect = document.getElementById('task-edit-schedule-type');
    const cronInput = document.getElementById('task-edit-cron-expression');
    const intervalInput = document.getElementById('task-edit-interval-seconds');
    const onceInput = document.getElementById('task-edit-once-time');
    const actionTypeSelect = document.getElementById('task-edit-action-type');
    const channelTypeSelect = document.getElementById('task-edit-channel-type');
    const receiverInput = document.getElementById('task-edit-receiver');
    const contentInput = document.getElementById('task-edit-content');
    const statusEl = document.getElementById('task-edit-modal-status');
    const saveBtn = document.getElementById('task-edit-modal-save');
    
    const name = nameInput.value.trim();
    if (!name) {
        statusEl.textContent = 'Please enter task name';
        statusEl.style.opacity = '1';
        setTimeout(() => { statusEl.style.opacity = '0'; }, 3000);
        return;
    }
    
    const scheduleType = getDropdownValue(scheduleTypeSelect) || 'cron';
    const previousSchedule = (currentEditingTask && currentEditingTask.schedule) || {};
    const taskTimezone = previousSchedule.timezone || '';
    const schedule = { type: scheduleType };
    
    if (scheduleType === 'cron') {
        const expr = cronInput.value.trim();
        if (!expr) {
            statusEl.textContent = 'Please enter cron expression';
            statusEl.style.opacity = '1';
            setTimeout(() => { statusEl.style.opacity = '0'; }, 3000);
            return;
        }
        // Basic cron expression format validation: 5 or 6 fields
        const fields = expr.split(/\s+/);
        if (fields.length < 5 || fields.length > 6) {
            statusEl.textContent = 'Invalid cron expression, expected 5 or 6 fields (min hour day month weekday)';
            statusEl.style.opacity = '1';
            setTimeout(() => { statusEl.style.opacity = '0'; }, 3000);
            return;
        }
        schedule.expression = expr;
        if (taskTimezone) schedule.timezone = taskTimezone;
        // Note: detailed cron expression validity is verified by the backend croniter library; frontend only does basic format validation
    } else if (scheduleType === 'interval') {
        const seconds = parseInt(intervalInput.value);
        if (!seconds || seconds < 60) {
            statusEl.textContent = 'Interval must be at least 60 seconds';
            statusEl.style.opacity = '1';
            setTimeout(() => { statusEl.style.opacity = '0'; }, 3000);
            return;
        }
        schedule.seconds = seconds;
    } else if (scheduleType === 'once') {
        const time = onceInput.value;
        if (!time) {
            statusEl.textContent = 'Please select execution time';
            statusEl.style.opacity = '1';
            setTimeout(() => { statusEl.style.opacity = '0'; }, 3000);
            return;
        }
        const selectedUTC = taskLocalTimeToUTC(time, taskTimezone);
        if (!selectedUTC || isNaN(Date.parse(selectedUTC))) {
            statusEl.textContent = 'Invalid execution time format';
            statusEl.style.opacity = '1';
            setTimeout(() => { statusEl.style.opacity = '0'; }, 3000);
            return;
        }
        if (new Date(selectedUTC) <= new Date()) {
            statusEl.textContent = 'Execution time must be in the future';
            statusEl.style.opacity = '1';
            setTimeout(() => { statusEl.style.opacity = '0'; }, 3000);
            return;
        }
        if (taskTimezone) {
            schedule.timezone = taskTimezone;
            schedule.run_at = selectedUTC;
        } else {
            // datetime-local value with step="1" remains a legacy naive local
            // timestamp when the task does not declare an IANA timezone.
            schedule.run_at = time;
        }
    }
    
    const actionType = getDropdownValue(actionTypeSelect) || 'send_message';
    const channelType = getDropdownValue(channelTypeSelect) || 'web';
    const content = contentInput.value.trim();

    if (!content) {
        statusEl.textContent = 'Please enter content';
        statusEl.style.opacity = '1';
        setTimeout(() => { statusEl.style.opacity = '0'; }, 3000);
        return;
    }
    
    const showError = (msg) => {
        statusEl.textContent = msg;
        statusEl.style.opacity = '1';
        setTimeout(() => { statusEl.style.opacity = '0'; }, 3000);
    };
    const onDone = () => {
        closeTaskEditModal();
        tasksLoaded = false;
        loadTasksView();
    };

    // --- Create mode: post a brand-new cross-channel task to a trusted recipient
    if (taskModalMode === 'create') {
        if (!selectedTaskInstanceId) {
            showError(t('task_instance_required'));
            return;
        }
        const recipientEl = document.getElementById('task-edit-recipient');
        const key = recipientEl ? getDropdownValue(recipientEl) : '';
        const recipient = taskRecipientMap[key];
        if (!recipient) {
            showError(t('task_recipient_required'));
            return;
        }
        // The owning Agent is derived server-side from the recipient's channel
        // instance (an instance binds to one Agent), so the client only names
        // the instance + receiver. The instance is what delivery routes back
        // through; two instances of one channel type are distinct targets.
        const action = {
            type: actionType,
            channel_type: recipient.channel_type,
            instance_id: recipient.instance_id || recipient.channel_type,
            receiver: recipient.receiver,
        };
        if (actionType === 'send_message') {
            action.content = content;
        } else {
            action.task_description = content;
        }
        saveBtn.disabled = true;
        fetch('/api/scheduler/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name,
                enabled: enabledInput.checked,
                schedule: schedule,
                action: action,
            })
        }).then(r => r.json()).then(res => {
            saveBtn.disabled = false;
            if (res.status === 'success') {
                onDone();
            } else {
                showError(res.message || 'Create failed');
            }
        }).catch(() => {
            saveBtn.disabled = false;
            showError('Network error');
        });
        return;
    }

    // --- Edit mode: update an existing task.
    const origAction = (currentEditingTask && currentEditingTask.action) || {};
    const wasWeb = (origAction.channel_type || 'web') === 'web';

    const action = {
        type: actionType,
        channel_type: channelType,
        receiver: '',
        receiver_name: '',
        is_group: false,
        notify_session_id: ''
    };
    
    if (actionType === 'send_message') {
        action.content = content;
    } else {
        action.task_description = content;
    }
    
    if (wasWeb) {
        // Web target isn't switchable: keep the original session receiver/channel.
        action.channel_type = origAction.channel_type || 'web';
        action.receiver = origAction.receiver || '';
        action.receiver_name = origAction.receiver_name || '';
        action.is_group = origAction.is_group || false;
        action.notify_session_id = origAction.notify_session_id || '';
    } else {
        // IM task: channel instance + recipient can be switched via the picker,
        // exactly like create. Read them back from the two-step selection.
        if (!selectedTaskInstanceId) {
            showError(t('task_instance_required'));
            saveBtn.disabled = false;
            return;
        }
        const recipientEl = document.getElementById('task-edit-recipient');
        const key = recipientEl ? getDropdownValue(recipientEl) : '';
        const recipient = taskRecipientMap[key];
        if (!recipient) {
            showError(t('task_recipient_required'));
            saveBtn.disabled = false;
            return;
        }
        action.channel_type = recipient.channel_type;
        action.instance_id = recipient.instance_id || recipient.channel_type;
        action.receiver = recipient.receiver;
        action.receiver_name = recipient.name || recipient.receiver;
        action.is_group = recipient.is_group || false;
        action.notify_session_id = recipient.session_id || recipient.receiver;
        // Preserve channel-specific fields only when the channel is unchanged
        // (e.g. DingTalk sender_staff_id is meaningless on a different instance).
        if (
            action.channel_type === (origAction.channel_type || '') &&
            action.receiver === (origAction.receiver || '') &&
            origAction.dingtalk_sender_staff_id
        ) {
            action.dingtalk_sender_staff_id = origAction.dingtalk_sender_staff_id;
        }
    }
    
    saveBtn.disabled = true;
    
    const payload = {
        task_id: currentEditingTask.id,
        agent_id: currentEditingTask.agent_id || '',
        name: name,
        enabled: enabledInput.checked,
        schedule: schedule,
        action: action
    };
    
    fetch('/api/scheduler/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    }).then(r => r.json()).then(res => {
        saveBtn.disabled = false;
        if (res.status === 'success') {
            onDone();
        } else {
            showError(res.message || 'Save failed');
        }
    }).catch(() => {
        saveBtn.disabled = false;
        showError('Network error');
    });
}

function deleteTask() {
    if (!currentEditingTask) return;
    
    const taskName = currentEditingTask.name || currentEditingTask.id || '未知任务';
    const taskId = currentEditingTask.id;  // Capture early to avoid closure race condition
    const taskAgentId = currentEditingTask.agent_id || '';  // route delete to the owner's store
    showConfirmDialog({
        title: t('task_delete_confirm_title'),
        message: `Are you sure to delete task "${taskName}"?`,
        onConfirm: () => {
            fetch('/api/scheduler/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ task_id: taskId, agent_id: taskAgentId })
            }).then(r => r.json()).then(res => {
                if (res.status === 'success') {
                    closeTaskEditModal();
                    tasksLoaded = false;
                    loadTasksView();
                } else {
                    const statusEl = document.getElementById('task-edit-modal-status');
                    if (statusEl) {
                        statusEl.textContent = res.message || 'Delete failed';
                        statusEl.classList.remove('hidden', 'text-green-500');
                        statusEl.classList.add('text-red-500');
                        setTimeout(() => { statusEl.style.opacity = '0'; }, 3000);
                    }
                }
            }).catch(() => {
                const statusEl = document.getElementById('task-edit-modal-status');
                if (statusEl) {
                    statusEl.textContent = 'Network error';
                    statusEl.classList.remove('hidden', 'text-green-500');
                    statusEl.classList.add('text-red-500');
                    setTimeout(() => { statusEl.style.opacity = '0'; }, 3000);
                }
            });
        }
    });
}


// schedule-type / action-type / recipient are now cfg-dropdowns; their change
// handling is wired through initDropdown's onChange when each modal opens.
document.getElementById('task-edit-modal-cancel').addEventListener('click', closeTaskEditModal);
document.getElementById('task-edit-modal-save').addEventListener('click', saveTaskEdit);
document.getElementById('task-edit-modal-delete').addEventListener('click', deleteTask);
document.getElementById('task-edit-modal-overlay').addEventListener('click', function(e) {
    if (e.target === this) closeTaskEditModal();
});
