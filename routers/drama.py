"""
短剧工作室 API 路由

提供完整的短剧创作工作流：
1. 项目管理（CRUD）
2. 剧本自动生成（策划 Agent）
3. 分镜拆解（导演 Agent）
4. 批量视频生成提交
5. 审片与成片导出
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import (
    get_db, User, DramaProject, DramaEpisode, DramaScene,
    DramaStatus, TaskRecord, TaskStatus, Channel
)
from middleware.auth_middleware import get_current_user
from services.drama_service import (
    generate_script_outline,
    breakdown_to_scenes,
    assign_character_seeds,
    review_scene_quality,
    select_best_candidate,
    build_export_manifest,
    create_project,
    create_episode_from_script,
    create_scenes_from_breakdown,
    submit_scene_tasks,
    SHORT_DRAMA_GENRES,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/drama", tags=["短剧工作室"])


# ═══════════════════════════════════════════════════════════════════
# Pydantic Schemas
# ═══════════════════════════════════════════════════════════════════

class ProjectCreate(BaseModel):
    title: str
    genre: str = "逆袭"
    logline: str = ""
    total_episodes: int = 10


class ProjectUpdate(BaseModel):
    title: Optional[str] = None
    genre: Optional[str] = None
    logline: Optional[str] = None
    total_episodes: Optional[int] = None


class ScriptGenerateRequest(BaseModel):
    """剧本生成请求（按集）"""
    episode_numbers: Optional[list[int]] = None  # None=全部


class SceneRenderRequest(BaseModel):
    """场景渲染请求"""
    episode_ids: Optional[list[int]] = None
    scene_ids: Optional[list[int]] = None
    channel_id: Optional[int] = None
    model: str = ""
    resolution: str = "720p"
    ratio: str = "9:16"
    duration: str = "60s"
    ref_mode: str = "text2vid"
    subtitle_removal: bool = False
    use_real_people: bool = False


class SceneSelectRequest(BaseModel):
    """选择最佳候选视频"""
    scene_id: int
    video_url: str


# ═══════════════════════════════════════════════════════════════════
# 项目 CRUD
# ═══════════════════════════════════════════════════════════════════

@router.get("/genres")
def list_genres():
    """获取支持的短剧类型列表"""
    return {"genres": SHORT_DRAMA_GENRES}


@router.post("/projects")
def create_drama_project(
    data: ProjectCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建短剧项目"""
    if data.genre not in SHORT_DRAMA_GENRES:
        raise HTTPException(status_code=400, detail=f"不支持的短剧类型：{data.genre}，可选：{SHORT_DRAMA_GENRES}")
    
    project = create_project(db, user.id, data.title, data.genre, data.logline, data.total_episodes)
    
    return {
        "id": project.id,
        "title": project.title,
        "genre": project.genre,
        "logline": project.logline,
        "total_episodes": project.total_episodes,
        "status": project.status.value,
        "created_at": project.created_at.isoformat() if project.created_at else None,
    }


@router.get("/projects")
def list_drama_projects(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取用户的所有短剧项目"""
    projects = db.query(DramaProject).filter(
        DramaProject.user_id == user.id
    ).order_by(DramaProject.updated_at.desc()).all()
    
    return {
        "projects": [{
            "id": p.id,
            "title": p.title,
            "genre": p.genre,
            "logline": p.logline,
            "total_episodes": p.total_episodes,
            "episode_count": len(p.episodes) if p.episodes else 0,
            "status": p.status.value,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        } for p in projects]
    }


@router.get("/projects/{project_id}")
def get_drama_project(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取项目详情（含剧集列表）"""
    project = db.query(DramaProject).filter(
        DramaProject.id == project_id,
        DramaProject.user_id == user.id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    episodes = db.query(DramaEpisode).filter(
        DramaEpisode.project_id == project_id
    ).order_by(DramaEpisode.episode_number).all()
    
    return {
        "id": project.id,
        "title": project.title,
        "genre": project.genre,
        "logline": project.logline,
        "total_episodes": project.total_episodes,
        "status": project.status.value,
        "episodes": [{
            "id": ep.id,
            "episode_number": ep.episode_number,
            "title": ep.title,
            "hook": ep.hook,
            "cliffhanger": ep.cliffhanger,
            "scene_count": len(ep.scenes) if ep.scenes else 0,
            "status": ep.status.value,
            "created_at": ep.created_at.isoformat() if ep.created_at else None,
        } for ep in episodes],
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
    }


@router.put("/projects/{project_id}")
def update_drama_project(
    project_id: int,
    data: ProjectUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新项目信息"""
    project = db.query(DramaProject).filter(
        DramaProject.id == project_id,
        DramaProject.user_id == user.id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    if data.title is not None:
        project.title = data.title
    if data.genre is not None:
        project.genre = data.genre
    if data.logline is not None:
        project.logline = data.logline
    if data.total_episodes is not None:
        project.total_episodes = data.total_episodes
    
    db.commit()
    return {"success": True, "message": "项目已更新"}


@router.delete("/projects/{project_id}")
def delete_drama_project(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除项目"""
    project = db.query(DramaProject).filter(
        DramaProject.id == project_id,
        DramaProject.user_id == user.id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    db.delete(project)
    db.commit()
    return {"success": True, "message": "项目已删除"}


# ═══════════════════════════════════════════════════════════════════
# 剧本策划 Agent API
# ═══════════════════════════════════════════════════════════════════

@router.post("/projects/{project_id}/generate-script")
def generate_script(
    project_id: int,
    data: ScriptGenerateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    剧本策划 Agent：根据项目类型和梗概，自动生成结构化剧本
    
    按四幕结构生成每集内容，包含：
    - 黄金3秒钩子
    - 情绪走势
    - 勾人卡点
    """
    project = db.query(DramaProject).filter(
        DramaProject.id == project_id,
        DramaProject.user_id == user.id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    # 生成剧本大纲
    outline = generate_script_outline(
        genre=project.genre,
        logline=project.logline or "",
        total_episodes=project.total_episodes,
    )
    
    # 筛选需要生成的集数
    target_eps = data.episode_numbers or list(range(1, project.total_episodes + 1))
    
    created_episodes = []
    for ep_data in outline["episodes"]:
        if ep_data["number"] not in target_eps:
            continue
        
        # 检查是否已存在
        existing = db.query(DramaEpisode).filter(
            DramaEpisode.project_id == project_id,
            DramaEpisode.episode_number == ep_data["number"]
        ).first()
        if existing:
            # 更新已有剧集
            existing.script_content = {"acts": ep_data.get("acts", [])}
            existing.emotion_arc = ep_data.get("emotion_arc", [])
            existing.cliffhanger = ep_data.get("cliffhanger", "")
            existing.hook = ep_data.get("hook", "")
            existing.title = ep_data.get("title", existing.title)
            existing.status = DramaStatus.DRAFT
            db.commit()
            created_episodes.append(existing)
        else:
            episode = create_episode_from_script(db, project_id, ep_data)
            created_episodes.append(episode)
    
    # 更新项目状态
    project.status = DramaStatus.DRAFT
    db.commit()
    
    return {
        "success": True,
        "message": f"已生成 {len(created_episodes)} 集剧本",
        "episodes": [{
            "id": ep.id,
            "episode_number": ep.episode_number,
            "title": ep.title,
            "hook": ep.hook,
            "cliffhanger": ep.cliffhanger,
            "status": ep.status.value,
        } for ep in created_episodes],
    }


@router.get("/episodes/{episode_id}")
def get_episode_detail(
    episode_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取剧集详情（含完整剧本和场景）"""
    episode = db.query(DramaEpisode).filter(DramaEpisode.id == episode_id).first()
    if not episode:
        raise HTTPException(status_code=404, detail="剧集不存在")
    
    project = db.query(DramaProject).filter(DramaProject.id == episode.project_id).first()
    if not project or project.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问")
    
    scenes = db.query(DramaScene).filter(
        DramaScene.episode_id == episode_id
    ).order_by(DramaScene.scene_number).all()
    
    return {
        "id": episode.id,
        "project_id": episode.project_id,
        "episode_number": episode.episode_number,
        "title": episode.title,
        "hook": episode.hook,
        "cliffhanger": episode.cliffhanger,
        "emotion_arc": episode.emotion_arc,
        "script_content": episode.script_content,
        "status": episode.status.value,
        "scenes": [{
            "id": s.id,
            "scene_number": s.scene_number,
            "location": s.location,
            "time_period": s.time_period,
            "characters": s.characters,
            "camera_instruction": s.camera_instruction,
            "prompt_text": s.prompt_text,
            "character_seeds": s.character_seeds,
            "duration": s.duration,
            "status": s.status.value,
            "video_urls": s.video_urls,
            "selected_url": s.selected_url,
            "quality_score": s.quality_score,
            "has_defect": s.has_defect,
            "retry_count": s.retry_count,
        } for s in scenes],
        "created_at": episode.created_at.isoformat() if episode.created_at else None,
    }


# ═══════════════════════════════════════════════════════════════════
# 分镜导演 Agent API
# ═══════════════════════════════════════════════════════════════════

@router.post("/episodes/{episode_id}/breakdown")
def breakdown_episode(
    episode_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    分镜导演 Agent：将文学剧本拆解为结构化分镜场景
    
    生成每个镜头的位置、角色、运镜、提示词
    自动分配角色 Seed 确保跨镜头一致性
    """
    episode = db.query(DramaEpisode).filter(DramaEpisode.id == episode_id).first()
    if not episode:
        raise HTTPException(status_code=404, detail="剧集不存在")
    
    project = db.query(DramaProject).filter(DramaProject.id == episode.project_id).first()
    if not project or project.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问")
    
    if not episode.script_content:
        raise HTTPException(status_code=400, detail="请先生成剧本")
    
    # 获取默认模型（从场景配置中读取）
    model = ""
    
    # 拆解为分镜
    scenes_data = breakdown_to_scenes(
        episode=episode,
        genre=project.genre,
        model=model,
    )
    
    # 分配角色 Seed
    scenes_data = assign_character_seeds(scenes_data)
    
    # 删除旧的分镜（如果有）
    db.query(DramaScene).filter(DramaScene.episode_id == episode_id).delete()
    db.commit()
    
    # 创建新分镜
    scenes = create_scenes_from_breakdown(db, episode_id, scenes_data)
    
    episode.status = DramaStatus.DRAFT
    db.commit()
    
    return {
        "success": True,
        "message": f"已生成 {len(scenes)} 个分镜场景",
        "scenes": [{
            "id": s.id,
            "scene_number": s.scene_number,
            "prompt_text": s.prompt_text,
            "duration": s.duration,
        } for s in scenes],
    }


# ═══════════════════════════════════════════════════════════════════
# 视频生成 API（调用现有视频生成引擎）
# ═══════════════════════════════════════════════════════════════════

@router.post("/render")
def render_scenes(
    data: SceneRenderRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    批量提交场景渲染任务
    
    将分镜场景提交到视频生成引擎进行批量渲染
    核心场景（高潮/打斗）自动生成2个候选
    """
    # 确定要渲染的场景
    query = db.query(DramaScene).join(DramaEpisode).join(DramaProject)
    
    if data.scene_ids:
        query = query.filter(DramaScene.id.in_(data.scene_ids))
    elif data.episode_ids:
        query = query.filter(DramaScene.episode_id.in_(data.episode_ids))
    else:
        raise HTTPException(status_code=400, detail="请指定要渲染的场景或剧集")
    
    # 确保属于当前用户
    query = query.filter(DramaProject.user_id == user.id)
    
    scenes = query.order_by(DramaScene.episode_id, DramaScene.scene_number).all()
    if not scenes:
        raise HTTPException(status_code=404, detail="未找到需要渲染的场景")
    
    # 确定使用的渠道
    channel = None
    if data.channel_id:
        channel = db.query(Channel).filter(
            Channel.id == data.channel_id,
            Channel.is_active == True
        ).first()
        if not channel:
            raise HTTPException(status_code=400, detail="指定的渠道不可用")
    
    # 如果 model 为空，自动获取第一个活跃的视频接入点
    model_id = data.model
    if not model_id:
        from database import Endpoint, EndpointType
        default_ep = db.query(Endpoint).filter(
            Endpoint.is_active == True,
            Endpoint.type == EndpointType.VIDEO
        ).order_by(Endpoint.is_default.desc()).first()
        if default_ep:
            model_id = default_ep.endpoint_id
            logger.info(f"[drama] Auto-selected default endpoint: {model_id}")
        else:
            raise HTTPException(status_code=400, detail="没有可用的视频接入点，请先在管理后台配置")
    
    # 构建基础任务配置
    task_config_base = {
        "model": model_id,
        "resolution": data.resolution,
        "ratio": data.ratio,
        "duration": data.duration,
        "ref_mode": data.ref_mode,
        "subtitle_removal": data.subtitle_removal,
        "use_real_people": data.use_real_people,
        "generate_audio": True,
        "watermark": False,
    }
    
    # 提交任务（现有视频生成引擎）
    task_results = submit_scene_tasks(
        db=db,
        scenes=scenes,
        user_id=user.id,
        channel_id=channel.id if channel else 0,
        task_config_base=task_config_base,
    )
    
    return {
        "success": True,
        "message": f"已提交 {len(task_results)} 个渲染任务",
        "tasks": [{
            "scene_id": scene_id,
            "task_id": task_id,
        } for scene_id, task_id in task_results],
    }


# ═══════════════════════════════════════════════════════════════════
# 审片与导出 API
# ═══════════════════════════════════════════════════════════════════

@router.post("/scenes/{scene_id}/review")
def review_scene(
    scene_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    智能审片 Agent：质量初审
    
    检查视频是否存在缺陷，并给出质量评分
    """
    scene = db.query(DramaScene).filter(DramaScene.id == scene_id).first()
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")
    
    episode = db.query(DramaEpisode).filter(DramaEpisode.id == scene.episode_id).first()
    project = db.query(DramaProject).filter(DramaProject.id == episode.project_id).first()
    if project.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问")
    
    result = review_scene_quality(scene)
    
    # 更新场景质量标注
    scene.quality_score = result["quality_score"]
    scene.has_defect = result["has_defect"]
    db.commit()
    
    return {"scene_id": scene_id, **result}


@router.post("/scenes/{scene_id}/select")
def select_scene_video(
    scene_id: int,
    data: SceneSelectRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """从候选中选择最佳视频"""
    scene = db.query(DramaScene).filter(DramaScene.id == scene_id).first()
    if not scene:
        raise HTTPException(status_code=404, detail="场景不存在")
    
    episode = db.query(DramaEpisode).filter(DramaEpisode.id == scene.episode_id).first()
    project = db.query(DramaProject).filter(DramaProject.id == episode.project_id).first()
    if project.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问")
    
    if data.video_url not in (scene.video_urls or []):
        raise HTTPException(status_code=400, detail="所选视频不在候选列表中")
    
    scene.selected_url = data.video_url
    scene.status = DramaStatus.COMPLETED
    db.commit()
    
    return {"success": True, "message": "已选择视频"}


@router.get("/episodes/{episode_id}/export")
def export_episode(
    episode_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    成片导出 Agent：生成剪辑清单
    
    将所有选中的视频片段按顺序排列，输出成片清单
    """
    episode = db.query(DramaEpisode).filter(DramaEpisode.id == episode_id).first()
    if not episode:
        raise HTTPException(status_code=404, detail="剧集不存在")
    
    project = db.query(DramaProject).filter(DramaProject.id == episode.project_id).first()
    if project.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问")
    
    scenes = db.query(DramaScene).filter(
        DramaScene.episode_id == episode_id
    ).order_by(DramaScene.scene_number).all()
    
    # 自动为未选择的场景选择最佳候选
    for scene in scenes:
        if not scene.selected_url and scene.video_urls:
            best = select_best_candidate(scene)
            if best:
                scene.selected_url = best
                scene.status = DramaStatus.COMPLETED
    db.commit()
    
    manifest = build_export_manifest(episode, scenes)
    
    return manifest


@router.get("/projects/{project_id}/export")
def export_project(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    批量导出：返回项目所有剧集的剪辑清单（含视频下载地址）
    """
    project = db.query(DramaProject).filter(
        DramaProject.id == project_id,
        DramaProject.user_id == user.id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    episodes = db.query(DramaEpisode).filter(
        DramaEpisode.project_id == project_id
    ).order_by(DramaEpisode.episode_number).all()
    
    episodes_export = []
    for ep in episodes:
        scenes = db.query(DramaScene).filter(
            DramaScene.episode_id == ep.id
        ).order_by(DramaScene.scene_number).all()
        
        # 自动选择最佳候选
        for scene in scenes:
            if not scene.selected_url and scene.video_urls:
                best = select_best_candidate(scene)
                if best:
                    scene.selected_url = best
                    scene.status = DramaStatus.COMPLETED
        db.commit()
        
        manifest = build_export_manifest(ep, scenes)
        episodes_export.append(manifest)
    
    return {
        "project_id": project.id,
        "title": project.title,
        "genre": project.genre,
        "total_episodes": len(episodes_export),
        "episodes": episodes_export,
    }


# ═══════════════════════════════════════════════════════════════════
# 场景任务状态同步
# ═══════════════════════════════════════════════════════════════════

@router.get("/tasks/sync")
def sync_tasks_status(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    同步场景关联的任务状态到场景本身
    
    当前端轮询到任务完成时，调用此接口更新场景
    """
    # 查找所有正在生成中的场景
    generating_scenes = db.query(DramaScene).filter(
        DramaScene.status == DramaStatus.GENERATING,
        DramaScene.task_record_ids != None,
    ).join(DramaEpisode).join(DramaProject).filter(
        DramaProject.user_id == user.id
    ).all()
    
    updated = []
    for scene in generating_scenes:
        task_ids = scene.task_record_ids or []
        completed_urls = []
        all_done = True
        
        for task_id in task_ids:
            task = db.query(TaskRecord).filter(TaskRecord.id == task_id).first()
            if not task:
                continue
            if task.status == TaskStatus.SUCCESS and task.video_url:
                completed_urls.append(task.video_url)
            elif task.status in (TaskStatus.PENDING, TaskStatus.PROCESSING):
                all_done = False
            elif task.status == TaskStatus.FAILED:
                scene.error_msg = task.error_msg
        
        if completed_urls:
            scene.video_urls = completed_urls
        
        if all_done and completed_urls:
            scene.status = DramaStatus.COMPLETED
            # 自动选择第一个
            if not scene.selected_url:
                scene.selected_url = completed_urls[-1]
            updated.append(scene.id)
        elif all_done and not completed_urls:
            scene.status = DramaStatus.FAILED
            updated.append(scene.id)
    
    db.commit()
    
    return {
        "synced": len(updated),
        "updated_scene_ids": updated,
    }
