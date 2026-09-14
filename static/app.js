(() => {
  const state = {
    notebooks: [],
    currentId: null,
    currentNotebook: null,
    user: null,
    customInstructions: "",
    pendingChatAttachments: [], // ảnh dán vào khung chat (Ctrl+V) — nhất thời, chỉ để gửi kèm câu hỏi, KHÔNG lưu làm nguồn
  };

  // Hướng dẫn tùy chỉnh (Cá nhân hóa) — lưu THEO TỪNG TÀI KHOẢN ở server (không dùng
  // localStorage nữa, vì localStorage dùng chung cho mọi tài khoản đăng nhập trên cùng
  // trình duyệt, khiến admin và user bị lẫn hướng dẫn của nhau).
  const AI_MEMORY_KEY = "ai_memory";

  const $ = (sel) => document.querySelector(sel);
  const workspace = $("#workspace");
  const emptyState = $("#emptyState");
  const notebookSelect = $("#notebookSelect");
  const sourceList = $("#sourceList");
  const sourcesEmpty = $("#sourcesEmpty");
  const selectionCount = $("#selectionCount");
  const selectAllSources = $("#selectAllSources");
  const chatLog = $("#chatLog");
  const chatForm = $("#chatForm");
  const chatInput = $("#chatInput");
  const chatExpandBtn = $("#chatExpandBtn");
  const chatAttachments = $("#chatAttachments");
  const toastEl = $("#toast");
  const quotaNotice = $("#quotaNotice");
  const quotaNoticeText = $("#quotaNoticeText");
  const PERSONAL_API_CONFIG_KEY = "notebooklm-personal-api-config";

  function getCustomInstructions() {
    return state.customInstructions || "";
  }

  async function loadCustomInstructionsFromServer() {
    try {
      const data = await api("/api/account/personalization");
      state.customInstructions = data.custom_instructions || "";
    } catch (_error) {
      state.customInstructions = "";
    }
    return state.customInstructions;
  }

  async function saveCustomInstructionsToServer(value) {
    const text = value || "";
    await api("/api/account/personalization", {
      method: "POST",
      body: JSON.stringify({ custom_instructions: text }),
    });
    state.customInstructions = text;
  }

  function getAiMemory() {
    try {
      const raw = localStorage.getItem(AI_MEMORY_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch (_error) {
      return [];
    }
  }

  function setAiMemory(items) {
    localStorage.setItem(AI_MEMORY_KEY, JSON.stringify(Array.isArray(items) ? items : []));
  }

  function makeMemoryId() {
    return window.crypto && crypto.randomUUID ? crypto.randomUUID() : `memory-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function addAiMemoryEntry(question, answer) {
    const text = (answer || "").replace(/\s+/g, " ").trim();
    if (!text || !question) return;
    const entries = getAiMemory();
    entries.unshift({
      id: makeMemoryId(),
      question: String(question).trim(),
      summary: text.length > 220 ? `${text.slice(0, 217)}...` : text,
      createdAt: Date.now(),
    });
    setAiMemory(entries.slice(0, 20));
  }

  function clearAiMemory() {
    localStorage.removeItem(AI_MEMORY_KEY);
    const list = $("#aiMemoryList");
    if (list) list.innerHTML = "<p class='hint'>Chưa có thông tin bộ nhớ nào.</p>";
  }

  function renderAiMemoryModal() {
    const modal = $("#aiMemoryModal");
    const list = $("#aiMemoryList");
    if (!modal || !list) return;
    const entries = getAiMemory();
    if (!entries.length) {
      list.innerHTML = "<p class='hint'>Chưa có thông tin bộ nhớ nào.</p>";
      openModal(modal);
      return;
    }

    list.innerHTML = entries.map((entry) => `
      <div class="ai-memory-item">
        <div class="ai-memory-meta">${new Date(entry.createdAt || Date.now()).toLocaleString("vi-VN")}</div>
        <div class="ai-memory-question"><strong>Hỏi:</strong> ${escapeHtml(entry.question || "")}</div>
        <div class="ai-memory-summary"><strong>Ghi nhớ:</strong> ${escapeHtml(entry.summary || "")}</div>
        <button type="button" class="btn-ghost small ai-memory-remove" data-memory-id="${entry.id}">Xóa</button>
      </div>
    `).join("");

    list.querySelectorAll(".ai-memory-remove").forEach((button) => {
      button.addEventListener("click", () => {
        const nextEntries = getAiMemory().filter((item) => item.id !== button.dataset.memoryId);
        setAiMemory(nextEntries);
        renderAiMemoryModal();
      });
    });

    openModal(modal);
  }

  function getPersonalApiConfig() {
    try {
      const raw = localStorage.getItem(PERSONAL_API_CONFIG_KEY);
      if (!raw) return { apiKey: "", model: "", provider: "auto" };
      const parsed = JSON.parse(raw);
      return {
        apiKey: String(parsed.apiKey || ""),
        model: String(parsed.model || ""),
        provider: String(parsed.provider || "auto"),
      };
    } catch (_error) {
      return { apiKey: "", model: "", provider: "auto" };
    }
  }

  function setPersonalApiConfig(data = {}) {
    const next = { ...getPersonalApiConfig(), ...data };
    localStorage.setItem(PERSONAL_API_CONFIG_KEY, JSON.stringify(next));
  }

  // Hạn mức sử dụng (tokens/lượt gọi API) được lưu THEO TỪNG TÀI KHOẢN ở server
  // (không dùng localStorage nữa, vì localStorage dùng chung cho mọi tài khoản
  // đăng nhập trên cùng trình duyệt, khiến admin và user bị lẫn số liệu của nhau).
  async function renderUsageStats() {
    const tokenText = document.getElementById("tokensUsedText");
    const limitText = document.getElementById("tokensLimitText");
    const bar = document.getElementById("tokenUsageBar");
    const callsText = document.getElementById("apiCallsText");
    try {
      const res = await fetch("/api/account/usage", { headers: { Accept: "application/json" } });
      const stats = await res.json().catch(() => ({}));
      if (!res.ok) return;
      const tokens = Number(stats.tokens || 0);
      const limit = Number(stats.limit || 100000);
      if (tokenText) tokenText.textContent = tokens.toLocaleString("en-US");
      if (limitText) limitText.textContent = limit.toLocaleString("en-US");
      if (bar) bar.style.width = `${Math.min((tokens / limit) * 100, 100)}%`;
      if (callsText) callsText.textContent = String(Number(stats.calls || 0));
    } catch (_error) {
      /* noop */
    }
  }

  function showQuotaNotice(message) {
    quotaNoticeText.textContent = message;
    quotaNotice.hidden = false;
  }

  $("#dismissQuotaNotice").addEventListener("click", () => {
    quotaNotice.hidden = true;
  });

  function toast(msg) {
    toastEl.textContent = msg;
    toastEl.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => (toastEl.hidden = true), 3500);
  }

  async function api(path, options = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      if (res.status === 401) {
        state.user = null;
        updateAuthUi();
      }
      if (data.code === "quota_exceeded" || res.status === 429) {
        showQuotaNotice("API đã gần hết hoặc vượt hạn mức. Hãy kiểm tra key dự phòng trong Cài đặt.");
      }
      throw new Error(data.error || `Lỗi ${res.status}`);
    }
    if (/\/api\/notebooks\/[^/]+\/(chat|summary|quiz|audio|mindmap|flashcards)$/.test(path)) {
      // Server đã tự cộng dồn hạn mức cho ĐÚNG tài khoản đang đăng nhập ở phía
      // backend (xem _record_usage trong app.py) — ở đây chỉ cần tải lại số liệu
      // mới nhất để hiển thị, không tự cộng dồn ở trình duyệt nữa.
      renderUsageStats();
    }
    return data;
  }

  function updateAuthUi() {
    const userBadge = $("#userBadge");
    const landingIntro = $("#landingIntro");
    const isGuest = !state.user;

    document.body.classList.toggle("landing-mode", isGuest);
    document.body.classList.toggle("app-mode", !isGuest);

    if (state.user) {
      userBadge.hidden = false;
      userBadge.innerHTML = `<i class="fa-solid fa-user"></i> ${escapeHtml(state.user.username)}${state.user.role === "admin" ? " • Admin" : ""}`;
      $("#workspace").hidden = false;
      if (landingIntro) landingIntro.hidden = true;
    } else {
      userBadge.hidden = true;
      $("#workspace").hidden = true;
      $("#emptyState").hidden = true;
      if (landingIntro) landingIntro.hidden = false;
    }
  }

  async function loadAdminNotebooks() {
    const listEl = $("#adminNotebookList");
    try {
      const notebooks = await api("/api/admin/notebooks");
      listEl.innerHTML = notebooks.length
        ? notebooks.map((nb) => `
            <div class="admin-item">
              <strong>${escapeHtml(nb.name)}</strong>
              <small>Owner: ${escapeHtml(nb.owner_username || "Unknown")} · ${escapeHtml(nb.owner_role || "user")} · ${nb.doc_count} tài liệu</small>
            </div>
          `).join("")
        : "<p class='hint'>Chưa có notebook nào.</p>";
    } catch (error) {
      listEl.innerHTML = `<p class='hint'>${escapeHtml(error.message)}</p>`;
    }
  }

  async function loadSession() {
    try {
      const res = await fetch("/api/auth/me", { headers: { Accept: "application/json" } });
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.authenticated) {
        state.user = data.user;
        updateAuthUi();
        await loadNotebooks();
        await loadCustomInstructionsFromServer();
        return true;
      }
      state.user = null;
      updateAuthUi();
      return false;
    } catch (_error) {
      state.user = null;
      updateAuthUi();
      return false;
    }
  }

  // ---------- Notebooks ----------

  async function loadNotebooks(selectId) {
    state.notebooks = await api("/api/notebooks");
    notebookSelect.innerHTML = "";
    state.notebooks.forEach((nb) => {
      const opt = document.createElement("option");
      opt.value = nb.id;
      opt.textContent = nb.name;
      notebookSelect.appendChild(opt);
    });

    if (!state.notebooks.length) {
      emptyState.hidden = false;
      workspace.hidden = true;
      return;
    }
    emptyState.hidden = true;
    workspace.hidden = false;

    const target = selectId || state.currentId || state.notebooks[0].id;
    const exists = state.notebooks.some((n) => n.id === target);
    notebookSelect.value = exists ? target : state.notebooks[0].id;
    await selectNotebook(notebookSelect.value);
  }

  async function selectNotebook(id) {
    state.currentId = id;
    state.currentNotebook = await api(`/api/notebooks/${id}`);
    renderSources();
    renderChatHistory();
    resetStudio();
    renderStudioHistory();
    resumeActiveUploads(id);
  }

  notebookSelect.addEventListener("change", (e) => selectNotebook(e.target.value));

  $("#providerInput")?.addEventListener("change", async (e) => {
    try {
      await api("/api/config", {
        method: "POST",
        body: JSON.stringify({ provider: e.target.value }),
      });
      toast(`Đã chọn ${e.target.options[e.target.selectedIndex].text}.`);
    } catch (error) {
      toast(error.message);
    }
  });

  // ---------- New notebook modal ----------

  const newNotebookModal = $("#newNotebookModal");
  const newNotebookName = $("#newNotebookName");

  function openModal(el) {
    el.hidden = false;
    el.removeAttribute("hidden");
  }
  function closeModal(el) {
    el.hidden = true;
    el.setAttribute("hidden", "");
  }

  const authModal = $("#authModal");
  const authForm = $("#authForm");
  const authUsername = $("#authUsername");
  const authPassword = $("#authPassword");
  const authConfirmPassword = $("#authConfirmPassword");
  const confirmPasswordLabel = $("#confirmPasswordLabel");
  const submitAuthBtn = $("#submitAuthBtn");
  let authMode = "login";

  function setAuthMode(mode) {
    authMode = mode;
    document.querySelectorAll(".auth-tab").forEach((tab) => {
      tab.classList.toggle("active", tab.dataset.authTab === mode);
    });
    const isRegister = mode === "register";
    $("#authIdentifierLabel").textContent = isRegister ? "Email đăng ký" : "Username hoặc email";
    $("#authIdentifier").placeholder = isRegister ? "you@example.com" : "username hoặc you@example.com";
    $("#authUsername").hidden = !isRegister;
    $("#authUsernameLabel").hidden = !isRegister;
    confirmPasswordLabel.hidden = !isRegister;
    authConfirmPassword.hidden = !isRegister;
    submitAuthBtn.textContent = isRegister ? "Đăng ký" : "Đăng nhập";
  }

  document.querySelectorAll(".auth-tab").forEach((tab) => {
    tab.addEventListener("click", () => setAuthMode(tab.dataset.authTab));
  });

  function openAuth(mode) {
    setAuthMode(mode);
    if (authUsername) authUsername.value = "";
    $("#authIdentifier").value = "";
    authPassword.value = "";
    authConfirmPassword.value = "";
    openModal(authModal);
  }

  $("#landingLoginBtn")?.addEventListener("click", () => openAuth("login"));
  $("#landingRegisterBtn")?.addEventListener("click", () => openAuth("register"));

  const landingContent = document.querySelector("#landingContent");

  function renderLandingContent(key) {
    const contentMap = {
      overview: `
        <div class="content-block">
          <span class="eyebrow">NotebookLM Clone</span>
          <h1>Sổ Nghiên Cứu</h1>
          <p> Một không gian làm việc thông minh để đọc tài liệu, tìm thông tin nhanh, tạo tóm tắt, quiz, mind map và flashcard chỉ trong một nơi.</p>
          <div class="landing-actions">
            <button type="button" class="btn-primary" id="landingLoginBtn">Đăng nhập</button>
            <button type="button" class="btn-secondary landing-register" id="landingRegisterBtn">Đăng ký</button>
          </div>
        </div>
      `,
      features: `
        <div class="content-block">
          <span class="eyebrow">Tính năng</span>
          <h2>Giới thiệu tính năng</h2>
          <ul class="feature-list">
            <li>Chat AI theo tài liệu để trả lời nhanh và chính xác hơn.</li>
            <li>Tạo tóm tắt nội dung từ PDF, DOCX, TXT, MD và ảnh scan OCR.</li>
            <li>Hỗ trợ quiz, mind map và flashcard để ôn tập hiệu quả.</li>
            <li>Quản lý nhiều notebook và nguồn tài liệu trong một giao diện đơn giản.</li>
          </ul>
        </div>
      `,
      guide: `
        <div class="content-block">
          <span class="eyebrow">Hướng dẫn</span>
          <h2>Hướng dẫn sử dụng</h2>
          <ol class="step-list">
            <li>Đăng nhập hoặc đăng ký tài khoản mới.</li>
            <li>Tạo notebook và tải tài liệu lên hệ thống.</li>
            <li>Chọn tài liệu cần đọc, hỏi AI và tạo tóm tắt/quiz/flashcard.</li>
            <li>Quản lý và theo dõi nội dung trong từng notebook.</li>
          </ol>
        </div>
      `,
      contact: `
        <div class="content-block">
          <span class="eyebrow">Liên hệ</span>
          <h2>Thông tin liên hệ</h2>
          <ul class="contact-list">
            <li><strong>Gmail:</strong> <a class="contact-link" href="mailto:your-email@example.com">your-email@example.com</a></li>
            <li><strong>Facebook:</strong> <a class="contact-link" href="https://facebook.com/your-profile" target="_blank" rel="noreferrer">facebook.com/your-profile</a></li>
            <li><strong>Zalo:</strong> <a class="contact-link" href="https://zalo.me/your-phone-number" target="_blank" rel="noreferrer">zalo.me/your-phone-number</a></li>
            <li><strong>SĐT:</strong> <a class="contact-link" href="tel:+84901234567">+84 901 234 567</a></li>
          </ul>
        </div>
      `,
    };

    if (!landingContent) return;
    landingContent.innerHTML = contentMap[key] || contentMap.overview;

    const loginBtn = document.querySelector("#landingLoginBtn");
    const registerBtn = document.querySelector("#landingRegisterBtn");
    if (loginBtn) {
      loginBtn.addEventListener("click", () => openAuth("login"));
    }
    if (registerBtn) {
      registerBtn.addEventListener("click", () => openAuth("register"));
    }
  }

  document.querySelectorAll(".nav-pill").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".nav-pill").forEach((item) => {
        item.classList.toggle("active", item === button);
      });
      renderLandingContent(button.dataset.target || "overview");
    });
  });

  authForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (window.firebaseAuthFlow) {
      await window.firebaseAuthFlow.authenticate(event, authMode, toast);
      return;
    }
    const username = $("#authIdentifier").value.trim();
    const password = authPassword.value;
    if (!username || !password) {
      toast("Tên đăng nhập và mật khẩu không được bỏ trống.");
      return;
    }
    if (authMode === "register") {
      if (password.length < 6) {
        toast("Mật khẩu phải có ít nhất 6 ký tự.");
        return;
      }
      if (password !== authConfirmPassword.value) {
        toast("Mật khẩu xác nhận không khớp.");
        return;
      }
    }

    try {
      const endpoint = authMode === "register" ? "/api/auth/register" : "/api/auth/login";
      const payload = await api(endpoint, {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      state.user = payload.user;
      closeModal(authModal);
      updateAuthUi();
      await loadNotebooks();
      await loadCustomInstructionsFromServer();
      toast(authMode === "register" ? "Đăng ký thành công." : "Đăng nhập thành công.");
    } catch (error) {
      toast(error.message);
    }
  });

  $("#newNotebookBtn").addEventListener("click", () => {
    newNotebookName.value = "";
    openModal(newNotebookModal);
    newNotebookName.focus();
  });
  $("#deleteNotebookBtn")?.addEventListener("click", async () => {
    if (!state.currentId || !state.currentNotebook) {
      toast("Chưa có sổ tay nào để xóa.");
      return;
    }
    const name = state.currentNotebook.name || "sổ tay này";
    const confirmed = window.confirm(
      `Xóa "${name}"? Toàn bộ tài liệu, lịch sử trò chuyện và sản phẩm Studio trong sổ tay này sẽ bị xóa vĩnh viễn. Hành động này không thể hoàn tác.`
    );
    if (!confirmed) return;
    try {
      await api(`/api/notebooks/${state.currentId}`, { method: "DELETE" });
      state.currentId = null;
      state.currentNotebook = null;
      await loadNotebooks();
      toast("Đã xóa sổ tay.");
    } catch (error) {
      toast(error.message || "Không thể xóa sổ tay.");
    }
  });
  $("#emptyCreateBtn").addEventListener("click", () => {
    newNotebookName.value = "";
    openModal(newNotebookModal);
    newNotebookName.focus();
  });

  document.querySelectorAll("[data-close]").forEach((btn) =>
    btn.addEventListener("click", (e) => closeModal(e.target.closest(".modal-backdrop")))
  );

  $("#createNotebookBtn").addEventListener("click", async () => {
    const name = newNotebookName.value.trim() || "Sổ tay chưa đặt tên";
    try {
      const nb = await api("/api/notebooks", {
        method: "POST",
        body: JSON.stringify({ name }),
      });
      closeModal(newNotebookModal);
      await loadNotebooks(nb.id);
    } catch (e) {
      toast(e.message);
    }
  });

  // ---------- Settings modal with tabs ----------

  const settingsModal = $("#settingsModal");
  const adminModal = $("#adminModal");

  // Settings tab switching
  document.querySelectorAll(".settings-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      const tabName = tab.dataset.tab;
      document.querySelectorAll(".settings-tab").forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".settings-panel").forEach((p) => p.classList.remove("active"));
      tab.classList.add("active");
      const panel = document.getElementById(`panel-${tabName}`);
      if (panel) panel.classList.add("active");
    });
  });

  // Admin tab switching
  document.querySelectorAll(".admin-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      const tabName = tab.dataset.tab;
      document.querySelectorAll(".admin-tab").forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".admin-panel").forEach((p) => p.classList.remove("active"));
      tab.classList.add("active");
      const panel = document.getElementById(`panel-${tabName}`);
      if (panel) panel.classList.add("active");
    });
  });

  // Go to Admin button in Developer tab
  const goToAdminBtn = $("#goToAdminBtn");
  if (goToAdminBtn) {
    goToAdminBtn.addEventListener("click", () => {
      closeModal(settingsModal);
      window.location.href = "/admin";
    });
  }

  $("#settingsBtn").addEventListener("click", async () => {
    try {
      const sessionResponse = await fetch("/api/auth/me", { headers: { Accept: "application/json" } });
      const sessionData = await sessionResponse.json().catch(() => ({}));
      if (sessionResponse.ok && sessionData.authenticated && sessionData.user) {
        state.user = sessionData.user;
      }

      // Load non-API-key settings from localStorage
      const theme = localStorage.getItem("theme") || "auto";
      const lang = localStorage.getItem("language") || "vi";
      const tts = localStorage.getItem("enableTTS") !== "false";
      const voiceInput = localStorage.getItem("enableVoiceInput") !== "false";
      const saveChatHistory = localStorage.getItem("saveChatHistory") !== "false";
      const allowModelTraining = localStorage.getItem("allowModelTraining") === "true";
      const betaFeatures = localStorage.getItem("enableBetaFeatures") === "true";
      const customInstructions = await loadCustomInstructionsFromServer();
      const personalConfig = getPersonalApiConfig();

      // Set values in form
      $("#themeSelect").value = theme;
      $("#languageSelect").value = lang;
      const enableTts = $("#enableTTS");
      const enableVoiceInput = $("#enableVoiceInput");
      const enableBetaFeatures = $("#enableBetaFeatures");
      if (enableTts) enableTts.checked = tts;
      if (enableVoiceInput) enableVoiceInput.checked = voiceInput;
      $("#saveChatHistory").checked = saveChatHistory;
      $("#allowModelTraining").checked = allowModelTraining;
      if (enableBetaFeatures) enableBetaFeatures.checked = betaFeatures;
      $("#usernameDisplay").value = state.user?.username || "";
      $("#emailInput").value = state.user?.email || "";
      const customInstructionsEl = $("#customInstructions");
      if (customInstructionsEl) {
        customInstructionsEl.value = customInstructions;
      }
      const personalApiKeyInput = $("#personalApiKeyInput");
      if (personalApiKeyInput) personalApiKeyInput.value = personalConfig.apiKey || "";
      const personalModelInput = $("#personalModelInput");
      if (personalModelInput) personalModelInput.value = personalConfig.model || "gemini-2.5-flash";
      const personalProviderSelect = $("#personalProviderSelect");
      if (personalProviderSelect) personalProviderSelect.value = personalConfig.provider || "auto";
      renderUsageStats();
    } catch (e) {
      /* noop */
    }
    openModal(settingsModal);
  });

  const passwordModal = $("#passwordModal");
  const changePasswordBtn = $("#changePasswordBtn");
  const confirmChangePasswordBtn = $("#confirmChangePasswordBtn");

  changePasswordBtn?.addEventListener("click", () => {
    $("#currentPasswordInput").value = "";
    $("#newPasswordInput").value = "";
    $("#confirmNewPasswordInput").value = "";
    openModal(passwordModal);
  });

  confirmChangePasswordBtn?.addEventListener("click", async () => {
    const currentPassword = $("#currentPasswordInput").value;
    const newPassword = $("#newPasswordInput").value;
    const confirmPassword = $("#confirmNewPasswordInput").value;
    const email = state.user?.email;

    if (!email) {
      toast("Tài khoản này chưa có email để xác thực.");
      return;
    }
    if (!currentPassword || !newPassword || !confirmPassword) {
      toast("Hãy nhập đầy đủ các trường mật khẩu.");
      return;
    }
    if (newPassword.length < 6) {
      toast("Mật khẩu mới phải có ít nhất 6 ký tự.");
      return;
    }
    if (newPassword !== confirmPassword) {
      toast("Mật khẩu mới và xác nhận không khớp.");
      return;
    }
    if (!window.firebase?.auth || !window.FIREBASE_CONFIG?.apiKey) {
      toast("Firebase chưa được cấu hình để xác thực email.");
      return;
    }

    confirmChangePasswordBtn.disabled = true;
    try {
      const credential = await firebase.auth().signInWithEmailAndPassword(email, currentPassword);
      await credential.user.reload();
      if (!credential.user.emailVerified) {
        await firebase.auth().signOut();
        throw new Error("Email chưa được xác thực. Hãy kiểm tra hộp thư trước.");
      }

      const response = await api("/api/auth/password", {
        method: "POST",
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
          id_token: await credential.user.getIdToken(true),
        }),
      });
      closeModal(passwordModal);
      toast(response.ok ? "Đổi mật khẩu thành công." : "Đã đổi mật khẩu.");
    } catch (error) {
      toast(error.code ? "Mật khẩu hiện tại không đúng hoặc Firebase không thể xác thực." : error.message);
    } finally {
      confirmChangePasswordBtn.disabled = false;
    }
  });

  $("#saveSettingsBtn").addEventListener("click", async () => {
    // Save appearance settings
    localStorage.setItem("theme", $("#themeSelect").value || "auto");
    localStorage.setItem("language", $("#languageSelect").value || "vi");
    const enableTts = $("#enableTTS");
    const enableVoiceInput = $("#enableVoiceInput");
    const enableBetaFeatures = $("#enableBetaFeatures");
    if (enableTts) localStorage.setItem("enableTTS", enableTts.checked);
    if (enableVoiceInput) localStorage.setItem("enableVoiceInput", enableVoiceInput.checked);
    
    // Save privacy settings
    localStorage.setItem("saveChatHistory", $("#saveChatHistory").checked);
    localStorage.setItem("allowModelTraining", $("#allowModelTraining").checked);
    
    // Save personalization (lưu riêng theo tài khoản ở server, không dùng localStorage)
    const customInstructionsEl = $("#customInstructions");
    if (customInstructionsEl) {
      try {
        await saveCustomInstructionsToServer(customInstructionsEl.value || "");
      } catch (error) {
        toast(error.message || "Không thể lưu hướng dẫn cá nhân hóa.");
      }
    }
    if (enableBetaFeatures) localStorage.setItem("enableBetaFeatures", enableBetaFeatures.checked);

    const personalApiKeyInput = $("#personalApiKeyInput");
    const personalModelInput = $("#personalModelInput");
    const personalProviderSelect = $("#personalProviderSelect");
    if (personalApiKeyInput || personalModelInput || personalProviderSelect) {
      setPersonalApiConfig({
        apiKey: personalApiKeyInput ? personalApiKeyInput.value.trim() : "",
        model: personalModelInput ? personalModelInput.value.trim() : "",
        provider: personalProviderSelect ? personalProviderSelect.value : "auto",
      });
      try {
        await fetch("/api/personal-config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            api_key: personalApiKeyInput ? personalApiKeyInput.value.trim() : "",
            model: personalModelInput ? personalModelInput.value.trim() : "",
            provider: personalProviderSelect ? personalProviderSelect.value : "auto",
          }),
        });
      } catch (_error) {
        // noop
      }
    }

    toast("Đã lưu cài đặt.");
    closeModal(settingsModal);
  });

  $("#togglePersonalApiKeyBtn")?.addEventListener("click", () => {
    const input = $("#personalApiKeyInput");
    if (!input) return;
    const isPassword = input.type === "password";
    input.type = isPassword ? "text" : "password";
    const icon = $("#togglePersonalApiKeyBtn i");
    if (icon) {
      icon.className = isPassword ? "fa-solid fa-eye-slash" : "fa-solid fa-eye";
    }
  });

  $("#savePersonalApiKeyBtn")?.addEventListener("click", async () => {
    const personalApiKeyInput = $("#personalApiKeyInput");
    const personalModelInput = $("#personalModelInput");
    const personalProviderSelect = $("#personalProviderSelect");
    const payload = {
      api_key: personalApiKeyInput ? personalApiKeyInput.value.trim() : "",
      model: personalModelInput ? personalModelInput.value.trim() : "gemini-2.5-flash",
      provider: personalProviderSelect ? personalProviderSelect.value : "auto",
    };
    setPersonalApiConfig(payload);
    try {
      await fetch("/api/personal-config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      toast("Đã lưu API Key cá nhân.");
    } catch (error) {
      toast(error.message || "Không thể lưu API Key cá nhân.");
    }
  });

  $("#accountLogoutBtn").addEventListener("click", async () => {
    if (state.activeUploads.size) {
      const names = Array.from(state.activeUploads.values()).map((u) => u.filename).join(", ");
      const confirmed = window.confirm(
        `Tài liệu đang được xử lý (${names}).\n\n` +
        `Đăng xuất sẽ KHÔNG làm dừng quá trình xử lý ở máy chủ, nhưng bạn sẽ cần ` +
        `đăng nhập lại để xem tiến trình hoặc kết quả.\n\nBạn có muốn tiếp tục đăng xuất không?`
      );
      if (!confirmed) return;
    }
    try {
      await api("/api/auth/logout", { method: "POST" });
      window.location.href = "/";
    } catch (error) {
      toast(error.message);
    }
  });

  $("#viewAiMemoryBtn")?.addEventListener("click", renderAiMemoryModal);
  $("#clearChatHistoryBtn")?.addEventListener("click", async () => {
    if (!state.currentId || !state.currentNotebook) {
      toast("Chưa mở note nào để xóa lịch sử trò chuyện.");
      return;
    }
    const name = state.currentNotebook.name || "note này";
    const confirmed = window.confirm(
      `Xóa toàn bộ lịch sử trò chuyện trong "${name}"? Tài liệu, Quiz/Mindmap/Flashcard và hướng dẫn cá nhân hóa sẽ KHÔNG bị ảnh hưởng. Các note khác cũng không bị ảnh hưởng.`
    );
    if (!confirmed) return;
    try {
      await api(`/api/notebooks/${state.currentId}/chat`, { method: "DELETE" });
      await selectNotebook(state.currentId);
      toast("Đã xóa lịch sử trò chuyện của note này.");
    } catch (error) {
      toast(error.message || "Không thể xóa lịch sử trò chuyện.");
    }
  });
  $("#clearAiMemoryBtn")?.addEventListener("click", () => {
    const confirmed = window.confirm("Bạn có chắc muốn xóa toàn bộ dữ liệu bộ nhớ AI?");
    if (!confirmed) return;
    clearAiMemory();
    toast("Đã xóa bộ nhớ AI.");
    closeModal($("#aiMemoryModal"));
  });
  $("#aiMemoryModal [data-close]")?.addEventListener("click", () => closeModal($("#aiMemoryModal")));

  // ---------- Admin modal with API keys ----------

  $("#adminBtn")?.addEventListener("click", async () => {
    // Load API keys from config
    try {
      const cfg = await api("/api/config");
      $("#modelInput").value = cfg.model || "";
      $("#providerInput").value = cfg.provider || "auto";
      $("#openaiModelInput").value = cfg.openai_model || "gpt-4o-mini";
      $("#anthropicModelInput").value = cfg.anthropic_model || "claude-3-5-haiku-latest";
      $("#apiKeyInput").value = cfg.has_api_key ? "••••••••••••" : "";
      $("#openaiKeyInput").value = cfg.has_openai_key ? "••••••••••••" : "";
      $("#openrouterKeyInput").value = cfg.has_openrouter_key ? "••••••••••••" : "";
      $("#openrouterModelInput").value = cfg.openrouter_model || "openai/gpt-4o-mini";
      $("#anthropicKeyInput").value = cfg.has_anthropic_key ? "••••••••••••" : "";
      $("#githubTokenInput").value = cfg.has_github_token ? "••••••••••••" : "";
    } catch (e) {
      /* noop */
    }
    await loadAdminNotebooks();
    openModal(adminModal);
  });

  $("#saveAdminSettingsBtn").addEventListener("click", async () => {
    const keyVal = $("#apiKeyInput").value;
    const payload = {
      model: $("#modelInput").value.trim(),
      provider: $("#providerInput").value,
      openai_model: $("#openaiModelInput").value.trim(),
      anthropic_model: $("#anthropicModelInput").value.trim(),
    };
    if (keyVal && !keyVal.startsWith("••••")) payload.api_key = keyVal;
    const openaiKey = $("#openaiKeyInput").value;
    const openrouterKey = $("#openrouterKeyInput").value;
    const anthropicKey = $("#anthropicKeyInput").value;
    const githubToken = $("#githubTokenInput").value;
    if (openaiKey && !openaiKey.startsWith("••••")) payload.openai_api_key = openaiKey;
    if (openrouterKey && !openrouterKey.startsWith("••••")) payload.openrouter_api_key = openrouterKey;
    payload.openrouter_model = $("#openrouterModelInput").value.trim();
    if (anthropicKey && !anthropicKey.startsWith("••••")) payload.anthropic_api_key = anthropicKey;
    if (githubToken && !githubToken.startsWith("••••")) payload.github_token = githubToken;
    try {
      await api("/api/config", { method: "POST", body: JSON.stringify(payload) });
      toast("Đã lưu cài đặt API.");
      closeModal(adminModal);
    } catch (e) {
      toast(e.message);
    }
  });

  // ---------- Sources ----------

  function renderSources() {
    const docs = state.currentNotebook.documents;
    sourceList.innerHTML = "";
    sourcesEmpty.hidden = docs.length > 0;
    docs.forEach((doc) => {
      // Tài liệu đang thực sự được xử lý (còn upload tương ứng đang theo dõi ở
      // client) đã có sẵn một dòng "Đang tải và xử lý…" riêng — khỏi hiển thị
      // trùng ở đây, chỉ hiện khi nó bị GIÁN ĐOẠN (xem isStaleProcessing bên dưới).
      const isActivelyTracked = doc.processing &&
        Array.from(state.activeUploads.values()).some((u) => u.docId === doc.id);
      if (isActivelyTracked) return;

      const li = document.createElement("li");
      li.className = "source-item";
      const ocrBadge = doc.ocr_pages
        ? `<span class="ocr-badge" title="${doc.ocr_pages} trang nhận dạng bằng OCR">OCR</span>`
        : "";
      // Nếu còn cờ "processing" nhưng không có upload nào đang theo dõi (đã lọc
      // ở trên) — nghĩa là quá trình quét bị gián đoạn (VD: cmd bị đóng đột ngột).
      let statusBadge = "";
      if (doc.interrupted || doc.processing) {
        const pageInfo = doc.pages_done ? ` (đã quét được ${doc.pages_done} trang)` : "";
        statusBadge = `<small class="source-warning">⚠ Quét bị gián đoạn${pageInfo} — nội dung có thể chưa đầy đủ. Xóa và tải lại nếu cần quét lại từ đầu.</small>`;
      }
      li.innerHTML = `
        <input class="source-check" type="checkbox" data-doc-id="${doc.id}" checked aria-label="Chọn ${escapeHtml(doc.name)}">
        <span class="source-icon">${doc.source_type.toUpperCase().slice(0, 4)}</span>
        <span class="source-name">${escapeHtml(doc.name)}${ocrBadge}${statusBadge}</span>
        <button class="source-remove" title="Xóa tài liệu"><i class="fa-solid fa-xmark"></i></button>
      `;
      li.querySelector(".source-remove").addEventListener("click", async () => {
        await api(`/api/notebooks/${state.currentId}/documents/${doc.id}`, { method: "DELETE" });
        state.currentNotebook = await api(`/api/notebooks/${state.currentId}`);
        renderSources();
      });
      sourceList.appendChild(li);
    });
    sourceList.querySelectorAll(".source-check").forEach((check) => {
      check.addEventListener("change", updateSelectionState);
    });
    updateSelectionState();
  }

  function selectedDocumentIds(scope) {
    if (scope === "all") return state.currentNotebook.documents.map((doc) => doc.id);
    return Array.from(sourceList.querySelectorAll(".source-check:checked"))
      .map((check) => check.dataset.docId);
  }

  function updateSelectionState() {
    const checks = Array.from(sourceList.querySelectorAll(".source-check"));
    const selected = checks.filter((check) => check.checked).length;
    selectionCount.textContent = checks.length ? `${selected}/${checks.length} đã chọn` : "";
    selectAllSources.checked = checks.length > 0 && selected === checks.length;
    selectAllSources.indeterminate = selected > 0 && selected < checks.length;
  }

  selectAllSources.addEventListener("change", () => {
    sourceList.querySelectorAll(".source-check").forEach((check) => {
      check.checked = selectAllSources.checked;
    });
    updateSelectionState();
  });

  // Việc quét/OCR tài liệu chạy ở một luồng riêng trên server (xem app.py),
  // hoàn toàn độc lập với request HTTP đã khởi tạo nó. Vì vậy refresh trang,
  // đóng tab hay đăng xuất tài khoản sẽ KHÔNG làm dừng quá trình này — nó vẫn
  // tiếp tục chạy trên máy chủ. state.activeUploads chỉ dùng để: (1) hiển thị
  // lại thanh tiến trình sau khi refresh, và (2) cảnh báo người dùng trước khi
  // họ rời trang/đăng xuất, để họ hiểu rõ điều gì sẽ (và sẽ không) xảy ra.
  state.activeUploads = new Map(); // uploadId -> { filename, item }

  function addUploadingSource(filename) {
    sourcesEmpty.hidden = true;
    const li = document.createElement("li");
    li.className = "source-item source-uploading";
    li.innerHTML = `
      <span class="source-icon source-spinner" aria-hidden="true"></span>
      <span class="source-name">${escapeHtml(filename)}<small>Đang tải và xử lý…</small></span>
    `;
    sourceList.appendChild(li);
    return li;
  }

  async function refreshCurrentNotebook() {
    state.currentNotebook = await api(`/api/notebooks/${state.currentId}`);
    renderSources();
  }

  // Theo dõi một lượt upload đã tồn tại (dù mới gửi lên hay khôi phục sau refresh)
  // cho tới khi hoàn tất hoặc lỗi, đồng thời cập nhật thanh tiến trình trên UI.
  function trackUpload(nbId, uploadId, filename, docId, existingItem) {
    const uploadingItem = existingItem || addUploadingSource(filename);
    const startedAt = Date.now();
    state.activeUploads.set(uploadId, { filename, nbId, docId });
    updateUnloadGuard();

    return new Promise((resolve) => {
      const statusTimer = setInterval(() => {
        const status = uploadingItem.querySelector("small");
        if (!status) return;
        const seconds = Math.floor((Date.now() - startedAt) / 1000);
        if (!status.dataset.locked) {
          status.textContent = seconds >= 10
            ? `Đang xử lý OCR… (${seconds} giây)`
            : "Đang tải và xử lý…";
        }
      }, 1000);

      const poll = setInterval(async () => {
        try {
          const progress = await api(`/api/uploads/${uploadId}`);
          const status = uploadingItem.querySelector("small");
          if (progress.status === "processing") {
            if (status && progress.total) {
              status.dataset.locked = "1";
              status.textContent = `Đang OCR trang ${progress.page}/${progress.total}…`;
            }
            return;
          }
          clearInterval(poll);
          clearInterval(statusTimer);
          state.activeUploads.delete(uploadId);
          updateUnloadGuard();
          uploadingItem.remove();
          if (progress.status === "complete") {
            resolve({ ok: true, filename });
          } else {
            resolve({ ok: false, filename, error: progress.error || "Lỗi không xác định." });
          }
        } catch (_err) {
          // Notebook có thể đang được tải lại, cứ thử lại ở lượt sau.
        }
      }, 1000);
    });
  }

  // Nếu vẫn còn tài liệu đang xử lý khi rời trang, cảnh báo người dùng — dù việc
  // rời trang KHÔNG làm dừng quá trình xử lý ở server, chỉ là họ sẽ không thấy
  // tiến trình nữa cho tới khi mở lại notebook.
  function updateUnloadGuard() {
    window.onbeforeunload = state.activeUploads.size
      ? (e) => {
          e.preventDefault();
          e.returnValue = "";
          return "";
        }
      : null;
  }

  // Sau khi mở notebook (kể cả sau khi refresh trang), kiểm tra xem có lượt
  // upload nào đang xử lý dở dang không, để khôi phục lại thanh tiến trình
  // thay vì để người dùng tưởng là việc tải tài liệu đã bị mất.
  async function resumeActiveUploads(nbId) {
    let uploads;
    try {
      uploads = await api(`/api/notebooks/${nbId}/uploads`);
    } catch (_err) {
      return;
    }
    const processing = uploads.filter((u) => u.status === "processing" && !state.activeUploads.has(u.upload_id));
    if (!processing.length) return;
    toast(
      processing.length === 1
        ? `Tài liệu "${processing[0].filename}" vẫn đang được xử lý ở máy chủ, tiếp tục theo dõi…`
        : `${processing.length} tài liệu vẫn đang được xử lý ở máy chủ, tiếp tục theo dõi…`
    );
    processing.forEach((u) => {
      trackUpload(nbId, u.upload_id, u.filename, u.doc_id).then(async (result) => {
        if (result.ok) {
          toast(`Đã xử lý xong "${result.filename}".`);
        } else {
          toast(`Xử lý "${result.filename}" thất bại: ${result.error}`);
        }
        if (state.currentId === nbId) {
          try {
            await refreshCurrentNotebook();
          } catch (_err) {
            /* bỏ qua, người dùng có thể tự làm mới */
          }
        }
      });
    });
  }

  // Tải lên (các) file làm NGUỒN thật sự trong Sổ tay (lưu lại, OCR nếu cần, dùng
  // cho mọi câu hỏi sau này) — dùng chung cho nút "Tải lên" ở sidebar Nguồn VÀ
  // nút đính kèm tệp kế khung chat (📎).
  async function uploadFilesAsSources(files) {
    const nbId = state.currentId;
    let uploadedCount = 0;
    const errors = [];

    if (!files.length) return;

    toast(
      files.length === 1
        ? `Đang tải lên "${files[0].name}"… Bạn có thể refresh trang hoặc đăng xuất mà không làm gián đoạn quá trình xử lý.`
        : `Đang tải lên ${files.length} file… Bạn có thể refresh trang hoặc đăng xuất mà không làm gián đoạn quá trình xử lý.`
    );

    for (const file of files) {
      const fd = new FormData();
      fd.append("file", file);
      const uploadingItem = addUploadingSource(file.name);
      const uploadId = crypto.randomUUID();

      try {
        // Request này trả lời ngay lập tức (202) sau khi server nhận file và bắt
        // đầu xử lý ở luồng nền — không còn phải giữ kết nối mở suốt quá trình
        // quét/OCR như trước, nên refresh trang sẽ không "cắt ngang" việc xử lý.
        const res = await fetch(`/api/notebooks/${nbId}/documents`, {
          method: "POST",
          headers: { "X-Upload-ID": uploadId },
          body: fd,
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Lỗi tải lên");

        const result = await trackUpload(nbId, uploadId, file.name, data.doc_id, uploadingItem);
        if (result.ok) {
          uploadedCount += 1;
        } else {
          errors.push(`"${file.name}": ${result.error}`);
        }
      } catch (err) {
        state.activeUploads.delete(uploadId);
        updateUnloadGuard();
        uploadingItem.remove();
        errors.push(`"${file.name}": ${err.message}`);
      }
    }

    try {
      if (state.currentId === nbId) {
        await refreshCurrentNotebook();
      }
    } catch (err) {
      errors.push(`Không tải lại được danh sách tài liệu: ${err.message}`);
    }

    if (errors.length) {
      toast(
        uploadedCount
          ? `Đã tải ${uploadedCount}/${files.length} file. ${errors.join(" ")}`
          : `Tải lên thất bại. ${errors.join(" ")}`
      );
    } else if (uploadedCount) {
      toast(`Đã tải lên ${uploadedCount} file.`);
    }
  }

  $("#fileInput").addEventListener("change", async (e) => {
    const files = Array.from(e.target.files || []);
    e.target.value = "";
    await uploadFilesAsSources(files);
  });

  // ---------- Chat ----------

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  // ---------- Chuẩn hoá ký hiệu toán học & bỏ ký tự đặc biệt khó hiểu ----------
  // Model đôi khi vẫn lỡ trả về cú pháp LaTeX (\times, \frac{}{}, $...$...) dù đã
  // được nhắc không dùng. Các hàm dưới đây chuyển chúng thành ký hiệu toán học
  // thông thường, dễ đọc, đồng thời giữ lại dấu * khi nó là PHÉP NHÂN (vd "3 * 4")
  // thay vì xoá trắng như trước (khiến phép tính bị mất luôn dấu nhân).
  const SUPERSCRIPT_MAP = { "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹", "-": "⁻" };
  const SUBSCRIPT_MAP = { "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄", "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉" };
  const toSuperscriptDigits = (str) => String(str).split("").map((c) => SUPERSCRIPT_MAP[c] || c).join("");
  const toSubscriptDigits = (str) => String(str).split("").map((c) => SUBSCRIPT_MAP[c] || c).join("");

  function latexToPlainMath(value) {
    return String(value || "")
      .replace(/\\times|\\cdot/g, "×")
      .replace(/\\div/g, "÷")
      .replace(/\\pm/g, "±")
      .replace(/\\leq|\\le\b/g, "≤")
      .replace(/\\geq|\\ge\b/g, "≥")
      .replace(/\\neq|\\ne\b/g, "≠")
      .replace(/\\approx/g, "≈")
      .replace(/\\infty/g, "∞")
      .replace(/\\pi/g, "π")
      .replace(/\\sqrt\{([^{}]*)\}/g, "√($1)")
      .replace(/\\sqrt/g, "√")
      .replace(/\\frac\{([^{}]*)\}\{([^{}]*)\}/g, "($1/$2)")
      .replace(/\\left|\\right/g, "")
      .replace(/\\\[|\\\]|\\\(|\\\)/g, "")
      .replace(/\${1,2}/g, "")
      .replace(/\^\{(-?\d+)\}/g, (_, d) => toSuperscriptDigits(d))
      .replace(/\^(-?\d)\b/g, (_, d) => toSuperscriptDigits(d))
      .replace(/_\{(\d+)\}/g, (_, d) => toSubscriptDigits(d))
      .replace(/_(\d)\b/g, (_, d) => toSubscriptDigits(d));
  }

  function cleanMathAndSymbols(raw) {
    let text = latexToPlainMath(raw)
      .replace(/```[a-z]*\s*/gi, "")
      .replace(/```/g, "");
    // "**bold**" / "***bold***" -> bỏ dấu *, giữ chữ (không phải phép nhân)
    text = text.replace(/\*\*\*([^*]+)\*\*\*/g, "$1").replace(/\*\*([^*]+)\*\*/g, "$1");
    // Dấu * còn lại đứng giữa hai số là phép nhân -> đổi thành ×, KHÔNG xoá
    text = text.replace(/(\d)\s*\*\s*(\d)/g, "$1 × $2");
    // Dấu * lẻ còn sót (định dạng in nghiêng cũ) thì bỏ cho gọn, dễ đọc
    text = text.replace(/\*/g, "");
    return text
      .replace(/[\@&]/g, "")
      .replace(/[ \t]{2,}/g, " ")
      .trim();
  }

  function renderAnswerText(text) {
    const cleaned = cleanMathAndSymbols(text);
    const formatInline = (value) => escapeHtml(value).replace(
      /\[(\d+)\]/g,
      '<span class="cite-marker">$1</span>'
    );
    const lines = cleaned.split("\n");
    let html = "";
    let listItems = [];
    let tableRows = [];
    const flushList = () => {
      if (listItems.length) {
        html += `<ul class="answer-list">${listItems.map((item) => `<li>${formatInline(item)}</li>`).join("")}</ul>`;
        listItems = [];
      }
    };
    const flushTable = () => {
      if (tableRows.length) {
        const rows = tableRows.filter((row) => !/^\s*\|?\s*:?-{2,}/.test(row));
        if (rows.length) {
          html += `<div class="answer-table-wrap"><table class="answer-table">${rows.map((row, index) => {
            const tag = index === 0 ? "th" : "td";
            const cells = row.replace(/^\||\|$/g, "").split("|")
              .map((cell) => `<${tag}>${formatInline(cell.trim())}</${tag}>`)
              .join("");
            return `<tr>${cells}</tr>`;
          }).join("")}</table></div>`;
        }
        tableRows = [];
      }
    };
    for (const line of lines) {
      if (line.includes("|") && line.trim().split("|").length >= 3) {
        flushList();
        tableRows.push(line);
        continue;
      }
      flushTable();
      const heading = line.match(/^\s*#{1,3}\s+(.+)/);
      const bullet = line.match(/^\s*[-+]\s+(.+)/);
      if (heading) {
        flushList();
        html += `<h3 class="answer-heading">${formatInline(heading[1])}</h3>`;
      } else if (bullet) {
        listItems.push(bullet[1]);
      } else if (line.trim()) {
        flushList();
        html += `<p>${formatInline(line)}</p>`;
      } else {
        flushList();
      }
    }
    flushList();
    flushTable();
    return html;
  }

  function normalizeClipboardText(value) {
    return latexToPlainMath(String(value || ""))
      .replace(/(\d)\s*\*\s*(\d)/g, "$1×$2")
      .replace(/\u200B/g, "")
      .replace(/\u00A0/g, " ")
      .replace(/\r\n/g, "\n")
      .replace(/\[\d+\]/g, "")
      .replace(/\n{3,}/g, "\n\n")
      .replace(/[ \t]+\n/g, "\n")
      .replace(/\n[ \t]+/g, "\n")
      .trim();
  }

  function markdownInlineToHtml(value) {
    // Bảo vệ dấu * khi là phép nhân (vd "3 * 4") trước khi coi các dấu * còn lại
    // là cú pháp in đậm/in nghiêng của Markdown.
    const protectedText = latexToPlainMath(String(value || "")).replace(/(\d)\s*\*\s*(\d)/g, "$1×$2");
    return escapeHtml(protectedText)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\*(.+?)\*/g, "<em>$1</em>")
      .replace(/_(.+?)_/g, "<em>$1</em>")
      .replace(/`(.+?)`/g, "<code>$1</code>");
  }

  function markdownToCopyHtml(value) {
    const text = String(value || "");
    const lines = text.split(/\r?\n/);
    const htmlParts = [];
    let bulletList = [];
    let orderedList = [];

    const flushLists = () => {
      if (bulletList.length) {
        htmlParts.push(`<ul>${bulletList.map((item) => `<li>${markdownInlineToHtml(item)}</li>`).join("")}</ul>`);
        bulletList = [];
      }
      if (orderedList.length) {
        htmlParts.push(`<ol>${orderedList.map((item) => `<li>${markdownInlineToHtml(item)}</li>`).join("")}</ol>`);
        orderedList = [];
      }
    };

    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (!line) {
        flushLists();
        continue;
      }
      if (/^#{1,3}\s+/.test(rawLine)) {
        flushLists();
        const heading = rawLine.replace(/^#{1,3}\s+/, "");
        htmlParts.push(`<h3>${markdownInlineToHtml(heading)}</h3>`);
        continue;
      }
      if (/^[-*]\s+/.test(rawLine)) {
        bulletList.push(line.replace(/^[-*]\s+/, ""));
        continue;
      }
      if (/^\d+\.\s+/.test(rawLine)) {
        orderedList.push(line.replace(/^\d+\.\s+/, ""));
        continue;
      }
      flushLists();
      htmlParts.push(`<p>${markdownInlineToHtml(line)}</p>`);
    }

    flushLists();
    return htmlParts.join("");
  }

  function appendMessage(role, content, citations) {
    const wrap = document.createElement("div");
    wrap.className = `msg msg-${role}`;
    wrap.dataset.rawContent = String(content || "");
    const label = role === "user" ? "Bạn" : "Trợ lý";
    let citeHtml = "";
    if (citations && citations.length) {
      citeHtml = `<div class="citations">${citations
        .map(
          (c) =>
            `<div class="cite-row"><span class="cite-marker">${c.marker}</span> <b>${escapeHtml(
              c.doc_name
            )}</b> <span class="cite-page">• ${escapeHtml(c.position)}</span><br><span class="cite-snippet">“${escapeHtml(c.snippet)}…”</span></div>`
        )
        .join("")}</div>`;
    }
    const answerHtml = renderAnswerText(content);
    wrap.innerHTML = `
      <div class="msg-role">${label}</div>
      <div class="msg-bubble">
        <div class="answer-body">${answerHtml}</div>
        ${citeHtml}
      </div>
    `;
    chatLog.appendChild(wrap);
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  document.addEventListener("copy", (event) => {
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0) return;

    const selectedRange = selection.getRangeAt(0);
    const commonNode = selectedRange.commonAncestorContainer;
    const bubble = commonNode && commonNode.nodeType === Node.ELEMENT_NODE
      ? commonNode
      : commonNode?.parentElement;
    const msgBubble = bubble?.closest(".msg-bubble");
    const msgWrap = msgBubble?.closest(".msg");
    if (!msgBubble) return;

    const rawContent = String(msgWrap?.dataset.rawContent || msgBubble.textContent || selection.toString());
    const plainText = normalizeClipboardText(rawContent).replace(/\*\*/g, "");
    const richHtml = markdownToCopyHtml(rawContent);

    if (!plainText && !richHtml) return;
    event.preventDefault();
    event.clipboardData?.setData("text/plain", plainText || rawContent);
    event.clipboardData?.setData("text/html", richHtml || plainText || rawContent);
  });

  function renderChatHistory() {
    chatLog.innerHTML = "";
    const history = state.currentNotebook.chat_history || [];
    if (!history.length) {
      chatLog.innerHTML = `
        <div class="chat-welcome">
          <h1>Hỏi bất cứ điều gì về nguồn của bạn</h1>
          <p>Câu trả lời sẽ trích dẫn ngược lại đúng đoạn và tài liệu gốc.</p>
        </div>`;
      return;
    }
    history.forEach((turn) => appendMessage(turn.role, turn.content, turn.citations));
  }

  // ---------- Khung chat: tự giãn dòng, phóng to (nằm trong khung chat), đính kèm
  // tệp làm nguồn, và dán ảnh nhất thời (Ctrl+V) chỉ dùng riêng cho câu hỏi đó ----------

  const chatImageBtn = $("#chatImageBtn");
  const chatImageInput = $("#chatImageInput");
  let chatInputExpanded = false;

  function autosizeChatInput() {
    chatInput.style.height = "auto";
    const nextHeight = Math.min(chatInput.scrollHeight, chatInputExpanded ? Infinity : 160);
    chatInput.style.height = `${nextHeight}px`;
  }

  function setChatInputExpanded(expanded) {
    chatInputExpanded = expanded;
    chatForm.classList.toggle("expanded", expanded);
    chatExpandBtn.innerHTML = expanded
      ? '<i class="fa-solid fa-compress"></i>'
      : '<i class="fa-solid fa-expand"></i>';
    chatExpandBtn.title = expanded ? "Thu nhỏ khung chat" : "Phóng to khung chat";
    chatExpandBtn.setAttribute("aria-label", chatExpandBtn.title);
    autosizeChatInput();
    chatInput.focus();
  }

  chatInput.addEventListener("input", autosizeChatInput);

  chatExpandBtn.addEventListener("click", () => setChatInputExpanded(!chatInputExpanded));

  // Nút 📎 kế khung chat: đính kèm TỆP làm NGUỒN thật sự cho Sổ tay (PDF, DOCX,
  // TXT, MD, ảnh...) — giống hệt nút "Tải lên" ở sidebar Nguồn, tài liệu sẽ được
  // lưu lại và dùng cho mọi câu hỏi về sau. Khác với việc DÁN ảnh (Ctrl+V) bên
  // dưới, vốn chỉ nhất thời cho một câu hỏi và không lưu vào Nguồn.
  chatImageBtn.addEventListener("click", () => chatImageInput.click());
  chatImageInput.addEventListener("change", async (e) => {
    const files = Array.from(e.target.files || []);
    e.target.value = "";
    await uploadFilesAsSources(files);
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && chatInputExpanded) setChatInputExpanded(false);
  });

  // Enter để gửi, Shift+Enter để xuống dòng (vì khung chat giờ là textarea nhiều dòng)
  chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      chatForm.requestSubmit ? chatForm.requestSubmit() : chatForm.dispatchEvent(new Event("submit", { cancelable: true }));
    }
  });

  function renderChatAttachments() {
    const items = state.pendingChatAttachments;
    chatAttachments.hidden = items.length === 0;
    chatAttachments.innerHTML = items
      .map((att) => {
        const statusText = att.status === "uploading"
          ? "Đang đọc ảnh…"
          : att.status === "error"
          ? (att.error || "Lỗi đọc ảnh")
          : "Sẵn sàng · chỉ dùng cho câu hỏi này, không lưu vào Nguồn";
        return `
          <div class="attachment-chip${att.status === "error" ? " error" : ""}" data-att-id="${att.id}">
            <img src="${att.previewUrl}" alt="${escapeHtml(att.filename)}">
            <div class="attachment-info">
              <span class="attachment-name">${escapeHtml(att.filename)}</span>
              <span class="attachment-status">${escapeHtml(statusText)}</span>
            </div>
            <button type="button" class="attachment-remove" data-remove-att="${att.id}" title="Bỏ ảnh này" aria-label="Bỏ ảnh này"><i class="fa-solid fa-xmark"></i></button>
          </div>
        `;
      })
      .join("");
  }

  chatAttachments.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-remove-att]");
    if (!btn) return;
    const id = btn.getAttribute("data-remove-att");
    const att = state.pendingChatAttachments.find((a) => a.id === id);
    if (att?.previewUrl) URL.revokeObjectURL(att.previewUrl);
    // Ảnh dán chỉ tồn tại nhất thời trong bộ nhớ trình duyệt — không có tài liệu
    // nào được lưu ở server nên bỏ ảnh ở đây là xong, không cần gọi API xóa.
    state.pendingChatAttachments = state.pendingChatAttachments.filter((a) => a.id !== id);
    renderChatAttachments();
  });

  // Dán ảnh (Ctrl+V) vào khung chat: chỉ đọc chữ trong ảnh (OCR) NHẤT THỜI ở bộ
  // nhớ trình duyệt để gửi kèm câu hỏi hiện tại — KHÔNG upload/lưu ảnh thành
  // tài liệu/nguồn trong Sổ tay. Khi người dùng gửi câu hỏi, AI sẽ tập trung trả
  // lời dựa trên nội dung ảnh này + câu hỏi, thay vì đọc từ các nguồn đã tải lên.
  async function uploadPastedImage(file) {
    const id = crypto.randomUUID();
    const attachment = {
      id,
      filename: file.name || `anh-dan-${Date.now()}.png`,
      previewUrl: URL.createObjectURL(file),
      status: "uploading",
      ocrText: null,
      error: null,
    };
    state.pendingChatAttachments.push(attachment);
    renderChatAttachments();

    const nbId = state.currentId;
    if (!nbId) {
      attachment.status = "error";
      attachment.error = "Hãy chọn một sổ tay trước.";
      renderChatAttachments();
      return;
    }

    const fd = new FormData();
    fd.append("file", file, attachment.filename);

    try {
      // Endpoint riêng, ephemeral: server OCR xong là xóa file tạm ngay, không
      // tạo tài liệu/nguồn nào trong Sổ tay cả.
      const res = await fetch(`/api/notebooks/${nbId}/chat/image-context`, {
        method: "POST",
        body: fd,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Lỗi đọc ảnh");
      attachment.ocrText = data.text;
      attachment.status = "done";
    } catch (err) {
      attachment.status = "error";
      attachment.error = err.message;
    }
    renderChatAttachments();
  }

  // Ctrl+V: dán ảnh trực tiếp vào khung chat (ảnh sẽ đi cùng câu hỏi hiện tại),
  // hoặc dán văn bản như bình thường vào ô nhập.
  chatInput.addEventListener("paste", (e) => {
    const items = Array.from(e.clipboardData?.items || []);
    const imageItem = items.find((item) => item.kind === "file" && item.type.startsWith("image/"));
    if (!imageItem) return; // dán văn bản: để trình duyệt xử lý mặc định
    const file = imageItem.getAsFile();
    if (!file) return;
    e.preventDefault();
    uploadPastedImage(file);
  });

  function hasBusyAttachments() {
    return state.pendingChatAttachments.some((a) => a.status === "uploading");
  }

  chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const question = chatInput.value.trim();
    const attachmentCount = state.pendingChatAttachments.length;
    if ((!question && !attachmentCount) || !state.currentId) return;

    if (hasBusyAttachments()) {
      toast("Đang đọc ảnh vừa dán, vui lòng đợi trong giây lát rồi gửi lại…");
      return;
    }
    const failedAttachments = state.pendingChatAttachments.filter((a) => a.status === "error");
    if (failedAttachments.length) {
      toast(`Có ${failedAttachments.length} ảnh xử lý lỗi. Hãy bỏ ảnh đó hoặc thử dán lại trước khi gửi.`);
      return;
    }
    if (!question) return; // chỉ có ảnh, chưa có câu hỏi kèm theo

    // Gộp nội dung (đã OCR) của các ảnh vừa dán để gửi kèm câu hỏi — ảnh chỉ
    // nhất thời cho câu hỏi này, không phải nguồn đã lưu trong Sổ tay.
    const imageContext = state.pendingChatAttachments
      .filter((a) => a.status === "done" && a.ocrText)
      .map((a) => a.ocrText)
      .join("\n\n---\n\n");

    appendMessage("user", question, null);
    chatInput.value = "";
    state.pendingChatAttachments.forEach((a) => {
      if (a.previewUrl) URL.revokeObjectURL(a.previewUrl);
    });
    state.pendingChatAttachments = [];
    renderChatAttachments();
    autosizeChatInput();
    if (chatInputExpanded) setChatInputExpanded(false);
    const thinking = document.createElement("div");
    thinking.className = "msg msg-assistant";
    thinking.innerHTML = `<div class="msg-role">Trợ lý</div><div class="msg-bubble">${imageContext ? "Đang xem ảnh…" : "Đang đọc tài liệu…"}</div>`;
    chatLog.appendChild(thinking);
    chatLog.scrollTop = chatLog.scrollHeight;

    try {
      const result = await api(`/api/notebooks/${state.currentId}/chat`, {
        method: "POST",
        body: JSON.stringify({ question, custom_instructions: getCustomInstructions(), image_context: imageContext }),
      });
      thinking.remove();
      appendMessage("assistant", result.answer, result.citations);
      addAiMemoryEntry(question, result.answer);
      state.currentNotebook = await api(`/api/notebooks/${state.currentId}`);
    } catch (err) {
      thinking.remove();
      appendMessage("assistant", `⚠️ ${err.message}`, null);
    }
  });

  // ---------- Studio tabs ----------

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => {
        p.classList.remove("active");
        p.classList.remove("studio-expanded");
        p.style.cssText = "";
        p.style.display = "none";
        p.style.opacity = "1";
        p.style.visibility = "visible";
        p.style.transform = "none";
      });
      document.body.classList.remove("studio-modal-open");
      tab.classList.add("active");
      const panel = $(`#panel-${tab.dataset.tab}`);
      panel.style.cssText = "";
      panel.classList.add("active");
      panel.style.display = "block";
      panel.style.opacity = "1";
      panel.style.visibility = "visible";
      panel.style.transform = "none";
      document.querySelector(".studio-pane")?.classList.remove("studio-pane-expanded");
      updateStudioHistoryVisibility();
    });
  });

  function resetStudio() {
    $("#summaryOutput").innerHTML = "";
    $("#quizOutput").innerHTML = "";
    $("#audioOutput").innerHTML = "";
    $("#mindmapOutput").innerHTML = "";
    $("#flashcardsOutput").innerHTML = "";
    document.querySelector(".studio-pane")?.classList.remove("has-output");
  }

  function updateStudioHistoryVisibility() {
    const activeOutput = document.querySelector(".tab-panel.active .studio-output");
    const hasOutput = Boolean(activeOutput?.textContent.trim());
    document.querySelector(".studio-pane")?.classList.toggle("has-output", hasOutput);
  }

  document.querySelectorAll(".studio-output").forEach((output) => {
    new MutationObserver(updateStudioHistoryVisibility).observe(output, { childList: true, subtree: true, characterData: true });
  });

  async function saveStudioItem(type, title, content) {
    const data = await api(`/api/notebooks/${state.currentId}/studio`, {
      method: "POST",
      body: JSON.stringify({ type, title, content }),
    });
    state.currentNotebook.studio_items = [data.item, ...(state.currentNotebook.studio_items || [])];
    renderStudioHistory();
  }

  function setStudioGenerating(type, title, generating) {
    const history = $("#studioHistory");
    const pane = document.querySelector(".studio-pane");
    if (!history) return;
    const existing = history.querySelector(`[data-generating-type="${type}"]`);
    if (existing) existing.remove();
    if (!generating) {
      pane?.classList.remove("has-generating");
      return;
    }
    const item = document.createElement("div");
    item.className = "studio-history-item generating";
    item.dataset.generatingType = type;
    item.innerHTML = `<strong>Đang tạo ${escapeHtml(title)}...</strong><small>Dựa trên ${selectedDocumentIds("selected").length || 1} nguồn</small>`;
    history.prepend(item);
    pane?.classList.add("has-generating");
  }

  function activateStudioTab(type) {
    document.querySelector(`.tab[data-tab="${type}"]`)?.click();
  }

  function renderSavedStudioItem(item) {
    activateStudioTab(item.type);
    const out = $(`#${item.type === "flashcards" ? "flashcards" : item.type}Output`);
    if (!out) {
      return;
    }
    const content = item.content;
    if (item.type === "summary") {
      out.innerHTML = simpleMarkdown(String(content));
    } else if (item.type === "quiz") {
      let currentQuestion = 0;
      let score = 0;
      const addQuizCloseButton = () => {
        const closeButton = document.createElement("button");
        closeButton.type = "button";
        closeButton.className = "studio-saved-close";
        closeButton.innerHTML = '<i class="fa-solid fa-xmark"></i> Đóng Quiz';
        closeButton.addEventListener("click", () => {
          out.innerHTML = "";
          document.querySelectorAll(".studio-history-item").forEach((entry) => entry.classList.remove("active"));
          updateStudioHistoryVisibility();
        });
        out.prepend(closeButton);
      };
      const renderQuestion = () => {
        const question = content.questions?.[currentQuestion];
        if (!question) {
          out.innerHTML = `<div class="quiz-complete"><strong>Hoàn thành!</strong><span>Điểm: ${score}/${content.questions.length}</span><button type="button" class="btn-primary quiz-retry">Làm lại Quiz</button></div>`;
          out.querySelector(".quiz-retry").addEventListener("click", () => { currentQuestion = 0; score = 0; renderQuestion(); });
          addQuizCloseButton();
          return;
        }
        out.innerHTML = `<div class="quiz-card"><div class="quiz-progress">Câu ${currentQuestion + 1} / ${content.questions.length}</div><div class="quiz-q">${currentQuestion + 1}. ${escapeHtml(question.question || "")}</div><div class="quiz-options">${(question.options || []).map((option) => `<button class="quiz-opt" type="button">${escapeHtml(option)}</button>`).join("")}</div><div class="quiz-explain">${escapeHtml(question.explanation || "")}</div><button type="button" class="btn-primary quiz-next" disabled>${currentQuestion === content.questions.length - 1 ? "Xem kết quả" : "Câu tiếp theo"}</button></div>`;
        const card = out.querySelector(".quiz-card");
        const next = card.querySelector(".quiz-next");
        card.querySelectorAll(".quiz-opt").forEach((button, optionIndex) => button.addEventListener("click", () => {
          card.querySelectorAll(".quiz-opt").forEach((option) => option.disabled = true);
          const correctIndex = Number(question.correct_index);
          if (optionIndex === correctIndex) { score += 1; button.classList.add("correct"); } else { button.classList.add("wrong"); card.querySelectorAll(".quiz-opt")[correctIndex]?.classList.add("correct"); }
          card.querySelector(".quiz-explain").classList.add("show");
          next.disabled = false;
        }));
        next.addEventListener("click", () => { currentQuestion += 1; renderQuestion(); });
        addQuizCloseButton();
      };
      if (content.questions?.length) renderQuestion(); else out.innerHTML = "<p>Quiz không có câu hỏi.</p>";
    } else if (item.type === "flashcards") {
      const cards = Array.isArray(content.cards) ? content.cards : [];
      if (!cards.length) {
        out.innerHTML = "<p>Không có thẻ học nào.</p>";
      } else {
        let flashcardIndex = 0;
        let totalWrong = 0;
        let totalCorrect = 0;
        const ensureCloseButton = () => {
          const existing = out.querySelector(".studio-saved-close");
          if (existing) return;
          const closeButton = document.createElement("button");
          closeButton.type = "button";
          closeButton.className = "studio-saved-close";
          closeButton.innerHTML = '<i class="fa-solid fa-xmark"></i> Đóng Flash cards';
          closeButton.addEventListener("click", () => {
            out.innerHTML = "";
            updateStudioHistoryVisibility();
          });
          out.prepend(closeButton);
        };
        const renderDeck = () => {
          const card = cards[flashcardIndex];
          const progress = cards.length ? `${flashcardIndex + 1} / ${cards.length}` : "0 / 0";
          out.innerHTML = `
            <div class="flashcard-view">
              <div class="flashcard-toolbar">
                <span class="flashcard-progress">${progress}</span>
                <span class="flashcard-status new">New</span>
              </div>
              <div class="flashcard-stage">
                <button type="button" class="flashcard-card" aria-label="Lật thẻ flashcard">
                  <div class="flashcard-face flashcard-face-front">
                    <p>${escapeHtml(card.front || "")}</p>
                  </div>
                  <div class="flashcard-face flashcard-face-back">
                    <p>${escapeHtml(card.back || "")}</p>
                  </div>
                </button>
              </div>
              <div class="flashcard-nav-row">
                <button type="button" class="flashcard-nav flashcard-prev" aria-label="Câu trước"><i class="fa-solid fa-arrow-left"></i></button>
                <button type="button" class="flashcard-nav flashcard-mark wrong" data-result="wrong" aria-label="Đánh dấu sai"><span><i class="fa-solid fa-xmark"></i></span><span class="flashcard-mark-count">${totalWrong}</span></button>
                <button type="button" class="flashcard-nav flashcard-mark correct" data-result="correct" aria-label="Đánh dấu đúng"><span><i class="fa-solid fa-check"></i></span><span class="flashcard-mark-count">${totalCorrect}</span></button>
                <button type="button" class="flashcard-nav flashcard-next" aria-label="Câu tiếp theo"><i class="fa-solid fa-arrow-right"></i></button>
              </div>
            </div>
          `;

          ensureCloseButton();
          const cardEl = out.querySelector(".flashcard-card");
          const statusEl = out.querySelector(".flashcard-status");
          const prevBtn = out.querySelector(".flashcard-prev");
          const nextBtn = out.querySelector(".flashcard-next");
          const markButtons = out.querySelectorAll(".flashcard-mark");
          let answered = false;
          let selectedResult = null;

          const syncStatus = () => {
            if (!statusEl) return;
            if (!answered) {
              statusEl.textContent = cardEl.classList.contains("is-flipped") ? "Reviewing" : "New";
              statusEl.className = "flashcard-status new";
              return;
            }
            if (selectedResult === "correct") {
              statusEl.textContent = "Correct";
              statusEl.className = "flashcard-status correct";
            } else {
              statusEl.textContent = "Missed";
              statusEl.className = "flashcard-status missed";
            }
          };

          cardEl.addEventListener("click", () => {
            if (answered) return;
            cardEl.classList.toggle("is-flipped");
            syncStatus();
          });

          markButtons.forEach((button) => {
            button.addEventListener("click", (event) => {
              event.stopPropagation();
              if (answered) return;
              answered = true;
              selectedResult = button.dataset.result;
              if (selectedResult === "wrong") totalWrong += 1;
              else totalCorrect += 1;
              cardEl.classList.add("answered");
              markButtons.forEach((mark) => {
                mark.disabled = true;
                if (mark.dataset.result === selectedResult) {
                  mark.classList.add("selected");
                }
                const countNode = mark.querySelector(".flashcard-mark-count");
                if (countNode) {
                  countNode.textContent = mark.dataset.result === "wrong" ? String(totalWrong) : String(totalCorrect);
                }
              });
              syncStatus();
            });
          });

          prevBtn.addEventListener("click", () => {
            flashcardIndex = flashcardIndex > 0 ? flashcardIndex - 1 : cards.length - 1;
            renderDeck();
          });
          nextBtn.addEventListener("click", () => {
            flashcardIndex = flashcardIndex < cards.length - 1 ? flashcardIndex + 1 : 0;
            renderDeck();
          });
        };
        renderDeck();
      }
    } else if (item.type === "audio") {
      out.innerHTML = (content.turns || []).map((turn) => `<div class="podcast-turn"><b>${escapeHtml(turn.speaker)}:</b> ${escapeHtml(turn.text)}</div>`).join("") + `<audio controls src="${escapeHtml(content.audio_url || "")}"></audio>`;
    } else if (item.type === "mindmap") {
      const shortText = (value, length = 90) => {
        const text = String(value || "").replace(/\s+/g, " ").trim();
        return text.length > length ? `${text.slice(0, length - 1)}…` : text;
      };
      const renderNode = (node, level = 0) => `
        <li class="mindmap-node level-${level}" data-summary="${escapeHtml(node.summary || "Chưa có mô tả chi tiết.")}">
          <div class="mindmap-node-label">
            ${node.children?.length ? `<button type="button" class="mindmap-toggle" aria-label="Mở nội dung nhánh">›</button>` : `<span class="mindmap-leaf">•</span>`}
            <strong>${escapeHtml(shortText(node.title, 55))}</strong>
          </div>
          <div class="mindmap-inline-detail" hidden></div>
          ${node.children?.length ? `<ul hidden>${node.children.map((child) => renderNode(child, level + 1)).join("")}</ul>` : ""}
        </li>`;
      out.innerHTML = `<div class="mindmap-result saved-mindmap-result"><div class="mindmap-toolbar"><span>${escapeHtml(content.title || "Mind map")}</span></div><div class="mindmap-saved-tree"><div class="mindmap-root"><strong>${escapeHtml(shortText(content.title || "Mind map", 55))}</strong><span>Chủ đề tổng quát</span></div><ul class="mindmap-tree">${(content.nodes || []).map((node) => renderNode(node, 0)).join("")}</ul></div></div>`;
      out.querySelectorAll(".mindmap-toggle").forEach((toggle) => {
        toggle.addEventListener("click", () => {
          const node = toggle.closest(".mindmap-node");
          const children = node?.querySelector(":scope > ul");
          const detail = node?.querySelector(":scope > .mindmap-inline-detail");
          if (!children) return;
          const opening = children.hidden;
          children.hidden = !opening;
          if (detail) {
            detail.hidden = !opening;
            detail.textContent = node.dataset.summary || "Chưa có mô tả chi tiết.";
          }
          toggle.textContent = opening ? "⌄" : "›";
        });
      });
    }
    if (item.type !== "quiz") {
      const closeButton = document.createElement("button");
      closeButton.type = "button";
      closeButton.className = "studio-saved-close";
      closeButton.innerHTML = '<i class="fa-solid fa-xmark"></i> Đóng';
      closeButton.addEventListener("click", () => {
        out.innerHTML = "";
        document.querySelectorAll(".studio-history-item").forEach((entry) => entry.classList.remove("active"));
        updateStudioHistoryVisibility();
      });
      out.prepend(closeButton);
    }
    updateStudioHistoryVisibility();
  }

  function renderStudioHistory() {
    const history = $("#studioHistory");
    if (!history) return;
    history.innerHTML = "";
    (state.currentNotebook?.studio_items || []).forEach((item, index) => {
      const itemId = item.id || item.created_at || `legacy-${index}`;
      const itemRow = document.createElement("div");
      itemRow.className = "studio-history-row";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "studio-history-item";
      button.innerHTML = `<strong>${escapeHtml(item.title || item.type)}</strong><small>${escapeHtml(item.type)} · ${escapeHtml(item.created_at || "")}</small>`;
      button.addEventListener("click", () => {
        document.querySelectorAll(".studio-history-item").forEach((entry) => entry.classList.remove("active"));
        button.classList.add("active");
        renderSavedStudioItem(item);
      });
      const deleteButton = document.createElement("button");
      deleteButton.type = "button";
      deleteButton.className = "studio-history-delete";
      deleteButton.title = "Xóa sản phẩm đã lưu";
      deleteButton.setAttribute("aria-label", `Xóa ${item.title || item.type}`);
      deleteButton.innerHTML = '<i class="fa-solid fa-trash-can"></i>';
      deleteButton.addEventListener("click", async (event) => {
        event.stopPropagation();
        if (!window.confirm("Xóa sản phẩm này khỏi notebook?")) return;
        deleteButton.disabled = true;
        try {
          await api(`/api/notebooks/${state.currentId}/studio/${encodeURIComponent(itemId)}`, { method: "DELETE" });
          state.currentNotebook.studio_items = (state.currentNotebook.studio_items || []).filter((savedItem) => (savedItem.id || savedItem.created_at || `legacy-${index}`) !== itemId);
          if (button.classList.contains("active")) resetStudio();
          renderStudioHistory();
        } catch (error) {
          deleteButton.disabled = false;
          toast(error.message);
        }
      });
      itemRow.append(button, deleteButton);
      history.appendChild(itemRow);
    });
  }

  function simpleMarkdown(md) {
    const lines = md.split("\n");
    let html = "";
    let inList = false;
    for (const line of lines) {
      if (/^##\s+/.test(line)) {
        if (inList) { html += "</ul>"; inList = false; }
        html += `<h2>${escapeHtml(line.replace(/^##\s+/, ""))}</h2>`;
      } else if (/^[-*]\s+/.test(line)) {
        if (!inList) { html += "<ul>"; inList = true; }
        html += `<li>${escapeHtml(line.replace(/^[-*]\s+/, ""))}</li>`;
      } else if (line.trim() === "") {
        if (inList) { html += "</ul>"; inList = false; }
      } else {
        if (inList) { html += "</ul>"; inList = false; }
        html += `<p>${escapeHtml(line)}</p>`;
      }
    }
    if (inList) html += "</ul>";
    return html;
  }

  $("#genSummaryBtn").addEventListener("click", async () => {
    const button = $("#genSummaryBtn");
    const out = $("#summaryOutput");
    button.disabled = true;
    setStudioGenerating("summary", "Tóm tắt", true);
    out.innerHTML = "<p>Đang tổng hợp…</p>";
    try {
      const data = await api(`/api/notebooks/${state.currentId}/summary`, {
        method: "POST",
        body: JSON.stringify({
          document_ids: selectedDocumentIds($("#summaryScope").value),
          custom_instructions: getCustomInstructions(),
        }),
      });
      out.innerHTML = simpleMarkdown(data.summary);
      await saveStudioItem("summary", "Tóm tắt: " + new Date().toLocaleString("vi-VN"), data.summary);
    } catch (e) {
      out.innerHTML = `<p>⚠️ ${escapeHtml(e.message)}</p>`;
    } finally {
      setStudioGenerating("summary", "Tóm tắt", false);
      button.disabled = false;
    }
  });

  $("#genQuizBtn").addEventListener("click", async () => {
    const button = $("#genQuizBtn");
    const out = $("#quizOutput");
    button.disabled = true;
    setStudioGenerating("quiz", "Quiz", true);
    out.innerHTML = "<p>Đang tạo câu hỏi…</p>";
    try {
      const data = await api(`/api/notebooks/${state.currentId}/quiz`, {
        method: "POST",
        body: JSON.stringify({
          document_ids: selectedDocumentIds($("#quizScope").value),
          topic: $("#quizTopic").value.trim(),
          n_questions: Number($("#quizCount").value),
          difficulty: $("#quizDifficulty").value,
          custom_instructions: getCustomInstructions(),
        }),
      });
      out.innerHTML = "";
      let currentQuestion = 0;
      let score = 0;
      const addGeneratedQuizCloseButton = () => {
        const closeButton = document.createElement("button");
        closeButton.type = "button";
        closeButton.className = "studio-saved-close";
        closeButton.innerHTML = '<i class="fa-solid fa-xmark"></i> Đóng Quiz';
        closeButton.addEventListener("click", () => {
          out.innerHTML = "";
          updateStudioHistoryVisibility();
        });
        out.prepend(closeButton);
      };

      function renderQuizQuestion() {
        const q = data.questions[currentQuestion];
        if (!q) {
          out.innerHTML = `<div class="quiz-complete"><strong>Hoàn thành!</strong><span>Điểm: ${score}/${data.questions.length}</span><button type="button" class="btn-primary quiz-retry">Làm lại Quiz</button></div>`;
          out.querySelector(".quiz-retry").addEventListener("click", () => { currentQuestion = 0; score = 0; renderQuizQuestion(); });
          addGeneratedQuizCloseButton();
          return;
        }
        out.innerHTML = "";
        const card = document.createElement("div");
        card.className = "quiz-card";
        card.innerHTML = `
          <div class="quiz-progress">Câu ${currentQuestion + 1} / ${data.questions.length}</div>
          <div class="quiz-q">${currentQuestion + 1}. ${escapeHtml(q.question)}</div>
          <div class="quiz-options">
            ${q.options
              .map((opt, oi) => `<button class="quiz-opt" data-oi="${oi}">${escapeHtml(opt)}</button>`)
              .join("")}
          </div>
          <div class="quiz-explain">${escapeHtml(q.explanation || "")}</div>
          <button class="btn-primary quiz-next" disabled>${currentQuestion === data.questions.length - 1 ? "Xem kết quả" : "Câu tiếp theo"}</button>
        `;
        const next = card.querySelector(".quiz-next");
        card.querySelectorAll(".quiz-opt").forEach((btn) => {
          btn.addEventListener("click", () => {
            const oi = Number(btn.dataset.oi);
            card.querySelectorAll(".quiz-opt").forEach((option) => (option.disabled = true));
            const correctIndex = Number(q.correct_index);
            if (oi === correctIndex) {
              score += 1;
              btn.classList.add("correct");
            } else {
              btn.classList.add("wrong");
              card.querySelector(`[data-oi="${correctIndex}"]`).classList.add("correct");
            }
            card.querySelector(".quiz-explain").classList.add("show");
            next.disabled = false;
          });
        });
        next.addEventListener("click", () => {
          currentQuestion += 1;
          renderQuizQuestion();
        });
        out.appendChild(card);
        addGeneratedQuizCloseButton();
      }

      if (data.questions.length) renderQuizQuestion();
      else out.innerHTML = "<p>Không tạo được câu hỏi nào.</p>";
      await saveStudioItem("quiz", `Quiz: ${$("#quizTopic").value.trim() || "Không tên"}`, data);
    } catch (e) {
      out.innerHTML = `<p>⚠️ ${escapeHtml(e.message)}</p>`;
    } finally {
      setStudioGenerating("quiz", "Quiz", false);
      button.disabled = false;
    }
  });

  $("#genAudioBtn").addEventListener("click", async () => {
    const button = $("#genAudioBtn");
    const out = $("#audioOutput");
    button.disabled = true;
    out.innerHTML = "<p>Đang viết kịch bản và tạo giọng đọc… (có thể mất một lúc)</p>";
    try {
      const data = await api(`/api/notebooks/${state.currentId}/audio`, {
        method: "POST",
        body: JSON.stringify({
          document_ids: selectedDocumentIds($("#audioScope").value),
          custom_instructions: getCustomInstructions(),
        }),
      });
      const turnsHtml = data.turns
        .map((t) => `<div class="podcast-turn"><b>${t.speaker}:</b> ${escapeHtml(t.text)}</div>`)
        .join("");
      out.innerHTML = `${turnsHtml}<audio controls src="${data.audio_url}"></audio>`;
      await saveStudioItem("audio", "Audio: " + new Date().toLocaleString("vi-VN"), data);
    } catch (e) {
      out.innerHTML = `<p>⚠️ ${escapeHtml(e.message)}</p>`;
    } finally {
      button.disabled = false;
    }
  });

  $("#genMindmapBtn").addEventListener("click", async () => {
    const button = $("#genMindmapBtn");
    const out = $("#mindmapOutput");
    button.disabled = true;
    setStudioGenerating("mindmap", "Mind map", true);
    out.innerHTML = "<p>Đang tạo sơ đồ…</p>";
    try {
      const data = await api(`/api/notebooks/${state.currentId}/mindmap`, {
        method: "POST",
        body: JSON.stringify({
          document_ids: selectedDocumentIds($("#mindmapScope").value),
          topic: $("#mindmapTopic").value.trim(),
          custom_instructions: getCustomInstructions(),
        }),
      });
      const shortText = (value, length = 90) => {
        const text = String(value || "").replace(/\s+/g, " ").trim();
        return text.length > length ? `${text.slice(0, length - 1)}…` : text;
      };
      const renderNode = (node, level = 0) => `
        <li class="mindmap-node level-${level}" data-summary="${escapeHtml(node.summary || "Chưa có mô tả chi tiết.")}" >
          <div class="mindmap-node-label">
            ${node.children?.length ? `<button type="button" class="mindmap-toggle" aria-label="Mở nội dung nhánh">›</button>` : `<span class="mindmap-leaf">•</span>`}
            <strong>${escapeHtml(shortText(node.title, 55))}</strong>
          </div>
          <div class="mindmap-inline-detail" hidden></div>
          ${node.children?.length ? `<ul hidden>${node.children.map((child) => renderNode(child, level + 1)).join("")}</ul>` : ""}
        </li>`;
      out.innerHTML = `<div class="mindmap-result"><div class="mindmap-toolbar"><span>Mind map · Kéo để di chuyển · Lăn chuột để zoom</span></div><div class="mindmap-canvas"><div class="mindmap-canvas-tools"><button type="button" class="mindmap-zoom-out" title="Thu nhỏ"><i class="fa-solid fa-minus"></i></button><output class="mindmap-zoom-value">100%</output><button type="button" class="mindmap-zoom-in" title="Phóng to"><i class="fa-solid fa-plus"></i></button><button type="button" class="mindmap-reset" title="Đặt lại vị trí"><i class="fa-solid fa-rotate-right"></i></button><button type="button" class="mindmap-expand" title="Phóng to Mind map"><i class="fa-solid fa-expand"></i></button></div><div class="mindmap-viewport"><div class="mindmap-root"><strong>${escapeHtml(shortText(data.title || "Mind map", 55))}</strong><span>Chủ đề tổng quát</span></div><div class="mindmap-branches"><ul class="mindmap-tree">${(data.nodes || []).map((node) => renderNode(node, 0)).join("")}</ul></div></div></div><div class="mindmap-detail" hidden></div></div>`;
      const canvas = out.querySelector(".mindmap-canvas");
      const viewport = out.querySelector(".mindmap-viewport");
      const zoomValue = out.querySelector(".mindmap-zoom-value");
      let zoom = 1;
      let panX = 0;
      let panY = 0;
      let dragging = false;
      let dragStartX = 0;
      let dragStartY = 0;
      const updateViewport = () => {
        viewport.style.transform = `translate(${panX}px, ${panY}px) scale(${zoom})`;
      };
      canvas.addEventListener("wheel", (event) => {
        event.preventDefault();
        zoom = Math.max(0.45, Math.min(2.2, zoom + (event.deltaY < 0 ? 0.08 : -0.08)));
        updateViewport();
        zoomValue.textContent = `${Math.round(zoom * 100)}%`;
      }, { passive: false });
      const setZoom = (nextZoom) => {
        zoom = Math.max(0.45, Math.min(2.2, nextZoom));
        updateViewport();
        zoomValue.textContent = `${Math.round(zoom * 100)}%`;
      };
      out.querySelector(".mindmap-zoom-in").addEventListener("click", () => setZoom(zoom + 0.1));
      out.querySelector(".mindmap-zoom-out").addEventListener("click", () => setZoom(zoom - 0.1));
      out.querySelector(".mindmap-reset").addEventListener("click", () => {
        panX = 0;
        panY = 0;
        setZoom(1);
      });
      canvas.addEventListener("pointerdown", (event) => {
        if (event.target.closest("button")) return;
        dragging = true;
        dragStartX = event.clientX - panX;
        dragStartY = event.clientY - panY;
        canvas.setPointerCapture(event.pointerId);
      });
      canvas.addEventListener("pointermove", (event) => {
        if (!dragging) return;
        panX = event.clientX - dragStartX;
        panY = event.clientY - dragStartY;
        updateViewport();
      });
      canvas.addEventListener("pointerup", () => { dragging = false; });
      canvas.addEventListener("click", (event) => {
        const toggle = event.target.closest(".mindmap-toggle");
        if (toggle) {
          const children = toggle.closest(".mindmap-node")?.querySelector(":scope > ul");
          if (children) {
            const node = toggle.closest(".mindmap-node");
            const detail = node.querySelector(":scope > .mindmap-inline-detail");
            const opening = children.hidden;
            children.hidden = !opening;
            detail.hidden = !opening;
            detail.textContent = node.dataset.summary || "Chưa có mô tả chi tiết.";
            toggle.textContent = opening ? "⌄" : "›";
          }
        }
      });
      out.querySelector(".mindmap-expand").addEventListener("click", () => {
        const panel = $("#panel-mindmap");
        const expanded = panel.classList.toggle("studio-expanded");
        document.body.classList.toggle("studio-modal-open", expanded);
      });
      const closeMindmapButton = document.createElement("button");
      closeMindmapButton.type = "button";
      closeMindmapButton.className = "studio-saved-close";
      closeMindmapButton.innerHTML = '<i class="fa-solid fa-xmark"></i> Đóng Mind map';
      closeMindmapButton.addEventListener("click", () => {
        out.innerHTML = "";
        updateStudioHistoryVisibility();
      });
      out.prepend(closeMindmapButton);
      await saveStudioItem("mindmap", `Mind map: ${$("#mindmapTopic").value.trim() || "Không tên"}`, data);
    } catch (e) {
      out.innerHTML = `<p>⚠️ ${escapeHtml(e.message)}</p>`;
    } finally {
      setStudioGenerating("mindmap", "Mind map", false);
      button.disabled = false;
    }
  });

  $("#genFlashcardsBtn").addEventListener("click", async () => {
    const button = $("#genFlashcardsBtn");
    const out = $("#flashcardsOutput");
    button.disabled = true;
    out.innerHTML = "<p>Đang tạo thẻ học…</p>";
    try {
      const data = await api(`/api/notebooks/${state.currentId}/flashcards`, {
        method: "POST",
        body: JSON.stringify({
          document_ids: selectedDocumentIds($("#flashcardScope").value),
          topic: $("#flashcardTopic").value.trim(),
          n_cards: Number($("#flashcardCount").value),
          custom_instructions: getCustomInstructions(),
        }),
      });
      const cards = Array.isArray(data.cards) ? data.cards : [];
      if (!cards.length) {
        out.innerHTML = "<p>Không có thẻ học nào.</p>";
      } else {
        let flashcardIndex = 0;
        let totalWrong = 0;
        let totalCorrect = 0;
        const ensureCloseButton = () => {
          const existing = out.querySelector(".studio-saved-close");
          if (existing) return;
          const closeButton = document.createElement("button");
          closeButton.type = "button";
          closeButton.className = "studio-saved-close";
          closeButton.innerHTML = '<i class="fa-solid fa-xmark"></i> Đóng Flash cards';
          closeButton.addEventListener("click", () => {
            out.innerHTML = "";
            updateStudioHistoryVisibility();
          });
          out.prepend(closeButton);
        };
        const renderDeck = () => {
          const card = cards[flashcardIndex];
          out.innerHTML = `
            <div class="flashcard-view">
              <div class="flashcard-toolbar">
                <span class="flashcard-progress">${flashcardIndex + 1} / ${cards.length}</span>
                <span class="flashcard-status new">New</span>
              </div>
              <div class="flashcard-stage">
                <button type="button" class="flashcard-card" aria-label="Lật thẻ flashcard">
                  <div class="flashcard-face flashcard-face-front">
                    <p>${escapeHtml(card.front || "")}</p>
                  </div>
                  <div class="flashcard-face flashcard-face-back">
                    <p>${escapeHtml(card.back || "")}</p>
                  </div>
                </button>
              </div>
              <div class="flashcard-nav-row">
                <button type="button" class="flashcard-nav flashcard-prev" aria-label="Câu trước"><i class="fa-solid fa-arrow-left"></i></button>
                <button type="button" class="flashcard-nav flashcard-mark wrong" data-result="wrong" aria-label="Đánh dấu sai"><span><i class="fa-solid fa-xmark"></i></span><span class="flashcard-mark-count">${totalWrong}</span></button>
                <button type="button" class="flashcard-nav flashcard-mark correct" data-result="correct" aria-label="Đánh dấu đúng"><span><i class="fa-solid fa-check"></i></span><span class="flashcard-mark-count">${totalCorrect}</span></button>
                <button type="button" class="flashcard-nav flashcard-next" aria-label="Câu tiếp theo"><i class="fa-solid fa-arrow-right"></i></button>
              </div>
            </div>
          `;

          ensureCloseButton();
          const cardEl = out.querySelector(".flashcard-card");
          const statusEl = out.querySelector(".flashcard-status");
          const prevBtn = out.querySelector(".flashcard-prev");
          const nextBtn = out.querySelector(".flashcard-next");
          const markButtons = out.querySelectorAll(".flashcard-mark");
          let answered = false;
          let selectedResult = null;

          const syncStatus = () => {
            if (!statusEl) return;
            if (!answered) {
              statusEl.textContent = cardEl.classList.contains("is-flipped") ? "Reviewing" : "New";
              statusEl.className = "flashcard-status new";
              return;
            }
            if (selectedResult === "correct") {
              statusEl.textContent = "Correct";
              statusEl.className = "flashcard-status correct";
            } else {
              statusEl.textContent = "Missed";
              statusEl.className = "flashcard-status missed";
            }
          };

          cardEl.addEventListener("click", () => {
            if (answered) return;
            cardEl.classList.toggle("is-flipped");
            syncStatus();
          });

          markButtons.forEach((button) => {
            button.addEventListener("click", (event) => {
              event.stopPropagation();
              if (answered) return;
              answered = true;
              selectedResult = button.dataset.result;
              if (selectedResult === "wrong") totalWrong += 1;
              else totalCorrect += 1;
              cardEl.classList.add("answered");
              markButtons.forEach((mark) => {
                mark.disabled = true;
                if (mark.dataset.result === selectedResult) {
                  mark.classList.add("selected");
                }
                const countNode = mark.querySelector(".flashcard-mark-count");
                if (countNode) {
                  countNode.textContent = mark.dataset.result === "wrong" ? String(totalWrong) : String(totalCorrect);
                }
              });
              syncStatus();
            });
          });

          prevBtn.addEventListener("click", () => {
            flashcardIndex = flashcardIndex > 0 ? flashcardIndex - 1 : cards.length - 1;
            renderDeck();
          });
          nextBtn.addEventListener("click", () => {
            flashcardIndex = flashcardIndex < cards.length - 1 ? flashcardIndex + 1 : 0;
            renderDeck();
          });
        };
        renderDeck();
      }
      await saveStudioItem("flashcards", `Flashcards: ${$("#flashcardTopic").value.trim() || "Không tên"}`, data);
    } catch (e) {
      out.innerHTML = `<p>⚠️ ${escapeHtml(e.message)}</p>`;
    } finally {
      button.disabled = false;
    }
  });

  // Studio Pane Expand/Collapse
  const studioPaneExpandBtn = document.querySelector(".studio-pane-expand");
  const studioPane = document.querySelector(".studio-pane");
  
  if (studioPaneExpandBtn && studioPane) {
    studioPaneExpandBtn.addEventListener("click", () => {
      const isExpanded = studioPane.classList.contains("studio-expanded");
      studioPane.classList.toggle("studio-expanded");
      document.body.classList.toggle("studio-modal-open", !isExpanded);
      studioPaneExpandBtn.innerHTML = isExpanded ? '<i class="fa-solid fa-expand"></i>' : '<i class="fa-solid fa-xmark"></i>';
      studioPaneExpandBtn.title = isExpanded ? "Phóng to" : "Thu nhỏ";
      studioPaneExpandBtn.setAttribute("aria-label", isExpanded ? "Phóng to" : "Thu nhỏ");
    });
  }

  // Close expanded studio when clicking outside or pressing Escape
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && studioPane && studioPane.classList.contains("studio-expanded")) {
      studioPane.classList.remove("studio-expanded");
      document.body.classList.remove("studio-modal-open");
      if (studioPaneExpandBtn) {
        studioPaneExpandBtn.innerHTML = '<i class="fa-solid fa-expand"></i>';
        studioPaneExpandBtn.title = "Phóng to";
        studioPaneExpandBtn.setAttribute("aria-label", "Phóng to");
      }
    }
  });

  // ---------- Resizable sidebars ----------

  document.querySelectorAll(".resize-handle").forEach((handle) => {
    handle.addEventListener("pointerdown", (event) => {
      if (window.innerWidth <= 900) return;
      event.preventDefault();
      const type = handle.dataset.resize;
      const startX = event.clientX;
      const startColumns = getComputedStyle(workspace).gridTemplateColumns.split(" ");
      const startWidth = type === "sources"
        ? parseFloat(startColumns[0])
        : parseFloat(startColumns[startColumns.length - 1]);
      handle.setPointerCapture(event.pointerId);
      const move = (moveEvent) => {
        const delta = moveEvent.clientX - startX;
        const width = Math.max(190, Math.min(480, startWidth + (type === "sources" ? delta : -delta)));
        if (type === "sources") {
          workspace.style.gridTemplateColumns = `${width}px 8px minmax(0, 1fr) 8px ${startColumns.at(-1)}`;
        } else {
          workspace.style.gridTemplateColumns = `${startColumns[0]} 8px minmax(0, 1fr) 8px ${width}px`;
        }
      };
      const stop = () => {
        handle.releasePointerCapture(event.pointerId);
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", stop);
      };
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", stop);
    });
  });

  // ---------- Boot ----------

  setAuthMode("login");
  updateAuthUi();
  loadSession();
})();
