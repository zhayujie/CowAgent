# from roles.load_role import get_role_list
# roles_list_path = "role_file_map.json"
# import json5
# # from role import update_files
# def update_files():
#     try:
#         now_roles_list = get_role_list()
#     except FileNotFoundError:
#         now_roles_list = []
#     try:
#         with open(roles_list_path, "r", encoding="utf-8") as f:
#             old_roles_map = json5.load(f)
#     except FileNotFoundError:
#         old_roles_map = {}
#     old_roles_list = [item for item in old_roles_map.values()]

#     add_list = [item for item in now_roles_list if item not in old_roles_list]
#     del_list = [item for item in old_roles_list if item not in now_roles_list]

#     if add_list :
#         for item in add_list:
#             with open(f"roles/{item}.json", "r", encoding="utf-8") as f:
#                 ret = json5.load(f)
#                 old_roles_map[ret["title"]] = item
#     print(del_list)
#     for del_item in del_list:
#         for key, value in list(old_roles_map.items()):
#             if value == del_item:
#                 del old_roles_map[key]
#                 break
#     with open(roles_list_path, "w", encoding="utf-8") as f:
#         json5.dump(old_roles_map, f, indent=4, ensure_ascii=False)
import os
import json5
import json5
import os
import plugins
from bridge.bridge import Bridge
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common import const
from common.log import logger
from config import conf
from plugins import *
from roles.load_role import get_role_list


CURDIR = os.path.dirname(__file__)
TAGS_PATH = os.path.join(CURDIR, "tag.json")
ROLES_MAP_PATH = os.path.join(CURDIR, "role_file_map.json")
ROLES_DIR_PATH = os.path.join(CURDIR, "roles")


class RolePlay:
    def __init__(self, bot, sessionid, desc, wrapper=None):
        self.bot = bot
        self.sessionid = sessionid
        self.wrapper = wrapper or "%s"  # 用于包装用户输入
        self.desc = desc
        self.bot.sessions.build_session(self.sessionid, system_prompt=self.desc)

    def reset(self):
        self.bot.sessions.clear_session(self.sessionid)

    def action(self, user_action):
        session = self.bot.sessions.build_session(self.sessionid)
        if (
            session.system_prompt != self.desc
        ):  # 目前没有触发session过期事件，这里先简单判断，然后重置
            session.set_system_prompt(self.desc)
        prompt = self.wrapper % user_action
        return prompt



class Role(Plugin):
    def __init__(self):
        super().__init__()
        try:
            self.tags = {}
            self.roles = {}
            if os.path.exists(TAGS_PATH):
                with open(TAGS_PATH, "r", encoding="utf-8") as f:
                    tags_config = json5.load(f)
                    self.tags = {tag: (desc, []) for tag, desc in tags_config.get("tags", {}).items()}
            else:
                logger.warning(f"[Role] tag.json not found at {TAGS_PATH}")
            if os.path.exists(ROLES_MAP_PATH):
                with open(ROLES_MAP_PATH, "r", encoding="utf-8") as f:
                    self.role_map = json5.load(f)
            else:
                self.role_map = {}
                logger.warning(f"[Role] role_file_map.json not found at {ROLES_MAP_PATH}")

            for role_name, file_name in self.role_map.items():
                role_dict = self.get_role_dict(role_name)
                if not role_dict:
                    continue
                role_key = role_name.lower()
                self.roles[role_key] = role_dict
                for tag in role_dict.get("tags", []):
                    if tag not in self.tags:
                        logger.warning(f"[Role] unknown tag {tag} in role {role_name}")
                        self.tags[tag] = (tag, [])
                    self.tags[tag][1].append(role_dict)
            for tag in list(self.tags.keys()):
                if len(self.tags[tag][1]) == 0:
                    logger.debug(f"[Role] no role found for tag {tag} ")
                    del self.tags[tag]

            if len(self.roles) == 0:
                raise Exception("no role found in configurations")

            self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
            self.roleplays = {}
            logger.info(f"[Role] inited. Loaded {len(self.roles)} roles.")

        except Exception as e:
            logger.error(f"[Role] init failed: {e}")
            raise e

    def get_role_dict(self, role_name: str ) -> dict:
        if role_name not in self.role_map:
            logger.error(f"[Role] role_name '{role_name}' not found in role_map")
            return {}

        role_file = self.role_map[role_name]
        full_path = os.path.join(ROLES_DIR_PATH, f"{role_file}.json")

        try:
            if os.path.exists(full_path):
                with open(full_path, "r", encoding="utf-8") as f:
                    return json5.load(f)
            else:
                logger.error(f"[Role] file not found: {full_path}")
                return {}
        except Exception as e:
            logger.error(f"[Role] load role file '{full_path}' failed: {e}")
            return {}

    def get_role(self, name, find_closest=True, min_sim=0.35):
        name = name.lower()
        found_role = None
        if name in self.roles:
            found_role = name
        elif find_closest:
            import difflib

            def str_simularity(a, b):
                return difflib.SequenceMatcher(None, a, b).ratio()

            max_sim = min_sim
            max_role = None
            for role in self.roles:
                sim = str_simularity(name, role)
                if sim >= max_sim:
                    max_sim = sim
                    max_role = role
            found_role = max_role
        return found_role

    def on_handle_context(self, e_context: EventContext):
        if e_context["context"].type != ContextType.TEXT:
            return
        btype = Bridge().get_bot_type("chat")
        if btype not in [
            const.OPEN_AI, const.OPENAI, const.CHATGPT, const.CHATGPTONAZURE,
            const.QWEN_DASHSCOPE, const.XUNFEI, const.BAIDU, const.QIANFAN,
            const.ZHIPU_AI, const.MOONSHOT, const.MiniMax, const.LINKAI, const.MODELSCOPE,
        ]:
            logger.debug(f"不支持的bot: {btype}")
            return

        bot = Bridge().get_bot("chat")
        content = e_context["context"].content[:]
        clist = e_context["context"].content.split(maxsplit=1)
        desckey = None
        customize = False
        sessionid = e_context["context"]["session_id"]
        trigger_prefix = conf().get("plugin_trigger_prefix", "$")
        if clist[0] == f"{trigger_prefix}停止扮演":
            if sessionid in self.roleplays:
                self.roleplays[sessionid].reset()
                del self.roleplays[sessionid]
            reply = Reply(ReplyType.INFO, "角色扮演结束!")
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS
            return
        elif clist[0] == f"{trigger_prefix}角色":
            desckey = "descn"
        elif clist[0].lower() == f"{trigger_prefix}role":
            desckey = "description"
        elif clist[0] == f"{trigger_prefix}设定扮演":
            customize = True
        elif clist[0] == f"{trigger_prefix}角色类型":
            if len(clist) > 1:
                tag = clist[1].strip()
                help_text = "角色列表：\n"
                for key, value in self.tags.items():
                    if value[0] == tag:
                        tag = key
                        break
                if tag == "所有":
                    for role in self.roles.values():
                        help_text += f"{role['title']}: {role['remark']}\n"
                elif tag in self.tags:
                    for role in self.tags[tag][1]:
                        help_text += f"{role['title']}: {role['remark']}\n"
                else:
                    help_text = f"未知角色类型。\n目前的角色类型有: \n"
                    help_text += "，".join([self.tags[tag][0] for tag in self.tags]) + "\n"
            else:
                help_text = f"请输入角色类型。\n目前的角色类型有: \n"
                help_text += "，".join([self.tags[tag][0] for tag in self.tags]) + "\n"
            reply = Reply(ReplyType.INFO, help_text)
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS
            return
        if desckey is None and not customize and sessionid not in self.roleplays:
            return

        logger.debug("[Role] on_handle_context. content: %s" % content)

        if desckey is not None:
            if len(clist) == 1 or (len(clist) > 1 and clist[1].lower() in ["help", "帮助"]):
                reply = Reply(ReplyType.INFO, self.get_help_text(verbose=True))
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
                return

            role = self.get_role(clist[1])
            if role is None:
                reply = Reply(ReplyType.ERROR, "角色不存在")
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
                return
            else:
                self.roleplays[sessionid] = RolePlay(
                    bot,
                    sessionid,
                    self.roles[role][desckey],
                    self.roles[role].get("wrapper", "%s"),
                )
                reply = Reply(ReplyType.INFO, f"预设角色为 {role}:\n" + self.roles[role][desckey])
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
        elif customize:
            if len(clist) < 2:
                reply = Reply(ReplyType.ERROR, "请提供具体的角色设定内容")
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
                return
            self.roleplays[sessionid] = RolePlay(bot, sessionid, clist[1], "%s")
            reply = Reply(ReplyType.INFO, f"角色设定为:\n{clist[1]}")
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS
        else:
            # 已经处于扮演状态下的日常对话处理
            e_context["context"]["generate_breaked_by"] = EventAction.BREAK
            prompt = self.roleplays[sessionid].action(content)
            e_context["context"].type = ContextType.TEXT
            e_context["context"].content = prompt
            e_context.action = EventAction.BREAK

    def get_help_text(self, verbose=False, **kwargs):
        help_text = "让机器人扮演不同的角色。\n"
        if not verbose:
            return help_text
        trigger_prefix = conf().get("plugin_trigger_prefix", "$")
        help_text = (
                f"使用方法:\n{trigger_prefix}角色 预设角色名: 设定角色为{{预设角色名}}。\n"
                + f"{trigger_prefix}role 预设角色名: 同上，使用英文设定。\n"
                + f"{trigger_prefix}设定扮演 角色设定: 设定自定义角色人设。\n"
                + f"{trigger_prefix}停止扮演: 清除设定的角色。\n"
                + f"{trigger_prefix}角色类型 角色类型: 查看预设角色（如：{trigger_prefix}角色类型 所有）。\n"
        )
        help_text += "\n目前的角色类型有: \n"
        help_text += "，".join([self.tags[tag][0] for tag in self.tags]) + "。\n"
        return help_text


ret = Role()
print(ret.get_role_dict("费曼学习法教练")) 