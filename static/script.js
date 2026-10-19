document.addEventListener("DOMContentLoaded", () => {
  const menuButton = document.querySelector("[data-menu-toggle]");
  const sidebar = document.querySelector("#sidebar");

  if (menuButton && sidebar) {
    menuButton.addEventListener("click", () => {
      const isOpen = sidebar.classList.toggle("is-open");
      menuButton.setAttribute("aria-expanded", String(isOpen));
      menuButton.setAttribute("aria-label", isOpen ? "Close navigation" : "Open navigation");
    });

    document.addEventListener("click", (event) => {
      if (sidebar.classList.contains("is-open") && !sidebar.contains(event.target) && !menuButton.contains(event.target)) {
        sidebar.classList.remove("is-open");
        menuButton.setAttribute("aria-expanded", "false");
        menuButton.setAttribute("aria-label", "Open navigation");
      }
    });
  }

  document.querySelectorAll("[data-dismiss]").forEach((button) => {
    button.addEventListener("click", () => button.closest(".flash")?.remove());
  });

  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });

  document.querySelectorAll(".flash").forEach((notice) => {
    window.setTimeout(() => notice.remove(), 6500);
  });
});