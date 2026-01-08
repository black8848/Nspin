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

    # 过滤掉一些无关内容（如页码、标签等）
    filtered_lines = []
    skip_patterns = [
        r'^\d+/\d+$',  # 页码如 1/18
        r'^单选题$',
        r'^多选题$',
        r'^逻辑填空$',
        r'^\d{1,2}:\d{2}',  # 时间
    ]
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if any(re.match(p, line) for p in skip_patterns):
            continue
        filtered_lines.append(line)

    # 查找选项的位置
    option_pattern = r'^([A-D])[\.．、\s](.+)$'
    options = {}
    stem_lines = []
    in_options = False

    for line in filtered_lines:
        # 检查是否是选项行
        match = re.match(option_pattern, line)
        if match:
            in_options = True
            key, value = match.groups()
            options[key] = value.strip()
        elif in_options and len(line) <= 20:
            # 检查是否是纯选项标识如 "A 触摸 投影 气韵"
            multi_match = re.match(r'^([A-D])\s+(.+)$', line)
            if multi_match:
                key, value = multi_match.groups()
                options[key] = value.strip()
        else:
            if not in_options:
                stem_lines.append(line)

    # 如果没有找到标准格式的选项，尝试另一种解析方式
    if not options:
        options = _try_parse_inline_options(filtered_lines)
        if options:
            stem_lines = []
            for line in filtered_lines:
                has_option = False
                for opt in ['A', 'B', 'C', 'D']:
                    if line.strip().startswith(opt + ' ') or line.strip().startswith(opt + '　'):
                        has_option = True
                        break
                if not has_option:
                    stem_lines.append(line)

    stem = ''.join(stem_lines)

    # 清理题干中可能的问题标记
    stem = re.sub(r'依次填入横线处最恰当的是[（\(]\s*[）\)]。?', '', stem)
    stem = re.sub(r'[（\(]\s*[）\)]\s*。?$', '', stem)

    return Question(
        stem=stem.strip(),
        options=options,
        raw_text=text
    )


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
