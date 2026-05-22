import os
import yaml
from typing import Dict, List, Optional

from agentmesh import AgentTeam, Agent, LLMModel
from agentmesh.models import ClaudeModel
from agentmesh.tools import ToolManager
from config import conf

import plugins
from plugins import Plugin, Event, EventContext, EventAction
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger


@plugins.register(
    name="agent",
    desc="Use AgentMesh framework to process tasks with multi-agent teams",
    version="0.1.0",
    author="Saboteur7",
    desire_priority=1,
)
class AgentPlugin(Plugin):
    """Plugin for integrating AgentMesh framework."""
    
    def __init__(self):
        super().__init__()
        self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
        self.name = "agent"
        self.description = "Use AgentMesh framework to process tasks with multi-agent teams"
        self.config = self._load_config()
        self.tool_manager = ToolManager()
        self.tool_manager.load_tools(config_dict=self.config.get("tools"))
        logger.debug("[agent] inited")
    
    def _load_config(self) -> Dict:
        """Load configuration from config.yaml file."""
        config_path = os.path.join(self.path, "config.yaml")
        if not os.path.exists(config_path):
            logger.debug(f"Config file not found at {config_path}")
            return {}
            
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def get_help_text(self, verbose=False, **kwargs):
        """Return help message for the agent plugin."""
        help_text = "通过AgentMesh实现对终端、浏览器、文件系统、搜索引擎等工具的执行，并支持多智能体协作。"
        trigger_prefix = conf().get("plugin_trigger_prefix", "$")
        
        if not verbose:
            return help_text
            
        teams = self.get_available_teams()
        teams_str = ", ".join(teams) if teams else "未配置任何团队"
        
        help_text += "\n\n使用说明：\n"
        help_text += f"{trigger_prefix}agent [task] - 使用默认团队执行任务\n"
        help_text += f"{trigger_prefix}agent teams - 列出可用的团队\n"
        help_text += f"{trigger_prefix}agent use [team_name] [task] - 使用特定团队执行任务\n\n"
        help_text += f"可用团队: \n{teams_str}\n\n"
        help_text += f"示例:\n"
        help_text += f"{trigger_prefix}agent 帮我查看当前文件夹路径\n"
        help_text += f"{trigger_prefix}agent use software_team 帮我写一个产品预约体验的表单页面"
        return help_text
    
    def get_available_teams(self) -> List[str]:
        """Get list of available teams from configuration."""
        teams_config = self.config.get("teams", {})
        return list(teams_config.keys())


    def create_team_from_config(self, team_name: str) -> Optional[AgentTeam]:
        """Create a team from configuration."""
        # Get teams configuration
        teams_config = self.config.get("teams", {})

        # Check if the specified team exists
        if team_name not in teams_config:
            logger.error(f"Team '{team_name}' not found in configuration.")
            available_teams = list(teams_config.keys())
            logger.info(f"Available teams: {', '.join(available_teams)}")
            return None

        # Get team configuration
        team_config = teams_config[team_name]

        # Get team's model
        team_model_name = team_config.get("model", "gpt-4.1-mini")
        team_model = self.create_llm_model(team_model_name)

        # Get team's max_steps (default to 20 if not specified)
        team_max_steps = team_config.get("max_steps", 20)

        # Create team with the model
        team = AgentTeam(
            name=team_name,
            description=team_config.get("description", ""),
            rule=team_config.get("rule", ""),
            model=team_model,
            max_steps=team_max_steps
        )

        # Create and add agents to the team
        agents_config = team_config.get("agents", [])
        for agent_config in agents_config:
            # Check if agent has a specific model
            if agent_config.get("model"):
                agent_model = self.create_llm_model(agent_config.get("model"))
            else:
                agent_model = team_model

            # Get agent's max_steps
            agent_max_steps = agent_config.get("max_steps")

            agent = Agent(
                name=agent_config.get("name", ""),
                system_prompt=agent_config.get("system_prompt", ""),
                model=agent_model,  # Use agent's model if specified, otherwise will use team's model
                description=agent_config.get("description", ""),
                max_steps=agent_max_steps
            )

            # Add tools to the agent if specified
            tool_names = agent_config.get("tools", [])
            for tool_name in tool_names:
                tool = self.tool_manager.create_tool(tool_name)
                if tool:
                    agent.add_tool(tool)
                else:
                    if tool_name == "browser":
                        logger.warning(
                            "Tool 'Browser' loaded failed, "
                            "please install the required dependency with: \n"
                            "'pip install browser-use>=0.1.40' or 'pip install agentmesh-sdk[full]'\n"
                        )
                    else:
                        logger.warning(f"Tool '{tool_name}' not found for agent '{agent.name}'\n")

            # Add agent to team
            team.add(agent)

        return team
    
    def on_handle_context(self, e_context: EventContext):
        """Handle the message context."""
        if e_context['context'].type != ContextType.TEXT:
            return
        content = e_context['context'].content
        trigger_prefix = conf().get("plugin_trigger_prefix", "$")
        
        if not content.startswith(f"{trigger_prefix}agent "):
            e_context.action = EventAction.CONTINUE
            return

        if not self.config:
            reply = Reply()
            reply.type = ReplyType.ERROR
            reply.content = "未找到插件配置，请在 plugins/agent 目录下创建 config.yaml 配置文件，可根据 config-template.yml 模板文件复制"
            e_context['reply'] = reply
            e_context.action = EventAction.BREAK_PASS
            return

        # Extract the actual task
        task = content[len(f"{trigger_prefix}agent "):].strip()
        
        # If task is empty, return help message
        if not task:
            reply = Reply()
            reply.type = ReplyType.TEXT
            reply.content = self.get_help_text(verbose=True)
            e_context['reply'] = reply
            e_context.action = EventAction.BREAK_PASS
            return
            
        # Check if task is asking for available teams
        if task.lower() in ["teams", "list teams", "show teams"]:
            teams = self.get_available_teams()
            reply = Reply()
            reply.type = ReplyType.TEXT
            
            if not teams:
                reply.content = "未配置任何团队。请检查 config.yaml 文件。"
            else:
                reply.content = f"可用团队: {', '.join(teams)}"
                
            e_context['reply'] = reply
            e_context.action = EventAction.BREAK_PASS
            return
        
        # Check if task specifies a team
        team_name = None
        if task.startswith("use "):
            parts = task[4:].split(" ", 1)
            if len(parts) > 0:
                team_name = parts[0]
                if len(parts) > 1:
                    task = parts[1].strip()
                else:
                    reply = Reply()
                    reply.type = ReplyType.TEXT
                    reply.content = f"已选择团队 '{team_name}'。请输入您想执行的任务。"
                    e_context['reply'] = reply
                    e_context.action = EventAction.BREAK_PASS
                    return
        if not team_name:
            team_name = self.config.get("team")

        # If no team specified, use default or first available
        if not team_name:
            teams = self.configself.get_available_teams()
            if not teams:
                reply = Reply()
                reply.type = ReplyType.TEXT
                reply.content = "未配置任何团队。请检查 config.yaml 文件。"
                e_context['reply'] = reply
                e_context.action = EventAction.BREAK_PASS
                return
            team_name = teams[0]
            
        # Create team
        team = self.create_team_from_config(team_name)
        if not team:
            reply = Reply()
            reply.type = ReplyType.TEXT
            reply.content = f"创建团队 '{team_name}' 失败。请检查配置。"
            e_context['reply'] = reply
            e_context.action = EventAction.BREAK_PASS
            return
        
        # Run the task
        try:
            logger.info(f"[agent] Running task '{task}' with team '{team_name}', team_model={team.model.model}")
            result = team.run_async(task=task)
            for agent_result in result:
                res_text = f"🤖 {agent_result.get('agent_name')}\n\n{agent_result.get('final_answer')}"
                _send_text(e_context, content=res_text)
            
            reply = Reply()
            reply.type = ReplyType.TEXT
            reply.content = ""
            e_context['reply'] = reply
            e_context.action = EventAction.BREAK_PASS
            
        except Exception as e:
            logger.exception(f"Error running task with team '{team_name}'")
            
            reply = Reply()
            reply.type = ReplyType.ERROR
            reply.content = f"执行任务时出错: {str(e)}"
            e_context['reply'] = reply
            e_context.action = EventAction.BREAK_PASS
        return

    def create_llm_model(self, model_name) -> LLMModel:
        if conf().get("use_linkai"):
            api_base = "https://api.link-ai.tech/v1"
            api_key = conf().get("linkai_api_key")
        elif model_name.startswith(("gpt", "text-davinci", "o1", "o3")):
            api_base = conf().get("open_ai_api_base") or "https://api.openai.com/v1"
            api_key = conf().get("open_ai_api_key")
        elif model_name.startswith("claude"):
            return ClaudeModel(model=model_name, api_key=conf().get("claude_api_key"))
        elif model_name.startswith("moonshot"):
            api_base = "https://api.moonshot.cn/v1"
            api_key = conf().get("moonshot_api_key")
        elif model_name.startswith("qwen"):
            api_base = "https://dashscope.aliyuncs.com/compatible-mode/v1"
            api_key = conf().get("dashscope_api_key")
        else:
            api_base = conf().get("open_ai_api_base") or "https://api.openai.com/v1"
            api_key = conf().get("open_ai_api_key")

        llm_model = LLMModel(model=model_name, api_key=api_key, api_base=api_base)
        return llm_model


def _send_text(e_context: EventContext, content: str):
    reply = Reply(ReplyType.TEXT, content)
    channel = e_context["channel"]
    channel.send(reply, e_context["context"])
