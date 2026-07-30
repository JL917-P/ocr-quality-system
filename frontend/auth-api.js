(function () {
  const TOKEN_KEY = "qc_auth_token";
  const USER_KEY = "qc_auth_user";
  const REMEMBER_KEY = "qc_auth_remember";

  const PERMISSION_LABELS = {
    section_home: "Ver Inicio",
    section_clients: "Ver Clientes",
    section_products: "Ver Productos",
    section_transports: "Ver Transporte",
    section_ocr: "Ver Nueva constancia",
    section_constancias: "Ver Constancias",
    section_trazabilidad: "Ver Trazabilidad",
    section_trasiegos: "Ver Trasiegos",
    constancia_create: "Crear constancias",
    constancia_edit: "Editar constancias",
    constancia_delete: "Eliminar constancias",
    constancia_confirm: "Confirmar constancias",
    clients_write: "Crear/editar/eliminar clientes",
    products_write: "Crear/editar/eliminar productos",
    transports_write: "Crear/editar/eliminar transportes",
    trasiegos_write: "Crear/editar/eliminar trasiegos",
    trace_export: "Exportar trazabilidad",
    users_manage: "Administrar usuarios",
    audit_view: "Ver bitácora",
    sheets_sync: "Sincronizar Google Sheets",
  };

  function getToken() {
    try {
      return sessionStorage.getItem(TOKEN_KEY) || localStorage.getItem(TOKEN_KEY) || "";
    } catch (e) {
      return "";
    }
  }

  function getUser() {
    try {
      const raw = sessionStorage.getItem(USER_KEY) || localStorage.getItem(USER_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }

  function setSession(token, user, remember) {
    try {
      // Limpia tokens viejos antes de guardar el nuevo (evita Bearer obsoleto).
      sessionStorage.removeItem(TOKEN_KEY);
      sessionStorage.removeItem(USER_KEY);
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);

      sessionStorage.setItem(TOKEN_KEY, token);
      sessionStorage.setItem(USER_KEY, JSON.stringify(user));
      if (remember) {
        localStorage.setItem(TOKEN_KEY, token);
        localStorage.setItem(USER_KEY, JSON.stringify(user));
        localStorage.setItem(REMEMBER_KEY, "1");
      } else {
        localStorage.removeItem(REMEMBER_KEY);
      }
    } catch (e) {}
    window.QC_CURRENT_USER = user;
  }

  function clearSession() {
    try {
      sessionStorage.removeItem(TOKEN_KEY);
      sessionStorage.removeItem(USER_KEY);
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
      localStorage.removeItem(REMEMBER_KEY);
    } catch (e) {}
    window.QC_CURRENT_USER = null;
  }

  function hasPermission(key) {
    const user = getUser();
    if (!user) return false;
    if (user.is_admin) return true;
    return !!(user.permissions && user.permissions[key]);
  }

  function authHeaders(extra) {
    const headers = new Headers(extra || {});
    const token = getToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    return headers;
  }

  async function apiFetch(url, options = {}) {
    const opts = { ...options, credentials: "include" };
    const headers = authHeaders(opts.headers || {});
    if (opts.body && !headers.has("Content-Type") && !(opts.body instanceof FormData)) {
      headers.set("Content-Type", "application/json");
    }
    opts.headers = headers;
    return fetch(url, opts);
  }

  window.QCAuth = {
    TOKEN_KEY,
    USER_KEY,
    REMEMBER_KEY,
    PERMISSION_LABELS,
    getToken,
    getUser,
    setSession,
    clearSession,
    hasPermission,
    authHeaders,
    apiFetch,
  };

  // Adjunta token + cookies en /api/* sin cerrar sesión de golpe en cada 401.
  const nativeFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    const url = typeof input === "string" ? input : input && input.url;
    if (url && String(url).startsWith("/api/") && !String(url).includes("/api/auth/login")) {
      const opts = init ? { ...init } : {};
      opts.credentials = opts.credentials || "include";
      const headers = new Headers(opts.headers || (input && input.headers) || {});
      const token = getToken();
      if (token) {
        headers.set("Authorization", `Bearer ${token}`);
      }
      opts.headers = headers;
      return nativeFetch(input, opts);
    }
    return nativeFetch(input, init);
  };
})();
