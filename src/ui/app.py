import streamlit as st
from src.core.router import Router
from src.core.llm_client import LLMClient
from src.core.task_router import TaskRouter
from src.core.builder import Builder
from src.core.agent import Agent

# ---------------------------------------------------------------------------
# 页面配置
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="多模态 AI Agent",
    page_icon="",
    layout="wide",
    initial_sidebar_state="collapsed",
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
    return Agent(task_router, router, llm_client, builder)


agent = load_agent()

# ---------------------------------------------------------------------------
# 初始化 session state
# ---------------------------------------------------------------------------
if "user_input" not in st.session_state:
    st.session_state.user_input = ""
if "result" not in st.session_state:
    st.session_state.result = None

# ---------------------------------------------------------------------------
# 回调函数（在 widget 创建前执行，安全修改 session_state）
# ---------------------------------------------------------------------------
def fill_prompt(value: str):
    st.session_state.user_input = value


def clear_all():
    st.session_state.user_input = ""
    st.session_state.result = None


def do_execute():
    """执行 Agent，结果存入 session_state，清空输入框"""
    text = st.session_state.user_input.strip()
    if text:
        st.session_state.result = agent.run(text)
        st.session_state.user_input = ""


# ---------------------------------------------------------------------------
# 标题
# ---------------------------------------------------------------------------
st.title("自动拆解任务、匹配大模型、返回结果")
# ---------------------------------------------------------------------------
# 输入区域
# ---------------------------------------------------------------------------
st.markdown('<div class="input-card">', unsafe_allow_html=True)

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

st.markdown('</div>', unsafe_allow_html=True)

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
                    st.warning("图片 URL 为空")

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
