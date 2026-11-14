# derive web-sized mascot animations from assets/animations (the source of truth)
import sys
from PIL import Image
SRC, OUT = sys.argv[1], sys.argv[2]
H = int(sys.argv[3]) if len(sys.argv) > 3 else 240
Q = int(sys.argv[4]) if len(sys.argv) > 4 else 72
BOX = {'idle': (88, 0, 430, 600), 'searching': (88, 0, 430, 600), 'thinking': (88, 0, 430, 600), 'found-it': (12, 0, 430, 600)}
STEP = {'idle': 2, 'searching': 2, 'thinking': 2, 'found-it': 1}
for n, box in BOX.items():
    im = Image.open(f'{SRC}/monkey-{n}.webp')
    frames, durs = [], []
    for i in range(im.n_frames):
        im.seek(i)
        f = im.convert('RGBA').crop(box)
        w = round(f.width * H / f.height)
        frames.append(f.resize((w, H), Image.LANCZOS)); durs.append(im.info.get('duration') or 50)
    durs = [d if d >= 20 else 50 for d in durs]
    k = STEP[n]
    frames = frames[::k]; durs = [sum(durs[i:i + k]) for i in range(0, len(durs), k)]
    once = n == 'found-it'
    kw = dict(save_all=True, append_images=frames[1:], duration=durs, loop=1 if once else 0)
    frames[0].save(f'{OUT}/monkey-{n}.webp', 'WEBP', quality=Q, method=6, alpha_quality=80, **kw)
    gh = 150
    gf = []
    for f in frames:
        g = f.resize((round(f.width * gh / H), gh), Image.LANCZOS)
        a = g.getchannel('A').point(lambda v: 255 if v > 110 else 0)
        p = g.convert('RGB').quantize(colors=31, method=Image.MEDIANCUT, dither=Image.NONE)
        p.paste(31, mask=Image.eval(a, lambda v: 255 - v))
        p.info['transparency'] = 31
        gf.append(p)
    gkw = dict(save_all=True, append_images=gf[1:], duration=durs, transparency=31, disposal=2)
    if not once:
        gkw['loop'] = 0
    gf[0].save(f'{OUT}/monkey-{n}.gif', 'GIF', **gkw)
    still = frames[-1] if once else frames[0]
    still.save(f'{OUT}/monkey-{n}-still.png', optimize=True)
    print(n, frames[0].size, len(frames), sum(durs))
