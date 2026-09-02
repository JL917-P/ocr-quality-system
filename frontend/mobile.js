(function () {
  "use strict";

  const UI_MODE_KEY = "qc_ui_mode";
  const CAPTURE_SOURCE = "mobile";

  const listView = document.getElementById("mobileListView");
  const formView = document.getElementById("mobileFormView");
  const listEl = document.getElementById("mobileConstanciaList");
  const userLabel = document.getElementById("mobileUserLabel");
  const toastEl = document.getElementById("mobileToast");

  const fields = {
    id: document.getElementById("mobConstanciaId"),
    number: document.getElementById("mobNumber"),
    date: document.getElementById("mobDate"),
    client: document.getElementById("mobClient"),
    plate: document.getElementById("mobPlate"),
    products: document.getElementById("mobProducts"),
  };

  let editingId = null;

  function todayIso() {
    const now = new Date();
    const yyyy = now.getFullYear();
    const mm = String(now.getMonth() + 1).padStart(2, "0");
    const dd = String(now.getDate()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd}`;
  }

  function toInputDateValue(rawDate) {
    const value = (rawDate || "").trim();
    if (!value) return "";
    if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
    const slashMatch = value.match(/^(\d{2})\s*\/\s*(\d{2})\s*\/\s*(\d{4})$/);
    if (slashMatch) {
      const [, dd, mm, yyyy] = slashMatch;
      return `${yyyy}-${mm}-${dd}`;
    }
    return "";
  }

  function showToast(msg) {
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.classList.add("show");
    setTimeout(() => toastEl.classList.remove("show"), 2600);
  }

  function can(perm) {
    return window.QCAuth && typeof window.QCAuth.hasPermission === "function"
      ? window.QCAuth.hasPermission(perm)
      : false;
  }

  function actorName() {
    const u = window.QCAuth?.getUser?.();
    return u ? u.display_name || u.username || "usuario" : "usuario";
  }

  function showListView() {
    listView?.classList.remove("hidden");
    formView?.classList.add("hidden");
    editingId = null;
    loadList();
  }

  function showFormView() {
    listView?.classList.add("hidden");
    formView?.classList.remove("hidden");
  }

  function resetForm() {
    editingId = null;
    if (fields.id) fields.id.value = "";
    if (fields.number) fields.number.value = "";
    if (fields.date) fields.date.value = todayIso();
    if (fields.client) fields.client.value = "";
    if (fields.plate) fields.plate.value = "";
    if (fields.products) fields.products.innerHTML = "";
    addProductRow();
  }

  function productRowTemplate(index) {
    const row = document.createElement("div");
    row.className = "mob-product-row";
    row.innerHTML = `
      <div class="mob-product-row-head">
        <span>Producto ${index}</span>
        <button type="button" class="mob-row-del" title="Quitar">🗑</button>
      </div>
      <div class="mob-field">
        <label>Producto</label>
        <input type="text" class="mob-product" placeholder="Nombre del producto" autocomplete="off" />
      </div>
      <div class="mob-field">
        <label>Lote</label>
        <input type="text" class="mob-lot" placeholder="Lote" autocomplete="off" />
      </div>
      <div class="mob-field">
        <label>Fecha de producción</label>
        <input type="text" class="mob-prod-date" placeholder="Ej: FP01AGO26 o AGO26" autocomplete="off" />
      </div>
      <div class="mob-field">
        <label>Cantidad</label>
        <input type="number" class="mob-qty" min="0" step="any" placeholder="0" inputmode="decimal" />
      </div>
    `;
    row.querySelector(".mob-row-del")?.addEventListener("click", () => {
      const rows = fields.products?.querySelectorAll(".mob-product-row") || [];
      if (rows.length <= 1) {
        row.querySelector(".mob-product").value = "";
        row.querySelector(".mob-lot").value = "";
        row.querySelector(".mob-prod-date").value = "";
        row.querySelector(".mob-qty").value = "";
        return;
      }
      row.remove();
      reindexProductRows();
    });
    return row;
  }

  function reindexProductRows() {
    [...(fields.products?.querySelectorAll(".mob-product-row") || [])].forEach((row, idx) => {
      const label = row.querySelector(".mob-product-row-head span");
      if (label) label.textContent = `Producto ${idx + 1}`;
    });
  }

  function addProductRow(data = {}) {
    const index = (fields.products?.querySelectorAll(".mob-product-row").length || 0) + 1;
    const row = productRowTemplate(index);
    if (data.product) row.querySelector(".mob-product").value = data.product;
    if (data.lot) row.querySelector(".mob-lot").value = data.lot;
    if (data.production_text) row.querySelector(".mob-prod-date").value = data.production_text;
    if (data.quantity != null && data.quantity !== "") {
      row.querySelector(".mob-qty").value = String(data.quantity);
    }
    fields.products?.appendChild(row);
  }

  function collectItems() {
    const items = [];
    [...(fields.products?.querySelectorAll(".mob-product-row") || [])].forEach((row) => {
      const product = (row.querySelector(".mob-product")?.value || "").trim();
      if (!product) return;
      const lot = (row.querySelector(".mob-lot")?.value || "").trim();
      const production_text = (row.querySelector(".mob-prod-date")?.value || "").trim();
      const qtyRaw = row.querySelector(".mob-qty")?.value;
      const item = { product, lot, production_text };
      if (qtyRaw !== "" && qtyRaw != null) {
        const qty = Number(qtyRaw);
        if (!Number.isNaN(qty)) item.quantity = qty;
      }
      items.push(item);
    });
    return items;
  }

  function itemField(item, ...keys) {
    for (const key of keys) {
      const val = item?.[key];
      if (val !== undefined && val !== null && String(val).trim() !== "") return val;
    }
    return "";
  }

  function statusLabel(status) {
    if (status === "por_confirmar") return "Reservada";
    if (status === "confirmada") return "Grabada";
    return status || "";
  }

  function statusClass(status) {
    return status === "por_confirmar" ? "mob-badge mob-badge-reserve" : "mob-badge mob-badge-done";
  }

  function filterMobileConstancias(rows) {
    return (rows || []).filter((row) => {
      if (row.status === "por_confirmar") return true;
      if (row.status === "confirmada" && row.capture_source === CAPTURE_SOURCE) return true;
      return false;
    });
  }

  async function loadList() {
    if (!listEl) return;
    listEl.innerHTML = '<div class="mob-empty">Cargando…</div>';
    try {
      const res = await window.QCAuth.apiFetch("/api/constancias");
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Error al cargar");
      const rows = filterMobileConstancias(data.constancias || []);
      if (!rows.length) {
        listEl.innerHTML = '<div class="mob-empty">No hay constancias móviles. Pulsa <strong>Nuevo</strong> para ingresar.</div>';
        return;
      }
      listEl.innerHTML = "";
      rows.forEach((row) => {
        const card = document.createElement("button");
        card.type = "button";
        card.className = "mob-card";
        card.style.width = "100%";
        card.style.textAlign = "left";
        card.style.cursor = "pointer";
        const products = (row.items || [])
          .map((it) => itemField(it, "product_name_snapshot", "product"))
          .filter(Boolean)
          .slice(0, 2)
          .join(", ");
        card.innerHTML = `
          <div class="mob-card-title">${row.number || `#${row.id}`}</div>
          <div class="mob-card-meta">${row.client_name || "Sin cliente"}</div>
          <div class="mob-card-meta">${row.issue_date || ""} · Placa: ${row.transport_plate || "-"}</div>
          <div class="mob-card-meta">${products || "Sin productos"}</div>
          <span class="${statusClass(row.status)}">${statusLabel(row.status)}</span>
        `;
        card.addEventListener("click", () => openConstancia(row.id));
        listEl.appendChild(card);
      });
    } catch (err) {
      listEl.innerHTML = `<div class="mob-empty">${err.message || "No se pudo cargar la lista"}</div>`;
    }
  }

  async function openConstancia(id) {
    try {
      const res = await window.QCAuth.apiFetch(`/api/constancias/${id}`);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "No encontrada");
      editingId = data.id;
      if (fields.id) fields.id.value = String(data.id);
      if (fields.number) fields.number.value = data.number || "";
      if (fields.date) fields.date.value = toInputDateValue(data.issue_date) || todayIso();
      if (fields.client) fields.client.value = data.client_name || "";
      if (fields.plate) fields.plate.value = data.transport_plate || "";
      if (fields.products) fields.products.innerHTML = "";
      const items = data.items || [];
      if (items.length) {
        items.forEach((it) =>
          addProductRow({
            product: itemField(it, "product_name_snapshot", "product"),
            lot: itemField(it, "lote_snapshot", "lot"),
            production_text: itemField(it, "production_date_snapshot", "production_text"),
            quantity: it.quantity,
          })
        );
      } else {
        addProductRow();
      }
      showFormView();
    } catch (err) {
      showToast(err.message || "Error al abrir");
    }
  }

  async function saveConstancia(status) {
    if (!can("constancia_create") && !editingId) {
      showToast("Sin permiso para crear constancias.");
      return;
    }
    if (editingId && !can("constancia_edit")) {
      showToast("Sin permiso para editar.");
      return;
    }
    if (status === "confirmada" && !can("constancia_confirm")) {
      showToast("Sin permiso para grabar. Usa Reservar.");
      return;
    }
    const client_name = (fields.client?.value || "").trim();
    if (!client_name) {
      showToast("Ingresa el cliente.");
      return;
    }
    const items = collectItems();
    if (!items.length) {
      showToast("Agrega al menos un producto.");
      return;
    }
    const payload = {
      number: (fields.number?.value || "").trim(),
      issue_date: fields.date?.value || todayIso(),
      client_name,
      transport_plate: (fields.plate?.value || "").trim(),
      fumigacion: true,
      calidad: true,
      personalizado: false,
      status,
      items,
      capture_source: CAPTURE_SOURCE,
      usuario: actorName(),
    };
    const url = editingId ? `/api/constancias/${editingId}` : "/api/constancias";
    const method = editingId ? "PUT" : "POST";
    try {
      const res = await window.QCAuth.apiFetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Error al guardar");
      showToast(status === "por_confirmar" ? "Constancia reservada." : "Constancia grabada.");
      showListView();
    } catch (err) {
      showToast(err.message || "No se pudo guardar");
    }
  }

  function bindUi() {
    document.getElementById("mobNewBtn")?.addEventListener("click", () => {
      resetForm();
      showFormView();
    });
    document.getElementById("mobBackBtn")?.addEventListener("click", showListView);
    document.getElementById("mobAddProductBtn")?.addEventListener("click", () => addProductRow());
    document.getElementById("mobSaveBtn")?.addEventListener("click", () => saveConstancia("confirmada"));
    document.getElementById("mobReserveBtn")?.addEventListener("click", () => saveConstancia("por_confirmar"));
    document.getElementById("mobTabletBtn")?.addEventListener("click", () => {
      try {
        localStorage.setItem(UI_MODE_KEY, "tablet");
      } catch (e) {}
      const q = window.location.search || "";
      window.location.href = `/admin${q}`;
    });
    document.getElementById("mobileLogoutBtn")?.addEventListener("click", () => {
      document.getElementById("sidebarLogoutBtn")?.click();
    });
  }

  function refreshUserLabel() {
    const u = window.QCAuth?.getUser?.();
    if (userLabel && u) {
      userLabel.textContent = u.display_name || u.username || "Usuario";
    }
  }

  function initApp() {
    try {
      localStorage.setItem(UI_MODE_KEY, "mobile");
    } catch (e) {}
    refreshUserLabel();
    bindUi();
    resetForm();
    showListView();
  }

  window.addEventListener("qc-panel-ready", initApp);
  window.addEventListener("qc-auth-changed", refreshUserLabel);

  if (document.body && !document.body.classList.contains("auth-locked")) {
    initApp();
  }
})();
