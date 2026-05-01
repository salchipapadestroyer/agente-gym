"""Rolling 7-day metrics from Checkins_Diarios rows."""
from statistics import mean


def _num(v):
    if v in (None, "", "NA"):
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _yes(v) -> bool:
    return str(v or "").strip().lower() in ("sí", "si")


def _avg(xs, decimals=1):
    return round(mean(xs), decimals) if xs else None


def compute_7d(checkins: list[dict]) -> dict:
    if not checkins:
        return {
            "adherencia_entreno_7d": None,
            "adherencia_comida_7d": None,
            "energia_prom_7d": None,
            "hambre_prom_7d": None,
            "sueno_prom_7d": None,
            "alertas": "",
        }

    entrenos = [str(c.get("entreno", "")).strip().lower() for c in checkins]
    entrenos_validos = [e for e in entrenos if e in ("sí", "si", "no")]
    adherencia_entreno = (
        round(100 * sum(1 for e in entrenos_validos if e in ("sí", "si")) / len(entrenos_validos))
        if entrenos_validos else None
    )

    comidas = [x for x in (_num(c.get("comidas_pct")) for c in checkins) if x is not None]
    energia = [x for x in (_num(c.get("energia_1_10")) for c in checkins) if x is not None]
    hambre = [x for x in (_num(c.get("hambre_1_10")) for c in checkins) if x is not None]
    sueno = [x for x in (_num(c.get("sueno_horas")) for c in checkins) if x is not None]

    comidas_avg = _avg(comidas, 0)
    energia_avg = _avg(energia)
    hambre_avg = _avg(hambre)
    sueno_avg = _avg(sueno)
    dolores = sum(1 for c in checkins if _yes(c.get("dolor_molestia")))

    alertas = []
    if adherencia_entreno is not None and adherencia_entreno < 50:
        alertas.append("baja adherencia entreno")
    if comidas_avg is not None and comidas_avg < 60:
        alertas.append("baja adherencia comidas")
    if energia_avg is not None and energia_avg < 5:
        alertas.append("energía baja")
    if hambre_avg is not None and hambre_avg >= 8:
        alertas.append("hambre alta sostenida")
    if sueno_avg is not None and sueno_avg < 6:
        alertas.append("sueño bajo")
    if dolores >= 3:
        alertas.append(f"dolor recurrente ({dolores}/{len(checkins)})")

    return {
        "adherencia_entreno_7d": adherencia_entreno,
        "adherencia_comida_7d": comidas_avg,
        "energia_prom_7d": energia_avg,
        "hambre_prom_7d": hambre_avg,
        "sueno_prom_7d": sueno_avg,
        "alertas": "; ".join(alertas),
    }
