import json
from fastmcp import FastMCP
from tools import scraper

# MCP 서버 초기화 (카카오 정책 준수)
mcp = FastMCP("Marathon Info Agent")


@mcp.tool()
def search_marathon_schedule(month: int = None, region: str = None):
    """
    전마협에서 가져오는 함수인데 여길 알아서 채우길...
    """
    result = scraper.
    return result


@mcp.tool()
def get_marathon_details(race_id: str):
    """
    상세 정보를 가져오는 함수인데 이것도 맞춰서 하면됨
    """
    result = 
    return result


if __name__ == "__main__":
    mcp.run()