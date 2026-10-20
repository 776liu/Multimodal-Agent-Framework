"""工单 T-03：视频本地归档单元测试

覆盖:
- 正常下载落盘与命名规则
- 二次归档复用（幂等）
- 并发锁：第二下载者不互踩
- 大小上限拦截
- 空响应拒绝
- 下载失败时回退外链（不抛异常、不阻断）
- 路径穿越防护
- local URL 构造
- Artifact → TaskResult 的本地 URL 优先
"""
import time
from pathlib import Path
import tempfile

import pytest
import requests

from src.core import video_archive
from src.core.video_archive import (
    archive_video,
    is_valid_archive_name,
    resolve_local_url,
    is_valid_archive_name,
    resolve_local_url,
)
from src.core.contracts import Artifact


class _FakeResponse:
    """模拟 requests 响应"""

    def __init__(self, chunks, status_code=200, headers=None):
        self._chunks = chunks
        self.status_code = status_code
        self.headers = headers or {"Content-Length": str(sum(len(c) for c in chunks))}

    def iter_content(self, chunk_size=1):
        for c in self._chunks:
            yield c


class _FakeSession:
    """可编程的假 session，按 URL 前缀决定返回内容"""

    def __init__(self, handler):
        self.handler = handler

    def get(self, url, stream=True, timeout=None):
        return self.handler(url)


@pytest.fixture(autouse=True)
def _use_tmp_archive(monkeypatch):
    """所有测试用临时归档目录，不污染 data/videos"""
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setattr(video_archive, "ARCHIVE_DIR", tmp)
    yield
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


import tempfile  # noqa: E402


# ==================================================================
# 正常归档
# ==================================================================
def test_archive_downloads_and_names_by_task_step(monkeypatch):
    body = [b"\x00" * 1024]  # 1KB 视频字节
    monkeypatch.setattr(
        video_archive.requests, "get",
        lambda url, stream=True, timeout=None: _FakeResponse(body),
    )

    out = archive_video("https://signed/x.mp4", task_id="abc123", step=3)

    assert out is not None
    assert Path(out["local_path"]).name == "abc123_step3.mp4"
    assert Path(out["local_path"]).parent == video_archive.ARCHIVE_DIR
    assert out["size_bytes"] == 1024
    assert Path(out["local_path"]).exists()
    assert not Path(str(out["local_path"]) + ".part").exists()   # 无残留


def test_archive_is_idempotent(monkeypatch):
    """反思重试后二次调用同一任务，直接复用已归档文件"""
    monkeypatch.setattr(
        video_archive.requests, "get",
        lambda url, stream=True, timeout=None: _FakeResponse([b"data"]),
    )
    first = archive_video("https://signed/x.mp4", "t1", 1)
    second = archive_video("https://signed/x.mp4", "t1", 1)

    assert first["local_path"] == second["local_path"]
    assert second["size_bytes"] == first["size_bytes"]


# ==================================================================
# 并发与锁
# ==================================================================
def test_archive_lock_prevents_concurrent_duplicate(monkeypatch):
    """第二个下载者拿不到锁时应放弃归档（返回 None），不互踩文件"""
    # 预先占锁，模拟另一线程正在下载
    video_archive.ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    lock = video_archive.ARCHIVE_DIR / "t1_step1.mp4.lock"
    lock.touch()

    out = archive_video("https://signed/x.mp4", "t1", 1)
    assert out is None


def test_stale_lock_is_reclaimed(monkeypatch):
    """超过滞留时长的残留锁可被抢占，不会永久卡死归档"""
    video_archive.ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    lock = video_archive.ARCHIVE_DIR / "t1_step1.mp4.lock"
    lock.touch()
    # 把锁的 mtime 改到滞留阈值之前
    stale = time.time() - video_archive.PART_STALE_SECONDS - 10
    import os
    os.utime(lock, (stale, stale))

    monkeypatch.setattr(
        video_archive.requests, "get",
        lambda url, stream=True, timeout=None: _FakeResponse([b"ok"]),
    )
    out = archive_video("https://signed/x.mp4", "t1", 1)
    assert out is not None, "残留锁应被抢占"


# ==================================================================
# 防御性拦截
# ==================================================================
def test_archive_rejects_oversized_content(monkeypatch):
    """超过大小上限的视频拒绝归档，且不留 .part 残留"""
    big = [b"\x00" * (video_archive.MAX_VIDEO_BYTES // 2)] * 3   # 1.5x 上限
    monkeypatch.setattr(
        video_archive.requests, "get",
        lambda url, stream=True, timeout=None: _FakeResponse(big),
    )
    out = archive_video("https://signed/big.mp4", "t1", 1)
    assert out is None
    assert not (video_archive.ARCHIVE_DIR / "t1_step1.mp4").exists()
    assert not (video_archive.ARCHIVE_DIR / "t1_step1.mp4.part").exists()


def test_archive_rejects_empty_body(monkeypatch):
    monkeypatch.setattr(
        video_archive.requests, "get",
        lambda url, stream=True, timeout=None: _FakeResponse([]),
    )
    assert archive_video("https://signed/x.mp4", "t1", 1) is None


def test_archive_swallows_network_error(monkeypatch):
    """网络异常必须返回 None（回退外链），绝不能向任务主流程抛异常"""
    def _boom(url, stream=True, timeout=None):
        raise requests.ConnectionError("network down")

    monkeypatch.setattr(video_archive.requests, "get", _boom)
    assert archive_video("https://signed/x.mp4", "t1", 1) is None


def test_archive_rejects_non_200(monkeypatch):
    monkeypatch.setattr(
        video_archive.requests, "get",
        lambda url, stream=True, timeout=None: _FakeResponse([], status_code=403),
    )
    assert archive_video("https://signed/expired.mp4", "t1", 1) is None


# ==================================================================
# 名字安全
# ==================================================================
@pytest.mark.parametrize("bad", ["../etc/passwd", "a/b.mp4", "..\\x.mp4", "x.mp4/..", ""])
def test_invalid_archive_names_rejected(bad):
    assert is_valid_archive_name(bad) is False


def test_valid_archive_name_accepted():
    assert is_valid_archive_name("abc123_step1.mp4") is True


def test_resolve_local_url_format():
    assert resolve_local_url("data/videos/abc_step1.mp4") == "/api/artifacts/video/abc_step1.mp4"


# ==================================================================
# Artifact → TaskResult 本地优先
# ==================================================================
def test_video_task_result_prefers_local_url(monkeypatch):
    monkeypatch.setattr(
        video_archive.requests, "get",
        lambda url, stream=True, timeout=None: _FakeResponse([b"vid"]),
    )
    out = archive_video("https://signed/x.mp4", "t9", 2)

    art = Artifact.video_of(
        "https://signed/x.mp4",
        step=2,
        local_path=out["local_path"],
        size_bytes=out["size_bytes"],
        remote_url="https://signed/x.mp4",
    )
    tr = art.to_task_result()

    assert tr.url.startswith("/api/artifacts/video/")
    assert tr.url.endswith("t9_step2.mp4")
    assert art.metadata["remote_url"] == "https://signed/x.mp4"   # 外链留档


def test_video_task_result_falls_back_to_remote_when_not_archived():
    art = Artifact.video_of("https://signed/x.mp4", step=1)
    tr = art.to_task_result()
    assert tr.url == "https://signed/x.mp4"
