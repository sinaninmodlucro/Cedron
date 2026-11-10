"""Previsiones por combinacion de calculos sencillos.

Lo que la investigacion dice sobre prever precios de materias primas (10-nov-2026):

- Es muy dificil mejorar a las reglas tontas: "seguira como siempre" (media historica) o
  "no cambiara" (Alquist, Kilian y Vigfusson 2013; Welch y Goyal 2008).
- Lo que mejor aguanta fuera de muestra no es un modelo grande, sino la MEDIA de varios
  calculos pequenos, cada uno con una sola idea (Bates y Granger 1969; Timmermann 2006;
  Rapach, Strauss y Zhou 2010; Baumeister y Kilian 2015 para el petroleo). Pesos
  iguales: estimar los pesos suele empeorar.
- Cada calculo se estima solo con datos anteriores y su prevision se recorta al rango de
  lo ya visto (restricciones de sensatez de Campbell y Thompson 2008).
- Los bancos centrales (BCE, Fed, FMI) usan ademas los precios de los futuros; no hay
  una fuente gratuita con licencia para mostrarlos, asi que aqui no se usan.

Para un precio y un plazo de h meses, cada calculo es una regresion directa
    ln P[n+h] - ln P[n] = a + b * rasgos[n]
(Marcellino, Stock y Watson 2006), reestimada cada enero con lo ya conocido. La prevision
es la media simple de la media historica y de todos los calculos disponibles.

La prueba a ciegas compara esa prevision con la media historica (R2 fuera de muestra,
con margen por remuestreo de bloques de 12 meses) y con "no cambiara", y cuenta cuantas
veces acerto si el precio subia o bajaba.
"""
from __future__ import annotations

import logging
import math
import os
import random

from cedron import cadena
from cedron import indicators as ind
from cedron.store import escribir, iso, leer

log = logging.getLogger("cedron.prevision")

VERSION = 3
MINIMO = 36           # casos minimos para estimar un calculo


def num(mes: str) -> int:
    return int(mes[:4]) * 12 + int(mes[5:7]) - 1


def mes(n: int) -> str:
    return f"{n // 12:04d}-{n % 12 + 1:02d}"


def _r2(casos, k=2) -> float | None:
    """R2 fuera de muestra frente a la columna k (2 = media historica); k=None = 'no cambiara'."""
    if len(casos) < 24:
        return None
    sse_m = sum((c[0] - c[1]) ** 2 for c in casos)
    sse_b = sum((c[0] - (c[k] if k is not None else 0.0)) ** 2 for c in casos)
    return 1 - sse_m / sse_b if sse_b else None


MINIMO_CASOS_SEGURO = 96    # con menos de 8 anios de casos nunca se dice «con seguridad» (10-nov-2026)


def evaluar_casos(casos: list[tuple], remuestreos: int = 300, semilla: int = 2026) -> dict:
    """casos: [(real, prevision, media historica)]. Lo que se publica de una prueba a ciegas."""
    r2 = _r2(casos)
    ic = None
    if r2 is not None and remuestreos:
        rng = random.Random(semilla)
        n, vals = len(casos), []
        for _ in range(remuestreos):
            muestra = []
            while len(muestra) < n:
                j = rng.randrange(0, max(n - 12, 1))
                muestra.extend(casos[j:j + 12])
            v = _r2(muestra[:n])
            if v is not None:
                vals.append(v)
        vals.sort()
        if vals:
            ic = (vals[int(len(vals) * 0.025)], vals[int(len(vals) * 0.975) - 1])

    def _signo(k):
        return sum(1 for c in casos if (c[k] > 0) == (c[0] > 0)) / len(casos) if casos else None
    return {"r2": r2, "intervalo": ic, "casos": len(casos), "r2_sin_cambio": _r2(casos, None),
            "acierto_direccion": _signo(1), "acierto_base": _signo(2),
            "valido": bool(r2 is not None and r2 > 0 and ic and ic[0] > 0 and len(casos) >= MINIMO_CASOS_SEGURO)}


def combinar(lp: dict[int, float], rasgos: dict[str, dict[int, list[float]]], h: int, inicio: int,
             externas: dict[str, dict[int, float]] | None = None, ultimo: int | None = None,
             remuestreos: int = 300, semilla: int = 2026, criba: bool = False) -> dict:
    """Prueba a ciegas y prevision actual de la combinacion.

    criba (probada el 10-nov-2026 y NO usada): en cada mes solo entran en la media los
    calculos que hasta entonces han acertado mas que la media historica (combinacion
    recortada, Timmermann 2006; seleccion dinamica, Aye y otros 2015). En los 51 eslabones
    comprobados de la cadena fue peor que la media a partes iguales (a un anio, 3 previsiones
    que mejoran con seguridad frente a 15), como avisa la investigacion.

    lp: {mes en numero: ln precio}. rasgos: {calculo: {mes: [valores conocidos ese mes]}}.
    externas: {calculo: {mes: desviacion prevista sobre la media historica}} (calculos que
    no son una regresion, como el traslado pendiente). inicio: primer mes de la prueba.
    """
    externas = externas or {}
    ys = {n: lp[n + h] - lp[n] for n in lp if n + h in lp}
    orden = sorted(ys)
    estado = {"anio": None, "betas": {}}

    def prever(t: int, final: bool = False):
        pasado = [ys[n] for n in orden if n + h <= t]
        if len(pasado) < MINIMO:
            return None
        media, lo, hi = sum(pasado) / len(pasado), min(pasado), max(pasado)
        if estado["anio"] != t // 12:
            estado["anio"], estado["betas"] = t // 12, {}
            for k, r in rasgos.items():
                filas = [(r[n], ys[n]) for n in orden if n + h <= t and n in r]
                if len(filas) >= MINIMO:
                    beta, _ = cadena.mco([[1.0] + list(x) for x, _ in filas], [y for _, y in filas])
                    if beta:
                        estado["betas"][k] = beta
        piezas = {}
        for k, r in rasgos.items():
            b = estado["betas"].get(k)
            x = r.get(t)
            if x is None and final and r and max(r) > t:
                # Prevision de hoy de un precio que se publica con retraso: vale el dato mas
                # reciente que ya se conoce (p. ej. la curva de futuros de hoy). Nunca en la prueba.
                x = r[max(r)]
            if b and x is not None:
                piezas[k] = min(max(b[0] + sum(c * v for c, v in zip(b[1:], x)), lo), hi)
        for k, e in externas.items():
            if t in e:
                piezas[k] = min(max(media + e[t], lo), hi)
        buenas = {k: v for k, v in piezas.items() if not criba or _va_bien(k, t)}
        return media, piezas, (media + sum(buenas.values())) / (1 + len(buenas)), sorted(buenas)

    hechas: dict[str, list[tuple]] = {k: [] for k in list(rasgos) + list(externas)}   # (mes, prevision, media)

    def _va_bien(k: str, t: int) -> bool:
        vencidas = [(ys[s], p, m) for s, p, m in hechas[k] if s + h <= t]
        if len(vencidas) < 24:
            return False
        return sum((y - p) ** 2 for y, p, _ in vencidas) < sum((y - m) ** 2 for y, _, m in vencidas)

    casos, por_calculo = [], {k: [] for k in hechas}
    for t in sorted(n for n in lp if n >= orden[0]):
        p = prever(t)
        if p is None:
            continue
        media, piezas, combo, _ = p
        for k, v in piezas.items():
            hechas[k].append((t, v, media))
        if t < inicio or t not in ys:
            continue
        casos.append((ys[t], combo, media))
        for k, v in piezas.items():
            por_calculo[k].append((ys[t], v, media))
    prueba = evaluar_casos(casos, remuestreos, semilla)
    prueba["horizonte"] = h
    prueba["desde"] = mes(inicio)
    prueba["calculos"] = {k: {"r2": _r2(v), "casos": len(v)} for k, v in por_calculo.items()}
    salida = {"prueba": prueba, "casos": por_calculo}
    ultimo = max(lp) if ultimo is None else ultimo
    estado["anio"] = None                      # la prevision de hoy usa todo lo conocido
    p = prever(ultimo, final=True)
    if p:
        salida["prevision"] = {"media": p[0], "piezas": p[1], "total": p[2], "usadas": p[3]}
    return salida


# ---------------------------------------------------------------------------
# Metales
# ---------------------------------------------------------------------------
# Series de FRED con historia larga (ninguna necesita clave en el formato CSV):
# divisas de paises que exportan materias primas (Chen, Rogoff y Rossi 2010), divisas
# principales (valor del dolar), tipo a 10 anios e IPC de EE. UU. (tipo real).
FRED_MATERIAS = {"DEXUSAL": 1, "DEXUSNZ": 1, "DEXCAUS": -1}      # 1 = dolares por divisa; -1 = al reves
FRED_DOLAR = {"DEXUSUK": -1, "DEXJPUS": 1, "DEXSZUS": 1}         # 1 = divisa por dolar
FRED_TIPOS = ("GS10", "CPIAUCSL")


def _mensual(pares) -> dict[int, float]:
    d: dict[int, list[float]] = {}
    for f, v in pares:
        if v is not None and v > 0:
            d.setdefault(num(str(f)[:7]), []).append(float(v))
    return {n: sum(v) / len(v) for n, v in d.items()}


def _cesta(series: dict, signos: dict, meses: int) -> dict[int, float]:
    """Cambio medio (en log) de una cesta de divisas en 'meses' meses."""
    logs = [{n: s * math.log(v) for n, v in _mensual(series.get(k, [])).items()} for k, s in signos.items()]
    out = {}
    for n in set().union(*logs) if logs else ():
        vals = [l[n] - l[n - meses] for l in logs if n in l and n - meses in l]
        if len(vals) == len(logs):
            out[n] = sum(vals) / len(vals)
    return out


def rasgos_metal(lp: dict[int, float], macro: dict, lp_otro: dict[int, float] | None = None) -> dict:
    """Rasgos de un metal. Todos usan datos hasta el mes ANTERIOR (un mes de separacion:
    las medias mensuales crean una inercia falsa, efecto Working 1960)."""
    r: dict[str, dict[int, list[float]]] = {"tendencia": {}, "valor": {}}
    for n in lp:
        if n - 1 in lp and n - 13 in lp:
            r["tendencia"][n] = [lp[n - 1] - lp[n - 13]]          # Moskowitz, Ooi y Pedersen 2012
        viejo = [lp[j] for j in range(n - 66, n - 53) if j in lp]
        if n - 1 in lp and len(viejo) == 13:
            r["valor"][n] = [lp[n - 1] - sum(viejo) / 13]         # Asness, Moskowitz y Pedersen 2013
    divisas, dolar = _cesta(macro, FRED_MATERIAS, 3), _cesta(macro, FRED_DOLAR, 3)
    r["divisas"] = {n + 1: [v] for n, v in divisas.items()}
    r["dolar"] = {n + 1: [v] for n, v in dolar.items()}
    tipo, ipc = _mensual(macro.get("GS10", [])), _mensual(macro.get("CPIAUCSL", []))
    real = {n: tipo[n] - 100 * (ipc[n] / ipc[n - 12] - 1) for n in tipo if n in ipc and n - 12 in ipc}
    r["tipo_real"] = {n + 1: [real[n] - real[n - 12]] for n in real if n - 12 in real}
    if lp_otro:
        ratio = {n: lp[n] - lp_otro[n] for n in lp if n in lp_otro}
        r["ratio"] = {}
        for n in ratio:
            ventana = [ratio[j] for j in range(n - 120, n) if j in ratio]
            if n - 1 in ratio and len(ventana) >= 100:
                r["ratio"][n] = [ratio[n - 1] - sum(ventana) / len(ventana)]
    return r


NOMBRES = {"tendencia": "la tendencia del último año", "valor": "lo caro o barato que está frente a hace cinco años",
           "divisas": "las divisas de países exportadores", "dolar": "el dólar", "tipo_real": "los tipos de interés reales",
           "ratio": "la relación entre el oro y la plata", "traslado": "el traslado pendiente",
           "inercia": "la inercia del propio precio", "desfase": "el desfase con el precio de arriba"}


def _pct(x: float) -> float:
    return (math.exp(x) - 1) * 100


def prever_metal(lp: dict[int, float], rasgos: dict, plazos, corte: str, remuestreos: int = 300,
                 criba: bool = False) -> dict:
    out = {}
    for h in plazos:
        c = combinar(lp, rasgos, h, num(corte), remuestreos=remuestreos, criba=criba)
        if "prevision" not in c:
            continue
        p, u = c["prevision"], max(lp)
        out[str(h)] = {"total": _pct(p["total"]), "habitual": _pct(p["media"]),
                       "piezas": {k: _pct(v) for k, v in p["piezas"].items()}, "usadas": p["usadas"],
                       "desde_mes": mes(u), "vence": mes(u + h), "base": math.exp(lp[u]),
                       "prueba": c["prueba"]}
    return out


def descargar(cfg: dict) -> dict:
    from cedron import indices
    from cedron import sources as src
    indices.descargar()        # futuros de la EIA e indices de noticias (para los calculos extra)
    clave = os.environ.get("FRED_KEY", "")
    macro = {}
    for s in list(FRED_MATERIAS) + list(FRED_DOLAR) + list(FRED_TIPOS):
        diario = src.fred_serie(s, clave, "1971-01-01") if clave else src.fred_csv(s, "1971-01-01")
        # solo se guarda la media de cada mes (las divisas son diarias desde 1971)
        macro[s] = [[mes(n), round(v, 5)] for n, v in sorted(_mensual(diario).items())]
    entrada = {"macro": macro, "consultado": iso()}
    escribir("prevision/entrada.json", entrada)
    return entrada


def ejecutar(cfg: dict, descargar_datos: bool = True) -> dict:
    """Previsiones de los metales con historia larga. Escribe data/metales_prevision.json y
    apunta cada prevision en data/metales_previsiones.json (historial propio)."""
    pcfg = (cfg.get("previsiones") or {}).get("metales") or {}
    entrada = descargar(cfg) if descargar_datos else (leer("prevision/entrada.json") or {})
    macro = entrada.get("macro") or {}
    pink = (leer("pink.json", {}) or {}).get("series", {})
    desde = num(str(pcfg.get("desde", "1976-01")))
    logs = {}
    for a in cfg["activos"]:
        if a["id"] not in pcfg.get("activos", []):
            continue
        factor = ind.LIBRAS_POR_TONELADA if a.get("pink_sheet_unidad") == "tonelada" else 1
        serie = ind.serie_mensual([tuple(x) for x in pink.get(a.get("pink_sheet") or "", [])], [], factor)
        logs[a["id"]] = {num(m): math.log(v) for m, v in serie if v and v > 0 and num(m) >= desde}
    registro = leer("metales_previsiones.json", []) or []
    from cedron.news import balance_reciente
    recientes = balance_reciente(cfg["noticias"])
    activos = {}
    for aid, lp in logs.items():
        if len(lp) < 240:
            continue
        otro = logs.get({"oro": "plata", "plata": "oro"}.get(aid, ""))
        previsiones = prever_metal(lp, rasgos_metal(lp, macro, otro), pcfg.get("plazos", (3, 12)),
                                   str(pcfg.get("corte", "2006-01")), int(pcfg.get("remuestreos", 300)),
                                   bool(pcfg.get("criba", False)))
        precios = {mes(n): math.exp(v) for n, v in lp.items()}
        cadena.anotar_previsiones(registro, aid, previsiones, precios, recientes.get(aid))
        activos[aid] = {"previsiones": previsiones, "historial": cadena.resumen_previsiones(registro, aid),
                        "futuros": futuros_de(aid, previsiones, registro, precios)}
    resultado = {"activos": activos, "calculado": iso(), "datos_consultados": entrada.get("consultado"),
                 "corte": str(pcfg.get("corte", "2006-01"))}
    escribir("metales_prevision.json", resultado)
    escribir("metales_previsiones.json", registro)
    return resultado


# ---------------------------------------------------------------------------
# Materias primas de apoyo (10-nov-2026)
# ---------------------------------------------------------------------------
def rasgos_generales(lp: dict[int, float], macro: dict, con_dolar: bool) -> dict:
    """Tendencia del ultimo anio, valor frente a hace cinco anios, inercia de tres meses y,
    en los precios mundiales, el dolar y las divisas de paises exportadores. Todos con datos
    hasta el mes anterior (un mes de separacion, como en los metales)."""
    r = rasgos_metal(lp, macro if con_dolar else {})
    r["inercia"] = {n: [lp[n - 1] - lp[n - 4]] for n in lp if n - 1 in lp and n - 4 in lp}
    if not con_dolar:
        for k in ("divisas", "dolar", "tipo_real"):
            r.pop(k, None)
    else:
        r.pop("tipo_real", None)     # los tipos reales se probaron para los metales; aqui no hay razon
    return {k: v for k, v in r.items() if v}


def estacion_ciega(lp: dict[int, float], h: int) -> dict[int, float]:
    """Calculo de temporada: cuanto cambia de media este precio en los h meses que empiezan
    en el mismo mes del anio, frente a su cambio medio de cualquier mes. Solo con cambios ya
    conocidos en cada momento y con al menos 5 anios del mismo mes (frutas, hortalizas,
    huevos, electricidad... tienen temporadas marcadas)."""
    ys = {n: lp[n + h] - lp[n] for n in lp if n + h in lp}
    out = {}
    for t in lp:
        pasado = [(n, y) for n, y in ys.items() if n + h <= t]
        mismo = [y for n, y in pasado if n % 12 == t % 12]
        if len(mismo) >= 5:
            out[t] = sum(mismo) / len(mismo) - sum(y for _, y in pasado) / len(pasado)
    return out


NOMBRES["estacion"] = "la temporada (lo que suele cambiar en estos meses del año)"


def calculos_extra(grupo: str, clave: str) -> dict:
    """Calculos que superaron la prueba a ciegas solo en algunos precios y plazos (10-nov-2026):
    la pendiente de la curva de futuros del petroleo, a 3 meses, en el petroleo y en los
    eslabones de la cadena que parten del Brent. Devuelve {plazo: {calculo: rasgo}}."""
    from cedron import indices
    petroleo = (grupo == "apoyo" and clave.split(":")[0] in ("brent", "wti")) or                (grupo == "cadena" and clave == "pink:Crude oil, Brent")
    if not petroleo:
        return {}
    series = (leer("prevision/indices.json", {}) or {}).get("series") or {}
    if not series.get("wti_c1"):
        return {}
    return {3: {"futuros_petroleo": indices.pendiente_futuros(series, "wti")}}


NOMBRES["futuros_petroleo"] = "la curva de futuros del petróleo"


def prever_serie(lp: dict[int, float], rasgos: dict, plazos, inicio: int, remuestreos: int = 300,
                 extra_por_plazo: dict | None = None) -> dict:
    out = {}
    for h in plazos:
        r = {**rasgos, **((extra_por_plazo or {}).get(h) or {})}
        c = combinar(lp, r, h, inicio, {"estacion": estacion_ciega(lp, h)}, remuestreos=remuestreos)
        if "prevision" not in c or c["prueba"]["r2"] is None:
            continue
        p, u = c["prevision"], max(lp)
        out[str(h)] = {"total": _pct(p["total"]), "habitual": _pct(p["media"]),
                       "piezas": {k: _pct(v) for k, v in p["piezas"].items()}, "usadas": p["usadas"],
                       "desde_mes": mes(u), "vence": mes(u + h), "base": math.exp(lp[u]),
                       "prueba": c["prueba"]}
    return out


def ejecutar_apoyo(cfg: dict) -> dict:
    """Previsiones de cada materia de apoyo y cada ambito con historia suficiente. Escribe
    data/apoyo_prevision.json y el historial propio en data/apoyo_previsiones.json."""
    from cedron import apoyo
    pcfg = (cfg.get("previsiones") or {}).get("apoyo") or {}
    acfg = cfg.get("apoyo", {})
    minimo = int(pcfg.get("minimo_meses", 120))
    plazos = pcfg.get("plazos", (3, 12))
    remuestreos = int(pcfg.get("remuestreos", 300))
    macro = (leer("prevision/entrada.json") or {}).get("macro") or {}
    fuentes = apoyo.cargar_fuentes()
    cambio = apoyo.TipoCambio(apoyo.cambio_usd())
    registro = leer("apoyo_previsiones.json", []) or []
    from cedron.news import balance_reciente
    recientes = balance_reciente(cfg["noticias"])
    materias = {}
    for g in acfg.get("grupos", []):
        for m in g.get("materias", []):
            for a, amb in (m.get("ambitos") or {}).items():
                try:
                    s = apoyo.serie_ambito(amb, fuentes, cfg, cambio, acfg.get("en_euros", True))
                except (KeyError, ValueError, ZeroDivisionError) as e:
                    log.warning("Prevision %s/%s: %s", m["id"], a, e)
                    continue
                lp = {num(f): math.log(v) for f, v in apoyo.mensualizar(s["serie"]) if v and v > 0}
                if len(lp) < minimo or max(lp) < num(iso()[:7]) - 18:      # poca historia o serie parada
                    continue
                orden = sorted(lp)
                inicio = orden[max(len(orden) // 2, 60)]
                previsiones = prever_serie(lp, rasgos_generales(lp, macro, a == "global"), plazos,
                                           inicio, remuestreos, calculos_extra("apoyo", f"{m['id']}:{a}"))
                if not previsiones:
                    continue
                ident = f"{m['id']}:{a}"
                materia = (cfg["noticias"].get("materia_de_apoyo") or {}).get(m["id"])
                cadena.anotar_previsiones(registro, ident, previsiones, {mes(n): math.exp(v) for n, v in lp.items()},
                                          recientes.get(f"m:{materia}") if materia else None)
                fut = futuros_de(m["id"], previsiones, registro, {mes(n): math.exp(v) for n, v in lp.items()},
                                 f"futuros:{ident}") if a == "global" else None
                materias.setdefault(m["id"], {})[a] = {
                    "previsiones": previsiones, "historial": cadena.resumen_previsiones(registro, ident),
                    "futuros": fut,
                    "unidad": s["unidad"], "corte": mes(inicio)}
    resultado = {"materias": materias, "calculado": iso()}
    escribir("apoyo_prevision.json", resultado)
    escribir("apoyo_previsiones.json", registro)
    return resultado


def futuros_de(ident: str, previsiones: dict, registro: list, precios: dict, clave: str | None = None) -> dict | None:
    """Lo que descuentan los futuros a 3 y 12 meses y, para compararlo con nuestra
    prevision, se apunta en el mismo historial (id «futuros:...») con la misma base."""
    from cedron import sources as src
    c = ((leer("futuros.json", {}) or {}).get("contratos") or {}).get(ident)
    if not c or not c.get("curva"):
        return None
    curva = [tuple(x) for x in c["curva"]]
    hoy_mes = c["consultado"][:7]
    salida = {"consultado": c["consultado"], "plazos": {}}
    para_anotar = {}
    for k, p in previsiones.items():
        imp = src.implicito(curva, hoy_mes, int(k))
        if imp:
            salida["plazos"][k] = imp
            para_anotar[k] = {**p, "total": imp["cambio"]}
    if not salida["plazos"]:
        return None
    clave = clave or f"futuros:{ident}"
    cadena.anotar_previsiones(registro, clave, para_anotar, precios)
    salida["historial"] = cadena.resumen_previsiones(registro, clave)
    return salida
