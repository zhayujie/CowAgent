/* Write-only environment settings. Never persist or fetch plaintext values. */
Object.assign(I18N.zh, {
    env_title: '环境变量', env_help: '使用提示',
    env_description: '永远不会获取真实内容，仅显示脱敏内容',
    env_help_hint: '保存后未生效时，请重启 CowAgent。模型配置中的同名项可能覆盖此值。',
    env_model_hint: '同名模型配置可能覆盖此值。', env_model_settings: '检查模型配置',
    env_add: '新增变量', env_edit: '编辑变量', env_key: '变量名称', env_value: '值',
    env_value_new: '请输入值', env_value_keep: '留空保留原值',
    env_save: '保存', env_cancel: '取消',
    env_search: '搜索变量名称', env_refresh: '刷新',
    env_preview: '内容', env_actions: '操作', env_show: '显示输入值', env_hide: '隐藏输入值',
    env_copy: '复制名称', env_delete: '删除', env_no_preview: '待刷新',
    env_load_existing: '点击刷新加载已有变量',
    env_loading: '正在加载…', env_no_results: '没有匹配的变量', env_no_variables: '暂无变量',
    env_saved: '已保存',
    env_unchanged: '原值未变', env_deleted: '已删除', env_copied: '已复制名称',
    env_delete_title: '删除环境变量', env_delete_confirm: '确定删除此变量？此操作无法撤销：',
    env_error: '操作失败，请检查存储权限或重试。', env_auth: '请先登录 CowAgent。',
    env_metadata_pending: '已保存，点击刷新更新内容', env_reload_pending: '已保存，请重启后使用',
    env_invalid_key: '名称仅允许英文字母、数字和下划线，不能以数字开头，最多 128 个字符。',
    env_launch_setting: '运行路径由启动配置管理，不能在此修改。', env_invalid_value: '值必须是有效的单行文本，最多 8192 个字符。',
    env_masked_value: '不能把脱敏预览作为新密钥保存。',
    env_interpolated_value: '新值不能包含 ${…}，以避免重启时被 dotenv 替换。',
    env_value_required: '请输入值。', env_already_exists: '同名变量已存在，请使用编辑。',
    env_case_conflict: 'Windows 不区分变量名大小写，请使用唯一名称。',
    env_not_found: '变量已不存在，请刷新列表。', env_external_change: '内容已变更，请刷新后重试。',
    env_unsafe_file: '凭据文件必须是普通文件，不能通过此页面编辑符号链接。',
    env_cross_origin: '跨站请求已拒绝，请从当前 CowAgent 页面操作。', env_csrf: '请求安全校验失败，请刷新后重试。',
});
Object.assign(I18N['zh-Hant'], {
    env_title: '環境變數', env_help: '使用提示',
    env_description: '永遠不會取得真實內容，僅顯示脫敏內容',
    env_help_hint: '儲存後未生效時，請重新啟動 CowAgent。模型設定中的同名項目可能覆寫此值。',
    env_model_hint: '同名模型設定可能覆寫此值。', env_model_settings: '檢查模型設定',
    env_add: '新增變數', env_edit: '編輯變數', env_key: '變數名稱', env_value: '值',
    env_value_new: '請輸入值', env_value_keep: '留空保留原值',
    env_save: '儲存', env_cancel: '取消',
    env_search: '搜尋變數名稱', env_refresh: '重新整理',
    env_preview: '內容', env_actions: '操作', env_show: '顯示輸入值', env_hide: '隱藏輸入值',
    env_copy: '複製名稱', env_delete: '刪除', env_no_preview: '待重新整理',
    env_load_existing: '點擊重新整理以載入既有變數',
    env_loading: '正在載入…', env_no_results: '沒有符合的變數', env_no_variables: '暫無變數',
    env_saved: '已儲存',
    env_unchanged: '原值未變', env_deleted: '已刪除', env_copied: '已複製名稱',
    env_delete_title: '刪除環境變數', env_delete_confirm: '確定刪除此變數？此操作無法復原：',
    env_error: '操作失敗，請檢查儲存權限或重試。', env_auth: '請先登入 CowAgent。',
    env_metadata_pending: '已儲存，請重新整理以更新內容', env_reload_pending: '已儲存，請重新啟動後使用',
    env_invalid_key: '名稱僅允許英文字母、數字及底線，不能以數字開頭，最多 128 個字元。',
    env_launch_setting: '執行路徑由啟動設定管理，不能在此修改。', env_invalid_value: '值必須是有效的單行文字，最多 8192 個字元。',
    env_masked_value: '不能將脫敏預覽當作新金鑰儲存。',
    env_interpolated_value: '新值不能包含 ${…}，以免重新啟動時被 dotenv 替換。',
    env_value_required: '請輸入值。', env_already_exists: '同名變數已存在，請使用編輯。',
    env_case_conflict: 'Windows 不區分變數名稱大小寫，請使用唯一名稱。',
    env_not_found: '變數已不存在，請重新整理列表。', env_external_change: '內容已變更，請重新整理後重試。',
    env_unsafe_file: '憑證檔案必須是一般檔案，不能透過此頁面編輯符號連結。',
    env_cross_origin: '跨站請求已拒絕，請從目前的 CowAgent 頁面操作。', env_csrf: '請求安全驗證失敗，請重新整理後重試。',
});
Object.assign(I18N.en, {
    env_title: 'Environment variables', env_help: 'Usage tips',
    env_description: 'Never retrieves actual values; only masked values are displayed',
    env_help_hint: 'Restart CowAgent if a saved change has no effect. Matching model settings may overwrite this value.',
    env_model_hint: 'Matching model settings may overwrite this value.', env_model_settings: 'Check model settings',
    env_add: 'Add variable', env_edit: 'Edit variable', env_key: 'Variable name', env_value: 'Value',
    env_value_new: 'Enter a value', env_value_keep: 'Leave blank to keep current value',
    env_save: 'Save', env_cancel: 'Cancel',
    env_search: 'Search variable names', env_refresh: 'Refresh',
    env_preview: 'Value', env_actions: 'Actions', env_show: 'Show input', env_hide: 'Hide input',
    env_copy: 'Copy name', env_delete: 'Delete', env_no_preview: 'Refresh needed',
    env_load_existing: 'Refresh to load existing variables',
    env_loading: 'Loading…', env_no_results: 'No matching variables', env_no_variables: 'No variables yet',
    env_saved: 'Saved',
    env_unchanged: 'Value unchanged', env_deleted: 'Deleted', env_copied: 'Name copied',
    env_delete_title: 'Delete environment variable', env_delete_confirm: 'Delete this variable? This cannot be undone:',
    env_error: 'Operation failed. Check storage permissions or try again.', env_auth: 'Please sign in to CowAgent.',
    env_metadata_pending: 'Saved. Refresh to update the preview.', env_reload_pending: 'Saved. Restart to apply.',
    env_invalid_key: 'Use letters, digits and underscores; start with a letter or underscore. Maximum 128 characters.',
    env_launch_setting: 'Runtime paths are launch settings and cannot be changed here.', env_invalid_value: 'Use valid single-line text, up to 8192 characters.',
    env_masked_value: 'A masked preview cannot replace a secret.',
    env_interpolated_value: 'New values cannot contain ${…}, which dotenv would expand at restart.',
    env_value_required: 'Enter a value.', env_already_exists: 'This variable already exists. Use Edit.',
    env_case_conflict: 'Windows variable names are case-insensitive. Use a unique name.',
    env_not_found: 'This variable no longer exists. Refresh the list.', env_external_change: 'Contents changed. Refresh and try again.',
    env_unsafe_file: 'Credentials must be a regular file. Symbolic links cannot be edited here.',
    env_cross_origin: 'Cross-origin request rejected. Use the current CowAgent page.', env_csrf: 'Request validation failed. Refresh and try again.',
});

const envManager = { variables: [], editing: null, busy: false, loading: false, revision: 0, needsSync: false, fileExists: false, feedbackTimer: null };
const envEl = id => document.getElementById('env-' + id);

function hideEnvFeedback() {
    clearTimeout(envManager.feedbackTimer);
    envEl('feedback').classList.add('hidden');
}

function envFeedback(key, error = false) {
    hideEnvFeedback();
    const el = envEl('feedback');
    el.dataset.i18n = key;
    el.textContent = t(key);
    el.dataset.error = String(error);
    el.classList.remove('hidden');
    if (!error) envManager.feedbackTimer = setTimeout(hideEnvFeedback, 3500);
}

function envMessage(error) {
    const key = 'env_' + (error.code || 'error');
    envFeedback(typeof I18N.en[key] === 'string' ? key : 'env_error', true);
}

async function envRequest(path = '', method = 'GET', body) {
    const options = { method, cache: 'no-store', credentials: 'same-origin', headers: { 'X-Cow-Env-Request': '1' } };
    if (body !== undefined) {
        options.headers['Content-Type'] = 'application/json';
        options.body = JSON.stringify(body);
    }
    const response = await fetch('/api/env' + path, options);
    if (response.status === 401) throw { code: 'auth' };
    const data = await response.json();
    if (!response.ok || data.status !== 'success') throw { code: data.code || 'error' };
    return data;
}

function acceptEnvListing(data) {
    envManager.variables = data.variables || [];
    envManager.needsSync = !!data.needs_sync;
    envManager.fileExists = !!data.file_exists;
    renderEnvVariables();
}

async function loadEnvView(synchronize = false) {
    if (envManager.busy) return;
    hideEnvFeedback();
    const revision = ++envManager.revision;
    envManager.loading = true;
    if (synchronize) envBusy(true);
    renderEnvVariables();
    try {
        let data = await envRequest();
        // Reading the view stays metadata-only. A deliberate Refresh click
        // also initializes or repairs previews when needed.
        if (synchronize && data.needs_sync) data = await envRequest('/actions/sync', 'POST', {});
        if (revision === envManager.revision) acceptEnvListing(data);
    } catch (error) {
        if (revision === envManager.revision) { envManager.variables = []; envMessage(error); }
    } finally {
        if (revision === envManager.revision) {
            envManager.loading = false;
            if (synchronize) envBusy(false);
            else renderEnvVariables();
        }
    }
}

function envText(tag, text, className = '') {
    const el = document.createElement(tag);
    el.textContent = text;
    el.className = className;
    return el;
}

function envLocalized(tag, key, className = '') {
    const el = envText(tag, t(key), className);
    el.dataset.i18n = key;
    return el;
}

function renderEnvVariables() {
    const list = envEl('list');
    if (!list) return;
    list.replaceChildren();
    if (envManager.loading) { list.append(envLocalized('p', 'env_loading', 'env-list-empty')); return; }
    const query = envEl('search').value.trim().toLocaleLowerCase();
    const variables = envManager.variables.filter(v => v.key.toLocaleLowerCase().includes(query));
    if (!variables.length) {
        const empty = envManager.needsSync && envManager.fileExists ? 'env_load_existing' : 'env_no_variables';
        list.append(envLocalized('p', query ? 'env_no_results' : empty, 'env-list-empty'));
    }
    for (const variable of variables) {
        const row = envText('div', '', 'env-row text-sm');
        const info = envText('div', '');
        info.append(envText('div', variable.key, 'env-key-name font-mono'));
        const preview = variable.preview
            ? envText('div', variable.preview, 'env-row-preview font-mono')
            : envLocalized('div', 'env_no_preview', 'env-row-preview env-muted');
        const actions = envText('div', '', 'env-row-actions');
        for (const [label, icon, action] of [
            ['env_copy', 'fa-copy', () => copyEnvName(variable.key)],
            ['env_edit', 'fa-pen', () => openEnvEditor(variable)],
            ['env_delete', 'fa-trash-can', () => deleteEnvVariable(variable)],
        ]) {
            const button = envText('button', '', label === 'env_delete' ? 'env-delete' : '');
            button.type = 'button';
            button.title = t(label);
            button.setAttribute('aria-label', t(label) + ': ' + variable.key);
            const glyph = envText('i', '', 'fas ' + icon);
            glyph.setAttribute('aria-hidden', 'true');
            button.append(glyph);
            button.addEventListener('click', action);
            button.disabled = envManager.busy;
            actions.append(button);
        }
        row.append(info, preview, actions);
        list.append(row);
    }
}

function clearEnvEditor() {
    const form = envEl('editor');
    if (!form) return;
    form.reset();
    form.classList.add('hidden');
    envEl('value').type = 'password';
    envEl('value').required = true;
    envEl('value').dataset.i18nPlaceholder = 'env_value_new';
    envEl('value').placeholder = t('env_value_new');
    envEl('key').readOnly = false;
    envManager.editing = null;
    envUpdateToggle();
}

function openEnvEditor(variable = null) {
    if (envManager.busy) return;
    hideEnvFeedback();
    clearEnvEditor();
    envManager.editing = variable ? variable.key : null;
    envEl('editor-title').dataset.i18n = variable ? 'env_edit' : 'env_add';
    envEl('editor-title').textContent = t(variable ? 'env_edit' : 'env_add');
    envEl('key').value = variable ? variable.key : '';
    envEl('key').readOnly = !!variable;
    envEl('current').textContent = variable ? variable.preview || t('env_no_preview') : '';
    if (variable && !variable.preview) envEl('current').dataset.i18n = 'env_no_preview';
    else delete envEl('current').dataset.i18n;
    envEl('current').classList.toggle('hidden', !variable);
    const placeholder = variable ? 'env_value_keep' : 'env_value_new';
    envEl('value').required = !variable;
    envEl('value').dataset.i18nPlaceholder = placeholder;
    envEl('value').placeholder = t(placeholder);
    envKeyChanged();
    envEl('editor').classList.remove('hidden');
    envEl('editor').scrollIntoView({ block: 'nearest' });
    envEl(variable ? 'value' : 'key').focus();
}

function envKeyChanged() {
    const modelKeys = ['OPENAI_API_KEY', 'OPENAI_API_BASE', 'GEMINI_API_KEY', 'CLAUDE_API_KEY', 'LINKAI_API_KEY'];
    envEl('model-hint').classList.toggle('hidden', !modelKeys.includes(envEl('key').value));
}

function envUpdateToggle() {
    const shown = envEl('value').type === 'text';
    const button = envEl('toggle');
    button.dataset.i18nAriaLabel = shown ? 'env_hide' : 'env_show';
    button.setAttribute('aria-label', t(button.dataset.i18nAriaLabel));
    button.setAttribute('aria-pressed', String(shown));
    button.firstElementChild.className = 'fas ' + (shown ? 'fa-eye-slash' : 'fa-eye');
}

function toggleEnvValue() {
    envEl('value').type = envEl('value').type === 'password' ? 'text' : 'password';
    envUpdateToggle();
}

function envBusy(busy) {
    envManager.busy = busy;
    envEl('fields').disabled = busy;
    document.querySelectorAll('#config-panel-environment > .env-heading button, .env-toolbar button').forEach(b => { b.disabled = busy; });
    renderEnvVariables();
}

async function saveEnvVariable(event) {
    event.preventDefault();
    if (envManager.busy) return;
    const key = envEl('key').value;
    const editing = envManager.editing;
    const body = {};
    if (envEl('value').value) body.value = envEl('value').value;
    // Remove the DOM copy before awaiting the network. The request owns the
    // only transient copy; no app state, chat messages or browser storage.
    envEl('value').value = '';
    envEl('value').type = 'password';
    envUpdateToggle();
    ++envManager.revision;
    envManager.loading = false;
    envBusy(true);
    try {
        const data = await envRequest(editing ? '/' + encodeURIComponent(key) : '', editing ? 'PUT' : 'POST', editing ? body : { key, ...body });
        acceptEnvListing(data);
        clearEnvEditor();
        envFeedback(data.warning ? 'env_' + data.warning : data.restart_may_be_required ? 'env_saved' : 'env_unchanged', !!data.warning);
    } catch (error) { envMessage(error); }
    finally { delete body.value; envBusy(false); }
}

function deleteEnvVariable(variable) {
    if (envManager.busy) return;
    showConfirmDialog({
        title: t('env_delete_title'), message: t('env_delete_confirm') + ' ' + variable.key,
        okText: t('env_delete'), cancelText: t('env_cancel'),
        onConfirm: async () => {
            if (envManager.busy) return;
            ++envManager.revision;
            envManager.loading = false;
            envBusy(true);
            try {
                const data = await envRequest('/' + encodeURIComponent(variable.key), 'DELETE', {});
                acceptEnvListing(data);
                if (envManager.editing === variable.key) clearEnvEditor();
                envFeedback(data.warning ? 'env_' + data.warning : 'env_deleted', !!data.warning);
            } catch (error) { envMessage(error); }
            finally { envBusy(false); }
        },
    });
}

async function copyEnvName(key) {
    try { await copyToClipboard(key); envFeedback('env_copied'); }
    catch (_) { envFeedback('env_error', true); }
}

document.addEventListener('visibilitychange', () => { if (document.hidden) clearEnvEditor(); });
