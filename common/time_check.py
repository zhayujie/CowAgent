import re
import time
import config
from common.log import logger


def time_checker(f):
    def _time_checker(self, *args, **kwargs):
        _config = config.conf()
        chat_time_module = _config.get("chat_time_module", False)

        if chat_time_module:
            chat_start_time = _config.get("chat_start_time", "00:00")
            chat_stop_time = _config.get("chat_stop_time", "24:00")

            time_regex = re.compile(r"^([01]?[0-9]|2[0-3]):[0-5][0-9]$")

            if not (
                time_regex.match(chat_start_time)
                and (time_regex.match(chat_stop_time) or chat_stop_time == "24:00")
            ):
                logger.warning("时间格式不正确，请在config.json中修改CHAT_START_TIME/CHAT_STOP_TIME。")
                return None

            def _to_minutes(value):
                hours, minutes = (int(part) for part in value.split(":"))
                return hours * 60 + minutes

            now_time = _to_minutes(time.strftime("%H:%M"))
            chat_start_time = _to_minutes(chat_start_time)
            chat_stop_time = (
                24 * 60 if chat_stop_time == "24:00" else _to_minutes(chat_stop_time)
            )
            # 结束时间小于开始时间，跨天了
            if chat_stop_time < chat_start_time and (chat_start_time <= now_time or now_time <= chat_stop_time):
                f(self, *args, **kwargs)
            # 结束大于开始时间代表，没有跨天
            elif chat_start_time < chat_stop_time and chat_start_time <= now_time <= chat_stop_time:
                f(self, *args, **kwargs)
            else:
                # 定义匹配规则，如果以 #reconf 或者 #更新配置 结尾，非服务时间可以修改开始/结束时间并重载配置。
                # 重载配置是 godcmd 认的中文别名（ADMIN_COMMANDS["reconf"]["alias"]），
                # 和 #reconf 指的是同一件事，不该只认英文那一个。
                pattern = re.compile(r"^.*#(?:reconf|重载配置|更新配置)$")
                if args and pattern.match(args[0].content):
                    f(self, *args, **kwargs)
                else:
                    logger.info("非服务时间内，不接受访问")
                    return None
        else:
            f(self, *args, **kwargs)  # 未开启时间模块则直接回答

    return _time_checker
