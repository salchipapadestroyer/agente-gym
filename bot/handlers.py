import asyncio
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ConversationHandler, MessageHandler,
    ContextTypes, filters,
)
from . import sheets, claude_client, metrics

log = logging.getLogger(__name__)

DIAS_ES = {
    "monday": "lunes", "tuesday": "martes", "wednesday": "miércoles",
    "thursday": "jueves", "friday": "viernes", "saturday": "sábado",
    "sunday": "domingo",
}


def _dia_semana_es() -> str:
    return DIAS_ES[datetime.now().strftime("%A").lower()]


def _fmt_resumen(r: dict) -> str:
    return "\n".join(f"{k}: {v}" for k, v in r.items() if v not in (None, ""))


ONBOARDING_QS = [
    ("nombre", "¿Cómo te llamas?"),
    ("edad", "¿Cuántos años tienes?"),
    ("sexo", "Sexo (M/F/otro):"),
    ("estatura_cm", "Estatura en cm:"),
    ("peso_kg", "Peso en kg:"),
    ("grasa_pct_o_NA", "% de grasa si lo conoces (si no, escribe NA):"),
    ("objetivo", "Objetivo (bajar grasa / ganar músculo / recomposición / fuerza / salud general):"),
    ("nivel", "Nivel (principiante / intermedio / avanzado):"),
    ("dias_entrenamiento", "¿Cuántos días puedes entrenar por semana?"),
    ("lugar_entrenamiento", "Lugar de entrenamiento (gym / casa / mixto):"),
    ("lesiones_molestias", "Lesiones, molestias o ejercicios prohibidos (o 'ninguna'):"),
    ("alimentos_excluidos", "Alimentos que no comes o no te gustan (o 'ninguno'):"),
    ("dia_super", "¿Qué día haces súper?"),
    ("preferencia_menu", "¿Menú con gramos, porciones prácticas o ambos?"),
    ("horario_entrenamiento", "¿A qué hora sueles entrenar?"),
]
STATES = list(range(len(ONBOARDING_QS)))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    existing = await asyncio.to_thread(sheets.get_user, chat_id)
    if existing:
        await update.message.reply_text(
            f"Ya estás registrado, {existing.get('nombre', '')}. "
            "Usa /hoy para tu plan o /resumen para ver tu estado."
        )
        return ConversationHandler.END

    context.user_data["onboarding"] = {"telegram_chat_id": chat_id}
    await update.message.reply_text(
        "Va, para armarte tu plan necesito 15 datos. Voy uno por uno. "
        "Escribe /cancel si quieres salir."
    )
    await update.message.reply_text(ONBOARDING_QS[0][1])
    return STATES[0]


def _make_step(idx: int):
    async def step(update: Update, context: ContextTypes.DEFAULT_TYPE):
        field = ONBOARDING_QS[idx][0]
        context.user_data["onboarding"][field] = update.message.text.strip()
        nxt = idx + 1
        if nxt < len(ONBOARDING_QS):
            await update.message.reply_text(ONBOARDING_QS[nxt][1])
            return STATES[nxt]
        await update.message.reply_text("Listo. Dame un momento mientras te armo tu plan…")
        await _finalize_onboarding(update, context)
        return ConversationHandler.END
    return step


async def _finalize_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data["onboarding"]
    data.setdefault("usuario", data.get("nombre", f"user_{data['telegram_chat_id']}"))
    fecha_hoy = datetime.now().strftime("%Y-%m-%d")
    try:
        result = await asyncio.to_thread(claude_client.onboarding, data, fecha_hoy)
    except Exception as e:
        log.exception("onboarding failed")
        await update.message.reply_text(f"Falló la generación del plan: {e}. Vuelve a intentar /start.")
        context.user_data.clear()
        return

    fila_u = result["fila_usuarios"]
    fila_u["telegram_chat_id"] = data["telegram_chat_id"]
    fila_u.setdefault("fecha_registro", fecha_hoy)
    await asyncio.to_thread(sheets.append_row, "Usuarios", fila_u, sheets.USUARIOS_COLS)

    fila_r = result["fila_resumen_usuarios"]
    fila_r["telegram_chat_id"] = data["telegram_chat_id"]
    await asyncio.to_thread(sheets.upsert_resumen, fila_r)

    await update.message.reply_text(result["primer_mensaje_diario"])
    context.user_data.clear()


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Cancelado. Usa /start cuando quieras retomar.")
    return ConversationHandler.END


async def hoy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user = await asyncio.to_thread(sheets.get_user, chat_id)
    if not user:
        await update.message.reply_text("No te encuentro. Empieza con /start.")
        return
    fecha_hoy = datetime.now().strftime("%Y-%m-%d")
    existing = await asyncio.to_thread(sheets.get_plan_today, chat_id, fecha_hoy)
    if existing:
        await update.message.reply_text(
            f"Plan de hoy:\nRutina: {existing.get('rutina_programada','')}\n"
            f"Comidas: {existing.get('comidas_programadas','')}\n"
            f"Calorías: {existing.get('calorias_obj','')}\n\n"
            "(ya generé plan hoy; si lo perdiste scrollea arriba)"
        )
        return
    await send_plan(context.bot, chat_id, user)


async def send_plan(bot, chat_id: str, user: dict):
    resumen = await asyncio.to_thread(sheets.get_resumen, chat_id)
    if not resumen:
        await bot.send_message(chat_id=chat_id, text="Falta resumen. Haz /start primero.")
        return
    checkins = await asyncio.to_thread(sheets.get_last_checkins, chat_id, 1)
    ultimo = checkins[0] if checkins else None
    fecha_hoy = datetime.now().strftime("%Y-%m-%d")
    dia_es = _dia_semana_es()
    hoy_super = str(user.get("dia_super", "")).strip().lower() == dia_es

    result = await asyncio.to_thread(
        claude_client.plan_diario,
        _fmt_resumen(resumen), ultimo,
        resumen.get("ajuste_activo", ""), hoy_super,
        fecha_hoy, dia_es,
    )
    fila = result["fila_planes_diarios"]
    fila["telegram_chat_id"] = chat_id
    fila["fecha"] = fecha_hoy
    await asyncio.to_thread(sheets.append_row, "Planes_Diarios", fila, sheets.PLANES_COLS)
    await bot.send_message(chat_id=chat_id, text=result["mensaje_telegram"])
    if hoy_super:
        await super_for(bot, chat_id, resumen)


async def super_for(bot, chat_id: str, resumen: dict):
    result = await asyncio.to_thread(claude_client.lista_super, resumen, None)
    await bot.send_message(chat_id=chat_id, text=result["mensaje_telegram"])


async def checkin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user = await asyncio.to_thread(sheets.get_user, chat_id)
    if not user:
        await update.message.reply_text("No te encuentro. Empieza con /start.")
        return
    context.user_data["awaiting_checkin"] = True
    await update.message.reply_text(
        f"Cierre del día, {user.get('nombre', '')}. Respóndeme:\n\n"
        "1. ¿Entrenaste? Sí/No\n"
        "2. ¿Qué rutina hiciste?\n"
        "3. ¿Cumpliste comidas? 0-100%\n"
        "4. Energía 1-10:\n"
        "5. Hambre 1-10:\n"
        "6. ¿Dolor o molestia? Sí/No, ¿dónde?\n"
        "7. Horas de sueño:\n"
        "8. Peso (opcional):\n"
        "9. Comentario libre:\n\n"
        "Puedes responder corto tipo: 'sí entrené, comidas 80%, energía 7, dormí 7h'."
    )


async def checkin_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_checkin"):
        return
    context.user_data["awaiting_checkin"] = False
    chat_id = str(update.effective_chat.id)
    user = await asyncio.to_thread(sheets.get_user, chat_id)
    if not user:
        return
    fecha_hoy = datetime.now().strftime("%Y-%m-%d")
    try:
        parsed = await asyncio.to_thread(
            claude_client.parsear_checkin, update.message.text,
            user.get("nombre", ""), fecha_hoy,
        )
        resumen = await asyncio.to_thread(sheets.get_resumen, chat_id) or {}
        ajuste = await asyncio.to_thread(
            claude_client.ajuste_dia, user.get("nombre", ""),
            fecha_hoy, parsed, resumen,
        )
    except Exception as e:
        log.exception("checkin flow failed")
        await update.message.reply_text(f"Falló procesar el check-in: {e}")
        return

    fila = {
        "fecha": fecha_hoy,
        "telegram_chat_id": chat_id,
        "usuario": user.get("usuario", ""),
        "entreno": parsed.get("entreno", ""),
        "rutina_programada": "",
        "rutina_completada": parsed.get("rutina_completada", ""),
        "comidas_pct": parsed.get("comidas_pct", ""),
        "energia_1_10": parsed.get("energia_1_10", ""),
        "hambre_1_10": parsed.get("hambre_1_10", ""),
        "dolor_molestia": parsed.get("dolor_molestia", ""),
        "zona_dolor": parsed.get("zona_dolor", ""),
        "sueno_horas": parsed.get("sueno_horas", ""),
        "peso_corporal": parsed.get("peso_corporal", ""),
        "comentario_libre": parsed.get("comentario_libre", ""),
        "ajuste_recomendado": ajuste.get("ajuste_recomendado", ""),
        "timestamp": datetime.now().isoformat(),
    }
    await asyncio.to_thread(sheets.append_row, "Checkins_Diarios", fila, sheets.CHECKINS_COLS)

    if resumen:
        last7 = await asyncio.to_thread(sheets.get_last_checkins, chat_id, 7)
        resumen.update(metrics.compute_7d(last7))
        nuevo = ajuste.get("actualizar_ajuste_activo")
        if nuevo:
            resumen["ajuste_activo"] = nuevo
        if parsed.get("peso_corporal"):
            resumen["peso_actual"] = parsed["peso_corporal"]
        resumen["ultima_actualizacion"] = fecha_hoy
        await asyncio.to_thread(sheets.upsert_resumen, resumen)

    await update.message.reply_text(ajuste["mensaje_telegram"])
    if ajuste.get("alerta_seguridad"):
        await update.message.reply_text(ajuste["alerta_seguridad"])


async def super_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    resumen = await asyncio.to_thread(sheets.get_resumen, chat_id)
    if not resumen:
        await update.message.reply_text("No te encuentro. Empieza con /start.")
        return
    await super_for(context.bot, chat_id, resumen)


async def resumen_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    r = await asyncio.to_thread(sheets.get_resumen, chat_id)
    if not r:
        await update.message.reply_text("No te encuentro. Empieza con /start.")
        return
    await update.message.reply_text(_fmt_resumen(r))


async def run_weekly(bot, user: dict) -> bool:
    chat_id = str(user.get("telegram_chat_id"))
    resumen = await asyncio.to_thread(sheets.get_resumen, chat_id)
    if not resumen:
        return False
    checkins = await asyncio.to_thread(sheets.get_last_checkins, chat_id, 7)
    if not checkins:
        return False
    resumen.update(metrics.compute_7d(checkins))
    fechas = [c.get("fecha") for c in checkins if c.get("fecha")]
    peso_fin = next(
        (c.get("peso_corporal") for c in reversed(checkins) if c.get("peso_corporal")), None
    )
    result = await asyncio.to_thread(
        claude_client.reporte_semanal,
        user.get("nombre", ""), _fmt_resumen(resumen), checkins,
        fechas[0] if fechas else "", fechas[-1] if fechas else "",
        None, peso_fin,
    )
    await bot.send_message(chat_id=chat_id, text=result["mensaje_telegram"])
    nuevo = result.get("ajuste_semana_siguiente")
    if nuevo:
        resumen["ajuste_activo"] = nuevo
    resumen["ultima_actualizacion"] = datetime.now().strftime("%Y-%m-%d")
    await asyncio.to_thread(sheets.upsert_resumen, resumen)
    return True


async def semana(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user = await asyncio.to_thread(sheets.get_user, chat_id)
    if not user:
        await update.message.reply_text("No te encuentro. Empieza con /start.")
        return
    ok = await run_weekly(context.bot, user)
    if not ok:
        await update.message.reply_text("Aún no hay check-ins esta semana.")


async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Comandos:\n"
        "/start - registro inicial\n"
        "/hoy - plan del día\n"
        "/checkin - cierre del día\n"
        "/super - lista de súper\n"
        "/resumen - tu estado actual\n"
        "/semana - reporte semanal\n"
        "/ayuda - esto"
    )


def register(app: Application):
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            STATES[i]: [MessageHandler(filters.TEXT & ~filters.COMMAND, _make_step(i))]
            for i in range(len(ONBOARDING_QS))
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv)
    app.add_handler(CommandHandler("hoy", hoy))
    app.add_handler(CommandHandler("checkin", checkin))
    app.add_handler(CommandHandler("super", super_cmd))
    app.add_handler(CommandHandler("resumen", resumen_cmd))
    app.add_handler(CommandHandler("semana", semana))
    app.add_handler(CommandHandler("ayuda", ayuda))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, checkin_response))
