"""资产库管理路由 - 对接火山引擎 BytePlus 真实素材库 API"""
import json
import requests
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db, User
from middleware.auth_middleware import get_current_user

router = APIRouter(prefix="/api/assets", tags=["资产库"])

# 从数据库读取配置（首次初始化时可从环境变量读取）
_REGION = "ap-southeast-1"
_SERVICE = "ark"
_HOST = "open.ap-southeast-1.byteplusapi.com"
_VERSION = "2024-01-01"
_FILE_URL = "https://ark.ap-southeast.bytepluses.com/api/v3/files"


def _call_api(action: str, body: dict) -> dict:
    from volcengine.base.Request import Request
    from volcengine.Credentials import Credentials
    from volcengine.auth.SignerV4 import SignerV4

    body_bytes = json.dumps(body, separators=(",", ":")).encode("utf-8")
    r = Request()
    r.method = "POST"
    r.host = _HOST
    r.path = "/"
    r.query = {"Action": action, "Version": _VERSION}
    r.body = body_bytes
    r.headers = {"Host": _HOST, "Content-Type": "application/json"}

    SignerV4.sign(r, Credentials(_AK, _SK, _SERVICE, _REGION))
    resp = requests.post(
        f"https://{_HOST}/", headers=r.headers, params=r.query, data=body_bytes, timeout=15
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("Result", data)


def _format_assets(items: list) -> list:
    return [
        {
            "id": it["Id"],
            "name": it.get("Name") or it["Id"],
            "url": it.get("URL", ""),
            "status": it.get("Status", ""),
            "group_id": it.get("GroupId", ""),
            "asset_type": it.get("AssetType", "Image"),
        }
        for it in items
    ]


def _get_bearer_token(db) -> str:
    from database import Channel
    from services.auth_service import decrypt_value
    import os
    channel = db.query(Channel).filter(Channel.is_active == True).order_by(Channel.priority.desc()).first()
    if channel and channel.api_key_encrypted:
        try:
            return decrypt_value(channel.api_key_encrypted)
        except Exception:
            pass
    # 后备：从环境变量读取（首次初始化时使用）
    return os.getenv("SD_BYTEPLUS_API_KEY", "")


@router.get("/byteplus/portraits")
async def get_byteplus_portraits(
    page: int = 1,
    page_size: int = 20,
    group_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取真人肖像库资产列表 (GroupType=LivenessFace)"""
    try:
        body: dict = {
            "Filter": {"GroupType": "LivenessFace", "Statuses": ["Active"]},
            "PageNumber": page,
            "PageSize": page_size,
        }
        if group_id:
            body["Filter"]["GroupIds"] = [group_id]
        data = _call_api("ListAssets", body)
        items = _format_assets(data.get("Items", []))
        return {"success": True, "data": items, "total": data.get("TotalCount", len(items))}
    except Exception as e:
        return {"success": True, "data": [], "total": 0, "error": str(e)}


@router.get("/byteplus/avatars")
async def get_byteplus_avatars(
    page: int = 1,
    page_size: int = 20,
    group_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取虚拟人资产库列表 (GroupType=AIGC)"""
    try:
        body: dict = {
            "Filter": {"GroupType": "AIGC", "Statuses": ["Active"]},
            "PageNumber": page,
            "PageSize": page_size,
        }
        if group_id:
            body["Filter"]["GroupIds"] = [group_id]
        data = _call_api("ListAssets", body)
        items = _format_assets(data.get("Items", []))
        return {"success": True, "data": items, "total": data.get("TotalCount", len(items))}
    except Exception as e:
        return {"success": True, "data": [], "total": 0, "error": str(e)}


@router.get("/byteplus/groups")
async def get_asset_groups(
    group_type: str = "AIGC",
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取资产分组列表"""
    try:
        body = {
            "Filter": {"GroupType": group_type},
            "PageNumber": page,
            "PageSize": page_size,
        }
        data = _call_api("ListAssetGroups", body)
        items = data.get("Items", [])
        groups = [
            {
                "id": it["Id"],
                "name": it.get("Name") or it.get("Title") or it["Id"],
                "description": it.get("Description", ""),
                "group_type": it.get("GroupType", ""),
            }
            for it in items
        ]
        return {"success": True, "data": groups, "total": data.get("TotalCount", len(groups))}
    except Exception as e:
        return {"success": True, "data": [], "total": 0, "error": str(e)}


class CreateGroupBody(BaseModel):
    name: str
    group_type: str = "AIGC"  # AIGC=虚拟人, LivenessFace=真人


@router.post("/byteplus/create-group")
async def create_asset_group(
    body: CreateGroupBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建素材分组"""
    try:
        data = _call_api("CreateAssetGroup", {
            "Name": body.name,
            "GroupType": body.group_type,
            "ProjectName": "default",
        })
        err = data.get("ResponseMetadata", {}).get("Error")
        if err:
            return JSONResponse({"success": False, "message": err.get("Message", "创建失败")}, status_code=400)
        return {"success": True, "group_id": data.get("Id")}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@router.post("/byteplus/upload-asset")
async def upload_to_asset_library(
    file: UploadFile = File(...),
    group_id: str = "",
    group_type: str = "AIGC",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """上传文件到火山引擎素材库: 先上传到 Files API 获得 URL，再调 CreateAsset"""
    try:
        content = await file.read()
        bearer = _get_bearer_token(db)
        if not bearer:
            return JSONResponse({"success": False, "message": "未配置 API Key"}, status_code=400)

        # Step 1: 上传到 BytePlus Files API 获取可访问 URL
        file_resp = requests.post(
            _FILE_URL,
            headers={"Authorization": f"Bearer {bearer}"},
            data={"purpose": "user_data"},
            files={"file": (file.filename, content, file.content_type)},
            timeout=120,
        )
        if file_resp.status_code != 200:
            return JSONResponse({"success": False, "message": f"文件上传失败: {file_resp.text}"}, status_code=400)

        file_data = file_resp.json()
        file_url = file_data.get("url") or file_data.get("data", {}).get("url", "")
        if not file_url:
            return JSONResponse({"success": False, "message": "未获取到文件 URL"}, status_code=400)

        # Step 2: 如果没有 group_id，先创建默认分组
        if not group_id:
            group_name = "默认分组" if group_type == "AIGC" else "真人肖像默认组"
            try:
                g = _call_api("CreateAssetGroup", {
                    "Name": group_name,
                    "GroupType": group_type,
                    "ProjectName": "default",
                })
                group_id = g.get("Id", "")
            except Exception:
                pass

        if not group_id:
            return JSONResponse({"success": False, "message": "素材库分组创建失败，请先在火山引擎控制台创建分组"}, status_code=400)

        # Step 3: 调用 CreateAsset 注册到素材库
        asset_type = "Image" if file.content_type and file.content_type.startswith("image") else "Video"
        asset_data = _call_api("CreateAsset", {
            "GroupId": group_id,
            "URL": file_url,
            "AssetType": asset_type,
            "Name": file.filename or "",
            "ProjectName": "default",
        })

        err = asset_data.get("ResponseMetadata", {}).get("Error")
        if err:
            return JSONResponse({"success": False, "message": err.get("Message", "素材创建失败")}, status_code=400)

        asset_id = asset_data.get("Id", "")
        return {
            "success": True,
            "asset_id": asset_id,
            "asset_uri": f"asset://{asset_id}",
            "group_id": group_id,
            "file_url": file_url,
            "message": "上传成功，素材审核中，Active 后可使用",
        }
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)
