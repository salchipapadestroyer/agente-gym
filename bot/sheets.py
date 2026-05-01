import gspread
from google.oauth2.service_account import Credentials
from . import config

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

USUARIOS_COLS = [
    "telegram_chat_id", "usuario", "nombre", "edad", "sexo", "estatura_cm",
    "peso_inicial_kg", "grasa_pct", "objetivo", "nivel", "dias_entrenamiento",
    "lugar_entrenamiento", "lesiones_molestias", "alimentos_excluidos",
    "dia_super", "preferencia_menu", "horario_entrenamiento", "fecha_registro", "notas",
]

CHECKINS_COLS = [
    "fecha", "telegram_chat_id", "usuario", "entreno", "rutina_programada",
    "rutina_completada", "comidas_pct", "energia_1_10", "hambre_1_10",
    "dolor_molestia", "zona_dolor", "sueno_horas", "peso_corporal",
    "comentario_libre", "ajuste_recomendado", "timestamp",
]

RESUMEN_COLS = [
    "usuario", "telegram_chat_id", "peso_actual", "objetivo",
    "calorias_objetivo", "proteina_g", "carbs_g", "grasas_g", "rutina_base",
    "adherencia_entreno_7d", "adherencia_comida_7d", "energia_prom_7d",
    "hambre_prom_7d", "sueno_prom_7d", "alertas", "ajuste_activo",
    "proximo_dia_super", "ultima_actualizacion",
]

PLANES_COLS = [
    "fecha", "telegram_chat_id", "rutina_programada", "comidas_programadas",
    "calorias_obj", "notas",
]

_sheet = None


def get_sheet():
    global _sheet
    if _sheet is None:
        creds = Credentials.from_service_account_file(config.GOOGLE_CREDS_PATH, scopes=SCOPES)
        _sheet = gspread.authorize(creds).open_by_key(config.GOOGLE_SHEETS_ID)
    return _sheet


def _ws(name: str):
    return get_sheet().worksheet(name)


def get_user(chat_id: str) -> dict | None:
    for r in _ws("Usuarios").get_all_records():
        if str(r.get("telegram_chat_id")) == str(chat_id):
            return r
    return None


def get_all_users() -> list[dict]:
    return _ws("Usuarios").get_all_records()


def append_row(sheet_name: str, row: dict, cols: list[str]):
    values = [row.get(c, "") for c in cols]
    _ws(sheet_name).append_row(values, value_input_option="USER_ENTERED")


def get_resumen(chat_id: str) -> dict | None:
    for r in _ws("Resumen_Usuarios").get_all_records():
        if str(r.get("telegram_chat_id")) == str(chat_id):
            return r
    return None


def upsert_resumen(row: dict):
    ws = _ws("Resumen_Usuarios")
    records = ws.get_all_records()
    values = [row.get(c, "") for c in RESUMEN_COLS]
    for i, r in enumerate(records, start=2):
        if str(r.get("telegram_chat_id")) == str(row["telegram_chat_id"]):
            ws.update(values=[values], range_name=f"A{i}:{_col_letter(len(RESUMEN_COLS))}{i}")
            return
    ws.append_row(values, value_input_option="USER_ENTERED")


def get_last_checkins(chat_id: str, n: int = 7) -> list[dict]:
    records = _ws("Checkins_Diarios").get_all_records()
    user_records = [r for r in records if str(r.get("telegram_chat_id")) == str(chat_id)]
    return user_records[-n:]


def get_plan_today(chat_id: str, fecha: str) -> dict | None:
    for r in _ws("Planes_Diarios").get_all_records():
        if str(r.get("telegram_chat_id")) == str(chat_id) and r.get("fecha") == fecha:
            return r
    return None


def _col_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s
