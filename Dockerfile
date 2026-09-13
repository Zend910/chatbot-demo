FROM python:3.10-slim

# Cài đặt Tesseract OCR và các gói hỗ trợ tiếng Việt/Anh
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libtesseract-dev \
    tesseract-ocr-vie \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=10000
EXPOSE 10000

CMD ["python", "app.py"]