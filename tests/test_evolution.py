"""Self-evolution test harness.

Simulates multiple realistic conversations and checks the evolution pass behaves
correctly: stays silent when it should, evolves (memory/skill) when it should,
backs up before editing, notifies the user, and supports undo.

Two modes:
  - stub  (default): the review agent's reasoning is replaced by a scripted
    output per scenario. Fast, deterministic, validates the WIRING (backup,
    record, inject, notify, undo, protection). No model calls.
  - real:  the review agent runs the configured model for real. Validates the
    QUALITY of the judgement (does it correctly decide to act / stay silent).

Run:
    python tests/test_evolution.py            # stub mode
    python tests/test_evolution.py --real      # real model mode
"""

import os
import sys
import shutil
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class FakeChannel:
    """Captures channel.send calls instead of sending."""

    def __init__(self):
        self.sent = []

    def send(self, reply, context):
        self.sent.append({"content": getattr(reply, "content", str(reply)), "receiver": context.get("receiver")})


class FakeModel:
    pass


class FakeAgent:
    """Minimal stand-in for a chat Agent."""

    def __init__(self, messages, tools=None):
        import threading
        self.messages = messages
        self.messages_lock = threading.Lock()
        self.tools = tools or []
        self.model = FakeModel()
        self.skill_manager = None
        self.memory_manager = None


class FakeReviewAgent:
    """Review agent whose run_stream returns a scripted result (stub mode)."""

    def __init__(self, scripted_output, workspace, on_edit=None):
        self._out = scripted_output
        self._workspace = workspace
        self._on_edit = on_edit
        self.model = None

    def run_stream(self, user_message, clear_history=False, **kwargs):
        # Simulate the side effects a real review agent would perform.
        if self._on_edit:
            self._on_edit(self._workspace)
        return self._out


class FakeAgentBridge:
    """Stand-in for AgentBridge wiring used by the executor."""

    def __init__(self, agent, scripted_output, on_edit=None):
        self.agents = {"session_test": agent}
        self.default_agent = agent
        self._scripted = scripted_output
        self._on_edit = on_edit
        self.injected = []

    def create_agent(self, **kwargs):
        from agent.memory.config import get_default_memory_config
        ws = get_default_memory_config().get_workspace()
        return FakeReviewAgent(self._scripted, ws, on_edit=self._on_edit)

    def remember_scheduled_output(self, session_id, content, channel_type="", task_description=""):
        self.injected.append(content)


# ---------------------------------------------------------------------------
# Test scaffolding
# ---------------------------------------------------------------------------
def _setup_workspace():
    """Create a realistic temp workspace: seeded memory + real editable skills.

    Mirrors a real CowAgent workspace closely enough that the model has genuine
    content to read, reason about, and edit during a real evolution pass.
    """
    ws = Path(tempfile.mkdtemp(prefix="evo_test_"))
    (ws / "MEMORY.md").write_text(
        "# Long-term Memory\n\n"
        "## User\n"
        "- Name: 大锤 (David)\n"
        "- Lives in Shenzhen, works as a backend engineer\n"
        "- Company: a fintech startup, team of 8\n\n"
        "## Preferences\n"
        "- Likes detailed technical explanations\n",
        encoding="utf-8",
    )
    (ws / "memory").mkdir()
    (ws / "output").mkdir()
    skills = ws / "skills"

    # Editable skill 1: weekly report generator (has a structural gap: no risk).
    (skills / "weekly-report").mkdir(parents=True)
    (skills / "weekly-report" / "SKILL.md").write_text(
        "# Weekly Report\n\n"
        "Generate a weekly work report from the user's notes.\n\n"
        "## Steps\n"
        "1. Collect this week's completed items.\n"
        "2. Summarize key progress in 3-5 bullets.\n"
        "3. List next week's plan.\n\n"
        "## Output format\n"
        "Markdown with sections: 本周进展 / 下周计划\n",
        encoding="utf-8",
    )

    # Editable skill 2: expense tracker (has a wrong currency-format step).
    (skills / "expense-tracker").mkdir(parents=True)
    (skills / "expense-tracker" / "SKILL.md").write_text(
        "# Expense Tracker\n\n"
        "Record an expense into output/expenses.md.\n\n"
        "## Steps\n"
        "1. Parse amount and category from the user message.\n"
        "2. Append a row to output/expenses.md.\n"
        "3. Format the amount with a `$` prefix.\n",
        encoding="utf-8",
    )

    # Editable skill 3: an API caller whose SKILL.md hardcodes a WRONG endpoint
    # host. The conversation discovers the correct host at runtime; the right
    # fix is to edit this file's source, not just log the corrected fact.
    (skills / "data-fetch").mkdir(parents=True)
    (skills / "data-fetch" / "SKILL.md").write_text(
        "# Data Fetch\n\n"
        "Fetch records from the data service.\n\n"
        "## Steps\n"
        "1. Build the request payload from the user's query.\n"
        "2. POST it to `https://api.example-wrong.com/v1/fetch`.\n"
        "3. Parse and return the `data` field.\n",
        encoding="utf-8",
    )

    # Protected built-in skill: must never be edited by evolution.
    (skills / "image-generation").mkdir(parents=True)
    (skills / "image-generation" / "SKILL.md").write_text(
        "# Image Generation (built-in)\nDo not modify.\n", encoding="utf-8"
    )
    return ws


def _point_config_at(ws):
    """Force the global memory config to use the temp workspace."""
    from agent.memory.config import MemoryConfig, set_global_memory_config
    set_global_memory_config(MemoryConfig(workspace_root=str(ws)))


def _make_messages(turns):
    msgs = []
    for u, a in turns:
        msgs.append({"role": "user", "content": u})
        msgs.append({"role": "assistant", "content": a})
    return msgs


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------
def scenario_silent():
    """Pure small talk -> should stay SILENT (no change, no notify)."""
    return {
        "name": "闲聊 (should stay SILENT)",
        "goal": "none",
        "turns": [
            ("在吗", "在的，有什么可以帮你？"),
            ("今天周五了，终于要放假了", "是呀，周末好好休息一下。"),
            ("哈哈是的，那没事了", "好的，随时找我。"),
        ],
        "scripted": "[SILENT]",
        "on_edit": None,
        "expect_evolved": False,
    }


def scenario_silent_qa():
    """A normal knowledge Q&A -> nothing durable, should stay SILENT."""
    return {
        "name": "普通问答 (should stay SILENT)",
        "goal": "none",
        "turns": [
            ("Python 里 list 和 tuple 有什么区别？",
             "主要区别：list 可变、用 []；tuple 不可变、用 ()。tuple 更省内存、可作字典键。"),
            ("那什么时候该用 tuple？", "当数据不应被修改、或要做字典键/集合元素时用 tuple。"),
            ("懂了，谢谢", "不客气。"),
        ],
        "scripted": "[SILENT]",
        "on_edit": None,
        "expect_evolved": False,
    }


def scenario_silent_transient():
    """User shares transient, non-durable info -> should stay SILENT."""
    return {
        "name": "临时信息 (should stay SILENT)",
        "goal": "none",
        "turns": [
            ("帮我看下今天天气适合跑步吗，深圳", "深圳今天多云 26°C，傍晚湿度高，清晨或晚上跑步比较合适。"),
            ("那我晚上去吧", "好的，记得补水。"),
            ("行", "👍"),
        ],
        "scripted": "[SILENT]",
        "on_edit": None,
        "expect_evolved": False,
    }


def scenario_silent_advice():
    """User asks for one-off advice, no reusable workflow -> should stay SILENT."""
    return {
        "name": "一次性建议 (should stay SILENT)",
        "goal": "none",
        "turns": [
            ("给我起三个适合咖啡馆的名字", "可以考虑：① 拾光咖啡 ② 角落 Corner ③ 慢半拍。"),
            ("第二个不错", "嗯，「角落 Corner」简洁好记。"),
            ("就用这个了", "好的，祝开业顺利。"),
        ],
        "scripted": "[SILENT]",
        "on_edit": None,
        "expect_evolved": False,
    }


def scenario_memory_preference():
    """User states a durable working preference -> update MEMORY.md."""
    def edit(ws):
        from datetime import datetime
        p = ws / "memory" / (datetime.now().strftime("%Y-%m-%d") + ".md")
        p.write_text((p.read_text() if p.exists() else "") + "- Prefers concise replies; avoid long explanations\n", encoding="utf-8")

    return {
        "name": "记忆-偏好 (should note in daily memory)",
        "goal": "memory",
        "turns": [
            ("你能帮我解释下什么是数据库事务吗", "当然可以。数据库事务（Transaction）是一组要么全部成功、要么全部失败的操作单元，它有四个核心特性 ACID：原子性、一致性、隔离性、持久性……（接着是 5 段详细展开）"),
            ("打住打住，太长了", "抱歉，我说得太细了。"),
            ("对，你以后回答我都简短一点，抓重点就行，别长篇大论", "好的，明白了。"),
            ("嗯这样挺好", "👌"),
        ],
        "scripted": (
            "我刚做了一次自我学习。\n"
            "- 学到：你希望回答简短、抓重点\n"
            "- 调整：更新了长期记忆 MEMORY.md\n"
            "如果不对，回复「撤销上次学习」即可。"
        ),
        "on_edit": edit,
        "expect_evolved": True,
        "expect_memory_contains": "concise",
    }


def scenario_memory_correction():
    """User corrects a wrong fact the agent stated -> fix MEMORY.md."""
    def edit(ws):
        from datetime import datetime
        p = ws / "memory" / (datetime.now().strftime("%Y-%m-%d") + ".md")
        p.write_text((p.read_text() if p.exists() else "") + "- Correction: team size is now 15 (was recorded as 8)\n", encoding="utf-8")

    return {
        "name": "记忆-纠正事实 (should note correction in daily)",
        "goal": "memory",
        "turns": [
            ("我们团队最近又招了几个人", "记得你们是 8 人的小团队，扩张了挺好的。"),
            ("不对，我们现在是 15 个人了，上次你就记错了", "抱歉记错了，你们现在是 15 人团队。"),
            ("嗯对，记住啊", "好的，记住了。"),
        ],
        "scripted": (
            "我刚做了一次自我学习。\n"
            "- 学到：团队规模已是 15 人（之前记成 8 人）\n"
            "- 调整：修正了长期记忆 MEMORY.md\n"
            "如果不对，回复「撤销上次学习」即可。"
        ),
        "on_edit": edit,
        "expect_evolved": True,
        "expect_memory_contains": "15",
    }


def scenario_skill_gap():
    """Using weekly-report reveals a missing section -> patch the skill."""
    def edit(ws):
        p = ws / "skills" / "weekly-report" / "SKILL.md"
        p.write_text(p.read_text() + "4. List risk items / blockers.\n", encoding="utf-8")

    return {
        "name": "技能-缺陷 (should patch weekly-report skill)",
        "goal": "skill",
        "turns": [
            ("用周报技能帮我生成这周的周报，素材：完成了支付网关重构、修复了3个线上bug、对接了风控接口",
             "好的，我用 weekly-report 技能生成：\n\n## 本周进展\n- 完成支付网关重构\n- 修复 3 个线上 bug\n- 对接风控接口\n\n## 下周计划\n- 联调风控接口"),
            ("不错，但是每次周报都漏了风险项，我们 leader 每次都要问这个", "确实，风险项很重要。"),
            ("对，你能不能让这个周报技能以后都带上风险项这一节", "可以的，我把它固化进技能。"),
        ],
        "scripted": (
            "我刚做了一次自我学习。\n"
            "- 学到：周报需要固定包含「风险项」一节\n"
            "- 调整：给 weekly-report 技能补充了风险项步骤\n"
            "如果不对，回复「撤销上次学习」即可。"
        ),
        "on_edit": edit,
        "expect_evolved": True,
        "expect_skill_contains": ("weekly-report", "risk"),
    }


def scenario_skill_error():
    """A skill step is wrong (currency format) -> correct the skill."""
    def edit(ws):
        p = ws / "skills" / "expense-tracker" / "SKILL.md"
        p.write_text(p.read_text().replace("`$` prefix", "`¥` prefix (RMB)"), encoding="utf-8")

    return {
        "name": "技能-报错纠正 (should fix expense-tracker skill)",
        "goal": "skill",
        "turns": [
            ("用记账技能记一笔：午饭 35", "好的，已记录：午饭 $35（已写入 output/expenses.md）"),
            ("怎么是美元？我们都是人民币啊", "抱歉，格式用错了，应该是 ¥35。"),
            ("对，以后这个记账技能都用人民币符号", "明白，我修正技能里的货币格式。"),
        ],
        "scripted": (
            "我刚做了一次自我学习。\n"
            "- 学到：记账应使用人民币符号 ¥ 而非 $\n"
            "- 调整：修正了 expense-tracker 技能的货币格式步骤\n"
            "如果不对，回复「撤销上次学习」即可。"
        ),
        "on_edit": edit,
        "expect_evolved": True,
        "expect_skill_contains": ("expense-tracker", "¥"),
    }


def scenario_skill_wrong_config():
    """A skill's SKILL.md hardcodes a wrong endpoint; the chat works around it
    at runtime. Correct evolution = FIX the skill source, not log a memory note.
    """
    def edit(ws):
        p = ws / "skills" / "data-fetch" / "SKILL.md"
        p.write_text(
            p.read_text().replace("api.example-wrong.com", "api.example-correct.com"),
            encoding="utf-8",
        )

    return {
        "name": "技能-配置错误 (should fix skill source, not log memory)",
        "goal": "skill",
        "turns": [
            ("用 data-fetch 技能拉一下最新数据",
             "好的，我按技能里的步骤 POST 到 https://api.example-wrong.com/v1/fetch …… 报错了，连接失败。"),
            ("哦那个地址不对，正确的是 api.example-correct.com，你用这个调",
             "好的，换成 https://api.example-correct.com/v1/fetch ，成功拿到数据了 ✅"),
            ("嗯对，就是这个地址", "明白了，这个才是正确的服务地址。"),
        ],
        # The model must decide on its own to edit the skill; we still provide a
        # scripted output for stub mode wiring.
        "scripted": (
            "我刚做了一次自我学习。\n"
            "- 学到：data-fetch 的正确服务地址是 api.example-correct.com\n"
            "- 调整：修正了 data-fetch 技能里写错的接口地址\n"
            "如果不对，回复「撤销上次学习」即可。"
        ),
        "on_edit": edit,
        "expect_evolved": True,
        "expect_skill_contains": ("data-fetch", "api.example-correct.com"),
    }


def scenario_skill_create():
    """A reusable, repeatable workflow emerges that no skill covers, and the
    user explicitly asks to make it permanent -> CREATE a new skill.
    """
    return {
        "name": "技能-新增 (should create a new skill)",
        "goal": "skill",
        "turns": [
            ("每周一帮我把客户反馈整理成晨会简报：先按「严重/一般/建议」给反馈分类，再统计每类数量，最后写一段 3 句话的总结，发我",
             "好的，本周客户反馈晨会简报：\n\n## 严重 (2)\n- 支付失败\n- 数据丢失\n## 一般 (3)\n- 加载慢…\n## 建议 (1)\n- 增加暗色模式\n\n总结：本周以稳定性问题为主，建议优先排查支付与数据链路，其余可排期跟进。"),
            ("很好，就是这个格式。上周我也是这么让你弄的", "嗯，分类+计数+三句总结这套流程挺顺手。"),
            ("对，这个我每周一都要用，你能不能把这套流程固化下来，以后我直接说『生成客户反馈晨会简报』你就照这个来",
             "可以，我把这套「客户反馈晨会简报」流程固化成一个可复用的技能。"),
        ],
        "scripted": (
            "我刚做了一次自我学习。\n"
            "- 学到：你每周一都要按「分类+计数+三句总结」生成客户反馈晨会简报\n"
            "- 调整：新建了「客户反馈晨会简报」技能，固化这套流程\n"
            "如果不对，回复「撤销上次学习」即可。"
        ),
        "on_edit": _create_briefing_skill,
        "expect_evolved": True,
        "expect_new_skill": True,
    }


def scenario_skill_create_implicit():
    """A complex, clearly-structured multi-step workflow is executed once. The
    user NEVER says "I do this weekly" or "make this a skill" — the agent must
    判断 on its own that this is a reusable procedure worth capturing.

    This is the realistic, harder case: no explicit instruction to create a
    skill, only an obviously repeatable workflow.
    """
    return {
        "name": "技能-隐式新增 (complex workflow, user never asks to save)",
        "goal": "skill",
        "turns": [
            ("帮我做一份竞品调研：对比一下 Notion、飞书文档、语雀这三个产品",
             "好的，我按一套固定方法来做竞品调研：\n1. 先确定对比维度：定价、协作能力、模板生态、API 开放度、本地化；\n2. 逐个产品按维度收集信息；\n3. 做成对比表；\n4. 给出结论和选型建议。\n\n（随后产出了完整的五维度对比表 + 结论）"),
            ("不错。再帮我用同样的方法调研一下 Slack、企业微信、钉钉",
             "好的，沿用刚才那套方法（定价/协作/模板/API/本地化 五维度 → 收集 → 对比表 → 结论）：\n\n（产出了第二份五维度对比表 + 选型建议）"),
            ("可以，结论挺清楚的", "嗯，这套五维度对比的方法做下来结构很清楚。"),
        ],
        # In real mode the model decides on its own. The scripted side effect
        # only wires stub mode; it emulates capturing the procedure as a skill.
        "scripted": (
            "我刚做了一次自我学习。\n"
            "- 学到：你做竞品调研有一套固定方法（五维度对比 → 收集 → 对比表 → 结论）\n"
            "- 调整：把这套竞品调研流程固化成了一个可复用技能\n"
            "如果不对，回复「撤销上次学习」即可。"
        ),
        "on_edit": _create_competitor_skill,
        "expect_evolved": True,
        "expect_new_skill": True,
    }


def _create_competitor_skill(ws):
    """Stub side effect: emulate capturing the competitor-research procedure."""
    d = ws / "skills" / "competitor-research"
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        "# Competitor Research\n\n"
        "Compare a set of products with a fixed methodology.\n\n"
        "## Steps\n"
        "1. Fix the comparison dimensions (pricing, collaboration, templates, API, localization).\n"
        "2. Collect info per product across each dimension.\n"
        "3. Build a comparison table.\n"
        "4. Give a conclusion and recommendation.\n",
        encoding="utf-8",
    )


def scenario_skill_no_create():
    """A one-off, novel task with no sign of recurrence -> must NOT create a
    skill (and ideally stay silent). Guards against over-eager skill creation.
    """
    return {
        "name": "技能-不应新增 (one-off task, must NOT create skill)",
        "goal": "none",
        "turns": [
            ("帮我把这段话翻译成英文：今晚的庆功宴改到 8 点", "翻译：The celebration dinner tonight is moved to 8 PM."),
            ("谢谢", "不客气。"),
            ("嗯没事了", "好的，随时找我。"),
        ],
        "scripted": "[SILENT]",
        "on_edit": None,
        "expect_evolved": False,
        "expect_no_new_skill": True,
    }


def _create_briefing_skill(ws):
    """Stub side effect: emulate creating a new skill under workspace skills/."""
    d = ws / "skills" / "customer-feedback-briefing"
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        "# Customer Feedback Briefing\n\n"
        "Turn raw customer feedback into a standup briefing.\n\n"
        "## Steps\n"
        "1. Classify each item as 严重/一般/建议.\n"
        "2. Count items per category.\n"
        "3. Write a 3-sentence summary.\n",
        encoding="utf-8",
    )


def scenario_unfinished_task():
    """A promised deliverable was not produced -> finish it now via tools."""
    def edit(ws):
        p = ws / "output" / "team-roster.md"
        p.write_text("# Team Roster (backend)\n- 张伟\n- 李娜\n- 王强\n- 大锤\n", encoding="utf-8")

    return {
        "name": "未完成任务 (should finish & write output file)",
        "goal": "task",
        "turns": [
            ("帮我把后端团队花名册整理成一个文件保存下，成员有：张伟、李娜、王强，还有我自己（大锤）",
             "好的，后端 4 个人：张伟、李娜、王强、大锤。我整理成文件保存到 output/team-roster.md。"),
            ("好的麻烦了，我先去开个会", "没问题，我现在就处理。"),
            ("（用户离开，会话中断，文件尚未写入）", "（助手未及写入文件，对话中断）"),
        ],
        "scripted": (
            "我刚做了一次自我学习。\n"
            "- 发现：之前答应整理团队花名册但没完成\n"
            "- 已完成：把后端成员名单写入 output/team-roster.md\n"
            "如果不需要，回复「撤销上次学习」即可。"
        ),
        "on_edit": edit,
        "expect_evolved": True,
        "expect_output_file": "team-roster.md",
    }


SCENARIOS = [
    scenario_silent,
    scenario_silent_qa,
    scenario_silent_transient,
    scenario_silent_advice,
    scenario_memory_preference,
    scenario_memory_correction,
    scenario_skill_gap,
    scenario_skill_error,
    scenario_skill_wrong_config,
    scenario_skill_create,
    scenario_skill_create_implicit,
    scenario_skill_no_create,
    scenario_unfinished_task,
]

# Skill directories present in a fresh workspace; anything beyond these that
# appears after a pass is a newly-created skill.
_SEED_SKILLS = {"weekly-report", "expense-tracker", "data-fetch", "image-generation"}


def _new_skill_dirs(ws: Path) -> set:
    """Skill directories created beyond the seeded set."""
    skills_dir = ws / "skills"
    if not skills_dir.exists():
        return set()
    return {p.name for p in skills_dir.iterdir() if p.is_dir()} - _SEED_SKILLS


# ---------------------------------------------------------------------------
# Runner (stub mode)
# ---------------------------------------------------------------------------
def run_stub():
    from agent.evolution.executor import run_evolution_for_session
    from agent.evolution import backup as backup_mod
    from config import conf
    # Evolution is disabled by default now; enable for the test.
    conf()["self_evolution_enabled"] = True

    passed, failed = 0, 0
    for make in SCENARIOS:
        sc = make()
        ws = _setup_workspace()
        try:
            _point_config_at(ws)
            # Patch channel push to capture instead of send.
            channel = FakeChannel()
            import agent.evolution.executor as ex
            orig_notify = ex._notify_user
            ex._notify_user = lambda ct, rcv, summary: channel.send(
                type("R", (), {"content": summary})(),
                {"receiver": rcv},
            )

            agent = FakeAgent(_make_messages(sc["turns"]))
            bridge = FakeAgentBridge(agent, sc["scripted"], on_edit=sc["on_edit"])

            evolved = run_evolution_for_session(
                bridge, "session_test", channel_type="telegram", receiver="user_42"
            )

            ok = True
            errs = []

            if evolved != sc["expect_evolved"]:
                ok = False
                errs.append(f"evolved={evolved}, expected {sc['expect_evolved']}")

            if sc["expect_evolved"]:
                # memory / skill content checks
                if "expect_memory_contains" in sc:
                    # Evolution now writes to the dated daily file, not MEMORY.md.
                    from datetime import datetime
                    daily = ws / "memory" / (datetime.now().strftime("%Y-%m-%d") + ".md")
                    mem = daily.read_text() if daily.exists() else ""
                    if sc["expect_memory_contains"] not in mem:
                        ok = False
                        errs.append("daily memory missing expected content")
                if "expect_skill_contains" in sc:
                    sk, txt = sc["expect_skill_contains"]
                    content = (ws / "skills" / sk / "SKILL.md").read_text()
                    if txt not in content:
                        ok = False
                        errs.append("skill missing expected content")
                if sc.get("expect_new_skill") and not _new_skill_dirs(ws):
                    ok = False
                    errs.append("expected a new skill to be created")
                # notify happened
                if not channel.sent:
                    ok = False
                    errs.append("no notification sent")
                # injection happened (undo support)
                if not bridge.injected or "[EVOLUTION]" not in bridge.injected[0]:
                    ok = False
                    errs.append("no [EVOLUTION] record injected")
                # protected skill untouched
                prot = (ws / "skills" / "image-generation" / "SKILL.md").read_text()
                if prot != "# Image Generation (built-in)\nDo not modify.\n":
                    ok = False
                    errs.append("PROTECTED skill was modified!")
                # backup exists (undo possible)
                backups = list((ws / "memory" / ".evolution_backups").glob("*"))
                if not backups:
                    ok = False
                    errs.append("no backup created")
            else:
                # SILENT: nothing should have changed / been sent
                if channel.sent:
                    ok = False
                    errs.append("notification sent on SILENT")
                if bridge.injected:
                    ok = False
                    errs.append("injected record on SILENT")
            if sc.get("expect_no_new_skill") and _new_skill_dirs(ws):
                ok = False
                errs.append(f"unexpected new skill created: {_new_skill_dirs(ws)}")

            ex._notify_user = orig_notify

            if ok:
                passed += 1
                print(f"  PASS  {sc['name']}")
            else:
                failed += 1
                print(f"  FAIL  {sc['name']}: {'; '.join(errs)}")
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    # Undo verification (uses the memory scenario's backup path).
    print("\n-- undo tool --")
    _verify_undo()

    print(f"\nStub results: {passed} passed, {failed} failed")
    return failed == 0


def _verify_undo():
    from agent.evolution.backup import create_backup, restore_backup
    ws = _setup_workspace()
    try:
        _point_config_at(ws)
        mem = ws / "MEMORY.md"
        bid = create_backup(ws, [mem])
        mem.write_text("CORRUPTED", encoding="utf-8")
        from agent.tools.evolution_undo import EvolutionUndoTool
        r = EvolutionUndoTool().execute({"backup_id": bid})
        restored = mem.read_text()
        if r.status == "success" and "大锤" in restored:
            print("  PASS  undo restores pre-evolution state")
        else:
            print(f"  FAIL  undo: status={r.status}, content={restored[:40]}")
    finally:
        shutil.rmtree(ws, ignore_errors=True)


# ---------------------------------------------------------------------------
# Runner (real mode) — minimal: just prints the model's decision per scenario.
# ---------------------------------------------------------------------------
def _snapshot_ws(ws: Path) -> dict:
    """Map every text file under the workspace -> content (skip backups dir)."""
    snap = {}
    for p in ws.rglob("*"):
        if not p.is_file():
            continue
        rel = str(p.relative_to(ws))
        if rel.startswith("memory/.evolution_backups"):
            continue
        try:
            snap[rel] = p.read_text(encoding="utf-8")
        except Exception:
            pass
    return snap


def _print_diff(before: dict, after: dict) -> bool:
    """Print added/changed files. Returns True if anything changed."""
    changed = False
    keys = sorted(set(before) | set(after))
    for rel in keys:
        old = before.get(rel)
        new = after.get(rel)
        if old == new:
            continue
        changed = True
        tag = "NEW FILE" if old is None else "CHANGED"
        print(f"      ~ {rel} [{tag}]")
        old_lines = set((old or "").splitlines())
        for line in (new or "").splitlines():
            if line not in old_lines:
                print(f"          + {line}")
    return changed


def run_real():
    """Run real model evolution on each scenario and print the actual output.

    Uses config.json's configured model via a real AgentBridge, so you see
    exactly what the model decides and writes for each conversation.
    """
    from bridge.bridge import Bridge
    from agent.memory.config import (
        MemoryConfig,
        set_global_memory_config,
        get_default_memory_config,
    )
    from config import conf, load_config

    # Load config.json so real API keys are available to the bots.
    load_config()

    # Default the test to deepseek-v4-flash (fast, low cost) unless overridden.
    override_model = os.environ.get("EVO_TEST_MODEL", "deepseek-v4-flash")
    conf()["model"] = override_model
    conf()["bot_type"] = os.environ.get("EVO_TEST_BOT_TYPE", "deepseek")
    # Force-enable evolution for the test regardless of config.json default.
    conf()["self_evolution_enabled"] = True
    print(f"[test] model: {override_model} (bot_type={conf().get('bot_type')}, "
          f"key={'set' if conf().get('deepseek_api_key') else 'MISSING'})")

    from agent.memory.manager import MemoryManager
    import agent.evolution.executor as ex

    bridge = Bridge()
    agent_bridge = bridge.get_agent_bridge()

    # Capture the user-facing reply instead of pushing it to a channel.
    captured = {"reply": None}
    orig_notify = ex._notify_user
    ex._notify_user = lambda ct, rcv, summary: captured.__setitem__("reply", summary)

    results = []  # (name, goal, evolved, changed, reply_ok)

    only = os.environ.get("EVO_TEST_ONLY")  # substring filter on goal/name
    try:
        for make in SCENARIOS:
            sc = make()
            if only and only not in sc["goal"] and only not in sc["name"]:
                continue
            ws = _setup_workspace()
            captured["reply"] = None
            try:
                mem_cfg = MemoryConfig(workspace_root=str(ws))
                set_global_memory_config(mem_cfg)

                sid = "session_evo_real"
                # Fully isolated agent: tool cwd + memory_manager -> temp ws.
                iso_mem = MemoryManager(mem_cfg)
                agent = agent_bridge.create_agent(
                    system_prompt="You are a helpful assistant.",
                    tools=None,
                    workspace_dir=str(ws),
                    memory_manager=iso_mem,
                    enable_skills=False,
                )
                # Notify path needs a channel+receiver to fire; give dummies.
                agent_bridge.agents[sid] = agent
                with agent.messages_lock:
                    agent.messages.clear()
                    agent.messages.extend(_make_messages(sc["turns"]))

                before = _snapshot_ws(ws)

                print("\n" + "=" * 72)
                print(f"场景: {sc['name']}   [目标: {sc['goal']}]")
                print("-" * 72)
                print("【会话输入】")
                for u, a in sc["turns"]:
                    print(f"   用户: {u}")
                    print(f"   助手: {a}")

                from agent.evolution.executor import run_evolution_for_session
                evolved = run_evolution_for_session(
                    agent_bridge, sid, channel_type="telegram", receiver="tester"
                )

                after = _snapshot_ws(ws)
                print("\n【进化结果】 evolved =", evolved)
                changed = False
                if evolved:
                    changed = _print_diff(before, after)
                    if not changed:
                        print("      (无文件变更)")
                else:
                    print("      (静默，未做任何改动)")

                new_skills = _new_skill_dirs(ws)
                if new_skills:
                    print(f"      新建技能: {', '.join(sorted(new_skills))}")
                # Surface mismatches against the scenario's skill expectation.
                if sc.get("expect_new_skill") and not new_skills:
                    print("      ⚠ 预期新建技能，但未创建")
                if sc.get("expect_no_new_skill") and new_skills:
                    print("      ⚠ 不应新建技能，但创建了")

                print("\n【给用户的回复】")
                if captured["reply"]:
                    for line in captured["reply"].splitlines():
                        print(f"   {line}")
                else:
                    print("   (无推送)")

                reply_ok = bool(captured["reply"]) == bool(evolved)
                results.append((sc["name"], sc["goal"], evolved, changed, reply_ok))
                agent_bridge.agents.pop(sid, None)
            finally:
                shutil.rmtree(ws, ignore_errors=True)
    finally:
        ex._notify_user = orig_notify

    # Summary table.
    print("\n" + "=" * 72)
    print("汇总 (deepseek-v4-flash 真实运行)")
    print("-" * 72)
    for name, goal, evolved, changed, reply_ok in results:
        exp = "静默" if goal == "none" else "应进化"
        got = "进化" if evolved else "静默"
        mark = "✓" if (goal == "none") != evolved else "✗"
        print(f"  {mark}  {name:42s} 预期={exp} 实际={got}")


if __name__ == "__main__":
    if "--debug" in sys.argv:
        import logging
        from common.log import logger as _cow_logger
        _cow_logger.setLevel(logging.DEBUG)
        for _h in _cow_logger.handlers:
            _h.setLevel(logging.DEBUG)
    if "--real" in sys.argv:
        run_real()
    else:
        ok = run_stub()
        sys.exit(0 if ok else 1)
