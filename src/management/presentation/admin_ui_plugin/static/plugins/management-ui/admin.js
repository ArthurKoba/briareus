(() => {
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

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => applyLocalDateTimes());
  } else {
    applyLocalDateTimes();
  }
  window.addEventListener("pageshow", () => applyLocalDateTimes());
})();
