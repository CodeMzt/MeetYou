import sys
import os

# 把项目的根目录（MeetYou）加到环境变量里，这样 Python 就能找到 tools 文件夹了
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 然后再从 tools 导入你自己写的代码
from tools.mcp import MCPClient
import asyncio

# 下面是你之前写的测试代码...
async def main():
    project_path = "e:/Documents/Project/MeetYou"
    
    print("正在连接 File System Server...")
    client = MCPClient(
        server_command="npx.cmd", 
        server_args=["-y", "@modelcontextprotocol/server-filesystem", project_path]
    )
    
    await client.init_mcp_session()
    print("连接成功！")
    
    await client.load_mcp_tools()
    
    print("\n获取到的工具 Schema 列表：")
    for tool in client.tools_schema:
        print(f"- 工具名: {tool['function']['name']}")
        print(f"  描述: {tool['function']['description']}")
        
    print("\n准备关闭连接...")
    await client.shutdown_mcp_session()

if __name__ == "__main__":
    asyncio.run(main())
