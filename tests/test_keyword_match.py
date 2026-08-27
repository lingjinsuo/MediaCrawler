# -*- coding: utf-8 -*-
"""
覆盖 sql.comment_analysis_batch 中关键词拆分与匹配逻辑的单元测试。

不依赖数据库,只针对 _split_keywords / _match_keywords 两个纯函数。
"""
import sys
import os

# 让 tests/ 能 import sql/*
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sql.comment_analysis_batch import _split_keywords, _match_keywords


# ---------- _split_keywords ----------

def test_split_empty():
    assert _split_keywords("") == []
    assert _split_keywords(None) == []


def test_split_single():
    assert _split_keywords("价格") == ["价格"]


def test_split_half_comma():
    assert _split_keywords("价格,多少钱,怎么买") == ["价格", "多少钱", "怎么买"]


def test_split_full_width_and_pause():
    # 同时混半角/全角逗号、顿号、分号、换行
    raw = "价格,怎么买、how much;buy\n链接"
    assert _split_keywords(raw) == ["价格", "怎么买", "how much", "buy", "链接"]


def test_split_trim_and_strip_quotes():
    raw = '  价格  , "多少钱" ,\'怎么买\''
    assert _split_keywords(raw) == ["价格", "多少钱", "怎么买"]


def test_split_dedup_case_insensitive():
    raw = "价格,价格,Price,PRICE"
    # 去重后保留首次出现的原文
    assert _split_keywords(raw) == ["价格", "Price"]


def test_split_drop_empty():
    raw = ",,, ,"
    assert _split_keywords(raw) == []


# ---------- _match_keywords ----------

def test_match_hit():
    assert _match_keywords("这个多少钱?", ["多少钱"]) == "多少钱"


def test_match_miss():
    assert _match_keywords("纯分享", ["价格", "多少钱"]) is None


def test_match_case_insensitive():
    assert _match_keywords("How much?", ["how much"]) == "how much"
    assert _match_keywords("HOW MUCH?", ["how much"]) == "how much"


def test_match_substring():
    # 设计上采用包含匹配
    assert _match_keywords("价格表出来了", ["价格"]) == "价格"


def test_match_empty_content():
    assert _match_keywords("", ["价格"]) is None
    assert _match_keywords(None, ["价格"]) is None


def test_match_empty_keywords():
    assert _match_keywords("anything", []) is None
    assert _match_keywords("anything", None) is None


def test_match_first_hit_returned():
    # 多个关键词都能命中时,返回最先遍历到的那个
    hit = _match_keywords("多少钱? 求链接", ["求链接", "多少钱"])
    assert hit == "求链接"


def test_match_does_not_hit_when_keyword_empty():
    # 关键词列表里有空字符串也不算命中
    assert _match_keywords("随便", ["", "  "]) is None


# ---------- _process_comment_with_keywords(集成测试,不打真实数据库) ----------

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

from sql.comment_analysis_batch import CommentAnalysisBatch


def _make_comment(content: str, comment_time: int = None) -> dict:
    """构造一条评论字典;comment_time 用当前时间(秒)"""
    if comment_time is None:
        comment_time = int(time.time())  # 1小时以内,不会触发3天过期
    return {
        "cmt_id": 1,
        "comment_id": "c1",
        "comment_content": content,
        "comment_nickname": "user",
        "comment_time": comment_time,
        "note_id": "n1",
        "note_title": "t",
        "note_url": "u",
        "note_nickname": "author",
    }


def _make_batch_with_mock_session():
    batch = CommentAnalysisBatch(db_type="sqlite")  # db_type 不会被用,因为我们不真正查
    session = MagicMock()
    session.execute = AsyncMock()
    return batch, session


def _last_sql_text(mock_session):
    """拿到最后一次 session.execute 的 SQL 文本"""
    return mock_session.execute.call_args_list[-1][0][0].text


def test_process_comment_hit():
    """命中关键词:应标 analysis_status=2,且调用 _insert_push_record"""
    batch, session = _make_batch_with_mock_session()
    # mock 掉两个 SQL 写入方法
    batch._update_comment_status = AsyncMock()
    batch._insert_push_record = AsyncMock()

    comment = _make_comment("这个多少钱? 求链接")
    cfg = {"comment_table": "xhs_note_comment"}

    has_intent, reason = asyncio.run(
        batch._process_comment_with_keywords(session, comment, cfg, ["价格", "求链接"])
    )

    assert has_intent is True
    assert "求链接" in reason
    batch._update_comment_status.assert_awaited_once_with(session, 1, 2, cfg)
    batch._insert_push_record.assert_awaited_once_with(session, comment, cfg)


def test_process_comment_miss():
    """未命中关键词:应标 analysis_status=1,且不调用 _insert_push_record"""
    batch, session = _make_batch_with_mock_session()
    batch._update_comment_status = AsyncMock()
    batch._insert_push_record = AsyncMock()

    comment = _make_comment("纯分享, 拍得很好看")
    cfg = {"comment_table": "xhs_note_comment"}

    has_intent, reason = asyncio.run(
        batch._process_comment_with_keywords(session, comment, cfg, ["价格", "求链接"])
    )

    assert has_intent is False
    assert "未命中关键词" in reason
    batch._update_comment_status.assert_awaited_once_with(session, 1, 1, cfg)
    batch._insert_push_record.assert_not_awaited()


def test_process_comment_no_keywords():
    """未配置 comment_key:全部视为无意图,标 analysis_status=1,且不调推送"""
    batch, session = _make_batch_with_mock_session()
    batch._update_comment_status = AsyncMock()
    batch._insert_push_record = AsyncMock()

    comment = _make_comment("想买")
    cfg = {"comment_table": "xhs_note_comment"}

    has_intent, reason = asyncio.run(
        batch._process_comment_with_keywords(session, comment, cfg, [])
    )

    assert has_intent is False
    assert "未配置 comment_key" in reason
    batch._update_comment_status.assert_awaited_once_with(session, 1, 1, cfg)
    batch._insert_push_record.assert_not_awaited()


def test_process_comment_over_3_days():
    """超过 3 天的评论:直接标 1,跳过关键词匹配,不调推送"""
    batch, session = _make_batch_with_mock_session()
    batch._update_comment_status = AsyncMock()
    batch._insert_push_record = AsyncMock()

    five_days_ago = int(time.time()) - 5 * 24 * 60 * 60
    comment = _make_comment("多少钱?", comment_time=five_days_ago)
    cfg = {"comment_table": "xhs_note_comment"}

    has_intent, reason = asyncio.run(
        batch._process_comment_with_keywords(session, comment, cfg, ["价格"])
    )

    assert has_intent is False
    assert "3天" in reason
    batch._update_comment_status.assert_awaited_once_with(session, 1, 1, cfg)
    batch._insert_push_record.assert_not_awaited()


def test_get_comment_keywords_returns_empty_on_missing_table(monkeypatch):
    """mc_setting 表不存在/读取失败时,返回 [] 而不是抛异常"""
    from sqlalchemy.exc import SQLAlchemyError

    batch, session = _make_batch_with_mock_session()
    session.execute = AsyncMock(side_effect=SQLAlchemyError("no such table"))

    result = asyncio.run(batch._get_comment_keywords(session))
    assert result == []