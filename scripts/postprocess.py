#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""出稿与规整：转写稿到成稿的出稿能力（断句、标点、字幕折行、错别字提示，纯标准库）。

能力清单：
  出稿四选  --format transcript|roles|subtitle|srt|md|json
  三档规整  --clean verbatim|fluent|digest     （digest 需 --llm，禁止硬截）
  场记时间码 --fieldcode 1|5                  （每 N 分钟打 hh:mm:ss）
  字幕排版  --max-chars 14|16|18|20           （SRT 按字数折行，保持时间轴）
  持久化词库 --hotwords / --domain / --add / --prompt / --list-domains
  语言边界  --languages / --check-lang

用法示例：
  python3 postprocess.py "录音.整理稿.txt" --format roles --clean fluent
  python3 postprocess.py "录音.整理稿.txt" --fieldcode 5 --max-chars 16
  python3 postprocess.py --hotwords --domain 教育 --prompt
  python3 postprocess.py --hotwords --add "交付时间,验收标准" --prompt
  python3 postprocess.py --languages --check-lang yue

数据不出本机；digest 与翻译需要 --llm 时只生成请求包，由 analyze.py / agent 承接。
"""
import argparse
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HOTWORDS_PATH = os.path.join(ROOT, "hotwords.json")
LANGS_PATH = os.path.join(ROOT, "languages.json")

SEG_RE = re.compile(r"^\[(\d{1,3}):(\d{2})\]\s*(.*)$")
ROLE_RE = re.compile(
    r"^(?:说话人\s*\d+|角色\s*\d+|SPEAKER[_ -]?\d+|[^\W\d_]{1,6})\s*[:：]\s*",
    re.U,
)
PAREN_FILLER = re.compile(r"[（(]\s*(?:嗯|呃|额|啊|哦|哈|咳)\s*[)）]")
LEAD_FILLER = re.compile(
    r"^(?:嗯|呃|额|啊|哎|唉|哦|那个|这个|就是说|然后|对|是的|好吧|好|那么)[，,、\s]*"
)
FILLER_WORDS = ("嗯", "呃", "额", "那个", "这个", "就是说", "对吧", "是吧")

DIGEST_HINT = (
    "内容提炼（digest）需要语义判断，脚本硬截会毁内容。三选一：\n"
    "  1) 交给 agent：python3 analyze.py --input <稿> --tasks digest --engine agent\n"
    "  2) 走云端引擎：python3 analyze.py --input <稿> --tasks digest --engine cloud "
    "--i-understand-data-leaves-this-machine\n"
    "  3) 明确接受机械抽取（结果仅供浏览，不作定稿）：再加 --allow-mechanical"
)


def die(msg, code=2):
    sys.stderr.write("[postprocess] " + msg + "\n")
    sys.exit(code)


def read(path):
    with io.open(path, encoding="utf-8") as f:
        return f.read()


def parse_transcript(path):
    """解析 [mm:ss] 稿（可带说话人），返回 [{t, ts, who, text}]。"""
    segs = []
    for raw in read(path).splitlines():
        m = SEG_RE.match(raw.strip())
        if not m:
            continue
        t = int(m.group(1)) * 60 + int(m.group(2))
        body = m.group(3).strip()
        who = None
        rm = ROLE_RE.match(body)
        if rm:
            who = rm.group(0).rstrip("：: ").strip()
            body = body[rm.end():].strip()
        if body:
            segs.append({"t": t, "ts": "%02d:%02d" % (t // 60, t % 60),
                         "who": who, "text": body})
    return segs


def srt_ts(sec):
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    return "%02d:%02d:%02d,000" % (h, m, s)


def clock_ts(sec):
    return "%02d:%02d:%02d" % (sec // 3600, (sec % 3600) // 60, sec % 60)


def end_times(segs):
    out = []
    for i, s in enumerate(segs):
        nxt = segs[i + 1]["t"] if i + 1 < len(segs) else s["t"] + 5
        delta = max(1, min(nxt - s["t"], 20))
        out.append(s["t"] + delta)
    return out


def fold_srt_text(text, max_chars):
    """按字数折行；中文按字、英文按词，尽量不拆开拉丁词。"""
    if max_chars <= 0 or len(text) <= max_chars:
        return [text]
    lines, cur = [], ""
    i = 0
    while i < len(text):
        ch = text[i]
        if ch.isascii() and (ch.isalpha() or ch.isdigit()):
            j = i
            while j < len(text) and text[j].isascii() and (text[j].isalpha() or text[j].isdigit()):
                j += 1
            token = text[i:j]
            if cur and len(cur) + len(token) > max_chars:
                lines.append(cur.rstrip())
                cur = ""
            cur += token
            i = j
        else:
            if len(cur) >= max_chars:
                lines.append(cur.rstrip())
                cur = ""
            cur += ch
            i += 1
    if cur.strip():
        lines.append(cur.rstrip())
    return lines or [text]


def clean_segments(segs, mode, allow_mechanical=False):
    """verbatim 原样 / fluent 去语气词 / digest 需 --llm。"""
    if mode == "verbatim":
        return list(segs)
    if mode == "fluent":
        out = []
        for s in segs:
            t = PAREN_FILLER.sub("", s["text"])
            t = LEAD_FILLER.sub("", t).strip()
            for w in FILLER_WORDS:
                t = t.replace(w + "，", "").replace(w + ",", "")
            t = re.sub(r"\s{2,}", " ", t).strip()
            out.append(dict(s, text=t))
        return out
    if mode == "digest":
        if not allow_mechanical:
            die(DIGEST_HINT)
        # 机械抽取：均匀取样到约 35%，并明确标注非定稿
        keep = max(1, round(len(segs) * 0.35))
        step = max(1, len(segs) // keep)
        picked = segs[::step][:keep]
        return [dict(s, text=s["text"] + " 〔机械抽取，需人工复核〕") for s in picked]
    die("未知 --clean 值：%s" % mode)


def render_format(segs, fmt, max_chars, no_ts=False):
    ends = end_times(segs)
    if fmt == "json":
        return json.dumps(segs, ensure_ascii=False, indent=2)
    if fmt == "md":
        return "\n\n".join(
            "**[%s–%02d:%02d]** %s" % (s["ts"], ends[i] // 60, ends[i] % 60,
                                        (s["who"] + "：" if s["who"] else "") + s["text"])
            for i, s in enumerate(segs))
    if fmt == "srt":
        buf = []
        for i, s in enumerate(segs):
            body = ("\n".join(fold_srt_text(s["text"], max_chars))) if max_chars else s["text"]
            buf.append("%d\n%s --> %s\n%s\n" % (i + 1, srt_ts(s["t"]), srt_ts(ends[i]), body))
        return "\n".join(buf)
    if fmt == "subtitle":
        return "\n".join(
            "\n".join(fold_srt_text(s["text"], max_chars or 20)) for s in segs)
    if fmt == "roles":
        return "\n".join(
            ("[%s] " % s["ts"] if not no_ts else "") +
            "%s：%s" % (s["who"] or "角色1", s["text"]) for s in segs)
    return "\n".join(
        ("[%s] " % s["ts"] if not no_ts else "") + s["text"] for s in segs)


def render_fieldcode(segs, minutes):
    """场记时间码：每 N 分钟打一次 hh:mm:ss，段落归入所在时间桶。"""
    span = minutes * 60
    buckets = {}
    for s in segs:
        b = (s["t"] // span) * span
        buckets.setdefault(b, []).append(s)
    buf = []
    for b in sorted(buckets):
        buf.append("【%s】" % clock_ts(b))
        for s in buckets[b]:
            buf.append("[%s] %s" % (s["ts"], (s["who"] + "：" if s["who"] else "") + s["text"]))
        buf.append("")
    return "\n".join(buf)


def load_hotwords(path):
    p = path or HOTWORDS_PATH
    if not os.path.exists(p):
        die("词库不存在：%s" % p)
    return json.loads(read(p)), p


def hotword_prompt(db, domain=None):
    words = list(db.get("custom") or [])
    if domain:
        if domain not in db.get("domains", {}):
            die("没有这个领域：%s（用 --list-domains 看可用值）" % domain)
        words = list(db["domains"][domain]) + words
    seen, clean = set(), []
    lim = db.get("limits", {})
    for w in words:
        w = w.strip()
        if not w or w in seen:
            continue
        if not (lim.get("word_min_chars", 1) <= len(w) <= lim.get("word_max_chars", 16)):
            continue
        seen.add(w)
        clean.append(w)
        if len(clean) >= lim.get("max_words", 200):
            break
    s = ",".join(clean)
    max_chars = lim.get("max_chars", 1000)
    if len(s) > max_chars:
        s = s[:max_chars].rstrip(",")
    return s, len(clean)


def cmd_hotwords(args):
    db, path = load_hotwords(args.hotwords if args.hotwords != "default" else None)
    if args.list_domains:
        for k, v in db.get("domains", {}).items():
            print("  %-8s %2d 词  %s" % (k, len(v), ",".join(v[:5])))
        return
    if args.add:
        adds = [x.strip() for x in re.split(r"[,，;；]", args.add) if x.strip()]
        db["custom"] = list(dict.fromkeys((db.get("custom") or []) + adds))
        with io.open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(db, ensure_ascii=False, indent=2) + "\n")
        print("已写入 %d 个自定义词 -> %s" % (len(adds), path))
    if args.prompt or args.add:
        s, n = hotword_prompt(db, args.domain)
        print("词数 %d / 字符 %d" % (n, len(s)))
        print("--initial-prompt \"%s\"" % s)
    if args.json:
        print(json.dumps({"domains": list(db.get("domains", {})),
                          "custom": db.get("custom", []), "path": path}, ensure_ascii=False))
    if not (args.list_domains or args.add or args.prompt or args.json):
        print(__doc__)


def cmd_languages(args):
    db = json.loads(read(LANGS_PATH))
    if args.check_lang:
        code = args.check_lang.strip().lower()
        std = db["whisper_lang_codes"]
        print("语种 %s：%s" % (code, std.get(code, "未列在本包语言表")))
        if code == "zh":
            print("  标准语场景适用；可直接 transcribe.py --lang zh")
        elif code in std:
            print("  whisper 理论支持，但本包未验证；不宣称准确率")
        else:
            print("  本地引擎不适用；按 languages.json 的 routing_rule 走云端引擎")
        print("  方言/混说/翻译：", db["capabilities_not_in_local_engine"]["translation"])
        return
    print("== whisper 标准语（本地理论支持） ==")
    for k, v in db["whisper_lang_codes"].items():
        print("  %-4s %s" % (k, v))
    print("\n== 方言（本包标注为需云端） ==")
    print("  " + " / ".join(db["cloud_only_dialects"]))
    print("\n== 路由规则 ==")
    print("  " + db["routing_rule"])


def main():
    ap = argparse.ArgumentParser(
        description="出稿与规整（断句 / 标点 / 字幕折行 / 热词）",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("input", nargs="?", help="[mm:ss] 转写稿 / 整理稿 txt")
    ap.add_argument("--format", default="transcript",
                    choices=["transcript", "roles", "subtitle", "srt", "md", "json"],
                    help="出稿形态，默认 transcript（文稿）")
    ap.add_argument("--clean", default="verbatim",
                    choices=["verbatim", "fluent", "digest"], help="规整档位")
    ap.add_argument("--allow-mechanical", action="store_true",
                    help="允许 digest 做机械抽取（仅供浏览，非定稿）")
    ap.add_argument("--merge-paragraphs", action="store_true",
                    help="合并同说话人碎句成自然段（⚠️ 会改变时间锚点，重渲纪要需重新对齐）")
    ap.add_argument("--fieldcode", type=int, choices=[1, 5], default=0,
                    help="额外产出场记时间码：每 1 或 5 分钟打 hh:mm:ss")
    ap.add_argument("--max-chars", type=int, default=0,
                    help="字幕单行字数（14 / 16 / 18 / 20 四档），默认不折行")
    ap.add_argument("--no-timestamps", action="store_true", help="文稿不带 [mm:ss]")
    ap.add_argument("--out", default="", help="主输出路径")
    ap.add_argument("--outdir", default="", help="输出目录（默认与输入同目录）")
    ap.add_argument("--json", action="store_true", help="打印结构化摘要")
    ap.add_argument("--hotwords", nargs="?", const="default",
                    help="持久化热词库操作（可给自定义 json 路径）")
    ap.add_argument("--domain", default="", help="选领域词表，如 自媒体 / 法律")
    ap.add_argument("--add", default="", help="追加自定义热词，逗号分隔")
    ap.add_argument("--prompt", action="store_true", help="输出可用于 transcribe.py 的 --initial-prompt")
    ap.add_argument("--list-domains", action="store_true", help="列出领域词表")
    ap.add_argument("--languages", action="store_true", help="列出语言能力与边界")
    ap.add_argument("--check-lang", default="", help="检查某语种/方言的可用路由")
    args = ap.parse_args()

    if args.hotwords or args.list_domains or args.add or args.prompt:
        cmd_hotwords(args)
        return 0
    if args.languages or args.check_lang:
        cmd_languages(args)
        return 0
    if not args.input:
        ap.print_help()
        return 0
    if not os.path.exists(args.input):
        die("输入文件不存在：%s" % args.input)

    segs = parse_transcript(args.input)
    if not segs:
        die("没解析出任何 [mm:ss] 段落；本脚本只吃带时间戳的转写稿/整理稿")
    segs = clean_segments(segs, args.clean, args.allow_mechanical)
    if args.merge_paragraphs:
        merged = []
        for s in segs:
            if (merged and merged[-1]["who"] == s["who"] and
                    len(merged[-1]["text"]) + len(s["text"]) < 140):
                merged[-1]["text"] += s["text"]
            else:
                merged.append(dict(s))
        segs = merged

    outdir = args.outdir or os.path.dirname(os.path.abspath(args.input))
    os.makedirs(outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(args.input))[0]
    suffix = {"transcript": "文稿", "roles": "标角色文稿", "subtitle": "字幕",
              "srt": "字幕(标时间戳).srt", "md": "时间轴.md", "json": "段落.json"}[args.format]
    main_out = args.out or os.path.join(outdir, "%s-%s%s" % (
        stem, suffix, "" if args.format in ("srt", "md", "json") else ".txt"))
    body = render_format(segs, args.format, args.max_chars, args.no_timestamps)
    with io.open(main_out, "w", encoding="utf-8") as f:
        f.write(body.rstrip() + "\n")

    extras = []
    if args.fieldcode:
        fp = os.path.join(outdir, "%s-场记%d分钟.txt" % (stem, args.fieldcode))
        with io.open(fp, "w", encoding="utf-8") as f:
            f.write(render_fieldcode(segs, args.fieldcode).rstrip() + "\n")
        extras.append(fp)
    if args.max_chars and args.format != "srt":
        sp = os.path.join(outdir, "%s-字幕%d字.srt" % (stem, args.max_chars))
        with io.open(sp, "w", encoding="utf-8") as f:
            f.write(render_format(segs, "srt", args.max_chars))
        extras.append(sp)

    summary = {"input": args.input, "segments": len(segs), "clean": args.clean,
               "format": args.format, "max_chars": args.max_chars,
               "out": main_out, "extras": extras,
               "merge_paragraphs": args.merge_paragraphs}
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print("段数 %d | 规整 %s | 出稿 %s" % (len(segs), args.clean, args.format))
        print("  主输出 %s" % main_out)
        for p in extras:
            print("  附加   %s" % p)
        if args.merge_paragraphs:
            print("  ⚠️ 已合并段落：时间锚点变少，重渲纪要需重新对齐 {{mm:ss}}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
