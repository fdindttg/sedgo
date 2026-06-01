from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db, Channel, Endpoint
from schemas import ChannelCreate, ChannelUpdate, EndpointCreate, EndpointUpdate
from middleware.auth_middleware import get_admin_user
from database import User

router = APIRouter(prefix="/api/channels", tags=["channels"])


# ── Channel Routes ──

@router.get("/")
def list_channels(db: Session = Depends(get_db)):
    channels = db.query(Channel).filter(Channel.is_active == True).order_by(Channel.priority.desc()).all()
    return [{
        "id": c.id,
        "name": c.name,
        "provider": c.provider,
        "api_base_url": c.api_base_url,
        "project_name": c.project_name,
        "priority": c.priority,
        "is_active": c.is_active,
    } for c in channels]


@router.get("/{channel_id}")
def get_channel(channel_id: int, db: Session = Depends(get_db)):
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    # 获取该渠道的接入点列表
    endpoints = db.query(Endpoint).filter(Endpoint.channel_id == channel_id, Endpoint.is_active == True).all()
    
    return {
        "id": channel.id,
        "name": channel.name,
        "provider": channel.provider,
        "api_base_url": channel.api_base_url,
        "file_url": channel.file_url,
        "task_url": channel.task_url,
        "project_id": channel.project_id,
        "portrait_group_id": channel.portrait_group_id,
        "public_base_url": channel.public_base_url,
        "project_name": channel.project_name,
        "priority": channel.priority,
        "is_active": channel.is_active,
        "created_at": channel.created_at,
        "updated_at": channel.updated_at,
        "endpoints": [{
            "id": e.id,
            "endpoint_id": e.endpoint_id,
            "endpoint_name": e.endpoint_name,
            "endpoint_url": e.endpoint_url,
            "type": e.type,
            "models": e.models,
            "is_default": e.is_default,
            "is_active": e.is_active,
        } for e in endpoints],
    }


@router.post("/")
def create_channel(
    data: ChannelCreate,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    from services.auth_service import encrypt_value
    
    channel = Channel(
        name=data.name,
        provider=data.provider,
        api_base_url=data.api_base_url,
        file_url=data.file_url,
        task_url=data.task_url,
        ak_encrypted=encrypt_value(data.ak) if data.ak else None,
        sk_encrypted=encrypt_value(data.sk) if data.sk else None,
        api_key_encrypted=encrypt_value(data.api_key) if data.api_key else None,
        project_id=data.project_id,
        portrait_group_id=data.portrait_group_id,
        public_base_url=data.public_base_url,
        project_name=data.project_name,
        priority=data.priority,
        is_active=data.is_active,
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return {"id": channel.id, "name": channel.name, "message": "Channel created"}


@router.put("/{channel_id}")
def update_channel(
    channel_id: int,
    data: ChannelUpdate,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    from services.auth_service import encrypt_value
    
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    if data.name is not None:
        channel.name = data.name
    if data.api_base_url is not None:
        channel.api_base_url = data.api_base_url
    if data.file_url is not None:
        channel.file_url = data.file_url
    if data.task_url is not None:
        channel.task_url = data.task_url
    if data.ak is not None:
        channel.ak_encrypted = encrypt_value(data.ak)
    if data.sk is not None:
        channel.sk_encrypted = encrypt_value(data.sk)
    if data.api_key is not None:
        channel.api_key_encrypted = encrypt_value(data.api_key)
    if data.project_id is not None:
        channel.project_id = data.project_id
    if data.portrait_group_id is not None:
        channel.portrait_group_id = data.portrait_group_id
    if data.public_base_url is not None:
        channel.public_base_url = data.public_base_url
    if data.project_name is not None:
        channel.project_name = data.project_name
    if data.priority is not None:
        channel.priority = data.priority
    if data.is_active is not None:
        channel.is_active = data.is_active
    
    db.commit()
    return {"id": channel.id, "name": channel.name, "message": "Channel updated"}


@router.delete("/{channel_id}")
def delete_channel(
    channel_id: int,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    channel.is_active = False
    db.commit()
    return {"message": "Channel deactivated"}


# ── Endpoint Routes ──

@router.get("/{channel_id}/endpoints")
def list_endpoints(channel_id: int, db: Session = Depends(get_db)):
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    endpoints = db.query(Endpoint).filter(Endpoint.channel_id == channel_id, Endpoint.is_active == True).all()
    return [{
        "id": e.id,
        "channel_id": e.channel_id,
        "endpoint_id": e.endpoint_id,
        "endpoint_name": e.endpoint_name,
        "endpoint_url": e.endpoint_url,
        "type": e.type,
        "models": e.models,
        "is_default": e.is_default,
        "is_active": e.is_active,
        "created_at": e.created_at,
    } for e in endpoints]


@router.get("/{channel_id}/endpoints/{endpoint_id}")
def get_endpoint(channel_id: int, endpoint_id: int, db: Session = Depends(get_db)):
    endpoint = db.query(Endpoint).filter(Endpoint.id == endpoint_id, Endpoint.channel_id == channel_id).first()
    if not endpoint:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    
    return {
        "id": endpoint.id,
        "channel_id": endpoint.channel_id,
        "endpoint_id": endpoint.endpoint_id,
        "endpoint_name": endpoint.endpoint_name,
        "endpoint_url": endpoint.endpoint_url,
        "type": endpoint.type,
        "models": endpoint.models,
        "is_default": endpoint.is_default,
        "is_active": endpoint.is_active,
        "created_at": endpoint.created_at,
        "updated_at": endpoint.updated_at,
    }


@router.post("/{channel_id}/endpoints")
def create_endpoint(
    channel_id: int,
    data: EndpointCreate,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    # 如果设置为默认接入点，取消其他默认接入点
    if data.is_default:
        db.query(Endpoint).filter(Endpoint.channel_id == channel_id, Endpoint.is_default == True).update({"is_default": False})
    
    endpoint = Endpoint(
        channel_id=channel_id,
        endpoint_id=data.endpoint_id,
        endpoint_name=data.endpoint_name,
        endpoint_url=data.endpoint_url,
        type=data.type,
        models=data.models,
        is_default=data.is_default,
        is_active=data.is_active,
    )
    db.add(endpoint)
    db.commit()
    db.refresh(endpoint)
    return {"id": endpoint.id, "endpoint_id": endpoint.endpoint_id, "message": "Endpoint created"}


@router.put("/{channel_id}/endpoints/{endpoint_id}")
def update_endpoint(
    channel_id: int,
    endpoint_id: int,
    data: EndpointUpdate,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    endpoint = db.query(Endpoint).filter(Endpoint.id == endpoint_id, Endpoint.channel_id == channel_id).first()
    if not endpoint:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    
    if data.endpoint_id is not None:
        endpoint.endpoint_id = data.endpoint_id
    if data.endpoint_name is not None:
        endpoint.endpoint_name = data.endpoint_name
    if data.endpoint_url is not None:
        endpoint.endpoint_url = data.endpoint_url
    if data.type is not None:
        endpoint.type = data.type
    if data.models is not None:
        endpoint.models = data.models
    if data.is_default is not None:
        endpoint.is_default = data.is_default
        # 如果设置为默认接入点，取消其他默认接入点
        if data.is_default:
            db.query(Endpoint).filter(
                Endpoint.channel_id == channel_id, 
                Endpoint.id != endpoint_id,
                Endpoint.is_default == True
            ).update({"is_default": False})
    if data.is_active is not None:
        endpoint.is_active = data.is_active
    
    db.commit()
    return {"id": endpoint.id, "endpoint_id": endpoint.endpoint_id, "message": "Endpoint updated"}


@router.delete("/{channel_id}/endpoints/{endpoint_id}")
def delete_endpoint(
    channel_id: int,
    endpoint_id: int,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    endpoint = db.query(Endpoint).filter(Endpoint.id == endpoint_id, Endpoint.channel_id == channel_id).first()
    if not endpoint:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    
    endpoint.is_active = False
    db.commit()
    return {"message": "Endpoint deactivated"}