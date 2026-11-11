"""IPC del INE por producto y «La cesta» (11-nov-2026).

- recoger(): baja una vez al dia los indices mensuales de config.yaml (seccion 'ipc') y,
  una vez al mes, las ponderaciones oficiales. Se guarda en data/ipc.json.
- de_materia(): lo que ha subido en la tienda segun el IPC frente al precio en origen.
- cesta(): indice de alimentos y energia con las ponderaciones del INE, que productos
  empujan mas y las series que usa la cesta personal (que se calcula en el navegador).
"""
from __future__ import annotations

import logging
from datetime import date

from . import indicators as ind
from . import sources as src
from .store import Estado, escribir, iso, leer

log = logging.getLogger("cedron.ipc")
ARCHIVO = "ipc.json"
NOMBRE_ESTADO = "INE (IPC)"
GRUPOS_CESTA = {"alimentos": "Alimentos y bebidas", "energia": "Energía del hogar y carburantes"}


def recoger(cfg: dict, estado: Estado, forzar: bool = False) -> None:
    icfg = cfg.get("ipc") or {}
    if not icfg.get("series"):
        return
    hoy = date.today().isoformat()
    if not forzar and estado.get("ipc_dia") == hoy:
        return
    guardado = leer(ARCHIVO, {}) or {}
    series = guardado.get("series", {})
    try:
        pedidas = [("general", icfg["general"])] + [(s["id"], s["serie"]) for s in icfg["series"]]
        for ident, codigo in pedidas:
            nuevo = src.ine_serie(codigo, 400 if ident not in series else 14)
            por_mes = {f: v for f, v in series.get(ident, [])}
            por_mes.update(dict(nuevo))
            series[ident] = [[f, por_mes[f]] for f in sorted(por_mes)]
        pesos, pesos_mes = guardado.get("pesos", {}), guardado.get("pesos_mes")
        if forzar or pesos_mes != hoy[:7] or not pesos:
            pesos, pesos_mes = src.ine_pesos(icfg.get("tablas_pesos") or []), hoy[:7]
        escribir(ARCHIVO, {"series": series, "pesos": pesos, "pesos_mes": pesos_mes, "consultado": iso()})
        estado.set("ipc_dia", hoy)
        estado.registrar_fuente(NOMBRE_ESTADO, True)
    except src.FuenteError as e:
        estado.registrar_fuente(NOMBRE_ESTADO, False, str(e))
        log.warning("INE: %s", e)


def _cambio(serie: dict, mes: str, meses: int) -> float | None:
    a, b = serie.get(mes), serie.get(ind.restar_meses(mes, meses))
    return (a / b - 1) * 100 if a and b else None


def _peso(s: dict, pesos: dict) -> float | None:
    return pesos.get(src.normalizar_ine(s.get("peso_nombre") or s["nombre"]))


def de_materia(cfg: dict, datos: dict | None = None) -> dict[str, list[dict]]:
    """Por materia: [{nombre, mes, anual, mensual}] de cada serie del IPC que la acompana."""
    datos = datos if datos is not None else (leer(ARCHIVO) or {})
    out: dict[str, list[dict]] = {}
    for s in (cfg.get("ipc") or {}).get("series", []):
        serie = dict(map(tuple, (datos.get("series") or {}).get(s["id"], [])))
        if not s.get("materia") or not serie:
            continue
        mes = max(serie)
        out.setdefault(s["materia"], []).append({
            "id": s["id"], "nombre": s.get("etiqueta") or s["nombre"], "mes": mes, "indice": serie[mes],
            "anual": _cambio(serie, mes, 12), "mensual": _cambio(serie, mes, 1),
            "serie": serie})
    return out


def origen_frente_tienda(ipc_m: dict, mensual_origen: list | None) -> dict | None:
    """Cambio en un anio en origen (media mensual de Espana) en el mismo mes que el IPC."""
    if not mensual_origen:
        return None
    origen = dict(mensual_origen)
    mes = ipc_m["mes"] if ipc_m["mes"] in origen else max(origen)
    anual = _cambio(origen, mes, 12)
    if anual is None:
        return None
    tienda = _cambio(ipc_m["serie"], mes, 12)
    return {"mes": mes, "origen": anual, "tienda": tienda, "mismo_mes": mes == ipc_m["mes"]}


def cesta(cfg: dict, datos: dict | None = None, anios: int = 11) -> dict | None:
    """Indice de alimentos y energia con las ponderaciones oficiales del INE."""
    datos = datos if datos is not None else (leer(ARCHIVO) or {})
    series_g = datos.get("series") or {}
    pesos = datos.get("pesos") or {}
    items, fuera = [], []
    for s in (cfg.get("ipc") or {}).get("series", []):
        if not s.get("cesta"):
            continue
        serie = dict(map(tuple, series_g.get(s["id"], [])))
        w = _peso(s, pesos)
        if not serie or not w:
            fuera.append(s.get("etiqueta") or s["nombre"])
            continue
        items.append({"id": s["id"], "nombre": s.get("etiqueta") or s["nombre"], "grupo": s["cesta"],
                      "peso": w, "serie": serie, "materia": s.get("materia")})
    if not items:
        return None
    # Meses en que todos los productos tienen dato
    comunes = sorted(set.intersection(*(set(i["serie"]) for i in items)))
    if len(comunes) < 13:
        return None
    mes = comunes[-1]

    def indice(lista, m):
        tot = sum(i["peso"] for i in lista)
        return sum(i["peso"] * i["serie"][m] for i in lista) / tot

    grupos = {}
    for g, nombre in GRUPOS_CESTA.items():
        lista = [i for i in items if i["grupo"] == g]
        if lista:
            grupos[g] = lista
    filas = []
    total_peso = sum(i["peso"] for i in items)
    hace = ind.restar_meses(mes, 12)
    base_total = indice(items, hace) if hace in comunes else None
    for i in items:
        a = _cambio(i["serie"], mes, 12)
        # Aportacion al cambio anual de la cesta, en puntos porcentuales
        aporta = (i["peso"] * (i["serie"][mes] - i["serie"][hace]) / (total_peso * base_total) * 100
                  if base_total and hace in i["serie"] else None)
        filas.append({**{k: v for k, v in i.items() if k != "serie"}, "anual": a,
                      "mensual": _cambio(i["serie"], mes, 1), "aporta": aporta,
                      "peso_pct": i["peso"] / total_peso * 100})
    filas.sort(key=lambda f: -(f["aporta"] or 0))

    def resumen(lista):
        serie = {m: indice(lista, m) for m in comunes}
        return {"anual": _cambio(serie, mes, 12), "mensual": _cambio(serie, mes, 1),
                "serie": [[m, round(serie[m], 3)] for m in comunes[-12 * anios:]]}

    general = dict(map(tuple, series_g.get("general", [])))
    desde = comunes[-12 * anios] if len(comunes) > 12 * anios else comunes[0]
    return {"mes": mes, "total": resumen(items),
            "grupos": {g: {"nombre": GRUPOS_CESTA[g], **resumen(lista),
                           "peso_pct": sum(i["peso"] for i in lista) / total_peso * 100}
                       for g, lista in grupos.items()},
            "general": {"anual": _cambio(general, mes, 12), "mensual": _cambio(general, mes, 1)} if general else None,
            "filas": filas, "fuera": fuera, "peso_total": total_peso, "pesos_mes": datos.get("pesos_mes"),
            # Para la cesta personal (en el navegador): indices mensuales desde 'desde'
            "personal": {"meses": [m for m in comunes if m >= desde],
                         "items": [{"id": i["id"], "nombre": i["nombre"], "grupo": i["grupo"],
                                    "peso": round(i["peso"], 3),
                                    "serie": [round(i["serie"][m], 3) for m in comunes if m >= desde]}
                                   for i in items],
                         "general": [round(general[m], 3) if m in general else None for m in comunes if m >= desde]}}
