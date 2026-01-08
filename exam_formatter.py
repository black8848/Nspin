"""试卷样式排版模块"""

import os
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

from question_extractor import Question

# A4 横向尺寸 (300 DPI)
PAGE_WIDTH = 3508
PAGE_HEIGHT = 2480
MARGIN = 120
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN

# 字体设置
FONT_SIZE_STEM = 48
FONT_SIZE_OPTION = 44
LINE_HEIGHT_STEM = 72
LINE_HEIGHT_OPTION = 66


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    """获取中文字体"""
    # macOS 常见中文字体路径
    font_paths = [
        '/System/Library/Fonts/PingFang.ttc',
        '/System/Library/Fonts/STHeiti Light.ttc',
        '/System/Library/Fonts/Hiragino Sans GB.ttc',
        '/Library/Fonts/Arial Unicode.ttf',
        # Linux
        '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    ]
    for path in font_paths:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    # 回退到默认字体
    return ImageFont.load_default()


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """文本自动换行"""
    lines = []
    current_line = ""

    for char in text:
        test_line = current_line + char
        bbox = font.getbbox(test_line)
        width = bbox[2] - bbox[0]

        if width <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = char

    if current_line:
        lines.append(current_line)

    return lines


def render_questions_to_pages(questions: list[Question]) -> list[Image.Image]:
    """将题目渲染成试卷样式的页面"""
    if not questions:
        return []

    font_stem = _get_font(FONT_SIZE_STEM)
    font_option = _get_font(FONT_SIZE_OPTION)

    pages = []
    current_page = Image.new('RGB', (PAGE_WIDTH, PAGE_HEIGHT), 'white')
    draw = ImageDraw.Draw(current_page)
    current_y = MARGIN

    for idx, question in enumerate(questions, 1):
        # 计算这道题需要的高度
        question_height = _calculate_question_height(
            question, idx, font_stem, font_option, CONTENT_WIDTH
        )

        # 检查是否需要新页
        if current_y + question_height > PAGE_HEIGHT - MARGIN:
            pages.append(current_page)
            current_page = Image.new('RGB', (PAGE_WIDTH, PAGE_HEIGHT), 'white')
            draw = ImageDraw.Draw(current_page)
            current_y = MARGIN

        # 渲染题目
        current_y = _render_question(
            draw, question, idx, current_y,
            font_stem, font_option, CONTENT_WIDTH, MARGIN
        )

        # 题目间距
        current_y += 40

    # 添加最后一页
    if current_y > MARGIN:
        pages.append(current_page)

    return pages


def _calculate_question_height(
    question: Question,
    number: int,
    font_stem: ImageFont.FreeTypeFont,
    font_option: ImageFont.FreeTypeFont,
    max_width: int
) -> int:
    """计算题目渲染所需高度"""
    height = 0

    # 题干高度
    stem_text = f"{number}. {question.stem}"
    stem_lines = _wrap_text(stem_text, font_stem, max_width)
    height += len(stem_lines) * LINE_HEIGHT_STEM

    # 选项高度（两列布局）
    if question.options:
        option_rows = (len(question.options) + 1) // 2
        height += option_rows * LINE_HEIGHT_OPTION + 20  # 20是题干和选项的间距

    return height


def _render_question(
    draw: ImageDraw.Draw,
    question: Question,
    number: int,
    start_y: int,
    font_stem: ImageFont.FreeTypeFont,
    font_option: ImageFont.FreeTypeFont,
    max_width: int,
    margin: int
) -> int:
    """渲染单道题目，返回结束的y坐标"""
    current_y = start_y

    # 渲染题干
    stem_text = f"{number}. {question.stem}"
    stem_lines = _wrap_text(stem_text, font_stem, max_width)

    for line in stem_lines:
        draw.text((margin, current_y), line, font=font_stem, fill='black')
        current_y += LINE_HEIGHT_STEM

    # 渲染选项（两列布局：A B 一行，C D 一行）
    if question.options:
        current_y += 20  # 题干和选项的间距
        half_width = max_width // 2

        option_keys = sorted(question.options.keys())
        for i in range(0, len(option_keys), 2):
            # 左列
            key1 = option_keys[i]
            text1 = f"{key1}. {question.options[key1]}"
            draw.text((margin, current_y), text1, font=font_option, fill='black')

            # 右列
            if i + 1 < len(option_keys):
                key2 = option_keys[i + 1]
                text2 = f"{key2}. {question.options[key2]}"
                draw.text((margin + half_width, current_y), text2, font=font_option, fill='black')

            current_y += LINE_HEIGHT_OPTION

    return current_y


def render_questions_to_pdf(questions: list[Question]) -> bytes:
    """将题目渲染成PDF"""
    pages = render_questions_to_pages(questions)

    if not pages:
        raise ValueError("没有可渲染的题目")

    buffer = BytesIO()
    pages[0].save(
        buffer,
        format='PDF',
        save_all=True,
        append_images=pages[1:] if len(pages) > 1 else [],
        resolution=300
    )
    return buffer.getvalue()


def render_questions_to_images(questions: list[Question]) -> list[bytes]:
    """将题目渲染成PNG图片列表"""
    pages = render_questions_to_pages(questions)

    result = []
    for page in pages:
        buffer = BytesIO()
        page.save(buffer, format='PNG', dpi=(300, 300))
        result.append(buffer.getvalue())

    return result
