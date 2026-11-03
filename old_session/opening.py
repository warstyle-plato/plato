"""Заставка под песню: склейка по долям такта (129 BPM), 31.2 с.
Запуск: python3 opening.py <каталог ep1>  -> out/opening.mp4 (без звука)
"""
import os, subprocess, sys
from PIL import Image, ImageDraw, ImageFont

E = sys.argv[1]; Y = os.path.dirname(E); OUT = f"{E}/out"; os.makedirs(OUT, exist_ok=True)
V = f"{E}/v"; T = f"{Y}/vid"
W, H, FPS = 1280, 720, 24
BEAT = 60 / 129.2
YES = f"{Y}/fonts/Yeseva.ttf"; NUN = f"{Y}/fonts/Nunito.ttf"

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode: print(r.stderr[-1500:]); sys.exit(1)

def dur(p):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p]).decode())

def title(path, lines):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    for y in range(180, 520): d.line([(0, y), (W, y)], fill=(8, 11, 26, int(150 * (1 - abs(y - 350) / 170))))
    for txt, font, size, y, col in lines:
        f = ImageFont.truetype(font, size); tw = d.textlength(txt, font=f)
        d.text(((W - tw) / 2 + 3, y + 4), txt, font=f, fill=(0, 0, 0, 180)); d.text(((W - tw) / 2, y), txt, font=f, fill=col)
    im.save(path)

title(f"{OUT}/op_title.png", [("Йонг", YES, 150, 215, (255, 246, 236, 255)), ("Маленькая собака большого мира", YES, 44, 395, (242, 216, 190, 255))])
title(f"{OUT}/op_ep.png", [("Серия 1", NUN, 36, 255, (230, 230, 240, 255)), ("Йонг летит домой", YES, 88, 300, (255, 246, 236, 255))])

# (клип, с какой секунды клипа, долей такта, скорость, наезд камеры от->до, надпись)
SHOTS = [
    (f"{V}/301.mp4", 0.0, 4, 1.6, (1.0, 1.0), None),     # дом, камера плывёт
    (f"{V}/901.mp4", 0.5, 3, 1.2, (1.0, 1.0), None),     # Херра несётся на камеру
    (f"{V}/902.mp4", 0.5, 4, 1.15, (1.0, 1.0), None),     # «солнечный зайчик»
    (f"{V}/903.mp4", 0.5, 4, 1.0, (1.0, 1.0), None),     # «вкрадчивый взгляд»
    (f"{V}/904.mp4", 0.5, 4, 1.1, (1.0, 1.0), None),    # «носик размером с пальчик»
    (f"{V}/1104.mp4", 0.5, 2, 1.3, (1.0, 1.0), None),
    (f"{V}/905.mp4", 0.5, 4, 1.2, (1.0, 1.0), None),      # «характер как у сотни солдат»
    (f"{V}/1109.mp4", 0.5, 2, 1.0, (1.0, 1.0), None),
    (f"{V}/220.mp4", 2.0, 3, 1.4, (1.0, 1.0), None),
    (f"{V}/2113.mp4", 0.5, 3, 1.4, (1.0, 1.0), None),
    (f"{V}/700.mp4", 2.0, 5, 1.2, (1.0, 1.0), "op_title.png"),
    (f"{V}/909.mp4", 0.3, 4, 1.2, (1.0, 1.0), None),    # «Йонг, а Йонг?»
    (f"{V}/906.mp4", 0.5, 5, 1.2, (1.0, 1.0), None),     # «пинг-понг»
    (f"{V}/2106.mp4", 0.6, 4, 1.0, (1.0, 1.0), None),      # «Йонг, а Йонг!»
    (f"{V}/2109.mp4", 0.5, 3, 1.4, (1.0, 1.0), None),     # «поедем…»
    (f"{V}/310.mp4", 2.0, 2, 1.6, (1.0, 1.0), None),
    (f"{V}/907.mp4", 0.3, 5, 1.1, (1.0, 1.0), None),      # «нет-нет-нет»
    (f"{V}/908.mp4", 0.3, 6, 1.0, (1.0, 1.0), "op_ep.png"),  # «ты маленький человек» + название серии
]

parts = []
for i, (src, ss, beats, speed, (z0, z1), ov) in enumerate(SHOTS):
    d = beats * BEAT; n = int(round(d * FPS)); o = f"{OUT}/op_{i:02d}.mp4"
    need = d * speed; L = dur(src)
    ss = max(0.0, min(ss, L - need - 0.05))
    zp = f"zoompan=z='{z0}+({z1}-{z0})*on/{n}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS}"
    vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setpts=PTS/{speed},fps={FPS}" if z0 == z1 else f"scale={W*2}:{H*2}:force_original_aspect_ratio=increase,crop={W*2}:{H*2},setpts=PTS/{speed},fps={FPS},{zp}"
    if ov:
        fc = f"[0:v]{vf}[b];[1:v]format=rgba,fade=in:st=0.2:d=0.4:alpha=1[t];[b][t]overlay=0:0,format=yuv420p"
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{ss:.2f}", "-i", src, "-loop", "1", "-t", f"{d + 1:.2f}", "-i", f"{OUT}/{ov}",
             "-filter_complex", fc, "-an", "-frames:v", str(n), "-c:v", "libx264", "-crf", "18", "-preset", "medium", o])
    else:
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{ss:.2f}", "-i", src, "-vf", vf + ",format=yuv420p", "-an",
             "-frames:v", str(n), "-c:v", "libx264", "-crf", "18", "-preset", "medium", o])
    parts.append(o)

with open(f"{OUT}/op_list.txt", "w") as fh:
    for o in parts: fh.write(f"file '{o}'\n")
run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", f"{OUT}/op_list.txt",
     "-vf", "fade=in:st=0:d=0.4", "-c:v", "libx264", "-crf", "18", "-preset", "medium", f"{OUT}/opening.mp4"])
print("opening", round(dur(f"{OUT}/opening.mp4"), 2), "shots", len(parts))
