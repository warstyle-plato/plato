import os, sys, subprocess
from PIL import Image, ImageDraw, ImageFont
E = sys.argv[1]; Y = os.path.dirname(E); W, H = 1280, 720
YES = f"{Y}/fonts/Yeseva.ttf"; NUN = f"{Y}/fonts/Nunito.ttf"
O = f"{E}/outF"; os.makedirs(O, exist_ok=True)
def run(*a): subprocess.run(["ffmpeg", "-y", "-v", "error", *a], check=True)
def dur(p): return float(subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",p]))
# 1) часть 1 без «Продолжение следует…» (последний план end = 3.0 с)
d1 = dur(f"{E}/yong_ep1_part1.mp4"); END = 3.0
run("-i", f"{E}/yong_ep1_part1.mp4", "-t", f"{d1-END:.3f}", "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", f"{O}/p1.mp4")
# 2) заставка «Конец первой серии»
im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
for y in range(200, 470): d.line([(0, y), (W, y)], fill=(8, 11, 26, int(150 * (1 - abs(y - 335) / 135))))
for txt, font, size, y, col in [("Конец первой серии", YES, 72, 280, (255, 246, 236))]:
    f = ImageFont.truetype(font, size); tw = d.textlength(txt, font=f); x0 = (W - tw) / 2
    d.text((x0 + 2, y + 3), txt, font=f, fill=(0, 0, 0, 170)); d.text((x0, y), txt, font=f, fill=col + (255,))
im.save(f"{O}/ov_fin.png")
CL = 8.0
run("-i", f"{E}/v/302.mp4", "-loop", "1", "-i", f"{O}/ov_fin.png", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
    "-filter_complex", f"[0:v]trim=0:{CL},setpts=PTS-STARTPTS,scale={W}:{H},fps=24,format=yuv420p[b];[1:v]format=rgba,fade=in:st=0.6:d=0.8:alpha=1,trim=0:{CL}[t];[b][t]overlay=0:0:shortest=1,fade=in:st=0:d=0.6,fade=out:st={CL-1.5}:d=1.5[v]",
    "-map", "[v]", "-map", "2:a", "-t", f"{CL}", "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-c:a", "aac", "-b:a", "192k", f"{O}/fin.mp4")
# Хук на серию 2: Вася ночью приоткрывает глаз + фраза рассказчика, затем титр следующей серии
HK = 7.0
run("-i", f"{E}/v/K9306.mp4", "-i", f"{E}/a/HOOK.wav", "-i", f"{E}/sfx/room.mp3",
    "-filter_complex", f"[0:v]setpts=1.42*PTS,scale={W}:{H},fps=24,tpad=stop_mode=clone:stop_duration=1,trim=0:{HK},setpts=PTS-STARTPTS,format=yuv420p,fade=in:st=0:d=0.5[v];"
    f"[1:a]adelay=500|500,apad,atrim=0:{HK}[n];[2:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=0.25,atrim=0:{HK},afade=in:d=0.5[r];[n][r]amix=inputs=2:duration=first:normalize=0[a]",
    "-map", "[v]", "-map", "[a]", "-t", f"{HK}", "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", f"{O}/hook.mp4")
im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
for y in range(200, 470): d.line([(0, y), (W, y)], fill=(8, 11, 26, int(150 * (1 - abs(y - 335) / 135))))
for txt, font, size, y, col in [("Скоро: Серия 2", NUN, 34, 255, (230, 230, 240)), ("Вася против нового жильца", YES, 64, 305, (255, 246, 236))]:
    f = ImageFont.truetype(font, size); tw = d.textlength(txt, font=f); x0 = (W - tw) / 2
    d.text((x0 + 2, y + 3), txt, font=f, fill=(0, 0, 0, 170)); d.text((x0, y), txt, font=f, fill=col + (255,))
im.save(f"{O}/ov_next.png")
NX = 3.5
run("-ss", "4.88", "-i", f"{E}/v/K9306.mp4", "-loop", "1", "-i", f"{O}/ov_next.png", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
    "-filter_complex", f"[0:v]trim=0:{NX},setpts=PTS-STARTPTS,scale={W}:{H},fps=24,format=yuv420p,tpad=stop_mode=clone:stop_duration=2,trim=0:{NX}[b];[1:v]format=rgba,fade=in:st=0.2:d=0.6:alpha=1,trim=0:{NX}[t];[b][t]overlay=0:0:shortest=1,fade=out:st={NX-1.0}:d=1.0[v]",
    "-map", "[v]", "-map", "2:a", "-t", f"{NX}", "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-c:a", "aac", "-b:a", "192k", f"{O}/next.mp4")
# Финальная музыка: песня с начала фразы (95.0 с) до конца фразы (114.0 с), тихо под рассказчика, громче на заставке
S0, S1 = 95.0, 114.0
# 3) склейка
parts = [f"{O}/p1.mp4", f"{E}/yong_ep1_part2.mp4", f"{E}/yong_ep1_part3.mp4", f"{O}/fin.mp4", f"{O}/hook.mp4", f"{O}/next.mp4"]
n = len(parts); ins = sum([["-i", p] for p in parts], [])
fc = "".join(f"[{i}:v:0]setsar=1,fps=24,format=yuv420p[v{i}];[{i}:a:0]aresample=48000,aformat=channel_layouts=stereo[a{i}];" for i in range(n))
fc += "".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][a]"
run(*ins, "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "21", "-preset", "slow", "-c:a", "aac", "-b:a", "192k", f"{O}/cat.mp4")
cs = sum(dur(p) for p in parts[:3])          # начало заставки
t0 = cs + CL - 1.2 - (S1 - S0)                 # песня кончается за 1.2 с до конца, дальше хвост
up0, up1 = cs - t0 - 0.8, cs - t0 + 0.6       # рост громкости вокруг начала заставки (время песни)
vol = f"if(lt(t,{up0:.2f}),0.30,if(lt(t,{up1:.2f}),0.30+0.55*(t-{up0:.2f})/{up1-up0:.2f},0.85))"
afc = (f"[1:a]atrim={S0}:{S1},asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo,"
       f"volume='{vol}':eval=frame,afade=in:st=0:d=1.5,afade=out:st={S1-S0-1.8:.2f}:d=1.8,aecho=0.8:0.6:120|260:0.25|0.15,"
       f"apad=pad_dur=2,adelay={int(t0*1000)}|{int(t0*1000)}[m];[0:a][m]amix=inputs=2:duration=first:normalize=0[a]")
run("-i", f"{O}/cat.mp4", "-i", f"{E}/song.mp3", "-filter_complex", afc, "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", f"{E}/yong_ep1_full.mp4")
print("full", round(dur(f"{E}/yong_ep1_full.mp4"), 2), [round(dur(p), 2) for p in parts])
