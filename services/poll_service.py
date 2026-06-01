"""
高并发任务轮询服务
使用线程池实现高效的任务状态轮询，支持6000+并发任务
"""

import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from database import SessionLocal, TaskRecord, TaskStatus

logger = logging.getLogger(__name__)

# 轮询配置
POLL_INTERVAL_BASE = 5  # 基础轮询间隔（秒）
POLL_INTERVAL_MIN = 3   # 最小轮询间隔
POLL_INTERVAL_MAX = 30  # 最大轮询间隔

# 线程池配置
MAX_WORKERS = 50  # 轮询工作线程数
BATCH_SIZE = 100  # 每次查询的任务数量

# 状态常量
CST = timezone(timedelta(hours=8))

# 全局控制标志
_shutdown_event = threading.Event()


def get_poll_interval(task_age_seconds: int) -> int:
    """根据任务年龄动态调整轮询间隔"""
    # 任务刚创建时轮询更频繁，随着时间推移降低频率
    if task_age_seconds < 60:
        return POLL_INTERVAL_MIN
    elif task_age_seconds < 300:
        return POLL_INTERVAL_BASE
    elif task_age_seconds < 600:
        return POLL_INTERVAL_BASE * 2
    else:
        return min(POLL_INTERVAL_MAX, task_age_seconds // 30)


def poll_single_task(db: Session, task: TaskRecord) -> bool:
    """
    轮询单个任务的状态
    返回：任务是否已完成（成功/失败/取消）
    """
    from services.task_service import poll_task
    
    try:
        poll_task(db, task)
        db.refresh(task)
        
        if task.status in (TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED):
            return True
    except Exception as e:
        logger.error(f"[poll_worker] Failed to poll task {task.id}: {e}")
    
    return False


def poll_worker_batch(batch_tasks: list):
    """批量轮询任务（单个工作线程处理）"""
    db = SessionLocal()
    try:
        for task in batch_tasks:
            if _shutdown_event.is_set():
                break
            
            task_obj = db.query(TaskRecord).filter(TaskRecord.id == task['id']).first()
            if not task_obj:
                continue
            
            if task_obj.status not in (TaskStatus.PROCESSING, TaskStatus.PENDING):
                continue
            
            poll_single_task(db, task_obj)
            db.commit()
    except Exception as e:
        logger.error(f"[poll_worker_batch] Error: {e}")
    finally:
        db.close()


def poll_tasks_loop():
    """主轮询循环"""
    logger.info(f"[poll_service] Starting task polling service with {MAX_WORKERS} workers")
    
    executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="poll_worker")
    
    try:
        while not _shutdown_event.is_set():
            start_time = time.time()
            
            # 查询需要轮询的任务
            db = SessionLocal()
            try:
                # 获取所有PROCESSING状态的任务
                processing_tasks = db.query(TaskRecord).filter(
                    TaskRecord.status == TaskStatus.PROCESSING
                ).order_by(TaskRecord.created_at).all()
                
                task_count = len(processing_tasks)
                if task_count > 0:
                    logger.debug(f"[poll_service] Found {task_count} tasks to poll")
            finally:
                db.close()
            
            # 如果没有任务，等待后继续
            if task_count == 0:
                time.sleep(POLL_INTERVAL_BASE)
                continue
            
            # 分批处理
            futures = []
            for i in range(0, task_count, BATCH_SIZE):
                batch = processing_tasks[i:i+BATCH_SIZE]
                batch_data = [{'id': t.id, 'created_at': t.created_at} for t in batch]
                futures.append(executor.submit(poll_worker_batch, batch_data))
            
            # 等待所有批次完成
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"[poll_service] Batch processing failed: {e}")
            
            # 控制轮询频率
            elapsed = time.time() - start_time
            remaining = max(POLL_INTERVAL_MIN, POLL_INTERVAL_BASE - elapsed)
            time.sleep(remaining)
    
    except Exception as e:
        logger.error(f"[poll_service] Main loop crashed: {e}")
    finally:
        logger.info("[poll_service] Shutting down poll service...")
        executor.shutdown(wait=True)
        logger.info("[poll_service] Poll service stopped")


def start_poll_service():
    """启动任务轮询服务（后台线程）"""
    thread = threading.Thread(target=poll_tasks_loop, daemon=True, name="poll_service")
    thread.start()
    logger.info("[poll_service] Poll service started in background")


def stop_poll_service():
    """停止任务轮询服务"""
    _shutdown_event.set()
    logger.info("[poll_service] Poll service shutdown requested")


def get_poll_stats() -> dict:
    """获取轮询服务状态统计"""
    db = SessionLocal()
    try:
        processing_count = db.query(TaskRecord).filter(
            TaskRecord.status == TaskStatus.PROCESSING
        ).count()
        
        pending_count = db.query(TaskRecord).filter(
            TaskRecord.status == TaskStatus.PENDING
        ).count()
        
        return {
            "processing_tasks": processing_count,
            "pending_tasks": pending_count,
            "is_running": not _shutdown_event.is_set(),
            "max_workers": MAX_WORKERS,
            "batch_size": BATCH_SIZE
        }
    finally:
        db.close()


# 启动时自动初始化
_started = False
def ensure_poll_service_started():
    """确保轮询服务已启动"""
    global _started
    if not _started:
        start_poll_service()
        _started = True
