(() => {
  "use strict";
  const root = document.querySelector("[data-pos]");
  if (!root) return;

  const STORAGE_KEY = "maricel-pos-cart";
  const catalog = JSON.parse(document.getElementById("pos-catalog").textContent);
  const config = JSON.parse(document.getElementById("pos-config").textContent);
  const byId = new Map(catalog.map((p) => [p.id, p]));
  const $ = (selector) => document.querySelector(selector);

  const grid = $("[data-product-grid]");
  const search = $("[data-pos-search]");
  const itemsBox = $("[data-cart-items]");
  const emptyCart = $("[data-cart-empty]");
  const form = $("[data-checkout]");
  const discountType = $("[data-discount-type]");
  const discountValue = $("[data-discount-value]");
  const method = $("[data-payment-method]");
  const tendered = $("[data-tendered]");
  const customer = $("[data-customer]");
  const completeButton = $("[data-complete]");

  const peso = (value) => "₱" + Number(value).toLocaleString("en-PH", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const round2 = (value) => Math.round((value + Number.EPSILON) * 100) / 100;
  const plural = (unit, count) => (count === 1 ? unit : /(s|x|ch|sh)$/.test(unit) ? `${unit}es` : `${unit}s`);

  let category = 0;
  let cart = [];
  try {
    cart = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "[]").filter((line) => byId.has(line.id));
  } catch (_) { cart = []; }

  const save = () => sessionStorage.setItem(STORAGE_KEY, JSON.stringify(cart));
  const inCart = (id) => cart.find((line) => line.id === id);

  /* ---------- Catalog ---------- */
  const renderGrid = () => {
    const query = search.value.trim().toLowerCase();
    const matches = catalog.filter((p) =>
      (category === 0 || p.categoryId === category) &&
      (!query || p.name.toLowerCase().includes(query) || p.generic.toLowerCase().includes(query) || p.sku.toLowerCase().includes(query))
    );
    grid.replaceChildren();
    matches.forEach((product) => {
      const tile = document.createElement("button");
      tile.type = "button";
      tile.className = "product-tile";
      const reserved = inCart(product.id)?.qty || 0;
      const left = product.stock - reserved;
      tile.disabled = left <= 0 || product.price <= 0;
      tile.dataset.id = product.id;

      const name = document.createElement("span");
      name.className = "tile-name";
      name.textContent = product.name;
      const generic = document.createElement("span");
      generic.className = "tile-generic";
      generic.textContent = product.generic || product.category;
      const foot = document.createElement("span");
      foot.className = "tile-foot";
      const price = document.createElement("span");
      price.className = "tile-price";
      price.textContent = peso(product.price);
      const stock = document.createElement("span");
      stock.className = "tile-stock" + (left <= 0 ? " out" : left <= 10 ? " low" : "");
      stock.textContent = left <= 0 ? "Out of stock" : `${left.toLocaleString()} ${plural(product.unit, left)} left`;
      foot.append(price, stock);
      tile.append(name, generic, foot);
      if (product.rx) {
        tile.classList.add("has-rx");
        const rx = document.createElement("span");
        rx.className = "rx-tag";
        rx.textContent = "Rx";
        rx.title = "Prescription required";
        tile.append(rx);
      }
      tile.setAttribute("aria-label", `${product.name}, ${peso(product.price)}, ${left} in stock`);
      tile.addEventListener("click", () => addToCart(product.id));
      grid.append(tile);
    });
    $("[data-no-results]").hidden = matches.length > 0;
  };

  /* ---------- Cart ---------- */
  const addToCart = (id, amount = 1) => {
    const product = byId.get(id);
    const line = inCart(id);
    const current = line ? line.qty : 0;
    const next = Math.min(product.stock, current + amount);
    if (next <= 0) return;
    if (line) line.qty = next;
    else cart.push({ id, qty: next });
    if (product.rx && !line) {
      flashNote(`${product.name} requires a prescription — please check the customer's Rx.`);
    }
    update();
  };

  const setQty = (id, qty) => {
    const product = byId.get(id);
    const line = inCart(id);
    if (!line) return;
    const value = Math.floor(Number(qty));
    if (!Number.isFinite(value) || value <= 0) cart = cart.filter((l) => l.id !== id);
    else line.qty = Math.min(value, product.stock);
    update();
  };

  let noteTimer = null;
  const flashNote = (message) => {
    let note = document.querySelector("[data-pos-note]");
    if (!note) {
      note = document.createElement("div");
      note.className = "info-note";
      note.dataset.posNote = "";
      note.style.margin = "10px 18px 0";
      note.innerHTML = '<i class="fa-solid fa-prescription"></i><span></span>';
      itemsBox.before(note);
    }
    note.querySelector("span").textContent = message;
    note.hidden = false;
    clearTimeout(noteTimer);
    noteTimer = setTimeout(() => { note.hidden = true; }, 5000);
  };

  const renderCart = () => {
    itemsBox.querySelectorAll(".cart-line").forEach((el) => el.remove());
    emptyCart.hidden = cart.length > 0;
    cart.forEach((line) => {
      const product = byId.get(line.id);
      const row = document.createElement("div");
      row.className = "cart-line";

      const info = document.createElement("div");
      const name = document.createElement("div");
      name.className = "cart-line-name";
      name.textContent = product.name;
      const meta = document.createElement("div");
      meta.className = "cart-line-meta";
      meta.textContent = `${peso(product.price)} / ${product.unit} · ${product.stock.toLocaleString()} available`;
      info.append(name, meta);

      const total = document.createElement("div");
      total.className = "cart-line-total";
      total.textContent = peso(product.price * line.qty);

      const actions = document.createElement("div");
      actions.className = "cart-line-actions";
      const control = document.createElement("div");
      control.className = "qty-control";
      const minus = document.createElement("button");
      minus.type = "button";
      minus.setAttribute("aria-label", `Decrease ${product.name}`);
      minus.innerHTML = '<i class="fa-solid fa-minus"></i>';
      minus.addEventListener("click", () => setQty(line.id, line.qty - 1));
      const input = document.createElement("input");
      input.type = "number";
      input.min = "1";
      input.max = String(product.stock);
      input.value = line.qty;
      input.inputMode = "numeric";
      input.setAttribute("aria-label", `Quantity of ${product.name}`);
      input.addEventListener("change", () => setQty(line.id, input.value));
      const plus = document.createElement("button");
      plus.type = "button";
      plus.setAttribute("aria-label", `Increase ${product.name}`);
      plus.innerHTML = '<i class="fa-solid fa-plus"></i>';
      plus.disabled = line.qty >= product.stock;
      plus.addEventListener("click", () => setQty(line.id, line.qty + 1));
      control.append(minus, input, plus);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "remove-line";
      remove.innerHTML = '<i class="fa-solid fa-trash-can"></i> Remove';
      remove.addEventListener("click", () => setQty(line.id, 0));
      actions.append(control, remove);

      row.append(info, total, actions);
      itemsBox.append(row);
    });
  };

  const computeTotals = () => {
    const subtotal = round2(cart.reduce((sum, line) => sum + round2(byId.get(line.id).price * line.qty), 0));
    let discount = 0;
    if (discountType.value === "senior" || discountType.value === "pwd") discount = round2(subtotal * config.seniorRate / 100);
    else if (discountType.value === "custom") discount = Math.min(subtotal, Math.max(0, round2(Number(discountValue.value) || 0)));
    const tax = round2((subtotal - discount) * (config.taxRate || 0) / 100);
    const total = round2(subtotal - discount + tax);
    const count = cart.reduce((sum, line) => sum + line.qty, 0);
    return { subtotal, discount, tax, total, count };
  };

  const update = () => {
    save();
    renderCart();
    renderGrid();
    const t = computeTotals();
    $("[data-item-count]").textContent = t.count;
    $("[data-subtotal]").textContent = peso(t.subtotal);
    $("[data-discount]").textContent = "−" + peso(t.discount);
    const taxEl = $("[data-tax]");
    if (taxEl) taxEl.textContent = peso(t.tax);
    $("[data-total]").textContent = peso(t.total);
    $("[data-mobile-count]").textContent = t.count;
    $("[data-mobile-total]").textContent = peso(t.total);

    const isCash = method.value === "cash";
    $("[data-cash-field]").hidden = !isCash;
    $("[data-reference-field]").hidden = isCash;
    tendered.required = isCash && cart.length > 0;
    $("[data-discount-amount]").hidden = discountType.value !== "custom";

    const changeBox = $("[data-change]");
    let ready = cart.length > 0;
    if (isCash && cart.length) {
      const cash = Number(tendered.value);
      if (tendered.value !== "") {
        const change = round2(cash - t.total);
        changeBox.hidden = false;
        changeBox.classList.toggle("short", change < 0);
        changeBox.firstElementChild.textContent = change < 0 ? "Short by" : "Change";
        $("[data-change-value]").textContent = peso(Math.abs(change));
        if (change < 0) ready = false;
      } else {
        changeBox.hidden = true;
        ready = false;
      }
    } else {
      changeBox.hidden = true;
    }
    if ((discountType.value === "senior" || discountType.value === "pwd") && !customer.value) ready = false;
    completeButton.disabled = !ready;
    completeButton.title = !cart.length ? "Add products first"
      : (discountType.value === "senior" || discountType.value === "pwd") && !customer.value ? "Select the senior / PWD customer"
      : isCash && !ready ? "Enter the cash received" : "";
  };

  /* ---------- Events ---------- */
  search.addEventListener("input", renderGrid);
  search.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    const first = grid.querySelector(".product-tile:not(:disabled)");
    if (first) { addToCart(Number(first.dataset.id)); search.select(); }
  });
  document.querySelectorAll("[data-category]").forEach((chip) => {
    chip.addEventListener("click", () => {
      category = Number(chip.dataset.category);
      document.querySelectorAll("[data-category]").forEach((c) => c.classList.toggle("active", c === chip));
      renderGrid();
    });
  });
  [discountType, discountValue, method, tendered, customer].forEach((field) => {
    field.addEventListener("input", update);
    field.addEventListener("change", update);
  });
  $("[data-clear-cart]").addEventListener("click", () => {
    if (cart.length && !window.confirm("Clear all items from this sale?")) return;
    cart = [];
    tendered.value = "";
    update();
  });
  form.addEventListener("submit", (event) => {
    const t = computeTotals();
    if (!cart.length) { event.preventDefault(); return; }
    if (method.value === "cash" && Number(tendered.value) < t.total) {
      event.preventDefault();
      tendered.focus();
      return;
    }
    $("[data-cart-field]").value = JSON.stringify(cart);
    completeButton.disabled = true;
    completeButton.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Processing…';
  });

  // Hide the floating phone cart bar while the checkout panel is on screen.
  const mobileBar = $("[data-mobile-bar]");
  if ("IntersectionObserver" in window && mobileBar) {
    new IntersectionObserver(([entry]) => mobileBar.classList.toggle("is-hidden", entry.isIntersecting), { threshold: 0.15 })
      .observe(form);
  }

  update();
  search.focus({ preventScroll: true });
})();
