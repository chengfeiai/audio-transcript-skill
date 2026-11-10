#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 理解层：问答 / 洞察 / 图文纪要 / 章节速览 / 关键词 / 思维导图 / AI 写作。

默认 agent 引擎：不联网、数据不出本机。脚本把全文 + 任务 + 输出 schema 打成
analysis-request.md，由宿主 Agent 在对话里完成后回写 analysis-result.json；
再用 --apply 校验时间码、生成可直接渲染的 纪要内容.json 与各单件产物。

  # 1 生成请求包（默认，不出本机）
  python3 analyze.py --input "录音.整理稿.txt" --tasks minutes,chapters,keywords,todos,insights
  # 2 宿主 Agent 按请求包产出 analysis-result.json（在对话里完成）
  # 3 校验 + 拆件 + 出内容 JSON + 渲染器断链校验
  python3 analyze.py --apply analysis-result.json --transcript "录音.整理稿.txt" \
      --audio "录音.m4a" --duration "12:30" --verify-render

  # 可选：显式走外部大模型（数据出本机）
  python3 analyze.py --input "稿.txt" --tasks summary --engine cloud \
      --i-understand-data-leaves-this-machine

任务：summary digest chapters keywords todos highlights insights risks decisions
      questions mindmap rewrite polish write translate minutes
"""
import argparse
import datetime
import io
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RENDER_SPLIT = os.path.join(HERE, "render_split.py")
sys.path.insert(0, HERE)
import engines  # noqa: E402

TS_RE = re.compile(r"^\[(\d{1,3}):(\d{2})\]\s*(.*)$")
ROLE_RE = re.compile(r"^(?:说话人\s*\d+|角色\s*\d+|SPEAKER[_ -]?\d+|[^\W\d_]{1,6})\s*[:：]\s*", re.U)
CITE_RE = re.compile(r"\{\{(\d{1,3}:\d{2})\}\}")

TASKS = {
    "summary": "写 150 字以内的整体摘要，说清主题与结论，不空泛。",
    "digest": "内容提炼：保留原文 30%–40% 的信息量，按重要性取舍，不改写原意，逐条标注对应时间码。",
    "chapters": "章节速览：按内容转折切成 4–8 章，每章给 time(mm:ss)、title、note。",
    "keywords": "提取 8–15 个关键词，按重要性排序。",
    "todos": "抽取待办事项，逐条写明谁、做什么；没有明确待办就给空数组，不要编。",
    "highlights": "提炼 5–8 条重点，每条附一个可命中段首的时间码。",
    "insights": "洞察：分 risks(风险识别) / decisions(决策建议) / expansion(知识拓展) 三组，各 2–4 条。",
    "risks": "只做风险识别，列出潜在风险与依据时间码。",
    "decisions": "只做决策建议，列出可执行建议与依据。",
    "questions": "针对这份材料生成 3–5 个值得追问的方向。",
    "mindmap": "输出 mermaid mindmap 源码，根节点是主题，二级是主要板块，三级是关键点。",
    "rewrite": "语篇规整：把口语稿改写成书面语，保留全部事实与时间码，不新增内容。",
    "polish": "文章润色：在不改变事实的前提下优化表达与节奏。",
    "write": "AI 写作：按 --style 生成一篇成稿（工作汇报 / 心得体会 / 文章）。",
    "translate": "翻译成 --target 指定语种，保留段落结构。",
    "minutes": "生成完整结构化纪要：title、sub、brief（3 句结论）、chips、sections（每个含 title/items，items 含 text 与 time）、decl。",
}

RESULT_SCHEMA = {
    "title": "字符串，纪要标题",
    "sub": "字符串，一句话副标题",
    "summary": "字符串，150 字内摘要",
    "brief": ["三句结论，每句可含 {{mm:ss}} 引用"],
    "chips": [{"tone": "no|mid|ok", "k": "状态", "v": "事项"}],
    "sections": [{"title": "板块名", "sub": "板块说明",
                  "comment": "一句话点评",
                  "items": [{"text": "要点，可含 {{mm:ss}}", "time": "mm:ss"}]}],
    "chapters": [{"time": "mm:ss", "title": "章节名", "note": "本章说明"}],
    "keywords": ["关键词"],
    "todos": ["待办"],
    "highlights": ["重点"],
    "insights": {"risks": [], "decisions": [], "expansion": []},
    "qa": {"question": "", "answer": "", "followups": []},
    "mindmap": "mermaid mindmap 源码",
    "digest_segments": ["提炼后的段落"],
    "writing": "成稿全文",
    "translation": "译文全文",
    "decl": [{"k": "材料性质", "v": "说明"}],
}

SYSTEM_PROMPT = (
    "你是录音纪要整理助手。严格依据给定转写稿工作：\n"
    "1. 不编造事实、人名、数字、结论；原文没说的就不写。\n"
    "2. 所有时间码必须是转写稿里真实存在的段首 [mm:ss]，格式 mm:ss。\n"
    "3. 输出严格为单个 JSON 对象，不要 Markdown 代码块、不要解释文字。\n"
    "4. 只填本次任务要求的字段，其余字段给空数组或空字符串。\n"
    "5. 中文输出。"
)


def die(msg, code=2):
    sys.stderr.write("[analyze] " + msg + "\n")
    sys.exit(code)


def read(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


def parse_transcript(path):
    segs = []
    for line in read(path).splitlines():
        m = TS_RE.match(line.strip())
        if not m:
            continue
        t = "%s:%s" % (m.group(1).zfill(2), m.group(2))
        body = m.group(3).strip()
        who = ""
        rm = ROLE_RE.match(body)
        if rm:
            who = rm.group(0).rstrip("：: ").strip()
            body = body[rm.end():].strip()
        if body:
            segs.append({"t": t, "who": who, "x": body})
    return segs


def to_sec(t):
    p = t.split(":")
    return int(p[0]) * 60 + int(p[1])


def fmt(s):
    return "%02d:%02d" % (s // 60, s % 60)


def collect_times(obj, found=None):
    """递归收集 {{mm:ss}} 与 time 字段。"""
    if found is None:
        found = set()
    if isinstance(obj, str):
        found.update(CITE_RE.findall(obj))
        if re.fullmatch(r"\d{1,3}:\d{2}", obj.strip()):
            found.add(obj.strip())
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("time", "t", "cites") or isinstance(v, (str, list, dict)):
                collect_times(v, found)
    elif isinstance(obj, list):
        for v in obj:
            collect_times(v, found)
    return found


def replace_times(obj, mapping):
    if isinstance(obj, str):
        for a, b in mapping.items():
            obj = obj.replace("{{%s}}" % a, "{{%s}}" % b)
            if obj.strip() == a:
                obj = b
        return obj
    if isinstance(obj, list):
        return [replace_times(v, mapping) for v in obj]
    if isinstance(obj, dict):
        return {k: replace_times(v, mapping) for k, v in obj.items()}
    return obj


def validate_times(result, anchors, snap=False):
    """所有时间引用必须命中真实段首；不允许悄悄改。"""
    used = collect_times(result)
    # collect_times 会把 transcript 的 t 也收进来，这里 result 不含 transcript
    missing = sorted(t for t in used if t not in anchors)
    if missing and not snap:
        die("有 %d 个时间码未命中段首：%s\n"
            "  不擅自对齐。修正 analysis-result.json，或显式加 --snap-times 对齐到 ±5s 内最近段首。"
            % (len(missing), ", ".join(missing[:12])))
    mapping = {}
    if missing and snap:
        asec = sorted(to_sec(a) for a in anchors)
        for t in missing:
            v = to_sec(t)
            near = min(asec, key=lambda x: abs(x - v))
            if abs(near - v) > 5:
                die("时间码 %s 距最近段首超过 5 秒，拒绝自动对齐（会指错内容）" % t)
            mapping[t] = fmt(near)
        print("已显式对齐 %d 个时间码：%s" %
              (len(mapping), ", ".join("%s→%s" % kv for kv in list(mapping.items())[:8])))
    return replace_times(result, mapping) if mapping else result


def build_prompt(segs, tasks, ask, style, target, photos):
    lines = ["# 任务", ""]
    for t in tasks:
        lines.append("- **%s**：%s" % (t, TASKS[t]))
    if ask:
        lines.append("- **qa**：回答问题「%s」，并给 3–5 个推荐追问方向。" % ask)
    lines += ["", "## 输出要求", "",
              "输出单个 JSON，字段结构如下（未要求的字段给空值）：", "",
              "```json", json.dumps(RESULT_SCHEMA, ensure_ascii=False, indent=2), "```", "",
              "## 硬约束", "",
              "- 时间码只能取自下面的真实段首，格式 mm:ss。",
              "- 引用写成 {{mm:ss}}；独立字段 time 写 mm:ss。",
              "- 不得编造人名、数字、结论、引语。",
              "- 若涉多模态照片，只在 insights 里结合批注作答，不要虚构照片里没有的东西。", ""]
    if style:
        lines.append("--style = %s" % style)
    if target:
        lines.append("--target = %s" % target)
    if photos:
        lines += ["", "## 随录音记录的照片与批注（由 agent 自行打开查看）", ""]
        for p in photos:
            lines.append("- %s" % p)
    lines += ["", "## 转写全文（真实段首时间码见每行开头）", ""]
    for s in segs:
        lines.append("[%s] %s%s" % (s["t"], (s["who"] + "：" if s["who"] else ""), s["x"]))
    lines += ["", "## 真实段首时间码索引", "",
              ", ".join(s["t"] for s in segs), ""]
    return "\n".join(lines)


def cmd_request(args):
    if not args.input:
        die("需要 --input 转写稿")
    if not os.path.exists(args.input):
        die("输入不存在：%s" % args.input)
    segs = parse_transcript(args.input)
    if not segs:
        die("没解析出 [mm:ss] 段落；AI 理解层依赖真实时间锚点")
    tasks = []
    for t in args.tasks.split(","):
        t = t.strip()
        if not t:
            continue
        if t not in TASKS:
            die("未知任务 %s（可用：%s）" % (t, "/".join(TASKS)))
        tasks.append(t)
    if not tasks and not args.ask:
        tasks = ["summary", "chapters", "keywords", "minutes"]
    photos = [p.strip() for p in args.photos.split(",") if p.strip()] if args.photos else []
    outdir = os.path.abspath(args.outdir or os.path.dirname(os.path.abspath(args.input)))
    os.makedirs(outdir, exist_ok=True)
    prompt = build_prompt(segs, tasks, args.ask, args.style, args.target, photos)

    req_path = os.path.join(outdir, "analysis-request.md")
    schema_path = os.path.join(outdir, "analysis-schema.json")
    result_path = os.path.join(outdir, "analysis-result.json")
    with io.open(req_path, "w", encoding="utf-8") as f:
        f.write("# AI 理解请求包（引擎：%s）\n\n" % args.engine)
        f.write("产出后把结果写成 `%s`，再跑：\n" % os.path.basename(result_path))
        f.write("`python3 analyze.py --apply %s --transcript %s --verify-render`\n\n"
                % (result_path, args.input))
        f.write("---\n\n" + prompt)
    with io.open(schema_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(RESULT_SCHEMA, ensure_ascii=False, indent=2) + "\n")

    print("转写段数 %d | 任务 %s" % (len(segs), ",".join(tasks) or "qa"))
    print("引擎 %s（%s）" % (args.engine, "不出本机" if args.engine == "agent" else "数据出本机"))
    print("请求包 %s" % req_path)
    print("schema  %s" % schema_path)

    if args.engine == "agent":
        print("\n下一步：把请求包交给宿主 Agent，在本对话里完成并写回 %s" % result_path)
        print("再跑 --apply 校验时间码并生成纪要内容 JSON。")
        return 0
    engines.guard("cloud" if args.engine == "cloud" else "workbuddy", args.confirmed)
    if args.engine == "workbuddy":
        _, p = engines.workbuddy_request(prompt, SYSTEM_PROMPT, outdir)
        print("已生成平台 LLM 请求包：%s" % p)
        print("请交给 agent 用平台能力完成；脚本未直接调用后端。")
        return 0
    raw = engines.cloud_chat(prompt, SYSTEM_PROMPT)
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as e:
        bad = os.path.join(outdir, "llm-raw.txt")
        with io.open(bad, "w", encoding="utf-8") as f:
            f.write(raw)
        die("LLM 返回的不是合法 JSON（原文已存 %s）：%s" % (bad, e))
    with io.open(result_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print("结果 %s" % result_path)
    return 0


def normalize_sections(result):
    """把简化 sections 转成 render_split.py 的 cards 结构；原生结构原样保留。"""
    out = []
    for i, sec in enumerate(result.get("sections") or []):
        if not isinstance(sec, dict):
            continue
        if sec.get("type") in ("cards", "steps", "checks", "duel"):
            out.append(sec)
            continue
        items = sec.get("items") or []
        body = []
        for it in items:
            if isinstance(it, str):
                body.append(it)
            elif isinstance(it, dict):
                text = (it.get("text") or "").strip()
                t = (it.get("time") or "").strip()
                if text and t and "{{" not in text:
                    text += "（{{%s}}）" % t
                if text:
                    body.append(text)
        if not body:
            body = [(sec.get("sub") or "本板块要点待补")]
        out.append({
            "type": "cards", "title": sec.get("title") or "板块 %d" % (i + 1),
            "sub": sec.get("sub") or "", "tone": ["blue", "amber", "green"][i % 3],
            "cards": [{"label": sec.get("title") or "要点", "body": body,
                       "comment": sec.get("comment") or ""}],
        })
    chapters = result.get("chapters") or []
    if chapters:
        out.append({"type": "steps", "title": "章节速览",
                    "sub": "按内容转折划分，点时间码可回听",
                    "steps": [{"k": c.get("title") or "章节", "time": c.get("time") or "",
                               "tags": [], "body": c.get("note") or "", "cm": ""}
                              for c in chapters if isinstance(c, dict)]})
    todos = result.get("todos") or []
    if todos:
        out.append({"type": "checks", "title": "待办与待核",
                    "sub": "逐条回听确认",
                    "checks": [{"k": "待办", "v": t if isinstance(t, str) else str(t)}
                               for t in todos]})
    return out


def build_content(result, segs, stem, audio, duration, skin):
    roles = []
    for s in segs:
        if s["who"] and s["who"] not in roles:
            roles.append(s["who"])
    brief = result.get("brief") or []
    if isinstance(brief, dict):
        brief = [brief]
    brief = [{"x": (b.get("x") if isinstance(b, dict) else str(b))} for b in brief]
    sections = normalize_sections(result)
    if not sections:
        sections = [{"type": "cards", "title": "要点", "sub": "AI 辅助提炼",
                     "tone": "blue", "cards": [{"label": "摘要", "body": [result.get("summary") or "（无摘要）"],
                                               "comment": ""}]}]
    meta = result.get("meta") or [
        {"k": "素材", "v": stem},
        {"k": "时长", "v": duration or "未提供"},
        {"k": "整理方式", "v": "AI 辅助提炼 + 时间码校验"},
    ]
    return {
        "title": result.get("title") or stem,
        "title_tag": result.get("title") or stem,
        "kicker": result.get("kicker") or "录音纪要 · AI 辅助整理",
        "sub": result.get("sub") or (result.get("summary") or "")[:90],
        "meta": meta,
        "brief_title": result.get("brief_title") or "三句话结论",
        "brief": brief,
        "chips": result.get("chips") or [],
        "audio": audio,
        "duration": duration,
        "roles": roles,
        "search_placeholder": "在全文搜索关键词（按 / 聚焦）",
        "sections": sections,
        "decl": result.get("decl") or [
            {"k": "材料性质", "v": "本纪要由 AI 辅助提炼，时间码、说话人归属与事实须回听原音核验。"}],
        "stamp": "整理日期 %s · 依据录音转写 AI 理解层生成" % datetime.date.today().isoformat(),
        "transcript": segs,
        "_skin": skin,
    }


def write_text(path, lines):
    with io.open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(str(x) for x in lines).rstrip() + "\n")


def cmd_apply(args):
    if not os.path.exists(args.apply):
        die("结果文件不存在：%s" % args.apply)
    if not args.transcript or not os.path.exists(args.transcript):
        die("--apply 需要 --transcript 指向真实整理稿（用于校验时间锚点）")
    result = json.loads(read(args.apply))
    segs = parse_transcript(args.transcript)
    if not segs:
        die("整理稿没解析出段落")
    anchors = {s["t"] for s in segs}
    result = validate_times(result, anchors, args.snap_times)

    outdir = os.path.abspath(args.outdir or os.path.dirname(os.path.abspath(args.apply)))
    os.makedirs(outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(args.transcript))[0].replace("-整理稿", "").replace("-对话稿(纯正文)", "")
    made = []

    def put(name, content):
        p = os.path.join(outdir, name)
        if isinstance(content, (list, dict)):
            with io.open(p, "w", encoding="utf-8") as f:
                f.write(json.dumps(content, ensure_ascii=False, indent=2) + "\n")
        else:
            write_text(p, [content])
        made.append(p)

    if result.get("summary"):
        put("%s-摘要.md" % stem, "# %s · 摘要\n\n%s" % (stem, result["summary"]))
    if result.get("digest_segments"):
        put("%s-内容提炼.txt" % stem, result["digest_segments"])
    if result.get("chapters"):
        ch = ["# 章节速览", ""]
        for c in result["chapters"]:
            if isinstance(c, dict):
                ch.append("- **[%s] %s** — %s" % (c.get("time", ""), c.get("title", ""), c.get("note", "")))
        put("%s-章节速览.md" % stem, ch)
    if result.get("keywords"):
        put("%s-关键词.txt" % stem, result["keywords"])
    if result.get("todos"):
        put("%s-待办.md" % stem, ["# 待办", ""] + ["- [ ] %s" % t for t in result["todos"]])
    if result.get("highlights"):
        put("%s-重点.md" % stem, ["# 重点", ""] + ["- %s" % t for t in result["highlights"]])
    ins = result.get("insights") or {}
    if isinstance(ins, dict) and any(ins.values()):
        lines = ["# 洞察、风险与建议", ""]
        for k, label in (("risks", "风险识别"), ("decisions", "决策建议"), ("expansion", "知识拓展")):
            if ins.get(k):
                lines += ["## " + label, ""] + ["- %s" % x for x in ins[k]] + [""]
        put("%s-洞察与风险.md" % stem, lines)
    if result.get("mindmap"):
        put("%s-思维导图.mmd" % stem, result["mindmap"])
    qa = result.get("qa") or {}
    if qa:
        lines = ["# 问答", "", "**问**：%s" % qa.get("question", ""), "",
                 "**答**：%s" % qa.get("answer", ""), "", "## 推荐追问", ""]
        lines += ["- %s" % q for q in (qa.get("followups") or [])]
        put("%s-问答.md" % stem, lines)
    if result.get("writing"):
        put("%s-写作稿.md" % stem, result["writing"])
    if result.get("translation"):
        put("%s-译文.txt" % stem, [result["translation"]])
    if result.get("rewrite"):
        put("%s-书面语稿.txt" % stem, [result["rewrite"]])

    content = build_content(result, segs, stem, args.audio, args.duration, args.skin)
    content.pop("_skin", None)
    cj = os.path.join(outdir, "%s-纪要内容.json" % stem)
    put(os.path.basename(cj), content)

    print("校验通过：%d 段锚点，时间引用全部命中" % len(anchors))
    print("内容 JSON：%s" % cj)
    print("单件产物 %d 个：" % len(made))
    for p in made:
        print("  " + p)

    if args.verify_render:
        out = os.path.join(outdir, "%s-校验渲染.html" % stem)
        cmd = [sys.executable, RENDER_SPLIT, "--content", cj,
               "--audio", args.audio or "audio.m4a", "--skin", args.skin,
               "--check", "--out", out]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        blob = (r.stdout or "") + (r.stderr or "")
        m = re.search(r"断链\s*(\d+)\s*处", blob)
        ok = r.returncode == 0 and m and m.group(1) == "0"
        print("渲染器 --check：exit=%d 断链=%s -> %s" %
              (r.returncode, m.group(1) if m else "未匹配", "PASS" if ok else "FAIL"))
        if not ok:
            sys.stderr.write(blob[-1200:] + "\n")
            return 1
    return 0


def main():
    ap = argparse.ArgumentParser(description="AI 理解层（问答/洞察/纪要/章节/关键词/导图/写作）",
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__)
    ap.add_argument("--input", default="", help="[mm:ss] 整理稿")
    ap.add_argument("--tasks", default="summary,chapters,keywords,todos,highlights,insights,questions,minutes",
                    help="逗号分隔的任务，见文件头")
    ap.add_argument("--ask", default="", help="针对材料提问，并生成推荐追问")
    ap.add_argument("--style", default="", help="write 任务的文风：report/reflection/article")
    ap.add_argument("--target", default="", help="translate 任务的目标语种")
    ap.add_argument("--photos", default="", help="照片路径，逗号分隔（agent 自行查看）")
    ap.add_argument("--engine", default="agent", choices=["agent", "cloud", "workbuddy"])
    ap.add_argument("--i-understand-data-leaves-this-machine", action="store_true",
                    dest="confirmed")
    ap.add_argument("--outdir", default="")
    ap.add_argument("--apply", default="", help="把 analysis-result.json 拆成产物并生成纪要内容 JSON")
    ap.add_argument("--transcript", default="", help="--apply 时的真实整理稿（时间锚点来源）")
    ap.add_argument("--snap-times", action="store_true", help="显式允许把 ±5s 内偏差对齐到最近段首")
    ap.add_argument("--audio", default="", help="音频文件名（相对 HTML 目录）")
    ap.add_argument("--duration", default="", help="总时长 mm:ss")
    ap.add_argument("--skin", default="neutral", help="校验渲染时用的皮肤")
    ap.add_argument("--verify-render", action="store_true", help="调用 render_split.py --check 验证可渲染")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.apply:
        return cmd_apply(args)
    return cmd_request(args)


if __name__ == "__main__":
    sys.exit(main())
