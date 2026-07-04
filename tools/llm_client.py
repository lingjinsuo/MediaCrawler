# -*- coding: utf-8 -*-
"""
MiniMax LLM 客户端
用于判断评论是否具有购买意图
"""

import json
import httpx
import os
from typing import Optional
from pathlib import Path

# 加载 .env 文件
def load_env():
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())

load_env()


class MiniMaxClient:
    """MiniMax LLM 客户端"""
    
    def __init__(self, api_key: str, base_url: str = "https://api.minimaxi.com/v1/chat/completions"):
        self.api_key = api_key
        self.base_url = base_url
    
    async def analyze_purchase_intent(self, comment_content: str) -> tuple[bool, str]:
        """
        分析评论是否具有购买意图
        
        Args:
            comment_content: 评论内容
            
        Returns:
            tuple[bool, str]: (是否有购买意图, 分析理由)
        """
        prompt = self._build_prompt(comment_content)
        
        messages = [
            {"role": "user", "content": prompt}
        ]
        
        payload = {
            "model": "MiniMax-M2.7",
            "messages": messages,
            "max_tokens": 100,
            "temperature": 0.3
        }
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.base_url,
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                result = response.json()
                
                content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                
                print(f"[LLM Client] Raw response: {content}")
                return self._parse_response(content)
                
        except Exception as e:
            print(f"[LLM Client] Error: {e}")
            raise
    
    def _build_prompt(self, comment_content: str) -> str:
        """构建分析提示词"""
        return f"""请分析以下评论是否具有买卖/收售意图。

只要评论中涉及以下任何一种情况，都属于有买卖/收售意图：
1. 询问价格/多少钱/什么价
2. 询问在哪里买/在哪里卖/有链接吗/有购买渠道吗
3. 表达购买意向：想买/想入手/求购/要买
4. 表达出售意向：想卖/出售/出/卖
5. 表达收购/回收/收购
6. 问能不能买卖/能不能出

如果评论只是在夸赞、聊天、或者没有任何买卖意图，则回答"否"。

评论内容：
{comment_content}

请只回答 "是" 或 "否"，不要包含其他内容。"""
    
    def _parse_response(self, content: str) -> tuple[bool, str]:
        """解析LLM响应"""
        content = content.strip().upper()
        
        if "是" in content and "否" not in content:
            return True, "判断为有购买意图"
        elif "否" in content:
            return False, "判断为无购买意图"
        else:
            # 默认认为无购买意图，避免误推送
            return False, "无法明确判断，默认无购买意图"


# 全局客户端实例
_llm_client: Optional[MiniMaxClient] = None


def get_llm_client() -> MiniMaxClient:
    """获取 LLM 客户端实例"""
    global _llm_client
    
    if _llm_client is None:
        import os
        api_key = os.getenv("MINIMAX_API_KEY", "")
        if not api_key:
            raise ValueError("MINIMAX_API_KEY environment variable not set")
        
        base_url = os.getenv("MINIMAX_API_URL", "https://api.minimaxi.com/v1/chat/completions")
        _llm_client = MiniMaxClient(api_key=api_key, base_url=base_url)
    
    return _llm_client


async def analyze_comment_purchase_intent(comment_content: str) -> tuple[bool, str]:
    """
    分析评论购买意图的便捷函数
    
    Args:
        comment_content: 评论内容
        
    Returns:
        tuple[bool, str]: (是否有购买意图, 分析理由)
    """
    client = get_llm_client()
    return await client.analyze_purchase_intent(comment_content)
