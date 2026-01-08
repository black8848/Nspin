# 错题拼接打印

将手机截图拼接成 A4 横向 PDF，方便打印。

## 功能

- 上传多张手机截图
- 自动裁切状态栏和底部横条
- 每页 4 张图片，横向排列
- 支持拖拽排序
- 一键生成 PDF 下载

## 安装

```bash
pip install -r requirements.txt
```

## 运行

```bash
python main.py
```

访问 http://localhost:8000

## 配置

编辑 `image_stitcher.py` 顶部常量：

```python
CROP_TOP_PERCENT = 5      # 顶部裁切比例
CROP_BOTTOM_PERCENT = 3   # 底部裁切比例
COLUMNS = 4               # 每页图片数量
```
