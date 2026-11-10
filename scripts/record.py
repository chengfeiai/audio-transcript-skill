#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实时采集：实时录音 / 边录边转 / 插入批注 / 实时字幕（纯标准库 + ffmpeg）。

能力：
  --list-devices        列出本机音频输入设备
  --check               只探测依赖与设备，不占麦克风（CI / 回归安全）
  --system-audio        检测系统声音内录条件（虚拟声卡），缺则给安装指引
  --seconds N           录一段麦克风音频
  --live                分片录音 + 增量转写（边录边转）
  --live-srt            同时增量写字幕
  --interactive         录音过程中从终端读批注行：普通文本 / photo:/abs/path
  --dry-run             只打印将执行的命令，不录音、不占设备

素材不出本机。系统声音内录需要虚拟声卡（BlackHole / Soundflower），本脚本不安装任何驱动。
"""
import argparse
import io
import json
import os
import re
import select
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TRANSCRIBE = os.path.join(HERE, "transcribe.py")
# 默认用当前解释器；装有转写依赖的其它环境可用 WB_TRANSCRIBE_PY 指定
DEFAULT_PY = os.environ.get("WB_TRANSCRIBE_PY") or sys.executable
DEVICE_RE = re.compile(r"\[AVFoundation (?:input device|indev) @[^\]]+\]\s*\[(\d+)\]\s*(.+)")
VIRTUAL_AUDIO = ("blackhole", "soundflower", "loopback", "virtual", "sound siphon",
                 "aggregate device", "blackhole 2ch", "vb-cable")


def die(msg, code=2):
    sys.stderr.write("[record] " + msg + "\n")
    sys.exit(code)


def find_ffmpeg():
    try:
        import imageio_ffmpeg
        p = imageio_ffmpeg.get_ffmpeg_exe()
        if p and os.path.exists(p):
            return p
    except Exception:
        pass
    for cand in ("ffmpeg", "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg",
                 os.path.expanduser("~/.local/bin/ffmpeg")):
        if os.path.exists(cand):
            return cand
        r = subprocess.run(["which", cand], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    return None


def platform_name():
    return "macos" if sys.platform == "darwin" else ("linux" if sys.platform.startswith("linux") else "other")


def list_devices(ffmpeg):
    plat = platform_name()
    if plat == "macos":
        r = subprocess.run([ffmpeg, "-hide_banner", "-f", "avfoundation",
                            "-list_devices", "true", "-i", ""],
                           capture_output=True, text=True)
        blob = (r.stdout or "") + "\n" + (r.stderr or "")
        audio_part = blob.split("AVFoundation audio devices:")[-1]
        devs = [{"index": int(m.group(1)), "name": m.group(2).strip()}
                for m in DEVICE_RE.finditer(audio_part)]
        if not devs:
            devs = [{"index": int(m.group(1)), "name": m.group(2).strip()}
                    for m in DEVICE_RE.finditer(blob)]
        return devs, blob
    if plat == "linux":
        r = subprocess.run(["arecord", "-l"], capture_output=True, text=True)
        return ([{"index": 0, "name": "default"}], (r.stdout or "") + (r.stderr or ""))
    return [], "当前平台未适配自动设备枚举，请用 --device 显式指定 ffmpeg 输入"


def check_system_audio(blob):
    low = blob.lower()
    hit = [v for v in VIRTUAL_AUDIO if v in low]
    return hit


def record_chunk(ffmpeg, device, seconds, out, dry_run=False):
    if platform_name() == "macos":
        src = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
               "-f", "avfoundation", "-i", ":%s" % device]
    elif platform_name() == "linux":
        src = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
               "-f", "alsa", "-i", "default"]
    else:
        die("当前平台未适配录音，请用 --dry-run 查看命令后手工执行")
    cmd = src + ["-t", str(seconds), "-ar", "16000", "-ac", "1", "-vn", out]
    if dry_run:
        print("[dry-run] " + " ".join(cmd))
        return True
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write((r.stderr or "")[-600:] + "\n")
        return False
    return os.path.exists(out) and os.path.getsize(out) > 1000


def parse_segs(path, offset=0):
    segs = []
    if not os.path.exists(path):
        return segs
    for line in io.open(path, encoding="utf-8"):
        m = re.match(r"^\[(\d{1,3}):(\d{2})\]\s*(.*)$", line.strip())
        if not m:
            continue
        t = int(m.group(1)) * 60 + int(m.group(2)) + offset
        if m.group(3).strip():
            segs.append({"t": t, "text": m.group(3).strip()})
    return segs


def srt_of(segs):
    def ts(t):
        return "%02d:%02d:%02d,000" % (t // 3600, (t % 3600) // 60, t % 60)
    return "\n".join("%d\n%s --> %s\n%s\n" % (
        i + 1, ts(s["t"]), ts(s["t"] + 5), s["text"]) for i, s in enumerate(segs))


def read_mark():
    try:
        if not sys.stdin.isatty():
            return None
        ready, _, _ = select.select([sys.stdin], [], [], 0)
        if not ready:
            return None
        line = sys.stdin.readline()
        return line.strip() if line else None
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description="实时采集（实时录音 / 边录边转）",
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__)
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--check", action="store_true", help="只探测，不占设备")
    ap.add_argument("--system-audio", action="store_true", help="检测系统内录条件")
    ap.add_argument("--seconds", type=int, default=0, help="单次录音秒数")
    ap.add_argument("--live", action="store_true", help="分片增量转写")
    ap.add_argument("--live-srt", action="store_true", help="增量写 SRT")
    ap.add_argument("--interactive", action="store_true", help="录音中读终端批注行")
    ap.add_argument("--chunk", type=int, default=15, help="分片秒数，默认 15")
    ap.add_argument("--chunks", type=int, default=4, help="--live 的分片数，默认 4")
    ap.add_argument("--device", default="0", help="macOS 音频设备序号")
    ap.add_argument("--python", default=DEFAULT_PY, help="装有转写依赖的 Python 解释器（默认 WB_TRANSCRIBE_PY 或当前解释器）")
    ap.add_argument("--model", default="medium")
    ap.add_argument("--lang", default="zh")
    ap.add_argument("--outdir", default=".", help="输出目录")
    ap.add_argument("--out", default="", help="输出文件名（默认 实时录音-时间戳）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        die("找不到 ffmpeg。安装后重试，或参考 安装说明.md 的可选依赖")
    devs, blob = list_devices(ffmpeg)

    if args.list_devices or args.check or args.system_audio:
        print("ffmpeg: %s" % ffmpeg)
        print("平台: %s" % platform_name())
        print("音频输入设备:")
        for d in devs:
            print("  [%s] %s" % (d["index"], d["name"]))
        if not devs:
            print("  （未枚举到设备；可能需要麦克风权限，或用 --device 指定）")
        virt = check_system_audio(blob)
        if args.system_audio or args.check:
            if virt:
                print("系统声音内录: 检测到虚拟/会议音频设备 %s" % "/".join(virt))
                print("  可能可用于系统内录；用 --list-devices 看序号，")
                print("  再 --seconds 5 --device <序号> 试录确认（本脚本不代申请权限）。")
            else:
                print("系统声音内录: 未检测到虚拟声卡")
                print("  安装 BlackHole（brew install blackhole-2ch）或 Soundflower，")
                print("  在「音频 MIDI 设置」建多输出设备，再用 --device 选该设备。")
                print("  macOS 13+ 也可走 ScreenCapture 框架，但需单独授权，本脚本不代申请。")
        if args.check:
            print("转写解释器: %s" % ("可用" if os.path.exists(args.python) else "不可用（--live 需 --python 指定）"))
            print("transcribe.py: %s" % ("存在" if os.path.exists(TRANSCRIBE) else "缺失"))
        return 0

    outdir = os.path.abspath(args.outdir)
    os.makedirs(outdir, exist_ok=True)
    stem = args.out or ("实时录音-" + time.strftime("%Y%m%d-%H%M%S"))
    wav = os.path.join(outdir, stem + ".wav")

    if not args.live:
        secs = args.seconds or 10
        ok = record_chunk(ffmpeg, args.device, secs, wav, args.dry_run)
        print("录音 %s：%s" % ("命令已生成（未执行）" if args.dry_run else ("成功" if ok else "失败"), wav))
        return 0 if (ok or args.dry_run) else 1

    if not os.path.exists(args.python):
        die("--live 需要装有转写依赖的 Python 解释器：%s 不存在。用 --python 指定，或只跑 --check/--seconds" % args.python)
    if not os.path.exists(TRANSCRIBE):
        die("缺少 transcribe.py：%s" % TRANSCRIBE)

    all_segs, marks = [], []
    txt_path = os.path.join(outdir, stem + ".txt")
    srt_path = os.path.join(outdir, stem + ".srt")
    ann_path = os.path.join(outdir, stem + "-批注.json")
    env = dict(os.environ)
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"

    for i in range(args.chunks):
        offset = i * args.chunk
        part = os.path.join(outdir, "%s-part%02d.wav" % (stem, i + 1))
        if not record_chunk(ffmpeg, args.device, args.chunk, part, args.dry_run):
            print("第 %d 片录音失败，停止" % (i + 1))
            break
        if args.dry_run:
            continue
        r = subprocess.run([args.python, TRANSCRIBE, part, "--lang", args.lang,
                            "--model", args.model, "--outdir", outdir],
                           capture_output=True, text=True, env=env)
        if r.returncode != 0:
            sys.stderr.write("第 %d 片转写失败：%s\n" % (i + 1, (r.stderr or "")[-300:]))
        got = parse_segs(os.path.join(outdir, os.path.splitext(os.path.basename(part))[0] + ".txt"), offset)
        all_segs.extend(got)
        with io.open(txt_path, "w", encoding="utf-8") as f:
            for s in all_segs:
                f.write("[%02d:%02d] %s\n" % (s["t"] // 60, s["t"] % 60, s["text"]))
        if args.live_srt:
            with io.open(srt_path, "w", encoding="utf-8") as f:
                f.write(srt_of(all_segs))
        mark = read_mark() if args.interactive else None
        if mark:
            photo = ""
            if mark.lower().startswith("photo:"):
                photo = mark[6:].strip()
                mark = "照片批注"
            marks.append({"t": offset + args.chunk, "ts": "%02d:%02d" % ((offset + args.chunk) // 60,
                                                                        (offset + args.chunk) % 60),
                          "text": mark, "photo": photo})
            with io.open(ann_path, "w", encoding="utf-8") as f:
                f.write(json.dumps({"session": stem, "marks": marks}, ensure_ascii=False, indent=2))
        print("  第 %d/%d 片：+%d 段（累计 %d）" % (i + 1, args.chunks, len(got), len(all_segs)))

    summary = {"session": stem, "segments": len(all_segs), "marks": len(marks),
               "txt": txt_path, "srt": srt_path if args.live_srt else "",
               "annotations": ann_path if marks else "", "dry_run": args.dry_run}
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2) if args.dry_run else
              "完成：%d 段，输出 %s" % (len(all_segs), txt_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
