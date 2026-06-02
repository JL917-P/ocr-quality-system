(function () {
  const splash = document.getElementById("appSplash");
  if (!splash) return;

  const key = "qc_quality_splash_seen";

  function dismiss() {
    splash.classList.add("splash-out");
    setTimeout(function () {
      if (splash.parentNode) splash.remove();
    }, 450);
    try {
      sessionStorage.setItem(key, "1");
    } catch (e) {}
  }

  try {
    if (sessionStorage.getItem(key)) {
      splash.remove();
      return;
    }
  } catch (e) {}

  splash.addEventListener("click", dismiss);
  setTimeout(dismiss, 2400);
})();
