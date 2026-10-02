"""仅处理内存文字。结果含类别/理由/框，默认日志不包含原文。"""
import re
import unicodedata
from datetime import datetime


def normalize(text):
    return unicodedata.normalize('NFKC', text).strip()


def rect_of(polygon):
    xs, ys = [float(p[0]) for p in polygon], [float(p[1]) for p in polygon]
    return (min(xs), min(ys), max(xs)-min(xs), max(ys)-min(ys))


def valid_id(number):
    if not re.fullmatch(r'\d{17}[\dXx]', number):
        return False
    try:
        datetime.strptime(number[6:14], '%Y%m%d')
    except ValueError:
        return False
    weights = [7,9,10,5,8,4,2,1,6,3,7,9,10,5,8,4,2]
    checksum = '10X98765432'[sum(int(a)*b for a,b in zip(number[:17], weights)) % 11]
    return number[-1].upper() == checksum


def nearby(a, b):
    ax, ay, aw, ah = rect_of(a['polygon'])
    bx, by, bw, bh = rect_of(b['polygon'])
    vertical = max(ay, by)-min(ay+ah, by+bh)
    horizontal = max(ax, bx)-min(ax+aw, bx+bw)
    return vertical <= max(ah, bh)*2.5 and horizontal <= max(ah, bh)*4


def detect(lines, semantic=None):
    hits = {}
    def add(index, category, reason):
        hit = hits.setdefault(index, {'line_index': index, 'polygon': lines[index]['polygon'], 'categories': [], 'reasons': []})
        if category not in hit['categories']:
            hit['categories'].append(category)
            hit['reasons'].append(reason)
    labels = {'验证码': '验证码', '动态口令': '验证码', '学号': '学号', '账号': '账号',
              '帐号': '账号', '密码': '账号凭证', '地址': '地址', '住址': '地址',
              '身份证': '身份证', '姓名': '姓名'}
    for i, line in enumerate(lines):
        text = normalize(line['text'])
        compact = re.sub(r'\s+', '', text)
        if re.search(r'(?<!\d)1[3-9]\d{9}(?!\d)', compact):
            add(i, '手机号', '手机号格式')
        if re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', compact):
            add(i, '邮箱', '邮箱格式')
        for number in re.findall(r'(?<!\d)\d{17}[\dXx](?!\d)', compact):
            if valid_id(number):
                add(i, '身份证', '格式与校验码')
        for label, category in labels.items():
            # “讨论如何修改密码”不是凭证；要求赋值语境或独立标签。
            if text == label or re.search(re.escape(label)+r'\s*(?:[:：]|是|为)', text):
                add(i, category, '标签上下文')
                candidates = []
                for j, other in enumerate(lines):
                    if i != j and nearby(line, other):
                        other_text = normalize(other['text'])
                        if any(re.search(re.escape(key)+r'\s*[:：]', other_text) for key in labels):
                            continue
                        # 只关联右侧同一行或下方对齐的候选，不关联上方数字。
                        ax,ay,aw,ah = rect_of(line['polygon'])
                        bx,by,bw,bh = rect_of(other['polygon'])
                        same_row = abs((ay+ah/2)-(by+bh/2)) <= max(ah,bh)*.6 and bx >= ax+aw-2
                        below = by >= ay+ah-2 and max(ax,bx) <= min(ax+aw,bx+bw)+max(ah,bh)
                        if not (same_row or below):
                            continue
                        patterns = {'验证码':r'(?<!\d)\d{4,8}(?!\d)',
                                    '学号':r'[A-Za-z0-9]{5,}', '账号':r'[A-Za-z0-9_@.\-]{3,}',
                                    '账号凭证':r'\S{3,}', '身份证':r'\d{17}[\dXx]',
                                    '姓名':r'^[\u4e00-\u9fff]{2,8}$',
                                    '地址':r'[省市县区街路号楼栋室]'}
                        if re.search(patterns[category], other_text):
                            distance = abs(by-ay)+abs(bx-ax)*.2
                            candidates.append((distance,j))
                if candidates:
                    # 最近的一个值行；地址多行覆盖仍需后续场景评估。
                    add(min(candidates)[1], category, '邻近标签关联')
        # 低置信度不能当作安全文字；未知内容保守覆盖。
        if line['confidence'] < 0.65:
            add(i, '无法确定', '低OCR置信度')
        if semantic is not None:
            label, score = semantic.classify(text)
            if label != '普通聊天':
                add(i, label, '实验语义分类')
    return list(hits.values())
