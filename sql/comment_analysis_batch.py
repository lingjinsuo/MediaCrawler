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
import re
import time
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

from sqlalchemy import select, update, text
from sqlalchemy.ext.asyncio import AsyncSession

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db_session import get_session, get_async_engine
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


def normalize_timestamp_to_seconds(ts: Optional[int]) -> int:
    """将评论时间戳统一为秒。小红书等为毫秒，抖音等为秒。"""
    if not ts:
        return 0
    ts = int(ts)
    if ts >= 10**12:
        return ts // 1000
    return ts


def _split_keywords(raw: str) -> List[str]:
    """
    把 mc_setting.comment_key 的 content 字段拆成关键词列表。
    支持半角逗号、全角逗号、顿号、换行、分号作为分隔符；
    自动 trim、去前后引号、去空项、去重(大小写不敏感)。
    """
    if not raw:
        return []
    parts = re.split(r"[,，、\n;；]+", str(raw))
    keywords: List[str] = []
    seen = set()
    for p in parts:
        kw = p.strip().strip('"').strip("'").strip()
        if not kw:
            continue
        key = kw.lower()
        if key in seen:
            continue
        seen.add(key)
        keywords.append(kw)
    return keywords


def _match_keywords(content: Optional[str], keywords: List[str]) -> Optional[str]:
    """
    判断评论内容是否命中任一关键词(子串包含,大小写不敏感)。
    命中则返回第一个命中的关键词(原文大小写),否则返回 None。
    """
    if not content or not keywords:
        return None
    content_lower = str(content).lower()
    for kw in keywords:
        if kw and kw.lower() in content_lower:
            return kw
    return None


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
            # 0. 一次性加载关键词(避免每条评论都查一次 mc_setting)
            keywords = await self._get_comment_keywords(session)
            if keywords:
                print(f"[{cfg['name']}] 已加载 comment_key 关键词 {len(keywords)} 个: {keywords}")
            else:
                print(f"[{cfg['name']}] [WARNING] mc_setting.comment_key 未配置,所有评论将标记为无意图")

            # 1. 查询未分析的评论
            comments = await self._get_unanalyzed_comments(session, cfg)

            if not comments:
                print(f"[{cfg['name']}] 没有未分析的评论")
                return

            print(f"[{cfg['name']}] 找到 {len(comments)} 条未分析评论")

            # 2. 逐条分析
            for idx, comment in enumerate(comments):
                try:
                    has_intent, reason = await self._process_comment_with_keywords(
                        session, comment, cfg, keywords
                    )
                    content_preview = (comment.get("comment_content") or "")[:30].replace("\n", " ")
                    if has_intent:
                        print(f"[{cfg['name']}] [{idx+1}/{len(comments)}] 分析 -> 有购买意图。评论内容:{content_preview}")
                    else:
                        print(f"[{cfg['name']}] [{idx+1}/{len(comments)}] 分析 -> {reason}。评论内容:{content_preview}")
                except Exception as e:
                    content_preview = (comment.get("comment_content") or "")[:30].replace("\n", " ")
                    print(f"[{cfg['name']}] [{idx+1}/{len(comments)}] 分析 -> 失败: {e}。评论内容:{content_preview}")

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
            LIMIT 500
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
    
    async def _get_comment_keywords(self, session: AsyncSession) -> List[str]:
        """
        从 mc_setting 表读取 key='comment_key' 的 content 字段,
        拆分为关键词数组。若记录不存在、content 为空或读取失败,返回空列表
        (等价于"未配置 → 不启用关键词过滤")。
        """
        try:
            sql = text("SELECT content FROM mc_setting WHERE `key` = :k LIMIT 1")
            result = await session.execute(sql, {"k": "comment_key"})
            row = result.fetchone()
            if not row or row[0] is None:
                return []
            return _split_keywords(row[0])
        except Exception as e:
            print(f"[mc_setting] 读取 comment_key 失败: {e}")
            return []

    async def _process_comment(self, session: AsyncSession, comment: dict, cfg: dict) -> Tuple[bool, str]:
        """
        兼容旧签名的入口:内部会重新读取一次 mc_setting.comment_key。
        推荐使用 _process_comment_with_keywords 以避免每条评论都查一次库。
        """
        keywords = await self._get_comment_keywords(session)
        return await self._process_comment_with_keywords(session, comment, cfg, keywords)

    async def _process_comment_with_keywords(
        self,
        session: AsyncSession,
        comment: dict,
        cfg: dict,
        keywords: List[str],
    ) -> Tuple[bool, str]:
        """处理单条评论(改用 mc_setting.comment_key 关键词命中,不再调用 LLM)"""
        comment_id = comment["cmt_id"]
        content = comment.get("comment_content") or ""
        comment_time_sec = normalize_timestamp_to_seconds(comment.get("comment_time", 0))

        # ① 3 天硬性过期:评论 > 3 天 → 不分析、不入库,直接标记 analysis_status=1
        three_days_ago = int(time.time()) - 3 * 24 * 60 * 60
        if comment_time_sec and comment_time_sec < three_days_ago:
            await self._update_comment_status(session, comment_id, 1, cfg)
            return False, "评论已超过3天，跳过入库"

        # ② 关键词命中判定(替代原 LLM 调用)
        hit_keyword = _match_keywords(content, keywords)

        if hit_keyword:
            # 有购买意图:更新状态为2,并写入推送表
            await self._update_comment_status(session, comment_id, 2, cfg)
            await self._insert_push_record(session, comment, cfg)
            return True, f"命中关键词: {hit_keyword}"

        # 无购买意图:更新状态为1
        await self._update_comment_status(session, comment_id, 1, cfg)
        if keywords:
            return False, "未命中关键词"
        return False, "未配置 comment_key,默认无意图"
    
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
        comment_time_sec = normalize_timestamp_to_seconds(comment.get("comment_time", 0))
        three_days_ago = int(time.time()) - 3 * 24 * 60 * 60
        
        # 评论时间已超过3天，标记为已处理
        push_status = 1 if comment_time_sec and comment_time_sec < three_days_ago else 0
        
        query = text("""
            INSERT INTO comment_push (
                platform, note_title, note_url, note_nickname,
                comment_id, comment_content, comment_nickname, comment_time,
                original_comment_id, push_status, create_time, analysis_time
            ) VALUES (
                :platform, :note_title, :note_url, :note_nickname,
                :comment_id, :comment_content, :comment_nickname, :comment_time,
                :original_comment_id, :push_status, UNIX_TIMESTAMP(NOW()) * 1000, NOW()
            )
        """)
        
        # 截取字段避免超过数据库字段长度
        note_title = comment.get("note_title")
        if note_title and len(note_title) > 500:
            note_title = note_title[:500]
        
        await session.execute(query, {
            "platform": cfg["platform"],
            "note_title": note_title,
            "note_url": comment.get("note_url"),
            "note_nickname": comment.get("note_nickname"),
            "comment_id": comment.get("comment_id"),
            "comment_content": comment.get("comment_content"),
            "comment_nickname": comment.get("comment_nickname"),
            "comment_time": comment_time_sec,
            "original_comment_id": comment.get("cmt_id"),
            "push_status": push_status,
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
