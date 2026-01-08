"""图片智能拼接模块 - 将多张图片拼接成A4尺寸"""

from dataclasses import dataclass
from PIL import Image
from io import BytesIO

# A4 尺寸 (300 DPI)
A4_WIDTH = 2480
A4_HEIGHT = 3508
PADDING = 40  # 页边距
GAP = 20  # 图片间距


@dataclass
class PlacedImage:
    """已放置的图片信息"""
    image: Image.Image
    x: int
    y: int
    width: int
    height: int


class ImageStitcher:
    """智能图片拼接器"""

    def __init__(self, a4_width: int = A4_WIDTH, a4_height: int = A4_HEIGHT):
        self.a4_width = a4_width
        self.a4_height = a4_height
        self.content_width = a4_width - 2 * PADDING
        self.content_height = a4_height - 2 * PADDING

    def stitch(self, images: list[Image.Image]) -> list[Image.Image]:
        """
        将图片智能拼接成多张A4页面

        Args:
            images: 待拼接的图片列表

        Returns:
            A4页面图片列表
        """
        if not images:
            return []

        # 预处理：缩放图片以适应页面宽度
        scaled_images = self._scale_images(images)

        # 智能布局
        pages = self._layout_images(scaled_images)

        # 渲染页面
        return [self._render_page(page) for page in pages]

    def _scale_images(self, images: list[Image.Image]) -> list[Image.Image]:
        """缩放图片，确保宽度不超过内容区域"""
        scaled = []
        for img in images:
            if img.width > self.content_width:
                ratio = self.content_width / img.width
                new_height = int(img.height * ratio)
                img = img.resize((self.content_width, new_height), Image.Resampling.LANCZOS)
            scaled.append(img)
        return scaled

    def _layout_images(self, images: list[Image.Image]) -> list[list[PlacedImage]]:
        """
        智能布局算法：尝试双列布局，如果图片太宽则单独一行
        """
        pages: list[list[PlacedImage]] = []
        current_page: list[PlacedImage] = []
        current_y = 0

        i = 0
        while i < len(images):
            img = images[i]

            # 检查是否需要新页面
            if current_y + img.height > self.content_height and current_page:
                pages.append(current_page)
                current_page = []
                current_y = 0

            # 尝试双列布局
            half_width = (self.content_width - GAP) // 2

            if img.width <= half_width and i + 1 < len(images):
                next_img = images[i + 1]
                if next_img.width <= half_width:
                    # 可以并排放置
                    left_img = self._fit_to_width(img, half_width)
                    right_img = self._fit_to_width(next_img, half_width)
                    row_height = max(left_img.height, right_img.height)

                    if current_y + row_height <= self.content_height:
                        current_page.append(PlacedImage(
                            image=left_img,
                            x=PADDING,
                            y=PADDING + current_y,
                            width=left_img.width,
                            height=left_img.height
                        ))
                        current_page.append(PlacedImage(
                            image=right_img,
                            x=PADDING + half_width + GAP,
                            y=PADDING + current_y,
                            width=right_img.width,
                            height=right_img.height
                        ))
                        current_y += row_height + GAP
                        i += 2
                        continue

            # 单列放置
            if current_y + img.height > self.content_height:
                if current_page:
                    pages.append(current_page)
                    current_page = []
                    current_y = 0

            current_page.append(PlacedImage(
                image=img,
                x=PADDING,
                y=PADDING + current_y,
                width=img.width,
                height=img.height
            ))
            current_y += img.height + GAP
            i += 1

        if current_page:
            pages.append(current_page)

        return pages

    def _fit_to_width(self, img: Image.Image, target_width: int) -> Image.Image:
        """缩放图片以适应目标宽度"""
        if img.width <= target_width:
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


def stitch_images_to_a4(image_bytes_list: list[bytes]) -> list[bytes]:
    """
    便捷函数：将图片字节数据拼接成A4页面

    Args:
        image_bytes_list: 图片字节数据列表

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
        images.append(img)

    stitcher = ImageStitcher()
    pages = stitcher.stitch(images)

    result = []
    for page in pages:
        buffer = BytesIO()
        page.save(buffer, format='PNG', dpi=(300, 300))
        result.append(buffer.getvalue())

    return result
