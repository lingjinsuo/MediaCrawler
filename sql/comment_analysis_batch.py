# -*- coding: utf-8 -*-
"""
评论购买意图分析跑批脚本
支持：小红书(xhs)、抖音(dy)、快手(ks)
9-20点每小时执行一次

使用方法:
    python sql/comment_analysis_batch.py                    # 跑所有平台
    python sql/comment_analysis_batch.py --platform xhs    # 只跑小红书
"""

import asyncio
import argparse
import time
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy import select, update, text
from sqlalchemy.ext.asyncio import AsyncSession

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db_session import get_session, get_async_engine
from tools.llm_client import analyze_comment_purchase_intent
import config


# 平台配置
PLATFORM_CONFIG = {
    "xhs": {
        "name": "小红书",
        "comment_table": "xhs_note_comment",
        "note_table": "xhs_note",
        "note_id_field": "note_id",
        "note_url_field": "note_url",
        "platform": "xhs"
    },
    "dy": {
        "name": "抖音",
        "comment_table": "douyin_aweme_comment",
        "note_table": "douyin_aweme",
        "note_id_field": "aweme_id",
        "note_url_field": "aweme_url",
        "platform": "dy"
    },
    "ks": {
        "name": "快手",
        "comment_table": "kuaishou_video_comment",
        "note_table": "kuaishou_video",
        "note_id_field": "video_id",
        "note_url_field": "video_url",
        "platform": "ks"
    }
}


class CommentAnalysisBatch:
    """评论分析跑批"""
    
    def __init__(self, db_type: str = None):
        self.db_type = db_type or config.SAVE_DATA_OPTION
        self.engine = get_async_engine(self.db_type)
    
    async def run(self, platform: Optional[str] = None):
        """
        执行跑批
        
        Args:
            platform: 指定平台，如 None 则跑所有平台
        """
        print(f"[{datetime.now()}] === 评论分析跑批开始 ===")
        
        platforms = [platform] if platform else list(PLATFORM_CONFIG.keys())
        
        for p in platforms:
            if p not in PLATFORM_CONFIG:
                print(f"[{p}] 未知平台: {p}")
                continue
            
            try:
                await self.process_platform(p)
            except Exception as e:
                print(f"[{p}] 处理失败: {e}")
        
        print(f"[{datetime.now()}] === 评论分析跑批完成 ===")
    
    async def process_platform(self, platform: str):
        """处理单个平台"""
        cfg = PLATFORM_CONFIG[platform]
        print(f"\n[{cfg['name']}] 开始处理...")
        
        async with get_session() as session:
            # 1. 查询未分析的评论
            comments = await self._get_unanalyzed_comments(session, cfg)
            
            if not comments:
                print(f"[{cfg['name']}] 没有未分析的评论")
                return
            
            print(f"[{cfg['name']}] 找到 {len(comments)} 条未分析评论")
            
            # 2. 逐条分析
            for idx, comment in enumerate(comments):
                try:
                    await self._process_comment(session, comment, cfg)
                    print(f"[{cfg['name']}] [{idx+1}/{len(comments)}] 分析完成")
                except Exception as e:
                    print(f"[{cfg['name']}] [{idx+1}/{len(comments)}] 分析失败: {e}")
                
                # 避免请求过快
                await asyncio.sleep(0.5)
            
            await session.commit()
    
    async def _get_unanalyzed_comments(self, session: AsyncSession, cfg: dict) -> List[Dict]:
        """获取未分析的评论"""
        note_id_field = cfg['note_id_field']
        note_url_field = cfg.get('note_url_field', 'note_url')
        
        query = text(f"""
            SELECT 
                cmt.id as cmt_id,
                cmt.comment_id as comment_id,
                cmt.content as comment_content,
                cmt.nickname as comment_nickname,
                cmt.create_time as comment_time,
                cmt.{note_id_field} as note_id,
                xn.title as note_title,
                xn.{note_url_field} as note_url,
                xn.nickname as note_nickname
            FROM {cfg['comment_table']} cmt
            LEFT JOIN {cfg['note_table']} xn ON cmt.{note_id_field} = xn.{cfg['note_id_field']}
            WHERE cmt.analysis_status = 0
            LIMIT 10
        """)
        
        result = await session.execute(query)
        rows = result.fetchall()
        
        comments = []
        for row in rows:
            comments.append({
                "cmt_id": row[0],
                "comment_id": row[1],
                "comment_content": row[2],
                "comment_nickname": row[3],
                "comment_time": row[4],
                "note_id": row[5],
                "note_title": row[6] if len(row) > 6 else None,
                "note_url": row[7] if len(row) > 7 else None,
                "note_nickname": row[8] if len(row) > 8 else None,
            })
        
        return comments
    
    async def _process_comment(self, session: AsyncSession, comment: dict, cfg: dict):
        """处理单条评论"""
        comment_id = comment["cmt_id"]
        content = comment["comment_content"]
        
        # 调用LLM分析
        has_intent, reason = await analyze_comment_purchase_intent(content)
        
        # 显示评论摘要（前30字）
        content_preview = content[:30].replace("\n", " ") if content else ""
        if has_intent:
            # 有购买意图：更新状态为2，并写入推送表
            await self._update_comment_status(session, comment_id, 2, cfg)
            await self._insert_push_record(session, comment, cfg)
            print(f"  -> 有购买意图: {reason}。评论内容：{content_preview}")
        else:
            # 无购买意图：更新状态为1
            await self._update_comment_status(session, comment_id, 1, cfg)
            print(f"  -> 无购买意图: {reason}。评论内容：{content_preview}")
    
    async def _update_comment_status(self, session: AsyncSession, comment_id: int, status: int, cfg: dict):
        """更新评论状态"""
        query = text(f"""
            UPDATE {cfg['comment_table']}
            SET analysis_status = :status,
                analysis_time = NOW()
            WHERE id = :id AND analysis_status = 0
        """)
        await session.execute(query, {"status": status, "id": comment_id})
    
    async def _insert_push_record(self, session: AsyncSession, comment: dict, cfg: dict):
        """写入推送表"""
        query = text("""
            INSERT INTO comment_push (
                platform, note_title, note_url, note_nickname,
                comment_id, comment_content, comment_nickname, comment_time,
                original_comment_id, push_status, create_time, analysis_time
            ) VALUES (
                :platform, :note_title, :note_url, :note_nickname,
                :comment_id, :comment_content, :comment_nickname, :comment_time,
                :original_comment_id, 0, UNIX_TIMESTAMP(NOW()) * 1000, NOW()
            )
        """)
        
        await session.execute(query, {
            "platform": cfg["platform"],
            "note_title": comment.get("note_title"),
            "note_url": comment.get("note_url"),
            "note_nickname": comment.get("note_nickname"),
            "comment_id": comment.get("comment_id"),
            "comment_content": comment.get("comment_content"),
            "comment_nickname": comment.get("comment_nickname"),
            "comment_time": comment.get("comment_time"),
            "original_comment_id": comment.get("cmt_id"),
        })


async def run_scheduler():
    """运行调度器 - 9-20点每小时执行"""
    batch = CommentAnalysisBatch()
    
    while True:
        now = datetime.now()
        hour = now.hour
        
        # 检查是否在9-20点之间
        if 9 <= hour < 20:
            print(f"[调度器] 当前时间 {hour}:00，执行跑批")
            await batch.run()
        else:
            print(f"[调度器] 当前时间 {hour}:00，跳过执行")
        
        # 等待1小时
        await asyncio.sleep(3600)


def main():
    parser = argparse.ArgumentParser(description="评论购买意图分析跑批")
    parser.add_argument("--platform", "-p", choices=["xhs", "dy", "ks"], 
                        help="指定平台: xhs-小红书, dy-抖音, ks-快手")
    parser.add_argument("--schedule", "-s", action="store_true",
                        help="启用调度模式 (9-20点每小时执行)")
    
    args = parser.parse_args()
    
    if args.schedule:
        # 调度模式
        print("启动调度模式 (9-20点每小时执行)")
        asyncio.run(run_scheduler())
    else:
        # 单次执行
        asyncio.run(CommentAnalysisBatch().run(args.platform))


if __name__ == "__main__":
    main()
