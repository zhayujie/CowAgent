# encoding:utf-8

import os
import signal
import sys
import time

from channel import channel_factory
from common import const
from common.log import logger
from config import load_config, conf
from plugins import *
import threading


_channel_mgr = None

# Desktop mode: a lighter runtime for the packaged Electron client. Plugins are
# loaded in a background thread (so command plugins like cow_cli/godcmd work
# without slowing startup), while MCP warmup is still skipped to keep it fast.
DESKTOP_MODE = os.environ.get("COW_DESKTOP") == "1"


def get_channel_manager():
    return _channel_mgr


def _parse_channel_type(raw) -> list:
    """
    Parse channel_type config value into a list of channel names.
    Supports:
      - single string: "feishu"
      - comma-separated string: "feishu, dingtalk"
      - list: ["feishu", "dingtalk"]
    """
    if isinstance(raw, list):
        return [ch.strip() for ch in raw if ch.strip()]
    if isinstance(raw, str):
        return [ch.strip() for ch in raw.split(",") if ch.strip()]
    return []


class ChannelManager:
    """
    Manage the lifecycle of multiple channels running concurrently.
    Each channel.startup() runs in its own daemon thread.
    The web channel is started as default console unless explicitly disabled.
    """

    def __init__(self):
        self._channels = {}        # channel_name -> channel instance
        self._threads = {}         # channel_name -> thread
        self._primary_channel = None
        self._lock = threading.Lock()
        self.cloud_mode = False    # set to True when cloud client is active

    @property
    def channel(self):
        """Return the primary (first non-web) channel for backward compatibility."""
        return self._primary_channel

    def get_channel(self, channel_name: str):
        return self._channels.get(channel_name)

    def start(self, channel_names: list, first_start: bool = False):
        """
        Create and start one or more channels in sub-threads.
        If first_start is True, plugins and linkai client will also be initialized.
        """
        with self._lock:
            channels = []
            for name in channel_names:
                ch = channel_factory.create_channel(name)
                ch.cloud_mode = self.cloud_mode
                self._channels[name] = ch
                channels.append((name, ch))
                if self._primary_channel is None and name != "web":
                    self._primary_channel = ch

            if self._primary_channel is None and channels:
                self._primary_channel = channels[0][1]

            if first_start:
                if DESKTOP_MODE:
                    # Load plugins in the background so command plugins
                    # (cow_cli / godcmd, e.g. /status, #help) work in the
                    # desktop client, without blocking web-service readiness.
                    threading.Thread(
                        target=PluginManager().load_plugins, daemon=True
                    ).start()
                else:
                    PluginManager().load_plugins()

                # Cloud client is optional. It is only started when
                # use_linkai=True AND cloud_deployment_id is set.
                # By default neither is configured, so the app runs
                # entirely locally without any remote connection.
                if conf().get("use_linkai") and (
                    os.environ.get("CLOUD_DEPLOYMENT_ID") or conf().get("cloud_deployment_id")
                ):
                    try:
                        from common import cloud_client
                        threading.Thread(
                            target=cloud_client.start,
                            args=(self._primary_channel, self),
                            daemon=True,
                        ).start()
                    except Exception:
                        pass

            # Start web console first so its logs print cleanly,
            # then start remaining channels after a brief pause.
            web_entry = None
            other_entries = []
            for entry in channels:
                if entry[0] == "web":
                    web_entry = entry
                else:
                    other_entries.append(entry)

            ordered = ([web_entry] if web_entry else []) + other_entries
            for i, (name, ch) in enumerate(ordered):
                if i > 0 and name != "web":
                    time.sleep(0.1)
                t = threading.Thread(target=self._run_channel, args=(name, ch), daemon=True)
                self._threads[name] = t
                t.start()
                logger.debug(f"[ChannelManager] Channel '{name}' started in sub-thread")

    def _run_channel(self, name: str, channel):
        try:
            channel.startup()
        except Exception as e:
            logger.error(f"[ChannelManager] Channel '{name}' startup error: {e}")
            logger.exception(e)

    def stop(self, channel_name: str = None):
        """
        Stop channel(s). If channel_name is given, stop only that channel;
        otherwise stop all channels.
        """
        # Pop under lock, then stop outside lock to avoid deadlock
        with self._lock:
            names = [channel_name] if channel_name else list(self._channels.keys())
            to_stop = []
            for name in names:
                ch = self._channels.pop(name, None)
                th = self._threads.pop(name, None)
                to_stop.append((name, ch, th))
            if channel_name and self._primary_channel is self._channels.get(channel_name):
                self._primary_channel = None

        for name, ch, th in to_stop:
            if ch is None:
                logger.warning(f"[ChannelManager] Channel '{name}' not found in managed channels")
                if th and th.is_alive():
                    self._interrupt_thread(th, name)
                continue
            logger.info(f"[ChannelManager] Stopping channel '{name}'...")
            graceful = False
            if hasattr(ch, 'stop'):
                try:
                    ch.stop()
                    graceful = True
                except Exception as e:
                    logger.warning(f"[ChannelManager] Error during channel '{name}' stop: {e}")
            if th and th.is_alive():
                th.join(timeout=5)
                if th.is_alive():
                    if graceful:
                        logger.info(f"[ChannelManager] Channel '{name}' thread still alive after stop(), "
                                    "leaving daemon thread to finish on its own")
                    else:
                        logger.warning(f"[ChannelManager] Channel '{name}' thread did not exit in 5s, forcing interrupt")
                        self._interrupt_thread(th, name)

    @staticmethod
    def _interrupt_thread(th: threading.Thread, name: str):
        """Raise SystemExit in target thread to break blocking loops like start_forever."""
        import ctypes
        try:
            tid = th.ident
            if tid is None:
                return
            res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
                ctypes.c_ulong(tid), ctypes.py_object(SystemExit)
            )
            if res == 1:
                logger.info(f"[ChannelManager] Interrupted thread for channel '{name}'")
            elif res > 1:
                ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(tid), None)
                logger.warning(f"[ChannelManager] Failed to interrupt thread for channel '{name}'")
        except Exception as e:
            logger.warning(f"[ChannelManager] Thread interrupt error for '{name}': {e}")

    def restart(self, new_channel_name: str):
        """
        Restart a single channel with a new channel type.
        Can be called from any thread (e.g. linkai config callback).
        """
        logger.info(f"[ChannelManager] Restarting channel to '{new_channel_name}'...")
        self.stop(new_channel_name)
        _clear_singleton_cache(new_channel_name)
        time.sleep(1)
        self.start([new_channel_name], first_start=False)
        logger.info(f"[ChannelManager] Channel restarted to '{new_channel_name}' successfully")

    def add_channel(self, channel_name: str):
        """
        Dynamically add and start a new channel.
        If the channel is already running, restart it instead.
        """
        with self._lock:
            if channel_name in self._channels:
                logger.info(f"[ChannelManager] Channel '{channel_name}' already exists, restarting")
        if self._channels.get(channel_name):
            self.restart(channel_name)
            return
        logger.info(f"[ChannelManager] Adding channel '{channel_name}'...")
        _clear_singleton_cache(channel_name)
        self.start([channel_name], first_start=False)
        logger.info(f"[ChannelManager] Channel '{channel_name}' added successfully")

    def remove_channel(self, channel_name: str):
        """
        Dynamically stop and remove a running channel.
        """
        with self._lock:
            if channel_name not in self._channels:
                logger.warning(f"[ChannelManager] Channel '{channel_name}' not found, nothing to remove")
                return
        logger.info(f"[ChannelManager] Removing channel '{channel_name}'...")
        self.stop(channel_name)
        logger.info(f"[ChannelManager] Channel '{channel_name}' removed successfully")


def _clear_singleton_cache(channel_name: str):
    """
    Clear the singleton cache for the channel class so that
    a new instance can be created with updated config.
    """
    cls_map = {
        "web": "channel.web.web_channel.WebChannel",
        "wechatmp": "channel.wechatmp.wechatmp_channel.WechatMPChannel",
        "wechatmp_service": "channel.wechatmp.wechatmp_channel.WechatMPChannel",
        "wechatcom_app": "channel.wechatcom.wechatcomapp_channel.WechatComAppChannel",
        const.WECHAT_KF: "channel.wechat_kf.wechat_kf_channel.WechatKfChannel",
        const.FEISHU: "channel.feishu.feishu_channel.FeiShuChanel",
        const.DINGTALK: "channel.dingtalk.dingtalk_channel.DingTalkChanel",
        const.WECOM_BOT: "channel.wecom_bot.wecom_bot_channel.WecomBotChannel",
        const.QQ: "channel.qq.qq_channel.QQChannel",
        const.TELEGRAM: "channel.telegram.telegram_channel.TelegramChannel",
        const.SLACK: "channel.slack.slack_channel.SlackChannel",
        const.DISCORD: "channel.discord.discord_channel.DiscordChannel",
        const.WEIXIN: "channel.weixin.weixin_channel.WeixinChannel",
        "wx": "channel.weixin.weixin_channel.WeixinChannel",
    }
    module_path = cls_map.get(channel_name)
    if not module_path:
        return
    try:
        parts = module_path.rsplit(".", 1)
        module_name, class_name = parts[0], parts[1]
        import importlib
        module = importlib.import_module(module_name)
        wrapper = getattr(module, class_name, None)
        if wrapper and hasattr(wrapper, '__closure__') and wrapper.__closure__:
            for cell in wrapper.__closure__:
                try:
                    cell_contents = cell.cell_contents
                    if isinstance(cell_contents, dict):
                        cell_contents.clear()
                        logger.debug(f"[ChannelManager] Cleared singleton cache for {class_name}")
                        break
                except ValueError:
                    pass
    except Exception as e:
        logger.warning(f"[ChannelManager] Failed to clear singleton cache: {e}")


def sigterm_handler_wrap(_signo):
    old_handler = signal.getsignal(_signo)

    def func(_signo, _stack_frame):
        logger.info("signal {} received, exiting...".format(_signo))
        conf().save_user_datas()
        if callable(old_handler):  #  check old_handler
            return old_handler(_signo, _stack_frame)
        sys.exit(0)

    signal.signal(_signo, func)


def _warmup_mcp_tools():
    """
    Kick off MCP server loading at process startup so subprocesses
    (npx / uvx etc.) finish initializing before the first user message
    arrives. Returns immediately — the actual work happens on a daemon
    thread inside ToolManager. Safe to call when MCP is not configured.
    """
    try:
        from agent.tools import ToolManager
        ToolManager()._load_mcp_tools()
    except Exception as e:
        logger.warning(f"[App] MCP warmup failed (non-fatal): {e}")


def _warmup_scheduler():
    """Eager-init AgentBridge so the scheduler thread starts at process
    boot rather than waiting for the first user message."""
    try:
        from bridge.bridge import Bridge
        Bridge().get_agent_bridge()
    except Exception as e:
        logger.warning(f"[App] Scheduler warmup failed: {e}")


def _sync_builtin_skills():
    """Sync builtin skills from project skills/ to workspace skills/ on startup."""
    import shutil
    try:
        workspace = conf().get("agent_workspace", "~/cow")
        workspace = os.path.expanduser(workspace)
        project_root = os.path.dirname(os.path.abspath(__file__))
        builtin_dir = os.path.join(project_root, "skills")
        custom_dir = os.path.join(workspace, "skills")

        if not os.path.isdir(builtin_dir):
            return

        os.makedirs(custom_dir, exist_ok=True)
        synced = 0
        for name in os.listdir(builtin_dir):
            src = os.path.join(builtin_dir, name)
            if not os.path.isdir(src) or not os.path.isfile(os.path.join(src, "SKILL.md")):
                continue
            dst = os.path.join(custom_dir, name)
            try:
                if os.path.isdir(dst):
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
                synced += 1
            except Exception as e:
                logger.warning(f"[App] Failed to sync builtin skill '{name}': {e}")
        if synced:
            logger.info(f"[App] Synced {synced} builtin skill(s) to workspace")
    except Exception as e:
        logger.warning(f"[App] Builtin skills sync failed: {e}")


def _start_purification_scheduler():
    """Start a background thread that periodically runs skill purification.
    
    Runs every 24 hours (configurable) to:
    1. Auto-disable skills unused for 90+ days
    2. Clean up old tracking files and backups
    3. Log purification results
    
    This is a lightweight daemon thread — failures are isolated and never
    disrupt the main application.
    """
    def _purification_loop():
        import time as _time
        from pathlib import Path
        
        # Initial delay: wait 5 minutes after startup before first run
        _time.sleep(300)
        
        while True:
            try:
                from bridge.bridge import Bridge
                bridge = Bridge()
                agent_bridge = bridge.get_agent_bridge()
                
                if not agent_bridge or not hasattr(agent_bridge, 'default_agent'):
                    # Sleep for configured interval (default 24h)
                    interval_hours = conf().get("purification_cleanup_interval_hours", 24)
                    _time.sleep(interval_hours * 3600)
                    continue
                
                agent = agent_bridge.default_agent
                if not agent or not hasattr(agent, 'skill_manager') or not agent.skill_manager:
                    interval_hours = conf().get("purification_cleanup_interval_hours", 24)
                    _time.sleep(interval_hours * 3600)
                    continue
                
                # 1. Run cleanup: disable skills unused for 90+ days
                days_threshold = conf().get("purification_unused_days", 90)
                disabled = agent.skill_manager.cleanup_unused_skills(days_threshold)
                if disabled > 0:
                    logger.info(
                        f"[Purification] Auto-disabled {disabled} unused skill(s) "
                        f"(threshold: {days_threshold} days)"
                    )
                
                # 2. Run file cleanup: old tracking files and backups
                workspace_dir = getattr(agent, 'workspace_dir', None)
                if workspace_dir:
                    from agent.skills.purification import run_periodic_cleanup
                    # Pass skills_config to protect referenced backups
                    skills_config = agent.skill_manager.get_skills_config() if hasattr(agent.skill_manager, 'get_skills_config') else None
                    cleanup_stats = run_periodic_cleanup(Path(workspace_dir), skills_config=skills_config)
                    if cleanup_stats.get("tracking_files_deleted", 0) > 0 or cleanup_stats.get("backups_deleted", 0) > 0:
                        logger.info(
                            f"[Purification] File cleanup: "
                            f"{cleanup_stats.get('tracking_files_deleted', 0)} tracking files, "
                            f"{cleanup_stats.get('backups_deleted', 0)} backups deleted"
                        )
                
                # 3. Log quality report if available
                if workspace_dir:
                    report = agent.skill_manager.get_quality_report(workspace_dir, days=30)
                    if report.get("total_evolutions", 0) > 0:
                        logger.info(
                            f"[Purification] Quality report (30d): "
                            f"evolutions={report['total_evolutions']}, "
                            f"success_rate={report['success_rate']:.1%}, "
                            f"patches={report['skill_patches']}, "
                            f"creates={report['skill_creates']}, "
                            f"undos={report['undo_count']}, "
                            f"retries={report['retry_count']}"
                        )
                
            except Exception as e:
                logger.debug(f"[Purification] Scheduled run failed (non-fatal): {e}")
            
            # Sleep for configured interval (default 24h)
            interval_hours = conf().get("purification_cleanup_interval_hours", 24)
            _time.sleep(interval_hours * 3600)
    
    t = threading.Thread(
        target=_purification_loop, daemon=True, name="purification-scheduler"
    )
    t.start()
    logger.info("[Purification] Background scheduler started (cleanup + quality monitoring)")


def run():
    global _channel_mgr
    try:
        # load config
        load_config()
        # ctrl + c
        sigterm_handler_wrap(signal.SIGINT)
        # kill signal
        sigterm_handler_wrap(signal.SIGTERM)

        # Parse channel_type into a list
        raw_channel = conf().get("channel_type", "web")

        if "--cmd" in sys.argv:
            channel_names = ["terminal"]
        else:
            channel_names = _parse_channel_type(raw_channel)
            if not channel_names:
                channel_names = ["web"]

        # Auto-start web console unless explicitly disabled
        web_console_enabled = conf().get("web_console", True)
        if web_console_enabled and "web" not in channel_names:
            channel_names.append("web")

        # Sync builtin skills to workspace before channels start
        _sync_builtin_skills()

        # Kick off MCP server loading in the background so first-message
        # latency isn't dominated by npx package downloads. Skipped in desktop
        # mode (MCP relies on external npx/uvx runtimes that aren't bundled).
        if not DESKTOP_MODE:
            _warmup_mcp_tools()

        if DESKTOP_MODE:
            # Defer the (heavy) AgentBridge/scheduler warmup to a background
            # thread so the web API becomes available within a couple seconds.
            # The scheduler still starts; it just doesn't block UI readiness.
            threading.Thread(target=_warmup_scheduler, daemon=True).start()
        else:
            _warmup_scheduler()

        # Start skill purification scheduler (runs every 24h)
        if conf().get("purification_enabled", True):
            _start_purification_scheduler()

        logger.info(f"[App] Starting channels: {channel_names}")

        _channel_mgr = ChannelManager()
        _channel_mgr.start(channel_names, first_start=True)

        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error("App startup failed!")
        logger.exception(e)


if __name__ == "__main__":
    run()
