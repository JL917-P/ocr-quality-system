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

  function runLoading() {
    hideScreen(loginScreen);
    showScreen(loadingScreen);
    if (progressFill) progressFill.style.width = "0%";
    if (progressPct) progressPct.textContent = "0%";
    const start = performance.now();
    function tick(now) {
      const elapsed = now - start;
      const pct = Math.min(100, Math.round((elapsed / LOADING_MS) * 100));
      if (progressFill) progressFill.style.width = `${pct}%`;
      if (progressPct) progressPct.textContent = `${pct}%`;
      if (elapsed < LOADING_MS) {
        requestAnimationFrame(tick);
      } else {
        if (progressFill) progressFill.style.width = "100%";
        if (progressPct) progressPct.textContent = "100%";
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
    const token = window.QCAuth.getToken();
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
