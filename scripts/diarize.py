#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""说话人分离转写：mlx-whisper 转写 + speechbrain ECAPA 声纹聚类（免费、无 token）。

用法:
  diarize.py <音频1> [音频2 ...] [--model medium] [--lang zh]
             [--initial-prompt "..."] [--min-speakers 1] [--max-speakers 6]
             [--outdir DIR] [--no-md] [--verbose]

输出（每个音频，与音频同目录）:
  <name>.对话稿.txt   每行: [mm:ss] 说话人N: 文字
  <name>.对话稿.md    Markdown 时间轴 + 说话人标注
"""
import argparse
import os
import subprocess
import sys
import time

MODEL_DEFAULT = "medium"


def get_ffmpeg():
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


def load_wav16k(src: str, ffmpeg: str):
    """任意格式 → (numpy float32 单声道 16k) 一次性读入。"""
    import numpy as np
    import soundfile as sf
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        cmd = [ffmpeg, "-y", "-i", src, "-ar", "16000", "-ac", "1", "-vn", tmp]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg 转码失败: {r.stderr[-500:]}")
        audio, sr = sf.read(tmp, dtype="float32")
        if sr != 16000:
            raise RuntimeError(f"采样率异常: {sr}")
        return audio
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def fmt_ts(sec: float) -> str:
    m = int(sec // 60)
    s = int(sec % 60)
    return f"{m:02d}:{s:02d}"


def merge_short_segments(segs, min_len=1.2):
    """把过短的段并入前一段（时间上最接近的相邻段）。"""
    out = []
    for s in segs:
        if out and (s["end"] - s["start"]) < min_len:
            prev = out[-1]
            prev["end"] = s["end"]
            prev["text"] = (prev["text"] + s["text"]).strip()
        else:
            out.append(dict(s))
    return out


def best_kmeans(X, min_k=1, max_k=6):
    """KMeans + silhouette 自动估计说话人数。"""
    import numpy as np
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    n = len(X)
    if n == 1:
        return 1, np.zeros(1, dtype=int)
    max_k = min(max_k, n)
    best_k, best_labels, best_score = 1, np.zeros(n, dtype=int), -1.0
    for k in range(min_k, max_k + 1):
        if k >= n:
            break
        km = KMeans(n_clusters=k, n_init=10, random_state=42)
        labels = km.fit_predict(X)
        if k == 1:
            best_k, best_labels = 1, labels
            continue
        sc = silhouette_score(X, labels)
        if sc > best_score:
            best_score, best_k, best_labels = sc, k, labels
    return best_k, best_labels


def main() -> int:
    ap = argparse.ArgumentParser(description="说话人分离转写")
    ap.add_argument("audios", nargs="+", help="音频文件（可多个，模型只加载一次）")
    ap.add_argument("--model", default=MODEL_DEFAULT, choices=["small", "medium", "large", "turbo"])
    ap.add_argument("--lang", default="zh")
    ap.add_argument("--initial-prompt", default=None)
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--min-speakers", type=int, default=1)
    ap.add_argument("--max-speakers", type=int, default=6)
    ap.add_argument("--no-md", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    import numpy as np
    import torch
    from speechbrain.inference.speaker import EncoderClassifier

    ffmpeg = get_ffmpeg()
    if ffmpeg is None:
        print("✗ 找不到 ffmpeg", file=sys.stderr)
        return 1

    print("⏳ 加载声纹模型 ECAPA-TDNN（首次会自动下载 ~200MB）…")
    t0 = time.time()
    classifier = EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        savedir=os.path.expanduser("~/.cache/speechbrain"),
        run_opts={"device": "cpu"},
    )
    print(f"✓ 声纹模型就绪（{time.time()-t0:.0f}s）\n")

    import mlx_whisper
    print(f"⏳ 加载转写模型 whisper-{args.model}…")
    t0 = time.time()

    for idx, src in enumerate(args.audios, 1):
        src = os.path.abspath(src)
        if not os.path.exists(src):
            print(f"✗ 跳过（不存在）: {src}", file=sys.stderr)
            continue
        base, _ = os.path.splitext(src)
        name = os.path.basename(base)
        outdir = args.outdir or os.path.dirname(src) or "."
        os.makedirs(outdir, exist_ok=True)
        print(f"\n[{idx}/{len(args.audios)}] {name}")

        # 1) 转写
        t1 = time.time()
        print("   ⏳ 转写…")
        result = mlx_whisper.transcribe(
            src,
            path_or_hf_repo=f"mlx-community/whisper-{args.model}-mlx",
            language=args.lang,
            initial_prompt=args.initial_prompt,
            verbose=False,
        )
        segs = merge_short_segments(result.get("segments", []))
        if not segs:
            print("   ⚠ 无转写内容，跳过")
            continue
        print(f"   ✓ 转写完成 {len(segs)} 段（{time.time()-t1:.0f}s）")

        # 2) 声纹 embedding（整段读入，按段切片）
        t1 = time.time()
        audio = load_wav16k(src, ffmpeg)
        embeds = []
        for s in segs:
            i0 = int(s["start"] * 16000)
            i1 = min(int(s["end"] * 16000), len(audio))
            chunk = audio[i0:i1]
            if chunk.shape[0] < 1600:  # <0.1s 直接跳过，用相邻填充
                chunk = np.pad(chunk, (0, 1600 - chunk.shape[0]))
            wav_t = torch.from_numpy(chunk).unsqueeze(0)
            with torch.no_grad():
                emb = classifier.encode_batch(wav_t).squeeze().numpy()
            embeds.append(emb)
        X = np.stack(embeds)
        print(f"   ✓ 声纹提取 {X.shape[0]} 段（{time.time()-t1:.0f}s）")

        # 3) 聚类
        k, labels = best_kmeans(X, args.min_speakers, args.max_speakers)
        print(f"   ✓ 说话人数估计: {k}（silhouette 自动）")

        # 4) 输出
        txt_path = os.path.join(outdir, f"{name}.对话稿.txt")
        lines = [f"[{fmt_ts(s['start'])}] 说话人{labels[i]+1}: {s['text'].strip()}"
                 for i, s in enumerate(segs)]
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print(f"   ✓ {txt_path}")

        if not args.no_md:
            md_path = os.path.join(outdir, f"{name}.对话稿.md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(f"# {name}\n\n> 说话人分离转写 · model={args.model} · 说话人 {k} 位\n\n")
                for i, s in enumerate(segs):
                    f.write(f"**[{fmt_ts(s['start'])}–{fmt_ts(s['end'])}] 说话人{labels[i]+1}**\n\n{s['text'].strip()}\n\n")
            print(f"   ✓ {md_path}")

    print("\n✅ 全部完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
