"""Crea (o verifica) las 4 hojas con sus headers en el Google Sheet.

Requiere: GOOGLE_SHEETS_ID y GOOGLE_CREDS_PATH en .env.

Uso: python -m scripts.setup_sheet
"""
import sys
from bot import sheets

WORKSHEETS = [
    ("Usuarios", sheets.USUARIOS_COLS),
    ("Checkins_Diarios", sheets.CHECKINS_COLS),
    ("Resumen_Usuarios", sheets.RESUMEN_COLS),
    ("Planes_Diarios", sheets.PLANES_COLS),
]


def main() -> int:
    sh = sheets.get_sheet()
    existing = {ws.title: ws for ws in sh.worksheets()}

    for name, cols in WORKSHEETS:
        if name in existing:
            ws = existing[name]
            header = ws.row_values(1)
            if header == cols:
                print(f"[ok]       {name}: headers correctos ({len(cols)} columnas)")
            else:
                print(f"[actualiz] {name}: reescribiendo headers")
                ws.update(values=[cols], range_name="A1")
        else:
            print(f"[crear]    {name}")
            ws = sh.add_worksheet(title=name, rows=1000, cols=len(cols))
            ws.update(values=[cols], range_name="A1")

    default = existing.get("Sheet1") or existing.get("Hoja 1")
    if default and default.title not in [n for n, _ in WORKSHEETS]:
        try:
            sh.del_worksheet(default)
            print(f"[limpiar]  {default.title} por defecto eliminada")
        except Exception as e:
            print(f"[warn]     no pude borrar hoja por defecto: {e}")

    print("\nSetup completo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
