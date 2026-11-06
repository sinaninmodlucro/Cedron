"""Prueba historica de las reglas de Cedron (fase 4 del plan).

Aplica, mes a mes, los mismos indicadores que usa la web (cedron/indicators.py,
con los parametros de config.yaml) a toda la historia disponible, usando en cada
mes SOLO los datos que existian entonces, y mira que paso despues con el precio.
No es una estrategia de inversion ni simula compras: solo comprueba si las
senales tenian relacion con lo que ocurrio despues.

Para que el resultado sea fiable (ver la pagina de metodologia):
- Un mes de separacion entre la senal y la medicion. El Banco Mundial publica
  medias mensuales, y las medias crean una inercia aparente entre un mes y el
  siguiente (Working, 1960); saltarse un mes la elimina.
- Prueba a ciegas: el periodo se parte en dos (antes y despues de `corte`). Una
  regla solo se considera coherente si funciona en los dos por separado; el
  segundo periodo hace de comprobacion de lo que se veria eligiendo con el primero.
- Margen de error: remuestreo por bloques de 12 meses (los meses seguidos se
  parecen entre si y los periodos de medicion se solapan, asi que no son casos
  independientes). Si el intervalo de confianza (95 %) incluye el cero, el
  efecto no se distingue de la casualidad.
- Reglas candidatas: variantes de config.yaml que se prueban igual, sin usarse
  en la web, para decidir cambios con datos.

calcular() es pura (sin red ni disco); descargar() trae la historia larga.
"""
from __future__ import annotations

import calendar
import copy
import logging
import os
import random
import statistics
from datetime import date

from cedron import indicators as ind
from cedron import sources as src
from cedron.store import escribir, iso, leer

log = logging.getLogger("cedron.prueba")

INDICADORES = ["tendencia", "momento", "macro", "posicionamiento", "ratio"]
NOMBRES = {"tendencia": "Tendencia", "momento": "Momento", "macro": "Entorno macro",
           "posicionamiento": "Posicionamiento", "ratio": "Valoración relativa",
           "suma": "Lectura (suma)"}
CLASES = {
    "coherente": "Coherente",
    "debil": "Apunta bien, sin seguridad",
    "sin_efecto": "Apunta al revés, sin seguridad",
    "al_reves": "Al revés",
    "inestable": "Inestable",
    "fija": "Casi siempre la misma señal",
    "rara": "Casi nunca da señal",
    "pocos": "Pocos casos",
    "sin_datos": "Sin datos",
}
RATIOS = {  # activo -> (numerador, denominador, etiqueta, invertir)
    "oro": ("oro", "plata", "oro/plata", False),
    "plata": ("oro", "plata", "oro/plata", True),
    "platino": ("platino", "oro", "platino/oro", False),
}
VERSION = 3            # subirla al cambiar el metodo: la prueba se repite en la siguiente ejecucion
MINIMO_CASOS = 6       # meses de cada senal (+1 y -1) para poder comparar
BLOQUE = 12            # meses por bloque en el remuestreo


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


def lectura_de(puntos: dict, quitar: set, cfg_lectura: dict) -> int | None:
    """Lectura como +1/0/-1 (None sin datos suficientes), igual que indicators.combinar."""
    validos = [v for k, v in puntos.items() if v is not None and k not in quitar]
    if len(validos) < 3:
        return None
    total = sum(validos)
    return 1 if total >= cfg_lectura["favorable_desde"] else -1 if total <= cfg_lectura["desfavorable_hasta"] else 0


def _fusionar(base: dict, cambios: dict) -> dict:
    salida = copy.deepcopy(base)
    for k, v in (cambios or {}).items():
        if isinstance(v, dict) and isinstance(salida.get(k), dict):
            salida[k] = _fusionar(salida[k], v)
        else:
            salida[k] = v
    return salida


# ---------------------------------------------------------------------------
# Senales mes a mes (puro)
# ---------------------------------------------------------------------------
def senales(cfg: dict, mensuales: dict, tipo_real: list, dolar: list, cot: dict,
            anios: int, nuevos: dict | None = None, capacidad: list | None = None) -> dict:
    """Para cada activo y mes evaluado, los puntos de cada indicador.

    `nuevos`: parametros de los indicadores del metodo en estudio (si se dan, se
    calculan tambien); `capacidad`: serie de actividad industrial para "actividad".
    """
    icfg = cfg["indicadores"]
    nuevos = nuevos or {}
    salida = {}
    for a in cfg["activos"]:
        aid = a["id"]
        serie = mensuales.get(aid) or []
        if len(serie) < 24:
            continue
        inicio = ind.restar_meses(serie[-1][0], anios * 12 - 1)
        cot_a = cot.get(aid, [])
        filas = []
        for i, (mes, precio) in enumerate(serie):
            if mes < inicio:
                continue
            hist = serie[:i + 1]
            corte = fin_de_mes(mes).isoformat()
            res = [ind.tendencia(hist, precio, icfg["tendencia"]),
                   ind.momento(hist, precio, icfg["momento"])]
            if a.get("macro"):
                res.append(ind.macro(_hasta(tipo_real, corte), _hasta(dolar, corte),
                                     fin_de_mes(mes), icfg["macro"]))
            res.append(ind.posicionamiento([c for c in cot_a if c["fecha"] <= corte],
                                           icfg["posicionamiento"]))
            if aid in RATIOS:
                num, den, etiqueta, invertir = RATIOS[aid]
                res.append(ind.ratio(_hasta(mensuales[num], mes), _hasta(mensuales[den], mes),
                                     etiqueta, invertir, icfg["ratio"]))
            if "tendencia_plazos" in nuevos:
                res.append(ind.tendencia_plazos(hist, precio, nuevos["tendencia_plazos"]))
            if "valor" in nuevos:
                res.append(ind.valor(hist, precio, nuevos["valor"]))
            if "actividad" in nuevos and capacidad:
                res.append(ind.actividad(capacidad, mes, nuevos["actividad"]))
            filas.append({"mes": mes, "precio": precio, "i": i,
                          "puntos": {r.id: r.puntos for r in res}})
        salida[aid] = filas
    return salida


# ---------------------------------------------------------------------------
# Estadistica (pura)
# ---------------------------------------------------------------------------
def _diferencia(filas, clave, futuros, horizontes) -> float | None:
    """Media (entre horizontes) de: cambio tras +1 menos cambio tras -1, en puntos %."""
    difs = []
    for h in horizontes:
        mas = [r for f in filas if f["puntos"].get(clave) == 1 and (r := futuros[f["i"]].get(h)) is not None]
        menos = [r for f in filas if f["puntos"].get(clave) == -1 and (r := futuros[f["i"]].get(h)) is not None]
        if len(mas) >= MINIMO_CASOS and len(menos) >= MINIMO_CASOS:
            difs.append(statistics.mean(mas) - statistics.mean(menos))
    return statistics.mean(difs) if difs else None


def intervalo(filas, clave, futuros, horizontes, remuestreos: int, semilla: int,
              confianza: float = 95) -> tuple | None:
    """Intervalo de confianza de la diferencia, remuestreando bloques de meses seguidos."""
    n = len(filas)
    if n < BLOQUE * 3 or remuestreos <= 0:
        return None
    rng = random.Random(semilla)
    bloques = -(-n // BLOQUE)
    valores = []
    for _ in range(remuestreos):
        muestra = []
        for _ in range(bloques):
            j = rng.randrange(0, n - BLOQUE + 1)
            muestra.extend(filas[j:j + BLOQUE])
        d = _diferencia(muestra[:n], clave, futuros, horizontes)
        if d is not None:
            valores.append(d)
    if len(valores) < remuestreos * 0.8:
        return None
    valores.sort()
    cola = (100 - confianza) / 200
    return valores[int(len(valores) * cola)], valores[int(len(valores) * (1 - cola)) - 1]


def veredicto(filas, clave, futuros, horizontes, corte: str,
              remuestreos: int = 0, semilla: int = 2026, confianza: float = 95) -> dict:
    """Clasifica una senal segun lo que paso despues.

    - "sin_datos"; "rara": +1 o -1 en menos del 10 % de los meses; "fija": +1 o -1
      en mas del 75 % (casi siempre la misma senal); "pocos": no hay 6 meses de
      cada senal para comparar.
    - "inestable": el periodo de eleccion y el de comprobacion apuntan a lados
      distintos (o el total contradice a los dos).
    - Si todo apunta al mismo lado: "coherente" o "al_reves" si el intervalo de
      confianza no incluye el cero; si lo incluye, "debil" (apunta bien) o
      "sin_efecto" (apunta al reves), sin seguridad.
    """
    con = [f for f in filas if f["puntos"].get(clave) is not None]
    if not con:
        return {"clase": "sin_datos", "senal_pct": 0}
    n_mas = sum(1 for f in con if f["puntos"][clave] == 1)
    n_menos = sum(1 for f in con if f["puntos"][clave] == -1)
    senal_pct = (n_mas + n_menos) / len(con) * 100
    base = {"senal_pct": senal_pct, "desde": con[0]["mes"], "meses": len(con)}
    if senal_pct < 10:
        return {"clase": "rara", **base}
    if max(n_mas, n_menos) / len(con) > 0.75:
        return {"clase": "fija", **base}
    total = _diferencia(con, clave, futuros, horizontes)
    eleccion = _diferencia([f for f in con if f["mes"] < corte], clave, futuros, horizontes)
    comprobacion = _diferencia([f for f in con if f["mes"] >= corte], clave, futuros, horizontes)
    base.update(diferencia=total, eleccion=eleccion, comprobacion=comprobacion,
                a_ciegas=eleccion is not None and comprobacion is not None)
    if total is None:
        return {"clase": "pocos", **base}
    signos = {x > 0 for x in (total, eleccion, comprobacion) if x is not None}
    if len(signos) > 1:
        return {"clase": "inestable", **base}
    ic = intervalo(con, clave, futuros, horizontes, remuestreos, semilla, confianza)
    base["intervalo"] = ic
    seguro = ic is not None and (ic[0] > 0 or ic[1] < 0)
    if total > 0:
        return {"clase": "coherente" if seguro else "debil", **base}
    return {"clase": "al_reves" if seguro else "sin_efecto", **base}


def _futuros(serie, filas, horizontes, salto) -> dict:
    """Cambio del precio h meses despues, empezando `salto` meses tras la senal."""
    out = {}
    for f in filas:
        j0 = f["i"] + salto
        out[f["i"]] = {h: (serie[j0 + h][1] / serie[j0][1] - 1) * 100
                       for h in horizontes if j0 + h < len(serie)}
    return out


def _estados(filas, clave, futuros, horizontes) -> dict:
    estados = {}
    for p in (1, 0, -1):
        grupo = [f for f in filas if f["puntos"].get(clave) == p]
        estados[str(p)] = {"meses": len(grupo),
                           **{f"h{h}": _resumen([r for f in grupo if (r := futuros[f["i"]].get(h)) is not None])
                              for h in horizontes}}
    return estados


def evaluar(cfg: dict, tabla: dict, mensuales: dict, horizontes, salto, corte, remuestreos,
            semilla, quitar: dict | None = None, claves: list | None = None,
            confianza: float = 95) -> dict:
    """Estadisticas por activo: cada indicador (o solo `claves`) y la lectura (suma)."""
    quitar = quitar or {}
    activos = {}
    for a in cfg["activos"]:
        aid = a["id"]
        filas = tabla.get(aid)
        if not filas:
            continue
        fut = _futuros(mensuales[aid], filas, horizontes, salto)
        q = set(quitar.get(aid, []))
        for f in filas:
            f["puntos"]["suma"] = lectura_de({k: v for k, v in f["puntos"].items() if k in INDICADORES},
                                             q, cfg["indicadores"]["lectura"])
        base = {f"h{h}": _resumen([r for f in filas if (r := fut[f["i"]].get(h)) is not None])
                for h in horizontes}
        indicadores = {}
        for clave in (claves if claves is not None else INDICADORES) + ["suma"]:
            if not any(clave in f["puntos"] for f in filas):
                continue
            indicadores[clave] = {
                "estados": _estados(filas, clave, fut, horizontes),
                "veredicto": veredicto(filas, clave, fut, horizontes, corte, remuestreos,
                                       semilla + len(indicadores), confianza)}
        activos[aid] = {"nombre": a["nombre"], "desde": filas[0]["mes"], "hasta": filas[-1]["mes"],
                        "meses": len(filas), "base": base, "indicadores": indicadores,
                        "quitados": sorted(q)}
    return activos


# ---------------------------------------------------------------------------
# Metodo en estudio: probabilidad historica (pura)
# ---------------------------------------------------------------------------
def _clase(total, eleccion, comprobacion, ic) -> str:
    """Misma clasificacion que veredicto() para una medida donde > 0 es bueno."""
    if total is None:
        return "pocos"
    if len({x > 0 for x in (total, eleccion, comprobacion) if x is not None}) > 1:
        return "inestable"
    seguro = ic is not None and (ic[0] > 0 or ic[1] < 0)
    if total > 0:
        return "coherente" if seguro else "debil"
    return "al_reves" if seguro else "sin_efecto"


def _mejora_brier(casos) -> float | None:
    """Mejora frente a la frecuencia general: 1 - Brier(modelo) / Brier(frecuencia general)."""
    if len(casos) < 24:
        return None
    bm = sum((c["p"] - c["y"]) ** 2 for c in casos)
    bb = sum((c["b"] - c["y"]) ** 2 for c in casos)
    return 1 - bm / bb if bb else None


def probabilidades(filas: list, estado_de, futuros: dict, h: int, salto: int, previa: float,
                   minimo: int) -> list[dict]:
    """Probabilidad de subida a h meses calculada en cada mes SOLO con el pasado.

    En el mes t solo se conocen los resultados de los meses cuyo plazo ya ha
    terminado (j + salto + h <= t). La probabilidad de un estado es su frecuencia
    de subidas, acercada a la frecuencia general con `previa` casos ficticios
    (cuando hay pocos casos del estado, manda la frecuencia general).
    """
    salida, conocidos = [], 0
    cuentas: dict = {}
    total_n = total_k = 0
    for t, f in enumerate(filas):
        while conocidos < t and filas[conocidos]["i"] + salto + h <= f["i"]:
            g = filas[conocidos]
            y = futuros[g["i"]].get(h)
            e = estado_de(g)
            if y is not None:
                total_n += 1
                total_k += y > 0
                if e is not None:
                    n, k = cuentas.get(e, (0, 0))
                    cuentas[e] = (n + 1, k + (y > 0))
            conocidos += 1
        e = estado_de(f)
        y = futuros[f["i"]].get(h)
        if e is None or total_n < minimo:
            salida.append({"mes": f["mes"], "estado": e, "p": None, "b": None, "y": None, "n": 0})
            continue
        b = total_k / total_n
        n, k = cuentas.get(e, (0, 0))
        salida.append({"mes": f["mes"], "estado": e, "p": (k + previa * b) / (n + previa), "b": b,
                       "y": None if y is None else int(y > 0), "n": n})
    return salida


def evaluar_probabilidad(previsiones: list, corte: str, remuestreos: int, semilla: int,
                         confianza: float) -> dict:
    casos = [c for c in previsiones if c["p"] is not None and c["y"] is not None]
    total = _mejora_brier(casos)
    eleccion = _mejora_brier([c for c in casos if c["mes"] < corte])
    comprobacion = _mejora_brier([c for c in casos if c["mes"] >= corte])
    ic = None
    if total is not None and remuestreos > 0 and len(casos) >= BLOQUE * 3:
        rng = random.Random(semilla)
        n, valores = len(casos), []
        for _ in range(remuestreos):
            muestra = []
            for _ in range(-(-n // BLOQUE)):
                j = rng.randrange(0, n - BLOQUE + 1)
                muestra.extend(casos[j:j + BLOQUE])
            v = _mejora_brier(muestra[:n])
            if v is not None:
                valores.append(v)
        if len(valores) >= remuestreos * 0.8:
            valores.sort()
            cola = (100 - confianza) / 200
            ic = (valores[int(len(valores) * cola)], valores[int(len(valores) * (1 - cola)) - 1])
    # Calibracion: lo que se dijo frente a lo que paso
    tramos = [(0, 0.45), (0.45, 0.55), (0.55, 0.65), (0.65, 1.01)]
    calibracion = []
    for a, b in tramos:
        g = [c for c in casos if a <= c["p"] < b]
        if g:
            calibracion.append({"desde": a, "hasta": min(b, 1), "n": len(g),
                                "dicho": statistics.mean(c["p"] for c in g) * 100,
                                "pasado": statistics.mean(c["y"] for c in g) * 100})
    return {"clase": _clase(total, eleccion, comprobacion, ic), "mejora": total,
            "eleccion": eleccion, "comprobacion": comprobacion, "intervalo": ic,
            "casos": len(casos), "desde": casos[0]["mes"] if casos else None,
            "calibracion": calibracion}


def evaluar_metodo(metodo: dict, cfg: dict, tabla: dict, mensuales: dict, horizontes, salto, corte,
                   remuestreos, semilla, confianza) -> dict:
    """Evalua el metodo en estudio frente al actual, con la misma vara de medir."""
    h = int(metodo.get("horizonte", 12))
    previa = float(metodo.get("previa", 12))
    minimo = int(metodo.get("minimo_casos", 60))
    min_ind = int(metodo.get("min_indicadores", 2))
    cl = cfg["indicadores"]["lectura"]
    activos = {}
    for a in cfg["activos"]:
        aid = a["id"]
        lista = (metodo.get("indicadores") or {}).get(aid)
        filas = tabla.get(aid)
        if not lista or not filas:
            continue
        fut = _futuros(mensuales[aid], filas, tuple(horizontes), salto)

        def estado_nuevo(f, lista=lista):
            v = [f["puntos"].get(k) for k in lista]
            v = [x for x in v if x is not None]
            return sum(v) if len(v) >= min_ind else None

        def estado_actual(f):
            return lectura_de({k: v for k, v in f["puntos"].items() if k in INDICADORES}, set(), cl)

        for f in filas:
            e = estado_nuevo(f)
            f["puntos"]["metodo"] = None if e is None else (1 if e > 0 else -1 if e < 0 else 0)
        indicadores = {}
        for clave in [k for k in lista if k not in INDICADORES] + ["metodo"]:
            if any(f["puntos"].get(clave) is not None for f in filas):
                indicadores[clave] = {"estados": _estados(filas, clave, fut, horizontes),
                                      "veredicto": veredicto(filas, clave, fut, horizontes, corte,
                                                             remuestreos, semilla + len(indicadores),
                                                             confianza)}
        prev_nuevo = probabilidades(filas, estado_nuevo, fut, h, salto, previa, minimo)
        prev_actual = probabilidades(filas, estado_actual, fut, h, salto, previa, minimo)
        # Situaciones parecidas (toda la historia) y la de ahora
        por_estado = {}
        for f in filas:
            e, y = estado_nuevo(f), fut[f["i"]].get(h)
            if e is None or y is None:
                continue
            por_estado.setdefault(e, []).append(y)
        situaciones = [{"estado": e, "n": len(v), "sube": sum(1 for x in v if x > 0) / len(v) * 100,
                        "media": statistics.mean(v)} for e, v in sorted(por_estado.items())]
        ultimo = prev_nuevo[-1] if prev_nuevo else None
        activos[aid] = {
            "nombre": a["nombre"], "lista": lista, "indicadores": indicadores,
            "probabilidad": evaluar_probabilidad(prev_nuevo, corte, remuestreos, semilla, confianza),
            "probabilidad_actual": evaluar_probabilidad(prev_actual, corte, remuestreos, semilla, confianza),
            "situaciones": situaciones, "ahora": ultimo}
    return {"texto": metodo.get("texto", ""), "horizonte": h, "previa": previa, "activos": activos}


def calcular(cfg: dict, mensuales: dict, tipo_real: list, dolar: list, cot: dict,
             anios: int = 50, horizontes: tuple = (3, 6, 12), salto: int = 1,
             corte: str = "2006-01", remuestreos: int = 500, semilla: int = 2026,
             candidatas: dict | None = None, confianza: float = 95,
             metodo: dict | None = None, capacidad: list | None = None) -> dict:
    """Prueba completa: reglas actuales, cada regla candidata y el metodo en estudio."""
    nuevos = (metodo or {}).get("parametros") or {}
    tabla = senales(cfg, mensuales, tipo_real, dolar, cot, anios, nuevos, capacidad)
    actual = evaluar(cfg, tabla, mensuales, horizontes, salto, corte, remuestreos, semilla,
                     confianza=confianza)
    resultado_candidatas = {}
    for nombre, c in (candidatas or {}).items():
        cambios = c.get("indicadores") or {}
        quitar = c.get("quitar") or {}
        if isinstance(quitar, list):          # una lista vale para todos los metales
            quitar = {a["id"]: quitar for a in cfg["activos"]}
        if cambios:
            cfg_c = {**cfg, "indicadores": _fusionar(cfg["indicadores"], cambios)}
            tabla_c = senales(cfg_c, mensuales, tipo_real, dolar, cot, anios, nuevos, capacidad)
        else:
            cfg_c = cfg
            tabla_c = {k: [{**f, "puntos": dict(f["puntos"])} for f in v] for k, v in tabla.items()}
        resultado_candidatas[nombre] = {
            "texto": c.get("texto", nombre),
            "activos": evaluar(cfg_c, tabla_c, mensuales, horizontes, salto, corte, remuestreos,
                               semilla, quitar, claves=list(cambios), confianza=confianza)}
    resultado_metodo = (evaluar_metodo(metodo, cfg, tabla, mensuales, horizontes, salto, corte,
                                       remuestreos, semilla, confianza) if metodo else None)
    return {"anios": anios, "horizontes": list(horizontes), "salto": salto, "corte": corte,
            "remuestreos": remuestreos, "confianza": confianza, "activos": actual,
            "candidatas": resultado_candidatas, "metodo": resultado_metodo}


# ---------------------------------------------------------------------------
# Datos (red y disco)
# ---------------------------------------------------------------------------
def descargar(cfg: dict) -> dict:
    """Trae la historia larga que la web no guarda: FRED y CFTC completos."""
    clave = os.environ.get("FRED_KEY", "")
    desde = "1990-01-01"      # DFII10 empieza en 2003 y DTWEXBGS en 2006
    # CAPUTLG331S: utilizacion de la capacidad en metales primarios de EE. UU. (desde 1967)
    macro = {}
    for s in ("DFII10", "DTWEXBGS", "CAPUTLG331S"):
        inicio = "1960-01-01" if s == "CAPUTLG331S" else desde
        macro[s] = src.fred_serie(s, clave, inicio) if clave else src.fred_csv(s, inicio)
    # El informe Legacy de la CFTC llega hasta 1986: unas 2.100 semanas
    cot = {a["id"]: src.cftc_posiciones(a["cftc"], 2200) for a in cfg["activos"] if a.get("cftc")}
    entrada = {"macro": macro, "cot": cot, "consultado": iso()}
    escribir("prueba/entrada.json", entrada)
    return entrada


def ejecutar(cfg: dict, descargar_datos: bool = True) -> dict:
    pcfg = cfg.get("prueba_historica", {})
    entrada = descargar(cfg) if descargar_datos else (leer("prueba/entrada.json") or {})
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
                         entrada["cot"],
                         anios=int(pcfg.get("anios", 50)),
                         horizontes=tuple(pcfg.get("horizontes", (3, 6, 12))),
                         salto=int(pcfg.get("salto_meses", 1)),
                         corte=str(pcfg.get("corte", "2006-01")),
                         remuestreos=int(pcfg.get("remuestreos", 500)),
                         candidatas=pcfg.get("candidatas") or {},
                         confianza=float(pcfg.get("confianza", 95)),
                         metodo=pcfg.get("metodo_nuevo"),
                         capacidad=[tuple(x) for x in entrada["macro"].get("CAPUTLG331S", [])])
    resultado["calculado"] = iso()
    resultado["datos_consultados"] = entrada.get("consultado")
    resultado["parametros"] = cfg["indicadores"]
    escribir("prueba_historica.json", resultado)
    return resultado
