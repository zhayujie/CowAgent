/* =====================================================================
   CowAgent Console - Main Application Script
   ===================================================================== */

// =====================================================================
// Version — fetched from backend (single source: /VERSION file)
// =====================================================================
let APP_VERSION = '';

// =====================================================================
// i18n
// =====================================================================
const I18N = {
    zh: {
        console: '控制台',
        nav_chat: '对话', nav_manage: '管理', nav_monitor: '监控',
        menu_chat: '对话', menu_agents: '智能体', menu_config: '配置', menu_skills: '技能',
        agents_page_title: '智能体团队', agents_page_desc: '管理团队中的智能体成员',
        agents_create: '创建智能体',
        agents_name_placeholder: '智能体名称',
        agents_name_required: '请填写名称',
        agents_stale: '列表已更新，请刷新后重试',
        agents_id_placeholder: '留空则自动生成',
        agents_id_tip: '智能体的唯一标识，创建后不可修改。仅支持小写英文、数字和连字符（-），如 coding-agent。留空则根据名称自动生成。',
        agents_id_invalid: 'ID 需以字母或数字开头，仅支持字母、数字、下划线和连字符，最长 64 位',
        agents_avatar: '头像',
        agents_tab_profile: '概况',
        agents_tab_skills: '能力',
        agents_tab_files: '核心文件',
        agents_core_edit: '编辑',
        agents_core_preview: '预览',
        agents_core_file_agent: '智能体设定',
        agents_core_file_user: '用户信息',
        agents_core_file_rule: '工作空间规则',
        agents_core_file_memory: '长期记忆',
        agents_default: '默认',
        agents_archived: '已归档',
        agents_chat: '开始对话',
        agents_delete: '删除',
        agents_delete_title: '删除智能体',
        agents_delete_confirm: '确定删除智能体「{name}」吗？其工作空间和会话将一并移除，且无法恢复。',
        agents_pick_hint: '选择智能体',
        agents_clone_label: '从已有智能体复制',
        agents_clone_hint: '复制其配置、技能与知识作为起点',
        agents_avatar_upload: '上传图片',
        agents_clone_none: '空白',
        agents_clone_from: '{name}',
        agents_name: '名称',
        agents_saved: '已保存',
        agents_save_failed: '保存失败',
        agents_no_desc: '暂无职责',
        agents_description: '职责',
        agents_description_placeholder: '该智能体负责哪些工作、在什么场景被使用',
        agents_description_hint: '用于多智能体协作时的任务分配',
        agents_model: '默认模型',
        agents_model_follows_global: '跟随全局配置',
        agents_model_default_hint: '默认使用主模型，在「模型配置」中修改。',
        agents_skills_all: '使用全部已安装技能',
        agents_skills_pick: '只启用勾选的技能',
        agents_knowledge: '知识库',
        agents_knowledge_shared: '共享',
        agents_knowledge_own: '独立',
        agents_knowledge_hint: '共享：与团队读写同一个知识库\n独立：拥有专属知识库，互不影响',
        agents_knowledge_working: '处理中…',
        agents_knowledge_failed: '切换失败',
        agents_empty: '还没有智能体。创建一个，开始组团队。',
        agents_select_hint: '从左侧选择一个智能体进行配置',
        agents_pick_tip: '切换当前智能体',
        composer_current_agent: '当前智能体',
        team_members: '当前会话成员',
        team_invite: '添加到会话',
        team_remove: '移出这个会话',
        composer_agent_owner: '主智能体',
        channel_bound_agent: '绑定智能体',
        channel_bound_default: '默认',
        channel_bound_agent_hint: '第一个为默认智能体，负责接收消息并可委派给其他成员',
        channel_team_none: '未选择',
        channel_team_no_candidates: '暂无可选的智能体',
        settings_tab_basic: '基础配置',
        settings_tab_models: '模型配置',
        knowledge_shared_hint: '知识库默认全员共享，在侧栏「知识」查看和编辑。',
        menu_memory: '记忆', menu_knowledge: '知识', menu_channels: '通道', menu_tasks: '定时',
        menu_logs: '日志',
        models_title: '模型管理',
        models_desc: '统一管理对话、图像、语音、向量、搜索能力',
        models_section_vendors: '厂商凭据',
        models_section_vendors_desc: '一处配置，多个模型能力共享',
        models_section_capabilities: '模型能力',
        models_add_vendor: '添加厂商',
        models_provider: '厂商',
        models_model: '模型',
        models_voice: '音色',
        models_configured: '已配置',
        models_not_configured: '未配置',
        models_pick_to_configure: '选择以配置',
        models_clear_credential: '清除凭据',
        models_base_default_hint: '留空将使用官方默认地址',
        models_catalog: '模型列表',
        models_catalog_advanced: '（高级 · 可选）',
        models_tag_text: '文本模型',
        models_catalog_add: '添加模型',
        models_catalog_window: '上下文窗口',
        models_catalog_output: '最大输出',
        models_catalog_no_budget: '该模型类型不区分上下文窗口与最大输出',
        models_catalog_custom_hint: '为自定义厂商添加模型列表，配置后可在对话页面下拉选择对应模型，留空则需要手动输入模型名称',
        models_catalog_name_ph: '模型名称',
        models_catalog_reset: '恢复默认',
        models_tag_chat: '主模型',
        models_tag_vision: '图像理解',
        models_tag_video: '视频理解',
        models_tag_image: '图像生成',
        models_tag_embedding: '向量',
        models_tag_asr: '语音识别',
        models_tag_tts: '语音合成',
        models_base_default: '默认',
        models_custom_vendor_label: '自定义',
        models_custom_name: '名称',
        models_custom_delete: '删除',
        models_custom_delete_confirm_title: '删除自定义厂商',
        models_custom_delete_confirm_msg: '确定删除该自定义厂商吗？此操作无法撤销。',
        models_custom_name_required: '请填写名称',
        models_custom_base_required: '请填写 API Base',
        models_custom_edit_title: '编辑自定义厂商',
        models_custom_add_title: '添加自定义厂商',
        models_capability_chat: '主模型',
        models_capability_chat_desc: '用于基础对话和 Agent 推理',
        models_capability_chat_fallback: '主模型兜底',
        models_capability_chat_fallback_desc: '仅在主模型彻底失败（重试耗尽）后接管',
        models_fallback_enable: '启用兜底模型',
        models_fallback_config: '兜底模型',
        models_fallback_config_tip: '配置主模型兜底：主模型彻底失败后接管',
        models_fallback_modal_title: '主模型兜底',
        models_fallback_modal_desc: '当主模型重试次数用尽仍然失败时，按顺序尝试兜底链上的下一个模型，直到某个成功或全部失败',
        models_fallback_badge_on: '兜底已启用',
        models_fallback_chain_title: '兜底链（按顺序尝试）',
        models_fallback_chain_desc: '第 1 个失败就试第 2 个，依次推进；链越长，一轮可用的备选越多',
        models_fallback_chain_add: '添加兜底模型',
        models_fallback_chain_empty: '还没有兜底模型，点下方按钮添加一个',
        models_fallback_chain_link: '兜底 {{n}}',
        models_fallback_chain_move_up: '上移',
        models_fallback_chain_move_down: '下移',
        models_fallback_chain_remove: '移除',
        models_fallback_chain_incomplete: '启用兜底至少需要一条完整的「厂商 + 模型」',
        models_capability_vision: '图像理解',
        models_capability_vision_desc: '识别图片内容，用于图像识别工具',
        models_capability_image: '图像生成',
        models_capability_image_desc: '生成图片，用于图像生成技能',
        models_auto_using: '当前优先使用',
        models_capability_asr: '语音识别',
        models_capability_asr_desc: '语音转文字',
        models_capability_tts: '语音合成',
        models_capability_tts_desc: '文字转语音',
        models_capability_embedding: '向量',
        models_capability_embedding_desc: '用于记忆与知识的向量化检索',
        models_capability_search: '联网搜索',
        models_capability_search_desc: '实时网页检索能力，用于搜索工具',
        models_strategy_auto: '自动',
        models_search_strategy_label: '策略',
        models_search_strategy_fixed: '指定',
        models_search_strategy_auto_hint: '从已配置厂商中自动选择',
        models_search_strategy_fixed_hint: '指定使用搜索厂商',
        models_pending_config: '待配置',
        models_search_available_label: '可用搜索厂商：',
        models_search_none_configured: '暂未启用任何搜索厂商，点击添加',
        models_search_add_provider: '添加厂商',
        models_search_add_desc: '选择一个搜索厂商进行配置',
        models_search_bocha_title: '配置博查 API Key',
        models_search_bocha_desc: '前往博查开放平台创建 API Key',
        models_search_anysearch_title: '配置 AnySearch API Key',
        models_search_anysearch_desc: '前往 anysearch.com 控制台创建 API Key。',
        models_search_serply_title: '配置 Serply API Key',
        models_search_serply_desc: '前往 serply.io 控制台创建 API Key。',
        models_search_tavily_title: '配置 Tavily API Key',
        models_search_tavily_desc: '前往 tavily.com 控制台创建 API Key。',
        models_search_searxng_title: '配置 SearXNG 实例 URL',
        models_search_searxng_desc: '输入自托管 SearXNG 实例的 URL（无需 API Key）。',
        models_search_anysearch_anon_hint: '留空可启用匿名模式（无需 API Key）',
        models_search_anonymous_badge: '匿名',
        models_search_anonymous_disable: '停用匿名',
        models_search_keenable_title: '配置 Keenable API Key（可选）',
        models_search_keenable_desc: '留空保存启用匿名模式；填入密钥可提升频率上限，前往 keenable.ai 获取。',
        models_search_keenable_anon_hint: '',
        models_search_edit_hint: '点击修改配置',
        models_unavailable: '不可用',
        models_set_via_env: '通过环境变量启用',
        models_dim_label: '维度',
        models_save_success: '已保存',
        models_save_failed: '保存失败',
        models_cleared: '已清除',
        models_clear_failed: '清除失败',
        models_embedding_change_title: '更改向量模型',
        models_embedding_change_msg: '切换向量模型后，已有索引将失效，需要重建。是否继续？',
        models_embedding_saved_title: '向量模型已更新',
        models_embedding_saved_msg: '请在聊天框输入 /memory rebuild-index 重建索引。',
        models_embedding_saved_ok: '去执行',
        models_pick_provider: '待选择',
        models_manage_api_key: '管理 API Key',
        models_clear_confirm_title: '清除厂商凭据',
        models_clear_confirm_msg: '确认清除该厂商的 API Key 与 Base URL 吗？相关能力将不再可用。',
        cancel: '取消',
        save: '保存',
        ok: '确定',
        knowledge_title: '知识库', knowledge_desc: '浏览和探索你的知识库',
        knowledge_tab_docs: '文档', knowledge_tab_graph: '图谱',
        knowledge_loading: '加载知识库中...', knowledge_loading_desc: '知识页面将显示在这里',
        knowledge_select_hint: '选择一个文档查看', knowledge_empty_hint: '暂无知识页面',
        knowledge_empty_guide: '在对话中发送文档、链接或主题给 Agent，它会自动整理到你的知识库中。',
        knowledge_go_chat: '开始对话',
        knowledge_new: '新建',
        knowledge_new_category: '新建分类',
        knowledge_new_document: '新建文档',
        knowledge_import_documents: '导入文档',
        welcome_subtitle: '我可以帮你解答问题、管理计算机、创造和执行技能，并通过<br>长期记忆和知识库不断成长',
        example_sys_title: '系统管理', example_sys_text: '查看工作空间里有哪些文件',
        example_task_title: '定时任务', example_task_text: '1分钟后提醒我检查服务器',
        example_code_title: '编程助手', example_code_text: '搜索AI资讯并生成可视化网页报告',
        example_knowledge_title: '知识库', example_knowledge_text: '查看知识库当前文档情况',
        example_skill_title: '技能系统', example_skill_text: '查看所有支持的工具和技能',
        example_web_title: '指令中心', example_web_text: '查看全部命令',
        slash_help: '显示命令帮助',
        slash_status: '查看运行状态',
        slash_context: '查看对话上下文',
        slash_context_clear: '清除对话上下文',
        slash_compact: '压缩较早的对话以释放上下文',
        slash_skill_list: '查看已安装技能',
        slash_skill_list_remote: '浏览技能广场',
        slash_skill_search: '搜索技能',
        slash_skill_install: '安装技能 (名称或 GitHub URL)',
        slash_skill_uninstall: '卸载技能',
        slash_skill_info: '查看技能详情',
        slash_skill_enable: '启用技能',
        slash_skill_disable: '禁用技能',
        slash_memory_dream: '手动触发记忆蒸馏 (可指定天数, 默认3)',
        slash_knowledge: '查看知识库统计',
        slash_knowledge_list: '查看知识库文件树',
        slash_knowledge_on: '开启知识库',
        slash_knowledge_off: '关闭知识库',
        slash_config: '查看当前配置',
        slash_cancel: '中止当前正在运行的 Agent 任务',
        slash_steer: '向当前正在运行的 Agent 任务注入引导指令',
        steer_active: '引导当前任务',
        slash_logs: '查看最近日志',
        slash_version: '查看版本',
        input_placeholder: '输入消息，/ 使用指令，@ 引用文件',
        input_placeholder_team: '输入消息，/ 使用指令，@ 引用智能体或文件',
        config_title: '配置管理', config_desc: '管理模型和 Agent 配置',
        config_model: '模型配置', config_agent: 'Agent 配置',
        config_language: '语言', config_language_hint: '界面展示、命令文案、系统提示词等使用的语言（与右上角切换同步）',
        config_system: '系统',
        config_task_notify: '任务通知', config_task_notify_hint: '窗口在后台且任务完成或失败时发送浏览器通知，点击可跳转会话',
        config_task_notify_sound: '通知声音', config_task_notify_sound_hint: '通知开启时可单独关闭提示音',
        config_task_notify_blocked: '系统通知已被浏览器屏蔽，请点击地址栏左侧图标 → 通知 → 允许后刷新页面',
        notify_task_done: '任务完成',
        notify_task_error: '任务失败',
        config_model_advanced: '高级配置',
        config_channel: '通道配置',
        config_agent_enabled: 'Agent 模式',
        config_max_tokens: '最大上下文 Token', config_max_tokens_hint: '上下文输入预算上限，达到后会压缩历史以控制成本；仍不会超过当前模型窗口。填 0 表示不限制、跟随模型窗口',
        config_max_turns: '最大记忆轮次', config_max_turns_hint: '一问一答为一轮，超过后会智能压缩处理',
        config_max_steps: '最大执行步数', config_max_steps_hint: '单次对话中 Agent 最多调用工具的次数',
        config_enable_thinking: '深度思考', config_enable_thinking_hint: '是否启用深度思考模式',
        config_reasoning_effort: '思考强度', config_reasoning_effort_hint: '按当前模型厂商支持的原生枚举发送',
        config_subagent: '子 Agent', config_subagent_hint: '把可独立完成的任务交给子 Agent，多个任务并行执行，只把结论带回主对话',
        config_self_evolution: '自主进化', config_self_evolution_hint: '会话空闲后自动复盘，沉淀记忆、优化技能、处理未完成事项',
        evolution_badge: '自主学习',
        config_channel_type: '通道类型',
        config_provider: '模型厂商', config_model_name: '模型',
        config_custom_model_hint: '输入自定义模型名称',
        config_save: '保存', config_saved: '已保存',
        config_save_error: '保存失败',
        config_custom_option: '自定义',
        config_custom_tip: '接口需遵循 OpenAI API 协议',
        config_security: '安全设置', config_password: '访问密码',
        config_password_hint: '留空则不启用密码保护',
        config_permission: '默认权限',
        config_permission_hint: '新会话的默认权限范围，决定 Agent 能修改哪些文件、能执行哪些命令',
        config_permission_desc: '新会话默认使用该权限；单个会话可在输入框下方单独调整',
        config_password_changed: '密码已更新',
        config_password_cleared: '密码已清除',
        config_password_security_warning: '⚠️ 警告：目前密码为空且对外连接埠开放，建议重启服务，或检查是否调整监听位址绑定。',
        skills_title: '技能管理', skills_desc: '查看、启用或禁用 Agent 工具和技能', skills_hub_btn: '探索技能广场',
        skills_loading: '加载技能中...', skills_loading_desc: '技能加载后将显示在此处',
        tools_section_title: '内置工具', tools_loading: '加载工具中...',
        skills_section_title: '技能', skill_enable: '启用', skill_disable: '禁用',
        skill_toggle_error: '操作失败，请稍后再试',
        skill_open_hint: '点击查看技能内容',
        skill_edit_hint: '编辑技能',
        skill_back: '返回列表',
        skill_load_failed: '读取技能内容失败',
        skill_builtin_readonly: '内置技能不可编辑（重启会覆盖）',
        mcp_section_title: 'MCP 服务器', mcp_section_hint: '添加、编辑或停用 MCP 服务器。保存后下一条消息生效，无需重启进程。',
        mcp_add: '添加服务器', mcp_edit: '编辑服务器', mcp_empty: '尚未配置 MCP 服务器',
        mcp_test: '测试连接', mcp_save: '保存', mcp_cancel: '取消', mcp_delete: '删除',
        mcp_status_ready: '就绪', mcp_status_pending: '加载中', mcp_status_failed: '失败',
        mcp_status_needs_auth: '待授权', mcp_status_disabled: '已停用', mcp_status_idle: '未加载',
        mcp_field_name: '名称', mcp_field_type: '传输方式', mcp_field_command: '命令',
        mcp_field_args: '参数（每行一个）', mcp_field_env: '环境变量（每行 KEY=value）',
        mcp_field_url: 'URL', mcp_field_headers: '请求头（每行 KEY=value）', mcp_field_scope: 'OAuth scope',
        mcp_field_prefix: '工具名前缀', mcp_field_timeout: '超时（秒）', mcp_field_disabled: '停用此服务器',
        mcp_test_ok: '连接成功', mcp_test_fail: '连接失败', mcp_save_error: '保存失败',
        mcp_delete_confirm: '确定删除这个 MCP 服务器吗？', mcp_apply_hint: '将在下一条消息生效',
        skill_install_btn: '安装', skill_install_placeholder: 'Skill Hub 名称或 GitHub URL',
        skill_install_error: '安装失败', skill_delete: '卸载',
        skill_delete_confirm: '确定卸载这个技能吗？', skill_delete_error: '卸载失败',
        memory_title: '记忆管理', memory_desc: '查看 Agent 记忆文件和内容',
        memory_tab_files: '记忆文件', memory_tab_dreams: '自主进化',
        memory_loading: '加载记忆文件中...', memory_loading_desc: '记忆文件将显示在此处',
        memory_back: '返回列表',
        memory_col_name: '文件名', memory_col_type: '类型', memory_col_size: '大小', memory_col_updated: '更新时间',
        channels_title: '通道管理', channels_desc: '管理已接入的消息通道',
        channels_add: '接入通道', channels_disconnect: '断开',
        channels_save: '保存配置', channels_saved: '已保存', channels_save_error: '保存失败',
        channels_restarted: '已保存并重启',
        channels_connect_btn: '接入', channels_cancel: '取消',
        channel_rename: '重命名通道',
        channels_select_placeholder: '选择要接入的通道...',
        channels_empty: '暂未接入任何通道', channels_empty_desc: '点击右上角「接入通道」按钮开始配置',
        channels_disconnect_confirm: '通道将停止接入，是否确认断开？',
        channels_disconnect_error: '断开失败',
        channels_connected: '已接入', channels_connecting: '接入中...',
        weixin_scan_title: '微信扫码登录', weixin_scan_desc: '请使用微信扫描下方二维码',
        weixin_scan_loading: '正在获取二维码...', weixin_scan_waiting: '等待扫码...',
        weixin_scan_scanned: '已扫码，请在手机上确认', weixin_scan_expired: '二维码已过期，正在刷新...',
        weixin_scan_success: '登录成功，正在启动通道...', weixin_scan_fail: '获取二维码失败',
        weixin_qr_tip: '二维码约2分钟后过期',
        wecom_scan_btn: '扫码创建企微机器人', wecom_scan_desc: '使用企业微信扫码，一键创建智能机器人',
        wecom_scan_success: '创建成功，正在启动通道...',
        wecom_scan_fail: '创建失败',
        wecom_mode_scan: '扫码接入', wecom_mode_manual: '手动填写',
        feishu_scan_btn: '一键创建飞书应用',
        feishu_scan_desc: '使用飞书 App 扫码，自动创建应用并预置全部权限与事件订阅',
        feishu_scan_replace_desc: '使用飞书 App 扫码创建新机器人，将覆盖当前的 App ID / Secret',
        feishu_scan_loading: '正在向飞书申请二维码...',
        feishu_scan_waiting: '等待扫码...',
        feishu_scan_tip: '二维码 10 分钟内有效，仅供一次扫描',
        feishu_scan_open_link: '或点击此处在浏览器中打开',
        feishu_scan_success: '应用创建成功，正在启动通道...',
        feishu_scan_expired: '二维码已过期，请重试',
        feishu_scan_denied: '已取消授权',
        feishu_scan_fail: '创建失败',
        feishu_scan_retry: '重试',
        feishu_sdk_downloading: '正在下载飞书组件...',
        feishu_sdk_downloading_tip: '首次启用需要下载，约 1MB，稍后自动继续',
        feishu_mode_scan: '扫码创建', feishu_mode_manual: '手动填写',
        tasks_title: '定时任务', tasks_desc: '查看和管理定时任务',
        tasks_coming: '即将推出', tasks_coming_desc: '定时任务管理功能即将在此提供',
        tasks_tab_tasks: '任务', tasks_tab_records: '执行记录',
        records_desc: '查看定时任务的执行历史',
        records_loading: '加载执行记录中...', records_empty: '暂无执行记录',
        records_empty_guide: '任务执行后，成功与失败的记录都会显示在这里',
        records_status_done: '成功', records_status_error: '失败', records_status_running: '执行中',
        records_trigger_scheduled: '定时触发', records_trigger_manual: '手动执行',
        records_duration: '耗时', records_no_output: '（无内容）',
        records_load_more: '加载更多', records_delete: '删除',
        records_delete_confirm_title: '删除执行记录', records_delete_confirm_msg: '确定删除这条执行记录吗？此操作不可恢复。',
        records_delete_failed: '删除失败，请重试',
        record_detail_title: '执行详情', record_detail_loading: '加载详情中...',
        record_detail_status: '状态', record_detail_trigger: '触发方式',
        record_detail_started: '开始时间', record_detail_duration: '耗时',
        record_detail_channel_type: '通道类型', record_detail_channel_name: '通道名称',
        record_detail_agent: '智能体', record_detail_output: '发送内容',
        record_detail_view_preview: '预览', record_detail_view_text: '文本',
        record_detail_error: '错误信息',
        record_channel_web_type: 'web', record_channel_web_name: '网页',
        task_add_btn: '新增任务',
        task_edit_title: '编辑定时任务',
        task_add_title: '新增定时任务',
        task_name: '任务名称',
        task_enabled: '启用任务',
        task_schedule_type: '调度类型',
        task_schedule_cron: 'Cron 表达式',
        task_schedule_interval: '固定间隔',
        task_schedule_once: '一次性任务',
        task_cron_expression: 'Cron 表达式',
        task_cron_hint: '格式: 分 时 日 月 周，例如 "0 9 * * *" 表示每天 9:00',
        task_interval_seconds: '间隔秒数',
        task_interval_hint: '最小 60 秒，例如 3600 表示每小时执行一次',
        task_once_time: '执行时间',
        task_action_type: '任务类型',
        task_action_send_message: '固定消息',
        task_action_agent_task: 'AI 任务',
        task_channel_type: '通道类型',
        task_channel_hint: '选择定时消息发送的通道',
        task_message_content: '消息内容',
        task_fixed_content: '固定内容',
        task_task_description: '任务描述',
        task_delete_btn: '删除任务',
        task_delete_confirm_title: '删除定时任务',
        task_delete_confirm_msg: '确定删除该定时任务吗？此操作无法撤销。',
        task_run_now: '立即执行',
        task_run_confirm_title: '立即执行任务',
        task_run_confirm_msg: '该任务会立即向已配置的通道和接收者发送内容。是否继续？',
        task_run_started: '已开始执行',
        task_run_failed: '执行失败',
        task_add_title: '新增定时任务',
        task_add_btn: '新增任务',
        task_recipient: '接收人',
        task_recipient_hint: '先选择通道，再选择该通道下已联系过的联系人，任务将主动推送给 TA',
        task_recipient_select: '选择接收人',
        task_recipient_empty: '暂无可选接收人。对方需先通过通道（飞书/企业微信等）联系过智能体。',
        task_recipient_group: '群聊',
        task_recipient_user: '用户',
        task_recipient_required: '请先选择接收人',
        task_recipient_placeholder: '请选择接收人',
        task_recipient_refresh: '刷新接收人列表',
        task_recipient_pick_instance_first: '请先选择通道',
        task_recipient_empty_hint: '该通道下暂无接收人，请先在这个通道向智能体发送一条消息',
        task_instance: '通道',
        task_instance_tip: '选择通道后，可指定该通道下已对话过的联系人，将任务结果推送给 TA',
        task_instance_placeholder: '请选择通道',
        task_instance_empty: '暂无可用通道',
        task_instance_no_recipient: '暂无接收人',
        task_instance_required: '请先选择通道',
        logs_title: '日志', logs_desc: '实时日志输出 (run.log)',
        logs_live: '实时', logs_coming_msg: '日志流即将在此提供。将连接 run.log 实现类似 tail -f 的实时输出。',
        new_chat: '新对话',
        new_team_chat: '多智能体对话',
        new_team_chat_hint: '选择参与本次对话的智能体，第一个为会话的主智能体。',
        new_team_chat_owner: '主智能体',
        new_team_chat_start: '开始对话',
        new_team_chat_min: '至少选择两个智能体',
        session_history: '历史会话',
        ws_toggle: '工作空间', ws_tab_preview: '预览', ws_tab_files: '文件',
        ws_default_workspace: '默认空间', ws_sel_title: '选择工作空间',
        ws_sel_default_hint: '使用默认工作空间（~/cow）', ws_sel_recents: '最近使用',
        ws_sel_open: '打开项目…', ws_sel_new: '新建项目', ws_sel_new_placeholder: '项目名称',
        ws_sel_create: '创建', ws_sel_up: '上一级',
        ws_sel_new_subtitle: '将在 {root} 下创建新项目目录', ws_sel_new_hint: '仅填写项目名称，不含路径分隔符',
        ws_sel_name_required: '请输入项目名称', ws_sel_name_no_slash: '项目名称不能包含 / 或 \\',
        ws_sel_open_here: '打开此目录', ws_sel_dblclick_hint: '双击进入子目录，单击选中',
        ws_sel_no_subdirs: '此目录下没有子文件夹', ws_sel_drives: '此电脑',
        ws_open_external: '在新标签页打开', ws_download: '下载', ws_copy_path: '复制路径',
        ws_close: '关闭', ws_refresh: '刷新', ws_preview: '预览',
        ws_search_placeholder: '搜索文件',
        ws_preview_empty: '选择一个文件进行预览',
        ws_preview_failed: '预览失败',
        ws_link_not_found: '工作空间中找不到该文件',
        ws_no_inline_preview: '该类型不支持内嵌预览',
        ws_empty_dir: '空目录', ws_no_results: '没有匹配的文件',
        ws_truncated: '文件过多，仅显示部分',
        ws_edit: '编辑', ws_edit_save: '保存 (Ctrl+S)', ws_edit_cancel: '退出编辑',
        ws_edit_saved: '已保存',
        ws_edit_load_failed: '打开编辑器失败',
        ws_edit_save_failed: '保存失败',
        ws_edit_too_large: '文件过大，无法在面板中编辑',
        ws_edit_unsupported: '该类型不支持编辑',
        ws_edit_encoding: '该文件不是 UTF-8 编码，编辑会损坏内容',
        ws_edit_conflict_title: '文件已被改动',
        ws_edit_conflict_msg: '这个文件在你编辑期间被改动过（可能是 Agent 写入的）。覆盖保存会丢弃磁盘上的新内容。',
        ws_edit_overwrite: '覆盖保存',
        ws_edit_discard_title: '放弃未保存的修改？',
        ws_edit_discard_msg: '当前文件有未保存的修改，继续操作会丢失这些内容。',
        ws_edit_discard_ok: '放弃修改',
        today: '今天', yesterday: '昨天', earlier: '更早',
        session_pinned_group: '置顶',
        pin_session: '置顶',
        unpin_session: '取消置顶',
        project_rename: '重命名项目',
        project_delete: '删除项目',
        project_rename_title: '重命名项目',
        project_delete_title: '删除项目',
        project_delete_confirm: '确认删除项目「{name}」？仅移除项目记录，磁盘上的文件不会被删除，其下会话将回到默认空间。',
        perm_menu_title: '本次会话权限',
        perm_read_only: '只读',
        perm_workspace_write: '工作区可写',
        perm_full_access: '全部可访问',
        perm_read_only_desc: '只能查看和分析，不修改任何文件',
        perm_workspace_write_desc: '在当前工作空间内自由读写，空间之外的写入会被拒绝',
        perm_full_access_desc: '不加限制，可修改任意位置（当前默认）',
        perm_follow_global: '跟随全局设置',
        perm_tip: '权限：{name}',
        perm_denied_hint: '当前权限为「{name}」，此操作被拒绝。',
        perm_denied_action: '调整权限',
        model_menu_title: '本次会话模型',
        model_follow_global: '跟随全局设置',
        model_follow_agent: '跟随智能体默认模型',
        model_tip: '模型：{name}',
        model_unset: '未配置',
        session_settings_failed: '设置失败，请重试',
        delete_session_confirm: '确认删除该会话？所有消息将被清除。',
        delete_session_title: '删除会话',
        rename_session: '重命名',
        delete_message_confirm: '确认删除这条消息？',
        delete_message_title: '删除消息',
        edit_disabled_reply_active: '正在生成回复，暂时无法编辑。',
        delete_disabled_reply_active: '正在生成回复，暂时无法删除。',
        untitled_session: '新对话',
        context_cleared: '— 以上内容已从上下文中移除 —',
        tip_new_chat: '新建对话',
        tip_clear_context: '清除上下文',
        ctx_usage_title: '上下文用量',
        ctx_system: '系统提示词',
        ctx_tools: '工具和技能',
        ctx_history: '对话历史',
        ctx_free: '剩余可用',
        ctx_used_of: '已用 {used} / {limit}',
        ctx_estimated: '估算值',
        ctx_empty: '当前对话暂无上下文',
        ctx_error: '无法获取上下文用量',
        ctx_act_compact: '压缩', ctx_act_compact_tip: '总结较早的对话以释放上下文',
        ctx_act_clear: '清除', ctx_act_clear_tip: '清除当前对话上下文',
        ctx_act_adjust: '配置', ctx_act_adjust_tip: '调整最大上下文 Token',
        ctx_compacting: '正在压缩上下文…',
        ctx_compact_failed: '压缩失败，请稍后重试',
        ctx_compact_noop: '当前上下文较短，无需压缩',
        ctx_compacted_divider: '上下文已压缩（{before} → {after} 条）',
        ctx_busy_turn: '正在生成回复，请等回复结束后再操作',
        tip_attach: '添加附件',
        tip_cancel: '中止',
        tip_cancelled: '已中止',
        attach_menu_file: '上传文件',
        mic_idle_title: '点击录音 / 再按一次结束',
        mic_recording_title: '录音中，再次点击结束',
        mic_busy_title: '识别中…',
        mic_permission_denied: '无法访问麦克风，请检查浏览器权限',
        mic_too_short: '录音太短，请重试',
        mic_error: '语音识别失败',
        optimize_idle_title: '智能优化输入',
        optimize_busy_title: '优化中…',
        optimize_error: '指令优化失败',
        optimize_empty: '输入为空，无法优化',
        speak_msg: '朗读这段回复',
        voice_reply_mode_label: '语音回复策略',
        voice_reply_off: '关闭',
        voice_reply_if_voice: '仅语音问/语音答',
        voice_reply_always: '总是语音回复',
        attach_menu_folder: '上传文件夹',
        confirm_yes: '确认',
        confirm_cancel: '取消',
        error_send: '发送失败，请稍后再试。', error_timeout: '请求超时，请再试一次。',
        thinking_in_progress: '思考中...', thinking_done: '已深度思考', thinking_duration: '耗时',
        edit_message: '编辑消息',
        regenerate_response: '重新生成',
        edit_save: '保存并发送',
        edit_cancel: '取消',
        logout: '退出',
        update_check: '检查更新',
        update_checking: '正在检查…',
        update_up_to_date: '已是最新版本',
        update_now: '立即更新',
        update_changelog: '版本说明',
        update_error: '检查更新失败',
        update_unsupported: '此安装方式不支持一键更新',
        update_confirm: '将拉取最新代码并重启服务。确认继续？',
        update_starting: '正在开始更新…',
        update_in_progress: '正在更新…',
        update_reconnect: '服务重启中，正在重新连接…',
        update_done: '更新完成',
        update_failed: '更新失败',
        update_step_git_pull: '拉取最新代码',
        update_step_install_deps: '安装依赖',
        update_step_install_cli: '重装 CLI',
        update_step_self_check: '检查新代码',
        update_step_restart: '重启服务',
        update_step_starting: '准备更新',
        update_step_done: '完成',
    },
    'zh-Hant': {

        console: '控制台',
        nav_chat: '對話', nav_manage: '管理', nav_monitor: '監控',
        menu_chat: '對話', menu_agents: '智慧體', menu_config: '設定', menu_skills: '技能',
        agents_page_title: '智慧體團隊', agents_page_desc: '管理團隊中的智慧體成員',
        agents_create: '建立智慧體',
        agents_name_placeholder: '智慧體名稱',
        agents_name_required: '請填寫名稱',
        agents_stale: '列表已更新，請重新整理後再試',
        agents_id_placeholder: '留空則自動產生',
        agents_id_tip: '智慧體的唯一識別碼，建立後不可修改。僅支援小寫英文、數字與連字號（-），如 coding-agent。留空則依名稱自動產生。',
        agents_id_invalid: 'ID 需以字母或數字開頭，僅支援字母、數字、底線與連字號，最長 64 位',
        agents_avatar: '頭像',
        agents_tab_profile: '概況',
        agents_tab_skills: '能力',
        agents_tab_files: '核心檔案',
        agents_core_edit: '編輯',
        agents_core_preview: '預覽',
        agents_core_file_agent: '智慧體設定',
        agents_core_file_user: '使用者資訊',
        agents_core_file_rule: '工作空間規則',
        agents_core_file_memory: '長期記憶',
        agents_default: '預設',
        agents_archived: '已封存',
        agents_chat: '開始對話',
        agents_delete: '刪除',
        agents_delete_title: '刪除智慧體',
        agents_delete_confirm: '確定刪除智慧體「{name}」嗎？其工作空間與會話將一併移除，且無法復原。',
        agents_pick_hint: '選擇智慧體',
        agents_clone_label: '從已有智慧體複製',
        agents_clone_hint: '複製其設定、技能與知識作為起點',
        agents_avatar_upload: '上傳圖片',
        agents_clone_none: '空白',
        agents_clone_from: '{name}',
        agents_name: '名稱',
        agents_saved: '已儲存',
        agents_save_failed: '儲存失敗',
        agents_no_desc: '暫無職責',
        agents_description: '職責',
        agents_description_placeholder: '該智慧體負責哪些工作、在什麼場景被使用',
        agents_description_hint: '用於多智慧體協作時的任務分配',
        agents_model: '預設模型',
        agents_model_follows_global: '跟隨全域設定',
        agents_model_default_hint: '預設使用主模型，於「模型設定」中修改。',
        agents_skills_all: '使用全部已安裝技能',
        agents_skills_pick: '只啟用勾選的技能',
        agents_knowledge: '知識庫',
        agents_knowledge_shared: '共享',
        agents_knowledge_own: '獨立',
        agents_knowledge_hint: '共享：與團隊讀寫同一個知識庫\n獨立：擁有專屬知識庫，互不影響',
        agents_knowledge_working: '處理中…',
        agents_knowledge_failed: '切換失敗',
        agents_empty: '還沒有智慧體。建立一個，開始組團隊。',
        agents_select_hint: '從左側選擇一個智能體進行設定',
        agents_pick_tip: '切換當前智能體',
        composer_current_agent: '當前智能體',
        team_members: '當前會話成員',
        team_invite: '新增到會話',
        team_remove: '移出這個會話',
        composer_agent_owner: '主智能體',
        channel_bound_agent: '綁定智慧體',
        channel_bound_default: '預設',
        channel_bound_agent_hint: '第一個為預設智慧體，負責接收訊息並可委派給其他成員',
        channel_team_none: '未選擇',
        channel_team_no_candidates: '暫無可選的智慧體',
        settings_tab_basic: '基礎設定',
        settings_tab_models: '模型設定',
        knowledge_shared_hint: '知識庫預設全員共享，在側欄「知識」查看和編輯。',
        menu_memory: '記憶', menu_knowledge: '知識', menu_channels: '管道', menu_tasks: '定時',
        menu_logs: '日誌',
        models_title: '模型管理',
        models_desc: '統一管理對話、影像、語音、向量、搜尋能力',
        models_section_vendors: '廠商憑據',
        models_section_vendors_desc: '一處設定，多個模型能力共享',
        models_section_capabilities: '模型能力',
        models_add_vendor: '新增廠商',
        models_provider: '廠商',
        models_model: '模型',
        models_voice: '音色',
        models_configured: '已設定',
        models_not_configured: '未設定',
        models_pick_to_configure: '選擇以設定',
        models_clear_credential: '清除憑據',
        models_base_default_hint: '留空將使用官方預設地址',
        models_catalog: '模型列表',
        models_catalog_advanced: '（高級 · 可選）',
        models_tag_text: '文本模型',
        models_catalog_add: '新增模型',
        models_catalog_window: '上下文窗口',
        models_catalog_output: '最大輸出',
        models_catalog_no_budget: '該模型類型不區分上下文視窗與最大輸出',
        models_catalog_custom_hint: '為自訂廠商新增模型列表，設定後可在對話頁面下拉選擇對應模型，留空則需手動輸入模型名稱',
        models_catalog_name_ph: '模型名稱',
        models_catalog_reset: '恢復預設',
        models_tag_chat: '主模型',
        models_tag_vision: '圖像理解',
        models_tag_video: '影片理解',
        models_tag_image: '圖像生成',
        models_tag_embedding: '向量',
        models_tag_asr: '語音辨識',
        models_tag_tts: '語音合成',
        models_base_default: '預設',
        models_custom_vendor_label: '自定義',
        models_custom_name: '名稱',
        models_custom_delete: '刪除',
        models_custom_delete_confirm_title: '刪除自定義廠商',
        models_custom_delete_confirm_msg: '確定刪除該自定義廠商嗎？此操作無法撤銷。',
        models_custom_name_required: '請填寫名稱',
        models_custom_base_required: '請填寫 API Base',
        models_custom_edit_title: '編輯自定義廠商',
        models_custom_add_title: '新增自定義廠商',
        models_capability_chat: '主模型',
        models_capability_chat_desc: '用於基礎對話和 Agent 推理',
        models_capability_chat_fallback: '主模型兜底',
        models_capability_chat_fallback_desc: '僅在主模型徹底失敗（重試耗盡）後接管',
        models_fallback_enable: '啟用兜底模型',
        models_fallback_config: '兜底模型',
        models_fallback_config_tip: '設定主模型兜底：主模型徹底失敗後接管',
        models_fallback_modal_title: '主模型兜底',
        models_fallback_modal_desc: '當主模型重試次數用盡仍然失敗時，依序嘗試兜底鏈上的下一個模型，直到某個成功或全部失敗',
        models_fallback_badge_on: '兜底已啟用',
        models_fallback_chain_title: '兜底鏈（依序嘗試）',
        models_fallback_chain_desc: '第 1 個失敗就試第 2 個，依序推進；鏈越長，一輪可用的備選越多',
        models_fallback_chain_add: '新增兜底模型',
        models_fallback_chain_empty: '還沒有兜底模型，點下方按鈕新增一個',
        models_fallback_chain_link: '兜底 {{n}}',
        models_fallback_chain_move_up: '上移',
        models_fallback_chain_move_down: '下移',
        models_fallback_chain_remove: '移除',
        models_fallback_chain_incomplete: '啟用兜底至少需要一條完整的「廠商 + 模型」',
        models_capability_vision: '影像理解',
        models_capability_vision_desc: '識別圖片內容，用於影像識別工具',
        models_capability_image: '影像生成',
        models_capability_image_desc: '生成圖片，用於影像生成技能',
        models_auto_using: '當前優先使用',
        models_capability_asr: '語音識別',
        models_capability_asr_desc: '語音轉文字',
        models_capability_tts: '語音合成',
        models_capability_tts_desc: '文字轉語音',
        models_capability_embedding: '向量',
        models_capability_embedding_desc: '用於記憶與知識的向量化檢索',
        models_capability_search: '聯網搜尋',
        models_capability_search_desc: '實時網頁檢索能力，用於搜尋工具',
        models_strategy_auto: '自動',
        models_search_strategy_label: '策略',
        models_search_strategy_fixed: '指定',
        models_search_strategy_auto_hint: '從已設定廠商中自動選擇',
        models_search_strategy_fixed_hint: '指定使用搜尋廠商',
        models_pending_config: '待設定',
        models_search_available_label: '可用搜尋廠商：',
        models_search_none_configured: '暫未啟用任何搜尋廠商，點選新增',
        models_search_add_provider: '新增廠商',
        models_search_add_desc: '選擇一個搜尋廠商進行設定',
        models_search_bocha_title: '設定博查 API Key',
        models_search_bocha_desc: '前往博查開放平臺建立 API Key',
        models_search_anysearch_title: '設定 AnySearch API Key',
        models_search_anysearch_desc: '前往 anysearch.com 控制台建立 API Key',
        models_search_serply_title: '設定 Serply API Key',
        models_search_serply_desc: '前往 serply.io 控制台建立 API Key',
        models_search_tavily_title: '設定 Tavily API Key',
        models_search_tavily_desc: '前往 tavily.com 控制台建立 API Key',
        models_search_searxng_title: '設定 SearXNG 實例 URL',
        models_search_searxng_desc: '輸入自託管 SearXNG 實例的 URL（無需 API Key）。',
        models_search_anysearch_anon_hint: '留空可啟用匿名模式（無需 API Key）',
        models_search_anonymous_badge: '匿名',
        models_search_anonymous_disable: '停用匿名',
        models_search_keenable_title: '設定 Keenable API Key（選填）',
        models_search_keenable_desc: '留空儲存啟用匿名模式；填入金鑰可提高頻率上限，前往 keenable.ai 取得。',
        models_search_keenable_anon_hint: '',
        models_search_edit_hint: '點選修改設定',
        models_unavailable: '不可用',
        models_set_via_env: '透過環境變數啟用',
        models_dim_label: '維度',
        models_save_success: '已儲存',
        models_save_failed: '儲存失敗',
        models_cleared: '已清除',
        models_clear_failed: '清除失敗',
        models_embedding_change_title: '更改向量模型',
        models_embedding_change_msg: '切換向量模型後，已有索引將失效，需要重建。是否繼續？',
        models_embedding_saved_title: '向量模型已更新',
        models_embedding_saved_msg: '請在聊天框輸入 /memory rebuild-index 重建索引。',
        models_embedding_saved_ok: '去執行',
        models_pick_provider: '待選擇',
        models_manage_api_key: '管理 API Key',
        models_clear_confirm_title: '清除廠商憑據',
        models_clear_confirm_msg: '確認清除該廠商的 API Key 與 Base URL 嗎？相關能力將不再可用。',
        cancel: '取消',
        save: '儲存',
        ok: '確定',
        knowledge_title: '知識庫', knowledge_desc: '瀏覽和探索你的知識庫',
        knowledge_tab_docs: '檔案', knowledge_tab_graph: '圖譜',
        knowledge_loading: '載入知識庫中...', knowledge_loading_desc: '知識頁面將顯示在這裡',
        knowledge_select_hint: '選擇一個檔案檢視', knowledge_empty_hint: '暫無知識頁面',
        knowledge_empty_guide: '在對話中傳送檔案、連結或主題給 Agent，它會自動整理到你的知識庫中。',
        knowledge_go_chat: '開始對話',
        knowledge_new: '新建',
        knowledge_new_category: '新建分類',
        knowledge_new_document: '新建檔案',
        knowledge_import_documents: '匯入檔案',
        welcome_subtitle: '我可以幫你解答問題、管理電腦、創造和執行技能，並透過<br>長期記憶和知識庫不斷成長',
        example_sys_title: '系統管理', example_sys_text: '檢視工作空間裡有哪些檔案',
        example_task_title: '定時任務', example_task_text: '1分鐘後提醒我檢查伺服器',
        example_code_title: '程式設計助手', example_code_text: '搜尋AI資訊並生成視覺化網頁報告',
        example_knowledge_title: '知識庫', example_knowledge_text: '檢視知識庫當前檔案情況',
        example_skill_title: '技能系統', example_skill_text: '檢視所有支援的工具和技能',
        example_web_title: '指令中心', example_web_text: '檢視全部命令',
        slash_help: '顯示命令幫助',
        slash_status: '檢視執行狀態',
        slash_context: '檢視對話上下文',
        slash_context_clear: '清除對話上下文',
        slash_compact: '壓縮較早的對話以釋放上下文',
        slash_skill_list: '檢視已安裝技能',
        slash_skill_list_remote: '瀏覽技能廣場',
        slash_skill_search: '搜尋技能',
        slash_skill_install: '安裝技能 (名稱或 GitHub URL)',
        slash_skill_uninstall: '解除安裝技能',
        slash_skill_info: '檢視技能詳情',
        slash_skill_enable: '啟用技能',
        slash_skill_disable: '禁用技能',
        slash_memory_dream: '手動觸發記憶蒸餾 (可指定天數, 預設3)',
        slash_knowledge: '檢視知識庫統計',
        slash_knowledge_list: '檢視知識庫檔案樹',
        slash_knowledge_on: '開啟知識庫',
        slash_knowledge_off: '關閉知識庫',
        slash_config: '檢視當前設定',
        slash_cancel: '中止當前正在執行的 Agent 任務',
        slash_steer: '向當前正在執行的 Agent 任務注入引導指令',
        steer_active: '引導當前任務',
        slash_logs: '檢視最近日誌',
        slash_version: '檢視版本',
        input_placeholder: '輸入訊息，/ 使用指令，@ 引用檔案',
        input_placeholder_team: '輸入訊息，/ 使用指令，@ 引用智慧體或檔案',
        config_title: '設定管理', config_desc: '管理模型和 Agent 設定',
        config_model: '模型設定', config_agent: 'Agent 設定',
        config_language: '語言', config_language_hint: '介面展示、命令文案、系統提示詞等使用的語言（與右上角切換同步）',
        config_system: '系統',
        config_task_notify: '任務通知', config_task_notify_hint: '視窗在背景且任務完成或失敗時發送瀏覽器通知，點擊可跳轉會話',
        config_task_notify_sound: '通知聲音', config_task_notify_sound_hint: '通知開啟時可單獨關閉提示音',
        config_task_notify_blocked: '系統通知已被瀏覽器封鎖，請點擊網址列左側圖示 → 通知 → 允許後重新整理頁面',
        notify_task_done: '任務完成',
        notify_task_error: '任務失敗',
        config_model_advanced: '高階設定',
        config_channel: '管道設定',
        config_agent_enabled: 'Agent 模式',
        config_max_tokens: '最大上下文 Token', config_max_tokens_hint: '上下文輸入預算上限，達到後會壓縮歷史以控制成本；仍不會超過當前模型視窗。填 0 表示不限制、跟隨模型視窗',
        config_max_turns: '最大記憶輪次', config_max_turns_hint: '一問一答為一輪，超過後會智慧壓縮處理',
        config_max_steps: '最大執行步數', config_max_steps_hint: '單次對話中 Agent 最多呼叫工具的次數',
        config_enable_thinking: '深度思考', config_enable_thinking_hint: '是否啟用深度思考模式',
        config_reasoning_effort: '思考強度', config_reasoning_effort_hint: '按目前模型廠商支援的原生枚舉傳送',
        config_subagent: '子 Agent', config_subagent_hint: '把可獨立完成的任務交給子 Agent，多個任務並行執行，只把結論帶回主對話',
        config_self_evolution: '自主進化', config_self_evolution_hint: '會話空閒後自動覆盤，沉澱記憶、最佳化技能、處理未完成事項',
        evolution_badge: '自主學習',
        config_channel_type: '管道型別',
        config_provider: '模型廠商', config_model_name: '模型',
        config_custom_model_hint: '輸入自定義模型名稱',
        config_save: '儲存', config_saved: '已儲存',
        config_save_error: '儲存失敗',
        config_custom_option: '自定義',
        config_custom_tip: '介面需遵循 OpenAI API 協議',
        config_security: '安全設定', config_password: '訪問密碼',
        config_password_hint: '留空則不啟用密碼保護',
        config_permission: '預設權限',
        config_permission_hint: '新會話的預設權限範圍，決定 Agent 能修改哪些檔案、能執行哪些命令',
        config_permission_desc: '新會話預設使用該權限；單個會話可在輸入框下方單獨調整',
        config_password_changed: '密碼已更新',
        config_password_cleared: '密碼已清除',
        config_password_security_warning: '⚠️ 警告：目前密碼為空且對外連接埠開放，建議重啟服務，或檢查是否調整監聽位址綁定。',
        skills_title: '技能管理', skills_desc: '檢視、啟用或禁用 Agent 工具和技能', skills_hub_btn: '探索技能廣場',
        skills_loading: '載入技能中...', skills_loading_desc: '技能載入後將顯示在此處',
        tools_section_title: '內建工具', tools_loading: '載入工具中...',
        skills_section_title: '技能', skill_enable: '啟用', skill_disable: '禁用',
        skill_toggle_error: '操作失敗，請稍後再試',
        skill_open_hint: '點擊檢視技能內容',
        skill_edit_hint: '編輯技能',
        skill_back: '返回列表',
        skill_load_failed: '讀取技能內容失敗',
        skill_builtin_readonly: '內建技能不可編輯（重啟會覆蓋）',
        mcp_section_title: 'MCP 伺服器', mcp_section_hint: '新增、編輯或停用 MCP 伺服器。儲存後下一則訊息生效，無需重啟行程。',
        mcp_add: '新增伺服器', mcp_edit: '編輯伺服器', mcp_empty: '尚未設定 MCP 伺服器',
        mcp_test: '測試連線', mcp_save: '儲存', mcp_cancel: '取消', mcp_delete: '刪除',
        mcp_status_ready: '就緒', mcp_status_pending: '載入中', mcp_status_failed: '失敗',
        mcp_status_needs_auth: '待授權', mcp_status_disabled: '已停用', mcp_status_idle: '未載入',
        mcp_field_name: '名稱', mcp_field_type: '傳輸方式', mcp_field_command: '命令',
        mcp_field_args: '參數（每行一個）', mcp_field_env: '環境變數（每行 KEY=value）',
        mcp_field_url: 'URL', mcp_field_headers: '請求頭（每行 KEY=value）', mcp_field_scope: 'OAuth scope',
        mcp_field_prefix: '工具名前綴', mcp_field_timeout: '逾時（秒）', mcp_field_disabled: '停用此伺服器',
        mcp_test_ok: '連線成功', mcp_test_fail: '連線失敗', mcp_save_error: '儲存失敗',
        mcp_delete_confirm: '確定刪除這個 MCP 伺服器嗎？', mcp_apply_hint: '將在下一則訊息生效',
        skill_install_btn: '安裝', skill_install_placeholder: 'Skill Hub 名稱或 GitHub URL',
        skill_install_error: '安裝失敗', skill_delete: '解除安裝',
        skill_delete_confirm: '確定解除安裝這個技能嗎？', skill_delete_error: '解除安裝失敗',
        memory_title: '記憶管理', memory_desc: '檢視 Agent 記憶檔案和內容',
        memory_tab_files: '記憶檔案', memory_tab_dreams: '自主進化',
        memory_loading: '載入記憶檔案中...', memory_loading_desc: '記憶檔案將顯示在此處',
        memory_back: '返回列表',
        memory_col_name: '檔名', memory_col_type: '型別', memory_col_size: '大小', memory_col_updated: '更新時間',
        channels_title: '管道管理', channels_desc: '管理已接入的訊息管道',
        channels_add: '接入管道', channels_disconnect: '斷開',
        channels_save: '儲存設定', channels_saved: '已儲存', channels_save_error: '儲存失敗',
        channels_restarted: '已儲存並重啟',
        channels_connect_btn: '接入', channels_cancel: '取消',
        channel_rename: '重新命名管道',
        channels_select_placeholder: '選擇要接入的管道...',
        channels_empty: '暫未接入任何管道', channels_empty_desc: '點選右上角「接入管道」按鈕開始設定',
        channels_disconnect_confirm: '管道將停止接入，是否確認斷開？',
        channels_disconnect_error: '斷開失敗',
        channels_connected: '已接入', channels_connecting: '接入中...',
        weixin_scan_title: '微信掃碼登入', weixin_scan_desc: '請使用微信掃描下方二維碼',
        weixin_scan_loading: '正在獲取二維碼...', weixin_scan_waiting: '等待掃碼...',
        weixin_scan_scanned: '已掃碼，請在手機上確認', weixin_scan_expired: '二維碼已過期，正在重新整理...',
        weixin_scan_success: '登入成功，正在啟動管道...', weixin_scan_fail: '獲取二維碼失敗',
        weixin_qr_tip: '二維碼約2分鐘後過期',
        wecom_scan_btn: '掃碼建立企微機器人', wecom_scan_desc: '使用企業微信掃碼，一鍵建立智慧機器人',
        wecom_scan_success: '建立成功，正在啟動管道...',
        wecom_scan_fail: '建立失敗',
        wecom_mode_scan: '掃碼接入', wecom_mode_manual: '手動填寫',
        feishu_scan_btn: '一鍵建立飛書應用',
        feishu_scan_desc: '使用飛書 App 掃碼，自動建立應用並預置全部許可權與事件訂閱',
        feishu_scan_replace_desc: '使用飛書 App 掃碼建立新機器人，將覆蓋當前的 App ID / Secret',
        feishu_scan_loading: '正在向飛書申請二維碼...',
        feishu_scan_waiting: '等待掃碼...',
        feishu_scan_tip: '二維碼 10 分鐘內有效，僅供一次掃描',
        feishu_scan_open_link: '或點選此處在瀏覽器中開啟',
        feishu_scan_success: '應用建立成功，正在啟動管道...',
        feishu_scan_expired: '二維碼已過期，請重試',
        feishu_scan_denied: '已取消授權',
        feishu_scan_fail: '建立失敗',
        feishu_scan_retry: '重試',
        feishu_sdk_downloading: '正在下載飛書元件...',
        feishu_sdk_downloading_tip: '首次啟用需要下載，約 1MB，稍後自動繼續',
        feishu_mode_scan: '掃碼建立', feishu_mode_manual: '手動填寫',
        tasks_title: '定時任務', tasks_desc: '檢視和管理定時任務',
        tasks_coming: '即將推出', tasks_coming_desc: '定時任務管理功能即將在此提供',
        tasks_tab_tasks: '任務', tasks_tab_records: '執行記錄',
        records_desc: '檢視定時任務的執行歷史',
        records_loading: '載入執行記錄中...', records_empty: '暫無執行記錄',
        records_empty_guide: '任務執行後，成功與失敗的記錄都會顯示在這裡',
        records_status_done: '成功', records_status_error: '失敗', records_status_running: '執行中',
        records_trigger_scheduled: '定時觸發', records_trigger_manual: '手動執行',
        records_duration: '耗時', records_no_output: '（無內容）',
        records_load_more: '載入更多', records_delete: '刪除',
        records_delete_confirm_title: '刪除執行記錄', records_delete_confirm_msg: '確定刪除這條執行記錄嗎？此操作不可復原。',
        records_delete_failed: '刪除失敗，請重試',
        record_detail_title: '執行詳情', record_detail_loading: '載入詳情中...',
        record_detail_status: '狀態', record_detail_trigger: '觸發方式',
        record_detail_started: '開始時間', record_detail_duration: '耗時',
        record_detail_channel_type: '通道類型', record_detail_channel_name: '通道名稱',
        record_detail_agent: '智慧體', record_detail_output: '傳送內容',
        record_detail_view_preview: '預覽', record_detail_view_text: '文字',
        record_detail_error: '錯誤訊息',
        record_channel_web_type: 'web', record_channel_web_name: '網頁',
        task_add_btn: '新增任務',
        task_edit_title: '編輯定時任務',
        task_add_title: '新增定時任務',
        task_name: '任務名稱',
        task_enabled: '啟用任務',
        task_schedule_type: '排程型別',
        task_schedule_cron: 'Cron 表示式',
        task_schedule_interval: '固定間隔',
        task_schedule_once: '一次性任務',
        task_cron_expression: 'Cron 表示式',
        task_cron_hint: '格式: 分 時 日 月 周，例如 "0 9 * * *" 表示每天 9:00',
        task_interval_seconds: '間隔秒數',
        task_interval_hint: '最小 60 秒，例如 3600 表示每小時執行一次',
        task_once_time: '執行時間',
        task_action_type: '任務型別',
        task_action_send_message: '固定訊息',
        task_action_agent_task: 'AI 任務',
        task_channel_type: '管道型別',
        task_channel_hint: '選擇定時訊息傳送的管道',
        task_message_content: '訊息內容',
        task_fixed_content: '固定內容',
        task_task_description: '任務描述',
        task_delete_btn: '刪除任務',
        task_delete_confirm_title: '刪除定時任務',
        task_delete_confirm_msg: '確定刪除該定時任務嗎？此操作無法撤銷。',
        task_run_now: '立即執行',
        task_run_confirm_title: '立即執行任務',
        task_run_confirm_msg: '該任務會立即向已設定的通道和接收者傳送內容。是否繼續？',
        task_run_started: '已開始執行',
        task_run_failed: '執行失敗',
        task_add_title: '新增定時任務',
        task_add_btn: '新增任務',
        task_recipient: '接收人',
        task_recipient_hint: '先選擇通道，再選擇該通道下已聯絡過的聯絡人，任務將主動推送給 TA',
        task_recipient_select: '選擇接收人',
        task_recipient_empty: '暫無可選接收人。對方需先透過通道（飛書/企業微信等）聯絡過智慧體。',
        task_recipient_group: '群聊',
        task_recipient_user: '使用者',
        task_recipient_required: '請先選擇接收人',
        task_recipient_placeholder: '請選擇接收人',
        task_recipient_refresh: '重新整理接收人列表',
        task_recipient_pick_instance_first: '請先選擇通道',
        task_recipient_empty_hint: '該通道下暫無接收人，請先在這個通道向智慧體發送一條訊息',
        task_instance: '通道',
        task_instance_tip: '選擇通道後，可指定該通道下已對話過的聯絡人，將任務結果推送給 TA',
        task_instance_placeholder: '請選擇通道',
        task_instance_empty: '暫無可用通道',
        task_instance_no_recipient: '暫無接收人',
        task_instance_required: '請先選擇通道',
        logs_title: '日誌', logs_desc: '實時日誌輸出 (run.log)',
        logs_live: '實時', logs_coming_msg: '日誌流即將在此提供。將連線 run.log 實現類似 tail -f 的實時輸出。',
        new_chat: '新對話',
        new_team_chat: '多智慧體對話',
        new_team_chat_hint: '選擇參與本次對話的智慧體，第一個為會話的主智慧體。',
        new_team_chat_owner: '主智慧體',
        new_team_chat_start: '開始對話',
        new_team_chat_min: '至少選擇兩個智慧體',
        session_history: '歷史會話',
        ws_toggle: '工作空間', ws_tab_preview: '預覽', ws_tab_files: '檔案',
        ws_default_workspace: '預設空間', ws_sel_title: '選擇工作空間',
        ws_sel_default_hint: '使用預設工作空間（~/cow）', ws_sel_recents: '最近使用',
        ws_sel_open: '開啟專案…', ws_sel_new: '新建專案', ws_sel_new_placeholder: '專案名稱',
        ws_sel_create: '建立', ws_sel_up: '上一層',
        ws_sel_new_subtitle: '將在 {root} 下建立新專案目錄', ws_sel_new_hint: '僅填寫專案名稱，不含路徑分隔符',
        ws_sel_name_required: '請輸入專案名稱', ws_sel_name_no_slash: '專案名稱不能包含 / 或 \\',
        ws_sel_open_here: '開啟此目錄', ws_sel_dblclick_hint: '雙擊進入子目錄，單擊選中',
        ws_sel_no_subdirs: '此目錄下沒有子資料夾', ws_sel_drives: '本機',
        ws_open_external: '在新分頁開啟', ws_download: '下載', ws_copy_path: '複製路徑',
        ws_close: '關閉', ws_refresh: '重新整理', ws_preview: '預覽',
        ws_search_placeholder: '搜尋檔案',
        ws_preview_empty: '選擇一個檔案進行預覽',
        ws_preview_failed: '預覽失敗',
        ws_link_not_found: '工作空間中找不到該檔案',
        ws_no_inline_preview: '該類型不支援內嵌預覽',
        ws_empty_dir: '空目錄', ws_no_results: '沒有符合的檔案',
        ws_truncated: '檔案過多，僅顯示部分',
        ws_edit: '編輯', ws_edit_save: '儲存 (Ctrl+S)', ws_edit_cancel: '離開編輯',
        ws_edit_saved: '已儲存',
        ws_edit_load_failed: '開啟編輯器失敗',
        ws_edit_save_failed: '儲存失敗',
        ws_edit_too_large: '檔案過大，無法在面板中編輯',
        ws_edit_unsupported: '該類型不支援編輯',
        ws_edit_encoding: '該檔案不是 UTF-8 編碼，編輯會損壞內容',
        ws_edit_conflict_title: '檔案已被變更',
        ws_edit_conflict_msg: '這個檔案在你編輯期間被變更過（可能是 Agent 寫入的）。覆寫儲存會丟棄磁碟上的新內容。',
        ws_edit_overwrite: '覆寫儲存',
        ws_edit_discard_title: '放棄未儲存的變更？',
        ws_edit_discard_msg: '目前檔案有未儲存的變更，繼續操作會遺失這些內容。',
        ws_edit_discard_ok: '放棄變更',
        today: '今天', yesterday: '昨天', earlier: '更早',
        session_pinned_group: '置頂',
        pin_session: '置頂',
        unpin_session: '取消置頂',
        project_rename: '重新命名專案',
        project_delete: '刪除專案',
        project_rename_title: '重新命名專案',
        project_delete_title: '刪除專案',
        project_delete_confirm: '確認刪除專案「{name}」？僅移除專案記錄，磁碟上的檔案不會被刪除，其下會話將回到預設空間。',
        perm_menu_title: '本次會話權限',
        perm_read_only: '唯讀',
        perm_workspace_write: '工作區可寫',
        perm_full_access: '全部可存取',
        perm_read_only_desc: '只能查看和分析，不修改任何檔案',
        perm_workspace_write_desc: '在目前工作空間內自由讀寫，空間之外的寫入會被拒絕',
        perm_full_access_desc: '不加限制，可修改任意位置（目前預設）',
        perm_follow_global: '跟隨全域設定',
        perm_tip: '權限：{name}',
        perm_denied_hint: '目前權限為「{name}」，此操作被拒絕。',
        perm_denied_action: '調整權限',
        model_menu_title: '本次會話模型',
        model_follow_global: '跟隨全域設定',
        model_follow_agent: '跟隨智慧體預設模型',
        model_tip: '模型：{name}',
        model_unset: '未設定',
        session_settings_failed: '設定失敗，請重試',
        delete_session_confirm: '確認刪除該會話？所有訊息將被清除。',
        delete_session_title: '刪除會話',
        rename_session: '重新命名',
        delete_message_confirm: '確認刪除這條訊息？',
        delete_message_title: '刪除訊息',
        edit_disabled_reply_active: '正在生成回覆，暫時無法編輯。',
        delete_disabled_reply_active: '正在生成回覆，暫時無法刪除。',
        untitled_session: '新對話',
        context_cleared: '— 以上內容已從上下文中移除 —',
        tip_new_chat: '新建對話',
        tip_clear_context: '清除上下文',
        ctx_usage_title: '上下文用量',
        ctx_system: '系統提示詞',
        ctx_tools: '工具和技能',
        ctx_history: '對話歷史',
        ctx_free: '剩餘可用',
        ctx_used_of: '已用 {used} / {limit}',
        ctx_estimated: '估算值',
        ctx_empty: '目前對話暫無上下文',
        ctx_error: '無法取得上下文用量',
        ctx_act_compact: '壓縮', ctx_act_compact_tip: '總結較早的對話以釋放上下文',
        ctx_act_clear: '清除', ctx_act_clear_tip: '清除目前對話上下文',
        ctx_act_adjust: '配置', ctx_act_adjust_tip: '調整最大上下文 Token',
        ctx_compacting: '正在壓縮上下文…',
        ctx_compact_failed: '壓縮失敗，請稍後重試',
        ctx_compact_noop: '目前上下文較短，無需壓縮',
        ctx_compacted_divider: '上下文已壓縮（{before} → {after} 條）',
        ctx_busy_turn: '正在生成回覆，請等回覆結束後再操作',
        tip_attach: '新增附件',
        tip_cancel: '中止',
        tip_cancelled: '已中止',
        attach_menu_file: '上傳檔案',
        mic_idle_title: '點選錄音 / 再按一次結束',
        mic_recording_title: '錄音中，再次點選結束',
        mic_busy_title: '識別中…',
        mic_permission_denied: '無法訪問麥克風，請檢查瀏覽器許可權',
        mic_too_short: '錄音太短，請重試',
        mic_error: '語音識別失敗',
        speak_msg: '朗讀這段回覆',
        voice_reply_mode_label: '語音回覆策略',
        voice_reply_off: '關閉',
        voice_reply_if_voice: '僅語音問/語音答',
        voice_reply_always: '總是語音回覆',
        attach_menu_folder: '上傳資料夾',
        confirm_yes: '確認',
        confirm_cancel: '取消',
        error_send: '傳送失敗，請稍後再試。', error_timeout: '請求超時，請再試一次。',
        thinking_in_progress: '思考中...', thinking_done: '已深度思考', thinking_duration: '耗時',
        edit_message: '編輯訊息',
        regenerate_response: '重新生成',
        edit_save: '儲存併傳送',
        edit_cancel: '取消',
        logout: '登出',
        update_check: '檢查更新',
        update_checking: '正在檢查…',
        update_up_to_date: '已是最新版本',
        update_now: '立即更新',
        update_changelog: '版本說明',
        update_error: '檢查更新失敗',
        update_unsupported: '此安裝方式不支援一鍵更新',
        update_confirm: '將拉取最新程式碼並重啟服務。確認繼續？',
        update_starting: '正在開始更新…',
        update_in_progress: '正在更新…',
        update_reconnect: '服務重啟中，正在重新連線…',
        update_done: '更新完成',
        update_failed: '更新失敗',
        update_step_git_pull: '拉取最新程式碼',
        update_step_install_deps: '安裝依賴',
        update_step_install_cli: '重裝 CLI',
        update_step_self_check: '檢查新程式碼',
        update_step_restart: '重啟服務',
        update_step_starting: '準備更新',
        update_step_done: '完成',
        },
    en: {
        console: 'Console',
        nav_chat: 'Chat', nav_manage: 'Management', nav_monitor: 'Monitor',
        menu_chat: 'Chat', menu_agents: 'Agents', menu_config: 'Config', menu_skills: 'Skills',
        agents_page_title: 'Agent Team', agents_page_desc: 'Manage the Agents on your team',
        agents_create: 'New Agent',
        agents_name_placeholder: 'Agent name',
        agents_name_required: 'Please enter a name',
        agents_stale: 'The list changed; please refresh and try again',
        agents_id_placeholder: 'Auto-generated if left blank',
        agents_id_tip: 'A unique identifier, fixed once created. Lowercase letters, digits and hyphens (-) only, e.g. ops-agent. Left blank, it is derived from the name.',
        agents_id_invalid: 'The id must start with a letter or digit and use only letters, digits, underscores and hyphens (max 64)',
        agents_avatar: 'Avatar',
        agents_tab_profile: 'Profile',
        agents_tab_skills: 'Skills',
        agents_tab_files: 'Core files',
        agents_core_edit: 'Edit',
        agents_core_preview: 'Preview',
        agents_core_file_agent: 'Persona',
        agents_core_file_user: 'User info',
        agents_core_file_rule: 'Workspace rules',
        agents_core_file_memory: 'Long-term memory',
        agents_default: 'Default',
        agents_archived: 'Archived',
        agents_chat: 'Start chat',
        agents_delete: 'Delete',
        agents_delete_title: 'Delete Agent',
        agents_delete_confirm: 'Delete Agent "{name}"? Its workspace and conversations will be removed for good.',
        agents_pick_hint: 'Pick Agents',
        agents_clone_label: 'Copy from an existing agent',
        agents_clone_hint: 'Copy its config, skills and knowledge as a starting point',
        agents_avatar_upload: 'Upload image',
        agents_clone_none: 'Blank',
        agents_clone_from: '{name}',
        agents_name: 'Name',
        agents_saved: 'Saved',
        agents_save_failed: 'Save failed',
        agents_no_desc: 'No responsibilities yet',
        agents_description: 'Responsibilities',
        agents_description_placeholder: 'What this Agent handles and when it should be used',
        agents_description_hint: 'Used for task assignment when Agents collaborate',
        agents_model: 'Default model',
        agents_model_follows_global: 'Follow the configured model',
        agents_model_default_hint: 'Uses the primary model. Change it under Model config.',
        agents_skills_all: 'Use every installed skill',
        agents_knowledge: 'Knowledge base',
        agents_knowledge_shared: 'Shared',
        agents_knowledge_own: 'Own',
        agents_knowledge_hint: 'Shared: read and write the same knowledge base as the team\nOwn: a private base, isolated from others',
        agents_knowledge_working: 'Working…',
        agents_knowledge_failed: 'Switch failed',
        agents_skills_pick: 'Only the skills checked below',
        agents_empty: 'No Agents yet. Create one to start a team.',
        agents_select_hint: 'Pick an Agent on the left to configure it',
        agents_pick_tip: 'Switch current Agent',
        composer_current_agent: 'Current Agent',
        team_members: 'In this conversation',
        team_invite: 'Add to chat',
        team_remove: 'Remove from this chat',
        composer_agent_owner: 'Owner',
        channel_bound_agent: 'Bind agent',
        channel_bound_default: 'default',
        channel_bound_agent_hint: 'first pick is the default agent: it receives messages and can delegate to the rest',
        channel_team_none: 'None',
        channel_team_no_candidates: 'No agents available',
        settings_tab_basic: 'General',
        settings_tab_models: 'Models',
        knowledge_shared_hint: 'Knowledge is shared by every Agent. Open it from the Knowledge page.',
        menu_memory: 'Memory', menu_knowledge: 'Knowledge', menu_channels: 'Channels', menu_tasks: 'Tasks',
        menu_logs: 'Logs',
        models_title: 'Models',
        models_desc: 'Manage chat, image, voice, embedding and search capabilities in one place',
        models_section_vendors: 'Provider Credentials',
        models_section_vendors_desc: 'Configured once, shared by multiple model capabilities',
        models_section_capabilities: 'Capabilities',
        models_add_vendor: 'Add Provider',
        models_provider: 'Provider',
        models_model: 'Model',
        models_voice: 'Voice',
        models_configured: 'configured',
        models_not_configured: 'not configured',
        models_pick_to_configure: 'pick to configure',
        models_clear_credential: 'Clear credentials',
        models_base_default_hint: 'Leave blank to use the official default base URL',
        models_catalog: 'Model catalog',
        models_catalog_advanced: '(Advanced · optional)',
        models_tag_text: 'Text',
        models_catalog_add: 'Add model',
        models_catalog_window: 'Context window',
        models_catalog_output: 'Max output',
        models_catalog_no_budget: 'Context window and max output do not apply to this model type',
        models_catalog_custom_hint: 'Add a model list for this custom provider so you can pick models from a dropdown on the chat page; leave empty to type the model name manually',
        models_catalog_name_ph: 'Model name',
        models_catalog_reset: 'Restore defaults',
        models_tag_chat: 'Main Model',
        models_tag_vision: 'Image Understanding',
        models_tag_video: 'Video Understanding',
        models_tag_image: 'Image Generation',
        models_tag_embedding: 'Embedding',
        models_tag_asr: 'Speech Recognition',
        models_tag_tts: 'Speech Synthesis',
        models_base_default: 'Default',
        models_custom_vendor_label: 'Custom',
        models_custom_name: 'Name',
        models_custom_delete: 'Delete',
        models_custom_delete_confirm_title: 'Delete custom provider',
        models_custom_delete_confirm_msg: 'Delete this custom provider? This cannot be undone.',
        models_custom_name_required: 'Name is required',
        models_custom_base_required: 'API Base is required',
        models_custom_edit_title: 'Edit custom provider',
        models_custom_add_title: 'Add custom provider',
        models_capability_chat: 'Main Model',
        models_capability_chat_desc: 'Used for basic chat and agent reasoning',
        models_capability_chat_fallback: 'Main Model Fallback',
        models_capability_chat_fallback_desc: 'Takes over only after the main model fails for good',
        models_fallback_enable: 'Enable the fallback model',
        models_fallback_config: 'Fallback',
        models_fallback_config_tip: 'Configure the main-model fallback (takes over after the main model fails)',
        models_fallback_modal_title: 'Main Model Fallback',
        models_fallback_modal_desc: 'When the main model still fails after exhausting its retries, the next model in the fallback chain is tried in order until one succeeds or the chain runs out.',
        models_fallback_badge_on: 'Fallback on',
        models_fallback_chain_title: 'Fallback chain (tried in order)',
        models_fallback_chain_desc: 'If the first one fails, the second is tried, and so on — the longer the chain, the more backups a turn has',
        models_fallback_chain_add: 'Add a fallback model',
        models_fallback_chain_empty: 'No fallback models yet — add one below',
        models_fallback_chain_link: 'Fallback {{n}}',
        models_fallback_chain_move_up: 'Move up',
        models_fallback_chain_move_down: 'Move down',
        models_fallback_chain_remove: 'Remove',
        models_fallback_chain_incomplete: 'Enabling the fallback needs at least one complete provider + model entry',
        models_capability_vision: 'Image Understanding',
        models_capability_vision_desc: 'Recognizes image content, used by image recognition tools',
        models_capability_image: 'Image Generation',
        models_capability_image_desc: 'Generates images, used by image generation skills',
        models_auto_using: 'Preferred',
        models_capability_asr: 'Speech Recognition',
        models_capability_asr_desc: 'Voice to text',
        models_capability_tts: 'Speech Synthesis',
        models_capability_tts_desc: 'Text to voice',
        models_capability_embedding: 'Embedding',
        models_capability_embedding_desc: 'Used for vectorized retrieval of memory and knowledge',
        models_capability_search: 'Web Search',
        models_capability_search_desc: 'Real-time web retrieval, used by search tools',
        models_strategy_auto: 'auto',
        models_search_strategy_label: 'Strategy',
        models_search_strategy_fixed: 'Pinned',
        models_search_strategy_auto_hint: 'Auto-pick from configured providers',
        models_search_strategy_fixed_hint: 'Always use a specific provider',
        models_pending_config: 'Pending setup',
        models_search_available_label: 'Available:',
        models_search_none_configured: 'No search provider enabled yet — click add.',
        models_search_add_provider: 'Add provider',
        models_search_add_desc: 'Pick a search provider to configure',
        models_search_bocha_title: 'Configure Bocha API Key',
        models_search_bocha_desc: 'Create a key at the Bocha open platform.',
        models_search_anysearch_title: 'Configure AnySearch API Key',
        models_search_anysearch_desc: 'Create a key at the AnySearch console (anysearch.com).',
        models_search_serply_title: 'Configure Serply API Key',
        models_search_serply_desc: 'Create a key at the Serply console (serply.io).',
        models_search_tavily_title: 'Configure Tavily API Key',
        models_search_tavily_desc: 'Create a key at the Tavily console (tavily.com).',
        models_search_searxng_title: 'Configure SearXNG Instance URL',
        models_search_searxng_desc: 'Enter the URL of your self-hosted SearXNG instance (no API key required).',
        models_search_anysearch_anon_hint: 'Leave empty to enable anonymous mode (no API key required)',
        models_search_anonymous_badge: 'anonymous',
        models_search_anonymous_disable: 'Disable anonymous',
        models_search_keenable_title: 'Configure Keenable API Key (optional)',
        models_search_keenable_desc: 'Save empty to enable anonymous mode; add a key from keenable.ai to lift the rate limits.',
        models_search_keenable_anon_hint: '',
        models_search_edit_hint: 'Click to edit',
        models_unavailable: 'unavailable',
        models_set_via_env: 'enable via environment variable',
        models_dim_label: 'dim',
        models_save_success: 'Saved',
        models_save_failed: 'Save failed',
        models_cleared: 'Cleared',
        models_clear_failed: 'Clear failed',
        models_embedding_change_title: 'Change embedding model',
        models_embedding_change_msg: 'Switching the embedding model invalidates the existing index — a rebuild will be needed. Continue?',
        models_embedding_saved_title: 'Embedding model updated',
        models_embedding_saved_msg: 'Send /memory rebuild-index in the chat to rebuild the index.',
        models_embedding_saved_ok: 'Go',
        models_pick_provider: 'Pick a provider',
        models_manage_api_key: 'Manage API keys',
        models_clear_confirm_title: 'Clear provider credentials',
        models_clear_confirm_msg: 'Remove this provider\'s API Key and Base URL? Capabilities relying on it will stop working.',
        cancel: 'Cancel',
        save: 'Save',
        ok: 'OK',
        knowledge_title: 'Knowledge', knowledge_desc: 'Browse and explore your knowledge base',
        knowledge_tab_docs: 'Documents', knowledge_tab_graph: 'Graph',
        knowledge_loading: 'Loading knowledge base...', knowledge_loading_desc: 'Knowledge pages will be displayed here',
        knowledge_select_hint: 'Select a document to view', knowledge_empty_hint: 'No knowledge pages yet',
        knowledge_empty_guide: 'Send documents, links or topics to the agent in chat, and it will automatically organize them into your knowledge base.',
        knowledge_go_chat: 'Start a conversation',
        knowledge_new: 'New',
        knowledge_new_category: 'New category',
        knowledge_new_document: 'New document',
        knowledge_import_documents: 'Import documents',
        welcome_subtitle: 'I can help you answer questions, manage your computer, create and execute skills, and keep growing through <br> long-term memory and a personal knowledge base.',
        example_sys_title: 'System', example_sys_text: 'Show me the files in the workspace',
        example_task_title: 'Scheduler', example_task_text: 'Remind me to check the server in 5 minutes',
        example_code_title: 'Coding', example_code_text: 'Search today\'s AI news and generate a visual report webpage',
        example_knowledge_title: 'Knowledge', example_knowledge_text: 'Show me the current knowledge base',
        example_skill_title: 'Skills', example_skill_text: 'Show current tools and skills',
        example_web_title: 'Commands', example_web_text: 'Show all commands',
        slash_help: 'Show this help',
        slash_status: 'Show running status',
        slash_context: 'Show conversation context',
        slash_context_clear: 'Clear conversation context',
        slash_compact: 'Summarize older turns to free up context',
        slash_skill_list: 'List installed skills',
        slash_skill_list_remote: 'Browse Skill Hub',
        slash_skill_search: 'Search skills',
        slash_skill_install: 'Install a skill (name or GitHub URL)',
        slash_skill_uninstall: 'Uninstall a skill',
        slash_skill_info: 'Show skill details',
        slash_skill_enable: 'Enable a skill',
        slash_skill_disable: 'Disable a skill',
        slash_memory_dream: 'Trigger memory distillation (optional days, default 3)',
        slash_knowledge: 'Show knowledge base stats',
        slash_knowledge_list: 'Show knowledge base file tree',
        slash_knowledge_on: 'Enable knowledge base',
        slash_knowledge_off: 'Disable knowledge base',
        slash_config: 'Show current config',
        slash_cancel: 'Abort the running Agent task',
        slash_steer: 'Inject guidance into the running Agent task',
        steer_active: 'Steer active task',
        slash_logs: 'Show recent logs',
        slash_version: 'Show version',
        input_placeholder: 'Type a message, / for commands, @ to reference a file',
        input_placeholder_team: 'Type a message, / for commands, @ to mention an Agent or a file',
        config_title: 'Configuration', config_desc: 'Manage model and agent settings',
        config_model: 'Model Configuration', config_agent: 'Agent Configuration',
        config_language: 'Language', config_language_hint: 'Language for the UI, command text, system prompts and more (synced with the top-right switch)',
        config_system: 'System',
        config_task_notify: 'Task Notifications', config_task_notify_hint: 'Show a browser notification when a task finishes or fails while the window is in the background; click to open the session',
        config_task_notify_sound: 'Notification Sound', config_task_notify_sound_hint: 'Turn off the alert sound while keeping notifications',
        config_task_notify_blocked: 'Notifications are blocked by the browser. Click the icon on the left of the address bar → Notifications → Allow, then reload.',
        notify_task_done: 'Task finished',
        notify_task_error: 'Task failed',
        config_model_advanced: 'Advanced',
        config_channel: 'Channel Configuration',
        config_agent_enabled: 'Agent Mode',
        config_max_tokens: 'Max Context Tokens', config_max_tokens_hint: 'Cap on the context input budget; history is compacted once reached, to control cost. Still clamped below the model window. Set 0 to disable the cap and follow the model window',
        config_max_turns: 'Max Memory Turns', config_max_turns_hint: 'One Q&A pair = one turn, auto-compressed when exceeded',
        config_max_steps: 'Max Steps', config_max_steps_hint: 'Max tool calls the Agent can make in a single conversation',
        config_enable_thinking: 'Deep Thinking', config_enable_thinking_hint: 'Enable deep thinking mode',
        config_reasoning_effort: 'Reasoning Effort', config_reasoning_effort_hint: 'Sent as the active provider\'s native enum value',
        config_subagent: 'Sub Agents', config_subagent_hint: 'Hand self-contained tasks to sub agents, which run in parallel and report back only their conclusions',
        config_self_evolution: 'Self-Evolution', config_self_evolution_hint: 'Auto-review idle conversations to consolidate memory, improve skills, and follow up on unfinished tasks',
        evolution_badge: 'Self-learned',
        config_channel_type: 'Channel Type',
        config_provider: 'Provider', config_model_name: 'Model',
        config_custom_model_hint: 'Enter custom model name',
        config_save: 'Save', config_saved: 'Saved',
        config_save_error: 'Save failed',
        config_custom_option: 'Custom',
        config_custom_tip: 'API must follow OpenAI protocol.',
        config_security: 'Security', config_password: 'Password',
        config_password_hint: 'Leave empty to disable password protection',
        config_permission: 'Default permissions',
        config_permission_hint: 'The default scope for new chats: which files the agent may change and which commands it may run',
        config_permission_desc: 'New chats start with this; each chat can be changed under the input box',
        config_password_changed: 'Password updated',
        config_password_cleared: 'Password cleared',
        config_password_security_warning: '⚠️ Warning: Password is now empty and the port is exposed. Consider restarting the service or adjusting the listening address binding.',
        skills_title: 'Skills', skills_desc: 'View, enable, or disable agent tools and skills', skills_hub_btn: 'Skill Hub',
        skills_loading: 'Loading skills...', skills_loading_desc: 'Skills will be displayed here after loading',
        tools_section_title: 'Built-in Tools', tools_loading: 'Loading tools...',
        skills_section_title: 'Skills', skill_enable: 'Enable', skill_disable: 'Disable',
        skill_toggle_error: 'Operation failed, please try again',
        skill_open_hint: 'Click to view this skill',
        skill_edit_hint: 'Edit skill',
        skill_back: 'Back to list',
        skill_load_failed: 'Could not read the skill',
        skill_builtin_readonly: 'Built-in skill, read-only (replaced on restart)',
        mcp_section_title: 'MCP Servers', mcp_section_hint: 'Add, edit, or disable MCP servers. Saved servers apply on the next message; no process restart.',
        mcp_add: 'Add server', mcp_edit: 'Edit server', mcp_empty: 'No MCP servers configured',
        mcp_test: 'Test connection', mcp_save: 'Save', mcp_cancel: 'Cancel', mcp_delete: 'Delete',
        mcp_status_ready: 'Ready', mcp_status_pending: 'Loading', mcp_status_failed: 'Failed',
        mcp_status_needs_auth: 'Needs auth', mcp_status_disabled: 'Disabled', mcp_status_idle: 'Idle',
        mcp_field_name: 'Name', mcp_field_type: 'Transport', mcp_field_command: 'Command',
        mcp_field_args: 'Args (one per line)', mcp_field_env: 'Env (KEY=value per line)',
        mcp_field_url: 'URL', mcp_field_headers: 'Headers (KEY=value per line)', mcp_field_scope: 'OAuth scope',
        mcp_field_prefix: 'Tool name prefix', mcp_field_timeout: 'Timeout (seconds)', mcp_field_disabled: 'Disable this server',
        mcp_test_ok: 'Connected', mcp_test_fail: 'Connection failed', mcp_save_error: 'Save failed',
        mcp_delete_confirm: 'Delete this MCP server?', mcp_apply_hint: 'Applies on the next message',
        skill_install_btn: 'Install', skill_install_placeholder: 'Skill Hub name or GitHub URL',
        skill_install_error: 'Install failed', skill_delete: 'Uninstall',
        skill_delete_confirm: 'Uninstall this skill?', skill_delete_error: 'Uninstall failed',
        memory_title: 'Memory', memory_desc: 'View agent memory files and contents',
        memory_tab_files: 'Memory Files', memory_tab_dreams: 'Self-Evolution',
        memory_loading: 'Loading memory files...', memory_loading_desc: 'Memory files will be displayed here',
        memory_back: 'Back to list',
        memory_col_name: 'Filename', memory_col_type: 'Type', memory_col_size: 'Size', memory_col_updated: 'Updated',
        channels_title: 'Channels', channels_desc: 'Manage connected messaging channels',
        channels_add: 'Connect', channels_disconnect: 'Disconnect',
        channels_save: 'Save', channels_saved: 'Saved', channels_save_error: 'Save failed',
        channels_restarted: 'Saved & Restarted',
        channels_connect_btn: 'Connect', channels_cancel: 'Cancel',
        channel_rename: 'Rename channel',
        channels_select_placeholder: 'Select a channel to connect...',
        channels_empty: 'No channels connected', channels_empty_desc: 'Click the "Connect" button above to get started',
        channels_disconnect_confirm: 'This channel will stop receiving messages. Disconnect it?',
        channels_disconnect_error: 'Failed to disconnect',
        channels_connected: 'Connected', channels_connecting: 'Connecting...',
        weixin_scan_title: 'WeChat QR Login', weixin_scan_desc: 'Scan the QR code below with WeChat',
        weixin_scan_loading: 'Loading QR code...', weixin_scan_waiting: 'Waiting for scan...',
        weixin_scan_scanned: 'Scanned, please confirm on your phone', weixin_scan_expired: 'QR code expired, refreshing...',
        weixin_scan_success: 'Login successful, starting channel...', weixin_scan_fail: 'Failed to load QR code',
        weixin_qr_tip: 'QR code expires in ~2 minutes',
        wecom_scan_btn: 'Scan to Create WeCom Bot', wecom_scan_desc: 'Scan with WeCom to create a bot instantly',
        wecom_scan_success: 'Bot created, starting channel...',
        wecom_scan_fail: 'Bot creation failed',
        wecom_mode_scan: 'Scan QR', wecom_mode_manual: 'Manual',
        feishu_scan_btn: 'One-click Create Feishu App',
        feishu_scan_desc: 'Scan with Feishu App to create an app with all required permissions pre-configured',
        feishu_scan_replace_desc: 'Scan with Feishu App to create a new bot — will overwrite the current App ID / Secret',
        feishu_scan_loading: 'Requesting QR code from Feishu...',
        feishu_scan_waiting: 'Waiting for scan...',
        feishu_scan_tip: 'QR code expires in 10 minutes, single use only',
        feishu_scan_open_link: 'Or click here to open in browser',
        feishu_scan_success: 'App created, starting channel...',
        feishu_scan_expired: 'QR code expired, please retry',
        feishu_scan_denied: 'Authorization cancelled',
        feishu_scan_fail: 'App creation failed',
        feishu_scan_retry: 'Retry',
        feishu_sdk_downloading: 'Downloading Feishu components...',
        feishu_sdk_downloading_tip: 'A one-time ~1MB download; this will continue automatically',
        feishu_mode_scan: 'Scan QR', feishu_mode_manual: 'Manual',
        tasks_title: 'Scheduled Tasks', tasks_desc: 'View and manage scheduled tasks',
        tasks_coming: 'Coming Soon', tasks_coming_desc: 'Scheduled task management will be available here',
        tasks_tab_tasks: 'Tasks', tasks_tab_records: 'History',
        records_desc: 'Execution history of scheduled tasks',
        records_loading: 'Loading history...', records_empty: 'No executions yet',
        records_empty_guide: 'Once tasks run, both successful and failed executions show up here',
        records_status_done: 'Success', records_status_error: 'Failed', records_status_running: 'Running',
        records_trigger_scheduled: 'Scheduled', records_trigger_manual: 'Manual',
        records_duration: 'Duration', records_no_output: '(no content)',
        records_load_more: 'Load more', records_delete: 'Delete',
        records_delete_confirm_title: 'Delete record', records_delete_confirm_msg: 'Delete this execution record? This cannot be undone.',
        records_delete_failed: 'Delete failed, please retry',
        record_detail_title: 'Execution detail', record_detail_loading: 'Loading detail...',
        record_detail_status: 'Status', record_detail_trigger: 'Trigger',
        record_detail_started: 'Started', record_detail_duration: 'Duration',
        record_detail_channel_type: 'Channel type', record_detail_channel_name: 'Channel name',
        record_detail_agent: 'Agent', record_detail_output: 'Delivered',
        record_detail_view_preview: 'Preview', record_detail_view_text: 'Text',
        record_detail_error: 'Error',
        record_channel_web_type: 'web', record_channel_web_name: 'Web',
        task_add_btn: 'Add Task',
        task_edit_title: 'Edit Task',
        task_add_title: 'Add Task',
        task_name: 'Task Name',
        task_enabled: 'Enable Task',
        task_schedule_type: 'Schedule Type',
        task_schedule_cron: 'Cron Expression',
        task_schedule_interval: 'Fixed Interval',
        task_schedule_once: 'One-time Task',
        task_cron_expression: 'Cron Expression',
        task_cron_hint: 'Format: minute hour day month weekday, e.g. "0 9 * * *" means daily at 9:00',
        task_interval_seconds: 'Interval (seconds)',
        task_interval_hint: 'Minimum 60 seconds, e.g. 3600 means once per hour',
        task_once_time: 'Execution Time',
        task_action_type: 'Task Type',
        task_action_send_message: 'Fixed Message',
        task_action_agent_task: 'AI Task',
        task_channel_type: 'Channel Type',
        task_channel_hint: 'Select the channel to send scheduled messages',
        task_message_content: 'Message Content',
        task_fixed_content: 'Fixed Content',
        task_task_description: 'Task Description',
        task_delete_btn: 'Delete Task',
        task_delete_confirm_title: 'Delete Task',
        task_delete_confirm_msg: 'Delete this scheduled task? This action cannot be undone.',
        task_run_now: 'Run now',
        task_run_confirm_title: 'Run task now',
        task_run_confirm_msg: 'This task will immediately send to its configured channel and receiver. Continue?',
        task_run_started: 'Run started',
        task_run_failed: 'Run failed',
        task_add_title: 'New Scheduled Task',
        task_add_btn: 'New Task',
        task_recipient: 'Recipient',
        task_recipient_hint: 'Pick a channel first, then a contact within it; the task will be pushed to them.',
        task_recipient_select: 'Select recipient',
        task_recipient_empty: 'No recipients yet. They must contact the agent on a channel (Feishu / WeCom, etc.) first.',
        task_recipient_group: 'Group',
        task_recipient_user: 'User',
        task_recipient_placeholder: 'Select a recipient',
        task_recipient_refresh: 'Refresh recipient list',
        task_recipient_pick_instance_first: 'Pick a channel first',
        task_recipient_empty_hint: 'No recipients on this channel yet — message the agent on this channel first.',
        task_instance: 'Channel',
        task_instance_tip: 'After picking a channel, choose a contact you have talked with there; the task result is pushed to them.',
        task_instance_placeholder: 'Select a channel',
        task_instance_empty: 'No channels available',
        task_instance_no_recipient: 'No recipients',
        task_instance_required: 'Please select a channel',
        task_recipient_required: 'Please select a recipient',
        logs_title: 'Logs', logs_desc: 'Real-time log output (run.log)',
        logs_live: 'Live', logs_coming_msg: 'Log streaming will be available here. Connects to run.log for real-time output similar to tail -f.',
        new_chat: 'New Chat',
        new_team_chat: 'Group chat',
        new_team_chat_hint: 'Pick the Agents for this conversation; the first is its main Agent.',
        new_team_chat_owner: 'Main',
        new_team_chat_start: 'Start chat',
        new_team_chat_min: 'Pick at least two Agents',
        session_history: 'History',
        ws_toggle: 'Workspace', ws_tab_preview: 'Preview', ws_tab_files: 'Files',
        ws_default_workspace: 'Default', ws_sel_title: 'Select workspace',
        ws_sel_default_hint: 'Use the default workspace (~/cow)', ws_sel_recents: 'Recent',
        ws_sel_open: 'Open project…', ws_sel_new: 'New project', ws_sel_new_placeholder: 'Project name',
        ws_sel_create: 'Create', ws_sel_up: 'Up',
        ws_sel_new_subtitle: 'Creates a new project directory under {root}', ws_sel_new_hint: 'Project name only, no path separators',
        ws_sel_name_required: 'Please enter a project name', ws_sel_name_no_slash: 'Project name must not contain / or \\',
        ws_sel_open_here: 'Open this folder', ws_sel_dblclick_hint: 'Double-click to enter, single-click to select',
        ws_sel_no_subdirs: 'No sub-folders here', ws_sel_drives: 'This PC',
        ws_open_external: 'Open in new tab', ws_download: 'Download', ws_copy_path: 'Copy path',
        ws_close: 'Close', ws_refresh: 'Refresh', ws_preview: 'Preview',
        ws_search_placeholder: 'Search files',
        ws_preview_empty: 'Select a file to preview',
        ws_preview_failed: 'Preview failed',
        ws_link_not_found: 'File not found in the workspace',
        ws_no_inline_preview: 'No inline preview for this file type',
        ws_empty_dir: 'Empty directory', ws_no_results: 'No matching files',
        ws_truncated: 'Too many files, showing a subset',
        ws_edit: 'Edit', ws_edit_save: 'Save (Ctrl+S)', ws_edit_cancel: 'Leave editor',
        ws_edit_saved: 'Saved',
        ws_edit_load_failed: 'Could not open the editor',
        ws_edit_save_failed: 'Save failed',
        ws_edit_too_large: 'File is too large to edit in the panel',
        ws_edit_unsupported: 'This file type cannot be edited',
        ws_edit_encoding: 'This file is not UTF-8; editing would corrupt it',
        ws_edit_conflict_title: 'File changed on disk',
        ws_edit_conflict_msg: 'This file changed while you were editing it, most likely written by the agent. Overwriting discards the newer content on disk.',
        ws_edit_overwrite: 'Overwrite',
        ws_edit_discard_title: 'Discard unsaved changes?',
        ws_edit_discard_msg: 'This file has unsaved changes and continuing will lose them.',
        ws_edit_discard_ok: 'Discard',
        today: 'Today', yesterday: 'Yesterday', earlier: 'Earlier',
        session_pinned_group: 'Pinned',
        pin_session: 'Pin',
        unpin_session: 'Unpin',
        project_rename: 'Rename project',
        project_delete: 'Delete project',
        project_rename_title: 'Rename project',
        project_delete_title: 'Delete project',
        project_delete_confirm: 'Delete project “{name}”? Only the project record is removed — files on disk are kept, and its chats revert to the default workspace.',
        perm_menu_title: 'Permissions for this chat',
        perm_read_only: 'Read-only',
        perm_workspace_write: 'Workspace write',
        perm_full_access: 'Full access',
        perm_read_only_desc: 'Read and analyse only; no file is modified',
        perm_workspace_write_desc: 'Write freely inside this workspace; writes outside it are refused',
        perm_full_access_desc: 'No limits, anywhere on the machine (current default)',
        perm_follow_global: 'Follow global setting',
        perm_tip: 'Permissions: {name}',
        perm_denied_hint: 'This session is “{name}”, so the action was refused.',
        perm_denied_action: 'Adjust permissions',
        model_menu_title: 'Model for this chat',
        model_follow_global: 'Follow global setting',
        model_follow_agent: 'Follow the agent\u2019s default model',
        model_tip: 'Model: {name}',
        model_unset: 'Not set',
        session_settings_failed: 'Could not apply, please retry',
        delete_session_confirm: 'Delete this session? All messages will be removed.',
        delete_session_title: 'Delete Session',
        rename_session: 'Rename',
        delete_message_confirm: 'Delete this message?',
        delete_message_title: 'Delete Message',
        edit_disabled_reply_active: 'Reply is being generated; editing is temporarily unavailable.',
        delete_disabled_reply_active: 'Reply is being generated; deletion is temporarily unavailable.',
        untitled_session: 'New Chat',
        context_cleared: '— Context above has been cleared —',
        tip_new_chat: 'New Chat',
        tip_clear_context: 'Clear Context',
        ctx_usage_title: 'Context usage',
        ctx_system: 'System prompt',
        ctx_tools: 'Tools & skills',
        ctx_history: 'Conversation',
        ctx_free: 'Free',
        ctx_used_of: '{used} / {limit} used',
        ctx_estimated: 'estimated',
        ctx_empty: 'No context built for this session yet',
        ctx_error: 'Could not load context usage',
        ctx_act_compact: 'Compact', ctx_act_compact_tip: 'Summarize older turns to free up context',
        ctx_act_clear: 'Clear', ctx_act_clear_tip: 'Clear the current conversation context',
        ctx_act_adjust: 'Config', ctx_act_adjust_tip: 'Adjust the max context tokens',
        ctx_compacting: 'Compacting context…',
        ctx_compact_failed: 'Compaction failed, please try again',
        ctx_compact_noop: 'Context is already short, nothing to compact',
        ctx_compacted_divider: 'Context compacted ({before} → {after} messages)',
        ctx_busy_turn: 'A reply is being generated; please wait until it finishes',
        tip_attach: 'Add Attachment',
        tip_cancel: 'Cancel',
        tip_cancelled: 'Cancelled',
        attach_menu_file: 'Upload File',
        mic_idle_title: 'Click to record, click again to stop',
        mic_recording_title: 'Recording, click to stop',
        mic_busy_title: 'Transcribing…',
        mic_permission_denied: 'Cannot access microphone — check browser permissions',
        mic_too_short: 'Recording too short, please retry',
        mic_error: 'Speech recognition failed',
        optimize_idle_title: 'Optimize prompt',
        optimize_busy_title: 'Optimizing…',
        optimize_error: 'Prompt optimization failed',
        optimize_empty: 'Input is empty, nothing to optimize',
        speak_msg: 'Read this reply aloud',
        voice_reply_mode_label: 'Voice reply policy',
        voice_reply_off: 'Off',
        voice_reply_if_voice: 'Voice only if voice input',
        voice_reply_always: 'Always reply with voice',
        attach_menu_folder: 'Upload Folder',
        confirm_yes: 'Confirm',
        confirm_cancel: 'Cancel',
        error_send: 'Failed to send. Please try again.', error_timeout: 'Request timeout. Please try again.',
        thinking_in_progress: 'Thinking...', thinking_done: 'Thought', thinking_duration: 'Duration',
        edit_message: 'Edit message',
        regenerate_response: 'Regenerate',
        edit_save: 'Save and send',
        edit_cancel: 'Cancel',
        logout: 'Logout',
        update_check: 'Check for update',
        update_checking: 'Checking…',
        update_up_to_date: 'You are up to date',
        update_now: 'Update now',
        update_changelog: 'Release notes',
        update_error: 'Could not check for updates',
        update_unsupported: 'This install cannot self-update',
        update_confirm: 'This will pull the latest code and restart the service. Continue?',
        update_starting: 'Starting update…',
        update_in_progress: 'Updating…',
        update_reconnect: 'Service is restarting. Reconnecting…',
        update_done: 'Update complete',
        update_failed: 'Update failed',
        update_step_git_pull: 'Pulling latest code',
        update_step_install_deps: 'Installing dependencies',
        update_step_install_cli: 'Reinstalling the CLI',
        update_step_self_check: 'Checking the new code',
        update_step_restart: 'Restarting the service',
        update_step_starting: 'Preparing the update',
        update_step_done: 'Done',
    }
};

// Resolve language by priority: user choice (localStorage) -> backend-detected
// (cow_lang) -> browser language -> 'zh'. Shares __cowResolveLang__ defined in
// chat.html; falls back to a local resolver if loaded standalone.
let currentLang = (typeof window.__cowResolveLang__ === 'function')
    ? window.__cowResolveLang__()
    : (function () {
        const norm = (raw) => {
            if (!raw) return '';
            const v = String(raw).trim().toLowerCase();
            if (v === 'auto') return '';
            // Handle Traditional Chinese variants first (more specific)
            if (v === 'zh-hant' || v.startsWith('zh-hant-') || v === 'zh-tw' || v === 'zh-hk') return 'zh-Hant';
            // Then Simplified Chinese
            if (v.indexOf('zh') === 0) return 'zh';
            if (v.indexOf('en') === 0) return 'en';
            return '';
        };
        return norm(localStorage.getItem('cow_lang'))
            || norm(window.__COW_DEFAULT_LANG__)
            || norm(navigator.language)
            || 'zh';
    })();

function t(key) {
    return (I18N[currentLang] && I18N[currentLang][key]) || (I18N.en[key]) || key;
}

// Resolve a localized label that may be either a plain string or
// a {zh, en} object returned by the backend.
function localizedLabel(label) {
    if (label && typeof label === 'object') {
        return label[currentLang] || label.en || label.zh || '';
    }
    return label || '';
}

function applyI18n() {
    document.querySelectorAll('[data-i18n]').forEach(el => {
        el.textContent = t(el.dataset.i18n);
    });
    document.querySelectorAll('[data-i18n-html]').forEach(el => {
        el.innerHTML = t(el.dataset.i18nHtml);
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
        el.placeholder = t(el.dataset['i18nPlaceholder']);
    });
    document.querySelectorAll('[data-i18n-title]').forEach(el => {
        el.title = t(el.dataset['i18nTitle']);
    });
    document.querySelectorAll('[data-i18n-aria-label]').forEach(el => {
        el.setAttribute('aria-label', t(el.dataset['i18nAriaLabel']));
    });
    document.querySelectorAll('[data-i18n-tip]').forEach(el => {
        el.setAttribute('data-tip', t(el.dataset['i18nTip']));
    });
    document.querySelectorAll('[data-tip-key]').forEach(el => {
        el.setAttribute('data-tooltip', t(el.dataset.tipKey));
    });
    installCfgTipPortal();
    installContextUsagePopover();
    
    // Clear any status messages when language changes
    document.querySelectorAll('[id$="-status"]').forEach(el => {
        el.classList.add('opacity-0');
    });
    
    _syncLangControls();
    // Point the docs link to the locale-specific documentation site.
    const docsLink = document.getElementById('docs-link');
    if (docsLink) docsLink.href = currentLang === 'zh' ? 'https://docs.cowagent.ai/zh' : 'https://docs.cowagent.ai';
    // Workspace panel content is rendered by JS, not data-i18n attributes.
    if (typeof relocalizeWorkspacePanel === 'function') relocalizeWorkspacePanel();
}

// Single entry point for switching language. Updates the in-memory language,
// persists the user choice locally, re-renders the UI, and binds the choice to
// the backend `cow_lang` config so logs / agent replies / CLI follow suit.
function setLanguage(lang) {
    const next = (lang === 'en' || lang === 'zh' || lang === 'zh-Hant') ? lang : 'zh';
    if (next === currentLang) {
        // Still persist + sync in case storage/backend drifted from the UI.
        syncLanguageToBackend(next);
        return;
    }
    currentLang = next;
    localStorage.setItem('cow_lang', currentLang);
    applyI18n();
    _applyInputTooltips();
    // Keep the language switch button and config selector visually in sync.
    try { updateLangControls(); } catch (e) {}
    
    // Sync language choice to backend first, then trigger dynamic views reload
    // to avoid race conditions on API endpoints.
    syncLanguageToBackend(currentLang, () => {
        try { rerenderDynamicViews(); } catch (e) {}
    });
}

// Persist the language to the backend `cow_lang` config (best-effort; the UI
// has already switched locally, so a network failure is non-blocking).
function syncLanguageToBackend(lang, callback) {
    try {
        fetch('/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ updates: { cow_lang: lang } })
        })
        .then(() => { if (callback) callback(); })
        .catch(() => { if (callback) callback(); });
    } catch (e) {
        if (callback) callback();
    }
}

// Reflect the current language on both the top-right toggle and the config
// selector (if present), so the two entry points stay synchronized.
function updateLangControls() {
    _syncLangControls();
    // The config language picker is the custom .cfg-dropdown component. Only
    // sync it once it has been initialized (i.e. the config panel was opened).
    const sel = document.getElementById('cfg-lang-select');
    if (sel && sel._ddValue !== undefined && sel._ddValue !== currentLang) {
        sel._ddValue = currentLang;
        const textEl = sel.querySelector('.cfg-dropdown-text');
        if (textEl) {
            if (currentLang === 'zh-Hant') textEl.textContent = '繁體中文';
            else if (currentLang === 'zh') textEl.textContent = '简体中文';
            else textEl.textContent = 'English';
        }
        sel.querySelectorAll('.cfg-dropdown-item').forEach(i => {
            i.classList.toggle('active', i.dataset.value === currentLang);
        });
    }
}

// Reflect the current language on the header dropdown: short label on the
// toggle (简 / 繁 / EN) plus the active item highlighted in the menu.
function _syncLangControls() {
    const langLabel = document.getElementById('lang-label');
    if (langLabel) {
        if (currentLang === 'zh-Hant') langLabel.textContent = '繁';
        else if (currentLang === 'zh') langLabel.textContent = '简';
        else langLabel.textContent = 'EN';
    }
    document.querySelectorAll('#lang-menu .lang-menu-item').forEach(item => {
        const active = item.dataset.lang === currentLang;
        item.classList.toggle('text-blue-600', active);
        item.classList.toggle('dark:text-blue-400', active);
        item.classList.toggle('font-medium', active);
    });
}

// Toggle the header language dropdown menu open/closed.
function toggleLangMenu(event) {
    if (event) event.stopPropagation();
    const menu = document.getElementById('lang-menu');
    if (menu) menu.classList.toggle('hidden');
}

// Pick a language from the dropdown, then close the menu.
function selectLanguage(lang) {
    const menu = document.getElementById('lang-menu');
    if (menu) menu.classList.add('hidden');
    setLanguage(lang);
}
window.toggleLangMenu = toggleLangMenu;
window.selectLanguage = selectLanguage;

// Close the language menu when clicking outside of it.
document.addEventListener('click', (e) => {
    const selector = document.getElementById('lang-selector');
    const menu = document.getElementById('lang-menu');
    if (menu && !menu.classList.contains('hidden') && selector && !selector.contains(e.target)) {
        menu.classList.add('hidden');
    }
});

// Refresh JS-rendered views after a language switch. Each branch uses the
// lightweight in-memory re-render path (no extra network round-trips).
function rerenderDynamicViews() {
    // Models are a tab of the config view, not a view of their own.
    if (currentView === 'config' && typeof renderModelsView === 'function'
            && modelsState && (modelsState.providers || modelsState.capabilities)) {
        renderModelsView();
    }
    // Reload task list after language switch
    if (currentView === 'tasks') {
        tasksLoaded = false;
        loadTasksView();
    }
    // Reload skills and tools after language switch
    if (currentView === 'skills') {
        toolsLoaded = false;
        loadSkillsView();
    }
    // Reload channels after language switch
    if (currentView === 'channels') {
        loadChannelsView();
    }
    // Reload config after language switch
    if (currentView === 'config') {
        loadConfigView();
    }
    // Repaint the Agents workbench after a language switch. The grid, detail
    // pane and avatar picker are built from t() into innerHTML, so applyI18n()
    // (which only touches data-i18n nodes) can't relocalize them; re-render from
    // the in-memory catalog instead of refetching.
    if (currentView === 'agents') {
        renderAgentsGrid();
        if (selectedAdminAgentId) renderAgentDetail();
    }
}

// Floating tooltip portal for [data-tip-key] elements. Tooltip nodes are
// appended to <body> so they aren't clipped by overflow:hidden ancestors
// (e.g. the config panel's scroll container).
let _cfgTipPortalEl = null;
let _cfgTipPortalInstalled = false;
function installCfgTipPortal() {
    if (_cfgTipPortalInstalled) return;
    _cfgTipPortalInstalled = true;

    const showTip = (target) => {
        const text = target.getAttribute('data-tooltip');
        if (!text) return;
        if (!_cfgTipPortalEl) {
            _cfgTipPortalEl = document.createElement('div');
            _cfgTipPortalEl.className = 'cfg-tip-floating';
            document.body.appendChild(_cfgTipPortalEl);
        }
        _cfgTipPortalEl.textContent = text;
        const rect = target.getBoundingClientRect();
        // Render once to measure, then position relative to the target.
        _cfgTipPortalEl.style.left = '0px';
        _cfgTipPortalEl.style.top = '0px';
        _cfgTipPortalEl.classList.add('show');
        const tipRect = _cfgTipPortalEl.getBoundingClientRect();
        let left = rect.left + rect.width / 2 - tipRect.width / 2;
        // Clamp horizontally to the viewport with an 8px gutter.
        left = Math.max(8, Math.min(left, window.innerWidth - tipRect.width - 8));
        // Default above the target; place below when data-tooltip-pos="bottom".
        const below = target.getAttribute('data-tooltip-pos') === 'bottom';
        const top = below ? rect.bottom + 6 : rect.top - tipRect.height - 6;
        _cfgTipPortalEl.style.left = left + 'px';
        _cfgTipPortalEl.style.top = top + 'px';
    };
    const hideTip = () => {
        if (_cfgTipPortalEl) _cfgTipPortalEl.classList.remove('show');
    };

    // Matches config keys and any element opting into the floating tooltip via
    // [data-tip-float] (used for dynamic tooltips like the workspace selector,
    // whose data-tooltip is set at runtime rather than from a translation key).
    const _tipSel = '[data-tip-key],[data-tip-float]';
    document.addEventListener('mouseover', (e) => {
        const target = e.target.closest(_tipSel);
        if (target) showTip(target);
    });
    document.addEventListener('mouseout', (e) => {
        const target = e.target.closest(_tipSel);
        if (target) hideTip();
    });
    // Hide on scroll/resize so the tooltip doesn't drift away from its anchor.
    window.addEventListener('scroll', hideTip, true);
    window.addEventListener('resize', hideTip);
}

// =====================================================================
// Context usage popover (hover on the clear-context button)
// =====================================================================
// Body-level floating card that shows a pie of what is occupying the current
// session's context window, fetched from /api/sessions/{sid}/context_usage on
// hover. Reuses the portal approach of installCfgTipPortal so the composer's
// overflow can't clip it; unlike the text tooltips it renders innerHTML (an
// inline SVG donut).
let _ctxUsageEl = null;
let _ctxUsageInstalled = false;
const _CTX_SLICE_COLORS = {
    system: '#228547',
    tools: '#4ABE6E',
    history: '#f59e0b',
    free: '#64748b',
};
const _CTX_LEGEND = [
    { key: 'system', labelKey: 'ctx_system' },
    { key: 'tools', labelKey: 'ctx_tools' },
    { key: 'history', labelKey: 'ctx_history' },
    { key: 'free', labelKey: 'ctx_free' },
];
function _ctxFmtTokens(n) {
    if (n < 1000) return String(n);
    if (n < 10000) return (n / 1000).toFixed(1) + 'k';
    return Math.round(n / 1000) + 'k';
}
function _ctxDonutSvg(slices) {
    const size = 96, stroke = 12, r = (size - stroke) / 2, c = 2 * Math.PI * r;
    const total = slices.reduce((s, x) => s + Math.max(0, x.value), 0);
    const parts = [];
    let offset = 0;
    slices.forEach((s) => {
        const frac = total > 0 ? Math.max(0, s.value) / total : 0;
        if (frac > 0) {
            parts.push(
                '<circle cx="' + size / 2 + '" cy="' + size / 2 + '" r="' + r +
                '" fill="none" stroke="' + _CTX_SLICE_COLORS[s.key] +
                '" stroke-width="' + stroke +
                '" stroke-dasharray="' + (frac * c) + ' ' + c +
                '" stroke-dashoffset="' + (-offset * c) + '"></circle>'
            );
        }
        offset += frac;
    });
    return '<svg width="' + size + '" height="' + size +
        '" viewBox="0 0 ' + size + ' ' + size + '">' +
        '<g transform="rotate(-90 ' + size / 2 + ' ' + size / 2 + ')">' +
        parts.join('') + '</g></svg>';
}
function _ctxRenderCard(usage) {
    if (!usage || usage.status === 'error') {
        return '<div class="ctx-usage-empty">' + t('ctx_error') + '</div>';
    }
    if (!usage.available || !usage.breakdown) {
        return '<div class="ctx-usage-empty">' + t('ctx_empty') + '</div>';
    }
    const b = usage.breakdown;
    const limit = usage.limit || 0;
    const used = usage.used || 0;
    const percent = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;
    const slices = _CTX_LEGEND.map((l) => ({ key: l.key, value: b[l.key] || 0 }));
    const rows = _CTX_LEGEND.map((l) =>
        '<div class="ctx-usage-row">' +
        '<span class="ctx-usage-dot" style="background:' + _CTX_SLICE_COLORS[l.key] + '"></span>' +
        '<span class="ctx-usage-label">' + t(l.labelKey) + '</span>' +
        '<span class="ctx-usage-val">' + _ctxFmtTokens(b[l.key] || 0) + '</span>' +
        '</div>'
    ).join('');
    const usedLine = t('ctx_used_of')
        .replace('{used}', _ctxFmtTokens(used))
        .replace('{limit}', _ctxFmtTokens(limit));
    return (
        '<div class="ctx-usage-head">' +
        '<span class="ctx-usage-title">' + t('ctx_usage_title') + '</span>' +
        (usage.estimated ? '<span class="ctx-usage-est">' + t('ctx_estimated') + '</span>' : '') +
        '</div>' +
        '<div class="ctx-usage-donut-wrap">' + _ctxDonutSvg(slices) +
        '<span class="ctx-usage-pct">' + percent + '%</span></div>' +
        '<div class="ctx-usage-legend">' + rows + '</div>' +
        '<div class="ctx-usage-foot">' + usedLine + '</div>' +
        _ctxActionsBar()
    );
}

// Action row at the bottom of the usage card: clear / compact / adjust budget.
// Buttons carry data-ctx-action so one delegated handler on the card element
// wires them (the card's innerHTML is re-rendered on every refresh).
function _ctxActionsBar() {
    return (
        '<div class="ctx-usage-actions">' +
        '<button type="button" class="ctx-act-btn" data-ctx-action="compact" data-tooltip="' + t('ctx_act_compact_tip') + '">' +
        '<i class="fas fa-compress"></i><span>' + t('ctx_act_compact') + '</span></button>' +
        '<button type="button" class="ctx-act-btn" data-ctx-action="clear" data-tooltip="' + t('ctx_act_clear_tip') + '">' +
        '<i class="fas fa-trash-can"></i><span>' + t('ctx_act_clear') + '</span></button>' +
        '<button type="button" class="ctx-act-btn" data-ctx-action="adjust" data-tooltip="' + t('ctx_act_adjust_tip') + '">' +
        '<i class="fas fa-sliders"></i><span>' + t('ctx_act_adjust') + '</span></button>' +
        '</div>'
    );
}

// Small inline donut for the composer button, so the fill/percent is readable
// without opening the card. Mirrors _ctxDonutSvg's slice math at 16px with a
// thin stroke; grey ring when there's no context yet.
function _ctxMiniPieSvg(usage) {
    const size = 16, stroke = 4, r = (size - stroke) / 2, c = 2 * Math.PI * r;
    if (!usage || !usage.available || !usage.breakdown) {
        // Empty: a faint full ring.
        return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 ' + size + ' ' + size + '">' +
            '<circle cx="' + size / 2 + '" cy="' + size / 2 + '" r="' + r +
            '" fill="none" stroke="currentColor" stroke-width="' + stroke + '" opacity="0.35"></circle></svg>';
    }
    const b = usage.breakdown;
    const slices = _CTX_LEGEND.map((l) => ({ key: l.key, value: b[l.key] || 0 }));
    const total = slices.reduce((s, x) => s + Math.max(0, x.value), 0);
    const parts = [
        '<circle cx="' + size / 2 + '" cy="' + size / 2 + '" r="' + r +
        '" fill="none" stroke="currentColor" stroke-width="' + stroke + '" opacity="0.18"></circle>'
    ];
    let offset = 0;
    slices.forEach((s) => {
        const frac = total > 0 ? Math.max(0, s.value) / total : 0;
        if (frac > 0 && s.key !== 'free') {
            parts.push(
                '<circle cx="' + size / 2 + '" cy="' + size / 2 + '" r="' + r +
                '" fill="none" stroke="' + _CTX_SLICE_COLORS[s.key] +
                '" stroke-width="' + stroke +
                '" stroke-dasharray="' + (frac * c) + ' ' + c +
                '" stroke-dashoffset="' + (-offset * c) + '"></circle>'
            );
        }
        offset += frac;
    });
    return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 ' + size + ' ' + size + '">' +
        '<g transform="rotate(-90 ' + size / 2 + ' ' + size / 2 + ')">' + parts.join('') + '</g></svg>';
}

// Render the mini pie into the composer button. The pie is always shown — an
// empty session is just a 0% (faint) ring — so the indicator reads
// consistently instead of flipping between an icon and a chart.
function _ctxRenderMiniPie(usage) {
    const holder = document.getElementById('ctx-pie-mini');
    if (!holder) return;
    holder.innerHTML = _ctxMiniPieSvg(usage);
}
// Latest usage snapshot, shared between the mini pie and the card so actions
// can refresh both without a refetch when the server returns fresh usage.
let _ctxLastUsage = null;
let _ctxPinned = false;      // clicked-open: stays until dismissed
let _ctxCompacting = false;  // a compaction request is in flight (locks input)

function installContextUsagePopover() {
    if (_ctxUsageInstalled) return;
    _ctxUsageInstalled = true;

    const btn = document.getElementById('clear-context-btn');
    if (!btn) return;

    _ctxUsageEl = document.createElement('div');
    _ctxUsageEl.className = 'ctx-usage-pop';
    document.body.appendChild(_ctxUsageEl);

    let hoverTimer = null;
    let hideTimer = null;

    const position = () => {
        const rect = btn.getBoundingClientRect();
        const elRect = _ctxUsageEl.getBoundingClientRect();
        let left = rect.left + rect.width / 2 - elRect.width / 2;
        left = Math.max(8, Math.min(left, window.innerWidth - elRect.width - 8));
        _ctxUsageEl.style.left = left + 'px';
        _ctxUsageEl.style.top = (rect.top - elRect.height - 8) + 'px';
    };

    const hideCard = () => {
        if (_ctxPinned) return;
        _ctxUsageEl.classList.remove('show');
    };
    // Expose a forced hide (used after pin dismiss / actions).
    _ctxHideCard = () => {
        _ctxPinned = false;
        _ctxUsageEl.classList.remove('show');
    };

    // Render the card from a usage payload (or the loading/empty state) and
    // show it. Keeps _ctxLastUsage in sync so the mini pie matches.
    _ctxShowCard = (usage) => {
        _ctxLastUsage = usage;
        btn.removeAttribute('data-tooltip');
        // Empty / error states are just one line, so shrink the card (compact
        // modifier) instead of showing a wide box padded around a single line.
        const isEmpty = !usage || usage.status === 'error' || !usage.available || !usage.breakdown;
        _ctxUsageEl.classList.toggle('ctx-usage-pop--compact', isEmpty && !_ctxCompacting);
        _ctxUsageEl.innerHTML = _ctxCompacting
            ? _ctxRenderCard(usage) + _ctxLoadingOverlay()
            : _ctxRenderCard(usage);
        _ctxUsageEl.classList.add('show');
        position();
    };

    // Fetch fresh usage and (re)draw the mini pie + card if open.
    _ctxRefresh = (opts) => {
        opts = opts || {};
        return fetch('/api/sessions/' + encodeURIComponent(sessionId) + '/context_usage')
            .then((r) => r.json())
            .then((data) => {
                const ok = data && data.status !== 'error';
                _ctxLastUsage = ok ? data : null;
                _ctxRenderMiniPie(_ctxLastUsage);
                // Always open/refresh the card (an empty session just shows the
                // "no context yet" state) so the pie and card read consistently.
                if (opts.openCard) {
                    _ctxShowCard(ok ? data : null);
                } else if (_ctxUsageEl.classList.contains('show') && !_ctxCompacting) {
                    _ctxShowCard(ok ? data : null);
                }
                return _ctxLastUsage;
            })
            .catch(() => {
                if (opts.openCard) _ctxShowCard(null);
                return null;
            });
    };

    // The pie is always the affordance now; no plain button tooltip.
    btn.removeAttribute('data-tooltip');

    // Hover: preview after a short delay. Does not pin.
    btn.addEventListener('mouseenter', () => {
        clearTimeout(hideTimer);
        clearTimeout(hoverTimer);
        hoverTimer = setTimeout(() => { _ctxRefresh({ openCard: true }); }, 120);
    });
    btn.addEventListener('mouseleave', () => {
        clearTimeout(hoverTimer);
        // Delay so the pointer can travel into the card without it vanishing.
        hideTimer = setTimeout(hideCard, 180);
    });
    // Click pins the card open (stays until an outside click / Esc).
    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        clearTimeout(hoverTimer);
        clearTimeout(hideTimer);
        // Toggle: a second click on an already-pinned card collapses it (but
        // never while a compaction is running — that would hide the spinner).
        if (_ctxPinned && _ctxUsageEl.classList.contains('show') && !_ctxCompacting) {
            _ctxHideCard();
            return;
        }
        _ctxPinned = true;
        _ctxRefresh({ openCard: true });
    });

    // The card itself is interactive: keep it open while hovered, and wire the
    // action buttons via delegation (innerHTML is rebuilt on every refresh).
    _ctxUsageEl.addEventListener('mouseenter', () => clearTimeout(hideTimer));
    _ctxUsageEl.addEventListener('mouseleave', () => {
        hideTimer = setTimeout(hideCard, 180);
    });
    _ctxUsageEl.addEventListener('click', (e) => {
        e.stopPropagation();
        const actBtn = e.target.closest('[data-ctx-action]');
        if (!actBtn) return;
        const action = actBtn.getAttribute('data-ctx-action');
        if (action === 'clear') _ctxDoClear();
        else if (action === 'compact') _ctxDoCompact();
        else if (action === 'adjust') _ctxDoAdjust();
    });

    // Dismiss a pinned card on outside click / Esc.
    document.addEventListener('click', (e) => {
        if (!_ctxPinned) return;
        if (_ctxUsageEl.contains(e.target) || btn.contains(e.target)) return;
        _ctxHideCard();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && _ctxPinned && !_ctxCompacting) _ctxHideCard();
    });

    window.addEventListener('scroll', () => { if (!_ctxPinned) _ctxUsageEl.classList.remove('show'); }, true);
    window.addEventListener('resize', () => { if (_ctxUsageEl.classList.contains('show')) position(); });

    // Prime the mini pie once on load so the button reflects state immediately.
    _ctxRefresh({});
}

// Module-scope handles set up inside installContextUsagePopover so the action
// helpers below can drive the card.
let _ctxShowCard = null;
let _ctxHideCard = null;
let _ctxRefresh = null;

function _ctxLoadingOverlay() {
    return '<div class="ctx-usage-loading"><span class="ctx-spinner"></span>' +
        '<span>' + t('ctx_compacting') + '</span></div>';
}

// --- Actions -----------------------------------------------------------

// True while a reply is streaming — clearing/compacting mid-turn would race
// the agent's own message list, so we block it and nudge the user to wait.
function _ctxTurnActive() {
    return typeof sendBtnMode !== 'undefined' && sendBtnMode === 'cancel' && !!activeRequestId;
}

function _ctxDoClear() {
    if (_ctxCompacting) return;
    if (_ctxTurnActive()) { _wsToast(t('ctx_busy_turn')); return; }
    clearContext();
    _ctxHideCard && _ctxHideCard();
    // clear_context drops the agent instance; reflect the empty state.
    _ctxLastUsage = null;
    _ctxRenderMiniPie(null);
}

function _ctxDoAdjust() {
    _ctxHideCard && _ctxHideCard();
    // Jump to the Agent config: scroll the whole Agent card into view (so its
    // heading is visible, not just the field), then highlight + focus the
    // budget input.
    if (typeof navigateTo === 'function') navigateTo('config');
    setTimeout(() => {
        const card = document.getElementById('config-agent-card');
        const el = document.getElementById('cfg-max-tokens');
        if (card) card.scrollIntoView({ behavior: 'smooth', block: 'start' });
        else if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        if (el) {
            el.focus({ preventScroll: true });
            el.classList.add('cfg-field-highlight');
            setTimeout(() => el.classList.remove('cfg-field-highlight'), 2000);
        }
    }, 250);
}

// Synchronous compaction: lock the composer + show a spinner on the card, then
// refresh the chart from the fresh usage the server returns.
function _ctxDoCompact() {
    if (_ctxCompacting) return;
    if (_ctxTurnActive()) { _wsToast(t('ctx_busy_turn')); return; }
    // Nothing to compact on an empty session.
    if (!_ctxLastUsage || !_ctxLastUsage.available) return;
    _ctxCompacting = true;
    _ctxPinned = true;
    _ctxSetComposerLocked(true);
    // Re-render current card with the loading overlay.
    if (_ctxShowCard) _ctxShowCard(_ctxLastUsage);

    fetch('/api/sessions/' + encodeURIComponent(sessionId) + '/compact_context', { method: 'POST' })
        .then((r) => r.json())
        .then((data) => {
            _ctxCompacting = false;
            _ctxSetComposerLocked(false);
            if (!data || data.status === 'error') {
                _wsToast(t('ctx_compact_failed'));
                if (_ctxRefresh) _ctxRefresh({ openCard: true });
                return;
            }
            if (data.ok) {
                // Drop a divider so the summarize is visible in the thread.
                const divider = document.createElement('div');
                divider.className = 'context-divider';
                divider.innerHTML = '<span>' + t('ctx_compacted_divider')
                    .replace('{before}', data.before || 0)
                    .replace('{after}', data.after || 0) + '</span>';
                messagesDiv.appendChild(divider);
                scrollChatToBottom();
            } else {
                _wsToast(t('ctx_compact_noop'));
            }
            // Redraw from returned usage (or refetch).
            if (data.usage) {
                _ctxLastUsage = data.usage;
                _ctxRenderMiniPie(_ctxLastUsage);
                if (_ctxShowCard && _ctxPinned) _ctxShowCard(_ctxLastUsage);
            } else if (_ctxRefresh) {
                _ctxRefresh({ openCard: _ctxPinned });
            }
        })
        .catch(() => {
            _ctxCompacting = false;
            _ctxSetComposerLocked(false);
            _wsToast(t('ctx_compact_failed'));
        });
}

// Lock/unlock the composer during synchronous compaction. Disables the input
// and send button; a page refresh is a safe escape hatch if it ever hangs.
function _ctxSetComposerLocked(locked) {
    try {
        if (chatInput) {
            chatInput.disabled = locked;
            chatInput.classList.toggle('ctx-input-locked', locked);
            if (locked) {
                chatInput.setAttribute('data-prev-ph', chatInput.placeholder || '');
                chatInput.placeholder = t('ctx_compacting');
            } else {
                const prev = chatInput.getAttribute('data-prev-ph');
                if (prev !== null) chatInput.placeholder = prev;
            }
        }
        if (sendBtn) {
            if (locked) sendBtn.disabled = true;
            // On unlock, let the normal enable/disable rule (empty input, etc.)
            // decide rather than force-enabling.
            else if (typeof updateSendBtnState === 'function') updateSendBtnState();
            else sendBtn.disabled = false;
        }
    } catch (_) {}
}

// =====================================================================
// Theme
// =====================================================================
let currentTheme = localStorage.getItem('cow_theme') || 'dark';

function applyTheme() {
    const root = document.documentElement;
    if (currentTheme === 'dark') {
        root.classList.add('dark');
        document.getElementById('theme-icon').className = 'fas fa-sun';
        document.getElementById('hljs-light').disabled = true;
        document.getElementById('hljs-dark').disabled = false;
    } else {
        root.classList.remove('dark');
        document.getElementById('theme-icon').className = 'fas fa-moon';
        document.getElementById('hljs-light').disabled = false;
        document.getElementById('hljs-dark').disabled = true;
    }
}

function toggleTheme() {
    currentTheme = currentTheme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('cow_theme', currentTheme);
    applyTheme();
}

// =====================================================================
// Task completion notification (client-side preference)
// =====================================================================
const TASK_NOTIFY_KEY = 'cow_task_notify';
const TASK_NOTIFY_SOUND_KEY = 'cow_task_notify_sound';
let taskNotifyEnabled = localStorage.getItem(TASK_NOTIFY_KEY) !== '0';
let taskNotifySound = localStorage.getItem(TASK_NOTIFY_SOUND_KEY) !== '0';
let notifyAudioCtx = null;
let unreadCount = 0;
const baseDocTitle = document.title;

// Unlock audio on the first user gesture; browsers block autoplay otherwise.
document.addEventListener('pointerdown', function() {
    if (window.AudioContext) notifyAudioCtx = notifyAudioCtx || new AudioContext();
    if (notifyAudioCtx && notifyAudioCtx.state === 'suspended') {
        notifyAudioCtx.resume().catch(function() {});
    }
}, { once: true });

function playNotifyBeep() {
    if (!taskNotifySound) return;
    try {
        if (!notifyAudioCtx) {
            const Ctx = window.AudioContext || window.webkitAudioContext;
            if (!Ctx) return;
            notifyAudioCtx = new Ctx();
        }
        if (notifyAudioCtx.state === 'suspended') {
            notifyAudioCtx.resume().catch(function() {});
        }
        // Two short sine tones (A5 → D6); no audio asset needed.
        const t0 = notifyAudioCtx.currentTime;
        [880, 1174.66].forEach(function(freq, i) {
            const at = t0 + i * 0.09;
            const osc = notifyAudioCtx.createOscillator();
            const gain = notifyAudioCtx.createGain();
            osc.type = 'sine';
            osc.frequency.value = freq;
            gain.gain.setValueAtTime(0.001, at);
            gain.gain.exponentialRampToValueAtTime(0.12, at + 0.01);
            gain.gain.exponentialRampToValueAtTime(0.001, at + 0.09);
            osc.connect(gain).connect(notifyAudioCtx.destination);
            osc.start(at);
            osc.stop(at + 0.1);
        });
    } catch (_) {
        // Autoplay still blocked or AudioContext unavailable; stay silent.
    }
}

function firstLineSnippet(text) {
    return (text || '').split('\n')[0].trim().slice(0, 80);
}

function sessionTitleOf(sid) {
    const el = document.querySelector(`.session-item[data-session-id="${sid}"] .session-title`);
    return el ? el.textContent.trim() : '';
}

function popNotification(title, body, sid, agentId) {
    if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return;
    try {
        const n = new Notification(title, { body: body || title });
        n.onclick = function() {
            window.focus();
            // The browser decides which tab a notification click activates, and
            // it may not be the one that popped it. So ask ALL tabs to open this
            // session (broadcastOpenSession) — whichever tab ends up foregrounded
            // is then already on the right conversation. Also covers the case
            // where this tab was on another view (e.g. scheduler config).
            if (sid) broadcastOpenSession(sid, agentId);
            n.close();
        };
    } catch (_) {
        // Notification API unavailable; beep + title badge still applied.
    }
}

function showTaskNotification(title, body, sid, agentId) {
    if (!taskNotifyEnabled) return;
    // Only notify when the window is not focused. If the user is actively
    // watching the tab, the reply is already on screen — a notification/beep
    // would just be noise (especially for short tasks).
    if (document.hasFocus()) return;
    playNotifyBeep();
    if (document.hidden) {
        unreadCount += 1;
        document.title = `(${unreadCount}) ${baseDocTitle}`;
    }
    if (typeof Notification === 'undefined') return;
    // First time we actually need to notify (window is in the background):
    // request permission now, then show this notification once granted. This
    // is more contextual than prompting on page load.
    if (Notification.permission === 'default') {
        Notification.requestPermission()
            .then(function(perm) {
                if (perm === 'granted') popNotification(title, body, sid, agentId);
                else refreshNotifyBlockedHint();
            })
            .catch(function() {});
        return;
    }
    if (Notification.permission === 'denied') {
        // Can't notify; surface the hint in settings so the user knows why.
        refreshNotifyBlockedHint();
        return;
    }
    popNotification(title, body, sid, agentId);
}

function notifyTaskFinished(sid, kind, text, agentId) {
    const label = t(kind === 'error' ? 'notify_task_error' : 'notify_task_done');
    const snippet = firstLineSnippet(text);
    showTaskNotification(sessionTitleOf(sid) || label, snippet ? `${label}: ${snippet}` : label, sid, agentId);
}

// The global runs poller is the single source of scheduler notifications (the
// /poll loop deliberately stays silent for scheduler pushes). A run can surface
// in overlapping poll windows AND — the important case — the SAME run is seen
// independently by EVERY open browser tab, each running its own poll loop. To
// pop exactly one notification per run across all tabs, the "already notified"
// set is persisted in localStorage (shared by all same-origin tabs) and the
// claiming tab broadcasts the id so peers drop it immediately (localStorage
// alone races when two ticks fire ~simultaneously in different tabs).
const _NOTIFIED_RUNS_KEY = 'cow_notified_run_ids';
const _NOTIFIED_RUNS_MAX = 500;
const _notifiedRunIds = new Set();   // in-memory mirror of the shared set

// Cross-tab channel: a tab that claims a run tells the others right away, and a
// notification click asks all tabs to open the target session (see
// broadcastOpenSession) — since the browser, not us, decides which tab a system
// notification click activates, every tab pre-navigates so whichever one comes
// to the foreground is already on the right conversation.
let _notifyBus = null;
try {
    if (typeof BroadcastChannel !== 'undefined') {
        _notifyBus = new BroadcastChannel('cow_scheduler_notify');
        _notifyBus.onmessage = (e) => {
            const data = e && e.data;
            if (!data) return;
            if (data.type === 'open-session' && data.sid) {
                // Another tab's notification was clicked. Open the session here
                // too so this tab is correct if the browser activates it. Guarded
                // to the chat view switch; no focus stealing (browser owns that).
                try { switchSession(data.sid, data.agentId || ''); } catch (_) {}
                return;
            }
            // Default (legacy) shape: a claimed run id.
            if (data.runId) _notifiedRunIds.add(data.runId);
        };
    }
} catch (_) { _notifyBus = null; }

// Tell every tab to open this session, then open it locally. Used on
// notification click so the tab the browser foregrounds is already correct.
function broadcastOpenSession(sid, agentId) {
    if (!sid) return;
    if (_notifyBus) {
        try { _notifyBus.postMessage({ type: 'open-session', sid, agentId: agentId || '' }); } catch (_) {}
    }
    try { switchSession(sid, agentId); } catch (_) {}
}

// Route a manual "run now" notification back to the tab the user clicked in.
// This tab records ownership in-memory (_manualRunOrigin); a shared localStorage
// marker (_MANUAL_ORIGIN_KEY) lets OTHER tabs know *some* tab owns it so they
// stay silent, without them mistakenly thinking they own it.
const _manualRunOrigin = {};          // task_id -> ts (this tab's own claims)
const _MANUAL_ORIGIN_KEY = 'cow_manual_run_origin';
const _MANUAL_ORIGIN_TTL = 120000;    // 2 min: long enough for the run to surface

function _claimManualRunOrigin(taskId) {
    const now = Date.now();
    _manualRunOrigin[taskId] = now;
    setTimeout(() => { delete _manualRunOrigin[taskId]; }, _MANUAL_ORIGIN_TTL);
    try {
        const raw = localStorage.getItem(_MANUAL_ORIGIN_KEY);
        const map = raw ? (JSON.parse(raw) || {}) : {};
        // Drop stale entries so the shared marker can't grow unbounded.
        for (const k of Object.keys(map)) {
            if (now - map[k] >= _MANUAL_ORIGIN_TTL) delete map[k];
        }
        map[taskId] = now;
        localStorage.setItem(_MANUAL_ORIGIN_KEY, JSON.stringify(map));
    } catch (_) {}
}

// True if any tab (this one or a peer, within the TTL) claimed a manual run for
// this task. Reads the shared marker written by _claimManualRunOrigin.
function _someTabOwnsManualRun(taskId) {
    if (_manualRunOrigin[taskId]) return true;
    try {
        const raw = localStorage.getItem(_MANUAL_ORIGIN_KEY);
        if (!raw) return false;
        const map = JSON.parse(raw) || {};
        const ts = map[taskId];
        return !!ts && (Date.now() - ts) < _MANUAL_ORIGIN_TTL;
    } catch (_) { return false; }
}

function _loadNotifiedRunIds() {
    try {
        const raw = localStorage.getItem(_NOTIFIED_RUNS_KEY);
        if (!raw) return [];
        const arr = JSON.parse(raw);
        return Array.isArray(arr) ? arr : [];
    } catch (_) { return []; }
}

function _persistNotifiedRunIds(ids) {
    try { localStorage.setItem(_NOTIFIED_RUNS_KEY, JSON.stringify(ids)); } catch (_) {}
}

function claimScheduledRunNotify(runId) {
    if (!runId) return true;         // no id -> can't dedupe, allow once

    // Fast path: this tab already saw it (own tick or a peer's broadcast).
    if (_notifiedRunIds.has(runId)) return false;

    // Re-read the shared set so a claim from another tab that happened between
    // our ticks is honoured even if its broadcast was missed.
    const shared = _loadNotifiedRunIds();
    for (const id of shared) _notifiedRunIds.add(id);
    if (_notifiedRunIds.has(runId)) return false;

    // Claim it: record locally, persist to the shared store, and tell peers.
    _notifiedRunIds.add(runId);
    shared.push(runId);
    // Bound growth; the poll only looks back a short window so trimmed ids
    // can never reappear.
    const trimmed = shared.length > _NOTIFIED_RUNS_MAX
        ? shared.slice(shared.length - _NOTIFIED_RUNS_MAX)
        : shared;
    _persistNotifiedRunIds(trimmed);
    if (_notifyBus) { try { _notifyBus.postMessage({ runId }); } catch (_) {} }
    return true;
}

// Force a scheduled-task notification regardless of window focus.
//
// showTaskNotification() suppresses itself when the window is focused, which is
// right for a normal reply the user is watching stream in. A scheduled task is
// different: it can fire into a session the user isn't currently viewing (or
// while they're looking at another app/tab), so if we don't notify they have no
// way to know it happened. This reuses the same popNotification() plumbing but
// skips the focus gate. Still honours the user's "Task Notifications" toggle.
function forceScheduledNotification(title, body, sid, agentId) {
    if (!taskNotifyEnabled) return;
    playNotifyBeep();
    if (document.hidden) {
        unreadCount += 1;
        document.title = `(${unreadCount}) ${baseDocTitle}`;
    }
    if (typeof Notification === 'undefined') return;
    if (Notification.permission === 'default') {
        Notification.requestPermission()
            .then(function(perm) {
                if (perm === 'granted') popNotification(title, body, sid, agentId);
                else refreshNotifyBlockedHint();
            })
            .catch(function() {});
        return;
    }
    if (Notification.permission === 'denied') {
        refreshNotifyBlockedHint();
        return;
    }
    popNotification(title, body, sid, agentId);
}

document.addEventListener('visibilitychange', function() {
    if (!document.hidden) {
        unreadCount = 0;
        document.title = baseDocTitle;
    }
});

// Request OS notification permission when notifications are enabled and the
// browser hasn't decided yet. Safe to call repeatedly.
function ensureNotifyPermission() {
    if (taskNotifyEnabled
        && typeof Notification !== 'undefined'
        && Notification.permission === 'default') {
        Notification.requestPermission().catch(function() {});
    }
}

// Show the "blocked by browser" hint only when notifications are enabled but
// the browser permission is denied (nothing the app can do about it in code).
function refreshNotifyBlockedHint() {
    const el = document.getElementById('cfg-task-notify-blocked');
    if (!el) return;
    const blocked = taskNotifyEnabled
        && typeof Notification !== 'undefined'
        && Notification.permission === 'denied';
    el.classList.toggle('hidden', !blocked);
}

function initTaskNotifyToggles() {
    const notifyEl = document.getElementById('cfg-task-notify');
    if (notifyEl) {
        notifyEl.checked = taskNotifyEnabled;
        notifyEl.addEventListener('change', function() {
            taskNotifyEnabled = notifyEl.checked;
            localStorage.setItem(TASK_NOTIFY_KEY, taskNotifyEnabled ? '1' : '0');
            ensureNotifyPermission();
            refreshNotifyBlockedHint();
        });
    }
    const soundEl = document.getElementById('cfg-task-notify-sound');
    if (soundEl) {
        soundEl.checked = taskNotifySound;
        soundEl.addEventListener('change', function() {
            taskNotifySound = soundEl.checked;
            localStorage.setItem(TASK_NOTIFY_SOUND_KEY, taskNotifySound ? '1' : '0');
        });
    }
    refreshNotifyBlockedHint();
}

document.addEventListener('DOMContentLoaded', initTaskNotifyToggles);

// =====================================================================
// Sidebar & Navigation
// =====================================================================
const VIEW_META = {
    chat:     { group: 'nav_chat',    page: 'menu_chat' },
    agents:   { group: 'nav_manage',  page: 'menu_agents' },
    config:   { group: 'nav_manage',  page: 'menu_config' },
    skills:   { group: 'nav_manage',  page: 'menu_skills' },
    memory:   { group: 'nav_manage',  page: 'menu_memory' },
    knowledge:{ group: 'nav_manage',  page: 'menu_knowledge' },
    channels: { group: 'nav_manage',  page: 'menu_channels' },
    tasks:    { group: 'nav_manage',  page: 'menu_tasks' },
    logs:     { group: 'nav_monitor', page: 'menu_logs' },
};

let currentView = 'chat';

function navigateTo(viewId) {
    if (!VIEW_META[viewId]) return;
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    const target = document.getElementById('view-' + viewId);
    if (target) target.classList.add('active');
    document.querySelectorAll('.sidebar-item').forEach(item => {
        item.classList.toggle('active', item.dataset.view === viewId);
    });
    const meta = VIEW_META[viewId];
    document.getElementById('breadcrumb-group').textContent = t(meta.group);
    document.getElementById('breadcrumb-group').dataset.i18n = meta.group;
    document.getElementById('breadcrumb-page').textContent = t(meta.page);
    document.getElementById('breadcrumb-page').dataset.i18n = meta.page;
    const leavingAgents = currentView === 'agents' && viewId !== 'agents';
    currentView = viewId;
    // The Agent detail is a fixed drawer, so it would otherwise hang over
    // whatever view you navigate to. It only belongs to the Agent Team page.
    if (viewId !== 'agents') closeAgentDetail();
    if (viewId === 'agents') {
        // The team page is a wide two-pane workbench; the history panel on top
        // of it would leave the detail cramped. Tuck it away on entry and put it
        // back the way it was when the user leaves (only if they hadn't already
        // toggled it themselves in the meantime).
        _sessionPanelWasOpen = sessionPanelOpen;
        if (sessionPanelOpen) closeSessionPanel(true);
        loadAgentCatalog();
    } else if (leavingAgents && _sessionPanelWasOpen) {
        _sessionPanelWasOpen = false;
        openSessionPanel();
    }
    
    // Clear status messages when navigating away
    document.querySelectorAll('[id$="-status"]').forEach(el => {
        el.classList.add('opacity-0');
    });
    
    if (window.innerWidth < 1024) closeSidebar();
}

function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebar-overlay');
    const isOpen = !sidebar.classList.contains('-translate-x-full');
    if (isOpen) {
        closeSidebar();
    } else {
        sidebar.classList.remove('-translate-x-full');
        overlay.classList.remove('hidden');
    }
}

function closeSidebar() {
    document.getElementById('sidebar').classList.add('-translate-x-full');
    document.getElementById('sidebar-overlay').classList.add('hidden');
}

document.querySelectorAll('.menu-group > button').forEach(btn => {
    btn.addEventListener('click', () => {
        btn.parentElement.classList.toggle('open');
    });
});

document.querySelectorAll('.sidebar-item').forEach(item => {
    item.addEventListener('click', () => navigateTo(item.dataset.view));
});

window.addEventListener('resize', () => {
    if (window.innerWidth >= 1024) {
        document.getElementById('sidebar').classList.remove('-translate-x-full');
        document.getElementById('sidebar-overlay').classList.add('hidden');
    } else {
        if (!document.getElementById('sidebar').classList.contains('-translate-x-full')) {
            closeSidebar();
        }
    }
});

// =====================================================================
// Agents
// =====================================================================
let agentCatalog = [];
let channelInstances = [];
let rosterRevision = '';
let defaultAgentId = localStorage.getItem('cow_default_agent') || 'default';
let selectedAdminAgentId = '';
let selectedCoreRevision = '';
let installedSkills = [];

function findAgent(agentId) {
    return agentCatalog.find(a => a.id === agentId) || null;
}

function enabledAgents() {
    return agentCatalog.filter(a => a.enabled);
}

/* An uploaded avatar reuses the same URL every time, so the browser would keep
   serving the stale bytes. The roster revision only moves when the roster's
   *content* changes, and re-uploading over an existing image leaves the field as
   the same "image" token — so we stamp each successful upload with a fresh token
   here and prefer it, which forces the one re-fetch that shows the new picture. */
const avatarVersions = {};

/* How many muted discs the initials fallback cycles through. */
const AVATAR_TONES = 6;

/* Which disc an Agent gets. Keyed off the id alone, so a face never changes
   colour once the Agent exists, and so a draft in the create modal (no id yet)
   sits on the neutral tone instead of shifting as its name is typed. */
function avatarTone(agentId) {
    const key = String(agentId || '');
    let hash = 0;
    for (let i = 0; i < key.length; i++) hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
    return hash % AVATAR_TONES;
}

/* The character an Agent is shown by when it has no picture. Array.from rather
   than [0] so an astral-plane character is taken whole instead of as half a
   surrogate pair; uppercased for latin, left alone for scripts without case. */
function avatarInitial(name) {
    return (Array.from(String(name || '').trim())[0] || '').toUpperCase();
}

/* Every Agent wears its own face: the image its owner uploaded, or a muted disc
   carrying the first character of its name. Initials rather than the product
   logo so a team is distinguishable at a glance, and low-saturation tones so a
   roster of them stays quiet.

   A null agent means the id no longer resolves - a conversation pinned to a
   since-deleted Agent. Fall back to the default Agent's face rather than an
   empty disc, so the deleted Agent visibly degrades to the default one. */
function agentAvatarHTML(agent, size) {
    const cls = `agent-avatar agent-avatar-${size || 32}`;
    if (!agent && defaultAgentId) {
        agent = findAgent(defaultAgentId);
    }
    if (agent && agent.avatar === 'image') {
        // Prefer the server's per-file token (avatar mtime): it changes on every
        // upload, so replacing a picture busts the cache even after a hard reload
        // when in-memory hints are gone and the roster revision hasn't moved.
        const v = avatarVersions[agent.id] || agent.avatar_rev || rosterRevision || agent.id;
        return `<img class="${cls}" src="/api/agents/${encodeURIComponent(agent.id)}/avatar?v=${encodeURIComponent(v)}" alt="">`;
    }
    // The default (first) Agent falls back to the product logo when it has no
    // uploaded picture, so the instance's own Agent wears the CowAgent face.
    // Added Agents keep the initial-disc fallback so a team stays distinguishable.
    if (agent && agent.id && agent.id === defaultAgentId) {
        return `<img class="${cls}" src="assets/logo.jpg" alt="">`;
    }
    const initial = avatarInitial(agent && (agent.name || agent.id));
    return `<span class="${cls} agent-avatar-tone-${avatarTone(agent && agent.id)}">${escapeHtml(initial)}</span>`;
}

/* Repaint the faces on bubbles already on screen. Bubbles are rendered once and
   left alone, so an avatar changed in Settings would otherwise keep showing the
   old picture in the open conversation until reload. Each bot bubble remembers
   its speaker; the loading indicator follows the active Agent. */
function refreshBubbleAvatars() {
    const container = document.getElementById('chat-messages');
    if (!container) return;
    container.querySelectorAll('.bot-face').forEach(face => {
        const group = face.closest('.bot-message-group');
        // A bubble knows its speaker; the loading indicator (no group) tracks the
        // active Agent, the only one that can be mid-reply in a solo chat.
        const id = (group && group.dataset.speakerAgent) || activeAgentId;
        face.innerHTML = agentAvatarHTML(findAgent(id), 32);
    });
}

// Derive the ascii slug from a name, or '' when there is no ascii to work with
// (e.g. a name written in Chinese). Callers fall back to randomAgentId().
function slugAgentId(name) {
    return String(name || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 32);
}

// An id for a name that yields no slug.
function randomAgentId() {
    return 'agent-' + Math.random().toString(36).slice(2, 8);
}

function loadAgentCatalog() {
    return fetch('/api/agents')
        .then(r => r.json())
        .then(data => {
            if (data.status !== 'success') throw new Error(data.message || 'Failed to load Agents');
            agentCatalog = data.agents || [];
            channelInstances = data.channel_instances || [];
            rosterRevision = data.revision || '';
            defaultAgentId = data.default_agent_id || (agentCatalog[0] && agentCatalog[0].id) || 'default';
            localStorage.setItem('cow_default_agent', defaultAgentId);
            // The default Agent leads every list it appears in — menus, the grid,
            // the memory picker — so its position never depends on load order.
            agentCatalog.sort((a, b) => (b.id === defaultAgentId) - (a.id === defaultAgentId));
            const enabled = enabledAgents();
            if (!enabled.some(a => a.id === activeAgentId)) {
                activeAgentId = defaultAgentId;
                localStorage.setItem('cow_active_agent', activeAgentId);
            }
            if (!selectedAdminAgentId || !agentCatalog.some(a => a.id === selectedAdminAgentId)) {
                selectedAdminAgentId = '';
            }
            // Two-pane workbench: on a wide screen, land on the first Agent so the
            // right pane is never a blank placeholder. On a phone the list shows
            // first (the detail is a sheet), so leave nothing selected there.
            if (!selectedAdminAgentId && currentView === 'agents'
                    && agentCatalog.length && window.innerWidth > 900) {
                openAgentDetail((enabledAgents()[0] || agentCatalog[0]).id);
                return data;
            }
            renderAgentsGrid();
            if (selectedAdminAgentId) renderAgentDetail();
            else closeAgentDetail();
            renderComposerIdentity();
            renderMemoryAgentSelect();
            // The new-chat button only sprouts a menu (and its caret) once there
            // is more than one Agent to choose between.
            document.getElementById('new-chat-caret')?.classList.toggle('hidden', !multiAgentMode());
            // A name or avatar may have changed; keep faces already on screen in
            // sync with the roster instead of only new bubbles.
            refreshBubbleAvatars();
            return data;
        })
        .catch(err => {
            const status = document.getElementById('agent-editor-status');
            if (status) status.textContent = err.message;
        });
}

function renderAgentsGrid() {
    const grid = document.getElementById('agents-grid');
    if (!grid) return;
    if (!agentCatalog.length) {
        grid.innerHTML = `<div class="col-span-full text-sm text-slate-400 py-16 text-center">${escapeHtml(t('agents_empty'))}</div>`;
        return;
    }
    grid.innerHTML = agentCatalog.map(agent => {
        const selected = agent.id === selectedAdminAgentId;
        const desc = (agent.description || '').trim();
        // Status chips float in the top-right corner so a "default" or
        // "archived" card is exactly as tall as every other card.
        const corner = agent.id === defaultAgentId
            ? `<span class="agent-card-badge agent-chip-on">${escapeHtml(t('agents_default'))}</span>`
            : (!agent.enabled ? `<span class="agent-card-badge">${escapeHtml(t('agents_archived'))}</span>` : '');
        return `<div class="agent-card${selected ? ' selected' : ''}${agent.enabled ? '' : ' archived'}" onclick="openAgentDetail('${escapeHtml(agent.id)}')">
            ${corner}
            <div class="agent-card-top">
                ${agentAvatarHTML(agent, 32)}
                <div class="min-w-0 flex-1">
                    <div class="agent-card-name truncate">${escapeHtml(agent.name)}</div>
                    <div class="agent-card-desc">${desc ? escapeHtml(desc) : `<span class="agent-card-desc-empty">${escapeHtml(t('agents_no_desc'))}</span>`}</div>
            </div>
            </div>
        </div>`;
    }).join('');
}

function openAgentDetail(agentId) {
    selectedAdminAgentId = agentId;
    document.getElementById('agent-detail')?.classList.remove('hidden');
    renderAgentsGrid();
    renderAgentDetail();
    // Reset the core-file picker to a clean state per Agent, rather than
    // carrying over whichever file/view mode was left selected for the
    // previous one.
    const fileDd = document.getElementById('agent-core-file');
    if (fileDd) fileDd._ddValue = 'AGENT.md';
    setAgentCoreViewMode('edit');
    loadAgentCoreFile();
    // The model picker is drawn from the same catalog the composer uses, which
    // depends on which providers have keys. Re-render once it has arrived.
    if (!_sessCfg) refreshSessionSettings().then(() => {
        if (selectedAdminAgentId === agentId) renderAgentDetail();
    });
}

function closeAgentDetail() {
    selectedAdminAgentId = '';
    const detail = document.getElementById('agent-detail');
    if (detail) {
        detail.classList.add('hidden');
        // The empty pane's placeholder text (desktop two-pane layout).
        detail.setAttribute('data-empty-label', t('agents_select_hint'));
    }
    renderAgentsGrid();
}

function selectAgentDetailTab(tab) {
    document.querySelectorAll('.agent-detail-tab').forEach(el => {
        el.classList.toggle('active', el.dataset.tab === tab);
    });
    ['profile', 'skills', 'files'].forEach(name => {
        document.getElementById(`agent-detail-${name}`)?.classList.toggle('hidden', name !== tab);
    });
    if (tab === 'skills') renderAgentSkillsPane();
    if (tab === 'files') loadAgentCoreFile();
}

// A field label followed by a small info icon whose help shows on hover, so a
// form stays compact instead of carrying a paragraph of hint under every field.
// The tip text may contain \n to force a line break (e.g. one line per option
// of a shared/own choice) — rendered via the popup's `white-space: pre-line`.
function fieldLabelWithTip(label, tip) {
    return `<div class="agent-field-label-row">
        <label class="agent-field-label">${escapeHtml(label)}</label>
        <span class="agent-field-tip" data-tip="${escapeHtml(tip)}"><i class="fas fa-circle-info"></i></span>
    </div>`;
}

// Single popup instance fixed to <body>, positioned relative to whichever
// .agent-field-tip is hovered. Living outside every drawer/modal means it is
// never clipped by an ancestor's `overflow: auto` (unlike a CSS ::after would
// be inside the scrolling Agent detail pane).
let _fieldTipEl = null;
let _fieldTipIcon = null;  // which icon the popup currently belongs to
function _ensureFieldTipEl() {
    if (!_fieldTipEl) {
        _fieldTipEl = document.createElement('div');
        _fieldTipEl.className = 'agent-tip-popup';
        document.body.appendChild(_fieldTipEl);
    }
    return _fieldTipEl;
}

function _showFieldTip(iconEl) {
    const tip = iconEl.dataset.tip;
    if (!tip) return;
    // Already showing for this icon: don't re-measure/re-animate. Moving the
    // cursor from the <span> onto its own <i> would otherwise re-trigger the
    // whole show sequence and make the tip visibly flicker.
    if (_fieldTipIcon === iconEl && _fieldTipEl && _fieldTipEl.classList.contains('show')) return;
    _fieldTipIcon = iconEl;
    const popup = _ensureFieldTipEl();
    popup.textContent = tip;
    popup.classList.remove('show');
    popup.style.left = '0px';
    popup.style.top = '0px';
    // Measure after layout so width/height reflect the actual (possibly
    // multi-line) content before we clamp it into the viewport.
    requestAnimationFrame(() => {
        const rect = iconEl.getBoundingClientRect();
        const pw = popup.offsetWidth, ph = popup.offsetHeight;
        let left = rect.left + rect.width / 2 - pw / 2;
        const margin = 8;
        left = Math.max(margin, Math.min(left, window.innerWidth - pw - margin));
        let top = rect.top - ph - 8;
        let arrowTop = false;
        if (top < margin) { top = rect.bottom + 8; arrowTop = true; } // flip below if clipped above
        popup.style.left = `${left}px`;
        popup.style.top = `${top}px`;
        popup.style.setProperty('--tip-arrow-x', `${rect.left + rect.width / 2 - left}px`);
        popup.classList.toggle('tip-arrow-top', arrowTop);
        popup.classList.add('show');
    });
}

function _hideFieldTip() {
    if (_fieldTipEl) _fieldTipEl.classList.remove('show');
    _fieldTipIcon = null;
}

document.addEventListener('mouseover', (e) => {
    const icon = e.target.closest ? e.target.closest('.agent-field-tip') : null;
    if (icon) _showFieldTip(icon);
});
document.addEventListener('mouseout', (e) => {
    const icon = e.target.closest ? e.target.closest('.agent-field-tip') : null;
    if (!icon) return;
    // mouseout fires when moving between the icon's own children (span -> <i>).
    // Only hide when the cursor actually leaves this icon's subtree, i.e. the
    // element it moved to isn't inside the same .agent-field-tip.
    const to = e.relatedTarget;
    if (to && icon.contains(to)) return;
    _hideFieldTip();
});
document.addEventListener('scroll', _hideFieldTip, true);

function renderAgentDetail() {
    const agent = findAgent(selectedAdminAgentId);
    const identity = document.getElementById('agent-detail-identity');
    const profile = document.getElementById('agent-detail-profile');
    if (!agent || !identity || !profile) return;
    identity.innerHTML = `
        ${agentAvatarHTML(agent, 56)}
        <div class="min-w-0">
            <div class="text-lg font-semibold text-slate-800 dark:text-slate-100 truncate">${escapeHtml(agent.name)}</div>
            <div class="text-xs text-slate-400 font-mono truncate">${escapeHtml(agent.id)}</div>
        </div>`;
    const isDefault = agent.id === defaultAgentId;
    profile.innerHTML = `
        <div class="agent-field">
            <label class="agent-field-label">${escapeHtml(t('agents_avatar'))}</label>
            <div id="agent-edit-avatar" class="agent-avatar-picker"></div>
        </div>
        <div class="agent-field">
            <label class="agent-field-label">${escapeHtml(t('agents_name'))}</label>
            <input id="agent-edit-name" value="${escapeHtml(agent.name)}" class="agent-input">
        </div>
        <div class="agent-field">
            ${fieldLabelWithTip(t('agents_description'), t('agents_description_hint'))}
            <textarea id="agent-edit-description" rows="4"
                   placeholder="${escapeHtml(t('agents_description_placeholder'))}"
                   class="agent-input agent-textarea">${escapeHtml(agent.description || '')}</textarea>
        </div>
        <div class="agent-field">
            <label class="agent-field-label">${escapeHtml(t('agents_model'))}</label>
            ${isDefault
                ? `<div class="agent-input-locked">${escapeHtml(t('agents_model_follows_global'))}</div>
                   <p class="agent-field-hint">${escapeHtml(t('agents_model_default_hint'))}</p>`
                : `<div id="agent-edit-model" class="cfg-dropdown" tabindex="0">
                       <div class="cfg-dropdown-selected">
                           <span class="cfg-dropdown-text">--</span>
                           <i class="fas fa-chevron-down cfg-dropdown-arrow"></i>
                       </div>
                       <div class="cfg-dropdown-menu"></div>
                   </div>`}
        </div>
        ${isDefault ? '' : `
        <div class="agent-field">
            ${fieldLabelWithTip(t('agents_knowledge'), t('agents_knowledge_hint'))}
            <div class="flex items-center gap-3">
                <div id="agent-knowledge-toggle" class="agent-seg" role="group">
                    <button type="button" class="agent-seg-btn ${agent.knowledge_mode !== 'own' ? 'active' : ''}" data-mode="shared" onclick="setAgentKnowledgeMode('${escapeHtml(agent.id)}','shared')">
                        <i class="fas fa-users mr-1"></i>${escapeHtml(t('agents_knowledge_shared'))}
                    </button>
                    <button type="button" class="agent-seg-btn ${agent.knowledge_mode === 'own' ? 'active' : ''}" data-mode="own" onclick="setAgentKnowledgeMode('${escapeHtml(agent.id)}','own')">
                        <i class="fas fa-box-archive mr-1"></i>${escapeHtml(t('agents_knowledge_own'))}
                    </button>
                </div>
                <span id="agent-knowledge-status" class="agent-field-hint" style="margin-top:0"></span>
            </div>
        </div>`}
        <div class="agent-detail-actions">
            <button type="button" onclick="saveAgentProfile()" class="agent-btn agent-btn-primary">${escapeHtml(t('save'))}</button>
            <button type="button" onclick="startChatWithAgent('${escapeHtml(agent.id)}')" class="agent-btn agent-btn-ghost">${escapeHtml(t('agents_chat'))}</button>
            ${isDefault ? '' : `<button type="button" onclick="deleteAgent('${escapeHtml(agent.id)}')" class="agent-btn agent-btn-danger agent-detail-delete">${escapeHtml(t('agents_delete'))}</button>`}
        </div>
        <div id="agent-profile-status" class="agent-field-hint mt-3"></div>`;

    renderAvatarPicker('agent-edit-avatar', agent, (file) => uploadAgentAvatar(agent.id, file));

    if (!isDefault) {
        const dd = document.getElementById('agent-edit-model');
        const opts = agentModelDropdownOptions();
        const current = agent.model ? `${agent.bot_type || ''}|${agent.model}` : '';
        initDropdown(dd, opts, current, () => {}, { placeholder: t('agents_model_follows_global') });
    }
    // A save may re-render this pane several times; re-apply an in-flight
    // "saved" confirmation so it survives instead of being wiped.
    paintAgentSavedFlash();
}

/* A live preview beside an upload button, in the page's own styling rather than
   a raw file input. The default is the Agent's initial; uploading swaps it for
   the chosen image. `onUpload` may be null when the Agent does not exist yet
   (the create modal), leaving just the preview. */
function renderAvatarPicker(containerId, agent, onUpload) {
    const box = document.getElementById(containerId);
    if (!box) return;
    box.innerHTML = `
        <div class="agent-avatar-picker-preview">${agentAvatarHTML(agent, 56)}</div>
        <div class="agent-avatar-picker-body">
            ${onUpload ? `<button type="button" class="agent-avatar-upload">
                <i class="fas fa-arrow-up-from-bracket"></i><span>${escapeHtml(t('agents_avatar_upload'))}</span>
                <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden>
            </button>` : ''}
        </div>`;
    const upload = box.querySelector('.agent-avatar-upload');
    if (upload && onUpload) {
        const input = upload.querySelector('input');
        upload.addEventListener('click', () => input.click());
        input.addEventListener('change', () => onUpload(input.files && input.files[0]));
    }
}

/* Flattened for the styled dropdown: one row per model, its provider carried in
   the value (a model asked of the wrong vendor is an error), its brand shown as
   a dim hint. The first row clears the choice back to the configured model. */
function agentModelDropdownOptions() {
    const opts = [{ value: '', label: t('agents_model_follows_global') }];
    const providers = (_sessCfg && _sessCfg.model && _sessCfg.model.providers) || [];
    providers.forEach(p => {
        (p.models || []).forEach(m => {
            opts.push({ value: `${p.id}|${m}`, label: m, hint: localizedLabel(p.label) });
        });
    });
    return opts;
}

// Persist an Agent's skill selection. Writes are serialized per Agent and
// coalesce to the latest desired state, so ticking several boxes quickly sends
// them in order (each with the revision the previous one returned) instead of
// racing and tripping the stale-roster guard. No catalog reload happens, so the
// grid, composer and avatars never flicker and the checkboxes never jump.
//   null  -> use every installed skill (the "use all" master toggle)
//   [...] -> exactly this subset ([] means none)
const _skillSaveState = {};  // agentId -> { inflight: bool, pending: skills|undefined }

function saveAgentSkills(agent, skills) {
    agent.skills = skills;  // optimistic; the pane already reflects it
    const st = _skillSaveState[agent.id] || (_skillSaveState[agent.id] = { inflight: false, pending: undefined });
    if (st.inflight) { st.pending = skills; return; }  // newest wins; drop stale intermediate
    st.inflight = true;
    fetch('/api/agents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'update', id: agent.id, revision: rosterRevision, skills }),
    }).then(r => r.json()).then(data => {
        if (data.status === 'success') {
            if (data.revision) rosterRevision = data.revision;
        } else {
            const status = document.getElementById('agent-editor-status');
            if (status) status.textContent = data.message || 'Update failed';
        }
    }).catch(() => {}).then(() => {
        st.inflight = false;
        if (st.pending !== undefined) {
            const next = st.pending;
            st.pending = undefined;
            saveAgentSkills(agent, next);  // flush the latest queued state
        }
    });
}

// Switch an Agent between the shared knowledge base and its own. This is a
// filesystem toggle (symlink vs a real knowledge/ dir), so it applies at once
// rather than waiting for the profile "save".
async function setAgentKnowledgeMode(agentId, mode) {
    const agent = findAgent(agentId);
    if (!agent || agent.knowledge_mode === mode) return;
    const status = document.getElementById('agent-knowledge-status');
    const paintActive = (m) => document.querySelectorAll('#agent-knowledge-toggle .agent-seg-btn')
        .forEach(b => b.classList.toggle('active', b.dataset.mode === m));
    const prev = agent.knowledge_mode || 'shared';
    agent.knowledge_mode = mode;  // optimistic
    paintActive(mode);
    if (status) status.textContent = t('agents_knowledge_working') || '...';
    try {
        const res = await fetch('/api/agents', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'set_knowledge_mode', id: agentId, mode }),
        });
        const data = await res.json();
        if (data.status === 'success') {
            agent.knowledge_mode = (data.mode || mode);
            paintActive(agent.knowledge_mode);
            if (status) status.textContent = '';
        } else {
            agent.knowledge_mode = prev;  // roll back
            paintActive(prev);
            if (status) status.textContent = data.message || t('agents_knowledge_failed') || 'Failed';
        }
    } catch (e) {
        agent.knowledge_mode = prev;
        paintActive(prev);
        if (status) status.textContent = t('agents_knowledge_failed') || 'Failed';
    }
}

function renderAgentSkillsPane() {
    const pane = document.getElementById('agent-detail-skills');
    const agent = findAgent(selectedAdminAgentId);
    if (!pane || !agent) return;
    const render = () => {
        const all = agent.skills == null;
        const picked = new Set(all ? [] : agent.skills);
        pane.innerHTML = `
            <label class="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300 mb-3">
                <input type="checkbox" id="agent-skills-all" ${all ? 'checked' : ''}>
                <span>${escapeHtml(t('agents_skills_all'))}</span>
            </label>
            <p class="text-xs text-slate-400 mb-3">${escapeHtml(t('agents_skills_pick'))}</p>
            ${(installedSkills || []).map(skill => {
                const name = skill.name || skill.id;
                const checked = all || picked.has(name);
                return `<label class="agent-skill-row">
                    <input type="checkbox" class="agent-skill-item" value="${escapeHtml(name)}" ${checked ? 'checked' : ''} ${all ? 'disabled' : ''}>
                    <div>
                        <div class="text-sm text-slate-700 dark:text-slate-200">${escapeHtml(skill.display_name || name)}</div>
                        <div class="text-xs text-slate-400">${escapeHtml(skill.description || '')}</div>
                    </div>
                </label>`;
            }).join('')}`;
        document.getElementById('agent-skills-all')?.addEventListener('change', (e) => {
            // Toggle only flips ALL <-> empty subset. Turning it off starts from
            // an empty list so the user picks up exactly what they want, and the
            // stored value is [] rather than a full enumeration.
            const next = e.target.checked ? null : [];
            saveAgentSkills(agent, next);
            render();  // repaint in place — no page-wide reload, no flicker
        });
        pane.querySelectorAll('.agent-skill-item').forEach(box => {
            box.addEventListener('change', () => {
                const names = Array.from(pane.querySelectorAll('.agent-skill-item:checked')).map(el => el.value);
                saveAgentSkills(agent, names);
            });
        });
    };
    if (installedSkills.length) {
        render();
        return;
    }
    fetch('/api/skills').then(r => r.json()).then(data => {
        installedSkills = data.skills || [];
        render();
    }).catch(() => {
        pane.innerHTML = `<p class="text-sm text-slate-400">${escapeHtml(t('agents_skills_all'))}</p>`;
    });
}

// Held between opening the create modal and a successful create: the chosen
// avatar has nowhere to live server-side until the Agent exists, so we keep the
// File and its preview URL client-side and upload once creation returns.
let _pendingCreateAvatar = null;
let _createKnowledgeMode = 'shared';

// What the Agent being filled in would look like: no id yet, so the disc is the
// neutral tone and only the initial follows the name.
function createAvatarDraft() {
    const name = document.getElementById('agent-create-name');
    return { id: '', name: (name && name.value) || '', avatar: '' };
}

// Repaint just the preview disc as the name is typed. The whole picker is not
// re-rendered because that would rebind the upload input on every keystroke.
function refreshCreateAvatarPreview() {
    if (_pendingCreateAvatar) return;
    const slot = document.querySelector('#agent-create-avatar .agent-avatar-picker-preview');
    if (slot) slot.innerHTML = agentAvatarHTML(createAvatarDraft(), 56);
}

// The create modal's avatar picker: same look as the edit one, but the upload
// is staged locally (preview from an object URL) instead of POSTed immediately.
function renderCreateAvatarPicker() {
    const box = document.getElementById('agent-create-avatar');
    if (!box) return;
    const preview = _pendingCreateAvatar
        ? `<img class="agent-avatar agent-avatar-56" src="${_pendingCreateAvatar.url}" alt="">`
        : agentAvatarHTML(createAvatarDraft(), 56);
    box.innerHTML = `
        <div class="agent-avatar-picker-preview">${preview}</div>
        <div class="agent-avatar-picker-body">
            <button type="button" class="agent-avatar-upload">
                <i class="fas fa-arrow-up-from-bracket"></i><span>${escapeHtml(t('agents_avatar_upload'))}</span>
                <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden>
            </button>
        </div>`;
    const upload = box.querySelector('.agent-avatar-upload');
    const input = upload.querySelector('input');
    upload.addEventListener('click', () => input.click());
    input.addEventListener('change', () => {
        const file = input.files && input.files[0];
        if (!file) return;
        if (_pendingCreateAvatar && _pendingCreateAvatar.url) URL.revokeObjectURL(_pendingCreateAvatar.url);
        _pendingCreateAvatar = { file, url: URL.createObjectURL(file) };
        renderCreateAvatarPicker();
    });
}

function openAgentCreateForm() {
    const form = document.getElementById('agent-create-form');
    if (!form) return;
    form.classList.remove('hidden');
    const name = document.getElementById('agent-create-name');
    // The id is typed by hand or left blank on purpose; nothing writes to it
    // while the form is open. A blank one is filled in once, at submit.
    const id = document.getElementById('agent-create-id');
    const description = document.getElementById('agent-create-description');
    [name, id, description].forEach(el => { if (el) el.value = ''; });
    document.getElementById('agent-create-status').textContent = '';

    // The Agent has no home to store an avatar in yet, so the upload is held in
    // memory and previewed locally; it is POSTed the moment creation succeeds.
    _pendingCreateAvatar = null;
    renderCreateAvatarPicker();
    if (name && !name.dataset.avatarBound) {
        name.dataset.avatarBound = '1';
        // Without an upload the face is the name's first character, so the
        // preview has to follow what is being typed.
        name.addEventListener('input', refreshCreateAvatarPreview);
    }

    // Knowledge defaults to shared; reset the segmented control on every open.
    _createKnowledgeMode = 'shared';
    document.querySelectorAll('#agent-create-knowledge .agent-seg-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.mode === 'shared');
        if (!b.dataset.bound) {
            b.dataset.bound = '1';
            b.addEventListener('click', () => {
                _createKnowledgeMode = b.dataset.mode;
                document.querySelectorAll('#agent-create-knowledge .agent-seg-btn')
                    .forEach(x => x.classList.toggle('active', x === b));
            });
        }
    });

    const clone = document.getElementById('agent-create-clone');
    if (clone) {
        // Options carry the agent so both the row and the trigger show its
        // avatar + name; "blank" (no clone) has no face.
        const opts = [{ value: '', label: t('agents_clone_none') }].concat(
            enabledAgents().map(a => ({
                value: a.id,
                label: a.name || a.id,
                agent: a,
            }))
        );
        initDropdown(clone, opts, '', () => {});
    }
}

function closeAgentCreateForm() {
    document.getElementById('agent-create-form')?.classList.add('hidden');
    if (_pendingCreateAvatar && _pendingCreateAvatar.url) URL.revokeObjectURL(_pendingCreateAvatar.url);
    _pendingCreateAvatar = null;
}

document.addEventListener('click', (e) => {
    const menu = document.getElementById('composer-agent-menu');
    const btn = document.getElementById('composer-agent-btn');
    if (menu && !menu.classList.contains('hidden') && !menu.contains(e.target) && btn && !btn.contains(e.target)) {
        menu.classList.add('hidden');
    }
    const modal = document.getElementById('agent-create-form');
    if (modal && !modal.classList.contains('hidden') && e.target === modal) {
        closeAgentCreateForm();
    }
    const newMenu = document.getElementById('new-chat-menu');
    const newWrap = document.querySelector('.session-panel-new-wrap');
    if (newMenu && !newMenu.classList.contains('hidden') && newWrap && !newWrap.contains(e.target)) {
        newMenu.classList.add('hidden');
    }
    const teamModal = document.getElementById('team-chat-modal');
    if (teamModal && !teamModal.classList.contains('hidden') && e.target === teamModal) {
        closeTeamChatModal();
    }
});

function createAgentWorkspace() {
    const name = document.getElementById('agent-create-name').value.trim();
    const status = document.getElementById('agent-create-status');
    if (!name) {
        status.textContent = t('agents_name_required');
        return;
    }
    // A hand-typed id is used as given; blank falls back to the name's slug,
    // and then to a random one when the name has no ascii to slug (e.g. it is
    // written in Chinese). Generated here rather than while typing so the field
    // stays exactly as the user left it.
    const typed = document.getElementById('agent-create-id').value.trim();
    const id = typed || slugAgentId(name) || randomAgentId();
    // Mirrors the server's rule, so a bad id is caught before the round trip.
    if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(id)) {
        status.textContent = t('agents_id_invalid');
        return;
    }
    fetch('/api/agents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            action: 'create',
            id,
            name,
            description: document.getElementById('agent-create-description')?.value.trim() || '',
            clone_from: getDropdownValue(document.getElementById('agent-create-clone')) || null,
            knowledge_mode: _createKnowledgeMode,
            revision: rosterRevision,
        }),
    }).then(r => r.json()).then(data => {
        if (data.status !== 'success') {
            throw new Error(data.code === 'stale_roster' ? t('agents_stale') : (data.message || 'Create failed'));
        }
        if (data.revision) rosterRevision = data.revision;
        // Now that the workspace exists, push the staged avatar (if any) before
        // reloading, so the roster arrives already carrying the new image.
        const avatarStep = _pendingCreateAvatar
            ? uploadAgentAvatar(id, _pendingCreateAvatar.file).catch(() => {})
            : Promise.resolve();
        closeAgentCreateForm();
        return avatarStep.then(() => loadAgentCatalog()).then(() => openAgentDetail(id));
    }).catch(err => { status.textContent = err.message; });
}

function saveAgentProfile() {
    const agent = findAgent(selectedAdminAgentId);
    if (!agent) return;
    const payload = {
        name: document.getElementById('agent-edit-name')?.value.trim(),
        description: document.getElementById('agent-edit-description')?.value.trim() || '',
    };
    // Absent for the default Agent, which follows the configured model.
    const picker = document.getElementById('agent-edit-model');
    if (picker) {
        const [provider, model] = (getDropdownValue(picker) || '').split('|');
        payload.model = model || '';
        payload.bot_type = provider || '';
    }
    // The write itself is quick; the follow-up catalog reload is what's slow
    // (the default Agent carries a large skill list). Confirm optimistically so
    // the feedback is instant, and only override it if the save actually fails.
    flashAgentProfileStatus();
    updateAgentWorkspace(agent.id, payload).then(ok => {
        if (!ok) {
            _agentSavedFlashUntil = 0;
            const status = document.getElementById('agent-profile-status');
            if (status) {
                status.textContent = t('agents_save_failed');
                status.classList.remove('agent-status-ok');
            }
        }
    });
}

/* A brief inline confirmation on the detail pane's status line. A save reloads
   the catalog and can re-render this pane more than once (the model catalog
   arrives async), so the confirmation is kept as a deadline that every render
   re-applies, rather than a one-shot write a later render would wipe. */
let _agentSavedFlashUntil = 0;

function paintAgentSavedFlash() {
    const status = document.getElementById('agent-profile-status');
    if (!status) return;
    if (Date.now() < _agentSavedFlashUntil) {
        status.textContent = t('agents_saved');
        status.classList.add('agent-status-ok');
    }
}

function flashAgentProfileStatus() {
    _agentSavedFlashUntil = Date.now() + 2200;
    paintAgentSavedFlash();
    clearTimeout(flashAgentProfileStatus._t);
    flashAgentProfileStatus._t = setTimeout(() => {
        _agentSavedFlashUntil = 0;
        const status = document.getElementById('agent-profile-status');
        if (!status) return;
        status.textContent = '';
        status.classList.remove('agent-status-ok');
    }, 2200);
}

function uploadAgentAvatar(agentId, file) {
    if (!file) return;
    const picker = document.getElementById('agent-edit-avatar');
    if (picker) picker.classList.add('is-uploading');
    const status = document.getElementById('agent-profile-status');
    if (status) { status.classList.remove('agent-status-ok'); status.textContent = ''; }
    const form = new FormData();
    form.append('avatar', file);
    return fetch(`/api/agents/${encodeURIComponent(agentId)}/avatar`, { method: 'POST', body: form })
        .then(r => r.json())
        .then(data => {
            if (data.status !== 'success') throw new Error(data.message || 'Upload failed');
            // The image already persisted server-side. Patch the local catalog in
            // place and repaint just the affected surfaces, rather than reloading
            // the whole roster (slow when the default Agent carries many skills).
            avatarVersions[agentId] = String(Date.now());
            if (data.revision) rosterRevision = data.revision;
            const agent = findAgent(agentId);
            if (agent) agent.avatar = 'image';
            renderAgentsGrid();
            if (selectedAdminAgentId === agentId) renderAgentDetail();
            renderComposerIdentity();
            refreshBubbleAvatars();
            flashAgentProfileStatus();
        })
        .catch(err => {
            const s = document.getElementById('agent-profile-status');
            if (s) { s.classList.remove('agent-status-ok'); s.textContent = err.message; }
        })
        .then(() => {
            const p = document.getElementById('agent-edit-avatar');
            if (p) p.classList.remove('is-uploading');
        });
}

function updateAgentWorkspace(agentId, updates, _retried) {
    return fetch('/api/agents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'update', id: agentId, revision: rosterRevision, ...updates }),
    }).then(r => r.json()).then(data => {
        if (data.status !== 'success') {
            // Two quick edits race: the second still carried the revision from
            // before the first landed. Re-sync and retry once, silently, so a
            // fast click just works instead of showing a lock error.
            if (data.code === 'stale_roster' && !_retried) {
                return loadAgentCatalog().then(() => updateAgentWorkspace(agentId, updates, true));
            }
            throw new Error(data.code === 'stale_roster' ? t('agents_stale') : (data.message || 'Update failed'));
        }
        return loadAgentCatalog().then(() => true);
    }).catch(err => {
        const status = document.getElementById('agent-profile-status') || document.getElementById('agent-editor-status');
        if (status) status.textContent = err.message;
        return false;
    });
}

function deleteAgent(agentId) {
    const agent = findAgent(agentId);
    if (!agent) return;
    if (agentId === defaultAgentId) return; // the default Agent is the instance
    showConfirmDialog({
        title: t('agents_delete_title'),
        message: t('agents_delete_confirm').replace('{name}', agent.name || agentId),
        okText: t('agents_delete'),
        cancelText: t('cancel'),
        onConfirm: () => _performAgentDelete(agentId),
    });
}

function _performAgentDelete(agentId, _retried) {
    return fetch('/api/agents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'delete', id: agentId, revision: rosterRevision }),
    }).then(r => r.json()).then(data => {
        if (data.status !== 'success') {
            if (data.code === 'stale_roster' && !_retried) {
                return loadAgentCatalog().then(() => _performAgentDelete(agentId, true));
            }
            throw new Error(data.code === 'stale_roster' ? t('agents_stale') : (data.message || 'Delete failed'));
        }
        // Leaving the detail open on a now-deleted Agent would show a ghost.
        if (selectedAdminAgentId === agentId) closeAgentDetail();
        // A conversation owned by the deleted Agent falls back to the default.
        if (activeAgentId === agentId) {
            activeAgentId = defaultAgentId;
            localStorage.setItem('cow_active_agent', activeAgentId);
        }
        // Drop the deleted Agent's remembered session id — its conversations
        // went with the workspace, so the pinned id would only re-pin a ghost.
        localStorage.removeItem(`${SESSION_ID_KEY}:${agentId}`);
        return loadAgentCatalog().then(() => {
            renderComposerIdentity();
            // The Agent's sessions were removed server-side; refresh the open
            // list so its rows don't linger until the next unrelated reload.
            if (typeof loadSessionList === 'function') loadSessionList();
            return true;
        });
    }).catch(err => {
        const status = document.getElementById('agent-profile-status');
        if (status) status.textContent = err.message;
        else alert(err.message);
        return false;
    });
}

// The four core files an Agent can be edited through. BOOTSTRAP.md exists on
// disk for internal use but isn't meant for hand-editing, so it's left out of
// the picker entirely. Each option carries a short hint (rendered on the
// right of the dropdown row) so the raw filename isn't the only clue to what
// it holds.
function _agentCoreFileOptions() {
    return [
        { value: 'AGENT.md', label: 'AGENT.md', hint: t('agents_core_file_agent') },
        { value: 'USER.md', label: 'USER.md', hint: t('agents_core_file_user') },
        { value: 'RULE.md', label: 'RULE.md', hint: t('agents_core_file_rule') },
        { value: 'MEMORY.md', label: 'MEMORY.md', hint: t('agents_core_file_memory') },
    ];
}

let agentCoreViewMode = 'edit';

function initAgentCoreFileDropdown() {
    const el = document.getElementById('agent-core-file');
    if (!el) return;
    const current = el._ddValue || 'AGENT.md';
    initDropdown(el, _agentCoreFileOptions(), current, () => loadAgentCoreFile());
}

function currentAgentCoreFile() {
    const el = document.getElementById('agent-core-file');
    return (el && el._ddValue) || 'AGENT.md';
}

function setAgentCoreViewMode(mode) {
    agentCoreViewMode = mode;
    document.querySelectorAll('#agent-core-mode .agent-seg-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.mode === mode);
    });
    const editor = document.getElementById('agent-core-editor');
    const preview = document.getElementById('agent-core-preview');
    if (!editor || !preview) return;
    if (mode === 'preview') {
        preview.innerHTML = renderMarkdown(editor.value || '');
        // Same post-processing chat messages get: syntax highlighting plus the
        // language label + copy button on each code block (renderMarkdown only
        // produces the raw <pre>; the headers are added to the live DOM after).
        if (typeof applyHighlighting === 'function') applyHighlighting(preview);
        editor.classList.add('hidden');
        preview.classList.remove('hidden');
    } else {
        preview.classList.add('hidden');
        editor.classList.remove('hidden');
    }
}

function loadAgentCoreFile() {
    if (!selectedAdminAgentId) return;
    initAgentCoreFileDropdown();
    const filename = currentAgentCoreFile();
    if (!filename) return;
    _paintCoreFileStatus('pending', '…');
    fetch(`/api/agents/${encodeURIComponent(selectedAdminAgentId)}/files/${encodeURIComponent(filename)}`)
        .then(r => r.json()).then(data => {
            if (data.status !== 'success') throw new Error(data.message || t('agents_save_failed'));
            selectedCoreRevision = data.revision;
            document.getElementById('agent-core-editor').value = data.content || '';
            document.getElementById('agent-editor-label').textContent = `${selectedAdminAgentId} / ${filename}`;
            // The revision hash meant nothing to a human reader; a blank status
            // (nothing to report) reads better than a stray hex fragment.
            _paintCoreFileStatus('pending', '');
            // Refresh the preview in place if that's the active view, so
            // switching files while in preview mode doesn't show stale content.
            if (agentCoreViewMode === 'preview') setAgentCoreViewMode('preview');
        }).catch(err => { _paintCoreFileStatus('error', err.message); });
}

// Paint the save status with a colour + icon, not just bare text, so success
// and failure actually read differently at a glance. Success fades back to
// blank after a bit; failure stays until the next attempt so it isn't missed.
//
// Every other `*-status` element in this console is hidden via the shared
// `opacity-0` convention (see navigateTo/setLanguage, which blanket-fade any
// `[id$="-status"]` element on navigation). This one has the same id suffix
// so it gets caught by that same sweep — it must toggle `opacity-0` itself
// too, or a stray earlier sweep leaves it permanently invisible no matter
// what innerHTML is painted into it afterwards.
function _paintCoreFileStatus(kind, text) {
    const status = document.getElementById('agent-editor-status');
    if (!status) return;
    clearTimeout(_paintCoreFileStatus._t);
    status.classList.remove('agent-status-ok', 'agent-status-error');
    if (kind === 'ok') {
        status.innerHTML = `<i class="fas fa-check mr-1"></i>${escapeHtml(text)}`;
        status.classList.add('agent-status-ok');
        status.classList.remove('opacity-0');
        _paintCoreFileStatus._t = setTimeout(() => {
            status.textContent = '';
            status.classList.remove('agent-status-ok');
            status.classList.add('opacity-0');
        }, 2200);
    } else if (kind === 'error') {
        status.innerHTML = `<i class="fas fa-triangle-exclamation mr-1"></i>${escapeHtml(text)}`;
        status.classList.add('agent-status-error');
        status.classList.remove('opacity-0');
    } else {
        status.textContent = text || '';
        if (text) status.classList.remove('opacity-0');
    }
}

function saveAgentCoreFile() {
    if (!selectedAdminAgentId) return;
    const filename = currentAgentCoreFile();
    const btn = document.querySelector('#agent-detail-files button[onclick="saveAgentCoreFile()"]');
    _paintCoreFileStatus('pending', '…');
    if (btn) btn.disabled = true;
    fetch(`/api/agents/${encodeURIComponent(selectedAdminAgentId)}/files/${encodeURIComponent(filename)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: document.getElementById('agent-core-editor').value, revision: selectedCoreRevision }),
    }).then(async r => ({ ok: r.ok, data: await r.json() })).then(({ ok, data }) => {
        if (!ok || data.status !== 'success') throw new Error(data.message || t('agents_save_failed'));
        selectedCoreRevision = data.revision;
        _paintCoreFileStatus('ok', t('agents_saved'));
    }).catch(err => {
        _paintCoreFileStatus('error', err.message);
    }).finally(() => {
        if (btn) btn.disabled = false;
    });
}

function startChatWithAgent(agentId) {
    if (!agentId) return;
    activeAgentId = agentId;
    localStorage.setItem('cow_active_agent', activeAgentId);
    newChat(true);
    navigateTo('chat');
    renderComposerIdentity();
}

function conversationHasMessages() {
    return !!document.querySelector('#chat-messages .user-message-group, #chat-messages .bot-message-group');
}

/** A roster of one behaves exactly like the console did before Agents existed:
 *  no face on the composer, no faces in the session list, no @ mentions. */
function multiAgentMode() {
    return enabledAgents().length > 1;
}

/** True once this conversation holds more than its owner. Until then it is an
 *  ordinary chat and is drawn like one. */
function sharedConversation() {
    return multiAgentMode() && currentTeamIds().length > 0;
}

// Who is answering each in-flight request, as reported when it was accepted.
// Lets a streaming bubble carry the right name before anything is persisted.
const _liveSpeakers = {};

function rememberLiveSpeaker(data) {
    if (data && data.request_id && data.speaker) {
        _liveSpeakers[data.request_id] = data.speaker;
    }
}

/** Repaint a still-visible loading indicator with the resolved speaker's face,
 *  once /message has said who took the turn. No-op if streaming already
 *  replaced the dots with a bubble. */
function setLoadingSpeaker(loadingEl, requestId) {
    if (!loadingEl || !loadingEl.isConnected) return;
    const face = loadingEl.querySelector('.bot-face');
    if (face) face.innerHTML = agentAvatarHTML(liveSpeakerAgent(requestId), 32);
}

/** The Agent to draw on a reply, or null to keep the product's own face. */
function botSpeakerAgent(msg, requestId) {
    if (!sharedConversation()) return null;
    const id = (msg && msg.extras && msg.extras.agent_id)
        || (requestId && _liveSpeakers[requestId])
        || activeAgentId;
    return findAgent(id) || null;
}

/** The Agent answering a live request, for the streaming bubble and the loading
 *  dots. Unlike botSpeakerAgent this also resolves in a solo chat, so a single
 *  Agent's own uploaded avatar shows while it streams instead of the logo. */
function liveSpeakerAgent(requestId) {
    const id = (requestId && _liveSpeakers[requestId]) || activeAgentId;
    return findAgent(id) || null;
}

/** Turn a written-out mention into a chip, so a name reads as a name instead
 *  of as an id someone pasted. Runs on the rendered bubble rather than on the
 *  markdown source, which keeps code spans untouched. */
function highlightMentions(root) {
    const roster = sessionRoster();
    if (!root || roster.length < 2) return;
    const byLabel = new Map();
    roster.forEach(agent => {
        [agent.name, agent.id].forEach(label => {
            if (label) byLabel.set(String(label).toLowerCase(), agent);
        });
    });
    const alternation = Array.from(byLabel.keys())
        .sort((a, b) => b.length - a.length)
        .map(label => label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
        .join('|');
    const re = new RegExp('@(' + alternation + ')(?=[\\s，,：:、]|$)', 'gi');

    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
        acceptNode: node => node.parentElement
            && node.parentElement.closest('code, pre, .mention-tag')
            ? NodeFilter.FILTER_REJECT
            : NodeFilter.FILTER_ACCEPT,
    });
    const targets = [];
    let node;
    while ((node = walker.nextNode())) {
        re.lastIndex = 0;
        if (re.test(node.nodeValue)) targets.push(node);
    }
    targets.forEach(text => {
        const value = text.nodeValue;
        const frag = document.createDocumentFragment();
        let cursor = 0;
        let match;
        re.lastIndex = 0;
        while ((match = re.exec(value))) {
            if (match.index > cursor) {
                frag.appendChild(document.createTextNode(value.slice(cursor, match.index)));
            }
            const agent = byLabel.get(match[1].toLowerCase());
            const tag = document.createElement('span');
            tag.className = 'mention-tag';
            if (agent) {
                // A chip that looks like the teammate it names: their face, then
                // their name. Falls back to plain text for an unknown label.
                tag.innerHTML = `<span class="mention-tag-face">${agentAvatarHTML(agent, 16)}</span><span class="mention-tag-name">${escapeHtml(agent.name || agent.id)}</span>`;
            } else {
                tag.textContent = '@' + match[1];
            }
            frag.appendChild(tag);
            cursor = match.index + match[0].length;
        }
        if (cursor < value.length) {
            frag.appendChild(document.createTextNode(value.slice(cursor)));
        }
        text.parentNode.replaceChild(frag, text);
    });
}

function renderComposerIdentity() {
    const wrap = document.getElementById('composer-identity');
    const btn = document.getElementById('composer-agent-btn');
    if (!wrap || !btn) return;
    // A single-Agent install keeps the composer exactly as it always was: no
    // avatar, no menu. The identity chip only appears once there is more than
    // one Agent and thus an actual choice to make.
    if (!multiAgentMode()) {
        wrap.classList.add('hidden');
        document.getElementById('composer-agent-menu')?.classList.add('hidden');
        return;
    }
    wrap.classList.remove('hidden');
    const agent = findAgent(activeAgentId) || { id: activeAgentId || defaultAgentId, name: activeAgentId || 'Agent' };
    const others = currentTeamIds().length;
    btn.innerHTML = agentAvatarHTML(agent, 22)
        + (others ? `<span class="composer-agent-count">${others + 1}</span>` : '');
    const face = btn.querySelector('.agent-avatar');
    if (face) face.id = 'composer-agent-avatar';
    // The owner can only be swapped before the first turn, but joining is
    // allowed at any point, so the button itself never goes dead.
    btn.classList.toggle('locked', conversationHasMessages());
    btn.dataset.tooltip = agent.name || agent.id;
}

function toggleComposerAgentMenu(event) {
    event.stopPropagation();
    const menu = document.getElementById('composer-agent-menu');
    if (!menu) return;
    if (!menu.classList.contains('hidden')) {
        menu.classList.add('hidden');
        return;
    }
    _closeComposerMenus(menu);
    renderComposerAgentMenu();
    menu.classList.remove('hidden');
}

/** Paint the agent menu's body from the current roster / team. Kept separate
 *  from the open/close toggle so an invite or removal can refresh the list in
 *  place — the menu stays open, the +/× flips, and the user can keep going. */
function renderComposerAgentMenu() {
    const menu = document.getElementById('composer-agent-menu');
    if (!menu) return;
    const taken = new Set(currentTeamIds());
    const members = (_sessCfg && _sessCfg.team && _sessCfg.team.members) || [];
    const sections = [];

    // A solo chat only shows who it is talking to right now — the current
    // Agent, and just that one. Switching to a different Agent (which would
    // silently start a fresh conversation) was more confusing than useful, so
    // the roster is gone; adding teammates below is how you bring others in.
    if (!sharedConversation()) {
        const current = findAgent(activeAgentId)
            || { id: activeAgentId, name: activeAgentId };
        sections.push(
            `<div class="composer-menu-title">${escapeHtml(t('composer_current_agent'))}</div>`
            + `<div class="composer-menu-item agent-row current">
                    ${agentAvatarHTML(current, 24)}
                    <span>${escapeHtml(current.name || current.id)}</span>
                    <i class="fas fa-check ml-auto text-[11px]"></i>
                </div>`
        );
    }

    const candidates = enabledAgents().filter(a => a.id !== activeAgentId && !taken.has(a.id));

    // A group chat lists everyone in the conversation, host first. The host is
    // the main Agent (owner) and is shown with a "main Agent" badge and no
    // remove control — it cannot be dropped from its own conversation. The
    // teammates below it are removable. A separate section further down offers
    // who can still be pulled in.
    if (sharedConversation()) {
        const owner = findAgent(activeAgentId)
            || { id: activeAgentId, name: activeAgentId };
        const ownerRow = `
            <div class="composer-menu-item agent-row joined is-owner">
                ${agentAvatarHTML(owner, 24)}
                <span>${escapeHtml(owner.name || owner.id)}</span>
                <span class="composer-menu-badge owner-badge ml-auto">${escapeHtml(t('composer_agent_owner'))}</span>
            </div>`;
        const joined = members.filter(m => m.id !== activeAgentId).map(m => `
            <button type="button" class="composer-menu-item agent-row joined"
                    onclick="removeTeamMember('${escapeHtml(m.id)}')" title="${escapeHtml(t('team_remove'))}">
                ${agentAvatarHTML(m, 24)}
                <span>${escapeHtml(m.name || m.id)}</span>
                <i class="fas fa-check ml-auto text-[11px] joined-check"></i>
                <i class="fas fa-xmark ml-auto text-[11px] joined-remove"></i>
            </button>`).join('');
        sections.push(
            `<div class="composer-menu-title">${escapeHtml(t('team_members'))}</div>${ownerRow}${joined}`
        );
    }

    const invitable = candidates.map(agent => `
        <button type="button" class="composer-menu-item agent-row"
                onclick="inviteTeamMember('${escapeHtml(agent.id)}')">
            ${agentAvatarHTML(agent, 24)}
            <span>${escapeHtml(agent.name)}</span>
            <i class="fas fa-plus ml-auto text-[11px] text-slate-400"></i>
        </button>`).join('');
    if (invitable) {
        sections.push(
            `<div class="composer-menu-title">${escapeHtml(t('team_invite'))}</div>${invitable}`
        );
    }

    // Always offer a way to make a new Agent, so a single-Agent user discovers
    // the team feature straight from the composer.
    sections.push(
        `<button type="button" class="composer-menu-item agent-row composer-menu-create"
                onclick="openAgentCreateFromComposer()">
            <span class="composer-menu-create-icon"><i class="fas fa-plus"></i></span>
            <span>${escapeHtml(t('agents_create'))}</span>
        </button>`
    );

    menu.innerHTML = sections.join('<div class="composer-menu-sep"></div>');
}

/** Jump from the composer straight into agent creation: close the menu, land on
 *  the team tab, and open the create form. */
function openAgentCreateFromComposer() {
    document.getElementById('composer-agent-menu')?.classList.add('hidden');
    navigateTo('agents');
    if (typeof openAgentCreateForm === 'function') openAgentCreateForm();
}

function inviteTeamMember(agentId) {
    // Keep the menu open so the invited Agent visibly moves from "+ add" to the
    // "× remove" list, and the user can invite several in a row without having
    // to reopen it each time.
    addTeamMember(agentId).then(refreshComposerAgentMenuIfOpen);
}

/** Everyone addressable in this conversation, owner first. */
function sessionRoster() {
    const owner = findAgent(activeAgentId);
    const members = (_sessCfg && _sessCfg.team && _sessCfg.team.members) || [];
    const roster = owner ? [owner] : [];
    members.forEach(m => {
        if (!roster.some(a => a.id === m.id)) roster.push(findAgent(m.id) || m);
    });
    return roster;
}

/** The teammate a message hands the turn to, or '' for nobody.
 *  Mirrors the server's rule: a leading mention only. */
function addressedAgentId(text) {
    const stripped = String(text || '').replace(/^\s+/, '');
    if (!stripped.startsWith('@')) return '';
    const labels = [];
    sessionRoster().forEach(agent => {
        [agent.name, agent.id].forEach(label => {
            if (label) labels.push([String(label), agent.id]);
        });
    });
    labels.sort((a, b) => b[0].length - a[0].length);
    for (const [label, id] of labels) {
        const re = new RegExp('^@' + label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(?=[\\s，,：:、]|$)', 'i');
        // The owner is addressable too; the server treats "@owner" as the owner
        // simply taking the turn, so no special-casing here.
        if (re.test(stripped)) return id;
    }
    return '';
}

function mentionedAgentIds(text) {
    const id = addressedAgentId(text);
    return id ? [id] : [];
}

function currentTeamIds() {
    return ((_sessCfg && _sessCfg.team && _sessCfg.team.members) || []).map(m => m.id);
}

function setTeamMembers(ids) {
    const unique = Array.from(new Set(ids.filter(id => id && id !== activeAgentId)));
    return fetch(`/api/sessions/${encodeURIComponent(sessionId)}/settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ members: unique.length ? unique : null }),
    }).then(r => r.json()).then(data => {
        if (data.status === 'success') {
            _sessCfg = { model: data.model, permission: data.permission, team: data.team };
            renderComposerIdentity();
            // Inviting or removing someone changes whether one model can speak
            // for this conversation, and whether @ can address an Agent.
            _renderModelChip();
            _renderInputPlaceholder();
        }
    });
}

function addTeamMember(agentId) {
    if (!agentId || agentId === activeAgentId) return Promise.resolve();
    const ids = currentTeamIds();
    if (ids.includes(agentId)) return Promise.resolve();
    return setTeamMembers([...ids, agentId]);
}

function removeTeamMember(agentId) {
    return setTeamMembers(currentTeamIds().filter(id => id !== agentId))
        .then(refreshComposerAgentMenuIfOpen);
}

/** Repaint the agent menu if it is still open, so add/remove show immediately. */
function refreshComposerAgentMenuIfOpen() {
    const menu = document.getElementById('composer-agent-menu');
    if (menu && !menu.classList.contains('hidden')) renderComposerAgentMenu();
}

async function syncTeamFromText(text) {
    const extra = mentionedAgentIds(text);
    if (!extra.length) return;
    await setTeamMembers([...currentTeamIds(), ...extra]);
}

// Point a channel instance at an Agent. Binding lives on the instance itself
// (channel_instances[].agent_id); an empty agentId means "follow the default
// Agent". instanceId defaults to the channel type for a single-instance channel.
function bindChannelAgent(channelType, agentId, instanceId, members) {
    const defaultId = defaultAgentId;
    const bound = (agentId && agentId !== defaultId) ? agentId : '';
    const iid = instanceId || channelType;
    const payload = {
        action: 'bind_channel_instance',
        channel_type: channelType,
        instance_id: iid,
        agent_id: bound,
    };
    // Only send members when we mean to set the team; omitting it leaves the
    // stored roster untouched (a plain owner-only rebind).
    if (Array.isArray(members)) payload.members = members;
    return fetch('/api/agents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    }).then(r => r.json()).then(data => {
        if (data.status !== 'success') throw new Error(data.message || 'Save failed');
        // Rebinding is a hot swap on the server (no channel restart), and the
        // dropdown already reflects the new value locally, so only the roster
        // catalog needs refreshing. Re-rendering the channels view here would
        // rebuild the cards and reset the scan/manual tab state for no reason.
        if (Array.isArray(channelInstancesView)) {
            const rec = channelInstancesView.find(i => i.instance_id === iid);
            if (rec) {
                rec.agent_id = bound;
                if (data.result && Array.isArray(data.result.members)) {
                    rec.members = data.result.members.slice();
                }
            }
        }
        return loadAgentCatalog();
    }).catch(err => _wsToast(err.message));
}

function channelBoundAgentId(channelType) {
    const inst = channelInstances.find(i =>
        (i.channel_type || '').toLowerCase() === channelType
    );
    return inst ? (inst.agent_id || '') : '';
}

let memoryAgentId = localStorage.getItem('cow_memory_agent') || '';

function viewingMemoryAgentId() {
    return memoryAgentId || activeAgentId || defaultAgentId;
}

function renderMemoryAgentSelect() {
    const el = document.getElementById('memory-agent-select');
    if (!el) return;
    const current = viewingMemoryAgentId();
    const list = agentCatalog.length ? agentCatalog : enabledAgents();
    const options = list.map(a => ({ value: a.id, label: a.name || a.id, agent: a }));
    initDropdown(el, options, current, (value) => selectMemoryAgent(value), { withAvatar: true });
}

function selectMemoryAgent(agentId) {
    memoryAgentId = agentId;
    localStorage.setItem('cow_memory_agent', agentId);
    closeMemoryViewer();
    loadMemoryView(1);
}

loadAgentCatalog();

// =====================================================================
// Markdown Renderer
// =====================================================================
const FALLBACK_HLJS = {
    getLanguage() { return false; },
    highlight(str) { return { value: escapeHtml(str) }; },
    highlightAuto(str) { return { value: escapeHtml(str) }; },
    highlightElement() {},
};

function getHljs() {
    return window.hljs || FALLBACK_HLJS;
}

// CJK ideographs, kana, Hangul and full/halfwidth forms (BMP only).
const CJK_CHAR_RE = /[\u1100-\u11FF\u2E80-\u303F\u3040-\u33FF\u3400-\u4DBF\u4E00-\u9FFF\uA960-\uA97F\uAC00-\uD7FF\uF900-\uFAFF\uFE10-\uFE19\uFE30-\uFE6F\uFF00-\uFF60\uFFE0-\uFFE6]/;

// CommonMark's flanking rules treat every Unicode punctuation alike, so
// `是**"引号"**——` never opens emphasis: the quote after `**` is punctuation
// while 是 before it is neither punctuation nor space, and the run degrades to
// literal asterisks. Apply the CJK-friendly amendment
// (github.com/tats-u/markdown-cjk-friendly): a `*` run with a CJK neighbour and
// no adjacent whitespace both opens and closes. `_` keeps the stock rules,
// whose intraword behavior depends on the original classification.
function patchCjkEmphasis(md) {
    const State = md.inline && md.inline.State;
    if (!State || !State.prototype.scanDelims || State.prototype._cjkEmphasisPatched) return;
    const utils = md.utils;
    const scanDelims = State.prototype.scanDelims;
    State.prototype.scanDelims = function(start, canSplitWord) {
        const res = scanDelims.call(this, start, canSplitWord);
        if (!canSplitWord) return res;
        const lastCode = start > 0 ? this.src.charCodeAt(start - 1) : 0x20;
        const nextPos = start + res.length;
        const nextCode = nextPos < this.posMax ? this.src.charCodeAt(nextPos) : 0x20;
        if (utils.isWhiteSpace(lastCode) || utils.isWhiteSpace(nextCode)) return res;
        if (!CJK_CHAR_RE.test(String.fromCharCode(lastCode)) &&
            !CJK_CHAR_RE.test(String.fromCharCode(nextCode))) return res;
        res.can_open = true;
        res.can_close = true;
        return res;
    };
    State.prototype._cjkEmphasisPatched = true;
}

function createMd() {
    const hljsLib = getHljs();
    const mdFactory = window.markdownit;
    if (typeof mdFactory !== 'function') {
        return {
            render(text) {
                return `<p>${escapeHtml(text || '')}</p>`;
            }
        };
    }
    const md = mdFactory({
        html: false, breaks: true, linkify: true, typographer: true,
        highlight: function(str, lang) {
            if (lang && hljsLib.getLanguage(lang)) {
                try { return hljsLib.highlight(str, { language: lang }).value; } catch (_) {}
            }
            return hljsLib.highlightAuto(str).value;
        }
    });
    patchCjkEmphasis(md);
    // Fix greedy linkify: markdown-it's linkify swallows markdown emphasis (*)
    // and CJK full-width punctuation glued to a URL (common in LLM output like
    // "**https://x**，中文"), turning the whole tail into one broken link. Cut
    // the URL at the first such char and spill the remainder back as text.
    var GREEDY_LINK_CUT = /[*\u3000-\u303F\uFF00-\uFFEF]/;
    md.core.ruler.after('linkify', 'fix_greedy_linkify', function(state) {
        for (var b = 0; b < state.tokens.length; b++) {
            var blk = state.tokens[b];
            if (blk.type !== 'inline' || !blk.children) continue;
            var ch = blk.children;
            for (var i = 0; i < ch.length; i++) {
                var open = ch[i];
                if (open.type !== 'link_open' || open.markup !== 'linkify') continue;
                var textTok = ch[i + 1], close = ch[i + 2];
                if (!textTok || textTok.type !== 'text' || !close || close.type !== 'link_close') continue;
                var idx = textTok.content.search(GREEDY_LINK_CUT);
                if (idx < 0) continue;
                var keep = textTok.content.slice(0, idx);
                var spill = textTok.content.slice(idx);
                textTok.content = keep;
                open.attrSet('href', keep);
                var spillTok = new state.Token('text', '', 0);
                spillTok.content = spill;
                ch.splice(i + 3, 0, spillTok);
            }
        }
    });
    const defaultLinkOpen = md.renderer.rules.link_open || function(tokens, idx, options, env, self) {
        return self.renderToken(tokens, idx, options);
    };
    md.renderer.rules.link_open = function(tokens, idx, options, env, self) {
        const token = tokens[idx];
        // A workspace-relative href would resolve against the console URL and
        // 404 in a new tab. Tag it instead so the click handler in
        // workspace.js opens it in the preview panel.
        const wsPath = typeof wsWorkspaceHref === 'function'
            ? wsWorkspaceHref(token.attrGet('href') || '') : null;
        if (wsPath) {
            token.attrPush(['data-ws-path', wsPath]);
            token.attrJoin('class', 'ws-link');
        } else {
            token.attrPush(['target', '_blank']);
            token.attrPush(['rel', 'noopener noreferrer']);
        }
        return defaultLinkOpen(tokens, idx, options, env, self);
    };
    // A table can't shrink below its columns' minimum content width, so a wide
    // comparison table would run past the bubble. Wrap it in a scroller: it
    // still fills the bubble when it fits and scrolls sideways when it doesn't.
    const defaultTableOpen = md.renderer.rules.table_open || function(tokens, idx, options, env, self) {
        return self.renderToken(tokens, idx, options);
    };
    const defaultTableClose = md.renderer.rules.table_close || function(tokens, idx, options, env, self) {
        return self.renderToken(tokens, idx, options);
    };
    md.renderer.rules.table_open = function(tokens, idx, options, env, self) {
        return '<div class="table-wrap">' + defaultTableOpen(tokens, idx, options, env, self);
    };
    md.renderer.rules.table_close = function(tokens, idx, options, env, self) {
        return defaultTableClose(tokens, idx, options, env, self) + '</div>';
    };
    return md;
}

const md = createMd();

const VIDEO_EXT_RE = /\.(?:mp4|webm|mov|avi|mkv)$/i;  // tested against URL without query string
const IMAGE_EXT_RE = /\.(?:jpg|jpeg|png|gif|webp|bmp|svg)$/i;  // tested against URL without query string

// Windows absolute path (D:\x.png / D:/x.png).
const WIN_ABS_PATH_RE = /^[A-Za-z]:[\\/]/;

function _toWebUrl(url) {
    if ((/^\/[A-Za-z]/.test(url) || WIN_ABS_PATH_RE.test(url)) && !url.startsWith('/api/')) {
        return '/api/file?path=' + encodeURIComponent(url);
    }
    if (/^file:\/\/\//i.test(url)) {
        // file:///home/x → /home/x, but file:///D:/x stays drive-relative.
        const p = url.replace(/^file:\/\/\//i, '');
        return '/api/file?path=' + encodeURIComponent(WIN_ABS_PATH_RE.test(p) ? p : '/' + p);
    }
    return url;
}

function _buildVideoHtml(url) {
    const webUrl = _toWebUrl(url);
    const fileName = url.split('/').pop().split('?')[0];
    return `<div style="margin:10px 0;">` +
        `<video controls preload="metadata" ` +
        `style="max-width:100%;border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,0.15);display:block;">` +
        `<source src="${webUrl}"></video>` +
        `<a href="${webUrl}" target="_blank" ` +
        `style="display:inline-flex;align-items:center;gap:4px;margin-top:4px;font-size:12px;color:#8b8fa8;text-decoration:none;">` +
        `<i class="fas fa-download"></i> ${escapeHtml(fileName)}</a></div>`;
}

function _openImageLightbox(src) {
    let overlay = document.getElementById('cow-lightbox');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'cow-lightbox';
        overlay.style.cssText = 'position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,0.85);display:flex;align-items:center;justify-content:center;cursor:zoom-out;opacity:0;transition:opacity .2s';
        overlay.onclick = () => { overlay.style.opacity = '0'; setTimeout(() => overlay.style.display = 'none', 200); };
        const img = document.createElement('img');
        img.id = 'cow-lightbox-img';
        img.style.cssText = 'max-width:92vw;max-height:92vh;border-radius:8px;box-shadow:0 4px 24px rgba(0,0,0,0.5);object-fit:contain;';
        img.onclick = (e) => e.stopPropagation();
        overlay.appendChild(img);
        document.body.appendChild(overlay);
    }
    overlay.querySelector('#cow-lightbox-img').src = src;
    overlay.style.display = 'flex';
    requestAnimationFrame(() => overlay.style.opacity = '1');
}

function _buildImageHtml(url) {
    const webUrl = _toWebUrl(url);
    const safeUrl = webUrl.replace(/"/g, '&quot;');
    return `<div style="margin:10px 0;">` +
        `<img src="${safeUrl}" alt="image" loading="lazy" ` +
        `onclick="_openImageLightbox(this.src)" ` +
        `style="max-width:520px;width:100%;border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,0.15);display:block;cursor:zoom-in;">` +
        `</div>`;
}

function injectVideoPlayers(html) {
    // Step 1: replace markdown-it anchor tags whose href points to a video file.
    const step1 = html.replace(
        /<a\s+href="(https?:\/\/[^"]+)"[^>]*>[^<]*<\/a>/gi,
        (match, url) => VIDEO_EXT_RE.test(url.split('?')[0]) ? _buildVideoHtml(url) : match
    );
    // Step 2: replace any remaining bare video URLs in text nodes (not inside HTML tags).
    // Split on HTML tags to avoid touching src/href attributes already in markup.
    return step1.split(/(<[^>]+>)/).map((chunk, idx) => {
        // Even indices are text nodes; odd indices are HTML tags — leave them untouched.
        if (idx % 2 !== 0) return chunk;
        return chunk.replace(/https?:\/\/\S+/gi, (url) => {
            const bare = url.replace(/[),.\s]+$/, '');  // strip trailing punctuation
            return VIDEO_EXT_RE.test(bare.split('?')[0]) ? _buildVideoHtml(bare) : url;
        });
    }).join('');
}

// Convert image URLs into inline <img> previews. Mirrors injectVideoPlayers but for images.
// Handles three cases produced by markdown-it:
//   1. <a href="...image.jpg">...</a>  (bare URL or autolink that linkify turned into an anchor)
//   2. <img src="...">                  (markdown image syntax) — leave as-is, but normalize style
//   3. raw URL still present in a text node                    — only as a safety net
function injectImagePreviews(html) {
    // Step 1: anchor whose href points to an image file -> replace with <img> preview.
    const step1 = html.replace(
        /<a\s+href="(https?:\/\/[^"]+)"[^>]*>[^<]*<\/a>/gi,
        (match, url) => IMAGE_EXT_RE.test(url.split('?')[0]) ? _buildImageHtml(url) : match
    );
    // Step 2: bare image URLs left in text nodes (rare — markdown-it's linkify usually catches them).
    return step1.split(/(<[^>]+>)/).map((chunk, idx) => {
        if (idx % 2 !== 0) return chunk;
        return chunk.replace(/https?:\/\/\S+/gi, (url) => {
            const bare = url.replace(/[),.\s]+$/, '');
            return IMAGE_EXT_RE.test(bare.split('?')[0]) ? _buildImageHtml(bare) : url;
        });
    }).join('');
}

function _rewriteLocalImgSrc(html) {
    return html.replace(/<img\s([^>]*?)src="([^"]+)"([^>]*?)>/gi, (match, pre, src, post) => {
        const webSrc = _toWebUrl(src);
        const safeSrc = webSrc.replace(/"/g, '&quot;');
        const hasClick = /onclick/i.test(pre + post);
        const clickAttr = hasClick ? '' : ` onclick="_openImageLightbox(this.src)" style="cursor:zoom-in;"`;
        return `<img ${pre}src="${safeSrc}"${post}${clickAttr}>`;
    });
}

function renderMarkdown(text) {
    try {
        let html = md.render(text);
        html = _rewriteLocalImgSrc(html);
        // Order matters: video first (more specific), then image.
        html = injectImagePreviews(injectVideoPlayers(html));
        // Fallback for files the agent only mentions by path (workspace.js).
        if (typeof injectFileChips === 'function') html = injectFileChips(html);
        // Note: Code block headers are added via DOM manipulation after insertion
        // See addCodeBlockHeadersToElement()
        return html;
    }
    catch (e) { return text.replace(/\n/g, '<br>'); }
}

function _addCodeBlockHeaders(container) {
    // Add header with language label and copy button to each <pre> block using DOM manipulation
    const preBlocks = container.querySelectorAll('pre');
    preBlocks.forEach(pre => {
        if (pre.parentElement && pre.parentElement.classList.contains('code-block-wrapper')) return;
        
        const codeEl = pre.querySelector('code');
        if (!codeEl) return;
        
        const langClass = Array.from(codeEl.classList).find(c => c.startsWith('language-'));
        const language = langClass ? langClass.replace('language-', '') : '';
        // Hide label for unknown/empty languages (e.g. language-undefined)
        const showLang = language && language !== 'undefined' && language !== 'code';
        const langLabel = showLang ? language.charAt(0).toUpperCase() + language.slice(1) : '';
        
        const wrapper = document.createElement('div');
        wrapper.className = 'code-block-wrapper';
        
        const header = document.createElement('div');
        header.className = 'code-block-header';
        header.innerHTML = `
            <span class="code-block-lang">${langLabel}</span>
            <button class="code-copy-btn" title="Copy code">
                <i class="fas fa-copy"></i>
            </button>
        `;
        
        pre.parentNode.insertBefore(wrapper, pre);
        wrapper.appendChild(header);
        wrapper.appendChild(pre);
    });
}

// =====================================================================
// Chat Module
// =====================================================================
let isPolling = false;
let pollGeneration = 0;   // incremented on each restart to cancel stale poll loops
// Auth gate for background pollers. When a web_password is set, the /poll and
// /api/scheduler/runs loops must NOT run before the user logs in — otherwise
// they fire every few seconds with no cookie and spam the server log with
// "401 Unauthorized (credentials offered: none)". Both loops call
// requestAuthGatedStart(); the actual start is deferred until the login/auth
// check opens the gate via openAuthGate(). When no password is set the gate is
// opened immediately at startup so behavior is unchanged.
let authGateOpen = false;
const _pendingAuthGatedStarts = [];
function requestAuthGatedStart(fn) {
    if (authGateOpen) { fn(); return; }
    _pendingAuthGatedStarts.push(fn);
}
function openAuthGate() {
    if (authGateOpen) return;
    authGateOpen = true;
    while (_pendingAuthGatedStarts.length) {
        const fn = _pendingAuthGatedStarts.shift();
        try { fn(); } catch (_) {}
    }
}
let loadingContainers = {};
let activeStreams = {};   // request_id -> EventSource
let sessionActiveRequest = {};   // agent_id + session_id -> request_id
const PENDING_VOICE_ATTACH_TTL_MS = 2 * 60 * 1000;
const PENDING_VOICE_ATTACH_MAX = 100;
const pendingVoiceAttachments = new Map(); // session_id:bot_seq -> pending audio

function runtimeSessionKey(sid, agentId = activeAgentId) {
    return `${agentId || defaultAgentId || 'default'}::${sid}`;
}

function isCurrentSessionConversationActive() {
    return !!sessionActiveRequest[runtimeSessionKey(sessionId)];
}

function updateEditButtonsState() {
    const active = isCurrentSessionConversationActive();
    document.querySelectorAll('.edit-msg-btn, .delete-msg-btn').forEach(btn => {
        btn.disabled = active;
        if (btn.classList.contains('edit-msg-btn')) {
            btn.title = active
                ? t('edit_disabled_reply_active')
                : t('edit_message');
        } else {
            btn.title = active
                ? t('delete_disabled_reply_active')
                : t('delete_message_title');
        }
    });
}
let streamBuffers = {};   // request_id -> { items: [event...], timestamp } for re-attach replay
let isComposing = false;
let appConfig = { use_agent: false, title: 'CowAgent', subtitle: '', providers: {}, api_bases: {} };

let activeAgentId = localStorage.getItem('cow_active_agent') || '';
const SESSION_ID_KEY = 'cow_session_id';

function activeSessionStorageKey() {
    return activeAgentId && activeAgentId !== defaultAgentId && activeAgentId !== 'default'
        ? `${SESSION_ID_KEY}:${activeAgentId}`
        : SESSION_ID_KEY;
}

// Carry the selected Agent through existing console requests without forcing
// every feature panel to implement its own routing glue.
const _nativeFetch = window.fetch.bind(window);
window.fetch = function(input, init) {
    init = init ? { ...init } : {};
    let url = typeof input === 'string' ? input : input.url;
    if (activeAgentId && typeof url === 'string' && url.startsWith('/')) {
        if (!/[?&]agent_id=/.test(url)) {
        const joiner = url.includes('?') ? '&' : '?';
        url = `${url}${joiner}agent_id=${encodeURIComponent(activeAgentId)}`;
        }
        if (typeof input !== 'string') input = new Request(url, input);
        else input = url;

        // JSON bodies read agent_id from the payload, so inject it there too.
        // Multipart (FormData) uploads must NOT get a body copy: the query
        // string above already carries it, and web.py merges query + body,
        // collapsing the duplicate into a list (agent_id=['x','x']). That list
        // then reaches handlers expecting a plain string and raises
        // "unhashable type: 'list'", silently killing every file upload.
        if (typeof init.body === 'string') {
            const contentType = new Headers(init.headers || {}).get('Content-Type') || '';
            if (contentType.includes('application/json')) {
                try {
                    const body = JSON.parse(init.body);
                    if (body && typeof body === 'object' && !Array.isArray(body) && !body.agent_id) {
                        body.agent_id = activeAgentId;
                        init.body = JSON.stringify(body);
                    }
                } catch (_) {}
            }
        }
    }
    return _nativeFetch(input, init);
};

function generateSessionId() {
    return 'session_' + ([1e7]+-1e3+-4e3+-8e3+-1e11).replace(/[018]/g, c =>
        (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16)
    );
}

// Restore session_id from localStorage so conversation history survives page refresh.
// A new id is only generated when the user explicitly starts a new chat.
function loadOrCreateSessionId() {
    const stored = localStorage.getItem(activeSessionStorageKey());
    if (stored) return stored;
    const fresh = generateSessionId();
    localStorage.setItem(activeSessionStorageKey(), fresh);
    return fresh;
}

let sessionId = loadOrCreateSessionId();

// ---- Conversation history state ----
let historyPage = 0;       // last page fetched (0 = nothing fetched yet)
let historyHasMore = false;
let historyLoading = false;

fetch('/config').then(r => r.json()).then(data => {
    if (data.status === 'success') {
        appConfig = data;
        const title = data.title || 'CowAgent';
        document.getElementById('welcome-title').textContent = title;
        initConfigView(data);
    }
    loadHistory(1);
}).catch(() => { loadHistory(1); });

// Start polling so scheduler/push messages are received. Gated behind auth so a
// password-protected console doesn't poll (and log 401s) before login.
requestAuthGatedStart(startPolling);

const chatInput = document.getElementById('chat-input');
const sendBtn = document.getElementById('send-btn');
const steerBtn = document.getElementById('steer-btn');
const messagesDiv = document.getElementById('chat-messages');
const fileInput = document.getElementById('file-input');
const folderInput = document.getElementById('folder-input');
const attachBtn = document.getElementById('attach-btn');
const attachMenu = document.getElementById('attach-menu');
const attachFolderOption = document.getElementById('attach-folder-option');
const supportsDirectoryUpload = !!folderInput && 'webkitdirectory' in folderInput;

if (!supportsDirectoryUpload && attachFolderOption) {
    attachFolderOption.classList.add('hidden');
}

// Composer textarea sizing. The empty box is deliberately tall (a few lines of
// room, like other coding agents) and grows with the text up to a cap, after
// which it scrolls.
const COMPOSER_MIN_H = 52;
const COMPOSER_MAX_H = 220;

function autoResizeComposer() {
    chatInput.style.height = COMPOSER_MIN_H + 'px';
    const scrollH = chatInput.scrollHeight;
    chatInput.style.height = Math.max(COMPOSER_MIN_H, Math.min(scrollH, COMPOSER_MAX_H)) + 'px';
    chatInput.style.overflowY = scrollH > COMPOSER_MAX_H ? 'auto' : 'hidden';
}

/** Shrink the composer back to its resting height after the text is consumed. */
function resetComposerHeight() {
    chatInput.style.height = COMPOSER_MIN_H + 'px';
    chatInput.style.overflowY = 'hidden';
}

// ---------------- Mic button: in-page voice input via the configured ASR provider ----------------
(function setupMicButton() {
    const micBtn = document.getElementById('mic-btn');
    if (!micBtn) return;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia ||
        typeof window.MediaRecorder === 'undefined') {
        micBtn.style.display = 'none';
        return;
    }

    let mediaRecorder = null;
    let stream = null;
    let chunks = [];
    let recording = false;

    // Use the custom CSS tooltip (data-tooltip) instead of the native title:
    // native title has a ~1.5s hover delay and is not i18n-aware.
    const setTip = (text) => {
        micBtn.setAttribute('data-tooltip', text);
        micBtn.removeAttribute('title');
    };

    const setIdle = () => {
        recording = false;
        micBtn.classList.remove('text-red-500', 'animate-pulse');
        micBtn.classList.add('text-slate-400');
        micBtn.querySelector('i').className = 'fas fa-microphone text-sm';
        setTip(t('mic_idle_title'));
    };
    const setRecording = () => {
        recording = true;
        micBtn.classList.remove('text-slate-400');
        micBtn.classList.add('text-red-500', 'animate-pulse');
        micBtn.querySelector('i').className = 'fas fa-stop text-sm';
        setTip(t('mic_recording_title'));
    };
    const setBusy = () => {
        micBtn.classList.remove('text-red-500', 'animate-pulse', 'text-slate-400');
        micBtn.classList.add('text-primary-500');
        micBtn.querySelector('i').className = 'fas fa-spinner fa-spin text-sm';
        setTip(t('mic_busy_title'));
    };

    const pickMimeType = () => {
        const candidates = [
            'audio/webm;codecs=opus',
            'audio/webm',
            'audio/ogg;codecs=opus',
            'audio/mp4',
        ];
        for (const m of candidates) {
            if (window.MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(m)) {
                return m;
            }
        }
        return '';
    };

    const stopStream = () => {
        if (stream) {
            stream.getTracks().forEach(t => t.stop());
            stream = null;
        }
    };

    let _micTipTimer = null;
    const flashError = (msg) => {
        console.warn('[mic]', msg);
        // Pop a small bubble above the mic so the user actually notices it.
        // The mic lives inside a relatively-positioned wrapper around the
        // textarea (see chat.html), so we hang the tip off that wrapper.
        const wrapper = micBtn.parentElement;
        if (!wrapper) return;
        let tip = wrapper.querySelector('.mic-tip');
        if (!tip) {
            tip = document.createElement('div');
            tip.className = 'mic-tip absolute right-1 bottom-full mb-2 px-2 py-1 rounded-md '
                + 'text-xs text-white bg-slate-800/90 dark:bg-slate-700/90 shadow-md '
                + 'pointer-events-none whitespace-nowrap z-10';
            wrapper.appendChild(tip);
        }
        tip.textContent = msg;
        tip.style.opacity = '1';
        if (_micTipTimer) clearTimeout(_micTipTimer);
        _micTipTimer = setTimeout(() => {
            tip.style.opacity = '0';
            tip.style.transition = 'opacity 200ms';
            setTimeout(() => tip.remove(), 250);
        }, 2000);
    };

    const upload = async (blob, ext) => {
        setBusy();
        const fd = new FormData();
        fd.append('file', blob, `recording.${ext}`);
        try {
            const resp = await fetch('/api/voice/asr', { method: 'POST', body: fd });
            const data = await resp.json();
            if (data.status === 'success' && data.text) {
                // Voice-message UX: drop the recording into the conversation
                // as a playable bubble with the caption underneath, then
                // dispatch the recognised text through the regular send path.
                sendVoiceMessage(data.text, data.audio_url);
            } else {
                flashError(data.message || t('mic_error'));
            }
        } catch (e) {
            flashError(t('mic_error') + ': ' + e.message);
        } finally {
            setIdle();
        }
    };

    const start = async () => {
        try {
            stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        } catch (e) {
            flashError(t('mic_permission_denied'));
            return;
        }
        chunks = [];
        const mimeType = pickMimeType();
        try {
            mediaRecorder = mimeType
                ? new MediaRecorder(stream, { mimeType })
                : new MediaRecorder(stream);
        } catch (e) {
            stopStream();
            flashError(t('mic_error') + ': ' + e.message);
            return;
        }
        mediaRecorder.ondataavailable = (ev) => {
            if (ev.data && ev.data.size > 0) chunks.push(ev.data);
        };
        mediaRecorder.onstop = () => {
            stopStream();
            const blob = new Blob(chunks, { type: mediaRecorder.mimeType || 'audio/webm' });
            // Map mime -> extension so the server picks the right file suffix.
            const mt = (mediaRecorder.mimeType || 'audio/webm').split(';')[0];
            const extMap = {
                'audio/webm': 'webm', 'audio/ogg': 'ogg',
                'audio/mp4': 'm4a',   'audio/mpeg': 'mp3',
            };
            const ext = extMap[mt] || 'webm';
            // 256 bytes ~ container header only, no actual audio. Anything
            // below that we treat as "tapped by mistake".
            if (blob.size < 256) {
                setIdle();
                flashError(t('mic_too_short'));
                return;
            }
            upload(blob, ext);
        };
        // timeslice=250ms: force the recorder to flush a chunk every 250ms.
        // Without it some browsers wait for stop() before producing any data,
        // which loses the audio on very short taps.
        mediaRecorder.start(250);
        recordStartedAt = Date.now();
        setRecording();
    };

    let recordStartedAt = 0;

    const stopWithMinDuration = () => {
        const elapsed = Date.now() - recordStartedAt;
        const minMs = 350;
        if (elapsed < minMs) {
            // Give the recorder a moment to capture at least one chunk
            // before we tell it to stop.
            setTimeout(() => stop(), minMs - elapsed);
        } else {
            stop();
        }
    };

    const stop = () => {
        if (mediaRecorder && mediaRecorder.state !== 'inactive') {
            mediaRecorder.stop();
        }
    };

    micBtn.addEventListener('click', () => {
        if (recording) {
            stopWithMinDuration();
        } else {
            start();
        }
    });

    setIdle();
})();

// ---------------- Optimize button: prompt optimization via AI ----------------
(function setupOptimizeButton() {
    const optBtn = document.getElementById('optimize-btn');
    if (!optBtn) return;

    let busy = false;

    // Use the custom CSS tooltip (data-tooltip) instead of the native title:
    // native title has a ~1.5s hover delay and is not i18n-aware.
    const setTip = (text) => {
        optBtn.setAttribute('data-tooltip', text);
        optBtn.removeAttribute('title');
    };

    const setIdle = () => {
        busy = false;
        optBtn.classList.remove('text-primary-500', 'animate-spin');
        optBtn.classList.add('text-slate-400');
        optBtn.querySelector('i').className = 'fas fa-magic text-[13px]';
        setTip(t('optimize_idle_title'));
        optBtn.style.pointerEvents = '';
    };
    const setBusy = () => {
        busy = true;
        optBtn.classList.remove('text-slate-400');
        optBtn.classList.add('text-primary-500');
        optBtn.querySelector('i').className = 'fas fa-spinner fa-spin text-[13px]';
        setTip(t('optimize_busy_title'));
        optBtn.style.pointerEvents = 'none';
    };

    // Shared flashError from mic setup — reuse its style by injecting into the same wrapper
    const flashError = (msg) => {
        console.warn('[optimize]', msg);
        const wrapper = optBtn.parentElement;
        if (!wrapper) return;
        let tip = wrapper.querySelector('.opt-tip');
        if (!tip) {
            tip = document.createElement('div');
            tip.className = 'opt-tip absolute right-9 bottom-full mb-2 px-2 py-1 rounded-md '
                + 'text-xs text-white bg-slate-800/90 dark:bg-slate-700/90 shadow-md '
                + 'pointer-events-none whitespace-nowrap z-10';
            wrapper.appendChild(tip);
        }
        tip.textContent = msg;
        tip.style.opacity = '1';
        tip.style.transition = '';
        clearTimeout(tip._timer);
        tip._timer = setTimeout(() => {
            tip.style.transition = 'opacity 200ms';
            tip.style.opacity = '0';
        }, 2500);
    };

    optBtn.addEventListener('click', async () => {
        if (busy) return;
        const raw = chatInput.value.trim();
        if (!raw) {
            flashError(t('optimize_empty'));
            return;
        }
        setBusy();
        try {
            // Gather optional context: last few message groups visible in the chat.
            // User and bot messages are distinguished by their group class.
            const contextMessages = [];
            const groups = messagesDiv.querySelectorAll('.user-message-group, .bot-message-group');
            const recentGroups = Array.from(groups).slice(-6);
            for (const g of recentGroups) {
                const role = g.classList.contains('user-message-group') ? 'user' : 'assistant';
                // Only read the main message content, not action buttons or timestamps.
                const contentEl = g.querySelector('.msg-content');
                const text = ((contentEl || g).textContent || '').trim().slice(0, 200);
                if (text) {
                    contextMessages.push({ role: role, content: text });
                }
            }

            const resp = await fetch('/api/prompt/optimize', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ input: raw, context_messages: contextMessages }),
            });
            const data = await resp.json();
            if (data.status === 'success' && data.optimized) {
                chatInput.value = data.optimized;
                chatInput.dispatchEvent(new Event('input', { bubbles: true }));
                chatInput.focus();
                // Place cursor at end
                chatInput.setSelectionRange(chatInput.value.length, chatInput.value.length);
            } else {
                flashError(data.message || t('optimize_error'));
            }
        } catch (e) {
            flashError(t('optimize_error') + ': ' + e.message);
        } finally {
            setIdle();
        }
    });

    setIdle();
})();


// Smart auto-scroll: pause as soon as the user scrolls up, resume only when
// they return near the bottom. We must distinguish a real user gesture from
// the programmatic scroll that scrollChatToBottom() performs on every stream
// tick — otherwise a tiny upward scroll (still within the bottom threshold)
// leaves auto-scroll on and the next tick yanks the view back down, which
// feels like the list "fighting" the user and snapping to the bottom.
let _autoScrollEnabled = true;
const _SCROLL_THRESHOLD = 80; // px from bottom to re-enable auto-scroll
let _programmaticScroll = false; // set while scrollChatToBottom() adjusts scrollTop
let _lastScrollTop = 0;

messagesDiv.addEventListener('scroll', () => {
    const scrollTop = messagesDiv.scrollTop;
    const distFromBottom = messagesDiv.scrollHeight - scrollTop - messagesDiv.clientHeight;

    if (_programmaticScroll) {
        // Our own scroll-to-bottom; don't reinterpret it as user intent.
        _programmaticScroll = false;
    } else if (scrollTop < _lastScrollTop - 1) {
        // User scrolled up (any amount) -> stop following the stream.
        _autoScrollEnabled = false;
    } else if (distFromBottom <= _SCROLL_THRESHOLD) {
        // User is back near the bottom -> resume auto-scroll.
        _autoScrollEnabled = true;
    }

    _lastScrollTop = scrollTop;
    _updateScrollToBottomBtn();
});

// Intercept internal navigation links in chat messages
messagesDiv.addEventListener('click', (e) => {
    // Code block copy button
    const codeCopyBtn = e.target.closest('.code-copy-btn');
    if (codeCopyBtn) {
        e.preventDefault();
        const wrapper = codeCopyBtn.closest('.code-block-wrapper');
        const codeEl = wrapper && wrapper.querySelector('pre code');
        if (codeEl) {
            const codeText = codeEl.textContent;
            copyToClipboard(codeText).then(() => {
                const icon = codeCopyBtn.querySelector('i');
                if (icon) { icon.className = 'fas fa-check'; setTimeout(() => { icon.className = 'fas fa-copy'; }, 1500); }
            });
        }
        return;
    }

    const copyBtn = e.target.closest('.copy-msg-btn');
    if (copyBtn) {
        e.preventDefault();
        const msgRoot = copyBtn.closest('.flex.gap-3');
        const answerEl = msgRoot && msgRoot.querySelector('.answer-content');
        const rawMd = answerEl && answerEl.dataset.rawMd;
        if (rawMd) {
            copyToClipboard(rawMd).then(() => {
                const icon = copyBtn.querySelector('i');
                if (icon) { icon.className = 'fas fa-check'; setTimeout(() => { icon.className = 'fas fa-copy'; }, 1500); }
            });
        }
        return;
    }

    // Edit user message
    const editBtn = e.target.closest('.edit-msg-btn');
    if (editBtn) {
        e.preventDefault();
        if (isCurrentSessionConversationActive()) return;
        const msgRoot = editBtn.closest('.user-message-group');
        if (msgRoot) editUserMessage(msgRoot);
        return;
    }

    // Regenerate bot response
    const regenerateBtn = e.target.closest('.regenerate-msg-btn');
    if (regenerateBtn) {
        e.preventDefault();
        const botMsgRoot = regenerateBtn.closest('.flex.gap-3');
        if (botMsgRoot) regenerateResponse(botMsgRoot);
        return;
    }

    // Delete message (user bubble only; bot bubbles intentionally lack a
    // delete button — removing only the bot reply would leave an orphan
    // user message that breaks LLM context alternation).
    const deleteBtn = e.target.closest('.delete-msg-btn');
    if (deleteBtn) {
        e.preventDefault();
        if (isCurrentSessionConversationActive()) return;
        const userMsgEl = deleteBtn.closest('.user-message-group');
        if (!userMsgEl) return;

        showConfirmModal(t('delete_message_title'), t('delete_message_confirm'), () => {
            // Find the next bot reply for this turn (skip non-message nodes).
            let botReplyEl = null;
            let sibling = userMsgEl.nextElementSibling;
            while (sibling) {
                if (sibling.classList && sibling.classList.contains('bot-message-group')) {
                    botReplyEl = sibling;
                    break;
                }
                sibling = sibling.nextElementSibling;
            }
            userMsgEl.remove();
            if (botReplyEl) botReplyEl.remove();

            const userSeq = userMsgEl.dataset.seq;
            if (userSeq) {
                fetch('/api/messages/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ session_id: sessionId, user_seq: parseInt(userSeq) })
                }).then(r => r.json()).then(data => {
                    if (data.status === 'success') console.log(`Deleted ${data.deleted} messages`);
                }).catch(err => console.error('Failed to delete:', err));
            }
        });
        return;
    }

    const a = e.target.closest('a');
    if (!a) return;
    const href = a.getAttribute('href') || '';
    if (href === '/memory/dreams') {
        e.preventDefault();
        navigateTo('memory');
        setTimeout(() => switchMemoryTab('dreams'), 50);
    } else if (href === '/memory/MEMORY.md') {
        e.preventDefault();
        navigateTo('memory');
        setTimeout(() => { switchMemoryTab('files'); openMemoryFile('MEMORY.md', 'memory'); }, 50);
    }
});
const attachmentPreview = document.getElementById('attachment-preview');

// Pending attachments: [{file_path, file_name, file_type, preview_url}]
// Items with _uploading=true are still in flight.
let pendingAttachments = [];
let uploadingCount = 0;

// Input history (like terminal arrow-key recall)
const inputHistory = [];
let historyIdx = -1;
let historySavedDraft = '';

// While an SSE stream is in flight, the send button morphs into a cancel
// button. Only one in-flight request is supported at a time.
let activeRequestId = null;
let sendBtnMode = 'send'; // 'send' | 'cancel'

function setSendBtnCancelMode(requestId) {
    activeRequestId = requestId;
    sendBtnMode = 'cancel';
    sendBtn.disabled = false;
    sendBtn.classList.add('send-btn-cancel');
    _setBtnTooltip(sendBtn, t('tip_cancel'));
    sendBtn.innerHTML = '<i class="fas fa-stop text-sm"></i>';
    updateSteerBtnState();
}

function resetSendBtnSendMode() {
    activeRequestId = null;
    sendBtnMode = 'send';
    sendBtn.classList.remove('send-btn-cancel');
    _setBtnTooltip(sendBtn, '');
    sendBtn.innerHTML = '<i class="fas fa-paper-plane text-sm"></i>';
    steerBtn.classList.add('hidden');
    steerBtn.classList.remove('flex');
    steerBtn.disabled = true;
    updateSendBtnState();
    // A turn just finished — refresh the mini pie (and the card if it's open)
    // so the context indicator tracks the latest usage in real time.
    if (typeof _ctxRefresh === 'function') { try { _ctxRefresh({}); } catch (_) {} }
}

function updateSteerBtnState() {
    // Show the steer button only while a task is running AND the user has typed
    // something to steer with — a blank composer keeps it hidden so the toolbar
    // stays clean until there's actually guidance to send.
    const running = sendBtnMode === 'cancel' && !!activeRequestId;
    const hasText = !!(chatInput && chatInput.value.trim());
    const active = running && hasText;
    steerBtn.classList.toggle('hidden', !active);
    steerBtn.classList.toggle('flex', active);
    steerBtn.disabled = !active || uploadingCount > 0;
}

function steerActiveTask() {
    const instruction = chatInput.value.trim();
    if (!instruction || sendBtnMode !== 'cancel' || !activeRequestId) return;

    inputHistory.push(instruction);
    historyIdx = -1;
    historySavedDraft = '';
    addUserMessage(`↪ ${instruction}`, new Date());

    chatInput.value = '';
    resetComposerHeight();
    updateSteerBtnState();

    fetch('/message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            session_id: sessionId,
            message: instruction,
            steer: true,
            stream: false,
            lang: currentLang,
        }),
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'success' && data.inline_reply) {
            addBotMessage(data.inline_reply, new Date());
        } else {
            addBotMessage(t('error_send'), new Date());
        }
    })
    .catch(err => {
        console.warn('[steer] request failed', err);
        addBotMessage(t('error_send'), new Date());
    })
    .finally(updateSteerBtnState);
}

steerBtn.addEventListener('click', steerActiveTask);

function requestCancel() {
    const reqId = activeRequestId;
    if (!reqId) return;
    fetch('/cancel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request_id: reqId, session_id: sessionId, lang: currentLang }),
    }).catch(err => {
        console.warn('[cancel] request failed', err);
    });
    // Optimistic UI lock so the click visibly registers before the SSE
    // "cancelled" event arrives.
    sendBtn.disabled = true;
    _setBtnTooltip(sendBtn, t('tip_cancelled'));
}

// Button click is the only path to Cancel. Pressing Enter still calls
// sendMessage() so users can submit "/cancel" as a regular slash command.
sendBtn.addEventListener('click', () => {
    if (sendBtnMode === 'cancel') {
        requestCancel();
    } else {
        sendMessage();
    }
});

function updateSendBtnState() {
    if (sendBtnMode === 'cancel') {
        // Self-heal a stuck Cancel button: if there's no live stream backing
        // the current request, the cancel state leaked (e.g. a stream ended
        // without resetting). Recover to Send so the input isn't blocked.
        if (!activeRequestId || !activeStreams[activeRequestId]) {
            resetSendBtnSendMode();
        } else {
            // Don't downgrade a genuinely active Cancel button on input edits.
            updateSteerBtnState();
            return;
        }
    }
    sendBtn.disabled = uploadingCount > 0 || (!chatInput.value.trim() && pendingAttachments.length === 0);
    updateSteerBtnState();
}

function renderAttachmentPreview() {
    if (pendingAttachments.length === 0) {
        attachmentPreview.classList.add('hidden');
        attachmentPreview.innerHTML = '';
        updateSendBtnState();
        return;
    }
    attachmentPreview.classList.remove('hidden');
    attachmentPreview.innerHTML = pendingAttachments.map((att, idx) => {
        if (att._uploading) {
            const suffix = att.file_type === 'directory' && att.file_count
                ? ` (${att.file_count})`
                : '';
            return `<div class="att-chip att-uploading" data-idx="${idx}">
                <i class="fas fa-spinner fa-spin"></i>
                <span class="att-name">${escapeHtml(att.file_name)}${suffix}</span>
            </div>`;
        }
        if (att.file_type === 'image') {
            return `<div class="att-thumb" data-idx="${idx}">
                <img src="${att.preview_url}" alt="${escapeHtml(att.file_name)}">
                <button class="att-remove" onclick="removeAttachment(${idx})">&times;</button>
            </div>`;
        }
        const icon = att.file_type === 'video'
            ? 'fa-film'
            : (att.file_type === 'directory' ? 'fa-folder-tree'
            : (att.is_dir ? 'fa-folder' : 'fa-file-alt'));
        const suffix = att.file_type === 'directory' && att.file_count
            ? ` (${att.file_count})`
            : '';
        return `<div class="att-chip" data-idx="${idx}">
            <i class="fas ${icon}"></i>
            <span class="att-name">${escapeHtml(att.file_name)}${suffix}</span>
            <button class="att-remove" onclick="removeAttachment(${idx})">&times;</button>
        </div>`;
    }).join('');
    updateSendBtnState();
}

function removeAttachment(idx) {
    if (pendingAttachments[idx]?._uploading) return;
    pendingAttachments.splice(idx, 1);
    renderAttachmentPreview();
}

function isAttachMenuVisible() {
    return attachMenu && !attachMenu.classList.contains('hidden');
}

function hideAttachMenu() {
    if (attachMenu) attachMenu.classList.add('hidden');
}

function toggleAttachMenu(event) {
    if (!attachMenu) return;
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    attachMenu.classList.toggle('hidden');
}

function triggerFileUpload() {
    hideAttachMenu();
    fileInput?.click();
}

function triggerFolderUpload() {
    if (!supportsDirectoryUpload) return;
    hideAttachMenu();
    folderInput?.click();
}

async function handleFileSelect(files) {
    if (!files || files.length === 0) return;
    const tasks = [];
    for (const file of files) {
        const placeholder = { file_name: file.name, file_type: 'file', _uploading: true };
        pendingAttachments.push(placeholder);
        uploadingCount++;
        renderAttachmentPreview();

        tasks.push((async () => {
            const formData = new FormData();
            formData.append('file', file);
            formData.append('session_id', sessionId);
            try {
                const resp = await fetch('/upload', { method: 'POST', body: formData });
                const data = await resp.json();
                if (data.status === 'success') {
                    placeholder.file_path = data.file_path;
                    placeholder.file_name = data.file_name;
                    placeholder.file_type = data.file_type;
                    placeholder.preview_url = data.preview_url;
                    delete placeholder._uploading;
                } else {
                    const i = pendingAttachments.indexOf(placeholder);
                    if (i !== -1) pendingAttachments.splice(i, 1);
                }
            } catch (e) {
                console.error('Upload failed:', e);
                const i = pendingAttachments.indexOf(placeholder);
                if (i !== -1) pendingAttachments.splice(i, 1);
            }
            uploadingCount--;
            renderAttachmentPreview();
        })());
    }
    await Promise.all(tasks);
}

function _makeUploadId() {
    return `dir_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

function _groupDirectoryFiles(files) {
    const groups = new Map();
    for (const file of Array.from(files || [])) {
        const relPath = file.webkitRelativePath || file.name;
        const parts = relPath.split('/').filter(Boolean);
        const rootName = parts[0] || file.name;
        if (!groups.has(rootName)) groups.set(rootName, []);
        groups.get(rootName).push({ file, relPath });
    }
    return groups;
}

async function handleFolderSelect(files) {
    if (!files || files.length === 0) return;
    const groups = _groupDirectoryFiles(files);
    const groupTasks = [];

    for (const [rootName, entries] of groups.entries()) {
        const placeholder = {
            file_name: rootName,
            file_type: 'directory',
            file_count: entries.length,
            _uploading: true,
        };
        pendingAttachments.push(placeholder);
        uploadingCount++;
        renderAttachmentPreview();

        const uploadId = _makeUploadId();
        groupTasks.push((async () => {
            try {
                const formData = new FormData();
                formData.append('session_id', sessionId);
                formData.append('upload_id', uploadId);
                for (const { file, relPath } of entries) {
                    formData.append('files', file);
                    formData.append('relative_paths', relPath);
                }

                const resp = await fetch('/upload', { method: 'POST', body: formData });
                const data = await resp.json();
                if (data.status !== 'success') {
                    throw new Error(data.message || 'Upload failed');
                }
                if (!data.root_path) {
                    throw new Error('Directory root path missing');
                }
                placeholder.file_path = data.root_path;
                placeholder.file_name = data.root_name || rootName;
                delete placeholder._uploading;
            } catch (e) {
                console.error('Directory upload failed:', e);
                const i = pendingAttachments.indexOf(placeholder);
                if (i !== -1) pendingAttachments.splice(i, 1);
            } finally {
                uploadingCount--;
            }
            renderAttachmentPreview();
        })());
    }

    await Promise.all(groupTasks);
}

fileInput.addEventListener('change', function() {
    handleFileSelect(this.files);
    this.value = '';
});

folderInput.addEventListener('change', function() {
    handleFolderSelect(this.files);
    this.value = '';
});

document.addEventListener('click', (e) => {
    if (!isAttachMenuVisible()) return;
    if (attachMenu.contains(e.target) || attachBtn.contains(e.target)) return;
    hideAttachMenu();
});

// =====================================================================
// Workspace selector (project picker above the input)
// =====================================================================
let _wsSelState = { current: null, recents: [], defaultWorkspace: '', projectsRoot: '' };

function _wsSelBtn() { return document.getElementById('workspace-selector-btn'); }
function _wsSelMenu() { return document.getElementById('workspace-selector-menu'); }

// Minimal self-dismissing toast for selector errors (no global toast exists).
function _wsToast(msg) {
    let el = document.getElementById('ws-sel-toast');
    if (!el) {
        el = document.createElement('div');
        el.id = 'ws-sel-toast';
        el.style.cssText = 'position:fixed;bottom:80px;left:50%;transform:translateX(-50%);' +
            'background:#1e293b;color:#fff;padding:8px 14px;border-radius:8px;font-size:13px;' +
            'z-index:9999;box-shadow:0 4px 16px rgba(0,0,0,0.2);opacity:0;transition:opacity .2s;';
        document.body.appendChild(el);
    }
    el.textContent = msg;
    el.style.opacity = '1';
    clearTimeout(el._t);
    el._t = setTimeout(() => { el.style.opacity = '0'; }, 2600);
}

// Refresh the selector state + label for the current session.
async function refreshWorkspaceSelector() {
    const label = document.getElementById('workspace-selector-label');
    try {
        // Scope the request to the active Agent so the default-workspace hint
        // matches the file panel's real root in multi-Agent setups.
        let url = `/api/projects?session=${encodeURIComponent(sessionId)}`;
        const aid = (typeof activeAgentId !== 'undefined') ? activeAgentId : '';
        if (aid) url += `&agent=${encodeURIComponent(aid)}`;
        const res = await fetch(url);
        const data = await res.json();
        if (data.status !== 'success') return;
        _wsSelState = {
            current: data.current || null,
            recents: data.recents || [],
            defaultWorkspace: data.default_workspace || '',
            projectsRoot: data.projects_root || '',
        };
        _wsSelUpdateLabel();
    } catch (e) { /* keep last label */ }
}

// Sync the selector button's label and hover tooltip with the current state.
// Called after every selection so the tooltip always shows the live full path.
function _wsSelUpdateLabel() {
    const label = document.getElementById('workspace-selector-label');
    if (label) {
        label.textContent = _wsSelState.current
            ? _wsSelState.current.name
            : t('ws_default_workspace');
    }
    const btn = _wsSelBtn();
    if (btn) {
        // The default workspace is the resting state, so it collapses to just
        // the folder icon (matching the desktop composer); a picked workspace
        // shows its name so the user knows they've moved off the default.
        btn.classList.toggle('composer-chip-icon-only', !_wsSelState.current);
        const full = _wsSelState.current
            ? _wsSelState.current.path
            : _wsSelState.defaultWorkspace;
        btn.setAttribute('data-tooltip', full || t('ws_sel_title'));
        btn.setAttribute('data-tooltip-pos', 'top');
        // Route through the body-level floating tooltip so the full path isn't
        // clipped/covered by the chat history above the input bar.
        btn.setAttribute('data-tip-float', '');
    }
}

function toggleWorkspaceSelector(event) {
    if (event) { event.preventDefault(); event.stopPropagation(); }
    const menu = _wsSelMenu();
    if (!menu) return;
    if (!menu.classList.contains('hidden')) {
        _wsSelHide();
        return;
    }
    _closeComposerMenus(menu);
    refreshWorkspaceSelector().then(renderWorkspaceSelectorMenu);
    menu.classList.remove('hidden');
    _wsSelBtn()?.classList.add('open');
}

function _wsSelHide() {
    const menu = _wsSelMenu();
    if (menu) menu.classList.add('hidden');
    _wsSelBtn()?.classList.remove('open');
}

function renderWorkspaceSelectorMenu() {
    const menu = _wsSelMenu();
    if (!menu) return;

    const parts = [];
    const isDefault = !_wsSelState.current;
    parts.push(`<div class="ws-sel-section-title">${escapeHtml(t('ws_sel_title'))}</div>`);
    // Default workspace: hovering shows the full ~/cow absolute path.
    parts.push(`
        <button class="ws-sel-item ${isDefault ? 'active' : ''}" onclick="selectWorkspaceProject(null)"
                data-tip-float data-tooltip="${escapeHtml(_wsSelState.defaultWorkspace || '')}" data-tooltip-pos="bottom">
            <i class="fas fa-house"></i>
            <span class="ws-sel-name">${escapeHtml(t('ws_default_workspace'))}</span>
            ${isDefault ? '<i class="fas fa-check ws-sel-check"></i>' : ''}
        </button>`);

    if ((_wsSelState.recents || []).length) {
        parts.push(`<div class="ws-sel-divider"></div>`);
        parts.push(`<div class="ws-sel-section-title">${escapeHtml(t('ws_sel_recents'))}</div>`);
        _wsSelState.recents.forEach(r => {
            const active = _wsSelState.current && _wsSelState.current.path === r.path;
            parts.push(`
                <button class="ws-sel-item ${active ? 'active' : ''}" onclick="selectWorkspaceProject('${_wsAttr(r.path)}')"
                        data-tip-float data-tooltip="${escapeHtml(r.path)}" data-tooltip-pos="bottom">
                    <i class="fas fa-folder"></i>
                    <span class="ws-sel-name">${escapeHtml(r.name)}</span>
                    ${active ? '<i class="fas fa-check ws-sel-check"></i>' : ''}
                </button>`);
        });
    }

    parts.push(`<div class="ws-sel-divider"></div>`);
    parts.push(`
        <button class="ws-sel-item" onclick="wsSelOpenProjectDialog()">
            <i class="fas fa-folder-open"></i>
            <span class="ws-sel-name">${escapeHtml(t('ws_sel_open'))}</span>
        </button>`);
    parts.push(`
        <button class="ws-sel-item" onclick="wsSelNewProjectDialog()">
            <i class="fas fa-folder-plus"></i>
            <span class="ws-sel-name">${escapeHtml(t('ws_sel_new'))}</span>
        </button>`);

    menu.innerHTML = parts.join('');
}

// Escape a path for safe embedding inside a single-quoted inline handler.
function _wsAttr(p) { return String(p || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'"); }

// ------- Folder picker modal (open an existing project) -------
let _fpCurrent = '';   // absolute path currently listed
let _fpBound = false;  // one-time listener binding guard

function wsSelOpenProjectDialog() {
    _wsSelHide();
    _fpBindOnce();
    const overlay = document.getElementById('folder-picker-overlay');
    document.getElementById('folder-picker-cancel').textContent = t('channels_cancel') || t('ws_sel_up');
    document.getElementById('folder-picker-open').textContent = t('ws_sel_open_here');
    document.getElementById('folder-picker-hint').textContent = t('ws_sel_dblclick_hint');
    overlay.classList.remove('hidden');
    _fpBrowse('');  // '' => backend starts at ~
}

function _fpBindOnce() {
    if (_fpBound) return;
    _fpBound = true;
    const overlay = document.getElementById('folder-picker-overlay');
    const close = () => overlay.classList.add('hidden');
    document.getElementById('folder-picker-cancel').addEventListener('click', close);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    document.getElementById('folder-picker-open').addEventListener('click', async () => {
        if (!_fpCurrent) return;
        const ok = await _wsSelApply('/api/projects/select', { session: sessionId, project_dir: _fpCurrent });
        if (ok) close();
    });
}

// Virtual path (Windows) that lists logical drives; not a real openable dir.
const _FP_DRIVES = '__DRIVES__';

async function _fpBrowse(path) {
    const list = document.getElementById('folder-picker-list');
    list.innerHTML = `<div class="fp-empty"><i class="fas fa-spinner fa-spin"></i></div>`;
    try {
        const res = await fetch(`/api/projects/browse?path=${encodeURIComponent(path || '')}`);
        const data = await res.json();
        if (data.status !== 'success') { list.innerHTML = `<div class="fp-empty">${escapeHtml(data.message || 'error')}</div>`; return; }
        const isDrives = data.path === _FP_DRIVES;
        _fpCurrent = isDrives ? null : data.path;
        // Drives view is a selector, not a real directory: show a label and
        // disable "Open here" so the sentinel can't be picked as a project.
        const label = isDrives ? (t('ws_sel_drives') || 'This PC') : data.path;
        document.getElementById('folder-picker-path').textContent = label;
        document.getElementById('folder-picker-path').setAttribute('title', label);
        document.getElementById('folder-picker-open').disabled = isDrives;
        _fpRenderToolbar(data);
        _fpRenderList(data);
    } catch (e) {
        list.innerHTML = `<div class="fp-empty">${escapeHtml(String(e.message || e))}</div>`;
    }
}

function _fpRenderToolbar(data) {
    const bar = document.getElementById('folder-picker-toolbar');
    const upDisabled = !data.parent;
    bar.innerHTML = `
        <button class="fp-btn" ${upDisabled ? 'disabled' : ''} onclick="_fpBrowse('${_wsAttr(data.parent || '')}')" data-tooltip="${escapeHtml(t('ws_sel_up'))}" data-tooltip-pos="bottom">
            <i class="fas fa-arrow-up"></i>
        </button>
        <button class="fp-btn" onclick="_fpBrowse('~')" data-tooltip="~" data-tooltip-pos="bottom">
            <i class="fas fa-house"></i>
        </button>`;
}

function _fpRenderList(data) {
    const list = document.getElementById('folder-picker-list');
    const dirs = data.dirs || [];
    if (!dirs.length) {
        list.innerHTML = `<div class="fp-empty"><i class="fas fa-folder-open"></i><span>${escapeHtml(t('ws_sel_no_subdirs'))}</span></div>`;
        return;
    }
    list.innerHTML = dirs.map(d => `
        <div class="fp-row" ondblclick="_fpBrowse('${_wsAttr(d.path)}')" onclick="_fpSelectRow(this,'${_wsAttr(d.path)}')" title="${escapeHtml(d.path)}">
            <i class="fas fa-folder"></i>
            <span class="fp-name">${escapeHtml(d.name)}</span>
            <i class="fas fa-chevron-right fp-into" onclick="event.stopPropagation();_fpBrowse('${_wsAttr(d.path)}')"></i>
        </div>`).join('');
}

// Single click selects a child folder as the target (so you can open a folder
// without navigating into it); double click / chevron navigates inside.
function _fpSelectRow(el, path) {
    document.querySelectorAll('#folder-picker-list .fp-row.selected').forEach(r => r.classList.remove('selected'));
    el.classList.add('selected');
    _fpCurrent = path;
    // Picking a row (e.g. a drive in the drives view) is a valid target again.
    document.getElementById('folder-picker-open').disabled = false;
    document.getElementById('folder-picker-path').textContent = path;
}

// Create a new project by name (lands under the projects root), then open it.
function wsSelNewProjectDialog() {
    _wsSelHide();
    openKnowledgeDialog({
        title: t('ws_sel_new'),
        subtitle: (t('ws_sel_new_subtitle') || '').replace('{root}', _wsSelState.projectsRoot || ''),
        label: t('ws_sel_new_placeholder'),
        hint: t('ws_sel_new_hint'),
        icon: 'fa-folder-plus',
        value: '',
        validate: (v) => {
            v = (v || '').trim();
            if (!v) return t('ws_sel_name_required');
            if (v.includes('/') || v.includes('\\')) return t('ws_sel_name_no_slash');
            return '';
        },
        onSubmit: async (name) => {
            const ok = await _wsSelApply('/api/projects/create', { session: sessionId, name: name.trim() });
            return ok ? true : null;
        },
    });
}

// Shared apply path for select/create: POST, update label, then reveal the
// project in the right-hand file panel so the user sees they are "inside" it.
async function _wsSelApply(url, body) {
    try {
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await res.json();
        if (data.status !== 'success') { _wsToast(data.message || 'failed'); return false; }
        _wsSelState.current = data.current || null;
        if (Array.isArray(data.recents)) _wsSelState.recents = data.recents;
        if (data.default_workspace) _wsSelState.defaultWorkspace = data.default_workspace;
        _wsSelUpdateLabel();
        _wsSelRevealFiles();
        return true;
    } catch (e) { _wsToast(String(e.message || e)); return false; }
}

// Open (or refresh) the right-hand file panel on the Files tab so the newly
// selected project's directory is visible.
function _wsSelRevealFiles() {
    try {
        if (typeof openWorkspacePanel === 'function') {
            wsAutoOpenSuppressed = false;
            // Reset to the root of the new workspace before opening.
            if (typeof wsCurrentDir !== 'undefined') wsCurrentDir = '';
            openWorkspacePanel('files');
        }
        if (typeof refreshWorkspaceTree === 'function') refreshWorkspaceTree();
    } catch (e) { /* panel not present on this view */ }
}

// Kept for callers that select without a dialog (default / recents).
async function selectWorkspaceProject(projectDir) {
    _wsSelHide();
    await _wsSelApply('/api/projects/select', { session: sessionId, project_dir: projectDir });
}

document.addEventListener('click', (e) => {
    const menu = _wsSelMenu();
    const btn = _wsSelBtn();
    if (!menu || menu.classList.contains('hidden')) return;
    if (menu.contains(e.target) || (btn && btn.contains(e.target))) return;
    _wsSelHide();
});

// =====================================================================
// Per-session settings: permission mode and model
//
// Both live next to the workspace picker under the input, because all three
// answer the same question - what this conversation is allowed to do, and with
// what. Each falls back to the global setting until the user pins one here, so
// a session that was never touched keeps following Settings.
// =====================================================================

// Icons and i18n keys per mode. Ordered most-open first so the menu reads from
// "least restricted" downward, matching how the chip colours escalate.
const PERMISSION_META = {
    'full-access':     { icon: 'fa-lock-open',     key: 'perm_full_access' },
    'workspace-write': { icon: 'fa-shield-halved', key: 'perm_workspace_write' },
    'read-only':       { icon: 'fa-eye',           key: 'perm_read_only' },
};

// Last state from GET /api/sessions/<id>/settings; null until first fetch.
let _sessCfg = null;

function _permBtn() { return document.getElementById('permission-selector-btn'); }
function _permMenu() { return document.getElementById('permission-selector-menu'); }
function _modelBtn() { return document.getElementById('model-selector-btn'); }
function _modelMenu() { return document.getElementById('model-selector-menu'); }

function _permLabel(mode) { return t((PERMISSION_META[mode] || {}).key || 'perm_full_access'); }

/** Close every composer popover except `keep` (so one chip's menu replaces another's). */
function _closeComposerMenus(keep) {
    [[_wsSelMenu(), _wsSelBtn()], [_permMenu(), _permBtn()], [_modelMenu(), _modelBtn()]]
        .forEach(([menu, btn]) => {
            if (!menu || menu === keep) return;
            menu.classList.add('hidden');
            if (btn) btn.classList.remove('open');
        });
    const agentMenu = document.getElementById('composer-agent-menu');
    if (agentMenu && agentMenu !== keep) agentMenu.classList.add('hidden');
}

// Fetch this session's effective model + permission and repaint both chips.
async function refreshSessionSettings() {
    try {
        const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/settings`);
        const data = await res.json();
        if (data.status !== 'success') return;
        _sessCfg = { model: data.model, permission: data.permission, team: data.team };
    } catch (e) {
        // Keep whatever the chips already show rather than blanking them.
        return;
    }
    _renderPermissionChip();
    _renderModelChip();
    _renderInputPlaceholder();
    renderComposerIdentity();
}

function _renderPermissionChip() {
    const btn = _permBtn();
    if (!btn || !_sessCfg) return;
    const state = _sessCfg.permission || {};
    const mode = state.mode || 'full-access';
    const meta = PERMISSION_META[mode] || PERMISSION_META['full-access'];

    const label = document.getElementById('permission-selector-label');
    if (label) label.textContent = _permLabel(mode);
    const icon = document.getElementById('permission-selector-icon');
    if (icon) icon.className = `fas ${meta.icon}`;

    // One colour per mode, so an unrestricted session is visibly different from
    // a read-only one without having to read the label.
    btn.classList.remove('perm-read-only', 'perm-workspace-write', 'perm-full-access');
    btn.classList.add(`perm-${mode}`);

    const tip = t('perm_tip').replace('{name}', _permLabel(mode))
        + (state.source === 'global' ? ` · ${t('perm_follow_global')}` : '');
    btn.setAttribute('data-tooltip', tip);
    btn.setAttribute('data-tooltip-pos', 'top');
    btn.setAttribute('data-tip-float', '');
}

// The composer placeholder only advertises "@ an Agent" when the conversation
// actually has other members to address. A solo chat can only @ files, so it
// falls back to the file-only hint. Runs whenever the session's team changes.
function _renderInputPlaceholder() {
    const input = document.getElementById('chat-input');
    if (!input) return;
    input.placeholder = t(sharedConversation() ? 'input_placeholder_team' : 'input_placeholder');
}

function _renderModelChip() {
    const btn = _modelBtn();
    if (!btn || !_sessCfg) return;
    // Once a conversation has more than one Agent there is no single model to
    // show: each answers on its own. Pinning one here would silently apply to
    // whoever happens to own the conversation.
    const shared = sharedConversation();
    btn.classList.toggle('hidden', shared);
    if (shared) {
        _modelMenu()?.classList.add('hidden');
        btn.classList.remove('open');
        return;
    }
    const state = _sessCfg.model || {};
    const model = state.model || '';

    const label = document.getElementById('model-selector-label');
    if (label) label.textContent = model || t('model_unset');

    const tip = t('model_tip').replace('{name}', model || t('model_unset'))
        + (state.source === 'global' ? ` · ${t('model_follow_global')}` : '')
        + (state.source === 'agent' ? ` · ${t('model_follow_agent')}` : '');
    btn.setAttribute('data-tooltip', tip);
    btn.setAttribute('data-tooltip-pos', 'top');
    btn.setAttribute('data-tip-float', '');
}

function togglePermissionSelector(event) {
    if (event) { event.preventDefault(); event.stopPropagation(); }
    const menu = _permMenu();
    if (!menu) return;
    if (!menu.classList.contains('hidden')) {
        _closeComposerMenus();
        return;
    }
    _closeComposerMenus(menu);
    const open = () => { renderPermissionMenu(); menu.classList.remove('hidden'); _permBtn()?.classList.add('open'); };
    if (_sessCfg) open(); else refreshSessionSettings().then(open);
}

function renderPermissionMenu() {
    const menu = _permMenu();
    if (!menu) return;
    const state = (_sessCfg && _sessCfg.permission) || {};
    const modes = state.modes && state.modes.length ? state.modes : Object.keys(PERMISSION_META);
    const current = state.mode || 'full-access';
    const isGlobal = state.source === 'global';

    const parts = [`<div class="composer-menu-title">${escapeHtml(t('perm_menu_title'))}</div>`];
    // Menu order follows PERMISSION_META, not the backend tuple, so the list
    // reads consistently even if the backend reorders its modes. "Follow global"
    // is intentionally not a row of its own: picking a mode simply pins it, and
    // clicking the already-active mode clears the pin (back to global) so the
    // behaviour is still reachable without cluttering the menu.
    Object.keys(PERMISSION_META).filter(m => modes.includes(m)).forEach(mode => {
        const meta = PERMISSION_META[mode];
        const active = mode === current;
        // When this mode is the active one AND it is pinned, clicking it clears
        // the pin; otherwise clicking pins this mode.
        const arg = (active && !isGlobal) ? 'null' : `'${mode}'`;
        parts.push(`
            <button class="composer-menu-item ${active ? 'active' : ''}" onclick="selectSessionPermission(${arg})">
                <i class="fas ${meta.icon}"></i>
                <span class="composer-menu-body">
                    <span class="composer-menu-name">${escapeHtml(t(meta.key))}</span>
                    <span class="composer-menu-desc">${escapeHtml(t(meta.key + '_desc'))}</span>
                </span>
                ${active ? '<i class="fas fa-check composer-menu-check"></i>' : ''}
            </button>`);
    });

    menu.innerHTML = parts.join('');
}

/** Pin this session's permission mode, or pass null to follow the global one. */
async function selectSessionPermission(mode) {
    _closeComposerMenus();
    await _applySessionSettings({ permission: mode });
}

// Insert an actionable hint after a tool card whose call was refused by the
// permission gate. Clicking it opens the permission selector under the input so
// the user can raise the mode without hunting for the chip.
function _appendPermissionDeniedHint(toolEl, mode) {
    if (!toolEl || !toolEl.parentElement) return;
    // Avoid stacking duplicate hints if the model retries the same blocked call.
    if (toolEl.nextElementSibling
        && toolEl.nextElementSibling.classList
        && toolEl.nextElementSibling.classList.contains('perm-denied-hint')) {
        return;
    }
    const label = _permLabel(mode || (_sessCfg && _sessCfg.permission && _sessCfg.permission.mode) || 'workspace-write');
    const hint = document.createElement('div');
    hint.className = 'perm-denied-hint';
    hint.innerHTML = `
        <i class="fas fa-shield-halved"></i>
        <span class="perm-denied-text">${escapeHtml(t('perm_denied_hint').replace('{name}', label))}</span>
        <button type="button" class="perm-denied-btn">${escapeHtml(t('perm_denied_action'))}</button>`;
    hint.querySelector('.perm-denied-btn').addEventListener('click', (e) => {
        e.stopPropagation();
        const btn = _permBtn();
        if (btn) { btn.scrollIntoView({ block: 'nearest' }); }
        togglePermissionSelector();
    });
    toolEl.parentElement.insertBefore(hint, toolEl.nextElementSibling);
}

function toggleModelSelector(event) {
    if (event) { event.preventDefault(); event.stopPropagation(); }
    const menu = _modelMenu();
    if (!menu) return;
    if (!menu.classList.contains('hidden')) {
        _closeComposerMenus();
        return;
    }
    _closeComposerMenus(menu);
    const open = () => { renderModelMenu(); menu.classList.remove('hidden'); _modelBtn()?.classList.add('open'); };
    // Always re-fetch: the catalog depends on which providers have keys, which
    // may have changed in Settings since this page loaded.
    refreshSessionSettings().then(() => { if (_sessCfg) open(); });
}

function renderModelMenu() {
    const menu = _modelMenu();
    if (!menu) return;
    const state = (_sessCfg && _sessCfg.model) || {};
    const providers = state.providers || [];
    const pinned = state.source === 'session';

    // Which model is currently effective (pinned or inherited from global), so
    // the check mark shows on it even when the session follows the global model.
    const activeModel = state.model || (state.global && state.global.model) || '';
    const activeProvider = state.provider || (state.global && state.global.provider) || '';

    const parts = [`<div class="composer-menu-title">${escapeHtml(t('model_menu_title'))}</div>`];
    providers.forEach((p, idx) => {
        if (idx > 0) parts.push('<div class="composer-menu-divider"></div>');
        parts.push(`<div class="composer-menu-title">${escapeHtml(localizedLabel(p.label))}</div>`);
        (p.models || []).forEach(m => {
            const active = m === activeModel && p.id === activeProvider;
            // Clicking the already-pinned model clears the pin (back to global);
            // "follow global" is no longer a separate row.
            const arg = (active && pinned)
                ? 'null, null'
                : `'${_wsAttr(p.id)}','${_wsAttr(m)}'`;
            parts.push(`
                <button class="composer-menu-item ${active ? 'active' : ''}"
                        onclick="selectSessionModel(${arg})">
                    <i class="fas fa-microchip"></i>
                    <span class="composer-menu-body">
                        <span class="composer-menu-name">${escapeHtml(m)}</span>
                    </span>
                    ${active ? '<i class="fas fa-check composer-menu-check"></i>' : ''}
                </button>`);
        });
    });

    menu.innerHTML = parts.join('');
}

/** Pin a model for this session; pass nulls to follow the global model again. */
async function selectSessionModel(provider, model) {
    _closeComposerMenus();
    await _applySessionSettings({ provider: provider, model: model });
}

// Single writer for both chips: POST the change, then repaint from the state the
// backend echoes back so the UI can never disagree with what was stored.
async function _applySessionSettings(body) {
    try {
        const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/settings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await res.json();
        if (data.status !== 'success') { _wsToast(data.message || t('session_settings_failed')); return; }
        _sessCfg = { model: data.model, permission: data.permission };
        _renderPermissionChip();
        _renderModelChip();
    } catch (e) {
        _wsToast(t('session_settings_failed'));
    }
}

document.addEventListener('click', (e) => {
    [[_permMenu(), _permBtn()], [_modelMenu(), _modelBtn()]].forEach(([menu, btn]) => {
        if (!menu || menu.classList.contains('hidden')) return;
        if (menu.contains(e.target) || (btn && btn.contains(e.target))) return;
        menu.classList.add('hidden');
        if (btn) btn.classList.remove('open');
    });
});

// Drag-and-drop support on entire chat view
const chatView = document.getElementById('view-chat');
const chatInputArea = document.getElementById('composer-card') || chatInput.closest('.flex-shrink-0');

// Create drag overlay for visual feedback
let dragOverlay = document.getElementById('drag-overlay');
if (!dragOverlay) {
    dragOverlay = document.createElement('div');
    dragOverlay.id = 'drag-overlay';
    dragOverlay.className = 'drag-overlay hidden';
    dragOverlay.innerHTML = `
        <div class="drag-overlay-content">
            <i class="fas fa-cloud-arrow-up"></i>
            <p>Drop files here to upload</p>
        </div>
    `;
    chatView.appendChild(dragOverlay);
}

let dragCounter = 0;

function showDragOverlay() {
    dragOverlay.classList.remove('hidden');
    dragOverlay.classList.add('active');
}

function hideDragOverlay() {
    dragOverlay.classList.remove('active');
    dragOverlay.classList.add('hidden');
}

/** Clear every drag affordance at once, whatever the drag's outcome was. */
function resetDragState() {
    dragCounter = 0;
    hideDragOverlay();
    chatInputArea.classList.remove('drag-over');
    document.getElementById('chat-main')?.classList.remove('ws-drop-active');
}

chatView.addEventListener('dragenter', (e) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter++;
    if (e.dataTransfer.types.includes('Files')) {
        showDragOverlay();
    }
});

chatView.addEventListener('dragover', (e) => {
    e.preventDefault();
    e.stopPropagation();
    // Only external file drags upload here; workspace drags have their own target.
    if (e.dataTransfer.types.includes('Files')) {
        chatInputArea.classList.add('drag-over');
    }
});

chatView.addEventListener('dragleave', (e) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter--;
    if (dragCounter <= 0) {
        resetDragState();
    }
});

chatView.addEventListener('drop', (e) => {
    e.preventDefault();
    e.stopPropagation();
    resetDragState();
    if (e.dataTransfer.files.length) {
        handleFileSelect(e.dataTransfer.files);
    }
});

// A drag can end without ever reaching a drop target (Esc, or released over
// another element). Clear the highlight unconditionally so it can't stay stuck
// until the next reload.
document.addEventListener('dragend', resetDragState);
window.addEventListener('drop', resetDragState);

document.body.addEventListener('dragover', (e) => {
    if (e.dataTransfer.types.includes('Files')) {
        e.preventDefault();
    }
});

document.body.addEventListener('drop', (e) => {
    if (e.dataTransfer.types.includes('Files')) {
        e.preventDefault();
    }
});

// Paste image support
chatInput.addEventListener('paste', (e) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    const files = [];
    for (const item of items) {
        if (item.kind === 'file') {
            files.push(item.getAsFile());
        }
    }
    if (files.length) {
        e.preventDefault();
        handleFileSelect(files);
    }
});

chatInput.addEventListener('compositionstart', () => { isComposing = true; });
chatInput.addEventListener('compositionend', () => { setTimeout(() => { isComposing = false; }, 100); });

// ── Slash Command Menu ───────────────────────────────────────
// desc holds an i18n key, resolved via t() at render time so the menu follows
// the current UI language.
const SLASH_COMMANDS = [
    { cmd: '/help',                desc: 'slash_help' },
    { cmd: '/status',              desc: 'slash_status' },
    { cmd: '/context',             desc: 'slash_context' },
    { cmd: '/clear',               desc: 'slash_context_clear' },
    { cmd: '/compact',             desc: 'slash_compact' },
    { cmd: '/skill list',          desc: 'slash_skill_list' },
    { cmd: '/skill list --remote', desc: 'slash_skill_list_remote' },
    { cmd: '/skill search ',       desc: 'slash_skill_search' },
    { cmd: '/skill install ',      desc: 'slash_skill_install' },
    { cmd: '/skill uninstall ',    desc: 'slash_skill_uninstall' },
    { cmd: '/skill info ',         desc: 'slash_skill_info' },
    { cmd: '/skill enable ',       desc: 'slash_skill_enable' },
    { cmd: '/skill disable ',      desc: 'slash_skill_disable' },
    { cmd: '/memory dream ',       desc: 'slash_memory_dream' },
    { cmd: '/knowledge',           desc: 'slash_knowledge' },
    { cmd: '/knowledge list',      desc: 'slash_knowledge_list' },
    { cmd: '/knowledge on',        desc: 'slash_knowledge_on' },
    { cmd: '/knowledge off',       desc: 'slash_knowledge_off' },
    { cmd: '/config',              desc: 'slash_config' },
    { cmd: '/cancel',              desc: 'slash_cancel' },
    { cmd: '/steer ',              desc: 'slash_steer' },
    { cmd: '/logs',                desc: 'slash_logs' },
    { cmd: '/version',             desc: 'slash_version' },
];

const slashMenu = document.getElementById('slash-menu');
let slashActiveIdx = 0;
let slashFiltered = [];
let slashJustSelected = false;
let slashLastFilter = '';
let slashLastMouseX = -1;
let slashLastMouseY = -1;

function showSlashMenu(filter) {
    const q = filter.toLowerCase();
    if (q === slashLastFilter && !slashMenu.classList.contains('hidden')) return;
    slashLastFilter = q;

    const newFiltered = SLASH_COMMANDS.filter(c => c.cmd.toLowerCase().startsWith(q));
    if (newFiltered.length === 0) {
        hideSlashMenu();
        return;
    }

    const changed = newFiltered.length !== slashFiltered.length ||
        newFiltered.some((c, i) => c.cmd !== slashFiltered[i]?.cmd);
    slashFiltered = newFiltered;
    if (changed) slashActiveIdx = 0;
    slashActiveIdx = Math.min(slashActiveIdx, slashFiltered.length - 1);

    slashNavByKeyboard = true;
    renderSlashItems();
    slashMenu.classList.remove('hidden');
}

function hideSlashMenu() {
    slashMenu.classList.add('hidden');
    slashMenu.innerHTML = '';
    slashFiltered = [];
    slashActiveIdx = -1;
    slashLastFilter = '';
    slashNavByKeyboard = false;
    slashLastMouseX = -1;
    slashLastMouseY = -1;
}

function isSlashMenuVisible() {
    return !slashMenu.classList.contains('hidden') && slashFiltered.length > 0;
}

function renderSlashItems() {
    slashMenu.innerHTML =
        '<div class="slash-menu-header">Commands</div>' +
        slashFiltered.map((c, i) =>
            `<div class="slash-menu-item${i === slashActiveIdx ? ' active' : ''}" data-idx="${i}">` +
            `<span class="cmd">${escapeHtml(c.cmd)}</span>` +
            `<span class="desc">${escapeHtml(t(c.desc))}</span></div>`
        ).join('');

    const activeEl = slashMenu.querySelector('.slash-menu-item.active');
    if (activeEl) activeEl.scrollIntoView({ block: 'nearest' });
}

// Delegated events on the persistent slashMenu container (not destroyed by innerHTML)
// Use coordinate comparison to distinguish real mouse movement from DOM-rebuild phantom events.
slashMenu.addEventListener('mousemove', (e) => {
    if (e.clientX === slashLastMouseX && e.clientY === slashLastMouseY) return;
    slashLastMouseX = e.clientX;
    slashLastMouseY = e.clientY;
    if (!slashNavByKeyboard) return;
    slashNavByKeyboard = false;
    const item = e.target.closest('.slash-menu-item');
    if (!item) return;
    const idx = parseInt(item.dataset.idx);
    if (idx === slashActiveIdx) return;
    slashActiveIdx = idx;
    slashMenu.querySelectorAll('.slash-menu-item').forEach(el => {
        el.classList.toggle('active', parseInt(el.dataset.idx) === idx);
    });
});

slashMenu.addEventListener('mouseover', (e) => {
    if (slashNavByKeyboard) return;
    const item = e.target.closest('.slash-menu-item');
    if (!item) return;
    const idx = parseInt(item.dataset.idx);
    if (idx === slashActiveIdx) return;
    slashActiveIdx = idx;
    slashMenu.querySelectorAll('.slash-menu-item').forEach(el => {
        el.classList.toggle('active', parseInt(el.dataset.idx) === idx);
    });
});

slashMenu.addEventListener('mousedown', (e) => {
    const item = e.target.closest('.slash-menu-item');
    if (!item) return;
    e.preventDefault();
    selectSlashCommand(parseInt(item.dataset.idx));
});

function selectSlashCommand(idx) {
    if (idx < 0 || idx >= slashFiltered.length) return;
    const chosen = slashFiltered[idx].cmd;
    slashJustSelected = true;
    chatInput.value = chosen;
    chatInput.dispatchEvent(new Event('input'));
    hideSlashMenu();
    chatInput.focus();
    chatInput.selectionStart = chatInput.selectionEnd = chosen.length;
}

chatInput.addEventListener('input', function() {
    autoResizeComposer();
    updateSendBtnState();
    // Reveal/hide the steer button as the user types during a running turn.
    updateSteerBtnState();

    const val = this.value;
    if (slashJustSelected) {
        slashJustSelected = false;
    } else if (val.startsWith('/')) {
        showSlashMenu(val);
    } else {
        hideSlashMenu();
    }
});

chatInput.addEventListener('keydown', function(e) {
    if (e.keyCode === 229 || e.isComposing || isComposing) return;

    if (e.key === 'Escape' && isAttachMenuVisible()) {
        hideAttachMenu();
        return;
    }

    if (isSlashMenuVisible()) {
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            slashNavByKeyboard = true;
            slashActiveIdx = Math.min(slashActiveIdx + 1, slashFiltered.length - 1);
            renderSlashItems();
            return;
        }
        if (e.key === 'ArrowUp') {
            e.preventDefault();
            slashNavByKeyboard = true;
            slashActiveIdx = Math.max(slashActiveIdx - 1, 0);
            renderSlashItems();
            return;
        }
        if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey) {
            e.preventDefault();
            selectSlashCommand(slashActiveIdx);
            return;
        }
        if (e.key === 'Escape') {
            e.preventDefault();
            hideSlashMenu();
            return;
        }
        if (e.key === 'Tab') {
            e.preventDefault();
            selectSlashCommand(slashActiveIdx);
            return;
        }
    }

    // Arrow-key history recall (only when input is empty or already browsing history)
    if (e.key === 'ArrowUp' && inputHistory.length > 0 && !isSlashMenuVisible()) {
        const curVal = this.value.trim();
        const isSingleLine = !this.value.includes('\n');
        if (isSingleLine && (curVal === '' || historyIdx >= 0)) {
            e.preventDefault();
            if (historyIdx < 0) {
                historySavedDraft = this.value;
                historyIdx = inputHistory.length - 1;
            } else if (historyIdx > 0) {
                historyIdx--;
            }
            this.value = inputHistory[historyIdx];
            slashJustSelected = true;
            this.dispatchEvent(new Event('input'));
            hideSlashMenu();
            this.selectionStart = this.selectionEnd = this.value.length;
            return;
        }
    }
    if (e.key === 'ArrowDown' && historyIdx >= 0 && !isSlashMenuVisible()) {
        const isSingleLine = !this.value.includes('\n');
        if (isSingleLine) {
            e.preventDefault();
            if (historyIdx < inputHistory.length - 1) {
                historyIdx++;
                this.value = inputHistory[historyIdx];
            } else {
                historyIdx = -1;
                this.value = historySavedDraft;
                historySavedDraft = '';
            }
            slashJustSelected = true;
            this.dispatchEvent(new Event('input'));
            hideSlashMenu();
            this.selectionStart = this.selectionEnd = this.value.length;
            return;
        }
    }

    if ((e.ctrlKey || e.shiftKey) && e.key === 'Enter') {
        const start = this.selectionStart;
        const end = this.selectionEnd;
        this.value = this.value.substring(0, start) + '\n' + this.value.substring(end);
        this.selectionStart = this.selectionEnd = start + 1;
        this.dispatchEvent(new Event('input'));
        e.preventDefault();
    } else if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey) {
        sendMessage();
        e.preventDefault();
    }
});

chatInput.addEventListener('blur', () => {
    setTimeout(hideSlashMenu, 150);
});

document.querySelectorAll('.example-card').forEach(card => {
    card.addEventListener('click', () => {
        // data-send overrides the visible text (e.g. show "查看全部命令" but send "/help")
        const sendText = card.dataset.send;
        if (sendText) {
            chatInput.value = sendText;
            chatInput.dispatchEvent(new Event('input'));
            chatInput.focus();
            return;
        }
        const textEl = card.querySelector('[data-i18n*="text"]');
        if (textEl) {
            chatInput.value = textEl.textContent;
            chatInput.dispatchEvent(new Event('input'));
            chatInput.focus();
        }
    });
});

// Voice-message variant of sendMessage(): renders a playable audio bubble
// with the ASR caption, then dispatches the recognised text to /message
// through the same SSE/loading flow as a typed message.
function sendVoiceMessage(text, audioUrl) {
    text = (text || '').trim();
    if (!text) return;

    inputHistory.push(text);
    historyIdx = -1;
    historySavedDraft = '';

    const ws = document.getElementById('welcome-screen');
    const isFirstMessage = !!ws;
    if (ws) ws.remove();

    const titleInfo = isFirstMessage ? { sid: sessionId, userMsg: text } : null;
    const timestamp = new Date();
    addUserVoiceMessage(audioUrl, text, timestamp);
    const loadingEl = addLoadingIndicator();

    const body = {
        session_id: sessionId,
        message: text,
        stream: true,
        timestamp: timestamp.toISOString(),
        is_voice: true,
        lang: currentLang,
    };

    const MAX_RETRIES = 2;
    const RETRY_DELAY_MS = 1000;
    function postWithRetry(attempt) {
        fetch('/message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success') {
                rememberLiveSpeaker(data);
                setLoadingSpeaker(loadingEl, data.request_id);
                if (data.inline_reply) {
                    // Synchronous fast-path reply (e.g. /cancel); skip SSE.
                    loadingEl.remove();
                    addBotMessage(data.inline_reply, new Date());
                } else if (data.stream) {
                    setSendBtnCancelMode(data.request_id);
                    startSSE(data.request_id, loadingEl, timestamp, titleInfo);
                } else {
                    loadingContainers[data.request_id] = loadingEl;
                }
            } else {
                loadingEl.remove();
                addBotMessage(t('error_send'), new Date());
                resetSendBtnSendMode();
            }
        })
        .catch(err => {
            if (attempt < MAX_RETRIES) {
                setTimeout(() => postWithRetry(attempt + 1), RETRY_DELAY_MS * (attempt + 1));
                return;
            }
            loadingEl.remove();
            addBotMessage(t('error_send'), new Date());
        });
    }
    postWithRetry(0);
}

function addUserVoiceMessage(audioUrl, caption, timestamp) {
    const el = document.createElement('div');
    el.className = 'flex justify-end px-4 sm:px-6 py-3';
    // Voice-message bubble: compact voice pill on top, ASR caption beneath.
    // The bubble keeps the same primary tint as a normal user message so
    // it visually slots into the conversation flow.
    el.innerHTML = `
        <div class="max-w-[75%] sm:max-w-[60%]">
            <div class="bg-slate-100 dark:bg-white/10 text-slate-700 dark:text-slate-200 rounded-2xl px-3 py-2 msg-content user-bubble">
                <div class="user-voice-slot"></div>
                ${caption ? `<div class="text-xs mt-1.5 leading-snug text-slate-500 dark:text-slate-400 whitespace-pre-wrap break-words">${escapeHtml(caption)}</div>` : ''}
            </div>
            <div class="text-xs text-slate-400 dark:text-slate-500 mt-1.5 text-right">${formatTime(timestamp)}</div>
        </div>
    `;
    el.querySelector('.user-voice-slot').appendChild(renderVoicePill(audioUrl));
    messagesDiv.appendChild(el);
    _autoScrollEnabled = true;
    scrollChatToBottom(true);
}

// Clipboard helper with fallback for non-HTTPS environments
function copyToClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
        return navigator.clipboard.writeText(text);
    }
    // Fallback for HTTP environments
    return new Promise((resolve, reject) => {
        const textArea = document.createElement('textarea');
        textArea.value = text;
        textArea.style.position = 'fixed';
        textArea.style.left = '-999999px';
        textArea.style.top = '-999999px';
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        try {
            document.execCommand('copy') ? resolve() : reject(new Error('Copy failed'));
        } catch (err) {
            reject(err);
        } finally {
            textArea.remove();
        }
    });
}

// Edit user message: extract content, remove this and subsequent messages, fill input
async function editUserMessage(msgEl) {
    if (isCurrentSessionConversationActive()) return;
    const rawContent = msgEl.dataset.rawContent;
    if (!rawContent) return;

    // Delete this message and ALL subsequent messages from database (cascade)
    // Must await to ensure delete completes before user sends a new message
    const userSeq = msgEl.dataset.seq;
    if (userSeq) {
        try {
            const resp = await fetch('/api/messages/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    session_id: sessionId, 
                    user_seq: parseInt(userSeq),
                    delete_user: true,
                    cascade: true
                })
            });
            const data = await resp.json();
            if (data.status === 'success') console.log(`Deleted ${data.deleted} old messages`);
        } catch (err) {
            console.error('Failed to delete old messages:', err);
        }
    }

    // Remove this message bubble and every later bubble that belongs to
    // this or a subsequent turn. We mirror the backend cascade contract:
    // anything with a data-seq >= current seq, plus any live SSE bubble
    // that is still being streamed (no seq yet) after this point.
    const currentSeqNum = userSeq ? parseInt(userSeq) : null;
    const messagesToRemove = [];
    let current = msgEl;
    while (current) {
        if (current.classList && (current.classList.contains('user-message-group') || current.classList.contains('bot-message-group'))) {
            const seqAttr = current.dataset.seq;
            if (seqAttr === undefined || seqAttr === '') {
                // Live message without a persisted seq yet — treat as later.
                messagesToRemove.push(current);
            } else if (currentSeqNum === null || parseInt(seqAttr) >= currentSeqNum) {
                messagesToRemove.push(current);
            }
        }
        current = current.nextElementSibling;
    }
    messagesToRemove.forEach(el => {
        if (el && el.parentNode) el.parentNode.removeChild(el);
    });

    // Fill input with the original content
    chatInput.value = rawContent;
    chatInput.dispatchEvent(new Event("input", { bubbles: true }));
    chatInput.focus();
    chatInput.selectionStart = chatInput.selectionEnd = chatInput.value.length;
    scrollChatToBottom();
}

// Regenerate bot response: find the preceding user message and resend it
async function regenerateResponse(botMsgEl) {
    let prevEl = botMsgEl.previousElementSibling;
    while (prevEl && !prevEl.classList.contains('user-message-group')) {
        prevEl = prevEl.previousElementSibling;
    }

    if (!prevEl) {
        console.warn('No preceding user message found');
        return;
    }

    const userContent = prevEl.dataset.rawContent;
    if (!userContent) {
        console.warn('No content in preceding user message');
        return;
    }

    // Delete both the old user message AND bot reply from database
    // (because /message will create a fresh user message + new bot reply)
    // Must await to ensure delete completes before /message is sent
    const userSeq = prevEl.dataset.seq;
    if (userSeq) {
        try {
            const resp = await fetch('/api/messages/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    session_id: sessionId, 
                    user_seq: parseInt(userSeq),
                    delete_user: true
                })
            });
            const data = await resp.json();
            if (data.status === 'success') console.log(`Deleted ${data.deleted} old messages`);
        } catch (err) {
            console.error('Failed to delete old messages:', err);
        }
    }

    // Remove both the old user message and bot message from DOM
    if (prevEl.parentNode) prevEl.parentNode.removeChild(prevEl);
    if (botMsgEl.parentNode) botMsgEl.parentNode.removeChild(botMsgEl);

    // Re-add the user message to DOM (so it appears before the loading indicator)
    addUserMessage(userContent, new Date());

    // Show loading indicator
    const loadingEl = addLoadingIndicator();

    // Resend the message
    const timestamp = new Date();
    const body = { session_id: sessionId, message: userContent, stream: true, timestamp: timestamp.toISOString(), lang: currentLang };
    const regenAddressed = addressedAgentId(userContent);
    if (regenAddressed) body.speaker_agent_id = regenAddressed;

    const MAX_RETRIES = 2;
    const RETRY_DELAY_MS = 1000;

    function postWithRetry(attempt) {
        fetch('/message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success') {
                rememberLiveSpeaker(data);
                setLoadingSpeaker(loadingEl, data.request_id);
                if (data.inline_reply) {
                    loadingEl.remove();
                    addBotMessage(data.inline_reply, new Date());
                } else if (data.stream) {
                    setSendBtnCancelMode(data.request_id);
                    startSSE(data.request_id, loadingEl, timestamp, null);
                } else {
                    loadingContainers[data.request_id] = loadingEl;
                }
            } else {
                loadingEl.remove();
                addBotMessage(t('error_send'), new Date());
                resetSendBtnSendMode();
            }
        })
        .catch(err => {
            if (err.name === 'AbortError') {
                loadingEl.remove();
                addBotMessage(t('error_timeout'), new Date());
                resetSendBtnSendMode();
                return;
            }
            if (attempt < MAX_RETRIES) {
                console.warn(`[regenerateResponse] attempt ${attempt + 1} failed, retrying...`, err);
                setTimeout(() => postWithRetry(attempt + 1), RETRY_DELAY_MS * (attempt + 1));
                return;
            }
            loadingEl.remove();
            addBotMessage(t('error_send'), new Date());
            resetSendBtnSendMode();
        });
    }

    postWithRetry(0);
}

function sendMessage() {
    // Do NOT branch on sendBtnMode here: Enter should always send (so
    // typing "/cancel" submits normally). Cancel is wired only to the
    // send button's pointer click — see send-btn listener above.

    const text = chatInput.value.trim();
    if (!text && pendingAttachments.length === 0) return;

    if (text) {
        inputHistory.push(text);
        historyIdx = -1;
        historySavedDraft = '';
    }

    const ws = document.getElementById('welcome-screen');
    const isFirstMessage = !!ws;
    if (ws) ws.remove();

    const titleInfo = (isFirstMessage && text) ? { sid: sessionId, userMsg: text } : null;
    syncTeamFromText(text);
    renderComposerIdentity();

    const timestamp = new Date();
    const attachments = [...pendingAttachments];
    addUserMessage(text, timestamp, attachments);

    const loadingEl = addLoadingIndicator();

    chatInput.value = '';
    resetComposerHeight();
    pendingAttachments = [];
    renderAttachmentPreview();
    sendBtn.disabled = true;
    if (typeof resetTurnArtifacts === 'function') resetTurnArtifacts();

    const body = { session_id: sessionId, message: text, stream: true, timestamp: timestamp.toISOString(), lang: currentLang };
    // Naming somebody hands them the turn. Sent explicitly because the composer
    // already knows who it wrote, and the server re-checks it either way.
    const addressed = addressedAgentId(text);
    if (addressed) body.speaker_agent_id = addressed;
    if (attachments.length > 0) {
        body.attachments = attachments.map(a => ({
            file_path: a.file_path,
            file_name: a.file_name,
            file_type: a.file_type,
            file_count: a.file_count,
        }));
    }

    const MAX_RETRIES = 2;
    const RETRY_DELAY_MS = 1000;

    function postWithRetry(attempt) {
        fetch('/message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success') {
                rememberLiveSpeaker(data);
                setLoadingSpeaker(loadingEl, data.request_id);
                if (data.inline_reply) {
                    // Channel handled synchronously (e.g. /cancel fast-path);
                    // render as a bot bubble and skip SSE entirely.
                    loadingEl.remove();
                    addBotMessage(data.inline_reply, new Date());
                } else if (data.stream) {
                    setSendBtnCancelMode(data.request_id);
                    startSSE(data.request_id, loadingEl, timestamp, titleInfo);
                } else {
                    loadingContainers[data.request_id] = loadingEl;
                }
            } else {
                loadingEl.remove();
                addBotMessage(t('error_send'), new Date());
                resetSendBtnSendMode();
            }
        })
        .catch(err => {
            if (err.name === 'AbortError') {
                loadingEl.remove();
                addBotMessage(t('error_timeout'), new Date());
                resetSendBtnSendMode();
                return;
            }
            if (attempt < MAX_RETRIES) {
                console.warn(`[sendMessage] attempt ${attempt + 1} failed, retrying...`, err);
                setTimeout(() => postWithRetry(attempt + 1), RETRY_DELAY_MS * (attempt + 1));
                return;
            }
            loadingEl.remove();
            addBotMessage(t('error_send'), new Date());
            resetSendBtnSendMode();
        });
    }

    postWithRetry(0);
}

function startSSE(requestId, loadingEl, timestamp, titleInfo, replayItems) {
    let botEl = null;
    let stepsEl = null;    // .agent-steps  (thinking summaries + tool indicators)
    let contentEl = null;  // .answer-content (final streaming answer)
    let mediaEl = null;    // .media-content (images & file attachments)
    let accumulatedText = '';
    const toolElements = new Map();
    let currentReasoningEl = null;  // live reasoning bubble
    let reasoningText = '';
    let reasoningStartTime = 0;
    let done = false;
    let mainDone = false;
    let completedBotSeq = null;
    let cancelled = false;
    let lastSeq = 0;

    // A stream can end while tools are still marked in-flight (cancel, dropped
    // connection). Settle them so nothing spins forever.
    function settlePendingTools() {
        toolElements.forEach(el => {
            el.classList.remove('tool-streaming');
            const icon = el.querySelector('.tool-icon');
            if (icon) icon.className = 'fas fa-minus text-slate-400 flex-shrink-0 tool-icon';
        });
        toolElements.clear();
    }

    // The session this stream belongs to. Sessions run in parallel: the user
    // may switch to another session while this one is still streaming. The
    // stream keeps running in the background (so the reply still completes and
    // persists); when foreign it does not touch the view but still records
    // every event into a buffer, so returning to the session can rebuild the
    // bubble by replaying the buffer and then resume live rendering.
    const ownerSession = sessionId;
    const ownerAgent = activeAgentId;
    const ownerKey = runtimeSessionKey(ownerSession, ownerAgent);
    const isActive = () => ownerSession === sessionId && ownerAgent === activeAgentId;
    sessionActiveRequest[ownerKey] = requestId;
    updateEditButtonsState();
    // Per-request event buffer used to rebuild the bubble on re-attach.
    const buffer = streamBuffers[requestId] || { items: [], timestamp };
    streamBuffers[requestId] = buffer;
    const clearOwnerRequest = () => {
        if (sessionActiveRequest[ownerKey] === requestId) {
            delete sessionActiveRequest[ownerKey];
            updateEditButtonsState();
        }
        delete streamBuffers[requestId];
    };

    const MAX_RECONNECTS = 10;
    const RECONNECT_BASE_MS = 1000;
    let reconnectCount = 0;

    function ensureBotEl() {
        if (botEl) return;
        if (loadingEl) { loadingEl.remove(); loadingEl = null; }
        botEl = document.createElement('div');
        botEl.className = 'flex gap-3 px-4 sm:px-6 py-3 bot-message-group';
        botEl.dataset.requestId = requestId;
        // Regenerate button starts hidden; it's revealed in the "done"
        // event handler once seq metadata arrives from the backend.
        // The streaming face is whoever is answering this request: the addressed
        // teammate if one was named, else the conversation's own Agent. Wrapped
        // in .bot-face so a later avatar change repaints it like any bubble.
        const speaker = liveSpeakerAgent(requestId);
        if (speaker && speaker.id) botEl.dataset.speakerAgent = speaker.id;
        // In a group the bubble is labelled with its author while it streams,
        // exactly as the replayed history shows it — a solo chat stays unlabelled.
        const speakerName = (sharedConversation() && speaker)
            ? `<div class="bot-speaker">${escapeHtml(speaker.name || speaker.id)}</div>`
            : '';
        botEl.innerHTML = `
            <span class="bot-face">${agentAvatarHTML(speaker, 32)}</span>
            <div class="min-w-0 flex-1 max-w-[85%]">
                ${speakerName}
                <div class="bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-2xl px-4 py-3 text-sm leading-relaxed msg-content text-slate-700 dark:text-slate-200">
                    <div class="agent-steps"></div>
                    <div class="answer-content sse-streaming"></div>
                    <div class="media-content"></div>
                    <div class="bot-audio-slot"></div>
                </div>
                <div class="flex items-center gap-2 mt-1.5">
                    <span class="text-xs text-slate-400 dark:text-slate-500">${formatTime(timestamp)}</span>
                    <button class="copy-msg-btn text-xs text-slate-300 dark:text-slate-600 hover:text-slate-500 dark:hover:text-slate-400 transition-colors cursor-pointer" title="${currentLang === 'zh' ? '复制' : 'Copy'}" style="display:none">
                        <i class="fas fa-copy"></i>
                    </button>
                    <button class="speak-msg-btn text-xs text-slate-300 dark:text-slate-600 hover:text-slate-500 dark:hover:text-slate-400 transition-colors cursor-pointer" title="${t('speak_msg')}" style="display:none;">
                        <i class="fas fa-volume-up"></i>
                    </button>
                    <button class="regenerate-msg-btn text-xs text-slate-300 dark:text-slate-600 hover:text-primary-400 dark:hover:text-primary-400 transition-colors cursor-pointer" title="${t('regenerate_response')}" style="display:none;">
                        <i class="fas fa-rotate-right"></i>
                    </button>
                </div>
            </div>
        `;
        messagesDiv.appendChild(botEl);
        stepsEl = botEl.querySelector('.agent-steps');
        contentEl = botEl.querySelector('.answer-content');
        mediaEl = botEl.querySelector('.media-content');
    }

    // Holds the live EventSource so terminal events (done/voice_attach/error)
    // can close it. During replay there is no live connection (null).
    let currentEs = null;

    // Render one SSE event into the bubble. Used by the live handler and by
    // re-attach replay alike, so both paths produce identical UI.
    function processSSEItem(item) {
            if (item.type === 'reasoning') {
                ensureBotEl();
                reasoningText += item.content;
                if (!currentReasoningEl) {
                    reasoningStartTime = Date.now();
                    currentReasoningEl = document.createElement('div');
                    currentReasoningEl.className = 'agent-step agent-thinking-step';
                    // During streaming, use a <pre> with a single text node and
                    // append-only updates. This avoids re-parsing markdown and
                    // re-setting innerHTML on every chunk, which is what causes
                    // the page to crash on long chains-of-thought.
                    currentReasoningEl.innerHTML = `
                        <div class="thinking-header" onclick="this.parentElement.classList.toggle('expanded')">
                            <i class="fas fa-lightbulb text-amber-400 flex-shrink-0"></i>
                            <span class="thinking-summary">${t('thinking_in_progress')}</span>
                            <i class="fas fa-chevron-right thinking-chevron"></i>
                        </div>
                        <div class="thinking-full"><pre class="thinking-stream-pre"></pre></div>`;
                    stepsEl.appendChild(currentReasoningEl);
                    const preEl = currentReasoningEl.querySelector('.thinking-stream-pre');
                    preEl.appendChild(document.createTextNode(''));
                    currentReasoningEl._streamTextNode = preEl.firstChild;
                    currentReasoningEl._streamPendingText = '';
                    currentReasoningEl._streamRafScheduled = false;
                    currentReasoningEl._streamCharsRendered = 0;
                    currentReasoningEl._streamCapped = false;
                }
                // Hard cap: once REASONING_RENDER_CAP chars are in the DOM, stop
                // appending further deltas. The full text is still kept in
                // `reasoningText` for finalize-time head+tail rendering.
                if (!currentReasoningEl._streamCapped) {
                    currentReasoningEl._streamPendingText += item.content;
                    if (!currentReasoningEl._streamRafScheduled) {
                        currentReasoningEl._streamRafScheduled = true;
                        const elRef = currentReasoningEl;
                        requestAnimationFrame(() => {
                            elRef._streamRafScheduled = false;
                            if (!elRef.isConnected || !elRef._streamTextNode) return;
                            let pending = elRef._streamPendingText;
                            elRef._streamPendingText = '';
                            if (!pending) return;
                            const remaining = REASONING_RENDER_CAP - elRef._streamCharsRendered;
                            if (remaining <= 0) {
                                elRef._streamCapped = true;
                            } else {
                                if (pending.length > remaining) {
                                    pending = pending.slice(0, remaining);
                                    elRef._streamCapped = true;
                                }
                                elRef._streamTextNode.appendData(pending);
                                elRef._streamCharsRendered += pending.length;
                                if (elRef._streamCapped) {
                                    elRef._streamTextNode.appendData(
                                        '\n\n... [reasoning truncated for display] ...'
                                    );
                                }
                            }
                            scrollChatToBottom();
                        });
                    }
                }

            } else if (item.type === 'delta') {
                ensureBotEl();
                if (currentReasoningEl) {
                    finalizeThinking(currentReasoningEl, reasoningStartTime, reasoningText);
                    currentReasoningEl = null;
                    reasoningText = '';
                }
                accumulatedText += item.content;
                contentEl.innerHTML = renderMarkdown(accumulatedText);
                scrollChatToBottom();

            } else if (item.type === 'message_end') {
                if (item.has_tool_calls && accumulatedText.trim()) {
                    ensureBotEl();
                    const frozenEl = document.createElement('div');
                    frozenEl.className = 'agent-step agent-content-step';
                    frozenEl.innerHTML = `<div class="agent-content-body">${renderMarkdown(accumulatedText.trim())}</div>`;
                    stepsEl.appendChild(frozenEl);
                    accumulatedText = '';
                    contentEl.innerHTML = '';
                    scrollChatToBottom();
                }

            } else if (item.type === 'tool_start') {
                ensureBotEl();
                if (currentReasoningEl) {
                    finalizeThinking(currentReasoningEl, reasoningStartTime, reasoningText);
                    currentReasoningEl = null;
                    reasoningText = '';
                }
                accumulatedText = '';
                contentEl.innerHTML = '';

                // Add tool execution indicator (collapsible)
                const toolEl = document.createElement('div');
                toolEl.className = 'agent-step agent-tool-step tool-streaming';
                toolEl.dataset.progressReceived = 'false';
                const argsStr = formatToolArgs(item.arguments || {});
                toolEl.innerHTML = `
                    <div class="tool-header" onclick="this.parentElement.classList.toggle('expanded')">
                        <i class="fas fa-cog fa-spin text-primary-400 flex-shrink-0 tool-icon"></i>
                        <span class="tool-name">${item.tool}</span>
                        <span class="tool-substep-count"></span>
                        <i class="fas fa-chevron-right tool-chevron"></i>
                    </div>
                    <div class="tool-detail">
                        <div class="tool-detail-section">
                            <div class="tool-detail-label">Input</div>
                            <pre class="tool-detail-content">${argsStr}</pre>
                        </div>
                        <div class="tool-detail-section tool-substeps-section hidden">
                            <div class="tool-detail-label">Steps</div>
                            <div class="tool-substeps"></div>
                        </div>
                        <div class="tool-detail-section tool-output-section">
                            <div class="tool-detail-label tool-output-label">Output</div>
                            <pre class="tool-detail-content tool-live-output"></pre>
                            <div class="tool-display-output"></div>
                        </div>
                    </div>`;
                stepsEl.appendChild(toolEl);
                toolElements.set(item.tool_call_id, toolEl);

                scrollChatToBottom();

            } else if (item.type === 'tool_progress') {
                const toolEl = toolElements.get(item.tool_call_id);
                if (toolEl) {
                    if (toolEl.dataset.progressReceived !== 'true') {
                        toolEl.classList.add('expanded');
                        toolEl.dataset.progressReceived = 'true';
                    }
                    toolEl.querySelector('.tool-live-output').textContent = String(item.content || '');
                    scrollChatToBottom();
                }

            } else if (item.type === 'tool_end') {
                const toolEl = toolElements.get(item.tool_call_id);
                if (toolEl) {
                    const isError = item.status !== 'success';
                    const icon = toolEl.querySelector('.tool-icon');
                    icon.className = isError
                        ? 'fas fa-times text-red-400 flex-shrink-0 tool-icon'
                        : 'fas fa-check text-primary-400 flex-shrink-0 tool-icon';

                    // Show execution time
                    const nameEl = toolEl.querySelector('.tool-name');
                    if (item.execution_time !== undefined) {
                        nameEl.innerHTML += ` <span class="tool-time">${item.execution_time}s</span>`;
                    }

                    // Fill output section. A tool that wrote its outcome for a
                    // person (item.display) gets rendered as markdown; the raw
                    // result is what the model reads and stays hidden then.
                    const outputLabel = toolEl.querySelector('.tool-output-label');
                    const outputEl = toolEl.querySelector('.tool-live-output');
                    const displayEl = toolEl.querySelector('.tool-display-output');
                    if (outputLabel) outputLabel.textContent = isError ? 'Error' : 'Output';
                    if (displayEl && item.display) {
                        displayEl.innerHTML = renderMarkdown(String(item.display));
                        displayEl.classList.add('has-content');
                        if (outputEl) outputEl.textContent = '';
                    } else if (outputEl) {
                        outputEl.textContent = item.result ? String(item.result) : '';
                        outputEl.classList.toggle('tool-error-text', isError);
                    }

                    toolEl.classList.remove('tool-streaming');
                    // Tools collapse once they are done; their output is a
                    // trace. A tool that wrote something for a person to read
                    // stays open — the reader just waited for it.
                    toolEl.classList.toggle('expanded', !!item.display);
                    if (!item.result && !item.display) {
                        const outputSection = toolEl.querySelector('.tool-output-section');
                        if (outputSection) outputSection.remove();
                    }
                    if (isError) toolEl.classList.add('tool-failed');
                    // A permission refusal is not an ordinary failure: surface a
                    // one-click way to raise this session's permission instead of
                    // leaving the user to decode the model's error text.
                    if (item.permission_denied) {
                        _appendPermissionDeniedHint(toolEl, item.permission_mode);
                    }
                    toolElements.delete(item.tool_call_id);
                }

            } else if (item.type === 'subagent_step') {
                // A tool call made inside a sub agent, rendered under that sub
                // agent's card so its minutes of work are followable.
                renderSubagentStep(toolElements.get(item.card_id), item);
                scrollChatToBottom();

            } else if (item.type === 'image') {
                ensureBotEl();
                const imgEl = document.createElement('img');
                imgEl.src = item.content;
                imgEl.alt = 'screenshot';
                imgEl.style.cssText = 'max-width:600px;border-radius:8px;margin:8px 0;cursor:zoom-in;box-shadow:0 1px 4px rgba(0,0,0,0.1);';
                imgEl.onclick = () => _openImageLightbox(imgEl.src);
                mediaEl.appendChild(imgEl);
                scrollChatToBottom();

            } else if (item.type === 'text') {
                // Intermediate text sent before media items; display it but keep SSE open.
                ensureBotEl();
                contentEl.classList.remove('sse-streaming');
                const textContent = item.content || accumulatedText;
                if (textContent) contentEl.innerHTML = renderMarkdown(textContent);
                applyHighlighting(botEl);
                scrollChatToBottom();

            } else if (item.type === 'video') {
                ensureBotEl();
                const wrapper = document.createElement('div');
                wrapper.innerHTML = _buildVideoHtml(item.content);
                mediaEl.appendChild(wrapper.firstElementChild || wrapper);
                scrollChatToBottom();

            } else if (item.type === 'file') {
                ensureBotEl();
                const fileName = item.file_name || item.content.split('/').pop();
                const fileEl = document.createElement('a');
                fileEl.href = item.content;
                fileEl.download = fileName;
                fileEl.target = '_blank';
                fileEl.className = 'file-attachment';
                fileEl.style.cssText = 'display:inline-flex;align-items:center;gap:6px;padding:8px 14px;margin:8px 0;border-radius:8px;background:var(--bg-secondary,#f3f4f6);color:var(--text-primary,#374151);text-decoration:none;font-size:14px;border:1px solid var(--border-color,#e5e7eb);';
                fileEl.innerHTML = `<i class="fas fa-file-download" style="color:#6b7280;"></i> ${fileName}`;
                mediaEl.appendChild(fileEl);
                scrollChatToBottom();

            } else if (item.type === 'artifact') {
                // A user-facing file the agent wrote; render a card and let the
                // workspace panel decide whether to auto-open it (workspace.js).
                ensureBotEl();
                if (typeof appendArtifactCard === 'function') {
                    appendArtifactCard(mediaEl, item);
                }
                scrollChatToBottom();

            } else if (item.type === 'phase') {
                // Coarse progress (e.g. cow install-browser); must not close SSE (unlike "done")
                ensureBotEl();
                const wrap = document.createElement('div');
                wrap.className = 'text-xs sm:text-sm text-slate-600 dark:text-slate-400 border-l-2 border-primary-400 pl-2 py-1 my-0.5';
                wrap.textContent = String(item.content || '');
                stepsEl.appendChild(wrap);
                scrollChatToBottom();

            } else if (item.type === 'cancelled') {
                // Agent acknowledged the stop; mark the bubble. A trailing
                // "done" still arrives with the partial answer.
                cancelled = true;
                ensureBotEl();
                if (currentReasoningEl) {
                    finalizeThinking(currentReasoningEl, reasoningStartTime, reasoningText);
                    currentReasoningEl = null;
                    reasoningText = '';
                }
                if (!botEl.querySelector('.agent-cancelled-tag')) {
                    const tag = document.createElement('div');
                    tag.className = 'agent-cancelled-tag text-xs text-amber-600 dark:text-amber-400 mt-1';
                    tag.textContent = (currentLang === 'zh') ? '已中止' : 'Cancelled';
                    stepsEl.appendChild(tag);
                }
                resetSendBtnSendMode();

            } else if (item.type === 'done') {
                // The answer is persisted, but async attachments may still
                // follow. Only stream_end closes the request lifecycle.
                mainDone = true;
                if (item.bot_seq !== undefined && item.bot_seq !== null) {
                    completedBotSeq = item.bot_seq;
                }
                settlePendingTools();
                resetSendBtnSendMode();

                const finalTextRaw = item.content || accumulatedText;
                const finalText = localizeCancelMarker(finalTextRaw);

                if (!botEl && finalText) {
                    if (loadingEl) { loadingEl.remove(); loadingEl = null; }
                    addBotMessage(finalText, new Date((item.timestamp || Date.now() / 1000) * 1000), requestId);
                } else if (botEl) {
                    contentEl.classList.remove('sse-streaming');
                    if (finalText) contentEl.innerHTML = renderMarkdown(finalText);
                    contentEl.dataset.rawMd = finalTextRaw || '';
                    const copyBtn = botEl.querySelector('.copy-msg-btn');
                    if (copyBtn && finalText) copyBtn.style.display = '';
                    applyHighlighting(botEl);
                }

                // Backfill seq metadata so edit/regenerate buttons can call
                // the delete API without a page refresh. Backend includes
                // user_seq / bot_seq on the done event after persistence.
                const targetBotEl = botEl || (requestId ? messagesDiv.querySelector(`[data-request-id="${requestId}"]`) : null);
                if (targetBotEl) {
                    if (item.bot_seq !== undefined && item.bot_seq !== null) {
                        targetBotEl.dataset.seq = item.bot_seq;
                    }
                    // Reveal regenerate button now that the seq is wired up.
                    const regenBtn = targetBotEl.querySelector('.regenerate-msg-btn');
                    if (regenBtn) regenBtn.style.display = '';
                    if (item.user_seq !== undefined && item.user_seq !== null) {
                        // Locate the preceding user bubble for this turn.
                        let prev = targetBotEl.previousElementSibling;
                        while (prev && !prev.classList.contains('user-message-group')) {
                            prev = prev.previousElementSibling;
                        }
                        if (prev && !prev.dataset.seq) {
                            prev.dataset.seq = item.user_seq;
                        }
                    }
                }
                renderBotSpeakerButton(botEl, finalText);
                scrollChatToBottom();

                if (typeof maybeAutoOpenArtifact === 'function') maybeAutoOpenArtifact();

                if (titleInfo) {
                    generateSessionTitle(titleInfo.sid, titleInfo.userMsg, '');
                    titleInfo = null;
                } else if (sessionPanelOpen) {
                    loadSessionList();
                }

            } else if (item.type === 'voice_attach') {
                // TTS finished — attach a playable audio element to the
                // persisted bot bubble. If history is still loading after a
                // session switch, keep the attachment until that bubble exists.
                if (item.url && completedBotSeq !== null) {
                    rememberPendingVoiceAttachment(
                        ownerSession, completedBotSeq, item.url
                    );
                    flushPendingVoiceAttachments(ownerSession, true);
                }

            } else if (item.type === 'stream_end') {
                done = true;
                if (currentEs) { currentEs.close(); }
                delete activeStreams[requestId];
                clearOwnerRequest();

            } else if (item.type === 'resync_required') {
                done = true;
                settlePendingTools();
                if (currentEs) { currentEs.close(); }
                delete activeStreams[requestId];
                clearOwnerRequest();
                resetSendBtnSendMode();
                if (isActive()) {
                    messagesDiv.innerHTML = '';
                    historyPage = 0;
                    historyHasMore = false;
                    historyLoading = false;
                    loadHistory(1);
                }

            } else if (item.type === 'error') {
                done = true;
                settlePendingTools();
                if (currentEs) { currentEs.close(); }
                delete activeStreams[requestId];
                clearOwnerRequest();
                if (loadingEl) { loadingEl.remove(); loadingEl = null; }
                // After a stop the stream is expected to end; the bubble is
                // already tagged "已中止", so don't stack a failure on top.
                if (!cancelled) addBotMessage(t('error_send'), new Date());
                resetSendBtnSendMode();
            }
    }

    function connect() {
        const es = new EventSource(
            `/stream?request_id=${encodeURIComponent(requestId)}`
            + `&after_seq=${lastSeq}`
        );
        currentEs = es;
        activeStreams[requestId] = es;

        es.onmessage = function(e) {
            let item;
            try { item = JSON.parse(e.data); } catch (_) { return; }

            const seq = Number(item.seq || 0);
            if (seq && seq <= lastSeq) return;

            // Successful data received, reset reconnect counter
            reconnectCount = 0;

            // Record every event for re-attach replay (capped to avoid
            // unbounded growth on very long streams).
            if (item.type === 'tool_progress' && item.tool_call_id) {
                const previousIndex = buffer.items.findIndex(
                    buffered => buffered.type === 'tool_progress'
                        && buffered.tool_call_id === item.tool_call_id
                );
                if (previousIndex >= 0) buffer.items.splice(previousIndex, 1);
            }
            if (buffer.items.length < 5000) buffer.items.push(item);
            if (seq) lastSeq = seq;

            // done is persisted before it is published. Remember that state
            // even while this session is in the background, where rendering
            // is intentionally skipped. Notify for both foreground and
            // background sessions, before the render guard below.
            if (item.type === 'done') {
                mainDone = true;
                if (item.bot_seq !== undefined && item.bot_seq !== null) {
                    completedBotSeq = item.bot_seq;
                }
                // Scheduler deliveries are notified solely by the global runs
                // poller (maybeNotifyScheduledRun), which forces a notice across
                // all sessions and dedupes by run id. Notifying here too would
                // double-pop, so skip scheduler streams.
                if (!isSchedulerRequest(requestId)) {
                    notifyTaskFinished(ownerSession, 'done', item.content, ownerAgent);
                }
            } else if (item.type === 'error') {
                if (!cancelled && !isSchedulerRequest(requestId)) notifyTaskFinished(ownerSession, 'error', '', ownerAgent);
            } else if (
                item.type === 'voice_attach'
                && item.url
                && completedBotSeq !== null
            ) {
                // Background sessions skip rendering below. Preserve their
                // attachment so loadHistory can mount it when the user returns.
                rememberPendingVoiceAttachment(
                    ownerSession, completedBotSeq, item.url
                );
            }

            // Background session: keep the stream alive so the reply finishes
            // and persists, but skip rendering into the now-foreign view. The
            // buffer above still grows so returning to the session can rebuild
            // the bubble and resume live rendering.
            if (ownerSession !== sessionId) {
                if (item.type === 'stream_end' || item.type === 'error' || item.type === 'resync_required') {
                    done = true;
                    es.close();
                    delete activeStreams[requestId];
                    clearOwnerRequest();
                }
                return;
            }

            processSSEItem(item);
        };

        es.onerror = function() {
            es.close();
            delete activeStreams[requestId];

            if (done) {
                // stream_end or an unrecoverable event already closed it.
                return;
            }

            if (cancelled && !mainDone) {
                // The user stopped the run, so the stream ending here is the
                // expected outcome. Reconnecting would only land on a queue
                // the backend has already reclaimed.
                settlePendingTools();
                clearOwnerRequest();
                if (loadingEl) { loadingEl.remove(); loadingEl = null; }
                if (contentEl) contentEl.classList.remove('sse-streaming');
                resetSendBtnSendMode();
                return;
            }

            if (currentReasoningEl) {
                finalizeThinking(currentReasoningEl, reasoningStartTime, reasoningText);
                currentReasoningEl = null;
                reasoningText = '';
            }

            if (reconnectCount < MAX_RECONNECTS) {
                reconnectCount++;
                const delay = Math.min(RECONNECT_BASE_MS * reconnectCount, 5000);
                console.warn(`[SSE] connection lost for ${requestId}, reconnecting in ${delay}ms (attempt ${reconnectCount}/${MAX_RECONNECTS})`);
                setTimeout(connect, delay);
                return;
            }

            // Exhausted retries. Only surface the failure in the owning view —
            // a background session must not mutate the currently shown chat.
            clearOwnerRequest();
            settlePendingTools();
            if (!isActive()) return;
            if (loadingEl) { loadingEl.remove(); loadingEl = null; }
            if (!botEl) {
                addBotMessage(t('error_send'), new Date());
            } else if (accumulatedText) {
                contentEl.classList.remove('sse-streaming');
                contentEl.innerHTML = renderMarkdown(accumulatedText);
                applyHighlighting(botEl);
            }
            resetSendBtnSendMode();
        };
    }

    // Re-attach replay: rebuild the bubble from buffered events (snapshot,
    // not animated) before connecting for the live tail. `processSSEItem`
    // is the same renderer used by the live onmessage handler, so the
    // snapshot matches exactly what live rendering would have produced.
    if (replayItems && replayItems.length) {
        for (const item of replayItems) {
            const seq = Number(item.seq || 0);
            if (seq > lastSeq) lastSeq = seq;
            try { processSSEItem(item); } catch (_) {}
            if (item.type === 'stream_end' || item.type === 'error' || item.type === 'resync_required') {
                done = true;
            }
        }
        // If the buffered stream already finished, don't reconnect — the
        // reply is complete and persisted; show its final state and stop.
        if (done) {
            clearOwnerRequest();
            resetSendBtnSendMode();
            scrollChatToBottom(true);
            return;
        }
    }

    connect();
}

function startPolling() {
    const gen = ++pollGeneration;
    isPolling = true;
    let pollInFlight = false;

    function poll() {
        if (gen !== pollGeneration) return;
        if (pollInFlight) return;
        // Keep polling while hidden: push messages are exactly what the
        // notification below should deliver to a background tab.
        pollInFlight = true;
        fetch('/poll', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sessionId })
        })
        .then(r => r.json())
        .then(data => {
            pollInFlight = false;
            if (gen !== pollGeneration) return;
            if (data.status === 'success' && data.has_content) {
                const rid = data.request_id;
                if (loadingContainers[rid]) {
                    loadingContainers[rid].remove();
                    delete loadingContainers[rid];
                }
                // Skip if this reply is already on screen. Happens when a reply
                // arrives via both the SSE stream and the poll queue (e.g. the
                // user switched away mid-run, leaving the queued reply to be
                // re-fetched on return) — render it only once.
                const already = rid && messagesDiv.querySelector(
                    `[data-request-id="${rid}"]`
                );
                if (!already) {
                    const welcomeScreen = document.getElementById('welcome-screen');
                    if (welcomeScreen) welcomeScreen.remove();
                    addBotMessage(data.content, new Date(data.timestamp * 1000), rid);
                    scrollChatToBottom();
                    // Scheduler executions are notified by the global runs poll
                    // (maybeNotifyScheduledRun) — it forces a notice across ALL
                    // sessions, including this one and manual "run now", and
                    // dedupes by run id. Notifying here too would double-pop, so
                    // only notify for an ordinary missed reply.
                    if (!isSchedulerRequest(rid)) {
                    showTaskNotification(
                        sessionTitleOf(sessionId) || 'CowAgent',
                        firstLineSnippet(data.content),
                            sessionId,
                            activeAgentId
                    );
                    }
                }
            }
            const delay = (data.status === 'success' && data.has_content) ? 5000 : 10000;
            setTimeout(poll, delay);
        })
        .catch(() => { pollInFlight = false; setTimeout(poll, 10000); });
    }
    poll();
}

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

// Attachment markers the backend appends to the prompt, keyed by the label it
// emitted (see the workspace_ref branch in web_channel.post_message). History
// only persists the prompt text, so this is the only way back to a chip.
const ATTACHMENT_MARKER_TYPES = {
    '工作空间文件': 'workspace_ref', '工作空间檔案': 'workspace_ref', 'Workspace file': 'workspace_ref',
    '工作空间目录': 'workspace_dir', '工作空间目錄': 'workspace_dir', 'Workspace directory': 'workspace_dir',
    '图片': 'image', '圖片': 'image', 'Image': 'image',
    '视频': 'video', '影片': 'video', 'Video': 'video',
    '目录': 'directory', '目錄': 'directory', 'Directory': 'directory',
    '文件': 'file', '檔案': 'file', 'File': 'file',
};

/**
 * Split trailing `[label: path]` lines off a persisted user message.
 * Returns the remaining text plus the attachments they describe.
 */
function parseAttachmentMarkers(content) {
    const lines = (content || '').split('\n');
    const found = [];
    while (lines.length) {
        const line = lines[lines.length - 1].trim();
        if (!line) { lines.pop(); continue; }
        const m = line.match(/^\[([^\]:]+):\s*(.+)\]$/);
        const type = m && ATTACHMENT_MARKER_TYPES[m[1].trim()];
        if (!type) break;
        found.unshift({ type, path: m[2].trim() });
        lines.pop();
    }
    if (!found.length) return { text: content, attachments: null };
    return {
        text: lines.join('\n').trimEnd(),
        attachments: found.map(f => ({
            file_path: f.path,
            file_name: f.path.split(/[\\/]/).filter(Boolean).pop() || f.path,
            file_type: f.type === 'workspace_dir' ? 'workspace_ref' : f.type,
            is_dir: f.type === 'workspace_dir' || f.type === 'directory',
        })),
    };
}

function createUserMessageEl(content, timestamp, attachments) {
    const el = document.createElement('div');
    el.className = 'flex justify-end px-4 sm:px-6 py-3 user-message-group';

    // Replaying history: recover the chips from the markers left in the text.
    if (!attachments) {
        const parsed = parseAttachmentMarkers(content);
        if (parsed.attachments) {
            attachments = parsed.attachments;
            content = parsed.text;
        }
    }

    let attachHtml = '';
    if (attachments && attachments.length > 0) {
        const items = attachments.map(a => {
            if (a.file_type === 'image') {
                // History replay recovers attachments from prompt markers, which
                // carry only the local file_path — route it through /api/file.
                const src = (a.preview_url || _toWebUrl(a.file_path || '')).replace(/"/g, '&quot;');
                return `<img src="${src}" alt="${escapeHtml(a.file_name)}" class="user-msg-image" onclick="_openImageLightbox(this.src)">`;
            }
            const icon = a.file_type === 'video'
                ? 'fa-film'
                : (a.file_type === 'directory' ? 'fa-folder-tree'
                : (a.is_dir ? 'fa-folder' : 'fa-file-alt'));
            const suffix = a.file_type === 'directory' && a.file_count
                ? ` (${a.file_count})`
                : '';
            // Workspace references stay openable in the preview panel.
            const openable = a.file_type === 'workspace_ref'
                ? ` data-ws-open="${escapeHtml(a.file_path)}" title="${escapeHtml(a.file_path)}"`
                : '';
            return `<div class="user-msg-file${openable ? ' is-openable' : ''}"${openable}>` +
                `<i class="fas ${icon}"></i> ${escapeHtml(a.file_name)}${suffix}</div>`;
        }).join('');
        attachHtml = `<div class="user-msg-attachments">${items}</div>`;
    }

    const textHtml = content ? renderMarkdown(content) : '';
    el.innerHTML = `
        <div class="max-w-[75%] sm:max-w-[60%]">
            <div class="bg-primary-400 text-white rounded-2xl px-4 py-2.5 text-sm leading-relaxed msg-content user-bubble">
                ${attachHtml}${textHtml}
            </div>
            <div class="flex items-center justify-end gap-2 mt-1.5">
                <button class="edit-msg-btn text-xs text-slate-300 dark:text-slate-600 hover:text-primary-400 dark:hover:text-primary-400 transition-colors cursor-pointer" title="${t('edit_message')}">
                    <i class="fas fa-pen-to-square"></i>
                </button>
                <button class="delete-msg-btn text-xs text-slate-300 dark:text-slate-600 hover:text-red-500 dark:hover:text-red-400 transition-colors cursor-pointer" title="${t('delete_message_title')}">
                    <i class="fas fa-trash"></i>
                </button>
                <span class="text-xs text-slate-400 dark:text-slate-500">${formatTime(timestamp)}</span>
            </div>
        </div>
    `;
    // Store raw content for editing
    el.dataset.rawContent = content || '';
    highlightMentions(el.querySelector('.msg-content'));
    return el;
}

function renderToolCallsHtml(toolCalls) {
    if (!toolCalls || toolCalls.length === 0) return '';
    return toolCalls.map(tc => {
        const argsStr = formatToolArgs(tc.arguments || {});
        const resultStr = tc.result ? escapeHtml(String(tc.result)) : '';
        const hasResult = !!resultStr;
        return `
<div class="agent-step agent-tool-step">
    <div class="tool-header" onclick="this.parentElement.classList.toggle('expanded')">
        <i class="fas fa-check text-primary-400 flex-shrink-0 tool-icon"></i>
        <span class="tool-name">${escapeHtml(tc.name || '')}</span>
        <i class="fas fa-chevron-right tool-chevron"></i>
    </div>
    <div class="tool-detail">
        <div class="tool-detail-section">
            <div class="tool-detail-label">Input</div>
            <pre class="tool-detail-content">${argsStr}</pre>
        </div>
        ${hasResult ? `
        <div class="tool-detail-section tool-output-section">
            <div class="tool-detail-label">Output</div>
            <pre class="tool-detail-content">${resultStr}</pre>
        </div>` : ''}
    </div>
</div>`;
    }).join('');
}

// Cap for rendering reasoning content in the bubble. Beyond this size,
// we skip markdown rendering entirely and show plain text head + tail to
// keep the page responsive (very long chains-of-thought can otherwise
// stall or crash the browser when re-parsed by marked.js).
// Keep this in sync with backend MAX_STORED_REASONING_CHARS and
// MAX_REASONING_STREAM_CHARS so storage / SSE / display stay aligned.
const REASONING_RENDER_CAP = 4 * 1024; // 4 KB

function _truncateReasoningForDisplay(text) {
    if (!text || text.length <= REASONING_RENDER_CAP) return { text, truncated: false, omitted: 0 };
    const half = Math.floor(REASONING_RENDER_CAP / 2);
    const head = text.slice(0, half);
    const tail = text.slice(-half);
    return {
        text: head + '\n\n... [' + (text.length - head.length - tail.length) + ' chars omitted] ...\n\n' + tail,
        truncated: true,
        omitted: text.length - head.length - tail.length,
    };
}

function _renderReasoningBody(text) {
    // For short reasoning, render as markdown. For long ones, fall back to
    // an escaped <pre> block to avoid expensive markdown parsing.
    const { text: shown, truncated } = _truncateReasoningForDisplay(text);
    if (truncated || shown.length > REASONING_RENDER_CAP) {
        return '<pre class="thinking-stream-pre">' + escapeHtml(shown) + '</pre>';
    }
    return renderMarkdown(shown);
}

function finalizeThinking(el, startTime, text) {
    const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
    el.querySelector('.thinking-summary').textContent = t('thinking_done');
    const fullDiv = el.querySelector('.thinking-full');
    fullDiv.innerHTML = `<div class="thinking-duration">${t('thinking_duration')} ${elapsed}s</div>` + _renderReasoningBody(text);
}

function renderThinkingHtml(text) {
    if (!text || !text.trim()) return '';
    const full = text.trim();
    return `
<div class="agent-step agent-thinking-step">
    <div class="thinking-header" onclick="this.parentElement.classList.toggle('expanded')">
        <i class="fas fa-lightbulb text-amber-400 flex-shrink-0"></i>
        <span class="thinking-summary">${t('thinking_done')}</span>
        <i class="fas fa-chevron-right thinking-chevron"></i>
    </div>
    <div class="thinking-full">${_renderReasoningBody(full)}</div>
</div>`;
}

function renderStepsHtml(steps) {
    if (!steps || steps.length === 0) return { stepsHtml: '', finalContent: '' };

    // Find the index of the last content step — it becomes the main answer, not a step
    let lastContentIdx = -1;
    for (let i = steps.length - 1; i >= 0; i--) {
        if (steps[i].type === 'content') { lastContentIdx = i; break; }
    }

    let html = '';
    let lastContentText = '';
    for (let i = 0; i < steps.length; i++) {
        const step = steps[i];
        if (step.type === 'thinking') {
            html += renderThinkingHtml(step.content);
        } else if (step.type === 'content') {
            if (i === lastContentIdx) {
                lastContentText = step.content;
            } else {
                html += `<div class="agent-step agent-content-step"><div class="agent-content-body">${renderMarkdown(step.content)}</div></div>`;
            }
        } else if (step.type === 'tool') {
            const argsStr = formatToolArgs(step.arguments || {});
            const resultStr = step.result ? escapeHtml(String(step.result)) : '';
            const isErr = step.is_error === true;
            const iconClass = isErr
                ? 'fas fa-times text-red-400 flex-shrink-0 tool-icon'
                : 'fas fa-check text-primary-400 flex-shrink-0 tool-icon';
            // Same rule as the live stream: a tool that wrote its outcome for
            // a person shows that, not the form the model was handed.
            const outputHtml = step.display
                ? `<div class="tool-display-output has-content">${renderMarkdown(String(step.display))}</div>`
                : (resultStr
                    ? `<pre class="tool-detail-content${isErr ? ' tool-error-text' : ''}">${resultStr}</pre>`
                    : '');
            html += `
<div class="agent-step agent-tool-step${isErr ? ' tool-failed' : ''}">
    <div class="tool-header" onclick="this.parentElement.classList.toggle('expanded')">
        <i class="${iconClass}"></i>
        <span class="tool-name">${escapeHtml(step.name || '')}</span>
        <i class="fas fa-chevron-right tool-chevron"></i>
    </div>
    <div class="tool-detail">
        <div class="tool-detail-section">
            <div class="tool-detail-label">Input</div>
            <pre class="tool-detail-content">${argsStr}</pre>
        </div>
        ${outputHtml ? `
        <div class="tool-detail-section tool-output-section">
            <div class="tool-detail-label">${isErr ? 'Error' : 'Output'}</div>
            ${outputHtml}
        </div>` : ''}
    </div>
</div>`;
            // If this tool sent a file (send/read tool), render the media inline
            // so it persists across page refreshes (SSE-only file events are not stored).
            const mediaHtml = _renderSentFileFromToolResult(step);
            if (mediaHtml) html += mediaHtml;
        }
    }
    return { stepsHtml: html, lastContentText };
}

// Extract file-to-send metadata from a tool's result and render an inline preview.
// Returns '' if the result isn't a file_to_send payload.
function _renderSentFileFromToolResult(step) {
    if (!step || !step.result) return '';
    let payload;
    try {
        payload = typeof step.result === 'string' ? JSON.parse(step.result) : step.result;
    } catch (_) { return ''; }
    if (!payload || payload.type !== 'file_to_send' || !payload.path) return '';
    const webUrl = _toWebUrl(payload.path);
    const fileType = payload.file_type || 'file';
    const fileName = payload.file_name || payload.path.split('/').pop();
    if (fileType === 'image') {
        return `<div class="agent-step">${_buildImageHtml(webUrl)}</div>`;
    }
    if (fileType === 'video') {
        return `<div class="agent-step">${_buildVideoHtml(webUrl)}</div>`;
    }
    return `<div class="agent-step"><a href="${webUrl}" download="${escapeHtml(fileName)}" target="_blank" ` +
        `style="display:inline-flex;align-items:center;gap:6px;padding:8px 14px;margin:8px 0;border-radius:8px;` +
        `background:var(--bg-secondary,#f3f4f6);color:var(--text-primary,#374151);text-decoration:none;font-size:14px;` +
        `border:1px solid var(--border-color,#e5e7eb);">` +
        `<i class="fas fa-file-download" style="color:#6b7280;"></i> ${escapeHtml(fileName)}</a></div>`;
}

// Cosmetic translator for cancel markers persisted in history.
// History keeps the English canonical form for the LLM; only display is localized.
function localizeCancelMarker(text) {
    if (!text) return text;
    if (currentLang !== 'zh') return text;
    return text
        .replace(/_\(Cancelled by user\)_/g, '_(用户已中止)_')
        .replace(/_\(Cancelled\)_/g, '_(已中止)_');
}

function createBotMessageEl(content, timestamp, requestId, msg) {
    const el = document.createElement('div');
    el.className = 'flex gap-3 px-4 sm:px-6 py-3 bot-message-group';
    if (requestId) el.dataset.requestId = requestId;

    let stepsHtml = '';
    let displayContent = localizeCancelMarker(content);

    if (msg && msg.steps && msg.steps.length > 0) {
        // New format: ordered steps with interleaved content
        const result = renderStepsHtml(msg.steps);
        stepsHtml = result.stepsHtml;
        // The final content (last text after all steps) is the main answer
        displayContent = content || result.lastContentText;
    } else {
        // Legacy format: separate tool_calls + optional reasoning
        const toolCalls = msg && msg.tool_calls;
        const reasoning = msg && msg.reasoning;
        stepsHtml = renderThinkingHtml(reasoning) + renderToolCallsHtml(toolCalls);
    }

    // Files written this turn, as computed by the history API (workspace.js).
    const artifactsHtml = typeof renderArtifactCards === 'function'
        ? renderArtifactCards(msg && msg.artifacts)
        : '';

    // Self-evolution bubbles get a small badge so the user can feel the agent
    // learned something on its own (text itself stays clean). History replay
    // carries msg.kind; live pushes are identified by the evolution_ request id.
    const isEvolution = (msg && msg.kind === 'evolution')
        || (typeof requestId === 'string' && requestId.startsWith('evolution_'));
    const evolutionBadge = isEvolution
        ? `<div class="flex items-center gap-1 mb-1.5 text-xs text-slate-400 dark:text-slate-500">
                <i class="fas fa-seedling text-[11px]"></i>
                <span>${t('evolution_badge')}</span>
           </div>`
        : '';

    // The reply's face is whichever Agent spoke: its uploaded image, or the
    // product logo by default. A shared conversation also labels the bubble,
    // since consecutive bubbles can come from different Agents; a solo chat
    // stays unlabelled but still reflects that Agent's own avatar.
    const speaker = botSpeakerAgent(msg, requestId) || findAgent(activeAgentId);
    // Remember who spoke, so a later avatar change can repaint this exact face
    // without re-rendering the whole bubble.
    if (speaker && speaker.id) el.dataset.speakerAgent = speaker.id;
    const faceHtml = `<span class="bot-face">${agentAvatarHTML(speaker, 32)}</span>`;
    const speakerName = (sharedConversation() && speaker)
        ? `<div class="bot-speaker">${escapeHtml(speaker.name || speaker.id)}</div>`
        : '';

    el.innerHTML = `
        ${faceHtml}
        <div class="min-w-0 flex-1 max-w-[85%]">
            ${speakerName}
            <div class="bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-2xl px-4 py-3 text-sm leading-relaxed msg-content text-slate-700 dark:text-slate-200">
                ${evolutionBadge}
                ${stepsHtml ? `<div class="agent-steps">${stepsHtml}</div>` : ''}
                <div class="answer-content">${renderMarkdown(displayContent)}</div>
                <div class="media-content">${artifactsHtml}</div>
                <div class="bot-audio-slot"></div>
            </div>
            <div class="flex items-center gap-2 mt-1.5">
                <span class="text-xs text-slate-400 dark:text-slate-500">${formatTime(timestamp)}</span>
                <button class="copy-msg-btn text-xs text-slate-300 dark:text-slate-600 hover:text-slate-500 dark:hover:text-slate-400 transition-colors cursor-pointer" title="${currentLang === 'zh' ? '复制' : 'Copy'}">
                    <i class="fas fa-copy"></i>
                </button>
                <button class="speak-msg-btn text-xs text-slate-300 dark:text-slate-600 hover:text-slate-500 dark:hover:text-slate-400 transition-colors cursor-pointer" title="${t('speak_msg')}" style="display:none;">
                    <i class="fas fa-volume-up"></i>
                </button>
                <button class="regenerate-msg-btn text-xs text-slate-300 dark:text-slate-600 hover:text-primary-400 dark:hover:text-primary-400 transition-colors cursor-pointer" title="${t('regenerate_response')}">
                    <i class="fas fa-rotate-right"></i>
                </button>
            </div>
        </div>
    `;
    el.querySelector('.answer-content').dataset.rawMd = displayContent;
    // Existing TTS attachment (history replay): mount the player up-front.
    const existingAudio = msg && msg.extras && msg.extras.audio && msg.extras.audio.url;
    if (existingAudio) {
        attachAudioToBotBubble(el, existingAudio, { autoplay: false });
    }
    renderBotSpeakerButton(el, displayContent);
    applyHighlighting(el);
    return el;
}

// Append (or replace) a small audio player inside a bot bubble's
// dedicated `.bot-audio-slot`. Used by both live TTS pushes and history
// replay. Silent failures: never throws.
function attachAudioToBotBubble(botEl, audioUrl, opts) {
    try {
        if (!botEl || !audioUrl) return;
        const slot = botEl.querySelector('.bot-audio-slot');
        if (!slot) return;
        slot.innerHTML = '';
        slot.style.marginTop = '6px';
        const pill = renderVoicePill(audioUrl, { autoplay: !!(opts && opts.autoplay) });
        slot.appendChild(pill);
        const speakBtn = botEl.querySelector('.speak-msg-btn');
        if (speakBtn) speakBtn.style.display = 'none';
    } catch (_) { /* silent */ }
}

function pendingVoiceAttachmentKey(sid, botSeq) {
    return `${sid}:${botSeq}`;
}

function rememberPendingVoiceAttachment(sid, botSeq, audioUrl) {
    if (!sid || botSeq === undefined || botSeq === null || !audioUrl) return;
    const key = pendingVoiceAttachmentKey(sid, botSeq);
    const pending = {
        sid,
        botSeq: String(botSeq),
        audioUrl,
        expiresAt: Date.now() + PENDING_VOICE_ATTACH_TTL_MS,
    };
    pendingVoiceAttachments.delete(key);
    pendingVoiceAttachments.set(key, pending);

    while (pendingVoiceAttachments.size > PENDING_VOICE_ATTACH_MAX) {
        pendingVoiceAttachments.delete(pendingVoiceAttachments.keys().next().value);
    }
    setTimeout(() => {
        if (pendingVoiceAttachments.get(key) === pending) {
            pendingVoiceAttachments.delete(key);
        }
    }, PENDING_VOICE_ATTACH_TTL_MS);
}

function flushPendingVoiceAttachments(sid, autoplay) {
    if (!sid || sid !== sessionId) return 0;
    const now = Date.now();
    let attached = 0;
    pendingVoiceAttachments.forEach((pending, key) => {
        if (pending.expiresAt <= now) {
            pendingVoiceAttachments.delete(key);
            return;
        }
        if (pending.sid !== sid) return;
        const botEl = Array.from(
            messagesDiv.querySelectorAll('.bot-message-group[data-seq]')
        ).find(el => el.dataset.seq === pending.botSeq);
        if (!botEl) return;
        attachAudioToBotBubble(botEl, pending.audioUrl, { autoplay: !!autoplay });
        pendingVoiceAttachments.delete(key);
        attached++;
    });
    return attached;
}

// Build a compact play/pause + progress + duration pill that wraps a
// hidden <audio>. Returns the root element; safe to embed anywhere.
function renderVoicePill(audioUrl, opts) {
    opts = opts || {};
    const wrap = document.createElement('div');
    wrap.className = 'voice-pill';
    wrap.innerHTML = `
        <button type="button" class="voice-pill-btn" data-state="play" aria-label="play">
            <i class="fas fa-play"></i>
        </button>
        <div class="voice-pill-track"><div class="voice-pill-fill"></div></div>
        <span class="voice-pill-time">0:00</span>
        <audio preload="metadata" src="${audioUrl}"></audio>
    `;
    const btn = wrap.querySelector('.voice-pill-btn');
    const fill = wrap.querySelector('.voice-pill-fill');
    const timeEl = wrap.querySelector('.voice-pill-time');
    const audio = wrap.querySelector('audio');

    const fmt = (s) => {
        if (!isFinite(s) || s < 0) s = 0;
        const m = Math.floor(s / 60);
        const r = Math.floor(s % 60);
        return `${m}:${r < 10 ? '0' : ''}${r}`;
    };
    const setIcon = (state) => {
        btn.dataset.state = state;
        btn.querySelector('i').className = state === 'pause' ? 'fas fa-pause' : 'fas fa-play';
        btn.setAttribute('aria-label', state === 'pause' ? 'pause' : 'play');
    };

    audio.addEventListener('loadedmetadata', () => {
        if (audio.duration && isFinite(audio.duration)) timeEl.textContent = fmt(audio.duration);
    });
    audio.addEventListener('timeupdate', () => {
        const dur = audio.duration || 0;
        if (dur > 0) {
            fill.style.width = `${Math.min(100, (audio.currentTime / dur) * 100)}%`;
            timeEl.textContent = fmt(dur - audio.currentTime);
        }
    });
    audio.addEventListener('ended', () => {
        setIcon('play');
        fill.style.width = '0%';
        timeEl.textContent = fmt(audio.duration || 0);
    });
    audio.addEventListener('play',  () => setIcon('pause'));
    audio.addEventListener('pause', () => setIcon('play'));

    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (audio.paused) {
            audio.play().catch(() => {});
        } else {
            audio.pause();
        }
    });

    if (opts.autoplay) {
        // Autoplay may be blocked by the browser; fall back silently and
        // let the user tap the play button.
        const tryPlay = () => audio.play().catch(() => {});
        if (audio.readyState >= 2) tryPlay();
        else audio.addEventListener('canplay', tryPlay, { once: true });
    }
    return wrap;
}

// Show the manual "read aloud" button when TTS is configured but the
// bubble has no audio yet. Lazily probes capability via /api/models so
// we don't expose the button when nothing can synthesize speech.
function renderBotSpeakerButton(botEl, text) {
    if (!botEl || !text || !text.trim()) return;
    const btn = botEl.querySelector('.speak-msg-btn');
    if (!btn) return;
    if (botEl.querySelector('.bot-audio-slot audio')) return;
    _isTtsReady().then(ready => {
        if (!ready) return;
        btn.style.display = '';
        btn.onclick = () => _triggerManualTts(btn, botEl, text);
    });
}

let _ttsReadyPromise = null;
let _ttsReadyTs = 0;
function _isTtsReady() {
    // Cache for 30s to avoid hammering /api/models on every bubble.
    if (_ttsReadyPromise && Date.now() - _ttsReadyTs < 30000) {
        return _ttsReadyPromise;
    }
    _ttsReadyTs = Date.now();
    _ttsReadyPromise = fetch('/api/models')
        .then(r => r.json())
        .then(data => {
            const tts = data && data.capabilities && data.capabilities.tts;
            if (!tts) return false;
            return Boolean(tts.current_provider || tts.suggested_provider);
        })
        .catch(() => false);
    return _ttsReadyPromise;
}

function _triggerManualTts(btn, botEl, text) {
    if (btn.dataset.busy === '1') return;
    btn.dataset.busy = '1';
    const icon = btn.querySelector('i');
    const prev = icon ? icon.className : '';
    if (icon) icon.className = 'fas fa-spinner fa-spin';
    fetch('/api/voice/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, session_id: sessionId }),
    })
        .then(r => r.json())
        .then(data => {
            if (data && data.status === 'success' && data.audio_url) {
                attachAudioToBotBubble(botEl, data.audio_url, { autoplay: true });
            }
        })
        .catch(() => {})
        .finally(() => {
            btn.dataset.busy = '0';
            if (icon) icon.className = prev || 'fas fa-volume-up';
        });
}

function addUserMessage(content, timestamp, attachments) {
    const el = createUserMessageEl(content, timestamp, attachments);
    messagesDiv.appendChild(el);
    _autoScrollEnabled = true;
    scrollChatToBottom(true);
}

function addBotMessage(content, timestamp, requestId) {
    const el = createBotMessageEl(content, timestamp, requestId);
    messagesDiv.appendChild(el);
    scrollChatToBottom();
}

// Load conversation history from the server (page 1 = most recent messages).
// Subsequent pages prepend older messages when the user scrolls to the top.
function loadHistory(page) {
    if (historyLoading) return;
    historyLoading = true;
    const historySessionId = sessionId;

    // A shared conversation labels each bubble with its author and paints the
    // right face. That resolution needs this session's team roster (_sessCfg),
    // which loads asynchronously; without it every replayed bubble falls back
    // to the owner's avatar and loses its name. Make sure the roster is in hand
    // before rendering so a reload looks exactly like the live conversation.
    const ready = _sessCfg ? Promise.resolve() : refreshSessionSettings().catch(() => {});

    ready.then(() => fetch(`/api/history?session_id=${encodeURIComponent(historySessionId)}&page=${page}&page_size=20`)
        .then(r => r.json())
        .then(data => {
            // A response from a session we have since left must never render
            // into the new session's message list.
            if (historySessionId !== sessionId) return;
            if (data.status !== 'success' || data.messages.length === 0) return;

            const prevScrollHeight = messagesDiv.scrollHeight;
            const isFirstLoad = page === 1;

            // On first load, remove the welcome screen if history exists
            if (isFirstLoad) {
                const ws = document.getElementById('welcome-screen');
                if (ws) ws.remove();
            }

            // Build a fragment of history message elements in chronological order
            const fragment = document.createDocumentFragment();

            if (data.has_more && page > 1) {
                // Keep the "load more" sentinel in place (inserted below)
            }

            const ctxStartSeq = data.context_start_seq || 0;
            let dividerInserted = false;

            data.messages.forEach(msg => {
                const hasContent = msg.content && msg.content.trim();
                const hasToolCalls = msg.role === 'assistant' && msg.tool_calls && msg.tool_calls.length > 0;
                if (!hasContent && !hasToolCalls) return;

                // Insert context divider when transitioning from above to below boundary
                if (ctxStartSeq > 0 && !dividerInserted && msg._seq !== undefined && msg._seq >= ctxStartSeq) {
                    dividerInserted = true;
                    const divider = document.createElement('div');
                    divider.className = 'context-divider';
                    divider.innerHTML = `<span>${t('context_cleared')}</span>`;
                    fragment.appendChild(divider);
                }

                const ts = new Date(msg.created_at * 1000);
                const el = msg.role === 'user'
                    ? createUserMessageEl(msg.content, ts)
                    : createBotMessageEl(msg.content || '', ts, null, msg);
                // Store seq for delete functionality
                if (msg._seq !== undefined) {
                    el.dataset.seq = msg._seq;
                }
                fragment.appendChild(el);
            });

            // If context was cleared but no new messages exist yet, append divider at the end
            if (ctxStartSeq > 0 && !dividerInserted) {
                const divider = document.createElement('div');
                divider.className = 'context-divider';
                divider.innerHTML = `<span>${t('context_cleared')}</span>`;
                fragment.appendChild(divider);
            }

            // Prepend history above any existing messages
            const sentinel = document.getElementById('history-load-more');
            const insertBefore = sentinel ? sentinel.nextSibling : messagesDiv.firstChild;
            messagesDiv.insertBefore(fragment, insertBefore);
            updateEditButtonsState();
            // A background voice_attach can arrive before this history
            // fragment creates its target bubble. Retry now that seq metadata
            // is present in the DOM; do not autoplay delayed attachments.
            if (isFirstLoad) {
                flushPendingVoiceAttachments(historySessionId, false);
            }

            // Manage the "load more" sentinel at the very top
            if (data.has_more) {
                if (!document.getElementById('history-load-more')) {
                    const btn = document.createElement('div');
                    btn.id = 'history-load-more';
                    btn.className = 'flex justify-center py-3';
                    btn.innerHTML = `<button class="text-xs text-slate-400 dark:text-slate-500 hover:text-primary-400 transition-colors" onclick="loadHistory(historyPage + 1)">Load earlier messages</button>`;
                    messagesDiv.insertBefore(btn, messagesDiv.firstChild);
                }
            } else {
                const sentinel = document.getElementById('history-load-more');
                if (sentinel) sentinel.remove();
            }

            historyHasMore = data.has_more;
            historyPage = page;

            if (isFirstLoad) {
                // Scroll to the very bottom after the DOM settles. A single
                // rAF isn't enough: markdown/code-highlight/images keep growing
                // scrollHeight after the first paint, leaving the last bubble's
                // timestamp clipped. Re-pin a few times to catch late layout.
                requestAnimationFrame(() => scrollChatToBottom(true));
                [120, 350, 700].forEach(d => setTimeout(() => scrollChatToBottom(true), d));
            } else {
                // Restore scroll position so loading older messages doesn't jump the view
                messagesDiv.scrollTop = messagesDiv.scrollHeight - prevScrollHeight;
            }
        })
        .catch(() => {})
        .finally(() => {
            historyLoading = false;
            renderComposerIdentity();
        }));
}

function addLoadingIndicator() {
    const el = document.createElement('div');
    el.className = 'flex gap-3 px-4 sm:px-6 py-3 loading-indicator';
    // Starts on the conversation's own Agent; setLoadingSpeaker swaps the face
    // once the server says who actually took the turn (an addressed teammate).
    el.innerHTML = `
        <span class="bot-face">${agentAvatarHTML(findAgent(activeAgentId), 32)}</span>
        <div class="bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-2xl px-4 py-3">
            <div class="flex items-center gap-1.5">
                <span class="w-2 h-2 rounded-full bg-primary-400 animate-pulse-dot" style="animation-delay: 0s"></span>
                <span class="w-2 h-2 rounded-full bg-primary-400 animate-pulse-dot" style="animation-delay: 0.2s"></span>
                <span class="w-2 h-2 rounded-full bg-primary-400 animate-pulse-dot" style="animation-delay: 0.4s"></span>
            </div>
        </div>
    `;
    messagesDiv.appendChild(el);
    scrollChatToBottom();
    return el;
}

/* The session-panel "新对话" button. With a single Agent there is nobody to
   choose between, so it just starts a chat. With several, it opens a menu: pick
   an Agent for a solo chat, or open the team picker for a group chat. */
function onNewChatButton(event) {
    if (!multiAgentMode()) { newChat(true); return; }
    if (event) event.stopPropagation();
    const menu = document.getElementById('new-chat-menu');
    if (!menu) { newChat(true); return; }
    if (!menu.classList.contains('hidden')) { menu.classList.add('hidden'); return; }
    const rows = enabledAgents().map(agent => `
        <button type="button" class="new-chat-item" onclick="startSoloChat('${escapeHtml(agent.id)}')">
            ${agentAvatarHTML(agent, 22)}
            <span>${escapeHtml(agent.name)}</span>
        </button>`).join('');
    menu.innerHTML = `
        <div class="new-chat-section">${rows}</div>
        <div class="new-chat-sep"></div>
        <button type="button" class="new-chat-item new-chat-team" onclick="openTeamChatModal()">
            <span class="new-chat-team-ico"><i class="fas fa-user-group"></i></span>
            <span>${escapeHtml(t('new_team_chat'))}</span>
        </button>`;
    menu.classList.remove('hidden');
}

function startSoloChat(agentId) {
    document.getElementById('new-chat-menu')?.classList.add('hidden');
    if (!agentId) { newChat(true); return; }
    activeAgentId = agentId;
    localStorage.setItem('cow_active_agent', activeAgentId);
    newChat(true);
    if (typeof resetWorkspaceToAgentRoot === 'function') resetWorkspaceToAgentRoot();
    renderComposerIdentity();
}

// The first checked Agent owns the conversation; the rest are invited as guests.
let _teamChatPicks = [];

function openTeamChatModal() {
    document.getElementById('new-chat-menu')?.classList.add('hidden');
    _teamChatPicks = [activeAgentId || defaultAgentId];
    const status = document.getElementById('team-chat-status');
    if (status) status.textContent = '';
    renderTeamChatList();
    document.getElementById('team-chat-modal')?.classList.remove('hidden');
}

function closeTeamChatModal() {
    document.getElementById('team-chat-modal')?.classList.add('hidden');
}

/** From the group-chat picker, jump to creating a new Agent. */
function openAgentCreateFromModal() {
    closeTeamChatModal();
    navigateTo('agents');
    if (typeof openAgentCreateForm === 'function') openAgentCreateForm();
}

function toggleTeamChatPick(agentId) {
    const i = _teamChatPicks.indexOf(agentId);
    if (i === -1) _teamChatPicks.push(agentId);
    else _teamChatPicks.splice(i, 1);
    renderTeamChatList();
}

function renderTeamChatList() {
    const list = document.getElementById('team-chat-list');
    if (!list) return;
    list.innerHTML = enabledAgents().map(agent => {
        const rank = _teamChatPicks.indexOf(agent.id);
        const on = rank !== -1;
        const owner = rank === 0;
        return `<button type="button" class="team-chat-row${on ? ' on' : ''}" onclick="toggleTeamChatPick('${escapeHtml(agent.id)}')">
            ${agentAvatarHTML(agent, 28)}
            <span class="team-chat-name">${escapeHtml(agent.name)}</span>
            ${owner ? `<span class="team-chat-owner">${escapeHtml(t('new_team_chat_owner'))}</span>` : ''}
            <span class="team-chat-check"><i class="fas ${on ? 'fa-circle-check' : 'fa-circle'}"></i></span>
        </button>`;
    }).join('');
}

function startTeamChat() {
    const picks = _teamChatPicks.filter(id => enabledAgents().some(a => a.id === id));
    if (picks.length < 2) {
        const status = document.getElementById('team-chat-status');
        if (status) status.textContent = t('new_team_chat_min');
        return;
    }
    closeTeamChatModal();
    const [owner, ...guests] = picks;
    activeAgentId = owner;
    localStorage.setItem('cow_active_agent', activeAgentId);
    newChat(true);
    if (typeof resetWorkspaceToAgentRoot === 'function') resetWorkspaceToAgentRoot();
    // The fresh session exists client-side; invite the guests onto it so the
    // very first message already goes to a group.
    setTeamMembers(guests).then(() => renderComposerIdentity());
}

function newChat(optimistic = true, inherit = true) {
    // A fresh session resets the preview panel, discarding an open editor.
    if (typeof wsGuardUnsaved === 'function'
        && !wsGuardUnsaved(() => newChat(optimistic, inherit))) return;

    // Do NOT close active streams: other sessions keep streaming in the
    // background (each stream self-guards against the foreign view) and their
    // replies still complete and persist.

    // Generate a fresh session and persist it so the next page load also starts clean
    sessionId = generateSessionId();
    localStorage.setItem(activeSessionStorageKey(), sessionId);
    refreshWorkspaceSelector();  // a fresh session starts on the default workspace
    refreshSessionSettings();    // ... and on the global model / permission
    if (typeof wsOnSessionSwitch === 'function') wsOnSessionSwitch();
    resetSendBtnSendMode();  // fresh session has no in-flight reply
    startPolling();  // bump generation so old loop self-cancels, new loop uses fresh sessionId
    messagesDiv.innerHTML = '';
    const ws = document.createElement('div');
    ws.id = 'welcome-screen';
    ws.className = 'flex flex-col items-center justify-center h-full px-6 pb-16';
    ws.style.paddingTop = '6vh';
    ws.innerHTML = `
        <img src="assets/logo.jpg" alt="CowAgent" class="w-16 h-16 rounded-2xl mb-6 shadow-lg shadow-primary-500/20">
        <h1 class="text-2xl font-bold text-slate-800 dark:text-slate-100 mb-3">${appConfig.title || 'CowAgent'}</h1>
        <p class="text-slate-500 dark:text-slate-400 text-center max-w-lg mb-10 leading-relaxed" data-i18n="welcome_subtitle">${t('welcome_subtitle')}</p>
        <div class="grid grid-cols-2 sm:grid-cols-3 gap-3 w-full max-w-2xl">
            <div class="example-card group bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-xl p-4 cursor-pointer hover:border-primary-300 dark:hover:border-primary-600 hover:shadow-md transition-all duration-200">
                <div class="flex items-center gap-2 mb-2">
                    <div class="w-7 h-7 rounded-lg bg-blue-50 dark:bg-blue-900/30 flex items-center justify-center">
                        <i class="fas fa-folder-open text-blue-500 text-xs"></i>
                    </div>
                    <span class="font-medium text-sm text-slate-700 dark:text-slate-200" data-i18n="example_sys_title">${t('example_sys_title')}</span>
                </div>
                <p class="text-sm text-slate-500 dark:text-slate-400 leading-relaxed" data-i18n="example_sys_text">${t('example_sys_text')}</p>
            </div>
            <div class="example-card group bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-xl p-4 cursor-pointer hover:border-primary-300 dark:hover:border-primary-600 hover:shadow-md transition-all duration-200">
                <div class="flex items-center gap-2 mb-2">
                    <div class="w-7 h-7 rounded-lg bg-amber-50 dark:bg-amber-900/30 flex items-center justify-center">
                        <i class="fas fa-clock text-amber-500 text-xs"></i>
                    </div>
                    <span class="font-medium text-sm text-slate-700 dark:text-slate-200" data-i18n="example_task_title">${t('example_task_title')}</span>
                </div>
                <p class="text-sm text-slate-500 dark:text-slate-400 leading-relaxed" data-i18n="example_task_text">${t('example_task_text')}</p>
            </div>
            <div class="example-card group bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-xl p-4 cursor-pointer hover:border-primary-300 dark:hover:border-primary-600 hover:shadow-md transition-all duration-200">
                <div class="flex items-center gap-2 mb-2">
                    <div class="w-7 h-7 rounded-lg bg-emerald-50 dark:bg-emerald-900/30 flex items-center justify-center">
                        <i class="fas fa-code text-emerald-500 text-xs"></i>
                    </div>
                    <span class="font-medium text-sm text-slate-700 dark:text-slate-200" data-i18n="example_code_title">${t('example_code_title')}</span>
                </div>
                <p class="text-sm text-slate-500 dark:text-slate-400 leading-relaxed" data-i18n="example_code_text">${t('example_code_text')}</p>
            </div>
            <div class="example-card group bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-xl p-4 cursor-pointer hover:border-primary-300 dark:hover:border-primary-600 hover:shadow-md transition-all duration-200">
                <div class="flex items-center gap-2 mb-2">
                    <div class="w-7 h-7 rounded-lg bg-violet-50 dark:bg-violet-900/30 flex items-center justify-center">
                        <i class="fas fa-book text-violet-500 text-xs"></i>
                    </div>
                    <span class="font-medium text-sm text-slate-700 dark:text-slate-200" data-i18n="example_knowledge_title">${t('example_knowledge_title')}</span>
                </div>
                <p class="text-sm text-slate-500 dark:text-slate-400 leading-relaxed" data-i18n="example_knowledge_text">${t('example_knowledge_text')}</p>
            </div>
            <div class="example-card group bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-xl p-4 cursor-pointer hover:border-primary-300 dark:hover:border-primary-600 hover:shadow-md transition-all duration-200">
                <div class="flex items-center gap-2 mb-2">
                    <div class="w-7 h-7 rounded-lg bg-rose-50 dark:bg-rose-900/30 flex items-center justify-center">
                        <i class="fas fa-puzzle-piece text-rose-500 text-xs"></i>
                    </div>
                    <span class="font-medium text-sm text-slate-700 dark:text-slate-200" data-i18n="example_skill_title">${t('example_skill_title')}</span>
                </div>
                <p class="text-sm text-slate-500 dark:text-slate-400 leading-relaxed" data-i18n="example_skill_text">${t('example_skill_text')}</p>
            </div>
            <div class="example-card group bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-xl p-4 cursor-pointer hover:border-primary-300 dark:hover:border-primary-600 hover:shadow-md transition-all duration-200" data-send="/help">
                <div class="flex items-center gap-2 mb-2">
                    <div class="w-7 h-7 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center">
                        <i class="fas fa-terminal text-slate-500 text-xs"></i>
                    </div>
                    <span class="font-medium text-sm text-slate-700 dark:text-slate-200" data-i18n="example_web_title">${t('example_web_title')}</span>
                </div>
                <p class="text-sm text-slate-500 dark:text-slate-400 leading-relaxed" data-i18n="example_web_text">${t('example_web_text')}</p>
            </div>
        </div>
    `;
    messagesDiv.appendChild(ws);
    renderComposerIdentity();
    ws.querySelectorAll('.example-card').forEach(card => {
        card.addEventListener('click', () => {
            const sendText = card.dataset.send;
            if (sendText) {
                chatInput.value = sendText;
                chatInput.dispatchEvent(new Event('input'));
                chatInput.focus();
                return;
            }
            const textEl = card.querySelector('[data-i18n*="text"]');
            if (textEl) {
                chatInput.value = textEl.textContent;
                chatInput.dispatchEvent(new Event('input'));
                chatInput.focus();
            }
        });
    });
    if (currentView !== 'chat') navigateTo('chat');

    // Show panel and load full session list, then prepend the new session on top
    const panel = document.getElementById('session-panel');
    if (panel && !sessionPanelOpen) {
        sessionPanelOpen = true;
        panel.classList.remove('hidden');
        _showSessionOverlay();
        _persistPanelState();
    }
    // Only prepend an optimistic "new chat" item when this is a real new-chat
    // action. When called after deleting the current session, skip it: the
    // fresh session has no backend record yet, so inserting it would leave an
    // empty, undeletable item in the list (deleting it just spawns another).
    const newSid = sessionId;
    if (optimistic) {
        loadSessionList(() => _addOptimisticSessionItem(newSid));
    } else {
        loadSessionList();
    }
}

// =====================================================================
// Session Panel
// =====================================================================

const SESSION_PANEL_KEY = 'cow_session_panel_open';
let sessionPanelOpen = localStorage.getItem(SESSION_PANEL_KEY) === '1';
// Whether the history panel was open before entering the team page, so it can
// be restored on the way out (the team page force-closes it for room).
let _sessionPanelWasOpen = false;

function _persistPanelState() {
    localStorage.setItem(SESSION_PANEL_KEY, sessionPanelOpen ? '1' : '0');
}

function _isMobileView() {
    return window.innerWidth <= 768;
}

function _showSessionOverlay() {
    if (!_isMobileView()) return;
    const overlay = document.getElementById('session-panel-overlay');
    if (overlay) overlay.classList.remove('hidden');
}

function _hideSessionOverlay() {
    const overlay = document.getElementById('session-panel-overlay');
    if (overlay) overlay.classList.add('hidden');
}

function closeSessionPanel(skipPersist) {
    const panel = document.getElementById('session-panel');
    if (!panel || !sessionPanelOpen) return;
    sessionPanelOpen = false;
    panel.classList.add('hidden');
    _hideSessionOverlay();
    // When the team page tucks the panel away it shouldn't overwrite the user's
    // own preference; only real user closes persist.
    if (!skipPersist) _persistPanelState();
}

function toggleSessionPanel() {
    const panel = document.getElementById('session-panel');
    if (!panel) return;
    sessionPanelOpen = !sessionPanelOpen;
    panel.classList.toggle('hidden', !sessionPanelOpen);
    if (sessionPanelOpen) {
        _showSessionOverlay();
    } else {
        _hideSessionOverlay();
    }
    _persistPanelState();
    if (sessionPanelOpen) loadSessionList();
}

function openSessionPanel() {
    const panel = document.getElementById('session-panel');
    if (!panel || sessionPanelOpen) return;
    sessionPanelOpen = true;
    panel.classList.remove('hidden');
    _showSessionOverlay();
    _persistPanelState();
    loadSessionList();
}

function _restoreSessionPanel() {
    const panel = document.getElementById('session-panel');
    if (!panel) return;
    if (sessionPanelOpen && !_isMobileView()) {
        panel.classList.remove('hidden');
        _showSessionOverlay();
        loadSessionList();
    } else {
        panel.classList.add('hidden');
        _hideSessionOverlay();
    }
}

// Swap the native `title` for the CSS tooltip so hints appear instantly
// instead of waiting for the browser's built-in delay.
function _setBtnTooltip(el, text) {
    if (!el) return;
    el.setAttribute('data-tooltip', text);
    el.removeAttribute('title');
}

function _applyInputTooltips() {
    const set = (id, key, pos) => {
        const el = document.getElementById(id);
        if (!el) return;
        _setBtnTooltip(el, t(key));
        if (pos) el.setAttribute('data-tooltip-pos', pos);
    };
    set('new-chat-btn', 'tip_new_chat');
    // #clear-context-btn gets a rich hover popover (context-usage chart) instead
    // of the plain text tooltip, so it must not carry a data-tooltip here —
    // otherwise both would pop at once.
    set('attach-btn', 'tip_attach');
    set('steer-btn', 'steer_active');
    set('session-toggle-btn', 'session_history', 'bottom');
    set('workspace-toggle-btn', 'ws_toggle', 'bottom');
    // Optimize / mic buttons carry state-dependent tooltips managed in their
    // own setup, but on language switch we reset them to the idle label so the
    // tooltip follows the current locale.
    set('optimize-btn', 'optimize_idle_title');
    set('mic-btn', 'mic_idle_title');
    // Send button only carries a tooltip while it acts as the cancel button.
    _setBtnTooltip(sendBtn, sendBtnMode === 'cancel' ? t('tip_cancel') : '');
    // The permission / model chips carry translated labels and tooltips, so they
    // are repainted here too (this runs on every language switch).
    _renderPermissionChip();
    _renderModelChip();
    // applyI18n resets the placeholder to the solo hint via data-i18n-placeholder,
    // so re-apply the team-aware variant for group conversations.
    _renderInputPlaceholder();
}

// A session that exists in the browser but not yet in the database: the user
// pressed "new chat" and has not sent the first message. Rendered from the same
// path as real sessions so it lands in the right group.
function _addOptimisticSessionItem(sid) {
    const container = document.getElementById('session-list');
    if (!container) return;
    if (_sessionItems.some(s => s.session_id === sid)) return;

    _sessionItems.unshift({
        session_id: sid,
        title: t('new_chat'),
        last_active: Math.floor(Date.now() / 1000),
        pinned: 0,
        // The fresh session inherits the workspace the selector currently shows.
        project: _wsSelState.current
            ? { path: _wsSelState.current.path, name: _wsSelState.current.name }
            : null,
    });
    _renderSessionList();
}

function _sessionTimeGroup(ts) {
    const now = new Date();
    const d = new Date(ts * 1000);
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
    if (d >= today) return t('today');
    if (d >= yesterday) return t('yesterday');
    return t('earlier');
}

let _sessionPage = 1;
let _sessionHasMore = false;
let _sessionLoading = false;
const _SESSION_PAGE_SIZE = 50;

// Every session loaded so far, in backend order (pinned first, then recency).
// Kept as data rather than only as DOM because grouping by project reorders the
// whole list, which cannot be done by appending page by page.
let _sessionItems = [];
// 'time' (今天/昨天/更早, the behavior before projects existed) or 'project'.
// The backend decides, based on how many spaces are in use across all sessions.
let _sessionGroupMode = 'time';
// User-chosen order of project spaces (paths + '__default__'), from the backend.
let _projectOrder = [];
// Sentinel the backend uses for the default workspace in the ordering.
const DEFAULT_SPACE_KEY = '__default__';

// Which project groups are collapsed, persisted per-browser so the choice
// survives reloads. Keyed by space key (project path or the default sentinel).
const _COLLAPSED_KEY = 'cow_collapsed_projects';
function _loadCollapsed() {
    try { return new Set(JSON.parse(localStorage.getItem(_COLLAPSED_KEY) || '[]')); }
    catch (e) { return new Set(); }
}
function _saveCollapsed(set) {
    try { localStorage.setItem(_COLLAPSED_KEY, JSON.stringify([...set])); } catch (e) {}
}
let _collapsedProjects = _loadCollapsed();

function loadSessionList(onDone) {
    const container = document.getElementById('session-list');
    if (!container) return;

    _sessionPage = 1;
    _sessionHasMore = false;

    _fetchSessionPage(1, true, onDone);
}

function _fetchSessionPage(page, clear, onDone) {
    if (_sessionLoading) return;
    _sessionLoading = true;

    const container = document.getElementById('session-list');
    if (!container) { _sessionLoading = false; return; }

    fetch(`/api/sessions?page=${page}&page_size=${_SESSION_PAGE_SIZE}&scope=all`)
        .then(r => r.json())
        .then(data => {
            _sessionLoading = false;
            if (data.status !== 'success') return;

            if (clear) _sessionItems = [];

            const sessions = data.sessions || [];
            _sessionPage = page;
            _sessionHasMore = !!data.has_more;
            _sessionGroupMode = data.group_mode === 'project' ? 'project' : 'time';
            if (Array.isArray(data.project_order)) _projectOrder = data.project_order;

            const sessionKey = s => `${(s.agent && s.agent.id) || ''}::${s.session_id}`;
            const seen = new Set(_sessionItems.map(sessionKey));
            sessions.forEach(s => {
                const key = sessionKey(s);
                if (seen.has(key)) return;
                seen.add(key);
                _sessionItems.push(s);
            });

            _renderSessionList();
            if (typeof onDone === 'function') onDone();
        })
        .catch(() => { _sessionLoading = false; });
}

// Split the loaded sessions into ordered, labelled groups.
//
// Time mode keeps the original today/yesterday/earlier buckets, with one
// addition: pinned conversations move into a group of their own at the top,
// because a pin that stayed inside its date bucket would not be findable.
// Project mode groups by workspace instead, and pins float to the top of their
// own project - that is where the user filed them.
function _sessionGroups() {
    const groups = [];
    const bucket = (key, label, icon, hint, isProject) => {
        let g = groups.find(x => x.key === key);
        if (!g) { g = { key, label, icon, hint, isProject, items: [] }; groups.push(g); }
        return g;
    };

    if (_sessionGroupMode === 'project') {
        // `_sessionItems` is already pinned-first / newest-first, so appending in
        // order gives each project the same ordering for free.
        _sessionItems.forEach(s => {
            const key = s.project ? s.project.path : DEFAULT_SPACE_KEY;
            const name = s.project ? s.project.name : t('ws_default_workspace');
            const icon = s.project ? 'fa-folder' : 'fa-house';
            bucket(key, name, icon, s.project ? s.project.path : '', !!s.project).items.push(s);
        });
        // Sort groups by the user's chosen order; spaces without a saved
        // position keep their natural (recency) order after the ordered ones.
        if (_projectOrder.length) {
            const rank = new Map(_projectOrder.map((k, i) => [k, i]));
            groups.sort((a, b) => {
                const ra = rank.has(a.key) ? rank.get(a.key) : Infinity;
                const rb = rank.has(b.key) ? rank.get(b.key) : Infinity;
                return ra - rb;
            });
        }
        return groups;
    }

    const pinned = _sessionItems.filter(s => s.pinned);
    if (pinned.length) {
        bucket('__pinned__', t('session_pinned_group'), 'fa-thumbtack', '', false).items.push(...pinned);
    }
    _sessionItems.filter(s => !s.pinned).forEach(s => {
        const label = _sessionTimeGroup(s.last_active);
        bucket('time:' + label, label, '', '', false).items.push(s);
    });
    return groups;
}

function _renderSessionList() {
    const container = document.getElementById('session-list');
    if (!container) return;

    if (!_sessionItems.length) {
        container.innerHTML = '<div class="session-empty">' + t('untitled_session') + '</div>';
        return;
    }

    container.innerHTML = '';
    const projectMode = _sessionGroupMode === 'project';
    // Indent sessions under their project header when several projects are
    // shown, so the list reads as a tree aligned to the folder icon above.
    const indentItems = projectMode && _sessionGroups().length > 1;
    _sessionGroups().forEach(group => {
        const collapsed = projectMode && _collapsedProjects.has(group.key);
        const header = document.createElement('div');
        header.className = 'session-group-label' + (projectMode ? ' session-group-project' : '');
        if (group.hint) header.title = group.hint;

        if (projectMode) {
            // A collapsible, draggable project header. The default space has no
            // rename/delete actions (there is no record to edit) but still drags.
            header.draggable = true;
            header.dataset.spaceKey = group.key;
            const isDefault = group.key === DEFAULT_SPACE_KEY;
            const actions = isDefault ? '' : `
                <button class="session-group-action" title="${escapeHtml(t('project_rename'))}"
                        onclick="event.stopPropagation(); renameProject('${_wsAttr(group.key)}','${_wsAttr(group.label)}')">
                    <i class="fas fa-pen"></i>
                </button>
                <button class="session-group-action" title="${escapeHtml(t('project_delete'))}"
                        onclick="event.stopPropagation(); deleteProject('${_wsAttr(group.key)}','${_wsAttr(group.label)}')">
                    <i class="fas fa-trash-can"></i>
                </button>`;
            header.innerHTML = `
                <i class="fas fa-chevron-down session-group-caret ${collapsed ? 'collapsed' : ''}"></i>
                <i class="fas ${group.icon} session-group-icon"></i>
                <span class="session-group-name">${escapeHtml(group.label)}</span>
                <span class="session-group-count">${group.items.length}</span>
                <span class="session-group-actions">${actions}</span>`;
            header.addEventListener('click', () => _toggleProjectCollapse(group.key));
            _wireGroupDrag(header, group.key);
        } else if (group.icon) {
            header.innerHTML = `<i class="fas ${group.icon}"></i><span>${escapeHtml(group.label)}</span>`;
        } else {
            header.textContent = group.label;
        }
        container.appendChild(header);

        if (!collapsed) {
            group.items.forEach(s => container.appendChild(_sessionItemEl(s, indentItems)));
        }
    });
}

function _toggleProjectCollapse(key) {
    if (_collapsedProjects.has(key)) _collapsedProjects.delete(key);
    else _collapsedProjects.add(key);
    _saveCollapsed(_collapsedProjects);
    _renderSessionList();
}

// --- Project group drag-to-reorder -------------------------------------------
let _dragSpaceKey = null;

function _wireGroupDrag(header, key) {
    header.addEventListener('dragstart', (e) => {
        _dragSpaceKey = key;
        header.classList.add('dragging');
        try { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', key); } catch (err) {}
    });
    header.addEventListener('dragend', () => {
        _dragSpaceKey = null;
        header.classList.remove('dragging');
        document.querySelectorAll('.session-group-project.drop-target')
            .forEach(el => el.classList.remove('drop-target'));
    });
    header.addEventListener('dragover', (e) => {
        if (_dragSpaceKey === null || _dragSpaceKey === key) return;
        e.preventDefault();
        header.classList.add('drop-target');
    });
    header.addEventListener('dragleave', () => header.classList.remove('drop-target'));
    header.addEventListener('drop', (e) => {
        e.preventDefault();
        header.classList.remove('drop-target');
        if (_dragSpaceKey === null || _dragSpaceKey === key) return;
        _reorderSpace(_dragSpaceKey, key);
    });
}

// Move `fromKey` to sit just before `beforeKey`, then persist the new order.
function _reorderSpace(fromKey, beforeKey) {
    // Start from the currently displayed group order so dragging is stable even
    // when some spaces have no saved position yet.
    const current = _sessionGroups().map(g => g.key);
    const order = current.filter(k => k !== fromKey);
    const idx = order.indexOf(beforeKey);
    if (idx < 0) order.push(fromKey);
    else order.splice(idx, 0, fromKey);

    _projectOrder = order;
    _renderSessionList();

    fetch('/api/projects/order', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ order }),
    }).catch(() => {});
}

// Rename a project (display name only; the folder on disk is untouched).
function renameProject(path, currentName) {
    showPromptModal(t('project_rename_title'), currentName, (name) => {
        if (name === null) return;
        fetch('/api/projects/manage', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path, name }),
        })
            .then(r => r.json())
            .then(data => {
                if (data.status !== 'success') { _wsToast(data.message || t('session_settings_failed')); return; }
                loadSessionList();
            })
            .catch(() => _wsToast(t('session_settings_failed')));
    });
}

// Delete a project record. Only the CowAgent record is removed; files stay and
// bound sessions revert to the default workspace.
function deleteProject(path, name) {
    showConfirmModal(
        t('project_delete_title'),
        t('project_delete_confirm').replace('{name}', name || path),
        () => {
            fetch('/api/projects/manage', {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path }),
            })
                .then(r => r.json())
                .then(data => {
                    if (data.status !== 'success') { _wsToast(data.message || t('session_settings_failed')); return; }
                    loadSessionList();
                })
                .catch(() => _wsToast(t('session_settings_failed')));
        }
    );
}

function _sessionItemEl(s, indent) {
    const item = document.createElement('div');
    const ownerId = (s.agent && s.agent.id) || '';
    const isActive = s.session_id === sessionId && (!ownerId || ownerId === activeAgentId);
    item.className = 'session-item' + (isActive ? ' active' : '') + (s.pinned ? ' pinned' : '')
        + (indent ? ' session-item-indent' : '');
    item.dataset.sessionId = s.session_id;
    if (ownerId) item.dataset.agentId = ownerId;

    const title = s.title || t('untitled_session');
    const sid = _wsAttr(s.session_id);
    const owner = ownerId ? _wsAttr(ownerId) : '';
    // Faces mark a conversation that has several Agents in it, the way a group
    // chat is distinguishable from a direct one. A conversation with a single
    // Agent stays a plain row, whatever the roster looks like elsewhere. We show
    // at most three overlapping faces to keep the row tidy; when more took part,
    // a small "+N" caps the stack so the group's size is still legible.
    const roster = s.participants || [];
    const crowd = roster.length > 1 ? roster.slice(0, 3) : null;
    const overflow = roster.length - 3;
    const face = crowd
        ? `<span class="session-faces">${crowd.map(a => agentAvatarHTML(a, 20)).join('')}`
            + (overflow > 0 ? `<span class="session-face-more">+${overflow}</span>` : '')
            + `</span>`
        : `<i class="fas ${s.pinned ? 'fa-thumbtack' : 'fa-message'} session-icon"></i>`;
    item.innerHTML = `
        ${face}
        <span class="session-title" title="${escapeHtml(title)}">${escapeHtml(title)}</span>
        <button class="session-pin" onclick="event.stopPropagation(); toggleSessionPin('${sid}', '${owner}')"
                title="${escapeHtml(t(s.pinned ? 'unpin_session' : 'pin_session'))}">
            <i class="fas fa-thumbtack"></i>
        </button>
        <button class="session-rename" onclick="event.stopPropagation(); renameSession('${sid}')" title="${escapeHtml(t('rename_session'))}">
            <i class="fas fa-pen"></i>
        </button>
        <button class="session-delete" onclick="event.stopPropagation(); deleteSession('${sid}', '${owner}')" title="Delete">
            <i class="fas fa-trash-can"></i>
        </button>
    `;
    item.addEventListener('click', () => switchSession(s.session_id, ownerId || undefined));
    return item;
}

// Pin / unpin, then re-render so the conversation moves to its new place.
// Reorder loaded sessions to match the backend's ordering (pinned first, then
// most-recently-active), so an optimistic pin/unpin lands in the right place
// without waiting for a reload. Stable within each bucket.
function _sortSessionItems() {
    _sessionItems.sort((a, b) => {
        const pa = a.pinned ? 1 : 0;
        const pb = b.pinned ? 1 : 0;
        if (pa !== pb) return pb - pa;
        return (b.last_active || 0) - (a.last_active || 0);
    });
}

function toggleSessionPin(sid, agentId) {
    const entry = _sessionItems.find(s => s.session_id === sid && (!agentId || (s.agent && s.agent.id) === agentId));
    if (!entry) return;
    const pinned = !entry.pinned;

    // Move it optimistically: the reorder is the whole point of the click, and
    // the list is re-rendered from this same data anyway. Pinning must also
    // reorder `_sessionItems` — the group renderer relies on the array already
    // being pinned-first, so flipping only the flag would leave a just-pinned
    // chat sitting in place (especially inside a project group).
    entry.pinned = pinned ? 1 : 0;
    _sortSessionItems();
    _renderSessionList();

    const owner = agentId || (entry.agent && entry.agent.id) || activeAgentId;
    fetch(`/api/sessions/${encodeURIComponent(sid)}?agent_id=${encodeURIComponent(owner || '')}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pinned, agent_id: owner }),
    })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success') return;
            // Most often an empty brand-new chat: it has no row to pin until the
            // first message is stored.
            _wsToast(data.message || t('session_settings_failed'));
            entry.pinned = pinned ? 0 : 1;
            _sortSessionItems();
            _renderSessionList();
        })
        .catch(() => {
            entry.pinned = pinned ? 0 : 1;
            _sortSessionItems();
            _renderSessionList();
        });
}

function _onSessionListScroll() {
    if (!_sessionHasMore || _sessionLoading) return;
    const container = document.getElementById('session-list');
    if (!container) return;
    // Trigger when scrolled near the bottom (within 60px)
    if (container.scrollHeight - container.scrollTop - container.clientHeight < 60) {
        _fetchSessionPage(_sessionPage + 1, false);
    }
}

// Attach scroll listener once DOM is ready
(function _initSessionScroll() {
    const el = document.getElementById('session-list');
    if (el) {
        el.addEventListener('scroll', _onSessionListScroll);
    } else {
        document.addEventListener('DOMContentLoaded', () => {
            const el2 = document.getElementById('session-list');
            if (el2) el2.addEventListener('scroll', _onSessionListScroll);
        });
    }
})();

// Returning to a session whose reply is still streaming in the background.
// Close the background EventSource, rebuild the bubble from the buffered
// events (snapshot), then resume live streaming via a fresh connection that
// reads the remaining tail from the backend replay log. Returns true if a stream
// was re-attached. The user's own bubble is already in history (persisted
// eagerly), so it was rendered by loadHistory before this runs.
function _reattachStream(sid) {
    const key = runtimeSessionKey(sid);
    const requestId = sessionActiveRequest[key];
    if (!requestId) return false;
    const buffer = streamBuffers[requestId];
    if (!buffer) return false;

    // If the buffered stream already finished, the assistant reply is already
    // persisted and rendered by loadHistory — re-attaching would duplicate it.
    // Just clean up the buffer/cursor and rely on history.
    const finished = buffer.items.some(
        it => it.type === 'stream_end' || it.type === 'error' || it.type === 'resync_required'
    );
    if (finished) {
        const oldEs = activeStreams[requestId];
        if (oldEs) { try { oldEs.close(); } catch (_) {} delete activeStreams[requestId]; }
        delete streamBuffers[requestId];
        delete sessionActiveRequest[key];
        resetSendBtnSendMode();
        return false;
    }

    // done already exists in persistent history. Keep the background tail
    // connected for voice_attach/stream_end, but do not replay the answer into
    // the freshly loaded history view or it would create a duplicate bubble.
    if (buffer.items.some(it => it.type === 'done')) {
        resetSendBtnSendMode();
        return false;
    }

    // Stop the background connection before rebuilding. Each new connection
    // resumes independently from its last accepted sequence number.
    const oldEs = activeStreams[requestId];
    if (oldEs) { try { oldEs.close(); } catch (_) {} delete activeStreams[requestId]; }

    // Snapshot the buffered events into the replay, then start a fresh stream
    // that replays them and reconnects for the live tail.
    const replay = buffer.items.slice();
    startSSE(requestId, null, buffer.timestamp || new Date(), null, replay);
    return true;
}

function switchSession(newSessionId, agentId) {
    if (agentId && agentId !== activeAgentId) {
        activeAgentId = agentId;
        localStorage.setItem('cow_active_agent', activeAgentId);
    }
    if (newSessionId === sessionId) {
        if (currentView !== 'chat') navigateTo('chat');
        renderComposerIdentity();
        return;
    }

    // The preview panel is scoped to a session's workspace, so switching tears
    // down an open editor. Settle unsaved edits before committing to the switch.
    if (typeof wsGuardUnsaved === 'function'
        && !wsGuardUnsaved(() => switchSession(newSessionId))) return;

    // Do NOT close active streams here: sessions run in parallel, so any
    // in-flight reply for another session must keep streaming in the
    // background (it self-guards against rendering into the foreign view).
    // Switching back re-attaches and resumes live streaming.

    sessionId = newSessionId;
    updateEditButtonsState();
    localStorage.setItem(activeSessionStorageKey(), sessionId);
    refreshWorkspaceSelector();
    refreshSessionSettings();
    // Reflect the new session's context in the mini pie right away.
    if (typeof _ctxRefresh === 'function') { try { _ctxRefresh({}); } catch (_) {} }
    // Reset the file/preview panel so it reflects the new session's root.
    if (typeof wsOnSessionSwitch === 'function') wsOnSessionSwitch();

    historyPage = 0;
    historyHasMore = false;
    historyLoading = false;

    messagesDiv.innerHTML = '';
    loadHistory(1);
    startPolling();

    // Restore the send button to match this session's stream state, and if a
    // reply is still streaming in the background, re-attach to resume showing
    // it live (the user turn itself comes from history above).
    const pendingReq = sessionActiveRequest[runtimeSessionKey(sessionId)];
    if (pendingReq) {
        setSendBtnCancelMode(pendingReq);
        _reattachStream(sessionId);
    } else {
        resetSendBtnSendMode();
    }

    document.querySelectorAll('.session-item').forEach(el => {
        el.classList.toggle('active', el.dataset.sessionId === sessionId);
    });

    if (_isMobileView()) closeSessionPanel();
    if (currentView !== 'chat') navigateTo('chat');
    renderComposerIdentity();
}

// In-place rename a session title: replace the title <span> with an <input>,
// commit on Enter/blur, cancel on Escape. Persists via PUT /api/sessions/<id>.
function renameSession(sid) {
    const item = document.querySelector(`.session-item[data-session-id="${sid}"]`);
    if (!item) return;
    const titleEl = item.querySelector('.session-title');
    if (!titleEl || item.querySelector('.session-title-input')) return;

    const oldTitle = titleEl.textContent;

    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'session-title-input';
    input.value = oldTitle;
    input.maxLength = 100;

    // Avoid switching session while interacting with the input
    const stop = e => e.stopPropagation();
    input.addEventListener('click', stop);
    input.addEventListener('mousedown', stop);

    titleEl.replaceWith(input);
    input.focus();
    input.select();

    let done = false;

    const restore = (title) => {
        if (done) return;
        done = true;
        const span = document.createElement('span');
        span.className = 'session-title';
        span.title = title;
        span.textContent = title;
        input.replaceWith(span);
    };

    // Undo the optimistic rename in both the DOM and the cached entry.
    const revert = () => {
        const cachedEntry = _sessionItems.find(s => s.session_id === sid);
        if (cachedEntry) cachedEntry.title = oldTitle;
        const span = item.querySelector('.session-title');
        if (span) {
            span.title = oldTitle;
            span.textContent = oldTitle;
        }
    };

    const commit = () => {
        if (done) return;
        const newTitle = input.value.trim();
        if (!newTitle || newTitle === oldTitle) {
            restore(oldTitle);
            return;
        }
        // Optimistically show the new title, then persist. The cached entry is
        // updated too, or the next re-render (a pin, say) would revive the old one.
        restore(newTitle);
        const cached = _sessionItems.find(s => s.session_id === sid);
        if (cached) cached.title = newTitle;
        fetch(`/api/sessions/${encodeURIComponent(sid)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: newTitle })
        })
            .then(r => r.json())
            .then(data => {
                if (data.status !== 'success') revert();
            })
            .catch(revert);
    };

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); commit(); }
        else if (e.key === 'Escape') { e.preventDefault(); restore(oldTitle); }
    });
    input.addEventListener('blur', commit);
}

function deleteSession(sid, agentId) {
    showConfirmModal(t('delete_session_title'), t('delete_session_confirm'), () => {
        const owner = agentId || activeAgentId;
        const deletingCurrent = sid === sessionId && (!owner || owner === activeAgentId);
        const next = deletingCurrent ? _findNextSession(sid, owner) : null;

        fetch(`/api/sessions/${encodeURIComponent(sid)}?agent_id=${encodeURIComponent(owner || '')}`, { method: 'DELETE' })
            .then(r => r.json())
            .then(data => {
                if (data.status !== 'success') return;
                if (!deletingCurrent) {
                    loadSessionList();
                    return;
                }
                if (next) {
                    switchSession(next.sessionId, next.agentId);
                    loadSessionList();
                } else {
                    newChat(false);
                }
            })
            .catch(() => {});
    });
}

// Pick the session to show after deleting `sid` (the current session): prefer
// the next item below it in the list, otherwise the previous one. Returns null
// if no other session exists.
function _findNextSession(sid, agentId) {
    const items = Array.from(document.querySelectorAll('.session-item[data-session-id]'));
    const same = el => el.dataset.sessionId === sid && (!agentId || el.dataset.agentId === agentId);
    const idx = items.findIndex(same);
    const pick = el => el ? { sessionId: el.dataset.sessionId, agentId: el.dataset.agentId || '' } : null;
    if (idx === -1) {
        return pick(items.find(el => !same(el)));
    }
    return pick(items[idx + 1] || items[idx - 1]);
}

function showConfirmModal(title, message, onConfirm) {
    let overlay = document.getElementById('confirm-modal-overlay');
    if (overlay) overlay.remove();

    overlay = document.createElement('div');
    overlay.id = 'confirm-modal-overlay';
    overlay.className = 'confirm-overlay';

    const modal = document.createElement('div');
    modal.className = 'confirm-modal';
    modal.innerHTML = `
        <div class="confirm-title">${escapeHtml(title)}</div>
        <div class="confirm-message">${escapeHtml(message)}</div>
        <div class="confirm-actions">
            <button class="confirm-btn confirm-btn-cancel">${t('confirm_cancel')}</button>
            <button class="confirm-btn confirm-btn-ok">${t('confirm_yes')}</button>
        </div>
    `;
    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    requestAnimationFrame(() => overlay.classList.add('visible'));

    const close = () => {
        overlay.classList.remove('visible');
        setTimeout(() => overlay.remove(), 200);
    };

    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    modal.querySelector('.confirm-btn-cancel').addEventListener('click', close);
    modal.querySelector('.confirm-btn-ok').addEventListener('click', () => {
        close();
        onConfirm();
    });
}

// A confirm modal with a single text input. Calls onSubmit(value) on OK, and
// does nothing on cancel. Mirrors showConfirmModal's look and lifecycle.
function showPromptModal(title, initialValue, onSubmit) {
    let overlay = document.getElementById('confirm-modal-overlay');
    if (overlay) overlay.remove();

    overlay = document.createElement('div');
    overlay.id = 'confirm-modal-overlay';
    overlay.className = 'confirm-overlay';

    const modal = document.createElement('div');
    modal.className = 'confirm-modal';
    modal.innerHTML = `
        <div class="confirm-title">${escapeHtml(title)}</div>
        <input type="text" class="prompt-modal-input" maxlength="100" />
        <div class="confirm-actions">
            <button class="confirm-btn confirm-btn-cancel">${t('confirm_cancel')}</button>
            <button class="confirm-btn confirm-btn-ok">${t('confirm_yes')}</button>
        </div>
    `;
    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    const input = modal.querySelector('.prompt-modal-input');
    input.value = initialValue || '';
    requestAnimationFrame(() => { overlay.classList.add('visible'); input.focus(); input.select(); });

    const close = () => {
        overlay.classList.remove('visible');
        setTimeout(() => overlay.remove(), 200);
    };
    const submit = () => { const v = input.value.trim(); close(); onSubmit(v); };

    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    modal.querySelector('.confirm-btn-cancel').addEventListener('click', close);
    modal.querySelector('.confirm-btn-ok').addEventListener('click', submit);
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); submit(); }
        else if (e.key === 'Escape') { e.preventDefault(); close(); }
    });
}

function clearContext() {
    fetch(`/api/sessions/${encodeURIComponent(sessionId)}/clear_context`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.status !== 'success') return;
            // Insert a visual divider in the chat
            const divider = document.createElement('div');
            divider.className = 'context-divider';
            divider.innerHTML = `<span>${t('context_cleared')}</span>`;
            messagesDiv.appendChild(divider);
            scrollChatToBottom();
        })
        .catch(() => {});
}

function generateSessionTitle(sid, userMsg, assistantReply) {
    fetch(`/api/sessions/${encodeURIComponent(sid)}/generate_title`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_message: userMsg, assistant_reply: assistantReply }),
    })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'success' && sessionPanelOpen) {
                loadSessionList();
            }
        })
        .catch(() => {});
}

// =====================================================================
// Utilities
// =====================================================================
function formatTime(date) {
    const now = new Date();
    const sameDay = date.getFullYear() === now.getFullYear()
        && date.getMonth() === now.getMonth()
        && date.getDate() === now.getDate();
    const time = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (sameDay) return time;
    const m = String(date.getMonth() + 1).padStart(2, '0');
    const d = String(date.getDate()).padStart(2, '0');
    if (date.getFullYear() === now.getFullYear()) return `${m}-${d} ${time}`;
    return `${date.getFullYear()}-${m}-${d} ${time}`;
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

function ChannelsHandler_maskSecret(val) {
    if (!val || val.length <= 8) return val;
    return val.slice(0, 4) + '*'.repeat(val.length - 8) + val.slice(-4);
}

function formatToolArgs(args) {
    if (!args || Object.keys(args).length === 0) return '(none)';
    try {
        return escapeHtml(JSON.stringify(args, null, 2));
    } catch (_) {
        return escapeHtml(String(args));
    }
}

const SUBSTEP_ARGS_CHARS = 90;

/** Tool arguments on one line, for a step in a list of dozens. */
function summarizeToolArgs(args) {
    if (!args || typeof args !== 'object') return '';
    const parts = [];
    for (const [key, value] of Object.entries(args)) {
        const text = typeof value === 'object' ? JSON.stringify(value) : String(value);
        parts.push(`${key}=${text}`);
    }
    const joined = parts.join(', ');
    return joined.length > SUBSTEP_ARGS_CHARS
        ? joined.slice(0, SUBSTEP_ARGS_CHARS) + '…'
        : joined;
}

/**
 * Add or settle one step inside a sub agent's card.
 *
 * Silent when the card is gone: a sub agent cancelled on timeout keeps working
 * until its next checkpoint, and steps that arrive after its card closed
 * describe work nobody is waiting on any more.
 */
function renderSubagentStep(toolEl, item) {
    if (!toolEl || !item.step_id) return;
    const section = toolEl.querySelector('.tool-substeps-section');
    const list = toolEl.querySelector('.tool-substeps');
    if (!section || !list) return;

    let stepEl = list.querySelector(`[data-step-id="${CSS.escape(item.step_id)}"]`);
    if (!stepEl) {
        if (item.phase !== 'start') return;
        stepEl = document.createElement('div');
        stepEl.className = 'tool-substep';
        stepEl.dataset.stepId = item.step_id;
        stepEl.innerHTML = `
            <i class="fas fa-circle-notch fa-spin tool-substep-icon"></i>
            <span class="tool-substep-name">${escapeHtml(item.tool || 'tool')}</span>
            <span class="tool-substep-args">${escapeHtml(summarizeToolArgs(item.arguments))}</span>
            <span class="tool-substep-time"></span>`;
        list.appendChild(stepEl);
        section.classList.remove('hidden');
        // The first step is also the first sign of life from a sub agent that
        // runs for minutes, so it opens the card it belongs to.
        toolEl.classList.add('expanded');
        updateSubstepCount(toolEl, list.children.length);
        return;
    }

    if (item.phase !== 'end') return;
    const isError = item.status && item.status !== 'success';
    const icon = stepEl.querySelector('.tool-substep-icon');
    if (icon) {
        icon.className = isError
            ? 'fas fa-times tool-substep-icon tool-substep-failed'
            : 'fas fa-check tool-substep-icon';
    }
    const timeEl = stepEl.querySelector('.tool-substep-time');
    if (timeEl && item.execution_time) timeEl.textContent = `${item.execution_time}s`;
    if (item.error) {
        // A step that failed says so where it happened; the sub agent's report
        // covers what the successful ones found.
        const argsEl = stepEl.querySelector('.tool-substep-args');
        if (argsEl) {
            argsEl.textContent = String(item.error);
            argsEl.classList.add('tool-substep-failed');
        }
        stepEl.title = String(item.error);
    }
}

function updateSubstepCount(toolEl, count) {
    const countEl = toolEl.querySelector('.tool-substep-count');
    if (countEl) countEl.textContent = count === 1 ? '1 step' : `${count} steps`;
}

function scrollChatToBottom(force) {
    if (force || _autoScrollEnabled) {
        if (force) _autoScrollEnabled = true;
        const target = messagesDiv.scrollHeight;
        // Only flag a programmatic scroll when scrollTop will actually change
        // (i.e. a scroll event will fire). Otherwise the flag would go stale
        // and swallow the user's next real scroll-up gesture.
        if (Math.abs(messagesDiv.scrollTop - target) > 1) {
            _programmaticScroll = true;
        }
        messagesDiv.scrollTop = target;
        _lastScrollTop = messagesDiv.scrollTop;
    }
}

function _updateScrollToBottomBtn() {
    const btn = document.getElementById('scroll-to-bottom-btn');
    if (!btn) return;
    const distFromBottom = messagesDiv.scrollHeight - messagesDiv.scrollTop - messagesDiv.clientHeight;
    btn.classList.toggle('hidden', distFromBottom <= _SCROLL_THRESHOLD);
}

function applyHighlighting(container) {
    const root = container || document;
    setTimeout(() => {
        const hljsLib = getHljs();
        root.querySelectorAll('pre code').forEach(block => {
            if (!block.classList.contains('hljs')) {
                hljsLib.highlightElement(block);
            }
        });
        // Add language labels and copy buttons to code blocks
        _addCodeBlockHeaders(root);
    }, 0);
}

// =====================================================================
// Config View
// =====================================================================
let configProviders = {};
let configApiBases = {};
let configApiKeys = {};
let configCurrentModel = '';
let cfgProviderValue = '';
let cfgModelValue = '';
let cfgReasoningEffortValue = 'high';
let configReasoningByModel = {};
// Remembers the custom model name the user typed per provider, so switching
// away from a provider (which rebuilds its model dropdown) and back does not
// lose an unsaved custom model. Keyed by provider id.
let configCustomModelByProvider = {};
// Same idea for the Models tab capability cards: remember the custom model the
// user typed per (capability, provider) and the provider active before the
// last switch, so switching vendors and back restores the custom model.
// Keyed by `${capabilityId}:${providerId}` -> custom model string.
let capabilityCustomModelMemory = {};
// Keyed by capabilityId -> provider id active before the current switch.
let capabilityLastProviderId = {};

// --- Custom dropdown helper ---
function initDropdown(el, options, selectedValue, onChange, opts) {
    // opts.placeholder: when set AND selectedValue is empty, render that text
    // in a dim style instead of auto-selecting options[0]. Useful for
    // "pick or empty" capabilities (asr / embedding) where we want the
    // user to make an explicit choice.
    opts = opts || {};
    const textEl = el.querySelector('.cfg-dropdown-text');
    const menuEl = el.querySelector('.cfg-dropdown-menu');
    const selEl = el.querySelector('.cfg-dropdown-selected');
    // Optional avatar face in the trigger (opts.withAvatar). Each option then
    // carries an `agent` object so both the row and the trigger can paint it.
    const faceEl = el.querySelector('.cfg-dropdown-face');

    el._ddValue = selectedValue || '';
    el._ddOnChange = onChange;

    function paintFace(opt) {
        if (!faceEl) return;
        faceEl.innerHTML = (opt && opt.agent) ? agentAvatarHTML(opt.agent, 20) : '';
    }

    function render() {
        menuEl.innerHTML = '';
        options.forEach(opt => {
            const item = document.createElement('div');
            item.className = 'cfg-dropdown-item' + (opt.value === el._ddValue ? ' active' : '');
            item.dataset.value = opt.value;
            // Hint is an optional dim secondary label rendered on the right
            // side of the row (e.g. friendly brand name next to a technical
            // model id). When absent the row degrades to the original
            // single-string layout.
            if (opt.agent) {
                const face = document.createElement('span');
                face.className = 'cfg-dropdown-item-face';
                face.innerHTML = agentAvatarHTML(opt.agent, 20);
                const labelEl = document.createElement('span');
                labelEl.className = 'cfg-dropdown-label';
                labelEl.textContent = opt.label;
                item.appendChild(face);
                item.appendChild(labelEl);
                // Optional trailing pill (e.g. a "default" marker) rendered
                // dim after the name.
                if (opt.badge) {
                    const badgeEl = document.createElement('span');
                    badgeEl.className = 'cfg-dropdown-badge';
                    badgeEl.textContent = opt.badge;
                    item.appendChild(badgeEl);
                }
            } else if (opt.hint) {
                const labelEl = document.createElement('span');
                labelEl.className = 'cfg-dropdown-label';
                labelEl.textContent = opt.label;
                const hintEl = document.createElement('span');
                hintEl.className = 'cfg-dropdown-hint';
                hintEl.textContent = opt.hint;
                item.appendChild(labelEl);
                item.appendChild(hintEl);
            } else {
                item.textContent = opt.label;
            }
            item.addEventListener('click', (e) => {
                e.stopPropagation();
                el._ddValue = opt.value;
                textEl.textContent = opt.label;
                // Now that a real option is picked, drop the muted placeholder
                // style — otherwise the chosen label stays grey (visible on
                // dropdowns that start in a placeholder state, e.g. the chat
                // fallback pickers).
                textEl.classList.remove('text-slate-400', 'dark:text-slate-500');
                paintFace(opt);
                menuEl.querySelectorAll('.cfg-dropdown-item').forEach(i => i.classList.remove('active'));
                item.classList.add('active');
                el.classList.remove('open');
                if (el._ddOnChange) el._ddOnChange(opt.value);
            });
            menuEl.appendChild(item);
        });
        const sel = options.find(o => o.value === el._ddValue);
        if (sel) {
            textEl.textContent = sel.label;
            paintFace(sel);
            textEl.classList.remove('text-slate-400', 'dark:text-slate-500');
        } else if (opts.placeholder && !el._ddValue) {
            // No selection yet — show the placeholder in muted style.
            // Do NOT write a fallback value, so the dropdown stays
            // "unsaved" until the user explicitly picks.
            textEl.textContent = opts.placeholder;
            paintFace(null);
            textEl.classList.add('text-slate-400', 'dark:text-slate-500');
        } else {
            textEl.textContent = options[0] ? options[0].label : '--';
            paintFace(options[0]);
            textEl.classList.remove('text-slate-400', 'dark:text-slate-500');
            if (options[0]) el._ddValue = options[0].value;
        }
    }

    render();

    if (!el._ddBound) {
        selEl.addEventListener('click', (e) => {
            e.stopPropagation();
            document.querySelectorAll('.cfg-dropdown.open').forEach(d => { if (d !== el) d.classList.remove('open'); });
            const willOpen = !el.classList.contains('open');
            if (willOpen) {
                // Flip the menu above the control when it would otherwise be
                // clipped against the viewport bottom (e.g. the last channel's
                // config dropdown sitting near the window edge).
                const rect = el.getBoundingClientRect();
                const below = window.innerHeight - rect.bottom;
                const menuH = Math.min(menuEl.scrollHeight || 240, 280) + 8;
                el.classList.toggle('drop-up', below < menuH && rect.top > below);
            }
            el.classList.toggle('open');
        });
        el._ddBound = true;
    }
}

document.addEventListener('click', () => {
    document.querySelectorAll('.cfg-dropdown.open').forEach(d => d.classList.remove('open'));
});

function getDropdownValue(el) { return el._ddValue || ''; }

// --- Config init ---
function initConfigView(data) {
    configProviders = data.providers || {};
    configApiBases = data.api_bases || {};
    configApiKeys = data.api_keys || {};
    configCurrentModel = data.model || '';
    configReasoningByModel = data.reasoning_effort_by_model || {};
    cfgReasoningEffortValue = data.reasoning_effort || 'high';

    const providerEl = document.getElementById('cfg-provider');
    const providerOpts = Object.entries(configProviders).map(([pid, p]) => ({ value: pid, label: localizedLabel(p.label) }));

    // if use_linkai is enabled, always select linkai as the provider
    // Otherwise prefer bot_type from config, fall back to model-based detection
    const detected = data.use_linkai ? 'linkai'
        : (data.bot_type && configProviders[data.bot_type] ? data.bot_type : detectProvider(configCurrentModel));
    cfgProviderValue = detected || (providerOpts[0] ? providerOpts[0].value : '');

    initDropdown(providerEl, providerOpts, cfgProviderValue, onProviderChange);

    onProviderChange(cfgProviderValue);
    syncModelSelection(configCurrentModel);

    document.getElementById('cfg-max-tokens').value = data.agent_max_context_tokens ?? 64000;
    document.getElementById('cfg-max-turns').value = data.agent_max_context_turns || 20;
    document.getElementById('cfg-max-steps').value = data.agent_max_steps || 20;
    const thinkingEl = document.getElementById('cfg-enable-thinking');
    thinkingEl.checked = data.enable_thinking === true;
    if (!thinkingEl._cfgReasoningBound) {
        thinkingEl.addEventListener('change', syncReasoningEffortOptions);
        thinkingEl._cfgReasoningBound = true;
    }
    const customModelEl = document.getElementById('cfg-model-custom');
    if (customModelEl && !customModelEl._cfgReasoningBound) {
        customModelEl.addEventListener('input', () => {
            // Remember the typed custom model for the current provider so a
            // provider switch and switch-back doesn't lose it.
            if (cfgModelValue === '__custom__') {
                configCustomModelByProvider[cfgProviderValue] = customModelEl.value.trim();
            }
            syncReasoningEffortOptions();
        });
        customModelEl._cfgReasoningBound = true;
    }
    syncReasoningEffortOptions();
    document.getElementById('cfg-subagent').checked = data.subagent_enabled !== false;
    document.getElementById('cfg-self-evolution').checked = data.self_evolution_enabled === true;

    // Reflect the current UI language (already resolved, may include the user's
    // local choice) on the selector so it stays in sync with the top-right toggle.
    const langSel = document.getElementById('cfg-lang-select');
    if (langSel) {
        initDropdown(
            langSel,
            [{ value: 'zh', label: '简体中文' }, { value: 'zh-Hant', label: '繁體中文' }, { value: 'en', label: 'English' }],
            currentLang,
            (val) => setLanguage(val)
        );
    }

    // Default permission mode for new conversations. Applied on pick, like the
    // language selector: the card's save button belongs to the password field,
    // and a security default that silently waited for a save would be worse than
    // one that takes effect immediately.
    const permEl = document.getElementById('cfg-permission');
    if (permEl) {
        const offered = data.permission_modes && data.permission_modes.length
            ? data.permission_modes
            : Object.keys(PERMISSION_META);
        const permOpts = Object.keys(PERMISSION_META)
            .filter(mode => offered.includes(mode))
            .map(mode => ({ value: mode, label: t(PERMISSION_META[mode].key) }));
        initDropdown(permEl, permOpts, data.agent_permission_mode || 'full-access', saveGlobalPermission);
    }

    const pwdInput = document.getElementById('cfg-password');
    const maskedPwd = data.web_password_masked || '';
    pwdInput.value = maskedPwd;
    pwdInput.dataset.masked = maskedPwd ? '1' : '';
    pwdInput.dataset.maskedVal = maskedPwd;
    pwdInput.classList.toggle('cfg-key-masked', !!maskedPwd);

    if (maskedPwd) {
        pwdInput.placeholder = '••••••••';
    } else {
        pwdInput.placeholder = '';
    }

    if (!pwdInput._cfgBound) {
        pwdInput.addEventListener('focus', function() {
            if (this.dataset.masked === '1') {
                this.value = '';
                this.dataset.masked = '';
                this.classList.remove('cfg-key-masked');
            }
        });
        pwdInput.addEventListener('input', function() {
            this.dataset.masked = '';
        });
        pwdInput._cfgBound = true;
    }
}

function detectProvider(model) {
    if (!model) return Object.keys(configProviders)[0] || '';
    for (const [pid, p] of Object.entries(configProviders)) {
        if (pid === 'linkai') continue;
        if (p.models && p.models.includes(model)) return pid;
    }
    return Object.keys(configProviders)[0] || '';
}

function onProviderChange(pid) {
    cfgProviderValue = pid || getDropdownValue(document.getElementById('cfg-provider'));
    const p = configProviders[cfgProviderValue];
    if (!p) return;

    const customTip = document.getElementById('cfg-custom-tip');
    if (customTip) customTip.classList.toggle('hidden', cfgProviderValue !== 'custom');

    const modelEl = document.getElementById('cfg-model-select');
    const modelOpts = (p.models || []).map(m => ({ value: m, label: m }));
    modelOpts.push({ value: '__custom__', label: t('config_custom_option') });

    // Restore a custom model the user typed for this provider earlier in the
    // session (kept in configCustomModelByProvider). Fall back to the first
    // preset. For a custom provider with no preset models the picker only has
    // the "__custom__" entry, so a remembered value is the only way its model
    // survives a provider switch.
    const rememberedCustom = configCustomModelByProvider[cfgProviderValue];
    const initialModelValue = rememberedCustom
        ? '__custom__'
        : (modelOpts[0] ? modelOpts[0].value : '');

    initDropdown(modelEl, modelOpts, initialModelValue, onModelSelectChange);

    // API Key
    const keyField = p.api_key_field;
    const keyWrap = document.getElementById('cfg-api-key-wrap');
    const keyInput = document.getElementById('cfg-api-key');

    // Only LinkAI (an aggregation platform) gets a link to its console for
    // managing the aggregated key; other providers manage keys on their sites.
    const cfgManageKey = document.getElementById('cfg-manage-key');
    if (cfgManageKey) cfgManageKey.classList.toggle('hidden', cfgProviderValue !== 'linkai');
    if (keyField) {
        keyWrap.classList.remove('hidden');
        keyInput.classList.add('cfg-key-masked');
        const maskedVal = configApiKeys[keyField] || '';
        keyInput.value = maskedVal;
        keyInput.dataset.field = keyField;
        keyInput.dataset.masked = maskedVal ? '1' : '';
        keyInput.dataset.maskedVal = maskedVal;
        const toggleIcon = document.querySelector('#cfg-api-key-toggle i');
        if (toggleIcon) toggleIcon.className = 'fas fa-eye text-xs';

        if (!keyInput._cfgBound) {
            keyInput.addEventListener('focus', function() {
                if (this.dataset.masked === '1') {
                    this.value = '';
                    this.dataset.masked = '';
                    this.classList.remove('cfg-key-masked');
                }
            });
            keyInput.addEventListener('blur', function() {
                if (!this.value.trim() && this.dataset.maskedVal) {
                    this.value = this.dataset.maskedVal;
                    this.dataset.masked = '1';
                    this.classList.add('cfg-key-masked');
                }
            });
            keyInput.addEventListener('input', function() {
                this.dataset.masked = '';
            });
            keyInput._cfgBound = true;
        }
    } else {
        keyWrap.classList.add('hidden');
        keyInput.value = '';
        keyInput.dataset.field = '';
    }

    // API Base
    const apiBaseInput = document.getElementById('cfg-api-base');
    if (p.api_base_key) {
        document.getElementById('cfg-api-base-wrap').classList.remove('hidden');
        apiBaseInput.value = configApiBases[p.api_base_key] || p.api_base_default || '';
        // Hint the version-path tail (e.g. /v1) so users are reminded to
        // include it themselves. We don't auto-rewrite anything server-side.
        apiBaseInput.placeholder = p.api_base_placeholder || 'https://...';
    } else {
        document.getElementById('cfg-api-base-wrap').classList.add('hidden');
        apiBaseInput.value = '';
        apiBaseInput.placeholder = 'https://...';
    }

    onModelSelectChange(initialModelValue, { restoredCustom: rememberedCustom });
    syncReasoningEffortOptions();
}

function onModelSelectChange(val, opts) {
    opts = opts || {};
    cfgModelValue = val || getDropdownValue(document.getElementById('cfg-model-select'));
    const customWrap = document.getElementById('cfg-model-custom-wrap');
    const customInput = document.getElementById('cfg-model-custom');
    if (cfgModelValue === '__custom__') {
        customWrap.classList.remove('hidden');
        // When switching back to a provider we restore the remembered value;
        // otherwise this is a fresh pick of "custom" and we focus for input.
        if (opts.restoredCustom) {
            customInput.value = opts.restoredCustom;
        } else {
            customInput.focus();
        }
    } else {
        customWrap.classList.add('hidden');
        customInput.value = '';
    }
    syncReasoningEffortOptions();
}

function syncModelSelection(model) {
    const p = configProviders[cfgProviderValue];
    if (!p) return;

    const modelEl = document.getElementById('cfg-model-select');
    if (p.models && p.models.includes(model)) {
        const modelOpts = (p.models || []).map(m => ({ value: m, label: m }));
        modelOpts.push({ value: '__custom__', label: t('config_custom_option') });
        initDropdown(modelEl, modelOpts, model, onModelSelectChange);
        cfgModelValue = model;
        document.getElementById('cfg-model-custom-wrap').classList.add('hidden');
    } else {
        cfgModelValue = '__custom__';
        const modelOpts = (p.models || []).map(m => ({ value: m, label: m }));
        modelOpts.push({ value: '__custom__', label: t('config_custom_option') });
        initDropdown(modelEl, modelOpts, '__custom__', onModelSelectChange);
        document.getElementById('cfg-model-custom-wrap').classList.remove('hidden');
        document.getElementById('cfg-model-custom').value = model;
        // Seed the per-provider memory so switching away and back keeps it.
        if (model) configCustomModelByProvider[cfgProviderValue] = model;
    }
    syncReasoningEffortOptions();
}

function syncReasoningEffortOptions() {
    const wrap = document.getElementById('cfg-reasoning-effort-wrap');
    const el = document.getElementById('cfg-reasoning-effort');
    if (!wrap || !el) return;

    const provider = configProviders[cfgProviderValue] || {};
    const selectedModel = getSelectedModel();
    const reasoningByModel = provider.reasoning_by_model || {};
    const reasoning = reasoningByModel[selectedModel] || provider.reasoning || {};
    const options = reasoning.supported ? (reasoning.options || []) : [];
    const thinkingEl = document.getElementById('cfg-enable-thinking');

    if (options.length) {
        const values = options.map(opt => opt.value);
        // Prefer this model's own saved effort (per-model config) so switching
        // vendors never reinterprets a value set for a different model. Key is
        // the lowercased model name, matching the backend resolve path.
        const savedForModel = configReasoningByModel[`${cfgProviderValue}:${selectedModel.trim().toLowerCase()}`]
            || configReasoningByModel[cfgProviderValue + ':' + selectedModel];
        const saved = savedForModel || cfgReasoningEffortValue;
        // Fall back to the active model's native enum when the saved value is
        // not valid here. Resolved even while hidden so a save never writes
        // another model's enum under this model's key.
        cfgReasoningEffortValue = values.includes(saved) ? saved : (reasoning.default || options[0].value);
    }

    // Effort only shapes a thinking pass, so the field follows the toggle.
    if (!thinkingEl || !thinkingEl.checked || !options.length) {
        wrap.classList.add('hidden');
        return;
    }

    wrap.classList.remove('hidden');
    initDropdown(
        el,
        options.map(opt => ({ value: opt.value, label: opt.label || opt.value })),
        cfgReasoningEffortValue,
        (val) => { cfgReasoningEffortValue = val; }
    );
}

function getSelectedModel() {
    if (cfgModelValue === '__custom__') {
        return document.getElementById('cfg-model-custom').value.trim();
    }
    return cfgModelValue;
}

function toggleApiKeyVisibility() {
    const input = document.getElementById('cfg-api-key');
    const icon = document.querySelector('#cfg-api-key-toggle i');
    if (input.classList.contains('cfg-key-masked')) {
        input.classList.remove('cfg-key-masked');
        icon.className = 'fas fa-eye-slash text-xs';
    } else {
        input.classList.add('cfg-key-masked');
        icon.className = 'fas fa-eye text-xs';
    }
}

function showStatus(elId, msgKey, isError) {
    const el = document.getElementById(elId);
    el.textContent = t(msgKey);
    el.classList.toggle('text-red-500', !!isError);
    el.classList.toggle('text-primary-500', !isError);
    el.classList.remove('opacity-0');
    // Warning messages (errors) should stay visible, success messages auto-hide
    if (!isError) {
        setTimeout(() => el.classList.add('opacity-0'), 2500);
    }
}

function saveModelConfig() {
    const model = getSelectedModel();
    if (!model) return;

    const updates = { model: model };
    const p = configProviders[cfgProviderValue];
    updates.use_linkai = (cfgProviderValue === 'linkai');
    if (cfgProviderValue === 'linkai') {
        updates.bot_type = '';
    } else {
        updates.bot_type = cfgProviderValue;
    }
    if (p && p.api_base_key) {
        const base = document.getElementById('cfg-api-base').value.trim();
        if (base) updates[p.api_base_key] = base;
    }
    if (p && p.api_key_field) {
        const keyInput = document.getElementById('cfg-api-key');
        const rawVal = keyInput.value.trim();
        if (rawVal && keyInput.dataset.masked !== '1') {
            updates[p.api_key_field] = rawVal;
        }
    }

    const btn = document.getElementById('cfg-model-save');
    btn.disabled = true;
    fetch('/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ updates })
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'success') {
            configCurrentModel = model;
            if (data.applied) {
                const keyInput = document.getElementById('cfg-api-key');
                Object.entries(data.applied).forEach(([k, v]) => {
                    if (k === 'model') return;
                    if (k.includes('api_key')) {
                        const masked = v.length > 8
                            ? v.substring(0, 4) + '*'.repeat(v.length - 8) + v.substring(v.length - 4)
                            : v;
                        configApiKeys[k] = masked;
                        if (keyInput.dataset.field === k) {
                            keyInput.value = masked;
                            keyInput.dataset.masked = '1';
                            keyInput.dataset.maskedVal = masked;
                            keyInput.classList.add('cfg-key-masked');
                            const toggleIcon = document.querySelector('#cfg-api-key-toggle i');
                            if (toggleIcon) toggleIcon.className = 'fas fa-eye text-xs';
                        }
                    } else {
                        configApiBases[k] = v;
                    }
                });
            }
            showStatus('cfg-model-status', 'config_saved', false);
        } else {
            showStatus('cfg-model-status', 'config_save_error', true);
        }
    })
    .catch(() => showStatus('cfg-model-status', 'config_save_error', true))
    .finally(() => { btn.disabled = false; });
}

function saveAgentConfig() {
    const effortKey = `${cfgProviderValue}:${getSelectedModel().trim().toLowerCase()}`;
    const mergedEffortByModel = Object.assign({}, configReasoningByModel, { [effortKey]: cfgReasoningEffortValue });
    const updates = {
        agent_max_context_tokens: parseInt(document.getElementById('cfg-max-tokens').value) || 0,
        agent_max_context_turns: parseInt(document.getElementById('cfg-max-turns').value) || 20,
        agent_max_steps: parseInt(document.getElementById('cfg-max-steps').value) || 20,
        enable_thinking: document.getElementById('cfg-enable-thinking').checked,
        // Persist effort per model (merge with the existing map so other
        // models' saved efforts survive the flat config save).
        reasoning_effort_by_model: mergedEffortByModel,
        subagent_enabled: document.getElementById('cfg-subagent').checked,
        self_evolution_enabled: document.getElementById('cfg-self-evolution').checked,
    };

    const btn = document.getElementById('cfg-agent-save');
    btn.disabled = true;
    fetch('/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ updates })
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'success') {
            // Reflect the merged map so a later model switch shows/uses the
            // just-saved value instead of a stale in-memory one.
            configReasoningByModel = mergedEffortByModel;
            showStatus('cfg-agent-status', 'config_saved', false);
        } else {
            showStatus('cfg-agent-status', 'config_save_error', true);
        }
    })
    .catch(() => showStatus('cfg-agent-status', 'config_save_error', true))
    .finally(() => { btn.disabled = false; });
}

// Persist the instance-wide default permission mode. Sessions that never pinned
// their own follow it, so the composer chip is refreshed afterwards.
function saveGlobalPermission(mode) {
    fetch('/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ updates: { agent_permission_mode: mode } })
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'success') {
            showStatus('cfg-password-status', 'config_saved', false);
            refreshSessionSettings();
        } else {
            showStatus('cfg-password-status', 'config_save_error', true);
        }
    })
    .catch(() => showStatus('cfg-password-status', 'config_save_error', true));
}

function savePasswordConfig() {
    const input = document.getElementById('cfg-password');
    if (input.dataset.masked === '1') {
        showStatus('cfg-password-status', 'config_saved', false);
        return;
    }
    const newPwd = input.value.trim();
    const btn = document.getElementById('cfg-password-save');
    btn.disabled = true;
    fetch('/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ updates: { web_password: newPwd } })
    })
    .then(r => r.json())
    .then(data => {
        console.log('[Password Config] Response:', data); // Debug
        if (data.status === 'success') {
            if (newPwd) {
                showStatus('cfg-password-status', 'config_password_changed', false);
                // Mark as masked so user needs to re-enter to change again
                input.dataset.masked = '1';
                input.dataset.maskedVal = newPwd;
                input.value = '••••••••';
                input.classList.add('cfg-key-masked');
                
                // Show logout button since password is now enabled
                const logoutBtn = document.getElementById('logout-btn-header');
                if (logoutBtn) logoutBtn.classList.remove('hidden');
            } else {
                input.dataset.masked = '';
                input.dataset.maskedVal = '';
                input.classList.remove('cfg-key-masked');
                
                // Show security warning if password was cleared with public host
                if (data.warning === 'password_cleared_with_public_host') {
                    showStatus('cfg-password-status', 'config_password_security_warning', true);
                } else {
                    showStatus('cfg-password-status', 'config_password_cleared', false);
                }
                
                const logoutBtn = document.getElementById('logout-btn-header');
                if (logoutBtn) logoutBtn.classList.add('hidden');
            }
        } else {
            showStatus('cfg-password-status', 'config_save_error', true);
        }
    })
    .catch(() => showStatus('cfg-password-status', 'config_save_error', true))
    .finally(() => { btn.disabled = false; });
}

function loadConfigView() {
    fetch('/config').then(r => r.json()).then(data => {
        if (data.status !== 'success') return;
        appConfig = data;
        initConfigView(data);
    }).catch(() => {});
}

function switchConfigTab(tab) {
    ['basic', 'models'].forEach(name => {
        document.getElementById(`config-tab-${name}`)?.classList.toggle('active', name === tab);
        document.getElementById(`config-panel-${name}`)?.classList.toggle('hidden', name !== tab);
    });
    if (tab === 'models') loadModelsView();
    // Re-pull /config when returning to Basic: a provider added on the Models
    // tab must show up in the basic main-model provider picker without a manual
    // page refresh. loadConfigView re-renders from the fresh provider list.
    if (tab === 'basic') loadConfigView();
}

// =====================================================================
// Skills View
// =====================================================================
let toolsLoaded = false;

const TOOL_ICONS = {
    bash: 'fa-terminal',
    edit: 'fa-pen-to-square',
    read: 'fa-file-lines',
    write: 'fa-file-pen',
    ls: 'fa-folder-open',
    send: 'fa-paper-plane',
    web_search: 'fa-magnifying-glass',
    browser: 'fa-globe',
    env_config: 'fa-key',
    scheduler: 'fa-clock',
    memory_get: 'fa-brain',
    memory_search: 'fa-brain',
};

function getToolIcon(name) {
    return TOOL_ICONS[name] || 'fa-wrench';
}

function loadSkillsView() {
    bindSkillsConfigUi();
    loadToolsSection();
    loadMcpSection();
    loadSkillsSection();
}

let mcpServersCache = [];
let mcpEditorOriginalName = null;
let skillsConfigUiBound = false;

function bindSkillsConfigUi() {
    if (skillsConfigUiBound) return;
    skillsConfigUiBound = true;
    const addBtn = document.getElementById('mcp-add-btn');
    if (addBtn) addBtn.addEventListener('click', () => openMcpEditor());
    const typeSel = document.getElementById('mcp-field-type');
    if (typeSel) typeSel.addEventListener('change', syncMcpEditorTransport);
    const cancelBtn = document.getElementById('mcp-editor-cancel');
    if (cancelBtn) cancelBtn.addEventListener('click', closeMcpEditor);
    const overlay = document.getElementById('mcp-editor-overlay');
    if (overlay) overlay.addEventListener('click', (e) => { if (e.target === overlay) closeMcpEditor(); });
    const testBtn = document.getElementById('mcp-editor-test');
    if (testBtn) testBtn.addEventListener('click', testMcpEditor);
    const saveBtn = document.getElementById('mcp-editor-save');
    if (saveBtn) saveBtn.addEventListener('click', saveMcpEditor);
    const installBtn = document.getElementById('skill-install-btn');
    if (installBtn) installBtn.addEventListener('click', installSkillFromInput);
    const installInput = document.getElementById('skill-install-input');
    if (installInput) installInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); installSkillFromInput(); }
    });
}

function kvToObject(text) {
    const out = {};
    String(text || '').split(/\r?\n/).forEach((line) => {
        const trimmed = line.trim();
        if (!trimmed) return;
        const idx = trimmed.indexOf('=');
        if (idx <= 0) return;
        out[trimmed.slice(0, idx).trim()] = trimmed.slice(idx + 1);
    });
    return out;
}

function objectToKv(obj) {
    if (!obj || typeof obj !== 'object') return '';
    return Object.entries(obj).map(([k, v]) => `${k}=${v}`).join('\n');
}

function mcpStatusLabel(status) {
    const key = {
        ready: 'mcp_status_ready',
        pending: 'mcp_status_pending',
        failed: 'mcp_status_failed',
        needs_auth: 'mcp_status_needs_auth',
        disabled: 'mcp_status_disabled',
        idle: 'mcp_status_idle',
    }[status] || 'mcp_status_idle';
    return t(key);
}

function mcpStatusClass(status) {
    if (status === 'ready') return 'bg-emerald-50 text-emerald-600 dark:bg-emerald-900/20 dark:text-emerald-400';
    if (status === 'failed') return 'bg-red-50 text-red-600 dark:bg-red-900/20 dark:text-red-400';
    if (status === 'needs_auth') return 'bg-amber-50 text-amber-600 dark:bg-amber-900/20 dark:text-amber-400';
    if (status === 'disabled') return 'bg-slate-100 text-slate-500 dark:bg-white/10 dark:text-slate-400';
    return 'bg-blue-50 text-blue-600 dark:bg-blue-900/20 dark:text-blue-400';
}

function loadMcpSection() {
    const emptyEl = document.getElementById('mcp-empty');
    const listEl = document.getElementById('mcp-list');
    const badge = document.getElementById('mcp-count-badge');
    if (!listEl) return;
    fetch('/api/mcp/servers').then(r => r.json()).then(data => {
        if (data.status !== 'success') return;
        mcpServersCache = data.servers || [];
        if (badge) {
            badge.textContent = mcpServersCache.length;
            badge.classList.toggle('hidden', mcpServersCache.length === 0);
        }
        if (!mcpServersCache.length) {
            if (emptyEl) emptyEl.classList.remove('hidden');
            listEl.classList.add('hidden');
            listEl.innerHTML = '';
            return;
        }
        if (emptyEl) emptyEl.classList.add('hidden');
        listEl.innerHTML = '';
        mcpServersCache.forEach((server) => listEl.appendChild(renderMcpCard(server)));
        listEl.classList.remove('hidden');
    }).catch(() => {
        if (emptyEl) {
            emptyEl.classList.remove('hidden');
            emptyEl.innerHTML = `<span class="text-sm text-slate-400 dark:text-slate-500">${t('mcp_save_error')}</span>`;
        }
    });
}

function renderMcpCard(server) {
    const card = document.createElement('div');
    card.className = 'bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10 p-4 flex items-start gap-3';
    const summary = server.type === 'stdio'
        ? [server.command, ...(server.args || [])].filter(Boolean).join(' ')
        : (server.url || server.type);
    card.innerHTML = `
        <div class="w-9 h-9 rounded-lg bg-primary-50 dark:bg-primary-900/20 flex items-center justify-center flex-shrink-0">
            <i class="fas fa-plug text-primary-500 text-sm"></i>
        </div>
        <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 mb-1">
                <span class="font-medium text-sm text-slate-700 dark:text-slate-200 truncate flex-1 font-mono">${escapeHtml(server.name)}</span>
                <span class="px-1.5 py-0.5 rounded-full text-[10px] ${mcpStatusClass(server.status)}">${escapeHtml(mcpStatusLabel(server.status))}</span>
                <button type="button" data-mcp-edit class="p-1 rounded text-slate-300 hover:text-slate-500"><i class="fas fa-pen text-[10px]"></i></button>
                <button type="button" data-mcp-delete class="p-1 rounded text-slate-300 hover:text-red-500"><i class="fas fa-trash text-[10px]"></i></button>
            </div>
            <p class="text-xs text-slate-400 dark:text-slate-500 truncate">${escapeHtml(summary || server.type)}</p>
        </div>`;
    card.querySelector('[data-mcp-edit]').onclick = () => openMcpEditor(server);
    card.querySelector('[data-mcp-delete]').onclick = () => deleteMcpServer(server.name);
    return card;
}

function syncMcpEditorTransport() {
    const type = document.getElementById('mcp-field-type').value;
    const stdio = type === 'stdio';
    document.getElementById('mcp-stdio-fields').classList.toggle('hidden', !stdio);
    document.getElementById('mcp-url-fields').classList.toggle('hidden', stdio);
}

function fillMcpEditor(server) {
    const s = server || {};
    document.getElementById('mcp-field-name').value = s.name || '';
    document.getElementById('mcp-field-name').disabled = !!s.name;
    document.getElementById('mcp-field-type').value = s.type || (s.url ? 'sse' : 'stdio');
    document.getElementById('mcp-field-command').value = s.command || '';
    document.getElementById('mcp-field-args').value = (s.args || []).join('\n');
    document.getElementById('mcp-field-env').value = objectToKv(s.env);
    document.getElementById('mcp-field-url').value = s.url || '';
    document.getElementById('mcp-field-headers').value = objectToKv(s.headers);
    document.getElementById('mcp-field-scope').value = s.scope || '';
    document.getElementById('mcp-field-prefix').value = s.tool_name_prefix || '';
    document.getElementById('mcp-field-timeout').value = s.timeout || '';
    document.getElementById('mcp-field-disabled').checked = !!s.disabled;
    const result = document.getElementById('mcp-test-result');
    result.classList.add('hidden');
    result.textContent = '';
    document.getElementById('mcp-editor-title').textContent = s.name ? t('mcp_edit') : t('mcp_add');
    syncMcpEditorTransport();
}

function readMcpEditor() {
    const type = document.getElementById('mcp-field-type').value;
    const cfg = {
        name: document.getElementById('mcp-field-name').value.trim(),
        type,
        tool_name_prefix: document.getElementById('mcp-field-prefix').value,
        disabled: document.getElementById('mcp-field-disabled').checked,
    };
    const timeout = document.getElementById('mcp-field-timeout').value.trim();
    if (timeout) cfg.timeout = Number(timeout);
    if (type === 'stdio') {
        cfg.command = document.getElementById('mcp-field-command').value.trim();
        cfg.args = document.getElementById('mcp-field-args').value.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
        cfg.env = kvToObject(document.getElementById('mcp-field-env').value);
    } else {
        cfg.url = document.getElementById('mcp-field-url').value.trim();
        cfg.headers = kvToObject(document.getElementById('mcp-field-headers').value);
        cfg.scope = document.getElementById('mcp-field-scope').value.trim();
    }
    return cfg;
}

function openMcpEditor(server) {
    mcpEditorOriginalName = server ? server.name : null;
    fillMcpEditor(server);
    document.getElementById('mcp-editor-overlay').classList.remove('hidden');
}

function closeMcpEditor() {
    document.getElementById('mcp-editor-overlay').classList.add('hidden');
    mcpEditorOriginalName = null;
}

async function persistMcpServers(servers) {
    const res = await fetch('/api/mcp/servers', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ servers }),
    });
    const data = await res.json();
    if (data.status !== 'success') throw new Error(data.message || t('mcp_save_error'));
    mcpServersCache = data.servers || servers;
    loadMcpSection();
    return data;
}

async function saveMcpEditor() {
    try {
        const cfg = readMcpEditor();
        const next = mcpServersCache.filter(s => s.name !== mcpEditorOriginalName && s.name !== cfg.name);
        next.push(cfg);
        await persistMcpServers(next);
        closeMcpEditor();
    } catch (err) {
        const result = document.getElementById('mcp-test-result');
        result.classList.remove('hidden');
        result.textContent = err.message || t('mcp_save_error');
    }
}

async function testMcpEditor() {
    const result = document.getElementById('mcp-test-result');
    result.classList.remove('hidden');
    result.textContent = t('mcp_test') + '...';
    try {
        const res = await fetch('/api/mcp/servers/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ server: readMcpEditor() }),
        });
        const data = await res.json();
        if (data.ok) {
            const names = (data.tools || []).map(x => x.name).filter(Boolean);
            result.textContent = t('mcp_test_ok') + (names.length ? (': ' + names.join(', ')) : '');
        } else {
            result.textContent = t('mcp_test_fail') + ': ' + (data.error || data.message || '');
        }
    } catch (err) {
        result.textContent = t('mcp_test_fail') + ': ' + (err.message || '');
    }
}

function deleteMcpServer(name) {
    showConfirmDialog({
        title: t('mcp_delete'),
        message: t('mcp_delete_confirm'),
        okText: t('mcp_delete'),
        onConfirm: async () => {
            try {
                await persistMcpServers(mcpServersCache.filter(s => s.name !== name));
            } catch (err) {
                alert(err.message || t('mcp_save_error'));
            }
        },
    });
}

async function installSkillFromInput() {
    const input = document.getElementById('skill-install-input');
    const spec = (input && input.value || '').trim();
    if (!spec) return;
    const btn = document.getElementById('skill-install-btn');
    if (btn) btn.disabled = true;
    try {
        const res = await fetch('/api/skills', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'install', spec }),
        });
        const data = await res.json();
        if (data.status !== 'success') throw new Error(data.message || t('skill_install_error'));
        if (input) input.value = '';
        loadSkillsSection();
    } catch (err) {
        alert(err.message || t('skill_install_error'));
    } finally {
        if (btn) btn.disabled = false;
    }
}

function deleteSkill(name) {
    showConfirmDialog({
        title: t('skill_delete'),
        message: t('skill_delete_confirm'),
        okText: t('skill_delete'),
        onConfirm: async () => {
            try {
                const res = await fetch('/api/skills', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action: 'delete', name }),
                });
                const data = await res.json();
                if (data.status !== 'success') throw new Error(data.message || t('skill_delete_error'));
                loadSkillsSection();
            } catch (err) {
                alert(err.message || t('skill_delete_error'));
            }
        },
    });
}

function loadToolsSection() {
    if (toolsLoaded) return;
    const emptyEl = document.getElementById('tools-empty');
    const listEl = document.getElementById('tools-list');
    const badge = document.getElementById('tools-count-badge');

    fetch('/api/tools').then(r => r.json()).then(data => {
        if (data.status !== 'success') return;
        const tools = data.tools || [];
        emptyEl.classList.add('hidden');
        if (tools.length === 0) {
            emptyEl.classList.remove('hidden');
            emptyEl.innerHTML = `<span class="text-sm text-slate-400 dark:text-slate-500">${currentLang === 'zh' ? '暂无内置工具' : 'No built-in tools'}</span>`;
            return;
        }
        badge.textContent = tools.length;
        badge.classList.remove('hidden');
        listEl.innerHTML = '';
        tools.forEach(tool => {
            const card = document.createElement('div');
            card.className = 'bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10 p-4 flex items-start gap-3';
            card.innerHTML = `
                <div class="w-9 h-9 rounded-lg bg-blue-50 dark:bg-blue-900/20 flex items-center justify-center flex-shrink-0">
                    <i class="fas ${getToolIcon(tool.name)} text-blue-500 dark:text-blue-400 text-sm"></i>
                </div>
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2">
                        <span class="font-medium text-sm text-slate-700 dark:text-slate-200 font-mono">${escapeHtml(tool.name)}</span>
                    </div>
                    <p class="text-xs text-slate-400 dark:text-slate-500 mt-1 line-clamp-2">${escapeHtml(tool.description || '--')}</p>
                </div>`;
            listEl.appendChild(card);
        });
        listEl.classList.remove('hidden');
        toolsLoaded = true;
    }).catch(() => {
        emptyEl.classList.remove('hidden');
        emptyEl.innerHTML = `<span class="text-sm text-slate-400 dark:text-slate-500">${currentLang === 'zh' ? '加载失败' : 'Failed to load'}</span>`;
    });
}

function loadSkillsSection() {
    const emptyEl = document.getElementById('skills-empty');
    const listEl = document.getElementById('skills-list');
    const badge = document.getElementById('skills-count-badge');

    fetch('/api/skills').then(r => r.json()).then(data => {
        if (data.status !== 'success') return;
        const skills = data.skills || [];
        if (skills.length === 0) {
            const p = emptyEl.querySelector('p');
            if (p) p.textContent = currentLang === 'zh' ? '暂无技能' : 'No skills found';
            return;
        }
        badge.textContent = skills.length;
        badge.classList.remove('hidden');
        emptyEl.classList.add('hidden');
        listEl.innerHTML = '';

        skills.forEach(sk => {
            const card = document.createElement('div');
            card.className = 'bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10 '
                + 'p-4 flex items-start gap-3 transition-opacity cursor-pointer '
                + 'hover:border-slate-300 dark:hover:border-white/20';
            card.dataset.skillName = sk.name;
            card.dataset.skillDesc = sk.description || '';
            card.dataset.skillDisplayName = sk.display_name || '';
            card.dataset.enabled = sk.enabled ? '1' : '0';
            card.dataset.deletable = sk.deletable ? '1' : '0';
            renderSkillCard(card, sk);
            listEl.appendChild(card);
        });
    }).catch(() => {});
}

function renderSkillCard(card, sk) {
    const enabled = sk.enabled;
    const iconColor = enabled ? 'text-primary-400' : 'text-slate-300 dark:text-slate-600';
    const trackClass = enabled
        ? 'bg-primary-400'
        : 'bg-slate-200 dark:bg-slate-700';
    const thumbTranslate = enabled ? 'translate-x-3' : 'translate-x-0.5';
    card.innerHTML = `
        <div class="w-9 h-9 rounded-lg bg-amber-50 dark:bg-amber-900/20 flex items-center justify-center flex-shrink-0">
            <i class="fas fa-bolt ${iconColor} text-sm"></i>
        </div>
        <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 mb-1">
                <span class="font-medium text-sm text-slate-700 dark:text-slate-200 truncate flex-1">${escapeHtml(sk.display_name || sk.name)}</span>
                <button
                    data-skill-edit
                    class="flex-shrink-0 p-1 -mx-1 -mt-1.5 -mb-1 rounded text-slate-300 dark:text-slate-600 hover:text-slate-500 dark:hover:text-slate-300 transition-colors"
                    title="${t('skill_edit_hint')}"
                >
                    <i class="fas fa-pen text-[10px]"></i>
                </button>
                ${sk.deletable ? `<button data-skill-delete class="flex-shrink-0 p-1 -mx-1 -mt-1.5 -mb-1 rounded text-slate-300 dark:text-slate-600 hover:text-red-500 transition-colors" title="${t('skill_delete')}"><i class="fas fa-trash text-[10px]"></i></button>` : ''}
                <button
                    role="switch"
                    data-skill-switch
                    aria-checked="${enabled}"
                    class="relative inline-flex h-4 w-7 flex-shrink-0 cursor-pointer rounded-full transition-colors duration-200 ease-in-out focus:outline-none ${trackClass}"
                    title="${enabled ? (currentLang === 'zh' ? '点击禁用' : 'Click to disable') : (currentLang === 'zh' ? '点击启用' : 'Click to enable')}"
                >
                    <span class="inline-block h-3 w-3 mt-0.5 rounded-full bg-white shadow transform transition-transform duration-200 ease-in-out ${thumbTranslate}"></span>
                </button>
            </div>
            <p class="text-xs text-slate-400 dark:text-slate-500 line-clamp-2">${escapeHtml(sk.description || '--')}</p>
        </div>`;

    // Bound here rather than written into the markup above: a skill name comes
    // from its own frontmatter, and one containing a quote would break out of
    // an inline onclick attribute.
    card.title = t('skill_open_hint');
    card.onclick = () => openSkillFile(sk.name);
    const editBtn = card.querySelector('[data-skill-edit]');
    if (editBtn) {
        editBtn.onclick = (e) => {
            e.stopPropagation();
            openSkillFile(sk.name, { edit: true });
        };
    }
    const sw = card.querySelector('[data-skill-switch]');
    if (sw) {
        sw.onclick = (e) => {
            e.stopPropagation();
            toggleSkill(sk.name, enabled);
        };
    }
    const delBtn = card.querySelector('[data-skill-delete]');
    if (delBtn) {
        delBtn.onclick = (e) => {
            e.stopPropagation();
            deleteSkill(sk.name);
        };
    }
}

function toggleSkill(name, currentlyEnabled) {
    const action = currentlyEnabled ? 'close' : 'open';
    const card = document.querySelector(`[data-skill-name="${CSS.escape(name)}"]`);
    if (card) card.style.opacity = '0.5';

    fetch('/api/skills', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, name })
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'success') {
            if (card) {
                card.dataset.enabled = currentlyEnabled ? '0' : '1';
                card.style.opacity = '1';
                renderSkillCard(card, {
                    name: name,
                    description: card.dataset.skillDesc || '',
                    display_name: card.dataset.skillDisplayName || '',
                    enabled: !currentlyEnabled,
                    deletable: card.dataset.deletable === '1',
                });
            }
        } else {
            if (card) card.style.opacity = '1';
            alert(currentLang === 'zh' ? '操作失败，请稍后再试' : 'Operation failed, please try again');
        }
    })
    .catch(() => {
        if (card) card.style.opacity = '1';
        alert(currentLang === 'zh' ? '操作失败，请稍后再试' : 'Operation failed, please try again');
    });
}

// ---------------------------------------------------------------------
// Skill viewer / editor
// ---------------------------------------------------------------------

/**
 * Skills are addressed by name, not by path: which file a name resolves to is
 * the loader's business, and a builtin skill lives outside the workspace that
 * the file APIs are confined to.
 */
async function skillReadContent(name) {
    const res = await fetch(`/api/skills/content?name=${encodeURIComponent(name)}`);
    const data = await res.json();
    if (data.status !== 'success') throw new Error(data.message || 'read failed');
    return data;
}

/** Save a skill's definition. Returns the raw response, a conflict included. */
async function skillWriteContent(name, content, expectedMtime) {
    const res = await fetch('/api/skills/content', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name, content: content, expected_mtime: expectedMtime }),
    });
    return res.json();
}

/** The i18n key explaining why a skill cannot be edited, or null if it can. */
function skillReadonlyReason(data) {
    if (data.editable) return null;
    // Not `source === 'builtin'`: the workspace copy of a builtin skill reads
    // back as `custom` and is refused all the same, so the server says so.
    if (data.ships_with_install) return 'skill_builtin_readonly';
    return docUneditableReason(data);
}

/**
 * Split a skill's SKILL.md into its YAML frontmatter fields and the markdown
 * body. The `---` header is metadata, not prose: fed to the markdown renderer
 * as-is it turns into a giant bold heading and a horizontal rule. Pull it out
 * so the viewer can present name/description as a proper header instead.
 *
 * @returns {{fields: Array<[string, string]>, body: string}}
 */
function parseSkillFrontmatter(content) {
    const text = content || '';
    const match = text.match(/^---\s*\r?\n([\s\S]*?)\r?\n---\s*\r?\n?/);
    if (!match) return { fields: [], body: text };

    const fields = [];
    for (const raw of match[1].split(/\r?\n/)) {
        const line = raw.trim();
        if (!line || line.startsWith('#')) continue;
        const idx = line.indexOf(':');
        if (idx === -1) continue;
        const key = line.slice(0, idx).trim();
        let value = line.slice(idx + 1).trim();
        // Drop surrounding quotes a YAML scalar may carry.
        value = value.replace(/^['"]|['"]$/g, '');
        if (key) fields.push([key, value]);
    }
    return { fields, body: text.slice(match[0].length) };
}

/**
 * Render a skill's content into the viewer: the frontmatter as a titled header,
 * the remainder as markdown.
 */
function skillRenderBody(content) {
    const el = document.getElementById('skill-viewer-content');
    if (!el) return;
    const { fields, body } = parseSkillFrontmatter(content);

    let headerHtml = '';
    if (fields.length) {
        const rows = fields.map(([key, value]) => `
            <div class="flex gap-3 text-sm">
                <span class="flex-shrink-0 w-24 font-medium text-slate-400 dark:text-slate-500">${escapeHtml(key)}</span>
                <span class="flex-1 min-w-0 text-slate-700 dark:text-slate-200 break-words">${escapeHtml(value)}</span>
            </div>`).join('');
        headerHtml = `
            <div class="mb-5 pb-5 border-b border-slate-100 dark:border-white/10 space-y-2">
                ${rows}
            </div>`;
    }

    el.innerHTML = headerHtml + `<div class="msg-content">${renderMarkdown(body || '')}</div>`;
    applyHighlighting(el);
}

const skillEditor = createDocEditor({
    body: () => document.getElementById('skill-viewer-content'),
    buttons: () => ({
        edit: document.getElementById('skill-btn-edit'),
        save: document.getElementById('skill-btn-save'),
        cancel: document.getElementById('skill-btn-cancel'),
    }),
    read: (doc) => skillReadContent(doc.name),
    write: (doc, content, mtime) => skillWriteContent(doc.name, content, mtime),
    render: (doc) => skillRenderBody(doc.content),
    canEdit: (doc) => !doc.readonlyKey,
    refusal: skillReadonlyReason,
    onState: (state) => docRenderTitle('skill-viewer-title', skillEditor.current()?.name, state),
});

function openSkillFile(name, opts) {
    const startEditing = !!(opts && opts.edit);
    skillReadContent(name).then(data => {
        const badge = document.getElementById('skill-viewer-readonly');
        const readonlyKey = skillReadonlyReason(data);
        if (badge) {
            badge.classList.toggle('hidden', !readonlyKey);
            if (readonlyKey) {
                // Keep data-i18n in step so a language switch re-translates it.
                badge.dataset.i18n = readonlyKey;
                badge.textContent = t(readonlyKey);
                badge.title = t(readonlyKey);
            }
        }
        document.getElementById('skills-panel-list').classList.add('hidden');
        document.getElementById('skills-panel-viewer').classList.remove('hidden');
        skillEditor.open({
            name: data.name || name,
            content: data.content || '',
            readonlyKey: readonlyKey,
        });
        // The pencil on a card jumps straight into editing, skipping the
        // read-only view - but only where the skill is actually editable.
        if (startEditing && !readonlyKey) skillEditor.start();
    }).catch(e => _wsToast(`${t('skill_load_failed')}: ${e.message}`));
}

function closeSkillViewer() {
    if (!skillEditor.guard(closeSkillViewer)) return;
    resetSkillViewer();
    // A saved edit can change the name and description in the frontmatter, so
    // the cards behind this panel may be out of date.
    loadSkillsSection();
}

/** Drop the viewer and show the list, without asking about unsaved edits. */
function resetSkillViewer() {
    skillEditor.forget();
    document.getElementById('skills-panel-viewer')?.classList.add('hidden');
    document.getElementById('skills-panel-list')?.classList.remove('hidden');
}

// =====================================================================
// Memory View
// =====================================================================
let memoryPage = 1;
let memoryCategory = 'memory';   // 'memory' | 'evolution'
const memoryPageSize = 10;

function switchMemoryTab(tab) {
    document.querySelectorAll('.memory-tab').forEach(el => el.classList.remove('active'));
    document.getElementById('memory-tab-' + tab).classList.add('active');
    // The "dreams" tab now surfaces self-evolution logs (merged with dream diaries).
    memoryCategory = tab === 'dreams' ? 'evolution' : 'memory';
    loadMemoryView(1);
}

function loadMemoryView(page) {
    page = page || 1;
    memoryPage = page;
    const agent = viewingMemoryAgentId();
    fetch(`/api/memory?page=${page}&page_size=${memoryPageSize}&category=${memoryCategory}&agent_id=${encodeURIComponent(agent || '')}`).then(r => r.json()).then(data => {
        if (data.status !== 'success') return;
        const emptyEl = document.getElementById('memory-empty');
        const listEl = document.getElementById('memory-list');
        const files = data.list || [];
        const total = data.total || 0;

        if (total === 0) {
            const emptyIcon = emptyEl.querySelector('i');
            const emptyTitle = emptyEl.querySelector('p');
            if (memoryCategory === 'evolution') {
                emptyIcon.className = 'fas fa-seedling text-emerald-400 text-xl';
                emptyTitle.textContent = currentLang === 'zh' ? '暂无进化记录' : 'No evolution records yet';
            } else {
                emptyIcon.className = 'fas fa-brain text-purple-400 text-xl';
                emptyTitle.textContent = currentLang === 'zh' ? '暂无记忆文件' : 'No memory files';
            }
            emptyEl.classList.remove('hidden');
            listEl.classList.add('hidden');
            return;
        }
        emptyEl.classList.add('hidden');
        listEl.classList.remove('hidden');

        const tbody = document.getElementById('memory-table-body');
        tbody.innerHTML = '';
        files.forEach(f => {
            const tr = document.createElement('tr');
            tr.className = 'border-b border-slate-100 dark:border-white/5 hover:bg-slate-50 dark:hover:bg-white/5 cursor-pointer transition-colors';
            // In the merged evolution tab, resolve each file by its own origin
            // (evolution logs vs dream diaries live in different dirs).
            const fileCategory = (f.type === 'dream' || f.type === 'evolution') ? f.type : memoryCategory;
            tr.onclick = () => openMemoryFile(f.filename, fileCategory);
            let typeLabel;
            if (f.type === 'global') {
                typeLabel = '<span class="px-2 py-0.5 rounded-full text-xs bg-primary-50 dark:bg-primary-900/30 text-primary-600 dark:text-primary-400">Global</span>';
            } else if (f.type === 'evolution') {
                typeLabel = '<span class="px-2 py-0.5 rounded-full text-xs bg-emerald-50 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400">Evolution</span>';
            } else if (f.type === 'dream') {
                typeLabel = '<span class="px-2 py-0.5 rounded-full text-xs bg-violet-50 dark:bg-violet-900/30 text-violet-600 dark:text-violet-400">Dream</span>';
            } else {
                typeLabel = '<span class="px-2 py-0.5 rounded-full text-xs bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400">Daily</span>';
            }
            const sizeStr = f.size < 1024 ? f.size + ' B' : (f.size / 1024).toFixed(1) + ' KB';
            tr.innerHTML = `
                <td class="px-4 py-3 text-sm font-mono text-slate-700 dark:text-slate-200">${escapeHtml(f.filename)}</td>
                <td class="px-4 py-3 text-sm">${typeLabel}</td>
                <td class="px-4 py-3 text-sm text-slate-500 dark:text-slate-400">${sizeStr}</td>
                <td class="px-4 py-3 text-sm text-slate-500 dark:text-slate-400">${escapeHtml(f.updated_at)}</td>`;
            tbody.appendChild(tr);
        });

        // Pagination
        const totalPages = Math.ceil(total / memoryPageSize);
        const pagEl = document.getElementById('memory-pagination');
        if (totalPages <= 1) { pagEl.innerHTML = ''; return; }
        let pagHtml = `<span>${page} / ${totalPages}</span><div class="flex gap-2">`;
        if (page > 1) pagHtml += `<button onclick="loadMemoryView(${page - 1})" class="px-3 py-1 rounded-lg border border-slate-200 dark:border-white/10 hover:bg-slate-100 dark:hover:bg-white/10 text-xs">Prev</button>`;
        if (page < totalPages) pagHtml += `<button onclick="loadMemoryView(${page + 1})" class="px-3 py-1 rounded-lg border border-slate-200 dark:border-white/10 hover:bg-slate-100 dark:hover:bg-white/10 text-xs">Next</button>`;
        pagHtml += '</div>';
        pagEl.innerHTML = pagHtml;
    }).catch(() => {});
}

// =====================================================================
// Document viewers (memory files, skill definitions)
// =====================================================================

/**
 * Read one file's text for an editor. Throws on an API error so the editor can
 * report it.
 *
 * No session is passed on purpose. Memory files are anchored to the agent's
 * state root, and a session with a project open would resolve the same relative
 * path against that project instead.
 */
async function docReadFile(relPath) {
    const res = await fetch(`/api/workspace/read?path=${encodeURIComponent(relPath)}`);
    const data = await res.json();
    if (data.status !== 'success') throw new Error(data.message || 'read failed');
    return data;
}

/** Save one file's text. Returns the raw response, a conflict included. */
async function docWriteFile(relPath, content, expectedMtime) {
    const res = await fetch('/api/workspace/write', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: relPath, content: content, expected_mtime: expectedMtime }),
    });
    return res.json();
}

/** Render Markdown into a viewer body. */
function docRenderBody(id, content) {
    const el = document.getElementById(id);
    if (!el) return;
    el.innerHTML = renderMarkdown(content || '');
    applyHighlighting(el);
}

/** Put a document's name in a viewer title, with a dot while it is unsaved. */
function docRenderTitle(id, name, state) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = name || '';
    if (state && state.dirty) {
        el.insertAdjacentHTML('beforeend', ' <span class="doc-dirty-dot">•</span>');
    }
}

/**
 * Ask about any unsaved document edit before something tears its page down.
 *
 * @param {function} next - retried once the user agrees to lose the edits.
 * @returns {boolean} true when nothing is at stake and the caller may proceed.
 */
function docGuardUnsaved(next) {
    return memoryEditor.guard(next) && skillEditor.guard(next);
}

const memoryEditor = createDocEditor({
    body: () => document.getElementById('memory-viewer-content'),
    buttons: () => ({
        edit: document.getElementById('memory-btn-edit'),
        save: document.getElementById('memory-btn-save'),
        cancel: document.getElementById('memory-btn-cancel'),
    }),
    read: (doc) => docReadFile(doc.relPath),
    write: (doc, content, mtime) => docWriteFile(doc.relPath, content, mtime),
    render: (doc) => docRenderBody('memory-viewer-content', doc.content),
    onState: (state) => docRenderTitle('memory-viewer-title', memoryEditor.current()?.filename, state),
});

function openMemoryFile(filename, category) {
    category = category || 'memory';
    const agent = viewingMemoryAgentId();
    fetch(`/api/memory/content?filename=${encodeURIComponent(filename)}&category=${category}&agent_id=${encodeURIComponent(agent || '')}`).then(r => r.json()).then(data => {
        if (data.status !== 'success') return;
        document.getElementById('memory-panel-list').classList.add('hidden');
        document.getElementById('memory-panel-viewer').classList.remove('hidden');
        memoryEditor.open({
            filename: filename,
            // The memory API reports where the file sits under the workspace
            // root; the editor addresses it there rather than rebuilding the
            // path from filename plus category.
            relPath: data.rel_path || filename,
            content: data.content || '',
        });
    }).catch(() => {});
}

function closeMemoryViewer() {
    if (!memoryEditor.guard(closeMemoryViewer)) return;
    memoryEditor.forget();
    document.getElementById('memory-panel-viewer').classList.add('hidden');
    document.getElementById('memory-panel-list').classList.remove('hidden');
    // A save changed the size and timestamp the list shows.
    loadMemoryView(memoryPage);
}

// Reloading or closing the tab drops an unsaved edit. All the browser allows
// here is its own generic prompt, which still beats losing the text in silence.
window.addEventListener('beforeunload', (e) => {
    if (!memoryEditor.isDirty() && !skillEditor.isDirty()) return;
    e.preventDefault();
    e.returnValue = '';
});

// =====================================================================
// Custom Confirm Dialog
// =====================================================================
function showConfirmDialog({ title, message, okText, cancelText, onConfirm, hideCancel }) {
    const overlay = document.getElementById('confirm-dialog-overlay');
    document.getElementById('confirm-dialog-title').textContent = title || '';
    document.getElementById('confirm-dialog-message').textContent = message || '';
    document.getElementById('confirm-dialog-ok').textContent = okText || 'OK';
    const cancelBtn = document.getElementById('confirm-dialog-cancel');
    cancelBtn.textContent = cancelText || t('channels_cancel');
    cancelBtn.classList.toggle('hidden', !!hideCancel);

    function cleanup() {
        overlay.classList.add('hidden');
        okBtn.removeEventListener('click', onOk);
        cancelBtn.removeEventListener('click', onCancel);
        overlay.removeEventListener('click', onOverlayClick);
    }
    function onOk() { cleanup(); if (onConfirm) onConfirm(); }
    function onCancel() { cleanup(); }
    function onOverlayClick(e) { if (e.target === overlay) cleanup(); }

    const okBtn = document.getElementById('confirm-dialog-ok');
    okBtn.addEventListener('click', onOk);
    cancelBtn.addEventListener('click', onCancel);
    overlay.addEventListener('click', onOverlayClick);
    overlay.classList.remove('hidden');
}

// =====================================================================
// Models View
// =====================================================================
// Capability cards rendered on the Models page. Order matters — main model
// comes first because it transitively decides defaults for vision and image.
// Icon palette is grouped by capability family:
//   - chat                       → primary (brand green; the "main" capability)
//   - vision + image             → blue    (everything visual)
//   - asr + tts                  → amber   (everything audio)
//   - embedding                  → purple  (vectors)
//   - search                     → orange  (retrieval)
// Each card uses an explicit `iconClass` string so Tailwind's CDN JIT can
// see the literal class names — dynamic `bg-${color}-50` strings would not
// be picked up reliably.
const MODELS_CAPABILITY_DEFS = [
    { id: 'chat',      icon: 'fa-microchip',        editable: true,  needsModel: true,  toggleable: false, titleKey: 'models_capability_chat',      descKey: 'models_capability_chat_desc',
      iconChip: 'bg-primary-50 dark:bg-primary-900/30',  iconGlyph: 'text-primary-500' },
    // NOTE: the chat fallback is deliberately NOT a top-level card. It is a
    // rarely-touched safety net, so it lives behind a small gear on the main
    // model card (see renderCapabilityHeaderTag / openChatFallbackModal) and
    // is edited in a modal that reuses the same picker machinery.
    { id: 'vision',    icon: 'fa-eye',              editable: true,  needsModel: true,  titleKey: 'models_capability_vision',    descKey: 'models_capability_vision_desc',
      iconChip: 'bg-blue-50 dark:bg-blue-900/30',        iconGlyph: 'text-blue-500' },
    { id: 'image',     icon: 'fa-image',            editable: true,  needsModel: true,  titleKey: 'models_capability_image',     descKey: 'models_capability_image_desc',
      iconChip: 'bg-blue-50 dark:bg-blue-900/30',        iconGlyph: 'text-blue-500' },
    { id: 'asr',       icon: 'fa-microphone',       editable: true,  needsModel: true,  titleKey: 'models_capability_asr',       descKey: 'models_capability_asr_desc',
      iconChip: 'bg-amber-50 dark:bg-amber-900/30',      iconGlyph: 'text-amber-500' },
    { id: 'tts',       icon: 'fa-volume-high',      editable: true,  needsModel: true,  titleKey: 'models_capability_tts',       descKey: 'models_capability_tts_desc',
      iconChip: 'bg-amber-50 dark:bg-amber-900/30',      iconGlyph: 'text-amber-500' },
    { id: 'embedding', icon: 'fa-vector-square',    editable: true,  needsModel: true,  titleKey: 'models_capability_embedding', descKey: 'models_capability_embedding_desc',
      iconChip: 'bg-purple-50 dark:bg-purple-900/30',    iconGlyph: 'text-purple-500' },
    { id: 'search',    icon: 'fa-magnifying-glass', editable: true,  needsModel: false, titleKey: 'models_capability_search',    descKey: 'models_capability_search_desc',
      iconChip: 'bg-orange-50 dark:bg-orange-900/30',    iconGlyph: 'text-orange-500' },
];

// Provider logos: when a real SVG exists under static/logos/<id>.svg we use
// it; otherwise we fall back to a neutral monogram chip. SVGs are fetched
// via <img> with a hidden onerror so layout stays stable when files are
// absent. Vendors whose mark is rendered in pure (or near-pure) black are
// listed in MODELS_PROVIDER_LOGO_DARK_INVERT — for those, we apply a CSS
// invert filter in dark mode so the glyph stays visible against #1A1A1A.
const MODELS_PROVIDER_LOGO_PATH = 'assets/logos';
const MODELS_PROVIDER_LOGO_DARK_INVERT = new Set([
    'openai',     // black wordmark
    'moonshot',   // dark monogram
    'zhipu',      // dark monogram
    'custom',     // single-color slider glyph
]);

let modelsState = { providers: [], capabilities: {} };

// One-shot: { capabilityId, providerId } stashed before a Models reload,
// consumed by renderCapabilityBody to preselect a just-configured vendor.
let pendingCapabilitySelection = null;

// `opts.preserveScroll` keeps the page's vertical scroll position across the
// refresh. We capture it before unhiding the loading skeleton (which collapses
// content height to zero) and restore it after the new content is mounted.
// This matters when the user configures a vendor from inside a capability
// card's dropdown — without preservation, the post-save reload bounces them
// back to the top of the page, away from the card they were configuring.
function loadModelsView(opts) {
    const loading = document.getElementById('models-loading');
    const content = document.getElementById('models-content');
    if (!loading || !content) return;
    const preserveScroll = !!(opts && opts.preserveScroll);
    // The Models pane has its own scrollable container; capture its position
    // (not window.scrollY) so we can put the user back exactly where they were.
    const scroller = document.querySelector('#view-config .overflow-y-auto');
    const savedTop = preserveScroll && scroller ? scroller.scrollTop : null;

    loading.classList.remove('hidden');
    content.classList.add('hidden');

    fetch('/api/models').then(r => r.json()).then(data => {
        if (data.status !== 'success') {
            loading.innerHTML = `<span class="text-sm text-red-400">${escapeHtml(data.message || 'Failed to load')}</span>`;
            return;
        }
        modelsState.providers = data.providers || [];
        modelsState.capabilities = data.capabilities || {};
        renderModelsView();
        loading.classList.add('hidden');
        content.classList.remove('hidden');
        if (savedTop !== null && scroller) {
            // Wait one frame for the new layout to settle, otherwise the
            // restored scrollTop snaps to the previous (smaller) max.
            requestAnimationFrame(() => { scroller.scrollTop = savedTop; });
        }
    }).catch(err => {
        loading.innerHTML = `<span class="text-sm text-red-400">${escapeHtml(String(err))}</span>`;
    });
}

function renderModelsView() {
    const container = document.getElementById('models-content');
    container.innerHTML = '';
    container.appendChild(renderVendorsSection());
    MODELS_CAPABILITY_DEFS.forEach(def => container.appendChild(renderCapabilityCard(def)));
}

// True when a provider card is one of the expanded custom (OpenAI-compatible)
// providers (id "custom:<id>") — shown in the vendor grid alongside built-in
// vendors, but edited via the dedicated custom-provider modal.
function isCustomProviderCard(p) {
    return !!(p && p.is_custom && p.custom_name);
}

// ---------- Vendor section (Layer 1) -----------------------------------

function renderVendorsSection() {
    const wrap = document.createElement('div');
    wrap.className = 'bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10 p-6';

    // Custom providers always show once created (even without an api key,
    // e.g. a local vLLM/Ollama endpoint); built-in vendors show when configured.
    const configured = modelsState.providers.filter(p => p.configured || isCustomProviderCard(p));

    const header = `
        <div class="flex items-start gap-3 mb-5">
            <div class="w-9 h-9 rounded-lg bg-primary-50 dark:bg-primary-900/30 flex items-center justify-center flex-shrink-0">
                <i class="fas fa-key text-primary-500 text-sm"></i>
            </div>
            <div class="flex-1 min-w-0">
                <h3 class="font-semibold text-slate-800 dark:text-slate-100">${t('models_section_vendors')}</h3>
                <p class="text-xs text-slate-500 dark:text-slate-400 mt-0.5">${t('models_section_vendors_desc')}</p>
            </div>
        </div>`;

    let body;
    if (configured.length === 0) {
        body = `
            <div class="flex flex-col items-center justify-center py-8 px-4 rounded-lg border border-dashed border-slate-200 dark:border-white/10">
                <p class="text-sm text-slate-500 dark:text-slate-400 text-center">${t('models_not_configured')}</p>
                <button onclick="openVendorModal('')"
                        class="mt-3 px-3 py-1.5 rounded-lg text-xs font-medium bg-primary-50 dark:bg-primary-900/30 text-primary-600 dark:text-primary-400 hover:bg-primary-100 dark:hover:bg-primary-900/50 cursor-pointer transition-colors">
                    <i class="fas fa-plus text-[10px] mr-1"></i>${t('models_add_vendor')}
                </button>
            </div>`;
    } else {
        // Existing vendors as chips, plus a trailing "add" tile so a new
        // built-in or custom provider can still be added once at least one is
        // already configured (otherwise the add entry only showed on the empty
        // state). openVendorModal('') opens the picker → built-in or custom.
        const addTile = `
            <button onclick="openVendorModal('')"
                    class="flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg border border-dashed
                           border-slate-300 dark:border-white/15 text-slate-500 dark:text-slate-400
                           hover:border-primary-400 hover:text-primary-500 cursor-pointer transition-colors text-sm">
                <i class="fas fa-plus text-[11px]"></i>${t('models_add_vendor')}
            </button>`;
        body = `<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            ${configured.map(renderVendorChip).join('')}
            ${addTile}
        </div>`;
    }

    wrap.innerHTML = header + body;
    return wrap;
}

function renderVendorChip(p) {
    // The masked API key is intentionally not surfaced here; it is shown
    // inside the edit modal so the chip stays uncluttered and scannable.
    // Custom providers open their dedicated modal (name + base + key);
    // their ids are server-generated hex, safe to inline.
    const onclick = isCustomProviderCard(p)
        ? `openCustomProviderModal('${escapeHtml(p.custom_id)}')`
        : `openVendorModal('${escapeHtml(p.id)}')`;
    return `
        <button onclick="${onclick}"
                class="group flex items-center gap-3 px-3 py-2.5 rounded-lg border border-slate-200 dark:border-white/10
                       bg-slate-50 dark:bg-white/5 hover:border-primary-300 dark:hover:border-primary-500/50
                       cursor-pointer transition-colors duration-150 text-left">
            ${renderProviderLogo(p, 28)}
            <span class="flex-1 min-w-0 text-sm font-medium text-slate-800 dark:text-slate-100 truncate">${escapeHtml(localizedLabel(p.label))}</span>
            <i class="fas fa-pen-to-square text-[11px] text-slate-400 dark:text-slate-500 group-hover:text-primary-500 transition-colors"></i>
        </button>`;
}

// Render a uniformly-styled logo for a provider. Tries an SVG asset first; if
// it 404s the <img> swaps itself for a monogram fallback via onerror.
function renderProviderLogo(p, sizePx) {
    const initial = (localizedLabel(p.label) || p.id || '?').slice(0, 1).toUpperCase();
    const sz = sizePx || 32;
    const url = `${MODELS_PROVIDER_LOGO_PATH}/${encodeURIComponent(p.id)}.svg`;
    const fallbackId = `pl-${p.id}-${Math.random().toString(36).slice(2, 8)}`;
    const imgClass = MODELS_PROVIDER_LOGO_DARK_INVERT.has(p.id)
        ? 'absolute inset-0 m-auto provider-logo-img provider-logo-invert-dark'
        : 'absolute inset-0 m-auto provider-logo-img';
    return `
        <span class="relative flex items-center justify-center rounded-lg bg-slate-100 dark:bg-white/10
                     text-slate-600 dark:text-slate-300 flex-shrink-0 overflow-hidden"
              style="width:${sz}px;height:${sz}px;">
            <span id="${fallbackId}" class="text-xs font-bold">${escapeHtml(initial)}</span>
            <img src="${url}" alt="" aria-hidden="true"
                 class="${imgClass}"
                 style="width:${Math.round(sz * 0.65)}px;height:${Math.round(sz * 0.65)}px;"
                 onload="(function(el){var f=document.getElementById('${fallbackId}');if(f)f.style.display='none';})(this)"
                 onerror="this.remove();">
        </span>`;
}

function getCustomProviderCards() {
    return modelsState.providers.filter(isCustomProviderCard);
}

// ---------- Capability cards (Layer 2) ---------------------------------

function renderCapabilityCard(def) {
    const cap = modelsState.capabilities[def.id] || {};
    const wrap = document.createElement('div');
    wrap.className = 'bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10 p-6';
    wrap.id = `models-card-${def.id}`;

    const headerRight = renderCapabilityHeaderTag(def, cap);

    wrap.innerHTML = `
        <div class="flex items-start gap-3 mb-5">
            <div class="w-9 h-9 rounded-lg ${def.iconChip} flex items-center justify-center flex-shrink-0">
                <i class="fas ${def.icon} ${def.iconGlyph} text-sm"></i>
            </div>
            <div class="flex-1 min-w-0">
                <h3 class="font-semibold text-slate-800 dark:text-slate-100">${t(def.titleKey)}</h3>
                <p class="text-xs text-slate-500 dark:text-slate-400 mt-0.5">${t(def.descKey)}</p>
            </div>
            ${headerRight}
        </div>
        <div class="space-y-4" data-cap-body="${def.id}"></div>`;

    const body = wrap.querySelector(`[data-cap-body="${def.id}"]`);
    renderCapabilityBody(def, cap, body);
    return wrap;
}

function renderCapabilityHeaderTag(def, cap) {
    // The main model card carries a small gear that opens the chat-fallback
    // modal. The fallback is a rarely-touched safety net, so it stays out of
    // the card body; a badge appears next to the gear only while it is on, so
    // an active fallback is still discoverable at a glance.
    if (def.id === 'chat') {
        const fb = modelsState.capabilities.chat_fallback || {};
        // A single entry point that also reflects state: green + "on" label
        // when the fallback is enabled, muted + "configure" label when off.
        const on = !!fb.enabled;
        const cls = on
            ? 'text-primary-600 dark:text-primary-300 bg-primary-50 dark:bg-primary-900/30 hover:bg-primary-100 dark:hover:bg-primary-900/50'
            : 'text-slate-500 dark:text-slate-400 hover:text-primary-600 dark:hover:text-primary-300 hover:bg-slate-100 dark:hover:bg-white/5';
        const label = on ? t('models_fallback_badge_on') : t('models_fallback_config');
        return `
            <button type="button" onclick="openChatFallbackModal()"
                    title="${escapeHtml(t('models_fallback_config_tip'))}"
                    class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs flex-shrink-0
                           cursor-pointer transition-colors ${cls}">
                <i class="fas fa-shield-halved text-[11px]"></i>${label}
            </button>`;
    }
    return '';
}

// The chat fallback is configured in a modal rather than as a top-level card
// (it is a rarely-touched safety net). The modal body reuses the exact same
// picker machinery as a capability card — `renderCapabilityBody` keys every
// element off `cap-chat_fallback-*`, so we hand it a def with that id and let
// the existing provider/model/toggle/save code run unchanged. No such card is
// registered in MODELS_CAPABILITY_DEFS, so the ids never collide.
const CHAT_FALLBACK_DEF = {
    id: 'chat_fallback', editable: true, needsModel: true, toggleable: true,
    titleKey: 'models_fallback_modal_title', descKey: 'models_capability_chat_fallback_desc',
};

// ---------- Fallback chain editor -------------------------------------
//
// The fallback is an ordered list of provider+model links rather than a single
// backup model, so the modal renders one row per link with up/down/remove
// controls instead of a single provider + model pickers. Each row reuses the
// same initDropdown machinery the capability cards use, keyed off
// `fb-chain-<i>-*` so nothing collides with the shared capability ids.

// Working copy of the chain while the modal is open. Persisting is a separate
// act (Save), so a user can reorder freely and cancel without writing.
let fallbackChainDraft = [];

function _fallbackChainFromCapability() {
    const cap = modelsState.capabilities.chat_fallback || {};
    if (Array.isArray(cap.chain) && cap.chain.length) {
        return cap.chain.map(l => ({ provider: l.provider || '', model: l.model || '' }));
    }
    // Older backend (or a pre-chain config): a single backup model.
    if (cap.current_provider || cap.current_model) {
        return [{ provider: cap.current_provider || '', model: cap.current_model || '' }];
    }
    return [];
}

function _fallbackProviderOptions() {
    const cap = modelsState.capabilities.chat_fallback || {};
    const ids = (cap.providers && cap.providers.length)
        ? cap.providers.slice()
        : modelsState.providers.map(p => p.id);
    const byId = {};
    modelsState.providers.forEach(p => { byId[p.id] = p; });
    return ids.map(pid => ({
        value: pid,
        label: (byId[pid] && localizedLabel(byId[pid].label)) || pid,
    }));
}

// Model list for one row, mirroring rebuildCapabilityModelDropdown's
// provider_models -> provider.models fallback.
function _fallbackModelOptions(providerId) {
    const cap = modelsState.capabilities.chat_fallback || {};
    const map = cap.provider_models || {};
    let raw = map[providerId];
    if (!raw && providerId.startsWith('custom:') && map['custom']) raw = map['custom'];
    if (!raw) {
        const p = modelsState.providers.find(x => x.id === providerId);
        raw = (p && p.models) ? p.models : [];
    }
    return raw.map(e => {
        const v = (typeof e === 'string') ? e : e.value;
        return { value: v, label: (typeof e === 'string') ? e : (e.label || v) };
    });
}

function _readFallbackChainRow(i) {
    const provDd = document.getElementById(`fb-chain-${i}-provider`);
    const modelDd = document.getElementById(`fb-chain-${i}-model`);
    const customInput = document.getElementById(`fb-chain-${i}-model-custom`);
    let model = modelDd ? getDropdownValue(modelDd) : '';
    if (model === '__custom__') model = customInput ? customInput.value.trim() : '';
    return {
        provider: provDd ? getDropdownValue(provDd) : '',
        model: model,
    };
}

function _syncFallbackChainDraft() {
    // Pull every visible row into the draft so a reorder keeps the values the
    // user has typed but not yet committed to it.
    fallbackChainDraft = fallbackChainDraft.map((_, i) => {
        if (!document.getElementById(`fb-chain-${i}-provider`)) return fallbackChainDraft[i];
        return _readFallbackChainRow(i);
    });
}

function addFallbackChainLink() {
    _syncFallbackChainDraft();
    // Seed a new row from the first provider with a model, so it is one click
    // from usable instead of two.
    const opts = _fallbackProviderOptions();
    const first = opts[0];
    const models = first && first.value ? _fallbackModelOptions(first.value) : [];
    fallbackChainDraft.push({
        provider: first ? first.value : '',
        model: models.length ? models[0].value : '',
    });
    renderFallbackChainEditor();
}

function removeFallbackChainLink(i) {
    _syncFallbackChainDraft();
    fallbackChainDraft.splice(i, 1);
    renderFallbackChainEditor();
}

function moveFallbackChainLink(i, delta) {
    const j = i + delta;
    if (j < 0 || j >= fallbackChainDraft.length) return;
    _syncFallbackChainDraft();
    const tmp = fallbackChainDraft[i];
    fallbackChainDraft[i] = fallbackChainDraft[j];
    fallbackChainDraft[j] = tmp;
    renderFallbackChainEditor();
}

function onFallbackChainProviderChange(i, providerId) {
    // Keep the draft in sync, then rebuild just this row's model picker.
    const modelDd = document.getElementById(`fb-chain-${i}-model`);
    const customWrap = document.getElementById(`fb-chain-${i}-model-custom-wrap`);
    const models = _fallbackModelOptions(providerId);
    const opts = models.concat([{
        value: '__custom__',
        label: currentLang === 'zh' ? '自定义' : 'Custom',
    }]);
    if (modelDd) {
        initDropdown(modelDd, opts, models.length ? models[0].value : '', (value) => {
            if (!customWrap) return;
            if (value === '__custom__') customWrap.classList.remove('hidden');
            else customWrap.classList.add('hidden');
        });
    }
    if (customWrap) customWrap.classList.add('hidden');
    // The row just became usable (provider + a seeded model), so let the save
    // button re-evaluate.
    refreshFallbackChainSaveState();
}

function renderFallbackChainEditor() {
    const host = document.getElementById('fb-chain-list');
    if (!host) return;
    const rows = fallbackChainDraft;
    if (!rows.length) {
        host.innerHTML = `<p class="text-xs text-slate-400 dark:text-slate-500">${escapeHtml(t('models_fallback_chain_empty'))}</p>`;
        // No rows left means nothing usable to save. Refresh before returning
        // — the save button's state is derived from the draft, and removing the
        // last row is exactly when it has to flip back to disabled.
        refreshFallbackChainSaveState();
        return;
    }
    host.innerHTML = rows.map((link, i) => `
        <div class="rounded-xl border border-slate-200 dark:border-white/10 p-3 space-y-2.5">
            <div class="flex items-center justify-between gap-2">
                <span class="text-xs font-medium text-slate-500 dark:text-slate-400">
                    ${escapeHtml(t('models_fallback_chain_link').replace('{{n}}', String(i + 1)))}
                </span>
                <div class="flex items-center gap-1">
                    <button type="button" title="${escapeHtml(t('models_fallback_chain_move_up'))}"
                            onclick="moveFallbackChainLink(${i}, -1)"
                            ${i === 0 ? 'disabled' : ''}
                            class="px-1.5 py-1 rounded text-slate-400 hover:text-slate-700 dark:hover:text-slate-200
                                   hover:bg-slate-100 dark:hover:bg-white/5 cursor-pointer transition-colors
                                   disabled:opacity-30 disabled:cursor-not-allowed">
                        <i class="fas fa-arrow-up text-[11px]"></i>
                    </button>
                    <button type="button" title="${escapeHtml(t('models_fallback_chain_move_down'))}"
                            onclick="moveFallbackChainLink(${i}, 1)"
                            ${i === rows.length - 1 ? 'disabled' : ''}
                            class="px-1.5 py-1 rounded text-slate-400 hover:text-slate-700 dark:hover:text-slate-200
                                   hover:bg-slate-100 dark:hover:bg-white/5 cursor-pointer transition-colors
                                   disabled:opacity-30 disabled:cursor-not-allowed">
                        <i class="fas fa-arrow-down text-[11px]"></i>
                    </button>
                    <button type="button" title="${escapeHtml(t('models_fallback_chain_remove'))}"
                            onclick="removeFallbackChainLink(${i})"
                            class="px-1.5 py-1 rounded text-slate-400 hover:text-danger
                                   hover:bg-danger/10 cursor-pointer transition-colors">
                        <i class="fas fa-trash-can text-[11px]"></i>
                    </button>
                </div>
            </div>
            <div id="fb-chain-${i}-provider" class="cfg-dropdown" tabindex="0">
                <div class="cfg-dropdown-selected">
                    <span class="cfg-dropdown-text">--</span>
                    <i class="fas fa-chevron-down cfg-dropdown-arrow"></i>
                </div>
                <div class="cfg-dropdown-menu"></div>
            </div>
            <div id="fb-chain-${i}-model" class="cfg-dropdown" tabindex="0">
                <div class="cfg-dropdown-selected">
                    <span class="cfg-dropdown-text">--</span>
                    <i class="fas fa-chevron-down cfg-dropdown-arrow"></i>
                </div>
                <div class="cfg-dropdown-menu"></div>
            </div>
            <div id="fb-chain-${i}-model-custom-wrap" class="hidden">
                <input id="fb-chain-${i}-model-custom" type="text"
                       class="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600
                              bg-slate-50 dark:bg-white/5 text-sm text-slate-800 dark:text-slate-100
                              focus:outline-none focus:border-primary-500 font-mono transition-colors"
                       placeholder="custom model name">
            </div>
        </div>`).join('');

    rows.forEach((link, i) => {
        const provDd = document.getElementById(`fb-chain-${i}-provider`);
        if (provDd) {
            initDropdown(provDd, _fallbackProviderOptions(), link.provider || '',
                (value) => onFallbackChainProviderChange(i, value));
        }
        const models = _fallbackModelOptions(link.provider || '');
        const inCatalog = models.some(o => o.value === link.model);
        const modelDd = document.getElementById(`fb-chain-${i}-model`);
        const customWrap = document.getElementById(`fb-chain-${i}-model-custom-wrap`);
        const customInput = document.getElementById(`fb-chain-${i}-model-custom`);
        if (modelDd) {
            initDropdown(modelDd, models.concat([{
                value: '__custom__',
                label: currentLang === 'zh' ? '自定义' : 'Custom',
            }]), inCatalog ? link.model : (link.model ? '__custom__' : ''), (value) => {
                if (!customWrap) return;
                if (value === '__custom__') customWrap.classList.remove('hidden');
                else customWrap.classList.add('hidden');
            });
        }
        if (!inCatalog && link.model) {
            if (customWrap) customWrap.classList.remove('hidden');
            if (customInput) customInput.value = link.model;
        }
    });

    // Every add / remove / reorder re-renders the rows, so refresh the save
    // button here rather than at each call site: a row added after the toggle
    // was switched on would otherwise leave Save stuck on its previous state.
    refreshFallbackChainSaveState();
}

// Whether at least one row is usable — the backend rejects an empty chain
// when the fallback is being enabled, so block Save here too.
function fallbackChainIsComplete() {
    _syncFallbackChainDraft();
    return fallbackChainDraft.some(l => l.provider && l.model);
}

function refreshFallbackChainSaveState() {
    const cap = modelsState.capabilities.chat_fallback || {};
    const btn = document.getElementById('fb-chain-save');
    const hint = document.getElementById('fb-chain-incomplete-hint');
    if (!btn) return;
    const needsChain = !!cap.enabled;
    btn.disabled = needsChain && !fallbackChainIsComplete();
    if (hint) {
        hint.classList.toggle('hidden', !(needsChain && btn.disabled));
    }
}

// Resolve a capability def by id. The chat fallback is intentionally absent
// from MODELS_CAPABILITY_DEFS (it renders in a modal, not as a card), so the
// shared save/toggle handlers look it up here too.
function capabilityDefById(capId) {
    if (capId === 'chat_fallback') return CHAT_FALLBACK_DEF;
    return MODELS_CAPABILITY_DEFS.find(d => d.id === capId);
}

function openChatFallbackModal() {
    closeChatFallbackModal(); // never stack two

    // Read the capability *before* building the markup: the template below
    // renders the toggle and the chain from it, so a `cap` declared after the
    // innerHTML would still be in its temporal dead zone and throw.
    const cap = modelsState.capabilities.chat_fallback || {};

    const overlay = document.createElement('div');
    overlay.id = 'chat-fallback-modal-overlay';
    overlay.className = 'fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4';
    overlay.innerHTML = `
        <div class="w-full max-w-md rounded-2xl bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 shadow-xl">
            <div class="flex items-start gap-3 px-6 pt-6 pb-4 border-b border-slate-100 dark:border-white/5">
                <div class="w-9 h-9 rounded-lg bg-primary-50 dark:bg-primary-900/30 flex items-center justify-center flex-shrink-0">
                    <i class="fas fa-shield-halved text-primary-500 text-sm"></i>
                </div>
                <div class="flex-1 min-w-0">
                    <h3 class="font-semibold text-slate-800 dark:text-slate-100">${t('models_fallback_modal_title')}</h3>
                    <p class="text-xs text-slate-500 dark:text-slate-400 mt-1 leading-relaxed">${t('models_fallback_modal_desc')}</p>
                </div>
                <button type="button" onclick="closeChatFallbackModal()"
                        class="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 cursor-pointer transition-colors flex-shrink-0">
                    <i class="fas fa-xmark"></i>
                </button>
            </div>
            <div class="px-6 py-5 space-y-4 max-h-[70vh] overflow-y-auto" data-cap-body="chat_fallback">
                <div id="cap-chat_fallback-toggle-wrap" class="flex items-center justify-between gap-3">
                    <label class="text-sm font-medium text-slate-600 dark:text-slate-400">${escapeHtml(t('models_fallback_enable'))}</label>
                    <button type="button" id="cap-chat_fallback-toggle" role="switch"
                            aria-checked="${cap.enabled ? 'true' : 'false'}"
                            onclick="toggleChatFallbackEnabled()"
                            class="relative inline-flex h-5 w-9 flex-shrink-0 items-center rounded-full transition-colors cursor-pointer ${cap.enabled ? 'bg-primary-500' : 'bg-slate-200 dark:bg-slate-700'}">
                        <span class="inline-block h-3.5 w-3.5 rounded-full bg-white shadow transition-transform ${cap.enabled ? 'translate-x-[18px]' : 'translate-x-[3px]'}"></span>
                    </button>
                </div>
                <div id="fb-chain-wrap" class="space-y-3 ${cap.enabled ? '' : 'hidden'}">
                    <div>
                        <label class="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-1.5">${escapeHtml(t('models_fallback_chain_title'))}</label>
                        <p class="text-xs text-slate-400 dark:text-slate-500 leading-relaxed">${escapeHtml(t('models_fallback_chain_desc'))}</p>
                    </div>
                    <div id="fb-chain-list" class="space-y-2.5"></div>
                    <button type="button" onclick="addFallbackChainLink()"
                            class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs
                                   text-primary-600 dark:text-primary-300 bg-primary-50 dark:bg-primary-900/30
                                   hover:bg-primary-100 dark:hover:bg-primary-900/50 cursor-pointer transition-colors">
                        <i class="fas fa-plus text-[11px]"></i>${escapeHtml(t('models_fallback_chain_add'))}
                    </button>
                    <p id="fb-chain-incomplete-hint" class="text-xs text-danger hidden">${escapeHtml(t('models_fallback_chain_incomplete'))}</p>
                </div>
                <div class="flex items-center justify-between gap-3 pt-1">
                    <div class="flex-1 min-w-0"></div>
                    <div class="flex items-center gap-3 flex-shrink-0">
                        <span id="cap-chat_fallback-status" class="text-xs text-primary-500 opacity-0 transition-opacity duration-300"></span>
                        <button id="fb-chain-save" onclick="saveCapability('chat_fallback')"
                                class="px-4 py-2 rounded-lg bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium
                                       cursor-pointer transition-colors duration-150 disabled:opacity-50 disabled:cursor-not-allowed">
                            ${escapeHtml(t('save'))}
                        </button>
                    </div>
                </div>
            </div>
        </div>`;

    // Close on backdrop click (but not when clicking inside the dialog).
    overlay.addEventListener('click', (e) => { if (e.target === overlay) closeChatFallbackModal(); });

    document.body.appendChild(overlay);

    // Reset the draft each time the modal opens so a cancelled edit never
    // leaks into the next open.
    fallbackChainDraft = _fallbackChainFromCapability();
    renderFallbackChainEditor();
    refreshFallbackChainSaveState();
}

// The chain modal owns its own toggle (the shared capability body renders the
// picker rows instead), so it needs its own flip handler: toggle the local
// switch, show/hide the chain, and re-check whether Save is allowed.
function toggleChatFallbackEnabled() {
    const cap = modelsState.capabilities.chat_fallback || {};
    cap.enabled = !cap.enabled;
    modelsState.capabilities.chat_fallback = cap;

    const btn = document.getElementById('cap-chat_fallback-toggle');
    if (btn) {
        btn.setAttribute('aria-checked', cap.enabled ? 'true' : 'false');
        btn.classList.toggle('bg-primary-500', cap.enabled);
        btn.classList.toggle('bg-slate-200', !cap.enabled);
        btn.classList.toggle('dark:bg-slate-700', !cap.enabled);
        const knob = btn.querySelector('span');
        if (knob) {
            knob.classList.toggle('translate-x-[18px]', cap.enabled);
            knob.classList.toggle('translate-x-[3px]', !cap.enabled);
        }
    }
    const wrap = document.getElementById('fb-chain-wrap');
    if (wrap) wrap.classList.toggle('hidden', !cap.enabled);
    refreshFallbackChainSaveState();
}

function closeChatFallbackModal() {
    const overlay = document.getElementById('chat-fallback-modal-overlay');
    if (overlay) overlay.remove();
}

function _searchProviderLabel(cap, providerId) {
    const list = (cap && cap.providers) || [];
    const hit = list.find(p => p.id === providerId);
    return hit ? localizedLabel(hit.label) : providerId;
}

// Search card body: strategy picker + (when fixed) provider picker + a
// status row that surfaces which providers are ready and how to add the
// missing ones. Three of the four backends piggy-back on model-vendor
// credentials (zhipu / qianfan / linkai); bocha owns its own key under
// tools.web_search and gets its own minimal credential modal.
function renderSearchCapability(def, cap, body) {
    const providers = cap.providers || [];
    const configuredIds = cap.configured_providers || [];
    const hasAny = configuredIds.length > 0;
    const strategy = cap.strategy || 'auto';

    body.innerHTML = `
        <div>
            <label class="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-1.5">${t('models_search_strategy_label')}</label>
            <div id="cap-search-strategy" class="cfg-dropdown" tabindex="0">
                <div class="cfg-dropdown-selected">
                    <span class="cfg-dropdown-text">--</span>
                    <i class="fas fa-chevron-down cfg-dropdown-arrow"></i>
                </div>
                <div class="cfg-dropdown-menu"></div>
            </div>
        </div>
        <div id="cap-search-provider-wrap" class="hidden">
            <label class="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-1.5">${t('models_provider')}</label>
            <div id="cap-search-provider" class="cfg-dropdown" tabindex="0">
                <div class="cfg-dropdown-selected">
                    <span class="cfg-dropdown-text">--</span>
                    <i class="fas fa-chevron-down cfg-dropdown-arrow"></i>
                </div>
                <div class="cfg-dropdown-menu"></div>
            </div>
        </div>
        <div id="cap-search-summary"></div>
        <div class="flex items-center justify-end gap-3 pt-1">
            <span id="cap-search-status" class="text-xs text-primary-500 opacity-0 transition-opacity duration-300"></span>
            <button onclick="saveSearchCapability()"
                    class="px-4 py-2 rounded-lg bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium
                           cursor-pointer transition-colors duration-150 disabled:opacity-50 disabled:cursor-not-allowed">
                ${t('save')}
            </button>
        </div>
    `;

    // Strategy dropdown — when no provider is configured the strategy
    // value is meaningless, so we show a "待配置" placeholder instead of
    // a default selection. Once any provider gets configured the saved
    // strategy (or "auto") becomes the active value.
    initDropdown(
        body.querySelector('#cap-search-strategy'),
        [
            { value: 'auto',  label: t('models_strategy_auto'),         hint: t('models_search_strategy_auto_hint') },
            { value: 'fixed', label: t('models_search_strategy_fixed'), hint: t('models_search_strategy_fixed_hint') },
        ],
        hasAny ? strategy : '',
        (value) => _onSearchStrategyChange(cap, value, body),
        hasAny ? null : { placeholder: t('models_pending_config') },
    );

    // Provider dropdown — populated with configured providers only;
    // unconfigured ones cannot be pinned (they'd silently fall back).
    const provOpts = configuredIds.map(id => ({
        value: id,
        label: _searchProviderLabel(cap, id),
    }));
    if (provOpts.length === 0) provOpts.push({ value: '', label: '--' });
    initDropdown(
        body.querySelector('#cap-search-provider'),
        provOpts,
        cap.fixed_provider || configuredIds[0] || '',
        () => {},
    );

    _renderSearchSummary(body, cap);
    _setSearchProviderPickerVisible(body, strategy === 'fixed' && hasAny);
}

function _onSearchStrategyChange(cap, value, body) {
    const configuredIds = cap.configured_providers || [];
    _setSearchProviderPickerVisible(body, value === 'fixed' && configuredIds.length > 0);
}

function _setSearchProviderPickerVisible(body, visible) {
    const wrap = body.querySelector('#cap-search-provider-wrap');
    if (!wrap) return;
    if (visible) wrap.classList.remove('hidden');
    else wrap.classList.add('hidden');
}

// Search summary line: just lists configured providers + a trailing "+
// add" button. Unconfigured backends are hidden — the user picks one from
// a small chooser when they click add. Empty state surfaces the same add
// button as a primary CTA.
function _renderSearchSummary(body, cap) {
    const host = body.querySelector('#cap-search-summary');
    if (!host) return;
    const providers = cap.providers || [];
    const configured = providers.filter(p => p.configured);

    const missing = providers.filter(p => !p.configured);

    const addBtn = missing.length
        ? `<button type="button" id="cap-search-add-btn"
                  class="inline-flex items-center gap-1 px-2 py-0.5 text-[11px] rounded-md cursor-pointer
                         bg-slate-100 dark:bg-white/5 text-slate-500 dark:text-slate-400
                         hover:bg-slate-200 dark:hover:bg-white/10 transition-colors">
              <i class="fas fa-plus text-[10px]"></i>${t('models_search_add_provider')}
           </button>`
        : '';

    if (configured.length === 0) {
        host.innerHTML = `
            <div class="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                <i class="fas fa-circle-info text-[10px] text-amber-500"></i>
                <span>${t('models_search_none_configured')}</span>
                ${addBtn}
            </div>
        `;
    } else {
        const chips = configured.map(p => `
            <button type="button" data-search-edit-provider="${p.id}"
                    title="${t('models_search_edit_hint')}"
                    class="inline-flex items-center gap-1 px-2 py-0.5 text-[11px] rounded-md cursor-pointer
                           bg-emerald-50 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400
                           hover:bg-emerald-100 dark:hover:bg-emerald-900/50 transition-colors">
                <i class="fas fa-check text-[10px]"></i>${escapeHtml(localizedLabel(p.label))}${p.anonymous ? ` · ${t('models_search_anonymous_badge')}` : ''}
            </button>
        `).join('');
        host.innerHTML = `
            <div class="flex items-center flex-wrap gap-2 text-xs text-slate-500 dark:text-slate-400">
                <span>${t('models_search_available_label')}</span>
                ${chips}
                ${addBtn}
            </div>
        `;
    }

    const addBtnEl = host.querySelector('#cap-search-add-btn');
    if (addBtnEl) {
        addBtnEl.addEventListener('click', (ev) => {
            ev.preventDefault();
            openSearchAddProviderPicker(missing);
        });
    }
    host.querySelectorAll('[data-search-edit-provider]').forEach(el => {
        el.addEventListener('click', (ev) => {
            ev.preventDefault();
            const pid = el.getAttribute('data-search-edit-provider');
            const meta = (cap.providers || []).find(p => p.id === pid);
            _launchSearchProviderConfig(pid, meta);
        });
    });
}

// Two-step add flow: click "+ 添加厂商" -> chooser dialog -> per-provider
// credential editor. Bocha lands on the dedicated key modal; the others
// piggy-back on the existing vendor credential modal.
function openSearchAddProviderPicker(missingProviders) {
    if (!missingProviders || missingProviders.length === 0) return;
    if (missingProviders.length === 1) {
        _launchSearchProviderConfig(missingProviders[0].id);
        return;
    }

    const existing = document.getElementById('search-add-modal');
    if (existing) existing.remove();

    const rows = missingProviders.map(p => `
        <button type="button" data-pid="${p.id}"
                class="w-full flex items-center justify-between px-3 py-2.5 rounded-lg cursor-pointer
                       bg-slate-50 dark:bg-white/5 hover:bg-slate-100 dark:hover:bg-white/10
                       text-sm text-slate-700 dark:text-slate-200 transition-colors">
            <span>${escapeHtml(localizedLabel(p.label))}</span>
            <i class="fas fa-chevron-right text-[10px] text-slate-400"></i>
        </button>
    `).join('');

    const modal = document.createElement('div');
    modal.id = 'search-add-modal';
    modal.className = 'fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm';
    modal.innerHTML = `
        <div class="bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10
                    w-full max-w-md mx-4 p-6 shadow-xl">
            <h3 class="text-lg font-semibold text-slate-800 dark:text-slate-100 mb-1">${t('models_search_add_provider')}</h3>
            <p class="text-xs text-slate-500 dark:text-slate-400 mb-4">${t('models_search_add_desc')}</p>
            <div class="space-y-2">${rows}</div>
            <div class="flex items-center justify-end mt-5">
                <button type="button" onclick="document.getElementById('search-add-modal').remove()"
                        class="px-3 py-1.5 rounded-md text-sm text-slate-600 dark:text-slate-300
                               hover:bg-slate-100 dark:hover:bg-white/5 transition-colors">
                    ${t('cancel')}
                </button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
    modal.querySelectorAll('[data-pid]').forEach(el => {
        el.addEventListener('click', () => {
            const pid = el.getAttribute('data-pid');
            modal.remove();
            _launchSearchProviderConfig(pid);
        });
    });
}

function _launchSearchProviderConfig(providerId, providerMeta) {
    // Providers that hold their own credential (dedicated key or, for SearXNG,
    // an instance URL) use the bespoke search-key modal. zhipu/qianfan/linkai
    // reuse a model-vendor key and go through the vendor modal instead.
    if (['bocha', 'anysearch', 'serply', 'tavily', 'searxng', 'keenable'].includes(providerId)) {
        openSearchKeyModal(providerId, providerMeta);
    } else {
        openVendorModal(providerId, () => loadModelsView({ preserveScroll: true }));
    }
}


function saveSearchCapability() {
    const strategyDd = document.getElementById('cap-search-strategy');
    const providerDd = document.getElementById('cap-search-provider');
    // 如果策略下拉框的值是空（待配置），默认使用 'auto'
    const strategy = strategyDd ? (getDropdownValue(strategyDd) || 'auto') : 'auto';
    const provider = (strategy === 'fixed' && providerDd) ? getDropdownValue(providerDd) : '';

    fetch('/api/models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            action: 'set_capability',
            capability: 'search',
            strategy,
            provider,
        }),
    }).then(r => r.json()).then(data => {
        if (data.status === 'success') {
            showStatus('cap-search-status', 'models_save_success', false);
            setTimeout(() => loadModelsView({ preserveScroll: true }), 400);
        } else {
            console.log('[saveSearchCapability] Error:', data.message);
            showStatus('cap-search-status', 'models_save_failed', true);
        }
    }).catch(() => showStatus('cap-search-status', 'models_save_failed', true));
}


// Minimal bocha API-key modal. Reuses the existing vendor-modal markup
// helpers would be nice, but bocha isn't in PROVIDER_MODELS (it's not a
// model vendor), so we render a tiny dedicated dialog.
// For search vendors that hold their own keys.


function openSearchKeyModal(providerId, providerMeta) {
    const existing = document.getElementById('search-key-modal');
    if (existing) existing.remove();

        const searchCap = (modelsState && modelsState.capabilities && modelsState.capabilities.search) || {};
    const prov = (searchCap.providers || []).find(p => p.id === providerId);
    const isSearxng = providerId === 'searxng';
    // SearXNG holds an instance URL (echoed back verbatim in url_masked); the
    // rest hold a masked API key. Resolve whichever applies as the field value.
    let masked;
    if (isSearxng) {
        masked = (providerMeta && providerMeta.url_masked) || (prov && prov.url_masked) || '';
    } else {
        masked = (providerMeta && providerMeta.api_key_masked) || '';
        if (!masked && prov && prov.api_key_masked) masked = prov.api_key_masked;
    }
    // SearXNG URL is not masked, so it's safe to keep editable (not a sentinel).
    const hasKey = !!masked;
    const isAnonymous = (providerId === 'anysearch' || providerId === 'keenable')
        && !!((providerMeta && providerMeta.anonymous) || (prov && prov.anonymous));
    const clearBtnHtml = (hasKey || isAnonymous)
        ? `<button type="button" id="search-key-clear"
                  class="px-3 py-1.5 rounded-md text-xs text-red-500 dark:text-red-400
                         hover:bg-red-50 dark:hover:bg-red-900/20 cursor-pointer transition-colors">
              ${t('models_clear_credential')}
           </button>`
        : '';
    let descText = t('models_search_' + providerId + '_desc');
    if (providerId === 'anysearch') {
        const hint = currentLang === 'zh'
            ? '（留空可启用匿名模式，每日有免费额度）'
            : '(Leave blank to enable anonymous mode with daily free quota)';
        descText = descText + ' ' + hint;
    }
    const modal = document.createElement('div');
    modal.id = 'search-key-modal';
    modal.className = 'fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm';
    modal.innerHTML = `
        <div id="search-key-modal-card"
             class="bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10
                    w-full max-w-md mx-4 p-6 shadow-xl">
            <h3 class="text-lg font-semibold text-slate-800 dark:text-slate-100 mb-1">${t('models_search_' + providerId + '_title')}</h3>
            <p class="text-xs text-slate-500 dark:text-slate-400 mb-4">${descText}</p>
            <label class="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-1.5">${providerId === 'searxng' ? 'Instance URL' : 'API Key'}</label>
            <input id="search-key-input" type="text" autocomplete="off" data-1p-ignore data-lpignore="true"
                   class="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600
                          bg-slate-50 dark:bg-white/5 text-sm text-slate-800 dark:text-slate-100
                          focus:outline-none focus:border-primary-500 ${isSearxng ? '' : 'font-mono'} ${(hasKey && !isSearxng) ? 'cfg-key-masked' : ''}"
                   value="${escapeHtml(masked)}"
                   data-masked="${(hasKey && !isSearxng) ? '1' : ''}"
                   placeholder="${isSearxng ? 'https://searxng.example.com' : 'sk-...'}" />
            <div class="flex items-center justify-between gap-3 mt-5">
                <div>${clearBtnHtml}</div>
                <div class="flex items-center gap-3">
                    <button type="button" onclick="document.getElementById('search-key-modal').remove()"
                            class="px-3 py-1.5 rounded-md text-sm text-slate-600 dark:text-slate-300
                                   hover:bg-slate-100 dark:hover:bg-white/5 transition-colors">
                        ${t('cancel')}
                    </button>
                    <button type="button" onclick="_saveSearchKey('${providerId}')"
                            class="px-4 py-1.5 rounded-md bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium
                                   cursor-pointer transition-colors">
                        ${t('save')}
                    </button>
                </div>
            </div>
        </div>
    `;
    document.body.appendChild(modal);

    // Reset masked sentinel as soon as the user starts editing so the save
    // handler can tell apart "kept the existing key" vs "typed a new one".
    const input = document.getElementById('search-key-input');
    if (input) {
        const unmask = () => {
            if (input.dataset.masked === '1') {
                input.value = '';
                input.dataset.masked = '';
                input.classList.remove('cfg-key-masked');
            }
        };
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Tab' || e.key === 'Escape') return;
            unmask();
        });
        input.addEventListener('paste', unmask);
        if (!hasKey) setTimeout(() => input.focus(), 50);
    }
    const clearBtn = document.getElementById('search-key-clear');
    if (clearBtn) clearBtn.addEventListener('click', () => _clearSearchKey(providerId));

    modal.addEventListener('mousedown', (e) => {
        if (e.target === modal) modal.remove();
    });
    const onKey = (e) => {
        if (e.key === 'Escape') {
            modal.remove();
            document.removeEventListener('keydown', onKey);
        }
    };
    document.addEventListener('keydown', onKey);
}


function _saveSearchKey(providerId) {
    const input = document.getElementById('search-key-input');
    if (!input) return;
    if (input.dataset.masked === '1') {
        const modal = document.getElementById('search-key-modal');
        if (modal) modal.remove();
        return;
    }
    const apiKey = input.value.trim();

    // anysearch and keenable: saving with an empty key enables the anonymous tier.
    if (providerId === 'anysearch' || providerId === 'keenable') {
    fetch('/api/models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            action: 'set_search_credential',
            provider: providerId,
            api_key: apiKey,
            anonymous: !apiKey, // ← 字段名必须是 anonymous；留空保存 = 启用匿名（表第 2 行）
        }),
    }).then(r => r.json()).then(data => {
        if (data.status === 'success') {
            const modal = document.getElementById('search-key-modal');
            if (modal) modal.remove();
            loadModelsView({ preserveScroll: true });
        }
    });
    return;
}

    if (providerId === 'searxng') {
        // SearXNG uses an instance URL, not an API key. Empty input is a no-op
        // here (use the clear button to remove it).
    if (!apiKey) {
        input.focus();
        return;
    }
    fetch('/api/models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action: 'set_search_credential',
                provider: providerId,
                url: apiKey, // reuse the input value as the URL
            }),
    }).then(r => r.json()).then(data => {
        if (data.status === 'success') {
                const modal = document.getElementById('search-key-modal');
            if (modal) modal.remove();
            loadModelsView({ preserveScroll: true });
        }
    });
        return;
}

    if (!apiKey) {
        input.focus();
        return;
    }
    fetch('/api/models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'set_search_credential', provider: providerId, api_key: apiKey }),
    }).then(r => r.json()).then(data => {
        if (data.status === 'success') {
            const modal = document.getElementById('search-key-modal');
            if (modal) modal.remove();
            loadModelsView({ preserveScroll: true });
        }
    });
}

function _clearSearchKey(providerId) {
    // SearXNG is cleared by emptying its instance URL, not an API key.
    const payload = (providerId === 'searxng')
        ? { action: 'set_search_credential', provider: providerId, url: '' }
        : { action: 'set_search_credential', provider: providerId, api_key: '' };
    fetch('/api/models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    }).then(r => r.json()).then(data => {
        if (data.status === 'success') {
            const modal = document.getElementById('search-key-modal');
            if (modal) modal.remove();
            loadModelsView({ preserveScroll: true });
        }
    });
}

function renderCapabilityBody(def, cap, body) {
    if (def.id === 'search') {
        renderSearchCapability(def, cap, body);
        return;
    }

    // Editable cards: provider dropdown + (optional) model dropdown + save row
    const providerOpts = buildCapabilityProviderOptions(def, cap);
    const providerHtml = `
        <div>
            <label class="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-1.5">${t('models_provider')}</label>
            <div id="cap-${def.id}-provider" class="cfg-dropdown" tabindex="0">
                <div class="cfg-dropdown-selected">
                    <span class="cfg-dropdown-text">--</span>
                    <i class="fas fa-chevron-down cfg-dropdown-arrow"></i>
                </div>
                <div class="cfg-dropdown-menu"></div>
            </div>
        </div>`;

    // The model-picker container is always emitted so the provider-change
    // handler can show/hide it; for `auto` capabilities it starts hidden and
    // gets toggled by setCapabilityModelPickerVisible.
    const modelHtml = def.needsModel ? `
        <div id="cap-${def.id}-model-wrap">
            <label class="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-1.5">${t('models_model')}</label>
            <div id="cap-${def.id}-model" class="cfg-dropdown" tabindex="0">
                <div class="cfg-dropdown-selected">
                    <span class="cfg-dropdown-text">--</span>
                    <i class="fas fa-chevron-down cfg-dropdown-arrow"></i>
                </div>
                <div class="cfg-dropdown-menu"></div>
            </div>
            <div id="cap-${def.id}-model-custom-wrap" class="mt-2 hidden">
                <input id="cap-${def.id}-model-custom" type="text"
                       class="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600
                              bg-slate-50 dark:bg-white/5 text-sm text-slate-800 dark:text-slate-100
                              focus:outline-none focus:border-primary-500 font-mono transition-colors"
                       placeholder="custom model name">
            </div>
        </div>` : '';

    const dimHtml = (def.id === 'embedding' && cap.current_dim) ? `
        <p class="text-xs text-slate-400 dark:text-slate-500">
            <i class="fas fa-cube text-[10px] mr-1"></i>${t('models_dim_label')}: <span class="font-mono">${cap.current_dim}</span>
        </p>` : '';

    // Opt-in capabilities get an on/off switch above the pickers. Everything
    // below it is hidden while off, so a disabled fallback never looks like an
    // unconfigured one — it is simply not part of the setup.
    const toggleHtml = def.toggleable ? `
        <div id="cap-${def.id}-toggle-wrap" class="flex items-center justify-between gap-3">
            <label class="text-sm font-medium text-slate-600 dark:text-slate-400">${t('models_fallback_enable')}</label>
            <button type="button" id="cap-${def.id}-toggle" role="switch"
                    aria-checked="${cap.enabled ? 'true' : 'false'}"
                    onclick="toggleCapabilityEnabled('${def.id}')"
                    class="relative inline-flex h-5 w-9 flex-shrink-0 items-center rounded-full transition-colors cursor-pointer ${cap.enabled ? 'bg-primary-500' : 'bg-slate-200 dark:bg-slate-700'}">
                <span class="inline-block h-3.5 w-3.5 rounded-full bg-white shadow transition-transform ${cap.enabled ? 'translate-x-[18px]' : 'translate-x-[3px]'}"></span>
            </button>
        </div>` : '';

    // Footer layout: a "hint slot" (filled later by renderCapabilityHints for
    // auto-mode cards) sits on the left while status + save stay anchored on
    // the right. Keeping them on the same row means the save button hugs the
    // inputs above instead of being pushed down by a separate hint line.
    const footer = `
        <div class="flex items-center justify-between gap-3 pt-1">
            <div data-cap-hint="${def.id}" class="flex-1 min-w-0"></div>
            <div class="flex items-center gap-3 flex-shrink-0">
                <span id="cap-${def.id}-status" class="text-xs text-primary-500 opacity-0 transition-opacity duration-300"></span>
                <button onclick="saveCapability('${def.id}')"
                        class="px-4 py-2 rounded-lg bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium
                               cursor-pointer transition-colors duration-150 disabled:opacity-50 disabled:cursor-not-allowed">
                    ${t('save')}
                </button>
            </div>
        </div>`;

    // Pickers live in their own wrapper so a disabled opt-in capability can
    // hide them as a group (the toggle itself stays visible above). The
    // wrapper carries its own `space-y-4` because the body's `space-y-4` only
    // applies to *direct* children: without it the provider/model rows would
    // collapse against each other (and against the label above them).
    const pickersHtml = `<div id="cap-${def.id}-pickers" class="space-y-4">${providerHtml + modelHtml + dimHtml}</div>`;
    body.innerHTML = toggleHtml + pickersHtml + footer;

    // TTS: mount reply-mode above provider; defer off-mode toggle to the end.
    if (def.id === 'tts') {
        renderVoiceReplyMode(body, cap.reply_mode || 'off', { skipVisibilityToggle: true });
        // Voice-timbre picker depends on provider+model; rebuilt by callbacks.
        const modelWrap = body.querySelector(`#cap-${def.id}-model-wrap`);
        if (modelWrap) {
            const voiceWrap = document.createElement('div');
            voiceWrap.id = `cap-${def.id}-voice-wrap`;
            voiceWrap.innerHTML = `
                <label class="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-1.5">${t('models_voice')}</label>
                <div id="cap-${def.id}-voice" class="cfg-dropdown" tabindex="0">
                    <div class="cfg-dropdown-selected">
                        <span class="cfg-dropdown-text">--</span>
                        <i class="fas fa-chevron-down cfg-dropdown-arrow"></i>
                    </div>
                    <div class="cfg-dropdown-menu"></div>
                </div>
                <div id="cap-${def.id}-voice-custom-wrap" class="hidden mt-2">
                    <input id="cap-${def.id}-voice-custom" type="text"
                           class="w-full px-3 py-2 text-sm rounded-md border border-slate-200 dark:border-slate-700
                                  bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200
                                  placeholder:text-slate-400 dark:placeholder:text-slate-500
                                  focus:outline-none focus:ring-2 focus:ring-primary-500"
                           placeholder="voice id" />
                </div>
            `;
            modelWrap.parentNode.insertBefore(voiceWrap, modelWrap.nextSibling);
        }
    }

    // `body` is still detached from `document`; scope lookups locally.
    const provDd = body.querySelector(`#cap-${def.id}-provider`);
    // Strip private fields before handing to the generic initDropdown helper.
    const ddOpts = providerOpts.map(o => ({ value: o.value, label: o.label }));

    let pendingProvider = null;
    if (pendingCapabilitySelection
            && pendingCapabilitySelection.capabilityId === def.id
            && providerOpts.some(o => o.value === pendingCapabilitySelection.providerId)) {
        pendingProvider = pendingCapabilitySelection.providerId;
        pendingCapabilitySelection = null;
    }

    // Auto strategy => leave empty sentinel selected. `suggested_provider`
    // is a UI-only preselect (not persisted until the user clicks Save).
    // No current + no suggestion => leave unselected with a placeholder.
    //
    // Pending-config takes priority over both "auto" and "pick provider":
    // when no real (non-sentinel) configured option exists, surfacing
    // "auto" or "pick" misleads the user — there's nothing to auto-route
    // to or pick from. Force a "待配置" placeholder instead so all
    // capabilities behave consistently on a fresh environment.
    const hasConfiguredOpt = providerOpts.some(o => !o._isAuto && o._configured);
    const noSelectionAndNoHint = !cap.current_provider && !cap.suggested_provider;
    let initialProviderValue;
    let dropdownPlaceholder = null;
    if (!hasConfiguredOpt) {
        initialProviderValue = '';
        dropdownPlaceholder = { placeholder: t('models_pending_config') };
    } else {
        initialProviderValue = pendingProvider
            ? pendingProvider
            : ((cap.strategy === 'auto' && capabilitySupportsAuto(def.id))
                ? ''
                : (cap.current_provider
                    || cap.suggested_provider
                    || (noSelectionAndNoHint ? '' : (ddOpts[0] && ddOpts[0].value))
                    || ''));
        if (noSelectionAndNoHint) {
            dropdownPlaceholder = { placeholder: t('models_pick_provider') };
        }
    }
    // Seed the "provider active before the last switch" tracker so the very
    // first vendor switch can still stash the initial provider's custom model.
    capabilityLastProviderId[def.id] = initialProviderValue;
    // If the initially selected model is a custom one, remember it against the
    // initial provider so a switch-away-and-back keeps it too.
    if (initialProviderValue && cap.current_model) {
        const provList = (cap.provider_models && cap.provider_models[initialProviderValue])
            || (initialProviderValue.startsWith('custom:') && cap.provider_models && cap.provider_models['custom'])
            || [];
        const presetValues = provList.map(e => (typeof e === 'string' ? e : e.value));
        if (!presetValues.includes(cap.current_model)) {
            capabilityCustomModelMemory[`${def.id}:${initialProviderValue}`] = cap.current_model;
        }
    }
    initDropdown(
        provDd,
        ddOpts,
        initialProviderValue,
        (value) => onCapabilityProviderChange(def, value, body),
        dropdownPlaceholder,
    );
    decorateCapabilityProviderDropdown(def, provDd, providerOpts);

    if (def.needsModel) {
        rebuildCapabilityModelDropdown(def, initialProviderValue, cap.current_model || '', body);
        // Embedding: hide model picker when no provider is selected.
        const showModel = def.id === 'embedding' ? initialProviderValue !== '' :
            (initialProviderValue !== '' || !capabilitySupportsAuto(def.id));
        setCapabilityModelPickerVisible(def, showModel, body);
    }

    if (def.id === 'tts') {
        rebuildCapabilityVoiceDropdown(
            initialProviderValue,
            cap.current_voice || '',
            body,
            cap.current_model || ''
        );
    }

    // Inject auto/router-pending hint banners before the action footer.
    renderCapabilityHints(def, cap, body, initialProviderValue);

    // Opt-in capabilities start collapsed when disabled, so an inactive
    // fallback reads as "off" rather than as a half-configured capability.
    if (def.toggleable) {
        _setCapabilityPickersVisible(def, body, !!cap.enabled);
    }

    if (def.id === 'tts') {
        _setTtsConfigVisible(body, (cap.reply_mode || 'off') !== 'off');
    }
}

// TTS reply-policy dropdown (off / voice_if_voice / always). Persists on
// change. When off, hides the rest of the TTS card.
function renderVoiceReplyMode(host, currentMode, options) {
    options = options || {};
    const opts = [
        { value: 'off',            label: t('voice_reply_off') },
        { value: 'voice_if_voice', label: t('voice_reply_if_voice') },
        { value: 'always',         label: t('voice_reply_always') },
    ];
    const wrap = document.createElement('div');
    wrap.id = 'voice-reply-mode-wrap';
    wrap.innerHTML = `
        <label class="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-1.5">${t('voice_reply_mode_label')}</label>
        <div id="voice-reply-mode-dd" class="cfg-dropdown" tabindex="0">
            <div class="cfg-dropdown-selected">
                <span class="cfg-dropdown-text">--</span>
                <i class="fas fa-chevron-down cfg-dropdown-arrow"></i>
            </div>
            <div class="cfg-dropdown-menu"></div>
        </div>
    `;
    host.prepend(wrap);

    const dd = wrap.querySelector('#voice-reply-mode-dd');
    const valid = ['off', 'voice_if_voice', 'always'];
    const initial = valid.includes(currentMode) ? currentMode : 'off';
    if (!options.skipVisibilityToggle) _setTtsConfigVisible(host, initial !== 'off');
    initDropdown(dd, opts, initial, (mode) => {
        if (!valid.includes(mode)) return;
        _setTtsConfigVisible(host, mode !== 'off');
        fetch('/api/models', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'set_voice_reply_mode', mode }),
        })
            .then(r => r.json())
            .then(data => {
                if (data && data.status === 'success') {
                    _ttsReadyPromise = null;  // force re-probe on next bubble
                }
            })
            .catch(() => {});
    });
}

// Show/hide everything in the TTS card below the reply-mode dropdown.
function _setTtsConfigVisible(host, visible) {
    if (!host) return;
    Array.from(host.children).forEach((child) => {
        if (child.id === 'voice-reply-mode-wrap') return;
        child.classList.toggle('hidden', !visible);
    });
}

// Toggle wrapper visibility instead of re-rendering so dropdown state survives.
function setCapabilityModelPickerVisible(def, visible, scope) {
    const root = scope || document;
    const wrap = root.querySelector(`#cap-${def.id}-model-wrap`);
    if (!wrap) return;
    wrap.classList.toggle('hidden', !visible);
}

function renderCapabilityHints(def, cap, body, currentProvider) {
    // Capabilities that can be in "auto" mode show a fallback hint right
    // under the inputs so users always know what'd actually be hit. The
    // image card additionally surfaces a "router pending" warning until the
    // standalone dispatcher lands.
    // The hint slot is co-located with the save button in the footer row
    // (see renderCapabilityBody) so the save button stays close to the
    // inputs above. We just rewrite the slot's innerHTML — emptying it
    // when the card leaves auto mode, or rendering a one-line hint when
    // it's in auto mode.
    const slot = body.querySelector(`[data-cap-hint="${def.id}"]`);
    if (!slot) return;
    slot.innerHTML = '';

    if (currentProvider !== '' || !capabilitySupportsAuto(def.id)) return;

    // The hint mirrors what the runtime would actually pick when in auto
    // mode. fallback_provider/model are pre-computed on the backend (see
    // _predict_vision_auto, _predict_image_auto) so we can trust them
    // here without re-implementing the provider chain.
    const fbProv = cap.fallback_provider || '';
    const fbModel = cap.fallback_model || '';
    if (!fbProv && !fbModel) return;
    // Show the vendor's display label (e.g. "LinkAI") instead of the raw
    // id ("linkai") when we know it. Falls back to the id when the
    // provider isn't in our vendor table (rare).
    const provMeta = modelsState.providers.find(p => p.id === fbProv);
    const fbProvLabel = (provMeta && localizedLabel(provMeta.label)) || fbProv;
    const fbText = fbModel ? `${fbProvLabel} / ${fbModel}` : fbProvLabel;
    slot.innerHTML = `
        <p class="flex items-center gap-1.5 text-xs text-slate-400 dark:text-slate-500 min-w-0">
            <i class="fas fa-circle-info text-[10px] flex-shrink-0"></i>
            <span class="flex-shrink-0">${t('models_auto_using')}</span>
            <span class="font-mono text-slate-500 dark:text-slate-400 truncate">${escapeHtml(fbText)}</span>
        </p>`;
}

function buildCapabilityProviderOptions(def, cap) {
    // Show ALL vendors in capability dropdowns so users can see at a glance
    // who's configured (green check) and who isn't (gray dot, click to set
    // up). The list order puts configured vendors first; clicking an
    // unconfigured row opens the vendor modal in-place. ASR/TTS engines that
    // aren't tracked by PROVIDER_MODELS (azure/baidu/google etc.) are treated
    // as "always available" — no credential gate.
    const knownProviderMap = {};
    modelsState.providers.forEach(p => { knownProviderMap[p.id] = p; });

    const explicitList = cap.providers && cap.providers.length ? cap.providers : null;
    let providerIds = explicitList ? explicitList.slice() : modelsState.providers.map(p => p.id);
    if (cap.current_provider && !providerIds.includes(cap.current_provider)) {
        providerIds = [cap.current_provider, ...providerIds];
    }

    const opts = providerIds.map(pid => {
        const meta = knownProviderMap[pid];
        const tracked = !!meta;
        const configured = !tracked || !!meta.configured;
        return {
            value: pid,
            label: (meta && localizedLabel(meta.label)) || pid,
            _tracked: tracked,
            _configured: configured,
        };
    });

    opts.sort((a, b) => {
        if (a._configured === b._configured) return 0;
        return a._configured ? -1 : 1;
    });

    // Capabilities with a fallback ("auto") strategy expose it as a sentinel
    // option pinned to the top of the list. We use empty-string as the auto
    // value so the existing save handler propagates it untouched to the
    // backend, which interprets "" as "fall back to the main model".
    // Skip the sentinel when no real vendor is configured — "auto" would
    // route to nothing useful and the renderer will show "待配置" instead.
    const hasAnyConfigured = opts.some(o => o._configured);
    if ((cap.strategy === 'auto' || cap.strategy === 'specified') && hasAnyConfigured) {
        if (capabilitySupportsAuto(def.id)) {
            opts.unshift({
                value: '',
                label: t('models_strategy_auto'),
                _tracked: false,
                _configured: true,
                _isAuto: true,
            });
        }
    }
    return opts;
}

function capabilitySupportsAuto(capId) {
    // Embedding is intentionally NOT here: runtime only auto-falls back to
    // OpenAI/LinkAI, so dressing it up as "auto" hides reality from users.
    return capId === 'image' || capId === 'vision';
}

// After initDropdown renders the capability provider menu, decorate each
// row with the right-aligned configuration cue:
//   - configured rows: nothing extra — the .active marker (a brand-green ✓)
//     already comes from initDropdown's selected-state CSS for the row the
//     user currently picked. Other configured rows show no chrome, mirroring
//     a plain "switch to this" selector.
//   - unconfigured rows: a subdued gear icon hints at "click to configure".
//     The row's whole click handler is swapped to launch the vendor modal
//     in place rather than selecting an unusable value.
function decorateCapabilityProviderDropdown(def, ddEl, opts) {
    if (!ddEl) return;
    const menu = ddEl.querySelector('.cfg-dropdown-menu');
    if (!menu) return;

    const optByValue = {};
    opts.forEach(o => { optByValue[o.value] = o; });

    menu.querySelectorAll('.cfg-dropdown-item').forEach(item => {
        const value = item.dataset.value;
        const opt = optByValue[value];
        if (!opt) return;
        item.classList.add('cap-provider-item');
        if (!opt._configured) item.classList.add('cap-provider-unconfigured');

        // Wrap the label so the trailing affordance lines up via flex:auto.
        const labelText = item.textContent;
        item.textContent = '';
        const labelEl = document.createElement('span');
        labelEl.className = 'cap-provider-label';
        labelEl.textContent = labelText;
        item.appendChild(labelEl);

        if (!opt._configured) {
            // Trailing gear icon as the "configure this vendor" affordance.
            const gear = document.createElement('i');
            gear.className = 'fas fa-gear cap-provider-gear';
            item.appendChild(gear);
        }

        if (!opt._configured && opt._tracked) {
            // Hijack the click: open the vendor modal instead of selecting
            // an unusable value, and remember which capability the user was
            // configuring so the post-save reload can preselect the vendor.
            const newItem = item.cloneNode(true);
            item.replaceWith(newItem);
            newItem.addEventListener('click', (e) => {
                e.stopPropagation();
                ddEl.classList.remove('open');
                openVendorModal(value, (savedProviderId) => {
                    pendingCapabilitySelection = {
                        capabilityId: def.id,
                        providerId: savedProviderId || value,
                    };
                    loadModelsView({ preserveScroll: true });
                });
            });
        }
    });
}

// Lightweight decorator for the "add vendor" modal's provider picker:
// every configured vendor row gets a trailing brand-green ✓ so the user can
// see at a glance who's already set up, without having to read each row.
// Unlike decorateCapabilityProviderDropdown we don't hijack clicks here —
// picking an unconfigured vendor in this modal *is* the intended action.
function decorateVendorModalPicker(ddEl, opts) {
    if (!ddEl) return;
    const menu = ddEl.querySelector('.cfg-dropdown-menu');
    if (!menu) return;

    const optByValue = {};
    opts.forEach(o => { optByValue[o.value] = o; });

    menu.querySelectorAll('.cfg-dropdown-item').forEach(item => {
        const opt = optByValue[item.dataset.value];
        if (!opt) return;
        // Tag the row so the global active-row ✓ rule is suppressed in CSS
        // (otherwise configured AND selected rows would render two checks).
        item.classList.add('vendor-picker-item');
        if (opt._isAddNew) {
            // "Custom" is an add-new action (multiple entries allowed),
            // so show a trailing + instead of the configured ✓.
            const plus = document.createElement('i');
            plus.className = 'fas fa-plus vendor-picker-add-mark';
            item.appendChild(plus);
            return;
        }
        if (!opt._configured) return;
        const check = document.createElement('i');
        check.className = 'fas fa-check vendor-picker-configured-mark';
        item.appendChild(check);
    });
}

function rebuildCapabilityModelDropdown(def, providerId, selectedModel, scope) {
    // `scope` lets the caller (renderCapabilityBody) target a still-detached
    // subtree. After the card is mounted, callers may pass `document` instead.
    const root = scope || document;
    const el = root.querySelector(`#cap-${def.id}-model`);
    if (!el) return;

    // Prefer the capability-scoped model list when the backend provides one
    // (vision / image). It reflects the models the runtime can actually
    // dispatch to for this capability, instead of the vendor's full chat-
    // model catalog. Fall back to the generic provider.models for chat /
    // embedding / tts where any vendor model is fair game.
    //
    // Entries may be plain strings or {value, hint} objects (image catalog
    // uses the latter to surface brand aliases like "Nano Banana 2" next to
    // the technical Gemini model id). We normalize to {value, label, hint}
    // before handing off to initDropdown.
    const cap = modelsState.capabilities[def.id] || {};
    const capModelMap = cap.provider_models || {};
    let rawList;
    if (capModelMap[providerId]) {
        rawList = capModelMap[providerId].slice();
    } else if (providerId.startsWith('custom:') && capModelMap['custom']) {
        // Expanded custom:<id> entries share the same preset model list
        rawList = capModelMap['custom'].slice();
    } else {
        const provider = modelsState.providers.find(p => p.id === providerId);
        rawList = (provider && provider.models) ? provider.models.slice() : [];
    }
    const modelValues = [];
    const opts = rawList.map(entry => {
        if (typeof entry === 'string') {
            modelValues.push(entry);
            return { value: entry, label: entry };
        }
        modelValues.push(entry.value);
        return { value: entry.value, label: entry.label || entry.value, hint: entry.hint || '' };
    });
    opts.push({ value: '__custom__', label: currentLang === 'zh' ? '自定义' : 'Custom' });

    let initialValue = selectedModel || '';
    if (initialValue && !modelValues.includes(initialValue)) {
        initialValue = '__custom__';
    }
    if (!initialValue && opts.length) initialValue = opts[0].value;

    initDropdown(el, opts, initialValue, (value) => {
        const customWrap = document.getElementById(`cap-${def.id}-model-custom-wrap`);
        if (customWrap) {
            if (value === '__custom__') {
                customWrap.classList.remove('hidden');
                const input = document.getElementById(`cap-${def.id}-model-custom`);
                if (input && !input.value) input.value = selectedModel || '';
            } else {
                customWrap.classList.add('hidden');
            }
        }
        // TTS voice catalog may be scoped per engine model (aggregating
        // gateways). Rebuild the voice picker whenever the model changes.
        if (def.id === 'tts') {
            const provDd = document.getElementById('cap-tts-provider');
            const provId = provDd ? getDropdownValue(provDd) : '';
            rebuildCapabilityVoiceDropdown(provId, '', null, value);
        }
    });

    const customWrap = root.querySelector(`#cap-${def.id}-model-custom-wrap`);
    if (customWrap) {
        if (initialValue === '__custom__') {
            customWrap.classList.remove('hidden');
            const input = root.querySelector(`#cap-${def.id}-model-custom`);
            if (input) input.value = selectedModel || '';
        } else {
            customWrap.classList.add('hidden');
        }
    }
}

// TTS-only: rebuild the voice timbre picker against the provider's
// curated voice list. Hidden when no provider is picked.
//
// Each voice entry may be:
//   - a bare string  (code = label)
//   - {value, label, hint?}   so we can show a friendly Chinese name
//     while persisting the raw API code that the runtime sends.
function rebuildCapabilityVoiceDropdown(providerId, selectedVoice, scope, modelId) {
    const root = scope || document;
    const wrap = root.querySelector(`#cap-tts-voice-wrap`);
    const el = root.querySelector(`#cap-tts-voice`);
    if (!wrap || !el) return;
    const cap = modelsState.capabilities.tts || {};
    const voicesByProvider = cap.provider_voices || {};
    let raw = (providerId && voicesByProvider[providerId]) || [];
    // Some providers (gateways) scope voices by engine model id.
    if (raw && !Array.isArray(raw) && typeof raw === 'object') {
        const activeModel = modelId
            || (root.querySelector(`#cap-tts-model`) ? getDropdownValue(root.querySelector(`#cap-tts-model`)) : '');
        raw = (activeModel && raw[activeModel]) || [];
    }
    if (!raw || raw.length === 0) {
        wrap.classList.add('hidden');
        return;
    }
    wrap.classList.remove('hidden');
    // Voice picker: friendly name on the left, raw API code as right-hand
    // hint. Persisted/sent value is always the raw code.
    const codes = [];
    const opts = raw.map(entry => {
        if (typeof entry === 'string') {
            codes.push(entry);
            return { value: entry, label: entry };
        }
        codes.push(entry.value);
        const code = entry.value;
        const desc = entry.hint || entry.label || code;
        return {
            value: code,
            label: desc,
            hint: desc === code ? '' : code,
        };
    });
    opts.push({ value: '__custom__', label: currentLang === 'zh' ? '自定义' : 'Custom' });

    // Off-catalog values route through the custom branch.
    let initial = selectedVoice || '';
    const isCustom = initial && !codes.includes(initial);
    if (isCustom) initial = '__custom__';
    if (!initial) initial = codes[0];

    initDropdown(el, opts, initial, (value) => {
        const customWrap = root.querySelector(`#cap-tts-voice-custom-wrap`);
        if (!customWrap) return;
        if (value === '__custom__') {
            customWrap.classList.remove('hidden');
            const input = root.querySelector(`#cap-tts-voice-custom`);
            if (input && !input.value) input.value = isCustom ? selectedVoice : '';
        } else {
            customWrap.classList.add('hidden');
        }
    });

    const customWrap = root.querySelector(`#cap-tts-voice-custom-wrap`);
    if (customWrap) {
        if (initial === '__custom__') {
            customWrap.classList.remove('hidden');
            const input = root.querySelector(`#cap-tts-voice-custom`);
            if (input) input.value = isCustom ? selectedVoice : '';
        } else {
            customWrap.classList.add('hidden');
        }
    }
}

function onCapabilityProviderChange(def, providerId, scope) {
    if (def.needsModel) {
        // Before rebuilding the model picker for the newly picked provider,
        // stash the custom model the user had typed under the *previous*
        // provider, so switching back to it later restores that value.
        const prevProvider = capabilityLastProviderId[def.id];
        if (prevProvider && prevProvider !== providerId) {
            const prevDd = document.getElementById(`cap-${def.id}-model`);
            const prevInput = document.getElementById(`cap-${def.id}-model-custom`);
            if (prevDd && prevInput && getDropdownValue(prevDd) === '__custom__') {
                const typed = prevInput.value.trim();
                if (typed) capabilityCustomModelMemory[`${def.id}:${prevProvider}`] = typed;
            }
        }
        capabilityLastProviderId[def.id] = providerId;

        // Embedding: hide model picker when no provider is selected.
        const showModel = def.id === 'embedding' ? providerId !== '' :
            !(providerId === '' && capabilitySupportsAuto(def.id));
        if (showModel) {
            // Restore a remembered custom model for this provider (if any) so
            // switching vendors and back does not drop it.
            const remembered = capabilityCustomModelMemory[`${def.id}:${providerId}`] || '';
            rebuildCapabilityModelDropdown(def, providerId, remembered, scope);
        }
        setCapabilityModelPickerVisible(def, showModel, scope);
    }
    if (def.id === 'tts') {
        rebuildCapabilityVoiceDropdown(providerId, '', scope);
    }
    const body = scope || document.querySelector(`[data-cap-body="${def.id}"]`);
    if (body) {
        const cap = modelsState.capabilities[def.id] || {};
        renderCapabilityHints(def, cap, body, providerId);
    }
}

function getCapabilityModelValue(def) {
    if (!def.needsModel) return '';
    const dd = document.getElementById(`cap-${def.id}-model`);
    if (!dd) return '';
    const v = getDropdownValue(dd);
    if (v === '__custom__') {
        const input = document.getElementById(`cap-${def.id}-model-custom`);
        return input ? input.value.trim() : '';
    }
    return v || '';
}

// Opt-in capabilities: show/hide the pickers under the toggle without
// touching config. Mirrors the TTS reply-mode pattern — the toggle itself is
// pure UI state until the user presses Save.
function _setCapabilityPickersVisible(def, body, visible) {
    const wrap = body.querySelector(`#cap-${def.id}-pickers`);
    if (wrap) wrap.classList.toggle('hidden', !visible);
}

// Clicking the toggle flips the local switch. Persisting is a separate act
// (Save), so a user can flip back without ever writing to config.
function toggleCapabilityEnabled(capId) {
    const def = capabilityDefById(capId);
    if (!def || !def.toggleable) return;
    const cap = modelsState.capabilities[capId] || {};
    cap.enabled = !cap.enabled;
    modelsState.capabilities[capId] = cap;
    const btn = document.getElementById(`cap-${capId}-toggle`);
    if (btn) {
        btn.setAttribute('aria-checked', cap.enabled ? 'true' : 'false');
        btn.classList.toggle('bg-primary-500', cap.enabled);
        btn.classList.toggle('bg-slate-200', !cap.enabled);
        btn.classList.toggle('dark:bg-slate-700', !cap.enabled);
        const knob = btn.querySelector('span');
        if (knob) {
            knob.classList.toggle('translate-x-[18px]', cap.enabled);
            knob.classList.toggle('translate-x-[3px]', !cap.enabled);
        }
    }
    // Same lookup the rest of the file uses for a capability body.
    const body = document.querySelector(`[data-cap-body="${capId}"]`);
    if (body) _setCapabilityPickersVisible(def, body, cap.enabled);
}

function saveCapability(capId) {
    const def = capabilityDefById(capId);
    if (!def || !def.editable) return;
    // Search has its own form (strategy + provider, no model picker).
    if (capId === 'search') { saveSearchCapability(); return; }
    const provDd = document.getElementById(`cap-${capId}-provider`);
    let provider = provDd ? getDropdownValue(provDd) : '';
    // When the user is in auto mode (provider == ""), the model picker is
    // hidden and any value left in it is stale; persist an empty model so
    // the backend treats this as "fall back to the runtime chain".
    const isAuto = provider === '' && capabilitySupportsAuto(capId);
    // Embedding without a provider similarly means "cleared" — don't leak
    // a stale model value into config.
    // Declared with `let` because the chat fallback branch clears both values
    // below: it posts an ordered chain instead of a single provider/model pair.
    let model = (isAuto || (capId === 'embedding' && !provider)) ? '' : getCapabilityModelValue(def);
    // TTS carries an extra voice timbre (supports free-text custom ids).
    let voice = '';
    if (capId === 'tts' && !isAuto) {
        const voiceDd = document.getElementById(`cap-${capId}-voice`);
        voice = voiceDd ? getDropdownValue(voiceDd) : '';
        if (voice === '__custom__') {
            const input = document.getElementById(`cap-${capId}-voice-custom`);
            voice = input ? input.value.trim() : '';
        }
    }

    // Embedding changes invalidate any pre-existing vector index because
    // dimensions / vendor differ. Gate the save behind a confirm, and on
    // success surface a dedicated info dialog telling the user how to
    // rebuild — both via the in-app custom dialog, not the native alert.
    if (capId === 'embedding') {
        const cap = modelsState.capabilities[capId] || {};
        const before = (cap.current_provider || '').trim();
        const after = (provider || '').trim();
        if (before !== after) {
            showConfirmDialog({
                title: t('models_embedding_change_title'),
                message: t('models_embedding_change_msg'),
                okText: t('save'),
                cancelText: t('cancel'),
                onConfirm: () => _persistCapability(capId, provider, model, () => {
                    showConfirmDialog({
                        title: t('models_embedding_saved_title'),
                        message: t('models_embedding_saved_msg'),
                        okText: t('models_embedding_saved_ok'),
                        hideCancel: true,
                        onConfirm: () => {
                            navigateTo('chat');
                            // Defer focus + value set: navigateTo may
                            // re-render the chat panel; setting value before
                            // the input is mounted would be lost.
                            setTimeout(() => {
                                const input = document.getElementById('chat-input');
                                if (!input) return;
                                input.value = '/memory rebuild-index';
                                input.focus();
                                // Trigger any input listeners (autosize, send-button enable, etc.)
                                input.dispatchEvent(new Event('input', { bubbles: true }));
                            }, 60);
                        },
                    });
                }),
            });
            return;
        }
    }
    // Opt-in capabilities persist their on/off switch alongside the pickers.
    // It is sent even when turning off, so a broken entry can always be
    // cleared — and the backend refuses to enable a half-filled one.
    let enabled = undefined;
    if (def.toggleable) {
        const cap = modelsState.capabilities[capId] || {};
        enabled = !!cap.enabled;
    }
    // The chat fallback is edited inside a modal; close it once the save
    // lands so the user drops straight back to the models page (already
    // reloaded by _persistCapability, which refreshes the main-card badge).
    const onAfterSuccess = capId === 'chat_fallback' ? closeChatFallbackModal : undefined;
    // The fallback is an ordered chain rather than one provider/model pair,
    // so it posts the rows the modal is showing instead of the pickers.
    //
    // Sync first: the draft only records a row when it is added, removed or
    // moved, so a provider/model picked in a dropdown afterwards still lives
    // in the DOM alone. Saving without this would persist the row's seed
    // value — silently discarding whatever the user actually chose.
    let chain = undefined;
    if (capId === 'chat_fallback') {
        _syncFallbackChainDraft();
        chain = fallbackChainDraft.map(l => ({ provider: l.provider, model: l.model }));
        provider = '';
        model = '';
    }
    _persistCapability(capId, provider, model, onAfterSuccess, { voice, enabled, chain });
}

function _persistCapability(capId, provider, model, onAfterSuccess, extras) {
    const payload = { action: 'set_capability', capability: capId, provider_id: provider, model: model };
    if (extras && extras.voice !== undefined) payload.voice = extras.voice;
    // Opt-in capabilities (the chat fallback) carry their on/off switch.
    if (extras && extras.enabled !== undefined) payload.enabled = extras.enabled;
    // Only the chat fallback carries an ordered chain; every other capability
    // keeps sending the single provider/model pair above.
    if (extras && extras.chain !== undefined) payload.chain = extras.chain;
    fetch('/api/models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    }).then(r => r.json()).then(data => {
        if (data.status === 'success') {
            // Flash "Saved" before reload so the status survives the rebuild.
            showStatus(`cap-${capId}-status`, 'models_save_success', false);
            setTimeout(() => {
                loadModelsView({ preserveScroll: true });
                if (onAfterSuccess) onAfterSuccess();
            }, 400);
        } else {
            showStatus(`cap-${capId}-status`, 'models_save_failed', true);
        }
    }).catch(() => showStatus(`cap-${capId}-status`, 'models_save_failed', true));
}

// ---------- Vendor credential modal ------------------------------------

let vendorModalState = { providerId: '', onSaved: null };

function openVendorModal(providerId, onSaved) {
    vendorModalState = { providerId: providerId || '', onSaved: onSaved || null };

    const overlay = document.getElementById('vendor-modal-overlay');
    const titleEl = document.getElementById('vendor-modal-title');
    const subEl = document.getElementById('vendor-modal-subtitle');
    const pickerWrap = document.getElementById('vendor-modal-picker-wrap');
    const baseWrap = document.getElementById('vendor-modal-base-wrap');
    const baseInput = document.getElementById('vendor-modal-base');
    const baseHint = document.getElementById('vendor-modal-base-hint');
    const keyInput = document.getElementById('vendor-modal-key');
    const clearBtn = document.getElementById('vendor-modal-clear');

    // Reset any leftover status (e.g. previous "Saved" message)
    const statusEl = document.getElementById('vendor-modal-status');
    if (statusEl) {
        statusEl.textContent = '';
        statusEl.classList.add('opacity-0');
    }

    if (!providerId) {
        // Add flow — show provider picker, default to the first unconfigured one.
        // We render every configured vendor with a trailing green ✓ via the
        // dropdown decorator, mirroring the visual language used by the
        // capability provider dropdowns. The .active row already shows the
        // currently selected vendor via its own background highlight, so we
        // intentionally suppress the global active-row ✓ for this picker
        // (see CSS) — otherwise configured + selected rows would show two.
        // Expanded custom provider cards ("custom:<id>") are edited via their
        // dedicated modal, so they are excluded from this picker. Picking the
        // "custom" entry creates a *new* custom provider via that modal —
        // this is how multiple OpenAI-compatible endpoints are added.
        const builtinProviders = modelsState.providers.filter(p => !isCustomProviderCard(p));
        const unconfigured = builtinProviders.filter(p => !p.configured);

        // Every built-in is already configured: there is nothing to add here,
        // so go straight to the custom-provider modal and never show this one.
        // (Doing it via a "default to custom" pick would leave this overlay
        // visible behind the custom one — two stacked modals.)
        if (!unconfigured.length) {
            openCustomProviderModal('');
            return;
        }

        const pickerOpts = builtinProviders.map(p => ({
            value: p.id,
            label: localizedLabel(p.label),
            _configured: !!p.configured,
        }));
        // In multi-provider mode the backend replaces the bare "custom" card
        // with the expanded ones; re-add it here so the entry stays available.
        if (!pickerOpts.some(o => o.value === 'custom')) {
            pickerOpts.push({ value: 'custom', label: t('models_custom_vendor_label'), _configured: false });
        }
        // "Custom" always behaves as an add-new action (multiple entries
        // allowed), so it shows a + mark instead of the configured ✓.
        pickerOpts.forEach(o => { if (o.value === 'custom') { o._isAddNew = true; o._configured = false; } });
        const defaultId = unconfigured[0].id;
        pickerWrap.classList.remove('hidden');
        const pickerEl = document.getElementById('vendor-modal-picker');
        const onPick = (val) => {
            if (val === 'custom') {
                // "Custom" in the add flow always creates a new
                // OpenAI-compatible provider entry via the dedicated modal
                // (name + base + key), supporting multiple custom endpoints.
                closeVendorModal();
                openCustomProviderModal('');
                return;
            }
            fillVendorModalForProvider(val);
        };
        initDropdown(pickerEl, pickerOpts, defaultId, onPick);
        decorateVendorModalPicker(pickerEl, pickerOpts);
        onPick(defaultId);
    } else {
        pickerWrap.classList.add('hidden');
        fillVendorModalForProvider(providerId);
    }

    overlay.classList.remove('hidden');

    document.getElementById('vendor-modal-cancel').onclick = closeVendorModal;
    document.getElementById('vendor-modal-save').onclick = saveVendorModal;
    // Catalog section controls. Assigned (not addEventListener) so a repeated
    // open cannot stack duplicate handlers.
    bindCatalogControls('vendor-modal', vendorModalState.providerId);
    clearBtn.onclick = clearVendorModal;

    // Once the user edits the masked value, drop the "masked sentinel" dataset
    // so the save handler treats their input as a real new key. We compare on
    // the next tick because keydown fires before the new char lands in .value.
    keyInput.oninput = function () {
        if (keyInput.dataset.masked === '1' && keyInput.value !== keyInput.dataset.maskedVal) {
            keyInput.dataset.masked = '';
        }
    };

    function onOverlayClick(e) {
        if (e.target === overlay) {
            closeVendorModal();
            overlay.removeEventListener('click', onOverlayClick);
        }
    }
    overlay.addEventListener('click', onOverlayClick);
    keyInput.focus();
}

function fillVendorModalForProvider(providerId) {
    const meta = modelsState.providers.find(p => p.id === providerId);
    if (!meta) return;
    document.getElementById('vendor-modal-title').textContent = localizedLabel(meta.label);
    document.getElementById('vendor-modal-subtitle').textContent = meta.id;

    // LinkAI aggregates many vendors, so only for it do we surface a link to its
    // console for creating/managing the aggregated key. Other providers manage
    // their keys on their own sites.
    const manageKey = document.getElementById('vendor-modal-manage-key');
    if (manageKey) manageKey.classList.toggle('hidden', meta.id !== 'linkai');

    // ----- API Base -----
    // Always reflect the *current effective* base as the input value so the
    // user can see (and edit) what's in use today. Placeholder is reserved
    // strictly for the "not yet typed anything" state and shows the official
    // default — never mixed with the actual value.
    const baseWrap = document.getElementById('vendor-modal-base-wrap');
    const baseInput = document.getElementById('vendor-modal-base');
    const baseHint = document.getElementById('vendor-modal-base-hint');
    if (meta.api_base_field) {
        baseWrap.classList.remove('hidden');
        baseInput.placeholder = meta.api_base_default || meta.api_base_placeholder || '';
        baseInput.value = meta.api_base || '';
        baseHint.classList.add('hidden');
    } else {
        baseWrap.classList.add('hidden');
        baseInput.value = '';
    }

    // ----- API Key -----
    // For configured vendors, surface the masked key as the input *value* so
    // it shows up in the same dark text as a real entry — making "configured"
    // visually unambiguous. The masked form (e.g. "sk-r***zRU") is also a
    // sentinel: the save handler treats untouched masked input as "no change".
    const keyInput = document.getElementById('vendor-modal-key');
    if (meta.configured && meta.api_key_masked) {
        keyInput.value = meta.api_key_masked;
        keyInput.dataset.masked = '1';
        keyInput.dataset.maskedVal = meta.api_key_masked;
        keyInput.placeholder = '';
    } else {
        keyInput.value = '';
        keyInput.dataset.masked = '';
        keyInput.dataset.maskedVal = '';
        keyInput.placeholder = 'sk-...';
    }

    const clearBtn = document.getElementById('vendor-modal-clear');
    clearBtn.classList.toggle('hidden', !meta.configured);

    // Model catalog rows belong to the provider, so they load with it.
    fillCatalogForProvider('vendor-modal', providerId);

    vendorModalState.providerId = providerId;
}

function closeVendorModal() {
    document.getElementById('vendor-modal-overlay').classList.add('hidden');
}

// ---------- Model catalog editor (advanced, optional) -------------------
//
// A provider's catalog REPLACES its preset model list, so the editor is opt-in:
// rows only exist once the user adds them (or seeds them from the presets with
// the "restore presets" action). An empty row set is left untouched on save —
// it must never silently overwrite a working preset list.
//
// The same rows are offered by two modals — the built-in vendor modal and the
// custom (OpenAI-compatible) provider modal — so every helper takes an element
// id prefix instead of hardcoding one.

// Mirrors models/model_catalog.py VALID_CAPABILITIES. "text" drives the main
// model dropdown, the rest route a model into the matching tool position.
const MODEL_CATALOG_CAPABILITIES = ['text', 'vision', 'video', 'image', 'embedding', 'asr', 'tts'];

const MODEL_CATALOG_TAG_KEYS = {
    text: 'models_tag_chat',
    vision: 'models_tag_vision',
    video: 'models_tag_video',
    image: 'models_tag_image',
    embedding: 'models_tag_embedding',
    asr: 'models_tag_asr',
    tts: 'models_tag_tts',
};

// Capabilities with no notion of a text budget: an embedding model is scored
// on dimensions and a TTS/ASR one on audio, so offering "context window" for
// them would invite values that mean nothing.
const MODEL_CATALOG_UNBUDGETED = ['embedding', 'image', 'asr', 'tts'];

// Draft rows keyed by modal prefix, so the two editors never share state.
const catalogDrafts = {};

function _catalogRows(prefix) {
    if (!catalogDrafts[prefix]) catalogDrafts[prefix] = [];
    return catalogDrafts[prefix];
}

function _catalogCapLabel(cap) {
    const key = MODEL_CATALOG_TAG_KEYS[cap];
    return key ? t(key) : cap;
}

/** Render the draft rows for one modal. Each row edits one model entry. */
function renderCatalogRows(prefix) {
    const draft = _catalogRows(prefix);
    const rows = document.getElementById(prefix + '-catalog-rows');
    if (!rows) return;
    rows.innerHTML = draft.map((entry, idx) => `
        <div class="rounded-lg border border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-white/5 p-2.5">
            <div class="flex items-center gap-2 mb-2">
                <input type="text" value="${escapeHtml(entry.name || '')}"
                       placeholder="${escapeHtml(t('models_catalog_name_ph'))}"
                       oninput="updateCatalogRow('${prefix}', ${idx}, 'name', this.value)"
                       class="flex-1 min-w-0 px-2 py-1.5 rounded border border-slate-200 dark:border-slate-600
                              bg-white dark:bg-white/5 text-xs text-slate-800 dark:text-slate-100
                              focus:outline-none focus:border-primary-500 font-mono transition-colors">
                <button type="button" onclick="removeCatalogRow('${prefix}', ${idx})"
                        title="${escapeHtml(t('delete'))}"
                        class="flex-shrink-0 w-7 h-7 flex items-center justify-center rounded
                               text-slate-400 dark:text-slate-500 hover:text-red-500 hover:bg-red-50
                               dark:hover:bg-red-900/20 cursor-pointer transition-colors">
                    <i class="fas fa-trash-can text-[11px]"></i>
                </button>
            </div>
            <div class="flex flex-wrap gap-1.5 mb-2">
                ${MODEL_CATALOG_CAPABILITIES.map(cap => {
                    const on = (entry.capabilities || []).includes(cap);
                    return `<button type="button" onclick="toggleCatalogCap('${prefix}', ${idx}, '${cap}')"
                            class="px-1.5 py-0.5 rounded text-[10px] font-medium cursor-pointer transition-colors
                                   ${on
                                       ? 'bg-primary-100 dark:bg-primary-900/40 text-primary-600 dark:text-primary-400'
                                       : 'bg-slate-200/60 dark:bg-white/10 text-slate-500 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-white/20'}">
                            ${escapeHtml(_catalogCapLabel(cap))}</button>`;
                }).join('')}
            </div>
            ${(() => {
                // A model tagged only for unbudgeted work (embedding, TTS, ...)
                // has no window/output to configure — showing the inputs would
                // just invite meaningless numbers.
                const caps = entry.capabilities || [];
                const budgeted = caps.length === 0
                    || caps.some(c => !MODEL_CATALOG_UNBUDGETED.includes(c));
                if (!budgeted) {
                    return `<p class="text-[10px] text-slate-400 dark:text-slate-500">
                            <i class="fas fa-info-circle mr-1"></i>${escapeHtml(t('models_catalog_no_budget'))}</p>`;
                }
                return `<div class="grid grid-cols-2 gap-2">
                    <label class="block">
                        <span class="block text-[10px] text-slate-400 dark:text-slate-500 mb-0.5">${escapeHtml(t('models_catalog_window'))}</span>
                        <input type="number" min="1" value="${entry.context_window || ''}" placeholder="—"
                               oninput="updateCatalogRow('${prefix}', ${idx}, 'context_window', this.value)"
                               class="w-full px-2 py-1 rounded border border-slate-200 dark:border-slate-600
                                      bg-white dark:bg-white/5 text-xs text-slate-800 dark:text-slate-100
                                      focus:outline-none focus:border-primary-500 transition-colors">
                    </label>
                    <label class="block">
                        <span class="block text-[10px] text-slate-400 dark:text-slate-500 mb-0.5">${escapeHtml(t('models_catalog_output'))}</span>
                        <input type="number" min="1" value="${entry.max_output_tokens || ''}" placeholder="—"
                               oninput="updateCatalogRow('${prefix}', ${idx}, 'max_output_tokens', this.value)"
                               class="w-full px-2 py-1 rounded border border-slate-200 dark:border-slate-600
                                      bg-white dark:bg-white/5 text-xs text-slate-800 dark:text-slate-100
                                      focus:outline-none focus:border-primary-500 transition-colors">
                    </label>
                </div>`;
            })()}
        </div>`).join('');
}

function updateCatalogRow(prefix, idx, field, rawValue) {
    const entry = _catalogRows(prefix)[idx];
    if (!entry) return;
    if (field === 'name') {
        entry.name = rawValue;
        return;
    }
    // Numeric fields: keep "" (meaning "unset") rather than storing NaN/0.
    const n = parseInt(rawValue, 10);
    entry[field] = (rawValue === '' || Number.isNaN(n)) ? '' : n;
}

function toggleCatalogCap(prefix, idx, cap) {
    const entry = _catalogRows(prefix)[idx];
    if (!entry) return;
    const caps = entry.capabilities || [];
    const at = caps.indexOf(cap);
    if (at >= 0) caps.splice(at, 1); else caps.push(cap);
    entry.capabilities = caps;
    // The budget inputs are hidden for unbudgeted-only rows, but a hidden
    // field would still be sent — clear it so the stored entry can't carry a
    // window for a model that has no notion of one.
    const budgeted = caps.length === 0
        || caps.some(c => !MODEL_CATALOG_UNBUDGETED.includes(c));
    if (!budgeted) {
        entry.context_window = '';
        entry.max_output_tokens = '';
    }
    renderCatalogRows(prefix);
}

function addCatalogRow(prefix) {
    _catalogRows(prefix).push({
        name: '', capabilities: ['text'], context_window: '', max_output_tokens: '',
    });
    renderCatalogRows(prefix);
    const rows = document.getElementById(prefix + '-catalog-rows');
    const last = rows && rows.lastElementChild && rows.lastElementChild.querySelector('input');
    if (last) last.focus();
}

function removeCatalogRow(prefix, idx) {
    _catalogRows(prefix).splice(idx, 1);
    renderCatalogRows(prefix);
}

/** Reset the draft to the vendor's presets: discard every override and
 *  un-hide every removed preset, so the list is exactly what ships in code.
 *  Saving afterwards clears the provider's overlay entirely. */
function seedCatalogFromPresets(prefix, providerId) {
    const meta = modelsState.providers.find(p => p.id === providerId);
    const seed = (meta && meta.seed) || [];
    catalogDrafts[prefix] = seed.map(s => ({
        name: s.name,
        capabilities: (s.capabilities || []).slice(),
        context_window: s.context_window || '',
        max_output_tokens: s.max_output_tokens || '',
    }));
    renderCatalogRows(prefix);
}

/** Drop every row (back to presets). Applied on save, not immediately. */
function clearCatalogRows(prefix) {
    catalogDrafts[prefix] = [];
    renderCatalogRows(prefix);
}

/**
 * Collect the draft into the payload shape `save_catalog` expects.
 * Rows without a name are skipped — a nameless entry is rejected server-side
 * and would fail the whole save, so it is dropped before we send anything.
 */
function collectCatalogPayload(prefix) {
    return _catalogRows(prefix)
        .filter(e => (e.name || '').trim())
        .map(e => {
            const out = {
                name: e.name.trim(),
                capabilities: (e.capabilities || []).length ? e.capabilities : ['text'],
            };
            const cw = parseInt(e.context_window, 10);
            const mo = parseInt(e.max_output_tokens, 10);
            // Only send the numbers when set: an absent field means "fall back
            // to auto-detection", whereas 0 would be an invalid window.
            if (!Number.isNaN(cw) && cw > 0) out.context_window = cw;
            if (!Number.isNaN(mo) && mo > 0) out.max_output_tokens = mo;
            return out;
        });
}

// The preset base for one modal, kept so save can diff the draft against it
// (only rows that differ from a preset, or are new, are persisted; presets the
// user removed become tombstones). Keyed by modal prefix like the drafts.
const catalogSeeds = {};

/** Load one provider's effective model list (presets + overrides − removals)
 *  into a modal. The list is shown in full so editing one model can no longer
 *  wipe the rest — nothing is persisted until the user saves. */
function fillCatalogForProvider(prefix, providerId) {
    const meta = modelsState.providers.find(p => p.id === providerId);
    const effective = (meta && meta.effective) || (meta && meta.catalog) || [];
    catalogSeeds[prefix] = ((meta && meta.seed) || []).map(e => ({
        name: e.name || '',
        capabilities: (e.capabilities || []).slice(),
        context_window: e.context_window || '',
        max_output_tokens: e.max_output_tokens || '',
    }));
    catalogDrafts[prefix] = effective.map(e => ({
        name: e.name || '',
        capabilities: (e.capabilities || []).slice(),
        context_window: e.context_window || '',
        max_output_tokens: e.max_output_tokens || '',
    }));
    renderCatalogRows(prefix);

    // Always start collapsed so credentials stay the focus — the catalog is an
    // advanced, opt-in section the user expands deliberately.
    setCatalogSectionOpen(prefix, false);
}

/** Normalize seed rows into the same payload shape collectCatalogPayload emits,
 *  so the two can be compared for equality. */
function _normalizeEntries(rows) {
    return rows
        .filter(e => (e.name || '').trim())
        .map(e => {
            const out = {
                name: e.name.trim(),
                capabilities: (e.capabilities || []).length ? e.capabilities : ['text'],
            };
            const cw = parseInt(e.context_window, 10);
            const mo = parseInt(e.max_output_tokens, 10);
            if (!Number.isNaN(cw) && cw > 0) out.context_window = cw;
            if (!Number.isNaN(mo) && mo > 0) out.max_output_tokens = mo;
            return out;
        });
}

function setCatalogSectionOpen(prefix, open) {
    const body = document.getElementById(prefix + '-catalog-body');
    const caret = document.getElementById(prefix + '-catalog-caret');
    if (body) body.classList.toggle('hidden', !open);
    if (caret) caret.style.transform = open ? 'rotate(90deg)' : 'rotate(0deg)';
}

function toggleCatalogSection(prefix) {
    const body = document.getElementById(prefix + '-catalog-body');
    if (!body) return;
    setCatalogSectionOpen(prefix, body.classList.contains('hidden'));
}

/** Wire the section to one modal. Assigned (not addEventListener) so a
 *  repeated open cannot stack duplicate handlers. */
function bindCatalogControls(prefix, providerIdForSeed) {
    const toggle = document.getElementById(prefix + '-catalog-toggle');
    const add = document.getElementById(prefix + '-catalog-add');
    if (toggle) toggle.onclick = () => toggleCatalogSection(prefix);
    if (add) add.onclick = () => addCatalogRow(prefix);
    const seed = document.getElementById(prefix + '-catalog-seed');
    if (seed) seed.onclick = () => seedCatalogFromPresets(prefix, providerIdForSeed);
}

/**
 * Diff the draft against the provider's presets into the overlay the backend
 * stores: `overrides` (rows the user changed or added) and `hidden` (preset
 * names the user removed). A row identical to its preset is NOT persisted, so
 * that model keeps following the code-side metadata and a later constant bump
 * still reaches it.
 */
function diffCatalogAgainstSeed(prefix) {
    const seed = _normalizeEntries(catalogSeeds[prefix] || []);
    const draft = collectCatalogPayload(prefix);
    const seedByName = {};
    seed.forEach(e => { seedByName[e.name] = e; });
    const draftNames = new Set(draft.map(e => e.name));

    const overrides = draft.filter(e => {
        const preset = seedByName[e.name];
        // New model, or a preset the user edited: persist it. An unchanged
        // preset (deep-equal) is left out so it stays code-driven.
        return !preset || JSON.stringify(preset) !== JSON.stringify(e);
    });
    // Presets the user removed from the list become tombstones.
    const hidden = seed
        .map(e => e.name)
        .filter(name => !draftNames.has(name));
    return { overrides, hidden };
}

/**
 * Persist a modal's overlay, or do nothing when the draft still equals the
 * provider's effective list. Only the diff from the presets is written, so a
 * provider the user never opened is never touched.
 */
function saveCatalogForProvider(prefix, providerId) {
    const meta = modelsState.providers.find(p => p.id === providerId);
    const savedOverrides = (meta && meta.catalog) || [];
    const savedHidden = (meta && meta.hidden) || [];
    const { overrides, hidden } = diffCatalogAgainstSeed(prefix);

    const same = JSON.stringify(overrides) === JSON.stringify(_normalizeEntries(savedOverrides))
        && JSON.stringify([...hidden].sort()) === JSON.stringify([...savedHidden].sort());
    if (same) {
        return Promise.resolve(true);
    }
    // Empty overrides + empty hidden means "back to presets" — save_catalog
    // drops the provider's overlay for that, which is exactly the intent.
    return fetch('/api/models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            action: 'save_catalog', provider_id: providerId,
            models: overrides, hidden: hidden,
        }),
    }).then(r => r.json()).then(data => data.status === 'success').catch(() => false);
}

function saveVendorModal() {
    const providerId = vendorModalState.providerId;
    if (!providerId) return;
    const keyInput = document.getElementById('vendor-modal-key');
    const apiBase = document.getElementById('vendor-modal-base').value.trim();

    // Treat "input still equals the masked value we surfaced on open" as "no
    // change" — the backend uses missing/empty api_key to skip the field.
    let apiKey = keyInput.value.trim();
    const masked = keyInput.dataset.masked === '1';
    const maskedVal = keyInput.dataset.maskedVal || '';
    if (masked && apiKey === maskedVal) {
        apiKey = '';
    }

    if (!apiKey && !masked) {
        // First-time setup with no key entered → nudge the user.
        keyInput.focus();
        return;
    }

    const btn = document.getElementById('vendor-modal-save');
    btn.disabled = true;
    const payload = { action: 'set_provider', provider_id: providerId, api_base: apiBase };
    if (apiKey) payload.api_key = apiKey;
    fetch('/api/models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    }).then(r => r.json()).then(data => {
        if (data.status !== 'success') {
            btn.disabled = false;
            showStatus('vendor-modal-status', 'models_save_failed', true);
            return;
        }
        // Credentials are stored; now the catalog, which the backend keeps as
        // a separate document.
        return saveCatalogForProvider('vendor-modal', providerId).then(ok => {
            btn.disabled = false;
            if (!ok) {
                showStatus('vendor-modal-status', 'models_save_failed', true);
                return;
            }
            closeVendorModal();
            const onSaved = vendorModalState.onSaved;
            if (onSaved) {
                try { onSaved(providerId); } catch (e) { /* noop */ }
            } else {
                loadModelsView();
            }
        });
    }).catch(() => {
        btn.disabled = false;
        showStatus('vendor-modal-status', 'models_save_failed', true);
    });
}

function clearVendorModal() {
    const providerId = vendorModalState.providerId;
    if (!providerId) return;
    showConfirmDialog({
        title: t('models_clear_confirm_title'),
        message: t('models_clear_confirm_msg'),
        okText: t('models_clear_credential'),
        cancelText: t('cancel'),
        onConfirm: () => {
            fetch('/api/models', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'delete_provider', provider_id: providerId }),
            }).then(r => r.json()).then(data => {
                if (data.status === 'success') {
                    closeVendorModal();
                    loadModelsView();
                } else {
                    showStatus('vendor-modal-status', 'models_clear_failed', true);
                }
            }).catch(() => showStatus('vendor-modal-status', 'models_clear_failed', true));
        }
    });
}

// =====================================================================
// Custom (OpenAI-compatible) provider modal — add / edit
// =====================================================================
// State for the dedicated custom-provider modal. `editId` is empty when
// adding and set to the provider id when editing.
let customProviderModalState = { editId: '' };

function openCustomProviderModal(providerId) {
    const editing = !!providerId;
    customProviderModalState = { editId: editing ? providerId : '' };

    const card = editing ? getCustomProviderCards().find(p => p.custom_id === providerId) : null;

    const overlay = document.getElementById('custom-provider-modal-overlay');
    if (!overlay) return;

    document.getElementById('custom-provider-modal-title').textContent =
        editing ? t('models_custom_edit_title') : t('models_custom_add_title');

    const nameInput = document.getElementById('custom-provider-name');
    const baseInput = document.getElementById('custom-provider-base');
    const keyInput = document.getElementById('custom-provider-key');

    nameInput.value = card ? (card.custom_name || '') : '';
    baseInput.value = card ? (card.api_base || '') : '';

    // Surface the masked key as the value for configured providers so the
    // "already set" state is unambiguous; an untouched masked value means
    // "keep the existing key" on save (mirrors the vendor modal contract).
    if (card && card.configured && card.api_key_masked) {
        keyInput.value = card.api_key_masked;
        keyInput.dataset.masked = '1';
        keyInput.dataset.maskedVal = card.api_key_masked;
    } else {
        keyInput.value = '';
        keyInput.dataset.masked = '';
        keyInput.dataset.maskedVal = '';
    }
    keyInput.oninput = function () {
        if (keyInput.dataset.masked === '1' && keyInput.value !== keyInput.dataset.maskedVal) {
            keyInput.dataset.masked = '';
        }
    };

    const statusEl = document.getElementById('custom-provider-modal-status');
    if (statusEl) { statusEl.textContent = ''; statusEl.classList.add('opacity-0'); }

    overlay.classList.remove('hidden');
    document.getElementById('custom-provider-modal-cancel').onclick = closeCustomProviderModal;
    document.getElementById('custom-provider-modal-save').onclick = saveCustomProviderModal;

    // Delete is only available when editing an existing provider.
    const deleteBtn = document.getElementById('custom-provider-modal-delete');
    if (deleteBtn) {
        deleteBtn.classList.toggle('hidden', !editing);
        deleteBtn.onclick = editing ? () => deleteCustomProvider(providerId) : null;
    }

    function onOverlayClick(e) {
        if (e.target === overlay) {
            closeCustomProviderModal();
            overlay.removeEventListener('click', onOverlayClick);
        }
    }
    overlay.addEventListener('click', onOverlayClick);

    // Model catalog rows: a custom endpoint has no preset list, so these are
    // entirely user-authored. Only meaningful when editing an existing card —
    // a brand new card has no provider id yet, so its rows are saved right
    // after the provider is created (see saveCustomProviderModal).
    bindCatalogControls('custom-provider', editing ? 'custom:' + providerId : '');
    fillCatalogForProvider('custom-provider', editing ? 'custom:' + providerId : '');

    nameInput.focus();
}

function closeCustomProviderModal() {
    const overlay = document.getElementById('custom-provider-modal-overlay');
    if (overlay) overlay.classList.add('hidden');
}

function saveCustomProviderModal() {
    const name = document.getElementById('custom-provider-name').value.trim();
    const apiBase = document.getElementById('custom-provider-base').value.trim();
    const keyInput = document.getElementById('custom-provider-key');

    if (!name) {
        showStatus('custom-provider-modal-status', 'models_custom_name_required', true);
        document.getElementById('custom-provider-name').focus();
        return;
    }
    const editing = !!customProviderModalState.editId;
    if (!editing && !apiBase) {
        showStatus('custom-provider-modal-status', 'models_custom_base_required', true);
        document.getElementById('custom-provider-base').focus();
        return;
    }

    // Key handling (the custom provider's key is optional):
    //  - masked + untouched  => keep existing, omit from payload
    //  - non-empty typed value => set it
    //  - explicitly cleared on edit => send "" so the backend clears it
    const untouchedMasked =
        keyInput.dataset.masked === '1' && keyInput.value.trim() === (keyInput.dataset.maskedVal || '');
    const apiKey = untouchedMasked ? '' : keyInput.value.trim();

    const payload = {
        action: 'set_custom_provider',
        name: name,
        api_base: apiBase,
    };
    if (untouchedMasked) {
        // omit api_key entirely => backend keeps the stored key
    } else {
        // Send the value (possibly "") so an explicit clear is honored.
        payload.api_key = apiKey;
    }
    if (editing) payload.id = customProviderModalState.editId;

    const btn = document.getElementById('custom-provider-modal-save');
    btn.disabled = true;
    fetch('/api/models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    }).then(r => r.json()).then(data => {
        if (data.status !== 'success') {
            btn.disabled = false;
            showStatus('custom-provider-modal-status', 'models_save_failed', true);
            return;
        }
        // The backend assigns the id on create, so the catalog can only be
        // written once we know which provider it belongs to.
        const finalId = data.id ? 'custom:' + data.id : ('custom:' + customProviderModalState.editId);
        return saveCatalogForProvider('custom-provider', finalId).then(ok => {
            btn.disabled = false;
            if (!ok) {
                showStatus('custom-provider-modal-status', 'models_save_failed', true);
                return;
            }
            closeCustomProviderModal();
            loadModelsView();
        });
    }).catch(() => {
        btn.disabled = false;
        showStatus('custom-provider-modal-status', 'models_save_failed', true);
    });
}

function deleteCustomProvider(providerId) {
    showConfirmDialog({
        title: t('models_custom_delete_confirm_title'),
        message: t('models_custom_delete_confirm_msg'),
        okText: t('models_custom_delete'),
        cancelText: t('cancel'),
        onConfirm: () => {
            fetch('/api/models', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'delete_custom_provider', id: providerId }),
            }).then(r => r.json()).then(data => {
                if (data.status === 'success') {
                    closeCustomProviderModal();
                    loadModelsView();
                }
            }).catch(() => { /* noop */ });
        }
    });
}

// =====================================================================
// Channels View
// =====================================================================
let channelsData = [];
// Multi-Agent mode: the multi-instance-ready types (feishu) render one card per
// channel_instances record. These mirror the extra fields the API returns.
let channelInstancesView = [];
let multiInstanceTypes = [];
let channelsMultiAgent = false;

function isMultiInstanceType(name) {
    return channelsMultiAgent && multiInstanceTypes.indexOf(name) !== -1;
}

function loadChannelsView() {
    const container = document.getElementById('channels-content');
    if (!container) return Promise.resolve();
    container.innerHTML = `<div class="flex items-center gap-2 py-8 justify-center text-slate-400 dark:text-slate-500 text-sm">
        <i class="fas fa-spinner fa-spin text-xs"></i><span>Loading...</span></div>`;

    const roster = agentCatalog.length ? Promise.resolve() : loadAgentCatalog();
    return roster.then(() => fetch('/api/channels').then(r => r.json()).then(data => {
        if (data.status !== 'success') return;
        channelsData = data.channels || [];
        channelsMultiAgent = !!data.multi_agent;
        multiInstanceTypes = data.multi_instance_types || [];
        channelInstancesView = data.instances || [];
        renderActiveChannels();
    }).catch(() => {
        container.innerHTML = '<p class="text-sm text-red-400 py-8 text-center">Failed to load channels</p>';
    }));
}

// Build the list of cards to render. In multi-Agent mode the multi-instance
// types (feishu) contribute one card per channel_instances record (from
// data.instances); everything else contributes its single per-type card. Each
// item carries an `iid` (instance id) that keys its DOM and actions: for legacy
// per-type cards it is just the channel name.
function channelRenderList() {
    const list = [];
    channelsData.forEach(ch => {
        if (isMultiInstanceType(ch.name)) return;  // rendered from instances
        if (ch.active) list.push(Object.assign({}, ch, { iid: ch.name }));
    });
    if (channelsMultiAgent) {
        channelInstancesView.forEach(inst => {
            list.push(Object.assign({}, inst, { iid: inst.instance_id }));
        });
    }
    // Show WeChat cards first; keep every other card in its existing relative
    // order (stable sort: weixin -> 0, everything else -> 1).
    list.sort((a, b) => (a.name === 'weixin' ? 0 : 1) - (b.name === 'weixin' ? 0 : 1));
    return list;
}

function renderActiveChannels() {
    stopWeixinQrPoll();
    stopWeixinStatusPoll();
    const container = document.getElementById('channels-content');
    container.innerHTML = '';
    closeAddChannelPanel();

    const activeChannels = channelRenderList();

    if (activeChannels.length === 0) {
        container.innerHTML = `
            <div class="flex flex-col items-center justify-center py-20">
                <div class="w-16 h-16 rounded-2xl bg-blue-50 dark:bg-blue-900/20 flex items-center justify-center mb-4">
                    <i class="fas fa-tower-broadcast text-blue-400 text-xl"></i>
                </div>
                <p class="text-slate-500 dark:text-slate-400 font-medium">${t('channels_empty')}</p>
                <p class="text-sm text-slate-400 dark:text-slate-500 mt-1">${t('channels_empty_desc')}</p>
            </div>`;
        return;
    }

    activeChannels.forEach(ch => {
        const iid = ch.iid;
        const label = (typeof ch.label === 'object') ? (ch.label[currentLang] || ch.label.en) : ch.label;
        const card = document.createElement('div');
        card.className = 'bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10 p-6';
        card.id = `channel-card-${iid}`;

        const fieldsHtml = buildChannelFieldsHtml(iid, ch.fields || []);
        const hasFields = (ch.fields || []).length > 0;

        const weixinWaiting = ch.name === 'weixin' && ch.login_status && ch.login_status !== 'logged_in';
        const wecomNeedsCreds = ch.name === 'wecom_bot' && !_wecomBotHasCreds(ch);
        // 飞书 active 卡片渲染带 Tab 的 panel：手动填写 + 扫码重建（覆盖现有配置）
        const isFeishu = ch.name === 'feishu';
        // An instance card (multi-Agent feishu) shows the bound agent inline and
        // uses the instance id as its subtitle instead of the bare type name.
        const isInstance = isMultiInstanceType(ch.name) && !!ch.instance_id;
        let statusDot, statusText;
        if (weixinWaiting) {
            statusDot = 'bg-amber-400 animate-pulse';
            statusText = ch.login_status === 'scanned'
                ? `<span class="text-xs text-primary-500">${t('weixin_scan_scanned')}</span>`
                : `<span class="text-xs text-amber-500">${t('weixin_scan_waiting')}</span>`;
        } else if (wecomNeedsCreds) {
            statusDot = 'bg-amber-400 animate-pulse';
            statusText = `<span class="text-xs text-amber-500">${t('channels_connecting')}</span>`;
        } else {
            statusDot = 'bg-primary-400';
            statusText = `<span class="text-xs text-primary-500">${t('channels_connected')}</span>`;
        }

        card.innerHTML = `
            <div class="flex items-center gap-4${hasFields || weixinWaiting || wecomNeedsCreds || isFeishu || multiAgentMode() ? ' mb-5' : ''}">
                <div class="w-10 h-10 rounded-xl bg-${ch.color}-50 dark:bg-${ch.color}-900/20 flex items-center justify-center flex-shrink-0">
                    <i class="fas ${ch.icon} text-${ch.color}-500 text-base"></i>
                </div>
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2">
                        <span class="font-semibold text-slate-800 dark:text-slate-100">${escapeHtml(isInstance ? (ch.instance_name || label) : label)}</span>
                        ${isInstance ? `<button onclick="renameChannelInstance('${ch.name}', '${escapeHtml(iid)}')" title="${escapeHtml(t('channel_rename'))}"
                            class="text-slate-400 hover:text-primary-500 cursor-pointer transition-colors flex-shrink-0">
                            <i class="fas fa-pen text-xs"></i>
                        </button>` : ''}
                        <span class="w-2 h-2 rounded-full ${statusDot}"></span>
                        ${statusText}
                    </div>
                    <p class="text-xs text-slate-500 dark:text-slate-400 mt-0.5 font-mono">${escapeHtml(isInstance ? `${label} · ${iid}` : iid)}</p>
                </div>
                <button onclick="disconnectChannel('${ch.name}', '${isInstance ? iid : ''}')"
                    class="px-3 py-1.5 rounded-lg text-xs font-medium
                           bg-red-50 dark:bg-red-900/20 text-red-500 dark:text-red-400
                           hover:bg-red-100 dark:hover:bg-red-900/40
                           cursor-pointer transition-colors flex-shrink-0">
                    ${t('channels_disconnect')}
                </button>
            </div>
            ${multiAgentMode() ? `<div class="channel-agent-bind">
                <span class="text-xs text-slate-500 whitespace-nowrap" title="${escapeHtml(t('channel_bound_agent_hint'))}">${escapeHtml(t('channel_bound_agent'))}</span>
                <div id="ch-members-${iid}" class="cfg-dropdown cfg-dropdown-avatar cfg-dropdown-sm cfg-dropdown-multi" tabindex="0" style="width: 200px;">
                    <div class="cfg-dropdown-selected">
                        <span class="cfg-dropdown-faces"></span>
                        <span class="cfg-dropdown-text">--</span>
                        <i class="fas fa-chevron-down cfg-dropdown-arrow"></i>
                    </div>
                    <div class="cfg-dropdown-menu"></div>
                </div>
            </div>` : ''}
            ${weixinWaiting ? `<div id="weixin-active-qr" class="flex flex-col items-center py-2">
                <button onclick="showWeixinActiveQr()"
                    class="px-4 py-2 rounded-lg bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium
                           cursor-pointer transition-colors duration-150">
                    ${t('weixin_scan_title')}
                </button>
            </div>` : ''}
            ${wecomNeedsCreds ? `<div id="wecom-active-auth" class="flex flex-col items-center py-2">
                <p class="text-sm text-slate-500 dark:text-slate-400 mb-3">${t('wecom_scan_desc')}</p>
                <button onclick="startWecomBotAuthInCard()"
                    class="px-5 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white text-sm font-medium
                           cursor-pointer transition-colors duration-150">
                    <i class="fas fa-qrcode mr-2"></i>${t('wecom_scan_btn')}
                </button>
                <div id="wecom-card-scan-status" class="mt-3"></div>
            </div>` : ''}
            ${isFeishu ? buildFeishuPanel(ch, true) : (hasFields ? `<div class="space-y-4">
                ${fieldsHtml}
                <div class="flex items-center justify-end gap-3 pt-1">
                    <span id="ch-status-${iid}" class="text-xs text-primary-500 opacity-0 transition-opacity duration-300"></span>
                    <button onclick="saveChannelConfig('${ch.name}', '${isInstance ? iid : ''}')"
                        class="px-4 py-2 rounded-lg bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium
                               cursor-pointer transition-colors duration-150 disabled:opacity-50 disabled:cursor-not-allowed"
                        id="ch-save-${iid}">${t('channels_save')}</button>
                </div>
            </div>` : '')}`;

        container.appendChild(card);
        bindSecretFieldEvents(card);
        initChannelTeam(ch);

        if (weixinWaiting) {
            startWeixinActiveStatusPoll();
        }
    });
}

// One multi-select per channel card, same idea as creating a team in the chat
// history: pick a set of Agents; the first pick is the owner (receives every
// message and can delegate), the rest are teammates. An ordered list, so the
// first checked stays the owner. Empty = follow the default Agent, solo.
let _channelTeam = {};  // iid -> ordered [ownerId, ...memberIds]

function initChannelTeam(ch) {
    const iid = ch.iid || ch.name;
    if (!multiAgentMode()) return;
    const box = document.getElementById(`ch-members-${iid}`);
    if (!box) return;
    // Seed the ordered team: owner first, then its members. A legacy per-type
    // card has no instance fields, so fall back to its channel-type binding.
    const owner = ch.instance_id ? (ch.agent_id || '') : (channelBoundAgentId(ch.name) || '');
    const members = Array.isArray(ch.members) ? ch.members : [];
    _channelTeam[iid] = [owner, ...members].filter((id, i, arr) => id && arr.indexOf(id) === i);
    box.dataset.channelName = ch.name;
    renderChannelTeam(iid);
    if (!box._ddBound) {
        box.querySelector('.cfg-dropdown-selected').addEventListener('click', (e) => {
            e.stopPropagation();
            document.querySelectorAll('.cfg-dropdown.open').forEach(d => { if (d !== box) d.classList.remove('open'); });
            box.classList.toggle('open');
        });
        box._ddBound = true;
    }
}

function renderChannelTeam(iid) {
    const box = document.getElementById(`ch-members-${iid}`);
    if (!box) return;
    const team = _channelTeam[iid] || [];
    const ownerId = team[0] || '';
    const agents = enabledAgents();
    const chosen = team.map(id => findAgent(id)).filter(Boolean);

    const faces = box.querySelector('.cfg-dropdown-faces');
    const textEl = box.querySelector('.cfg-dropdown-text');
    const MAX_FACES = 3;
    if (chosen.length) {
        // Trigger: up to MAX_FACES avatars; any beyond that become a "+N" pill
        // so the count always matches how many are hidden, never the total.
        const shown = chosen.slice(0, MAX_FACES);
        const extra = chosen.length - shown.length;
        faces.innerHTML = shown.map(a => agentAvatarHTML(a, 18)).join('')
            + (extra > 0 ? `<span class="cfg-dropdown-more">+${extra}</span>` : '');
        textEl.textContent = chosen[0].name || chosen[0].id;
        textEl.classList.remove('text-slate-400', 'dark:text-slate-500');
    } else {
        // Nothing picked: this channel follows the default Agent. Show it
        // (dim) rather than an empty "none", so the receiver is always clear.
        const def = findAgent(defaultAgentId);
        faces.innerHTML = def ? agentAvatarHTML(def, 18) : '';
        textEl.textContent = def ? (def.name || def.id) : t('channel_team_none');
        textEl.classList.add('text-slate-400', 'dark:text-slate-500');
    }

    // Menu: a checklist. The first-picked carries a small "default" badge so it
    // is clear which Agent receives and delegates. The selected tick is the
    // dropdown's global .active::after, so no per-row tick element is needed.
    const menu = box.querySelector('.cfg-dropdown-menu');
    if (!agents.length) {
        menu.innerHTML = `<div class="cfg-dropdown-item cfg-dropdown-empty">${escapeHtml(t('channel_team_no_candidates'))}</div>`;
        return;
    }
    menu.innerHTML = agents.map(a => {
        const on = team.includes(a.id);
        const isOwner = a.id === ownerId;
        return `<div class="cfg-dropdown-item cfg-dropdown-check${on ? ' active' : ''}"
            onclick="event.stopPropagation(); toggleChannelTeam('${iid}','${a.id}')">
            <span class="cfg-dropdown-item-face">${agentAvatarHTML(a, 20)}</span>
            <span class="cfg-dropdown-label">${escapeHtml(a.name || a.id)}</span>
            ${isOwner ? `<span class="cfg-dropdown-badge">${escapeHtml(t('channel_bound_default'))}</span>` : ''}
        </div>`;
    }).join('');
}

function toggleChannelTeam(iid, agentId) {
    const box = document.getElementById(`ch-members-${iid}`);
    const chName = box ? (box.dataset.channelName || '') : '';
    const team = _channelTeam[iid] || [];
    const i = team.indexOf(agentId);
    if (i === -1) team.push(agentId);       // append: order = pick order
    else team.splice(i, 1);                 // remove; if it was owner, next becomes owner
    _channelTeam[iid] = team;
    renderChannelTeam(iid);
    // Persist: first pick is the owner (empty -> default Agent), rest members.
    const ownerId = team[0] || '';
    const members = team.slice(1);
    bindChannelAgent(chName, ownerId, iid, members);
}

function buildChannelFieldsHtml(chName, fields) {
    let html = '';
    fields.forEach(f => {
        const inputId = `ch-${chName}-${f.key}`;
        let inputHtml = '';
        if (f.type === 'bool') {
            const checked = f.value ? 'checked' : '';
            inputHtml = `<label class="relative inline-flex items-center cursor-pointer">
                <input id="${inputId}" type="checkbox" ${checked} class="sr-only peer" data-field="${f.key}" data-ch="${chName}">
                <div class="w-9 h-5 bg-slate-200 dark:bg-slate-700 peer-checked:bg-primary-400 rounded-full
                            after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white
                            after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:after:translate-x-full"></div>
            </label>`;
        } else if (f.type === 'secret') {
            inputHtml = `<input id="${inputId}" type="text" value="${escapeHtml(String(f.value || ''))}"
                data-field="${f.key}" data-ch="${chName}" data-masked="${f.value ? '1' : ''}"
                class="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600
                       bg-slate-50 dark:bg-white/5 text-sm text-slate-800 dark:text-slate-100
                       focus:outline-none focus:border-primary-500 font-mono transition-colors
                       ${f.value ? 'cfg-key-masked' : ''}"
                placeholder="${escapeHtml(f.label)}">`;
        } else {
            const inputType = f.type === 'number' ? 'number' : 'text';
            inputHtml = `<input id="${inputId}" type="${inputType}" value="${escapeHtml(String(f.value ?? f.default ?? ''))}"
                data-field="${f.key}" data-ch="${chName}"
                class="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600
                       bg-slate-50 dark:bg-white/5 text-sm text-slate-800 dark:text-slate-100
                       focus:outline-none focus:border-primary-500 font-mono transition-colors"
                placeholder="${escapeHtml(f.label)}">`;
        }
        html += `<div>
            <label class="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-1.5">${escapeHtml(f.label)}</label>
            ${inputHtml}
        </div>`;
    });
    return html;
}

function bindSecretFieldEvents(container) {
    container.querySelectorAll('input[data-masked="1"]').forEach(inp => {
        inp.addEventListener('focus', function() {
            if (this.dataset.masked === '1') {
                this.value = '';
                this.dataset.masked = '';
                this.classList.remove('cfg-key-masked');
            }
        });
    });
}

function showChannelStatus(chName, msgKey, isError) {
    const el = document.getElementById(`ch-status-${chName}`);
    if (!el) return;
    el.textContent = t(msgKey);
    el.classList.toggle('text-red-500', !!isError);
    el.classList.toggle('text-primary-500', !isError);
    el.classList.remove('opacity-0');
    setTimeout(() => el.classList.add('opacity-0'), 2500);
}

function saveChannelConfig(chName, instanceId) {
    // instanceId keys the DOM (per-instance cards); falls back to the channel
    // name for legacy single-instance cards.
    const iid = instanceId || chName;
    const card = document.getElementById(`channel-card-${iid}`);
    if (!card) return;

    const updates = {};
    card.querySelectorAll('input[data-ch="' + iid + '"]').forEach(inp => {
        const key = inp.dataset.field;
        if (inp.type === 'checkbox') {
            updates[key] = inp.checked;
        } else {
            if (inp.dataset.masked === '1') return;
            updates[key] = inp.value;
        }
    });

    const btn = document.getElementById(`ch-save-${iid}`);
    if (btn) btn.disabled = true;

    fetch('/api/channels', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'save', channel: chName, instance_id: instanceId || '', config: updates })
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'success') {
            showChannelStatus(iid, data.restarted ? 'channels_restarted' : 'channels_saved', false);
        } else {
            showChannelStatus(iid, 'channels_save_error', true);
        }
    })
    .catch(() => showChannelStatus(iid, 'channels_save_error', true))
    .finally(() => { if (btn) btn.disabled = false; });
}

// A minimal single-input dialog, used for renaming a channel instance. Mirrors
// showConfirmDialog's lifecycle so it themes and closes the same way.
function showRenameDialog({ title, value, okText, cancelText, onConfirm }) {
    const overlay = document.getElementById('rename-dialog-overlay');
    if (!overlay) return;
    const titleEl = overlay.querySelector('h3');
    const input = document.getElementById('rename-dialog-input');
    const okBtn = document.getElementById('rename-dialog-ok');
    const cancelBtn = document.getElementById('rename-dialog-cancel');
    if (titleEl && title) titleEl.textContent = title;
    if (okText) okBtn.textContent = okText;
    if (cancelText) cancelBtn.textContent = cancelText;
    input.value = value || '';

    function cleanup() {
        overlay.classList.add('hidden');
        okBtn.removeEventListener('click', onOk);
        cancelBtn.removeEventListener('click', onCancel);
        overlay.removeEventListener('click', onOverlayClick);
        input.removeEventListener('keydown', onKey);
    }
    function onOk() { const v = input.value.trim(); cleanup(); if (onConfirm) onConfirm(v); }
    function onCancel() { cleanup(); }
    function onOverlayClick(e) { if (e.target === overlay) cleanup(); }
    function onKey(e) {
        // Ignore Enter while an IME is composing (e.g. picking a Chinese
        // candidate), otherwise confirming a candidate would submit the dialog.
        // keyCode 229 is the legacy signal for "still composing".
        if (e.isComposing || e.keyCode === 229) return;
        if (e.key === 'Enter') onOk();
        else if (e.key === 'Escape') onCancel();
    }

    okBtn.addEventListener('click', onOk);
    cancelBtn.addEventListener('click', onCancel);
    overlay.addEventListener('click', onOverlayClick);
    input.addEventListener('keydown', onKey);
    overlay.classList.remove('hidden');
    setTimeout(() => { input.focus(); input.select(); }, 30);
}

function renameChannelInstance(chName, instanceId) {
    const inst = (channelInstancesView || []).find(i => i.instance_id === instanceId);
    const current = inst ? (inst.instance_name || '') : '';
    showRenameDialog({
        title: t('channel_rename'),
        value: current,
        okText: t('channels_save'),
        cancelText: t('channels_cancel'),
        onConfirm: (newName) => {
            fetch('/api/channels', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'rename', channel: chName, instance_id: instanceId, name: newName })
            })
            .then(r => r.json())
            .then(data => { if (data.status === 'success') loadChannelsView(); })
            .catch(() => {});
        }
    });
}

function disconnectChannel(chName, instanceId) {
    const ch = channelsData.find(c => c.name === chName);
    const label = ch ? ((typeof ch.label === 'object') ? (ch.label[currentLang] || ch.label.en) : ch.label) : chName;

    showConfirmDialog({
        title: t('channels_disconnect'),
        message: t('channels_disconnect_confirm'),
        okText: t('channels_disconnect'),
        cancelText: t('channels_cancel'),
        onConfirm: () => {
            fetch('/api/channels', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'disconnect', channel: chName, instance_id: instanceId || '' })
            })
            .then(r => r.json())
            .then(data => {
                if (data.status === 'success') {
                    // An instance removal changes the instances list; reload from
                    // the server so the card set is authoritative. Legacy per-type
                    // disconnect can flip the flag locally.
                    if (instanceId) {
                        loadChannelsView();
                    } else {
                    if (ch) ch.active = false;
                    renderActiveChannels();
                    }
                } else {
                    // Surface the failure instead of silently leaving the card in
                    // place — otherwise a rejected disconnect looks like nothing
                    // happened at all.
                    _wsToast(data.message || t('channels_disconnect_error'));
                }
            })
            .catch(() => _wsToast(t('channels_disconnect_error')));
        }
    });
}

// --- Add channel panel ---
function openAddChannelPanel() {
    const panel = document.getElementById('channels-add-panel');
    // A multi-instance-ready type (feishu) can always be added again — each add
    // creates a new instance. Other types disappear once active.
    const activeNames = new Set(
        channelsData.filter(c => c.active && !isMultiInstanceType(c.name)).map(c => c.name)
    );
    const available = channelsData.filter(c => !activeNames.has(c.name));

    const anyCards = channelRenderList().length > 0;
    const content = document.getElementById('channels-content');
    if (!anyCards && content) content.classList.add('hidden');

    if (available.length === 0) {
        panel.innerHTML = `<div class="bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10 p-6 text-center">
            <p class="text-sm text-slate-500 dark:text-slate-400">${currentLang === 'zh' ? '所有通道均已接入' : 'All channels are already connected'}</p>
            <button onclick="closeAddChannelPanel()" class="mt-3 text-xs text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 cursor-pointer">${t('channels_cancel')}</button>
        </div>`;
        panel.classList.remove('hidden');
        return;
    }

    const ddOptions = [
        { value: '', label: t('channels_select_placeholder') },
        ...available.map(ch => {
            const label = (typeof ch.label === 'object') ? (ch.label[currentLang] || ch.label.en) : ch.label;
            return { value: ch.name, label: `${label} (${ch.name})` };
        })
    ];

    panel.innerHTML = `
        <div class="bg-white dark:bg-[#1A1A1A] rounded-xl border border-primary-200 dark:border-primary-800 p-6">
            <div class="flex items-center gap-3 mb-5">
                <div class="w-9 h-9 rounded-lg bg-primary-50 dark:bg-primary-900/30 flex items-center justify-center">
                    <i class="fas fa-plus text-primary-500 text-sm"></i>
                </div>
                <h3 class="font-semibold text-slate-800 dark:text-slate-100">${t('channels_add')}</h3>
            </div>
            <div class="mb-4">
                <div id="add-channel-select" class="cfg-dropdown" tabindex="0">
                    <div class="cfg-dropdown-selected">
                        <span class="cfg-dropdown-text">--</span>
                        <i class="fas fa-chevron-down cfg-dropdown-arrow"></i>
                    </div>
                    <div class="cfg-dropdown-menu"></div>
                </div>
            </div>
            <div id="add-channel-fields" class="space-y-4"></div>
            <div id="add-channel-actions" class="hidden flex items-center justify-end gap-3 pt-4">
                <button onclick="closeAddChannelPanel()"
                    class="px-4 py-2 rounded-lg border border-slate-200 dark:border-white/10
                           text-slate-600 dark:text-slate-300 text-sm font-medium
                           hover:bg-slate-50 dark:hover:bg-white/5
                           cursor-pointer transition-colors duration-150">${t('channels_cancel')}</button>
                <button id="add-channel-submit" onclick="submitAddChannel()"
                    class="px-4 py-2 rounded-lg bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium
                           cursor-pointer transition-colors duration-150 disabled:opacity-50 disabled:cursor-not-allowed">${t('channels_connect_btn')}</button>
            </div>
        </div>`;
    panel.classList.remove('hidden');
    panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    const ddEl = document.getElementById('add-channel-select');
    initDropdown(ddEl, ddOptions, '', onAddChannelSelect);
}

function closeAddChannelPanel() {
    stopWeixinQrPoll();
    stopFeishuRegisterPoll();
    const panel = document.getElementById('channels-add-panel');
    if (panel) {
        panel.classList.add('hidden');
        panel.innerHTML = '';
    }
    const content = document.getElementById('channels-content');
    if (content) content.classList.remove('hidden');
}

function onAddChannelSelect(chName) {
    stopWeixinQrPoll();
    stopFeishuRegisterPoll();
    const fieldsContainer = document.getElementById('add-channel-fields');
    const actions = document.getElementById('add-channel-actions');

    if (!chName) {
        fieldsContainer.innerHTML = '';
        actions.classList.add('hidden');
        return;
    }

    if (chName === 'weixin') {
        actions.classList.add('hidden');
        fieldsContainer.innerHTML = `
            <div id="weixin-qr-panel" class="flex flex-col items-center py-4">
                <p class="text-sm text-slate-500 dark:text-slate-400 mb-4">${t('weixin_scan_loading')}</p>
            </div>`;
        startWeixinQrLogin();
        return;
    }

    if (chName === 'wecom_bot') {
        actions.classList.add('hidden');
        const ch = channelsData.find(c => c.name === chName);
        fieldsContainer.innerHTML = buildWecomBotPanel(ch);
        return;
    }

    if (chName === 'feishu') {
        actions.classList.add('hidden');
        const ch = channelsData.find(c => c.name === chName);
        fieldsContainer.innerHTML = buildFeishuPanel(ch);
        return;
    }

    const ch = channelsData.find(c => c.name === chName);
    if (!ch) return;

    fieldsContainer.innerHTML = buildChannelFieldsHtml(chName, ch.fields || []);
    bindSecretFieldEvents(fieldsContainer);
    actions.classList.remove('hidden');
}

function submitAddChannel() {
    const ddEl = document.getElementById('add-channel-select');
    const chName = getDropdownValue(ddEl);
    if (!chName) return;

    const fieldsContainer = document.getElementById('add-channel-fields');
    const updates = {};
    fieldsContainer.querySelectorAll('input[data-ch="' + chName + '"]').forEach(inp => {
        const key = inp.dataset.field;
        if (inp.type === 'checkbox') {
            updates[key] = inp.checked;
        } else {
            if (inp.dataset.masked === '1') return;
            updates[key] = inp.value;
        }
    });

    const btn = document.getElementById('add-channel-submit');
    if (btn) { btn.disabled = true; btn.textContent = t('channels_connecting'); }

    fetch('/api/channels', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'connect', channel: chName, config: updates })
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'success') {
            // A new multi-instance record only shows up by reloading the
            // instances list from the server; legacy per-type add can patch
            // local state and re-render.
            if (isMultiInstanceType(chName) || data.instance_id) {
                loadChannelsView();
                return;
            }
            const ch = channelsData.find(c => c.name === chName);
            if (ch) {
                ch.active = true;
                (ch.fields || []).forEach(f => {
                    if (updates[f.key] !== undefined) {
                        f.value = f.type === 'secret' ? ChannelsHandler_maskSecret(updates[f.key]) : updates[f.key];
                    }
                });
            }
            renderActiveChannels();
        } else {
            if (btn) { btn.disabled = false; btn.textContent = t('channels_connect_btn'); }
        }
    })
    .catch(() => {
        if (btn) { btn.disabled = false; btn.textContent = t('channels_connect_btn'); }
    });
}

// =====================================================================
// WeChat QR Login
// =====================================================================
let _weixinQrPollTimer = null;
let _weixinStatusPollTimer = null;

function stopWeixinStatusPoll() {
    if (_weixinStatusPollTimer) {
        clearTimeout(_weixinStatusPollTimer);
        _weixinStatusPollTimer = null;
    }
}

function startWeixinActiveStatusPoll() {
    stopWeixinStatusPoll();
    _weixinStatusPollTimer = setTimeout(() => {
        fetch('/api/channels').then(r => r.json()).then(data => {
            if (data.status !== 'success') return;
            const wx = (data.channels || []).find(c => c.name === 'weixin');
            if (!wx || !wx.active) return;
            if (wx.login_status === 'logged_in') {
                channelsData = data.channels;
                renderActiveChannels();
            } else {
                const ch = channelsData.find(c => c.name === 'weixin');
                if (ch) ch.login_status = wx.login_status;
                startWeixinActiveStatusPoll();
            }
        }).catch(() => { startWeixinActiveStatusPoll(); });
    }, 3000);
}

function showWeixinActiveQr() {
    const container = document.getElementById('weixin-active-qr');
    if (!container) return;
    container.innerHTML = `
        <div id="weixin-qr-panel" class="flex flex-col items-center py-2">
            <p class="text-sm text-slate-500 dark:text-slate-400 mb-4">${t('weixin_scan_loading')}</p>
        </div>`;
    stopWeixinStatusPoll();
    startWeixinQrLogin();
}

function stopWeixinQrPoll() {
    if (_weixinQrPollTimer) {
        clearTimeout(_weixinQrPollTimer);
        _weixinQrPollTimer = null;
    }
}

function startWeixinQrLogin() {
    stopWeixinQrPoll();
    fetch('/api/weixin/qrlogin')
        .then(r => r.json())
        .then(data => {
            const panel = document.getElementById('weixin-qr-panel');
            if (!panel) return;
            if (data.status !== 'success') {
                panel.innerHTML = `<p class="text-sm text-red-500">${t('weixin_scan_fail')}: ${data.message || ''}</p>`;
                return;
            }
            renderWeixinQr(data.qr_image || data.qrcode_url, 'waiting');
            if (data.source === 'channel') {
                startWeixinActiveStatusPoll();
            } else {
                pollWeixinQrStatus();
            }
        })
        .catch(() => {
            const panel = document.getElementById('weixin-qr-panel');
            if (panel) panel.innerHTML = `<p class="text-sm text-red-500">${t('weixin_scan_fail')}</p>`;
        });
}

function renderWeixinQr(qrcodeUrl, status) {
    const panel = document.getElementById('weixin-qr-panel');
    if (!panel) return;

    let statusText = t('weixin_scan_waiting');
    let statusColor = 'text-slate-500 dark:text-slate-400';
    if (status === 'scanned') {
        statusText = t('weixin_scan_scanned');
        statusColor = 'text-primary-500';
    } else if (status === 'expired') {
        statusText = t('weixin_scan_expired');
        statusColor = 'text-amber-500';
    } else if (status === 'confirmed') {
        statusText = t('weixin_scan_success');
        statusColor = 'text-primary-500';
    }

    panel.innerHTML = `
        <div class="flex flex-col items-center">
            <p class="text-sm font-medium text-slate-700 dark:text-slate-200 mb-1">${t('weixin_scan_title')}</p>
            <p class="text-xs text-slate-400 dark:text-slate-500 mb-4">${t('weixin_scan_desc')}</p>
            <div class="bg-white p-3 rounded-xl shadow-sm border border-slate-100 dark:border-slate-700 mb-3">
                <img src="${escapeHtml(qrcodeUrl)}" alt="QR Code" class="w-52 h-52" style="image-rendering: pixelated;"/>
            </div>
            <p class="text-xs ${statusColor} mb-1">${statusText}</p>
            <p class="text-xs text-slate-400 dark:text-slate-500">${t('weixin_qr_tip')}</p>
        </div>`;
}

function pollWeixinQrStatus() {
    _weixinQrPollTimer = setTimeout(() => {
        fetch('/api/weixin/qrlogin', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'poll' })
        })
        .then(r => r.json())
        .then(data => {
            const panel = document.getElementById('weixin-qr-panel');
            if (!panel) { stopWeixinQrPoll(); return; }

            if (data.status !== 'success') {
                pollWeixinQrStatus();
                return;
            }

            const qrStatus = data.qr_status;
            if (qrStatus === 'confirmed') {
                renderWeixinQr('', 'confirmed');
                panel.innerHTML = `
                    <div class="flex flex-col items-center py-4">
                        <div class="w-12 h-12 rounded-full bg-primary-50 dark:bg-primary-900/30 flex items-center justify-center mb-3">
                            <i class="fas fa-check text-primary-500 text-lg"></i>
                        </div>
                        <p class="text-sm font-medium text-primary-600 dark:text-primary-400">${t('weixin_scan_success')}</p>
                    </div>`;
                connectWeixinAfterQr();
            } else if (qrStatus === 'expired' && (data.qr_image || data.qrcode_url)) {
                renderWeixinQr(data.qr_image || data.qrcode_url, 'waiting');
                pollWeixinQrStatus();
            } else if (qrStatus === 'scaned') {
                const img = panel.querySelector('img');
                const currentSrc = img ? img.src : '';
                renderWeixinQr(currentSrc, 'scanned');
                pollWeixinQrStatus();
            } else {
                pollWeixinQrStatus();
            }
        })
        .catch(() => {
            pollWeixinQrStatus();
        });
    }, 2000);
}

function connectWeixinAfterQr() {
    fetch('/api/channels', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'connect', channel: 'weixin', config: {} })
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'success') {
            // Multi-Agent: the new Weixin instance only lives in the server's
            // channel_instances yet, and its card is rendered from that list —
            // so reload the channels view to make it appear. Re-rendering from
            // the stale local state would drop the freshly scanned card until a
            // manual refresh. Legacy single-instance patches local state.
            if (isMultiInstanceType('weixin') || data.instance_id) {
                setTimeout(() => loadChannelsView(), 1500);
                return;
            }
            const ch = channelsData.find(c => c.name === 'weixin');
            if (ch) ch.active = true;
            setTimeout(() => renderActiveChannels(), 1500);
        }
    })
    .catch(() => {});
}

// =====================================================================
// WeCom Bot QR Auth
// =====================================================================
// NOTE: This is the only remaining external script in the Web Console.
// Tencent's WeCom Bot SDK must be loaded from their official CDN — it
// performs runtime origin/signature checks and will not work if
// self-hosted. The SDK is fetched lazily, only when the user opens the
// "WeCom Bot" channel QR-login flow, so the rest of the console works
// fully offline.
const WECOM_BOT_SDK_URL = 'https://wwcdn.weixin.qq.com/node/wework/js/wecom-aibot-sdk@0.1.0.min.js';
const WECOM_BOT_SOURCE = 'cowagent';
let _wecomSdkLoaded = false;

function ensureWecomSdkLoaded() {
    return new Promise((resolve, reject) => {
        if (_wecomSdkLoaded && window.WecomAIBotSDK) { resolve(); return; }
        if (document.querySelector(`script[src="${WECOM_BOT_SDK_URL}"]`)) {
            _wecomSdkLoaded = true; resolve(); return;
        }
        const s = document.createElement('script');
        s.src = WECOM_BOT_SDK_URL;
        s.onload = () => { _wecomSdkLoaded = true; resolve(); };
        s.onerror = () => reject(new Error('Failed to load WecomAIBotSDK'));
        document.head.appendChild(s);
    });
}

function _wecomBotHasCreds(ch) {
    if (!ch || !ch.fields) return false;
    const idField = ch.fields.find(f => f.key === 'wecom_bot_id');
    const secretField = ch.fields.find(f => f.key === 'wecom_bot_secret');
    return !!(idField && idField.value && secretField && secretField.value);
}

function buildWecomBotPanel(ch) {
    const scanLabel = t('wecom_mode_scan');
    const manualLabel = t('wecom_mode_manual');
    const hasCreds = _wecomBotHasCreds(ch);
    const defaultMode = hasCreds ? 'manual' : 'scan';
    return `
        <div id="wecom-bot-panel" data-default-mode="${defaultMode}">
            <div class="flex items-center justify-center gap-1 mb-5 bg-slate-100 dark:bg-white/5 rounded-lg p-1">
                <button id="wecom-tab-scan" onclick="switchWecomBotMode('scan')"
                    class="flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors
                           bg-white dark:bg-slate-700 text-slate-800 dark:text-slate-100 shadow-sm">
                    ${scanLabel}
                </button>
                <button id="wecom-tab-manual" onclick="switchWecomBotMode('manual')"
                    class="flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors
                           text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200">
                    ${manualLabel}
                </button>
            </div>
            <div id="wecom-mode-content"></div>
        </div>`;
}

function switchWecomBotMode(mode) {
    const scanTab = document.getElementById('wecom-tab-scan');
    const manualTab = document.getElementById('wecom-tab-manual');
    const content = document.getElementById('wecom-mode-content');
    const actions = document.getElementById('add-channel-actions');
    if (!scanTab || !manualTab || !content) return;

    const activeClasses = 'bg-white dark:bg-slate-700 text-slate-800 dark:text-slate-100 shadow-sm';
    const inactiveClasses = 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200';

    if (mode === 'scan') {
        scanTab.className = scanTab.className.replace(/text-slate-500[^\s]*/g, '').replace(/hover:\S+/g, '');
        scanTab.className = `flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${activeClasses}`;
        manualTab.className = `flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${inactiveClasses}`;
        actions.classList.add('hidden');
        content.innerHTML = `
            <div class="flex flex-col items-center py-4">
                <p class="text-sm text-slate-600 dark:text-slate-300 mb-2">${t('wecom_scan_desc')}</p>
                <button onclick="startWecomBotAuth()"
                    class="mt-3 px-6 py-2.5 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white text-sm font-medium
                           cursor-pointer transition-colors duration-150">
                    <i class="fas fa-qrcode mr-2"></i>${t('wecom_scan_btn')}
                </button>
                <div id="wecom-scan-status" class="mt-3"></div>
            </div>`;
    } else {
        manualTab.className = `flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${activeClasses}`;
        scanTab.className = `flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${inactiveClasses}`;
        const ch = channelsData.find(c => c.name === 'wecom_bot');
        content.innerHTML = `<div class="space-y-4">${buildChannelFieldsHtml('wecom_bot', ch ? ch.fields || [] : [])}</div>`;
        bindSecretFieldEvents(content);
        actions.classList.remove('hidden');
    }
}

function startWecomBotAuth() {
    const statusEl = document.getElementById('wecom-scan-status');
    ensureWecomSdkLoaded().then(() => {
        WecomAIBotSDK.openBotInfoAuthWindow({
            source: WECOM_BOT_SOURCE,
            onCreated: function(bot) {
                if (statusEl) {
                    statusEl.innerHTML = `
                        <div class="flex flex-col items-center py-2">
                            <div class="w-10 h-10 rounded-full bg-emerald-50 dark:bg-emerald-900/30 flex items-center justify-center mb-2">
                                <i class="fas fa-check text-emerald-500 text-lg"></i>
                            </div>
                            <p class="text-sm font-medium text-emerald-600 dark:text-emerald-400">${t('wecom_scan_success')}</p>
                        </div>`;
                }
                connectWecomBotAfterAuth(bot.botid, bot.secret);
            },
            onError: function(err) {
                if (statusEl) {
                    statusEl.innerHTML = `<p class="text-sm text-red-500">${t('wecom_scan_fail')}: ${err.message || err.code || ''}</p>`;
                }
            }
        });
    }).catch(err => {
        if (statusEl) {
            statusEl.innerHTML = `<p class="text-sm text-red-500">SDK load failed: ${err.message}</p>`;
        }
    });
}

function connectWecomBotAfterAuth(botId, secret) {
    fetch('/api/channels', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            action: 'connect',
            channel: 'wecom_bot',
            config: { wecom_bot_id: botId, wecom_bot_secret: secret }
        })
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'success') {
            const ch = channelsData.find(c => c.name === 'wecom_bot');
            if (ch) {
                ch.active = true;
                (ch.fields || []).forEach(f => {
                    if (f.key === 'wecom_bot_id') f.value = botId;
                    if (f.key === 'wecom_bot_secret') f.value = ChannelsHandler_maskSecret(secret);
                });
            }
            setTimeout(() => renderActiveChannels(), 1500);
        }
    })
    .catch(() => {});
}

function startWecomBotAuthInCard() {
    const statusEl = document.getElementById('wecom-card-scan-status');
    ensureWecomSdkLoaded().then(() => {
        WecomAIBotSDK.openBotInfoAuthWindow({
            source: WECOM_BOT_SOURCE,
            onCreated: function(bot) {
                if (statusEl) {
                    statusEl.innerHTML = `
                        <div class="flex flex-col items-center py-2">
                            <div class="w-10 h-10 rounded-full bg-emerald-50 dark:bg-emerald-900/30 flex items-center justify-center mb-2">
                                <i class="fas fa-check text-emerald-500 text-lg"></i>
                            </div>
                            <p class="text-sm font-medium text-emerald-600 dark:text-emerald-400">${t('wecom_scan_success')}</p>
                        </div>`;
                }
                connectWecomBotAfterAuth(bot.botid, bot.secret);
            },
            onError: function(err) {
                if (statusEl) {
                    statusEl.innerHTML = `<p class="text-sm text-red-500">${t('wecom_scan_fail')}: ${err.message || err.code || ''}</p>`;
                }
            }
        });
    }).catch(err => {
        if (statusEl) {
            statusEl.innerHTML = `<p class="text-sm text-red-500">SDK load failed: ${err.message}</p>`;
        }
    });
}

// Initialize wecom bot panel with correct default mode when inserted into DOM
document.addEventListener('DOMContentLoaded', function() {
    const observer = new MutationObserver(function() {
        const wecomPanel = document.getElementById('wecom-bot-panel');
        if (wecomPanel && !wecomPanel.dataset.initialized) {
            wecomPanel.dataset.initialized = '1';
            switchWecomBotMode(wecomPanel.dataset.defaultMode || 'scan');
        }
        // Init every feishu panel on screen, not just the first: multiple
        // instance cards can be present at once, each with its own id suffix.
        document.querySelectorAll('.feishu-panel').forEach(feishuPanel => {
            if (feishuPanel.dataset.initialized) return;
            feishuPanel.dataset.initialized = '1';
            switchFeishuMode(feishuPanel.dataset.iid || 'feishu', feishuPanel.dataset.defaultMode || 'scan');
        });
    });
    observer.observe(document.body, { childList: true, subtree: true });
});

// =====================================================================
// Feishu One-click App Registration (lark-oapi register_app)
// =====================================================================
let _feishuRegisterPollTimer = null;

function _feishuHasCreds(ch) {
    if (!ch || !ch.fields) return false;
    const idField = ch.fields.find(f => f.key === 'feishu_app_id');
    const secretField = ch.fields.find(f => f.key === 'feishu_app_secret');
    return !!(idField && idField.value && secretField && secretField.value);
}

function buildFeishuPanel(ch, isActive) {
    const scanLabel = t('feishu_mode_scan');
    const manualLabel = t('feishu_mode_manual');
    // 已有凭据时默认进入手动 Tab，方便修改；否则推荐扫码
    const defaultMode = _feishuHasCreds(ch) ? 'manual' : 'scan';
    const activeAttr = isActive ? 'data-active="1"' : '';
    // Every DOM id in the panel is suffixed with the instance id so two feishu
    // cards on screen at once never collide: without this, getElementById()
    // always resolves to the first card, so the second card is dead and its tab
    // clicks drive the first one. The Add panel (no instance yet) uses the bare
    // "feishu" suffix; an active instance card uses its real instance id.
    const iid = (isActive && ch && ch.iid) ? ch.iid : 'feishu';
    return `
        <div id="feishu-panel-${iid}" class="feishu-panel" data-default-mode="${defaultMode}" data-iid="${escapeHtml(iid)}" ${activeAttr}>
            <div class="flex items-center justify-center gap-1 mb-5 bg-slate-100 dark:bg-white/5 rounded-lg p-1">
                <button id="feishu-tab-scan-${iid}" onclick="switchFeishuMode('${iid}', 'scan')"
                    class="flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors
                           bg-white dark:bg-slate-700 text-slate-800 dark:text-slate-100 shadow-sm">
                    ${scanLabel}
                </button>
                <button id="feishu-tab-manual-${iid}" onclick="switchFeishuMode('${iid}', 'manual')"
                    class="flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors
                           text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200">
                    ${manualLabel}
                </button>
            </div>
            <div id="feishu-mode-content-${iid}"></div>
        </div>`;
}

function switchFeishuMode(iid, mode) {
    // Back-compat: old call sites passed only the mode. Treat a bare mode as the
    // Add panel's "feishu" instance.
    if (mode === undefined && (iid === 'scan' || iid === 'manual')) {
        mode = iid;
        iid = 'feishu';
    }
    iid = iid || 'feishu';
    const panel = document.getElementById(`feishu-panel-${iid}`);
    const scanTab = document.getElementById(`feishu-tab-scan-${iid}`);
    const manualTab = document.getElementById(`feishu-tab-manual-${iid}`);
    const content = document.getElementById(`feishu-mode-content-${iid}`);
    if (!scanTab || !manualTab || !content) return;

    // 已激活通道卡片中嵌入此 panel 时，没有 add-channel-actions（保存按钮就近渲染）
    const isActive = panel && panel.dataset.active === '1';
    const actions = isActive ? null : document.getElementById('add-channel-actions');
    const scanStatusId = `feishu-scan-status-${iid}`;

    const activeClasses = 'bg-white dark:bg-slate-700 text-slate-800 dark:text-slate-100 shadow-sm';
    const inactiveClasses = 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200';

    stopFeishuRegisterPoll();

    if (mode === 'scan') {
        scanTab.className = `flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${activeClasses}`;
        manualTab.className = `flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${inactiveClasses}`;
        if (actions) actions.classList.add('hidden');
        // active 卡片下扫码替换的提示文案，强调"创建新机器人会覆盖现有配置"
        const desc = isActive
            ? t('feishu_scan_replace_desc')
            : t('feishu_scan_desc');
        content.innerHTML = `
            <div class="flex flex-col items-center py-4">
                <p class="text-sm text-slate-600 dark:text-slate-300 mb-3 text-center">${desc}</p>
                <button onclick="startFeishuRegister('${scanStatusId}')"
                    class="mt-2 px-6 py-2.5 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white text-sm font-medium
                           cursor-pointer transition-colors duration-150">
                    <i class="fas fa-qrcode mr-2"></i>${t('feishu_scan_btn')}
                </button>
                <div id="${scanStatusId}" class="mt-4 w-full"></div>
            </div>`;
    } else {
        manualTab.className = `flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${activeClasses}`;
        scanTab.className = `flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${inactiveClasses}`;
        // An active instance card keys its fields by the instance id (so the
        // card's data-ch query and the save target line up); the Add panel keys
        // by the bare type since no instance exists yet.
        const ch = (isActive && iid !== 'feishu')
            ? channelInstancesView.find(c => c.instance_id === iid)
            : channelsData.find(c => c.name === 'feishu');
        const fieldsHtml = buildChannelFieldsHtml(iid, ch ? ch.fields || [] : []);
        if (isActive) {
            // 已接入卡片：内置保存按钮，复用 saveChannelConfig 走 update 流程
            content.innerHTML = `
                <div class="space-y-4">
                    ${fieldsHtml}
                    <div class="flex items-center justify-end gap-3 pt-1">
                        <span id="ch-status-${iid}" class="text-xs text-primary-500 opacity-0 transition-opacity duration-300"></span>
                        <button onclick="saveChannelConfig('feishu', '${iid === 'feishu' ? '' : iid}')"
                            class="px-4 py-2 rounded-lg bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium
                                   cursor-pointer transition-colors duration-150 disabled:opacity-50 disabled:cursor-not-allowed"
                            id="ch-save-${iid}">${t('channels_save')}</button>
                    </div>
                </div>`;
        } else {
            content.innerHTML = `<div class="space-y-4">${fieldsHtml}</div>`;
            if (actions) actions.classList.remove('hidden');
        }
        bindSecretFieldEvents(content);
    }
}

function stopFeishuRegisterPoll() {
    if (_feishuRegisterPollTimer) {
        clearTimeout(_feishuRegisterPollTimer);
        _feishuRegisterPollTimer = null;
    }
}

function startFeishuRegister(targetStatusId) {
    const statusId = targetStatusId || 'feishu-scan-status';
    const statusEl = document.getElementById(statusId);
    if (statusEl) {
        statusEl.innerHTML = `<p class="text-sm text-slate-500 dark:text-slate-400 text-center">${t('feishu_scan_loading')}</p>`;
    }
    stopFeishuRegisterPoll();
    fetch('/api/feishu/register')
        .then(r => r.json())
        .then(data => {
            if (data.status !== 'success') {
                renderFeishuRegisterError(statusId, data.message || t('feishu_scan_fail'));
                return;
            }
            if (data.register_status === 'downloading') {
                // Desktop first run: the SDK bundle lands before the QR exists.
                renderFeishuSdkDownloading(statusId);
            } else {
                renderFeishuQr(statusId, data.qr_image, data.qrcode_url);
            }
            pollFeishuRegisterStatus(statusId);
        })
        .catch(err => {
            renderFeishuRegisterError(statusId, err.message || t('feishu_scan_fail'));
        });
}

function renderFeishuQr(statusId, qrImage, qrUrl) {
    const statusEl = document.getElementById(statusId);
    if (!statusEl) return;
    const imgHtml = qrImage
        ? `<img src="${qrImage}" alt="QR" class="w-44 h-44 rounded-lg border border-slate-200 dark:border-white/10 bg-white p-2"/>`
        : `<div class="w-44 h-44 rounded-lg border border-dashed border-slate-300 flex items-center justify-center text-xs text-slate-400">QR</div>`;
    statusEl.innerHTML = `
        <div class="flex flex-col items-center gap-3">
            ${imgHtml}
            <p class="text-xs text-amber-500">${t('feishu_scan_waiting')}</p>
            <p class="text-xs text-slate-400 dark:text-slate-500">${t('feishu_scan_tip')}</p>
            ${qrUrl ? `<a href="${qrUrl}" target="_blank" rel="noopener"
                class="text-xs text-blue-500 hover:text-blue-600 underline">${t('feishu_scan_open_link')}</a>` : ''}
        </div>`;
}

function renderFeishuSdkDownloading(statusId) {
    const statusEl = document.getElementById(statusId);
    if (!statusEl) return;
    statusEl.innerHTML = `
        <div class="flex flex-col items-center gap-2 py-6">
            <i class="fas fa-spinner fa-spin text-slate-400"></i>
            <p class="text-sm text-slate-500 dark:text-slate-400">${t('feishu_sdk_downloading')}</p>
            <p class="text-xs text-slate-400 dark:text-slate-500">${t('feishu_sdk_downloading_tip')}</p>
        </div>`;
}

function renderFeishuRegisterError(statusId, message) {
    const statusEl = document.getElementById(statusId);
    if (!statusEl) return;
    statusEl.innerHTML = `
        <div class="flex flex-col items-center gap-2 py-2">
            <p class="text-sm text-red-500 text-center">${message}</p>
            <button onclick="startFeishuRegister('${statusId}')"
                class="mt-1 px-4 py-1.5 rounded-md text-xs font-medium
                       bg-slate-100 dark:bg-white/10 text-slate-700 dark:text-slate-200
                       hover:bg-slate-200 dark:hover:bg-white/20 cursor-pointer">
                <i class="fas fa-rotate-right mr-1"></i>${t('feishu_scan_retry')}
            </button>
        </div>`;
}

function pollFeishuRegisterStatus(statusId) {
    stopFeishuRegisterPoll();
    _feishuRegisterPollTimer = setTimeout(() => {
        fetch('/api/feishu/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'poll' })
        })
        .then(r => r.json())
        .then(data => {
            if (data.status !== 'success') {
                renderFeishuRegisterError(statusId, data.message || t('feishu_scan_fail'));
                return;
            }
            const rs = data.register_status;
            if (rs === 'downloading') {
                renderFeishuSdkDownloading(statusId);
                pollFeishuRegisterStatus(statusId);
                return;
            }
            // The QR may only be generated after the bundle downloaded, in
            // which case the initial GET could not carry it. Render it once;
            // repainting on every poll would make it flicker.
            const shown = document.getElementById(statusId);
            if ((data.qr_image || data.qrcode_url) && shown && !shown.querySelector('img')) {
                renderFeishuQr(statusId, data.qr_image, data.qrcode_url);
            }
            if (rs === 'done') {
                const statusEl = document.getElementById(statusId);
                if (statusEl) {
                    statusEl.innerHTML = `
                        <div class="flex flex-col items-center py-2">
                            <div class="w-10 h-10 rounded-full bg-emerald-50 dark:bg-emerald-900/30 flex items-center justify-center mb-2">
                                <i class="fas fa-check text-emerald-500 text-lg"></i>
                            </div>
                            <p class="text-sm font-medium text-emerald-600 dark:text-emerald-400">${t('feishu_scan_success')}</p>
                        </div>`;
                }
                connectFeishuAfterRegister(data.app_id, data.app_secret);
            } else if (rs === 'expired') {
                renderFeishuRegisterError(statusId, t('feishu_scan_expired'));
            } else if (rs === 'denied') {
                renderFeishuRegisterError(statusId, t('feishu_scan_denied'));
            } else if (rs === 'error') {
                renderFeishuRegisterError(statusId, data.message || t('feishu_scan_fail'));
            } else {
                pollFeishuRegisterStatus(statusId);
            }
        })
        .catch(() => {
            pollFeishuRegisterStatus(statusId);
        });
    }, 2000);
}

function connectFeishuAfterRegister(appId, appSecret) {
    fetch('/api/channels', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            action: 'connect',
            channel: 'feishu',
            config: { feishu_app_id: appId, feishu_app_secret: appSecret }
        })
    })
    .then(r => r.json())
    .then(data => {
        if (data.status === 'success') {
            // Multi-Agent mode created a new feishu instance server-side; reload
            // so its card appears. Legacy mode patches local state.
            if (isMultiInstanceType('feishu') || data.instance_id) {
                setTimeout(() => loadChannelsView(), 1500);
                return;
            }
            const ch = channelsData.find(c => c.name === 'feishu');
            if (ch) {
                ch.active = true;
                (ch.fields || []).forEach(f => {
                    if (f.key === 'feishu_app_id') f.value = appId;
                    if (f.key === 'feishu_app_secret') f.value = ChannelsHandler_maskSecret(appSecret);
                });
            }
            setTimeout(() => renderActiveChannels(), 1500);
        }
    })
    .catch(() => {});
}

// =====================================================================
// Scheduler View
// =====================================================================
let tasksLoaded = false;
// Which sub-tab of the Tasks view is showing: 'tasks' | 'records'.
let tasksActiveTab = 'tasks';
let runsLoaded = false;

// Switch between the task list and the execution-record history. The header's
// add/refresh buttons and subtitle follow the active tab so the two panes share
// one chrome (mirrors the desktop client).
function switchTasksTab(tab) {
    tasksActiveTab = tab;
    const isTasks = tab === 'tasks';
    document.getElementById('tasks-pane').classList.toggle('hidden', !isTasks);
    document.getElementById('runs-pane').classList.toggle('hidden', isTasks);
    // Add button is only meaningful on the task list.
    const addBtn = document.getElementById('task-add-btn');
    if (addBtn) addBtn.classList.toggle('hidden', !isTasks);
    const subtitle = document.getElementById('tasks-subtitle');
    if (subtitle) subtitle.textContent = t(isTasks ? 'tasks_desc' : 'records_desc');

    // Tab visual state (active color + underline).
    [['tasks-tab-tasks', isTasks], ['tasks-tab-records', !isTasks]].forEach(([id, active]) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.classList.toggle('text-primary-500', active);
        el.classList.toggle('text-slate-400', !active);
        el.classList.toggle('dark:text-slate-500', !active);
        const underline = el.querySelector('.tasks-tab-underline');
        if (underline) underline.classList.toggle('hidden', !active);
    });

    if (!isTasks) loadRunsView();
}

function refreshTasksView() {
    const btn = document.getElementById('task-refresh-btn');
    const icon = btn.querySelector('i');
    
    // Add spin animation
    icon.classList.add('fa-spin');
    btn.disabled = true;
    
    if (tasksActiveTab === 'records') {
        runsLoaded = false;
        loadRunsView();
    } else {
    tasksLoaded = false;
    const listEl = document.getElementById('tasks-list');
    listEl.innerHTML = '';
    loadTasksView();
    }
    
    // Restore button after animation ends
    setTimeout(() => {
        icon.classList.remove('fa-spin');
        btn.disabled = false;
    }, 500);
}

// ---- Execution records (history) -----------------------------------------

// Format a Unix-seconds timestamp for display; '--' when absent/invalid.
function formatRunTime(sec) {
    if (!sec) return '--';
    const d = new Date(sec * 1000);
    return isNaN(d.getTime()) ? '--' : d.toLocaleString();
}

// Compact elapsed time between start and end (blank while still running).
function formatRunDuration(start, end) {
    if (!start || !end || end < start) return '';
    const s = end - start;
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    const r = s % 60;
    return r ? `${m}m ${r}s` : `${m}m`;
}

// Status pill (done / error / running) matching the task-card status dot palette.
function runStatusBadge(status) {
    if (status === 'done') {
        return `<span class="inline-flex items-center gap-1 text-emerald-500"><i class="fas fa-circle-check text-xs"></i><span class="text-xs font-medium">${t('records_status_done')}</span></span>`;
    }
    if (status === 'error') {
        return `<span class="inline-flex items-center gap-1 text-red-500"><i class="fas fa-circle-xmark text-xs"></i><span class="text-xs font-medium">${t('records_status_error')}</span></span>`;
    }
    return `<span class="inline-flex items-center gap-1 text-slate-400"><i class="fas fa-spinner fa-spin text-xs"></i><span class="text-xs font-medium">${t('records_status_running')}</span></span>`;
}

// A web task is delivered to a chat session, not a bound IM instance, so present
// it with the friendly web type / name instead of a bare type + empty name.
function runChannelDisplay(run) {
    const isWeb = run.channel_type === 'web' || (!run.channel_type && !run.instance_id);
    if (isWeb) return { type: t('record_channel_web_type'), name: t('record_channel_web_name') };
    const inst = (taskInstances || []).find(i => i.instance_id === run.instance_id);
    return { type: run.channel_type || '', name: (inst && inst.name) || run.instance_id || '' };
}

const RUNS_PAGE_SIZE = 30;
let runsOffset = 0;
let runsHasMore = false;
let runsLoadingMore = false;

function loadRunsView() {
    if (runsLoaded) return;
    const rosterReady = agentCatalog.length ? Promise.resolve() : loadAgentCatalog();
    const loadingEl = document.getElementById('runs-loading');
    const emptyEl = document.getElementById('runs-empty');
    const listEl = document.getElementById('runs-list');
    loadingEl.classList.remove('hidden'); loadingEl.classList.add('flex');
    emptyEl.classList.add('hidden'); listEl.classList.add('hidden');
    runsOffset = 0; runsHasMore = false;

    rosterReady.then(() => Promise.all([
        // Empty agent_id => whole team's history (not the active chat Agent).
        fetch(`/api/scheduler/runs?agent_id=&limit=${RUNS_PAGE_SIZE}&offset=0`).then(r => r.json()).catch(() => null),
        // Instances feed the friendly channel-name resolution; cached in taskInstances.
        (taskInstances && taskInstances.length)
            ? Promise.resolve({ status: 'success', instances: taskInstances })
            : fetch('/api/scheduler/instances').then(r => r.json()).catch(() => null),
    ])).then(([runData, instData]) => {
        runsLoaded = true;
        loadingEl.classList.add('hidden'); loadingEl.classList.remove('flex');
        if (instData && instData.status === 'success') taskInstances = instData.instances || [];
        const runs = (runData && runData.status === 'success') ? (runData.runs || []) : [];
        if (runs.length === 0) {
            emptyEl.classList.remove('hidden'); emptyEl.classList.add('flex');
            listEl.classList.add('hidden');
            return;
        }
        emptyEl.classList.add('hidden'); emptyEl.classList.remove('flex');
        listEl.classList.remove('hidden');
        listEl.innerHTML = '';
        runs.forEach(run => listEl.appendChild(renderRunCard(run)));
        runsOffset = runs.length;
        runsHasMore = runs.length >= RUNS_PAGE_SIZE;
        renderRunsLoadMore();
    });
}

// Append the next page of records. A full page implies there may be more.
function loadMoreRuns() {
    if (runsLoadingMore || !runsHasMore) return;
    runsLoadingMore = true;
    const btn = document.getElementById('runs-load-more-btn');
    if (btn) { btn.disabled = true; btn.innerHTML = `<i class="fas fa-spinner fa-spin mr-1"></i>${t('records_loading')}`; }
    fetch(`/api/scheduler/runs?agent_id=&limit=${RUNS_PAGE_SIZE}&offset=${runsOffset}`)
        .then(r => r.json()).catch(() => null)
        .then(data => {
            runsLoadingMore = false;
            const runs = (data && data.status === 'success') ? (data.runs || []) : [];
            const listEl = document.getElementById('runs-list');
            runs.forEach(run => listEl.appendChild(renderRunCard(run)));
            runsOffset += runs.length;
            runsHasMore = runs.length >= RUNS_PAGE_SIZE;
            renderRunsLoadMore();
        });
}

// Render (or remove) the "load more" footer button below the list.
function renderRunsLoadMore() {
    const listEl = document.getElementById('runs-list');
    if (!listEl) return;
    let footer = document.getElementById('runs-load-more');
    if (!runsHasMore) { if (footer) footer.remove(); return; }
    if (!footer) {
        footer = document.createElement('div');
        footer.id = 'runs-load-more';
        footer.className = 'flex justify-center py-3';
        footer.innerHTML = `<button id="runs-load-more-btn" class="px-4 py-1.5 text-sm rounded-lg border border-slate-200 dark:border-white/10 text-slate-500 dark:text-slate-400 hover:border-slate-300 dark:hover:border-white/20 transition-colors">${t('records_load_more')}</button>`;
        footer.querySelector('#runs-load-more-btn').addEventListener('click', loadMoreRuns);
    } else {
        const b = footer.querySelector('#runs-load-more-btn');
        if (b) { b.disabled = false; b.innerHTML = t('records_load_more'); }
    }
    listEl.parentElement.appendChild(footer);
}

function renderRunCard(run) {
    const card = document.createElement('div');
    card.className = 'bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10 p-4 cursor-pointer hover:border-slate-300 dark:hover:border-white/20 transition-colors';
    const owner = (multiAgentMode() && run.agent_id) ? findAgent(run.agent_id) : null;
    const ownerChip = owner
        ? `<span class="inline-flex items-center gap-1 pl-1 pr-1.5 py-0.5 rounded-full bg-slate-100 dark:bg-white/10 text-[10px] leading-none text-slate-400 dark:text-slate-500">${agentAvatarHTML(owner, 15)}<span class="truncate max-w-[80px]">${escapeHtml(owner.name || owner.id)}</span></span>`
        : '';
    const trigger = run.trigger === 'manual' ? t('records_trigger_manual') : t('records_trigger_scheduled');
    const duration = formatRunDuration(run.started_at, run.ended_at);
    const bodyLine = (run.status === 'error' && run.error)
        ? `<p class="text-xs text-red-500 mb-2 line-clamp-2 break-words">${escapeHtml(run.error)}</p>`
        : `<p class="text-xs text-slate-500 dark:text-slate-400 mb-2 line-clamp-2 break-words">${run.output_preview ? escapeHtml(run.output_preview) : `<span class="italic text-slate-400">${t('records_no_output')}</span>`}</p>`;
    card.innerHTML = `
        <div class="flex items-center gap-2 mb-1.5">
            ${runStatusBadge(run.status)}
            <span class="font-medium text-sm text-slate-700 dark:text-slate-200 truncate">${escapeHtml(run.task_name || run.task_id || t('tasks_tab_records'))}</span>
            ${ownerChip}
            <div class="flex-1"></div>
            <span class="text-[10px] px-1.5 py-0.5 rounded-full bg-slate-100 dark:bg-white/10 text-slate-400 dark:text-slate-500">${escapeHtml(trigger)}</span>
            <button class="run-delete-btn text-slate-300 hover:text-red-500 dark:text-slate-600 dark:hover:text-red-400 transition-colors px-1" title="${t('records_delete')}"><i class="fas fa-trash-can text-xs"></i></button>
        </div>
        ${bodyLine}
        <div class="flex items-center gap-2 text-xs text-slate-400 dark:text-slate-500">
            <i class="fas fa-clock"></i><span>${formatRunTime(run.started_at)}</span>
            ${duration ? `<span class="opacity-50">·</span><span>${t('records_duration')} ${duration}</span>` : ''}
        </div>`;
    card.addEventListener('click', () => showRunDetailModal(run));
    const delBtn = card.querySelector('.run-delete-btn');
    if (delBtn) {
        delBtn.addEventListener('click', (e) => {
            e.stopPropagation();   // don't open the detail modal
            deleteRunRecord(run, card);
        });
    }
    return card;
}

// Confirm, then delete one execution record and drop its card from the list.
function deleteRunRecord(run, card) {
    showConfirmDialog({
        title: t('records_delete_confirm_title'),
        message: t('records_delete_confirm_msg'),
        okText: t('records_delete'),
        onConfirm: () => {
            fetch('/api/scheduler/runs/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ run_id: run.run_id })
            }).then(r => r.json()).then(res => {
                if (res.status !== 'success') throw new Error(res.message || 'delete failed');
                card.remove();
                if (runsOffset > 0) runsOffset -= 1;   // keep paging offset aligned
                const listEl = document.getElementById('runs-list');
                if (listEl && listEl.children.length === 0 && !runsHasMore) {
                    const emptyEl = document.getElementById('runs-empty');
                    listEl.classList.add('hidden');
                    if (emptyEl) { emptyEl.classList.remove('hidden'); emptyEl.classList.add('flex'); }
                }
            }).catch(() => {
                alert(t('records_delete_failed'));
            });
        }
    });
}

function showRunDetailModal(run) {
    const overlay = document.getElementById('run-detail-modal-overlay');
    document.getElementById('run-detail-title').textContent = run.task_name || run.task_id || t('record_detail_title');

    const ch = runChannelDisplay(run);
    const owner = (multiAgentMode() && run.agent_id) ? findAgent(run.agent_id) : null;
    const trigger = run.trigger === 'manual' ? t('records_trigger_manual') : t('records_trigger_scheduled');
    const duration = formatRunDuration(run.started_at, run.ended_at);
    const cell = (label, valueHtml) => `<div><div class="text-xs text-slate-400 dark:text-slate-500 mb-0.5">${label}</div><div class="text-slate-700 dark:text-slate-200">${valueHtml}</div></div>`;
    const meta = [];
    meta.push(cell(t('record_detail_status'), runStatusBadge(run.status)));
    meta.push(cell(t('record_detail_trigger'), escapeHtml(trigger)));
    meta.push(cell(t('record_detail_started'), escapeHtml(formatRunTime(run.started_at))));
    if (duration) meta.push(cell(t('record_detail_duration'), escapeHtml(duration)));
    if (ch.type) meta.push(cell(t('record_detail_channel_type'), escapeHtml(ch.type)));
    if (ch.name) meta.push(cell(t('record_detail_channel_name'), `<span class="break-all">${escapeHtml(ch.name)}</span>`));
    if (owner) meta.push(cell(t('record_detail_agent'), `<span class="inline-flex items-center gap-1.5">${agentAvatarHTML(owner, 16)}<span class="truncate max-w-[140px]">${escapeHtml(owner.name || owner.id)}</span></span>`));
    document.getElementById('run-detail-meta').innerHTML = meta.join('');

    const errWrap = document.getElementById('run-detail-error-wrap');
    if (run.status === 'error' && run.error) {
        errWrap.classList.remove('hidden');
        document.getElementById('run-detail-error').textContent = run.error;
    } else {
        errWrap.classList.add('hidden');
    }

    const outEl = document.getElementById('run-detail-output');
    // Show the preview immediately, then swap in the full body once fetched.
    outEl.innerHTML = `<span class="text-slate-400"><i class="fas fa-spinner fa-spin mr-1"></i>${t('record_detail_loading')}</span>`;
    runDetailBody = '';
    runDetailView = 'preview';  // always default to rendered markdown on open
    updateRunDetailViewToggle();
    overlay.classList.remove('hidden');

    fetch(`/api/scheduler/runs/detail?run_id=${encodeURIComponent(run.run_id)}`)
        .then(r => r.json())
        .then(data => {
            const detail = (data && data.status === 'success') ? data.run : null;
            const body = (detail && detail.full_output) || run.output_preview || '';
            runDetailBody = body;
            renderRunDetailOutput();
        })
        .catch(() => {
            runDetailBody = run.output_preview || '';
            renderRunDetailOutput();
        });
}

// The run-detail output can be shown as rendered Markdown (default) or as raw
// text. We keep the fetched body around so toggling between the two views never
// needs a refetch.
let runDetailBody = '';
let runDetailView = 'preview';  // 'preview' (markdown) | 'text' (raw)

function renderRunDetailOutput() {
    const outEl = document.getElementById('run-detail-output');
    if (!outEl) return;
    if (!runDetailBody) {
        outEl.classList.remove('whitespace-pre-wrap');
        outEl.innerHTML = `<span class="italic text-slate-400">${t('records_no_output')}</span>`;
        return;
    }
    if (runDetailView === 'text') {
        // Raw text: preserve newlines/indentation, no markdown parsing.
        outEl.classList.add('whitespace-pre-wrap');
        outEl.textContent = runDetailBody;
    } else {
        outEl.classList.remove('whitespace-pre-wrap');
        // Use .msg-content (not just .agent-content-body): the full markdown
        // styling — paragraph spacing, headings, lists, tables, code — is scoped
        // to .msg-content. Without it Tailwind's preflight resets p/h margins to
        // 0, so a multi-paragraph body renders as one flat block with no visible
        // breaks (the "no markdown newlines" bug).
        outEl.innerHTML = `<div class="msg-content agent-content-body">${renderMarkdown(runDetailBody)}</div>`;
    }
}

function updateRunDetailViewToggle() {
    const toggle = document.getElementById('run-detail-view-toggle');
    if (!toggle) return;
    toggle.querySelectorAll('button[data-view]').forEach(btn => {
        const active = btn.dataset.view === runDetailView;
        btn.classList.toggle('bg-slate-800', active);
        btn.classList.toggle('dark:bg-white/15', active);
        btn.classList.toggle('text-white', active);
        btn.classList.toggle('dark:text-white', active);
        btn.classList.toggle('text-slate-500', !active);
        btn.classList.toggle('dark:text-slate-400', !active);
    });
}

function setRunDetailView(view) {
    if (view !== 'preview' && view !== 'text') return;
    runDetailView = view;
    updateRunDetailViewToggle();
    renderRunDetailOutput();
}

(function wireRunDetailModal() {
    const overlay = document.getElementById('run-detail-modal-overlay');
    if (!overlay) return;
    const close = () => overlay.classList.add('hidden');
    const closeBtn = document.getElementById('run-detail-close');
    if (closeBtn) closeBtn.addEventListener('click', close);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    const toggle = document.getElementById('run-detail-view-toggle');
    if (toggle) {
        toggle.querySelectorAll('button[data-view]').forEach(btn => {
            btn.addEventListener('click', () => setRunDetailView(btn.dataset.view));
        });
    }
})();

function runTaskNow(task, button) {
    showConfirmDialog({
        title: t('task_run_confirm_title'),
        message: `${task.name || task.id}: ${t('task_run_confirm_msg')}`,
        okText: t('task_run_now'),
        onConfirm: () => {
            const originalHtml = button.innerHTML;
            button.disabled = true;
            button.innerHTML = `<i class="fas fa-spinner fa-spin mr-1"></i>${t('task_run_now')}`;
            fetch('/api/scheduler/run', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({task_id: task.id, agent_id: task.agent_id || ''})
            }).then(r => r.json()).then(res => {
                if (res.status !== 'success') throw new Error(res.message || t('task_run_failed'));
                // Remember this tab kicked off the run so its notification is
                // routed back here (see maybeNotifyScheduledRun), not to some
                // other tab that also happens to have this session open.
                _claimManualRunOrigin(task.id);
                button.innerHTML = `<i class="fas fa-check mr-1"></i>${t('task_run_started')}`;
                setTimeout(() => {
                    button.innerHTML = originalHtml;
                    button.disabled = false;
                }, 1500);
            }).catch(() => {
                button.innerHTML = `<i class="fas fa-triangle-exclamation mr-1"></i>${t('task_run_failed')}`;
                setTimeout(() => {
                    button.innerHTML = originalHtml;
                    button.disabled = false;
                }, 2000);
            });
        }
    });
}

function loadTasksView() {
    if (tasksLoaded) return;
    // The list tags each task with an owning Agent; make sure the roster is in
    // hand first so findAgent()/multiAgentMode() can resolve the avatar + name.
    const rosterReady = agentCatalog.length ? Promise.resolve() : loadAgentCatalog();
    rosterReady.then(() => {
    // Explicit empty agent_id so the global fetch wrapper doesn't inject the
    // active chat Agent: the task list is the whole team's schedule and must
    // NOT follow whichever Agent the conversation is currently on. The backend
    // treats an empty agent_id as "aggregate across all Agents".
    fetch('/api/scheduler?agent_id=').then(r => r.json()).then(data => {
        if (data.status !== 'success') return;
        const emptyEl = document.getElementById('tasks-empty');
        const listEl = document.getElementById('tasks-list');
        const allTasks = data.tasks || [];
        // Backend already sorted by enabled and next_run_at, no need to re-sort on frontend
        if (allTasks.length === 0) {
            emptyEl.querySelector('p').textContent = currentLang === 'zh' ? '暂无定时任务' : 'No scheduled tasks';
            emptyEl.classList.remove('hidden');
            listEl.classList.add('hidden');
            tasksLoaded = true;
            return;
        }
        emptyEl.classList.add('hidden');
        listEl.classList.remove('hidden');
        listEl.innerHTML = '';

        allTasks.forEach(task => {
            const isEnabled = task.enabled !== false;
            const card = document.createElement('div');
            card.className = 'bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10 p-4';
            card.dataset.taskId = task.id;
            if (!isEnabled) card.classList.add('opacity-50');
            const schedule = task.schedule || {};
            let typeLabel = '';
            if (schedule.type === 'cron') {
                typeLabel = `<span class="text-xs font-mono text-slate-400">${escapeHtml(schedule.expression || '')}</span>`;
            } else if (schedule.type === 'interval') {
                const seconds = schedule.seconds || 0;
                const hours = Math.floor(seconds / 3600);
                const mins = Math.floor((seconds % 3600) / 60);
                const secs = seconds % 60;
                let intervalText = [];
                if (hours > 0) intervalText.push(`${hours}h`);
                if (mins > 0) intervalText.push(`${mins}m`);
                if (secs > 0 || intervalText.length === 0) intervalText.push(`${secs}s`);
                typeLabel = `<span class="text-xs text-slate-400">${intervalText.join(' ')}</span>`;
            } else {
                typeLabel = `<span class="text-xs text-slate-400">${escapeHtml(schedule.type || 'once')}</span>`;
            }
            let nextRun = '--';
            if (task.next_run_at) {
                const d = new Date(task.next_run_at);
                if (!isNaN(d.getTime())) nextRun = d.toLocaleString();
            }
            const action = task.action || {};
            const taskContent = action.content || action.task_description || '';
            const toggleId = 'toggle-' + task.id;
            // Owner chip: only when several Agents exist (otherwise every task
            // carries the same face and it's just noise). Empty on a solo install.
            const owner = (multiAgentMode() && task.agent_id) ? findAgent(task.agent_id) : null;
            const ownerChip = owner
                ? `<span class="inline-flex items-center gap-1 ml-2 pl-1 pr-1.5 py-0.5 rounded-full bg-slate-100 dark:bg-white/10 text-[10px] leading-none text-slate-400 dark:text-slate-500">
                        ${agentAvatarHTML(owner, 15)}<span class="truncate max-w-[80px]">${escapeHtml(owner.name || owner.id)}</span>
                   </span>`
                : '';
            card.innerHTML = `
                <div class="flex items-center gap-2 mb-2">
                    <span class="w-2 h-2 rounded-full ${isEnabled ? 'bg-primary-400' : 'bg-slate-300 dark:bg-slate-600'}"></span>
                    <span class="font-medium text-sm text-slate-700 dark:text-slate-200">${escapeHtml(task.name || task.id || '--')}</span>
                    ${ownerChip}
                    <div class="flex-1"></div>
                    ${typeLabel}
                </div>
                <p class="text-xs text-slate-500 dark:text-slate-400 mb-2 line-clamp-2">${escapeHtml(taskContent)}</p>
                <div class="flex items-center gap-4 text-xs text-slate-400 dark:text-slate-500">
                    <span><i class="fas fa-clock mr-1"></i>${currentLang === 'zh' ? '下次执行' : 'Next run'}: ${nextRun}</span>
                    <div class="flex-1"></div>
                    <button type="button" class="task-run-now px-2 py-1 rounded-md text-primary-500 hover:bg-primary-50 dark:hover:bg-primary-500/10 transition-colors">
                        <i class="fas fa-play mr-1"></i>${t('task_run_now')}
                    </button>
                    <label class="relative inline-flex items-center cursor-pointer" for="${toggleId}">
                        <input type="checkbox" id="${toggleId}" class="sr-only peer" ${isEnabled ? 'checked' : ''}>
                        <div class="w-9 h-5 bg-slate-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-primary-500 dark:bg-slate-600 dark:peer-checked:bg-primary-500"></div>
                    </label>
                </div>`;
            const runButton = card.querySelector('.task-run-now');
            runButton.addEventListener('click', function(e) {
                e.stopPropagation();
                runTaskNow(task, runButton);
            });
            const checkbox = card.querySelector('#' + toggleId);
            checkbox.addEventListener('change', function() {
                const newEnabled = this.checked;
                fetch('/api/scheduler/toggle', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({task_id: task.id, enabled: newEnabled, agent_id: task.agent_id || ''})
                }).then(r => r.json()).then(res => {
                    if (res.status === 'success') {
                        const dot = card.querySelector('.rounded-full.w-2');
                        if (newEnabled) {
                            card.classList.remove('opacity-50');
                            if (dot) { dot.classList.remove('bg-slate-300','dark:bg-slate-600'); dot.classList.add('bg-primary-400'); }
                        } else {
                            card.classList.add('opacity-50');
                            if (dot) { dot.classList.remove('bg-primary-400'); dot.classList.add('bg-slate-300','dark:bg-slate-600'); }
                        }
                    } else {
                        this.checked = !newEnabled;
                    }
                }).catch(() => { this.checked = !newEnabled; });
            });
            // Card click event (excluding toggle switch clicks)
            card.addEventListener('click', function(e) {
                if (!e.target.closest('label') && !e.target.closest('input[type="checkbox"]')) {
                    openTaskEditModal(task);
                }
            });
            card.style.cursor = 'pointer';
            listEl.appendChild(card);
        });
        tasksLoaded = true;
    }).catch(() => {});
    });
}

// =====================================================================
// Logs View
// =====================================================================
let logEventSource = null;

function logLevelClass(line) {
    if (/\[CRITICAL\]/.test(line)) return 'log-line-critical';
    if (/\[ERROR\]/.test(line))    return 'log-line-error';
    if (/\[WARNING\]/.test(line))  return 'log-line-warning';
    if (/\[INFO\]/.test(line))     return 'log-line-info';
    if (/\[DEBUG\]/.test(line))    return 'log-line-debug';
    return '';
}

function getHiddenLevels() {
    const hidden = new Set();
    document.querySelectorAll('.log-filter-cb').forEach(function(cb) {
        if (!cb.checked) hidden.add('log-line-' + cb.dataset.level);
    });
    return hidden;
}

function applyLogFilter() {
    const hidden = getHiddenLevels();
    document.querySelectorAll('#log-output .log-line').forEach(function(span) {
        const level = span.classList[1] || '';
        span.style.display = hidden.has(level) ? 'none' : '';
    });
}

function appendLogLines(output, text) {
    const hidden = getHiddenLevels();
    let lastLevelClass = '';
    const lines = text.split('\n');
    lines.forEach(function(line, i) {
        if (i === lines.length - 1 && line === '') return;
        const span = document.createElement('span');
        const levelClass = logLevelClass(line) || lastLevelClass;
        if (logLevelClass(line)) lastLevelClass = levelClass;
        span.className = 'log-line ' + levelClass;
        span.textContent = line + '\n';
        if (hidden.has(levelClass)) span.style.display = 'none';
        output.appendChild(span);
    });
}

document.addEventListener('change', function(e) {
    if (e.target.classList.contains('log-filter-cb')) applyLogFilter();
});

function startLogStream() {
    if (logEventSource) return;
    const output = document.getElementById('log-output');
    output.innerHTML = '';

    logEventSource = new EventSource('/api/logs');
    logEventSource.onmessage = function(e) {
        let item;
        try { item = JSON.parse(e.data); } catch (_) { return; }

        if (item.type === 'init') {
            output.innerHTML = '';
            appendLogLines(output, item.content || '');
            output.scrollTop = output.scrollHeight;
        } else if (item.type === 'line') {
            appendLogLines(output, item.content);
            output.scrollTop = output.scrollHeight;
        } else if (item.type === 'error') {
            output.textContent = item.message || 'Error loading logs';
        }
    };
    logEventSource.onerror = function() {
        logEventSource.close();
        logEventSource = null;
    };
}

function stopLogStream() {
    if (logEventSource) {
        logEventSource.close();
        logEventSource = null;
    }
}

// =====================================================================
// View Navigation Hook
// =====================================================================
const _origNavigateTo = navigateTo;
navigateTo = function(viewId) {
    // An open document editor is about to be replaced by another view, which
    // would drop the edit with nothing on screen to say so.
    if (!docGuardUnsaved(() => navigateTo(viewId))) return;

    // Stop log stream when leaving logs view
    if (currentView === 'logs' && viewId !== 'logs') stopLogStream();

    _origNavigateTo(viewId);

    // Lazy-load view data
    if (viewId === 'config') { loadConfigView(); switchConfigTab('basic'); }
    else if (viewId === 'skills') { resetSkillViewer(); loadSkillsView(); }
    else if (viewId === 'memory') {
        memoryEditor.forget();
        document.getElementById('memory-panel-viewer').classList.add('hidden');
        document.getElementById('memory-panel-list').classList.remove('hidden');
        // Keep the last viewed Agent across refreshes, but drop it if that
        // Agent has since been deleted so we don't point at a ghost.
        if (memoryAgentId && agentCatalog.length && !agentCatalog.some(a => a.id === memoryAgentId)) {
            memoryAgentId = '';
            localStorage.removeItem('cow_memory_agent');
        }
        if (!memoryAgentId) memoryAgentId = activeAgentId || defaultAgentId;
        renderMemoryAgentSelect();
        switchMemoryTab('files');
    }
    else if (viewId === 'knowledge') loadKnowledgeView();
    else if (viewId === 'channels') loadChannelsView();
    else if (viewId === 'tasks') { switchTasksTab('tasks'); loadTasksView(); }
    else if (viewId === 'logs') startLogStream();
};

// =====================================================================
// Knowledge View
// =====================================================================
let _knowledgeTreeData = [];
let _knowledgeRootFiles = [];
let _knowledgeCurrentFile = null;
let _knowledgeGraphLoaded = false;
const KNOWLEDGE_IMPORT_MAX_FILES = 100;
const KNOWLEDGE_IMPORT_MAX_FILE_SIZE = 10 * 1024 * 1024;
const KNOWLEDGE_IMPORT_MAX_TOTAL_SIZE = 200 * 1024 * 1024;

// Which Agent's knowledge base the page is viewing. Persisted like the memory
// page's selector so a refresh keeps the last choice. An Agent on "shared" mode
// resolves to the shared base on the backend, so this simply scopes the view.
let knowledgeAgentId = localStorage.getItem('cow_knowledge_agent') || '';

function viewingKnowledgeAgentId() {
    return knowledgeAgentId || activeAgentId || defaultAgentId;
}

// Append the viewed Agent to a knowledge URL. The global fetch wrapper only
// injects activeAgentId when no agent_id is present, so an explicit one wins.
function _kbUrl(path) {
    const joiner = path.includes('?') ? '&' : '?';
    return `${path}${joiner}agent_id=${encodeURIComponent(viewingKnowledgeAgentId())}`;
}

function renderKnowledgeAgentSelect() {
    const el = document.getElementById('knowledge-agent-select');
    if (!el) return;
    const current = viewingKnowledgeAgentId();
    const list = agentCatalog.length ? agentCatalog : enabledAgents();
    const options = list.map(a => ({ value: a.id, label: a.name || a.id, agent: a }));
    initDropdown(el, options, current, (value) => selectKnowledgeAgent(value), { withAvatar: true });
}

function selectKnowledgeAgent(agentId) {
    knowledgeAgentId = agentId;
    localStorage.setItem('cow_knowledge_agent', agentId);
    loadKnowledgeView();
}

function loadKnowledgeView(targetPath) {
    // Reset to docs tab
    switchKnowledgeTab('docs');
    _knowledgeGraphLoaded = false;
    _knowledgeCurrentFile = null;

    // Drop a deleted Agent selection so we never point at a ghost.
    if (knowledgeAgentId && agentCatalog.length && !agentCatalog.some(a => a.id === knowledgeAgentId)) {
        knowledgeAgentId = '';
        localStorage.removeItem('cow_knowledge_agent');
    }
    renderKnowledgeAgentSelect();

    fetch(_kbUrl('/api/knowledge/list')).then(r => r.json()).then(data => {
        if (data.status !== 'success') return;
        initKnowledgeImportDropZone();

        const emptyEl = document.getElementById('knowledge-empty');
        const docsPanel = document.getElementById('knowledge-panel-docs');
        const statsEl = document.getElementById('knowledge-stats');

        const tree = data.tree || [];
        const rootFiles = data.root_files || [];
        _knowledgeTreeData = tree;
        _knowledgeRootFiles = rootFiles;
        const stats = data.stats || {};
        const totalPages = stats.pages || 0;
        const sizeStr = stats.size < 1024 ? stats.size + ' B' : (stats.size / 1024).toFixed(1) + ' KB';

        statsEl.textContent = totalPages + ' pages · ' + sizeStr;

        if (totalPages === 0 && tree.length === 0 && rootFiles.length === 0) {
            emptyEl.querySelector('p').textContent = t('knowledge_empty_hint');
            const guideEl = document.getElementById('knowledge-empty-guide');
            if (guideEl) guideEl.classList.remove('hidden');
            emptyEl.classList.remove('hidden');
            docsPanel.classList.add('hidden');
            return;
        }
        emptyEl.classList.add('hidden');
        docsPanel.classList.remove('hidden');

        renderKnowledgeTree(tree, rootFiles);

        // Prefer opening the just created/imported file; ensure its group is
        // expanded so the active item is visible in the tree.
        const targetTitle = targetPath ? _findKnowledgeFileTitle(targetPath) : null;
        if (targetTitle !== null) {
            _expandKnowledgeGroupFor(targetPath);
            openKnowledgeFile(targetPath, targetTitle);
            return;
        }

        // Auto-select the first file (desktop only)
        if (window.innerWidth >= 768) {
            const firstFile = rootFiles.length > 0 ? rootFiles[0] : null;
            const firstGroup = !firstFile ? tree.find(g => g.files && g.files.length > 0) : null;
            if (firstFile) {
                openKnowledgeFile(firstFile.name, firstFile.title);
            } else if (firstGroup) {
                const gf = firstGroup.files[0];
                openKnowledgeFile(firstGroup.dir + '/' + gf.name, gf.title);
            }
        } else {
            document.getElementById('knowledge-content-placeholder').classList.add('hidden');
            document.getElementById('knowledge-content-viewer').classList.add('hidden');
        }
    }).catch(() => {});
}

// Find a file's display title by its relative path within the knowledge tree.
// Returns the title, or null when the path is not present.
function _findKnowledgeFileTitle(path) {
    if (!path) return null;
    const rootHit = (_knowledgeRootFiles || []).find(f => f.name === path);
    if (rootHit) return rootHit.title || rootHit.name;
    const walk = (groups, parentPath) => {
        for (const group of groups || []) {
            const groupPath = parentPath ? `${parentPath}/${group.dir}` : group.dir;
            const hit = (group.files || []).find(f => `${groupPath}/${f.name}` === path);
            if (hit) return hit.title || hit.name;
            const childHit = walk(group.children, groupPath);
            if (childHit !== null) return childHit;
        }
        return null;
    };
    return walk(_knowledgeTreeData, '');
}

// Open every ancestor group of the given file path so it is visible.
function _expandKnowledgeGroupFor(path) {
    if (!path || !path.includes('/')) return;
    const target = document.querySelector(`.knowledge-tree-file[data-path="${CSS.escape(path)}"]`);
    let node = target ? target.closest('.knowledge-tree-group') : null;
    while (node) {
        node.classList.add('open');
        node = node.parentElement ? node.parentElement.closest('.knowledge-tree-group') : null;
    }
}

function renderKnowledgeTree(tree, rootFilesOrFilter, filter) {
    const container = document.getElementById('knowledge-tree');
    container.innerHTML = '';
    let rootFiles, lowerFilter;
    if (typeof rootFilesOrFilter === 'string') {
        rootFiles = _knowledgeRootFiles;
        lowerFilter = (rootFilesOrFilter || '').toLowerCase();
    } else {
        rootFiles = rootFilesOrFilter || _knowledgeRootFiles;
        lowerFilter = (filter || '').toLowerCase();
    }
    (rootFiles || []).forEach(f => {
        if (lowerFilter && !f.title.toLowerCase().includes(lowerFilter) && !f.name.toLowerCase().includes(lowerFilter)) return;
        const fbtn = document.createElement('button');
        fbtn.className = 'knowledge-tree-file' + (_knowledgeCurrentFile === f.name ? ' active' : '');
        fbtn.dataset.path = f.name;
        fbtn.innerHTML = `<i class="fas fa-file-lines text-[10px] text-slate-400"></i><span class="truncate">${escapeHtml(f.title)}</span>${_knowledgeFileActions(f.name)}`;
        fbtn.onclick = () => openKnowledgeFile(f.name, f.title);
        container.appendChild(fbtn);
    });
    _renderKnowledgeGroups(container, tree, '', lowerFilter, 0);
}

function _renderKnowledgeGroups(container, groups, parentPath, lowerFilter, depth) {
    const indent = depth * 12;
    groups.forEach(group => {
        const groupPath = parentPath ? parentPath + '/' + group.dir : group.dir;
        const files = (group.files || []).filter(f =>
            !lowerFilter || f.title.toLowerCase().includes(lowerFilter) || f.name.toLowerCase().includes(lowerFilter)
        );
        const children = group.children || [];
        const hasMatchingChildren = lowerFilter ? _hasFilterMatch(children, lowerFilter) : children.length > 0;
        if (files.length === 0 && !hasMatchingChildren && lowerFilter) return;

        const div = document.createElement('div');
        div.className = 'knowledge-tree-group open';

        const fileCount = _countFiles(group);
        const btn = document.createElement('button');
        btn.className = 'knowledge-tree-group-btn';
        btn.style.paddingLeft = (8 + indent) + 'px';
        btn.innerHTML = `<i class="fas fa-chevron-right chevron"></i><i class="fas fa-folder text-amber-400 text-[11px]"></i><span>${escapeHtml(group.dir)}</span><span class="ml-auto text-[10px] text-slate-400">${fileCount}</span>${_knowledgeCategoryActions(groupPath)}`;
        btn.onclick = () => div.classList.toggle('open');
        div.appendChild(btn);

        const items = document.createElement('div');
        items.className = 'knowledge-tree-group-items';
        files.forEach(f => {
            const fbtn = document.createElement('button');
            const fpath = groupPath + '/' + f.name;
            fbtn.className = 'knowledge-tree-file' + (_knowledgeCurrentFile === fpath ? ' active' : '');
            fbtn.dataset.path = fpath;
            fbtn.style.paddingLeft = (24 + indent) + 'px';
            fbtn.innerHTML = `<i class="fas fa-file-lines text-[10px] text-slate-400"></i><span class="truncate">${escapeHtml(f.title)}</span>${_knowledgeFileActions(fpath)}`;
            fbtn.onclick = () => openKnowledgeFile(fpath, f.title);
            items.appendChild(fbtn);
        });
        if (children.length > 0) {
            _renderKnowledgeGroups(items, children, groupPath, lowerFilter, depth + 1);
        }
        div.appendChild(items);
        container.appendChild(div);
    });
}

function _knowledgeActionButton(icon, title, handler) {
    const danger = icon === 'fa-trash' ? ' danger' : '';
    return `<span role="button" tabindex="0" title="${escapeHtml(title)}" onclick="event.stopPropagation();${handler}" class="knowledge-action${danger}"><i class="fas ${icon}"></i></span>`;
}

function _knowledgeFileActions(path) {
    if (path === 'index.md' || path === 'log.md') return '';
    const value = JSON.stringify(path).replace(/"/g, '&quot;');
    return `<span class="knowledge-actions">${_knowledgeActionButton('fa-arrow-right-arrow-left', '移动', `moveKnowledgeDocument(${value})`)}${_knowledgeActionButton('fa-trash', '删除', `deleteKnowledgeDocument(${value})`)}</span>`;
}

function _knowledgeCategoryActions(path) {
    const value = JSON.stringify(path).replace(/"/g, '&quot;');
    return `<span class="knowledge-actions">${_knowledgeActionButton('fa-pen', '重命名', `renameKnowledgeCategory(${value})`)}${_knowledgeActionButton('fa-trash', '删除', `deleteKnowledgeCategory(${value})`)}</span>`;
}

async function dispatchKnowledgeAction(action, payload, openPathResolver) {
    _setKnowledgeStatus(currentLang === 'zh' ? '处理中...' : 'Working...', false, true);
    try {
        const response = await fetch('/api/knowledge/action', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({action, payload, agent_id: viewingKnowledgeAgentId()}),
        });
        const result = await response.json();
        if (result.status !== 'success') {
            _setKnowledgeStatus(result.message || (currentLang === 'zh' ? '操作失败' : 'Operation failed'), true);
            loadKnowledgeView();
            return null;
        }
        _setKnowledgeStatus(_knowledgeResultMessage(action, result.payload), false);
        // Optionally auto-open the affected file after the tree refreshes.
        const openPath = openPathResolver ? openPathResolver(result.payload) : null;
        loadKnowledgeView(openPath || undefined);
        return result.payload;
    } catch (error) {
        _setKnowledgeStatus(currentLang === 'zh' ? '请求失败，请稍后重试' : 'Request failed, please try again', true);
        return null;
    }
}

function _setKnowledgeStatus(message, isError, persistent) {
    const el = document.getElementById('knowledge-action-status');
    el.textContent = message;
    el.className = `text-xs transition-opacity duration-200 ${isError ? 'text-red-500' : 'text-primary-500'}`;
    el.classList.remove('opacity-0');
    clearTimeout(el._hideTimer);
    if (!persistent) el._hideTimer = setTimeout(() => el.classList.add('opacity-0'), 3500);
}

function _knowledgeResultMessage(action, payload) {
    if (currentLang !== 'zh') {
        return action === 'create_category' ? 'Category created' :
            action === 'create_document' ? 'Document created' :
            action === 'rename_category' ? 'Category renamed' :
            action === 'delete_category' ? 'Category deleted' :
            action === 'import_documents' ? `${payload?.imported || 0} imported · ${payload?.skipped || 0} skipped · ${payload?.failed || 0} failed` :
            action === 'move_documents' ? `${payload?.moved || 0} document moved` :
            `${payload?.deleted || 0} document deleted`;
    }
    return action === 'create_category' ? '分类已创建' :
        action === 'create_document' ? '文档已创建' :
        action === 'rename_category' ? '分类已重命名' :
        action === 'delete_category' ? '分类已删除' :
        action === 'import_documents' ? `导入 ${payload?.imported || 0} 个，跳过 ${payload?.skipped || 0} 个，失败 ${payload?.failed || 0} 个` :
        action === 'move_documents' ? `已移动 ${payload?.moved || 0} 个文档` :
        `已删除 ${payload?.deleted || 0} 个文档`;
}

function _knowledgeCategoryPaths(groups, parent = '') {
    const paths = [];
    for (const group of groups || []) {
        const path = parent ? `${parent}/${group.dir}` : group.dir;
        paths.push(path, ..._knowledgeCategoryPaths(group.children || [], path));
    }
    return paths;
}

function openKnowledgeDialog(options) {
    const overlay = document.getElementById('knowledge-dialog-overlay');
    const card = document.getElementById('knowledge-dialog-card');
    const input = document.getElementById('knowledge-dialog-input');
    const select = document.getElementById('knowledge-dialog-select');
    const textarea = document.getElementById('knowledge-dialog-textarea');
    const documentForm = document.getElementById('knowledge-document-form');
    const documentFilename = document.getElementById('knowledge-document-filename');
    const documentContent = document.getElementById('knowledge-document-content');
    const templateBtn = document.getElementById('knowledge-document-template');
    const documentPathPreview = document.getElementById('knowledge-document-path-preview');
    const submit = document.getElementById('knowledge-dialog-submit');
    const cancel = document.getElementById('knowledge-dialog-cancel');
    document.getElementById('knowledge-dialog-title').textContent = options.title;
    document.getElementById('knowledge-dialog-subtitle').textContent = options.subtitle || '';
    document.getElementById('knowledge-dialog-label').textContent = options.label;
    document.getElementById('knowledge-dialog-hint').textContent = options.hint || '';
    document.getElementById('knowledge-dialog-error').classList.add('hidden');
    document.getElementById('knowledge-dialog-icon').className = `fas ${options.icon || 'fa-folder'} text-emerald-500`;
    card.classList.toggle('knowledge-document-dialog', options.type === 'document');
    input.classList.toggle('hidden', options.type === 'select' || options.type === 'textarea' || options.type === 'document');
    select.classList.toggle('hidden', options.type !== 'select');
    textarea.classList.toggle('hidden', options.type !== 'textarea');
    documentForm.classList.toggle('hidden', options.type !== 'document');
    input.value = options.value || '';
    textarea.value = options.value || '';
    documentFilename.value = options.filename || '';
    documentContent.value = options.content || '';
    document.getElementById('knowledge-document-category-label').textContent = currentLang === 'zh' ? '目标分类' : 'Destination category';
    documentPathPreview.textContent = options.category
        ? `knowledge/${options.category}/`
        : 'knowledge/';
    documentFilename.oninput = null;
    document.getElementById('knowledge-document-filename-label').textContent = currentLang === 'zh' ? '文件名' : 'Filename';
    document.getElementById('knowledge-document-content-label').textContent = currentLang === 'zh' ? 'Markdown 内容' : 'Markdown content';
    templateBtn.textContent = currentLang === 'zh' ? '插入模板' : 'Insert template';
    templateBtn.onclick = () => {
        if (documentContent.value.trim()) return;
        const title = (documentFilename.value || 'untitled').replace(/\.md$/i, '');
        documentContent.value = currentLang === 'zh'
            ? `# ${title}\n\n## 摘要\n\n\n## 关键点\n\n- \n\n## 参考\n\n`
            : `# ${title}\n\n## Summary\n\n\n## Key points\n\n- \n\n## References\n\n`;
        documentContent.focus();
    };
    if (options.type === 'select') {
        // Use the shared custom dropdown component instead of a native
        // <select> so the arrow / menu match the rest of the console.
        const ddOptions = (options.choices || []).map(value => ({ value, label: value }));
        initDropdown(select, ddOptions, (options.choices || [])[0] || '', null);
    }
    submit.textContent = currentLang === 'zh' ? '确定' : 'Confirm';
    cancel.textContent = currentLang === 'zh' ? '取消' : 'Cancel';
    submit.disabled = options.type === 'select' && !(options.choices || []).length;

    const close = () => overlay.classList.add('hidden');
    const submitAction = async () => {
        const rawValue = options.type === 'select' ? getDropdownValue(select) :
            (options.type === 'textarea' ? textarea.value :
            (options.type === 'document' ? {
                filename: documentFilename.value.trim(),
                content: documentContent.value,
            } : input.value));
        const value = options.type === 'textarea' || options.type === 'document' ? rawValue : rawValue.trim();
        const error = options.validate ? options.validate(value) : (!value ? (currentLang === 'zh' ? '此项不能为空' : 'This field is required') : '');
        if (error) {
            const errorEl = document.getElementById('knowledge-dialog-error');
            errorEl.textContent = error;
            errorEl.classList.remove('hidden');
            return;
        }
        submit.disabled = true;
        const ok = await options.onSubmit(value);
        submit.disabled = false;
        if (ok !== null) close();
    };
    submit.onclick = submitAction;
    cancel.onclick = close;
    overlay.onclick = event => { if (event.target === overlay) close(); };
    input.onkeydown = event => { if (event.key === 'Enter') submitAction(); };
    overlay.classList.remove('hidden');
    setTimeout(() => (options.type === 'select' ? select : (options.type === 'textarea' ? textarea : (options.type === 'document' ? documentFilename : input))).focus(), 0);
}

function closeKnowledgeNewMenu() {
    const list = document.getElementById('knowledge-new-menu-list');
    if (list) list.classList.add('hidden');
    document.removeEventListener('click', _knowledgeNewMenuOutside, true);
}

function _knowledgeNewMenuOutside(event) {
    const menu = document.getElementById('knowledge-new-menu');
    if (menu && !menu.contains(event.target)) closeKnowledgeNewMenu();
}

function toggleKnowledgeNewMenu(event) {
    if (event) event.stopPropagation();
    const list = document.getElementById('knowledge-new-menu-list');
    if (!list) return;
    const willOpen = list.classList.contains('hidden');
    list.classList.toggle('hidden');
    if (willOpen) {
        document.addEventListener('click', _knowledgeNewMenuOutside, true);
    } else {
        document.removeEventListener('click', _knowledgeNewMenuOutside, true);
    }
}

function createKnowledgeCategory() {
    openKnowledgeDialog({
        title: currentLang === 'zh' ? '新建分类' : 'New category',
        subtitle: currentLang === 'zh' ? '分类会创建为 knowledge/ 下的目录' : 'Creates a directory under knowledge/',
        label: currentLang === 'zh' ? '分类路径' : 'Category path',
        hint: currentLang === 'zh' ? '支持嵌套路径，例如 research/ai' : 'Nested paths are supported, e.g. research/ai',
        icon: 'fa-folder-plus',
        onSubmit: path => dispatchKnowledgeAction('create_category', {path}),
    });
}

function createKnowledgeDocument() {
    const categories = _knowledgeCategoryPaths(_knowledgeTreeData);
    if (!categories.length) {
        _setKnowledgeStatus(currentLang === 'zh' ? '请先创建分类' : 'Create a category first', true);
        return;
    }
    openKnowledgeDialog({
        title: currentLang === 'zh' ? '新建文档' : 'New document',
        subtitle: currentLang === 'zh' ? '先选择分类，然后输入文件名' : 'Choose a category, then enter a filename',
        label: currentLang === 'zh' ? '目标分类' : 'Destination category',
        type: 'select',
        choices: categories,
        icon: 'fa-file-circle-plus',
        onSubmit: category => {
            openKnowledgeDocumentEditor(category);
            return null;
        },
    });
}

function openKnowledgeDocumentEditor(category) {
    openKnowledgeDialog({
        title: currentLang === 'zh' ? '新建文档' : 'New document',
        subtitle: currentLang === 'zh' ? `保存到 ${category}` : `Save to ${category}`,
        label: '',
        hint: currentLang === 'zh' ? '文件名可省略 .md 后缀；保存后会自动同步索引。' : 'The .md suffix is optional. Index sync runs after saving.',
        type: 'document',
        category,
        filename: '',
        content: '',
        icon: 'fa-file-circle-plus',
        validate: value => {
            if (!value.filename) return currentLang === 'zh' ? '文件名不能为空' : 'Filename is required';
            if (/\.[^.]+$/i.test(value.filename) && !/\.md$/i.test(value.filename)) {
                return currentLang === 'zh' ? '新建文档仅支持 .md 文件名' : 'New documents must be .md files';
            }
            if (!value.content.trim()) return currentLang === 'zh' ? '内容不能为空' : 'Content is required';
            if (new Blob([value.content]).size > KNOWLEDGE_IMPORT_MAX_FILE_SIZE) {
                return currentLang === 'zh' ? '内容不能超过 10MB' : 'Content cannot exceed 10MB';
            }
            return '';
        },
        onSubmit: value => {
            const safeName = value.filename.endsWith('.md') ? value.filename : `${value.filename}.md`;
            return dispatchKnowledgeAction('create_document', {
                path: `${category}/${safeName}`,
                content: value.content,
                overwrite: false,
            }, payload => payload?.path || `${category}/${safeName}`);
        },
    });
}

function selectKnowledgeImportFiles() {
    const input = document.getElementById('knowledge-import-input');
    input.value = '';
    input.onchange = () => {
        if (input.files && input.files.length) openKnowledgeImportDialog(Array.from(input.files));
    };
    input.click();
}

function openKnowledgeImportDialog(files) {
    const validationError = validateKnowledgeImportFiles(files);
    if (validationError) {
        _setKnowledgeStatus(validationError, true);
        return;
    }
    const choices = _knowledgeCategoryPaths(_knowledgeTreeData);
    openKnowledgeDialog({
        title: currentLang === 'zh' ? '导入文档' : 'Import documents',
        subtitle: currentLang === 'zh' ? `已选择 ${files.length} 个文件` : `${files.length} file(s) selected`,
        label: currentLang === 'zh' ? '目标分类' : 'Destination category',
        hint: choices.length ? (currentLang === 'zh' ? '支持 Markdown 和 TXT，TXT 会转成 Markdown 文档' : 'Markdown and TXT are supported. TXT is converted to Markdown.') :
            (currentLang === 'zh' ? '请先创建一个分类' : 'Create a category first'),
        type: 'select',
        choices,
        icon: 'fa-file-arrow-up',
        onSubmit: target => importKnowledgeDocuments(files, target),
    });
}

async function importKnowledgeDocuments(files, targetCategory) {
    const validationError = validateKnowledgeImportFiles(files);
    if (validationError) {
        _setKnowledgeStatus(validationError, true);
        return null;
    }
    const supported = files.filter(file => /\.(md|txt)$/i.test(file.name || ''));
    if (!supported.length) {
        _setKnowledgeStatus(currentLang === 'zh' ? '请选择 .md 或 .txt 文件' : 'Choose .md or .txt files', true);
        return null;
    }
    const formData = new FormData();
    formData.append('target_category', targetCategory);
    formData.append('conflict_strategy', 'rename');
    supported.forEach(file => formData.append('files', file, file.name));
    _setKnowledgeStatus(currentLang === 'zh' ? '正在导入...' : 'Importing...', false, true);
    try {
        const response = await fetch(_kbUrl('/api/knowledge/import'), { method: 'POST', body: formData });
        const result = await response.json();
        if (result.status !== 'success') {
            _setKnowledgeStatus(result.message || (currentLang === 'zh' ? '导入失败' : 'Import failed'), true);
            loadKnowledgeView();
            return null;
        }
        _setKnowledgeStatus(_knowledgeResultMessage('import_documents', result.payload), false);
        // Auto-open the first successfully imported document.
        const firstImported = (result.payload?.results || []).find(item => item.status === 'imported');
        loadKnowledgeView(firstImported ? firstImported.path : undefined);
        return result.payload;
    } catch (error) {
        _setKnowledgeStatus(currentLang === 'zh' ? '导入请求失败' : 'Import request failed', true);
        return null;
    }
}

function validateKnowledgeImportFiles(files) {
    if (!files || !files.length) return currentLang === 'zh' ? '请选择文件' : 'Choose files';
    if (files.length > KNOWLEDGE_IMPORT_MAX_FILES) {
        return currentLang === 'zh' ? `一次最多导入 ${KNOWLEDGE_IMPORT_MAX_FILES} 个文件` : `Import at most ${KNOWLEDGE_IMPORT_MAX_FILES} files at a time`;
    }
    let total = 0;
    for (const file of files) {
        total += file.size || 0;
        if ((file.size || 0) > KNOWLEDGE_IMPORT_MAX_FILE_SIZE) {
            return currentLang === 'zh' ? `${file.name} 超过 10MB` : `${file.name} exceeds 10MB`;
        }
    }
    if (total > KNOWLEDGE_IMPORT_MAX_TOTAL_SIZE) {
        return currentLang === 'zh' ? '单次导入总大小不能超过 200MB' : 'Total import size cannot exceed 200MB';
    }
    return '';
}

let _knowledgeImportDropReady = false;
function initKnowledgeImportDropZone() {
    if (_knowledgeImportDropReady) return;
    const panel = document.getElementById('knowledge-panel-docs');
    if (!panel) return;
    _knowledgeImportDropReady = true;
    ['dragenter', 'dragover'].forEach(name => {
        panel.addEventListener(name, event => {
            if (!event.dataTransfer || !event.dataTransfer.types.includes('Files')) return;
            event.preventDefault();
            panel.classList.add('knowledge-import-drag-over');
        });
    });
    ['dragleave', 'drop'].forEach(name => {
        panel.addEventListener(name, event => {
            if (event.type === 'drop') {
                event.preventDefault();
                const files = Array.from(event.dataTransfer?.files || []);
                if (files.length) openKnowledgeImportDialog(files);
            }
            panel.classList.remove('knowledge-import-drag-over');
        });
    });
}

function renameKnowledgeCategory(path) {
    openKnowledgeDialog({
        title: currentLang === 'zh' ? '重命名分类' : 'Rename category',
        subtitle: path,
        label: currentLang === 'zh' ? '新的分类路径' : 'New category path',
        value: path,
        icon: 'fa-pen',
        validate: value => value === path ? (currentLang === 'zh' ? '请输入不同的分类路径' : 'Enter a different category path') : '',
        onSubmit: newPath => dispatchKnowledgeAction('rename_category', {path, new_path: newPath}),
    });
}

function deleteKnowledgeCategory(path) {
    showConfirmDialog({
        title: '删除分类',
        message: `确认删除“${path}”及其中全部文档？`,
        okText: t('confirm_yes'),
        cancelText: t('confirm_cancel'),
        onConfirm: () => dispatchKnowledgeAction('delete_category', {path, confirm: true}),
    });
}

function deleteKnowledgeDocument(path) {
    showConfirmDialog({
        title: '删除文档',
        message: `确认删除“${path}”？`,
        okText: t('confirm_yes'),
        cancelText: t('confirm_cancel'),
        onConfirm: () => dispatchKnowledgeAction('delete_documents', {paths: [path]}),
    });
}

function moveKnowledgeDocument(path) {
    const currentCategory = path.includes('/') ? path.split('/').slice(0, -1).join('/') : '';
    const choices = _knowledgeCategoryPaths(_knowledgeTreeData).filter(value => value !== currentCategory);
    openKnowledgeDialog({
        title: currentLang === 'zh' ? '移动文档' : 'Move document',
        subtitle: path,
        label: currentLang === 'zh' ? '目标分类' : 'Destination category',
        hint: choices.length ? '' : (currentLang === 'zh' ? '请先创建其他分类' : 'Create another category first'),
        type: 'select',
        choices,
        icon: 'fa-arrow-right-arrow-left',
        onSubmit: target => dispatchKnowledgeAction('move_documents', {paths: [path], target_category: target}),
    });
}

function _hasFilterMatch(groups, lowerFilter) {
    for (const g of groups) {
        for (const f of (g.files || [])) {
            if (f.title.toLowerCase().includes(lowerFilter) || f.name.toLowerCase().includes(lowerFilter)) return true;
        }
        if (_hasFilterMatch(g.children || [], lowerFilter)) return true;
    }
    return false;
}

function _countFiles(group) {
    let count = (group.files || []).length;
    for (const child of (group.children || [])) {
        count += _countFiles(child);
    }
    return count;
}

function filterKnowledgeTree(query) {
    renderKnowledgeTree(_knowledgeTreeData, _knowledgeRootFiles, query);
}

function resolveKnowledgePath(currentFilePath, relativeHref) {
    // currentFilePath: e.g. "concepts/mcp-protocol.md"
    // relativeHref: e.g. "../entities/openai.md"
    const parts = currentFilePath.split('/');
    parts.pop(); // remove filename, keep directory
    const segments = [...parts, ...relativeHref.split('/')];
    const resolved = [];
    for (const seg of segments) {
        if (seg === '..') resolved.pop();
        else if (seg !== '.' && seg !== '') resolved.push(seg);
    }
    return resolved.join('/');
}

function bindKnowledgeLinks(container, currentFilePath) {
    container.querySelectorAll('a').forEach(a => {
        const href = a.getAttribute('href');
        if (!href || !href.endsWith('.md')) return;
        // Skip absolute URLs
        if (/^https?:\/\//.test(href)) return;

        a.addEventListener('click', (e) => {
            e.preventDefault();
            const resolved = resolveKnowledgePath(currentFilePath, href);
            const linkTitle = a.textContent.trim() || resolved.replace(/\.md$/, '').split('/').pop();
            openKnowledgeFile(resolved, linkTitle);
        });
        a.style.cursor = 'pointer';
        a.classList.add('text-primary-500', 'hover:underline');
    });
}

// Rewrite <img> srcs that are relative to the knowledge doc's directory into
// /api/file URLs, mirroring bindKnowledgeLinks for links. Runs on rendered
// DOM, so markdown syntax quoted inside code blocks is never touched. The
// lightbox onclick that renderMarkdown attached reads this.src at click time,
// so rewriting src alone keeps zoom working.
function bindKnowledgeImages(container, baseDir) {
    if (!baseDir) return;
    container.querySelectorAll('img').forEach(img => {
        const src = img.getAttribute('src');
        // Remote / data / site-absolute srcs resolve on their own.
        if (!src || /^(?:[a-z][\w+.-]*:|\/)/i.test(src)) return;
        const combined = `${baseDir}/${src.split('?')[0]}`;
        const segments = [];
        for (const seg of combined.split('/')) {
            if (seg === '..') segments.pop();
            else if (seg !== '.' && seg !== '') segments.push(seg);
        }
        // baseDir is an absolute posix path, so restore the leading slash the
        // split() dropped — /api/file rejects non-absolute paths.
        const resolved = (combined.startsWith('/') ? '/' : '') + segments.join('/');
        img.src = '/api/file?path=' + encodeURIComponent(resolved);
    });
}

function openKnowledgeFile(path, title) {
    _knowledgeCurrentFile = path;
    // Update active state in tree via data-path
    document.querySelectorAll('.knowledge-tree-file').forEach(el => {
        el.classList.toggle('active', el.dataset.path === path);
    });

    // Immediately hide placeholder
    document.getElementById('knowledge-content-placeholder').classList.add('hidden');

    fetch(_kbUrl(`/api/knowledge/read?path=${encodeURIComponent(path)}`)).then(r => r.json()).then(data => {
        if (data.status !== 'success') return;
        const viewer = document.getElementById('knowledge-content-viewer');
        document.getElementById('knowledge-viewer-title').textContent = title;
        document.getElementById('knowledge-viewer-path').textContent = path;
        const bodyEl = document.getElementById('knowledge-viewer-body');
        bodyEl.innerHTML = renderMarkdown(data.content || '');
        viewer.classList.remove('hidden');
        applyHighlighting(viewer);
        bindKnowledgeLinks(bodyEl, path);
        bindKnowledgeImages(bodyEl, data.dir);

        // Mobile: hide sidebar, show content
        if (window.innerWidth < 768) {
            document.getElementById('knowledge-sidebar').classList.add('hidden');
        }
    }).catch(() => {});
}

function knowledgeMobileBack() {
    document.getElementById('knowledge-sidebar').classList.remove('hidden');
    document.getElementById('knowledge-content-viewer').classList.add('hidden');
}

function switchKnowledgeTab(tab) {
    document.querySelectorAll('.knowledge-tab').forEach(el => el.classList.remove('active'));
    document.getElementById('knowledge-tab-' + tab).classList.add('active');

    const docsPanel = document.getElementById('knowledge-panel-docs');
    const graphPanel = document.getElementById('knowledge-panel-graph');

    if (tab === 'docs') {
        docsPanel.classList.remove('hidden');
        graphPanel.classList.add('hidden');
    } else {
        docsPanel.classList.add('hidden');
        graphPanel.classList.remove('hidden');
        if (!_knowledgeGraphLoaded) {
            loadKnowledgeGraph();
        }
    }
}

let _d3LoadPromise = null;

function ensureD3Loaded() {
    if (window.d3) return Promise.resolve(window.d3);
    if (_d3LoadPromise) return _d3LoadPromise;
    _d3LoadPromise = new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = 'assets/vendor/d3/d3.min.js';
        script.async = true;
        script.onload = () => resolve(window.d3);
        script.onerror = () => reject(new Error('Failed to load d3'));
        document.head.appendChild(script);
    });
    return _d3LoadPromise;
}

function loadKnowledgeGraph() {
    _knowledgeGraphLoaded = true;
    const container = document.getElementById('knowledge-graph-container');
    container.innerHTML = '<div class="flex items-center justify-center h-full text-slate-400 text-sm"><i class="fas fa-spinner fa-spin mr-2"></i>Loading graph...</div>';

    Promise.all([
        ensureD3Loaded(),
        fetch(_kbUrl('/api/knowledge/graph')).then(r => r.json()),
    ]).then(([, data]) => {
        const nodes = data.nodes || [];
        const links = data.links || [];
        if (nodes.length === 0) {
            container.innerHTML = `<div class="flex flex-col items-center justify-center h-full text-slate-400"><i class="fas fa-diagram-project text-3xl mb-3 opacity-40"></i><p class="text-sm">${t('knowledge_empty_hint')}</p></div>`;
            return;
        }
        container.innerHTML = '';
        renderKnowledgeGraph(container, nodes, links);
    }).catch(() => {
        container.innerHTML = '<div class="flex items-center justify-center h-full text-slate-400 text-sm">Failed to load graph</div>';
    });
}

function renderKnowledgeGraph(container, nodes, links) {
    const width = container.clientWidth;
    const height = container.clientHeight || 600;

    // Order categories by node count so the dominant cluster gets the most
    // salient palette entry. Ties break by name to keep colors stable.
    const catCount = {};
    nodes.forEach(n => { catCount[n.category] = (catCount[n.category] || 0) + 1; });
    const categories = Object.keys(catCount).sort(
        (a, b) => catCount[b] - catCount[a] || a.localeCompare(b)
    );
    const colorScale = d3.scaleOrdinal(d3.schemeTableau10).domain(categories);

    // Connection count for sizing
    const connCount = {};
    nodes.forEach(n => connCount[n.id] = 0);
    links.forEach(l => {
        connCount[l.source] = (connCount[l.source] || 0) + 1;
        connCount[l.target] = (connCount[l.target] || 0) + 1;
    });

    const svg = d3.select(container)
        .append('svg')
        .attr('width', width)
        .attr('height', height);

    const g = svg.append('g');

    // Zoom with adaptive label visibility
    let currentZoomScale = 1;
    // Set once the graph is fitted to the viewport. Labels hide below it, so
    // zooming out past the default view still declutters.
    let fittedScale = 1;
    const zoom = d3.zoom()
        .scaleExtent([0.2, 5])
        .on('zoom', (event) => {
            g.attr('transform', event.transform);
            currentZoomScale = event.transform.k;
            updateLabelVisibility();
        });
    svg.call(zoom);

    function updateLabelVisibility() {
        if (!label) return;
        // Fitting a graph of any size into the panel lands well below scale 1,
        // so a fixed threshold would hide every label in the default view.
        // Compare against the fitted scale instead, and keep the text a
        // constant size on screen — inside the zoomed <g>, that means dividing
        // by the scale.
        if (currentZoomScale < fittedScale * 0.9) {
            label.attr('opacity', 0);
            return;
        }
        label.attr('opacity', 1)
            .attr('font-size', 10 / currentZoomScale)
            .attr('dx', d => getNodeRadius(d) + 4 / currentZoomScale)
            .attr('dy', 3 / currentZoomScale);
    }

    const simulation = d3.forceSimulation(nodes)
        .force('link', d3.forceLink(links).id(d => d.id).distance(90))
        .force('charge', d3.forceManyBody().strength(-180))
        .force('center', d3.forceCenter(width / 2, height / 2))
        .force('x', d3.forceX(width / 2).strength(0.06))
        .force('y', d3.forceY(height / 2).strength(0.06))
        .force('collision', d3.forceCollide().radius(d => getNodeRadius(d) + 30));

    function getNodeRadius(d) {
        return Math.max(5, Math.min(16, 5 + (connCount[d.id] || 0) * 2));
    }

    const link = g.append('g')
        .selectAll('line')
        .data(links)
        .join('line')
        .attr('stroke', '#94a3b8')
        .attr('stroke-opacity', 0.3)
        .attr('stroke-width', 1);

    const node = g.append('g')
        .selectAll('circle')
        .data(nodes)
        .join('circle')
        .attr('r', d => getNodeRadius(d))
        .attr('fill', d => colorScale(d.category))
        .attr('stroke', '#fff')
        .attr('stroke-width', 1.5)
        .style('cursor', 'pointer')
        .call(d3.drag()
            .on('start', (event, d) => { if (!event.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
            .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y; })
            .on('end', (event, d) => { if (!event.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; })
        );

    const label = g.append('g')
        .selectAll('text')
        .data(nodes)
        .join('text')
        .text(d => d.label.length > 15 ? d.label.slice(0, 14) + '…' : d.label)
        .attr('font-size', 9)
        .attr('dx', d => getNodeRadius(d) + 4)
        .attr('dy', 3)
        .attr('fill', '#64748b')
        .style('pointer-events', 'none');

    // Tooltip
    const tooltip = document.createElement('div');
    tooltip.className = 'knowledge-graph-tooltip';
    container.style.position = 'relative';
    container.appendChild(tooltip);

    node.on('mouseover', (event, d) => {
        tooltip.textContent = d.label + ' (' + d.category + ')';
        tooltip.style.opacity = '1';
        tooltip.style.left = (event.offsetX + 12) + 'px';
        tooltip.style.top = (event.offsetY - 8) + 'px';
        // Highlight connections
        link.attr('stroke-opacity', l => (l.source.id === d.id || l.target.id === d.id) ? 0.8 : 0.1);
        node.attr('opacity', n => n.id === d.id || links.some(l => (l.source.id === d.id && l.target.id === n.id) || (l.target.id === d.id && l.source.id === n.id)) ? 1 : 0.2);
        label.attr('opacity', n => n.id === d.id || links.some(l => (l.source.id === d.id && l.target.id === n.id) || (l.target.id === d.id && l.source.id === n.id)) ? 1 : 0.1);
    }).on('mousemove', (event) => {
        tooltip.style.left = (event.offsetX + 12) + 'px';
        tooltip.style.top = (event.offsetY - 8) + 'px';
    }).on('mouseout', () => {
        tooltip.style.opacity = '0';
        link.attr('stroke-opacity', 0.3);
        node.attr('opacity', 1);
        label.attr('opacity', 1);
    }).on('click', (event, d) => {
        // Switch to docs tab and open the file
        switchKnowledgeTab('docs');
        openKnowledgeFile(d.id, d.label);
    });

    simulation.on('tick', () => {
        link.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
            .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
        node.attr('cx', d => d.x).attr('cy', d => d.y);
        label.attr('x', d => d.x).attr('y', d => d.y);
    });

    // Auto fit-to-view when simulation settles
    simulation.on('end', () => {
        const pad = 16;
        let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
        nodes.forEach(n => {
            if (n.x < x0) x0 = n.x;
            if (n.y < y0) y0 = n.y;
            if (n.x > x1) x1 = n.x;
            if (n.y > y1) y1 = n.y;
        });
        const bw = x1 - x0 + pad * 2;
        const bh = y1 - y0 + pad * 2;
        if (bw > 0 && bh > 0) {
            const scale = Math.min(width / bw, height / bh, 4);
            fittedScale = scale;
            const tx = width / 2 - (x0 + x1) / 2 * scale;
            const ty = height / 2 - (y0 + y1) / 2 * scale;
            svg.transition().duration(500).call(
                zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale)
            );
        }
    });

    // Legend
    const legendDiv = document.createElement('div');
    legendDiv.className = 'knowledge-graph-legend';
    categories.forEach(cat => {
        const item = document.createElement('span');
        item.className = 'knowledge-graph-legend-item';
        item.innerHTML = `<span class="knowledge-graph-legend-dot" style="background:${colorScale(cat)}"></span>${escapeHtml(cat)}`;
        legendDiv.appendChild(item);
    });
    container.appendChild(legendDiv);
}

// =====================================================================
// Authentication
// =====================================================================
function toggleLoginPassword() {
    const input = document.getElementById('login-password');
    const icon = document.querySelector('#login-toggle-pwd i');
    if (input.type === 'password') {
        input.type = 'text';
        icon.classList.replace('fa-eye', 'fa-eye-slash');
    } else {
        input.type = 'password';
        icon.classList.replace('fa-eye-slash', 'fa-eye');
    }
}
window.toggleLoginPassword = toggleLoginPassword;

function showLoginScreen() {
    const overlay = document.getElementById('login-overlay');
    if (!overlay) return;
    overlay.classList.remove('hidden');
    document.getElementById('app').classList.add('hidden');

    const subtitle = document.getElementById('login-subtitle');
    const loginBtn = document.getElementById('login-btn');
    if (currentLang === 'en') {
        subtitle.textContent = 'Enter password to access the console';
        loginBtn.textContent = 'Login';
    } else if (currentLang === 'zh-Hant') {
        subtitle.textContent = '請輸入密碼以存取控制台';
        loginBtn.textContent = '登入';
    } else {
        subtitle.textContent = '请输入密码以访问控制台';
        loginBtn.textContent = '登录';
    }

    const form = document.getElementById('login-form');
    const pwdInput = document.getElementById('login-password');
    pwdInput.focus();

    form.onsubmit = function(e) {
        e.preventDefault();
        const pwd = pwdInput.value;
        if (!pwd) return;
        const btn = document.getElementById('login-btn');
        const errEl = document.getElementById('login-error');
        btn.disabled = true;
        errEl.classList.add('hidden');

        fetch('/auth/login', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({password: pwd})
        }).then(r => r.json()).then(data => {
            if (data.status === 'success') {
                overlay.classList.add('hidden');
                document.getElementById('app').classList.remove('hidden');
                const logoutBtn = document.getElementById('logout-btn-header');
                if (logoutBtn) logoutBtn.classList.remove('hidden');
                // Now that the auth cookie is set, release the parked pollers.
                openAuthGate();
                initApp();
            } else {
                if (currentLang === 'zh-Hant') {
                    errEl.textContent = '密碼錯誤';
                } else if (currentLang === 'zh') {
                    errEl.textContent = '密码错误';
                } else {
                    errEl.textContent = 'Wrong password';
                }
                errEl.classList.remove('hidden');
                pwdInput.value = '';
                pwdInput.focus();
            }
            btn.disabled = false;
        }).catch(() => {
            if (currentLang === 'zh-Hant') {
                errEl.textContent = '網路錯誤，請重試';
            } else if (currentLang === 'zh') {
                errEl.textContent = '网络错误，请重试';
            } else {
                errEl.textContent = 'Network error, please retry';
            }
            errEl.classList.remove('hidden');
            btn.disabled = false;
        });
        return false;
    };
}

function handleLogout() {
    fetch('/auth/logout', {
        method: 'POST'
    }).then(r => r.json()).then(data => {
        if (data.status === 'success') {
            window.location.reload();
        }
    }).catch(() => {
        window.location.reload();
    });
}
window.handleLogout = handleLogout;

// Intercept 401 responses globally to show login screen on session expiry
const _originalFetch = window.fetch;
window.fetch = function(...args) {
    return _originalFetch.apply(this, args).then(response => {
        if (response.status === 401) {
            const url = typeof args[0] === 'string' ? args[0] : (args[0]?.url || '');
            if (!url.startsWith('/auth/')) {
                showLoginScreen();
            }
        }
        return response;
    });
};


const GITHUB_RELEASES_URL = 'https://github.com/zhayujie/CowAgent/releases';
let UPDATE_META = { version: '', install_kind: 'unknown', update_supported: false, unsupported_reason: '' };
let UPDATE_CHECK = null;
let _updateChecking = false;
let _updateRunning = false;
let _updatePollTimer = null;
let _updateReconnectTimer = null;

function toggleUpdateMenu(event) {
    if (event) event.stopPropagation();
    const menu = document.getElementById('update-menu');
    const btn = document.getElementById('sidebar-version');
    if (!menu) return;
    const willOpen = menu.classList.contains('hidden');
    if (willOpen) {
        menu.classList.remove('hidden');
        if (btn) btn.setAttribute('aria-expanded', 'true');
        setTimeout(() => document.addEventListener('click', _closeUpdateMenuOnOutside), 0);
    } else {
        closeUpdateMenu();
    }
}

function closeUpdateMenu() {
    const menu = document.getElementById('update-menu');
    const btn = document.getElementById('sidebar-version');
    if (menu) menu.classList.add('hidden');
    if (btn) btn.setAttribute('aria-expanded', 'false');
    document.removeEventListener('click', _closeUpdateMenuOnOutside);
}

function _closeUpdateMenuOnOutside(event) {
    const menu = document.getElementById('update-menu');
    const btn = document.getElementById('sidebar-version');
    if (!menu) return;
    if (menu.contains(event.target) || (btn && btn.contains(event.target))) return;
    closeUpdateMenu();
}

// Set the sidebar version text. The red dot lives outside this button (as a
// footer child), so plain textContent is safe.
function _setSidebarVersionLabel(text) {
    const btn = document.getElementById('sidebar-version');
    if (btn) btn.textContent = text || '';
}

// "版本说明": open the GitHub releases page (keeps the old click-through behaviour).
function openReleaseNotes() {
    window.open(GITHUB_RELEASES_URL, '_blank', 'noopener,noreferrer');
    closeUpdateMenu();
}

// Single update entry, mirroring the desktop NavRail: one row whose icon +
// label + red dot are driven by the current update state. Keeping it a single
// fixed-height line means the icon and label never fall out of alignment.
//   idle        -> "检查更新"           (click = check)
//   checking    -> "正在检查…" (spinner)
//   up_to_date  -> "已是最新版本"
//   available   -> "立即更新" + red dot (click = update)
//   updating    -> current step label   (spinner, not clickable)
//   failed      -> "更新失败" + retry
let _updateUiState = 'idle';

function _renderUpdateAction(state, label, opts) {
    opts = opts || {};
    _updateUiState = state;
    const item = document.getElementById('update-action-item');
    const icon = document.getElementById('update-action-icon');
    const text = document.getElementById('update-action-label');
    const dot = document.getElementById('update-dot');
    if (!item || !icon || !text) return;

    text.textContent = label;
    item.classList.toggle('is-new', state === 'available');
    item.classList.toggle('is-ok', state === 'up_to_date');
    item.classList.toggle('is-disabled', !!opts.disabled);
    item.disabled = !!opts.disabled;
    if (dot) dot.classList.toggle('hidden', state !== 'available');

    // Swap the leading icon per state.
    const iconClass = {
        idle: 'fas fa-arrows-rotate',
        checking: 'fas fa-arrows-rotate fa-spin-update',
        up_to_date: 'fas fa-circle-check',
        available: 'fas fa-download',
        updating: 'fas fa-arrows-rotate fa-spin-update',
        failed: 'fas fa-triangle-exclamation'
    }[state] || 'fas fa-arrows-rotate';
    icon.className = iconClass;
}

// The single row's click behaviour depends on the current state.
function onUpdateActionClick() {
    if (_updateChecking || _updateRunning) return;
    if (_updateUiState === 'available') {
        startConsoleUpdate();
    } else {
        checkForConsoleUpdate();
    }
}

// "检查更新": the only action that contacts GitHub. Turns the row into
// "立即更新" (+ red dot) when a newer version exists.
function checkForConsoleUpdate() {
    if (_updateChecking || _updateRunning) return;
    _updateChecking = true;
    _renderUpdateAction('checking', t('update_checking'), { disabled: true });
    fetch('/api/update/check', { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'error') {
                _renderUpdateAction('failed', data.message || t('update_error'));
                return;
            }
            UPDATE_CHECK = data;
            if (typeof data.update_supported === 'boolean') UPDATE_META.update_supported = data.update_supported;
            if (data.install_kind) UPDATE_META.install_kind = data.install_kind;
            if (data.up_to_date) {
                _renderUpdateAction('up_to_date', t('update_up_to_date'));
            } else if (UPDATE_META.update_supported) {
                _renderUpdateAction('available', t('update_now'));
            } else {
                // Docker / packaged / Windows: a newer version exists but this
                // install can't self-update, so keep the dot but disable the row.
                const reason = UPDATE_META.unsupported_reason || t('update_unsupported');
                _renderUpdateAction('available', reason, { disabled: true });
            }
        })
        .catch(() => _renderUpdateAction('failed', t('update_error')))
        .finally(() => { _updateChecking = false; });
}

// "立即更新": reuse the cow-update path (git pull + pip + restart) via the
// detached worker, then poll progress and auto-reconnect when it comes back.
function startConsoleUpdate() {
    if (_updateRunning) return;
    if (!UPDATE_META.update_supported || !(UPDATE_CHECK && UPDATE_CHECK.up_to_date === false)) return;
    showConfirmModal(t('update_now'), t('update_confirm'), () => {
        _updateRunning = true;
        _renderUpdateAction('updating', t('update_starting'), { disabled: true });
        fetch('/api/update/start', { method: 'POST' })
            .then(r => r.json())
            .then(data => {
                if (data.status === 'error') {
                    _renderUpdateAction('failed', `${t('update_failed')}: ${data.message || ''}`);
                    _updateRunning = false;
                    return;
                }
                _pollUpdateStatus();
            })
            .catch(() => {
                _renderUpdateAction('failed', t('update_failed'));
                _updateRunning = false;
            });
    });
}

function _pollUpdateStatus() {
    if (_updatePollTimer) clearInterval(_updatePollTimer);
    _updatePollTimer = setInterval(() => {
        fetch('/api/update/status')
            .then(r => {
                if (!r.ok) throw new Error('offline');
                return r.json();
            })
            .then(data => {
                const stepKey = data.step ? `update_step_${data.step}` : '';
                const stepLabel = (stepKey && I18N[currentLang] && I18N[currentLang][stepKey])
                    ? t(stepKey)
                    : (data.message || t('update_in_progress'));
                if (data.state === 'failed') {
                    clearInterval(_updatePollTimer);
                    _updatePollTimer = null;
                    _renderUpdateAction('failed', `${t('update_failed')}: ${data.error || data.message || ''}`);
                    _updateRunning = false;
                    return;
                }
                if (data.state === 'success') {
                    clearInterval(_updatePollTimer);
                    _updatePollTimer = null;
                    _renderUpdateAction('updating', t('update_reconnect'), { disabled: true });
                    _waitForBackend();
                    return;
                }
                if (data.state === 'restarting') {
                    _renderUpdateAction('updating', t('update_reconnect'), { disabled: true });
                    return;
                }
                _renderUpdateAction('updating', stepLabel, { disabled: true });
            })
            .catch(() => {
                // The old process was replaced mid-poll; switch to reconnecting.
                _renderUpdateAction('updating', t('update_reconnect'), { disabled: true });
                _waitForBackend();
            });
    }, 1500);
}

function _waitForBackend() {
    if (_updateReconnectTimer) return;
    _updateReconnectTimer = setInterval(() => {
        fetch('/api/version')
            .then(r => r.json())
            .then(data => {
                if (!data || !data.version) return;
                clearInterval(_updateReconnectTimer);
                _updateReconnectTimer = null;
                if (_updatePollTimer) {
                    clearInterval(_updatePollTimer);
                    _updatePollTimer = null;
                }
                UPDATE_META = {
                    version: data.version,
                    install_kind: data.install_kind || UPDATE_META.install_kind,
                    update_supported: !!data.update_supported,
                    unsupported_reason: data.unsupported_reason || ''
                };
                APP_VERSION = `v${data.version}`;
                _setSidebarVersionLabel(`CowAgent ${APP_VERSION}`);
                UPDATE_CHECK = { up_to_date: true, newer_releases: [], latest: null, current_release: null };
                _updateRunning = false;
                _renderUpdateAction('up_to_date', t('update_done'));
            })
            .catch(() => {});
    }, 1500);
}


function initApp() {
    applyI18n();
    _applyInputTooltips();
    _restoreSessionPanel();
    refreshWorkspaceSelector();
    refreshSessionSettings();

    fetch('/api/knowledge/list').then(r => r.json()).then(data => {
        if (data.status === 'success') {
            _knowledgeTreeData = data.tree || [];
            _knowledgeRootFiles = data.root_files || [];
        }
    }).catch(() => {});

    fetch('/api/version').then(r => r.json()).then(data => {
        APP_VERSION = `v${data.version}`;
        UPDATE_META = {
            version: data.version || '',
            install_kind: data.install_kind || 'unknown',
            update_supported: !!data.update_supported,
            unsupported_reason: data.unsupported_reason || ''
        };
        _setSidebarVersionLabel(`CowAgent ${APP_VERSION}`);
    }).catch(() => {
        _setSidebarVersionLabel('CowAgent');
    });
    chatInput.focus();
}

// =====================================================================
// Initialization
// =====================================================================
applyTheme();
applyI18n();

fetch('/auth/check').then(r => r.json()).then(data => {
    if (data.auth_required && !data.authenticated) {
        // Keep background pollers parked until login succeeds (openAuthGate is
        // called from the login handler), so they don't spam 401s meanwhile.
        showLoginScreen();
    } else {
        if (data.auth_required) {
            const logoutBtn = document.getElementById('logout-btn-header');
            if (logoutBtn) logoutBtn.classList.remove('hidden');
        }
        openAuthGate();
        initApp();
    }
}).catch(() => {
    // No auth info available (e.g. request failed): fall back to running so a
    // password-less deployment still works.
    openAuthGate();
    initApp();
});

requestAnimationFrame(() => {
    document.body.classList.add('transition-colors', 'duration-200');
});

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
            // Manually parse ISO time string to avoid cross-browser timezone issues with new Date()
            // run_at format: "YYYY-MM-DDTHH:mm:ss" or "YYYY-MM-DDTHH:mm:ss.ffffff"
            const parts = schedule.run_at.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/);
            if (parts) {
                const timeInput = document.getElementById('task-edit-once-time');
                timeInput.value = `${parts[1]}-${parts[2]}-${parts[3]}T${parts[4]}:${parts[5]}:${parts[6]}`;
            }
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
        statusEl.textContent = currentLang === 'zh' ? '请输入任务名称' : 'Please enter task name';
        statusEl.style.opacity = '1';
        setTimeout(() => { statusEl.style.opacity = '0'; }, 3000);
        return;
    }
    
    const scheduleType = getDropdownValue(scheduleTypeSelect) || 'cron';
    const schedule = { type: scheduleType };
    
    if (scheduleType === 'cron') {
        const expr = cronInput.value.trim();
        if (!expr) {
            statusEl.textContent = currentLang === 'zh' ? '请输入 Cron 表达式' : 'Please enter cron expression';
            statusEl.style.opacity = '1';
            setTimeout(() => { statusEl.style.opacity = '0'; }, 3000);
            return;
        }
        // Basic cron expression format validation: 5 or 6 fields
        const fields = expr.split(/\s+/);
        if (fields.length < 5 || fields.length > 6) {
            statusEl.textContent = currentLang === 'zh' ? 'Cron 表达式格式错误，应为 5 或 6 个字段（分 时 日 月 周）' : 'Invalid cron expression, expected 5 or 6 fields (min hour day month weekday)';
            statusEl.style.opacity = '1';
            setTimeout(() => { statusEl.style.opacity = '0'; }, 3000);
            return;
        }
        schedule.expression = expr;
        // Note: detailed cron expression validity is verified by the backend croniter library; frontend only does basic format validation
    } else if (scheduleType === 'interval') {
        const seconds = parseInt(intervalInput.value);
        if (!seconds || seconds < 60) {
            statusEl.textContent = currentLang === 'zh' ? '间隔秒数最小为 60 秒' : 'Interval must be at least 60 seconds';
            statusEl.style.opacity = '1';
            setTimeout(() => { statusEl.style.opacity = '0'; }, 3000);
            return;
        }
        schedule.seconds = seconds;
    } else if (scheduleType === 'once') {
        const time = onceInput.value;
        if (!time) {
            statusEl.textContent = currentLang === 'zh' ? '请选择执行时间' : 'Please select execution time';
            statusEl.style.opacity = '1';
            setTimeout(() => { statusEl.style.opacity = '0'; }, 3000);
            return;
        }
        // Validate execution time format
        const selectedTime = new Date(time);
        if (isNaN(selectedTime.getTime())) {
            statusEl.textContent = currentLang === 'zh' ? '执行时间格式错误' : 'Invalid execution time format';
            statusEl.style.opacity = '1';
            setTimeout(() => { statusEl.style.opacity = '0'; }, 3000);
            return;
        }
        // Validate that time is in the future for one-time tasks
        if (selectedTime <= new Date()) {
            statusEl.textContent = currentLang === 'zh' ? '执行时间必须在当前时间之后' : 'Execution time must be in the future';
            statusEl.style.opacity = '1';
            setTimeout(() => { statusEl.style.opacity = '0'; }, 3000);
            return;
        }
        // datetime-local value with step="1" is already in YYYY-MM-DDTHH:mm:ss format
        // Backend _parse_naive_local treats strings without timezone suffix as local time
        schedule.run_at = time;
    }
    
    const actionType = getDropdownValue(actionTypeSelect) || 'send_message';
    const channelType = getDropdownValue(channelTypeSelect) || 'web';
    const content = contentInput.value.trim();

    if (!content) {
        statusEl.textContent = currentLang === 'zh' ? '请输入内容' : 'Please enter content';
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
                showError(res.message || (currentLang === 'zh' ? '创建失败' : 'Create failed'));
            }
        }).catch(() => {
            saveBtn.disabled = false;
            showError(currentLang === 'zh' ? '网络错误' : 'Network error');
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
            showError(res.message || (currentLang === 'zh' ? '保存失败' : 'Save failed'));
        }
    }).catch(() => {
        saveBtn.disabled = false;
        showError(currentLang === 'zh' ? '网络错误' : 'Network error');
    });
}

function deleteTask() {
    if (!currentEditingTask) return;
    
    const taskName = currentEditingTask.name || currentEditingTask.id || '未知任务';
    const taskId = currentEditingTask.id;  // Capture early to avoid closure race condition
    const taskAgentId = currentEditingTask.agent_id || '';  // route delete to the owner's store
    showConfirmDialog({
        title: t('task_delete_confirm_title'),
        message: (currentLang === 'zh' ? `确定要删除任务「${taskName}」吗？` : `Are you sure to delete task "${taskName}"?`),
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
