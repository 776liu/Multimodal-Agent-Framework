import streamlit as st
import time
from datetime import datetime
from src.core.router import Router
from src.core.llm_client import LLMClient
from src.core.task_router import TaskRouter
from src.core.builder import Builder
from src.core.memory import Memory
from src.core.agent import Agent

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
        --shadow-lg: 0 8px 32px rgba(108,92,231,0.12);
    }

    .stApp {
        background: linear-gradient(135deg, #F8F9FE 0%, #F0F2FF 50%, #F8F9FE 100%);
    }

    .main .block-container {
        padding-top: 2rem;
        max-width: 1200px;
    }

    /* 图片占位骨架屏 */
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

    /* 结果卡片 */
    .result-card {
        background: var(--bg-card);
        border-radius: var(--radius);
        padding: 1.5rem;
        margin: 1rem 0;
        box-shadow: var(--shadow-sm);
        border: 1px solid var(--border);
    }
    .result-card .result-header {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 1rem;
        padding-bottom: 0.75rem;
        border-bottom: 1px solid var(--border);
    }
    .result-card .result-badge {
        font-size: 0.78rem;
        padding: 4px 12px;
        border-radius: 12px;
        font-weight: 600;
    }
    .result-card .result-badge.text {
        background: #E8F4FD;
        color: #0984E3;
    }
    .result-card .result-badge.image {
        background: #FDE8FF;
        color: #A855F7;
    }

    /* 状态横幅 */
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
        color: #00896B;
        border: 1px solid #B2F0D6;
    }
    .status-banner.partial {
        background: linear-gradient(135deg, #FFF8E1, #FFF3CD);
        color: #B8860B;
        border: 1px solid #FDE68A;
    }
    .status-banner.failed {
        background: linear-gradient(135deg, #FFE8E8, #FDE8E8);
        color: #C0392B;
        border: 1px solid #F5C6C6;
    }

    /* 调用链时间线 */
    .timeline {
        position: relative;
        padding-left: 28px;
    }
    .timeline::before {
        content: '';
        position: absolute;
        left: 8px;
        top: 0;
        bottom: 0;
        width: 2px;
        background: linear-gradient(to bottom, var(--primary-light), var(--border));
    }
    .timeline-item {
        position: relative;
        margin-bottom: 1rem;
        padding: 0.75rem 1rem;
        background: var(--bg-card);
        border-radius: 10px;
        border: 1px solid var(--border);
        font-size: 0.88rem;
    }
    .timeline-item::before {
        content: '';
        position: absolute;
        left: -24px;
        top: 14px;
        width: 10px;
        height: 10px;
        border-radius: 50%;
        border: 2px solid white;
    }
    .timeline-item.ok::before {
        background: var(--success);
        box-shadow: 0 0 0 3px rgba(0,184,148,0.2);
    }
    .timeline-item.err::before {
        background: var(--danger);
        box-shadow: 0 0 0 3px rgba(255,118,117,0.2);
    }
    .timeline-item .tl-model {
        font-weight: 700;
        color: var(--primary);
    }
    .timeline-item .tl-meta {
        color: var(--text-secondary);
        font-size: 0.8rem;
    }

    [data-testid="stExpander"] details {
        border: 1px solid var(--border) !important;
        border-radius: var(--radius) !important;
        box-shadow: var(--shadow-sm) !important;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# 初始化核心引擎（缓存，只执行一次）
# ---------------------------------------------------------------------------
@st.cache_resource
def load_agent():
    router = Router()
    llm_client = LLMClient()
    task_router = TaskRouter(router, llm_client)
    builder = Builder()
    memory = Memory(max_history=10)
    return Agent(task_router, router, llm_client, builder, memory)


agent = load_agent()

# ---------------------------------------------------------------------------
# 初始化 session state
# ---------------------------------------------------------------------------
if "user_input" not in st.session_state:
    st.session_state.user_input = ""
if "result" not in st.session_state:
    st.session_state.result = None
if "_should_run" not in st.session_state:
    st.session_state._should_run = False
if "_input_to_run" not in st.session_state:
    st.session_state._input_to_run = ""
if "_last_context" not in st.session_state:
    st.session_state._last_context = ""

# ---- 多会话管理器 ----
if "sessions" not in st.session_state:
    default_sid = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    st.session_state.sessions = {
        default_sid: {"created_at": time.time(), "label": "新对话"}
    }
if "session_id" not in st.session_state:
    st.session_state.session_id = next(iter(st.session_state.sessions))

# ---------------------------------------------------------------------------
# 回调函数（在 widget 创建前执行，安全修改 session_state）
# ---------------------------------------------------------------------------
def fill_prompt(value: str):
    st.session_state.user_input = value


def clear_all():
    st.session_state.user_input = ""
    st.session_state.result = None
    st.session_state._last_context = ""


def do_execute():
    """保存输入并标记待执行，同时清空输入框"""
    text = st.session_state.user_input.strip()
    if text:
        st.session_state._input_to_run = text
        st.session_state.user_input = ""
        st.session_state._should_run = True


# ---- 会话管理 ----
def _save_session_state():
    """把当前页面临时状态存回 sessions 字典"""
    sid = st.session_state.session_id
    if sid in st.session_state.sessions:
        st.session_state.sessions[sid]["result"] = st.session_state.result
        st.session_state.sessions[sid]["user_input"] = st.session_state.user_input
        st.session_state.sessions[sid]["_last_context"] = st.session_state._last_context


def _restore_session_state(sid: str):
    """从 sessions 字典恢复页面状态"""
    meta = st.session_state.sessions.get(sid, {})
    st.session_state.result = meta.get("result")
    st.session_state.user_input = meta.get("user_input", "")
    st.session_state._last_context = meta.get("_last_context", "")


def new_session():
    _save_session_state()
    sid = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
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
    agent.memory.sessions.pop(sid, None)
    st.session_state.sessions.pop(sid, None)
    if sid == st.session_state.session_id:
        if st.session_state.sessions:
            new_sid = next(iter(st.session_state.sessions))
            st.session_state.session_id = new_sid
            _restore_session_state(new_sid)
        else:
            # 最后一个会话被删，自动建一个新的
            new_sid = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
            st.session_state.sessions[new_sid] = {"created_at": time.time(), "label": "新对话"}
            st.session_state.session_id = new_sid
            _restore_session_state(new_sid)



# ---------------------------------------------------------------------------
# 侧边栏：partner_01 风格 — 会话列表 + 记忆 + 调试
# ---------------------------------------------------------------------------
session_id = st.session_state.session_id

with st.sidebar:
    st.subheader("会话信息")

    st.button("新建会话", width="stretch", icon=":material/add:", on_click=new_session)

    st.text("会话列表")
    sessions = st.session_state.sessions
    for sid in sorted(sessions.keys(), reverse=True):
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

    # 当前会话记忆
    history = agent.memory.get_history(session_id)
    if history:
        st.caption(f"已记忆 {len(history)} 条消息")
    else:
        st.caption("暂无历史对话")

    with st.expander("调试面板", expanded=False):
        if st.session_state.get("_last_context"):
            st.caption("**注入的完整上下文:**")
            st.code(st.session_state._last_context, language="text")
        else:
            st.caption("尚无上下文（首次对话或无历史）")


# ---------------------------------------------------------------------------
# 标题
# ---------------------------------------------------------------------------
st.title("自动拆解任务、匹配大模型、返回结果")
# ---------------------------------------------------------------------------
# 输入区域
# ---------------------------------------------------------------------------
st.text_area(
    "描述你的需求",
    key="user_input",
    placeholder="例如：生成一张关于未来城市的图片，并写一段描述它的文字",
    height=100,
    label_visibility="collapsed",
)

# 快捷提示词按钮
col_q1, col_q2, col_q3, col_q4 = st.columns(4)
with col_q1:
    st.button(
        "翻译 Hello World", use_container_width=True,
        on_click=fill_prompt, args=("把 Hello World 翻译成中文",),
    )
with col_q2:
    st.button(
        "生成小猫图片", use_container_width=True,
        on_click=fill_prompt, args=("生成一张小猫的图片",),
    )
with col_q3:
    st.button(
        "生成图片并描述", use_container_width=True,
        on_click=fill_prompt, args=("生成一张小猫的图片，并写一段描述",),
    )

# 执行 / 清空
col_btn1, col_btn2, _ = st.columns([1, 1, 4])
with col_btn1:
    st.button("开始执行", type="primary", use_container_width=True, on_click=do_execute)
with col_btn2:
    st.button("清空", use_container_width=True, on_click=clear_all)

# ---------------------------------------------------------------------------
# 执行阶段 — 带实时进度反馈
# ---------------------------------------------------------------------------
if st.session_state._should_run:
    st.session_state._should_run = False
    text = st.session_state._input_to_run
    st.session_state._input_to_run = ""

    start_time = time.time()
    TIMEOUT_SECONDS = 180

    with st.status("分析意图，拆解任务...", expanded=True) as status_widget:
        progress_bar = st.progress(0, text="准备中...")

        def on_progress(event: dict):
            stage = event["stage"]
            if stage == "planning":
                status_widget.update(label="分析意图，拆解任务...", state="running")
                progress_bar.progress(0, text="TaskRouter 解析中...")
            elif stage == "planned":
                count = event.get("count", 0)
                status_widget.update(label=f"任务拆解完成，共 {count} 个子任务", state="running")
                progress_bar.progress(0.05, text=f"已拆解为 {count} 个步骤")
            elif stage == "routing":
                step = event["step"]; total = event["total"]
                pct = 0.05 + 0.85 * (step - 1) / total
                status_widget.update(label=f"步骤 {step}/{total}: 匹配可用模型...", state="running")
                progress_bar.progress(pct, text=f"步骤 {step}/{total}: 查询模型注册中心...")
            elif stage == "calling":
                step = event["step"]; total = event["total"]
                model_name = event.get("model", "--")
                pct = 0.05 + 0.85 * (step - 0.5) / total
                status_widget.update(label=f"步骤 {step}/{total}: 正在调用 {model_name}...", state="running")
                progress_bar.progress(pct, text=f"步骤 {step}/{total}: 等待 {model_name} 响应...")
            elif stage == "subtask_done":
                step = event["step"]; total = event["total"]
                model_name = event.get("model", "--")
                is_ok = event.get("status") == "ok"
                label = (
                    f"步骤 {step}/{total}: {model_name} 调用成功"
                    if is_ok else
                    f"步骤 {step}/{total}: {model_name} 调用失败 (错误码: {event.get('error_code', '--')})"
                )
                pct = 0.05 + 0.85 * step / total
                status_widget.update(label=label, state="running")
                progress_bar.progress(pct, text=label)

        # 保存注入的完整上下文供调试面板查看
        history_before = agent.memory.get_history(session_id)
        if history_before:
            st.session_state._last_context = agent.memory.build_context(session_id, text)
        else:
            st.session_state._last_context = text

        result = agent.run(text, session_id, on_progress=on_progress)
        elapsed = time.time() - start_time

        if elapsed > TIMEOUT_SECONDS:
            status_widget.update(label=f"执行超时 (耗时 {elapsed:.0f}s)", state="error")
        else:
            status_widget.update(label=f"执行完成 (耗时 {elapsed:.1f}s)", state="complete")
        progress_bar.progress(1.0, text="完成")

    # 超时告警
    log_data = result.get("log_record", {})
    if any(c.get("error_code") == 408 for c in log_data.get("call_chain", [])):
        st.warning("部分模型调用超时，已自动切换备选模型")
    if elapsed > TIMEOUT_SECONDS:
        st.warning("生成超时，请重试")

    st.session_state.result = result

    # 首次执行后自动给会话打标签
    if session_id in st.session_state.sessions:
        cur_label = st.session_state.sessions[session_id].get("label", "")
        if cur_label == "新对话":
            st.session_state.sessions[session_id]["label"] = text[:30]

    st.rerun()

# ---------------------------------------------------------------------------
# 无结果时提前结束
# ---------------------------------------------------------------------------
if st.session_state.result is None and not st.session_state.user_input.strip():
    st.stop()

# ---------------------------------------------------------------------------
# 结果展示
# ---------------------------------------------------------------------------
result = st.session_state.result
if result is None:
    st.stop()

frontend = result["frontend_response"]
log = result["log_record"]
task_status = frontend.get("task_status", "FAILED")
task_id = frontend.get("task_id", "--")

status_map = {
    "SUCCESS":         ("success",  "任务执行成功"),
    "PARTIAL_SUCCESS": ("partial",  "部分任务完成 -- 部分模型的备选已耗尽"),
    "FAILED":          ("failed",   "任务执行失败 -- 所有模型均已耗尽"),
}
status_class, status_text = status_map.get(task_status, ("failed", "未知状态"))
st.markdown(
    f'<div class="status-banner {status_class}">'
    f'<span>{status_text}</span>'
    f'<span style="margin-left:auto;font-size:0.8rem;opacity:0.7;">ID: {task_id}</span>'
    f'</div>',
    unsafe_allow_html=True,
)

# 生成结果
data = frontend.get("data", {})
results = data.get("results", [])

if results:
    st.markdown("### 生成结果")
    cols = st.columns(min(len(results), 2))
    for i, item in enumerate(results):
        col_idx = i % 2
        with cols[col_idx]:
            st.markdown('<div class="result-card">', unsafe_allow_html=True)

            if item.get("type") == "image":
                st.markdown(
                    '<div class="result-header">'
                    '<span class="result-badge image">图片生成</span>'
                    f'<span style="font-size:0.85rem;color:#636E72;">结果 #{i + 1}</span>'
                    '</div>',
                    unsafe_allow_html=True,
                )
                img_url = item.get("url", "")
                if img_url:
                    st.image(img_url, use_column_width=True)
                else:
                    st.markdown(
                        '<div class="image-skeleton">'
                        '<span style="color:#B0B8C1;">图片加载中...</span>'
                        '</div>',
                        unsafe_allow_html=True,
                    )

            elif item.get("type") == "text":
                st.markdown(
                    '<div class="result-header">'
                    '<span class="result-badge text">文本生成</span>'
                    f'<span style="font-size:0.85rem;color:#636E72;">结果 #{i + 1}</span>'
                    '</div>',
                    unsafe_allow_html=True,
                )
                content = item.get("content", "")
                st.markdown(
                    f'<div style="background:#F8F9FE;padding:1rem;border-radius:10px;'
                    f'font-size:0.95rem;line-height:1.7;color:#2D3436;white-space:pre-wrap;">'
                    f'{content}</div>',
                    unsafe_allow_html=True,
                )

            st.markdown('</div>', unsafe_allow_html=True)

# 记忆写入确认
if task_status in ("SUCCESS", "PARTIAL_SUCCESS"):
    st.success("本轮对话已写入记忆，后续提问可引用上下文")

# 失败提示
if task_status == "FAILED" and data.get("message"):
    st.info(data["message"])

st.divider()

# ---------------------------------------------------------------------------
# 调用链日志
# ---------------------------------------------------------------------------
with st.expander("查看内部调用链与日志", expanded=False):
    tab1, tab2 = st.tabs(["调用链时间线", "错误摘要"])

    with tab1:
        call_chain = log.get("call_chain", [])
        if not call_chain:
            st.caption("暂无调用记录")
        else:
            st.markdown('<div class="timeline">', unsafe_allow_html=True)
            for idx, call in enumerate(call_chain, 1):
                is_ok = call.get("status") == "SUCCESS"
                css_class = "ok" if is_ok else "err"
                status_text_item = "[OK]" if is_ok else "[FAIL]"

                ts = call.get("attempted_at", "")
                try:
                    from datetime import datetime
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
                    f'<br><span class="tl-meta">{ts_display}</span>'
                    f'{error_part}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            st.markdown('</div>', unsafe_allow_html=True)

    with tab2:
        errors = log.get("error_summary", [])
        if not errors:
            st.success("无错误 -- 所有调用均成功")
        else:
            for i, err in enumerate(errors, 1):
                st.markdown(
                    f'<div style="background:#FFF5F5;border:1px solid #FED7D7;'
                    f'border-radius:10px;padding:0.75rem 1rem;margin-bottom:0.5rem;">'
                    f'<strong style="color:#C0392B;">#{i}</strong>&nbsp;&nbsp;'
                    f'模型: <code>{err.get("model_name", "--")}</code>&nbsp;·&nbsp;'
                    f'能力: <code>{err.get("capability", "--")}</code>&nbsp;·&nbsp;'
                    f'错误码: <code style="color:#E74C3C;">{err.get("error_code", "--")}</code>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
