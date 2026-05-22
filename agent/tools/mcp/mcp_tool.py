from agent.tools.base_tool import BaseTool, ToolResult
from common.log import logger


class McpTool(BaseTool):
    """
    将单个 MCP 工具包装为 BaseTool。
    一个 MCP Server 可以提供多个工具，每个工具对应一个 McpTool 实例。
    """

    def __init__(self, client, tool_schema: dict, server_name: str):
        """
        :param client: 该工具所属的 McpClient 实例
        :param tool_schema: MCP 返回的工具描述，格式：
            {"name": str, "description": str, "inputSchema": dict}
        :param server_name: Server 名称，用于日志
        """
        self.client = client
        self.server_name = server_name
        self.name = tool_schema["name"]
        self.description = tool_schema.get("description", "")
        self.params = tool_schema.get("inputSchema", {})

    def execute(self, params: dict) -> ToolResult:
        logger.info(f"[McpTool] server={self.server_name} tool={self.name} params={params}")
        try:
            result = self.client.call_tool(self.name, params)
            return ToolResult.success(result)
        except Exception as e:
            logger.error(f"[McpTool] server={self.server_name} tool={self.name} error: {e}")
            return ToolResult.fail(str(e))
