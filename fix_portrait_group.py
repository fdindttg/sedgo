"""在服务器上运行：创建真人素材分组并更新 channel 1 的 portrait_group_id"""
import sys
sys.path.insert(0, '.')

from routers.asset_library import _call_api
from database import SessionLocal, Channel

# Step 1: 创建 LivenessFace 分组
print("Creating LivenessFace group...")
try:
    result = _call_api("CreateAssetGroup", {
        "Name": "seedance-portraits",
        "GroupType": "LivenessFace",
        "ProjectName": "default",
    })
    group_id = result.get("Id", "")
    print(f"Created group: {group_id}")
except Exception as e:
    print(f"CreateAssetGroup failed: {e}")
    # 如果已存在，列出现有分组
    try:
        r = _call_api("ListAssetGroups", {"Filter": {"GroupType": "LivenessFace"}, "PageNumber": 1, "PageSize": 20})
        for g in r.get("Items", []):
            print(f"  Existing group: {g.get('Id')} - {g.get('Name')}")
        group_id = input("Enter existing group_id to use: ").strip()
    except Exception as e2:
        print(f"ListAssetGroups also failed: {e2}")
        sys.exit(1)

if not group_id:
    print("No group_id, exit")
    sys.exit(1)

# Step 2: 更新数据库 channel 1
db = SessionLocal()
try:
    channel = db.query(Channel).filter(Channel.id == 1).first()
    if channel:
        channel.portrait_group_id = group_id
        db.commit()
        print(f"Updated channel 1 portrait_group_id = {group_id}")
    else:
        print("Channel 1 not found")
finally:
    db.close()
