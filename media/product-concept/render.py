"""Deterministic 3D card compositor. Renders a 30 s product film, never runs detection."""
from __future__ import annotations

import argparse
from functools import lru_cache
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
W, H = 1920, 1080
FONTS = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'


def clamp(x):
    return max(0.0, min(1.0, x))


def ease(x):
    x = clamp(x)
    return x*x*x*(x*(x*6-15)+10)


def mix(a, b, x):
    return a + (b-a)*x


def rgb(value):
    return tuple(bytes.fromhex(value.lstrip('#')))


@lru_cache(maxsize=64)
def font(size, bold=False, latin=False):
    env = os.environ.get('VISION_FILM_FONT_BOLD' if bold else 'VISION_FILM_FONT')
    names = ([env] if env else []) + ([str(FONTS / ('segoeuib.ttf' if bold else 'segoeui.ttf'))] if latin else [])
    names += [str(FONTS / ('msyhbd.ttc' if bold else 'msyhl.ttc')), str(FONTS / 'msyh.ttc')]
    for name in names:
        if Path(name).exists():
            return ImageFont.truetype(name, size)
    raise FileNotFoundError('Set VISION_FILM_FONT and VISION_FILM_FONT_BOLD to CJK font paths.')


@lru_cache(maxsize=128)
def text_image(value, size, color, bold=False, latin=False, tracking=0):
    face = font(size, bold, latin)
    if tracking:
        width = int(sum(face.getlength(c) for c in value) + tracking * max(0, len(value)-1)) + 8
    else:
        width = int(face.getlength(value)) + 10
    image = Image.new('RGBA', (width, size+22), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if tracking:
        x = 0.0
        for character in value:
            draw.text((x, 0), character, font=face, fill=color, anchor='lt')
            x += face.getlength(character) + tracking
    else:
        draw.text((0, 0), value, font=face, fill=color, anchor='lt')
    return np.array(image)


def composite(frame, layer, x, y, opacity=1):
    if opacity <= 0:
        return
    x, y = int(round(x)), int(round(y))
    lh, lw = layer.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x+lw), min(H, y+lh)
    if x0 >= x1 or y0 >= y1:
        return
    crop = layer[y0-y:y1-y, x0-x:x1-x]
    a = crop[..., 3:4].astype(np.float32) * (opacity/255)
    destination = frame[y0:y1, x0:x1]
    destination[:] = np.clip(destination*(1-a)+crop[..., :3]*a, 0, 255).astype(np.uint8)


def text(frame, value, x, y, size=30, color='#182b23', bold=False, alpha=1, latin=False, tracking=0):
    composite(frame, text_image(value, size, color, bold, latin, tracking), x, y, alpha)


def background(night=False):
    # Broad studio lights, not animated gradients or stock backgrounds.
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    spot = np.exp(-(((x-1330)/700)**2+((y-430)/570)**2))
    lower = np.exp(-(((x-500)/1000)**2+((y-1060)/350)**2))
    if night:
        base = np.array([10, 19, 15], np.float32)
        value = base + spot[..., None]*np.array([12, 22, 17]) + lower[..., None]*np.array([4, 8, 6])
    else:
        base = np.array([238, 240, 233], np.float32)
        value = base + spot[..., None]*np.array([15, 14, 19]) - lower[..., None]*np.array([8, 6, 9])
    return np.clip(value, 0, 255).astype(np.uint8)


def card(image, title=None, radius=24):
    image = image.convert('RGBA')
    if title:
        bar_h = 52
        output = Image.new('RGBA', (image.width, image.height+bar_h), '#f7f9f8')
        output.alpha_composite(image, (0, bar_h))
        d = ImageDraw.Draw(output)
        d.text((24, 13), title, font=font(23), fill='#64766c', anchor='lt')
        right = output.width
        d.line((right-148, 25, right-128, 25), fill='#87958d', width=2)
        d.rectangle((right-98, 18, right-81, 33), outline='#87958d', width=2)
        d.line((right-45, 18, right-29, 34), fill='#87958d', width=2)
        d.line((right-29, 18, right-45, 34), fill='#87958d', width=2)
        image = output
    mask = Image.new('L', image.size)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, image.width-1, image.height-1), radius=radius, fill=255)
    image.putalpha(mask)
    d = ImageDraw.Draw(image)
    d.rounded_rectangle((1, 1, image.width-2, image.height-2), radius=radius, outline=(255, 255, 255, 225), width=2)
    return np.array(image)


def module_card(image):
    """Give enlarged native controls breathing room without changing their design."""
    output = Image.new('RGBA', (image.width+56, image.height+56), '#f7f9f8')
    output.alpha_composite(image.convert('RGBA'), (28, 28))
    return card(output, radius=22)


class Studio:
    def __init__(self, assets, config):
        self.config = config
        self.light, self.dark = background(), background(True)
        self.images = {}
        self.panels = {}
        for name in ('main-safe', 'main-risk', 'main-dark', 'main-paused', 'settings', 'settings-popup'):
            self.images[name] = Image.open(assets / (name+'.png')).convert('RGBA')
            self.panels[name] = card(self.images[name], '设置 · 视界盾' if 'settings' in name else '视界盾')
        layout_file = assets / 'layout.json'
        self.layout = json.loads(layout_file.read_text(encoding='utf-8')) if layout_file.exists() else {}
        self.effects = {}
        self.controls_rect = self.layout.get('assets', {}).get('main-safe.png', {}).get('effect_crop_rect', [56, 732, 928, 286])
        rect = self.controls_rect
        crop = (rect[0], rect[1], rect[0]+rect[2], rect[1]+rect[3])
        for value in range(2, 65):
            file = assets / f'main-blur-{value}.png'
            if file.exists():
                source = Image.open(file).convert('RGBA')
                self.effects[value] = module_card(source.crop(crop))
        self.effects['dark'] = module_card(self.images['main-dark'].crop(crop))
        settings_rect = self.layout.get('assets', {}).get('settings.png', {}).get('effects_crop_rect', [56, 190, 1008, 444])
        crop = (settings_rect[0], settings_rect[1], settings_rect[0]+settings_rect[2], settings_rect[1]+settings_rect[3])
        self.options = {key: module_card(self.images[key].crop(crop)) for key in ('settings', 'settings-popup')}
        self.docs = self.make_documents()
        self.shadows = {}
        self.premultiplied = {}

    def make_documents(self):
        page = Image.new('RGBA', (1120, 790), '#f7f9f8')
        d = ImageDraw.Draw(page)
        d.rectangle((0, 0, 1120, 64), fill='#edf1ed')
        d.text((34, 22), '研究笔记', font=font(25, True), fill='#24392e', anchor='lt')
        d.text((910, 24), '虚构演示', font=font(19), fill='#64766c', anchor='lt')
        d.text((72, 116), '周五小组协作', font=font(44, True), fill='#1b3025', anchor='lt')
        d.text((72, 187), '公开议程与内部信息，在同一张屏幕上。', font=font(27), fill='#697a70', anchor='lt')
        for value, y in [('内部方案 · 仅组内查看', 306), ('演示验证码：482613', 380), ('下次会议：周五 15:00', 454)]:
            d.text((106, y), value, font=font(34, y==306), fill='#253c2e', anchor='lt')
        d.line((72, 555, 1048, 555), fill='#d7e0d9', width=2)
        d.text((72, 598), '公开任务', font=font(27, True), fill='#263e2f', anchor='lt')
        d.text((72, 650), '整理演示材料  /  检查安装包  /  准备团队汇报', font=font(27), fill='#697a70', anchor='lt')
        selected = page.copy()
        box = (76, 278, 1038, 520)
        d = ImageDraw.Draw(selected)
        d.rounded_rectangle(box, radius=12, outline='#24724f', width=3)
        d.rounded_rectangle((772, 237, 1038, 278), radius=8, fill='#24724f')
        d.text((790, 246), '已选择的保护范围', font=font(21), fill='white', anchor='lt')
        result = {'clear': card(selected)}
        region = (90, 291, 1024, 507)
        for strength in range(0, 33):
            blurred = selected.copy()
            blurred.paste(page.crop(region).filter(ImageFilter.GaussianBlur(strength)), region[:2])
            result[strength] = card(blurred)
        blocked = selected.copy()
        ImageDraw.Draw(blocked).rounded_rectangle(region, radius=8, fill='#17281f')
        result['block'] = card(blocked)
        return result

    def projection(self, image, center, height, yaw, pitch, roll, depth=1800):
        ih, iw = image.shape[:2]
        ww = height*iw/ih
        points = np.array([[-ww/2, -height/2, 0], [ww/2, -height/2, 0],
                           [ww/2, height/2, 0], [-ww/2, height/2, 0]], np.float64)
        a, b, c = [math.radians(v) for v in (yaw, pitch, roll)]
        ry = np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])
        rx = np.array([[1, 0, 0], [0, math.cos(b), -math.sin(b)], [0, math.sin(b), math.cos(b)]])
        rz = np.array([[math.cos(c), -math.sin(c), 0], [math.sin(c), math.cos(c), 0], [0, 0, 1]])
        points = points @ (rz @ rx @ ry).T
        z = depth/(depth+points[:, 2])
        return (points[:, :2]*z[:, None]+np.array(center)).astype(np.float32)

    def surface(self, frame, image, center, height, yaw=0, pitch=0, roll=0, opacity=1, shadow=True):
        if opacity < .003:
            return
        dst = self.projection(image, center, height, yaw, pitch, roll)
        # Work only in the visible projected rectangle. Avoid full-frame warp allocations.
        margin = 44
        x0 = max(0, int(np.min(dst[:, 0]))-margin)
        x1 = min(W, int(np.max(dst[:, 0]))+margin)
        y0 = max(0, int(np.min(dst[:, 1]))-margin)
        y1 = min(H, int(np.max(dst[:, 1]))+margin)
        if x1 <= x0 or y1 <= y0:
            return
        if shadow:
            # A soft elliptic shadow on the studio floor provides depth under the card.
            sw, sh = int(height*image.shape[1]/image.shape[0]*1.03), 110
            key = (sw, sh)
            if key not in self.shadows:
                layer = Image.new('RGBA', (sw, sh))
                ImageDraw.Draw(layer).ellipse((20, 37, sw-20, 83), fill=(8, 25, 15, 54))
                self.shadows[key] = np.array(layer.filter(ImageFilter.GaussianBlur(21)))
                if len(self.shadows) > 80:
                    self.shadows.pop(next(iter(self.shadows)))
            composite(frame, self.shadows[key], center[0]-sw/2, center[1]+height/2-8, opacity)
        # The thin offset edge is rendered before the front, like a floating native window.
        edge = np.zeros((y1-y0, x1-x0, 4), dtype=np.uint8)
        cv2.polylines(edge, [np.round(dst+np.array([3-x0, 5-y0])).astype(np.int32)], True,
                      (90, 111, 99, 90), 4, cv2.LINE_AA)
        composite(frame, edge, x0, y0, opacity)
        ih, iw = image.shape[:2]
        src = np.float32([[0, 0], [iw-1, 0], [iw-1, ih-1], [0, ih-1]])
        matrix = cv2.getPerspectiveTransform(src, (dst-[x0, y0]).astype(np.float32))
        # Premultiply alpha to avoid dark seams on the transparent rounded corners.
        key = id(image)
        if key not in self.premultiplied:
            premult = image.copy()
            premult[..., :3] = (premult[..., :3].astype(np.float32)*(premult[..., 3:4]/255)).astype(np.uint8)
            self.premultiplied[key] = premult
        premult = self.premultiplied[key]
        warped = cv2.warpPerspective(premult, matrix, (x1-x0, y1-y0), flags=cv2.INTER_LINEAR)
        alpha = warped[..., 3:4].astype(np.float32)*(opacity/255)
        roi = frame[y0:y1, x0:x1]
        roi[:] = np.clip(roi*(1-alpha)+warped[..., :3]*opacity, 0, 255).astype(np.uint8)

    def copy(self, frame, index, local, night=False):
        item = self.config['scenes'][index]
        appear = ease(local/.8)
        ink, muted = ('#f2f5ef', '#9faf9f') if night else ('#182b23', '#6b7c71')
        shift = 34*(1-appear)
        text(frame, item['eyebrow'], 146, 304+shift, 17, '#87b798' if night else '#24724f', alpha=appear, latin=True, tracking=3)
        for i, line in enumerate(item['headline']):
            delayed = ease((local-.1*i)/.9)
            text(frame, line, 140, 360+96*i+34*(1-delayed), 74, ink, True, delayed)
        text(frame, item['subline'], 146, 583+shift, 26, muted, alpha=appear)

    def scene(self, index, t):
        item = self.config['scenes'][index]
        local, length = t-item['start'], item['end']-item['start']
        u = clamp(local/length)
        night = index in (1, 3)
        frame = (self.dark if night else self.light).copy()
        if index == 0:
            intro = ease(local/1.5)
            y = 540+24*math.sin(u*math.pi)-40*(1-intro)
            # Two receding panels create a real perspective stack during the opening.
            self.surface(frame, self.panels['settings'], (1428, 526), 700, -22, 8, 6, .16*intro)
            self.surface(frame, self.panels['main-safe'], (1290+100*(1-intro), y), mix(675, 798, intro),
                         mix(-28, -7, ease(u)), mix(13, 3, intro), mix(-5, -1.5, ease(u)), intro)
            self.copy(frame, index, local)
            text(frame, '原生界面  /  后台运行', 146, 664+18*(1-intro), 23, '#7c8a80', alpha=intro)
        elif index == 1:
            enter = ease(local/.9)
            # Protection is deliberately a staged animation, not a latency recording.
            strength = int(32*ease((local-1.1)/.75)*(1-ease((local-4.35)/.65)))
            risk = ease((local-.9)/.5)*(1-ease((local-4)/.45))
            self.surface(frame, self.docs[strength], (1280+45*math.sin(u*math.pi), 570+18*math.sin(u*2*math.pi)),
                         mix(570, 655, enter), mix(-14, 5, ease(u)), -4+5*u, -1, enter)
            self.copy(frame, index, local, True)
            text(frame, '所选范围之外，保持清晰', 146, 651, 25, '#afc4b2', alpha=enter)
            label = '风险出现 · 保护所选范围' if risk > .3 else '风险稳定消失后恢复'
            text(frame, label, 967, 948, 24, '#aed9bc', alpha=enter)
            text(frame, '虚构内容 / 演示状态', 146, 859, 20, '#708a77', alpha=enter)
        elif index == 2:
            zoom = ease((local-.65)/1.1)
            main_opacity = 1-ease((local-.75)/.65)
            self.surface(frame, self.panels['main-safe'], (1315, mix(542, 415, zoom)), mix(780, 1180, zoom),
                         -6+6*zoom, 3-3*zoom, -1, main_opacity)
            value = int(round(mix(8, 64, ease((local-1.65)/2.55))))
            value = min(self.effects, key=lambda n: abs(n-value) if isinstance(n, int) else 10000)
            block = ease((local-4.55)/.4)
            controls = self.effects[value]
            center = (1250, 615+11*math.sin(local*.85))
            self.surface(frame, controls, center, mix(250, 310, zoom), mix(-17, 1, ease(u)), 3, -2+3*u,
                         zoom*(1-block), shadow=True)
            if block > 0:
                self.surface(frame, self.effects['dark'], center, 310, 1, 3, -2+3*u, block)
            # A second floating sample visibly changes along with the original app control.
            doc_img = self.docs['block' if block > .5 else int(mix(4, 32, ease((local-1.65)/2.55)))]
            self.surface(frame, doc_img, (1325, 251), 242, -5, 7, 2, zoom*.94)
            self.copy(frame, index, local)
            text(frame, '模糊  →  深色遮挡' if block > .5 else '弱  →  强', 146, 666, 25, '#24724f', alpha=zoom)
            text(frame, '较弱模糊可能仍可读，按场景选择强度。', 146, 878, 20, '#7b897f', alpha=zoom)
        elif index == 3:
            enter = ease(local/1)
            push = ease((local-1.1)/1.2)
            popup = ease((local-3.2)/.45)
            self.surface(frame, self.panels['settings'], (1290, 534-70*push), mix(810, 1280, push),
                         mix(14, 0, ease(u)), 5, mix(3, -1, ease(u)), enter*(1-push))
            self.surface(frame, self.options['settings'], (1250, 561), 455, -7+7*u, 4-4*u, -1.6,
                         push*(1-popup))
            if popup > 0:
                self.surface(frame, self.options['settings-popup'], (1250, 561), 455, -7+7*u, 4-4*u, -1.6,
                             push*popup)
            self.copy(frame, index, local, True)
            text(frame, '在设置中，选择适合你的防护方式。', 146, 666, 25, '#b7c9b7', alpha=enter)
            # This line is an editorial callout, not an invented in-app control.
            text(frame, '遮蔽  ·  音效  ·  弹窗', 994, 870, 24, '#a3cfb1', alpha=push)
        else:
            enter = ease(local/1.2)
            settle = ease(local/4)
            self.surface(frame, self.panels['settings'], (1490, 550), 706, -17, 5, 6, .7*enter)
            self.surface(frame, self.panels['main-safe'], (1185, 530+9*math.sin(local*.6)), 788,
                         mix(-18, -5, settle), mix(7, 2, settle), -2, enter)
            self.copy(frame, index, local)
            text(frame, 'VisionShield', 146, 692, 43, '#24724f', True, enter, True)
            text(frame, 'Windows 预览版', 146, 761, 23, '#718176', alpha=enter)
        # Consistent brand lockup and clear concept label remain in the safe area.
        color = '#b4cbbd' if night else '#536d5d'
        text(frame, 'VisionShield', 94, 64, 24, color, True, latin=True)
        text(frame, '视界盾', 272, 67, 20, color)
        notice = self.config['notice']
        layer = text_image(notice, 20, '#728979' if night else '#7a877e')
        composite(frame, layer, (W-layer.shape[1])/2, 1023, .9)
        return frame

    def frame(self, t):
        scenes = self.config['scenes']
        index = next((i for i, scene in enumerate(scenes) if scene['start'] <= t < scene['end']), len(scenes)-1)
        # Match-cut dissolve overlaps real spatial motion; no still-image slideshow.
        width = .55
        if index > 0 and t-scenes[index]['start'] < width:
            p = ease((t-scenes[index]['start'])/width)
            previous = self.scene(index-1, min(t, scenes[index-1]['end']))
            current = self.scene(index, t)
            return cv2.addWeighted(previous, 1-p, current, p, 0)
        return self.scene(index, t)


def find_ffmpeg(explicit=None):
    if explicit:
        return str(Path(explicit).resolve())
    found = shutil.which('ffmpeg')
    if found:
        return found
    isolated = ROOT / 'output' / 'deps'
    if isolated.exists():
        sys.path.insert(0, str(isolated))
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def preview(studio, directory):
    times = [.8, 3.5, 7.3, 9.8, 13.8, 15.4, 17.3, 19.2, 22.2, 26.6, 28.8]
    thumbs = []
    for timestamp in times:
        frame = studio.frame(timestamp)
        image = Image.fromarray(frame)
        image.save(directory/f'frame-{timestamp:04.1f}.jpg', quality=95)
        thumbnail = image.resize((640, 360), Image.Resampling.LANCZOS)
        draw = ImageDraw.Draw(thumbnail)
        draw.rectangle((0, 334, 112, 360), fill='#182b23')
        draw.text((12, 338), f'{timestamp:04.1f}s', fill='white', font=font(17, latin=True), anchor='lt')
        thumbs.append(thumbnail)
    sheet = Image.new('RGB', (1920, 1440), '#e9ede7')
    for i, thumbnail in enumerate(thumbs):
        sheet.paste(thumbnail, (640*(i%3), 360*(i//3)))
    sheet.save(directory/'contact-sheet.jpg', quality=94)


def render(studio, output, ffmpeg, fps, duration, score, preview_scale=1.0):
    # 1080p is the default deliverable; --scale .5 is for quick animation proofs only.
    ow, oh = int(W*preview_scale)//2*2, int(H*preview_scale)//2*2
    command = [ffmpeg, '-y', '-hide_banner', '-loglevel', 'warning', '-f', 'rawvideo',
               '-pix_fmt', 'rgb24', '-s', f'{ow}x{oh}', '-r', str(fps), '-i', 'pipe:0']
    if score:
        command += ['-i', str(score), '-map', '0:v:0', '-map', '1:a:0', '-c:a', 'aac', '-b:a', '256k']
    command += ['-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p',
                '-r', str(fps), '-t', str(duration), '-movflags', '+faststart',
                '-metadata', 'title=VisionShield - Product Concept', str(output)]
    log_file = output.parent/'encode.log'
    started = time.perf_counter()
    total = int(round(fps*duration))
    with log_file.open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log)
        try:
            for index in range(total):
                frame = studio.frame(index/fps)
                if preview_scale != 1:
                    frame = cv2.resize(frame, (ow, oh), interpolation=cv2.INTER_AREA)
                process.stdin.write(frame.tobytes())
                if index % fps == 0:
                    print(f'Render {index}/{total} ({index/fps:.0f}s), elapsed {time.perf_counter()-started:.1f}s', flush=True)
            process.stdin.close()
            if process.wait() != 0:
                raise RuntimeError(f'Encoder failed. See {log_file}')
        except BaseException:
            process.kill()
            process.wait()
            raise
    print(f'Completed: {output} ({time.perf_counter()-started:.1f}s)', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path, default=ROOT/'output'/'assets')
    parser.add_argument('--output', type=Path, default=ROOT/'output'/'VisionShield_Concept_30s_1080p.mp4')
    parser.add_argument('--storyboard', type=Path, default=ROOT/'storyboard.json')
    parser.add_argument('--ffmpeg')
    parser.add_argument('--preview-only', action='store_true')
    parser.add_argument('--scale', type=float, default=1)
    parser.add_argument('--silent', action='store_true')
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    config = json.loads(args.storyboard.read_text(encoding='utf-8'))
    if config['width'] != W or config['height'] != H:
        raise ValueError('Layout is designed for 1920x1080. Use --scale only for previews.')
    studio = Studio(args.assets, config)
    preview(studio, args.output.parent)
    if not args.preview_only:
        score = ROOT/'output'/'score.wav'
        if not args.silent and not score.exists():
            subprocess.run([sys.executable, str(ROOT/'soundtrack.py'), '--output', str(score)], check=True)
        render(studio, args.output, find_ffmpeg(args.ffmpeg), config['fps'], config['duration'],
               None if args.silent else score, args.scale)


if __name__ == '__main__':
    main()
