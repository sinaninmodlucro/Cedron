"""Estado de las fuentes y de los historiales (pagina «Estado», 11-nov-2026).

De cada fuente: cuando respondio por ultima vez, de que fecha es su dato mas nuevo y si va
con retraso segun lo que suele tardar en publicar (config: estado_fuentes). De los
historiales de previsiones: cuantas hay apuntadas y comprobadas.
"""
from __future__ import annotations

from datetime import date, timedelta

from .store import HISTORIALES, leer, parse_iso

TEXTOS = {"al_dia": "Al día", "retraso": "Con retraso", "fallo": "Último intento fallido",
          "fallando": "Fallando", "sin_datos": "Sin datos"}


def fin_periodo(f: str) -> date | None:
    """'2026-09' -> 30-sep-2026; '2026-11-02' o '2026-11-02T10:00Z' -> ese dia."""
    if not f or not isinstance(f, str):
        return None
    try:
        if len(f) == 7:
            a, m = int(f[:4]), int(f[5:7])
            return date(a + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
        if len(f) == 4:
            return date(int(f), 12, 31)
        return date.fromisoformat(f[:10])
    except ValueError:
        return None


def _ultima_de_lista(lista) -> str | None:
    if isinstance(lista, list) and lista:
        x = lista[-1]
        if isinstance(x, (list, tuple)) and x:
            return str(x[0])
        if isinstance(x, dict):
            return x.get("fecha")
    return None


def ultimo_dato(spec: dict) -> tuple[str | None, int, int]:
    """(fecha del dato mas nuevo, series con dato, series sin dato reciente)."""
    datos = leer(spec["archivo"])
    if datos is None:
        return None, 0, 0
    modo = spec.get("modo", "series")
    if modo == "consultado":
        return (datos.get("consultado") or "")[:10] or None, 1, 0
    if modo == "noticias":
        fechas = [n.get("fecha") or "" for n in datos.get("noticias", [])]
        return (max(fechas)[:10] if fechas else None), len(fechas), 0
    if modo == "lista":
        f = _ultima_de_lista(datos)
        return f, int(bool(f)), 0
    series = datos.get("series") or {}
    fechas = [f for f in (_ultima_de_lista(s) for s in series.values()) if f]
    if not fechas:
        return None, 0, 0
    nueva = max(fechas, key=lambda f: fin_periodo(f) or date.min)
    limite = (fin_periodo(nueva) or date.min) - timedelta(days=int(spec.get("max_dias", 30)))
    paradas = sum(1 for f in fechas if (fin_periodo(f) or date.min) < limite)
    return nueva, len(fechas), paradas


def fuentes(cfg: dict, estado: dict | None = None, hoy: date | None = None) -> list[dict]:
    hoy = hoy or date.today()
    registro = (estado if estado is not None else (leer("estado.json", {}) or {})).get("fuentes", {})
    filas = []
    for spec in cfg.get("estado_fuentes") or []:
        fecha, n, paradas = ultimo_dato(spec)
        info = registro.get(spec.get("estado", ""), {})
        fin = fin_periodo(fecha) if fecha else None
        edad = (hoy - fin).days if fin else None
        fallos = int(info.get("fallos_seguidos") or 0)
        if fallos >= 3:
            clase = "fallando"
        elif fecha is None:
            clase = "sin_datos"
        elif edad > int(spec.get("max_dias", 30)):
            clase = "retraso"
        elif fallos:
            clase = "fallo"
        else:
            clase = "al_dia"
        filas.append({**spec, "fecha": fecha, "edad": edad, "series": n, "paradas": paradas,
                      "ultimo_ok": info.get("ultimo_ok"), "fallos": fallos, "error": info.get("ultimo_error"),
                      "clase": clase, "texto": TEXTOS[clase]})
    return filas


def historiales() -> list[dict]:
    nombres = {"metales_previsiones.json": "Metales", "apoyo_previsiones.json": "Materias primas de apoyo",
               "cadena_previsiones.json": "Cadena de costes"}
    filas = []
    for archivo in HISTORIALES:
        reg = leer(archivo, []) or []
        filas.append({"nombre": nombres.get(archivo, archivo), "archivo": archivo, "total": len(reg),
                      "futuros": sum(1 for r in reg if str(r.get("id", "")).startswith("futuros:")),
                      "comprobadas": sum(1 for r in reg if r.get("real") is not None),
                      "ultima": max((r.get("apuntada") or "" for r in reg), default="") or None,
                      "proxima": min((r["vence"] for r in reg if r.get("real") is None and r.get("vence")), default=None)})
    return filas


def problemas(filas: list[dict]) -> list[dict]:
    return [f for f in filas if f["clase"] not in ("al_dia", "fallo")]
