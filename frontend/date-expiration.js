(function () {
  "use strict";

  const MONTH_ABBR = [
    "ene", "feb", "mar", "abr", "may", "jun",
    "jul", "ago", "sep", "oct", "nov", "dic",
  ];

  function parseConstanciaDate(dateText) {
    const value = (dateText || "").trim();
    if (!value) return null;
    let match = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (match) {
      return {
        day: parseInt(match[3], 10),
        month: parseInt(match[2], 10),
        year: parseInt(match[1], 10),
        dayPadded: true,
        monthPadded: true,
        yearDigits: 4,
      };
    }
    match = value.match(/^(\d{1,2})\s*\/\s*(\d{1,2})\s*\/\s*(\d{4})$/);
    if (match) {
      return {
        day: parseInt(match[1], 10),
        month: parseInt(match[2], 10),
        year: parseInt(match[3], 10),
        dayPadded: match[1].length >= 2,
        monthPadded: match[2].length >= 2,
        yearDigits: 4,
      };
    }
    match = value.match(/^(\d{1,2})\s*\/\s*(\d{1,2})\s*\/\s*(\d{2})$/);
    if (match) {
      let year = parseInt(match[3], 10);
      year += year < 50 ? 2000 : 1900;
      return {
        day: parseInt(match[1], 10),
        month: parseInt(match[2], 10),
        year,
        dayPadded: match[1].length >= 2,
        monthPadded: match[2].length >= 2,
        yearDigits: 2,
      };
    }
    return null;
  }

  function addMonthsKeepDay(parsed, months) {
    let monthIndex = parsed.month - 1 + months;
    let year = parsed.year + Math.floor(monthIndex / 12);
    monthIndex = ((monthIndex % 12) + 12) % 12;
    const lastDay = new Date(year, monthIndex + 1, 0).getDate();
    const day = Math.min(parsed.day, lastDay);
    return {
      day,
      month: monthIndex + 1,
      year,
      dayPadded: parsed.dayPadded,
      monthPadded: parsed.monthPadded,
      yearDigits: parsed.yearDigits,
      monthCase: parsed.monthCase,
    };
  }

  function formatUser01ProdExpDate(parsed) {
    const dd = parsed.dayPadded === true ? String(parsed.day).padStart(2, "0") : String(parsed.day);
    const mm = parsed.monthPadded === true ? String(parsed.month).padStart(2, "0") : String(parsed.month);
    const yy = parsed.yearDigits === 4 ? String(parsed.year) : String(parsed.year).slice(-2);
    return `${dd}/${mm}/${yy}`;
  }

  function parseMonthYearText(dateText) {
    const raw = (dateText || "").trim();
    if (!raw) return null;
    const match = raw.match(/^([A-Za-zÁÉÍÓÚáéíóúüÜ]{3})\s*([-./]?)\s*(\d{2}|\d{4})$/);
    if (!match) return null;
    const monthToken = match[1];
    const sep = match[2] || "";
    let year = parseInt(match[3], 10);
    if (match[3].length === 2) year += year < 50 ? 2000 : 1900;
    const monthKey = monthToken.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
    const aliases = { set: "sep", sept: "sep" };
    const normalized = aliases[monthKey] || monthKey;
    const monthIndex = MONTH_ABBR.indexOf(normalized);
    if (monthIndex < 0) return null;
    let monthCase = "lower";
    if (monthToken === monthToken.toUpperCase()) monthCase = "upper";
    else if (monthToken[0] === monthToken[0].toUpperCase()) monthCase = "title";
    return { month: monthIndex + 1, year, hasHyphen: sep === "-", monthCase };
  }

  function formatMonthYearText(parsed) {
    const abbr = MONTH_ABBR[parsed.month - 1] || "";
    let monthOut = abbr;
    if (parsed.monthCase === "upper") monthOut = abbr.toUpperCase();
    else if (parsed.monthCase === "title") monthOut = abbr.charAt(0).toUpperCase() + abbr.slice(1);
    const yy = String(parsed.year).slice(-2);
    return parsed.hasHyphen ? `${monthOut}-${yy}` : `${monthOut}${yy}`;
  }

  function addMonthsMonthYear(parsed, months) {
    let monthIndex = parsed.month - 1 + months;
    let year = parsed.year + Math.floor(monthIndex / 12);
    monthIndex = ((monthIndex % 12) + 12) % 12;
    return { month: monthIndex + 1, year, hasHyphen: parsed.hasHyphen, monthCase: parsed.monthCase };
  }

  function parseDayMonthYearText(dateText) {
    const raw = (dateText || "").trim();
    if (!raw) return null;
    const match = raw.match(/^(\d{1,2})\s*([A-Za-zÁÉÍÓÚáéíóúüÜ]{3})\s*(\d{2}|\d{4})$/);
    if (!match) return null;
    const day = parseInt(match[1], 10);
    const monthToken = match[2];
    let year = parseInt(match[3], 10);
    if (match[3].length === 2) year += year < 50 ? 2000 : 1900;
    const monthKey = monthToken.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
    const aliases = { set: "sep", sept: "sep" };
    const normalized = aliases[monthKey] || monthKey;
    const monthIndex = MONTH_ABBR.indexOf(normalized);
    if (monthIndex < 0 || day < 1 || day > 31) return null;
    let monthCase = "lower";
    if (monthToken === monthToken.toUpperCase()) monthCase = "upper";
    else if (monthToken[0] === monthToken[0].toUpperCase()) monthCase = "title";
    return { day, month: monthIndex + 1, year, monthCase, dayPadded: match[1].length >= 2 };
  }

  function formatDayMonthYearText(parsed) {
    const abbr = MONTH_ABBR[parsed.month - 1] || "";
    let monthOut = abbr;
    if (parsed.monthCase === "upper") monthOut = abbr.toUpperCase();
    else if (parsed.monthCase === "title") monthOut = abbr.charAt(0).toUpperCase() + abbr.slice(1);
    const dd = parsed.dayPadded ? String(parsed.day).padStart(2, "0") : String(parsed.day);
    const yy = String(parsed.year).slice(-2);
    return `${dd}${monthOut}${yy}`;
  }

  function productIsIntegral(productName) {
    return (productName || "")
      .toString()
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .includes("integral");
  }

  function isUser01Owner(ownerUsername) {
    return String(ownerUsername || "").trim().toLowerCase() === "user01";
  }

  function hasAdminFpPrefix(text) {
    return /^(FP)\s*/i.test((text || "").trim());
  }

  function stripAdminFpFvPrefix(text) {
    const raw = (text || "").trim();
    const match = raw.match(/^(FP|FV)\s*(.+)$/i);
    return match ? match[2].trim() : raw;
  }

  function formatAdminDayMonthYearBody(parsed) {
    const abbr = MONTH_ABBR[parsed.month - 1] || "";
    const monthOut = parsed.monthCase === "lower" ? abbr : abbr.toUpperCase();
    const dd = parsed.dayPadded !== false ? String(parsed.day).padStart(2, "0") : String(parsed.day);
    const yy = String(parsed.year).slice(-2);
    return `${dd}${monthOut}${yy}`;
  }

  function computeUser01Expiration(productionText, productName) {
    const value = (productionText || "").trim();
    if (!value) return null;
    const monthsAhead = productIsIntegral(productName) ? 6 : 8;
    const numeric = parseConstanciaDate(value);
    if (numeric) return formatUser01ProdExpDate(addMonthsKeepDay(numeric, monthsAhead));
    const monthYear = parseMonthYearText(value);
    if (monthYear) return formatMonthYearText(addMonthsMonthYear(monthYear, monthsAhead));
    const dayMonthYear = parseDayMonthYearText(value);
    if (dayMonthYear) {
      const next = addMonthsKeepDay(dayMonthYear, monthsAhead);
      return formatDayMonthYearText({ ...next, monthCase: dayMonthYear.monthCase, dayPadded: dayMonthYear.dayPadded });
    }
    return null;
  }

  function computeAdminExpiration(productionText, productName) {
    const value = (productionText || "").trim();
    if (!value) return null;
    const monthsAhead = productIsIntegral(productName) ? 6 : 8;
    const useFvPrefix = hasAdminFpPrefix(value);
    const inner = stripAdminFpFvPrefix(value);

    const dayMonthYear = parseDayMonthYearText(inner);
    if (dayMonthYear) {
      const next = addMonthsKeepDay(dayMonthYear, monthsAhead);
      const body = formatAdminDayMonthYearBody({ ...next, monthCase: dayMonthYear.monthCase, dayPadded: dayMonthYear.dayPadded });
      return useFvPrefix ? `FV${body}` : body;
    }
    const monthYear = parseMonthYearText(inner);
    if (monthYear) {
      const next = addMonthsMonthYear(monthYear, monthsAhead);
      const body = formatMonthYearText({ ...next, monthCase: monthYear.monthCase });
      return useFvPrefix ? `FV${body}` : body;
    }
    const numeric = parseConstanciaDate(inner);
    if (numeric) {
      const next = addMonthsKeepDay(numeric, monthsAhead);
      if (useFvPrefix) {
        return `FV${formatAdminDayMonthYearBody({ ...next, monthCase: "upper", dayPadded: true })}`;
      }
      return formatUser01ProdExpDate(next);
    }
    return null;
  }

  function computeExpirationFromProduction(productionText, productName, ownerUsername) {
    if (isUser01Owner(ownerUsername)) {
      return computeUser01Expiration(productionText, productName);
    }
    return computeAdminExpiration(productionText, productName);
  }

  window.QCDateExpiration = {
    computeExpirationFromProduction,
    isUser01Owner,
    productIsIntegral,
  };
})();
