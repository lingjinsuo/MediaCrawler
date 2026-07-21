# -*- coding: utf-8 -*-
"""
评论推送 API
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_session import get_session
import config


router = APIRouter(prefix="/comment-push", tags=["comment-push"])


class CommentPushItem(BaseModel):
    """推送条目"""
    id: int
    platform: str
    platform_name: str
    note_title: Optional[str]
    note_url: Optional[str]
    note_nickname: Optional[str]
    comment_content: Optional[str]
    comment_nickname: Optional[str]
    comment_time: Optional[int]
    push_status: int
    process_content: Optional[str]
    process_time: Optional[datetime]
    create_time: Optional[int]
    analysis_time: Optional[datetime]


class CommentPushListResponse(BaseModel):
    """推送列表响应"""
    total: int
    items: List[CommentPushItem]


class CommentPushUpdateRequest(BaseModel):
    """更新推送状态请求"""
    id: int
    process_content: Optional[str] = None
    push_status: Optional[int] = None


# 平台名称映射
PLATFORM_NAMES = {
    "xhs": "小红书",
    "dy": "抖音",
    "ks": "快手"
}


@router.get("/list", response_model=CommentPushListResponse)
async def get_comment_push_list(
    platform: Optional[str] = None,
    push_status: Optional[int] = None,
    search: Optional[str] = None,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
    page: int = 1,
    page_size: int = 20
):
    """获取评论推送列表
    
    Args:
        platform: 平台筛选
        push_status: 推送状态筛选
        search: 搜索关键词（搜索评论内容和评论者名字）
        start_time: 创建时间戳筛选起始（毫秒时间戳，如 1783924010000）
        end_time: 创建时间戳筛选结束（毫秒时间戳，如 1783924010000）
        page: 页码
        page_size: 每页数量
    """
    async with get_session() as session:
        # 构建查询
        where_clauses = []
        params = {}
        
        if platform:
            where_clauses.append("platform = :platform")
            params["platform"] = platform
        
        if push_status is not None:
            where_clauses.append("push_status = :push_status")
            params["push_status"] = push_status
        
        # 搜索评论内容和评论者名字
        if search:
            where_clauses.append("(comment_content LIKE :search OR comment_nickname LIKE :search)")
            params["search"] = f"%{search}%"
        
        # 创建时间范围筛选
        if start_time is not None:
            where_clauses.append("create_time >= :start_time")
            params["start_time"] = start_time
        
        if end_time is not None:
            where_clauses.append("create_time <= :end_time")
            params["end_time"] = end_time
        
        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        
        # 查询总数
        count_sql = text(f"SELECT COUNT(*) FROM comment_push WHERE {where_sql}")
        result = await session.execute(count_sql, params)
        total = result.scalar() or 0
        
        # 查询列表
        offset = (page - 1) * page_size
        list_sql = text(f"""
            SELECT id, platform, note_title, note_url, note_nickname,
                   comment_content, comment_nickname, comment_time,
                   push_status, process_content, process_time,
                   create_time, analysis_time
            FROM comment_push
            WHERE {where_sql}
            ORDER BY comment_time DESC
            LIMIT :limit OFFSET :offset
        """)
        params["limit"] = page_size
        params["offset"] = offset
        
        result = await session.execute(list_sql, params)
        rows = result.fetchall()
        
        items = []
        for row in rows:
            platform_code = row[1] or ""
            items.append(CommentPushItem(
                id=row[0],
                platform=platform_code,
                platform_name=PLATFORM_NAMES.get(platform_code, platform_code),
                note_title=row[2],
                note_url=row[3],
                note_nickname=row[4],
                comment_content=row[5],
                comment_nickname=row[6],
                comment_time=row[7],
                push_status=row[8] or 0,
                process_content=row[9],
                process_time=row[10],
                create_time=row[11],
                analysis_time=row[12]
            ))
        
        return CommentPushListResponse(total=total, items=items)


@router.post("/update")
async def update_comment_push(request: CommentPushUpdateRequest):
    """更新推送状态"""
    async with get_session() as session:
        # 只更新有值的字段
        updates = []
        params = {"id": request.id}
        
        if request.push_status is not None:
            updates.append("push_status = :push_status")
            params["push_status"] = request.push_status
        
        updates.append("process_time = NOW()")
        
        if request.process_content is not None:
            updates.append("process_content = :process_content")
            params["process_content"] = request.process_content
        
        sql = text(f"""
            UPDATE comment_push
            SET {', '.join(updates)}
            WHERE id = :id
        """)
        
        result = await session.execute(sql, params)
        
        await session.commit()
        
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="记录不存在")
        
        return {"status": "ok", "message": "更新成功"}


@router.get("/stats")
async def get_comment_push_stats():
    """获取统计信息"""
    async with get_session() as session:
        sql = text("""
            SELECT 
                platform,
                COUNT(*) as total,
                SUM(CASE WHEN push_status = 0 THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN push_status = 1 THEN 1 ELSE 0 END) as processed
            FROM comment_push
            GROUP BY platform
        """)
        
        result = await session.execute(sql)
        rows = result.fetchall()
        
        stats = {}
        for row in rows:
            platform = row[0] or ""
            stats[platform] = {
                "platform_name": PLATFORM_NAMES.get(platform, platform),
                "total": row[1] or 0,
                "pending": row[2] or 0,
                "processed": row[3] or 0
            }
        
        return {"stats": stats}


@router.post("/batch-update")
async def batch_update_comment_push(ids: List[int], push_status: int = 1):
    """批量更新推送状态"""
    async with get_session() as session:
        if not ids:
            raise HTTPException(status_code=400, detail="请选择要更新的记录")
        
        sql = text(f"""
            UPDATE comment_push
            SET push_status = :push_status,
                process_time = NOW()
            WHERE id IN ({','.join([':id' + str(i) for i in range(len(ids))])})
        """)
        
        params = {"push_status": push_status}
        for i, id_ in enumerate(ids):
            params[f"id{i}"] = id_
        
        result = await session.execute(sql, params)
        await session.commit()
        
        return {"status": "ok", "message": f"更新了 {result.rowcount} 条记录"}


@router.post("/run-batch")
async def run_comment_analysis_batch(platform: Optional[str] = None):
    """触发评论分析跑批"""
    import asyncio
    import sys
    import os
    
    # 动态导入跑批模块
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from sql.comment_analysis_batch import CommentAnalysisBatch
    
    try:
        batch = CommentAnalysisBatch()
        await batch.run(platform=platform)
        return {"status": "ok", "message": "跑批执行完成"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"跑批执行失败: {str(e)}")
