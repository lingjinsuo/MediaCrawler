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
                
                return self._parse_response(content)
                
        except Exception as e:
            raise
    
    def _build_prompt(self, comment_content: str) -> str:
        """构建分析提示词"""
        return f"""你是一个专业的电商评论分析师。请判断下面这条评论是否表达了购买或出售的意图（比如问价格、问在哪买、说想买/想卖、求链接等）。

评论：{comment_content}

请只回答"是"或"否"。"""
    
    def _parse_response(self, content: str) -> tuple[bool, str]:
        """解析LLM响应"""
        content = content.strip()
        
        
        # 提取最终答案（去推理过程）
        # LLM返回格式通常是: <think>推理过程</think>答案
        final_answer = content
        if "</think>" in content:
            parts = content.split("</think>")
            final_answer = parts[-1].strip() if len(parts) > 1 else content
        
        # 清理可能的引号
        final_answer = final_answer.strip('"\'。')
        
        
        # 检查最终答案
        has_yes = "是" in final_answer
        has_no = "否" in final_answer or final_answer == "不" or final_answer == "no" or final_answer == "No"
        
        
        if has_yes and not has_no:
            return True, "判断为有购买意图"
        elif has_no or final_answer in ["不", "no", "No"]:
            return False, "判断为无购买意图"
        elif not final_answer:
            # 空答案，默认无购买意图
            return True, "无法明确判断，默认无购买意图-空答案"
        else:
            # 其他情况，默认无购买意图
            return True, "无法明确判断，默认无购买意图-其他情况"


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
