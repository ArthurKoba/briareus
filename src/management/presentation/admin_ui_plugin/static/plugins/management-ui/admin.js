(() => {
  const THEME_KEY = "mcp-admin-theme";
  const VALID_THEMES = new Set(["light", "dark"]);

  function preferredTheme() {
    const saved = window.localStorage.getItem(THEME_KEY);
    if (saved && VALID_THEMES.has(saved)) return saved;
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function applyTheme(theme) {
    const normalized = VALID_THEMES.has(theme) ? theme : "light";
    document.documentElement.setAttribute("data-bs-theme", normalized);
    document.documentElement.style.colorScheme = normalized;
    window.localStorage.setItem(THEME_KEY, normalized);
    document.querySelectorAll("[data-mcp-theme-toggle]").forEach(button => {
      const next = normalized === "dark" ? "light" : "dark";
      button.setAttribute("aria-label", `Switch to ${next} theme`);
      button.setAttribute("title", `Switch to ${next} theme`);
      button.innerHTML = normalized === "dark"
        ? '<i class="fa-solid fa-sun" aria-hidden="true"></i>'
        : '<i class="fa-solid fa-moon" aria-hidden="true"></i>';
    });
  }

  function toggleTheme() {
    applyTheme(document.documentElement.getAttribute("data-bs-theme") === "dark" ? "light" : "dark");
  }

  function themeButton(extraClass = "") {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `btn btn-icon ${extraClass}`.trim();
    button.dataset.mcpThemeToggle = "1";
    button.addEventListener("click", toggleTheme);
    return button;
  }

  function installThemeControls() {
    const desktopNav = document.querySelector("header.navbar .navbar-nav.flex-row.order-md-last");
    if (desktopNav && !desktopNav.querySelector("[data-mcp-theme-toggle]")) {
      desktopNav.prepend(themeButton());
    }

    const mobileNav = document.querySelector("aside.navbar .navbar-nav.flex-row.d-lg-none");
    if (mobileNav && !mobileNav.querySelector("[data-mcp-theme-toggle]")) {
      mobileNav.prepend(themeButton("btn-ghost-light"));
    }

    if (!desktopNav && !mobileNav && !document.querySelector("[data-mcp-theme-toggle]")) {
      const floating = themeButton("mcp-theme-toggle-floating");
      document.body.appendChild(floating);
    }

    applyTheme(preferredTheme());
  }

  function formatLocalDateTime(element) {
    const raw = element.getAttribute("datetime");
    if (!raw) return;

    const value = new Date(raw);
    if (Number.isNaN(value.getTime())) return;

    element.textContent = new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "medium",
    }).format(value);
    element.title = raw;
  }

  function applyLocalDateTimes(root = document) {
    root.querySelectorAll("time.js-local-datetime").forEach(formatLocalDateTime);
  }

  function initialize() {
    installThemeControls();
    applyLocalDateTimes();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize);
  } else {
    initialize();
  }
  window.addEventListener("pageshow", initialize);
})();
