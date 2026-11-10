#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""资产与协作层：自动分类知识库 / 多端同步 / 分享链接 / 导出链接 / 企业接入。

默认全程本机；--sync / --publish 会把数据送出本机，必须显式确认。

  python3 library.py --root <工作区> --index
  python3 library.py --share <纪要.html> --outdir <分享目录>
  python3 library.py --export-link <纪要.html> --outdir <目录>
  python3 library.py --sync --target user@host:/path --i-understand-data-leaves-this-machine
  python3 library.py --access
"""
import argparse
import datetime
import io
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOTWORDS = os.path.join(ROOT, "hotwords.json")
AUDIO_EXT = (".m4a", ".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4v", ".mp4")
TEXT_EXT = (".txt", ".md", ".srt", ".json", ".minutes", ".mmd")
SKIP_DIRS = {".git", ".workbuddy", "__pycache__", "node_modules", "share"}

WARNING = "⚠️ 数据将离开本机：本次会把本地文件上传到外部位置。"

ACCESS = [
    ("桌面客户端 / App / 小程序 / 录音笔 / 会议屏", "GUI 与硬件产品", "开新应用项目；CLI 等价能力已在 record.py"),
    ("人工精转团队 / 加急 / 闲时 / 超时退款", "真实人力与订单系统", "外部出稿后 engines.py ingest → render_split.py --transcript"),
    ("厂商准确率数字背书", "需第三方评测报告", "本包不宣称任何准确率数字"),
    ("译后配音 / 声音克隆", "TTS 与声纹克隆服务", "接入云端 TTS（L3 显式开关）"),
    ("团队权限 / SSO / 企业后台 / 会议资产沉淀", "后端与身份系统", "开通应用云服务：auth + database 模块"),
    ("API / SDK / 混合云 / 私有化部署", "企业采购与运维", "同上，需企业方案与部署"),
    ("账号 / 订单 / 计费 / 会员 / 短信通知 / 客服", "商业系统与资质", "产品运营范畴，非脚本可交付"),
    ("在线分享链接", "需发布站点", "agent 调用发布能力，复用同一 applicationId"),
]


def die(msg, code=2):
    sys.stderr.write("[library] " + msg + "\n")
    sys.exit(code)


def classify(name, head):
    try:
        db = json.loads(io.open(HOTWORDS, encoding="utf-8").read())
    except Exception:
        return "未分类"
    blob = (name + " " + head).lower()
    best, score = "未分类", 0
    for domain, words in db.get("domains", {}).items():
        n = sum(1 for w in words if w.lower() in blob)
        if n > score:
            best, score = domain, n
    return best


def scan(root):
    items = []
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for f in sorted(files):
            ext = os.path.splitext(f)[1].lower()
            if ext not in AUDIO_EXT + TEXT_EXT + (".html",):
                continue
            p = os.path.join(base, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            head = ""
            if ext in (".txt", ".md", ".minutes"):
                try:
                    head = io.open(p, encoding="utf-8", errors="replace").read(400)
                except OSError:
                    pass
            items.append({"path": p, "rel": os.path.relpath(p, root), "name": f,
                          "ext": ext, "bytes": st.st_size,
                          "mtime": datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d"),
                          "topic": classify(f, head)})
    return items


def cmd_index(args):
    root = os.path.abspath(args.root or ".")
    if not os.path.isdir(root):
        die("目录不存在：%s" % root)
    items = scan(root)
    groups = {}
    for it in items:
        groups.setdefault(it["topic"], []).append(it)
    outdir = os.path.abspath(args.outdir or root)
    os.makedirs(outdir, exist_ok=True)
    idx = os.path.join(outdir, "知识库索引.md")
    lines = ["# 录音知识库索引", "",
             "生成时间：%s · 扫描目录：`%s` · 文件 %d 个" %
             (datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), root, len(items)), "",
             "> 本索引由本地规则聚类生成，未联网、未上传任何文件。分类依据 hotwords.json 领域词表。", ""]
    for topic in sorted(groups):
        lines += ["## %s（%d）" % (topic, len(groups[topic])), ""]
        for it in groups[topic]:
            kb = it["bytes"] / 1024
            size = "%.1f MB" % (kb / 1024) if kb > 1024 else "%.0f KB" % kb
            lines.append("- `%s` · %s · %s" % (it["rel"], size, it["mtime"]))
        lines.append("")
    with io.open(idx, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")
    data = os.path.join(outdir, "library.json")
    with io.open(data, "w", encoding="utf-8") as f:
        f.write(json.dumps({"root": root, "count": len(items),
                            "topics": {k: len(v) for k, v in groups.items()},
                            "items": items}, ensure_ascii=False, indent=2) + "\n")
    print("扫描 %d 个文件，聚类 %d 类 -> %s" % (len(items), len(groups), idx))
    for k, v in sorted(groups.items()):
        print("  %-10s %d" % (k, len(v)))
    if args.json:
        print(json.dumps({"index": idx, "data": data, "count": len(items)}, ensure_ascii=False))
    return 0


def find_audio_in_html(html):
    s = io.open(html, encoding="utf-8", errors="replace").read()
    return re.findall(r'(?:src|data-audio)=["\']([^"\']+\.(?:m4a|mp3|wav|aac|ogg))["\']', s, re.I)


def cmd_share(args):
    if not args.share or not os.path.exists(args.share):
        die("--share 需要一个存在的 HTML 文件")
    html = os.path.abspath(args.share)
    outdir = os.path.abspath(args.outdir or os.path.join(os.path.dirname(html), "share"))
    os.makedirs(outdir, exist_ok=True)
    copied = []
    dst_html = os.path.join(outdir, os.path.basename(html))
    shutil.copy2(html, dst_html)
    copied.append(dst_html)
    audios = find_audio_in_html(html)
    for a in audios:
        src = os.path.join(os.path.dirname(html), a)
        if os.path.exists(src):
            dst = os.path.join(outdir, os.path.basename(a))
            shutil.copy2(src, dst)
            copied.append(dst)
        else:
            print("⚠️ HTML 引用的音频不在同目录：%s（回听会失效）" % a)
    note = os.path.join(outdir, "分享说明.md")
    with io.open(note, "w", encoding="utf-8") as f:
        f.write("# 分享包说明\n\n")
        f.write("- HTML 与音频必须同目录，页面才能点时间码回听。\n")
        f.write("- 单独转发 HTML 时，搜索、复制、导出 Word 仍可用，只是不能播音频。\n")
        f.write("- 包内文件：\n")
        for p in copied:
            f.write("  - `%s`\n" % os.path.basename(p))
        f.write("\n## 生成在线链接\n\n")
        f.write("本脚本不自行发布。把整个目录交给 agent，由 agent 调用发布能力生成在线链接，\n")
        f.write("并复用同一 applicationId（否则云端登录的 Origin 校验会失败）。\n")
        f.write("拿到 URL 后可用 `qrencode -o qr.png '<URL>'` 生成二维码。\n")
    req = os.path.join(outdir, "publish-request.json")
    with io.open(req, "w", encoding="utf-8") as f:
        f.write(json.dumps({"action": "publish", "directory": outdir,
                            "entryHtml": os.path.basename(dst_html),
                            "note": "由 agent 用平台发布能力完成；脚本不自行调用后端",
                            "publish": bool(args.publish)}, ensure_ascii=False, indent=2) + "\n")
    qr = shutil.which("qrencode")
    if args.url and qr:
        r = subprocess.run([qr, "-o", os.path.join(outdir, "qr.png"), args.url],
                           capture_output=True, text=True)
        if r.returncode == 0:
            copied.append(os.path.join(outdir, "qr.png"))
    elif args.url:
        with io.open(os.path.join(outdir, "二维码生成命令.txt"), "w", encoding="utf-8") as f:
            f.write("qrencode -o qr.png '%s'\n" % args.url)
        print("未装 qrencode，已写生成命令；brew install qrencode 后可直接生成二维码")
    print("分享包：%s（%d 个文件）" % (outdir, len(copied)))
    for p in copied:
        print("  " + os.path.basename(p))
    print("说明：%s" % note)
    if args.publish:
        print("已生成发布请求包（未自行发布）：%s" % req)
        print("请交给 agent 用平台能力完成；脚本不假称已上线。")
    return 0


def cmd_export_link(args):
    html = args.export_link
    if not html or not os.path.exists(html):
        die("--export-link 需要一个存在的 HTML")
    outdir = os.path.abspath(args.outdir or os.path.dirname(os.path.abspath(html)))
    os.makedirs(outdir, exist_ok=True)
    title = os.path.splitext(os.path.basename(html))[0]
    card = os.path.join(outdir, title + "-分享卡片.html")
    url = args.url or "（发布后填入在线链接）"
    with io.open(card, "w", encoding="utf-8") as f:
        f.write("<!doctype html><meta charset=\"utf-8\"><title>%s · 分享卡片</title>\n" % title)
        f.write("<div style=\"font:14px/1.7 system-ui;max-width:560px;margin:60px auto;padding:24px;"
                "border:1px solid #e5e5e5;border-radius:12px\">")
        f.write("<h2 style=\"font-weight:500;margin:0 0 12px\">%s</h2>" % title)
        f.write("<p>本地文件：<code>%s</code></p>" % os.path.basename(html))
        f.write("<p>在线链接：<code>%s</code></p>" % url)
        f.write("<p style=\"color:#666\">链接由 agent 发布后填入；本卡片只是链接格式的导出载体，"
                "不含任何外部请求。</p></div>\n")
    print("分享卡片：%s" % card)
    print("⚠️ 未发布前 URL 是占位，不是可访问链接。")
    return 0


def cmd_sync(args):
    if not args.confirmed:
        print(WARNING)
        die("未确认。请显式追加 --i-understand-data-leaves-this-machine")
    target = args.target or os.environ.get("WB_SYNC_TARGET", "")
    if not target:
        die("缺少同步目标：--target 或环境变量 WB_SYNC_TARGET")
    tool = "rclone" if shutil.which("rclone") else ("rsync" if shutil.which("rsync") else "")
    if not tool:
        die("本机没有 rsync / rclone；安装后重试。未发起任何上传。")
    src = os.path.abspath(args.root or ".")
    if tool == "rsync":
        cmd = ["rsync", "-av", "--dry-run" if args.dry_run else "-v", src + "/", target]
        if args.dry_run:
            cmd = ["rsync", "-av", "--dry-run", src + "/", target]
    else:
        cmd = ["rclone", "copy", src, target] + (["--dry-run"] if args.dry_run else [])
    print("执行：%s" % " ".join(cmd))
    if args.dry_run:
        print("（--dry-run，未真正上传）")
    r = subprocess.run(cmd, capture_output=True, text=True)
    print((r.stdout or "")[-800:])
    if r.returncode != 0:
        sys.stderr.write((r.stderr or "")[-500:] + "\n")
        return 1
    return 0


def cmd_access(args):
    print("%-42s %-24s %s" % ("项目", "为什么不是代码", "由谁点一下"))
    print("-" * 110)
    for a, b, c in ACCESS:
        print("%-42s %-24s %s" % (a, b, c))
    print("\n完整说明见 能力全景与接入清单.md 第 4 节。")
    return 0


def main():
    ap = argparse.ArgumentParser(description="资产与协作层（知识库 / 分享 / 企业接入）",
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__)
    ap.add_argument("--root", default="", help="扫描目录")
    ap.add_argument("--index", action="store_true", help="生成知识库索引")
    ap.add_argument("--share", default="", help="准备分享包的 HTML")
    ap.add_argument("--export-link", default="", help="导出链接格式分享卡片")
    ap.add_argument("--sync", action="store_true", help="同步到远端（数据出本机）")
    ap.add_argument("--target", default="", help="同步目标")
    ap.add_argument("--access", action="store_true", help="打印非代码形态接入清单")
    ap.add_argument("--publish", action="store_true", help="生成发布请求包（不自行发布）")
    ap.add_argument("--url", default="", help="已有在线链接，用于二维码")
    ap.add_argument("--outdir", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--i-understand-data-leaves-this-machine", action="store_true",
                    dest="confirmed")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.access:
        return cmd_access(args)
    if args.sync:
        return cmd_sync(args)
    if args.share:
        return cmd_share(args)
    if args.export_link:
        return cmd_export_link(args)
    if args.index:
        return cmd_index(args)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
