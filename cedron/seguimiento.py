"""Seguimiento diario del historial de previsiones (10-nov-2026).

Las previsiones se apuntan una vez al mes (cadena.py y prevision.py) y nunca se
reescriben. Este modulo, cada dia:
  1. pone el resultado real a las que ya han vencido, en cuanto se publica el dato;
  2. resume el historial para la pagina «Previsiones»: cuantas hay, cuantas han vencido,
     y si acertamos mas que «lo habitual» y que los futuros.

Una prevision cuenta como «hecha a tiempo» solo si su mes de vencimiento es posterior al
mes en que se apunto. Las demas (el dato llega con meses de retraso y el plazo ya habia
pasado al apuntarla) se separan: se parecen a adivinar un dato ya ocurrido pero sin
publicar y no deben mezclarse con las previsiones de verdad.
"""
from __future__ import annotations

import logging
import math

from cedron import apoyo, cadena, prevision
from cedron import indicators as ind
from cedron.store import escribir, iso, leer

log = logging.getLogger("cedron.seguimiento")

ARCHIVOS = {"cadena": "cadena_previsiones.json", "metales": "metales_previsiones.json",
            "apoyo": "apoyo_previsiones.json"}
APUNTADA_ANTIGUA = "2026-11-10"      # las primeras se apuntaron antes de guardar la fecha


def apuntada(r: dict) -> str:
    return (r.get("apuntada") or APUNTADA_ANTIGUA)[:7]


def a_tiempo(r: dict) -> bool:
    return r["vence"] > apuntada(r)


# ---------------------------------------------------------------------------
# Series con las que se comprueba cada prevision (las mismas que se previeron)
# ---------------------------------------------------------------------------
def series_metales(cfg: dict) -> dict[str, dict]:
    pink = (leer("pink.json", {}) or {}).get("series", {})
    out = {}
    for a in cfg["activos"]:
        factor = ind.LIBRAS_POR_TONELADA if a.get("pink_sheet_unidad") == "tonelada" else 1
        serie = ind.serie_mensual([tuple(x) for x in pink.get(a.get("pink_sheet") or "", [])], [], factor)
        out[a["id"]] = {m: v for m, v in serie if v and v > 0}
    return out


def series_apoyo(cfg: dict) -> dict[str, dict]:
    acfg = cfg.get("apoyo", {})
    fuentes = apoyo.cargar_fuentes()
    cambio = apoyo.TipoCambio(apoyo.cambio_usd())
    out = {}
    for g in acfg.get("grupos", []):
        for m in g.get("materias", []):
            for a, amb in (m.get("ambitos") or {}).items():
                try:
                    s = apoyo.serie_ambito(amb, fuentes, cfg, cambio, acfg.get("en_euros", True))
                except (KeyError, ValueError, ZeroDivisionError):
                    continue
                out[f"{m['id']}:{a}"] = {f: v for f, v in apoyo.mensualizar(s["serie"]) if v and v > 0}
    return out


def series_cadena(cfg: dict) -> dict[str, dict]:
    cambio = apoyo.TipoCambio(apoyo.cambio_usd())
    out = {}
    for c in (cfg.get("cadena") or {}).get("cadenas", []):
        for e in c.get("eslabones", []):
            out[e["id"]] = cadena.cargar_serie(e["abajo"]["serie"], cambio, e["abajo"].get("en_euros", False))
    return out


def rellenar(registro: list[dict], series: dict[str, dict]) -> int:
    """Pone el cambio real a las previsiones vencidas con dato publicado. Devuelve cuantas."""
    n = 0
    for r in registro:
        if r.get("real") is not None or not r.get("base"):
            continue
        ident = r["id"][len("futuros:"):] if r["id"].startswith("futuros:") else r["id"]
        serie = series.get(ident) or {}
        if r["vence"] in serie:
            r["real"] = (serie[r["vence"]] / r["base"] - 1) * 100
            r["comprobada"] = iso()[:10]
            n += 1
    return n


def revisar(cfg: dict) -> dict:
    """Rellena los resultados reales de los tres historiales y escribe el resumen."""
    cargar = {"cadena": series_cadena, "metales": series_metales, "apoyo": series_apoyo}
    registros = {}
    for grupo, archivo in ARCHIVOS.items():
        registro = leer(archivo, []) or []
        if registro:
            nuevas = rellenar(registro, cargar[grupo](cfg))
            if nuevas:
                escribir(archivo, registro)
                log.info("Historial %s: %d previsiones comprobadas", grupo, nuevas)
        registros[grupo] = registro
    resumen = resumir(registros)
    escribir("previsiones_resumen.json", resumen)
    return resumen


# ---------------------------------------------------------------------------
# Resumen para la pagina
# ---------------------------------------------------------------------------
def _medir(lista: list[dict]) -> dict:
    hechas = [r for r in lista if r.get("real") is not None]
    if not hechas:
        return {"n": 0}
    def acierto(r, k):
        return (r[k] > 0) == (r["real"] > 0)
    out = {"n": len(hechas),
           "aciertos": sum(acierto(r, "previsto") for r in hechas),
           "aciertos_habitual": sum(acierto(r, "habitual") for r in hechas if r.get("habitual") is not None),
           "error": sum(abs(r["previsto"] - r["real"]) for r in hechas) / len(hechas)}
    # Cuando las noticias de esa semana apuntaban claramente a un lado (mas titulares al alza
    # que a la baja, o al reves), ¿acertaron la direccion? ¿y nuestra prevision en esos casos?
    con_not = [r for r in hechas if r.get("noticias") and r["noticias"].get("alza", 0) != r["noticias"].get("baja", 0)]
    if con_not:
        out["con_noticias"] = len(con_not)
        out["aciertos_noticias"] = sum(1 for r in con_not if (r["noticias"]["alza"] > r["noticias"]["baja"]) == (r["real"] > 0))
        out["aciertos_nuestra_con_noticias"] = sum(1 for r in con_not if acierto(r, "previsto"))
    con_hab = [r for r in hechas if r.get("habitual") is not None]
    if con_hab:
        out["error_habitual"] = sum(abs(r["habitual"] - r["real"]) for r in con_hab) / len(con_hab)
        out["mejor_que_habitual"] = sum(1 for r in con_hab if abs(r["previsto"] - r["real"]) < abs(r["habitual"] - r["real"]))
    return out


def resumir(registros: dict[str, list[dict]]) -> dict:
    grupos = {}
    calendario: dict[str, int] = {}
    for grupo, registro in registros.items():
        propias = [r for r in registro if not r["id"].startswith("futuros:")]
        futuros = [r for r in registro if r["id"].startswith("futuros:")]
        bloques = {}
        for nombre, lista in (("nuestras", propias), ("futuros", futuros)):
            if not lista:
                continue
            bloques[nombre] = {
                "apuntadas": len(lista),
                "a_tiempo": sum(1 for r in lista if a_tiempo(r)),
                "pendientes": sum(1 for r in lista if a_tiempo(r) and r.get("real") is None),
                "plazos": {str(p): _medir([r for r in lista if a_tiempo(r) and r["plazo"] == p]) for p in (3, 12)},
                "atrasadas": _medir([r for r in lista if not a_tiempo(r)]),
            }
        # Comparacion justa con los futuros: solo las mismas materias, plazo y mes de partida
        pares = []
        por_clave = {(r["id"], r["plazo"], r["desde"]): r for r in propias}
        for f in futuros:
            p = por_clave.get((f["id"][len("futuros:"):], f["plazo"], f["desde"]))
            if p and p.get("real") is not None and f.get("real") is not None and a_tiempo(p):
                pares.append((p, f))
        if pares:
            bloques["frente_futuros"] = {
                "n": len(pares),
                "nuestra": sum(1 for p, f in pares if (p["previsto"] > 0) == (p["real"] > 0)),
                "futuros": sum(1 for p, f in pares if (f["previsto"] > 0) == (f["real"] > 0)),
                "nuestra_mas_cerca": sum(1 for p, f in pares if abs(p["previsto"] - p["real"]) < abs(f["previsto"] - f["real"]))}
        grupos[grupo] = bloques
        for r in registro:
            if a_tiempo(r) and r.get("real") is None:
                calendario[r["vence"]] = calendario.get(r["vence"], 0) + 1
    return {"grupos": grupos, "calendario": sorted(calendario.items())[:18], "actualizado": iso()}
