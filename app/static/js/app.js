(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  /* ---------- Sidebar (off-canvas on tablets and phones) ---------- */
  const sidebar = $("#sidebar");
  const backdrop = $(".sidebar-backdrop");
  const toggle = $("[data-menu-toggle]");
  const setMenu = (open) => {
    if (!sidebar) return;
    sidebar.classList.toggle("sidebar-open", open);
    if (backdrop) backdrop.hidden = !open;
    toggle?.setAttribute("aria-expanded", String(open));
    document.body.classList.toggle("modal-open", open && window.innerWidth <= 992);
  };
  toggle?.addEventListener("click", () => setMenu(!sidebar.classList.contains("sidebar-open")));
  $$("[data-menu-close]").forEach((el) => el.addEventListener("click", () => setMenu(false)));
  window.addEventListener("resize", () => { if (window.innerWidth > 992) setMenu(false); });

  /* ---------- Dropdowns ---------- */
  $$("[data-dropdown]").forEach((dropdown) => {
    const button = $("[data-dropdown-toggle]", dropdown);
    const menu = $(".dropdown-menu", dropdown);
    const close = () => { menu.hidden = true; button.setAttribute("aria-expanded", "false"); };
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const open = menu.hidden;
      menu.hidden = !open;
      button.setAttribute("aria-expanded", String(open));
    });
    document.addEventListener("click", (event) => { if (!dropdown.contains(event.target)) close(); });
    document.addEventListener("keydown", (event) => { if (event.key === "Escape") close(); });
  });

  /* ---------- Modals with create / edit record forms ---------- */
  let lastTrigger = null;
  const openModal = (modal, trigger) => {
    lastTrigger = trigger || document.activeElement;
    modal.hidden = false;
    document.body.classList.add("modal-open");
    const form = $("form", modal);
    if (trigger && form) {
      const record = trigger.dataset.record ? JSON.parse(trigger.dataset.record) : null;
      const editing = Boolean(record);
      if (trigger.dataset.formAction) form.action = trigger.dataset.formAction;
      if (!editing) form.reset();
      const title = $("[data-modal-title]", modal);
      if (title && trigger.dataset.formTitle) title.textContent = trigger.dataset.formTitle;
      $$("[data-create-only]", modal).forEach((el) => { el.hidden = editing; });
      $$("[data-edit-only]", modal).forEach((el) => { el.hidden = !editing; });
      $$("[data-create-only] [data-required], [data-edit-only] [data-required]", modal).forEach((input) => {
        input.required = !input.closest("[hidden]");
      });
      if (record) {
        Object.entries(record).forEach(([name, value]) => {
          const field = form.elements.namedItem(name);
          if (!field) return;
          if (field.type === "checkbox") field.checked = Boolean(value);
          else field.value = value ?? "";
          field.dispatchEvent(new Event("change", { bubbles: true }));
        });
      }
      $$("[data-fill]", modal).forEach((el) => {
        const key = el.dataset.fill;
        if (record && key in record) el.textContent = record[key];
      });
      $$("[data-toggle-target]", modal).forEach((checkbox) => checkbox.dispatchEvent(new Event("change")));
    }
    const focusTarget = $("[autofocus], input:not([type=hidden]):not([disabled]), select, textarea", modal);
    window.setTimeout(() => focusTarget?.focus(), 30);
  };
  const closeModal = (modal) => {
    modal.hidden = true;
    if (!$(".modal-backdrop:not([hidden])")) document.body.classList.remove("modal-open");
    lastTrigger?.focus?.();
  };
  $$("[data-modal-open]").forEach((button) => {
    button.addEventListener("click", () => {
      const modal = document.getElementById(button.dataset.modalOpen);
      if (modal) openModal(modal, button);
    });
  });
  $$("[data-modal-close]").forEach((button) => {
    button.addEventListener("click", () => closeModal(button.closest(".modal-backdrop")));
  });
  $$(".modal-backdrop").forEach((modal) => {
    modal.addEventListener("mousedown", (event) => { if (event.target === modal) closeModal(modal); });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const open = $$(".modal-backdrop:not([hidden])").pop();
    if (open) closeModal(open);
    else if (sidebar?.classList.contains("sidebar-open")) setMenu(false);
  });

  /* Toggle dependent sections (e.g. "create login account" fields). */
  $$("[data-toggle-target]").forEach((checkbox) => {
    const sync = () => {
      $$(checkbox.dataset.toggleTarget).forEach((target) => {
        target.hidden = !checkbox.checked;
        $$("input, select", target).forEach((input) => {
          if (input.dataset.required !== undefined) input.required = checkbox.checked;
        });
      });
    };
    checkbox.addEventListener("change", sync);
    sync();
  });

  /* ---------- Confirm destructive actions ---------- */
  $$("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });

  /* Prevent double submission. */
  $$("form").forEach((form) => {
    form.addEventListener("submit", (event) => {
      window.setTimeout(() => {
        if (event.defaultPrevented || form.method.toLowerCase() === "get") return;
        $$("button[type=submit]", form).forEach((button) => {
          if (!button.hasAttribute("data-keep-enabled")) button.disabled = true;
        });
      }, 0);
    });
  });

  /* ---------- Tables: phone card labels and live search ---------- */
  $$("table.data-table").forEach((table) => {
    const headers = $$("thead th", table).map((th) => th.textContent.trim());
    $$("tbody tr", table).forEach((row) => {
      let index = 0;
      Array.from(row.children).forEach((cell) => {
        if (!cell.hasAttribute("data-label") && headers[index]) cell.setAttribute("data-label", headers[index]);
        index += Number(cell.getAttribute("colspan") || 1);
      });
    });
  });
  $$("[data-table-search]").forEach((input) => {
    const table = input.dataset.tableSearch ? $(input.dataset.tableSearch) : $("[data-searchable-table]");
    const counter = $("[data-result-count]");
    const filter = () => {
      const query = input.value.trim().toLocaleLowerCase();
      let visible = 0;
      $$("tbody tr:not(.empty-row)", table).forEach((row) => {
        const match = row.textContent.toLocaleLowerCase().includes(query);
        row.hidden = !match;
        if (match) visible += 1;
      });
      if (counter) counter.textContent = `${visible} shown`;
    };
    input.addEventListener("input", filter);
  });

  /* Auto-submit filter selects. */
  $$("[data-auto-submit]").forEach((field) => {
    field.addEventListener("change", () => field.form?.requestSubmit());
  });
  $$("[data-range-select]").forEach((select) => {
    const sync = () => {
      $$("[data-custom-range]", select.form).forEach((el) => { el.hidden = select.value !== "custom"; });
    };
    select.addEventListener("change", () => { sync(); if (select.value !== "custom") select.form.requestSubmit(); });
    sync();
  });

  /* ---------- Password visibility ---------- */
  $$("[data-password-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const input = button.parentElement.querySelector("input");
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      button.setAttribute("aria-label", show ? "Hide password" : "Show password");
      button.innerHTML = show ? '<i class="fa-regular fa-eye-slash"></i>' : '<i class="fa-regular fa-eye"></i>';
    });
  });

  /* ---------- Flash messages ---------- */
  const hideFlash = (flash) => {
    flash.classList.add("flash-hide");
    window.setTimeout(() => flash.remove(), 300);
  };
  $$("[data-flash-close]").forEach((button) => button.addEventListener("click", () => hideFlash(button.closest(".flash"))));
  window.setTimeout(() => $$(".flash.success").forEach(hideFlash), 6000);

  /* A completed sale's receipt clears the saved POS cart. */
  if ($("[data-clear-pos-cart]")) {
    try { sessionStorage.removeItem("maricel-pos-cart"); } catch (_) { /* storage unavailable */ }
  }

  /* Print buttons */
  $$("[data-print]").forEach((button) => button.addEventListener("click", () => window.print()));
})();
