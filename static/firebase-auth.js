(() => {
  const config = window.FIREBASE_CONFIG || {};
  const required = ["apiKey", "authDomain", "projectId", "appId"];

  function configured() {
    return required.every((key) => config[key]);
  }

  function friendlyError(error) {
    const messages = {
      "auth/email-already-in-use": "Email này đã được đăng ký. Hãy chuyển sang Đăng nhập.",
      "auth/invalid-email": "Địa chỉ email không hợp lệ.",
      "auth/invalid-credential": "Email hoặc mật khẩu không đúng.",
      "auth/wrong-password": "Email hoặc mật khẩu không đúng.",
      "auth/user-not-found": "Email này chưa được đăng ký.",
      "auth/weak-password": "Mật khẩu phải có ít nhất 6 ký tự.",
      "auth/api-key-not-valid": "Firebase API key không hợp lệ. Hãy kiểm tra lại firebase-config.js.",
      "auth/popup-closed-by-user": "Cửa sổ đăng nhập đã bị đóng trước khi hoàn tất.",
      "auth/account-exists-with-different-credential": "Email này đã được đăng ký bằng phương thức khác.",
      "auth/popup-blocked": "Trình duyệt đã chặn cửa sổ đăng nhập. Hãy cho phép popup rồi thử lại.",
    };
    return messages[error.code] || error.message || "Không thể xác thực Firebase.";
  }

  // "Ghi nhớ đăng nhập": đọc từ ô checkbox #rememberMeCheckbox nếu có trên trang
  // (trang /login có, trang khác không có thì mặc định coi như có ghi nhớ).
  function rememberChecked() {
    const el = document.querySelector("#rememberMeCheckbox");
    return el ? !!el.checked : true;
  }

  async function loginLegacyAccount(identifier, password, toast) {
    const response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: identifier, password, remember: rememberChecked() }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      toast(data.error || "Tên đăng nhập hoặc mật khẩu không đúng.");
      return false;
    }
    window.location.href = "/chat";
    return true;
  }

  async function establishSessionFromCredential(credential) {
    const response = await fetch("/api/auth/firebase", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id_token: await credential.user.getIdToken(), remember: rememberChecked() }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `Lỗi ${response.status}`);
    window.location.href = "/chat";
  }

  async function authenticate(event, mode, toast) {
    event.preventDefault();
    if (!configured()) {
      toast("Chưa cấu hình Firebase Web app trong static/firebase-config.js.");
      return;
    }

    const identifier = document.querySelector("#authIdentifier").value.trim();
    const username = document.querySelector("#authUsername")?.value.trim() || "";
    const password = document.querySelector("#authPassword").value;
    const confirm = document.querySelector("#authConfirmPassword");
    const agreeTerms = document.querySelector("#agreeTermsCheckbox");
    if (!identifier || !password || (mode === "register" && !username)) {
      toast(mode === "register" ? "Username, email và mật khẩu không được để trống." : "Username/email và mật khẩu không được để trống.");
      return;
    }
    if (mode === "register" && (password.length < 6 || password !== confirm?.value)) {
      toast(password.length < 6 ? "Mật khẩu phải có ít nhất 6 ký tự." : "Mật khẩu xác nhận không khớp.");
      return;
    }
    if (mode === "register" && agreeTerms && !agreeTerms.checked) {
      toast("Bạn cần đồng ý với điều khoản & điều kiện để đăng ký.");
      return;
    }

    try {
      const auth = firebase.auth();
      let credential;
      if (mode === "register") {
        if (!identifier.includes("@")) {
          toast("Trường email phải chứa @.");
          return;
        }
        credential = await auth.createUserWithEmailAndPassword(identifier, password);
        const profileResponse = await fetch("/api/auth/firebase/profile", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            username,
            id_token: await credential.user.getIdToken(),
          }),
        });
        const profileData = await profileResponse.json().catch(() => ({}));
        if (!profileResponse.ok) {
          await credential.user.delete().catch(() => {});
          throw new Error(profileData.error || `Lỗi ${profileResponse.status}`);
        }
        await credential.user.sendEmailVerification();
        await auth.signOut();
        toast("Đã gửi email xác thực. Hãy xác thực email trước khi đăng nhập.");
        return;
      }

      let email = identifier;
      if (!identifier.includes("@")) {
        const lookupResponse = await fetch("/api/auth/firebase/identifier", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ identifier }),
        });
        const lookupData = await lookupResponse.json().catch(() => ({}));
        if (!lookupResponse.ok) {
          if (lookupResponse.status === 404) {
            await loginLegacyAccount(identifier, password, toast);
            return;
          }
          throw new Error(lookupData.error || `Lỗi ${lookupResponse.status}`);
        }
        email = lookupData.email;
      }
      credential = await auth.signInWithEmailAndPassword(email, password);
      await credential.user.reload();
      if (!credential.user.emailVerified) {
        await auth.signOut();
        toast("Email chưa được xác thực. Hãy kiểm tra hộp thư rồi đăng nhập lại.");
        return;
      }

      await establishSessionFromCredential(credential);
    } catch (error) {
      await firebase.auth().signOut().catch(() => {});
      toast(friendlyError(error));
    }
  }

  // Đăng nhập bằng Google — dùng chung endpoint /api/auth/firebase với đăng nhập
  // email/password (endpoint đó chỉ cần một Firebase ID token hợp lệ đã có email).
  async function signInWithGoogle(toast) {
    if (!configured()) {
      toast("Chưa cấu hình Firebase Web app trong static/firebase-config.js.");
      return;
    }
    try {
      const provider = new firebase.auth.GoogleAuthProvider();
      const credential = await firebase.auth().signInWithPopup(provider);
      await establishSessionFromCredential(credential);
    } catch (error) {
      await firebase.auth().signOut().catch(() => {});
      toast(friendlyError(error));
    }
  }

  // Đăng nhập bằng Facebook — cần bật Facebook làm nhà cung cấp đăng nhập trong
  // Firebase Console (Authentication > Sign-in method) và nhập App ID/Secret của
  // Facebook Developer thì nút này mới hoạt động.
  async function signInWithFacebook(toast) {
    if (!configured()) {
      toast("Chưa cấu hình Firebase Web app trong static/firebase-config.js.");
      return;
    }
    try {
      const provider = new firebase.auth.FacebookAuthProvider();
      const credential = await firebase.auth().signInWithPopup(provider);
      await establishSessionFromCredential(credential);
    } catch (error) {
      await firebase.auth().signOut().catch(() => {});
      toast(friendlyError(error));
    }
  }

  // Quên mật khẩu: xác thực chủ sở hữu email bằng liên kết Firebase gửi qua
  // email (bấm liên kết = đã xác thực), sau đó Firebase cho đặt mật khẩu mới.
  // Đây là bước "xác thực email trước rồi mới được đổi mật khẩu" mà không cần
  // biết mật khẩu cũ.
  async function sendPasswordReset(identifier, toast) {
    if (!configured()) {
      toast("Chưa cấu hình Firebase Web app trong static/firebase-config.js.");
      return false;
    }
    const value = (identifier || "").trim();
    if (!value) {
      toast("Hãy nhập username hoặc email để đặt lại mật khẩu.");
      return false;
    }
    try {
      let email = value;
      if (!value.includes("@")) {
        const lookupResponse = await fetch("/api/auth/firebase/identifier", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ identifier: value }),
        });
        const lookupData = await lookupResponse.json().catch(() => ({}));
        if (!lookupResponse.ok) {
          throw new Error(lookupData.error || "Không tìm thấy tài khoản này hoặc tài khoản chưa có email.");
        }
        email = lookupData.email;
      }
      await firebase.auth().sendPasswordResetEmail(email);
      toast("Đã gửi email đặt lại mật khẩu. Hãy kiểm tra hộp thư (và mục spam).");
      return true;
    } catch (error) {
      toast(friendlyError(error));
      return false;
    }
  }

  if (configured()) {
    firebase.initializeApp(config);
  }
  window.firebaseAuthFlow = { authenticate, signInWithGoogle, signInWithFacebook, sendPasswordReset };
})();
