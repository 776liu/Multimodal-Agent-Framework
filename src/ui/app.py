"""
Streamlit 单对话框模式 — 通过 REST API 提交任务并轮询结果。
st.session_state 只存:
  - session_id: 固定会话 ID（F5 刷新后不变）
  - _submitted: 任务提交缓存 {task_id: user_input}
  - user_input: 文本输入框绑定值
"""
import streamlit as st
import time
import uuid
import requests
from datetime import datetime
from src.adapters.config import load_app_config

# ---------------------------------------------------------------------------
# 页面配置
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Multimodal AI Agent",
    layout="wide",
)

# ---------------------------------------------------------------------------
# 自定义 CSS
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    :root {
        --primary: #6C5CE7;
        --primary-light: #A29BFE;
        --success: #00B894;
        --warning: #FDCB6E;
        --danger: #FF7675;
        --bg-card: #FFFFFF;
        --bg-page: #F8F9FE;
        --text-primary: #2D3436;
        --text-secondary: #636E72;
        --border: #E8ECF1;
        --radius: 16px;
        --shadow-sm: 0 2px 8px rgba(108,92,231,0.06);
        --shadow-md: 0 4px 20px rgba(108,92,231,0.10);
    }

    .stApp {
        background: linear-gradient(135deg, #F8F9FE 0%, #F0F2FF 50%, #F8F9FE 100%);
    }

    .main .block-container {
        padding-top: 2rem;
        max-width: 900px;
    }

    .image-skeleton {
        background: linear-gradient(90deg, #E8ECF1 25%, #F0F2F5 50%, #E8ECF1 75%);
        background-size: 200% 100%;
        animation: skeleton-shimmer 1.5s ease-in-out infinite;
        border-radius: 12px;
        width: 100%;
        min-height: 280px;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    @keyframes skeleton-shimmer {
        0% { background-position: 200% 0; }
        100% { background-position: -200% 0; }
    }

    .result-header {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 0.75rem;
    }
    .result-badge {
        font-size: 0.78rem;
        padding: 4px 12px;
        border-radius: 12px;
        font-weight: 600;
    }
    .result-badge.text { background: #E8F4FD; color: #0984E3; }
    .result-badge.image { background: #FDE8FF; color: #A855F7; }

    .status-banner {
        padding: 1rem 1.5rem;
        border-radius: 12px;
        font-weight: 600;
        font-size: 1rem;
        display: flex;
        align-items: center;
        gap: 8px;
        margin: 1rem 0;
    }
    .status-banner.success {
        background: linear-gradient(135deg, #D4FCEB, #E8F8F5);
        color: #00896B; border: 1px solid #B2F0D6;
    }
    .status-banner.partial {
        background: linear-gradient(135deg, #FFF8E1, #FFF3CD);
        color: #B8860B; border: 1px solid #FDE68A;
    }
    .status-banner.failed {
        background: linear-gradient(135deg, #FFE8E8, #FDE8E8);
        color: #C0392B; border: 1px solid #F5C6C6;
    }

    .timeline {
        position: relative; padding-left: 28px;
    }
    .timeline::before {
        content: ''; position: absolute; left: 8px; top: 0; bottom: 0;
        width: 2px;
        background: linear-gradient(to bottom, var(--primary-light), var(--border));
    }
    .timeline-item {
        position: relative; margin-bottom: 1rem; padding: 0.75rem 1rem;
        background: var(--bg-card); border-radius: 10px;
        border: 1px solid var(--border); font-size: 0.88rem;
    }
    .timeline-item::before {
        content: ''; position: absolute; left: -24px; top: 14px;
        width: 10px; height: 10px; border-radius: 50%; border: 2px solid white;
    }
    .timeline-item.ok::before {
        background: var(--success);
        box-shadow: 0 0 0 3px rgba(0,184,148,0.2);
    }
    .timeline-item.err::before {
        background: var(--danger);
        box-shadow: 0 0 0 3px rgba(255,118,117,0.2);
    }
    .timeline-item .tl-model { font-weight: 700; color: var(--primary); }
    .timeline-item .tl-meta { color: var(--text-secondary); font-size: 0.8rem; }

    [data-testid="stExpander"] details {
        border: 1px solid var(--border) !important;
        border-radius: var(--radius) !important;
        box-shadow: var(--shadow-sm) !important;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# 加载应用配置
# ---------------------------------------------------------------------------
app_cfg = load_app_config()
API_BASE = app_cfg["api_base"]
POLL_INTERVAL = app_cfg["poll_interval"]
TIMEOUT_SECONDS = app_cfg["timeout_seconds"]

# ---------------------------------------------------------------------------
# API 辅助函数
# ---------------------------------------------------------------------------
def api_submit_task(user_input: str, session_id: str) -> dict | None:
    """提交任务 → 返回 {task_id, status}，失败返回 None"""
    try:
        resp = requests.post(
            f"{API_BASE}/api/task/submit",
            json={"user_input": user_input, "session_id": session_id},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return None


def api_get_task(task_id: str) -> dict | None:
    """查询单个任务 → 返回完整任务数据（result 已由服务端 json.loads 解析为 dict）"""
    try:
        resp = requests.get(
            f"{API_BASE}/api/task/{task_id}",
            timeout=5,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return None


def api_get_session_tasks(session_id: str) -> dict | None:
    """获取某会话下所有任务（仅用于发现 task_id，不直接使用其中的 result 数据）"""
    try:
        resp = requests.get(
            f"{API_BASE}/api/session/{session_id}/tasks",
            timeout=5,
        )
        if resp.status_code == 404:
            return {"session_id": session_id, "processing": [], "completed": []}
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return None


# ---------------------------------------------------------------------------
# 初始化 session_state
# ---------------------------------------------------------------------------
if "user_input" not in st.session_state:
    st.session_state.user_input = ""

if "session_id" not in st.session_state:
    sid = uuid.uuid4().hex[:8]
    # 尝试从 API 恢复最近的会话
    try:
        resp = requests.get(f"{API_BASE}/api/sessions", timeout=5)
        resp.raise_for_status()
        sessions = resp.json().get("sessions", [])
        if sessions:
            sid = sessions[0]["session_id"]
    except requests.RequestException:
        pass
    st.session_state.session_id = sid

# _submitted → {task_id: user_input}
if "_submitted" not in st.session_state:
    st.session_state._submitted = {}

# F5 刷新后从 API 恢复 _submitted
if "_submitted_restored" not in st.session_state:
    st.session_state._submitted_restored = True
    tasks_resp = api_get_session_tasks(st.session_state.session_id)
    if tasks_resp:
        for t in tasks_resp.get("processing", []):
            tid = t.get("task_id", "")
            ui = t.get("user_input", "")
            if tid and ui:
                st.session_state._submitted[tid] = ui
        for t in tasks_resp.get("completed", []):
            tid = t.get("task_id", "")
            ui = t.get("user_input", "")
            if tid and ui:
                st.session_state._submitted[tid] = ui

session_id = st.session_state.session_id

# ---------------------------------------------------------------------------
# 回调函数
# ---------------------------------------------------------------------------
def fill_prompt(value: str):
    st.session_state.user_input = value


def clear_all():
    st.session_state.user_input = ""
    st.session_state._submitted = {}


def do_submit():
    text = st.session_state.user_input.strip()
    if not text:
        return

    result = api_submit_task(text, session_id)
    if result is None:
        st.error(f"后端连接失败，请确认 FastAPI 已启动: {API_BASE}")
        return

    task_id = result["task_id"]
    st.session_state._submitted[task_id] = text
    st.session_state.user_input = ""


# ---------------------------------------------------------------------------
# 标题 + 输入区
# ---------------------------------------------------------------------------
st.title("Multimodal AI Agent")

st.text_area(
    "描述你的需求",
    key="user_input",
    placeholder="例如：生成一张关于未来城市的图片，并写一段描述它的文字",
    height=100,
    label_visibility="collapsed",
)

col_q1, col_q2, col_q3 = st.columns(3)
with col_q1:
    st.button("翻译 Hello World", width="stretch",
              on_click=fill_prompt, args=("把 Hello World 翻译成中文",))
with col_q2:
    st.button("生成小猫图片", width="stretch",
              on_click=fill_prompt, args=("生成一张小猫的图片",))
with col_q3:
    st.button("生成图片并描述", width="stretch",
              on_click=fill_prompt, args=("生成一张小猫的图片，并写一段描述",))

col_btn1, col_btn2, _ = st.columns([1, 1, 4])
with col_btn1:
    st.button("开始执行", type="primary", width="stretch", on_click=do_submit)
with col_btn2:
    st.button("清空", width="stretch", on_click=clear_all)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
TERMINAL_STATUSES = {"SUCCESS", "PARTIAL_SUCCESS", "FAILED", "expired"}

# ---------------------------------------------------------------------------
# 构建任务展示列表
# ---------------------------------------------------------------------------
# 1. 收集所有已知 task_id：本地缓存 + API 发现
known_task_ids: set[str] = set(st.session_state._submitted.keys())

session_tasks = api_get_session_tasks(session_id)
if session_tasks:
    for t in session_tasks.get("processing", []):
        tid = t.get("task_id", "")
        if tid:
            known_task_ids.add(tid)
    for t in session_tasks.get("completed", []):
        tid = t.get("task_id", "")
        if tid:
            known_task_ids.add(tid)

# 2. 对每个 task_id，以 api_get_task 为主要数据源（唯一返回完整解析结果的端点）
display_tasks: list[dict] = []

for tid in known_task_ids:
    # ---- 主数据源：GET /api/task/{task_id}（result 已由服务端 json.loads 解析）----
    detail = api_get_task(tid)

    if detail:
        status = detail.get("status", "pending")
        result = detail.get("result")  # 已完成时为完整 BuilderOutput dict，否则为 None
        user_input = detail.get("user_input", "")
        created_at_raw = detail.get("created_at", 0)
    else:
        # 任务已过期（如 Redis TTL 到期）→ 从 storage 摘要兜底
        status = "expired"
        result = None
        user_input = st.session_state._submitted.get(tid, "")
        created_at_raw = 0

    # 若 user_input 缺失，用本地缓存补全
    if not user_input:
        user_input = st.session_state._submitted.get(tid, "")

    # ---- 规范化 created_at 为 float ----
    try:
        created_at = float(created_at_raw)
    except (ValueError, TypeError):
        created_at = 0.0

    display_tasks.append({
        "task_id": tid,
        "user_input": user_input,
        "status": status,
        "result": result,
        "created_at": created_at,
    })

# 3. 按创建时间降序排列（新的在上面）
display_tasks.sort(key=lambda t: t["created_at"], reverse=True)

# ---------------------------------------------------------------------------
# 侧边栏 — 调试日志
# ---------------------------------------------------------------------------
with st.sidebar:
    st.subheader("调试日志")

    debug_tab1, debug_tab2 = st.tabs(["任务调试", "调用链路"])

    with debug_tab1:
        if not display_tasks:
            st.caption("暂无任务")
        else:
            for task in display_tasks:
                tid = task["task_id"]
                status = task["status"]
                ui = task["user_input"] or "(无输入)"
                result = task["result"]

                is_done = status in TERMINAL_STATUSES
                exp_label = f"{'[OK]' if status == 'SUCCESS' else '[PART]' if status == 'PARTIAL_SUCCESS' else '[FAIL]' if status == 'FAILED' else '[..]'} {ui[:24]}..."
                with st.expander(exp_label, expanded=False):
                    st.caption(f"**Task ID:** `{tid[:20]}...`")
                    st.caption(f"**Status:** `{status}`")

                    # 解析任务类型
                    if result and isinstance(result, dict):
                        frontend = result.get("frontend_response", {})
                        log = result.get("log_record", {})
                        data = frontend.get("data", {})
                        results_list = data.get("results", [])
                        if results_list:
                            types_seen = set()
                            for r in results_list:
                                types_seen.add(r.get("type", "?"))
                            st.caption(f"**Task type:** {', '.join(types_seen)}")
                            for i, r in enumerate(results_list):
                                rtype = r.get("type", "?")
                                st.caption(f"  Subtask #{i + 1}: `{rtype}`")

                        # 调用的大模型
                        call_chain = log.get("call_chain", [])
                        if call_chain:
                            st.caption("**Models called:**")
                            for c in call_chain:
                                m = c.get("model_name", "?")
                                cap = c.get("capability", "?")
                                ok = c.get("status") == "SUCCESS"
                                st.caption(f"  {'[OK]' if ok else '[FAIL]'} `{m}` ({cap})")
                        else:
                            st.caption("**Models called:** (none)")

                        # 错误摘要
                        errors = log.get("error_summary", [])
                        if errors:
                            st.caption(f"**Errors ({len(errors)}):**")
                            for e in errors:
                                st.caption(
                                    f"  [FAIL] `{e.get('model_name', '?')}` - "
                                    f"`{e.get('error_code', '?')}`"
                                )
                    else:
                        st.caption("**Task type:** (no result data)")
                        st.caption("**Models called:** (no record)")

    with debug_tab2:
        # 汇总所有任务的调用链
        all_chains: list[dict] = []
        for task in display_tasks:
            result = task.get("result")
            if result and isinstance(result, dict):
                log = result.get("log_record", {})
                chain = log.get("call_chain", [])
                for c in chain:
                    all_chains.append({
                        **c,
                        "_task_id": task["task_id"],
                        "_user_input": task["user_input"],
                    })

        if not all_chains:
            st.caption("暂无调用链路")
        else:
            # 按时间排序
            all_chains.sort(key=lambda c: c.get("attempted_at", ""), reverse=True)
            st.markdown('<div class="timeline">', unsafe_allow_html=True)
            for call in all_chains:
                is_ok = call.get("status") == "SUCCESS"
                css_class = "ok" if is_ok else "err"
                icon = "[OK]" if is_ok else "[FAIL]"
                ts = call.get("attempted_at", "")
                try:
                    ts_display = datetime.fromtimestamp(float(ts)).strftime("%H:%M:%S")
                except (ValueError, TypeError):
                    ts_display = str(ts)[:10] if ts else "--"
                st.markdown(
                    f'<div class="timeline-item {css_class}">'
                    f'{icon} <span class="tl-model">{call.get("model_name", "--")}</span>'
                    f'&nbsp;|&nbsp; <span class="tl-meta">{call.get("capability", "--")}</span>'
                    f'<br><span class="tl-meta">{ts_display}</span>'
                    f'&nbsp;|&nbsp; <span style="font-size:0.78rem;color:#636E72;">'
                    f'{call.get("_user_input", "")[:20]}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            st.markdown('</div>', unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# 轮询逻辑
# ---------------------------------------------------------------------------
in_progress_count = sum(
    1 for t in display_tasks
    if t["status"] not in TERMINAL_STATUSES
)

if in_progress_count > 0:
    st.caption(f"正在等待 {in_progress_count} 个任务完成...（每 {POLL_INTERVAL}s 自动刷新）")
    time.sleep(POLL_INTERVAL)
    st.rerun()

# ---------------------------------------------------------------------------
# 结果展示
# ---------------------------------------------------------------------------
if not display_tasks:
    st.info("提交你的第一个需求，Agent 会自动拆解并匹配模型执行")
    st.stop()

for idx, task in enumerate(display_tasks):
    user_input = task["user_input"] or "(无输入记录)"
    status = task["status"]
    result = task["result"]
    task_id = task["task_id"]

    # 用户输入
    st.markdown(f"**You:** {user_input}")

    # 状态展示
    if status in ("submitted", "pending", "processing"):
        st.caption(f"状态: {status} (task: {task_id[:16]}...)")
        st.markdown(
            '<div class="image-skeleton">'
            '<span style="color:#B0B8C1;">处理中...</span>'
            '</div>',
            unsafe_allow_html=True,
        )

    elif result is not None:
        frontend = {}
        log = {}

        if isinstance(result, dict) and ("frontend_response" in result or "log_record" in result):
            frontend = result.get("frontend_response", {})
            log = result.get("log_record", {})
        elif isinstance(result, list):
            frontend = {"task_status": status, "data": {"results": result}}
            log = {}
        elif isinstance(result, dict) and "task_status" in result:
            frontend = result
            log = {}
        else:
            frontend = {"task_status": status, "data": {"results": []}}
            log = {}

        task_status = frontend.get("task_status", status or "FAILED")
        data = frontend.get("data", {})

        # 状态横幅
        status_map = {
            "SUCCESS": ("success", "任务执行成功"),
            "PARTIAL_SUCCESS": ("partial", "部分任务完成"),
            "FAILED": ("failed", "任务执行失败"),
        }
        sc, st_text = status_map.get(task_status, ("failed", "未知状态"))
        st.markdown(
            f'<div class="status-banner {sc}">'
            f'<span>{st_text}</span>'
            f'<span style="margin-left:auto;font-size:0.8rem;opacity:0.7;">{task_id}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # 结果内容
        results: list = data.get("results", [])
        if results:
            cols = st.columns(min(len(results), 2))
            for i, item in enumerate(results):
                with cols[i % 2]:
                    if item.get("type") == "image":
                        st.markdown(
                            '<div class="result-header">'
                            '<span class="result-badge image">图片生成</span>'
                            f'<span style="font-size:0.85rem;color:#636E72;">#{i + 1}</span>'
                            '</div>',
                            unsafe_allow_html=True,
                        )
                        img_url = item.get("url", "")
                        if img_url:
                            st.image(img_url)
                        else:
                            st.markdown(
                                '<div class="image-skeleton">'
                                '<span style="color:#B0B8C1;">图片加载中...</span></div>',
                                unsafe_allow_html=True,
                            )
                    elif item.get("type") == "text":
                        st.markdown(
                            '<div class="result-header">'
                            '<span class="result-badge text">文本生成</span>'
                            f'<span style="font-size:0.85rem;color:#636E72;">#{i + 1}</span>'
                            '</div>',
                            unsafe_allow_html=True,
                        )
                        st.markdown(
                            f'<div style="background:#F8F9FE;padding:1rem;border-radius:10px;'
                            f'font-size:0.95rem;line-height:1.7;color:#2D3436;white-space:pre-wrap;">'
                            f'{item.get("content", "")}</div>',
                            unsafe_allow_html=True,
                        )

        if task_status == "SUCCESS":
            st.success("本轮对话已写入记忆，后续提问可引用上下文")
        elif task_status == "PARTIAL_SUCCESS":
            st.info("部分子任务完成，已记录调用链")
        if task_status == "FAILED" and data.get("message"):
            st.info(data["message"])

        # 调用链日志
        if log:
            with st.expander(f"调用链日志 — {task_id[:16]}", expanded=False):
                tab1, tab2 = st.tabs(["时间线", "错误摘要"])
                with tab1:
                    call_chain = log.get("call_chain", [])
                    if not call_chain:
                        st.caption("暂无调用记录")
                    else:
                        st.markdown('<div class="timeline">', unsafe_allow_html=True)
                        for call in call_chain:
                            is_ok = call.get("status") == "SUCCESS"
                            css_class = "ok" if is_ok else "err"
                            status_text_item = "[OK]" if is_ok else "[FAIL]"
                            ts = call.get("attempted_at", "")
                            try:
                                ts_display = datetime.fromtimestamp(float(ts)).strftime("%H:%M:%S")
                            except (ValueError, TypeError):
                                ts_display = str(ts)[:10] if ts else "--"
                            error_part = (
                                f"&nbsp;·&nbsp; <span style='color:#FF7675;'>"
                                f"错误码: {call.get('error_code', '--')}</span>"
                            ) if not is_ok else ""
                            st.markdown(
                                f'<div class="timeline-item {css_class}">'
                                f'{status_text_item} <span class="tl-model">{call.get("model_name", "--")}</span>'
                                f'&nbsp;·&nbsp; <span class="tl-meta">{call.get("capability", "--")}</span>'
                                f'<br><span class="tl-meta">{ts_display}</span>{error_part}'
                                f'</div>',
                                unsafe_allow_html=True,
                            )
                        st.markdown('</div>', unsafe_allow_html=True)
                with tab2:
                    errors = log.get("error_summary", [])
                    if not errors:
                        st.success("无错误")
                    else:
                        for j, err in enumerate(errors, 1):
                            st.markdown(
                                f'<div style="background:#FFF5F5;border:1px solid #FED7D7;'
                                f'border-radius:10px;padding:0.75rem 1rem;margin-bottom:0.5rem;">'
                                f'<strong style="color:#C0392B;">#{j}</strong>&nbsp;&nbsp;'
                                f'模型: <code>{err.get("model_name", "--")}</code>&nbsp;·&nbsp;'
                                f'能力: <code>{err.get("capability", "--")}</code>&nbsp;·&nbsp;'
                                f'错误码: <code style="color:#E74C3C;">{err.get("error_code", "--")}</code>'
                                f'</div>',
                                unsafe_allow_html=True,
                            )
    else:
        # result 为空但状态为终态 → 极少见（Worker 先写 result 再改 status）
        st.error(f"任务 {task_id} 状态为 {status}，但未获取到结果")

    if idx < len(display_tasks) - 1:
        st.divider()
