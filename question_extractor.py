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


def extract_text_from_image(image_bytes: bytes) -> str:
    """使用百度OCR从图片中提取文字"""
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

    # 调用百度OCR API（通用文字识别-高精度版）
    access_token = _get_access_token()
    url = f"https://aip.baidubce.com/rest/2.0/ocr/v1/accurate_basic?access_token={access_token}"

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {"image": img_base64}

    response = requests.post(url, headers=headers, data=data, timeout=30)
    result = response.json()

    if "error_code" in result:
        raise ValueError(f"OCR识别失败: {result.get('error_msg', 'Unknown error')}")

    # 提取文字
    words_result = result.get("words_result", [])
    lines = [item["words"] for item in words_result]

    return '\n'.join(lines)


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
        text = extract_text_from_image(image_bytes)
        if text:
            question = parse_question(text)
            questions.append(question)
    return questions
