(() => {
  const $ = (selector) => document.querySelector(selector);

  // Trước đây các nút này mở modal đăng nhập/đăng ký ngay trên trang landing.
  // Giờ chuyển hướng sang trang riêng /login và /register (xem app.py, auth.html).
  function goToLogin() {
    window.location.href = "/login";
  }
  function goToRegister() {
    window.location.href = "/register";
  }

  function bindAuthButtons() {
    $("#landingLoginBtn")?.addEventListener("click", goToLogin);
    $("#landingRegisterBtn")?.addEventListener("click", goToRegister);
  }

  bindAuthButtons();

  const landingContent = $("#landingContent");
  const contentMap = {
    overview: '<div class="content-block"><span class="eyebrow">NotebookLM Clone</span><h1>Sổ Nghiên Cứu</h1><p>Một không gian làm việc thông minh để đọc tài liệu, tìm thông tin nhanh, tạo tóm tắt, quiz, mind map và flashcard chỉ trong một nơi.</p><div class="landing-actions"><button type="button" class="btn-primary" id="landingLoginBtn">Đăng nhập</button><button type="button" class="btn-secondary landing-register" id="landingRegisterBtn">Đăng ký</button></div></div>',
    features: '<div class="content-block"><span class="eyebrow">Tính năng</span><h2>Giới thiệu tính năng</h2><ul class="feature-list"><li>Chat AI theo tài liệu để trả lời nhanh và chính xác hơn.</li><li>Tạo tóm tắt từ PDF, DOCX, TXT, MD và ảnh scan OCR.</li><li>Hỗ trợ quiz, mind map và flashcard để ôn tập hiệu quả.</li><li>Quản lý nhiều notebook và nguồn tài liệu trong một giao diện.</li></ul></div>',
    guide: '<div class="content-block"><span class="eyebrow">Hướng dẫn</span><h2>Hướng dẫn sử dụng</h2><ol class="step-list"><li>Đăng nhập hoặc đăng ký tài khoản mới.</li><li>Tạo notebook và tải tài liệu lên hệ thống.</li><li>Chọn tài liệu, hỏi AI và tạo nội dung ôn tập.</li></ol></div>',
    contact: '<div class="content-block"><span class="eyebrow">Liên hệ</span><h2>Thông tin liên hệ</h2><ul class="contact-list"><li><strong>Gmail:</strong> your-email@example.com</li><li><strong>Facebook:</strong> facebook.com/your-profile</li></ul></div>',
  };

  document.querySelectorAll(".nav-pill").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".nav-pill").forEach((item) => item.classList.toggle("active", item === button));
      landingContent.innerHTML = contentMap[button.dataset.target] || contentMap.overview;
      bindAuthButtons();
    });
  });
})();
