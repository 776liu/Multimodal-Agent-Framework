"""生成层提示词辅助（工程 workaround，非架构设计）

解决的实际问题
--------------
扩散式图像/视频模型有明显的"自发文字"倾向：prompt 没提文字，模型也会在画面里
渲染伪文字、水印、乱码字符。这是模型固有缺陷，换模型、调参都无法稳定消除，
只能在 prompt 层面追加负面约束来压制。

处理方式
--------
在 Image/Video Agent 发起调用前，按需给 prompt 追加一句"画面禁止出现文字"的约束。
属于生成层的提示词工程，**不构成系统设计层面的创新**，论文中不作为设计点论述。

为什么需要消歧
--------------
若用户明确要求画面含文字（海报、招牌、logo、字幕…），注入"禁止文字"会造成
指令冲突反而破坏产物，因此需先识别文字诉求；用户已自行写了"不要文字"时也不重复注入。
"""


#: 用户显式要求画面含文字的关键词（中英双语），命中则不注入约束
_TEXT_INTENT_KEYWORDS = (
    "文字", "汉字", "中文", "标题", "标语", "口号", "字幕", "文案",
    "牌匾", "招牌", "店招", "横幅", "海报", "封面", "排版", "题字", "题词",
    "书法", "印章", "落款", "标签", "带字", "写字", "logo", "LOGO", "Logo",
    "text", "lettering", "typography", "typographic", "title", "headline",
    "caption", "subtitle", "slogan", "sign", "signage", "poster", "banner",
    "label", "wordmark", "calligraphy", "chinese characters", "kanji", "hangul",
)

#: 用户已自行表达"画面不要文字"的关键词，命中则不重复注入
_NO_TEXT_KEYWORDS = (
    "不要文字", "不含文字", "无文字", "没有文字", "不带文字", "别加文字",
    "不要字", "无字", "纯画面", "不要水印", "无水印",
    "no text", "without text", "no watermark", "no lettering", "text-free",
)

_IMAGE_NEGATIVE = (
    "画面中禁止出现任何文字、汉字、字母、数字、标语、标题、字幕、水印、签名、"
    "logo、UI 控件或界面元素；不要渲染任何可读文本。"
)

_VIDEO_NEGATIVE = (
    "视频画面中禁止出现任何文字、汉字、字母、数字、标语、标题、字幕、水印、签名、"
    "logo、UI 控件或界面元素；不要渲染任何可读文本，且全片段需保持画面干净无文字。"
)


def has_explicit_no_text(prompt: str) -> bool:
    """用户是否已自行声明"画面不要文字"。"""
    return bool(prompt) and any(k in prompt.lower() for k in _NO_TEXT_KEYWORDS)


def has_text_intent(prompt: str) -> bool:
    """用户是否显式要求画面中出现文字。"""
    if not prompt:
        return False
    if has_explicit_no_text(prompt):
        return False
    return any(k in prompt.lower() for k in _TEXT_INTENT_KEYWORDS)


def apply_no_text(prompt: str, is_video: bool = False) -> str:
    """给视觉生成的 prompt 追加"画面无文字"约束。

    需要追加时返回新 prompt，否则原样返回。幂等：重复调用不会重复追加。
    """
    if not prompt:
        return prompt
    if has_explicit_no_text(prompt) or has_text_intent(prompt):
        return prompt

    constraint = _VIDEO_NEGATIVE if is_video else _IMAGE_NEGATIVE
    if constraint[:20] in prompt:      # 幂等保护
        return prompt

    return f"{prompt.rstrip()}。{constraint}"
