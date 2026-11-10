#!/usr/bin/env python3
"""浅色双栏「阅读器」版式渲染器 —— 左篇纪要 / 右栏全文 + 回听 + 搜索筛选。

与深色 v3 渲染器（render_minutes.py）分工：
  render_minutes.py  → 深色图文纪要（板块 + 卡片 + 极光）
  render_split.py    → 浅色双栏阅读器（逐段核对原音、打印归档）

用法:
  python3 render_split.py --content 内容.json --out 输出.html
  python3 render_split.py --content 内容.json --audio 录音.m4a --transcript 整理稿.txt --out 输出.html

内容 JSON 的 schema 见 SKILL.md「内容 JSON 字段」，最小可用示例见本文件末尾 __main__ 注释。
"""
import argparse
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# 模板与能力模块可能装在技能包内，也可能按旧布局单独部署，逐个找
TPL_CANDIDATES = [
    os.path.join(HERE, "..", "templates", "split"),     # 技能包布局
    os.path.join(HERE, "templates", "split"),           # 旧布局：脚本与模板同级
    os.path.join(os.path.expanduser("~"), ".workbuddy", "skills",
                 "录音转写", "templates", "split"),
]
TPL_DIR = next((p for p in TPL_CANDIDATES if os.path.isdir(p)), TPL_CANDIDATES[0])

TOOLS_CANDIDATES = [
    os.path.join(HERE, "..", "assets", "minutes-tools.js"),
    os.path.join(os.path.expanduser("~"), ".hermes", "scripts", "assets", "minutes-tools.js"),
    os.path.join(os.path.expanduser("~"), ".workbuddy", "skills", "录音转写", "assets", "minutes-tools.js"),
]

# 三个角色默认配色（与 CSS 的 sp-a / sp-b / sp-c 一致）
ROLE_CLS = ["a", "b", "c"]
ROLE_COLOR = ["#1E64FF", "#D69A2D", "#1F7A55"]

# 皮肤包：可在项目目录（cwd/skins）或技能包内，逐个找
SKIN_DIR_CANDIDATES = [
    os.path.join(os.getcwd(), "skins"),
    os.path.join(HERE, "..", "skins"),                  # 技能包布局
    os.path.join(os.path.expanduser("~"), ".workbuddy", "skills",
                 "录音转写", "skins"),
]
SKIN_FILES = {
    "default": None,                                    # 不注入任何样式
    "mist": "skin-mist.css",
    "plain": "skin-plain.css",
    "dark": "skin-dark.css",
    "neutral": "skin-neutral.css",
    "obsidian": "skin-obsidian.css",
}
DEFAULT_SKIN = "mist"


def find_skin_dir(explicit=""):
    """返回皮肤包目录；显式指定优先，否则按候选逐个找。"""
    cands = ([explicit] if explicit else []) + SKIN_DIR_CANDIDATES
    for p in cands:
        if p and os.path.isdir(p):
            return p
    return ""


def load_skin(skin_id, skin_dir=""):
    """读皮肤 CSS 全文。default 返回空串；找不到文件抛错，绝不静默降级。"""
    if not skin_id or skin_id == "default":
        return ""
    d = find_skin_dir(skin_dir)
    if not d:
        raise FileNotFoundError(
            "未找到皮肤包目录，候选：" + "、".join(SKIN_DIR_CANDIDATES))
    fname = SKIN_FILES.get(skin_id)
    if fname is None:
        raise KeyError("未知皮肤 id：%s（可选：%s）" % (skin_id, "、".join(SKIN_FILES)))
    path = os.path.join(d, fname)
    if not os.path.isfile(path):
        raise FileNotFoundError("皮肤文件缺失：%s" % path)
    with open(path, encoding="utf-8") as f:
        css = f.read()
    # 皮肤会被塞进 style 元素，正文里出现结束标签会把 <style> 提前截断
    if "</style" in css.lower():
        raise ValueError("皮肤 CSS 含 </style 字面量，注入会截断样式：%s" % path)
    return css


def inject_skin(page, css, skin_id):
    """独立 <style data-skin> 注入到 </head> 之前（即主 style 之后）。

    不能拼接到主 style 末尾：主 style 一旦有未闭合注释，追加的样式会被整段吞掉。
    """
    if not css:
        return page
    block = '<style data-skin="%s">\n%s\n</style>\n' % (skin_id, css)
    if "</head>" in page:
        return page.replace("</head>", block + "</head>", 1)
    print("! 模板没有 </head>，皮肤未注入", file=sys.stderr)
    return page


def list_skins(skin_dir=""):
    """列出可选皮肤（名称与描述优先读 skins.json，缺失时退回内置表）。"""
    d = find_skin_dir(skin_dir)
    meta = {}
    if d:
        jp = os.path.join(d, "skins.json")
        try:
            with open(jp, encoding="utf-8") as f:
                for s in json.load(f).get("skins", []):
                    meta[s.get("id")] = s
        except (OSError, ValueError):
            pass
    rows = []
    for sid in SKIN_FILES:
        m = meta.get(sid, {})
        rows.append({
            "id": sid,
            "name": m.get("name", sid),
            "desc": m.get("desc", ""),
            "preview": os.path.join(d, m.get("preview", "")) if d and m.get("preview") else "",
            "default": sid == DEFAULT_SKIN,
        })
    return rows, d


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


def read_tpl(name):
    path = os.path.join(TPL_DIR, name)
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        print(f"✗ 找不到版式模板 {name}（在 {TPL_DIR} 下）；"
              f"请把 templates/split/ 与脚本一起安装", file=sys.stderr)
        print("  候选路径: " + " | ".join(TPL_CANDIDATES), file=sys.stderr)
        sys.exit(1)


def to_sec(t):
    """'08:44' / '1:02:03' -> 秒"""
    parts = [int(x) for x in str(t).split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return int(parts[0])


def cite(txt):
    """{{mm:ss}} -> 可点击时间引用；已含 <a class=cite> 的原文不再重复处理。"""
    return re.sub(r"\{\{(\d{1,2}:\d{2})\}\}",
                  r'<a class="cite" data-t="\1">\1</a>', str(txt))


def li(items):
    return "<ul>" + "".join(f"<li>{cite(x)}</li>" for x in items) + "</ul>"


class Renderer:
    def __init__(self, data):
        self.d = data
        self.roles = list(data.get("roles") or [])
        self.segs = data.get("transcript") or []
        self.unknown = set()

        # 整理稿常用简称（干部/当事/三人），映射回 roles 里的全名
        self.alias = {}
        for full, shorts in (data.get("aliases") or {}).items():
            for s in ([shorts] if isinstance(shorts, str) else shorts):
                self.alias[s] = full

        # 角色 -> cls / 颜色
        self.cls = {}
        self.color = {}
        for i, r in enumerate(self.roles):
            self.cls[r] = ROLE_CLS[i % 3]
            self.color[r] = ROLE_COLOR[i % 3]

        # 总时长：优先 duration，否则末段 + 60 秒
        dur = data.get("duration")
        if dur:
            self.total = to_sec(dur)
        elif self.segs:
            self.total = to_sec(self.segs[-1]["t"]) + 60
        else:
            self.total = 0

    # ---------- 片段 ----------
    def who_norm(self, who):
        """简称回归全名；不认识的角色记下来，渲染后统一提示。"""
        if who in self.alias:
            return self.alias[who]
        if who and self.roles and who not in self.cls:
            self.unknown.add(who)
        return who

    def seg_html(self, s, dur):
        t = s["t"]
        who = self.who_norm(s.get("who", ""))
        txt = html.escape(s.get("x", ""))
        c = self.cls.get(who, "a")
        return (f'<div class="seg sp-{c}" data-who="{html.escape(who)}" data-t="{t}" data-d="{dur}">'
                f'<span class="seg-t" data-t="{t}">{t}</span>'
                f'<span class="seg-who">{html.escape(who)}</span>'
                f'<span class="seg-x">{txt}</span></div>')

    def transcript_html(self):
        if not self.segs:
            return ""
        starts = [to_sec(s["t"]) for s in self.segs]
        out = []
        for i, s in enumerate(self.segs):
            nxt = starts[i + 1] if i + 1 < len(starts) else self.total
            out.append(self.seg_html(s, max(1, nxt - starts[i])))
        return "\n".join(out)

    # ---------- 卡片 ----------
    def card_html(self, idx, c, tone):
        body = c.get("body")
        if isinstance(body, list):
            body = li(body)
        body = cite(body or "")
        cm = c.get("comment")
        cm_html = f'<p class="card-cm">「{cite(cm)}」</p>' if cm else ""
        return (f'<article class="card" data-tone="{tone}">\n'
                f'  <div class="card-hd"><span class="dot"></span><span class="card-no">{idx}</span>'
                f'<h4>{cite(c.get("label", ""))}</h4></div>\n'
                f'  <div class="card-bd">{body}</div>\n'
                f'  {cm_html}\n'
                f'</article>')

    # ---------- 对照面板 ----------
    def duel_html(self, d):
        def side(side_data, cls):
            cites = " ".join(f'<a class="cite" data-t="{t}">{t}</a>'
                             for t in side_data.get("cites", []))
            role = side_data.get("role", "")
            rows = []
            for r in side_data.get("rows", []):
                tone = r.get("tone", "")
                rows.append(f'<div class="verdict {tone}"><span>{cite(r.get("k", ""))}</span>'
                            f'<b>{cite(r.get("v", ""))}</b></div>')
            note = side_data.get("note", "")
            note_html = f'<p class="duel-note">{cite(note)}</p>' if note else ""
            return (f'    <div class="duel-side {cls}">\n'
                    f'      <div class="duel-role">{role}{(" · " + cites) if cites else ""}</div>\n'
                    + "\n".join("      " + x for x in rows) + "\n"
                    + (f"      {note_html}\n" if note_html else "")
                    + "    </div>")

        hd = d.get("title", "")
        legend = d.get("legend", "")
        legend_html = f'<em class="duel-legend">{legend}</em>' if legend else ""
        return ('<div class="duel">\n'
                f'  <div class="duel-hd"><span>{hd}</span>{legend_html}</div>\n'
                '  <div class="duel-grid">\n'
                + side(d.get("left", {}), "a") + "\n"
                '    <div class="duel-vs"><span>VS</span></div>\n'
                + side(d.get("right", {}), "b") + "\n"
                '  </div>\n'
                '</div>')

    # ---------- 步骤 / 清单 ----------
    def steps_html(self, steps):
        out = []
        for s in steps:
            tags = "".join(f'<span class="tag">{t}</span>' for t in s.get("tags", []))
            time = s.get("time", "")
            time_html = f'<span class="step-time mono">{time}</span>' if time else ""
            cm = s.get("cm")
            cm_html = f'<p class="card-cm">「{cite(cm)}」</p>' if cm else ""
            out.append('''<div class="step">
  <div class="step-rail"><span class="step-dot"></span></div>
  <div class="step-bd">
    <div class="step-top"><b>__K__</b>__TIME____TAGS__</div>
    <p>__BODY__</p>
    __CM__
  </div>
</div>'''.replace("__K__", cite(s.get("k", "")))
                .replace("__TIME__", time_html)
                .replace("__TAGS__", tags)
                .replace("__BODY__", cite(s.get("body", "")))
                .replace("__CM__", cm_html))
        return "\n".join(out)

    def checks_html(self, checks):
        out = []
        for c in checks:
            if isinstance(c, dict):
                k, v = c.get("k", ""), c.get("v", "")
            else:
                k, v = c[0], c[1]
            out.append('<li><label><input type="checkbox"><span class="ck">'
                       f'<b>{cite(k)}</b><em>{cite(v)}</em></span></label></li>')
        return "\n".join(out)

    # ---------- 板块 ----------
    def sections_html(self):
        blocks = []
        for i, sec in enumerate(self.d.get("sections", []), start=1):
            num = sec.get("num") or i
            sid = sec.get("id") or f"s{num}"
            typ = sec.get("type", "cards")
            title = sec.get("title", "")
            sub = sec.get("sub", "")
            hd = (f'  <div class="sec-hd"><span class="sec-no">{int(num):02d}</span>'
                  f'<h3>{title}</h3><span class="sec-sub">{sub}</span></div>')

            if typ == "cards":
                tone = sec.get("tone", "blue")
                inner = "\n".join(
                    self.card_html(f"{int(num)}.{j+1}", c, tone)
                    for j, c in enumerate(sec.get("cards", [])))
                extra = self.duel_html(sec["duel"]) if sec.get("duel") else ""
                blocks.append(f'<section class="sec" id="{sid}">\n{hd}\n'
                              f'  <div class="grid">{inner}</div>\n'
                              + (f"  {extra}\n" if extra else "")
                              + '</section>')
            elif typ == "steps":
                blocks.append(f'<section class="sec" id="{sid}">\n{hd}\n'
                              f'  <div class="steps">{self.steps_html(sec.get("steps", []))}</div>\n'
                              '</section>')
            elif typ == "checks":
                blocks.append(f'<section class="sec" id="{sid}">\n{hd}\n'
                              f'  <ul class="checks">{self.checks_html(sec.get("checks", []))}</ul>\n'
                              '</section>')
            elif typ == "duel":
                blocks.append(self.duel_html(sec))
            else:
                raw = sec.get("html", "")
                blocks.append(f'<section class="sec" id="{sid}">\n{hd}\n{raw}\n</section>')
        return "\n\n".join(blocks)

    def subnav_html(self):
        out = []
        for i, sec in enumerate(self.d.get("sections", []), start=1):
            num = sec.get("num") or i
            sid = sec.get("id") or f"s{num}"
            if not sec.get("title"):
                continue
            on = ' class="on"' if i == 1 else ""
            out.append(f'      <a href="#{sid}"{on}><i>{int(num):02d}</i>{sec["title"]}</a>')
        return "\n".join(out)

    # ---------- 整页 ----------
    def render(self, tools_js=""):
        d = self.d
        title = d.get("title")
        if isinstance(title, list):
            h1 = "<br>".join(title)
            title_tag = " · ".join(title)
        else:
            h1 = title or ""
            title_tag = h1

        meta_rows = []
        for m in d.get("meta", []):
            k, v = (m.get("k"), m.get("v")) if isinstance(m, dict) else (m[0], m[1])
            extra = ' class="mono" style="font-size:11.5px;word-break:break-all"' if (
                isinstance(m, dict) and m.get("mono")) else ""
            meta_rows.append(f"          <div><dt>{k}</dt><dd{extra}>{v}</dd></div>")

        brief = "\n".join(f"            <li>{cite(b['x'] if isinstance(b, dict) else b)}</li>"
                          for b in d.get("brief", []))

        chips = []
        for c in d.get("chips", []):
            tone = c.get("tone", "")
            tone_attr = f' class="chip {tone}"' if tone else ' class="chip"'
            chips.append(f'            <span{tone_attr}><i>{cite(c.get("k", ""))}</i>'
                         f'{cite(c.get("v", ""))}</span>')

        decl = []
        for p in d.get("decl", []):
            k, v = (p.get("k"), p.get("v")) if isinstance(p, dict) else (p[0], p[1])
            decl.append(f"        <p><b>{k}</b>{cite(v)}</p>")

        filters = "\n".join(
            f'        <button class="fbtn" type="button" data-who="{r}">{r}</button>'
            for r in self.roles)

        legend = "".join(
            f'<span><i class="i-{self.cls[r]}"></i>{r}</span>' for r in self.roles[:3])

        # —— 皮肤装饰文案：全部取自内容 JSON，皮肤 CSS 通过 attr() 读取；缺字段时留空 ——
        def meta_val(key):
            for m in d.get("meta", []):
                k, v = (m.get("k"), m.get("v")) if isinstance(m, dict) else (m[0], m[1])
                if k == key:
                    return str(v)
            return ""
        skin_subline = " · ".join(
            x for x in (meta_val("会议时间"), meta_val("会议时长"), d.get("kicker", "")) if x
        ) or (d.get("sub") or "")
        skin_caption = d.get("sub") or d.get("kicker") or ""

        repl = {
            "__SKIN_TITLE__": html.escape(title_tag, quote=True),
            "__SKIN_SUBLINE__": html.escape(skin_subline, quote=True),
            "__SKIN_CAPTION__": html.escape(skin_caption, quote=True),
            "__TITLE_TAG__": title_tag,
            "__CSS__": read_tpl("page.css"),
            "__KICKER__": d.get("kicker", ""),
            "__TITLE_HTML__": h1,
            "__DOCSUB__": d.get("sub", ""),
            "__META_ROWS__": "\n".join(meta_rows),
            "__BRIEF_TITLE__": d.get("brief_title", "三句话结论"),
            "__BRIEF_ITEMS__": brief,
            "__CHIPS__": "\n".join(chips),
            "__SUBNAV__": self.subnav_html(),
            "__SECTIONS__": self.sections_html(),
            "__DECL__": "\n".join(decl),
            "__STAMP__": d.get("stamp", ""),
            "__SEGCOUNT__": str(len(self.segs)),
            "__FILTERS__": filters,
            "__RHYTHM_LEGEND__": legend,
            "__TRANSCRIPT__": self.transcript_html(),
            "__AUDIO__": d.get("audio", ""),
            "__DUR__": d.get("duration", "00:00"),
            "__SEARCH_PH__": d.get("search_placeholder",
                                   "在全文搜索关键词（按 / 聚焦）"),
            "__JS__": (read_tpl("page.js")
                       .replace("__TOTAL__", str(self.total))
                       .replace("__WHOCOLORS__", json.dumps(self.color, ensure_ascii=False))),
            "__TOOLS_JS__": tools_js,
        }

        page = read_tpl("page.html")
        for k, v in repl.items():
            page = page.replace(k, v)

        leftover = re.findall(r"__[A-Z_]{3,}__", page)
        if leftover:
            print("! 模板仍有未替换占位符:", set(leftover), file=sys.stderr)
        return page


def load_transcript(path):
    """整理稿 -> [{t, who, x}]，兼容 '[08:44] 说话人：正文' 与 '说话人1: 正文'"""
    segs = []
    pat = re.compile(r"^\s*\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?\s*([^：:]{1,12})[：:]\s*(.*)$")
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            m = pat.match(line)
            if m:
                segs.append({"t": m.group(1), "who": m.group(2).strip(), "x": m.group(3).strip()})
            elif segs:
                segs[-1]["x"] += line.strip()
    return segs


def main():
    ap = argparse.ArgumentParser(description="浅色双栏阅读器版式渲染器")
    ap.add_argument("--content", default="", help="内容 JSON")
    ap.add_argument("--transcript", default="", help="整理稿 txt（覆盖 JSON 里的 transcript）")
    ap.add_argument("--audio", default="", help="音频文件名（覆盖 JSON 里的 audio）")
    ap.add_argument("--out", default="", help="输出 HTML")
    ap.add_argument("--no-tools", action="store_true", help="不内联导出/复制模块")
    ap.add_argument("--check", action="store_true", help="校验时间引用是否都能命中段落")
    ap.add_argument("--skin", default="", help="皮肤 id：default / mist / plain / dark / neutral / obsidian")
    ap.add_argument("--skins-dir", default="", help="皮肤包目录（缺省自动查找 cwd/skins）")
    ap.add_argument("--list-skins", action="store_true", help="列出可选皮肤后退出")
    args = ap.parse_args()

    if args.list_skins:
        rows, d = list_skins(args.skins_dir)
        if not d:
            print("! 未找到皮肤包目录，候选：" + "、".join(SKIN_DIR_CANDIDATES),
                  file=sys.stderr)
            return 3
        print("皮肤包：%s（默认 %s）" % (d, DEFAULT_SKIN))
        for r in rows:
            print("%-8s %-6s %s%s" % (r["id"], r["name"],
                                      "【默认】" if r["default"] else "        ", r["desc"]))
            if r["preview"]:
                print("         预览：%s" % r["preview"])
        return 0

    if not args.content:
        ap.error("--content 必填（除非只用 --list-skins）")

    with open(args.content, encoding="utf-8") as f:
        data = json.load(f)

    if args.transcript:
        data["transcript"] = load_transcript(args.transcript)
    if args.audio:
        data["audio"] = args.audio
    if not data.get("roles"):
        amap = {}
        for full, shorts in (data.get("aliases") or {}).items():
            for s in ([shorts] if isinstance(shorts, str) else shorts):
                amap[s] = full
        seen = []
        for s in data.get("transcript", []):
            who = amap.get(s.get("who"), s.get("who"))
            if who and who not in seen:
                seen.append(who)
        data["roles"] = seen
        for s in data.get("transcript", []):
            s["who"] = amap.get(s.get("who"), s.get("who"))

    r = Renderer(data)

    if args.check:
        have = {s["t"] for s in r.segs}
        page = r.render(tools_js="")
        # 未渲染的 {{mm:ss}} 与已渲染的 data-t 都要查，否则漏检
        used = set(re.findall(r"\{\{(\d{1,2}:\d{2})\}\}", json.dumps(data, ensure_ascii=False)))
        used |= set(re.findall(r'class="cite" data-t="(\d{1,2}:\d{2})"', page))
        bad = sorted(used - have)
        print(f"段落 {len(r.segs)} 段 · 引用 {len(used)} 处 · 断链 {len(bad)} 处"
              + (f" -> {bad}" if bad else ""))
        if bad:
            return 2

    out = args.out or os.path.splitext(args.content)[0] + "-交互纪要(双栏).html"
    page = r.render(tools_js="" if args.no_tools else load_tools())
    if args.skin:
        try:
            css = load_skin(args.skin, args.skins_dir)
        except (FileNotFoundError, KeyError, ValueError) as e:
            print("! 皮肤注入失败：%s" % e, file=sys.stderr)
            return 4
        page = inject_skin(page, css, args.skin)
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    if r.unknown:
        print(f"! 这些说话人不在 roles 里，配色退化为第一档: {sorted(r.unknown)}", file=sys.stderr)
        print("  用 aliases 或 roles 字段登记它们", file=sys.stderr)
    print("✅ 已生成:", out, len(page), "chars,", len(r.segs), "segs",
          ("· skin=" + args.skin) if args.skin else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
