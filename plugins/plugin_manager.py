# encoding:utf-8

import importlib
import importlib.util
import json
import os
import sys

from common.log import logger
from common.singleton import singleton
from common.sorted_dict import SortedDict
from config import conf, remove_plugin_config, write_plugin_config

from .event import *


@singleton
class PluginManager:
    def __init__(self):
        self.plugins = SortedDict(lambda k, v: v.priority, reverse=True)
        self.listening_plugins = {}
        self.instances = {}
        self.pconf = {}
        self.current_plugin_path = None
        self.loaded = {}

    def register(self, name: str, desire_priority: int = 0, **kwargs):
        def wrapper(plugincls):
            plugincls.name = name
            plugincls.priority = desire_priority
            plugincls.desc = kwargs.get("desc")
            plugincls.author = kwargs.get("author")
            plugincls.path = self.current_plugin_path
            plugincls.version = kwargs.get("version") if kwargs.get("version") != None else "1.0"
            plugincls.namecn = kwargs.get("namecn") if kwargs.get("namecn") != None else name
            plugincls.hidden = kwargs.get("hidden") if kwargs.get("hidden") != None else False
            # enabled 默认 True；示例性插件可在装饰器中显式传 enabled=False，
            # 首次启动写入 plugins.json 时即为关闭状态，避免拦截用户消息。
            plugincls.enabled = kwargs.get("enabled", True)
            if self.current_plugin_path == None:
                raise Exception("Plugin path not set")
            self.plugins[name.upper()] = plugincls
            logger.debug("Plugin %s_v%s registered, path=%s" % (name, plugincls.version, plugincls.path))

        return wrapper

    def save_config(self):
        with open("./plugins/plugins.json", "w", encoding="utf-8") as f:
            json.dump(self.pconf, f, indent=4, ensure_ascii=False)

    def load_config(self):
        logger.debug("Loading plugins config...")

        modified = False
        if os.path.exists("./plugins/plugins.json"):
            with open("./plugins/plugins.json", "r", encoding="utf-8") as f:
                pconf = json.load(f)
                pconf["plugins"] = SortedDict(lambda k, v: v["priority"], pconf["plugins"], reverse=True)
        else:
            modified = True
            pconf = {"plugins": SortedDict(lambda k, v: v["priority"], reverse=True)}
        self.pconf = pconf
        if modified:
            self.save_config()
        return pconf

    @staticmethod
    def _load_all_config():
        """
        背景: 目前插件配置存放于每个插件目录的config.json下，docker运行时不方便进行映射，故增加统一管理的入口，优先
        加载 plugins/config.json，原插件目录下的config.json 不受影响

        从 plugins/config.json 中加载所有插件的配置并写入 config.py 的全局配置中，供插件中使用
        插件实例中通过 config.pconf(plugin_name) 即可获取该插件的配置
        """
        all_config_path = "./plugins/config.json"
        try:
            if os.path.exists(all_config_path):
                # read from all plugins config
                with open(all_config_path, "r", encoding="utf-8") as f:
                    all_conf = json.load(f)
                    logger.info(f"load all config from plugins/config.json: {all_conf}")

                # write to global config
                write_plugin_config(all_conf)
        except Exception as e:
            logger.error(e)

    def scan_plugins(self):
        logger.debug("Scanning plugins ...")
        plugins_dir = "./plugins"
        raws = [self.plugins[name] for name in self.plugins]
        for plugin_name in os.listdir(plugins_dir):
            plugin_path = os.path.join(plugins_dir, plugin_name)
            if os.path.isdir(plugin_path):
                # 判断插件是否包含同名__init__.py文件
                main_module_path = os.path.join(plugin_path, "__init__.py")
                if os.path.isfile(main_module_path):
                    # 导入插件
                    import_path = "plugins.{}".format(plugin_name)
                    try:
                        self.current_plugin_path = plugin_path
                        if plugin_path in self.loaded:
                            if plugin_name.upper() != 'GODCMD':
                                logger.info("reload module %s" % plugin_name)
                                self.loaded[plugin_path] = importlib.reload(sys.modules[import_path])
                                dependent_module_names = [name for name in sys.modules.keys() if name.startswith(import_path + ".")]
                                for name in dependent_module_names:
                                    logger.info("reload module %s" % name)
                                    importlib.reload(sys.modules[name])
                        else:
                            self.loaded[plugin_path] = importlib.import_module(import_path)
                        self.current_plugin_path = None
                    except Exception as e:
                        logger.warn("Failed to import plugin %s: %s" % (plugin_name, e))
                        continue
        pconf = self.pconf
        news = [self.plugins[name] for name in self.plugins]
        new_plugins = list(set(news) - set(raws))
        modified = False
        for name, plugincls in self.plugins.items():
            rawname = plugincls.name
            if rawname not in pconf["plugins"]:
                modified = True
                logger.info("Plugin %s not found in pconfig, adding to pconfig..." % name)
                pconf["plugins"][rawname] = {
                    "enabled": plugincls.enabled,
                    "priority": plugincls.priority,
                }
            else:
                self.plugins[name].enabled = pconf["plugins"][rawname]["enabled"]
                self.plugins[name].priority = pconf["plugins"][rawname]["priority"]
                self.plugins._update_heap(name)  # 更新下plugins中的顺序
        if modified:
            self.save_config()
        return new_plugins

    def refresh_order(self):
        for event in self.listening_plugins.keys():
            self.listening_plugins[event].sort(key=lambda name: self.plugins[name].priority, reverse=True)

    def activate_plugins(self):  # 生成新开启的插件实例
        failed_plugins = []
        for name, plugincls in self.plugins.items():
            if plugincls.enabled:
                if 'GODCMD' in self.instances and name == 'GODCMD':
                    continue
                # if name not in self.instances:
                try:
                    instance = plugincls()
                except Exception as e:
                    logger.warn("Failed to init %s, diabled. %s" % (name, e))
                    self.disable_plugin(name)
                    failed_plugins.append(name)
                    continue
                if name in self.instances:
                    self.instances[name].handlers.clear()
                self.instances[name] = instance
                for event in instance.handlers:
                    if event not in self.listening_plugins:
                        self.listening_plugins[event] = []
                    self.listening_plugins[event].append(name)
        self.refresh_order()
        return failed_plugins

    def reload_plugin(self, name: str):
        name = name.upper()
        remove_plugin_config(name)
        if name in self.instances:
            for event in self.listening_plugins:
                if name in self.listening_plugins[event]:
                    self.listening_plugins[event].remove(name)
            if name in self.instances:
                self.instances[name].handlers.clear()
            del self.instances[name]
            self.activate_plugins()
            return True
        return False

    def load_plugins(self):
        self.load_config()
        self.scan_plugins()
        # 加载全量插件配置
        self._load_all_config()
        pconf = self.pconf
        logger.debug("plugins.json config={}".format(pconf))
        for name, plugin in pconf["plugins"].items():
            if name.upper() not in self.plugins:
                logger.error("Plugin %s not found, but found in plugins.json" % name)
        self.activate_plugins()

    def emit_event(self, e_context: EventContext, *args, **kwargs):
        if e_context.event in self.listening_plugins:
            for name in self.listening_plugins[e_context.event]:
                if self.plugins[name].enabled and e_context.action == EventAction.CONTINUE:
                    logger.debug("Plugin %s triggered by event %s" % (name, e_context.event))
                    instance = self.instances[name]
                    instance.handlers[e_context.event](e_context, *args, **kwargs)
                    if e_context.is_break():
                        e_context["breaked_by"] = name
                        logger.debug("Plugin %s breaked event %s" % (name, e_context.event))
        return e_context

    def set_plugin_priority(self, name: str, priority: int):
        name = name.upper()
        if name not in self.plugins:
            return False
        if self.plugins[name].priority == priority:
            return True
        self.plugins[name].priority = priority
        self.plugins._update_heap(name)
        rawname = self.plugins[name].name
        self.pconf["plugins"][rawname]["priority"] = priority
        self.pconf["plugins"]._update_heap(rawname)
        self.save_config()
        self.refresh_order()
        return True

    def enable_plugin(self, name: str):
        name = name.upper()
        if name not in self.plugins:
            return False, "插件不存在"
        if not self.plugins[name].enabled:
            self.plugins[name].enabled = True
            rawname = self.plugins[name].name
            self.pconf["plugins"][rawname]["enabled"] = True
            self.save_config()
            failed_plugins = self.activate_plugins()
            if name in failed_plugins:
                return False, "插件开启失败"
            return True, "插件已开启"
        return True, "插件已开启"

    def disable_plugin(self, name: str):
        name = name.upper()
        if name not in self.plugins:
            return False
        if self.plugins[name].enabled:
            self.plugins[name].enabled = False
            rawname = self.plugins[name].name
            self.pconf["plugins"][rawname]["enabled"] = False
            self.save_config()
            return True
        return True

    def list_plugins(self):
        return self.plugins

    def install_plugin(self, repo: str):
        try:
            import common.package_manager as pkgmgr

            pkgmgr.check_dulwich()
        except Exception as e:
            logger.error("Failed to install plugin, {}".format(e))
            return False, "无法导入dulwich，安装插件失败"
        import re

        from dulwich import porcelain

        logger.info("clone git repo: {}".format(repo))

        match = re.match(r"^(https?:\/\/|git@)([^\/:]+)[\/:]([^\/:]+)\/(.+).git$", repo)

        if not match:
            try:
                with open("./plugins/source.json", "r", encoding="utf-8") as f:
                    source = json.load(f)
                if repo in source["repo"]:
                    repo = source["repo"][repo]["url"]
                    match = re.match(r"^(https?:\/\/|git@)([^\/:]+)[\/:]([^\/:]+)\/(.+).git$", repo)
                    if not match:
                        return False, "安装插件失败，source中的仓库地址不合法"
                else:
                    return False, "安装插件失败，仓库地址不合法"
            except Exception as e:
                logger.error("Failed to install plugin, {}".format(e))
                return False, "安装插件失败，请检查仓库地址是否正确"
        dirname = os.path.join("./plugins", match.group(4))
        try:
            repo = porcelain.clone(repo, dirname, checkout=True)
            if os.path.exists(os.path.join(dirname, "requirements.txt")):
                logger.info("detect requirements.txt，installing...")
            pkgmgr.install_requirements(os.path.join(dirname, "requirements.txt"))
            return True, "安装插件成功，请使用 #scanp 命令扫描插件或重启程序，开启前请检查插件是否需要配置"
        except Exception as e:
            logger.error("Failed to install plugin, {}".format(e))
            return False, "安装插件失败，" + str(e)

    def update_plugin(self, name: str):
        try:
            import common.package_manager as pkgmgr

            pkgmgr.check_dulwich()
        except Exception as e:
            logger.error("Failed to install plugin, {}".format(e))
            return False, "无法导入dulwich，更新插件失败"
        from dulwich import porcelain

        name = name.upper()
        if name not in self.plugins:
            return False, "插件不存在"
        if name in [
            "HELLO",
            "GODCMD",
            "ROLE",
            "TOOL",
            "BDUNIT",
            "BANWORDS",
            "FINISH",
            "DUNGEON",
        ]:
            return False, "预置插件无法更新，请更新主程序仓库"
        dirname = self.plugins[name].path
        try:
            porcelain.pull(dirname, "origin")
            if os.path.exists(os.path.join(dirname, "requirements.txt")):
                logger.info("detect requirements.txt，installing...")
            pkgmgr.install_requirements(os.path.join(dirname, "requirements.txt"))
            return True, "更新插件成功，请重新运行程序"
        except Exception as e:
            logger.error("Failed to update plugin, {}".format(e))
            return False, "更新插件失败，" + str(e)

    def uninstall_plugin(self, name: str):
        name = name.upper()
        if name not in self.plugins:
            return False, "插件不存在"
        if name in self.instances:
            self.disable_plugin(name)
        dirname = self.plugins[name].path
        try:
            import shutil

            shutil.rmtree(dirname)
            rawname = self.plugins[name].name
            for event in self.listening_plugins:
                if name in self.listening_plugins[event]:
                    self.listening_plugins[event].remove(name)
            del self.plugins[name]
            del self.pconf["plugins"][rawname]
            self.loaded[dirname] = None
            self.save_config()
            return True, "卸载插件成功"
        except Exception as e:
            logger.error("Failed to uninstall plugin, {}".format(e))
            return False, "卸载插件失败，请手动删除文件夹完成卸载，" + str(e)
