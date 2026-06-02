(function () {
  const VALID_USER = "admin";
  const VALID_PASS = "123456";
  const AUTH_KEY = "qc_auth_session";
  const LOADING_MS = 4000;
  const WELCOME_MS = 2200;

  const loginScreen = document.getElementById("authLogin");
  const loadingScreen = document.getElementById("authLoading");
  const welcomeScreen = document.getElementById("authWelcome");
  const loginForm = document.getElementById("authLoginForm");
  const loginError = document.getElementById("authLoginError");
  const progressFill = document.getElementById("authProgressFill");
  const progressPct = document.getElementById("authProgressPct");
  const rememberCheck = document.getElementById("authRemember");

  if (!loginScreen || !loginForm) return;

  function isAuthenticated() {
    try {
      if (sessionStorage.getItem(AUTH_KEY) === "1") return true;
      if (localStorage.getItem(AUTH_KEY) === "1" && localStorage.getItem("qc_auth_remember") === "1") {
        return true;
      }
    } catch (e) {}
    return false;
  }

  function setAuthenticated(remember) {
    try {
      sessionStorage.setItem(AUTH_KEY, "1");
      if (remember) {
        localStorage.setItem(AUTH_KEY, "1");
        localStorage.setItem("qc_auth_remember", "1");
      } else {
        localStorage.removeItem(AUTH_KEY);
        localStorage.removeItem("qc_auth_remember");
      }
    } catch (e) {}
  }

  function clearAuthentication() {
    try {
      sessionStorage.removeItem(AUTH_KEY);
      localStorage.removeItem(AUTH_KEY);
      localStorage.removeItem("qc_auth_remember");
    } catch (e) {}
    if (rememberCheck) rememberCheck.checked = false;
  }

  function logout() {
    clearAuthentication();
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
  }

  function hideScreen(el) {
    if (el) el.classList.add("hidden");
  }

  function showScreen(el) {
    if (el) el.classList.remove("hidden");
  }

  function unlockApp() {
    document.body.classList.remove("auth-locked");
    hideScreen(welcomeScreen);
  }

  function runWelcome() {
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

  function startSession(remember) {
    setAuthenticated(remember);
    runLoading();
  }

  loginForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const user = (document.getElementById("authUser")?.value || "").trim();
    const pass = document.getElementById("authPass")?.value || "";
    if (user === VALID_USER && pass === VALID_PASS) {
      if (loginError) loginError.textContent = "";
      startSession(Boolean(rememberCheck?.checked));
    } else {
      if (loginError) loginError.textContent = "Usuario o contraseña incorrectos.";
    }
  });

  try {
    if (localStorage.getItem("qc_auth_remember") === "1" && rememberCheck) {
      rememberCheck.checked = true;
    }
  } catch (e) {}

  const logoutBtn = document.getElementById("sidebarLogoutBtn");
  if (logoutBtn) {
    logoutBtn.addEventListener("click", logout);
  }

  if (isAuthenticated()) {
    hideScreen(loginScreen);
    hideScreen(loadingScreen);
    hideScreen(welcomeScreen);
    document.body.classList.remove("auth-locked");
  } else {
    document.body.classList.add("auth-locked");
    showScreen(loginScreen);
  }
})();
