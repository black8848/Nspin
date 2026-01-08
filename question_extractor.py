"""题目识别与解析模块"""

import re
from dataclasses import dataclass
from io import BytesIO
from PIL import Image
from paddleocr import PaddleOCR


@dataclass
class Question:
    """解析后的题目结构"""
    stem: str  # 题干
    options: dict[str, str]  # 选项 {'A': '...', 'B': '...', ...}
    raw_text: str  # 原始识别文本


# 全局OCR实例（避免重复加载模型）
_ocr_instance: PaddleOCR | None = None


def get_ocr() -> PaddleOCR:
    """获取OCR实例（懒加载）"""
    global _ocr_instance
    if _ocr_instance is None:
        _ocr_instance = PaddleOCR(use_angle_cls=True, lang='ch')
    return _ocr_instance


def extract_text_from_image(image_bytes: bytes) -> str:
    """从图片中提取文字"""
    img = Image.open(BytesIO(image_bytes))
    if img.mode == 'RGBA':
        background = Image.new('RGB', img.size, 'white')
        background.paste(img, mask=img.split()[3])
        img = background
    elif img.mode != 'RGB':
        img = img.convert('RGB')

    # 保存为临时数组供OCR使用
    import numpy as np
    img_array = np.array(img)

    ocr = get_ocr()
    result = ocr.ocr(img_array, cls=True)

    if not result or not result[0]:
        return ""

    # 按y坐标排序，然后拼接文本
    lines = []
    for line in result[0]:
        box, (text, confidence) = line
        y_center = (box[0][1] + box[2][1]) / 2
        lines.append((y_center, text))

    lines.sort(key=lambda x: x[0])
    return '\n'.join(text for _, text in lines)


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
            # 可能是选项的延续或独立的选项标识
            # 检查是否是纯选项标识如 "A 触摸 投影 气韵"
            multi_match = re.match(r'^([A-D])\s+(.+)$', line)
            if multi_match:
                key, value = multi_match.groups()
                options[key] = value.strip()
            else:
                # 可能是上一个选项的延续
                pass
        else:
            if not in_options:
                stem_lines.append(line)

    # 如果没有找到标准格式的选项，尝试另一种解析方式
    if not options:
        options = _try_parse_inline_options(filtered_lines)
        if options:
            # 重新提取题干（去掉选项部分）
            stem_lines = []
            for line in filtered_lines:
                if not any(re.match(r'^[A-D][\s\.．、]', line) for _ in [1]):
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
        # 匹配 "A 内容" 格式
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
