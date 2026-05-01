import json
import logging
from anthropic import Anthropic
from . import config, prompts

log = logging.getLogger(__name__)

_client = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=config.require("ANTHROPIC_API_KEY"))
    return _client


def _call(system_blocks: list[str], user_text: str, model: str,
          max_tokens: int = 2000, temperature: float = 0.5) -> tuple[str, str]:
    system = [
        {"type": "text", "text": b, "cache_control": {"type": "ephemeral"}}
        for b in system_blocks[:-1]
    ]
    system.append({"type": "text", "text": system_blocks[-1]})
    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_text}],
    )
    if "opus-4-7" not in model:
        kwargs["temperature"] = temperature
    resp = _get_client().messages.create(**kwargs)
    return resp.content[0].text, resp.stop_reason


def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip().rstrip("`").strip()
    return text


def _call_json(system_blocks, user_text, model, max_tokens=2000, temperature=0.5) -> dict:
    budget = max_tokens
    last_raw = ""
    for attempt in range(3):
        raw, stop_reason = _call(system_blocks, user_text, model, budget, temperature)
        last_raw = raw
        if stop_reason == "max_tokens":
            log.warning("max_tokens hit (budget=%d), bumping and retrying", budget)
            budget = min(budget * 2, 16000)
            continue
        try:
            return json.loads(_strip_fence(raw))
        except json.JSONDecodeError as e:
            log.warning("JSON decode failed (attempt %d): %s", attempt + 1, e)
            log.debug("raw response head: %s", raw[:500])
            user_text = (
                user_text
                + "\n\nIMPORTANTE: tu respuesta anterior no fue JSON válido. "
                "Devuelve SOLO un JSON válido, sin texto antes o después, sin backticks. "
                "Si el contenido es largo, prioriza completar TODOS los campos antes que detalles dentro de cada uno."
            )
    log.error("JSON failed after 3 attempts. Last raw (first 1000 chars): %s", last_raw[:1000])
    raise json.JSONDecodeError("Claude no devolvió JSON válido tras 3 intentos", last_raw, 0)


def onboarding(data: dict, fecha_hoy: str) -> dict:
    system = [prompts.IDENTIDAD, prompts.REGLAS_ENTRENAMIENTO,
              prompts.REGLAS_NUTRICION, prompts.ONBOARDING_INSTRUCCION]
    user = prompts.ONBOARDING_USER.format(fecha_hoy=fecha_hoy, **data)
    return _call_json(system, user, "claude-opus-4-7", max_tokens=8000, temperature=0.7)


def plan_diario(resumen_compacto: str, ultimo_checkin: dict | None,
                ajuste_activo: str, hoy_super: bool,
                fecha_hoy: str, dia_semana: str) -> dict:
    system = [prompts.IDENTIDAD, prompts.REGLAS_ENTRENAMIENTO,
              prompts.REGLAS_NUTRICION, prompts.PLAN_DIARIO_INSTRUCCION]
    user = prompts.PLAN_DIARIO_USER.format(
        fecha_hoy=fecha_hoy,
        dia_semana=dia_semana,
        resumen_compacto=resumen_compacto,
        ultimo_checkin_json_o_NA=json.dumps(ultimo_checkin, ensure_ascii=False) if ultimo_checkin else "NA",
        ajuste_activo_o_ninguno=ajuste_activo or "ninguno",
        si_o_no="sí" if hoy_super else "no",
    )
    return _call_json(system, user, "claude-sonnet-4-6", max_tokens=2000, temperature=0.7)


def parsear_checkin(mensaje: str, nombre: str, fecha_hoy: str) -> dict:
    system = [prompts.PARSER_INSTRUCCION]
    user = prompts.PARSER_USER.format(
        fecha_hoy=fecha_hoy, nombre=nombre, mensaje_usuario=mensaje,
    )
    return _call_json(system, user, "claude-haiku-4-5-20251001",
                      max_tokens=600, temperature=0.3)


def ajuste_dia(nombre: str, fecha_hoy: str, checkin: dict, resumen: dict) -> dict:
    system = [prompts.IDENTIDAD, prompts.REGLAS_ENTRENAMIENTO,
              prompts.REGLAS_NUTRICION, prompts.AJUSTE_TABLA,
              prompts.AJUSTE_INSTRUCCION]
    user = prompts.AJUSTE_USER.format(
        nombre=nombre,
        fecha_hoy=fecha_hoy,
        checkin_json=json.dumps(checkin, ensure_ascii=False),
        adherencia_entreno_7d=resumen.get("adherencia_entreno_7d", "NA"),
        adherencia_comida_7d=resumen.get("adherencia_comida_7d", "NA"),
        energia_prom_7d=resumen.get("energia_prom_7d", "NA"),
        hambre_prom_7d=resumen.get("hambre_prom_7d", "NA"),
        sueno_prom_7d=resumen.get("sueno_prom_7d", "NA"),
        alertas=resumen.get("alertas", ""),
        ajuste_activo=resumen.get("ajuste_activo", ""),
        rutina_base=resumen.get("rutina_base", ""),
        calorias=resumen.get("calorias_objetivo", ""),
        proteina_g=resumen.get("proteina_g", ""),
        carbs_g=resumen.get("carbs_g", ""),
        grasas_g=resumen.get("grasas_g", ""),
    )
    return _call_json(system, user, "claude-sonnet-4-6",
                      max_tokens=1500, temperature=0.7)


def lista_super(resumen: dict, menu_base: dict | None = None) -> dict:
    system = [prompts.IDENTIDAD, prompts.REGLAS_NUTRICION, prompts.SUPER_INSTRUCCION]
    user = prompts.SUPER_USER.format(
        nombre=resumen.get("usuario", ""),
        objetivo=resumen.get("objetivo", ""),
        calorias=resumen.get("calorias_objetivo", ""),
        proteina_g=resumen.get("proteina_g", ""),
        carbs_g=resumen.get("carbs_g", ""),
        grasas_g=resumen.get("grasas_g", ""),
        alimentos_excluidos=resumen.get("alimentos_excluidos", ""),
        preferencia_menu=resumen.get("preferencia_menu", ""),
        menu_base_json=json.dumps(menu_base or {}, ensure_ascii=False),
        adherencia_comida_7d=resumen.get("adherencia_comida_7d", "NA"),
    )
    return _call_json(system, user, "claude-sonnet-4-6",
                      max_tokens=1800, temperature=0.7)


def reporte_semanal(nombre: str, resumen_compacto: str, checkins: list[dict],
                    fecha_inicio: str, fecha_fin: str,
                    peso_inicio, peso_fin) -> dict:
    system = [prompts.IDENTIDAD, prompts.REGLAS_ENTRENAMIENTO,
              prompts.REGLAS_NUTRICION, prompts.AJUSTE_TABLA,
              prompts.REPORTE_INSTRUCCION]
    user = prompts.REPORTE_USER.format(
        nombre=nombre,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        resumen_compacto=resumen_compacto,
        checkins_7d_json=json.dumps(checkins, ensure_ascii=False),
        peso_inicio=peso_inicio if peso_inicio else "NA",
        peso_fin=peso_fin if peso_fin else "NA",
    )
    return _call_json(system, user, "claude-opus-4-7",
                      max_tokens=2500, temperature=0.6)
