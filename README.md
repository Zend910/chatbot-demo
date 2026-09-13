# Sổ Nghiên Cứu — chatbot kiểu NotebookLM, chạy local

Ứng dụng web chạy hoàn toàn trên máy bạn (Flask + trình duyệt), dùng Google Gemini
API bản **miễn phí** (không cần thẻ tín dụng). Tải tài liệu lên, hỏi đáp có trích
dẫn nguồn, tóm tắt đa tài liệu, tạo bộ câu hỏi ôn tập, và tạo audio overview kiểu
podcast 2 người dẫn — giống các chức năng chính của NotebookLM.

## 1. Cài đặt

Yêu cầu: Python 3.9+.

```bash
cd notebooklm-clone
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**Lưu ý về TTS (tạo audio overview):** thư viện `pyttsx3` dùng engine giọng nói có
sẵn trên hệ điều hành.
- macOS / Windows: thường có sẵn, không cần cài thêm.
- Linux: cần cài `espeak` hoặc `espeak-ng` trước:
  ```bash
  sudo apt-get install espeak-ng
  ```
Nếu máy có từ 2 giọng đọc trở lên, hai "người dẫn" A/B trong audio overview sẽ
dùng 2 giọng khác nhau; nếu chỉ có 1 giọng, ứng dụng sẽ đọc với 2 tốc độ khác
nhau để dễ phân biệt. Chất lượng giọng tiếng Việt qua TTS offline có thể không
tự nhiên bằng dịch vụ TTS trên mây — đây là đánh đổi để mọi thứ chạy 100% local.

**Lưu ý về OCR (đọc PDF/ảnh scan):** cần cài chương trình **Tesseract OCR** trên
máy (thư viện `pytesseract` chỉ là lớp gọi tới nó):

- macOS: `brew install tesseract tesseract-lang` (gói `tesseract-lang` có dữ liệu
  tiếng Việt).
- Linux (Debian/Ubuntu): `sudo apt-get install tesseract-ocr tesseract-ocr-vie`
- Windows: cài từ https://github.com/UB-Mannheim/tesseract/wiki (khi cài, chọn
  thêm gói ngôn ngữ Vietnamese), sau đó thêm đường dẫn cài đặt vào biến môi
  trường `PATH`.

Nếu thiếu gói ngôn ngữ `vie`, ứng dụng sẽ tự động thử lại bằng tiếng Anh thay vì
báo lỗi. Nếu hoàn toàn chưa cài Tesseract, app sẽ báo lỗi rõ ràng khi bạn tải
lên một PDF/ảnh cần OCR (các PDF có sẵn text vẫn hoạt động bình thường, không
cần Tesseract).

## 2. Lấy Google AI API key (MIỄN PHÍ, không cần thẻ)

Chatbot dùng Gemini API (của Google) để trả lời câu hỏi, tóm tắt, tạo quiz và
kịch bản podcast — có gói **miễn phí**, chỉ cần tài khoản Google, không cần
nhập thẻ tín dụng.

1. Vào **https://aistudio.google.com/apikey**
2. Đăng nhập bằng tài khoản Google.
3. Bấm **"Create API key"** (hoặc "Get API key" → "Create API key in new project").
4. Copy đoạn mã hiện ra (dạng `AIza...`).

Gói miễn phí có giới hạn số lượt gọi mỗi phút/mỗi ngày (đủ dùng thoải mái cho
một người dùng cá nhân); nếu dùng nhiều và bị báo lỗi giới hạn tốc độ, chỉ cần
đợi một chút rồi thử lại.

## 3. Chạy ứng dụng

```bash
python app.py
```

Mở trình duyệt tại **http://127.0.0.1:5050**.

## 4. Bật Firebase Email Verification

Tính năng đăng ký/đăng nhập bằng email dùng Firebase Authentication. Firebase Web
config không phải bí mật, nhưng Service Account của Firebase là bí mật và không
được đưa vào thư mục `static/` hoặc commit lên git.

1. Vào **https://console.firebase.google.com/** và tạo/chọn project.
2. Mở **Authentication → Sign-in method**, bật **Email/Password**.
3. Vào **Project settings → General → Your apps**, tạo Web app và copy config.
4. Dán các giá trị `apiKey`, `authDomain`, `projectId`, `appId` vào
  `static/firebase-config.js`.
5. Vào **Project settings → Service accounts → Generate new private key**, tải
  file JSON về máy và đặt ở vị trí riêng ngoài source code.
6. Trên PowerShell, khai báo đường dẫn Service Account trước khi chạy app:

  ```powershell
  $env:FIREBASE_SERVICE_ACCOUNT_JSON = "C:\secure\firebase-service-account.json"
  .\venv\Scripts\python.exe app.py
  ```

Sau khi cấu hình, đăng ký sẽ gọi `createUserWithEmailAndPassword()` rồi
`sendEmailVerification()`. Người dùng chưa xác thực sẽ bị `signOut()` ngay khi
đăng nhập; người đã xác thực mới được gửi Firebase ID token về Flask để tạo
session. Nếu thấy lỗi `Chưa cấu hình FIREBASE_SERVICE_ACCOUNT_JSON`, hãy kiểm tra
biến môi trường ở đúng cửa sổ PowerShell đang chạy Flask.

Vào **Cài đặt** (góc trên bên phải) → dán API key → model mặc định để nguyên
`gemini-2.5-flash` (đủ tốt và miễn phí) → **Lưu**.

## 5. Sử dụng

1. **Tạo sổ tay mới** ở góc trên.
2. **Tải lên** tài liệu (PDF, DOCX, TXT, MD, hoặc ảnh PNG/JPG) ở cột "Nguồn" bên
   trái. Với PDF, từng trang được thử trích xuất text trước; trang nào không có
   text (ảnh scan) sẽ tự động OCR — tài liệu có trang OCR sẽ hiện nhãn **OCR**
   cạnh tên. Ảnh tải lên trực tiếp luôn được OCR toàn bộ.
3. **Đặt câu hỏi** ở khung chat giữa — câu trả lời sẽ có số trích dẫn `[1]`,
   `[2]`… kèm danh sách nguồn (tên tài liệu + vị trí + đoạn trích) ngay bên dưới.
4. Ở cột **Xưởng** bên phải:
   - **Tóm tắt**: tổng hợp nội dung của tất cả tài liệu trong sổ tay.
   - **Quiz**: bộ câu hỏi trắc nghiệm để ôn tập, có giải thích đáp án.
   - **Audio**: kịch bản trò chuyện 2 người dẫn + file audio để nghe/tải về.

## Kiến trúc (tóm tắt cho ai muốn chỉnh sửa)

```
app.py            Flask routes (API + phục vụ giao diện)
storage.py         Lưu notebook/tài liệu/lịch sử chat vào data/notebooks.json
ingest.py           Đọc PDF/DOCX/TXT/MD/ảnh (kèm OCR cho trang scan), chia chunk
retrieval.py        Truy hồi đoạn liên quan bằng TF-IDF (không cần embedding API)
llm_client.py       Gọi Gemini API: hỏi đáp có trích dẫn, tóm tắt, quiz, kịch bản podcast
audio.py            Chuyển kịch bản thành file .wav bằng TTS offline (pyttsx3)
config.py           Lưu API key/model cục bộ trong data/config.json
templates/, static/ Giao diện web (HTML/CSS/JS thuần, không cần build)
```

Toàn bộ dữ liệu (tài liệu đã tải, lịch sử chat, audio đã tạo) lưu trong thư mục
`data/` ngay cạnh `app.py` — xóa thư mục này nếu muốn reset sạch.

## Giới hạn hiện tại

- Truy hồi dùng TF-IDF (từ khóa) thay vì embedding ngữ nghĩa — đủ tốt cho hầu hết
  câu hỏi nhưng kém hơn embedding thật với câu hỏi diễn đạt rất khác từ ngữ gốc.
- OCR chạy qua Tesseract offline — nhanh và miễn phí, nhưng độ chính xác với chữ
  viết tay, ảnh mờ/nghiêng, hoặc font lạ sẽ kém hơn các dịch vụ OCR cloud trả phí.
- Giọng đọc audio overview phụ thuộc voice TTS có sẵn trên máy, chưa hỗ trợ giọng
  đọc tiếng Việt chất lượng cao kiểu cloud TTS.
- Gói Gemini miễn phí có giới hạn số lượt gọi/phút và /ngày. Nếu gặp lỗi kiểu
  "quota" hoặc "rate limit", đợi khoảng 1 phút rồi thử lại.

## Xử lý lỗi thường gặp khi cài đặt

- **Gõ lệnh `cd ...` báo "filename, directory name, or volume label syntax is
  incorrect"**: thường do thiếu dấu cách giữa `cd` và đường dẫn (ví dụ dán vào
  bị dính liền thành `cdC:\...`). Sửa lại thành `cd C:\đường\dẫn\notebooklm-clone`.
- **`pip install -r requirements.txt` báo lỗi đỏ khi cài `numpy` (hoặc gói
  khác) do thiếu công cụ biên dịch**: cài từng gói không ép phiên bản cụ thể:
  ```bash
  pip install flask google-generativeai pypdf python-docx scikit-learn numpy pyttsx3 pymupdf pytesseract pillow
  ```
- **App báo "Chưa cấu hình Google AI API key"**: vào **Cài đặt** trong app, dán
  lại key, bấm **Lưu**.
