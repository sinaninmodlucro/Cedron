"""Prueba historica de las reglas de Cedron (fase 4 del plan).

Aplica, mes a mes, los mismos indicadores que usa la web (cedron/indicators.py,
con los parametros de config.yaml) a los ultimos N anios de historia, usando en
cada mes SOLO los datos que existian entonces, y mira que paso despues con el
precio. No es una estrategia de inversion ni simula compras: solo comprueba si
las lecturas tenian relacion con lo que ocurrio despues, para detectar reglas
absurdas o que no aportan.

Simplificaciones (se explican en la pagina de metodologia):
- El "precio del momento" es la media mensual del Banco Mundial de ese mes.
- Los horizontes se miden de media mensual a media mensual.
- Los periodos se solapan (cada mes mira los 6 siguientes), asi que los casos no
  son independientes: sirven para detectar fallos gordos, no para afinar decimales.

calcular() es pura (sin red ni disco); descargar() trae la historia larga.
"""
from __future__ import annotations

import calendar
import logging
import os
import statistics
from datetime import date, timedelta

from cedron import indicators as ind
from cedron import sources as src
from cedron.store import escribir, iso, leer

log = logging.getLogger("cedron.prueba")

CLASES = {
    "coherente": "Coherente",
    "inestable": "Inestable",
    "al_reves": "Al revés",
    "fija": "Casi siempre la misma señal",
    "rara": "Casi nunca da señal",
    "pocos": "Pocos casos",
    "sin_datos": "Sin datos",
}
INDICADORES = ["tendencia", "momento", "macro", "posicionamiento", "ratio"]
NOMBRES = {"tendencia": "Tendencia", "momento": "Momento", "macro": "Entorno macro",
           "posicionamiento": "Posicionamiento", "ratio": "Valoración relativa"}
RATIOS = {  # activo -> (numerador, denominador, etiqueta, invertir)
    "oro": ("oro", "plata", "oro/plata", False),
    "plata": ("oro", "plata", "oro/plata", True),
    "platino": ("platino", "oro", "platino/oro", False),
}


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def fin_de_mes(mes: str) -> date:
    a, m = int(mes[:4]), int(mes[5:7])
    return date(a, m, calendar.monthrange(a, m)[1])


def _hasta(serie: list[tuple[str, float]], fecha: str) -> list[tuple[str, float]]:
    return [x for x in serie if x[0] <= fecha]


def _resumen(valores: list[float]) -> dict | None:
    if not valores:
        return None
    return {"n": len(valores), "media": statistics.mean(valores),
            "mediana": statistics.median(valores),
            "sube": sum(1 for v in valores if v > 0) / len(valores) * 100}


# ---------------------------------------------------------------------------
# Calculo (puro)
# ---------------------------------------------------------------------------
def senales(cfg: dict, mensuales: dict, tipo_real: list, dolar: list, cot: dict,
            anios: int) -> dict:
    """Para cada activo y mes evaluado, los puntos de cada indicador y la lectura."""
    icfg = cfg["indicadores"]
    salida = {}
    for a in cfg["activos"]:
        aid = a["id"]
        serie = mensuales.get(aid) or []
        if len(serie) < 24:
            continue
        ultimo = serie[-1][0]
        inicio = ind.restar_meses(ultimo, anios * 12 - 1)
        filas = []
        for i, (mes, precio) in enumerate(serie):
            if mes < inicio:
                continue
            hist = serie[:i + 1]
            corte = fin_de_mes(mes).isoformat()
            res = [ind.tendencia(hist, precio, icfg["tendencia"]),
                   ind.momento(hist, precio, icfg["momento"])]
            if a.get("macro"):
                tr, dx = _hasta(tipo_real, corte), _hasta(dolar, corte)
                res.append(ind.macro(tr, dx, fin_de_mes(mes), icfg["macro"]))
            res.append(ind.posicionamiento([c for c in cot.get(aid, []) if c["fecha"] <= corte],
                                           icfg["posicionamiento"]))
            if aid in RATIOS:
                num, den, etiqueta, invertir = RATIOS[aid]
                res.append(ind.ratio(_hasta(mensuales[num], mes), _hasta(mensuales[den], mes),
                                     etiqueta, invertir, icfg["ratio"]))
            lectura = ind.combinar(aid, a["nombre"], res, icfg["lectura"])
            filas.append({"mes": mes, "precio": precio, "i": i,
                          "puntos": {r.id: r.puntos for r in res},
                          "total": lectura.total, "lectura": lectura.lectura})
        salida[aid] = filas
    return salida


def calcular(cfg: dict, mensuales: dict, tipo_real: list, dolar: list, cot: dict,
             anios: int = 15, horizontes: tuple = (3, 6, 12)) -> dict:
    """Estadisticas de lo que paso despues de cada senal, por activo e indicador."""
    tabla = senales(cfg, mensuales, tipo_real, dolar, cot, anios)
    activos = {}
    for a in cfg["activos"]:
        aid = a["id"]
        filas = tabla.get(aid)
        if not filas:
            continue
        serie = mensuales[aid]

        def futuro(fila, h):
            j = fila["i"] + h
            return (serie[j][1] / fila["precio"] - 1) * 100 if j < len(serie) else None

        base = {h: _resumen([r for f in filas if (r := futuro(f, h)) is not None]) for h in horizontes}
        indicadores = {}
        for clave in INDICADORES:
            con = [f for f in filas if clave in f["puntos"]]
            if not con:
                continue
            estados = {}
            for p in (1, 0, -1):
                grupo = [f for f in con if f["puntos"][clave] == p]
                estados[str(p)] = {
                    "meses": len(grupo),
                    **{f"h{h}": _resumen([r for f in grupo if (r := futuro(f, h)) is not None])
                       for h in horizontes}}
            disponibles = sum(1 for f in con if f["puntos"][clave] is not None)
            indicadores[clave] = {"estados": estados, "disponibles": disponibles,
                                  "veredicto": veredicto(con, clave, futuro, horizontes)}
        lecturas = {}
        for nombre in ("favorable", "neutral", "desfavorable", "datos insuficientes"):
            grupo = [f for f in filas if f["lectura"] == nombre]
            lecturas[nombre] = {"meses": len(grupo),
                                **{f"h{h}": _resumen([r for f in grupo if (r := futuro(f, h)) is not None])
                                   for h in horizontes}}
        activos[aid] = {"nombre": a["nombre"], "desde": filas[0]["mes"], "hasta": filas[-1]["mes"],
                        "meses": len(filas), "base": {f"h{h}": base[h] for h in horizontes},
                        "indicadores": indicadores, "lecturas": lecturas,
                        "aciertos": aciertos(filas, futuro, horizontes),
                        "serie": [{"mes": f["mes"], "total": f["total"], "lectura": f["lectura"]}
                                  for f in filas]}
    return {"anios": anios, "horizontes": list(horizontes), "activos": activos}


def _diferencia(filas, clave, futuro, horizontes) -> float | None:
    """Media (entre horizontes) de: precio tras +1 menos precio tras -1, en puntos %."""
    difs = []
    for h in horizontes:
        mas = [r for f in filas if f["puntos"].get(clave) == 1 and (r := futuro(f, h)) is not None]
        menos = [r for f in filas if f["puntos"].get(clave) == -1 and (r := futuro(f, h)) is not None]
        if len(mas) >= MINIMO_CASOS and len(menos) >= MINIMO_CASOS:
            difs.append(statistics.mean(mas) - statistics.mean(menos))
    return statistics.mean(difs) if difs else None


MINIMO_CASOS = 6


def veredicto(filas, clave, futuro, horizontes) -> dict:
    """Clasifica un indicador segun lo que paso despues de sus senales.

    Compara el precio tras +1 con el precio tras -1 en todo el periodo y en cada
    mitad por separado (para no fiarse de una sola racha del mercado):
    - "sin_datos"; "rara": menos del 10 % de meses con +1 o -1; "fija": +1 o -1
      en mas del 75 % de los meses (casi siempre la misma senal);
    - "coherente": tras +1 fue mejor que tras -1 en el total y en cada mitad;
    - "al_reves": fue peor en el total y en cada mitad;
    - "inestable": el total y las mitades no apuntan al mismo lado;
    - "pocos": no hay al menos 6 meses de cada senal para comparar.
    """
    con = [f for f in filas if f["puntos"].get(clave) is not None]
    if not con:
        return {"clase": "sin_datos", "senal_pct": 0}
    n_mas = sum(1 for f in con if f["puntos"][clave] == 1)
    n_menos = sum(1 for f in con if f["puntos"][clave] == -1)
    senal_pct = (n_mas + n_menos) / len(con) * 100
    base = {"senal_pct": senal_pct}
    if senal_pct < 10:
        return {"clase": "rara", **base}
    if max(n_mas, n_menos) / len(con) > 0.75:
        return {"clase": "fija", **base}
    mitad = len(con) // 2
    total = _diferencia(con, clave, futuro, horizontes)
    m1 = _diferencia(con[:mitad], clave, futuro, horizontes)
    m2 = _diferencia(con[mitad:], clave, futuro, horizontes)
    base.update(diferencia=total, mitad_1=m1, mitad_2=m2,
                corte=con[mitad]["mes"])
    if total is None:
        return {"clase": "pocos", **base}
    # Todo (total y cada mitad con datos) debe apuntar al mismo lado; si no, el
    # resultado depende de la epoca elegida (o es un efecto de mezclar epocas).
    signos = {x > 0 for x in (total, m1, m2) if x is not None}
    if len(signos) > 1:
        return {"clase": "inestable", **base}
    return {"clase": "coherente" if total > 0 else "al_reves", **base}


def aciertos(filas, futuro, horizontes) -> dict:
    """Porcentaje de lecturas favorables seguidas de subida y desfavorables de bajada."""
    out = {}
    for h in horizontes:
        fav = [r for f in filas if f["lectura"] == "favorable" and (r := futuro(f, h)) is not None]
        des = [r for f in filas if f["lectura"] == "desfavorable" and (r := futuro(f, h)) is not None]
        out[f"h{h}"] = {
            "favorable": {"n": len(fav), "acierto": sum(1 for r in fav if r > 0) / len(fav) * 100} if fav else None,
            "desfavorable": {"n": len(des), "acierto": sum(1 for r in des if r < 0) / len(des) * 100} if des else None,
        }
    return out


# ---------------------------------------------------------------------------
# Datos (red y disco)
# ---------------------------------------------------------------------------
def descargar(cfg: dict, anios: int = 15) -> dict:
    """Trae la historia larga que la web no guarda: FRED y CFTC desde antes del inicio."""
    desde = date.today() - timedelta(days=round((anios + 4) * 365.25))
    clave = os.environ.get("FRED_KEY", "")
    macro = {}
    for s in ("DFII10", "DTWEXBGS"):
        macro[s] = (src.fred_serie(s, clave, desde.isoformat()) if clave
                    else src.fred_csv(s, desde.isoformat()))
    semanas = (anios + 4) * 53
    cot = {a["id"]: src.cftc_posiciones(a["cftc"], semanas) for a in cfg["activos"] if a.get("cftc")}
    entrada = {"macro": macro, "cot": cot, "consultado": iso()}
    escribir("prueba/entrada.json", entrada)
    return entrada


def ejecutar(cfg: dict, descargar_datos: bool = True) -> dict:
    pcfg = cfg.get("prueba_historica", {})
    anios = int(pcfg.get("anios", 15))
    horizontes = tuple(pcfg.get("horizontes", (3, 6, 12)))
    entrada = descargar(cfg, anios) if descargar_datos else (leer("prueba/entrada.json") or {})
    if not entrada:
        raise src.FuenteError("no hay datos guardados para la prueba historica")
    pink = (leer("pink.json", {}) or {}).get("series", {})
    mensuales = {}
    for a in cfg["activos"]:
        factor = ind.LIBRAS_POR_TONELADA if a.get("pink_sheet_unidad") == "tonelada" else 1
        # Solo el Banco Mundial: los cierres propios son pocos y la prueba debe ser repetible
        mensuales[a["id"]] = ind.serie_mensual([tuple(x) for x in pink.get(a.get("pink_sheet") or "", [])],
                                               [], factor)
    resultado = calcular(cfg, mensuales,
                         [tuple(x) for x in entrada["macro"]["DFII10"]],
                         [tuple(x) for x in entrada["macro"]["DTWEXBGS"]],
                         entrada["cot"], anios, horizontes)
    resultado["calculado"] = iso()
    resultado["datos_consultados"] = entrada.get("consultado")
    resultado["parametros"] = cfg["indicadores"]
    escribir("prueba_historica.json", resultado)
    return resultado
