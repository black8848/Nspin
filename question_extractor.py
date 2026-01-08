"""题目识别与解析模块 - 使用百度云OCR API"""

import os
import re
import base64
import requests
from dataclasses import dataclass
from io import BytesIO
from PIL import Image


@dataclass
class Question:
    """解析后的题目结构"""
    stem: str  # 题干
    options: dict[str, str]  # 选项 {'A': '...', 'B': '...', ...}
    raw_text: str  # 原始识别文本


# 百度OCR配置
BAIDU_API_KEY = os.getenv('BAIDU_OCR_API_KEY', '')
BAIDU_SECRET_KEY = os.getenv('BAIDU_OCR_SECRET_KEY', '')

# 缓存access_token
_access_token: str | None = None


def _get_access_token() -> str:
    """获取百度API access_token"""
    global _access_token
    if _access_token:
        return _access_token

    if not BAIDU_API_KEY or not BAIDU_SECRET_KEY:
        raise ValueError("请设置环境变量 BAIDU_OCR_API_KEY 和 BAIDU_OCR_SECRET_KEY")

    url = "https://aip.baidubce.com/oauth/2.0/token"
    params = {
        "grant_type": "client_credentials",
        "client_id": BAIDU_API_KEY,
        "client_secret": BAIDU_SECRET_KEY
    }

    response = requests.post(url, params=params, timeout=10)
    result = response.json()

    if "access_token" not in result:
        raise ValueError(f"获取access_token失败: {result}")

    _access_token = result["access_token"]
    return _access_token


def extract_text_from_image(image_bytes: bytes) -> tuple[str, list[dict]]:
    """使用百度OCR从图片中提取文字，返回文本和带位置的结果"""
    # 预处理图片
    img = Image.open(BytesIO(image_bytes))
    if img.mode == 'RGBA':
        background = Image.new('RGB', img.size, 'white')
        background.paste(img, mask=img.split()[3])
        img = background
    elif img.mode != 'RGB':
        img = img.convert('RGB')

    # 转为base64
    buffer = BytesIO()
    img.save(buffer, format='JPEG', quality=90)
    img_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

    # 调用百度OCR API（通用文字识别-高精度含位置版）
    access_token = _get_access_token()
    url = f"https://aip.baidubce.com/rest/2.0/ocr/v1/accurate?access_token={access_token}"

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {"image": img_base64}

    response = requests.post(url, headers=headers, data=data, timeout=30)
    result = response.json()

    if "error_code" in result:
        raise ValueError(f"OCR识别失败: {result.get('error_msg', 'Unknown error')}")

    # 提取文字和位置
    words_result = result.get("words_result", [])
    lines = [item["words"] for item in words_result]

    return '\n'.join(lines), words_result


def parse_question_with_location(words_result: list[dict]) -> Question:
    """根据OCR位置信息解析题目

    处理手机截图的特殊布局：选项字母在内容中间，内容分布在字母上下
    例如：
        纳米材料质量轻、强度高，可用来制    ← A的前半内容
        A                                   ← 选项字母
        作机械外骨骼系统                    ← A的后半内容
    """
    if not words_result:
        return Question(stem="", options={}, raw_text="")

    # 过滤无关内容的模式
    skip_patterns = [
        r'^\d+/\d+$', r'^单选题$', r'^多选题$', r'^常识判断$',
        r'^逻辑填空$', r'^言语理解$', r'^资料分析$', r'^判断推理$',
        r'^数量关系$', r'^\d{1,2}:\d{2}', r'^5G', r'^\.\.\.$',
        r'^<$', r'^>$', r'^\d+$',
    ]

    # 过滤并提取有效内容
    valid_items = []
    for item in words_result:
        text = item.get("words", "").strip()
        loc = item.get("location", {})
        if not text or not loc:
            continue
        if len(text) <= 2 and not re.match(r'^[A-D]$', text):
            if any(re.match(p, text) for p in skip_patterns):
                continue
        if any(re.match(p, text) for p in skip_patterns):
            continue
        valid_items.append({
            "text": text,
            "top": loc.get("top", 0),
            "left": loc.get("left", 0),
            "height": loc.get("height", 0),
            "width": loc.get("width", 0)
        })

    # 按Y坐标排序
    valid_items.sort(key=lambda x: x["top"])

    raw_text = '\n'.join(item["text"] for item in valid_items)

    # 先尝试查找合并格式的选项（如 "A. 内容" 或 "A 内容"）
    options = {}
    option_items = []

    for i, item in enumerate(valid_items):
        text = item["text"]
        match = re.match(r'^([A-D])[\s\.．、]\s*(.+)$', text)
        if match:
            letter, content = match.groups()
            options[letter] = content.strip()
            option_items.append({"index": i, "letter": letter, "top": item["top"]})

    if options:
        first_option_idx = option_items[0]["index"] if option_items else len(valid_items)
        stem_items = valid_items[:first_option_idx]
        stem = ''.join(item["text"] for item in stem_items)
        stem = re.sub(r'[（\(]\s*[）\)]\s*。?$', '', stem)
        return Question(stem=stem.strip(), options=options, raw_text=raw_text)

    # 找独立的选项字母及其索引位置
    option_letters = []
    for i, item in enumerate(valid_items):
        if re.match(r'^[A-D]$', item["text"]):
            option_letters.append({
                "index": i,
                "letter": item["text"],
                "top": item["top"]
            })

    if not option_letters:
        return parse_question(raw_text)

    # 按Y坐标排序
    option_letters.sort(key=lambda x: x["top"])

    # 找题干：以 () 或 （）结尾的行
    stem_end_idx = -1
    for i, item in enumerate(valid_items):
        text = item["text"]
        if '()' in text or '（）' in text:
            stem_end_idx = i
            break

    # 如果没找到明确的题干结束标记，用第一个选项字母前两行作为分界
    # （因为第一个选项字母前一行是A的前半内容）
    if stem_end_idx < 0:
        first_letter_idx = option_letters[0]["index"]
        if first_letter_idx >= 2:
            stem_end_idx = first_letter_idx - 2
        else:
            stem_end_idx = -1

    # 提取题干
    if stem_end_idx >= 0:
        stem_items = valid_items[:stem_end_idx + 1]
        stem = ''.join(item["text"] for item in stem_items)
        stem = re.sub(r'[（\(]\s*[）\)]\s*。?$', '', stem)
    else:
        stem = ""

    # 提取选项内容
    # 策略：每个内容项只分配给距离最近的选项字母（避免重复）
    options = {opt["letter"]: [] for opt in option_letters}

    # 遍历所有非题干、非选项字母的内容
    for i, item in enumerate(valid_items):
        if i <= stem_end_idx:
            continue
        if re.match(r'^[A-D]$', item["text"]):
            continue

        item_top = item["top"]

        # 找距离最近的选项字母
        min_dist = float('inf')
        closest_letter = None
        for opt in option_letters:
            dist = abs(item_top - opt["top"])
            if dist < min_dist:
                min_dist = dist
                closest_letter = opt["letter"]

        if closest_letter:
            options[closest_letter].append(item)

    # 按行分组，组内按X排序，然后合并
    for letter in options:
        content_list = options[letter]
        if not content_list:
            options[letter] = ""
            continue

        # 先按Y排序
        content_list.sort(key=lambda x: x["top"])

        # 按Y坐标分组（Y差距<40的归为同一行）
        lines = []
        current_line = [content_list[0]]
        for item in content_list[1:]:
            if abs(item["top"] - current_line[0]["top"]) < 40:
                current_line.append(item)
            else:
                lines.append(current_line)
                current_line = [item]
        lines.append(current_line)

        # 每行内按X坐标排序
        for line in lines:
            line.sort(key=lambda x: x["left"])

        # 合并：行内用空格，行间直接拼接
        result_parts = []
        for line in lines:
            line_text = ' '.join(item["text"] for item in line)
            result_parts.append(line_text)
        options[letter] = ''.join(result_parts)

    return Question(stem=stem.strip(), options=options, raw_text=raw_text)


def parse_question(text: str) -> Question:
    """解析题目文本，提取题干和选项"""
    lines = text.strip().split('\n')

    # 过滤掉无关内容（状态栏、页码、标签等）
    filtered_lines = []
    skip_patterns = [
        r'^\d+/\d+$',  # 页码如 6/19
        r'^单选题$',
        r'^多选题$',
        r'^常识判断$',
        r'^逻辑填空$',
        r'^言语理解$',
        r'^资料分析$',
        r'^判断推理$',
        r'^数量关系$',
        r'^\d{1,2}:\d{2}',  # 时间如 9:17
        r'^5G',  # 信号
        r'^\d+$',  # 纯数字
        r'^\.{2,}',  # 省略号开头
        r'^\\\s*$',  # 反斜杠
    ]
    for line in lines:
        line = line.strip()
        if not line or len(line) <= 2:
            continue
        if any(re.match(p, line) for p in skip_patterns):
            continue
        filtered_lines.append(line)

    # 找出所有选项字母的位置
    option_positions = []  # [(index, letter), ...]
    for i, line in enumerate(filtered_lines):
        if re.match(r'^[A-D]$', line):
            option_positions.append((i, line))

    # 如果没有找到独立的选项字母，尝试其他格式
    if not option_positions:
        return _parse_inline_format(filtered_lines, text)

    # 找到第一个选项字母之前的内容作为题干
    first_option_idx = option_positions[0][0]

    # 题干可能在第一个选项内容之前，需要找到题干的结束位置
    # 通常题干以 () 或 （）结尾
    stem_end_idx = first_option_idx
    for i in range(first_option_idx):
        line = filtered_lines[i]
        if '()' in line or '（）' in line or line.endswith('。'):
            stem_end_idx = i + 1
            break

    stem_lines = filtered_lines[:stem_end_idx]
    stem = ''.join(stem_lines)

    # 提取选项内容
    # 选项内容 = 字母前的内容（从上一个选项结束到当前字母）+ 字母后的内容（到下一个选项开始）
    options = {}

    for idx, (pos, letter) in enumerate(option_positions):
        # 找到这个选项的内容范围
        # 前面的内容：从题干结束/上一个选项字母+1 到 当前字母位置
        if idx == 0:
            start_before = stem_end_idx
        else:
            start_before = option_positions[idx - 1][0] + 1

        content_before = filtered_lines[start_before:pos]

        # 后面的内容：从当前字母+1 到 下一个选项的"前内容"开始
        # 这比较复杂，简化处理：后面直到下一个选项字母或结束
        if idx + 1 < len(option_positions):
            end_after = option_positions[idx + 1][0]
        else:
            end_after = len(filtered_lines)

        content_after = filtered_lines[pos + 1:end_after]

        # 合并内容
        # 但要注意：content_after 可能包含下一个选项的"前内容"
        # 对于 A 后面的内容，只取到遇到看起来像新选项开始的地方
        final_content_after = []
        for line in content_after:
            # 如果这行看起来像是新选项的开始（较长的内容行），可能属于下一个选项
            # 简单处理：只取紧跟着选项字母的短行
            if len(final_content_after) == 0 or len(line) < 20:
                final_content_after.append(line)
            else:
                break

        all_content = content_before + final_content_after
        options[letter] = ''.join(all_content)

    # 清理题干
    stem = re.sub(r'[（\(]\s*[）\)]\s*。?$', '', stem)

    return Question(
        stem=stem.strip(),
        options=options,
        raw_text=text
    )


def _parse_inline_format(lines: list[str], raw_text: str) -> Question:
    """解析选项字母和内容在同一行的格式"""
    options = {}
    stem_lines = []

    for line in lines:
        match = re.match(r'^([A-D])[\s\.．、](.+)$', line)
        if match:
            key, value = match.groups()
            options[key] = value.strip()
        elif not options:
            stem_lines.append(line)

    stem = ''.join(stem_lines)
    stem = re.sub(r'[（\(]\s*[）\)]\s*。?$', '', stem)

    return Question(stem=stem.strip(), options=options, raw_text=raw_text)


def _try_parse_inline_options(lines: list[str]) -> dict[str, str]:
    """尝试解析内联格式的选项，如 'A 触摸 投影 气韵'"""
    options = {}
    for line in lines:
        match = re.match(r'^([A-D])\s+(.+)$', line.strip())
        if match:
            key, value = match.groups()
            options[key] = value.strip()
    return options


def extract_questions_from_images(image_bytes_list: list[bytes]) -> list[Question]:
    """从多张图片中提取题目"""
    questions = []
    for image_bytes in image_bytes_list:
        text, words_result = extract_text_from_image(image_bytes)
        if words_result:
            question = parse_question_with_location(words_result)
            questions.append(question)
    return questions
