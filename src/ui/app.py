import streamlit as st
import time
import uuid
import requests
from datetime import datetime
from src.core.router import Router
from src.core.llm_client import LLMClient
from src.core.task_router import TaskRouter
from src.core.builder import Builder
from src.core.memory import Memory
from src.core.storage import Storage
from src.core.agent import Agent
from src.adapters.config import load_app_config

# ---------------------------------------------------------------------------
# 页面配置
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="多模态 AI Agent",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
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
        max-width: 1200px;
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
# 初始化核心引擎
# ---------------------------------------------------------------------------
@st.cache_resource
def load_agent():
    router = Router()
    llm_client = LLMClient()
    task_router = TaskRouter(router, llm_client)
    builder = Builder()
    memory = Memory(max_history=10)
    storage = Storage(db_path="data/agent.db")
    agent = Agent(task_router, router, llm_client, builder, memory)
    return agent, storage


agent, storage = load_agent()
app_cfg = load_app_config()
API_BASE = app_cfg["api_base"]
POLL_INTERVAL = app_cfg["poll_interval"]
TIMEOUT_SECONDS = app_cfg["timeout_seconds"]

# ---------------------------------------------------------------------------
# 初始化 session state
# ---------------------------------------------------------------------------
if "user_input" not in st.session_state:
    st.session_state.user_input = ""
if "_should_run" not in st.session_state:
    st.session_state._should_run = False
if "_last_context" not in st.session_state:
    st.session_state._last_context = ""

# conversation: [{user_input, task_id, status, result}]
if "conversation" not in st.session_state:
    st.session_state.conversation = []

# ---- 多会话管理器 ----
if "sessions" not in st.session_state:
    db_sessions = storage.list_sessions()
    if db_sessions:
        restored = {}
        first_sid = None
        for entry in db_sessions:
            sid = entry["session_id"]
            ts_raw = entry["created_at"]
            if isinstance(ts_raw, str):
                try:
                    ts_raw = datetime.fromisoformat(ts_raw).timestamp()
                except ValueError:
                    ts_raw = time.time()
            restored[sid] = {"created_at": ts_raw, "label": entry["label"]}
            if first_sid is None:
                first_sid = sid
            if not agent.memory.has_session(sid):
                for m in storage.get_messages(sid):
                    agent.memory.add(sid, m["role"], m["content"])
        st.session_state.sessions = restored
        st.session_state.session_id = first_sid
        # 恢复对话历史
        builder_input = storage.get_last_task_input(first_sid)
        if builder_input:
            last_result = agent.builder.build(builder_input)
            st.session_state.conversation = [{
                "user_input": storage.get_first_message(first_sid),
                "task_id": builder_input.task_id,
                "status": builder_input.final_status,
                "result": last_result,
            }]
    else:
        sid = uuid.uuid4().hex[:8]
        st.session_state.sessions = {sid: {"created_at": time.time(), "label": "新对话"}}
        st.session_state.session_id = sid
        storage.save_session(sid)

if "session_id" not in st.session_state:
    st.session_state.session_id = next(iter(st.session_state.sessions))

# ---------------------------------------------------------------------------
# 回调函数
# ---------------------------------------------------------------------------
def fill_prompt(value: str):
    st.session_state.user_input = value


def clear_all():
    st.session_state.user_input = ""
    st.session_state.conversation = []
    st.session_state._last_context = ""


def do_execute():
    """提交任务到 API，不阻塞，立即返回"""
    text = st.session_state.user_input.strip()
    if not text:
        return

    session_id = st.session_state.session_id

    # 提交到 API
    try:
        resp = requests.post(
            f"{API_BASE}/api/task/submit",
            json={"user_input": text, "session_id": session_id},
            timeout=10,
        )
        resp.raise_for_status()
        task_id = resp.json()["task_id"]
    except Exception:
        st.error(f"后端连接失败，请确认 FastAPI 已启动: {API_BASE}")
        return

    # 追加到对话列表
    st.session_state.conversation.append({
        "user_input": text,
        "task_id": task_id,
        "status": "submitted",
        "result": None,
    })
    st.session_state.user_input = ""

    # 标签
    if session_id in st.session_state.sessions:
        cur_label = st.session_state.sessions[session_id].get("label", "")
        if cur_label == "新对话":
            st.session_state.sessions[session_id]["label"] = text[:30]
            storage.save_session(session_id, label=text[:30])


# ---- 会话管理 ----
def _save_session_state():
    sid = st.session_state.session_id
    if sid in st.session_state.sessions:
        st.session_state.sessions[sid]["conversation"] = list(st.session_state.conversation)


def _restore_session_state(sid: str):
    meta = st.session_state.sessions.get(sid, {})
    st.session_state.conversation = meta.get("conversation", [])
    st.session_state.user_input = ""
    st.session_state._last_context = ""


def new_session():
    _save_session_state()
    sid = uuid.uuid4().hex[:8]
    storage.save_session(sid)
    st.session_state.sessions[sid] = {"created_at": time.time(), "label": "新对话"}
    st.session_state.session_id = sid
    _restore_session_state(sid)


def switch_session(sid: str):
    if sid == st.session_state.session_id:
        return
    _save_session_state()
    st.session_state.session_id = sid
    _restore_session_state(sid)


def delete_session(sid: str):
    agent.memory.delete_session(sid)
    storage.delete_session_data(sid)
    st.session_state.sessions.pop(sid, None)
    if sid == st.session_state.session_id:
        if st.session_state.sessions:
            new_sid = next(iter(st.session_state.sessions))
            st.session_state.session_id = new_sid
            _restore_session_state(new_sid)
        else:
            new_sid = uuid.uuid4().hex[:8]
            storage.save_session(new_sid)
            st.session_state.sessions[new_sid] = {"created_at": time.time(), "label": "新对话"}
            st.session_state.session_id = new_sid
            _restore_session_state(new_sid)


# ---------------------------------------------------------------------------
# 侧边栏
# ---------------------------------------------------------------------------
session_id = st.session_state.session_id

with st.sidebar:
    st.subheader("会话信息")
    st.button("新建会话", width="stretch", icon=":material/add:", on_click=new_session)

    st.text("会话列表")
    sessions = st.session_state.sessions
    sorted_sids = sorted(
        sessions.keys(),
        key=lambda s: sessions[s].get("created_at", 0),
        reverse=True,
    )
    for sid in sorted_sids:
        is_active = sid == session_id
        meta = sessions[sid]
        label = meta.get("label", "新对话")[:28]
        col1, col2 = st.columns([4, 1])
        with col1:
            st.button(
                label, key=f"sw_{sid}", width="stretch",
                type="primary" if is_active else "secondary",
                on_click=switch_session, args=(sid,),
            )
        with col2:
            st.button("", key=f"del_{sid}", width="stretch", icon=":material/delete:",
                      on_click=delete_session, args=(sid,))

    st.divider()

    msgs = storage.get_messages(session_id, limit=20)
    if msgs:
        st.caption(f"已记忆 {len(msgs)} 条消息")
    else:
        st.caption("暂无历史对话")

    with st.expander("调试面板", expanded=False):
        if st.session_state.get("_last_context"):
            st.caption("**注入的完整上下文:**")
            st.code(st.session_state._last_context, language="text")
        else:
            st.caption("尚无上下文（首次对话或无历史）")


# ---------------------------------------------------------------------------
# 标题 + 输入区
# ---------------------------------------------------------------------------
st.title("自动拆解任务、匹配大模型、返回结果")

st.text_area(
    "描述你的需求",
    key="user_input",
    placeholder="例如：生成一张关于未来城市的图片，并写一段描述它的文字",
    height=100,
    label_visibility="collapsed",
)

col_q1, col_q2, col_q3 = st.columns(3)
with col_q1:
    st.button("翻译 Hello World", use_container_width=True,
              on_click=fill_prompt, args=("把 Hello World 翻译成中文",))
with col_q2:
    st.button("生成小猫图片", use_container_width=True,
              on_click=fill_prompt, args=("生成一张小猫的图片",))
with col_q3:
    st.button("生成图片并描述", use_container_width=True,
              on_click=fill_prompt, args=("生成一张小猫的图片，并写一段描述",))

col_btn1, col_btn2, _ = st.columns([1, 1, 4])
with col_btn1:
    st.button("开始执行", type="primary", use_container_width=True, on_click=do_execute)
with col_btn2:
    st.button("清空", use_container_width=True, on_click=clear_all)

# ---------------------------------------------------------------------------
# 后台轮询：更新进行中的任务
# ---------------------------------------------------------------------------
conversation = st.session_state.conversation
in_progress = any(c["status"] not in ("SUCCESS", "PARTIAL_SUCCESS", "FAILED")
                  for c in conversation)

if in_progress:
    with st.status("检查任务状态...", expanded=False) as poll_status:
        changed = False
        for i, conv in enumerate(conversation):
            if conv["status"] in ("SUCCESS", "PARTIAL_SUCCESS", "FAILED"):
                continue
            try:
                resp = requests.get(
                    f"{API_BASE}/api/task/{conv['task_id']}", timeout=5,
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                new_status = data.get("status", "")
                if new_status in ("SUCCESS", "PARTIAL_SUCCESS", "FAILED"):
                    convo = st.session_state.conversation[i]
                    convo["status"] = new_status
                    convo["result"] = data.get("result")
                    changed = True
                else:
                    poll_status.update(
                        label=f"task {conv['task_id'][:12]}... → {new_status}",
                        state="running",
                    )
            except requests.RequestException:
                poll_status.update(label="轮询中（API 暂时无响应）...", state="running")

        if not changed:
            poll_status.update(label="等待任务完成...", state="running")
        else:
            poll_status.update(label="任务更新完成", state="complete")
            st.rerun()

# 在轮询中时展示一个自动刷新提示
if in_progress:
    st.caption(f"正在等待 {sum(1 for c in conversation if c['status'] not in ('SUCCESS','PARTIAL_SUCCESS','FAILED'))} 个任务完成... (每 {POLL_INTERVAL}s 自动刷新)")
    time.sleep(POLL_INTERVAL)
    st.rerun()

# ---------------------------------------------------------------------------
# 对话列表展示
# ---------------------------------------------------------------------------
if not conversation:
    st.stop()

for idx, conv in enumerate(conversation):
    user_input = conv["user_input"]
    status = conv["status"]
    result = conv["result"]
    task_id = conv["task_id"]

    # 用户输入
    st.markdown(f"**You:** {user_input}")

    # 状态 / 结果
    if status in ("submitted", "pending", "processing"):
        st.caption(f"状态: {status} (task: {task_id[:16]}...)")
        st.markdown(
            '<div class="image-skeleton">'
            '<span style="color:#B0B8C1;">处理中...</span>'
            '</div>',
            unsafe_allow_html=True,
        )
    elif result:
        frontend = result.get("frontend_response", {})
        log = result.get("log_record", {})
        task_status = frontend.get("task_status", "FAILED")

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
        data = frontend.get("data", {})
        results = data.get("results", [])
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
                            st.image(img_url, width="stretch")
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

        if task_status in ("SUCCESS", "PARTIAL_SUCCESS"):
            st.success("本轮对话已写入记忆，后续提问可引用上下文")
        if task_status == "FAILED" and data.get("message"):
            st.info(data["message"])

        # 调用链日志（每条对话独立）
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
                            ts_display = ts[:10] if ts else "--"
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
        st.error(f"任务失败: {task_id}")

    # 对话之间有分隔线
    if idx < len(conversation) - 1:
        st.divider()
