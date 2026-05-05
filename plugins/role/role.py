# encoding:utf-8

import json
import os

import plugins
from bridge.bridge import Bridge
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common import const
from common.log import logger
from config import conf
from plugins import *


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
        if session.system_prompt != self.desc:  # 目前没有触发session过期事件，这里先简单判断，然后重置
            session.set_system_prompt(self.desc)
        prompt = self.wrapper % user_action
        return prompt


@plugins.register(
    name="Role",
    desire_priority=0,
    namecn="角色扮演",
    desc="为你的Bot设置预设角色",
    version="1.0",
    author="lanvent",
)
class Role(Plugin):
    def __init__(self):
        super().__init__()
        curdir = os.path.dirname(__file__)
        config_path = os.path.join(curdir, "roles.json")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                self.tags = {tag: (desc, []) for tag, desc in config["tags"].items()}
                self.roles = {}
                for role in config["roles"]:
                    self.roles[role["title"].lower()] = role
                    for tag in role["tags"]:
                        if tag not in self.tags:
                            logger.warning(f"[Role] unknown tag {tag} ")
                            self.tags[tag] = (tag, [])
                        self.tags[tag][1].append(role)
                for tag in list(self.tags.keys()):
                    if len(self.tags[tag][1]) == 0:
                        logger.debug(f"[Role] no role found for tag {tag} ")
                        del self.tags[tag]

            if len(self.roles) == 0:
                raise Exception("no role found")
            self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
            self.roleplays = {}
            logger.debug("[Role] inited")
        except Exception as e:
            if isinstance(e, FileNotFoundError):
                logger.warn(f"[Role] init failed, {config_path} not found, ignore or see https://github.com/zhayujie/chatgpt-on-wechat/tree/master/plugins/role .")
            else:
                logger.warn("[Role] init failed, ignore or see https://github.com/zhayujie/chatgpt-on-wechat/tree/master/plugins/role .")
            raise e

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
        if btype not in [const.OPEN_AI, const.OPENAI, const.CHATGPT, const.CHATGPTONAZURE, const.QWEN_DASHSCOPE, const.XUNFEI, const.BAIDU, const.QIANFAN, const.ZHIPU_AI, const.MOONSHOT, const.MiniMax, const.LINKAI, const.MODELSCOPE]:
            logger.debug(f'不支持的bot: {btype}')
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
                    help_text = f"未知角色类型。\n"
                    help_text += "目前的角色类型有: \n"
                    help_text += "，".join([self.tags[tag][0] for tag in self.tags]) + "\n"
            else:
                help_text = f"请输入角色类型。\n"
                help_text += "目前的角色类型有: \n"
                help_text += "，".join([self.tags[tag][0] for tag in self.tags]) + "\n"
            reply = Reply(ReplyType.INFO, help_text)
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS
            return
        elif sessionid not in self.roleplays:
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
        elif customize == True:
            self.roleplays[sessionid] = RolePlay(bot, sessionid, clist[1], "%s")
            reply = Reply(ReplyType.INFO, f"角色设定为:\n{clist[1]}")
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS
        else:
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
        help_text = f"使用方法:\n{trigger_prefix}角色" + " 预设角色名: 设定角色为{预设角色名}。\n" + f"{trigger_prefix}role" + " 预设角色名: 同上，但使用英文设定。\n"
        help_text += f"{trigger_prefix}设定扮演" + " 角色设定: 设定自定义角色人设为{角色设定}。\n"
        help_text += f"{trigger_prefix}停止扮演: 清除设定的角色。\n"
        help_text += f"{trigger_prefix}角色类型" + " 角色类型: 查看某类{角色类型}的所有预设角色，为所有时输出所有预设角色。\n"
        help_text += "\n目前的角色类型有: \n"
        help_text += "，".join([self.tags[tag][0] for tag in self.tags]) + "。\n"
        help_text += f"\n命令例子: \n{trigger_prefix}角色 写作助理\n"
        help_text += f"{trigger_prefix}角色类型 所有\n"
        help_text += f"{trigger_prefix}停止扮演\n"
        return help_text
