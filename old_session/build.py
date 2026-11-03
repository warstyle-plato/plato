"""Сборка первых минут серии 1 «Йонг летит домой».
Запуск: python3 build.py <каталог ep1>
"""
import json, os, shutil, subprocess, sys
from PIL import Image, ImageDraw, ImageFont

E = sys.argv[1]
Y = os.path.dirname(E)                      # .../scratchpad/yong
PART = os.environ.get("PART", "1")
OUT = f"{E}/out" if PART == "1" else f"{E}/out{PART}"; os.makedirs(OUT, exist_ok=True)
W, H, FPS = 1280, 720, 24
YES = f"{Y}/fonts/Yeseva.ttf"; NUN = f"{Y}/fonts/Nunito.ttf"

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print(" ".join(cmd)); print(r.stderr[-2000:]); sys.exit(1)

def dur(p):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p]).decode())

# ---------- текстовые карточки ----------
def text_png(path, lines, bg=None, shade=True):
    im = Image.open(bg).convert("RGB").resize((W, H)) if bg else Image.new("RGB", (W, H), (10, 12, 30))
    im = im.convert("RGBA")
    if shade:
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0)); od = ImageDraw.Draw(ov)
        for y in range(0, 380): od.line([(0, y), (W, y)], fill=(8, 11, 26, int(210 * (1 - y / 380))))
        im = Image.alpha_composite(im, ov)
    d = ImageDraw.Draw(im)
    for txt, font, size, y, col in lines:
        f = ImageFont.truetype(font, size); tw = d.textlength(txt, font=f)
        d.text(((W - tw) / 2 + 2, y + 3), txt, font=f, fill=(0, 0, 0, 160))
        d.text(((W - tw) / 2, y), txt, font=f, fill=col)
    im.convert("RGB").save(path)

CREAM, PEACH, SOFT = (255, 246, 236), (242, 216, 190), (230, 230, 240)
text_png(f"{OUT}/t_open.png", [("Йонг", YES, 130, 60, CREAM), ("Маленькая собака большого мира", YES, 46, 215, PEACH)], bg=f"{Y}/img/poster.png")
text_png(f"{OUT}/t_ep.png", [("Серия 1", NUN, 34, 250, SOFT), ("Йонг летит домой", YES, 84, 300, CREAM)], bg=None, shade=False)
text_png(f"{OUT}/t_end.png", [("Продолжение следует…", YES, 64, 300, CREAM)], bg=None, shade=False)

def overlay_png(path, lines, band, cx=None):
    """Прозрачная надпись поверх видео: band = 'top' (затемнение сверху) или 'mid' (полупрозрачная полоса)."""
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    if band == "top":
        for y in range(0, 360): d.line([(0, y), (W, y)], fill=(8, 11, 26, int(200 * (1 - y / 360))))
    else:
        for y in range(200, 470): d.line([(0, y), (W, y)], fill=(8, 11, 26, int(150 * (1 - abs(y - 335) / 135))))
    for txt, font, size, y, col in lines:
        f = ImageFont.truetype(font, size); tw = d.textlength(txt, font=f)
        x0 = (W - tw) / 2 if cx is None else cx - tw / 2
        d.text((x0 + 2, y + 3), txt, font=f, fill=(0, 0, 0, 170))
        d.text((x0, y), txt, font=f, fill=col + (255,))
    im.save(path)

overlay_png(f"{OUT}/ov_open.png", [("Йонг", YES, 130, 40, CREAM), ("Маленькая собака большого мира", YES, 34, 185, PEACH)], "top", cx=900)
overlay_png(f"{OUT}/ov_ep.png", [("Серия 1", NUN, 34, 250, SOFT), ("Йонг летит домой", YES, 84, 300, CREAM)], "mid")
overlay_png(f"{OUT}/ov_end.png", [("Продолжение следует…", YES, 64, 300, CREAM)], "mid")
OVERLAY = {"end": (f"{OUT}/ov_end.png", 0.3)}
def caption_png(path, title, sub):
    """Надпись места внизу слева: крупно город, мельче пояснение."""
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    for y in range(H - 200, H): d.line([(0, y), (W, y)], fill=(8, 11, 26, int(150 * (y - (H - 200)) / 200)))
    for txt, font, size, y, col in [(title, YES, 64, H - 150, CREAM), (sub, NUN, 30, H - 72, PEACH)]:
        f = ImageFont.truetype(font, size)
        d.text((62, y + 3), txt, font=f, fill=(0, 0, 0, 170)); d.text((60, y), txt, font=f, fill=col + (255,))
    im.save(path)
caption_png(f"{OUT}/cap_msk.png", "Москва", "Дом Жени")
caption_png(f"{OUT}/cap_seoul.png", "Сеул", "Южная Корея, за 6 600 км от Москвы")
CAPTION = {"s1": (f"{OUT}/cap_msk.png", 0.6, 5.2), "s8a": (f"{OUT}/cap_seoul.png", 0.6, 5.0)}

# ---------- сегменты ----------
V = f"{E}/v"; F = f"{E}/f"; A = f"{E}/a"; T = f"{Y}/vid"; I = f"{Y}/img"
# (id, тип, источник, базовая длительность, реплики [(файл, старт)], шумовой слой, движение для кадра)
SEG = [
  # источник: файл или список настоящих разных планов [(файл, с какой секунды, секунд)]; L* — кадры с синхронной артикуляцией, реплика стартует вместе с планом
  ("o1", "vid", f"{OUT}/opening.mp4", 31.2, [], None, None),
  # Сцена 1
  ("s1", "vid", [(f"{V}/1101.mp4", 0.0, 4.4), (f"{V}/1102.mp4", 0.3, 4.0)], 8.0, [("N1", 0.8)], "room", None),
  ("s2", "vid", [(f"{V}/202.mp4", 0.0, 3.0), (f"{V}/1103.mp4", 0.3, 3.0)], 5.0, [("N2", 0.5)], "room", None),
  ("s3", "vid", [(f"{V}/303.mp4", 0.0, 2.0), (f"{V}/S501.mp4", 0.0, 0.8), (f"{V}/303.mp4", 1.8, 4.3)], 0, [("Z1", 2.0)], "room", None),
  ("s4", "vid", [(f"{E}/up8/card_still.png", 0.0, 1.6), (f"{V}/S502.mp4", 0.0, 3.05)], 0, [("Z2", 1.6)], "room", None),
  ("s5", "vid", [(f"{E}/up8/card_still.png", 0.0, 1.5), (f"{V}/S503.mp4", 0.0, 2.75), (f"{V}/U2.mp4", 0.5, 4.5), (f"{V}/CARDV.mp4", 6.6, 2.4), (f"{V}/TYPE.mp4", 0.3, 2.0), (f"{E}/up8/n_transl.png", 0.0, 1.5)], 0, [("Z3", 1.5), ("Z4", 6.65), ("SKEYS", 11.15)], "room", None),
  ("s6", "vid", [(f"{V}/S505.mp4", 0.0, 4.05), (f"{V}/1103.mp4", 2.0, 1.4)], 0, [("Z5", 0.0)], "room", None),
  ("s7", "vid", [(f"{V}/S506.mp4", 0.0, 3.65)], 0, [("Z6", 0.0)], "room", None),
  ("s7b", "vid", [(f"{V}/1112.mp4", 0.3, 5.0), (f"{V}/302.mp4", 2.0, 5.1)], 10.1, [("N3", 0.5)], "room", None),
  # Сцена 2
  ("s8a", "vid", [(f"{V}/D9002c.mp4", 0.0, 5.9)], 0, [("N2b", 0.5)], "street_low", None),   # Сеул: Херра спит с игрушечным дракончиком
  ("s8", "vid", [(f"{V}/M312gx.mp4", 0.0, 7.45)], 0, [("H1", 1.5), ("H2a", 3.45), ("H2b", 4.25)], "street_low", None),
  ("s8c", "vid", [(f"{V}/U1.mp4", 0.0, 4.6)], 0, [], "street_low", None),   # мордочка заглядывает в переноску (изнутри)
  ("s8b", "vid", [(f"{V}/BREED4.mp4", 0.0, 6.4)], 0, [], "room", None),   # заводчица сажает Херру в переноску
  ("s9", "vid", [(f"{V}/M313.mp4", 0.0, 1.6), (f"{V}/310s.mp4", 0.0, 2.75)], 0, [("H3", 0.0)], "street_low", None),
  ("s10", "vid", [(f"{V}/310s.mp4", 2.75, 7.6), (f"{V}/2105t.mp4", 0.0, 4.11)], 0, [("N4", 0.3)], "street", None),
  # Сцена 3
  ("s11", "vid", [(f"{V}/N316s.mp4", 0.0, 4.83)], 0, [("H6", 0.0)], "airport", None),
  ("s12", "vid", [(f"{V}/612.mp4", 0.0, 2.4), (f"{V}/Q612s.mp4", 0.0, 5.05)], 0, [("BUMP", 2.1), ("H4", 2.4)], "airport", None),   # тележка задевает переноску, потом «Осторожно!»
  ("s13", "vid", [(f"{V}/1109.mp4", 1.85, 3.6), (f"{V}/M315.mp4", 2.4, 4.57)], 0, [("H5", 1.2)], "airport", None),
  ("s14a", "vid", [(f"{V}/2105t.mp4", 3.0, 4.6), (f"{V}/1109.mp4", 0.3, 3.2)], 0, [("N5", 0.3)], "airport", None),
  ("s14b", "vid", [(f"{V}/M314.mp4", 0.0, 4.15), (f"{V}/2105t.mp4", 5.3, 1.2), (f"{V}/M318.mp4", 0.0, 2.95)], 0, [("H7", 0.0), ("H8", 5.35)], "airport", None),
  # Сцена 4
  ("s15", "vid", [(f"{V}/M619g.mp4", 0.0, 3.45)], 0, [("H9", 0.0)], "takeoff", None),
  ("s15b", "vid", [(f"{V}/2106v.mp4", 0.8, 3.0)], 0, [], "takeoff", None),   # Херра пытается открыть решётку
  ("s16", "vid", [(f"{V}/N620g.mp4", 0.0, 4.65)], 0, [("H10", 0.0)], "takeoff", None),
  ("s17", "vid", [(f"{V}/2113.mp4", 0.0, 2.0), (f"{V}/2120s.mp4", 0.0, 4.2), (f"{V}/Q621bs.mp4", 0.0, 4.65)], 0, [("SCHIME", 0.3), ("ST1", 2.15), ("H11", 6.2)], "cabin", None),
  ("s17b", "vid", [(f"{V}/2113.mp4", 2.5, 2.5), (f"{V}/2109s.mp4", 0.0, 4.8)], 0, [("N6", 0.4)], "cabin", None),
  ("s18", "vid", [(f"{V}/2109s.mp4", 3.3, 1.74), (f"{V}/M623sb.mp4", 1.74, 7.85)], 0, [("H13a", 0.0), ("H13b", 5.3)], "cabin", None),
  # Сцена 5
  ("s19", "vid", [(f"{V}/2123s.mp4", 0.0, 3.2)], 0, [], "cabin", None),
  ("s20", "vid", [(f"{V}/220.mp4", 0.0, 1), (f"{V}/1111.mp4", 0.3, 1), (f"{V}/220.mp4", 6.5, 1)], 10.0, [("D1", 1.5), ("D2", 3.6), ("D3", 6.4)], "dream", None),
  ("s21", "vid", [(f"{V}/2123s.mp4", 0.8, 4.45)], 0, [("H16", 0.0)], "cabin", None),
  ("s21b", "vid", [(f"{V}/2113.mp4", 0.0, 4.0), (f"{V}/1112.mp4", 1.6, 3.6), (f"{V}/1102.mp4", 0.5, 4.2)], 0, [("N7", 0.5)], "cabin", None),
  ("end", "vid", f"{V}/302.mp4", 3.0, [], None, None),
]
if PART != "1":   # другие части серии: сегменты из seg<PART>.py
    exec(open(f"{E}/seg{PART}.py").read())
# Закадровые планы части 1 — медленнее камера под спокойный голос рассказчика (замечание 0:32)
SLOWMO = {k: 1.45 for k in ("s1", "s2", "s7b", "s10", "s14a", "s17b", "s21b")} if PART == "1" else {}
if PART == "1": SLOWMO["s8a"] = 1.48   # дракончик: берём только чистые 4 с (дальше уши меняются)
if PART != "1" and "SLOWMO_P" in globals(): SLOWMO = SLOWMO_P
def _mi(sl): return f",minterpolate=fps={FPS}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1" if sl > 1.12 else ""

# реплики сна — нарезка одного файла
run(["ffmpeg", "-y", "-v", "error", "-i", f"{A}/DREAM.mp3", "-t", "0.9", f"{A}/D1.mp3"])
if os.path.exists(f"{A}/H15.mp3"):   # реплика Херры во сне — новым голосом, если он уже записан
    run(["ffmpeg", "-y", "-v", "error", "-i", f"{A}/H15.mp3", f"{A}/D2.mp3"])
else:
    run(["ffmpeg", "-y", "-v", "error", "-ss", "1.0", "-to", "2.95", "-i", f"{A}/DREAM.mp3", f"{A}/D2.mp3"])
run(["ffmpeg", "-y", "-v", "error", "-ss", "3.05", "-i", f"{A}/DREAM.mp3", f"{A}/D3.mp3"])

# итоговые длительности
plan, t = [], 0.0
for sid, kind, src, base, cues, amb, mv in SEG:
    if kind == "vid" and isinstance(src, list):
        src = [(f, ss, w) if os.path.exists(f) else (f"{F}/{int(os.path.basename(f).split('.')[0]) - 100}.png", 0.0, w) for f, ss, w in src]
    elif kind == "vid" and not os.path.exists(src):   # черновой прогон: видео ещё не готово — берём его стартовый кадр
        num = int(os.path.basename(src).split(".")[0]) - 100
        kind, src, mv = "still", f"{F}/{num}.png", "in"
        print("placeholder", sid)
    if not base and isinstance(src, list): base = sum(w for _, _, w in src)
    need = max([st + dur(f"{A}/{c}.mp3") for c, st in cues if c not in ("VSTING",)] + [0]) + 0.05   # музыкальный акцент может звучать через склейку
    if need > base + 0.01: print(f"ВНИМАНИЕ: {sid} реплики длиннее планов на {need - base:.2f} с — планы растянутся, синхрон сдвинется")
    d = round(max(base, need) * FPS) / FPS   # длительность кратна кадру: иначе видео отстаёт от звука по ходу серии
    plan.append(dict(id=sid, kind=kind, src=src, dur=d, cues=cues, amb=amb, mv=mv, start=round(t, 2)))
    t += d
TOTAL = t
json.dump(plan, open(f"{OUT}/plan.json", "w"), ensure_ascii=False, indent=1)
print("total", round(TOTAL, 1))

# ---------- видео по сегментам ----------

MAXSHOT = 3.0
def split_long(o, d, sid):
    """План длиннее 3 с режется на куски по 2.2–2.8 с: общий план с наездом чередуется с крупным."""
    if d <= MAXSHOT or sid.startswith("o"):
        return
    k = int(d // 2.6) + (1 if d % 2.6 > 0.4 else 0)
    k = max(k, 2); L = d / k
    subs = []
    for i in range(k):
        nn = int(round(L * FPS)); so = f"{o}.{i}.mp4"
        if i % 2 == 0:
            z0, z1, cy = 1.0, 1.07, 0.5
        else:
            z0, z1, cy = 1.30, 1.38, 0.42
        zp = (f"scale={W*2}:{H*2},zoompan=z='{z0}+({z1}-{z0})*on/{nn}':x='iw/2-(iw/zoom/2)':"
              f"y='(ih-ih/zoom)*{cy}':d=1:s={W}x{H}:fps={FPS},format=yuv420p")
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{i*L:.3f}", "-i", o, "-vf", zp, "-frames:v", str(nn),
             "-c:v", "libx264", "-crf", "18", "-preset", "medium", so])
        subs.append(so)
    with open(o + ".txt", "w") as fh:
        for so in subs: fh.write(f"file '{so}'\n")
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", o + ".txt", "-c", "copy", o + ".cat.mp4"])
    os.replace(o + ".cat.mp4", o)

SC = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
SHIFT = json.load(open(f"{E}/cs4/shift.json")) if os.path.exists(f"{E}/cs4/shift.json") else {}
# Подкраска: в домашних планах шерсть Йонг выходит светло-бежевой — чуть теплее и насыщеннее, к абрикосовому цвету остальных планов
GRADE = {"M4902","M4903","M4905","M4906","M4908","M4911","M6003","M6105","M6109","M6111","M6118","M6120","M6122","M6124","M4614","M4905z","M4905c"}
def grade(f):
    return ",eq=saturation=1.12,colorbalance=rm=0.035:bm=-0.035" if os.path.basename(f).split(".")[0] in GRADE else ""
parts = []
ONLY = set(filter(None, os.environ.get("ONLY", "").split(",")))   # пересобрать только эти сцены, прочие взять готовыми
for p in plan:
    o = f"{OUT}/{p['id']}.mp4"; d = p["dur"]; n = int(round(d * FPS))
    if ONLY and p["id"] not in ONLY and os.path.exists(o + ".raw.mp4"):
        shutil.copy(o + ".raw.mp4", o); parts.append(o); continue
    if p["kind"] == "still":
        mv = p["mv"]
        if mv == "pan":
            z = "1.12"; x = f"(iw-iw/zoom)*on/{n}"; y = "ih/2-(ih/zoom/2)"
        elif mv == "out":
            z = f"1.12-0.12*on/{n}"; x = "iw/2-(iw/zoom/2)"; y = "ih/2-(ih/zoom/2)"
        elif mv == "in":
            z = f"1+0.10*on/{n}"; x = "iw/2-(iw/zoom/2)"; y = "ih/2-(ih/zoom/2)"
        else:
            z = "1"; x = "0"; y = "0"
        vf = f"scale=2560:1440:force_original_aspect_ratio=increase,crop=2560:1440,zoompan=z='{z}':x='{x}':y='{y}':d={n}:s={W}x{H}:fps={FPS},format=yuv420p"
        run(["ffmpeg", "-y", "-v", "error", "-i", p["src"], "-vf", vf, "-frames:v", str(n), "-c:v", "libx264", "-crf", "18", "-preset", "medium", o])
    elif isinstance(p["src"], list):
        tot = sum(w for _, _, w in p["src"]); subs = []; acc = 0.0; fr0 = 0
        for i, (f, ss, w) in enumerate(p["src"]):
            acc += w; fr1 = int(round(d * acc / tot * FPS)); nn = fr1 - fr0; fr0 = fr1   # накопительное округление: сумма кадров = длине плана
            Ls = nn / FPS; so = f"{o}.{i}.mp4"
            if f.endswith(".png"):
                vf = f"scale=2560:1440:force_original_aspect_ratio=increase,crop=2560:1440,zoompan=z='1+0.08*on/{nn}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={nn}:s={W}x{H}:fps={FPS},format=yuv420p"
                run(["ffmpeg", "-y", "-v", "error", "-i", f, "-vf", vf, "-frames:v", str(nn), "-c:v", "libx264", "-crf", "18", "-preset", "medium", so])
            else:
                shv = SHIFT.get(os.path.basename(f)[:-4], 0.0)          # сдвиг под задержку губ модели синхрона
                ss = ss + max(shv, 0.0); pre = max(-shv, 0.0)
                avail = max(0.5, dur(f) - ss)
                slow = max(min(max(Ls / avail, 1.0), 1.35), SLOWMO.get(p["id"], 1.0)); frz = max(0, Ls - avail * slow)
                if os.path.basename(f)[:-4] in SHIFT:   # реплики не растягивать: иначе губы уплывут от голоса
                    slow = 1.0; frz = max(0, Ls - pre - avail)
                if frz > 0.3: print(f"ВНИМАНИЕ: {p['id']}[{i}] стоит {frz:.1f} с")
                vf = f"{SC}{grade(f)},fps={FPS},setpts={slow}*PTS{_mi(slow)},tpad=start_mode=clone:start_duration={pre}:stop_mode=clone:stop_duration={frz + 1.0},setpts=PTS-STARTPTS,format=yuv420p"
                run(["ffmpeg", "-y", "-v", "error", "-ss", f"{ss:.2f}", "-i", f, "-vf", vf, "-an", "-frames:v", str(nn), "-c:v", "libx264", "-crf", "18", "-preset", "medium", so])
            subs.append(so)
        with open(o + ".txt", "w") as fh:
            for so in subs: fh.write(f"file '{so}'\n")
        run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", o + ".txt", "-c", "copy", o])
    else:
        L = dur(p["src"])
        slow = max(min(max(d / L, 1.0), 1.35), SLOWMO.get(p["id"], 1.0))
        freeze = max(0, d - L * slow)
        if freeze > 0.3:
            print(f"ВНИМАНИЕ: {p['id']} стоит неподвижно {freeze:.1f} с")
        vf = f"{SC}{grade(p['src'])},fps={FPS},setpts={slow}*PTS{_mi(slow)},tpad=stop_mode=clone:stop_duration={freeze + 1.0},setpts=PTS-STARTPTS,format=yuv420p"
        if p["id"] in OVERLAY:
            ovp, t0 = OVERLAY[p["id"]]
            fc = f"[0:v]{vf}[b];[1:v]format=rgba,fade=in:st={t0}:d=0.8:alpha=1[t];[b][t]overlay=0:0,format=yuv420p"
            run(["ffmpeg", "-y", "-v", "error", "-i", p["src"], "-loop", "1", "-t", str(d + 1), "-i", ovp, "-filter_complex", fc, "-an", "-frames:v", str(n), "-c:v", "libx264", "-crf", "18", "-preset", "medium", o])
        else:
            run(["ffmpeg", "-y", "-v", "error", "-i", p["src"], "-vf", vf, "-an", "-frames:v", str(n), "-c:v", "libx264", "-crf", "18", "-preset", "medium", o])
    if p["id"] in CAPTION:   # надпись места поверх готового плана: появляется и гаснет
        cp, t0, t1 = CAPTION[p["id"]]; shutil.move(o, o + ".nocap.mp4")
        fc = f"[1:v]format=rgba,fade=in:st={t0}:d=0.6:alpha=1,fade=out:st={t1 - 0.6}:d=0.6:alpha=1[t];[0:v][t]overlay=0:0:shortest=1,format=yuv420p"
        run(["ffmpeg", "-y", "-v", "error", "-i", o + ".nocap.mp4", "-loop", "1", "-t", str(d + 1), "-i", cp, "-filter_complex", fc, "-an", "-frames:v", str(n), "-c:v", "libx264", "-crf", "18", "-preset", "medium", o])
    shutil.copy(o, o + ".raw.mp4")
    parts.append(o)

# затемнения на сменах сцен
FADE_IN = {"o1", "s1", "s8a", "s11", "s15", "s19", "end"}
FADE_OUT = {"o1", "s7b", "s10", "s14b", "s18", "s21b", "end"}
if PART != "1": FADE_IN, FADE_OUT = FADE_IN_P, FADE_OUT_P
for p, o in zip(plan, parts):
    fl = []
    if p["id"] in FADE_IN: fl.append("fade=in:st=0:d=0.6")
    if p["id"] in FADE_OUT: fl.append(f"fade=out:st={p['dur'] - 0.7}:d=0.7")
    if fl:
        run(["ffmpeg", "-y", "-v", "error", "-i", o, "-vf", ",".join(fl), "-c:v", "libx264", "-crf", "18", "-preset", "medium", o + ".f.mp4"])
        os.replace(o + ".f.mp4", o)

XFADE = {"s4"}   # растворение из последнего кадра предыдущей сцены
for k, (p, o) in enumerate(zip(plan, parts)):
    if p["id"] in XFADE and k > 0:
        lf = o + ".prev.png"
        run(["ffmpeg", "-y", "-v", "error", "-sseof", "-0.05", "-i", parts[k-1], "-frames:v", "1", "-update", "1", lf])
        run(["ffmpeg", "-y", "-v", "error", "-i", o, "-loop", "1", "-i", lf, "-filter_complex",
             "[1:v]format=rgba,fade=out:st=0:d=0.6:alpha=1,trim=0:0.7[t];[0:v][t]overlay=0:0:eof_action=pass,format=yuv420p",
             "-c:v", "libx264", "-crf", "18", "-preset", "medium", o + ".x.mp4"])
        os.replace(o + ".x.mp4", o)

with open(f"{OUT}/list.txt", "w") as fh:
    for o in parts: fh.write(f"file '{o}'\n")
run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", f"{OUT}/list.txt", "-c", "copy", f"{OUT}/video.mp4"])

# ---------- звук ----------
# шумы места выровнены по громкости (sfx_norm, -25 LUFS), здесь — итоговый уровень под речью
AMB = {"room": (f"{E}/sfx_norm/room.mp3", 0.25), "street": (f"{E}/sfx_norm/street.mp3", 0.6), "street_low": (f"{E}/sfx_norm/street.mp3", 0.4),
       "airport": (f"{E}/sfx_norm/airport.mp3", 0.55), "cabin": (f"{E}/sfx_norm/cabin.mp3", 0.5), "takeoff": (f"{E}/sfx_norm/takeoff.mp3", 0.75),
       "dream": (f"{E}/sfx_norm/dream.mp3", 0.5), "car": (f"{E}/sfx_norm/car.mp3", 0.5), "snow": (f"{E}/sfx_norm/snow.mp3", 0.35)}
inputs, filt, labels = [], [], []
def add(path, start, vol, length=None, loop=False, fade=0.4, extra=""):
    i = len(labels)
    inputs.extend((["-stream_loop", "-1"] if loop else []) + ["-i", path])
    chain = f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo"
    if length is not None:
        chain += f",atrim=0:{length},afade=t=in:d={fade},afade=t=out:st={max(0, length - fade)}:d={fade}"
    chain += f"{extra},volume={vol},adelay={int(start * 1000)}|{int(start * 1000)}[x{i}]"
    filt.append(chain); labels.append(f"[x{i}]")

opening = sum(p["dur"] for p in plan if p["id"].startswith("o"))
if opening > 0: add(f"{E}/song.mp3", 0, 0.9, length=opening, fade=1.2)
# приглушение фоновой музыки (например, на появление Васи): (начало, конец) в секундах части
DUCK = list(globals().get("DUCK_P", [])) if PART != "1" else []
# музыка точечно: где улица, аэропорт, взлёт, машина или снег — звучит шум места, фоновая мелодия уходит
NOMUSIC = {"street", "street_low", "airport", "takeoff"}
# музыка только в ключевых местах: под рассказчиком, во сне и при встрече; в диалогах — только шум места
MUSIC_ON = {"s20", "p6b"}
def _music(p): return (p["id"] in MUSIC_ON or any(c.startswith("N") for c, _ in p["cues"])) and p["amb"] not in NOMUSIC
HALF = []
for p in plan:
    if p["amb"] not in NOMUSIC and not _music(p):
        a0, b0 = p["start"], p["start"] + p["dur"]
        if HALF and abs(HALF[-1][1] - a0) < 0.05: HALF[-1] = (HALF[-1][0], b0)
        else: HALF.append((a0, b0))
for p in plan:
    if p["amb"] in NOMUSIC:
        a0, b0 = p["start"], p["start"] + p["dur"]
        if DUCK and abs(DUCK[-1][1] - a0) < 0.05: DUCK[-1] = (DUCK[-1][0], b0)
        else: DUCK.append((a0, b0))
DUCK.sort()
duck = "".join(f",volume='1-clip((t-{a - opening:.2f})/1.0,0,1)+clip((t-{b - opening + 1.0:.2f})/1.5,0,1)':eval=frame" for a, b in DUCK)
duck += "".join(f",volume='1-0.55*clip((t-{a - opening:.2f})/1.0,0,1)+0.55*clip((t-{b - opening + 0.5:.2f})/1.5,0,1)':eval=frame" for a, b in HALF)
add(f"{E}/underscore.mp3", opening, 0.16, length=TOTAL - opening - 4, loop=True, fade=2.0, extra=duck)
# шумовые слои: склеиваем соседние сегменты с одинаковым слоем
runs = []
for p in plan:
    if p["amb"] and runs and runs[-1][0] == p["amb"] and abs(runs[-1][1] + runs[-1][2] - p["start"]) < 0.01:
        runs[-1][2] += p["dur"]
    elif p["amb"]:
        runs.append([p["amb"], p["start"], p["dur"]])
for name, st, ln in runs:
    path, vol = AMB[name]
    add(path, st, vol, length=ln, loop=name not in ("takeoff", "dream"), fade=0.8)
for p in plan:
    for c, st in p["cues"]:
        add(f"{A}/{c}.mp3", p["start"] + st, 1.0)
filt.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0,alimiter=limit=0.95,apad,atrim=0:{TOTAL}[a]")
run(["ffmpeg", "-y", "-v", "error"] + inputs + ["-filter_complex", ";".join(filt), "-map", "[a]", "-c:a", "aac", "-b:a", "192k", f"{OUT}/audio.m4a"])
run(["ffmpeg", "-y", "-v", "error", "-i", f"{OUT}/video.mp4", "-i", f"{OUT}/audio.m4a", "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-crf", "22", "-preset", "slow", "-c:a", "copy", "-shortest", "-movflags", "+faststart", f"{E}/yong_ep1_part{PART}.mp4"])
print("done", dur(f"{E}/yong_ep1_part{PART}.mp4"))
