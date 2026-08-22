(function () {

      function normalizeSearchText(value) {
        return (value || "")
          .toString()
          .trim()
          .toLowerCase()
          .normalize("NFD")
          .replace(/[\u0300-\u036f]/g, "")
          .replace(/[^a-z0-9]+/g, " ")
          .replace(/\s+/g, " ")
          .trim();
      }

      function itemSnapshotField(item, ...keys) {
        for (const key of keys) {
          const val = item?.[key];
          if (val !== undefined && val !== null && String(val).trim() !== "") return val;
        }
        return "";
      }

/** Firma por entorno: user01 usa firma propia; admin y resto usan firma.png */
      const FIRMA_BY_USERNAME = {
        admin: "/static/firma.png?v=1",
        user01: "/static/firma-user01.png?v=1",
      };

      function staticAssetUrl(path) {
        const value = String(path || "").trim();
        if (!value) return value;
        if (/^https?:\/\//i.test(value) || /^data:/i.test(value)) return value;
        try {
          const origin = typeof window !== "undefined" && window.location ? window.location.origin : "";
          if (origin) return `${origin}${value.startsWith("/") ? value : `/${value}`}`;
        } catch (e) {}
        return value;
      }

      function resolveFirmaSrcForUsername(username) {
        const key = String(username || "")
          .trim()
          .toLowerCase();
        return staticAssetUrl(FIRMA_BY_USERNAME[key] || "/static/firma.png?v=1");
      }

      function resolveConstanciaDocumentOwner(constancia, options) {
        const explicit = options?.ownerUsername || constancia?.owner_username;
        if (explicit) return String(explicit).trim();
        return "";
      }

      function applyConstanciaOwnerContext(username) {
        const ownerUser = String(username || "").trim();
        if (!ownerUser) return;
        window.QC_CONSTANCIA_OWNER_USERNAME = ownerUser;
        window.QC_CONSTANCIA_FIRMA_SRC = resolveFirmaSrcForUsername(ownerUser);
        if (typeof syncOcrMoreOptionsVisibility === "function") syncOcrMoreOptionsVisibility();
      }

      function syncConstanciaOwnerContextFromSession() {
        try {
          if (typeof isImpersonatingEnv === "function" && isImpersonatingEnv() && envOwnerProfile?.username) {
            applyConstanciaOwnerContext(envOwnerProfile.username);
            return;
          }
          const me = window.QCAuth && window.QCAuth.getUser && window.QCAuth.getUser();
          if (me?.username) applyConstanciaOwnerContext(me.username);
        } catch (e) {}
      }

      async function ensureConstanciaOwnerContext(fetchApi) {
        const fetchFn =
          fetchApi ||
          (window.QCAuth && typeof window.QCAuth.apiFetch === "function"
            ? window.QCAuth.apiFetch.bind(window.QCAuth)
            : fetch);
        try {
          const envRes = await fetchFn("/api/environment", { cache: "no-store" });
          const envData = await envRes.json().catch(() => ({}));
          if (envRes.ok && envData.owner?.username) {
            envOwnerProfile = envData.owner;
            applyConstanciaOwnerContext(envData.owner.username);
            return;
          }
        } catch (e) {}
        syncConstanciaOwnerContextFromSession();
      }

      function getConstanciaFirmaSrc() {
        if (typeof window !== "undefined" && window.QC_CONSTANCIA_FIRMA_SRC) {
          return staticAssetUrl(String(window.QC_CONSTANCIA_FIRMA_SRC));
        }
        try {
          if (typeof isImpersonatingEnv === "function" && isImpersonatingEnv()) {
            if (envOwnerProfile?.username) {
              return resolveFirmaSrcForUsername(envOwnerProfile.username);
            }
            return staticAssetUrl("/static/firma.png?v=1");
          }
          const me = window.QCAuth && window.QCAuth.getUser && window.QCAuth.getUser();
          if (me && me.username) return resolveFirmaSrcForUsername(me.username);
        } catch (e) {}
        return staticAssetUrl("/static/firma.png?v=1");
      }

      function getActiveConstanciaUsername() {
        try {
          if (typeof window !== "undefined" && window.QC_CONSTANCIA_OWNER_USERNAME) {
            return String(window.QC_CONSTANCIA_OWNER_USERNAME).trim().toLowerCase();
          }
          if (typeof isImpersonatingEnv === "function" && isImpersonatingEnv() && envOwnerProfile) {
            return String(envOwnerProfile.username || "").trim().toLowerCase();
          }
          const me = window.QCAuth && window.QCAuth.getUser && window.QCAuth.getUser();
          if (me && me.username) return String(me.username).trim().toLowerCase();
        } catch (e) {}
        return "";
      }

      function isUser01ConstanciaLayout() {
        return getActiveConstanciaUsername() === "user01";
      }

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

      /** PDF constancia: 06/06/2026 */
      function formatEmissionDate(dateText) {
        const parsed = parseConstanciaDate(dateText);
        if (!parsed) return dateText || "";
        const dd = String(parsed.day).padStart(2, "0");
        const mm = String(parsed.month).padStart(2, "0");
        return `${dd}/${mm}/${parsed.year}`;
      }

      /** PDF constancia — Fecha de envío: 6/06/26 */
      function formatShippingDate(dateText) {
        const parsed = parseConstanciaDate(dateText);
        if (!parsed) return dateText || "";
        const mm = String(parsed.month).padStart(2, "0");
        const yy = String(parsed.year).slice(-2);
        return `${parsed.day}/${mm}/${yy}`;
      }

      function formatDateMinusDays(dateText, days) {
        const parsed = parseConstanciaDate(dateText);
        if (!parsed) return "";
        const baseDate = new Date(parsed.year, parsed.month - 1, parsed.day);
        if (Number.isNaN(baseDate.getTime())) return "";
        baseDate.setDate(baseDate.getDate() - days);
        const dd = String(baseDate.getDate()).padStart(2, "0");
        const mm = String(baseDate.getMonth() + 1).padStart(2, "0");
        const yyyy = baseDate.getFullYear();
        return `${dd}/${mm}/${yyyy}`;
      }

      function formatShortDate(dateText) {
        const parts = (dateText || "").split("/").map((p) => p.trim());
        if (parts.length !== 3) return dateText || "";
        const [dd, mm, yyyy] = parts;
        if (!dd || !mm || !yyyy) return dateText || "";
        const yy = yyyy.slice(-2);
        return `${dd}/${mm}/${yy}`;
      }

      /** user01: suma meses conservando el día (si el mes no lo tiene, usa el último día). */
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

      /** Conserva el estilo de F. Prod: 03/08/2026, 3/8/26, 3/08/2026, etc. */
      function formatUser01ProdExpDate(parsed) {
        const dd =
          parsed.dayPadded === true
            ? String(parsed.day).padStart(2, "0")
            : String(parsed.day);
        const mm =
          parsed.monthPadded === true
            ? String(parsed.month).padStart(2, "0")
            : String(parsed.month);
        const yy =
          parsed.yearDigits === 4
            ? String(parsed.year)
            : String(parsed.year).slice(-2);
        return `${dd}/${mm}/${yy}`;
      }

      const USER01_MONTH_ABBR = [
        "ene",
        "feb",
        "mar",
        "abr",
        "may",
        "jun",
        "jul",
        "ago",
        "sep",
        "oct",
        "nov",
        "dic",
      ];

      /** Parsea ago-27 / ago27 / AGO27 / ago 27 → { month, year, hasHyphen, monthCase } */
      function parseUser01MonthYearText(dateText) {
        const raw = (dateText || "").trim();
        if (!raw) return null;
        const match = raw.match(/^([A-Za-zÁÉÍÓÚáéíóúüÜ]{3})\s*([-./]?)\s*(\d{2}|\d{4})$/);
        if (!match) return null;
        const monthToken = match[1];
        const sep = match[2] || "";
        let year = parseInt(match[3], 10);
        if (match[3].length === 2) year += year < 50 ? 2000 : 1900;
        const monthKey = monthToken
          .toLowerCase()
          .normalize("NFD")
          .replace(/[\u0300-\u036f]/g, "");
        const aliases = { set: "sep", sept: "sep" };
        const normalized = aliases[monthKey] || monthKey;
        const monthIndex = USER01_MONTH_ABBR.indexOf(normalized);
        if (monthIndex < 0) return null;
        const hasHyphen = sep === "-";
        let monthCase = "lower";
        if (monthToken === monthToken.toUpperCase()) monthCase = "upper";
        else if (monthToken[0] === monthToken[0].toUpperCase()) monthCase = "title";
        return {
          month: monthIndex + 1,
          year,
          hasHyphen,
          monthCase,
        };
      }

      function formatUser01MonthYearText(parsed) {
        const abbr = USER01_MONTH_ABBR[parsed.month - 1] || "";
        let monthOut = abbr;
        if (parsed.monthCase === "upper") monthOut = abbr.toUpperCase();
        else if (parsed.monthCase === "title") {
          monthOut = abbr.charAt(0).toUpperCase() + abbr.slice(1);
        }
        const yy = String(parsed.year).slice(-2);
        return parsed.hasHyphen ? `${monthOut}-${yy}` : `${monthOut}${yy}`;
      }

      function addMonthsMonthYear(parsed, months) {
        let monthIndex = parsed.month - 1 + months;
        let year = parsed.year + Math.floor(monthIndex / 12);
        monthIndex = ((monthIndex % 12) + 12) % 12;
        return {
          month: monthIndex + 1,
          year,
          hasHyphen: parsed.hasHyphen,
          monthCase: parsed.monthCase,
        };
      }

      /** Parsea 01DIC25 / 1ago26 → día + mes texto + año */
      function parseUser01DayMonthYearText(dateText) {
        const raw = (dateText || "").trim();
        if (!raw) return null;
        const match = raw.match(/^(\d{1,2})\s*([A-Za-zÁÉÍÓÚáéíóúüÜ]{3})\s*(\d{2}|\d{4})$/);
        if (!match) return null;
        const day = parseInt(match[1], 10);
        const monthToken = match[2];
        let year = parseInt(match[3], 10);
        if (match[3].length === 2) year += year < 50 ? 2000 : 1900;
        const monthKey = monthToken
          .toLowerCase()
          .normalize("NFD")
          .replace(/[\u0300-\u036f]/g, "");
        const aliases = { set: "sep", sept: "sep" };
        const normalized = aliases[monthKey] || monthKey;
        const monthIndex = USER01_MONTH_ABBR.indexOf(normalized);
        if (monthIndex < 0 || day < 1 || day > 31) return null;
        let monthCase = "lower";
        if (monthToken === monthToken.toUpperCase()) monthCase = "upper";
        else if (monthToken[0] === monthToken[0].toUpperCase()) monthCase = "title";
        return {
          day,
          month: monthIndex + 1,
          year,
          monthCase,
          dayPadded: match[1].length >= 2,
        };
      }

      function formatUser01DayMonthYearText(parsed) {
        const abbr = USER01_MONTH_ABBR[parsed.month - 1] || "";
        let monthOut = abbr;
        if (parsed.monthCase === "upper") monthOut = abbr.toUpperCase();
        else if (parsed.monthCase === "title") {
          monthOut = abbr.charAt(0).toUpperCase() + abbr.slice(1);
        }
        const dd = parsed.dayPadded
          ? String(parsed.day).padStart(2, "0")
          : String(parsed.day);
        const yy = String(parsed.year).slice(-2);
        return `${dd}${monthOut}${yy}`;
      }

      function user01ProductIsIntegral(productName) {
        return (productName || "")
          .toString()
          .toLowerCase()
          .normalize("NFD")
          .replace(/[\u0300-\u036f]/g, "")
          .includes("integral");
      }

      /** Devuelve F. Vencimiento (+6 integral / +8 resto) o null si no reconoce el formato. */
      function computeUser01ExpirationFromProduction(productionText, productName) {
        if (typeof isUser01ConstanciaLayout !== "function" || !isUser01ConstanciaLayout()) {
          return null;
        }
        const value = (productionText || "").trim();
        if (!value) return null;
        const monthsAhead = user01ProductIsIntegral(productName) ? 6 : 8;

        const numeric = parseConstanciaDate(value);
        if (numeric) {
          return formatUser01ProdExpDate(addMonthsKeepDay(numeric, monthsAhead));
        }

        const monthYear = parseUser01MonthYearText(value);
        if (monthYear) {
          return formatUser01MonthYearText(addMonthsMonthYear(monthYear, monthsAhead));
        }

        const dayMonthYear = parseUser01DayMonthYearText(value);
        if (dayMonthYear) {
          const next = addMonthsKeepDay(dayMonthYear, monthsAhead);
          return formatUser01DayMonthYearText({
            ...next,
            monthCase: dayMonthYear.monthCase,
            dayPadded: dayMonthYear.dayPadded,
          });
        }

        return null;
      }

      /** user01 (constancia): al editar F. Producción → F. Vencimiento. */
      function applyUser01ExpirationFromProduction(prodInput) {
        if (!(prodInput instanceof HTMLInputElement)) return;
        if (!prodInput.classList.contains("prod-date-input")) return;
        const row = prodInput.closest("tr");
        const expInput = row?.querySelector(".exp-date-input");
        if (!expInput) return;
        const productName = row.querySelector(".product-input")?.value || "";
        const computed = computeUser01ExpirationFromProduction(prodInput.value, productName);
        if (computed != null) expInput.value = computed;
      }

      /** user01 (catálogo): al editar Fecha Producción → Fecha Vencimiento. */
      function applyUser01CatalogExpirationFromProduction() {
        if (!prodProduction || !prodExpiration) return;
        const computed = computeUser01ExpirationFromProduction(
          prodProduction.value,
          prodName?.value || ""
        );
        if (computed != null) prodExpiration.value = computed;
      }

      function bindUser01CatalogExpirationCalc() {
        if (!prodProduction || !prodExpiration) return;
        const run = () => applyUser01CatalogExpirationFromProduction();
        prodProduction.addEventListener("change", run);
        prodProduction.addEventListener("blur", run);
        if (prodName) {
          prodName.addEventListener("change", () => {
            if ((prodProduction.value || "").trim()) run();
          });
          prodName.addEventListener("blur", () => {
            if ((prodProduction.value || "").trim()) run();
          });
        }
      }

      // SKU Ajiles: mapas independientes (admin/otros vs user01)
      const AJILES_PERU_SKU_MAP_ADMIN = [
        { patterns: ["ARROZ EXTRA GRAN CHALAN X 5KG", "GRAN CHALAN X 5KG"], sku: "13010200100586" },
        { patterns: ["DON CHEF ARROZ SUPERIOR BL 4KG", "ARROZ SUPERIOR BL 4KG"], sku: "130102003001" },
        { patterns: ["DON CHEF ARROZ EXTRA BL 650GR", "ARROZ EXTRA BL 650GR", "ARROZ EXTRA BL 650 GR"], sku: "130102003002" },
        { patterns: ["DON CHEF ARROZ EXTRA BL 2KG", "ARROZ EXTRA BL 2KG", "ARROZ EXTRA BL 2 KG"], sku: "13010200112538" },
        { patterns: ["MI ARROZ SUPERIOR NIR X 25 KG", "ARROZ SUPERIOR NIR X 25 KG"], sku: "130102003003" },
      ];
      const AJILES_PERU_SKU_MAP_USER01 = [
        {
          patterns: [
            "DON CHEF ARROZ EXTRA BL 650 GR",
            "DON CHEF ARROZ EXTRA BL 650GR",
            "ARROZ EXTRA BL 650 GR",
            "ARROZ EXTRA BL 650GR",
          ],
          sku: "130102003002",
        },
        {
          patterns: [
            "MI ARROZ SUPERIOR NIR 25 KG",
            "MI ARROZ SUPERIOR NIR X 25 KG",
            "ARROZ SUPERIOR NIR 25 KG",
            "ARROZ SUPERIOR NIR X 25 KG",
          ],
          sku: "130102003003",
        },
        {
          patterns: [
            "DON CHEF ARROZ SUPERIOR BL 4 KG",
            "DON CHEF ARROZ SUPERIOR BL 4KG",
            "ARROZ SUPERIOR BL 4 KG",
            "ARROZ SUPERIOR BL 4KG",
          ],
          sku: "130102003001",
        },
        {
          patterns: [
            "ARROZ EXTRA GRAN CHALAN 5KG",
            "ARROZ EXTRA GRAN CHALAN 5 KG",
            "ARROZ EXTRA GRAN CHALAN X 5KG",
            "GRAN CHALAN 5KG",
            "GRAN CHALAN X 5KG",
          ],
          sku: "13010200100586",
        },
      ];

      function isAjilesPeruClient(clientName) {
        const key = normalizeSearchText(clientName);
        return key.includes("ajiles") && key.includes("peru");
      }

      /** user01: clientes Makro → cabecera PDF de fumigación personalizada. */
      function isMakroClient(clientName) {
        return normalizeSearchText(clientName).includes("makro");
      }

      /** user01: HIPERMERCADOS TOTTUS S.A. → PDF fumigación/desinsectación personalizado. */
      function isHipermercadosTottusClient(clientName) {
        const key = normalizeSearchText(clientName);
        return key.includes("tottus") && key.includes("hipermercado");
      }

      /** user01: CENCOSUD CD PRINCIPAL → mismo formato que Tottus. */
      function isCencosudCdPrincipalClient(clientName) {
        const key = normalizeSearchText(clientName);
        return key.includes("cencosud") && key.includes("cd") && key.includes("principal");
      }

      /** Tottus o Cencosud CD Principal: mismo layout fumigación + desinsectación (solo user01). */
      function isTottusStyleConstanciaClient(clientName) {
        return isHipermercadosTottusClient(clientName) || isCencosudCdPrincipalClient(clientName);
      }

      function resolveAjilesSku(productName) {
        const key = normalizeSearchText(productName);
        if (!key) return "";
        const keyCompact = key.replace(/\s+/g, "");
        const map =
          typeof isUser01ConstanciaLayout === "function" && isUser01ConstanciaLayout()
            ? AJILES_PERU_SKU_MAP_USER01
            : AJILES_PERU_SKU_MAP_ADMIN;
        for (const entry of map) {
          for (const pattern of entry.patterns) {
            const normalizedPattern = normalizeSearchText(pattern);
            const patternCompact = normalizedPattern.replace(/\s+/g, "");
            if (
              key === normalizedPattern ||
              key.includes(normalizedPattern) ||
              normalizedPattern.includes(key) ||
              keyCompact === patternCompact ||
              keyCompact.includes(patternCompact) ||
              patternCompact.includes(keyCompact)
            ) {
              return entry.sku;
            }
          }
        }
        return "";
      }

      function formatAjilesDocDate(dateText) {
        const parsed = parseConstanciaDate(dateText);
        if (!parsed) return dateText || "";
        const dd = String(parsed.day).padStart(2, "0");
        const mm = String(parsed.month).padStart(2, "0");
        return `${dd} / ${mm} / ${parsed.year}`;
      }

      function formatAjilesFv(expirationText) {
        const raw = (expirationText || "").toString().trim();
        if (!raw || raw === "-") return "";
        return raw;
      }

      function formatAjilesLote(loteText) {
        const raw = (loteText || "").toString().trim();
        if (!raw || raw === "-") return "";
        if (/^LOTE-/i.test(raw)) return raw.toUpperCase();
        return raw;
      }

      function buildAjilesProductRows(items) {
        if (!items.length) {
          return `<tr><td colspan="8" class="aj-c aj-empty-row">Sin productos</td></tr>`;
        }
        return items
          .map((item, idx) => {
            const productName = itemSnapshotField(item, "product_name_snapshot", "product");
            const lote = itemSnapshotField(item, "lote_snapshot", "lot");
            const expiration = itemSnapshotField(item, "expiration_date_snapshot", "expiration_text");
            return `
            <tr>
              <td class="aj-c">${idx + 1}</td>
              <td class="aj-c">${resolveAjilesSku(productName)}</td>
              <td class="aj-c aj-desc">${productName}</td>
              <td class="aj-c">${item.quantity ?? ""}</td>
              <td class="aj-c">${formatAjilesFv(expiration)}</td>
              <td class="aj-c">${formatAjilesLote(lote)}</td>
              <td class="aj-c"></td>
              <td class="aj-c"></td>
            </tr>
          `;
          })
          .join("");
      }

      function buildAjilesQualityPage(constancia, clientMatch, items, fecha) {
        const docDate = formatAjilesDocDate(fecha);
        const cliente = (constancia.client_name || "AJILES PERU").toUpperCase();
        const clientRuc = (clientMatch?.ruc || "20612232203").toString().trim();
        const productRowsHtml = buildAjilesProductRows(items);
        return `
          <div class="page ajiles-quality-page last-page">
            <div class="ajiles-body">
              <div class="ajiles-main">
              <table class="ajiles-sheet ajiles-head" cellspacing="0" cellpadding="0">
                <colgroup>
                  <col class="aj-col-logo" />
                  <col class="aj-col-title" />
                  <col class="aj-col-meta" />
                </colgroup>
                <tr class="aj-h">
                  <td class="aj-logo-cell">
                    <img class="aj-logo" src="/static/logo-3a-header.png" alt="3A" />
                  </td>
                  <td class="aj-title-cell">
                    <strong>CONTROL DE CALIDAD EN LA RECEPCIÓN DE CENTRO DE DISTRIBUCIÓN MECHITA</strong>
                  </td>
                  <td class="aj-meta-cell">
                    <div class="aj-meta-wrap">
                      <table class="aj-meta-inner" cellspacing="0" cellpadding="0">
                        <tr><td class="aj-meta-l">Código:</td><td>013</td></tr>
                        <tr><td class="aj-meta-l">Revisión:</td><td>01</td></tr>
                        <tr><td class="aj-meta-l">Fecha:</td><td>${docDate}</td></tr>
                        <tr><td class="aj-meta-l">Página:</td><td>1 de 1</td></tr>
                      </table>
                    </div>
                  </td>
                </tr>
              </table>
              <table class="ajiles-sheet ajiles-provider" cellspacing="0" cellpadding="0">
                <colgroup>
                  <col class="aj-col-logo" />
                  <col class="aj-col-prov-val" />
                </colgroup>
                <tr><td colspan="2" class="aj-bar">PARA SER INGRESADO POR EL PROVEEDOR</td></tr>
                <tr>
                  <td class="aj-prov-lbl">PROVEEDOR</td>
                  <td class="aj-prov-val">${cliente}</td>
                </tr>
                <tr>
                  <td class="aj-prov-lbl">R.U.C.</td>
                  <td class="aj-prov-val">${clientRuc}</td>
                </tr>
                <tr>
                  <td class="aj-prov-lbl">FECHA DE DESPACHO</td>
                  <td class="aj-prov-val">${docDate}</td>
                </tr>
                <tr>
                  <td class="aj-prov-lbl">JERARQUÍA</td>
                  <td class="aj-prov-val">BÁSICOS</td>
                </tr>
              </table>
              <table class="ajiles-sheet ajiles-products" cellspacing="0" cellpadding="0">
                <colgroup>
                  <col style="width:3.5%" />
                  <col style="width:13.5%" />
                  <col style="width:30%" />
                  <col style="width:8.5%" />
                  <col style="width:10.5%" />
                  <col style="width:10.5%" />
                  <col style="width:9%" />
                  <col style="width:14.5%" />
                </colgroup>
                <tr>
                  <th colspan="6" rowspan="2" class="aj-bar aj-bar-merged">PARA SER INGRESADO POR EL PROVEEDOR</th>
                  <th colspan="2" class="aj-bar">INGRESADO POR 3A</th>
                </tr>
                <tr>
                  <th colspan="2" class="aj-bar">EVALUACIÓN DE PRODUCTOS</th>
                </tr>
                <tr class="aj-head-row">
                  <th>#</th>
                  <th>SKU 3A</th>
                  <th>DESCRIPCIÓN DEL PRODUCTO</th>
                  <th>CANTIDAD</th>
                  <th>FV</th>
                  <th>LOTE</th>
                  <th>T° (°C)</th>
                  <th>RESULTADO (C) Y (NC)</th>
                </tr>
                ${productRowsHtml}
              </table>
              <table class="ajiles-sheet ajiles-checks" cellspacing="0" cellpadding="0">
                <tr><td colspan="3" class="aj-bar">PARA SER INGRESADO POR 3A</td></tr>
                <tr>
                  <td class="aj-check-lbl">CONDICIONES DEL TRANSPORTE</td>
                  <td class="aj-check-opt">Se encuentra limpio y en buen estado</td>
                  <td class="aj-check-opt">Se encuentra sucio</td>
                </tr>
                <tr>
                  <td class="aj-check-lbl">BPH - PERSONAL</td>
                  <td class="aj-check-opt">Uniforme completo y limpio</td>
                  <td class="aj-check-opt">Tiene carnet de sanidad</td>
                </tr>
              </table>
              <table class="ajiles-sheet ajiles-obs" cellspacing="0" cellpadding="0">
                <tr>
                  <td class="aj-obs-cell">
                    <span class="aj-obs-title">OBSERVACIONES</span>
                  </td>
                </tr>
              </table>
              <div class="aj-obs-note">Se colocará '--' cuando no aplique el ítem mencionado.</div>
            </div>
            <div class="ajiles-bottom">
              <div class="aj-sign-row">
                <div class="aj-sign-col">
                  <div class="aj-sign-img-wrap">
                    <img class="aj-firma" src="${getConstanciaFirmaSrc()}" alt="Firma" />
                  </div>
                  <div class="aj-sign-line"></div>
                  <div class="aj-sign-lbl">NOMBRE DE REPRESENTANTE DE LA EMPRESA</div>
                </div>
                <div class="aj-sign-col">
                  <div class="aj-sign-spacer"></div>
                  <div class="aj-sign-line"></div>
                  <div class="aj-sign-lbl">NOMBRE DEL EVALUADOR</div>
                </div>
              </div>
              <table class="ajiles-sheet aj-temp-table" cellspacing="0" cellpadding="0">
                <tr>
                  <td class="aj-temp-cell">
                    <div class="aj-temp-title">Control de Temperatura: (NO OMITIR ESTA PARTE)</div>
                    <div class="aj-temp-line">* La temperatura del producto se valida con lo indicado en su rotulado. Para los productos que no presentan rango, considerar las siguientes temperaturas genéricas:</div>
                    <div class="aj-temp-line">* La temperatura de productos hidrobiológicos congelados: ≤ -18°C.</div>
                    <div class="aj-temp-line">* La temperatura de productos refrigerados: 0°C - 6°C.</div>
                    <div class="aj-temp-line">* La temperatura de productos congelados (no hidrobiológicos): ≤ -12°C.</div>
                    <div class="aj-temp-line">* La temperatura de productos helados: ≤ -16°C.</div>
                  </td>
                </tr>
              </table>
              <div class="aj-footer">
                <div>Av. Camino Real N° 931 Dpto. 201 San Isidro - Lima.</div>
                <div class="aj-email">induamerica@induamerica.com.pe</div>
              </div>
            </div>
            </div>
          </div>
        `;
      }

      const CENCOSUD_CD_LIMA_CLIENT_IDS = new Set([25]);

      function isCencosudCdLimaClient(clientName, clientMatch = null) {
        if (clientMatch?.id && CENCOSUD_CD_LIMA_CLIENT_IDS.has(Number(clientMatch.id))) {
          return true;
        }
        const candidates = [clientName, clientMatch?.name].filter(Boolean);
        return candidates.some((name) => {
          const key = normalizeSearchText(name);
          if (!key.includes("cencosud") || !key.includes("lima")) return false;
          return key.includes("cd") || key.includes("centro de distribucion");
        });
      }

      const CENCOSUD_TRANSPORT_EMPRESA = "INDUAMERICA INTERNACIONAL S.A.C.";

      function buildCencosudTransportRows(items, fecha, transporte, empresa) {
        const rowCount = Math.max(items.length, 1);
        const envio = formatEmissionDate(fecha);
        if (!items.length) {
          return `
            <tr>
              <td class="ct-col-item">1</td>
              <td class="ct-col-fecha">${envio}</td>
              <td class="ct-col-empresa" rowspan="1">${empresa}</td>
              <td class="ct-col-placa" rowspan="1">${transporte || ""}</td>
              <td class="ct-col-producto"></td>
              <td class="ct-col-cant"></td>
            </tr>
          `;
        }
        return items
          .map((item, idx) => {
            const productName = itemSnapshotField(item, "product_name_snapshot", "product");
            const mergedCells =
              idx === 0
                ? `<td class="ct-col-empresa" rowspan="${rowCount}">${empresa}</td><td class="ct-col-placa" rowspan="${rowCount}">${transporte || ""}</td>`
                : "";
            return `
            <tr>
              <td class="ct-col-item">${idx + 1}</td>
              <td class="ct-col-fecha">${envio}</td>
              ${mergedCells}
              <td class="ct-col-producto">${productName}</td>
              <td class="ct-col-cant">${item.quantity ?? ""}</td>
            </tr>
          `;
          })
          .join("");
      }

      function buildCencosudTransportPage(constancia, items, fecha, numero, cliente, transporte) {
        const transportRows = buildCencosudTransportRows(items, fecha, transporte, CENCOSUD_TRANSPORT_EMPRESA);
        return `
          <div class="page cencosud-transport-page last-page">
            <div class="header">
              <img class="logo" src="/static/logo.png" alt="Induamerica" />
            </div>
            <div class="box">
              <div class="title">CONSTANCIA DE FUMIGACIÓN TRANSPORTE N° ${numero}</div>
              <table class="meta ct-meta">
                <tbody>
                  <tr>
                    <td class="label">FECHA DE EMISION</td>
                    <td class="value">${formatEmissionDate(fecha)}</td>
                  </tr>
                  <tr>
                    <td class="label">CLIENTE:</td>
                    <td class="value">${cliente}</td>
                  </tr>
                </tbody>
              </table>
              <div class="note ct-note">
                Mediante el presente documento dejamos constancia que las unidades de transporte son desinsectadas con S-DELTA 50 SC (10 ml x 1 l de agua) con mochila manual; y las parihuelas son fumigadas con fosfuro de aluminio (PHOSFIN) en dosis de 4 Tab/m3 .
              </div>
              <table class="meta ct-pest">
                <tbody>
                  <tr>
                    <td class="label">Plaguicida Usado:</td>
                    <td class="value">S-DELTA 50 SC</td>
                    <td class="label">Proveedor:</td>
                    <td class="value ct-proveedor">INDUAMERICA</td>
                  </tr>
                </tbody>
              </table>
              <table class="data ct-transport">
                <colgroup>
                  <col style="width:3%" />
                  <col style="width:9%" />
                  <col style="width:16%" />
                  <col style="width:7%" />
                  <col style="width:56%" />
                  <col style="width:9%" />
                </colgroup>
                <thead>
                  <tr>
                    <th colspan="6">TRANSPORTE</th>
                  </tr>
                  <tr>
                    <th class="ct-col-item">Item</th>
                    <th class="ct-col-fecha">F. Envio</th>
                    <th class="ct-col-empresa">Empresa<br>Transporte</th>
                    <th class="ct-col-placa">Placa</th>
                    <th class="ct-col-producto">PRODUCTO</th>
                    <th class="ct-col-cant">Cant.</th>
                  </tr>
                </thead>
                <tbody>
                  ${transportRows}
                </tbody>
              </table>
            </div>
            <div class="footer">
              <div class="firma-wrap">
                <img class="firma" src="${getConstanciaFirmaSrc()}" alt="Firma" />
              </div>
              <div class="footer-text">
                <div>Av. Camino Real N° 931 Dpto. 201 San Isidro - Lima.</div>
                <div class="email">induamerica@induamerica.com.pe</div>
              </div>
            </div>
          </div>
        `;
      }

      const TOTTUS_DESINSECTACION_EMPRESA =
        "Induamerica Servicios<br>Logísticos S.A.C.";

      /** Consolida productos repetidos sumando cantidades (nombre una sola vez). */
      function consolidateTottusProducts(items) {
        const ordered = [];
        const indexByKey = new Map();
        (items || []).forEach((item) => {
          const productName = (itemSnapshotField(item, "product_name_snapshot", "product") || "")
            .toString()
            .trim();
          if (!productName) return;
          const key = normalizeSearchText(productName);
          const qtyRaw = item?.quantity;
          const qty = qtyRaw === "" || qtyRaw === null || qtyRaw === undefined ? 0 : Number(qtyRaw);
          const addQty = Number.isFinite(qty) ? qty : 0;
          if (indexByKey.has(key)) {
            const entry = ordered[indexByKey.get(key)];
            entry.quantity = (Number(entry.quantity) || 0) + addQty;
          } else {
            indexByKey.set(key, ordered.length);
            ordered.push({ product: productName, quantity: addQty });
          }
        });
        return ordered;
      }

      function buildTottusDesinsectacionRows(items, fecha, transporte, mobileNumber, pallets) {
        const consolidated = consolidateTottusProducts(items);
        const rowCount = Math.max(consolidated.length, 1);
        const envio = formatEmissionDate(fecha);
        const mobile = (mobileNumber || "").toString().trim().toUpperCase().slice(0, 2) || "";
        const palets = (pallets || "").toString().trim().slice(0, 2) || "";
        const plate = (transporte || "").toString().trim();
        if (!consolidated.length) {
          return `
            <tr>
              <td class="td-mobile" rowspan="1">${mobile}</td>
              <td class="td-fecha" rowspan="1">${envio}</td>
              <td class="td-empresa" rowspan="1">${TOTTUS_DESINSECTACION_EMPRESA}</td>
              <td class="td-placa" rowspan="1">${plate}</td>
              <td class="td-producto"></td>
              <td class="td-cant"></td>
              <td class="td-palets" rowspan="1">${palets}</td>
            </tr>
          `;
        }
        return consolidated
          .map((entry, idx) => {
            const merged =
              idx === 0
                ? `
              <td class="td-mobile" rowspan="${rowCount}">${mobile}</td>
              <td class="td-fecha" rowspan="${rowCount}">${envio}</td>
              <td class="td-empresa" rowspan="${rowCount}">${TOTTUS_DESINSECTACION_EMPRESA}</td>
              <td class="td-placa" rowspan="${rowCount}">${plate}</td>
            `
                : "";
            const paletsCell =
              idx === 0 ? `<td class="td-palets" rowspan="${rowCount}">${palets}</td>` : "";
            const qtyShow =
              entry.quantity === 0 || entry.quantity === "" ? "" : entry.quantity;
            return `
            <tr>
              ${merged}
              <td class="td-producto cell-fit-line">${entry.product}</td>
              <td class="td-cant">${qtyShow}</td>
              ${paletsCell}
            </tr>
          `;
          })
          .join("");
      }

      function computeUser01TableZoomStyle(rowCount, availMm = 128) {
        const n = Math.max(Number(rowCount) || 0, 1);
        const idealRowMm = availMm / n;
        const maxRowMm = n <= 3 ? 14 : n <= 6 ? 11.5 : n <= 12 ? 9 : 7;
        const rowMm = Math.min(maxRowMm, Math.max(4.2, idealRowMm));
        const fontPx = Math.min(11.5, Math.max(7.4, rowMm * 0.9));
        const headPx = Math.min(11.8, Math.max(7.6, fontPx * 1.05));
        const padPx = Math.min(3.2, Math.max(1.0, fontPx * 0.22));
        return `--u01-n:${n};--u01-fs:${fontPx.toFixed(2)}px;--u01-fs-head:${headPx.toFixed(2)}px;--u01-pad:${padPx.toFixed(2)}px;--u01-row-h:${rowMm.toFixed(2)}mm;`;
      }

      function buildTottusFumigacionPage({
        numero,
        fecha,
        cliente,
        issuerCompany,
        tableHeadHtml,
        rowsHtml,
        colspan,
        wrapTable,
      }) {
        const issuer = issuerCompany || "INDUAMERICA INTERNACIONAL S.A.C.";
        const introHtml = `
              <table class="meta tottus-meta">
                <tbody>
                  <tr>
                    <td class="label">FECHA DE EMISIÓN</td>
                    <td class="value">${formatEmissionDate(fecha)}</td>
                  </tr>
                  <tr>
                    <td class="label">CLIENTE</td>
                    <td class="value">${cliente || ""}</td>
                  </tr>
                </tbody>
              </table>
              <div class="note">
                Mediante el presente documento dejamos constancia que los lotes de arroz pilado, detallados han sido tratados con fosfuro de aluminio (PHOSFIN) en nuestro almacén principal, en dosis de 5 tab/ton.
              </div>
              <table class="meta tottus-pest">
                <tbody>
                  <tr>
                    <td class="label">Plaguicida Usado:</td>
                    <td class="value">FOSFURO DE ALUMINIO (PHOSFIN)</td>
                    <td class="label">Proveedor:</td>
                    <td class="value">${issuer}</td>
                  </tr>
                </tbody>
              </table>
            `;
        const wrap = typeof wrapTable === "function" ? wrapTable : (html) => html;
        return `
          <div class="page first-page">
            <div class="header">
              <img class="logo" src="/static/logo.png" alt="Induamerica" />
            </div>
            <div class="box">
              <div class="title">CONSTANCIA DE FUMIGACIÓN N° ${numero}</div>
              ${introHtml}
              ${wrap(`
              <table class="data tottus-fum">
                <thead>
                  <tr>
                    ${tableHeadHtml}
                  </tr>
                </thead>
                <tbody>
                  ${rowsHtml || `<tr><td colspan='${colspan}' class='empty'>Sin productos</td></tr>`}
                </tbody>
              </table>
              `)}
            </div>
            <div class="footer">
              <div class="firma-wrap">
                <img class="firma" src="${getConstanciaFirmaSrc()}" alt="Firma" />
              </div>
              <div class="footer-text">
                <div>Av. Camino Real N° 931 Dpto. 201 San Isidro - Lima.</div>
                <div class="email">induamerica@induamerica.com.pe</div>
              </div>
            </div>
          </div>
        `;
      }

      function buildTottusDesinsectacionPage(
        constancia,
        items,
        fecha,
        numero,
        cliente,
        transporte,
        options = {}
      ) {
        const mobileNumber = constancia.mobile_number || constancia.mobile || "";
        const pallets = constancia.pallets || constancia.palets || "";
        const enableUser01Zoom = !!options.enableUser01Zoom;
        const issuerCompany = options.issuerCompany || "INDUAMERICA INTERNACIONAL S.A.C.";
        const consolidated = consolidateTottusProducts(items);
        const rowsHtml = buildTottusDesinsectacionRows(
          items,
          fecha,
          transporte,
          mobileNumber,
          pallets
        );
        const tableHtml = `
              <table class="data tottus-desinsectacion">
                <colgroup>
                  <col style="width:5%" />
                  <col style="width:9%" />
                  <col style="width:12%" />
                  <col style="width:9%" />
                  <col style="width:47%" />
                  <col style="width:10%" />
                  <col style="width:8%" />
                </colgroup>
                <tbody>
                  ${rowsHtml}
                </tbody>
              </table>
            `;
        // Zoom propio según filas consolidadas (no según ítems crudos de fumigación)
        const tableBlock = enableUser01Zoom
          ? `<div class="u01-table-slot" style="${computeUser01TableZoomStyle(consolidated.length, 155)}">${tableHtml}</div>`
          : tableHtml;
        return `
          <div class="page tottus-desinsectacion-page last-page">
            <div class="header">
              <img class="logo" src="/static/logo.png" alt="Induamerica" />
            </div>
            <div class="box">
              <div class="title">CONSTANCIA DE DESINSECTACIÓN N° ${numero}</div>
              <table class="meta tottus-meta">
                <tbody>
                  <tr>
                    <td class="label">FECHA DE EMISION</td>
                    <td class="value">${formatEmissionDate(fecha)}</td>
                  </tr>
                  <tr>
                    <td class="label">CLIENTE</td>
                    <td class="value">${cliente || ""}</td>
                  </tr>
                </tbody>
              </table>
              <table class="meta tottus-pest" style="margin-top:0;">
                <tbody>
                  <tr>
                    <td class="label">Plaguicida Usado:</td>
                    <td class="value">S-DELTA 50 SC</td>
                    <td class="label">Proveedor:</td>
                    <td class="value">${issuerCompany}</td>
                  </tr>
                </tbody>
              </table>
              ${tableBlock}
            </div>
            <div class="footer">
              <div class="firma-wrap">
                <img class="firma" src="${getConstanciaFirmaSrc()}" alt="Firma" />
              </div>
              <div class="footer-text">
                <div>Av. Camino Real N° 931 Dpto. 201 San Isidro - Lima.</div>
                <div class="email">induamerica@induamerica.com.pe</div>
              </div>
            </div>
          </div>
        `;
      }

      function applyConstanciaPageBreaks(pageHtmlList) {
        return pageHtmlList
          .map((html, index) => {
            const breakClass = index < pageHtmlList.length - 1 ? "first-page" : "last-page";
            return html.replace(/class="([^"]*)"/, (full, classNames) => {
              if (!classNames.startsWith("page")) return full;
              const modifiers = classNames
                .split(/\s+/)
                .filter((c) => c && c !== "page" && c !== "first-page" && c !== "last-page");
              return `class="page${modifiers.length ? " " + modifiers.join(" ") : ""} ${breakClass}"`;
            });
          })
          .join("");
      }

      function buildConstanciaHtml(constancia, catalog, clients = null, options = null) {
        const documentOwner = resolveConstanciaDocumentOwner(constancia, options);
        if (documentOwner) {
          applyConstanciaOwnerContext(documentOwner);
        } else {
          syncConstanciaOwnerContextFromSession();
        }
        const previewSide =
          options && (options.dualPreviewSide === "internacional" || options.dualPreviewSide === "comercial")
            ? options.dualPreviewSide
            : null;
        const numero = constancia.number || constancia.id || "";
        const fecha = constancia.issue_date || "";
        const cliente = constancia.client_name || "";
        const clientList = Array.isArray(clients) ? clients : (Array.isArray(allClients) ? allClients : []);
        const clientKey = normalizeSearchText(cliente);
        const clientMatch = clientList.find((item) => normalizeSearchText(item.name) === clientKey);
        const clientRuc = (clientMatch?.ruc || "").toString().trim();
        const clientRucLine = clientRuc ? `<div style="margin-top:2px;">RUC: ${clientRuc}</div>` : "";
        const fileDate = formatShortDate(fecha).replaceAll("/", "-") || "constancia";
        const safeCliente = (cliente || "cliente")
          .replace(/[^a-zA-Z0-9 -]/g, "")
          .trim()
          .replace(/\s+/g, " ");
        let fileName = `${fileDate} ${safeCliente}`.trim();
        if (previewSide === "internacional") {
          fileName += " Intl";
        } else if (previewSide === "comercial") {
          fileName += " Comercial";
        }
        const transporte = constancia.transport_plate || "";
        const fumigacion = formatDateMinusDays(fecha, 9);
        const liberacion = formatDateMinusDays(fecha, 2);
        const instalaciones = formatDateMinusDays(fecha, 0);
        const showFumigacion = constancia.fumigacion !== 0 && constancia.fumigacion !== false;
        const showCalidad = constancia.calidad !== 0 && constancia.calidad !== false;
        const user01Layout = isUser01ConstanciaLayout();
        const isAjilesFumigacion = isAjilesPeruClient(cliente);
        const isMakroFumigacion =
          user01Layout && isMakroClient(cliente) && !isAjilesFumigacion;
        const isTottusFumigacion =
          user01Layout &&
          isTottusStyleConstanciaClient(cliente) &&
          !isAjilesFumigacion &&
          !isMakroFumigacion;
        const items = constancia.items || [];
        const productCellHtml = (name) =>
          `<td class="cell-fit-line">${(name || "").toString()}</td>`;
        function buildFumigacionRowsHtml(sourceItems, plateValue) {
          const list = sourceItems || [];
          const plate = plateValue ?? transporte;
          return list
            .map((item, idx) => {
            const fumDefault = isAjilesFumigacion ? liberacion : fumigacion;
            const fumCell = formatShortDate(
              itemSnapshotField(item, "f_fumigacion", "fumigacion_date") || fumDefault
            );
            const libCell = formatShortDate(
              itemSnapshotField(item, "f_liberacion", "liberacion_date") || liberacion
            );
            const instCell = formatShortDate(
              itemSnapshotField(item, "f_instalaciones", "instalaciones_date") || instalaciones
            );
            const shipRaw = itemSnapshotField(item, "fecha_envio", "shipping_date");
            const shipCell = shipRaw ? formatShortDate(shipRaw) || shipRaw : formatShippingDate(fecha);
            const sacos =
              itemSnapshotField(item, "fumigacion_sacos", "cant_fumigada") || "400";
            const tabletas = itemSnapshotField(item, "tabletas", "n_tabletas") || "100";
            const fosfina = itemSnapshotField(item, "nivel_fosfina", "fosfina") || "1800";
            const productName = itemSnapshotField(item, "product_name_snapshot", "product");
            if (isAjilesFumigacion) {
              const plateCell =
                idx === 0
                  ? `<td rowspan="${Math.max(list.length, 1)}" style="text-align:center; vertical-align:middle;">${plate || "-"}</td>`
                  : "";
              return `
            <tr>
              <td>${idx + 1}</td>
              <td>${shipCell}</td>
              ${productCellHtml(productName)}
              <td>${itemSnapshotField(item, "lote_snapshot", "lot") || "-"}</td>
              <td>${itemSnapshotField(item, "production_date_snapshot", "production_text") || "-"}</td>
              <td>${itemSnapshotField(item, "expiration_date_snapshot", "expiration_text") || "-"}</td>
              <td>${item.quantity ?? ""}</td>
              <td>${fumCell}</td>
              <td>${sacos}</td>
              <td>${tabletas}</td>
              <td>${fosfina}</td>
              ${plateCell}
            </tr>
          `;
            }
            if (isTottusFumigacion) {
              return `
            <tr>
              <td>${idx + 1}</td>
              <td>${shipCell}</td>
              ${productCellHtml(productName)}
              <td>${itemSnapshotField(item, "lote_snapshot", "lot") || "-"}</td>
              <td>${item.quantity ?? ""}</td>
              <td>${itemSnapshotField(item, "production_date_snapshot", "production_text") || "-"}</td>
              <td>${itemSnapshotField(item, "expiration_date_snapshot", "expiration_text") || "-"}</td>
              <td>${fumCell}</td>
              <td>${sacos}</td>
              <td>${tabletas}</td>
              <td>${fosfina}</td>
            </tr>
          `;
            }
            const lastCol = user01Layout
              ? `<td style="text-align:center; vertical-align:middle;">${instCell}</td>`
              : idx === 0
                ? `<td rowspan="${Math.max(list.length, 1)}" style="text-align:center; vertical-align:middle;">${plate}</td>`
                : "";
            return `
            <tr>
              <td>${idx + 1}</td>
              <td>${formatShippingDate(fecha)}</td>
              ${productCellHtml(productName)}
              <td>${itemSnapshotField(item, "lote_snapshot", "lot") || "-"}</td>
              <td>${item.quantity ?? ""}</td>
              <td>${itemSnapshotField(item, "production_date_snapshot", "production_text") || "-"}</td>
              <td>${itemSnapshotField(item, "expiration_date_snapshot", "expiration_text") || "-"}</td>
              <td>${fumCell}</td>
              <td>${libCell}</td>
              <td>400</td>
              <td>100</td>
              <td>1800</td>
              ${lastCol}
            </tr>
          `;
          })
          .join("");
        }
        const rows = buildFumigacionRowsHtml(items, transporte);
        const fumigacionLastHeader = isAjilesFumigacion
          ? "Placa transporte"
          : user01Layout
            ? "Fecha de Instalaciones"
            : "Unidad Transporte";
        const fumigacionColspan = isAjilesFumigacion ? 12 : isTottusFumigacion ? 11 : 13;
        const fumigacionTableHead = isAjilesFumigacion
          ? `
                    <th>Item</th>
                    <th>Fecha de Envío</th>
                    <th>Producto</th>
                    <th>Lote</th>
                    <th>Fecha de Producción</th>
                    <th>Fecha de Vencimiento</th>
                    <th>Cantidad</th>
                    <th>Fecha de Fumigación</th>
                    <th>Fumigación por sacos</th>
                    <th>Tabletas</th>
                    <th>Nivel de fosfina</th>
                    <th>${fumigacionLastHeader}</th>
          `
          : isTottusFumigacion
            ? `
                    <th>Item</th>
                    <th>Fecha de Envío</th>
                    <th>Producto</th>
                    <th>Lote</th>
                    <th>Cantidad</th>
                    <th>Fecha de Producción</th>
                    <th>Fecha de Vencimiento</th>
                    <th>Fecha de Fumigación</th>
                    <th>Cantidad de sacos</th>
                    <th>N° de tabletas</th>
                    <th>Nivel de fosfina</th>
          `
          : `
                    <th>Item</th>
                    <th>Fecha de Envío</th>
                    <th>Producto</th>
                    <th>Lote</th>
                    <th>Cant.<br>env<br>(u)</th>
                    <th>Fecha de Producción</th>
                    <th>Fecha de Vencimiento</th>
                    <th>Fecha de Fumigación</th>
                    <th>Fecha de Liberación</th>
                    <th>Cantidad Fumigada</th>
                    <th>N° de tabletas</th>
                    <th>Nivel de fosfina</th>
                    <th>${fumigacionLastHeader}</th>
          `;
        // user01: tipografía más visible, proporcional al zoom (cabeceras ≈ datos, sin salir de celda)
        const user01ItemCount = Math.max(items.length || 0, 0);
        const user01DynamicZoom = user01Layout && !isAjilesFumigacion;
        const user01ZoomCount = Math.max(user01ItemCount, 1);
        const user01AvailMm = 128;
        const user01IdealRowMm = user01AvailMm / user01ZoomCount;
        const user01MaxRowMm =
          user01ZoomCount <= 3 ? 14 : user01ZoomCount <= 6 ? 11.5 : user01ZoomCount <= 12 ? 9 : 7;
        const user01RowMm = Math.min(user01MaxRowMm, Math.max(4.2, user01IdealRowMm));
        const user01FontPx = Math.min(10.5, Math.max(7.4, user01RowMm * 0.88));
        const user01HeadPx = Math.min(10.8, Math.max(7.6, user01FontPx * 1.05));
        const user01PadPx = Math.min(2.8, Math.max(1.0, user01FontPx * 0.2));
        const user01FitStyle = user01DynamicZoom
          ? `--u01-n:${user01ZoomCount};--u01-fs:${user01FontPx.toFixed(2)}px;--u01-fs-head:${user01HeadPx.toFixed(2)}px;--u01-pad:${user01PadPx.toFixed(2)}px;--u01-row-h:${user01RowMm.toFixed(2)}mm;`
          : "";
        const wrapUser01Table = (tableHtml) =>
          user01Layout && user01DynamicZoom ? `<div class="u01-table-slot">${tableHtml}</div>` : tableHtml;
        const user01BodyClass = user01Layout
          ? `user01-wide${user01DynamicZoom ? " user01-zoom" : ""}`
          : "";
        const user01WideCss = user01Layout
          ? `
                /* user01: márgenes laterales (siempre) */
                body.user01-wide .page { padding: 6mm 4mm 8mm; }
                body.user01-wide .ajiles-quality-page { padding: 5mm 4mm 5mm; }
                body.user01-wide .data { font-size: 8.5px; }
                body.user01-wide .data th, body.user01-wide .data td { padding: 2px; }
                body.user01-wide .data.quality th, body.user01-wide .data.quality td { font-size: 8.5px; }
                body.user01-wide .box { padding: 4px; }
                body.user01-wide .meta { font-size: 9px; }
                body.user01-wide .note { font-size: 9px; }
                /* Zoom: letras más grandes, cabeceras y datos proporcionales, dentro de la celda */
                body.user01-wide.user01-zoom .page { padding: 6mm 4mm 10mm; overflow: hidden; }
                body.user01-wide.user01-zoom .box {
                  display: flex;
                  flex-direction: column;
                  min-height: 0;
                  overflow: hidden;
                }
                body.user01-wide.user01-zoom .meta,
                body.user01-wide.user01-zoom .note,
                body.user01-wide.user01-zoom .title { flex-shrink: 0; }
                body.user01-wide.user01-zoom .u01-table-slot {
                  flex: 0 1 auto;
                  min-height: 0;
                  margin-top: 2px;
                }
                body.user01-wide.user01-zoom .u01-table-slot .data:not(.ajiles-fum) {
                  width: 100%;
                  table-layout: fixed;
                  border-collapse: collapse;
                  font-size: var(--u01-fs);
                }
                body.user01-wide.user01-zoom .u01-table-slot .data:not(.ajiles-fum) thead th {
                  height: auto !important;
                  max-height: none !important;
                  padding: 2px 1px;
                  vertical-align: middle;
                  font-size: var(--u01-fs-head) !important;
                  font-weight: 400;
                  line-height: 1.12;
                  background: #fff;
                  overflow: hidden;
                }
                body.user01-wide.user01-zoom .u01-table-slot .data:not(.ajiles-fum) tbody td {
                  height: var(--u01-row-h);
                  min-height: var(--u01-row-h);
                  max-height: var(--u01-row-h);
                  padding: var(--u01-pad) 1px;
                  vertical-align: middle;
                  font-size: var(--u01-fs);
                  line-height: 1.12;
                  overflow: hidden;
                }
                body.user01-wide.user01-zoom .u01-table-slot .data.quality:not(.ajiles-fum) thead th,
                body.user01-wide.user01-zoom .u01-table-slot .data.quality:not(.ajiles-fum) tbody td {
                  font-size: var(--u01-fs) !important;
                }
                body.user01-wide.user01-zoom .u01-table-slot .data.quality:not(.ajiles-fum) thead th {
                  font-size: var(--u01-fs-head) !important;
                }
                body.user01-wide.user01-zoom .u01-table-slot .data.tottus-desinsectacion {
                  font-size: var(--u01-fs) !important;
                }
                body.user01-wide.user01-zoom .u01-table-slot .data.tottus-desinsectacion tbody td {
                  height: var(--u01-row-h);
                  min-height: var(--u01-row-h);
                  max-height: var(--u01-row-h);
                  padding: var(--u01-pad) 3px;
                  font-size: var(--u01-fs) !important;
                  line-height: 1.15;
                  overflow: hidden;
                }
                body.user01-wide.user01-zoom .u01-table-slot .data.tottus-desinsectacion .td-palets {
                  font-size: calc(var(--u01-fs) * 1.85) !important;
                  font-weight: 700;
                }
                body.user01-wide.user01-zoom .u01-org {
                  flex-shrink: 0;
                  margin-top: 6px !important;
                }
                body.user01-wide.user01-zoom .footer { flex-shrink: 0; }
              `
          : "";
        const itemQuality = (item, snapKey, legacyKey) => {
          const key = (itemSnapshotField(item, "product_name_snapshot", "product") || "").trim().toLowerCase();
          const prod = (catalog || []).find((p) => (p.name || "").trim().toLowerCase() === key);
          if (prod && legacyKey) {
            const catalogVal = prod[legacyKey];
            if (catalogVal !== undefined && catalogVal !== null && catalogVal !== "") {
              return catalogVal;
            }
          }
          if (item[snapKey] !== undefined && item[snapKey] !== null && item[snapKey] !== "") return item[snapKey];
          if (legacyKey && item[legacyKey] !== undefined && item[legacyKey] !== null && item[legacyKey] !== "") {
            return item[legacyKey];
          }
          return "";
        };
        const qualityRows = items
          .map((item, idx) => {
            return `
              <tr>
                <td>${idx + 1}</td>
                ${productCellHtml(itemSnapshotField(item, "product_name_snapshot", "product"))}
                <td>${itemSnapshotField(item, "lote_snapshot", "lot") || "-"}</td>
                <td>${item.quantity ?? ""}</td>
                <td>${itemSnapshotField(item, "production_date_snapshot", "production_text") || "-"}</td>
                <td>${itemSnapshotField(item, "expiration_date_snapshot", "expiration_text") || "-"}</td>
                <td>${itemQuality(item, "humidity_snapshot", "humidity")}</td>
                <td>${itemQuality(item, "broken_grains_snapshot", "broken_grains")}</td>
                <td>${itemQuality(item, "chalky_grains_1_snapshot", "chalky_1")}</td>
                <td>${itemQuality(item, "chalky_grains_2_snapshot", "chalky_2")}</td>
                <td>${itemQuality(item, "damaged_grains_snapshot", "damaged_grains")}</td>
                <td>${itemQuality(item, "whiteness_snapshot", "whiteness")}</td>
              </tr>
            `;
          })
          .join("");
        const fumigacionIntroHtml = isMakroFumigacion
          ? `
              <table class="meta makro-meta">
                <tbody>
                  <tr>
                    <td class="label">FECHA DE EMISION</td>
                    <td class="value">${formatEmissionDate(fecha)}</td>
                    <td class="label">RAZÓN SOCIAL:</td>
                    <td class="value">INDUAMERICA INTERNACIONAL S.A.C</td>
                  </tr>
                  <tr>
                    <td class="label">PRODUCTO:</td>
                    <td class="value">ARROZ ELABORADO</td>
                    <td class="label">RUC:</td>
                    <td class="value">20602740278</td>
                  </tr>
                  <tr>
                    <td class="value" colspan="4" style="text-align:center;">
                      Mediante el presente documento dejamos constancia que los lotes producidos detallados han sido tratados
                      con fosfuro de aluminio (PHOSFIN) en nuestro almacén principal en dosis de 4 a 5 tab/m3.
                    </td>
                  </tr>
                  <tr>
                    <td class="label">Plaguicida Usado:</td>
                    <td class="value" colspan="3">Fosfuro de Aluminio (PHOSFIN)</td>
                  </tr>
                  <tr>
                    <td class="value makro-client-block" colspan="4">
                      <div>MAKRO SUPERMAYORISTA S.A</div>
                      <div>${cliente || ""}</div>
                      ${clientRuc ? `<div>RUC: ${clientRuc}</div>` : ""}
                    </td>
                  </tr>
                </tbody>
              </table>
            `
          : isTottusFumigacion
            ? `
              <table class="meta tottus-meta">
                <tbody>
                  <tr>
                    <td class="label">FECHA DE EMISIÓN</td>
                    <td class="value">${formatEmissionDate(fecha)}</td>
                  </tr>
                  <tr>
                    <td class="label">CLIENTE</td>
                    <td class="value">${cliente || ""}</td>
                  </tr>
                </tbody>
              </table>
              <div class="note">
                Mediante el presente documento dejamos constancia que los lotes de arroz pilado, detallados han sido tratados con fosfuro de aluminio (PHOSFIN) en nuestro almacén principal, en dosis de 5 tab/ton.
              </div>
              <table class="meta tottus-pest">
                <tbody>
                  <tr>
                    <td class="label">Plaguicida Usado:</td>
                    <td class="value">FOSFURO DE ALUMINIO (PHOSFIN)</td>
                    <td class="label">Proveedor:</td>
                    <td class="value">INDUAMERICA INTERNACIONAL S.A.C.</td>
                  </tr>
                </tbody>
              </table>
            `
          : `
              <table class="meta quality-meta">
                <tbody>
                  <tr>
                    <td class="label">FECHA DE EMISIÓN</td>
                    <td class="value">${formatEmissionDate(fecha)}</td>
                  </tr>
                  <tr>
                    <td class="label">CLIENTE</td>
                    <td class="value">${cliente}${clientRucLine}</td>
                  </tr>
                </tbody>
              </table>
              <div class="note">
                Mediante el presente documento dejamos constancia que los lotes de arroz pilado, detallados han sido tratados con Fosfuro de Aluminio (PHOSFIN) en nuestro almacén principal, en dosis de 5 tab/ton.
              </div>
            `;
        const pageContent = `
          <div class="page first-page">
            <div class="header">
              <img class="logo" src="/static/logo.png" alt="Induamerica" />
            </div>
            <div class="box">
              <div class="title">CONSTANCIA DE FUMIGACIÓN N° ${numero}</div>
              ${fumigacionIntroHtml}
              ${wrapUser01Table(`
              <table class="data${isAjilesFumigacion ? " ajiles-fum" : ""}${isMakroFumigacion ? " makro-fum" : ""}${isTottusFumigacion ? " tottus-fum" : ""}">
                <thead>
                  <tr>
                    ${fumigacionTableHead}
                  </tr>
                </thead>
                <tbody>
                  ${rows || `<tr><td colspan='${fumigacionColspan}' class='empty'>Sin productos</td></tr>`}
                </tbody>
              </table>
              `)}
            </div>
            <div class="footer">
              <div class="firma-wrap">
                <img class="firma" src="${getConstanciaFirmaSrc()}" alt="Firma" />
              </div>
              <div class="footer-text">
                <div>Av. Camino Real N° 931 Dpto. 201 San Isidro - Lima.</div>
                <div class="email">induamerica@induamerica.com.pe</div>
              </div>
            </div>
          </div>
        `;
        const isAjilesQuality = isAjilesPeruClient(cliente);
        const isTottusDesinsectacion =
          user01Layout && isTottusStyleConstanciaClient(cliente) && !isAjilesQuality;
        const pageQualityStandard = `
          <div class="page last-page">
            <div class="header">
              <img class="logo" src="/static/logo.png" alt="Induamerica" />
            </div>
            <div class="box">
              <div class="title">CONSTANCIA DE CALIDAD N° ${numero}</div>
              <table class="meta">
                <tbody>
                  <tr>
                    <td class="label">FECHA DE EMISION</td>
                    <td class="value">${formatEmissionDate(fecha)}</td>
                    <td class="label">RAZON SOCIAL</td>
                    <td class="value">INDUAMERICA INTERNACIONAL S.A.C</td>
                  </tr>
                  <tr>
                    <td class="label">PRODUCTOS</td>
                    <td class="value">VARIOS</td>
                    <td class="label">RUC</td>
                    <td class="value">20602740278</td>
                  </tr>
                  <tr>
                    <td class="value" colspan="4" style="text-align:center;">
                      El área de control de calidad de la Empresa Induamerica Internacional S.A.C., da constancia que el producto con denominación
                    </td>
                  </tr>
                  <tr>
                    <td class="value" colspan="4" style="text-align:center;">
                      Cumple con las especificaciones de calidad de acuerdo a la Ficha Técnica, por lo que garantiza la conformidad del producto entregado a :
                    </td>
                  </tr>
                  <tr>
                    <td class="value" colspan="4" style="text-align:center; font-weight:600;">${cliente}</td>
                  </tr>
                  ${
                    clientRuc
                      ? `<tr><td class="value" colspan="4" style="text-align:center;">RUC: ${clientRuc}</td></tr>`
                      : ""
                  }
                </tbody>
              </table>
              ${wrapUser01Table(`
              <table class="data quality">
                <thead>
                  <tr>
                    <th rowspan="2">Item</th>
                    <th rowspan="2">Presentación</th>
                    <th rowspan="2">${user01Layout && isMakroClient(cliente) ? "Lote" : "Código lote"}</th>
                    <th rowspan="2">Cantidad (Unid)</th>
                    <th rowspan="2">Fecha de Producción</th>
                    <th rowspan="2">Fecha de Vencimiento</th>
                    <th rowspan="2">%H</th>
                    <th rowspan="2">Granos<br>Quebrados<br>(%)</th>
                    <th colspan="2">Granos Tizosos (%)</th>
                    <th rowspan="2">Granos Dañados<br>(%)</th>
                    <th rowspan="2">° Blancura</th>
                  </tr>
                  <tr>
                    <th>Tizosos Totales (%)</th>
                    <th>Tizosos Parciales (%)</th>
                  </tr>
                </thead>
                <tbody>
                  ${qualityRows || "<tr><td colspan='12' class='empty'>Sin productos</td></tr>"}
                </tbody>
              </table>
              `)}
              <table class="meta ${user01Layout ? "u01-org" : ""}" style="margin-top:8px; table-layout: fixed;">
                <tbody>
                  <tr>
                    <td class="value" rowspan="3" style="width:55%;"></td>
                    <td class="label" colspan="3" style="width:45%; text-align:center;">Características Organolépticas</td>
                  </tr>
                  <tr>
                    <td class="label">Sabores y Olores</td>
                    <td class="label">Color</td>
                    <td class="label">Grado de Lustre</td>
                  </tr>
                  <tr>
                    <td class="value">Exento de sabores y olores extraños.</td>
                    <td class="value">Ligeramente cremoso</td>
                    <td class="value">Bien pulido</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div class="footer">
              <div class="firma-wrap">
                <img class="firma" src="${getConstanciaFirmaSrc()}" alt="Firma" />
              </div>
              <div class="footer-text">
                <div>Av. Camino Real N° 931 Dpto. 201 San Isidro - Lima.</div>
                <div class="email">induamerica@induamerica.com.pe</div>
              </div>
            </div>
          </div>
        `;
        const pageQuality = isTottusDesinsectacion
          ? buildTottusDesinsectacionPage(constancia, items, fecha, numero, cliente, transporte, {
              enableUser01Zoom: user01DynamicZoom,
            })
          : isAjilesQuality
            ? buildAjilesQualityPage(constancia, clientMatch, items, fecha)
            : pageQualityStandard;
        const showTransport = isCencosudCdLimaClient(cliente, clientMatch);
        const pageTransport = showTransport
          ? buildCencosudTransportPage(constancia, items, fecha, numero, cliente, transporte)
          : "";
        const dualPayload = constancia.cencosud_dual;
        const hasDualPayload =
          dualPayload &&
          typeof dualPayload === "object" &&
          (dualPayload.internacional || dualPayload.comercial);
        const isCencosudDualPdf =
          isCencosudCdPrincipalClient(cliente) &&
          isTottusStyleConstanciaClient(cliente) &&
          !isAjilesFumigacion &&
          !isAjilesQuality &&
          (previewSide || hasDualPayload) &&
          (user01Layout || previewSide || hasDualPayload);
        let pageList;
        if (isCencosudDualPdf) {
          const dual = constancia.cencosud_dual || {};
          const intl = dual.internacional || {};
          const com = dual.comercial || {};
          const bumpNumber = (value) => {
            const s = String(value || "").trim();
            const match = s.match(/^(.*?)(\d+)(\D*)$/);
            if (!match) return s;
            return `${match[1]}${String(parseInt(match[2], 10) + 1).padStart(match[2].length, "0")}${match[3]}`;
          };
          const dualBlocks = [
            {
              side: "internacional",
              number: intl.number || numero,
              fecha: intl.issue_date || fecha,
              cliente: intl.client_name || cliente,
              transporte: intl.transport_plate || transporte,
              mobile_number: intl.mobile_number || constancia.mobile_number || constancia.mobile || "",
              pallets: intl.pallets || constancia.pallets || constancia.palets || "",
              issuer: "INDUAMERICA INTERNACIONAL S.A.C.",
              items: Array.isArray(intl.items) && intl.items.length ? intl.items : items,
            },
            {
              side: "comercial",
              number: com.number || bumpNumber(intl.number || numero),
              fecha: com.issue_date || fecha,
              cliente: com.client_name || cliente,
              transporte: com.transport_plate || transporte,
              mobile_number: com.mobile_number || constancia.mobile_number || constancia.mobile || "",
              pallets: com.pallets || constancia.pallets || constancia.palets || "",
              issuer: "INDUAMERICA COMERCIAL S.A.C.",
              items: Array.isArray(com.items) && com.items.length ? com.items : items,
            },
          ];
          const blocksToRender = previewSide
            ? dualBlocks.filter((block) => block.side === previewSide)
            : dualBlocks;
          pageList = [];
          blocksToRender.forEach((block) => {
            const blockItems = block.items || items;
            const blockRows = buildFumigacionRowsHtml(blockItems, block.transporte);
            if (showFumigacion) {
              pageList.push(
                buildTottusFumigacionPage({
                  numero: block.number,
                  fecha: block.fecha,
                  cliente: block.cliente,
                  issuerCompany: block.issuer,
                  tableHeadHtml: fumigacionTableHead,
                  rowsHtml: blockRows,
                  colspan: fumigacionColspan,
                  wrapTable: wrapUser01Table,
                })
              );
            }
            if (showCalidad) {
              pageList.push(
                buildTottusDesinsectacionPage(
                  {
                    mobile_number: block.mobile_number,
                    pallets: block.pallets,
                  },
                  blockItems,
                  block.fecha,
                  block.number,
                  block.cliente,
                  block.transporte,
                  {
                    enableUser01Zoom: user01DynamicZoom,
                    issuerCompany: block.issuer,
                  }
                )
              );
            }
          });
        } else {
          pageList = [showFumigacion ? pageContent : "", showCalidad ? pageQuality : "", showTransport ? pageTransport : ""].filter(
            (page) => page
          );
        }
        const selectedPages = applyConstanciaPageBreaks(pageList);
        const emptyMessage = `
          <div style="font-family: Arial, sans-serif; padding: 16px;">
            No hay constancias seleccionadas para mostrar.
          </div>
        `;
        const html2pdfScript =
          '<scr' +
          'ipt src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></scr' +
          'ipt>' +
          '<scr' +
          'ipt src="https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js"></scr' +
          'ipt>';
        const inlineScript =
          '<scr' +
          'ipt>' +
          `const pdfName = ${JSON.stringify(fileName || `Constancia ${numero}`)};
function fitSingleLineCells(){
  document.querySelectorAll("td.cell-fit-line").forEach((td)=>{
    td.style.whiteSpace="nowrap";
    td.style.overflow="hidden";
    td.style.wordBreak="normal";
    let size=parseFloat(window.getComputedStyle(td).fontSize)||10;
    td.style.fontSize=size+"px";
    let guard=0;
    while(td.scrollWidth>td.clientWidth+0.5 && size>5.5 && guard++<80){
      size-=0.2;
      td.style.fontSize=size+"px";
    }
  });
}
function printDoc(){fitSingleLineCells();window.print();}
async function savePdf(){
  fitSingleLineCells();
  const pages = Array.from(document.querySelectorAll(".page"));
  if (!pages.length || !window.html2canvas || !window.jspdf) return;
  document.body.classList.add("pdf-export");
  const pdf = new window.jspdf.jsPDF({ unit: "mm", format: "a4", orientation: "portrait" });
  for (let i = 0; i < pages.length; i += 1) {
    const canvas = await window.html2canvas(pages[i], { scale: 2, useCORS: true });
    const imgData = canvas.toDataURL("image/jpeg", 0.98);
    if (i > 0) pdf.addPage();
    pdf.addImage(imgData, "JPEG", 0, 0, 210, 297);
  }
  pdf.save(pdfName + ".pdf");
  document.body.classList.remove("pdf-export");
}
document.addEventListener("DOMContentLoaded",()=>{fitSingleLineCells();setTimeout(fitSingleLineCells,80);});` +
          '</scr' +
          'ipt>';
        const previewOrigin =
          typeof window !== "undefined" && window.location?.origin ? window.location.origin : "";
        return `
          <html>
            <head>
              ${previewOrigin ? `<base href="${previewOrigin}/">` : ""}
              <title>${fileName || `Constancia ${numero}`}</title>
              <style>
                body { margin: 0; background: #e5e7eb; font-family: "Segoe UI", Arial, sans-serif; }
                .actions { position: sticky; top: 0; background: #e5e7eb; padding: 10px 16px; display: flex; justify-content: flex-end; gap: 8px; z-index: 2; }
                .btn { background: #2563eb; color: #fff; border: none; border-radius: 8px; padding: 8px 14px; cursor: pointer; font-size: 12px; }
                .page { width: 210mm; height: 297mm; background: #fff; margin: 16px auto; padding: 10mm 12mm 18mm; box-sizing: border-box; box-shadow: 0 10px 30px rgba(15,23,42,0.12); display: flex; flex-direction: column; page-break-inside: avoid; }
                .first-page { page-break-after: always; }
                .last-page { page-break-after: auto; }
                .pdf-export .page { margin: 0; box-shadow: none; }
                .pdf-export @page { margin: 0; }
                .header { height: 30mm; display: flex; align-items: center; justify-content: flex-start; }
                .logo { max-height: 30mm; max-width: 100%; object-fit: contain; }
                .box { border: 1px solid #111827; padding: 6px; box-sizing: border-box; flex: 1; }
                .title { text-align: center; font-weight: 700; font-size: 12px; padding: 2px 0; }
                .meta { width: 100%; border-collapse: collapse; font-size: 10px; }
                .meta td { border: 1px solid #111827; padding: 4px; text-align: center; }
                .meta .label { font-weight: 600; }
                .quality-meta { table-layout: fixed; }
                .quality-meta td { width: 25%; }
                .quality-meta td.value { white-space: normal; }
                .note { border: 1px solid #111827; border-top: none; padding: 4px; font-size: 10px; text-align: center; }
                .makro-meta { table-layout: fixed; margin-bottom: 0; }
                .makro-meta td { width: 25%; }
                .makro-meta .makro-client-block {
                  text-align: center;
                  font-weight: 700;
                  line-height: 1.35;
                  padding: 6px 4px;
                }
                .data.makro-fum { margin-top: 4px; }
                .tottus-meta { table-layout: fixed; }
                .tottus-meta td.label { width: 28%; }
                .tottus-meta td.value { width: 72%; }
                .tottus-pest { table-layout: fixed; margin-top: 0; border-top: none; }
                .tottus-pest td { width: 25%; }
                .data.tottus-fum { margin-top: 4px; }
                .data.tottus-fum th:nth-child(1) { width: 4%; }
                .data.tottus-fum th:nth-child(2) { width: 8%; }
                .data.tottus-fum th:nth-child(3) { width: 28%; }
                .data.tottus-fum th:nth-child(4) { width: 8%; }
                .data.tottus-fum th:nth-child(5) { width: 7%; }
                .data.tottus-fum th:nth-child(6) { width: 9%; }
                .data.tottus-fum th:nth-child(7) { width: 9%; }
                .data.tottus-fum th:nth-child(8) { width: 9%; }
                .data.tottus-fum th:nth-child(9) { width: 7%; }
                .data.tottus-fum th:nth-child(10) { width: 6%; }
                .data.tottus-fum th:nth-child(11) { width: 5%; }
                .data { width: 100%; border-collapse: collapse; font-size: 8px; table-layout: fixed; }
                .data th, .data td { border: 1px solid #111827; padding: 3px; word-break: break-word; }
                .data th { text-align: center; font-weight: 400; }
                .data td { text-align: center; }
                .data td.cell-fit-line {
                  white-space: nowrap !important;
                  overflow: hidden !important;
                  word-break: normal !important;
                  text-overflow: clip;
                }
                .data td:nth-child(3) { text-align: center; }
                .data th:nth-child(1) { width: 3%; }
                .data th:nth-child(2) { width: 6%; }
                .data th:nth-child(3) { width: 30%; }
                .data th:nth-child(4) { width: 7%; }
                .data th:nth-child(5) { width: 5%; }
                .data th:nth-child(6) { width: 8%; }
                .data th:nth-child(7) { width: 8%; }
                .data th:nth-child(8) { width: 6%; }
                .data th:nth-child(9) { width: 6%; }
                .data th:nth-child(10) { width: 5%; }
                .data th:nth-child(11) { width: 5%; }
                .data th:nth-child(12) { width: 5%; }
                .data th:nth-child(13) { width: 7%; }
                /* Ajiles fumigación: más ancho en F. Producción / F. Vencimiento */
                .data.ajiles-fum th:nth-child(1) { width: 3%; }
                .data.ajiles-fum th:nth-child(2) { width: 7%; }
                .data.ajiles-fum th:nth-child(3) { width: 22%; }
                .data.ajiles-fum th:nth-child(4) { width: 7%; }
                .data.ajiles-fum th:nth-child(5) { width: 10%; }
                .data.ajiles-fum th:nth-child(6) { width: 10%; }
                .data.ajiles-fum th:nth-child(7) { width: 6%; }
                .data.ajiles-fum th:nth-child(8) { width: 8%; }
                .data.ajiles-fum th:nth-child(9) { width: 7%; }
                .data.ajiles-fum th:nth-child(10) { width: 6%; }
                .data.ajiles-fum th:nth-child(11) { width: 7%; }
                .data.ajiles-fum th:nth-child(12) { width: 7%; }
                .data.ajiles-fum td:nth-child(5),
                .data.ajiles-fum td:nth-child(6) {
                  white-space: nowrap;
                  word-break: normal;
                  overflow: hidden;
                }
                .data.quality th, .data.quality td { font-size: 8px; }
                .data.quality th:nth-child(1) { width: 4%; }
                .data.quality th:nth-child(2) { width: 26%; }
                .data.quality th:nth-child(3) { width: 8%; }
                .data.quality th:nth-child(4) { width: 6%; }
                .data.quality th:nth-child(5) { width: 8%; }
                .data.quality th:nth-child(6) { width: 8%; }
                .data.quality th:nth-child(7) { width: 5%; }
                .data.quality th:nth-child(8) { width: 6.5%; }
                .data.quality th:nth-child(9) { width: 7.5%; }
                .data.quality th:nth-child(10) { width: 7.5%; }
                .data.quality th:nth-child(11) { width: 6%; }
                .data.quality th:nth-child(12) { width: 6%; }
                .empty { text-align: center; padding: 6px; }
                .footer { display: flex; justify-content: space-between; align-items: flex-end; margin-top: 4px; gap: 12px; }
                .firma-wrap { width: 55%; min-height: 104px; display: flex; align-items: flex-end; }
                .firma { max-height: 104px; max-width: 100%; object-fit: contain; }
                .footer-text { width: 45%; font-size: 10px; text-align: right; line-height: 1.3; }
                .footer-text .email { color: #2563eb; text-decoration: underline; }
                .ajiles-quality-page { padding: 9mm 11mm 7mm; font-family: Arial, Helvetica, sans-serif; color: #000; box-sizing: border-box; height: 297mm; overflow: hidden; }
                .ajiles-body { display: flex; flex-direction: column; height: 100%; min-height: 100%; }
                .ajiles-main { flex: 0 0 auto; }
                .ajiles-bottom { margin-top: auto; flex-shrink: 0; width: 100%; }
                .ajiles-sheet { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 7pt; line-height: 1.15; margin: 0; flex-shrink: 0; }
                .ajiles-sheet + .ajiles-sheet { margin-top: -1px; }
                .ajiles-bottom .ajiles-sheet { margin-top: 6px; }
                .ajiles-sheet td, .ajiles-sheet th { border: 1px solid #000; padding: 2px 4px; vertical-align: middle; }
                .aj-bar { background: #f67116; text-align: center; font-weight: 700; font-size: 7pt; padding: 3px 2px; color: #000; }
                .aj-bar-merged { vertical-align: middle; }
                .aj-col-logo { width: 22%; }
                .aj-col-title { width: 52%; }
                .aj-col-meta { width: 26%; }
                .aj-col-prov-val { width: 78%; }
                .ajiles-head td { padding: 0 !important; vertical-align: middle; line-height: 1; }
                .aj-h td { padding: 0 !important; vertical-align: middle; line-height: 1; }
                .aj-logo-cell { line-height: 0; font-size: 0; background: #f67116; overflow: hidden; }
                .aj-logo { display: block; width: 100%; height: auto; margin: 0; aspect-ratio: 337 / 223; object-fit: fill; vertical-align: top; }
                .aj-title-cell { text-align: center; font-weight: 800; font-size: 5.25pt; padding: 0 3px !important; line-height: 1.05; letter-spacing: -0.02em; }
                .aj-title-cell strong { font-weight: 800; }
                .aj-meta-cell { vertical-align: top; overflow: hidden; position: relative; padding: 0 !important; }
                .aj-meta-wrap { position: absolute; inset: 0; }
                .aj-meta-inner { width: 100%; height: 100%; border-collapse: collapse; table-layout: fixed; font-size: 5.5pt; }
                .aj-meta-inner tr { height: 25%; }
                .aj-meta-inner td { border: 1px solid #000; padding: 0 3px; text-align: left; line-height: 1.05; vertical-align: middle; }
                .aj-meta-inner tr:first-child td { border-top: none; }
                .aj-meta-inner td:last-child { border-right: none; text-align: center; }
                .aj-meta-inner .aj-meta-l { font-weight: 700; width: 46%; }
                .ajiles-provider .aj-prov-lbl { font-weight: 700; text-align: left; padding-left: 6px !important; font-size: 6.5pt; background: #fff; }
                .ajiles-provider .aj-prov-val { text-align: left; padding-left: 6px !important; font-size: 7pt; background: #fff; }
                .ajiles-products th, .ajiles-products td { font-size: 6.5pt; background: #fff; }
                .ajiles-products .aj-bar { background: #f67116; }
                .ajiles-products tbody td { height: 15px; }
                .aj-head-row th { font-weight: 700; text-align: center; background: #fff; font-size: 6.5pt; }
                .aj-c { text-align: center; }
                .aj-desc { padding-left: 2px !important; padding-right: 2px !important; }
                .aj-empty-row { font-style: italic; }
                .aj-lbl { width: 25%; font-weight: 700; text-align: center; background: #fff; font-size: 6.5pt; }
                .aj-val { width: 25%; text-align: center; background: #fff; font-size: 7pt; }
                .aj-check-lbl { width: 34%; font-weight: 700; text-align: left; font-size: 6.5pt; padding-left: 6px !important; }
                .aj-check-opt { width: 33%; text-align: left; font-size: 6.5pt; padding-left: 6px !important; }
                .ajiles-checks td { background: #fff; }
                .aj-obs-cell { height: 100px; min-height: 100px; vertical-align: top !important; padding: 3px 6px 4px 6px !important; background: #fff; text-align: left; }
                .aj-obs-title { display: block; font-weight: 700; font-size: 7pt; margin: 0; padding: 0; line-height: 1.1; }
                .aj-obs-note { font-size: 6pt; margin: 2px 0 0; flex-shrink: 0; }
                .aj-sign-row { display: flex; gap: 0; margin: 4px 0 6px; flex-shrink: 0; }
                .aj-sign-col { flex: 1; padding: 0 10px; position: relative; }
                .aj-sign-img-wrap { min-height: 72px; display: flex; align-items: flex-end; justify-content: center; padding: 0 12px 2px 28px; }
                .aj-firma { max-height: 82px; max-width: 280px; width: auto; object-fit: contain; }
                .aj-sign-spacer { min-height: 72px; }
                .aj-sign-line { border-bottom: 1px solid #000; margin: 0 6px 3px; }
                .aj-sign-lbl { font-weight: 700; font-size: 6.5pt; text-align: center; padding-top: 2px; }
                .aj-temp-table { flex-shrink: 0; margin-top: 0; }
                .aj-temp-cell { padding: 3px 5px !important; font-size: 6pt; line-height: 1.25; vertical-align: top; background: #fff; }
                .aj-temp-title { font-weight: 700; margin-bottom: 1px; font-size: 6.5pt; }
                .aj-temp-line { margin-bottom: 0; }
                .aj-footer { padding-top: 4px; text-align: right; font-size: 6.5pt; line-height: 1.3; flex-shrink: 0; }
                .aj-email { color: #2563eb; text-decoration: underline; }
                .ct-meta { table-layout: fixed; }
                .ct-meta .label { width: 28%; text-align: left; padding-left: 6px; }
                .ct-meta .value { text-align: center; }
                .ct-note { font-size: 9px; line-height: 1.25; text-align: center; padding: 6px 8px; }
                .ct-pest { table-layout: fixed; margin-top: 0; }
                .ct-pest .label { width: 18%; text-align: left; padding-left: 6px; }
                .ct-pest .value { text-align: center; }
                .ct-pest .ct-proveedor { font-weight: 700; }
                .data.ct-transport { table-layout: fixed; width: 100%; border-collapse: collapse; }
                .data.ct-transport th,
                .data.ct-transport td {
                  font-size: 7.5px;
                  padding: 2px 2px;
                  word-break: normal;
                  overflow: hidden;
                  vertical-align: middle;
                  text-align: center;
                }
                .data.ct-transport .ct-col-item { width: 3%; white-space: nowrap; padding: 2px 0; }
                .data.ct-transport .ct-col-fecha { width: 9%; white-space: nowrap; font-size: 7px; }
                .data.ct-transport .ct-col-placa { width: 7%; white-space: nowrap; font-size: 7px; }
                .data.ct-transport .ct-col-cant { width: 9%; white-space: nowrap; padding: 2px 0; font-size: 7px; }
                .data.ct-transport .ct-col-empresa {
                  width: 16%;
                  font-size: 6.5px;
                  line-height: 1.15;
                  white-space: normal;
                  word-break: break-word;
                  hyphens: auto;
                }
                .data.ct-transport th.ct-col-empresa { font-size: 6px; line-height: 1.1; }
                .data.ct-transport .ct-col-producto {
                  width: 56%;
                  white-space: nowrap;
                  font-size: 7px;
                  letter-spacing: -0.03em;
                  text-align: center;
                  overflow: hidden;
                  text-overflow: clip;
                }
                .data.ct-transport th.ct-col-item,
                .data.ct-transport td.ct-col-item { width: 3% !important; max-width: 3% !important; }
                .data.ct-transport th.ct-col-fecha,
                .data.ct-transport td.ct-col-fecha { width: 9% !important; max-width: 9% !important; }
                .data.ct-transport th.ct-col-empresa,
                .data.ct-transport td.ct-col-empresa { width: 16% !important; max-width: 16% !important; }
                .data.ct-transport th.ct-col-placa,
                .data.ct-transport td.ct-col-placa { width: 7% !important; max-width: 7% !important; }
                .data.ct-transport th.ct-col-producto,
                .data.ct-transport td.ct-col-producto { width: 56% !important; max-width: 56% !important; }
                .data.ct-transport th.ct-col-cant,
                .data.ct-transport td.ct-col-cant { width: 9% !important; max-width: 9% !important; }
                .data.tottus-desinsectacion {
                  table-layout: fixed;
                  width: 100%;
                  border-collapse: collapse;
                  margin-top: 6px;
                  font-size: 10px;
                }
                .data.tottus-desinsectacion td {
                  border: 1px solid #111827;
                  padding: 4px 3px;
                  text-align: center;
                  vertical-align: middle;
                }
                .data.tottus-desinsectacion .td-producto {
                  text-align: left;
                  padding-left: 6px;
                  white-space: nowrap !important;
                  overflow: hidden !important;
                  word-break: normal !important;
                }
                .data.tottus-desinsectacion .td-palets {
                  font-size: 18px;
                  font-weight: 700;
                }
                .data.tottus-desinsectacion .td-mobile {
                  font-weight: 600;
                }
                .data.tottus-desinsectacion .td-empresa {
                  width: 12%;
                  max-width: 12%;
                  line-height: 1.15;
                  font-size: 0.92em;
                  white-space: normal;
                  word-break: normal;
                  padding-left: 2px;
                  padding-right: 2px;
                }
                @media print {
                  body { background: #fff; }
                  .actions { display: none; }
                  .page { margin: 0; box-shadow: none; }
                }
                ${user01WideCss}
              </style>
            </head>
            <body class="${user01BodyClass}" style="${user01FitStyle}">
              <div class="actions">
                <button class="btn" onclick="printDoc()">Imprimir</button>
                <button class="btn" onclick="savePdf()">Guardar PDF</button>
              </div>
              <div id="doc">
                ${selectedPages || emptyMessage}
              </div>
              ${html2pdfScript}
              ${inlineScript}
            </body>
          </html>
        `;
      }
      globalThis.buildConstanciaHtml = buildConstanciaHtml;
      globalThis.isCencosudCdLimaClient = isCencosudCdLimaClient;

})();
