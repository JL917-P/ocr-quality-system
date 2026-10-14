(function (global) {
  "use strict";

  var KEY = "qc_ui_mode";

  function readOverride() {
    try {
      return localStorage.getItem(KEY) || "";
    } catch (e) {
      return "";
    }
  }

  function writeOverride(value) {
    try {
      if (!value) localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, value);
    } catch (e) {}
  }

  function screenSides() {
    var w = Number(screen.width) || 0;
    var h = Number(screen.height) || 0;
    return {
      longSide: Math.max(w, h),
      shortSide: w && h ? Math.min(w, h) : 0,
    };
  }

  /**
   * Clasifica el aparato (PC, tablet o teléfono), no el ancho de la ventana.
   */
  function detectDevice() {
    var ua = navigator.userAgent || "";
    var touchPoints = navigator.maxTouchPoints || 0;
    var sides = screenSides();
    var fine = false;
    var coarse = false;
    try {
      fine = window.matchMedia("(pointer: fine)").matches;
      coarse = window.matchMedia("(pointer: coarse)").matches;
    } catch (e) {}

    var iPadOs = /Macintosh/i.test(ua) && touchPoints > 1;
    var tabletUa =
      /iPad|Tablet|PlayBook|Silk/i.test(ua) ||
      iPadOs ||
      (/Android/i.test(ua) && !/Mobile/i.test(ua));
    var phoneUa =
      /iPhone|iPod|Windows Phone|IEMobile|Opera Mini|BlackBerry|webOS/i.test(ua) ||
      (/Android/i.test(ua) && /Mobile/i.test(ua));

    if (tabletUa) return "tablet";
    if (phoneUa) return "mobile";
    if (fine) return "desktop";
    if (sides.shortSide >= 900 || sides.longSide >= 1280) return "desktop";
    if (coarse && sides.shortSide > 0 && sides.shortSide < 768) return "mobile";
    return "desktop";
  }

  /**
   * El panel móvil es solo para teléfonos.
   * PC y tablet usan el panel completo.
   * Un "mobile" guardado no puede dejar un escritorio en la vista móvil.
   * "tablet" sí es una elección del botón Tablet en un teléfono.
   */
  function shouldUseMobile() {
    var device = detectDevice();
    var override = readOverride();
    if (device === "desktop" || device === "tablet") {
      if (override === "mobile") writeOverride("");
      return false;
    }
    if (override === "tablet") return false;
    return true;
  }

  global.QCUiMode = {
    KEY: KEY,
    detectDevice: detectDevice,
    shouldUseMobile: shouldUseMobile,
    setMode: writeOverride,
  };
})(window);
