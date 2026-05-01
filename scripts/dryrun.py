"""CLI para probar el pipeline sin Telegram.

Uso:
  python -m scripts.dryrun onboard [--chat-id X] [--file perfil.json]
  python -m scripts.dryrun plan --chat-id X
  python -m scripts.dryrun checkin --chat-id X "sí entrené, comidas 80%, energía 7"
  python -m scripts.dryrun semana --chat-id X
  python -m scripts.dryrun resumen --chat-id X
"""
import argparse
import json
import sys
from datetime import datetime
from bot import sheets, claude_client, metrics
from bot.handlers import ONBOARDING_QS, DIAS_ES


def _fmt_resumen(r: dict) -> str:
    return "\n".join(f"{k}: {v}" for k, v in r.items() if v not in (None, ""))


def _ask_interactive(chat_id: str) -> dict:
    print(f"Onboarding interactivo para chat_id={chat_id}.\n")
    data = {"telegram_chat_id": chat_id}
    for field, q in ONBOARDING_QS:
        data[field] = input(f"  {q} ").strip()
    data.setdefault("usuario", data.get("nombre", f"user_{chat_id}"))
    return data


def cmd_onboard(args):
    chat_id = args.chat_id or "dryrun_0001"
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            data = json.load(f)
        data["telegram_chat_id"] = chat_id
        data.setdefault("usuario", data.get("nombre", f"user_{chat_id}"))
    else:
        data = _ask_interactive(chat_id)

    fecha = datetime.now().strftime("%Y-%m-%d")
    print("\n→ Llamando a Claude (onboarding)…\n")
    result = claude_client.onboarding(data, fecha)

    print("----- primer_mensaje_diario -----")
    print(result["primer_mensaje_diario"])
    print("\n----- resumen_compacto -----")
    print(result["resumen_compacto"])
    print("\n----- macros_objetivo -----")
    print(json.dumps(result["macros_objetivo"], ensure_ascii=False, indent=2))

    if input("\n¿Escribir a Sheets? (y/N) ").strip().lower() != "y":
        print("No se escribió nada.")
        return 0

    fila_u = result["fila_usuarios"]
    fila_u["telegram_chat_id"] = chat_id
    fila_u.setdefault("fecha_registro", fecha)
    sheets.append_row("Usuarios", fila_u, sheets.USUARIOS_COLS)

    fila_r = result["fila_resumen_usuarios"]
    fila_r["telegram_chat_id"] = chat_id
    sheets.upsert_resumen(fila_r)
    print(f"Escrito. chat_id={chat_id}")
    return 0


def cmd_plan(args):
    user = sheets.get_user(args.chat_id)
    if not user:
        print(f"No existe usuario con chat_id={args.chat_id}")
        return 1
    resumen = sheets.get_resumen(args.chat_id)
    if not resumen:
        print("No existe resumen.")
        return 1
    last = sheets.get_last_checkins(args.chat_id, 1)
    dia_es = DIAS_ES[datetime.now().strftime("%A").lower()]
    hoy_super = str(user.get("dia_super", "")).strip().lower() == dia_es
    fecha = datetime.now().strftime("%Y-%m-%d")
    print(f"→ Plan para {user.get('nombre')} ({dia_es}, súper={hoy_super})…\n")
    result = claude_client.plan_diario(
        _fmt_resumen(resumen),
        last[0] if last else None,
        resumen.get("ajuste_activo", ""),
        hoy_super, fecha, dia_es,
    )
    print("----- mensaje_telegram -----")
    print(result["mensaje_telegram"])
    print("\n----- fila_planes_diarios -----")
    print(json.dumps(result["fila_planes_diarios"], ensure_ascii=False, indent=2))
    return 0


def cmd_checkin(args):
    user = sheets.get_user(args.chat_id)
    if not user:
        print(f"No existe usuario con chat_id={args.chat_id}")
        return 1
    fecha = datetime.now().strftime("%Y-%m-%d")
    print("→ Parseando check-in…\n")
    parsed = claude_client.parsear_checkin(args.mensaje, user.get("nombre", ""), fecha)
    print(json.dumps(parsed, ensure_ascii=False, indent=2))

    resumen = sheets.get_resumen(args.chat_id) or {}
    print("\n→ Generando ajuste…\n")
    ajuste = claude_client.ajuste_dia(user.get("nombre", ""), fecha, parsed, resumen)
    print(json.dumps(ajuste, ensure_ascii=False, indent=2))

    if input("\n¿Escribir a Sheets? (y/N) ").strip().lower() != "y":
        print("No se escribió nada.")
        return 0

    fila = {
        "fecha": fecha,
        "telegram_chat_id": args.chat_id,
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
    sheets.append_row("Checkins_Diarios", fila, sheets.CHECKINS_COLS)

    last7 = sheets.get_last_checkins(args.chat_id, 7)
    resumen.update(metrics.compute_7d(last7))
    if ajuste.get("actualizar_ajuste_activo"):
        resumen["ajuste_activo"] = ajuste["actualizar_ajuste_activo"]
    if parsed.get("peso_corporal"):
        resumen["peso_actual"] = parsed["peso_corporal"]
    resumen["ultima_actualizacion"] = fecha
    sheets.upsert_resumen(resumen)
    print("\nEscrito. Resumen refrescado con métricas 7d.")
    return 0


def cmd_semana(args):
    user = sheets.get_user(args.chat_id)
    resumen = sheets.get_resumen(args.chat_id)
    if not user or not resumen:
        print("Falta usuario o resumen.")
        return 1
    checkins = sheets.get_last_checkins(args.chat_id, 7)
    if not checkins:
        print("Sin check-ins.")
        return 1
    resumen.update(metrics.compute_7d(checkins))
    fechas = [c.get("fecha") for c in checkins if c.get("fecha")]
    peso_fin = next(
        (c.get("peso_corporal") for c in reversed(checkins) if c.get("peso_corporal")), None
    )
    print("→ Reporte semanal…\n")
    result = claude_client.reporte_semanal(
        user.get("nombre", ""), _fmt_resumen(resumen), checkins,
        fechas[0] if fechas else "", fechas[-1] if fechas else "",
        None, peso_fin,
    )
    print("----- mensaje_telegram -----")
    print(result["mensaje_telegram"])
    print("\n----- ajuste_semana_siguiente -----")
    print(result.get("ajuste_semana_siguiente", ""))
    return 0


def cmd_resumen(args):
    r = sheets.get_resumen(args.chat_id)
    if not r:
        print("No existe resumen.")
        return 1
    print(_fmt_resumen(r))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    po = sub.add_parser("onboard")
    po.add_argument("--chat-id")
    po.add_argument("--file", help="JSON con las 15 respuestas")
    po.set_defaults(func=cmd_onboard)

    pp = sub.add_parser("plan")
    pp.add_argument("--chat-id", required=True)
    pp.set_defaults(func=cmd_plan)

    pc = sub.add_parser("checkin")
    pc.add_argument("--chat-id", required=True)
    pc.add_argument("mensaje")
    pc.set_defaults(func=cmd_checkin)

    ps = sub.add_parser("semana")
    ps.add_argument("--chat-id", required=True)
    ps.set_defaults(func=cmd_semana)

    pr = sub.add_parser("resumen")
    pr.add_argument("--chat-id", required=True)
    pr.set_defaults(func=cmd_resumen)

    args = p.parse_args()
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
