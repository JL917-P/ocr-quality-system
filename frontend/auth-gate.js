(function () {
  const LOADING_MS = 2800;
  const WELCOME_MS = 1800;

  const loginScreen = document.getElementById("authLogin");
  const loadingScreen = document.getElementById("authLoading");
  const welcomeScreen = document.getElementById("authWelcome");
  const loginForm = document.getElementById("authLoginForm");
  const loginError = document.getElementById("authLoginError");
  const progressFill = document.getElementById("authProgressFill");
  const progressPct = document.getElementById("authProgressPct");
  const rememberCheck = document.getElementById("authRemember");

  if (!loginScreen || !loginForm || !window.QCAuth) return;

  function hideScreen(el) {
    if (el) el.classList.add("hidden");
  }

  function showScreen(el) {
    if (el) el.classList.remove("hidden");
  }

  function unlockApp() {
    document.body.classList.remove("auth-locked");
    hideScreen(loginScreen);
    hideScreen(loadingScreen);
    hideScreen(welcomeScreen);
    try {
      window.dispatchEvent(new CustomEvent("qc-panel-ready"));
      window.dispatchEvent(new CustomEvent("qc-auth-changed"));
    } catch (e) {}
  }

  function runWelcome() {
    const user = window.QCAuth.getUser();
    const welcomeText = document.querySelector(".auth-welcome-text");
    if (welcomeText && user) {
      welcomeText.textContent = `Bienvenido, ${user.display_name || user.username}`;
    }
    showScreen(welcomeScreen);
    hideScreen(loadingScreen);
    setTimeout(unlockApp, WELCOME_MS);
  }

  const ORBIT_DOTS = 36;

  function ensureOrbitDots() {
    const host = document.querySelector("#authOrbit .auth-orbit-dots");
    if (!host || host.dataset.ready === "1") return;
    host.dataset.ready = "1";
    for (let i = 0; i < ORBIT_DOTS; i += 1) {
      const dot = document.createElement("span");
      dot.style.setProperty("--i", String(i));
      host.appendChild(dot);
    }
  }

  function paintLoad(pct) {
    const orbit = document.getElementById("authOrbit");
    if (orbit) orbit.style.setProperty("--load", `${pct}%`);
    ensureOrbitDots();
    const host = orbit && orbit.querySelector(".auth-orbit-dots");
    if (host) {
      const dots = host.children;
      const n = dots.length || 1;
      const filled = Math.max(0, Math.min(100, pct)) / 100;
      for (let i = 0; i < dots.length; i += 1) {
        const pos = i / n;
        const dot = dots[i];
        const angle = (i / n) * 360;
        if (filled <= 0 || pos > filled) {
          dot.style.opacity = "0";
          dot.style.transform = `rotate(${angle}deg) translateY(-118px) scale(0.35)`;
          continue;
        }
        const along = pos / filled;
        const scale = 0.55 + along * 1.05;
        dot.style.opacity = String(0.28 + along * 0.72);
        dot.style.transform = `rotate(${angle}deg) translateY(-118px) scale(${scale})`;
      }
    }
    if (progressFill) progressFill.style.width = `${pct}%`;
    if (progressPct) progressPct.textContent = `${pct}%`;
  }

  function runLoading() {
    hideScreen(loginScreen);
    showScreen(loadingScreen);
    paintLoad(0);
    const start = performance.now();
    function tick(now) {
      const elapsed = now - start;
      const pct = Math.min(100, Math.round((elapsed / LOADING_MS) * 100));
      paintLoad(pct);
      if (elapsed < LOADING_MS) {
        requestAnimationFrame(tick);
      } else {
        paintLoad(100);
        setTimeout(runWelcome, 200);
      }
    }
    requestAnimationFrame(tick);
  }

  async function logout() {
    try {
      await window.QCAuth.apiFetch("/api/auth/logout", { method: "POST" });
    } catch (e) {}
    window.QCAuth.clearSession();
    document.body.classList.add("auth-locked");
    hideScreen(loadingScreen);
    hideScreen(welcomeScreen);
    showScreen(loginScreen);
    const passInput = document.getElementById("authPass");
    const userInput = document.getElementById("authUser");
    if (passInput) passInput.value = "";
    if (userInput) userInput.value = "";
    if (loginError) loginError.textContent = "";
    const adminLayout = document.getElementById("adminLayout");
    if (adminLayout) adminLayout.classList.remove("sidebar-open");
    // Cerrar modales de permisos u otros avisos abiertos al salir
    document.querySelectorAll("body > .modal-backdrop.show").forEach((el) => {
      try {
        el.remove();
      } catch (e) {}
    });
    try {
      window.dispatchEvent(new CustomEvent("qc-auth-changed"));
    } catch (e) {}
  }

  loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const user = (document.getElementById("authUser")?.value || "").trim();
    const pass = document.getElementById("authPass")?.value || "";
    const remember = Boolean(rememberCheck?.checked);
    if (loginError) loginError.textContent = "";
    const submitBtn = loginForm.querySelector('button[type="submit"]');
    if (submitBtn) submitBtn.disabled = true;
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: user, password: pass, remember }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (loginError) loginError.textContent = data.detail || "Usuario o contraseña incorrectos.";
        return;
      }
      window.QCAuth.setSession(data.token, data.user, remember);
      // Operadores nunca heredan entorno de impersonación del admin.
      if (!data.user?.is_admin) {
        window.QCAuth.clearEnvOwnerId();
      }
      runLoading();
    } catch (err) {
      if (loginError) loginError.textContent = "No se pudo conectar con el servidor.";
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  });

  try {
    if (localStorage.getItem(window.QCAuth.REMEMBER_KEY) === "1" && rememberCheck) {
      rememberCheck.checked = true;
    }
  } catch (e) {}

  const logoutBtn = document.getElementById("sidebarLogoutBtn");
  if (logoutBtn) {
    logoutBtn.addEventListener("click", logout);
  }

  async function bootstrap() {
    // Nueva pestaña (Ver entorno): heredar sesión del admin sin pedir login.
    try {
      const raw = localStorage.getItem("qc_env_handoff");
      if (raw) {
        const handoff = JSON.parse(raw);
        localStorage.removeItem("qc_env_handoff");
        const age = Date.now() - Number(handoff?.ts || 0);
        if (handoff?.token && handoff?.user && age >= 0 && age < 120000) {
          window.QCAuth.setSession(handoff.token, handoff.user, true);
          if (handoff.envOwnerId) {
            window.QCAuth.setEnvOwnerId(handoff.envOwnerId);
          }
        }
      }
    } catch (e) {}

    // La URL tiene prioridad para el entorno activo.
    try {
      const envParam = new URLSearchParams(window.location.search || "").get("env");
      if (envParam) window.QCAuth.setEnvOwnerId(envParam);
      else if (!window.QCAuth.getEnvOwnerId()) {
        window.QCAuth.clearEnvOwnerId();
      }
    } catch (e) {}

    let token = window.QCAuth.getToken();
    // Si no hay token en storage pero hay cookie de sesión, recupera usuario.
    if (!token) {
      try {
        const res = await fetch("/api/auth/me", { credentials: "include" });
        const data = await res.json().catch(() => ({}));
        if (res.ok && data.user) {
          // Cookie válida: pide un token de continuidad para esta pestaña.
          const cont = await fetch("/api/auth/continue", {
            method: "POST",
            credentials: "include",
          });
          const contData = await cont.json().catch(() => ({}));
          if (cont.ok && contData.token) {
            window.QCAuth.setSession(contData.token, contData.user || data.user, true);
            token = contData.token;
          }
        }
      } catch (e) {}
    }

    if (!token) {
      document.body.classList.add("auth-locked");
      showScreen(loginScreen);
      return;
    }
    try {
      const res = await window.QCAuth.apiFetch("/api/auth/me");
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.user) {
        window.QCAuth.clearSession();
        document.body.classList.add("auth-locked");
        showScreen(loginScreen);
        return;
      }
      const remember = localStorage.getItem(window.QCAuth.REMEMBER_KEY) === "1";
      window.QCAuth.setSession(token, data.user, remember);
      if (!data.user?.is_admin) {
        const params = new URLSearchParams(window.location.search || "");
        if (!params.get("env")) {
          window.QCAuth.clearEnvOwnerId();
        }
      }
      hideScreen(loginScreen);
      hideScreen(loadingScreen);
      hideScreen(welcomeScreen);
      document.body.classList.remove("auth-locked");
      window.dispatchEvent(new CustomEvent("qc-panel-ready"));
      window.dispatchEvent(new CustomEvent("qc-auth-changed"));
    } catch (e) {
      window.QCAuth.clearSession();
      document.body.classList.add("auth-locked");
      showScreen(loginScreen);
    }
  }

  bootstrap();
})();
