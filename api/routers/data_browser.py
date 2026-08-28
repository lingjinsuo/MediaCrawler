# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/api/routers/data_browser.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#
# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

"""
数据浏览 (Data Browser) API

提供帖子与评论的统一浏览接口，按平台适配字段差异。
- 自动识别 data/{platform}/json / jsonl / csv 下的文件
- 同时支持从 SQLite 数据库读取
- 返回统一帖子 + 评论结构（评论嵌套在帖子下）
"""

import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/data-browser", tags=["data-browser"])

# Data directory (root)
ROOT_DIR = Path(__file__).parent.parent.parent
DATA_DIR = ROOT_DIR / "data"
SQLITE_DB_PATH = ROOT_DIR / "database" / "sqlite_tables.db"

# 平台显示配置
PLATFORM_META = {
    "xhs": {"label": "小红书", "emoji": "📕", "post_label": "笔记", "id_field": "note_id"},
    "dy": {"label": "抖音", "emoji": "🎵", "post_label": "视频", "id_field": "aweme_id"},
    "ks": {"label": "快手", "emoji": "🎬", "post_label": "视频", "id_field": "video_id"},
    "bili": {"label": "B站", "emoji": "📺", "post_label": "视频", "id_field": "video_id"},
    "wb": {"label": "微博", "emoji": "💬", "post_label": "微博", "id_field": "note_id"},
    "tieba": {"label": "百度贴吧", "emoji": "🗨️", "post_label": "帖子", "id_field": "note_id"},
    "zhihu": {"label": "知乎", "emoji": "❓", "post_label": "内容", "id_field": "content_id"},
}

POST_TABLE_MAP = {
    "xhs": "xhs_note",
    "dy": "douyin_aweme",
    "ks": "kuaishou_video",
    "bili": "bilibili_video",
    "wb": "weibo_note",
    "tieba": "tieba_note",
    "zhihu": "zhihu_content",
}

COMMENT_TABLE_MAP = {
    "xhs": "xhs_note_comment",
    "dy": "douyin_aweme_comment",
    "ks": "kuaishou_video_comment",
    "bili": "bilibili_video_comment",
    "wb": "weibo_note_comment",
    "tieba": "tieba_comment",
    "zhihu": "zhihu_comment",
}


def _safe_str(v: Any, default: str = "") -> str:
    if v is None:
        return default
    return str(v)


def _format_timestamp(ts: Any) -> str:
    """将各种时间格式统一格式化为 YYYY-MM-DD HH:MM:SS"""
    if not ts:
        return ""
    try:
        ts_int = int(ts)
        from datetime import datetime
        if ts_int > 10**12:
            ts_int = ts_int / 1000
        return datetime.fromtimestamp(ts_int).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return _safe_str(ts)


def _detect_storage_type(platform: str) -> List[str]:
    """检测某平台可用的存储类型（仅文件 + SQLite，MySQL 需要异步探测）。"""
    types = []
    platform_dir = DATA_DIR / platform
    if (platform_dir / "json").exists() and any((platform_dir / "json").glob("*.json")):
        types.append("json")
    if (platform_dir / "jsonl").exists() and any((platform_dir / "jsonl").glob("*.jsonl")):
        types.append("jsonl")
    if (platform_dir / "csv").exists() and any((platform_dir / "csv").glob("*.csv")):
        types.append("csv")
    if SQLITE_DB_PATH.exists():
        types.append("sqlite")
    return types


async def _detect_mysql_storage(platform: str) -> List[str]:
    """异步探测 MySQL 中是否有该平台的数据。"""
    try:
        from sqlalchemy import text
        from database.db_session import get_async_engine
        from sqlalchemy.ext.asyncio import AsyncSession
        from sqlalchemy.orm import sessionmaker

        engine = get_async_engine("mysql")
        if engine is None:
            return []
        table = POST_TABLE_MAP.get(platform)
        if not table:
            return []

        Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with Session() as session:
            result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
            count = result.scalar()
            return ["mysql"] if count and count > 0 else []
    except Exception as e:
        # 表不存在 / 连接失败 / 数据库不存在 都不算错误
        return []


async def _detect_storage_type_async(platform: str) -> List[str]:
    """异步版本：包含文件、SQLite、MySQL 全量探测。"""
    types = _detect_storage_type(platform)
    types.extend(await _detect_mysql_storage(platform))
    return types


def _load_json_file(path: Path) -> List[Dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            return [data]
    except Exception:
        return []


def _load_jsonl_file(path: Path) -> List[Dict]:
    items = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:
        return []
    return items


def _load_csv_file(path: Path) -> List[Dict]:
    items = []
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                items.append(row)
    except Exception:
        return []
    return items


def _load_posts_from_files(platform: str, storage: str) -> List[Dict]:
    """从文件中加载帖子列表。"""
    platform_dir = DATA_DIR / platform / storage
    if not platform_dir.exists():
        return []
    all_items: List[Dict] = []
    found = False
    for path in platform_dir.glob(f"*_contents_*.{storage}"):
        found = True
        if storage == "json":
            all_items.extend(_load_json_file(path))
        elif storage == "jsonl":
            all_items.extend(_load_jsonl_file(path))
        elif storage == "csv":
            all_items.extend(_load_csv_file(path))
    if not found:
        for path in platform_dir.glob(f"*.{storage}"):
            if "comment" in path.name.lower() or "creator" in path.name.lower():
                continue
            if storage == "json":
                all_items.extend(_load_json_file(path))
            elif storage == "jsonl":
                all_items.extend(_load_jsonl_file(path))
            elif storage == "csv":
                all_items.extend(_load_csv_file(path))
    return all_items


def _load_comments_from_files(platform: str, storage: str) -> List[Dict]:
    """从文件中加载评论列表。"""
    platform_dir = DATA_DIR / platform / storage
    if not platform_dir.exists():
        return []
    all_items: List[Dict] = []
    found = False
    for path in platform_dir.glob(f"*_comments_*.{storage}"):
        found = True
        if storage == "json":
            all_items.extend(_load_json_file(path))
        elif storage == "jsonl":
            all_items.extend(_load_jsonl_file(path))
        elif storage == "csv":
            all_items.extend(_load_csv_file(path))
    if not found:
        for path in platform_dir.glob(f"*.{storage}"):
            if "content" in path.name.lower() or "creator" in path.name.lower():
                continue
            if storage == "json":
                all_items.extend(_load_json_file(path))
            elif storage == "jsonl":
                all_items.extend(_load_jsonl_file(path))
            elif storage == "csv":
                all_items.extend(_load_csv_file(path))
    return all_items


async def _load_table_rows(table_name: str) -> List[Dict]:
    """从 SQLite 读取某张表的全部行。"""
    if not SQLITE_DB_PATH.exists():
        return []
    try:
        from sqlalchemy import text
        from database.db_session import get_async_engine
        from sqlalchemy.ext.asyncio import AsyncSession
        from sqlalchemy.orm import sessionmaker

        engine = get_async_engine("sqlite")
        if engine is None:
            return []
        Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with Session() as session:
            result = await session.execute(text(f"SELECT * FROM {table_name}"))
            rows = result.fetchall()
            columns = result.keys()
            return [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        print(f"[data_browser] SQLite load failed for {table_name}: {e}")
        return []


async def _load_posts_from_sqlite(platform: str) -> List[Dict]:
    table = POST_TABLE_MAP.get(platform)
    if not table:
        return []
    return await _load_table_rows(table)


async def _load_comments_from_sqlite(platform: str) -> List[Dict]:
    table = COMMENT_TABLE_MAP.get(platform)
    if not table:
        return []
    return await _load_table_rows(table)


# ===================== MySQL 加载 =====================

async def _load_table_rows_mysql(table_name: str) -> List[Dict]:
    """从 MySQL 读取某张表的全部行。"""
    try:
        from sqlalchemy import text
        from database.db_session import get_async_engine
        from sqlalchemy.ext.asyncio import AsyncSession
        from sqlalchemy.orm import sessionmaker

        engine = get_async_engine("mysql")
        if engine is None:
            return []
        Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with Session() as session:
            result = await session.execute(text(f"SELECT * FROM {table_name}"))
            rows = result.fetchall()
            columns = result.keys()
            return [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        print(f"[data_browser] MySQL load failed for {table_name}: {e}")
        return []


async def _load_posts_from_mysql(platform: str) -> List[Dict]:
    table = POST_TABLE_MAP.get(platform)
    if not table:
        return []
    return await _load_table_rows_mysql(table)


async def _load_comments_from_mysql(platform: str) -> List[Dict]:
    table = COMMENT_TABLE_MAP.get(platform)
    if not table:
        return []
    return await _load_table_rows_mysql(table)


def _normalize_xhs_post(item: Dict) -> Dict:
    image_list_raw = _safe_str(item.get("image_list", ""))
    image_urls = [u for u in image_list_raw.split(",") if u]
    return {
        "post_id": _safe_str(item.get("note_id")),
        "title": _safe_str(item.get("title")),
        "content": _safe_str(item.get("desc")),
        "author": _safe_str(item.get("nickname")),
        "cover_url": image_urls[0] if image_urls else "",
        "image_urls": image_urls,
        "video_url": _safe_str(item.get("video_url")),
        "post_url": _safe_str(item.get("note_url")),
        "liked_count": _safe_str(item.get("liked_count")),
        "collected_count": _safe_str(item.get("collected_count")),
        "comment_count": _safe_str(item.get("comment_count")),
        "share_count": _safe_str(item.get("share_count")),
        "create_time": _format_timestamp(item.get("time") or item.get("last_update_time")),
        "tags": _safe_str(item.get("tag_list")),
        "source_keyword": _safe_str(item.get("source_keyword")),
        "post_type": _safe_str(item.get("type")) or "normal",
    }


def _normalize_dy_post(item: Dict) -> Dict:
    image_urls = [u for u in _safe_str(item.get("note_download_url", "")).split(",") if u]
    return {
        "post_id": _safe_str(item.get("aweme_id")),
        "title": _safe_str(item.get("title")) or _safe_str(item.get("desc")),
        "content": _safe_str(item.get("desc")),
        "author": _safe_str(item.get("nickname")),
        "cover_url": _safe_str(item.get("cover_url")),
        "image_urls": image_urls,
        "video_url": _safe_str(item.get("video_download_url")),
        "post_url": _safe_str(item.get("aweme_url")),
        "liked_count": _safe_str(item.get("liked_count")),
        "collected_count": _safe_str(item.get("collected_count")),
        "comment_count": _safe_str(item.get("comment_count")),
        "share_count": _safe_str(item.get("share_count")),
        "create_time": _format_timestamp(item.get("create_time")),
        "tags": "",
        "source_keyword": _safe_str(item.get("source_keyword")),
        "post_type": _safe_str(item.get("aweme_type")) or "video",
    }


def _normalize_ks_post(item: Dict) -> Dict:
    return {
        "post_id": _safe_str(item.get("video_id")),
        "title": _safe_str(item.get("title")) or _safe_str(item.get("desc")),
        "content": _safe_str(item.get("desc")),
        "author": _safe_str(item.get("nickname")),
        "cover_url": _safe_str(item.get("video_cover_url")),
        "image_urls": [],
        "video_url": _safe_str(item.get("video_play_url")) or _safe_str(item.get("video_url")),
        "post_url": _safe_str(item.get("video_url")),
        "liked_count": _safe_str(item.get("liked_count")),
        "collected_count": "0",
        "comment_count": "0",
        "share_count": "0",
        "view_count": _safe_str(item.get("viewd_count")),
        "create_time": _format_timestamp(item.get("create_time")),
        "tags": "",
        "source_keyword": _safe_str(item.get("source_keyword")),
        "post_type": _safe_str(item.get("video_type")) or "video",
    }


def _normalize_bili_post(item: Dict) -> Dict:
    return {
        "post_id": _safe_str(item.get("video_id")),
        "title": _safe_str(item.get("title")),
        "content": _safe_str(item.get("desc")),
        "author": _safe_str(item.get("nickname")),
        "cover_url": _safe_str(item.get("video_cover_url")),
        "image_urls": [],
        "video_url": _safe_str(item.get("video_url")),
        "post_url": _safe_str(item.get("video_url")),
        "liked_count": _safe_str(item.get("liked_count")),
        "disliked_count": _safe_str(item.get("disliked_count")),
        "view_count": _safe_str(item.get("video_play_count")),
        "favorite_count": _safe_str(item.get("video_favorite_count")),
        "share_count": _safe_str(item.get("video_share_count")),
        "coin_count": _safe_str(item.get("video_coin_count")),
        "danmaku_count": _safe_str(item.get("video_danmaku")),
        "comment_count": _safe_str(item.get("video_comment")),
        "create_time": _format_timestamp(item.get("create_time")),
        "tags": "",
        "source_keyword": _safe_str(item.get("source_keyword")),
        "post_type": _safe_str(item.get("video_type")) or "video",
    }


def _normalize_wb_post(item: Dict) -> Dict:
    content = _safe_str(item.get("content"))
    return {
        "post_id": _safe_str(item.get("note_id")),
        "title": content[:80],
        "content": content,
        "author": _safe_str(item.get("nickname")),
        "cover_url": "",
        "image_urls": [],
        "video_url": "",
        "post_url": _safe_str(item.get("note_url")),
        "liked_count": _safe_str(item.get("liked_count")),
        "collected_count": "0",
        "comment_count": _safe_str(item.get("comments_count")),
        "share_count": _safe_str(item.get("shared_count")),
        "create_time": _format_timestamp(item.get("create_time")),
        "tags": "",
        "source_keyword": _safe_str(item.get("source_keyword")),
        "post_type": "weibo",
    }


def _normalize_tieba_post(item: Dict) -> Dict:
    return {
        "post_id": _safe_str(item.get("note_id")),
        "title": _safe_str(item.get("title")),
        "content": _safe_str(item.get("desc")),
        "author": _safe_str(item.get("user_nickname")),
        "cover_url": "",
        "image_urls": [],
        "video_url": "",
        "post_url": _safe_str(item.get("note_url")),
        "liked_count": "0",
        "collected_count": "0",
        "comment_count": _safe_str(item.get("total_replay_num")),
        "share_count": "0",
        "tieba_name": _safe_str(item.get("tieba_name")),
        "create_time": _safe_str(item.get("publish_time")),
        "tags": "",
        "source_keyword": _safe_str(item.get("source_keyword")),
        "post_type": "tieba",
    }


def _normalize_zhihu_post(item: Dict) -> Dict:
    return {
        "post_id": _safe_str(item.get("content_id")),
        "title": _safe_str(item.get("title")) or _safe_str(item.get("desc"))[:80],
        "content": _safe_str(item.get("content_text")),
        "author": _safe_str(item.get("user_nickname")),
        "cover_url": "",
        "image_urls": [],
        "video_url": "",
        "post_url": _safe_str(item.get("content_url")),
        "liked_count": _safe_str(item.get("voteup_count")),
        "collected_count": "0",
        "comment_count": _safe_str(item.get("comment_count")),
        "share_count": "0",
        "content_type": _safe_str(item.get("content_type")),
        "create_time": _safe_str(item.get("created_time")),
        "tags": "",
        "source_keyword": _safe_str(item.get("source_keyword")),
        "post_type": _safe_str(item.get("content_type")) or "answer",
    }


_PLATFORM_NORMALIZERS = {
    "xhs": _normalize_xhs_post,
    "dy": _normalize_dy_post,
    "ks": _normalize_ks_post,
    "bili": _normalize_bili_post,
    "wb": _normalize_wb_post,
    "tieba": _normalize_tieba_post,
    "zhihu": _normalize_zhihu_post,
}


def _normalize_post(platform: str, item: Dict) -> Dict:
    normalizer = _PLATFORM_NORMALIZERS.get(platform)
    if normalizer:
        return normalizer(item)
    return {
        "post_id": _safe_str(item.get("id") or item.get("post_id") or item.get("note_id")
                              or item.get("video_id") or item.get("aweme_id")),
        "title": _safe_str(item.get("title") or item.get("desc") or item.get("content")),
        "content": _safe_str(item.get("content") or item.get("desc") or item.get("text")),
        "author": _safe_str(item.get("nickname") or item.get("user_nickname")
                            or item.get("author") or item.get("user_name")),
        "cover_url": "",
        "image_urls": [],
        "video_url": "",
        "post_url": "",
        "liked_count": "0",
        "comment_count": "0",
        "share_count": "0",
        "create_time": "",
        "tags": "",
        "source_keyword": _safe_str(item.get("source_keyword")),
        "post_type": "unknown",
    }


def _normalize_comment(platform: str, item: Dict) -> Dict:
    return {
        "comment_id": _safe_str(item.get("comment_id")),
        "post_id": _safe_str(
            item.get("note_id") or item.get("aweme_id") or item.get("video_id")
        ),
        "content": _safe_str(item.get("content")),
        "author": _safe_str(item.get("nickname") or item.get("user_nickname")),
        "like_count": _safe_str(item.get("like_count") or item.get("comment_like_count") or 0),
        "sub_comment_count": _safe_str(item.get("sub_comment_count", 0)),
        "parent_comment_id": _safe_str(item.get("parent_comment_id") or "0"),
        "create_time": _format_timestamp(item.get("create_time") or item.get("publish_time")),
        "pictures": [u for u in _safe_str(item.get("pictures", "")).split(",") if u],
    }


# ===================== 通用加载（自动选择存储） =====================

async def _load_all_posts(platform: str, storage: str) -> List[Dict]:
    if storage == "sqlite":
        return await _load_posts_from_sqlite(platform)
    if storage == "mysql":
        return await _load_posts_from_mysql(platform)
    return _load_posts_from_files(platform, storage)


async def _load_all_comments(platform: str, storage: str) -> List[Dict]:
    if storage == "sqlite":
        return await _load_comments_from_sqlite(platform)
    if storage == "mysql":
        return await _load_comments_from_mysql(platform)
    return _load_comments_from_files(platform, storage)


def _pick_storage(platform: str, requested: Optional[str], available: Optional[List[str]] = None) -> Optional[str]:
    """根据可用存储选择实际使用的存储类型。

    available: 已探测到的可用存储列表（包含 MySQL 时使用）；None 时只查文件/SQLite。
    """
    storages = available if available is not None else _detect_storage_type(platform)
    if not storages:
        return None
    if requested:
        if requested not in ("json", "jsonl", "csv", "sqlite", "mysql"):
            return None
        return requested if requested in storages else None
    priority = ["mysql", "sqlite", "json", "jsonl", "csv"]
    for s in priority:
        if s in storages:
            return s
    return storages[0]


# ===================== API 端点 =====================

@router.get("/platforms")
async def list_platforms():
    """列出所有平台及其可用数据存储类型。"""
    platforms = []
    for code, meta in PLATFORM_META.items():
        storages = await _detect_storage_type_async(code)
        platforms.append({
            "value": code,
            "label": meta["label"],
            "emoji": meta["emoji"],
            "post_label": meta["post_label"],
            "storages": storages,
            "has_data": len(storages) > 0,
        })
    return {"platforms": platforms}


@router.get("/stats")
async def get_stats(platform: Optional[str] = Query(None)):
    """获取各平台数据统计。"""
    result = []
    targets = [platform] if platform else list(PLATFORM_META.keys())
    for code in targets:
        if code not in PLATFORM_META:
            continue
        meta = PLATFORM_META[code]
        all_storages = await _detect_storage_type_async(code)
        storage = _pick_storage(code, None, all_storages) if all_storages else None
        post_count = 0
        comment_count = 0
        if storage:
            posts = await _load_all_posts(code, storage)
            comments = await _load_all_comments(code, storage)
            post_count = len(posts)
            comment_count = len(comments)
        result.append({
            "platform": code,
            "label": meta["label"],
            "emoji": meta["emoji"],
            "storage": storage,
            "all_storages": all_storages,
            "has_data": len(all_storages) > 0,
            "post_count": post_count,
            "comment_count": comment_count,
        })
    return {"stats": result}


@router.get("/posts")
async def list_posts(
    platform: str = Query(..., description="平台代码"),
    storage: Optional[str] = Query(None, description="存储类型"),
    keyword: Optional[str] = Query(None, description="关键词过滤"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    include_comments: bool = Query(True, description="是否附带评论"),
):
    """获取帖子列表，评论嵌套返回。"""
    if platform not in PLATFORM_META:
        raise HTTPException(status_code=400, detail=f"不支持的平台: {platform}")

    available = await _detect_storage_type_async(platform)
    actual_storage = _pick_storage(platform, storage, available)
    if not actual_storage:
        return {"total": 0, "items": [], "storage": None, "limit": limit, "offset": offset}

    raw_posts = await _load_all_posts(platform, actual_storage)
    raw_comments = await _load_all_comments(platform, actual_storage) if include_comments else []

    posts = [_normalize_post(platform, item) for item in raw_posts]
    comments = [_normalize_comment(platform, item) for item in raw_comments]

    if keyword:
        kw = keyword.lower()
        posts = [
            p for p in posts
            if kw in (p.get("title") or "").lower()
            or kw in (p.get("content") or "").lower()
            or kw in (p.get("author") or "").lower()
            or kw in (p.get("source_keyword") or "").lower()
        ]

    posts.sort(key=lambda p: p.get("create_time") or "", reverse=True)
    total = len(posts)
    paged = posts[offset: offset + limit]

    comments_by_post: Dict[str, List[Dict]] = {}
    for c in comments:
        pid = c.get("post_id")
        if pid:
            comments_by_post.setdefault(pid, []).append(c)
    for pid in comments_by_post:
        comments_by_post[pid].sort(key=lambda c: c.get("create_time") or "")

    for p in paged:
        pid = p.get("post_id")
        post_comments = comments_by_post.get(pid, [])
        if include_comments:
            p["comments"] = post_comments[:10]
            p["has_more_comments"] = len(post_comments) > 10
        else:
            p["comments"] = []
            p["has_more_comments"] = False
        p["comments_total"] = len(post_comments)

    return {
        "total": total,
        "items": paged,
        "storage": actual_storage,
        "limit": limit,
        "offset": offset,
    }


@router.get("/comments")
async def list_comments(
    platform: str = Query(..., description="平台代码"),
    storage: Optional[str] = Query(None, description="存储类型"),
    post_id: Optional[str] = Query(None, description="按帖子 ID 过滤"),
    keyword: Optional[str] = Query(None, description="关键词过滤"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """获取评论列表。"""
    if platform not in PLATFORM_META:
        raise HTTPException(status_code=400, detail=f"不支持的平台: {platform}")

    available = await _detect_storage_type_async(platform)
    actual_storage = _pick_storage(platform, storage, available)
    if not actual_storage:
        return {"total": 0, "items": [], "storage": None, "limit": limit, "offset": offset}

    raw_comments = await _load_all_comments(platform, actual_storage)
    comments = [_normalize_comment(platform, item) for item in raw_comments]

    if post_id:
        comments = [c for c in comments if c.get("post_id") == post_id]
    if keyword:
        kw = keyword.lower()
        comments = [
            c for c in comments
            if kw in (c.get("content") or "").lower()
            or kw in (c.get("author") or "").lower()
        ]

    comments.sort(key=lambda c: c.get("create_time") or "", reverse=True)
    total = len(comments)
    paged = comments[offset: offset + limit]
    return {
        "total": total,
        "items": paged,
        "storage": actual_storage,
        "limit": limit,
        "offset": offset,
    }


@router.get("/post/{platform}/{post_id}")
async def get_post_detail(platform: str, post_id: str):
    """获取单个帖子的完整信息及其全部评论。"""
    if platform not in PLATFORM_META:
        raise HTTPException(status_code=400, detail=f"不支持的平台: {platform}")

    available = await _detect_storage_type_async(platform)
    actual_storage = _pick_storage(platform, None, available)
    if not actual_storage:
        raise HTTPException(status_code=404, detail="该平台暂无数据")

    raw_posts = await _load_all_posts(platform, actual_storage)
    id_field = PLATFORM_META[platform]["id_field"]
    target = None
    for p in raw_posts:
        if _safe_str(p.get(id_field)) == post_id:
            target = p
            break
    if not target:
        raise HTTPException(status_code=404, detail="未找到该帖子")

    raw_comments = await _load_all_comments(platform, actual_storage)
    comments = []
    for c in raw_comments:
        c_post_id = _safe_str(c.get("note_id") or c.get("aweme_id") or c.get("video_id"))
        if c_post_id == post_id:
            comments.append(_normalize_comment(platform, c))
    comments.sort(key=lambda c: c.get("create_time") or "")

    post = _normalize_post(platform, target)
    post["comments"] = comments
    post["comments_total"] = len(comments)
    return {"post": post, "storage": actual_storage}

