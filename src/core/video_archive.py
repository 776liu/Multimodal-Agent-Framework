"""视频产物本地归档（工单 T-03）

背景：模型平台返回的视频是带签名的 S3 临时 URL（X-Amz-Expires=86400），
24 小时后失效——答辩演示时点开历史视频会直接 403，属演示可靠性事故。

方案：任务成功后把视频下载到本地 `data/videos/`，
Artifact.metadata 写入 local_path，前端优先使用本地静态端点。

健壮性设计：
- 文件锁：同一目标文件只允许一个下载者（防止并发任务重名互踩）；
- 大小上限：超过 MAX_VIDEO_BYTES 视为异常产物，拒绝归档；
- 下载失败不阻断主流程：本地归档是增强，失败时仍返回原始外链；
- 原子写入：先写 .part 临时文件，完成后 rename，避免半截文件被播放。
"""
import os
import time
from pathlib import Path
from typing import Optional

import requests

# 归档根目录（相对项目根）
ARCHIVE_DIR = Path("data/videos")
# 单个视频大小上限 200MB（平台实测单视频 1~4MB，上限仅作异常防御）
MAX_VIDEO_BYTES = 200 * 1024 * 1024
# 下载超时
DOWNLOAD_TIMEOUT = 120
# .part 文件的最大滞留时长（秒），超时视为残留垃圾，可抢占
PART_STALE_SECONDS = 600


def archive_video(url: str, task_id: str, step: int,
                  session: Optional[requests.Session] = None) -> Optional[dict]:
    """下载视频到本地归档目录。

    返回:
        成功: {"local_path": "data/videos/xxx.mp4", "size_bytes": N}
        失败: None（调用方应回退使用原始外链，不抛异常）
    """
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{task_id}_step{step}.mp4"
    final_path = ARCHIVE_DIR / filename
    part_path = ARCHIVE_DIR / f"{filename}.part"
    lock_path = ARCHIVE_DIR / f"{filename}.lock"

    # 已归档过（如反思重试后二次调用）直接复用
    if final_path.exists() and final_path.stat().st_size > 0:
        return {"local_path": final_path.as_posix(), "size_bytes": final_path.stat().st_size}

    # 简易文件锁：create 模式独占创建，拿不到锁的调用方直接放弃归档
    try:
        if lock_path.exists() and time.time() - lock_path.stat().st_mtime > PART_STALE_SECONDS:
            lock_path.unlink()   # 抢占残留锁
        # O_CREAT|O_EXCL 独占创建（Path.touch(exclusive=) 需 3.13，兼容起见用 os.open）
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        return None              # 另一个下载者正在进行

    try:
        resp = (session or requests).get(url, stream=True, timeout=DOWNLOAD_TIMEOUT)
        if resp.status_code != 200:
            return None

        declared = int(resp.headers.get("Content-Length") or 0)
        if declared > MAX_VIDEO_BYTES:
            return None

        written = 0
        with open(part_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=256 * 1024):
                written += len(chunk)
                if written > MAX_VIDEO_BYTES:
                    f.close()
                    part_path.unlink(missing_ok=True)
                    return None
                f.write(chunk)

        if written == 0:
            part_path.unlink(missing_ok=True)
            return None

        # 原子替换：.part → 最终名
        os.replace(part_path, final_path)
        return {"local_path": final_path.as_posix(), "size_bytes": written}

    except (requests.RequestException, OSError):
        part_path.unlink(missing_ok=True)
        return None

    finally:
        lock_path.unlink(missing_ok=True)


def resolve_local_url(local_path: str) -> str:
    """由本地路径构造 API 静态端点 URL（前端优先使用，回退外链）"""
    name = Path(local_path).name
    return f"/api/artifacts/video/{name}"


def is_valid_archive_name(name: str) -> bool:
    """防路径穿越：只允许安全的归档文件名"""
    if "/" in name or "\\" in name or ".." in name:
        return False
    return name.endswith(".mp4") and len(name) < 200
