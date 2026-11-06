"""Motor de Cedron: recoge, valida, calcula y guarda. Se ejecuta cada hora."""
from __future__ import annotations

import logging
import os
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import apoyo
from . import indicators as ind
from . import sources as src
from .news import seleccionar
from .store import Estado, ahora, escribir, iso, leer, parse_iso

log = logging.getLogger("cedron")

SALTO_MAXIMO_PCT = 15     # un cambio mayor entre dos consultas se marca "en revision"


def _hoy_madrid(cfg) -> datetime:
    return ahora().astimezone(ZoneInfo(cfg["sitio"]["zona_horaria"]))


# ---------------------------------------------------------------------------
# Precios actuales
# ---------------------------------------------------------------------------
def toca_pedir_precios(cfg, estado: Estado, forzar: bool) -> tuple[bool, str]:
    local = _hoy_madrid(cfg)
    if estado.consultas_mes("metalcharts") >= cfg["presupuesto"]["metalcharts_mensual"]:
        return False, "presupuesto mensual agotado"
    if forzar:
        return True, "forzado"
    if local.weekday() >= 5:
        return False, "fin de semana (mercado cerrado)"
    if local.hour not in cfg["presupuesto"]["metalcharts_horas"]:
        return False, f"no es una hora programada ({local.hour}h)"
    ultima = estado.get("precios_ultima_consulta")
    if ultima and parse_iso(ultima).astimezone(local.tzinfo).strftime("%Y-%m-%d %H") == local.strftime("%Y-%m-%d %H"):
        return False, "ya consultado en esta hora"
    return True, "hora programada"


def actualizar_precios(cfg, estado: Estado, forzar=False) -> None:
    pedir, motivo = toca_pedir_precios(cfg, estado, forzar)
    log.info("Precios: %s (%s)", "se piden" if pedir else "no se piden", motivo)
    if not pedir:
        return
    activos = cfg["activos"]
    try:
        datos = src.metalcharts_precios(os.environ.get("METALCHARTS_KEY", ""),
                                        [a["metalcharts"] for a in activos])
        estado.sumar_consulta("metalcharts")
        estado.set("precios_ultima_consulta", iso())
        estado.registrar_fuente("MetalCharts", True)
    except src.FuenteError as e:
        estado.registrar_fuente("MetalCharts", False, str(e))
        log.warning("MetalCharts: %s", e)
        return

    precios = leer("precios.json", {}) or {}
    pink = leer("pink.json", {}) or {}
    hoy = date.today().isoformat()
    for a in activos:
        d = datos.get(a["metalcharts"])
        if not d:
            continue
        anterior = precios.get(a["id"], {}).get("precio")
        revision = []
        if anterior:
            salto = abs(d["precio"] / anterior - 1) * 100
            if salto > SALTO_MAXIMO_PCT:
                revision.append(f"salto de {salto:.0f}% desde la consulta anterior")
        # Control de unidades: el precio debe parecerse al ultimo mes del Banco Mundial
        serie_pink = pink.get("series", {}).get(a.get("pink_sheet") or "", [])
        if serie_pink:
            factor = ind.LIBRAS_POR_TONELADA if a.get("pink_sheet_unidad") == "tonelada" else 1
            referencia = serie_pink[-1][1] / factor
            if not 0.5 < d["precio"] / referencia < 2:
                revision.append("no cuadra con el histórico del Banco Mundial (posible cambio de unidad)")
        if d.get("obsoleto_segun_fuente"):
            revision.append("la fuente lo marca como desactualizado")
        precios[a["id"]] = {**d, "fuente": "MetalCharts", "consultado": iso(),
                            "estado": "en revisión" if revision else "ok", "motivos": revision}
        if not revision:
            historico = leer(f"historico/{a['id']}.json", []) or []
            historico = [h for h in historico if h[0] != hoy] + [[hoy, d["precio"]]]
            escribir(f"historico/{a['id']}.json", historico[-4000:])
    escribir("precios.json", precios)


# ---------------------------------------------------------------------------
# Datos diarios: Banco Mundial, FRED, CFTC
# ---------------------------------------------------------------------------
def _una_vez_al_dia(estado: Estado, clave: str) -> bool:
    return estado.get(clave) != date.today().isoformat()


def actualizar_diarios(cfg, estado: Estado, forzar=False) -> None:
    hoy = date.today().isoformat()

    # Metales: obligatorios. Materias de apoyo: opcionales (un error en una de ellas
    # nunca debe dejar a los metales sin historico).
    nombres = [a["pink_sheet"] for a in cfg["activos"] if a.get("pink_sheet")]
    opcionales = [n for n in apoyo.series_pink(cfg) if n not in nombres]
    guardadas = (leer("pink.json", {}) or {}).get("series", {})
    faltan = any(n not in guardadas for n in nombres + opcionales)   # p. ej. al anadir una materia
    if forzar or faltan or _una_vez_al_dia(estado, "pink_dia"):
        try:
            series = src.pink_sheet_mensual(nombres, opcionales)
            escribir("pink.json", {"series": series, "consultado": iso(),
                                   "fuente": "Banco Mundial, Commodity Price Data (Pink Sheet), CC BY 4.0"})
            estado.set("pink_dia", hoy)
            estado.registrar_fuente("Banco Mundial", True)
            perdidas = [n for n in opcionales if n not in series]
            if perdidas:
                estado.registrar_fuente("Banco Mundial (materias de apoyo)", False,
                                        "series no encontradas: " + ", ".join(perdidas))
            else:
                estado.registrar_fuente("Banco Mundial (materias de apoyo)", True)
        except src.FuenteError as e:
            estado.registrar_fuente("Banco Mundial", False, str(e))
            log.warning("Banco Mundial: %s", e)

    if forzar or _una_vez_al_dia(estado, "fred_dia"):
        clave = os.environ.get("FRED_KEY", "")
        desde = (date.today() - timedelta(days=365 * 6)).isoformat()
        try:
            macro = {s: src.fred_serie(s, clave, desde) for s in ("DFII10", "DTWEXBGS", "DEXUSEU")}
            escribir("macro.json", {"series": macro, "consultado": iso()})
            estado.set("fred_dia", hoy)
            estado.registrar_fuente("FRED", True)
        except src.FuenteError as e:
            estado.registrar_fuente("FRED", False, str(e))
            log.warning("FRED: %s", e)

    if forzar or _una_vez_al_dia(estado, "cftc_dia"):
        cot = {}
        try:
            for a in cfg["activos"]:
                cot[a["id"]] = src.cftc_posiciones(a["cftc"])
            escribir("cot.json", {"series": cot, "consultado": iso()})
            estado.set("cftc_dia", hoy)
            estado.registrar_fuente("CFTC", True)
        except src.FuenteError as e:
            estado.registrar_fuente("CFTC", False, str(e))
            log.warning("CFTC: %s", e)


# ---------------------------------------------------------------------------
# Noticias
# ---------------------------------------------------------------------------
CONSULTA_NEWSDATA = "gold OR silver OR copper OR platinum OR palladium OR oro OR plata OR cobre"


def actualizar_noticias(cfg, estado: Estado) -> None:
    brutas = leer("noticias_brutas.json", []) or []
    nuevas = []
    for m in cfg["medios"]:
        if not isinstance(m, dict) or not m.get("activo", True) or not m.get("rss"):
            continue
        try:
            for n in src.rss(m["rss"]):
                nuevas.append({**n, "medio": m["nombre"], "idioma": m.get("idioma", "")})
            estado.registrar_fuente(f"RSS {m['nombre']}", True)
        except src.FuenteError as e:
            estado.registrar_fuente(f"RSS {m['nombre']}", False, str(e))
            log.warning("RSS %s: %s", m["nombre"], e)

    if estado.consultas_dia("newsdata") < cfg["presupuesto"]["newsdata_diario"]:
        try:
            nuevas += src.newsdata(os.environ.get("NEWSDATA_KEY", ""), CONSULTA_NEWSDATA)
            estado.sumar_consulta_dia("newsdata")
            estado.registrar_fuente("NewsData.io", True)
        except src.FuenteError as e:
            estado.registrar_fuente("NewsData.io", False, str(e))
            log.warning("NewsData: %s", e)

    limite = iso(ahora() - timedelta(hours=cfg["noticias"]["horas_vigencia"]))
    por_enlace = {n["enlace"]: n for n in brutas + nuevas if (n.get("fecha") or "") >= limite}
    brutas = list(por_enlace.values())
    escribir("noticias_brutas.json", brutas)

    medios = {m["nombre"]: m for m in cfg["medios"]}
    nota_defecto = int(cfg["noticias"].get("nota_medio_desconocido", 50))
    escribir("noticias.json", {"noticias": seleccionar(brutas, cfg["noticias"], medios, nota_defecto),
                               "generado": iso()})


# ---------------------------------------------------------------------------
# Indicadores y lecturas
# ---------------------------------------------------------------------------
def calcular_lecturas(cfg) -> dict:
    icfg = cfg["indicadores"]
    precios = leer("precios.json", {}) or {}
    pink = (leer("pink.json", {}) or {}).get("series", {})
    macro = (leer("macro.json", {}) or {}).get("series", {})
    cot = (leer("cot.json", {}) or {}).get("series", {})

    mensuales = {}
    for a in cfg["activos"]:
        factor = ind.LIBRAS_POR_TONELADA if a.get("pink_sheet_unidad") == "tonelada" else 1
        diario = [tuple(x) for x in (leer(f"historico/{a['id']}.json", []) or [])]
        mensuales[a["id"]] = ind.serie_mensual([tuple(x) for x in pink.get(a.get("pink_sheet") or "", [])],
                                               diario, factor)

    tipo_real = [tuple(x) for x in macro.get("DFII10", [])]
    dolar = [tuple(x) for x in macro.get("DTWEXBGS", [])]
    salida = {}
    for a in cfg["activos"]:
        p = precios.get(a["id"], {})
        precio = p.get("precio") if p.get("estado") == "ok" else None
        origen = "precio actual" if precio is not None else None
        if precio is None and mensuales[a["id"]]:
            precio = mensuales[a["id"]][-1][1]   # sin precio vivo: ultimo dato mensual
            origen = f"media mensual de {mensuales[a['id']][-1][0]}"
        m = mensuales[a["id"]]
        resultados = []
        if precio is not None:
            resultados += [ind.tendencia(m, precio, icfg["tendencia"]),
                           ind.momento(m, precio, icfg["momento"])]
        if a.get("macro"):
            resultados.append(ind.macro(tipo_real, dolar, date.today(), icfg["macro"]))
        resultados.append(ind.posicionamiento(cot.get(a["id"], []), icfg["posicionamiento"]))
        if a["id"] == "oro":
            resultados.append(ind.ratio(mensuales["oro"], mensuales["plata"], "oro/plata", False, icfg["ratio"]))
        elif a["id"] == "plata":
            resultados.append(ind.ratio(mensuales["oro"], mensuales["plata"], "oro/plata", True, icfg["ratio"]))
        elif a["id"] == "platino":
            resultados.append(ind.ratio(mensuales["platino"], mensuales["oro"], "platino/oro", False, icfg["ratio"]))
        lectura = ind.combinar(a["id"], a["nombre"], resultados, icfg["lectura"])
        salida[a["id"]] = {**asdict(lectura), "precio_usado": precio, "precio_origen": origen,
                           "mensual": m[-130:], "calculado": iso()}
    escribir("lecturas.json", salida)

    # Historial publico: una foto al dia por activo (incluye las que luego fallen)
    historial = leer("historial_lecturas.json", []) or []
    hoy = date.today().isoformat()
    historial = [h for h in historial if h["fecha"] != hoy]
    for aid, l in salida.items():
        # solo con precio real del dia: el historial no se rellena con medias
        if l["lectura"] != "datos insuficientes" and l["precio_origen"] == "precio actual":
            historial.append({"fecha": hoy, "activo": aid, "lectura": l["lectura"],
                              "total": l["total"], "precio": l["precio_usado"]})
    escribir("historial_lecturas.json", historial)
    return salida


# ---------------------------------------------------------------------------
# Avisos de salud
# ---------------------------------------------------------------------------
def revisar_salud(cfg, estado: Estado) -> list[str]:
    # Los medios desactivados en config.yaml dejan de contar (y se olvida su historial)
    inactivos = {f"RSS {m['nombre']}" for m in cfg["medios"] if not m.get("activo", True)}
    # Igual con las fuentes de materias de apoyo que ya no usa ninguna materia
    # (p. ej. los carburantes del Ministerio, sustituidos por el boletin europeo)
    inactivos |= apoyo.fuentes_sin_uso(cfg)
    fuentes = estado.get("fuentes", {})
    for f in inactivos:
        fuentes.pop(f, None)
    avisos = []
    for fuente, info in sorted(fuentes.items()):
        if info.get("fallos_seguidos", 0) >= 3:
            avisos.append(f"- **{fuente}** lleva {info['fallos_seguidos']} fallos seguidos. "
                          f"Último error: {info.get('ultimo_error', '?')}")
    return avisos


def ejecutar(cfg, forzar=False) -> list[str]:
    estado = Estado()
    actualizar_diarios(cfg, estado, forzar)
    actualizar_precios(cfg, estado, forzar)
    apoyo.recoger(cfg, estado, forzar)
    actualizar_noticias(cfg, estado)
    calcular_lecturas(cfg)
    estado.set("ultima_ejecucion", iso())
    avisos = revisar_salud(cfg, estado)
    estado.guardar()
    return avisos
