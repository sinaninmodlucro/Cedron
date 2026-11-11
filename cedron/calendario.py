"""Calendario de fechas clave (11-nov-2026).

Tres tipos de fechas:
  - automaticas: reuniones de la Reserva Federal y del BCE, leidas de sus webs una vez a la
    semana (data/calendario.json);
  - fijas, en config.yaml (seccion 'calendario.fechas'), siempre con su fuente;
  - periodicas (config: 'calendario.periodicas'): publicaciones que salen siempre el mismo dia
    de la semana o del mes; se marcan «habitualmente» porque los festivos las mueven.
Ademas: fechas de las medidas regulatorias y meses en que vencen previsiones del historial.
Nunca se inventa una fecha: si una fuente no publica su calendario, no se muestra.
"""
from __future__ import annotations

import calendar as _cal
import logging
from datetime import date, timedelta

from . import sources as src
from .store import Estado, escribir, iso, leer

log = logging.getLogger("cedron.calendario")
ARCHIVO = "calendario.json"
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def recoger(cfg: dict, estado: Estado, forzar: bool = False) -> None:
    """Reuniones de los bancos centrales, una vez a la semana."""
    semana = date.today().isocalendar()
    clave = f"{semana.year}-{semana.week:02d}"
    if not forzar and estado.get("calendario_semana") == clave:
        return
    guardado = leer(ARCHIVO, {}) or {}
    fuentes = {"fed": ("Reserva Federal (calendario)", src.fed_reuniones),
               "bce": ("BCE (calendario)", src.bce_reuniones)}
    ok = True
    for ident, (nombre, funcion) in fuentes.items():
        try:
            guardado[ident] = funcion()
            estado.registrar_fuente(nombre, True)
        except src.FuenteError as e:
            ok = False
            estado.registrar_fuente(nombre, False, str(e))
            log.warning("%s: %s", nombre, e)
    guardado["consultado"] = iso()
    escribir(ARCHIVO, guardado)
    if ok:
        estado.set("calendario_semana", clave)


def _periodicas(c: dict, desde: date, hasta: date, tipos: dict) -> list[dict]:
    out = []
    for p in c.get("periodicas") or []:
        t = tipos.get(p.get("tipo"), {})
        base = {"titulo": p["titulo"], "tipo": p.get("tipo"), "tipo_nombre": t.get("nombre", ""),
                "materias": p.get("materias") or [], "fuente": p.get("fuente"), "enlace": p.get("enlace"),
                "aprox": True, "nota": p.get("nota")}
        if "dia_semana" in p:
            d = desde + timedelta(days=(int(p["dia_semana"]) - desde.weekday()) % 7)
            while d <= hasta:
                out.append({**base, "fecha": d.isoformat()})
                d += timedelta(days=7)
        elif "dia_mes" in p:
            a, m = desde.year, desde.month
            while date(a, m, 1) <= hasta:
                if p["dia_mes"] == "ultimo_laborable":
                    d = date(a, m, _cal.monthrange(a, m)[1])
                    while d.weekday() >= 5:
                        d -= timedelta(days=1)
                else:
                    d = date(a, m, min(int(p["dia_mes"]), _cal.monthrange(a, m)[1]))
                if desde <= d <= hasta:
                    out.append({**base, "fecha": d.isoformat()})
                a, m = (a + 1, 1) if m == 12 else (a, m + 1)
    return out


def eventos(cfg: dict, desde: date | None = None, hasta: date | None = None) -> list[dict]:
    """Todas las fechas conocidas entre 'desde' y 'hasta' (por defecto, de hoy a un anio)."""
    desde = desde or date.today()
    hasta = hasta or desde + timedelta(days=366)
    c = cfg.get("calendario") or {}
    tipos = c.get("tipos") or {}
    out = []
    auto = leer(ARCHIVO, {}) or {}
    for ident, texto in (("fed", "Reserva Federal: decisión de tipos de interés"),
                         ("bce", "BCE: decisión de tipos de interés")):
        t = tipos.get("banco_central", {})
        for f in auto.get(ident, []):
            out.append({"fecha": f, "titulo": texto, "tipo": "banco_central", "tipo_nombre": t.get("nombre", ""),
                        "materias": [], "fuente": "Reserva Federal" if ident == "fed" else "Banco Central Europeo",
                        "enlace": ("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm" if ident == "fed"
                                   else "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html")})
    for e in c.get("fechas") or []:
        t = tipos.get(e.get("tipo"), {})
        out.append({"fecha": str(e["fecha"]), "titulo": e["titulo"], "tipo": e.get("tipo"),
                    "tipo_nombre": t.get("nombre", ""), "materias": e.get("materias") or [],
                    "nota": e.get("nota"), "fuente": e.get("fuente"), "enlace": e.get("enlace")})
    out += _periodicas(c, desde, hasta, tipos)
    for m in cfg.get("medidas") or []:
        for campo, texto in (("desde", "Entra en vigor"), ("revision", "Puede revisarse"), ("hasta", "Termina")):
            if m.get(campo):
                out.append({"fecha": str(m[campo])[:10], "titulo": f"{texto}: {m['titulo']}", "tipo": "medida",
                            "tipo_nombre": tipos.get("medida", {}).get("nombre", "Medida regulatoria"),
                            "materias": [m.get("materia")], "fuente": m.get("fuente"), "enlace": m.get("enlace")})
    # Meses en que vencen previsiones del historial (se comprueban al publicarse el dato)
    for mes, n in (leer("previsiones_resumen.json") or {}).get("calendario") or []:
        out.append({"fecha": f"{mes}-01", "titulo": f"Vencen {n} previsiones del historial (dato de {mes})",
                    "tipo": "prevision", "tipo_nombre": tipos.get("prevision", {}).get("nombre", "Previsiones"),
                    "materias": [], "mes_entero": True})
    out = [e for e in out if desde.isoformat() <= e["fecha"] <= hasta.isoformat()
           or (e.get("mes_entero") and e["fecha"][:7] >= desde.isoformat()[:7] and e["fecha"] <= hasta.isoformat())]
    return sorted(out, key=lambda e: (e["fecha"], e["titulo"]))


def proximas(cfg: dict, dias: int = 14, hoy: date | None = None) -> list[dict]:
    hoy = hoy or date.today()
    return [e for e in eventos(cfg, hoy, hoy + timedelta(days=dias))
            if e.get("tipo") != "prevision" and not e.get("aprox")]


def por_meses(lista: list[dict]) -> list[tuple[str, list[dict]]]:
    meses: dict[str, list[dict]] = {}
    for e in lista:
        meses.setdefault(e["fecha"][:7], []).append(e)
    return sorted(meses.items())


def dia_semana(f: str) -> str:
    return DIAS[date.fromisoformat(f).weekday()]
