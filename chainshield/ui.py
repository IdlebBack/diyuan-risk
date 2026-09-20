"""Streamlit 视觉系统与安全的静态品牌组件。"""

from __future__ import annotations

from html import escape

import streamlit as st


PALETTE = {
    "navy": "#07172E",
    "blue": "#0B3B66",
    "cyan": "#0EA5A8",
    "orange": "#F59E52",
    "green": "#20A873",
    "ink": "#12233D",
    "muted": "#5E6F86",
    "surface": "#FFFFFF",
    "canvas": "#F4F7FB",
}


GLOBAL_CSS = r"""
<style>
:root {
  --gr-navy: #07172E; --gr-blue: #0B3B66; --gr-cyan: #0EA5A8;
  --gr-orange: #F59E52; --gr-green: #20A873; --gr-ink: #12233D;
  --gr-muted: #5E6F86; --gr-border: #DDE6F0; --gr-canvas: #F4F7FB;
  --gr-shadow: 0 12px 32px rgba(18,35,61,.07);
}
html { scroll-behavior: smooth; }
body, [class*="css"] {
  font-family: "Microsoft YaHei UI", "PingFang SC", "Noto Sans CJK SC",
               "Source Han Sans SC", system-ui, -apple-system, sans-serif;
}
[data-testid="stAppViewContainer"] {
  background: radial-gradient(circle at 82% 2%, rgba(14,165,168,.09), transparent 26rem),
              radial-gradient(circle at 18% 88%, rgba(11,59,102,.045), transparent 32rem),
              var(--gr-canvas);
  color: var(--gr-ink);
}
[data-testid="stHeader"] {
  height: 2rem;
  background: linear-gradient(180deg, rgba(244,247,251,.97), rgba(244,247,251,.78), transparent);
}
[data-testid="stToolbar"], [data-testid="stDecoration"], #MainMenu { display: none !important; }
.stApp [data-testid="stMainBlockContainer"] {
  max-width: 1480px; padding-top: 1.15rem; padding-bottom: 4.5rem;
}

/* 侧栏 */
[data-testid="stSidebar"] {
  background: radial-gradient(circle at 24% 0%, rgba(14,165,168,.23), transparent 14rem),
              linear-gradient(168deg, #0B2949 0%, #07182F 54%, #061328 100%);
  border-right: 1px solid rgba(167,214,225,.15);
  box-shadow: 12px 0 40px rgba(7,23,46,.10);
}
[data-testid="stSidebarContent"] { padding: .85rem .78rem 1.35rem; }
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
[data-testid="stSidebar"] [data-testid="stCaptionContainer"],
[data-testid="stSidebar"] label { color: #C9D8E8; }
[data-testid="stSidebar"] hr { border-color: rgba(202,224,236,.14); margin: 1.05rem .25rem; }
.gr-brand {
  display: flex; align-items: center; gap: .82rem; margin: .15rem .15rem 1.05rem;
  padding: .9rem .78rem; border: 1px solid rgba(165,218,226,.18); border-radius: 16px;
  background: linear-gradient(135deg, rgba(255,255,255,.095), rgba(255,255,255,.025));
  box-shadow: inset 0 1px 0 rgba(255,255,255,.08);
}
.gr-brand-mark {
  flex: 0 0 42px; width: 42px; height: 42px; display: grid; place-items: center;
  border-radius: 13px; background: linear-gradient(145deg, rgba(14,165,168,.27), rgba(14,165,168,.08));
  border: 1px solid rgba(117,224,219,.35); box-shadow: 0 9px 24px rgba(0,0,0,.18);
}
.gr-brand-copy { min-width: 0; line-height: 1.2; }
.gr-brand-kicker {
  display: block; margin-bottom: .2rem; color: #78DED8; font-size: .61rem;
  font-weight: 800; letter-spacing: .15em; text-transform: uppercase;
}
.gr-brand-copy strong { display: block; color: #FFF; font-size: 1.1rem; letter-spacing: .04em; }
.gr-brand-copy small { display: block; margin-top: .22rem; color: #9FB5CA; font-size: .69rem; white-space: nowrap; }
[data-testid="stSidebar"] div[role="radiogroup"] { gap: .16rem; }
[data-testid="stSidebar"] div[role="radiogroup"] > label {
  min-height: 2.72rem; padding: .45rem .64rem; border: 1px solid transparent;
  border-radius: 10px; transition: background .18s ease, border-color .18s ease, transform .18s ease;
}
[data-testid="stSidebar"] div[role="radiogroup"] > label:hover {
  background: rgba(255,255,255,.075); border-color: rgba(165,218,226,.13); transform: translateX(2px);
}
[data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) {
  color: #FFF; background: linear-gradient(90deg, rgba(14,165,168,.26), rgba(14,165,168,.08));
  border-color: rgba(103,218,211,.28); box-shadow: inset 3px 0 0 #45D0C9;
}
[data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) p { color: #FFF !important; font-weight: 700; }
[data-testid="stSidebar"] div[role="radiogroup"] [data-testid="stRadio"] { display: none; }
label[data-testid="stRadioOption"] > div > div > div:first-child { display: none !important; }
label[data-testid="stRadioOption"] > div > div { gap: 0; }
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {
  color: #91AAC1 !important; font-size: .72rem; font-weight: 750; letter-spacing: .08em;
}
[data-testid="stSidebar"] [data-testid="stToggle"] label { padding: .65rem .2rem .2rem; }

/* 轻量页面 hero */
.gr-page-hero {
  position: relative; overflow: hidden; min-height: 150px; margin: 0 0 1.25rem;
  padding: 1.45rem 1.65rem 1.35rem; border: 1px solid rgba(122,168,199,.22);
  border-radius: 20px; color: #FFF;
  background: linear-gradient(110deg, rgba(7,23,46,.98), rgba(9,45,76,.97) 64%, rgba(9,63,87,.94));
  box-shadow: 0 16px 42px rgba(7,23,46,.14);
}
.gr-page-hero::before {
  content: ""; position: absolute; width: 270px; height: 270px; right: -68px; top: -128px;
  border: 1px solid rgba(104,222,215,.20); border-radius: 50%;
  box-shadow: 0 0 0 32px rgba(75,204,201,.035), 0 0 0 72px rgba(75,204,201,.025);
}
.gr-page-hero::after {
  content: ""; position: absolute; right: 48px; bottom: 24px; width: 8px; height: 8px;
  border-radius: 50%; background: #5CE0D8;
  box-shadow: -58px -26px 0 -1px rgba(92,224,216,.72), -115px 20px 0 -2px rgba(92,224,216,.54),
              -36px 32px 0 -2px rgba(245,158,82,.76), -156px -18px 0 -2px rgba(255,255,255,.42);
}
.gr-hero-content { position: relative; z-index: 2; max-width: 74%; }
.gr-hero-topline { display: flex; align-items: center; gap: .65rem; margin-bottom: .55rem; }
.gr-step {
  display: inline-flex; align-items: center; min-height: 1.45rem; padding: .15rem .52rem;
  border: 1px solid rgba(103,218,211,.38); border-radius: 999px; color: #86E7E1;
  background: rgba(14,165,168,.13); font-size: .66rem; font-weight: 800; letter-spacing: .12em;
}
.gr-eyebrow { color: #AFC5D7; font-size: .72rem; font-weight: 650; letter-spacing: .06em; }
.gr-page-hero h1 {
  margin: 0; color: #FFF; font-size: clamp(1.7rem, 3vw, 2.35rem); font-weight: 800;
  line-height: 1.16; letter-spacing: -.025em;
}
.gr-page-hero p { max-width: 810px; margin: .58rem 0 0; color: #C6D7E6; font-size: .9rem; line-height: 1.65; }
.gr-hero-radar { position: absolute; z-index: 1; right: 24px; top: 8px; width: 190px; height: 140px; opacity: .55; pointer-events: none; }

/* 排版 */
.stApp h2, .stApp h3 { color: var(--gr-ink); letter-spacing: -.018em; }
.stApp h2 { margin-top: 1.45rem; font-size: 1.28rem; font-weight: 790; }
.stApp h3 { font-size: 1.05rem; font-weight: 760; }
.stApp p, .stApp li { line-height: 1.72; }
[data-testid="stCaptionContainer"] { color: var(--gr-muted); line-height: 1.6; }
a { color: #087E83; text-decoration-color: rgba(8,126,131,.3); }

/* 指标卡与容器 */
[data-testid="stMetric"] {
  min-height: 108px; padding: 1rem 1.05rem; border: 1px solid var(--gr-border);
  border-radius: 15px; background: linear-gradient(135deg, #FFF, #F8FBFD);
  box-shadow: 0 7px 20px rgba(18,35,61,.055);
  transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease;
}
[data-testid="stMetric"]:hover { transform: translateY(-2px); border-color: rgba(14,165,168,.38); box-shadow: 0 18px 44px rgba(18,35,61,.11); }
[data-testid="stMetricLabel"] p { color: var(--gr-muted); font-size: .76rem; font-weight: 700; letter-spacing: .035em; }
[data-testid="stMetricValue"] { color: var(--gr-ink); font-size: 1.72rem; font-weight: 800; letter-spacing: -.035em; }
[data-testid="stVerticalBlockBorderWrapper"] {
  border-color: var(--gr-border) !important; border-radius: 16px !important;
  background: rgba(255,255,255,.88); box-shadow: var(--gr-shadow);
}

/* 提示 */
[data-testid="stAlert"] { border: 0; border-left: 4px solid currentColor; border-radius: 10px; box-shadow: 0 5px 14px rgba(18,35,61,.045); }
[data-testid="stAlert"] [data-testid="stMarkdownContainer"] p { line-height: 1.6; }
div[data-baseweb="notification"] { border-radius: 10px; }
[data-testid="stAlert"]:has([data-testid="stAlertContentInfo"]) { border-left-color: var(--gr-blue); }
[data-testid="stAlert"]:has([data-testid="stAlertContentWarning"]) { border-left-color: var(--gr-orange); }
[data-testid="stAlert"]:has([data-testid="stAlertContentSuccess"]) { border-left-color: var(--gr-green); }
[data-testid="stAlert"]:has([data-testid="stAlertContentError"]) { border-left-color: #D85D5D; }
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]) { background: #EAF1FC; }
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]) { background: #FFF5E9; }
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]) { background: #EAF8F2; }
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]) { border-left: 4px solid var(--gr-blue); }
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]) { border-left: 4px solid var(--gr-orange); }
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]) { border-left: 4px solid var(--gr-green); }
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]) { border-left: 4px solid #D85D5D; }

/* 标签页 */
[data-baseweb="tab-list"] { gap: .35rem; padding: .3rem; border: 1px solid var(--gr-border); border-radius: 12px; background: #EAF0F6; }
[data-baseweb="tab"] { min-height: 2.45rem; padding: .45rem .9rem; border-radius: 9px; color: var(--gr-muted); font-weight: 700; }
[data-baseweb="tab"]:hover { color: var(--gr-blue); background: rgba(255,255,255,.55); }
[data-baseweb="tab"][aria-selected="true"] { color: var(--gr-blue); background: #FFF; box-shadow: 0 4px 12px rgba(18,35,61,.08); }
[data-baseweb="tab-highlight"], [data-baseweb="tab-border"] { display: none; }
[data-testid="stTabContent"] { padding-top: 1.05rem; }
[role="tablist"] {
  gap: .35rem; padding: .3rem; border: 1px solid var(--gr-border);
  border-radius: 12px; background: #EAF0F6;
}
[data-testid="stTab"] {
  min-height: 2.45rem; padding: .45rem .9rem; border-radius: 9px;
  color: var(--gr-muted); font-weight: 700;
}
[data-testid="stTab"]:hover { color: var(--gr-blue); background: rgba(255,255,255,.55); }
[data-testid="stTab"][aria-selected="true"] {
  color: var(--gr-blue); background: #FFF; box-shadow: 0 4px 12px rgba(18,35,61,.08);
}
[data-testid="stTab"] .react-aria-SelectionIndicator { display: none; }
[data-testid="stTabPanel"] { padding-top: 1.05rem; }

/* 按钮与输入 */
.stButton > button, .stDownloadButton > button {
  min-height: 2.55rem; padding: .48rem 1rem; border-radius: 9px; border-color: #C8D7E6;
  color: var(--gr-blue); background: #FFF; font-weight: 730; box-shadow: 0 4px 12px rgba(18,35,61,.055);
  transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease, background .16s ease;
}
.stButton > button:hover, .stDownloadButton > button:hover {
  transform: translateY(-1px); border-color: var(--gr-cyan); color: #087D80;
  background: #F5FFFE; box-shadow: 0 8px 20px rgba(14,165,168,.13);
}
.stButton > button[kind="primary"] {
  border: 1px solid #0A8D91; color: #FFF; background: linear-gradient(135deg, #0EA5A8, #087B87);
  box-shadow: 0 8px 20px rgba(14,165,168,.22);
}
.stButton > button[kind="primary"]:hover { color: #FFF; background: linear-gradient(135deg, #12B4B2, #086F7D); box-shadow: 0 10px 24px rgba(14,165,168,.30); }
.stButton > button:focus-visible, .stDownloadButton > button:focus-visible,
[data-baseweb="select"] *:focus-visible, input:focus-visible, textarea:focus-visible {
  outline: 3px solid rgba(14,165,168,.24) !important; outline-offset: 2px;
}
[data-baseweb="select"] > div, [data-baseweb="input"] > div, [data-baseweb="textarea"] > div,
[data-testid="stNumberInput"] input, [data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea {
  border-color: #CBD8E6; border-radius: 9px; background: rgba(255,255,255,.95);
}
[data-testid="stSlider"] [role="slider"] { border-color: #FFF; background: var(--gr-cyan); box-shadow: 0 0 0 3px rgba(14,165,168,.17); }

/* 表格 */
[data-testid="stDataFrame"], [data-testid="stDataEditor"] {
  overflow: hidden; border: 1px solid var(--gr-border); border-radius: 13px;
  background: #FFF; box-shadow: 0 7px 22px rgba(18,35,61,.055);
}
[data-testid="stDataFrame"] [role="columnheader"], [data-testid="stDataEditor"] [role="columnheader"] {
  color: var(--gr-blue); background: #EDF3F8 !important; font-weight: 750;
}

/* 折叠面板 */
[data-testid="stExpander"] {
  overflow: hidden; border: 1px solid var(--gr-border) !important; border-radius: 13px !important;
  background: rgba(255,255,255,.88); box-shadow: 0 6px 18px rgba(18,35,61,.045);
}
[data-testid="stExpander"] summary {
  min-height: 3rem; color: var(--gr-ink); font-weight: 740;
  background: linear-gradient(90deg, rgba(255,255,255,.98), rgba(246,250,252,.98));
}
[data-testid="stExpander"] summary:hover { color: #087D80; background: #F4FBFA; }
[data-testid="stExpanderDetails"] { border-top: 1px solid #E7EDF3; padding-top: .8rem; }

/* 图表与 JSON */
[data-testid="stVegaLiteChart"], [data-testid="stPyplotGlobalUse"] {
  padding: .7rem; border: 1px solid var(--gr-border); border-radius: 14px;
  background: #FFF; box-shadow: 0 7px 22px rgba(18,35,61,.05);
}
[data-testid="stJson"] { border: 1px solid var(--gr-border); border-radius: 11px; background: #0A1C32; }

.gr-footer {
  display: flex; align-items: center; justify-content: space-between; gap: 1rem;
  margin-top: 2.8rem; padding: 1rem .2rem .2rem; border-top: 1px solid var(--gr-border);
  color: #718096; font-size: .72rem;
}
.gr-footer strong { color: #426078; font-weight: 730; }
.gr-footer-dot {
  display: inline-block; width: 7px; height: 7px; margin-right: .38rem; border-radius: 50%;
  background: var(--gr-green); box-shadow: 0 0 0 3px rgba(32,168,115,.12);
}
@media (max-width: 900px) {
  .stApp [data-testid="stMainBlockContainer"] { padding: .75rem .85rem 3rem; }
  .gr-page-hero { min-height: 132px; padding: 1.25rem 1.2rem; border-radius: 16px; }
  .gr-hero-content { max-width: 100%; }
  .gr-hero-radar { display: none; }
  .gr-page-hero p { font-size: .84rem; }
  [data-testid="stMetric"] { min-height: 94px; padding: .82rem .9rem; }
  .gr-footer { align-items: flex-start; flex-direction: column; gap: .25rem; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; transition: none !important; }
}
</style>
"""


_RADAR_SVG = """
<svg viewBox="0 0 210 150" aria-hidden="true">
  <g fill="none" stroke="#79DDD8" stroke-width="1">
    <circle cx="135" cy="73" r="24" opacity=".34"/><circle cx="135" cy="73" r="46" opacity=".25"/>
    <circle cx="135" cy="73" r="68" opacity=".17"/><path d="M67 73h136M135 5v136M87 25l96 96M87 121l96-96" opacity=".16"/>
    <path d="M135 73 L183 31 A64 64 0 0 1 199 73 Z" fill="#38C7C0" opacity=".13"/>
  </g>
  <g stroke="#A7EEE9" stroke-width="1" opacity=".52"><path d="M34 112L78 94L104 111L135 73L166 88"/></g>
  <g fill="#6DE1DA"><circle cx="78" cy="94" r="3"/><circle cx="135" cy="73" r="4"/>
    <circle cx="166" cy="88" r="3"/><circle cx="104" cy="111" r="2.5"/></g>
  <circle cx="34" cy="112" r="3" fill="#F6A45E"/>
</svg>
"""


def inject_global_styles() -> None:
    """注入不依赖网络的全局视觉主题。"""

    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


def render_sidebar_brand() -> None:
    """渲染紧凑的侧栏品牌标识。"""

    st.sidebar.markdown(
        """
        <div class="gr-brand">
          <div class="gr-brand-mark" aria-hidden="true">
            <svg width="29" height="29" viewBox="0 0 32 32" fill="none">
              <path d="M16 3.2 27 7.6v7.1c0 7.1-4.4 11.7-11 14.1C9.4 26.4 5 21.8 5 14.7V7.6L16 3.2Z" stroke="#8EE8E3" stroke-width="1.5"/>
              <circle cx="16" cy="15" r="6.5" stroke="#8EE8E3" stroke-width="1.2" opacity=".72"/>
              <path d="M16 15 21.4 11.9" stroke="#F6AE70" stroke-width="1.8" stroke-linecap="round"/>
              <circle cx="16" cy="15" r="1.8" fill="#F6AE70"/>
            </svg>
          </div>
          <div class="gr-brand-copy"><span class="gr-brand-kicker">GEORISK RADAR</span>
            <strong>地缘风险</strong><small>供应链地缘风险雷达</small></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_page_header(step: str, eyebrow: str, title: str, description: str) -> None:
    """渲染每页共用的轻量 hero；所有动态文本先转义。"""

    st.markdown(
        f"""
        <section class="gr-page-hero" aria-labelledby="gr-page-title">
          <div class="gr-hero-content"><div class="gr-hero-topline">
            <span class="gr-step">STEP {escape(step)}</span><span class="gr-eyebrow">{escape(eyebrow)}</span>
          </div><h1 id="gr-page-title">{escape(title)}</h1><p>{escape(description)}</p></div>
          <div class="gr-hero-radar">{_RADAR_SVG}</div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_footer() -> None:
    """渲染全局边界提示。"""

    st.markdown(
        """
        <footer class="gr-footer">
          <span><span class="gr-footer-dot"></span><strong>确定性模型可复现</strong> · AI 仅作辅助解读</span>
          <span>西北民族大学 · 林明强 · 陈治希 · 李宇欣</span>
        </footer>
        """,
        unsafe_allow_html=True,
    )
