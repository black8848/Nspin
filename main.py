"""错题拼接打印服务"""

import base64
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response

from image_stitcher import stitch_images_to_a4, stitch_images_to_pdf
from question_extractor import extract_questions_from_images
from exam_formatter import render_questions_to_pdf

app = FastAPI(title="错题拼接打印服务")

ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB per file


def validate_image(filename: str, size: int) -> None:
    """验证上传的图片"""
    ext = '.' + filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"不支持的文件格式: {ext}")
    if size > MAX_FILE_SIZE:
        raise HTTPException(400, f"文件过大: {filename}")


@app.post("/api/stitch")
async def stitch_images(files: list[UploadFile] = File(...)):
    """
    上传多张图片，拼接成A4页面

    Returns:
        JSON包含base64编码的图片列表
    """
    if not files:
        raise HTTPException(400, "请上传至少一张图片")

    image_bytes_list = []
    for file in files:
        content = await file.read()
        validate_image(file.filename or "unknown", len(content))
        image_bytes_list.append(content)

    try:
        pages = stitch_images_to_a4(image_bytes_list)
    except Exception as e:
        raise HTTPException(500, f"图片处理失败: {str(e)}")

    if not pages:
        raise HTTPException(500, "生成页面失败")

    # 返回base64编码的图片列表
    images_base64 = [base64.b64encode(page).decode('utf-8') for page in pages]
    return JSONResponse({"pages": images_base64})


@app.post("/api/stitch/pdf")
async def stitch_images_pdf(files: list[UploadFile] = File(...)):
    """
    上传多张图片，拼接成A4页面并生成PDF
    """
    if not files:
        raise HTTPException(400, "请上传至少一张图片")

    image_bytes_list = []
    for file in files:
        content = await file.read()
        validate_image(file.filename or "unknown", len(content))
        image_bytes_list.append(content)

    try:
        pdf_data = stitch_images_to_pdf(image_bytes_list)
    except Exception as e:
        raise HTTPException(500, f"PDF生成失败: {str(e)}")

    return Response(
        content=pdf_data,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=output.pdf"}
    )


@app.post("/api/exam/pdf")
async def generate_exam_pdf(files: list[UploadFile] = File(...)):
    """
    OCR识别图片中的题目，生成试卷样式PDF
    """
    if not files:
        raise HTTPException(400, "请上传至少一张图片")

    image_bytes_list = []
    for file in files:
        content = await file.read()
        validate_image(file.filename or "unknown", len(content))
        image_bytes_list.append(content)

    try:
        questions = extract_questions_from_images(image_bytes_list)
        if not questions:
            raise HTTPException(400, "未能识别到任何题目")
        pdf_data = render_questions_to_pdf(questions)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"处理失败: {str(e)}")

    return Response(
        content=pdf_data,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=exam.pdf"}
    )


@app.get("/", response_class=HTMLResponse)
async def index():
    """返回前端页面"""
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>错题拼接打印</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #f5f5f5;
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
        }
        h1 {
            text-align: center;
            color: #333;
            margin-bottom: 20px;
        }
        .mode-toggle {
            display: flex;
            justify-content: center;
            margin-bottom: 20px;
            background: white;
            border-radius: 8px;
            padding: 4px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        .mode-btn {
            flex: 1;
            padding: 12px 20px;
            border: none;
            background: transparent;
            cursor: pointer;
            font-size: 14px;
            border-radius: 6px;
            transition: all 0.3s;
            color: #666;
        }
        .mode-btn.active {
            background: #007bff;
            color: white;
        }
        .upload-area {
            background: white;
            border: 2px dashed #ccc;
            border-radius: 12px;
            padding: 60px 20px;
            text-align: center;
            cursor: pointer;
            transition: all 0.3s;
        }
        .upload-area:hover, .upload-area.dragover {
            border-color: #007bff;
            background: #f8f9ff;
        }
        .upload-area input { display: none; }
        .upload-icon {
            font-size: 48px;
            margin-bottom: 15px;
        }
        .upload-text { color: #666; font-size: 16px; }
        .preview-area {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }
        .preview-item {
            position: relative;
            background: white;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        .preview-item img {
            width: 100%;
            height: 120px;
            object-fit: cover;
        }
        .preview-item .remove {
            position: absolute;
            top: 5px;
            right: 5px;
            width: 24px;
            height: 24px;
            background: rgba(255,0,0,0.8);
            color: white;
            border: none;
            border-radius: 50%;
            cursor: pointer;
            font-size: 14px;
            line-height: 24px;
        }
        .preview-item .order {
            position: absolute;
            top: 5px;
            left: 5px;
            width: 24px;
            height: 24px;
            background: rgba(0,123,255,0.9);
            color: white;
            border-radius: 50%;
            font-size: 12px;
            line-height: 24px;
            text-align: center;
        }
        .actions {
            margin-top: 20px;
            text-align: center;
        }
        .btn {
            padding: 12px 40px;
            font-size: 16px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.3s;
        }
        .btn-primary {
            background: #007bff;
            color: white;
        }
        .btn-primary:hover { background: #0056b3; }
        .btn-primary:disabled {
            background: #ccc;
            cursor: not-allowed;
        }
        .btn-secondary {
            background: #6c757d;
            color: white;
            margin-left: 10px;
        }
        .status {
            margin-top: 15px;
            padding: 10px;
            border-radius: 8px;
            text-align: center;
        }
        .status.loading { background: #fff3cd; color: #856404; }
        .status.success { background: #d4edda; color: #155724; }
        .status.error { background: #f8d7da; color: #721c24; }
        .tip {
            margin-top: 20px;
            padding: 15px;
            background: #e7f3ff;
            border-radius: 8px;
            color: #0c5460;
            font-size: 14px;
        }
        .result-area {
            margin-top: 20px;
            display: none;
        }
        .result-item {
            background: white;
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 15px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        .result-item h3 {
            margin-bottom: 10px;
            color: #333;
            font-size: 16px;
        }
        .result-item img {
            width: 100%;
            border: 1px solid #eee;
            border-radius: 4px;
        }
        .result-item .save-tip {
            margin-top: 10px;
            font-size: 12px;
            color: #666;
            text-align: center;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>错题拼接打印</h1>

        <div class="mode-toggle">
            <button class="mode-btn active" data-mode="stitch">截图拼接</button>
            <button class="mode-btn" data-mode="exam">试卷模式</button>
        </div>

        <div class="upload-area" id="uploadArea">
            <div class="upload-icon">📷</div>
            <div class="upload-text">点击或拖拽上传错题截图</div>
            <div class="upload-text" style="font-size:12px;color:#999;margin-top:8px;">支持 PNG、JPG、WEBP 格式，可多选</div>
            <input type="file" id="fileInput" multiple accept="image/*">
        </div>

        <div class="preview-area" id="previewArea"></div>

        <div class="actions" id="actions" style="display:none;">
            <button class="btn btn-primary" id="submitBtn">生成PDF打印</button>
            <button class="btn btn-secondary" id="clearBtn">清空</button>
        </div>

        <div class="status" id="status" style="display:none;"></div>

        <div class="result-area" id="resultArea"></div>

        <div class="tip" id="tipStitch">
            <strong>截图拼接模式：</strong><br>
            将多张截图按原样拼接成A4横向PDF，每页4张图片
        </div>
        <div class="tip" id="tipExam" style="display:none;">
            <strong>试卷模式：</strong><br>
            OCR识别截图中的题目，按试卷样式重新排版（题干+选项）
        </div>
    </div>

    <script>
        const uploadArea = document.getElementById('uploadArea');
        const fileInput = document.getElementById('fileInput');
        const previewArea = document.getElementById('previewArea');
        const actions = document.getElementById('actions');
        const submitBtn = document.getElementById('submitBtn');
        const clearBtn = document.getElementById('clearBtn');
        const status = document.getElementById('status');
        const resultArea = document.getElementById('resultArea');
        const tipStitch = document.getElementById('tipStitch');
        const tipExam = document.getElementById('tipExam');
        const modeBtns = document.querySelectorAll('.mode-btn');

        let files = [];
        let currentMode = 'stitch';

        // 模式切换
        modeBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                modeBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                currentMode = btn.dataset.mode;

                tipStitch.style.display = currentMode === 'stitch' ? 'block' : 'none';
                tipExam.style.display = currentMode === 'exam' ? 'block' : 'none';
            });
        });

        uploadArea.addEventListener('click', () => fileInput.click());
        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.classList.add('dragover');
        });
        uploadArea.addEventListener('dragleave', () => {
            uploadArea.classList.remove('dragover');
        });
        uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadArea.classList.remove('dragover');
            addFiles(e.dataTransfer.files);
        });
        fileInput.addEventListener('change', () => {
            addFiles(fileInput.files);
            fileInput.value = '';
        });

        function addFiles(newFiles) {
            for (const file of newFiles) {
                if (file.type.startsWith('image/')) {
                    files.push(file);
                }
            }
            renderPreviews();
        }

        function renderPreviews() {
            previewArea.innerHTML = '';
            files.forEach((file, index) => {
                const div = document.createElement('div');
                div.className = 'preview-item';
                div.draggable = true;
                div.dataset.index = index;

                const img = document.createElement('img');
                img.src = URL.createObjectURL(file);

                const order = document.createElement('span');
                order.className = 'order';
                order.textContent = index + 1;

                const remove = document.createElement('button');
                remove.className = 'remove';
                remove.textContent = '×';
                remove.onclick = () => {
                    files.splice(index, 1);
                    renderPreviews();
                };

                div.appendChild(img);
                div.appendChild(order);
                div.appendChild(remove);

                // 拖拽排序
                div.addEventListener('dragstart', (e) => {
                    e.dataTransfer.setData('text/plain', index);
                    div.style.opacity = '0.5';
                });
                div.addEventListener('dragend', () => div.style.opacity = '1');
                div.addEventListener('dragover', (e) => e.preventDefault());
                div.addEventListener('drop', (e) => {
                    e.preventDefault();
                    const fromIndex = parseInt(e.dataTransfer.getData('text/plain'));
                    const toIndex = index;
                    if (fromIndex !== toIndex) {
                        const [moved] = files.splice(fromIndex, 1);
                        files.splice(toIndex, 0, moved);
                        renderPreviews();
                    }
                });

                previewArea.appendChild(div);
            });

            actions.style.display = files.length > 0 ? 'block' : 'none';
        }

        clearBtn.addEventListener('click', () => {
            files = [];
            renderPreviews();
            status.style.display = 'none';
            resultArea.style.display = 'none';
            resultArea.innerHTML = '';
        });

        submitBtn.addEventListener('click', async () => {
            if (files.length === 0) return;

            submitBtn.disabled = true;
            const apiUrl = currentMode === 'exam' ? '/api/exam/pdf' : '/api/stitch/pdf';
            const loadingText = currentMode === 'exam' ? '正在识别并生成试卷...' : '正在生成PDF...';

            status.className = 'status loading';
            status.textContent = loadingText;
            status.style.display = 'block';
            resultArea.style.display = 'none';
            resultArea.innerHTML = '';

            const formData = new FormData();
            files.forEach(file => formData.append('files', file));

            try {
                const response = await fetch(apiUrl, {
                    method: 'POST',
                    body: formData
                });

                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || '处理失败');
                }

                const blob = await response.blob();
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = currentMode === 'exam' ? 'exam.pdf' : 'output.pdf';
                a.click();
                URL.revokeObjectURL(url);

                status.className = 'status success';
                status.textContent = '生成成功！PDF已开始下载';
            } catch (err) {
                status.className = 'status error';
                status.textContent = '错误: ' + err.message;
            } finally {
                submitBtn.disabled = false;
            }
        });
    </script>
</body>
</html>"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
