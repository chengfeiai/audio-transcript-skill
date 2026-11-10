#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一引擎适配器：local / manual / cloud / workbuddy（纯标准库）。

铁律：
  * local 与 manual 全程本机，不联网。
  * cloud / workbuddy 会把转写文本送出本机，必须显式传
    --i-understand-data-leaves-this-machine，并打印醒目警告。
  * workbuddy 引擎不自行构造后端地址、不虚构 publicConfig；只生成请求包，
    由 agent 用平台能力完成。脚本不直接调用云服务后端。
  * 不硬编码任何 endpoint / API key，全部来自环境变量。

CLI：
  python3 engines.py --list
  python3 engines.py --check cloud
  python3 engines.py ingest --input 外部精转稿.txt --out 规范稿.txt
  python3 engines.py --chat --text "..." --engine cloud --i-understand-data-leaves-this-machine
"""
import argparse
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TRANSCRIBE = os.path.join(HERE, "transcribe.py")

ENGINES = {
    "local": {
        "name": "本地 mlx-whisper", "offline": True,
        "desc": "默认识别引擎，Apple Silicon 上跑，音频不出本机",
        "env": ["HF_HUB_OFFLINE=1", "TRANSFORMERS_OFFLINE=1"],
    },
    "manual": {
        "name": "人工精转 / 外部稿接入", "offline": True,
        "desc": "外部速记团队或云端引擎出稿后规范化，直供渲染器",
        "env": [],
    },
    "cloud": {
        "name": "OpenAI 兼容端点（自备）", "offline": False,
        "desc": "AI 理解 / 翻译 / 内容提炼；需自备端点与密钥",
        "env": ["WB_LLM_ENDPOINT", "WB_LLM_KEY", "WB_LLM_MODEL(可选)"],
    },
    "workbuddy": {
        "name": "宿主平台免密钥大模型", "offline": False,
        "desc": "需 agent 开通应用云服务并注入 publicConfig；脚本只生成请求包",
        "env": ["由 agent 注入 publicConfig，脚本不读取长期密钥"],
    },
}

WARNING = (
    "⚠️ 数据将离开本机：本次会把转写正文发送到外部大模型。"
    "涉密、含个人信息或未授权公开的录音请勿继续。"
)

SRT_TIME_RE = re.compile(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*")
TS_RE = re.compile(r"^\[(\d{1,3}):(\d{2})\]\s*(.*)$")
ROLE_MAP = [
    (re.compile(r"^SPEAKER[_ -]?(\d+)\s*[:：]\s*", re.I), lambda m: "说话人%s：" % m.group(1)),
    (re.compile(r"^说话人\s*(\d+)\s*[:：]\s*"), lambda m: "说话人%s：" % m.group(1)),
    (re.compile(r"^角色\s*(\d+)\s*[:：]\s*"), lambda m: "说话人%s：" % m.group(1)),
]


def die(msg, code=2):
    sys.stderr.write("[engines] " + msg + "\n")
    sys.exit(code)


def guard(engine, confirmed):
    e = ENGINES.get(engine)
    if not e:
        die("未知引擎：%s（可用：%s）" % (engine, "/".join(ENGINES)))
    if not e["offline"]:
        print(WARNING)
        if not confirmed:
            die("未确认。请显式追加 --i-understand-data-leaves-this-machine 后重试。")
    return e


def check(engine):
    e = ENGINES[engine]
    print("[%s] %s | 离线=%s" % (engine, e["name"], e["offline"]))
    if engine == "local":
        print("  transcribe.py: %s" % ("存在" if os.path.exists(TRANSCRIBE) else "缺失"))
        print("  需要自备转写环境与模型缓存，见 安装说明.md")
    elif engine == "manual":
        print("  ingest 子命令可直接把外部稿规范化，无需任何依赖")
    elif engine == "cloud":
        for k in ("WB_LLM_ENDPOINT", "WB_LLM_KEY"):
            print("  %-18s %s" % (k, "已设置" if os.environ.get(k) else "未设置"))
        print("  WB_LLM_MODEL: %s" % os.environ.get("WB_LLM_MODEL", "（缺省 gpt-4o-mini）"))
        print("  未设置时 --chat 会明确报错，不静默降级")
    else:
        print("  脚本不直接调用后端；需 agent 开通应用云服务后注入 publicConfig")
        print("  未注入时只产出请求包，不假称已调用成功")
    return 0


def ingest(path, out, require_timestamps=False):
    """把外部精转稿 / SRT / 云端稿规范化成 [mm:ss] 说话人：正文。"""
    if not os.path.exists(path):
        die("输入不存在：%s" % path)
    src = io.open(path, encoding="utf-8").read()
    lines, no_ts = [], 0
    is_srt = "-->" in src
    pending_t = None
    for raw in src.splitlines():
        line = raw.strip()
        if not line:
            continue
        sm = SRT_TIME_RE.search(line)
        if sm:
            pending_t = "%02d:%02d" % (int(sm.group(1)) * 60 + int(sm.group(2)), int(sm.group(3)))
            continue
        if is_srt and re.match(r"^\d+$", line):
            continue
        m = TS_RE.match(line)
        if m:
            t, body = "%s:%s" % (m.group(1).zfill(2), m.group(2)), m.group(3).strip()
        elif pending_t:
            t, body = pending_t, line
            pending_t = None
        else:
            t, body = None, line
        for pat, fn in ROLE_MAP:
            mm = pat.match(body)
            if mm:
                body = fn(mm) + body[mm.end():]
                break
        if t:
            lines.append("[%s] %s" % (t, body))
        else:
            no_ts += 1
            lines.append(body)
    if require_timestamps and no_ts:
        die("有 %d 行没有时间码。--require-timestamps 已开启，拒绝编造时间锚点。" % no_ts)
    with io.open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("规范化 %d 行 -> %s" % (len(lines), out))
    if no_ts:
        print("⚠️ %d 行无时间锚点：可用于阅读，但纪要页的 {{mm:ss}} 引用无法指向它们。" % no_ts)
        print("   本脚本不会替你编时间码；请回原音频补时间戳，或用 --require-timestamps 先拦下。")
    return {"lines": len(lines), "no_timestamp": no_ts, "out": out}


def cloud_chat(prompt, system=""):
    """OpenAI 兼容端点；端点与密钥全部来自环境变量，不硬编码。"""
    ep = os.environ.get("WB_LLM_ENDPOINT", "").strip()
    key = os.environ.get("WB_LLM_KEY", "").strip()
    model = os.environ.get("WB_LLM_MODEL", "gpt-4o-mini").strip()
    if not ep or not key:
        die("cloud 引擎缺少环境变量 WB_LLM_ENDPOINT / WB_LLM_KEY。未发起任何请求。")
    url = ep if ep.rstrip("/").endswith("chat/completions") else ep.rstrip("/") + "/chat/completions"
    payload = {"model": model, "temperature": 0.3,
               "messages": ([{"role": "system", "content": system}] if system else []) +
                           [{"role": "user", "content": prompt}]}
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            body = json.loads(r.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        die("LLM 返回 HTTP %s：%s" % (e.code, e.read().decode("utf-8", "replace")[:300]))
    except urllib.error.URLError as e:
        die("LLM 请求失败：%s（未静默降级到任何本地假结果）" % e.reason)
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        die("LLM 响应结构不符合预期：%s" % e)


def workbuddy_request(prompt, system, outdir):
    """只生成请求包；由 agent 用平台能力完成，脚本不自行构造后端地址。"""
    os.makedirs(outdir, exist_ok=True)
    p = os.path.join(outdir, "llm-request.json")
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "engine": "workbuddy",
            "note": "需 agent 开通应用云服务并注入 publicConfig（endpoint / publishableKey）后，"
                    "由 agent 通过平台能力调用 LLM；本脚本不直接调用后端、不虚构 config。",
            "system": system, "prompt": prompt,
        }, ensure_ascii=False, indent=2))
    return None, p


def main():
    ap = argparse.ArgumentParser(description="统一引擎适配器（local/manual/cloud/workbuddy）",
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__)
    ap.add_argument("command", nargs="?", default="", help="ingest（外部稿规范化）")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--check", default="", help="检查某引擎可用性（不联网）")
    ap.add_argument("--chat", action="store_true", help="发起一次大模型对话")
    ap.add_argument("--text", default="", help="--chat 的用户提示词")
    ap.add_argument("--system", default="", help="--chat 的系统提示词")
    ap.add_argument("--input", default="", help="ingest 输入文件")
    ap.add_argument("--out", default="", help="ingest 输出文件 / 请求包目录")
    ap.add_argument("--require-timestamps", action="store_true")
    ap.add_argument("--engine", default="local", choices=list(ENGINES))
    ap.add_argument("--i-understand-data-leaves-this-machine", action="store_true",
                    dest="confirmed")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.list:
        for k, v in ENGINES.items():
            print("  %-10s %-24s 离线=%-5s %s" % (k, v["name"], v["offline"], v["desc"]))
            print("     " + " / ".join(v["env"]))
        return 0
    if args.check:
        return check(args.check)
    if args.command == "ingest":
        if not args.input or not args.out:
            die("ingest 需要 --input 与 --out")
        r = ingest(args.input, args.out, args.require_timestamps)
        if args.json:
            print(json.dumps(r, ensure_ascii=False))
        return 0
    if args.chat:
        guard(args.engine, args.confirmed)
        if not args.text:
            die("--chat 需要 --text")
        if args.engine == "cloud":
            print(cloud_chat(args.text, args.system))
            return 0
        if args.engine == "workbuddy":
            _, p = workbuddy_request(args.text, args.system, args.out or ".")
            print("已生成请求包：%s" % p)
            print("请交给 agent 用平台能力完成；脚本未直接调用后端。")
            return 0
        die("local / manual 引擎不是对话引擎；--chat 请用 cloud 或 workbuddy")
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
