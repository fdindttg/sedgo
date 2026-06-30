"""BytePlus API 错误信息友好化工具

将 BytePlus 返回的原始错误信息映射为多语言友好提示。
"""

import re
import logging

logger = logging.getLogger(__name__)

# 错误消息映射表（按关键词匹配，中文默认）
_ERROR_MAP_ZH = [
    # === 版权限制 ===
    (r"copyright|policy.*violation|OutputVideoSensitiveContentDetected",
     "生成的视频可能涉及版权限制，请调整提示词或更换参考素材后重试"),

    # === 敏感内容 / 审核 ===
    (r"sensitive|审核|moderation",
     "内容包含敏感信息，已被审核系统拒绝，请调整提示词或更换参考素材后重试"),

    # === 真人检测 ===
    (r"real person|real_human|真人|portrait.*detect|face.*detect",
     "输入素材中检测到真人肖像，请启用真人素材模式 (use_real_people) 或将素材上传到素材库后再试"),

    (r"privacyinformation|privacy.*information",
     "输入素材涉及隐私信息，请确保您拥有素材的使用权限，或尝试使用素材库上传"),

    # === 参数错误 ===
    (r"invalid url|not valid.*url|image.*not valid",
     "参考图片/视频链接无效，请检查文件是否上传成功或链接是否可公网访问"),

    (r"parameter.*not valid|invalid.*parameter",
     "请求参数无效，请检查输入参数是否合法"),

    (r"prompt.*required|text.*empty|text.*required",
     "提示词(prompt)不能为空，请输入描述文本"),

    (r"duration.*invalid|duration.*exceed|duration.*limit",
     "视频时长超出限制，单段视频最长15秒，请调整时长后重试"),

    # === 接入点/模型 ===
    (r"model.*not found|endpoint.*not found|does not exist|接入点.*不存在",
     "所选模型接入点不存在或已下架，请选择其他可用的接入点"),

    (r"model.*not available|endpoint.*not available",
     "所选模型接入点暂不可用，请稍后重试或选择其他接入点"),

    (r"r2v|real.*person.*feature|真人.*不支持",
     "当前接入点不支持真人素材(r2v)功能，请选择 2.0 版本模型"),

    # === 配额/限流 ===
    (r"rate.*limit|too many requests|qps|qpm|request.*throt",
     "请求过于频繁，触发 API 限流，请稍后重试"),

    (r"quota.*exceed|insufficient.*quota|超出配额",
     "API 配额已用尽，请联系管理员或升级套餐"),

    # === 认证 ===
    (r"unauthorized|auth.*failed|invalid.*key|invalid.*token|认证失败",
     "API 认证失败，请检查渠道的 API Key 或 AK/SK 配置是否正确"),

    (r"forbidden|access.*denied|无权限",
     "没有 API 访问权限，请检查账户授权"),

    # === 网络/服务 ===
    (r"timeout|超时|timed out",
     "API 请求超时，请稍后重试或检查网络连接"),

    (r"internal.*error|server.*error|service.*unavailable|服务器.*错误",
     "BytePlus 服务端错误，请稍后重试"),

    # === 文件/素材 ===
    (r"file.*too large|file.*size|文件.*过大",
     "素材文件过大，请压缩后重试（视频≤50MB，图片≤30MB）"),

    (r"unsupported.*format|格式.*不支持",
     "素材格式不支持，图片支持 jpg/png/webp，视频支持 mp4/mov，音频支持 mp3/wav"),

    (r"resolution.*invalid|分辨率.*无效",
     "视频分辨率不合法，支持 480p/720p/1080p"),

    # === 素材库 ===
    (r"asset.*failed|素材.*失败|processing.*failed",
     "素材上传到素材库后处理失败，请检查素材文件是否完整可读"),

    (r"group.*not found|分组.*不存在",
     "素材分组不存在，请先在素材库中创建分组"),
]

# 英文错误消息映射（同步更新）
_ERROR_MAP_EN = [
    (r"copyright|policy.*violation|OutputVideoSensitiveContentDetected",
     "The generated video may be related to copyright restrictions. Please adjust your prompt or reference material and try again"),

    (r"sensitive|审核|moderation",
     "Content contains sensitive information and was rejected by the review system. Please adjust your prompt or reference material and try again"),

    (r"real person|real_human|真人|portrait.*detect|face.*detect",
     "Real person portrait detected in input material. Please enable real-person mode (use_real_people) or upload materials to the asset library"),

    (r"privacyinformation|privacy.*information",
     "Input material involves privacy information. Please ensure you have the right to use it, or try uploading via the asset library"),

    (r"invalid url|not valid.*url|image.*not valid",
     "Reference image/video link is invalid. Please check if the file was uploaded successfully and the URL is publicly accessible"),

    (r"parameter.*not valid|invalid.*parameter",
     "Invalid request parameter. Please check your input"),

    (r"prompt.*required|text.*empty|text.*required",
     "Prompt text cannot be empty. Please enter a description"),

    (r"duration.*invalid|duration.*exceed|duration.*limit",
     "Video duration exceeds the limit (max 15 seconds per segment). Please reduce the duration"),

    (r"model.*not found|endpoint.*not found|does not exist|接入点.*不存在",
     "The selected model endpoint does not exist or has been deactivated. Please choose another available endpoint"),

    (r"model.*not available|endpoint.*not available",
     "The selected model endpoint is temporarily unavailable. Please try again later or choose another endpoint"),

    (r"r2v|real.*person.*feature|真人.*不支持",
     "The current endpoint does not support real-person (r2v) feature. Please use a 2.0 version model"),

    (r"rate.*limit|too many requests|qps|qpm|request.*throt",
     "Too many requests. API rate limit reached. Please try again later"),

    (r"quota.*exceed|insufficient.*quota|超出配额",
     "API quota exhausted. Please contact the administrator or upgrade your plan"),

    (r"unauthorized|auth.*failed|invalid.*key|invalid.*token|认证失败",
     "API authentication failed. Please check the channel's API Key or AK/SK configuration"),

    (r"forbidden|access.*denied|无权限",
     "API access denied. Please check your account permissions"),

    (r"timeout|超时|timed out",
     "API request timed out. Please try again or check your network"),

    (r"internal.*error|server.*error|service.*unavailable|服务器.*错误",
     "BytePlus server error. Please try again later"),

    (r"file.*too large|file.*size|文件.*过大",
     "Asset file is too large. Please compress and retry (video ≤50MB, image ≤30MB)"),

    (r"unsupported.*format|格式.*不支持",
     "Unsupported file format. Images: jpg/png/webp, Videos: mp4/mov, Audio: mp3/wav"),

    (r"resolution.*invalid|分辨率.*无效",
     "Invalid video resolution. Supported: 480p/720p/1080p"),

    (r"asset.*failed|素材.*失败|processing.*failed",
     "Asset processing failed after upload. Please check if the file is valid"),

    (r"group.*not found|分组.*不存在",
     "Asset group not found. Please create a group in the asset library first"),
]


def translate_error(error_message: str, lang: str = "zh") -> str:
    """将 BytePlus API 返回的错误信息翻译为友好提示。

    Args:
        error_message: BytePlus 原始错误消息
        lang: 语言代码，'zh' 中文，'en' 英文

    Returns:
        翻译后的友好错误消息
    """
    if not error_message:
        return "未知错误 (Unknown error)" if lang != "zh" else "未知错误"

    msg_lower = error_message.lower()
    error_map = _ERROR_MAP_EN if lang == "en" else _ERROR_MAP_ZH

    for pattern, friendly_msg in error_map:
        if re.search(pattern, msg_lower):
            logger.info(f"[error_utils] Matched pattern '{pattern}' for: {error_message[:120]}")
            return friendly_msg

    # 没有匹配到已知模式，返回简化后的原始错误
    logger.warning(f"[error_utils] No pattern matched for: {error_message[:200]}")
    if len(error_message) > 300:
        error_message = error_message[:300] + "..."
    if lang == "en":
        return f"Generation failed: {error_message}"
    return f"生成失败: {error_message}"


def is_real_person_error(error_message: str) -> bool:
    """检查错误消息是否表示真人肖像检测（支持中英文）。

    用于判断是否需要自动启用 use_real_people 模式重试。
    """
    msg_lower = error_message.lower()
    return bool(
        re.search(r"real person|real_human", msg_lower)
        or re.search(r"privacyinformation|privacy.*information", msg_lower)
        or "真人" in error_message
        or "隐私" in error_message
    )


def parse_api_error(response_or_result, lang: str = "zh") -> str:
    """从 API 响应中提取错误信息并翻译。

    支持以下格式:
    - response.json() -> {"error": {"message": "..."}}
    - response.json() -> {"ResponseMetadata": {"Error": {"Message": "..."}}}
    - dict -> 直接作为 result
    - str -> 直接作为原始错误

    Args:
        response_or_result: API 响应对象(http response)或结果 dict 或错误字符串
        lang: 语言代码

    Returns:
        友好的错误消息
    """
    raw_msg = ""

    # 1. HTTP Response 对象
    if hasattr(response_or_result, 'json'):
        try:
            data = response_or_result.json()
        except Exception:
            data = {}
        raw_msg = (
            data.get("error", {}).get("message", "")
            or data.get("ResponseMetadata", {}).get("Error", {}).get("Message", "")
            or str(data.get("error", ""))
            or data.get("message", "")
            or str(response_or_result.status_code)
        )

    # 2. 字典
    elif isinstance(response_or_result, dict):
        raw_msg = (
            response_or_result.get("error", {}).get("message", "")
            or response_or_result.get("ResponseMetadata", {}).get("Error", {}).get("Message", "")
            or str(response_or_result.get("error", ""))
            or response_or_result.get("message", "")
            or str(response_or_result)
        )

    # 3. 字符串
    elif isinstance(response_or_result, str):
        raw_msg = response_or_result
    else:
        raw_msg = str(response_or_result)

    return translate_error(raw_msg, lang)
