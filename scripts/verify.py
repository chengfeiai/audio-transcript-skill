#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""录音转写技能包 · 一键回归验证（纯标准库，无需安装任何依赖）。

用法：  python3 scripts/verify.py
退出码：0 = 全 PASS；1 = 有 FAIL。

覆盖范围：
  1. 十一个脚本语法（ast.parse）+ 两个 JS 语法（node --check，若装了 node）
  2. 示例 JSON 可解析
  3. 六套皮肤（default/mist/plain/dark/neutral/obsidian）渲染 --check 全 exit=0 且报 0 断链
  4. 渲染产物：敏感词 0 命中、残留占位符 0、能力模块内联、data-* 属性为示例内容
  5. 四套 CSS 不再含硬编码纪要串字；plain 不再隐藏真实 h1
  6. 预览图存在且尺寸为 1440x810（PNG 头读取，不依赖 Pillow）

注意：本脚本**不**验证转写/说话人分离链路（需 mlx-whisper 等重依赖）；
      也**不**重新生成预览图或 HTML 成品。它只锁定确定性的不变量。
"""
import ast
import io
import json
import os
import re
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONTENT = os.path.join(ROOT, "examples", "split-示例.json")
RENDER = os.path.join(ROOT, "scripts", "render_split.py")
SKINS = ["default", "mist", "plain", "dark", "neutral", "obsidian"]

# 敏感词占位表：每行一个词，用于检查渲染产物是否串入本地私有词。
# 文件不存在时自动跳过该项检查，见 分发与合规说明.md。
SENSITIVE = []
_sf = os.path.join(ROOT, "private-keywords.txt")
if os.path.exists(_sf):
    with open(_sf, encoding="utf-8") as _f:
        SENSITIVE = [w.strip() for w in _f if w.strip()]
# 双下划线占位符（残留即说明渲染器没填全）
PLACEHOLDER_RE = re.compile(r"__[A-Z][A-Z0-9_]{2,}__")

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("  PASS  " if ok else "  FAIL  ") + name + (("  — " + detail) if detail else ""))
    return ok


def read(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


def main():
    print("=" * 64)
    print("录音转写 · 一键回归验证  (root=%s)" % ROOT)
    print("=" * 64)

    # --- 1. 语法 ---
    print("\n[1] 脚本语法")
    for fn in ["transcribe.py", "diarize.py", "render_minutes.py", "render_split.py",
               "fetch_douyin_audio.py", "postprocess.py", "record.py", "engines.py",
               "analyze.py", "library.py", "verify.py"]:
        p = os.path.join(HERE, fn)
        try:
            ast.parse(read(p), filename=fn)
            check("ast.parse %s" % fn, True)
        except Exception as e:
            check("ast.parse %s" % fn, False, repr(e))
    for rel in ["assets/minutes-tools.js", "templates/split/page.js"]:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            check("node --check %s" % rel, False, "文件缺失")
            continue
        try:
            r = subprocess.run(["node", "--check", p], capture_output=True, text=True)
            check("node --check %s" % rel, r.returncode == 0, (r.stderr or "").strip()[:120])
        except FileNotFoundError:
            check("node --check %s" % rel, True, "node 未安装，跳过（非致命）")

    # --- 2. 示例 JSON ---
    print("\n[2] 示例数据")
    try:
        data = json.loads(read(CONTENT))
        check("examples/split-示例.json 可解析", isinstance(data, dict) and "sections" in data)
    except Exception as e:
        check("examples/split-示例.json 可解析", False, repr(e))
    skill_md = read(os.path.join(ROOT, "SKILL.md"))
    check("SKILL.md 含公开链接取流章节", "素材来源（可选）" in skill_md
          and "fetch_douyin_audio.py" in skill_md)
    check("安装说明.md 标注可选依赖", "ego-browser" in read(os.path.join(ROOT, "安装说明.md")))
    check("合规说明含公开链接取流边界", "公开链接取流边界" in read(os.path.join(ROOT, "分发与合规说明.md")))
    ref = read(os.path.join(ROOT, "设计参考-中性界面规范.md"))
    check("设计参考-中性界面规范.md 含规范 token", "--primary-base" in ref and "#335CFF" in ref
          and "组件清单与双栏对位" in ref)
    reg = json.loads(read(os.path.join(ROOT, "skins", "skins.json")))
    check("skins.json 注册 neutral", any(s.get("id") == "neutral" and
          s.get("file") == "skin-neutral.css" for s in reg.get("skins", [])))
    check("SKILL.md 皮肤清单为六选一", "六选一" in skill_md and "neutral" in skill_md
          and "obsidian" in skill_md)

    # --- 3/4. 六套皮肤渲染 ---
    print("\n[3] 六套皮肤渲染 + 产物校验")
    if not SENSITIVE:
        print("  · private-keywords.txt 未找到，敏感词检查跳过")
    tmp = tempfile.mkdtemp(prefix="dy_verify_")
    for skin in SKINS:
        out = os.path.join(tmp, "out_%s.html" % skin)
        cmd = [sys.executable, RENDER, "--content", CONTENT, "--skin", skin, "--check", "--out", out]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        combined = (r.stdout or "") + (r.stderr or "")
        ok_exit = r.returncode == 0
        check("render --skin %s 退出码" % skin, ok_exit, "exit=%d" % r.returncode)
        # 断链必须为 0
        m = re.search(r"断链\s*(\d+)\s*处", combined)
        check("render --skin %s 断链=0" % skin, bool(m) and m.group(1) == "0",
              ("断链=%s" % m.group(1)) if m else "未匹配到断链计数")
        if not os.path.exists(out):
            check("render --skin %s 产物存在" % skin, False, out)
            continue
        html = read(out)
        # 敏感词：正文（HTML 文本）里不能出现原包真实材料
        hit = [w for w in SENSITIVE if w in html]
        check("render --skin %s 敏感词 0 命中" % skin, len(hit) == 0, ",".join(hit))
        # 残留占位符
        ph = set(PLACEHOLDER_RE.findall(html))
        check("render --skin %s 残留占位符 0" % skin, len(ph) == 0, ",".join(sorted(ph)))
        # 能力模块内联
        check("render --skin %s minutes-tools 内联" % skin, 'id="minutes-tools"' in html)
        # data-* 属性（default 也注入，因为 page.html 加了属性；成品应含真实标题）
        check("render --skin %s data-title 存在" % skin, "data-title=" in html)
        # 倍速控件必须是「点开菜单选择」，不能退回旧的循环切换
        check("render --skin %s 倍速菜单节点" % skin,
              'id="plRateMenu"' in html and 'class="pl-rate-menu"' in html)
        check("render --skin %s 无旧版循环倍速" % skin,
              "var rates=[1,1.25,1.5,0.75,2]" not in html)

    # --- 5. CSS 不变量 ---
    print("\n[5] CSS 内容无关化")
    css_dir = os.path.join(ROOT, "skins")
    skin_css = ["skin-mist.css", "skin-plain.css", "skin-dark.css", "skin-neutral.css",
                "skin-obsidian.css"]
    all_css = ""
    for fn in skin_css:
        p = os.path.join(css_dir, fn)
        s = read(p)
        all_css += s + "\n"
        css_hit = [w for w in SENSITIVE if w in s]
        check("%s 敏感词 0 命中" % fn, len(css_hit) == 0, ",".join(css_hit))
        # 旧三套曾把标题/日期硬编码进 ::before，必须走 attr(data-*)；
        # neutral 不画任何装饰文案，改为断言「没有 content 装饰文案」。
        if fn == "skin-neutral.css":
            check("%s 不含装饰文案 content" % fn,
                  not re.search(r"content\s*:\s*(?!\"\"|''|none)", s))
        else:
            check("%s 用 content:attr(data-*)" % fn,
                  "content:attr(data-" in s or "content:\"☰ \" attr(data-" in s)
    plain = read(os.path.join(css_dir, "skin-plain.css"))
    check("plain 不再隐藏真实 h1", ".doc h1,.kicker{display:none}" not in plain)
    page_html = read(os.path.join(ROOT, "templates", "split", "page.html"))
    page_js = read(os.path.join(ROOT, "templates", "split", "page.js"))
    page_css = read(os.path.join(ROOT, "templates", "split", "page.css"))
    check("page.js 含倍速菜单逻辑", "plRateMenu" in page_js and "SPEEDKEY" in page_js)
    check("page.css 含倍速菜单样式", ".pl-rate-menu" in page_css)
    check("page.html 含倍速菜单节点", 'id="plRateMenu"' in page_html)
    for attr in ["__SKIN_TITLE__", "__SKIN_SUBLINE__", "__SKIN_CAPTION__"]:
        check("page.html 含占位 %s" % attr, attr in page_html)
    render_src = read(RENDER)
    for key in ["__SKIN_TITLE__", "__SKIN_SUBLINE__", "__SKIN_CAPTION__"]:
        check("render_split.py 填 %s" % key, key in render_src)

    # --- 6. 预览图 ---
    print("\n[6] 预览图（尺寸 + 存在）")
    for skin in SKINS:
        p = os.path.join(css_dir, "previews", "%s.png" % skin)
        if not os.path.exists(p):
            check("previews/%s.png 存在" % skin, False)
            continue
        with open(p, "rb") as f:
            head = f.read(24)
        w, h = struct.unpack(">II", head[16:24]) if head[:8] == b"\x89PNG\r\n\x1a\n" else (0, 0)
        check("previews/%s.png 1440x810" % skin, (w, h) == (1440, 810), "%dx%d" % (w, h))

    # --- 7. 出稿 / 引擎 / AI 理解 / 资产回归 ---
    print("\n[7] 出稿 / 引擎 / AI 理解 / 资产（不联网、不占麦克风）")
    work = tempfile.mkdtemp(prefix="dy_full_")
    draft = os.path.join(work, "回归稿.txt")
    with io.open(draft, "w", encoding="utf-8") as f:
        f.write("[00:00] 说话人1：今天先确认本次会议的三项议程\n"
                "[00:21] 说话人2：第二项需要补充一份书面材料\n"
                "[00:41] 说话人1：交付时间以双方确认的节点为准\n"
                "[01:02] 说话人2：没有异议的话我们先记录这一条\n")

    def run(args, cwd=ROOT):
        return subprocess.run([sys.executable] + args, capture_output=True, text=True, cwd=cwd)

    pp = os.path.join(HERE, "postprocess.py")
    r = run([pp, draft, "--format", "roles", "--clean", "fluent",
             "--fieldcode", "1", "--max-chars", "14", "--outdir", work])
    check("postprocess 出稿/规整/场记/折行 exit=0", r.returncode == 0,
          "exit=%d" % r.returncode)
    fc = os.path.join(work, "回归稿-场记1分钟.txt")
    check("场记时间码含 hh:mm:ss", os.path.exists(fc) and "【00:00:00】" in read(fc))
    sr = os.path.join(work, "回归稿-字幕14字.srt")
    check("SRT 单行字数折行生效", os.path.exists(sr) and "-->" in read(sr))
    r = run([pp, draft, "--clean", "digest", "--outdir", work])
    check("digest 拒绝机械硬截", r.returncode != 0 and "内容提炼" in (r.stderr or ""))

    hw = json.loads(read(os.path.join(ROOT, "hotwords.json")))
    check("hotwords.json 领域词表与 200 词上限", "教育" in hw.get("domains", {})
          and hw.get("limits", {}).get("max_words") == 200)
    lg = json.loads(read(os.path.join(ROOT, "languages.json")))
    check("languages.json 含方言表与云端路由", "routing_rule" in lg
          and len(lg.get("cloud_only_dialects", [])) >= 20)

    ep = os.path.join(HERE, "engines.py")
    r = run([ep, "--list"])
    check("engines 登记四引擎", all(k in (r.stdout or "") for k in
          ["local", "manual", "cloud", "workbuddy"]))
    r = run([ep, "--chat", "--text", "hi", "--engine", "cloud"])
    check("cloud 未确认时拒绝出本机", r.returncode != 0 and "未确认" in (r.stderr or ""))
    ext = os.path.join(work, "外部稿.srt")
    with io.open(ext, "w", encoding="utf-8") as f:
        f.write("1\n00:00:05,030 --> 00:00:08,790\n大家好\n\n"
                "2\n00:01:02,000 --> 00:01:05,000\nSPEAKER_2: 补充书面材料\n")
    norm = os.path.join(work, "规范稿.txt")
    r = run([ep, "ingest", "--input", ext, "--out", norm])
    check("外部精转稿规范化（SRT→[mm:ss]）", r.returncode == 0
          and "[00:05]" in read(norm) and "说话人2" in read(norm))

    ap_ = os.path.join(HERE, "analyze.py")
    r = run([ap_, "--input", draft, "--tasks", "summary,chapters,keywords,minutes",
             "--outdir", work])
    req = os.path.join(work, "analysis-request.md")
    check("analyze agent 请求包（不出本机）", r.returncode == 0
          and os.path.exists(req) and "真实段首时间码索引" in read(req))
    result = {
        "title": "回归用纪要", "sub": "四段稿的结构化结果",
        "summary": "四段回归稿的摘要。",
        "brief": ["第一句结论（{{00:00}}）", "第二句结论（{{00:41}}）"],
        "sections": [{"title": "开场", "sub": "命题", "comment": "",
                      "items": [{"text": "确认三项议程", "time": "00:00"},
                                {"text": "交付时间以书面节点为准", "time": "00:41"}]}],
        "chapters": [{"time": "00:00", "title": "开场", "note": "引入"},
                     {"time": "01:02", "title": "收尾", "note": "记录结论"}],
        "keywords": ["议程", "交付时间"], "todos": ["回听核对"],
        "insights": {"risks": ["交付节点未书面确认"], "decisions": [], "expansion": []},
        "mindmap": "mindmap\n  root((议程))\n    交付时间",
    }
    resp = os.path.join(work, "analysis-result.json")
    with io.open(resp, "w", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False, indent=2))
    r = run([ap_, "--apply", resp, "--transcript", draft, "--audio", "回归.m4a",
             "--duration", "01:10", "--verify-render", "--outdir", work])
    check("analyze --apply 产出内容 JSON 且渲染断链=0", r.returncode == 0
          and "断链=0" in (r.stdout or ""), (r.stdout or "")[-160:])
    result["brief"][0] = "第一句结论（{{04:44}}）"
    badp = os.path.join(work, "bad-result.json")
    with io.open(badp, "w", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False, indent=2))
    r = run([ap_, "--apply", badp, "--transcript", draft, "--outdir", work])
    check("编造时间码被拒（不擅自对齐）", r.returncode != 0
          and "未命中段首" in (r.stderr or ""))

    lp = os.path.join(HERE, "library.py")
    r = run([lp, "--access"])
    check("接入清单含私有化部署与人工精转", "私有化部署" in (r.stdout or "")
          and "人工精转" in (r.stdout or ""))
    r = run([lp, "--root", work, "--index", "--outdir", work])
    check("知识库索引生成", r.returncode == 0
          and os.path.exists(os.path.join(work, "知识库索引.md")))

    cap = read(os.path.join(ROOT, "能力全景与接入清单.md"))
    check("能力全景含五层与接入清单", "第 5 层" in cap and "非代码形态" in cap)
    check("SKILL.md 含能力全景章节", "## 能力全景" in skill_md)
    check("合规说明含数据出本机边界", "数据出本机边界" in
          read(os.path.join(ROOT, "分发与合规说明.md")))
    check("安装说明列出新脚本", all(x in read(os.path.join(ROOT, "安装说明.md"))
          for x in ["postprocess.py", "record.py", "engines.py", "analyze.py", "library.py"]))
    for fn in ["engines.py", "analyze.py", "library.py"]:
        check("%s 含显式确认开关" % fn,
              "--i-understand-data-leaves-this-machine" in read(os.path.join(HERE, fn)))

    # --- 汇总 ---
    npass = sum(1 for _, ok, _ in results if ok)
    nfail = len(results) - npass
    print("\n" + "=" * 64)
    print("汇总：%d 项  PASS=%d  FAIL=%d" % (len(results), npass, nfail))
    print("=" * 64)
    print("说明：本脚本只验证修复部分的确定性不变量；转写链路（mlx-whisper 等重依赖）")
    print("      与浏览器像素级渲染不在覆盖范围内，详见 发布自查清单.md。")
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())
