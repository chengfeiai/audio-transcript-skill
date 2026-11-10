#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""录音转文字：mlx-whisper 本地转写脚本（Apple Silicon 加速）。

用法:
  transcribe.py <音频文件> [--model small|medium|large] [--lang zh] [--outdir DIR]
                [--srt] [--md] [--no-txt] [--speakers] [--initial-prompt "..."]

输出（默认与音频同目录、同名）:
  <name>.txt   纯文字稿（带 [mm:ss] 时间戳段落）
  <name>.srt   字幕文件
  <name>.md    Markdown 时间轴稿（--md 时）
"""
import argparse
import os
import subprocess
import sys
import time

MODEL_DEFAULT = "medium"

def get_ffmpeg():
    """优先用 imageio-ffmpeg 自带的静态 ffmpeg；找不到则退回系统 PATH。"""
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass
    for cand in ("ffmpeg", "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        p = subprocess.run(["which", cand], capture_output=True, text=True)
        if p.returncode == 0:
            return p.stdout.strip()
    return None

def to_wav(src: str, dst: str, ffmpeg: str) -> None:
    """任意格式 → 16kHz 单声道 wav（whisper 的标准输入）。"""
    cmd = [ffmpeg, "-y", "-i", src, "-ar", "16000", "-ac", "1", "-vn", dst]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 转码失败: {r.stderr[-800:]}")

def fmt_ts(sec: float) -> str:
    m = int(sec // 60)
    s = int(sec % 60)
    return f"{m:02d}:{s:02d}"

def fmt_srt_ts(sec: float) -> str:
    h = int(sec // 3600); m = int((sec % 3600) // 60)
    s = int(sec % 60); ms = int((sec - int(sec)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def main() -> int:
    ap = argparse.ArgumentParser(description="本地录音转文字（mlx-whisper）")
    ap.add_argument("audio", help="音频文件路径（m4a/mp3/wav/flac/aac/ogg…）")
    ap.add_argument("--model", default=MODEL_DEFAULT, choices=["small", "medium", "large", "turbo"])
    ap.add_argument("--lang", default="zh", help="语言代码，默认 zh")
    ap.add_argument("--outdir", default=None, help="输出目录（默认与音频同目录）")
    ap.add_argument("--srt", action="store_true", help="同时输出 srt 字幕")
    ap.add_argument("--md", action="store_true", help="同时输出 md 时间轴稿")
    ap.add_argument("--no-txt", action="store_true", help="不输出 txt")
    ap.add_argument("--initial-prompt", default=None, help="提示词（如领域术语，提高准确率）")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    src = os.path.abspath(args.audio)
    if not os.path.exists(src):
        print(f"✗ 文件不存在: {src}", file=sys.stderr)
        return 1

    base, ext = os.path.splitext(src)
    outdir = args.outdir or os.path.dirname(src) or "."
    os.makedirs(outdir, exist_ok=True)
    name = os.path.basename(base)
    wav = os.path.join(outdir, f".{name}.tmp16k.wav")

    t0 = time.time()
    ffmpeg = get_ffmpeg()
    if ffmpeg is None:
        print("✗ 找不到 ffmpeg（请 pip install imageio-ffmpeg 或安装 ffmpeg）", file=sys.stderr)
        return 1

    print(f"⏳ 转码音频 → 16kHz wav ({ext})")
    to_wav(src, wav, ffmpeg)
    if args.verbose:
        print(f"   wav: {wav}")

    print(f"⏳ 转写中（model={args.model}, lang={args.lang}）…")
    import mlx_whisper
    result = mlx_whisper.transcribe(
        wav,
        path_or_hf_repo=f"mlx-community/whisper-{args.model}-mlx",
        language=args.lang,
        initial_prompt=args.initial_prompt,
        verbose=False,
    )
    segs = result.get("segments", [])
    if not segs:
        print("⚠ 未转写出任何文字（可能录音为空或过短）")
        if os.path.exists(wav):
            os.remove(wav)
        return 2

    # --- txt：纯文字稿，段落带时间戳 ---
    if not args.no_txt:
        txt_path = os.path.join(outdir, f"{name}.txt")
        lines = [f"[{fmt_ts(s['start'])}] {s['text'].strip()}" for s in segs]
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print(f"✓ 文字稿: {txt_path}")

    # --- srt 字幕 ---
    if args.srt:
        srt_path = os.path.join(outdir, f"{name}.srt")
        with open(srt_path, "w", encoding="utf-8") as f:
            for i, s in enumerate(segs, 1):
                f.write(f"{i}\n{fmt_srt_ts(s['start'])} --> {fmt_srt_ts(s['end'])}\n{s['text'].strip()}\n\n")
        print(f"✓ 字幕: {srt_path}")

    # --- md：Markdown 时间轴 ---
    if args.md:
        md_path = os.path.join(outdir, f"{name}.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(f"# {name}\n\n> 转写于 {time.strftime('%Y-%m-%d %H:%M')} · model={args.model} · lang={args.lang}\n\n")
            for s in segs:
                f.write(f"**[{fmt_ts(s['start'])}–{fmt_ts(s['end'])}]** {s['text'].strip()}\n\n")
        print(f"✓ 时间轴: {md_path}")

    dur = result.get("duration") or (segs[-1]["end"] if segs else 0)
    print(f"✓ 完成：共 {len(segs)} 段 / 时长 {dur:.0f}s / 耗时 {time.time()-t0:.1f}s")

    if os.path.exists(wav):
        os.remove(wav)
    return 0

if __name__ == "__main__":
    sys.exit(main())
