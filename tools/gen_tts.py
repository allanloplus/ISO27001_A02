"""產生旁白語音與時間軸。

讀取 content/script.json，以 edge-tts 為每句台詞合成語音
（Allan：台灣男聲 zh-TW-YunJheNeural；阿拉蕾：高音調女聲），
依固定間隔串接成一條 audio/narration.mp3，並輸出 js/timeline.js
供播放器與影片錄製共用。

用法：python3 tools/gen_tts.py [--force]
"""
import asyncio
import json
import os
import re
import ssl
import subprocess
import sys
import wave

import edge_tts
import edge_tts.communicate as _comm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "build", "tts")
SR = 24000

# 經由代理連線時使用代理的 CA；一般環境沿用 certifi
_CA = os.environ.get("TTS_CA_BUNDLE", "/root/.ccr/ca-bundle.crt")
if os.path.exists(_CA):
    _comm._SSL_CTX = ssl.create_default_context(cafile=_CA)
PROXY = os.environ.get("HTTPS_PROXY") or None

LEAD_FIRST = 1.2   # 影片開頭靜音
LEAD = 0.7         # 每個場景開始前
GAP = 0.35         # 句與句之間
TAIL = 0.9         # 場景結束後
END = 2.5          # 影片結尾

NUM = {"0": "零", "1": "一", "2": "二", "3": "三", "4": "四", "5": "五",
       "6": "六", "7": "七", "8": "八", "9": "九"}


def speak_text(text: str) -> str:
    """字幕文字 → 朗讀文字（處理條文編號等唸法）。"""
    t = text.replace("ISO 27001:2022", "ISO 兩萬七千零一，二零二二年版")
    t = t.replace("嗯洽", "嗯～洽")

    def clause(m):
        a, b = m.group(1), m.group(2)
        tail = "十一" if b == "11" else ("十八" if b == "18" else "".join(NUM[c] for c in b))
        return f"{NUM[a]}點{tail}"

    t = re.sub(r"(?<![\d.])(\d)\.(\d{1,2})(?![\d])", clause, t)
    t = t.replace("「", "").replace("」", "")
    return t


async def synth(text, sp, path):
    com = edge_tts.Communicate(text, sp["voice"], rate=sp["rate"], pitch=sp["pitch"], proxy=PROXY)
    await com.save(path)


def pcm(path):
    return subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
        check=True, capture_output=True).stdout


async def main(force=False):
    with open(os.path.join(ROOT, "content", "script.json"), encoding="utf-8") as f:
        script = json.load(f)
    os.makedirs(CACHE, exist_ok=True)
    os.makedirs(os.path.join(ROOT, "audio"), exist_ok=True)
    os.makedirs(os.path.join(ROOT, "js"), exist_ok=True)

    # 1) 逐句合成（有快取，文字不變不重做）
    jobs = []
    for s in script["scenes"]:
        for i, ln in enumerate(s["lines"]):
            sp = script["speakers"][ln["who"]]
            say = speak_text(ln["text"])
            key = f'{s["id"]}_{i:02d}'
            mp3 = os.path.join(CACHE, key + ".mp3")
            stamp = mp3 + ".txt"
            sig = json.dumps([say, sp], ensure_ascii=False)
            ln["_mp3"] = mp3
            if force or not os.path.exists(mp3) or not os.path.exists(stamp) or open(stamp, encoding="utf-8").read() != sig:
                jobs.append((say, sp, mp3, stamp, sig))
    print(f"synthesizing {len(jobs)} lines…")
    sem = asyncio.Semaphore(4)

    async def run(job):
        say, sp, mp3, stamp, sig = job
        async with sem:
            for attempt in range(4):
                try:
                    await synth(say, sp, mp3)
                    break
                except Exception as e:  # 網路偶發錯誤重試
                    if attempt == 3:
                        raise
                    await asyncio.sleep(2 ** attempt)
            with open(stamp, "w", encoding="utf-8") as f:
                f.write(sig)
    await asyncio.gather(*(run(j) for j in jobs))

    # 2) 串接並計算時間軸
    out = bytearray()
    silence = lambda sec: b"\x00\x00" * int(round(sec * SR))
    timeline = {"scenes": [], "lines": []}
    for si, s in enumerate(script["scenes"]):
        out += silence(LEAD_FIRST if si == 0 else LEAD)
        scene_start = len(out) / 2 / SR - (LEAD_FIRST if si == 0 else LEAD)
        for i, ln in enumerate(s["lines"]):
            if i:
                out += silence(GAP)
            start = len(out) / 2 / SR
            out += pcm(ln["_mp3"])
            end = len(out) / 2 / SR
            timeline["lines"].append({
                "scene": si, "who": ln["who"], "text": ln["text"],
                "step": ln.get("step"), "emote": ln.get("emote"),
                "start": round(start, 3), "end": round(end, 3)})
        out += silence(TAIL if si < len(script["scenes"]) - 1 else END)
        timeline["scenes"].append({"id": s["id"], "label": s["label"], "phase": s["phase"],
                                   "start": round(max(scene_start, 0), 3)})
    timeline["duration"] = round(len(out) / 2 / SR, 3)

    wav_path = os.path.join(ROOT, "build", "narration.wav")
    with wave.open(wav_path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(bytes(out))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", wav_path, "-c:a", "libmp3lame", "-b:a", "96k",
                    os.path.join(ROOT, "audio", "narration.mp3")], check=True)
    with open(os.path.join(ROOT, "js", "timeline.js"), "w", encoding="utf-8") as f:
        f.write("// 由 tools/gen_tts.py 自動產生，請勿手動修改\nwindow.TIMELINE = ")
        json.dump(timeline, f, ensure_ascii=False, indent=1)
        f.write(";\n")

    # 3) 講稿
    names = {k: v["name"] for k, v in script["speakers"].items()}
    md = [f'# {script["title"]}｜講稿', "", f'> {script["subtitle"]}', "",
          f'總長度約 {int(timeline["duration"] // 60)} 分 {int(timeline["duration"] % 60)} 秒', ""]
    for si, s in enumerate(script["scenes"]):
        st = timeline["scenes"][si]["start"]
        md += [f'## {si:02d}. {s["label"]}  `{int(st // 60):02d}:{int(st % 60):02d}`', ""]
        for ln in s["lines"]:
            md.append(f'- **{names[ln["who"]]}**：{ln["text"]}')
        md.append("")
    with open(os.path.join(ROOT, "講稿.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f'done: {len(timeline["lines"])} lines, {timeline["duration"]:.1f}s')


if __name__ == "__main__":
    asyncio.run(main(force="--force" in sys.argv))
