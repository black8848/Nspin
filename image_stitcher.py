"""图片智能拼接模块 - 将多张图片拼接成A4尺寸"""

from dataclasses import dataclass
from PIL import Image
from io import BytesIO

# A4 尺寸 (300 DPI) - 横向
A4_WIDTH = 3508
A4_HEIGHT = 2480
PADDING = 40  # 页边距
GAP = 20  # 图片间距
COLUMNS = 4  # 每行4列，每页只放1行

# 手机截图裁切比例
CROP_TOP_PERCENT = 5  # 裁切顶部7%（状态栏）
CROP_BOTTOM_PERCENT = 3  # 裁切底部3%（底部横条）


def crop_phone_screenshot(img: Image.Image) -> Image.Image:
    """裁切手机截图的状态栏和底部横条"""
    width, height = img.size
    top = int(height * CROP_TOP_PERCENT / 100)
    bottom = int(height * (100 - CROP_BOTTOM_PERCENT) / 100)
    return img.crop((0, top, width, bottom))


@dataclass
class PlacedImage:
    """已放置的图片信息"""
    image: Image.Image
    x: int
    y: int
    width: int
    height: int


class ImageStitcher:
    """图片拼接器 - 4列网格布局"""

    def __init__(self, a4_width: int = A4_WIDTH, a4_height: int = A4_HEIGHT):
        self.a4_width = a4_width
        self.a4_height = a4_height
        self.content_width = a4_width - 2 * PADDING
        self.content_height = a4_height - 2 * PADDING
        self.cell_width = (self.content_width - (COLUMNS - 1) * GAP) // COLUMNS

    def stitch(self, images: list[Image.Image]) -> list[Image.Image]:
        """
        将图片拼接成多张A4页面（4列网格布局）

        Args:
            images: 待拼接的图片列表

        Returns:
            A4页面图片列表
        """
        if not images:
            return []

        # 缩放所有图片到单元格宽度
        scaled_images = [self._fit_to_width(img, self.cell_width) for img in images]

        # 网格布局
        pages = self._layout_images(scaled_images)

        # 渲染页面
        return [self._render_page(page) for page in pages]

    def _layout_images(self, images: list[Image.Image]) -> list[list[PlacedImage]]:
        """4列布局，每页只放4张图片"""
        pages: list[list[PlacedImage]] = []

        for i in range(0, len(images), COLUMNS):
            row_images = images[i:i + COLUMNS]
            current_page: list[PlacedImage] = []

            for col, im in enumerate(row_images):
                x = PADDING + col * (self.cell_width + GAP)
                current_page.append(PlacedImage(
                    image=im,
                    x=x,
                    y=PADDING + 60,  # 下移一点点
                    width=im.width,
                    height=im.height
                ))

            pages.append(current_page)

        return pages

    def _fit_to_width(self, img: Image.Image, target_width: int) -> Image.Image:
        """缩放图片以适应目标宽度"""
        if img.width == target_width:
            return img
        ratio = target_width / img.width
        new_height = int(img.height * ratio)
        return img.resize((target_width, new_height), Image.Resampling.LANCZOS)

    def _render_page(self, placed_images: list[PlacedImage]) -> Image.Image:
        """渲染单个A4页面"""
        page = Image.new('RGB', (self.a4_width, self.a4_height), 'white')

        for placed in placed_images:
            # 确保图片是RGB模式
            img = placed.image
            if img.mode != 'RGB':
                img = img.convert('RGB')
            page.paste(img, (placed.x, placed.y))

        return page


def stitch_images_to_a4(image_bytes_list: list[bytes], crop: bool = True) -> list[bytes]:
    """
    便捷函数：将图片字节数据拼接成A4页面

    Args:
        image_bytes_list: 图片字节数据列表
        crop: 是否裁切手机截图的状态栏和底部横条

    Returns:
        A4页面的PNG字节数据列表
    """
    images = []
    for data in image_bytes_list:
        img = Image.open(BytesIO(data))
        if img.mode == 'RGBA':
            # 处理透明背景
            background = Image.new('RGB', img.size, 'white')
            background.paste(img, mask=img.split()[3])
            img = background
        # 裁切手机截图
        if crop:
            img = crop_phone_screenshot(img)
        images.append(img)

    stitcher = ImageStitcher()
    pages = stitcher.stitch(images)

    result = []
    for page in pages:
        buffer = BytesIO()
        page.save(buffer, format='PNG', dpi=(300, 300))
        result.append(buffer.getvalue())

    return result


def stitch_images_to_pdf(image_bytes_list: list[bytes], crop: bool = True) -> bytes:
    """
    将图片拼接成A4页面并生成PDF

    Args:
        image_bytes_list: 图片字节数据列表
        crop: 是否裁切手机截图的状态栏和底部横条

    Returns:
        PDF文件字节数据
    """
    images = []
    for data in image_bytes_list:
        img = Image.open(BytesIO(data))
        if img.mode == 'RGBA':
            background = Image.new('RGB', img.size, 'white')
            background.paste(img, mask=img.split()[3])
            img = background
        # 裁切手机截图
        if crop:
            img = crop_phone_screenshot(img)
        images.append(img)

    stitcher = ImageStitcher()
    pages = stitcher.stitch(images)

    if not pages:
        raise ValueError("没有生成任何页面")

    buffer = BytesIO()
    pages[0].save(
        buffer,
        format='PDF',
        save_all=True,
        append_images=pages[1:] if len(pages) > 1 else [],
        resolution=300
    )
    return buffer.getvalue()
