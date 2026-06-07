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

function parseConstanciaDate(dateText) {
        const value = (dateText || "").trim();
        if (!value) return null;
        let match = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
        if (match) {
          return {
            day: parseInt(match[3], 10),
            month: parseInt(match[2], 10),
            year: parseInt(match[1], 10),
          };
        }
        match = value.match(/^(\d{1,2})\s*\/\s*(\d{1,2})\s*\/\s*(\d{4})$/);
        if (match) {
          return {
            day: parseInt(match[1], 10),
            month: parseInt(match[2], 10),
            year: parseInt(match[3], 10),
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
        const parts = (dateText || "").split("/").map((p) => p.trim());
        const hasParts = parts.length === 3 && parts.every((p) => p.length >= 1);
        let baseDate = new Date();
        if (hasParts) {
          const [dd, mm, yyyy] = parts.map((p) => parseInt(p, 10));
          if (!Number.isNaN(dd) && !Number.isNaN(mm) && !Number.isNaN(yyyy)) {
            baseDate = new Date(yyyy, mm - 1, dd);
          }
        }
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

      const AJILES_PERU_SKU_MAP = [
        { patterns: ["ARROZ EXTRA GRAN CHALAN X 5KG", "GRAN CHALAN X 5KG"], sku: "13010200100586" },
        { patterns: ["DON CHEF ARROZ SUPERIOR BL 4KG", "ARROZ SUPERIOR BL 4KG"], sku: "130102003001" },
        { patterns: ["DON CHEF ARROZ EXTRA BL 650GR", "ARROZ EXTRA BL 650GR", "ARROZ EXTRA BL 650 GR"], sku: "130102003002" },
        { patterns: ["MI ARROZ SUPERIOR NIR X 25 KG", "ARROZ SUPERIOR NIR X 25 KG"], sku: "130102003003" },
      ];

      function isAjilesPeruClient(clientName) {
        const key = normalizeSearchText(clientName);
        return key.includes("ajiles") && key.includes("peru");
      }

      function resolveAjilesSku(productName) {
        const key = normalizeSearchText(productName);
        if (!key) return "";
        for (const entry of AJILES_PERU_SKU_MAP) {
          for (const pattern of entry.patterns) {
            const normalizedPattern = normalizeSearchText(pattern);
            if (key === normalizedPattern || key.includes(normalizedPattern) || normalizedPattern.includes(key)) {
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
                    <img class="aj-firma" src="/static/firma.png" alt="Firma" />
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
              <td>1</td>
              <td>${envio}</td>
              <td rowspan="1">${empresa}</td>
              <td rowspan="1">${transporte || ""}</td>
              <td></td>
              <td></td>
            </tr>
          `;
        }
        return items
          .map((item, idx) => {
            const productName = itemSnapshotField(item, "product_name_snapshot", "product");
            const mergedCells =
              idx === 0
                ? `<td rowspan="${rowCount}">${empresa}</td><td rowspan="${rowCount}">${transporte || ""}</td>`
                : "";
            return `
            <tr>
              <td>${idx + 1}</td>
              <td>${envio}</td>
              ${mergedCells}
              <td>${productName}</td>
              <td>${item.quantity ?? ""}</td>
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
                <thead>
                  <tr>
                    <th colspan="6">TRANSPORTE</th>
                  </tr>
                  <tr>
                    <th>Item</th>
                    <th>Fecha de Envio</th>
                    <th>EMPRESA DE TRANSPORTE</th>
                    <th>Nº DE PLACA</th>
                    <th>PRODUCTO</th>
                    <th>Cantidad (Und)</th>
                  </tr>
                </thead>
                <tbody>
                  ${transportRows}
                </tbody>
              </table>
            </div>
            <div class="footer">
              <div class="firma-wrap">
                <img class="firma" src="/static/firma.png" alt="Firma" />
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

      function buildConstanciaHtml(constancia, catalog, clients = null) {
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
        const fileName = `${fileDate} ${safeCliente}`.trim();
        const transporte = constancia.transport_plate || "";
        const fumigacion = formatDateMinusDays(fecha, 9);
        const liberacion = formatDateMinusDays(fecha, 2);
        const showFumigacion = constancia.fumigacion !== 0 && constancia.fumigacion !== false;
        const showCalidad = constancia.calidad !== 0 && constancia.calidad !== false;
        const items = constancia.items || [];
        const rows = items
          .map((item, idx) => `
            <tr>
              <td>${idx + 1}</td>
              <td>${formatShippingDate(fecha)}</td>
              <td>${itemSnapshotField(item, "product_name_snapshot", "product")}</td>
              <td>${itemSnapshotField(item, "lote_snapshot", "lot") || "-"}</td>
              <td>${item.quantity ?? ""}</td>
              <td>${itemSnapshotField(item, "production_date_snapshot", "production_text") || "-"}</td>
              <td>${itemSnapshotField(item, "expiration_date_snapshot", "expiration_text") || "-"}</td>
            <td>${formatShortDate(fumigacion)}</td>
            <td>${formatShortDate(liberacion)}</td>
              <td>400</td>
              <td>100</td>
              <td>1800</td>
              ${
                idx === 0
                  ? `<td rowspan="${Math.max(items.length, 1)}" style="text-align:center; vertical-align:middle;">${transporte}</td>`
                  : ""
              }
            </tr>
          `)
          .join("");
        const itemQuality = (item, snapKey, legacyKey) => {
          if (item[snapKey] !== undefined && item[snapKey] !== null && item[snapKey] !== "") return item[snapKey];
          if (legacyKey && item[legacyKey] !== undefined && item[legacyKey] !== null && item[legacyKey] !== "") {
            return item[legacyKey];
          }
          const key = (itemSnapshotField(item, "product_name_snapshot", "product") || "").trim().toLowerCase();
          const prod = (catalog || []).find((p) => (p.name || "").trim().toLowerCase() === key);
          if (prod && legacyKey && prod[legacyKey] !== undefined) return prod[legacyKey];
          return "";
        };
        const qualityRows = items
          .map((item, idx) => {
            return `
              <tr>
                <td>${idx + 1}</td>
                <td>${itemSnapshotField(item, "product_name_snapshot", "product")}</td>
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
        const pageContent = `
          <div class="page first-page">
            <div class="header">
              <img class="logo" src="/static/logo.png" alt="Induamerica" />
            </div>
            <div class="box">
              <div class="title">CONSTANCIA DE FUMIGACIÓN N° ${numero}</div>
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
              <table class="data">
                <thead>
                  <tr>
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
                    <th>Unidad Transporte</th>
                  </tr>
                </thead>
                <tbody>
                  ${rows || "<tr><td colspan='13' class='empty'>Sin productos</td></tr>"}
                </tbody>
              </table>
            </div>
            <div class="footer">
              <div class="firma-wrap">
                <img class="firma" src="/static/firma.png" alt="Firma" />
              </div>
              <div class="footer-text">
                <div>Av. Camino Real N° 931 Dpto. 201 San Isidro - Lima.</div>
                <div class="email">induamerica@induamerica.com.pe</div>
              </div>
            </div>
          </div>
        `;
        const isAjilesQuality = isAjilesPeruClient(cliente);
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
              <table class="data quality">
                <thead>
                  <tr>
                    <th rowspan="2">Item</th>
                    <th rowspan="2">Presentación</th>
                    <th rowspan="2">Código lote</th>
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
              <table class="meta" style="margin-top:8px; table-layout: fixed;">
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
                <img class="firma" src="/static/firma.png" alt="Firma" />
              </div>
              <div class="footer-text">
                <div>Av. Camino Real N° 931 Dpto. 201 San Isidro - Lima.</div>
                <div class="email">induamerica@induamerica.com.pe</div>
              </div>
            </div>
          </div>
        `;
        const pageQuality = isAjilesQuality
          ? buildAjilesQualityPage(constancia, clientMatch, items, fecha)
          : pageQualityStandard;
        const showTransport = isCencosudCdLimaClient(cliente, clientMatch);
        const pageTransport = showTransport
          ? buildCencosudTransportPage(constancia, items, fecha, numero, cliente, transporte)
          : "";
        const pageList = [showFumigacion ? pageContent : "", showCalidad ? pageQuality : "", showTransport ? pageTransport : ""].filter(
          (page) => page
        );
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
function printDoc(){window.print();}
async function savePdf(){
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
}` +
          '</scr' +
          'ipt>';
        return `
          <html>
            <head>
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
                .data { width: 100%; border-collapse: collapse; font-size: 8px; table-layout: fixed; }
                .data th, .data td { border: 1px solid #111827; padding: 3px; word-break: break-word; }
                .data th { text-align: center; font-weight: 600; }
                .data td { text-align: center; }
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
                .ct-transport th, .ct-transport td { font-size: 8px; }
                .ct-transport th:nth-child(1), .ct-transport td:nth-child(1) { width: 6%; }
                .ct-transport th:nth-child(2), .ct-transport td:nth-child(2) { width: 12%; }
                .ct-transport th:nth-child(3), .ct-transport td:nth-child(3) { width: 24%; }
                .ct-transport th:nth-child(4), .ct-transport td:nth-child(4) { width: 10%; }
                .ct-transport th:nth-child(5), .ct-transport td:nth-child(5) { width: 34%; }
                .ct-transport th:nth-child(6), .ct-transport td:nth-child(6) { width: 14%; }
                @media print {
                  body { background: #fff; }
                  .actions { display: none; }
                  .page { margin: 0; box-shadow: none; }
                }
              </style>
            </head>
            <body>
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
