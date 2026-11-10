#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公开短视频分享链接 → 本地音频轨（录音转写 skill 的可选「素材获取」环节）。

原理（别改回 yt-dlp 直取）：
  平台 Web 播放地址带签名参数，yt-dlp / 裸请求会报
  "Fresh cookies (not necessarily logged in) are needed"。
  本脚本不伪造签名：用 ego-browser 打开真实视频页，让页面自己完成
  带签名的请求，再从 performance 资源表里读现成的 CDN 独立音频轨
  （media-audio-und-mp4a），加 Referer 下载。转写只需要声音，
  因此不必下整段视频。

适用边界：
  - 仅公开可播放的视频页；不绕过登录墙 / 付费墙 / 私密内容。
  - 只取声音用于本地转写，不分发音视频原件，遵守平台服务条款。
  - 签名 URL 有时效；过期重跑一次即可（脚本会自动重开页面取新的）。

依赖（均非本包自带）：ego-browser CLI、curl、ffmpeg/ffprobe。
Python 侧纯标准库，无需 pip install。

用法:
  python3 scripts/fetch_douyin_audio.py "<分享短链或视频页 URL>" --out "音频.m4a"
  python3 scripts/fetch_douyin_audio.py "<URL>" --dry-run
  python3 scripts/fetch_douyin_audio.py "<URL>" --json

退出码: 0 成功 / 1 环境缺失 / 2 页面不可用 / 3 未找到流 / 4 下载失败 / 5 校验失败
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
REFERER = "https://www.douyin.com/"
BEGIN = "__DY_RESULT__"
END = "__DY_END__"
CODES = {"env": 1, "page": 2, "stream": 3, "download": 4, "verify": 5}


class ProbeError(Exception):
    """探测阶段可重试的失败：页面主线程忙 / 导航超时 / 风控波动。"""

OPEN_JS = r"""
const task = await taskSpace(__SPACE__);
try {
  const page = task.page("p1");
  await page.goto(__URL__, { timeout: __TIMEOUT__, waitUntil: "domcontentloaded" });
  await page.waitForTimeout(__WAIT__);
  console.log("__DY_OPENED__");
} catch (e) {
  try { await task.finish({ keep: [] }); } catch (e2) {}
  throw e;
}
"""

READ_JS = r"""
const task = await taskSpace(__SPACE__);
try {
  const page = task.page("p1");
  const info = await page.evaluate(() => {
    const urls = performance.getEntriesByType("resource").map(e => e.name);
    const uniq = a => Array.from(new Set(a));
    const audio = uniq(urls.filter(u =>
      /media-audio|mime_type=audio|douyinvod.*audio/i.test(u)));
    const video = uniq(urls.filter(u =>
      /media-video|douyinvod.*video|\.mp4(\?|$)/i.test(u) && !/\.js/i.test(u)));
    const m = (location.href || "").match(/\/video\/(\d{6,})/);
    return {
      pageUrl: location.href || "",
      title: document.title || "",
      awemeId: m ? m[1] : "",
      videoTags: document.querySelectorAll("video").length,
      resourceCount: urls.length,
      readyState: document.readyState || "",
      audio: audio.slice(0, 6),
      video: video.slice(0, 6)
    };
  });
  console.log("__DY_RESULT__" + JSON.stringify(info) + "__DY_END__");
} finally {
  if (!__KEEP__) await task.finish({ keep: [] });
}
"""


def die(kind, msg):
    sys.stderr.write("[fetch_douyin_audio] %s\n" % msg)
    sys.exit(CODES[kind])


def resolve(url):
    """把 v.douyin.com 短链解析成稳定视频页 URL，避免浏览器卡在跳转页。

    只走 HTTP 重定向链，不执行页面 JS；解析失败则原样返回，让浏览器自己跳。
    """
    if "douyin.com" not in url:
        return url
    m = re.search(r"/video/(\d{6,})", url)
    if m and "v.douyin.com" not in url:
        return "https://www.douyin.com/video/" + m.group(1)
    if "v.douyin.com" not in url:
        return url
    cmd = ["curl", "-sL", "--max-time", "20", "-A", UA,
           "-o", os.devnull, "-w", "%{url_effective}", url]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        eff = (r.stdout or "").strip()
    except Exception:
        return url
    m = re.search(r"/video/(\d{6,})", eff)
    return "https://www.douyin.com/video/" + m.group(1) if m else url


def check_env():
    missing = [x for x in ("ego-browser", "curl") if not shutil.which(x)]
    if missing:
        die("env", "缺少命令 %s。ego-browser 用于真实浏览器取流（见 SKILL.md「素材来源」），"
                   "curl 用于落盘。装好再跑；本包不自带这两者。" % ", ".join(missing))


def ego(js, timeout_s, what):
    """跑一段 ego-browser nodejs；console.log 可能落 stdout 也可能落 stderr，合并返回。"""
    try:
        r = subprocess.run(["ego-browser", "nodejs"], input=js,
                           capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        raise ProbeError("%s 超时。检查网络/代理，或加大 --timeout。" % what)
    return (r.stdout or "") + "\n" + (r.stderr or "")


def probe(url, space, wait_ms, timeout_ms, keep, attempts=3):
    """带重试的两阶段探测；页面主线程忙时换一个浏览器空间重开。"""
    last = ""
    for i in range(attempts):
        sp = space if i == 0 else "%s-t%d" % (space, i)
        try:
            return _probe_once(url, sp, wait_ms, timeout_ms, keep)
        except ProbeError as e:
            last = str(e)
            sys.stderr.write("[fetch_douyin_audio] 第 %d/%d 次探测失败，重开浏览器空间重试\n"
                             % (i + 1, attempts))
            time.sleep(2)
    die("page", "连续 %d 次探测失败（页面风控 / 主线程忙）。最后一次：%s\n"
                "隔几分钟重跑，或让用户直接提供本地音频文件。" % (attempts, last[-400:]))


def _probe_once(url, space, wait_ms, timeout_ms, keep):
    """先让真实页面稳定播放，再复用同一任务空间读资源表。

    平台页面刚 goto 完主线程较忙，page.evaluate 会撞 15s 超时；
    拆成两次进程调用（中间留出安静时间）后可用，也贴合手工验证过的节奏。
    """
    open_js = (OPEN_JS
               .replace("__SPACE__", json.dumps(space))
               .replace("__URL__", json.dumps(url))
               .replace("__TIMEOUT__", str(timeout_ms))
               .replace("__WAIT__", str(wait_ms)))
    read_js = (READ_JS
               .replace("__SPACE__", json.dumps(space))
               .replace("__KEEP__", "true" if keep else "false"))

    opened = ego(open_js, timeout_ms / 1000 + 90, "打开视频页")
    if "__DY_OPENED__" not in opened:
        raise ProbeError("视频页打开失败（跳转 / 网络 / 登录墙）。输出尾部："
                         + opened.strip()[-500:])
    time.sleep(2)
    blob = ego(read_js, 90, "读取页面资源表")
    m = re.search(re.escape(BEGIN) + r"(.*?)" + re.escape(END), blob, re.S)
    if not m:
        raise ProbeError("页面未返回探测结果（页面主线程忙 / 验证码 / 资源表被清空）。输出尾部："
                         + blob.strip()[-500:])
    try:
        return json.loads(m.group(1))
    except Exception as e:
        raise ProbeError("探测结果解析失败：%s" % e)


def find_ffmpeg():
    for p in (shutil.which("ffmpeg"), os.path.expanduser("~/.local/bin/ffmpeg"),
              "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if p and os.path.exists(p):
            return p
    return None


def download(url, dest, timeout):
    cmd = ["curl", "-sL", "--max-time", str(timeout), "-A", UA,
           "-H", "Referer: " + REFERER,
           "-H", "Origin: https://www.douyin.com",
           "-H", "Accept-Language: zh-CN,zh;q=0.9",
           url, "-o", dest, "-w", "%{http_code}"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 30)
    except subprocess.TimeoutExpired:
        return "TIMEOUT", 0
    code = (r.stdout or "").strip()[-3:]
    size = os.path.getsize(dest) if os.path.exists(dest) else 0
    return code, size


def inspect(path, ffmpeg):
    if not ffmpeg:
        return {"checked": False, "note": "未找到 ffmpeg，跳过媒体校验"}
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", path],
                       capture_output=True, text=True)
    s = r.stderr or ""
    dur = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", s)
    aud = re.search(r"Stream #[^\n]*Audio:\s*([^,\n]+)", s)
    seconds = (int(dur.group(1)) * 3600 + int(dur.group(2)) * 60 + float(dur.group(3))) if dur else None
    return {
        "checked": True,
        "valid": bool(dur and aud),
        "duration": ("%02d:%02d" % (int(seconds // 60), int(seconds % 60))) if seconds else "",
        "codec": aud.group(1).strip() if aud else "",
    }


def main():
    ap = argparse.ArgumentParser(description="公开短视频视频页 → 本地音频轨（借页面签名，不破解签名）")
    ap.add_argument("url", help="分享短链 v.douyin.com/... 或完整视频页 URL")
    ap.add_argument("--out", default=None, help="输出音频路径，默认 douyin-<id>.m4a")
    ap.add_argument("--wait", type=int, default=5000, help="每轮等待毫秒，默认 5000")
    ap.add_argument("--timeout", type=int, default=60, help="浏览器导航超时秒，默认 60")
    ap.add_argument("--dl-timeout", type=int, default=180, help="下载超时秒，默认 180")
    ap.add_argument("--space", default=None, help="ego-browser 任务空间名，默认自动生成")
    ap.add_argument("--keep-space", action="store_true", help="不关闭浏览器任务空间（调试用）")
    ap.add_argument("--dry-run", action="store_true", help="只探测流地址，不下载")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON 摘要")
    args = ap.parse_args()

    check_env()
    space = args.space or ("dyfetch-%d" % int(time.time()))
    timeout_ms = args.timeout * 1000

    target = resolve(args.url)
    if target != args.url:
        sys.stderr.write("[fetch_douyin_audio] 短链已解析：%s\n" % target)
    info = probe(target, space, args.wait, timeout_ms, args.keep_space)
    n_audio, n_video = len(info.get("audio") or []), len(info.get("video") or [])
    if not (n_audio or n_video):
        hint = ""
        head = (info.get("title") or "") + (info.get("readyState") or "")
        if any(k in head for k in ("验证", "登录", "安全", "滑块")):
            hint = "；页面疑似出现验证/登录拦截"
        elif info.get("videoTags") == 0:
            hint = "；页面没有 video 元素，可能是图文/直播回放/需要登录的内容"
        die("stream", "两轮探测都没找到可下载流%s。资源记录 %s 条，页面标题 %r。"
            % (hint, info.get("resourceCount", 0), info.get("title", "")))

    if args.dry_run:
        summary = {"ok": True, "dry_run": True, "aweme_id": info.get("awemeId", ""),
                   "page": info.get("pageUrl", ""), "title": info.get("title", ""),
                   "audio_tracks": n_audio, "video_tracks": n_video,
                   "resource_count": info.get("resourceCount", 0),
                   "note": "签名 URL 不写入日志，仅本次会话有效"}
        print(json.dumps(summary, ensure_ascii=False, indent=2) if args.json else
              "\n".join(["探测成功，未下载（--dry-run）",
                         "  页面      : " + summary["page"],
                         "  标题      : " + summary["title"],
                         "  独立音频轨: %d 条" % n_audio,
                         "  视频流    : %d 条" % n_video,
                         "  资源记录  : %d 条" % summary["resource_count"]]))
        return 0

    out = os.path.abspath(args.out or ("douyin-%s.m4a" % (info.get("awemeId") or "audio")))
    parent = os.path.dirname(out)
    if not os.path.isdir(parent):
        die("env", "输出目录不存在：%s" % parent)

    state = {"info": info}

    def pick():
        a = state["info"].get("audio") or []
        v = state["info"].get("video") or []
        if a:
            return "audio", a[0], out
        if v:
            return "video", v[0], out + ".video.mp4"
        return None, None, None

    ok, last, kind, dest = False, "", "", ""
    for attempt in range(2):
        kind, stream_url, dest = pick()
        if not stream_url:
            die("stream", "重试后仍无可下载流")
        code, size = download(stream_url, dest, args.dl_timeout)
        last = "HTTP %s / %d bytes" % (code, size)
        if code == "200" and size > 100000:
            ok = True
            break
        # 403 / 401 / 空文件：多半是 CDN 签名过期，重开页面取一条新 URL
        state["info"] = probe(target, "%s-r%d" % (space, attempt + 1),
                              args.wait, timeout_ms, args.keep_space)
    if not ok:
        die("download", "下载失败（%s）。签名可能已过期或内容需要登录；"
                       "重跑一次脚本会重开页面取新签名。详见 SKILL.md 诊断表。" % last)

    if kind == "video":
        ff = find_ffmpeg()
        if not ff:
            die("env", "该视频未拆独立音轨，需要 ffmpeg 从整段视频提取音频，但本机没找到 ffmpeg")
        r = subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error",
                            "-i", dest, "-vn", "-acodec", "copy", out],
                           capture_output=True, text=True)
        if r.returncode != 0:
            die("verify", "ffmpeg 提轨失败：%s" % (r.stderr or "")[-400:])
        os.remove(dest)

    meta = inspect(out, find_ffmpeg())
    if meta["checked"] and not meta["valid"]:
        die("verify", "落盘文件不是有效音频（缺少时长或音轨）：%s" % out)

    summary = {
        "ok": True, "out": out, "bytes": os.path.getsize(out),
        "aweme_id": state["info"].get("awemeId", ""),
        "page": state["info"].get("pageUrl", ""),
        "title": state["info"].get("title", ""),
        "stream": "独立音频轨" if kind == "audio" else "整段视频提轨",
        "duration": meta.get("duration", ""), "codec": meta.get("codec", ""),
        "media_check": "已校验" if meta["checked"] else meta.get("note", ""),
        "note": "签名 URL 未写入日志；仅供本地转写，不分发音视频原件",
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print("已取到音频轨（借页面签名，未破解签名）")
        print("  输出    : %s  (%.1f MB)" % (summary["out"], summary["bytes"] / 1048576.0))
        print("  来源    : %s" % summary["page"])
        print("  标题    : %s" % summary["title"])
        print("  流类型  : %s" % summary["stream"])
        print("  时长    : %s   编码: %s" % (summary["duration"] or "未知", summary["codec"] or "未知"))
        print("  校验    : %s" % summary["media_check"])
        print("  下一步  : <PY> scripts/transcribe.py \"%s\" --srt --md" % summary["out"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
