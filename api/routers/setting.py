# -*- coding: utf-8 -*-
# System settings API
# CRUD endpoints for mc_setting table

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from sqlalchemy import text

from database.db_session import get_session


router = APIRouter(prefix="/setting", tags=["setting"])


class SettingItem(BaseModel):
    id: int
    key: str
    content: Optional[str]
    create_time: Optional[datetime]
    update_time: Optional[datetime]


class SettingListResponse(BaseModel):
    total: int
    items: List[SettingItem]


class SettingCreateRequest(BaseModel):
    key: str
    content: Optional[str] = None


class SettingUpdateRequest(BaseModel):
    key: Optional[str] = None
    content: Optional[str] = None


@router.get("/list", response_model=SettingListResponse)
async def get_setting_list(search: Optional[str] = None):
    """Get all settings (with optional search by key/content)."""
    async with get_session() as session:
        where_clauses = []
        params = {}

        if search:
            where_clauses.append("(`key` LIKE :search OR content LIKE :search)")
            params["search"] = f"%{search}%"

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

        count_sql = text(f"SELECT COUNT(*) FROM mc_setting WHERE {where_sql}")
        result = await session.execute(count_sql, params)
        total = result.scalar() or 0

        list_sql = text(
            f"SELECT id, `key`, content, create_time, update_time "
            f"FROM mc_setting WHERE {where_sql} ORDER BY id ASC"
        )
        result = await session.execute(list_sql, params)
        rows = result.fetchall()

        items = []
        for row in rows:
            items.append(SettingItem(
                id=row[0],
                key=row[1] or "",
                content=row[2],
                create_time=row[3],
                update_time=row[4],
            ))

        return SettingListResponse(total=total, items=items)


@router.post("/create")
async def create_setting(request: SettingCreateRequest):
    """Create a new setting."""
    if not request.key or not request.key.strip():
        raise HTTPException(status_code=400, detail="key cannot be empty")

    async with get_session() as session:
        check_sql = text("SELECT id FROM mc_setting WHERE `key` = :key")
        result = await session.execute(check_sql, {"key": request.key})
        if result.scalar():
            raise HTTPException(
                status_code=400, detail=f"key '{request.key}' already exists"
            )

        insert_sql = text(
            "INSERT INTO mc_setting (`key`, content) VALUES (:key, :content)"
        )
        await session.execute(
            insert_sql, {"key": request.key, "content": request.content}
        )

        return {"status": "ok", "message": "Created successfully"}


@router.put("/update/{id}")
async def update_setting(id: int, request: SettingUpdateRequest):
    """Update a setting (called on blur)."""
    async with get_session() as session:
        check_sql = text("SELECT id FROM mc_setting WHERE id = :id")
        result = await session.execute(check_sql, {"id": id})
        if not result.scalar():
            raise HTTPException(status_code=404, detail="Setting not found")

        updates = []
        params = {"id": id}

        if request.key is not None:
            if not request.key.strip():
                raise HTTPException(status_code=400, detail="key cannot be empty")
            conflict_sql = text(
                "SELECT id FROM mc_setting WHERE `key` = :key AND id != :id"
            )
            r = await session.execute(
                conflict_sql, {"key": request.key, "id": id}
            )
            if r.scalar():
                raise HTTPException(
                    status_code=400,
                    detail=f"key '{request.key}' already exists",
                )
            updates.append("`key` = :key")
            params["key"] = request.key

        if request.content is not None:
            updates.append("content = :content")
            params["content"] = request.content

        if not updates:
            return {"status": "ok", "message": "Nothing to update"}

        update_sql = text(
            f"UPDATE mc_setting SET {', '.join(updates)} WHERE id = :id"
        )
        result = await session.execute(update_sql, params)

        if result.rowcount == 0:
            return {"status": "ok", "message": "No changes"}

        return {"status": "ok", "message": "Updated successfully"}


@router.delete("/delete/{id}")
async def delete_setting(id: int):
    """Delete a setting."""
    async with get_session() as session:
        delete_sql = text("DELETE FROM mc_setting WHERE id = :id")
        result = await session.execute(delete_sql, {"id": id})

        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Setting not found")

        return {"status": "ok", "message": "Deleted successfully"}
