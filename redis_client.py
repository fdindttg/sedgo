import json
import redis
from config import REDIS_URL, REDIS_PREFIX

_redis_client = None


def get_redis():
    global _redis_client
    if not REDIS_URL:
        return None
    try:
        # Always test connection to handle stale client after Redis restarts
        if _redis_client is not None:
            _redis_client.ping()
            return _redis_client
        _redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        _redis_client.ping()
    except Exception:
        _redis_client = None
    return _redis_client


def redis_available():
    return get_redis() is not None


def _key(name):
    return f"{REDIS_PREFIX}{name}"


def get_points_balance(user_id: int):
    r = get_redis()
    if not r:
        return None
    val = r.get(_key(f"points:{user_id}"))
    return int(val) if val is not None else None


def set_points_balance(user_id: int, balance: int, ttl: int = 600):
    r = get_redis()
    if r:
        r.setex(_key(f"points:{user_id}"), ttl, balance)


def del_points_balance(user_id: int):
    r = get_redis()
    if r:
        r.delete(_key(f"points:{user_id}"))


def cache_json_get(name: str):
    r = get_redis()
    if not r:
        return None
    val = r.get(_key(name))
    return json.loads(val) if val else None


def cache_json_set(name: str, data: dict, ttl: int = 600):
    r = get_redis()
    if r:
        r.setex(_key(name), ttl, json.dumps(data))