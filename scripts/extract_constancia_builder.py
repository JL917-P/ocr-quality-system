from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
admin = (ROOT / "frontend" / "admin.html").read_text(encoding="utf-8")
start = admin.index("      /** Firma por entorno:")
end = admin.index("      globalThis.buildConstanciaHtml = buildConstanciaHtml;")
helpers = """
      function normalizeSearchText(value) {
        return (value || "")
          .toString()
          .trim()
          .toLowerCase()
          .normalize("NFD")
          .replace(/[\\u0300-\\u036f]/g, "")
          .replace(/[^a-z0-9]+/g, " ")
          .replace(/\\s+/g, " ")
          .trim();
      }

      function itemSnapshotField(item, ...keys) {
        for (const key of keys) {
          const val = item?.[key];
          if (val !== undefined && val !== null && String(val).trim() !== "") return val;
        }
        return "";
      }

"""
body = admin[start:end].strip()
body = body.replace("      bindUser01CatalogExpirationCalc();\n", "")
footer = """
      globalThis.buildConstanciaHtml = buildConstanciaHtml;
      globalThis.isCencosudCdLimaClient = isCencosudCdLimaClient;
"""
out = "(function () {\n" + helpers + body + footer + "\n})();\n"
(ROOT / "frontend" / "constancia-builder.js").write_text(out, encoding="utf-8")
print(f"written {len(out)} bytes")
