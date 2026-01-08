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

    # 合并选项：处理 "A" 和 "选项内容" 分行的情况
    merged_lines = []
    i = 0
    while i < len(filtered_lines):
        line = filtered_lines[i]
        # 如果当前行只是一个选项字母
        if re.match(r'^[A-D]$', line) and i + 1 < len(filtered_lines):
            next_line = filtered_lines[i + 1]
            # 下一行不是选项字母，则合并
            if not re.match(r'^[A-D]$', next_line):
                merged_lines.append(f"{line} {next_line}")
                i += 2
                continue
        merged_lines.append(line)
        i += 1

    # 再次合并：处理选项内容跨多行的情况（如 "与能力" 是上一行的延续）
    final_lines = []
    current_option = None
    for line in merged_lines:
        # 检查是否是新选项开头
        match = re.match(r'^([A-D])[\s\.．、](.*)$', line)
        if match:
            if current_option:
                final_lines.append(current_option)
            current_option = line
        elif current_option and not re.match(r'^[A-D][\s\.．、]', line):
            # 可能是选项内容的延续（不以选项字母开头的短行）
            if len(line) < 30 and not line.endswith('。'):
                current_option += line
            else:
                final_lines.append(current_option)
                current_option = None
                final_lines.append(line)
        else:
            if current_option:
                final_lines.append(current_option)
                current_option = None
            final_lines.append(line)
    if current_option:
        final_lines.append(current_option)

    # 提取题干和选项
    options = {}
    stem_lines = []

    for line in final_lines:
        match = re.match(r'^([A-D])[\s\.．、](.+)$', line)
        if match:
            key, value = match.groups()
            options[key] = value.strip()
        elif not options:  # 还没遇到选项，都算题干
            stem_lines.append(line)

    stem = ''.join(stem_lines)

    # 清理题干
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
