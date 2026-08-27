# -*- coding: utf-8 -*-
# Crawl preset API
#
# 预设方案管理：为每个平台（抖音 / 小红书 ...）保存一套固定的抓取参数，
# 之后只需要点一下「启动」即可跑起来，不用每次重新填表单。
#
# 存储说明：
#   预设整体以 JSON 数组的形式存放在已有的 mc_setting 表中
#   （key = 'crawl_presets'），因此不需要新增任何建表语句。

import json
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from database.db_session import get_session

from ..schemas import (
    CrawlerStartRequest,
    CrawlerTypeEnum,
    LoginTypeEnum,
    PlatformEnum,
    SaveDataOptionEnum,
)
from ..schemas.crawler import MAX_API_LIMIT_COUNT
from ..services import crawler_manager

router = APIRouter(prefix="/crawl-preset", tags=["crawl-preset"])

# mc_setting 中用于存放预设列表的 key
SETTING_KEY = "crawl_presets"


class CrawlPreset(BaseModel):
    """单个平台的抓取预设方案"""

    id: str
    name: str = ""
    platform: PlatformEnum = PlatformEnum.XHS
    login_type: LoginTypeEnum = LoginTypeEnum.QRCODE
    crawler_type: CrawlerTypeEnum = CrawlerTypeEnum.SEARCH
    keywords: str = ""  # search 模式关键词，逗号分隔
    specified_ids: str = ""  # detail 模式的帖子/视频 ID，逗号分隔
    creator_ids: str = ""  # creator 模式的创作者 ID，逗号分隔
    start_page: int = Field(default=1, ge=1)
    enable_comments: bool = True
    enable_sub_comments: bool = False
    save_option: SaveDataOptionEnum = SaveDataOptionEnum.DB
    cookies: str = ""
    headless: bool = False
    max_notes_count: Optional[int] = Field(default=None, ge=1, le=MAX_API_LIMIT_COUNT)
    max_comments_count: Optional[int] = Field(default=None, ge=1, le=MAX_API_LIMIT_COUNT)
    enabled: bool = True
    sort_order: int = 0


class PresetListResponse(BaseModel):
    total: int
    items: List[CrawlPreset]


class PresetSaveRequest(BaseModel):
    """整体覆盖保存（前端一次提交全部预设，逻辑简单且不会产生脏数据）"""

    items: List[CrawlPreset]


async def _read_raw_presets() -> List[dict]:
    """从 mc_setting 读取原始预设列表"""
    async with get_session() as session:
        if session is None:
            # 当前 SAVE_DATA_OPTION 为文件类型（json/jsonl/csv），无数据库可用
            raise HTTPException(
                status_code=503,
                detail="当前 SAVE_DATA_OPTION 为文件模式，预设功能需要数据库支持",
            )

        sql = text("SELECT content FROM mc_setting WHERE `key` = :key")
        result = await session.execute(sql, {"key": SETTING_KEY})
        row = result.first()

    if not row or not row[0]:
        return []

    try:
        data = json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return []

    return data if isinstance(data, list) else []


async def _write_raw_presets(items: List[dict]) -> None:
    """写回 mc_setting（不存在则插入）"""
    content = json.dumps(items, ensure_ascii=False)

    async with get_session() as session:
        if session is None:
            raise HTTPException(
                status_code=503,
                detail="当前 SAVE_DATA_OPTION 为文件模式，预设功能需要数据库支持",
            )

        check_sql = text("SELECT id FROM mc_setting WHERE `key` = :key")
        result = await session.execute(check_sql, {"key": SETTING_KEY})

        if result.scalar():
            update_sql = text("UPDATE mc_setting SET content = :content WHERE `key` = :key")
            await session.execute(update_sql, {"content": content, "key": SETTING_KEY})
        else:
            insert_sql = text("INSERT INTO mc_setting (`key`, content) VALUES (:key, :content)")
            await session.execute(insert_sql, {"key": SETTING_KEY, "content": content})


def _parse_presets(raw_items: List[dict]) -> List[CrawlPreset]:
    """把原始 dict 解析成 CrawlPreset，跳过无法解析的脏数据"""
    presets: List[CrawlPreset] = []
    for raw in raw_items:
        try:
            presets.append(CrawlPreset(**raw))
        except Exception:
            continue
    presets.sort(key=lambda p: p.sort_order)
    return presets


@router.get("/list", response_model=PresetListResponse)
async def get_preset_list():
    """获取全部预设方案"""
    presets = _parse_presets(await _read_raw_presets())
    return PresetListResponse(total=len(presets), items=presets)


@router.post("/save")
async def save_presets(request: PresetSaveRequest):
    """整体保存预设方案（覆盖式）"""
    seen_ids = set()
    for preset in request.items:
        if not preset.id or not preset.id.strip():
            raise HTTPException(status_code=400, detail="预设 id 不能为空")
        if preset.id in seen_ids:
            raise HTTPException(status_code=400, detail=f"预设 id 重复: {preset.id}")
        seen_ids.add(preset.id)

    items = []
    for index, preset in enumerate(request.items):
        data = preset.model_dump(mode="json")
        data["sort_order"] = index
        items.append(data)

    await _write_raw_presets(items)
    return {"status": "ok", "message": "保存成功", "total": len(items)}


@router.delete("/delete/{preset_id}")
async def delete_preset(preset_id: str):
    """删除单个预设方案"""
    raw_items = await _read_raw_presets()
    remaining = [item for item in raw_items if str(item.get("id")) != preset_id]

    if len(remaining) == len(raw_items):
        raise HTTPException(status_code=404, detail="预设不存在")

    for index, item in enumerate(remaining):
        item["sort_order"] = index

    await _write_raw_presets(remaining)
    return {"status": "ok", "message": "删除成功"}


def _validate_preset(preset: CrawlPreset) -> None:
    """启动前的必填项校验"""
    if preset.crawler_type == CrawlerTypeEnum.SEARCH and not preset.keywords.strip():
        raise HTTPException(status_code=400, detail="搜索模式必须填写关键词")
    if preset.crawler_type == CrawlerTypeEnum.DETAIL and not preset.specified_ids.strip():
        raise HTTPException(status_code=400, detail="详情模式必须填写帖子/视频 ID")
    if preset.crawler_type == CrawlerTypeEnum.CREATOR and not preset.creator_ids.strip():
        raise HTTPException(status_code=400, detail="创作者模式必须填写创作者 ID")
    if preset.login_type == LoginTypeEnum.COOKIE and not preset.cookies.strip():
        raise HTTPException(status_code=400, detail="Cookie 登录方式必须填写 cookies")


def _to_start_request(preset: CrawlPreset) -> CrawlerStartRequest:
    """把预设转换成爬虫启动请求"""
    return CrawlerStartRequest(
        platform=preset.platform,
        login_type=preset.login_type,
        crawler_type=preset.crawler_type,
        keywords=preset.keywords.strip(),
        specified_ids=preset.specified_ids.strip(),
        creator_ids=preset.creator_ids.strip(),
        start_page=preset.start_page,
        enable_comments=preset.enable_comments,
        enable_sub_comments=preset.enable_sub_comments,
        save_option=preset.save_option,
        cookies=preset.cookies.strip(),
        headless=preset.headless,
        max_notes_count=preset.max_notes_count,
        max_comments_count=preset.max_comments_count,
    )


@router.post("/run/{preset_id}")
async def run_preset(preset_id: str):
    """按预设一键启动爬虫

    注意：crawler_manager 为全局单例，同一时刻只允许运行一个爬虫进程。
    """
    raw_items = await _read_raw_presets()
    target = next((item for item in raw_items if str(item.get("id")) == preset_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="预设不存在")

    try:
        preset = CrawlPreset(**target)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"预设数据非法: {e}")

    _validate_preset(preset)

    if crawler_manager.process and crawler_manager.process.poll() is None:
        raise HTTPException(status_code=400, detail="已有爬虫任务正在运行，请先停止")

    success = await crawler_manager.start(_to_start_request(preset))
    if not success:
        if crawler_manager.process and crawler_manager.process.poll() is None:
            raise HTTPException(status_code=400, detail="已有爬虫任务正在运行，请先停止")
        raise HTTPException(status_code=500, detail="启动爬虫失败")

    return {
        "status": "ok",
        "message": f"已启动: {preset.name or preset.platform.value}",
        "preset_id": preset.id,
        "platform": preset.platform.value,
    }


@router.post("/batch/run")
async def batch_run_presets():
    """一键顺序执行所有已启用的预设方案。

    会跳过：
      - 未启用的预设（enabled=False）
      - 必填项不合法（例如搜索模式无关键词）

    按 sort_order 顺序依次执行；上一个爬虫进程结束（成功/失败）后再启动下一个。
    """
    raw_items = await _read_raw_presets()
    presets = _parse_presets(raw_items)

    # 按 sort_order 排好序再过滤
    presets.sort(key=lambda p: p.sort_order)
    enabled = [p for p in presets if p.enabled]

    if not enabled:
        raise HTTPException(status_code=400, detail="没有可执行的已启用预设")

    # 逐个校验必填项
    skipped: List[str] = []
    items: List[tuple] = []
    for preset in enabled:
        try:
            _validate_preset(preset)
        except HTTPException as e:
            skipped.append(f"{preset.name or preset.platform.value}: {e.detail}")
            continue
        items.append((
            preset.name or preset.platform.value,
            _to_start_request(preset),
        ))

    if not items:
        raise HTTPException(
            status_code=400,
            detail="所有启用的预设都缺少必要参数: " + "; ".join(skipped),
        )

    success = await crawler_manager.start_batch(items)
    if not success:
        if crawler_manager._batch_active:
            raise HTTPException(status_code=400, detail="已有批量任务在运行，请先取消")
        if crawler_manager.process and crawler_manager.process.poll() is None:
            raise HTTPException(status_code=400, detail="已有爬虫任务正在运行，请先停止")
        raise HTTPException(status_code=500, detail="启动批量任务失败")

    return {
        "status": "ok",
        "message": f"已加入批量队列，共 {len(items)} 个任务",
        "total": len(items),
        "skipped": skipped,
    }


@router.post("/batch/cancel")
async def batch_cancel_presets():
    """取消正在执行的批量队列"""
    if not crawler_manager._batch_active:
        raise HTTPException(status_code=400, detail="当前没有批量任务在运行")

    await crawler_manager.cancel_batch()
    return {"status": "ok", "message": "已取消批量任务"}



