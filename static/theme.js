/*
 * Bộ tuỳ chỉnh màu giao diện (theme customizer).
 * - Áp dụng bảng màu ngay khi file này chạy (trước khi trang vẽ ra) để tránh
 *   hiện tượng "chớp" màu mặc định rồi mới đổi màu đã lưu.
 * - Lưu lựa chọn vào localStorage để tải lại trang vẫn giữ nguyên.
 * - Dựng một nút nổi (FAB) + bảng điều khiển nhỏ ở góc màn hình khi DOM sẵn sàng.
 */
(function () {
  "use strict";

  var STORAGE_KEY = "songhiencuu_theme_v1";

  // Bảng màu gốc của trang (dùng cho nút "Mặc định").
  var DEFAULT_PALETTE = {
    bg: "#F2EFE3",
    panel: "#FBFAF4",
    ink: "#202B1E",
    muted: "#6C7460",
    accent: "#3E6A48",
    accentDark: "#2C4E34",
    accentSoft: "#E3EBD9",
    line: "#DAD4BF"
  };

  var PRESETS = {
    "default": DEFAULT_PALETTE,
    "neon-cyan": {
      bg: "#05090b", panel: "#0c1517", ink: "#d8fbff", muted: "#5fa3a8",
      accent: "#00e5ff", accentDark: "#00aecb", accentSoft: "#082a2f", line: "#123338"
    },
    "dark-purple": {
      bg: "#140a1c", panel: "#1e1029", ink: "#f1e6ff", muted: "#9483ac",
      accent: "#a463f2", accentDark: "#7e3fd1", accentSoft: "#2a1638", line: "#3a2350"
    },
    "cyberpunk": {
      bg: "#0a0014", panel: "#160021", ink: "#f5f0ff", muted: "#c58fe6",
      accent: "#ff2bd6", accentDark: "#c400a0", accentSoft: "#2b0033", line: "#420a5c"
    },
    // Preset này bật kèm RGB Mode để có hiệu ứng đổi màu liên tục ngay khi chọn.
    "rgb-gradient": {
      bg: "#07060d", panel: "#0f0d1a", ink: "#f5f5ff", muted: "#9c9ac2",
      accent: "#ff2bd6", accentDark: "#7e3fd1", accentSoft: "#151029", line: "#2a2550"
    }
  };

  var CSS_VAR_NAMES = {
    bg: "--bg", panel: "--panel", ink: "--ink", muted: "--muted",
    accent: "--accent", accentDark: "--accent-dark", accentSoft: "--accent-soft", line: "--line"
  };
  var VAR_KEYS = Object.keys(CSS_VAR_NAMES);

  function clamp(n, min, max) { return Math.max(min, Math.min(max, n)); }

  function hexToRgb(hex) {
    hex = hex.replace("#", "");
    if (hex.length === 3) hex = hex.split("").map(function (c) { return c + c; }).join("");
    var num = parseInt(hex, 16);
    return { r: (num >> 16) & 255, g: (num >> 8) & 255, b: num & 255 };
  }

  function rgbToHex(r, g, b) {
    return "#" + [r, g, b].map(function (v) {
      v = clamp(Math.round(v), 0, 255);
      var s = v.toString(16);
      return s.length === 1 ? "0" + s : s;
    }).join("");
  }

  function hexToHsl(hex) {
    var rgb = hexToRgb(hex);
    var r = rgb.r / 255, g = rgb.g / 255, b = rgb.b / 255;
    var max = Math.max(r, g, b), min = Math.min(r, g, b);
    var h, s, l = (max + min) / 2;
    if (max === min) {
      h = s = 0;
    } else {
      var d = max - min;
      s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
      switch (max) {
        case r: h = (g - b) / d + (g < b ? 6 : 0); break;
        case g: h = (b - r) / d + 2; break;
        default: h = (r - g) / d + 4; break;
      }
      h /= 6;
    }
    return { h: h * 360, s: s * 100, l: l * 100 };
  }

  function hslToHex(h, s, l) {
    h = ((h % 360) + 360) % 360;
    h /= 360; s /= 100; l /= 100;
    var r, g, b;
    if (s === 0) {
      r = g = b = l;
    } else {
      var hue2rgb = function (p, q, t) {
        if (t < 0) t += 1;
        if (t > 1) t -= 1;
        if (t < 1 / 6) return p + (q - p) * 6 * t;
        if (t < 1 / 2) return q;
        if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
        return p;
      };
      var q = l < 0.5 ? l * (1 + s) : l + s - l * s;
      var p = 2 * l - q;
      r = hue2rgb(p, q, h + 1 / 3);
      g = hue2rgb(p, q, h);
      b = hue2rgb(p, q, h - 1 / 3);
    }
    return rgbToHex(r * 255, g * 255, b * 255);
  }

  // Từ 1 màu do người dùng chọn, tự sinh ra cả bộ màu đồng bộ (nền/chữ/nút)
  // theo phong cách nền tối + màu nhấn nổi bật, giữ đúng tông (hue) đã chọn.
  function paletteFromCustomColor(hex) {
    var h = hexToHsl(hex).h;
    return {
      accent: hslToHex(h, 80, 55),
      accentDark: hslToHex(h, 75, 38),
      accentSoft: hslToHex(h, 45, 14),
      bg: hslToHex(h, 28, 6),
      panel: hslToHex(h, 24, 10),
      ink: hslToHex(h, 20, 94),
      muted: hslToHex(h, 20, 62),
      line: hslToHex(h, 28, 20)
    };
  }

  function readState() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (e) { return null; }
  }

  function writeState(state) {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch (e) { /* ignore */ }
  }

  function applyPalette(pal) {
    var root = document.documentElement;
    VAR_KEYS.forEach(function (key) {
      if (pal[key]) root.style.setProperty(CSS_VAR_NAMES[key], pal[key]);
    });
  }

  var rgbTimer = null;
  var hue = Math.random() * 360;

  function stopRgbMode() {
    if (rgbTimer) { clearInterval(rgbTimer); rgbTimer = null; }
    document.documentElement.classList.remove("rgb-mode-active");
  }

  function startRgbMode() {
    document.documentElement.classList.add("rgb-mode-active");
    if (rgbTimer) return;
    rgbTimer = setInterval(function () {
      hue = (hue + 2) % 360;
      var root = document.documentElement;
      // Đồng bộ cả nền, khung, viền, chữ mờ theo cùng vòng màu với nút bấm,
      // giữ độ sáng/độ tương phản cố định để chữ chính (--ink) vẫn đọc được.
      root.style.setProperty("--bg", hslToHex(hue, 32, 6));
      root.style.setProperty("--panel", hslToHex(hue, 26, 10));
      root.style.setProperty("--line", hslToHex(hue, 32, 20));
      root.style.setProperty("--muted", hslToHex(hue, 22, 62));
      root.style.setProperty("--ink", hslToHex(hue, 12, 94));
      root.style.setProperty("--accent", hslToHex(hue, 85, 58));
      root.style.setProperty("--accent-dark", hslToHex(hue, 80, 40));
      root.style.setProperty("--accent-soft", hslToHex(hue, 55, 16));
    }, 40);
  }

  var state = readState() || { preset: "default", customColor: "#3E6A48", rgbMode: false };
  if (!PRESETS[state.preset] && state.preset !== "custom") state.preset = "default";

  function currentPalette() {
    if (state.preset === "custom") return paletteFromCustomColor(state.customColor || "#3E6A48");
    return PRESETS[state.preset] || DEFAULT_PALETTE;
  }

  function applyState() {
    applyPalette(currentPalette());
    if (state.rgbMode) startRgbMode(); else stopRgbMode();
  }

  // Áp dụng NGAY khi script chạy (trong <head>), trước khi phần còn lại của
  // trang được vẽ ra, để không bị "chớp" màu mặc định trước rồi mới đổi.
  applyState();

  function setPreset(name) {
    state.preset = name;
    if (name === "rgb-gradient") state.rgbMode = true;
    writeState(state);
    applyState();
    syncPanelUI();
  }

  function setCustomColor(hex) {
    state.preset = "custom";
    state.customColor = hex;
    writeState(state);
    applyState();
    syncPanelUI();
  }

  function setRgbMode(on) {
    state.rgbMode = !!on;
    writeState(state);
    applyState();
    syncPanelUI();
  }

  function resetDefault() {
    state = { preset: "default", customColor: "#3E6A48", rgbMode: false };
    writeState(state);
    applyState();
    syncPanelUI();
  }

  var panelEl, fabEl, colorInputEl, rgbToggleEl;

  function syncPanelUI() {
    if (!panelEl) return;
    if (colorInputEl) colorInputEl.value = state.preset === "custom" ? state.customColor : colorInputEl.value;
    if (rgbToggleEl) rgbToggleEl.checked = !!state.rgbMode;
    var buttons = panelEl.querySelectorAll("[data-preset]");
    for (var i = 0; i < buttons.length; i++) {
      var isActive = buttons[i].getAttribute("data-preset") === state.preset;
      buttons[i].classList.toggle("active", isActive);
    }
  }

  function buildPanel() {
    if (!document.body || document.getElementById("themeFab")) return;

    fabEl = document.createElement("button");
    fabEl.type = "button";
    fabEl.id = "themeFab";
    fabEl.className = "theme-fab";
    fabEl.title = "Tuỳ chỉnh màu giao diện";
    fabEl.setAttribute("aria-label", "Tuỳ chỉnh màu giao diện");
    fabEl.innerHTML = '<i class="fa-solid fa-palette"></i>';

    panelEl = document.createElement("div");
    panelEl.id = "themePanel";
    panelEl.className = "theme-panel";
    panelEl.hidden = true;
    panelEl.innerHTML =
      '<div class="theme-panel-head">' +
        '<span>Giao diện màu sắc</span>' +
        '<button type="button" class="theme-panel-close" aria-label="Đóng"><i class="fa-solid fa-xmark"></i></button>' +
      "</div>" +
      '<div class="theme-presets">' +
        '<button type="button" class="theme-swatch" data-preset="default">Mặc định</button>' +
        '<button type="button" class="theme-swatch" data-preset="neon-cyan">Neon Cyan</button>' +
        '<button type="button" class="theme-swatch" data-preset="rgb-gradient">RGB Gradient</button>' +
        '<button type="button" class="theme-swatch" data-preset="dark-purple">Dark Purple</button>' +
        '<button type="button" class="theme-swatch" data-preset="cyberpunk">Cyberpunk</button>' +
      "</div>" +
      '<label class="theme-color-row">' +
        "<span>Màu tuỳ chọn</span>" +
        '<input type="color" class="theme-color-input" value="' + (state.customColor || "#3E6A48") + '">' +
      "</label>" +
      '<label class="theme-rgb-row">' +
        "<span>Chế độ RGB (tự đổi màu)</span>" +
        '<input type="checkbox" class="theme-rgb-toggle">' +
      "</label>";

    document.body.appendChild(fabEl);
    document.body.appendChild(panelEl);

    colorInputEl = panelEl.querySelector(".theme-color-input");
    rgbToggleEl = panelEl.querySelector(".theme-rgb-toggle");

    fabEl.addEventListener("click", function () {
      panelEl.hidden = !panelEl.hidden;
    });
    panelEl.querySelector(".theme-panel-close").addEventListener("click", function () {
      panelEl.hidden = true;
    });
    var presetButtons = panelEl.querySelectorAll("[data-preset]");
    for (var i = 0; i < presetButtons.length; i++) {
      presetButtons[i].addEventListener("click", function () {
        var name = this.getAttribute("data-preset");
        if (name === "default") resetDefault(); else setPreset(name);
      });
    }
    colorInputEl.addEventListener("input", function () {
      setCustomColor(colorInputEl.value);
    });
    rgbToggleEl.addEventListener("change", function () {
      setRgbMode(rgbToggleEl.checked);
    });

    document.addEventListener("click", function (e) {
      if (!panelEl.hidden && !panelEl.contains(e.target) && !fabEl.contains(e.target)) {
        panelEl.hidden = true;
      }
    });

    syncPanelUI();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", buildPanel);
  } else {
    buildPanel();
  }
})();
