(() => {
  const $ = (selector) => document.querySelector(selector);
  const toastEl = $("#toast");

  function toast(message) {
    if (!toastEl) return;
    toastEl.textContent = message;
    toastEl.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { toastEl.hidden = true; }, 3500);
  }

  const mode = document.body.dataset.authMode || "login";

  // ---------- Đăng nhập ----------
  const loginForm = $("#loginForm");
  loginForm?.addEventListener("submit", (event) => {
    if (window.firebaseAuthFlow) {
      window.firebaseAuthFlow.authenticate(event, "login", toast);
    } else {
      event.preventDefault();
      toast("Không thể khởi tạo xác thực. Hãy tải lại trang.");
    }
  });

  // ---------- Đăng ký ----------
  const registerForm = $("#registerForm");
  registerForm?.addEventListener("submit", (event) => {
    if (window.firebaseAuthFlow) {
      window.firebaseAuthFlow.authenticate(event, "register", toast);
    } else {
      event.preventDefault();
      toast("Không thể khởi tạo xác thực. Hãy tải lại trang.");
    }
  });

  // ---------- Đăng nhập bằng Google / Facebook ----------
  $("#googleLoginBtn")?.addEventListener("click", () => {
    window.firebaseAuthFlow?.signInWithGoogle(toast);
  });
  $("#facebookLoginBtn")?.addEventListener("click", () => {
    window.firebaseAuthFlow?.signInWithFacebook(toast);
  });

  // ---------- Quên mật khẩu (chỉ có ở trang đăng nhập) ----------
  const loginView = $("#loginView");
  const forgotView = $("#forgotView");
  const forgotLink = $("#forgotPasswordLink");
  const backToLoginBtn = $("#backToLoginBtn");
  const sendResetBtn = $("#sendResetBtn");
  const forgotEmailInput = $("#forgotEmail");

  forgotLink?.addEventListener("click", () => {
    if (loginView) loginView.hidden = true;
    if (forgotView) forgotView.hidden = false;
    forgotEmailInput?.focus();
  });

  backToLoginBtn?.addEventListener("click", () => {
    if (forgotView) forgotView.hidden = true;
    if (loginView) loginView.hidden = false;
  });

  sendResetBtn?.addEventListener("click", async () => {
    if (!window.firebaseAuthFlow) {
      toast("Không thể khởi tạo xác thực. Hãy tải lại trang.");
      return;
    }
    sendResetBtn.disabled = true;
    try {
      const ok = await window.firebaseAuthFlow.sendPasswordReset(forgotEmailInput?.value || "", toast);
      if (ok && forgotEmailInput) forgotEmailInput.value = "";
    } finally {
      sendResetBtn.disabled = false;
    }
  });

  if (mode === "register") {
    document.title = "Đăng ký — Sổ Nghiên Cứu";
  } else {
    document.title = "Đăng nhập — Sổ Nghiên Cứu";
  }
})();
