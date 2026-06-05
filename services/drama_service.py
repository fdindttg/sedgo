"""
短剧工作室 Agent 服务层

包含三大 Agent：
1. 剧本策划 Agent — 根据用户灵感生成结构化短剧剧本（四幕结构）
2. 分镜导演 Agent — 将文学剧本拆解为视听语言提示词
3. 智能审片与剪辑 Agent — 质量检查 + 自动重跑 + 成片导出
"""

import json
import logging
import random
import time
from typing import Optional
from sqlalchemy.orm import Session

from database import (
    DramaProject, DramaEpisode, DramaScene, DramaSceneTask,
    DramaStatus, TaskRecord, TaskStatus
)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# 常量定义
# ═══════════════════════════════════════════════════════════════════

SHORT_DRAMA_GENRES = [
    "逆袭", "重生", "霸总", "甜宠", "穿越", "古装", "悬疑", "都市"
]

FOUR_ACT_STRUCTURE = [
    {"act": 1, "name": "建置强冲突", "ratio": 0.25,
     "desc": "快速建立主角身份、困境和核心冲突，黄金3秒抛出钩子"},
    {"act": 2, "name": "单元矛盾升级", "ratio": 0.30,
     "desc": "冲突不断升级，配角施压，主角隐忍或小规模反击"},
    {"act": 3, "name": "绝境危机", "ratio": 0.25,
     "desc": "主角陷入最大危机，看似无解，情绪降至最低点"},
    {"act": 4, "name": "爽快反击", "ratio": 0.20,
     "desc": "主角绝地反击，揭开底牌，留下下集悬念"},
]

# 不同类型短剧的模板提示词
GENRE_TEMPLATES = {
    "逆袭": {
        "protagonist": "出身卑微但有一技之长的普通人",
        "antagonist": "看不起主角的权贵或上司",
        "core_conflict": "社会阶层歧视与个人价值证明",
        "emotion_arc": ["遭受白眼", "独自隐忍", "暗中布局", "一鸣惊人"],
    },
    "重生": {
        "protagonist": "拥有前世记忆的重生者",
        "antagonist": "前世坑害主角的反派",
        "core_conflict": "前世遗憾与今生逆天改命",
        "emotion_arc": ["前世惨死", "重生震惊", "预知布局", "爽快复仇"],
    },
    "霸总": {
        "protagonist": "冷酷多金的霸道总裁",
        "antagonist": "觊觎主角地位的竞争者",
        "core_conflict": "权力博弈与情感纠葛",
        "emotion_arc": ["偶遇交锋", "误会加深", "危机相救", "甜蜜反轉"],
    },
    "甜宠": {
        "protagonist": "温柔善良的普通人",
        "antagonist": "制造小误会的配角",
        "core_conflict": "甜蜜互动与小误会的消解",
        "emotion_arc": ["初见心动", "甜蜜互动", "小小误会", "和好升温"],
    },
    "穿越": {
        "protagonist": "意外穿越到古代/异世界的现代人",
        "antagonist": "古代权贵或敌对势力",
        "core_conflict": "现代思维与古代规则的碰撞",
        "emotion_arc": ["穿越震惊", "文化冲突", "智斗权贵", "开挂逆袭"],
    },
    "古装": {
        "protagonist": "身世神秘的江湖儿女",
        "antagonist": "反派门派或奸臣",
        "core_conflict": "江湖恩怨与家国大义",
        "emotion_arc": ["身世揭露", "被迫逃亡", "绝境突破", "快意恩仇"],
    },
    "悬疑": {
        "protagonist": "敏锐的侦探或普通人",
        "antagonist": "隐藏身份的幕后黑手",
        "core_conflict": "真相追寻与危险逼近",
        "emotion_arc": ["离奇事件", "深入调查", "身陷险境", "真相大白"],
    },
    "都市": {
        "protagonist": "在大城市打拼的年轻人",
        "antagonist": "职场对手或生活压力",
        "core_conflict": "现实困境与梦想追求",
        "emotion_arc": ["生活压力", "遭遇打击", "贵人相助", "逆风翻盘"],
    },
}

# 默认分镜运镜模板
CAMERA_TEMPLATES = [
    "面部特写，捕捉角色微表情变化",
    "中景跟拍，展现角色动作",
    "远景拉远，呈现环境氛围",
    "特写推进，强调关键道具/细节",
    "环绕镜头，突出角色气场",
    "低角度仰拍，强化角色压迫感",
    "高角度俯拍，展现角色脆弱感",
    "快速推镜，制造紧张感",
    "慢镜头拉远，情绪释放",
    "手持晃动镜头，增加真实感",
]


# ═══════════════════════════════════════════════════════════════════
# Agent 1: 剧本策划 Agent
# ═══════════════════════════════════════════════════════════════════

def generate_script_outline(
    genre: str,
    logline: str,
    total_episodes: int = 10
) -> dict:
    """
    根据类型和梗概生成剧本大纲（模拟 AI 生成）
    
    实际项目中可以替换为 LLM API 调用（如 DeepSeek / ChatGPT）
    
    返回结构化大纲：
    {
        "episodes": [
            {
                "number": 1,
                "title": "第1集标题",
                "hook": "黄金3秒钩子",
                "cliffhanger": "结尾悬念",
                "emotion_arc": [...],
                "acts": [
                    {"act": 1, "summary": "...", "scenes": [...]},
                    ...
                ]
            },
            ...
        ]
    }
    """
    template = GENRE_TEMPLATES.get(genre, GENRE_TEMPLATES["逆袭"])
    episodes = []
    
    # 前3集：快速吸引观众（钩子密集）
    # 中间集：展开冲突
    # 最后2集：推向高潮
    
    for ep_num in range(1, total_episodes + 1):
        ep = _generate_single_episode(
            ep_num, total_episodes, genre, logline, template
        )
        episodes.append(ep)
    
    return {
        "genre": genre,
        "logline": logline,
        "total_episodes": total_episodes,
        "episodes": episodes,
    }


def _generate_single_episode(
    ep_num: int,
    total: int,
    genre: str,
    logline: str,
    template: dict
) -> dict:
    """生成单集剧本"""
    phase = "开场" if ep_num <= 3 else ("高潮" if ep_num > total - 2 else "展开")
    
    # 钩子和悬念随剧集动态变化
    hook = _generate_hook(ep_num, phase, genre, template)
    cliffhanger = _generate_cliffhanger(ep_num, total, phase, genre)
    
    # 情绪走势
    emotion_arc = _generate_emotion_arc(ep_num, template["emotion_arc"])
    
    # 四幕结构
    acts = []
    for act_info in FOUR_ACT_STRUCTURE:
        act = _generate_act(act_info, ep_num, phase, genre, logline, template)
        acts.append(act)
    
    return {
        "number": ep_num,
        "title": f"第{ep_num}集{' '.join(random.sample(['风云起','暗流涌','惊变','绝境','反击','真相','迷局','破局','逆转','终章'], 1))}" if ep_num != 1 else f"第1集{'开局' if genre in ['逆袭','重生'] else '初遇' if genre in ['甜宠','霸总'] else '穿越'}",
        "hook": hook,
        "cliffhanger": cliffhanger,
        "emotion_arc": emotion_arc,
        "acts": acts,
    }


def _generate_hook(ep_num: int, phase: str, genre: str, template: dict) -> str:
    """生成黄金3秒钩子"""
    hooks = {
        "逆袭": [
            f"当着全公司的面，{template['protagonist']}被{template['antagonist']}泼了一身咖啡...",
            f"'你这种人，一辈子都不可能翻身！' — 话音刚落，{template['protagonist']}默默掏出了...",
            f"面试官将简历扔进垃圾桶：'我们不招{template['protagonist']}这种人。'",
            f"'这个项目价值一个亿，你敢接吗？'{template['protagonist']}抬头，眼神坚毅。",
        ],
        "霸总": [
            f"'爬出我的房间。'{template['protagonist']}冷冷说道，{template['antagonist']}跪在地上...",
            f"整个城市都在找的男人，此刻正单膝跪地给她系鞋带。",
            f"合同上写着'契约婚姻一年'，她不知道这场游戏早已失控。",
        ],
        "甜宠": [
            f"第一次见面，他就把她的奶茶撞翻了。'我赔你。'他说。她不知道这一赔就是一辈子。",
            f"她随手在许愿树上挂了条红绳，第二天整个校园都挂满了她的照片。",
            f"'我们结婚吧。'认识第三天，他对她说。所有人都觉得他疯了，除了他自己。",
        ],
    }
    
    genre_hooks = hooks.get(genre)
    if genre_hooks:
        return random.choice(genre_hooks)
    return f"{template['protagonist']}做梦也想不到，今天的这个决定，将彻底改变他的人生..."


def _generate_cliffhanger(ep_num: int, total: int, phase: str, genre: str) -> str:
    """生成结尾悬念"""
    if ep_num >= total:
        return "（全剧终）这个夏天，故事结束了，但他们的传说才刚刚开始。"
    
    cliffhangers = [
        f"门被推开，一个意想不到的身影出现在门口——{'他' if random.random() > 0.5 else '她'}到底是谁？",
        f"手机屏幕亮起，上面只有一行字：'你以为结束了吗？这只是开始。'",
        f"正当所有人都松了一口气时，角落里传来一声冷笑...",
        f"那个被遗忘的秘密，终于浮出水面。但真相，远比想象中更加残酷。",
        f"她转过身，脸上的笑容消失了。'你确定，这就是全部真相吗？'",
        f"背后的黑影缓缓抬起头，露出一张{'熟悉' if random.random() > 0.5 else '陌生'}的面孔。",
    ]
    return random.choice(cliffhangers)


def _generate_emotion_arc(ep_num: int, template_arc: list) -> list:
    """生成单集情绪走势"""
    arc = []
    emotions = template_arc or ["平静", "冲突", "转折", "高潮"]
    for i, emotion in enumerate(emotions):
        arc.append({
            "order": i + 1,
            "emotion": emotion,
            "intensity": min(10, ep_num + i * 2),
        })
    return arc


def _generate_act(act_info: dict, ep_num: int, phase: str, genre: str, logline: str, template: dict) -> dict:
    """生成一幕的概要"""
    scenes_count = random.randint(2, 4)
    scenes = []
    
    for sc_num in range(1, scenes_count + 1):
        scenes.append({
            "scene_number": sc_num,
            "summary": f"{act_info['name']}场景{sc_num}：{template['protagonist']}{'遭遇' if sc_num == 1 else '应对'}{template['antagonist']}的{'打压' if act_info['act'] <= 2 else '反击'}",
            "duration": random.choice([3, 5, 5, 8]),
        })
    
    return {
        "act": act_info["act"],
        "name": act_info["name"],
        "summary": f"第{ep_num}集{act_info['name']}：{template['core_conflict']} — {act_info['desc']}",
        "scenes": scenes,
    }


# ═══════════════════════════════════════════════════════════════════
# Agent 2: 分镜导演 Agent
# ═══════════════════════════════════════════════════════════════════

def breakdown_to_scenes(
    episode: DramaEpisode,
    genre: str,
    model: str = "endpoint_id",  # 默认使用全局配置的模型
    resolution: str = "720p",
    ratio: str = "9:16"  # 短剧默认竖屏
) -> list[dict]:
    """
    将文学剧本拆解为结构化分镜场景
    
    返回 DramaScene 创建所需的数据列表
    """
    script = episode.script_content or {}
    acts = script.get("acts", [])
    scenes_data = []
    scene_number = 0
    
    for act in acts:
        act_scenes = act.get("scenes", [])
        for sc in act_scenes:
            scene_number += 1
            scene = _build_scene_prompt(
                scene_number, act, sc, episode, genre, model
            )
            scenes_data.append(scene)
    
    return scenes_data


def _build_scene_prompt(
    scene_number: int,
    act: dict,
    scene_info: dict,
    episode: DramaEpisode,
    genre: str,
    model: str,
) -> dict:
    """为单个分镜构建完整的提示词"""
    
    # 随机选择一个运镜方式
    camera = random.choice(CAMERA_TEMPLATES)
    
    # 构建角色描述
    template = GENRE_TEMPLATES.get(genre, GENRE_TEMPLATES["逆袭"])
    characters = [
        {
            "name": "主角",
            "description": template["protagonist"],
            "expression": random.choice(["愤怒", "冷静", "微笑", "紧张", "得意", "悲伤"]),
        },
        {
            "name": "反派/配角",
            "description": template["antagonist"],
            "expression": random.choice(["嘲讽", "不屑", "震惊", "恐慌", "得意"]),
        }
    ]
    
    # 构建完整提示词（短剧竖屏风格）
    char_strs = []
    for c in characters:
        cname = c.get("name", "?")
        cdesc = c.get("description", "?")
        cexpr = c.get("expression", "?")
        char_strs.append(f"{cname}({cdesc}, {cexpr})")
    characters_str = "; ".join(char_strs)
    
    mood = random.choice(['Tense', 'Dramatic', 'Light-hearted', 'Suspenseful', 'Triumphant'])
    
    prompt_parts = [
        f"[SCENE {scene_number}]",
        f"[Genre: {genre} Short Drama]",
        f"[Style: Cinematic, Vertical 9:16, Fast-paced]",
        f"[Characters: {characters_str}]",
        f"[Camera: {camera}]",
        f"[Action: {scene_info.get('summary', '')}]",
        f"[Mood: {mood}]",
    ]
    
    if model:
        if "2.0" in model.lower() or "seedance2" in model.lower():
            prompt_parts.append("[Quality: High-definition, Detailed facial expressions]")
    
    prompt_text = " ".join(prompt_parts)
    
    return {
        "scene_number": scene_number,
        "location": random.choice(["办公室", "豪宅客厅", "街角咖啡厅", "天台", "地下停车场", "会议室", "酒店大堂", "别墅花园"]),
        "time_period": random.choice(["白天", "夜晚", "黄昏", "清晨"]),
        "characters": characters,
        "camera_instruction": camera,
        "prompt_text": prompt_text,
        "duration": scene_info.get("duration", 5),
        "character_seeds": {},  # 将在创建任务时自动分配 Seed
        "model": model,
    }


def assign_character_seeds(scenes: list[dict]) -> list[dict]:
    """
    为场景中的角色分配固定 Seed，确保跨镜头的角色一致性
    
    同一个人物在同一个剧集中使用相同的 Seed
    """
    character_seed_map = {}
    for scene in scenes:
        for char in scene.get("characters", []):
            char_name = char.get("name", "unknown")
            if char_name not in character_seed_map:
                character_seed_map[char_name] = random.randint(100000, 999999)
        
        scene["character_seeds"] = dict(character_seed_map)
    
    return scenes


# ═══════════════════════════════════════════════════════════════════
# Agent 3: 智能审片与剪辑 Agent
# ═══════════════════════════════════════════════════════════════════

def review_scene_quality(scene: DramaScene) -> dict:
    """
    质量初审 — 根据现有信息判断视频是否有缺陷
    
    实际项目中可以接入多模态模型进行画面分析
    """
    issues = []
    
    # 1. 检查重试次数
    if scene.retry_count >= 3:
        issues.append(f"已重试{scene.retry_count}次，超过最大限制")
    
    # 2. 检查是否有错误信息
    if scene.error_msg:
        issues.append(f"生成错误：{scene.error_msg}")
    
    # 3. 检查视频 URL
    if not scene.video_urls:
        issues.append("没有生成任何视频")
    
    # 4. 检查候选数（核心镜头需要多个候选）
    video_count = len(scene.video_urls) if scene.video_urls else 0
    if video_count == 0:
        issues.append("缺少候选视频")
    
    has_defect = len(issues) > 0
    quality_score = max(1, 10 - len(issues) * 3)
    
    return {
        "has_defect": has_defect,
        "quality_score": quality_score,
        "issues": issues,
        "needs_retry": has_defect and scene.retry_count < 3,
    }


def select_best_candidate(scene: DramaScene) -> Optional[str]:
    """
    从多个候选视频中选择最佳视频
    
    实际项目可以使用多模态评分模型
    """
    videos = scene.video_urls or []
    if not videos:
        return None
    
    # 简单策略：选择最后一个（最新的）
    # 实际可以基于质量评分、分辨率、时长等综合判断
    return videos[-1]


def need_regenerate_for_core_scene(scene: DramaScene) -> bool:
    """
    核心/高潮镜头需要多个候选，如果不够则触发重跑
    
    核心场景条件：
    - 场景号是3的倍数（高潮/反转节奏点）
    - 或 quality_score 较低
    """
    is_core = (
        scene.scene_number % 3 == 0
        or (scene.quality_score or 0) < 6
    )
    
    if not is_core:
        return False
    
    candidate_count = len(scene.video_urls) if scene.video_urls else 0
    return candidate_count < 2  # 核心场景至少需要2个候选


# ═══════════════════════════════════════════════════════════════════
# 自动剪辑与成片导出
# ═══════════════════════════════════════════════════════════════════

def build_export_manifest(
    episode: DramaEpisode,
    scene_list: list[DramaScene]
) -> dict:
    """
    构建剪辑清单 — 将所有选中的视频片段按顺序排列
    
    输出格式兼容主流视频剪辑工具
    """
    clips = []
    total_duration = 0
    
    for scene in sorted(scene_list, key=lambda s: s.scene_number):
        video_url = scene.selected_url or (scene.video_urls[-1] if scene.video_urls else None)
        if not video_url:
            continue
        
        clips.append({
            "scene_number": scene.scene_number,
            "video_url": video_url,
            "duration": scene.duration,
            "camera": scene.camera_instruction,
            "prompt": scene.prompt_text,
        })
        total_duration += scene.duration
    
    return {
        "episode_id": episode.id,
        "episode_number": episode.episode_number,
        "title": episode.title or f"第{episode.episode_number}集",
        "total_duration": total_duration,
        "clip_count": len(clips),
        "clips": clips,
    }


# ═══════════════════════════════════════════════════════════════════
# 数据库操作辅助函数
# ═══════════════════════════════════════════════════════════════════

def create_project(db: Session, user_id: int, title: str, genre: str, logline: str, total_episodes: int = 10) -> DramaProject:
    """创建短剧项目"""
    project = DramaProject(
        user_id=user_id,
        title=title,
        genre=genre,
        logline=logline,
        total_episodes=total_episodes,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    logger.info(f"[drama] Created project {project.id}: {title}")
    return project


def create_episode_from_script(
    db: Session,
    project_id: int,
    ep_data: dict
) -> DramaEpisode:
    """根据剧本数据创建剧集"""
    episode = DramaEpisode(
        project_id=project_id,
        episode_number=ep_data["number"],
        title=ep_data.get("title", f"第{ep_data['number']}集"),
        script_content={
            "acts": ep_data.get("acts", []),
        },
        emotion_arc=ep_data.get("emotion_arc", []),
        cliffhanger=ep_data.get("cliffhanger", ""),
        hook=ep_data.get("hook", ""),
        status=DramaStatus.DRAFT,
    )
    db.add(episode)
    db.commit()
    db.refresh(episode)
    return episode


def create_scenes_from_breakdown(
    db: Session,
    episode_id: int,
    scenes_data: list[dict]
) -> list[DramaScene]:
    """根据分镜数据创建场景记录"""
    scenes = []
    for sc_data in scenes_data:
        scene = DramaScene(
            episode_id=episode_id,
            scene_number=sc_data["scene_number"],
            location=sc_data.get("location", ""),
            time_period=sc_data.get("time_period", ""),
            characters=sc_data.get("characters", []),
            camera_instruction=sc_data.get("camera_instruction", ""),
            prompt_text=sc_data.get("prompt_text", ""),
            character_seeds=sc_data.get("character_seeds", {}),
            duration=sc_data.get("duration", 5),
            status=DramaStatus.DRAFT,
        )
        db.add(scene)
        scenes.append(scene)
    
    db.commit()
    for s in scenes:
        db.refresh(s)
    return scenes


def submit_scene_tasks(
    db: Session,
    scenes: list[DramaScene],
    user_id: int,
    channel_id: int,
    task_config_base: dict,
) -> list[TaskRecord]:
    """
    批量提交分镜生成任务到视频生成引擎
    
    每个分镜场景创建一个 TaskRecord
    核心场景（scene_number % 3 == 0）创建2个候选
    """
    from services.task_service import create_task
    
    task_records = []
    
    for scene in scenes:
        # 构建单个分镜的任务配置
        config = dict(task_config_base)
        config["prompt"] = scene.prompt_text
        config["duration_seconds"] = scene.duration
        config["duration"] = scene.duration  # for points calculation
        
        # 注入角色 Seed 确保一致性
        if scene.character_seeds:
            seed_str = ",".join([f"{k}:{v}" for k, v in scene.character_seeds.items()])
            config["seed"] = seed_str
        
        # 核心场景生成多个候选
        candidate_count = 2 if (scene.scene_number % 3 == 0) else 1
        
        for i in range(candidate_count):
            try:
                task = create_task(
                    db=db,
                    user_id=user_id,
                    task_config=config,
                    channel_id=channel_id,
                )
                if task:
                    task_records.append((scene.id, task.id))
                    logger.info(f"[drama] Submitted task {task.id} for scene {scene.scene_number}")
            except Exception as e:
                logger.error(f"[drama] Failed to create task for scene {scene.scene_number}: {e}")
        
        # 更新场景状态
        scene.status = DramaStatus.GENERATING
        db.commit()
    
    return task_records
