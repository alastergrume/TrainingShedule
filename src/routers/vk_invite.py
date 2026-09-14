from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import asc, desc
from datetime import datetime
from typing import List, Optional

from src.models.base import get_db
from src.models.models import VkFriend, VkCommunityMember, VkInvite
from src.config import settings

router = APIRouter(prefix="/api/vk-invite", tags=["vk-invite"])

SORTABLE_FIELDS = {
    "friends": {
        "vk_user_id": VkFriend.vk_user_id,
        "first_name": VkFriend.first_name,
        "last_name": VkFriend.last_name,
        "synced_at": VkFriend.synced_at,
    },
    "members": {
        "vk_user_id": VkCommunityMember.vk_user_id,
        "first_name": VkCommunityMember.first_name,
        "last_name": VkCommunityMember.last_name,
        "synced_at": VkCommunityMember.synced_at,
    },
}


@router.get("/settings")
async def get_invite_settings():
    return {
        "daily_limit": settings.VK_INVITE_DAILY_LIMIT,
        "delay_seconds": settings.VK_INVITE_DELAY_SECONDS,
    }


@router.get("/stats")
async def get_stats(db: Session = Depends(get_db)):
    total_friends = db.query(VkFriend).count()
    active_friends = db.query(VkFriend).filter(VkFriend.is_deactivated == False).count()
    total_members = db.query(VkCommunityMember).count()
    invited = db.query(VkInvite).filter(VkInvite.status == "invited").count()
    errors = db.query(VkInvite).filter(VkInvite.status == "error").count()

    member_ids = db.query(VkCommunityMember.vk_user_id)
    invited_friend_ids = (
        db.query(VkInvite.friend_id).filter(VkInvite.status == "invited")
    )
    pending = (
        db.query(VkFriend)
        .filter(
            VkFriend.is_deactivated == False,
            ~VkFriend.vk_user_id.in_(member_ids),
            ~VkFriend.id.in_(invited_friend_ids),
        )
        .count()
    )

    return {
        "total_friends": total_friends,
        "active_friends": active_friends,
        "deactivated_friends": total_friends - active_friends,
        "total_members": total_members,
        "invited": invited,
        "errors": errors,
        "pending": pending,
    }


def _apply_sort(query, table_key: str, sort_by: str, sort_dir: str):
    fields = SORTABLE_FIELDS.get(table_key, {})
    col = fields.get(sort_by)
    if col is not None:
        return query.order_by(desc(col) if sort_dir == "desc" else asc(col))
    return query


@router.get("/friends")
async def list_friends(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    alive: Optional[str] = Query(None),
    sort_by: str = Query("vk_user_id"),
    sort_dir: str = Query("asc"),
    db: Session = Depends(get_db),
):
    query = db.query(VkFriend)
    if alive == "active":
        query = query.filter(VkFriend.is_deactivated == False)
    elif alive == "deactivated":
        query = query.filter(VkFriend.is_deactivated == True)

    total = query.count()
    query = _apply_sort(query, "friends", sort_by, sort_dir)
    items = query.offset((page - 1) * per_page).limit(per_page).all()

    return {
        "total": total,
        "page": page,
        "items": [
            {
                "id": f.id,
                "vk_user_id": f.vk_user_id,
                "first_name": f.first_name,
                "last_name": f.last_name,
                "is_deactivated": f.is_deactivated,
                "deactivated_reason": f.deactivated_reason,
                "synced_at": f.synced_at.isoformat() if f.synced_at else None,
            }
            for f in items
        ],
    }


@router.get("/members")
async def list_members(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    alive: Optional[str] = Query(None),
    sort_by: str = Query("vk_user_id"),
    sort_dir: str = Query("asc"),
    db: Session = Depends(get_db),
):
    query = db.query(VkCommunityMember)
    if alive == "active":
        query = query.filter(VkCommunityMember.is_deactivated == False)
    elif alive == "deactivated":
        query = query.filter(VkCommunityMember.is_deactivated == True)

    total = query.count()
    query = _apply_sort(query, "members", sort_by, sort_dir)
    items = query.offset((page - 1) * per_page).limit(per_page).all()

    return {
        "total": total,
        "page": page,
        "items": [
            {
                "id": m.id,
                "vk_user_id": m.vk_user_id,
                "first_name": m.first_name,
                "last_name": m.last_name,
                "is_deactivated": m.is_deactivated,
                "deactivated_reason": m.deactivated_reason,
                "synced_at": m.synced_at.isoformat() if m.synced_at else None,
            }
            for m in items
        ],
    }


@router.get("/invites")
async def list_invites(
    status: str = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(VkInvite).join(VkFriend)
    if status:
        query = query.filter(VkInvite.status == status)
    total = query.count()
    items = (
        query.order_by(VkInvite.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return {
        "total": total,
        "page": page,
        "items": [
            {
                "id": i.id,
                "friend_id": i.friend_id,
                "vk_user_id": i.friend.vk_user_id,
                "first_name": i.friend.first_name,
                "last_name": i.friend.last_name,
                "status": i.status,
                "error_message": i.error_message,
                "created_at": i.created_at.isoformat() if i.created_at else None,
            }
            for i in items
        ],
    }


@router.post("/sync")
async def sync_contacts(db: Session = Depends(get_db)):
    from vkbottle import API

    if not settings.VK_USER_TOKEN:
        raise HTTPException(400, "VK_USER_TOKEN not configured")

    user_api = API(token=settings.VK_USER_TOKEN)
    now = datetime.utcnow()

    friends_data = await user_api.request(
        "friends.get", {"fields": "first_name,last_name,deactivated", "count": 5000}
    )
    friend_vk_ids = set()
    for item in friends_data["items"]:
        vk_id = item["id"]
        friend_vk_ids.add(vk_id)
        deactivated = item.get("deactivated")
        existing = db.query(VkFriend).filter(VkFriend.vk_user_id == vk_id).first()
        if existing:
            existing.first_name = item.get("first_name", "")
            existing.last_name = item.get("last_name", "")
            existing.is_deactivated = deactivated is not None
            existing.deactivated_reason = deactivated
            existing.synced_at = now
        else:
            db.add(VkFriend(
                vk_user_id=vk_id,
                first_name=item.get("first_name", ""),
                last_name=item.get("last_name", ""),
                is_deactivated=deactivated is not None,
                deactivated_reason=deactivated,
                synced_at=now,
            ))

    members_synced = 0
    if settings.VK_GROUP_TOKEN and settings.VK_GROUP_ID:
        group_api = API(token=settings.VK_GROUP_TOKEN)
        members_data = await group_api.request(
            "groups.getMembers",
            {"group_id": str(settings.VK_GROUP_ID), "fields": "first_name,last_name,deactivated"},
        )
        member_vk_ids = set()
        for item in members_data["items"]:
            vk_id = item["id"]
            member_vk_ids.add(vk_id)
            deactivated = item.get("deactivated")
            existing = db.query(VkCommunityMember).filter(
                VkCommunityMember.vk_user_id == vk_id
            ).first()
            if existing:
                existing.first_name = item.get("first_name", "")
                existing.last_name = item.get("last_name", "")
                existing.is_deactivated = deactivated is not None
                existing.deactivated_reason = deactivated
                existing.synced_at = now
            else:
                db.add(VkCommunityMember(
                    vk_user_id=vk_id,
                    first_name=item.get("first_name", ""),
                    last_name=item.get("last_name", ""),
                    is_deactivated=deactivated is not None,
                    deactivated_reason=deactivated,
                    synced_at=now,
                ))
        members_synced = len(member_vk_ids)

    db.commit()
    return {"friends_synced": len(friend_vk_ids), "members_synced": members_synced}


class InviteSelectedRequest(BaseModel):
    friend_ids: List[int]
    daily_limit: int = settings.VK_INVITE_DAILY_LIMIT
    delay_seconds: int = settings.VK_INVITE_DELAY_SECONDS


@router.post("/invite/selected")
async def invite_selected(req: InviteSelectedRequest, db: Session = Depends(get_db)):
    if req.daily_limit < 0 or req.daily_limit > 40:
        raise HTTPException(400, "Daily limit must be between 0 and 40")
    if req.delay_seconds < 1 or req.delay_seconds > 60:
        raise HTTPException(400, "Delay must be between 1 and 60 seconds")

    from src.celery_app import invite_vk_friends_selected
    task = invite_vk_friends_selected.delay(req.friend_ids, req.daily_limit, req.delay_seconds)
    return {"task_id": task.id, "status": "started", "count": len(req.friend_ids)}


@router.post("/invite/start")
async def start_invite_task(
    daily_limit: int = Query(settings.VK_INVITE_DAILY_LIMIT, ge=0, le=40),
    delay_seconds: int = Query(settings.VK_INVITE_DELAY_SECONDS, ge=1, le=60),
):
    from src.celery_app import invite_vk_friends
    task = invite_vk_friends.delay(daily_limit, delay_seconds)
    return {"task_id": task.id, "status": "started"}
