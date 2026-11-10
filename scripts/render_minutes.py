#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""深色图文纪要渲染器 v3（玻璃拟态 + 霓虹发光 + 极光背景）。

用法不变：
  --from-markup <file> | --from-json <json>
  --duration --date --audio --transcript --out
"""
import json, os, re, sys, argparse, html

HERE = os.path.dirname(os.path.abspath(__file__))
# 模块可能装在技能包内，也可能按旧布局单独部署，逐个找
TOOLS_CANDIDATES = [
    os.path.join(HERE, "..", "assets", "minutes-tools.js"),
    os.path.join(os.path.expanduser("~"), ".hermes", "scripts", "assets", "minutes-tools.js"),
    os.path.join(os.path.expanduser("~"), ".workbuddy", "skills", "录音转写", "assets", "minutes-tools.js"),
]


def load_tools():
    """导出 Word / 复制文字的能力模块（零依赖，随页面内联）。"""
    js = None
    for path in TOOLS_CANDIDATES:
        try:
            with open(path, encoding="utf-8") as f:
                js = f.read()
            break
        except OSError:
            continue
    if js is None:
        print("! 未找到 minutes-tools.js，页面将缺少导出/复制能力", file=sys.stderr)
        return ""
    # 内联前转义结束标签，避免 HTML 解析器提前截断脚本
    return js.replace("</script", "<\\/script")

def esc(s):
    return html.escape(s)

TS_RE = re.compile(r"[（(\[]\s*(\d{1,3}):(\d{2})\s*[)）\]]")

def link_ts(s):
    """把（mm:ss）/ [mm:ss] 包成可点击跳转的时间标签。s 必须是已转义的文本。"""
    def rep(m):
        sec = int(m.group(1)) * 60 + int(m.group(2))
        return f'<a class="tref" data-t="{sec}" href="javascript:void(0)">{m.group(0)}</a>'
    return TS_RE.sub(rep, s)

def parse_attrs(s):
    return dict(re.findall(r'(\w+)="([^"]*)"', s))

def render_body(body):
    body = body.strip()
    if "<li>" in body:
        items = re.findall(r"<li>(.*?)</li>", body, re.S)
        return "<ul>" + "".join(f"<li>{link_ts(esc(i.strip()))}</li>" for i in items) + "</ul>"
    return f"<p>{link_ts(esc(body))}</p>"

# 板块色系（霓虹）：亮色 / 发光 / 深底 / 淡底
THEMES = {
    "核心争议焦点": ("#FB7185", "#F43F5E", "rgba(244,63,94,.14)", "rgba(244,63,94,.22)"),
    "部门回应与处理态度": ("#FBBF24", "#F59E0B", "rgba(245,158,11,.14)", "rgba(245,158,11,.22)"),
    "关键决策与行动方向": ("#34D399", "#10B981", "rgba(16,185,129,.14)", "rgba(16,185,129,.22)"),
    "背景与材料": ("#60A5FA", "#3B82F6", "rgba(59,130,246,.14)", "rgba(59,130,246,.22)"),
    "后续行动项": ("#34D399", "#10B981", "rgba(16,185,129,.14)", "rgba(16,185,129,.22)"),
}
DEFAULT_THEME = ("#60A5FA", "#3B82F6", "rgba(59,130,246,.14)", "rgba(59,130,246,.22)")

GLYPHS = {"起点": "起", "核心": "核", "进行中": "办", "明确要求": "诉",
          "转折": "转", "关键": "键", "结束": "终", "结果": "果", "风险": "险", "结论": "论"}
ICONS = {"flag": "🚩", "calendar": "📋", "person": "👤", "book": "📕", "fire": "🔥",
         "alarm-clock": "⏰", "trophy": "🏆", "compass": "🧭", "check": "✅",
         "question": "❓", "warning": "⚠️", "target": "🎯", "link": "🔗"}

def render_section(title, inner, is_step):
    light, accent, bg, bg2 = THEMES.get(title, DEFAULT_THEME)
    if is_step:
        cards = re.findall(r"<rich-card([^>]*)>(.*?)</rich-card>", inner, re.S)
        nodes = ""
        for i, (attrs, body) in enumerate(cards, 1):
            a = parse_attrs(attrs)
            label, tag, comment = a.get("label", ""), a.get("tags", ""), a.get("comment", "")
            glyph = GLYPHS.get(tag, str(i))
            nodes += f"""
            <div class="step-node">
              <div class="step-icon" style="background:linear-gradient(135deg,{light},{accent}); box-shadow:0 0 0 5px {bg}, 0 0 22px {accent}">{esc(glyph)}</div>
              <div class="step-card" style="border-left-color:{accent}">
                <div class="sc-head"><b>{esc(label)}</b>
                  {('<span class="tag" style="background:' + bg + '; color:' + light + '; box-shadow:0 0 10px ' + bg + '">' + esc(tag) + '</span>') if tag else ''}</div>
                {('<div class="sc-comment">' + esc(comment) + '</div>') if comment else ''}
                {render_body(body)}
              </div>
            </div>"""
        inner_html = f'<div class="step-line">{nodes}</div>'
    else:
        cards_html = ""
        for attrs, body in re.findall(r"<simple-card([^>]*)>(.*?)</simple-card>", inner, re.S):
            a = parse_attrs(attrs)
            cards_html += f"""
            <div class="gcard" style="border-left-color:{accent}">
              <div class="gc-title" style="color:{light}; text-shadow:0 0 14px {bg2}">{esc(a.get('label',''))}</div>
              {render_body(body)}
              {('<div class="gc-tag" style="background:' + bg + '; color:' + light + '; border:1px solid ' + bg2 + '">' + esc(a.get('comment','')) + '</div>') if a.get('comment') else ''}
            </div>"""
        for attrs, body in re.findall(r"<rich-card([^>]*)>(.*?)</rich-card>", inner, re.S):
            a = parse_attrs(attrs)
            icon = ICONS.get(a.get("icon", ""), "📌")
            cards_html += f"""
            <div class="gcard" style="border-left-color:{accent}">
              <div class="sc-head"><span class="gc-title" style="color:{light}; text-shadow:0 0 14px {bg2}">{icon} {esc(a.get('label',''))}</span>
                {('<span class="tag" style="background:' + bg + '; color:' + light + '; box-shadow:0 0 10px ' + bg + '">' + esc(a.get('tags','')) + '</span>') if a.get('tags') else ''}</div>
              {('<div class="sc-comment">' + esc(a.get('comment','')) + '</div>') if a.get('comment') else ''}
              {render_body(body)}
            </div>"""
        inner_html = f'<div class="grid">{cards_html}</div>'

    return f"""
<div class="block" style="--g:{light}">
  <div class="block-glow" style="background:radial-gradient(600px 120px at 10% -20%, {bg2}, transparent 70%)"></div>
  <div class="block-title"><span class="star" style="background:linear-gradient(135deg,{light},{accent}); box-shadow:0 0 16px {bg2}">★</span>{esc(title)}</div>
  {inner_html}
</div>"""

def build_html(title, summary, blocks_html, meta, transcript=None, tools_js=""):
    banner = ""
    has_audio = bool(meta.get("audio"))
    au_src = esc(meta.get("audio") or "")
    if has_audio or meta.get("duration") or meta.get("date"):
        if has_audio:
            info = f'<div class="banner-t">回听 纪要原始录音</div><div class="banner-file">🎧 {au_src}</div>'
            qr = '<div class="qr play">▶</div>'
        else:
            info = '<div class="banner-t">纪要原始录音（未附音频）</div>'
            qr = '<div class="qr">无<br>音频</div>'
        meta_spans = ""
        if meta.get("duration"):
            meta_spans += f'<span>⏱ {esc(meta["duration"])}</span>'
        if meta.get("date"):
            meta_spans += f'<span>🗓 {esc(meta["date"])}</span>'
        banner = f"""<div class="banner">
  {qr}
  <div>{info}<div class="banner-s">{meta_spans}</div></div>
  <div class="banner-r"><div class="mascot">🐼</div><div>图文纪要</div></div>
</div>"""
        if has_audio:
            banner += f"""
<div class="aud-wrap"><audio id="min-audio" controls preload="metadata" src="{au_src}"></audio><span class="aud-hint">点正文里的时间可跳转</span></div>"""

    trans_html = ""
    if transcript:
        dot_colors = ["#3B82F6", "#10B981", "#F59E0B", "#8B5CF6", "#EF4444", "#06B6D4"]
        name_idx = {}
        rows = ""
        nrow = 0
        for ln in transcript.splitlines():
            ln = ln.strip()
            if not ln:
                continue
            nrow += 1
            if "]" in ln:
                ts, txt = ln.split("]", 1)
                ts = ts.strip() + "]"
                txt = txt.strip()
                m = re.search(r"说话人(\d+)", txt)
                if m:
                    idx = int(m.group(1)) - 1
                else:
                    nm = re.match(r"([^：:]{1,14})[：:]", txt)
                    key = nm.group(1).strip() if nm else ""
                    if key and key not in name_idx:
                        name_idx[key] = len(name_idx)
                    idx = name_idx.get(key, -1)
                dot = ""
                if idx >= 0:
                    c = dot_colors[idx % len(dot_colors)]
                    dot = f'<span class="t-dot" style="background:{c}; box-shadow:0 0 8px {c}"></span>'
                ts_html = esc(ts)
                if has_audio:
                    mt = re.search(r"(\d{1,3}):(\d{2})", ts)
                    if mt:
                        sec = int(mt.group(1)) * 60 + int(mt.group(2))
                        ts_html = f'<a class="tref" data-t="{sec}" href="javascript:void(0)">{esc(ts)}</a>'
                rows += f'<div class="t-row"><span class="t-ts">{ts_html}</span>{dot}<span class="t-txt">{esc(txt)}</span></div>'
            else:
                rows += f'<div class="t-row"><span class="t-txt full">{esc(ln)}</span></div>'
        n = nrow
        trans_html = f"""
<div class="block transcript-block">
  <div class="block-title"><span class="star" style="background:linear-gradient(135deg,#A78BFA,#8B5CF6); box-shadow:0 0 16px rgba(139,92,246,.4)">📄</span>录音转写全文（{n} 行 · 说话人色点标注）</div>
  <details open>
    <summary>展开 / 收起全文</summary>
    <div class="t-body">{rows}</div>
  </details>
</div>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)}</title>
<style>
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:-apple-system,"PingFang SC","HarmonyOS Sans SC","Microsoft YaHei",sans-serif; background:#080D1A; color:#E2E8F0; line-height:1.75; }}
  .wrap {{ max-width:880px; margin:0 auto; padding:36px 22px 80px; position:relative; }}
  /* 极光背景 */
  .wrap::before {{ content:""; position:fixed; inset:0; z-index:-1; pointer-events:none;
    background:
      radial-gradient(900px 500px at 85% -10%, rgba(59,130,246,.16), transparent 60%),
      radial-gradient(700px 420px at -10% 30%, rgba(139,92,246,.12), transparent 60%),
      radial-gradient(800px 460px at 60% 110%, rgba(16,185,129,.10), transparent 60%); }}
  /* 回听横幅：玻璃拟态 */
  .banner {{ background:rgba(255,255,255,.05); backdrop-filter:blur(14px); -webkit-backdrop-filter:blur(14px);
    border:1px solid rgba(255,255,255,.10); border-radius:18px; padding:18px 24px; display:flex; align-items:center; gap:18px;
    margin-bottom:28px; box-shadow:0 8px 30px rgba(0,0,0,.35), inset 0 1px 0 rgba(255,255,255,.08); }}
  .qr {{ width:60px; height:60px; background:rgba(255,255,255,.07); border-radius:12px; display:flex; flex-direction:column; align-items:center; justify-content:center;
    font-size:11px; color:#93C5FD; border:1px dashed rgba(147,197,253,.4); font-weight:600; flex:none; }}
  .banner-t {{ font-size:17px; font-weight:800; color:#93C5FD; letter-spacing:.5px; text-shadow:0 0 20px rgba(59,130,246,.5); }}
  .banner-file {{ font-size:12.5px; color:#94A3B8; margin-top:2px; }}
  .banner-s {{ margin-top:6px; }}
  .banner-s span {{ background:rgba(255,255,255,.06); border:1px solid rgba(255,255,255,.10); padding:2px 11px; border-radius:99px; margin-right:8px; font-size:12px; color:#CBD5E1; }}
  .banner-r {{ margin-left:auto; text-align:center; color:#93C5FD; font-size:11px; }}
  .mascot {{ font-size:30px; }}
  /* 标题摘要 */
  .doc-title {{ font-size:26px; font-weight:900; letter-spacing:.5px; line-height:1.45; padding-left:16px; border-left:5px solid transparent;
    border-image:linear-gradient(180deg,#60A5FA,#8B5CF6) 1; text-shadow:0 2px 24px rgba(59,130,246,.35); }}
  .doc-summary {{ margin-top:18px; background:rgba(255,255,255,.05); backdrop-filter:blur(10px); border:1px solid rgba(255,255,255,.09);
    border-radius:14px; padding:18px 22px; font-size:14px; color:#B6C2D9; line-height:1.9; box-shadow:0 4px 20px rgba(0,0,0,.25); }}
  /* 板块：玻璃卡 */
  .block {{ margin-top:30px; border-radius:20px; padding:24px 26px; position:relative; overflow:hidden;
    background:rgba(255,255,255,.04); border:1px solid rgba(255,255,255,.08);
    box-shadow:0 10px 36px rgba(0,0,0,.35), inset 0 1px 0 rgba(255,255,255,.06); }}
  .block-glow {{ position:absolute; inset:-40px auto auto -40px; width:140%; height:140%; pointer-events:none; }}
  .block-title {{ display:flex; align-items:center; gap:11px; font-size:18px; font-weight:800; letter-spacing:.5px; margin-bottom:18px; color:#F1F5F9; position:relative; }}
  .star {{ width:30px; height:30px; border-radius:9px; color:#fff; display:flex; align-items:center; justify-content:center; font-size:14px; }}
  .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; align-items:stretch; position:relative; }}
  .gcard {{ background:rgba(13,21,38,.75); backdrop-filter:blur(8px); border:1px solid rgba(255,255,255,.08); border-left:4px solid var(--accent,#3B82F6);
    border-radius:14px; padding:18px 20px; display:flex; flex-direction:column; height:100%;
    box-shadow:0 6px 20px rgba(0,0,0,.28); transition:transform .18s ease, box-shadow .18s ease, border-color .18s ease; position:relative; }}
  .gcard:hover {{ transform:translateY(-3px); box-shadow:0 12px 30px rgba(0,0,0,.4), 0 0 24px var(--g2, rgba(59,130,246,.15)); }}
  .gcard:last-child:nth-child(odd) {{ grid-column:1/-1; }}
  .gc-title {{ font-size:15.5px; font-weight:800; margin-bottom:8px; }}
  .sc-head {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:6px; gap:8px; }}
  .gcard p {{ font-size:13px; color:#A8B6CE; flex:1 0 auto; }}
  .gcard ul {{ padding-left:18px; font-size:13px; color:#A8B6CE; flex:1 0 auto; }}
  .gcard li {{ margin-bottom:5px; }}
  .gc-tag {{ display:inline-block; font-size:12px; font-weight:700; padding:3px 12px; border-radius:999px; margin-top:12px; align-self:flex-start; }}
  .tag {{ font-size:11.5px; font-weight:700; padding:2px 11px; border-radius:999px; }}
  .sc-comment {{ font-size:12px; color:#64748B; margin-bottom:6px; }}
  /* 时间线：发光节点 */
  .step-line {{ position:relative; padding-left:56px; }}
  .step-line::before {{ content:""; position:absolute; left:27px; top:16px; bottom:16px; width:2px;
    background:linear-gradient(180deg, rgba(16,185,129,.5), rgba(16,185,129,.08)); }}
  .step-node {{ position:relative; margin-bottom:20px; }}
  .step-icon {{ position:absolute; left:-56px; top:9px; width:40px; height:40px; border-radius:50%; color:#fff; font-size:17px; font-weight:800;
    display:flex; align-items:center; justify-content:center; }}
  .step-card {{ background:rgba(13,21,38,.75); backdrop-filter:blur(8px); border:1px solid rgba(255,255,255,.08); border-left:4px solid #10B981;
    border-radius:14px; padding:16px 20px; box-shadow:0 6px 20px rgba(0,0,0,.28); transition:transform .18s ease, box-shadow .18s ease; }}
  .step-card:hover {{ transform:translateY(-3px); box-shadow:0 12px 30px rgba(0,0,0,.4); }}
  /* 转写全文 */
  .transcript-block {{ background:rgba(10,15,30,.8); }}
  .transcript-block .block-title {{ color:#CBD5E1; }}
  details summary {{ cursor:pointer; font-size:13px; color:#94A3B8; font-weight:600; user-select:none; margin-bottom:12px; }}
  .t-body {{ max-height:620px; overflow-y:auto; border:1px solid rgba(255,255,255,.07); border-radius:14px; background:rgba(5,9,20,.6); }}
  .t-row {{ display:flex; gap:10px; align-items:center; padding:6px 16px; font-size:13.5px; line-height:1.8; border-bottom:1px solid rgba(255,255,255,.05); }}
  .t-row:hover {{ background:rgba(255,255,255,.05); }}
  .t-row:last-child {{ border-bottom:none; }}
  .t-ts {{ flex:none; min-width:54px; color:#55627C; font-family:"SF Mono",Menlo,Consolas,monospace; font-size:12px; }}
  .t-dot {{ flex:none; width:9px; height:9px; border-radius:50%; }}
  .t-txt {{ color:#B9C6DD; }}
  .qr.play {{ color:#93C5FD; font-size:22px; border-style:solid; border-color:rgba(147,197,253,.25); background:rgba(96,165,250,.12); }}
  .aud-wrap {{ display:flex; align-items:center; gap:14px; margin:-8px 0 26px; padding:12px 18px;
    background:rgba(255,255,255,.04); border:1px solid rgba(255,255,255,.08); border-radius:14px; }}
  .aud-wrap audio {{ flex:1; height:36px; min-width:0; filter:invert(.92) hue-rotate(180deg); }}
  .aud-hint {{ font-size:11.5px; color:#64748B; white-space:nowrap; }}
  .tref {{ color:#60A5FA; text-decoration:none; border-bottom:1px dashed rgba(96,165,250,.45); cursor:pointer; }}
  .tref:hover {{ color:#C7DDFF; border-bottom-style:solid; border-bottom-color:rgba(147,197,253,.8); }}
  footer {{ text-align:right; margin-top:28px; font-size:11.5px; color:#55627C; }}
</style></head><body><div class="wrap">
{banner}
  <div class="doc-title">{esc(title)}</div>
  <div class="doc-summary">{esc(summary)}</div>
  {blocks_html}
  {trans_html}
  <footer>内容由 AI 生成 · 深色图文纪要 v3 · 本地渲染</footer>
</div>
<script id="minutes-tools">{tools_js}</script>
<script>
(function(){{
  var au = document.getElementById('min-audio');
  if (!au) return;
  document.addEventListener('click', function(e){{
    var a = e.target.closest ? e.target.closest('.tref') : null;
    if (!a) return;
    e.preventDefault();
    var t = parseFloat(a.getAttribute('data-t'));
    if (isNaN(t)) return;
    if (au.readyState === 0) {{ try {{ au.load(); }} catch(_) {{}} }}
    try {{ au.currentTime = t; }} catch(_) {{}}
    var p = au.play();
    if (p && p.catch) p.catch(function(){{}});
    au.style.boxShadow = '0 0 0 3px rgba(96,165,250,.45)';
    setTimeout(function(){{ au.style.boxShadow = ''; }}, 700);
  }});
}})();
</script>
</body></html>"""

def parse_markup(text):
    m = re.search(r"^#\s+(.+)$", text, re.M)
    title = m.group(1).strip() if m else "会议纪要"
    m = re.search(r"^>\s*(.+)$", text, re.M)
    summary = m.group(1).strip() if m else ""
    blocks = ""
    for sec in re.findall(r"<section>(.*?)</section>", text, re.S):
        t = re.search(r"##\s+(.+)", sec)
        stitle = t.group(1).strip() if t else "板块"
        blocks += render_section(stitle, sec, "<step-view" in sec)
    return title, summary, blocks

def main():
    ap = argparse.ArgumentParser(description="深色图文纪要渲染器 v3")
    ap.add_argument("--from-json", dest="from_json", help="INFOGRAPHIC_SUMMARY 结构 JSON 文件（第三方格式，迁移/对比用）")
    ap.add_argument("--from-markup", help="标记语言文件")
    ap.add_argument("--duration", default="")
    ap.add_argument("--date", default="")
    ap.add_argument("--audio", default="")
    ap.add_argument("--transcript", default="", help="对话稿 txt（转写全文，自动繁→简）")
    ap.add_argument("--out", default="")
    ap.add_argument("--no-tools", action="store_true",
                    help="不内联导出 Word / 复制模块（默认内联）")
    args = ap.parse_args()

    meta = {"duration": args.duration, "date": args.date, "audio": args.audio}

    transcript = None
    if args.transcript:
        raw = open(args.transcript, encoding="utf-8").read()
        try:
            from opencc import OpenCC
            transcript = OpenCC("t2s").convert(raw)
        except Exception:
            transcript = raw

    if args.from_json:
        data = json.load(open(args.from_json, encoding="utf-8"))
        title, summary, blocks = parse_markup(data.get("content", ""))
        base = os.path.splitext(args.from_json)[0]
    elif args.from_markup:
        title, summary, blocks = parse_markup(open(args.from_markup, encoding="utf-8").read())
        base = os.path.splitext(args.from_markup)[0]
    else:
        print("✗ 需要 --from-json 或 --from-markup", file=sys.stderr)
        return 1

    html_out = args.out or base + ".html"
    with open(html_out, "w", encoding="utf-8") as f:
        f.write(build_html(title, summary, blocks, meta, transcript,
                           tools_js="" if args.no_tools else load_tools()))
    print("✅ 已生成:", html_out)
    return 0

if __name__ == "__main__":
    sys.exit(main())
