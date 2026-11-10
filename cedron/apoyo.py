"""Materias primas de APOYO: energia, ganaderia y (mas adelante) agricolas,
fertilizantes y metales industriales.

No tienen lectura favorable/desfavorable. Para cada materia y ambito (Espana,
Europa, global) se guarda su serie de precios y se calcula un resumen
descriptivo: ultimo dato, cambio frente al dato anterior, cambio interanual y
posicion frente a su media de 10 meses.

Todo se configura en config.yaml, seccion 'apoyo'.
"""
from __future__ import annotations

import calendar
import logging
import os
from datetime import date, timedelta

from . import sources as src
from .store import Estado, escribir, iso, leer

log = logging.getLogger("cedron")

AMBITOS = ("espana", "europa", "global")
NOMBRES_AMBITO = {"espana": "España", "europa": "Europa", "global": "Global"}
ANIOS_HISTORIA = 10          # anos de historia diaria que se guardan de FRED
ANIOS_MAPA_INICIAL = 5       # anos que se descargan del MAPA la primera vez


# ---------------------------------------------------------------------------
# Recorrido de la configuracion
# ---------------------------------------------------------------------------
def materias(cfg) -> list[dict]:
    return [m for g in cfg.get("apoyo", {}).get("grupos", []) for m in g.get("materias", [])]


def _definiciones(cfg):
    """Todas las definiciones de serie: ambitos, sus historias y sus precios en tienda."""
    for m in materias(cfg):
        for amb in m.get("ambitos", {}).values():
            yield amb
            if amb.get("historia"):
                yield amb["historia"]
            if amb.get("tienda"):
                yield {"fuente": "panel", **amb["tienda"]}
            if amb.get("referencia"):
                yield amb["referencia"]


def _fuentes_de(cfg, tipo: str, clave: str) -> list[str]:
    """Valores de 'clave' de todas las definiciones que usan la fuente 'tipo'."""
    salida = []
    for d in _definiciones(cfg):
        if d.get("fuente") == tipo and d.get(clave) and d[clave] not in salida:
            salida.append(d[clave])
    return salida


def _canales_panel(cfg, d: dict) -> tuple[str, str]:
    p = cfg.get("panel", {})
    return d.get("canal") or p.get("canal", "SUPERMERCADO"), d.get("canal_respaldo") or p.get("canal_respaldo", "T.ESPAÑA")


def pares_panel(cfg) -> list[tuple[str, str]]:
    pares = []
    for d in _definiciones(cfg):
        if d.get("fuente") == "panel":
            for canal in _canales_panel(cfg, d):
                if (d["producto"], canal) not in pares:
                    pares.append((d["producto"], canal))
    return pares


# Nombre con el que cada tipo de fuente se registra en el estado (avisos de salud)
NOMBRE_ESTADO = {"carburantes": "Ministerio (carburantes)", "boletin": "Comisión Europea (Oil Bulletin)",
                 "mapa": "MAPA (precios semanales)", "panel": "MAPA (panel de consumo)",
                 "pagados": "MAPA (precios pagados)", "percibidos": "MAPA (precios percibidos)", "fred": "FRED (materias de apoyo)",
                 "eurostat": "Eurostat (precios industriales)"}


def fuentes_sin_uso(cfg) -> set[str]:
    """Nombres de estado de las fuentes de apoyo que ninguna materia usa ya."""
    usadas = {d.get("fuente") for d in _definiciones(cfg)}
    return {nombre for tipo, nombre in NOMBRE_ESTADO.items() if tipo not in usadas}


def series_pink(cfg) -> list[str]:
    return _fuentes_de(cfg, "pink", "serie")


# ---------------------------------------------------------------------------
# Recogida (con red). Cada fuente guarda su copia en data/apoyo/<fuente>.json
# ---------------------------------------------------------------------------
def _fusionar(antigua: list, nueva: list) -> list:
    por_fecha = {f: v for f, v in antigua}
    por_fecha.update({f: v for f, v in nueva})
    return [[f, por_fecha[f]] for f in sorted(por_fecha)]


def _una_vez_al_dia(estado: Estado, clave: str) -> bool:
    return estado.get(clave) != date.today().isoformat()


def recoger(cfg, estado: Estado, forzar: bool = False) -> None:
    hoy = date.today()

    # Carburantes en Espana: cada hora (el Ministerio actualiza varias veces al dia)
    campos = _fuentes_de(cfg, "carburantes", "campo")
    if campos:
        try:
            d = src.carburantes_media(campos)
            guardado = leer("apoyo/carburantes.json", {}) or {}
            dia = d["fecha"][:10]
            series = guardado.get("series", {})
            for campo, (valor, n) in d["medias"].items():
                series[campo] = _fusionar(series.get(campo, []), [[dia, round(valor, 4)]])[-4000:]
            escribir("apoyo/carburantes.json", {"series": series, "dato": d["fecha"], "consultado": iso(),
                                                "estaciones": {c: n for c, (_, n) in d["medias"].items()}})
            estado.registrar_fuente("Ministerio (carburantes)", True)
        except src.FuenteError as e:
            estado.registrar_fuente("Ministerio (carburantes)", False, str(e))
            log.warning("Carburantes: %s", e)

    # Weekly Oil Bulletin: una vez al dia (se publica los lunes o martes)
    columnas = _fuentes_de(cfg, "boletin", "columna")
    if columnas and (forzar or _una_vez_al_dia(estado, "apoyo_boletin_dia")):
        try:
            series = src.boletin_petroleo(columnas)
            escribir("apoyo/boletin.json", {"series": {c: [list(x) for x in s] for c, s in series.items()},
                                            "consultado": iso()})
            estado.set("apoyo_boletin_dia", hoy.isoformat())
            estado.registrar_fuente("Comisión Europea (Oil Bulletin)", True)
        except src.FuenteError as e:
            estado.registrar_fuente("Comisión Europea (Oil Bulletin)", False, str(e))
            log.warning("Oil Bulletin: %s", e)

    # MAPA: una vez al dia; el Excel trae solo el ano en curso, asi que se acumula
    productos = _fuentes_de(cfg, "mapa", "producto")
    if productos and (forzar or _una_vez_al_dia(estado, "apoyo_mapa_dia")):
        try:
            guardado = leer("apoyo/mapa.json", {}) or {}
            series = guardado.get("series", {})
            vacio = any(p not in series for p in productos)     # producto nuevo: baja su historia
            anios = list(range(hoy.year - ANIOS_MAPA_INICIAL, hoy.year + 1)) if vacio else \
                ([hoy.year - 1, hoy.year] if hoy.month == 1 else [hoy.year])
            nuevas = src.mapa_semanal(productos, anios)
            for p in productos:
                series[p] = _fusionar(series.get(p, []), [list(x) for x in nuevas.get(p, [])])
            escribir("apoyo/mapa.json", {"series": series, "consultado": iso()})
            estado.set("apoyo_mapa_dia", hoy.isoformat())
            estado.registrar_fuente("MAPA (precios semanales)", True)
        except src.FuenteError as e:
            estado.registrar_fuente("MAPA (precios semanales)", False, str(e))
            log.warning("MAPA: %s", e)

    # Panel de consumo (precio en tienda): una vez al dia. El ano anterior se sigue
    # leyendo porque el MAPA publica su diciembre meses despues.
    pares = pares_panel(cfg)
    if pares and (forzar or _una_vez_al_dia(estado, "apoyo_panel_dia")):
        try:
            guardado = leer("apoyo/panel.json", {}) or {}
            series = guardado.get("series", {})
            vacio = any(f"{p}|{c}" not in series for p, c in pares)    # producto nuevo: baja su historia
            desde = int(cfg.get("panel", {}).get("anios_inicial", hoy.year - 4))
            anios = list(range(desde, hoy.year + 1)) if vacio else [hoy.year - 1, hoy.year]
            nuevas = src.panel_consumo(pares, anios)
            for (p, c), s in nuevas.items():
                clave = f"{p}|{c}"
                series[clave] = _fusionar(series.get(clave, []), [list(x) for x in s])
            escribir("apoyo/panel.json", {"series": series, "consultado": iso()})
            estado.set("apoyo_panel_dia", hoy.isoformat())
            estado.registrar_fuente("MAPA (panel de consumo)", True)
        except src.FuenteError as e:
            estado.registrar_fuente("MAPA (panel de consumo)", False, str(e))
            log.warning("Panel de consumo: %s", e)

    # Precios pagados por los agricultores (abonos): mensual; se mira una vez al dia
    productos = _fuentes_de(cfg, "pagados", "producto")
    if productos and (forzar or _una_vez_al_dia(estado, "apoyo_pagados_dia")):
        try:
            series = {p: [list(x) for x in s] for p, s in src.precios_pagados(productos).items()}
            escribir("apoyo/pagados.json", {"series": series, "consultado": iso()})
            estado.set("apoyo_pagados_dia", hoy.isoformat())
            estado.registrar_fuente("MAPA (precios pagados)", True)
        except src.FuenteError as e:
            estado.registrar_fuente("MAPA (precios pagados)", False, str(e))
            log.warning("Precios pagados: %s", e)

    # Precios percibidos (historia de los precios en origen de Espana desde 2005): cambia una
    # vez al anio; se mira una vez al mes
    productos = _fuentes_de(cfg, "percibidos", "producto")
    guardadas = (leer("apoyo/percibidos.json", {}) or {}).get("series", {})
    if productos and (forzar or estado.get("apoyo_percibidos_mes") != hoy.isoformat()[:7]
                      or any(p not in guardadas for p in productos)):
        try:
            series = {p: [list(x) for x in s] for p, s in src.precios_percibidos(productos).items()}
            escribir("apoyo/percibidos.json", {"series": series, "consultado": iso()})
            estado.set("apoyo_percibidos_mes", hoy.isoformat()[:7])
            estado.registrar_fuente("MAPA (precios percibidos)", True)
        except src.FuenteError as e:
            estado.registrar_fuente("MAPA (precios percibidos)", False, str(e))
            log.warning("Precios percibidos: %s", e)

    # Eurostat (indices de precios industriales de Espana y la UE): mensual; una vez al dia
    series_eu = _fuentes_de(cfg, "eurostat", "serie")
    if series_eu and (forzar or _una_vez_al_dia(estado, "apoyo_eurostat_dia")):
        try:
            desde = f"{hoy.year - ANIOS_HISTORIA}-01"
            datos = {s: [list(x) for x in v] for s, v in src.eurostat_indices(series_eu, desde).items()}
            escribir("apoyo/eurostat.json", {"series": datos, "consultado": iso()})
            estado.set("apoyo_eurostat_dia", hoy.isoformat())
            estado.registrar_fuente("Eurostat (precios industriales)", True)
        except src.FuenteError as e:
            estado.registrar_fuente("Eurostat (precios industriales)", False, str(e))
            log.warning("Eurostat: %s", e)

    # FRED: una vez al dia
    codigos = _fuentes_de(cfg, "fred", "serie")
    if codigos and (forzar or _una_vez_al_dia(estado, "apoyo_fred_dia")):
        clave = os.environ.get("FRED_KEY", "")
        desde = (hoy - timedelta(days=365 * ANIOS_HISTORIA)).isoformat()
        try:
            series = {c: [list(x) for x in src.fred_serie(c, clave, desde)] for c in codigos}
            escribir("apoyo/fred.json", {"series": series, "consultado": iso()})
            estado.set("apoyo_fred_dia", hoy.isoformat())
            estado.registrar_fuente("FRED (materias de apoyo)", True)
        except src.FuenteError as e:
            estado.registrar_fuente("FRED (materias de apoyo)", False, str(e))
            log.warning("FRED apoyo: %s", e)
    # El Banco Mundial (pink) lo descarga engine.actualizar_diarios junto con los metales.


# ---------------------------------------------------------------------------
# Calculo (sin red): de las copias guardadas al resumen que muestra la web
# ---------------------------------------------------------------------------
FUENTES_NOMBRE = {
    "carburantes": "Ministerio para la Transición Ecológica",
    "boletin": "Comisión Europea, Weekly Oil Bulletin",
    "mapa": "Ministerio de Agricultura (MAPA)",
    "pink": "Banco Mundial (Pink Sheet)",
    "fred": "FRED",
    "panel": "Ministerio de Agricultura, panel de consumo en hogares",
    "pagados": "Ministerio de Agricultura, precios pagados por los agricultores",
    "percibidos": "Ministerio de Agricultura, precios percibidos por los agricultores (mensual)",
    "eurostat": "Eurostat, índices de precios industriales",
    "metalcharts": "MetalCharts",
}
CLAVE_FUENTE = {"carburantes": "campo", "boletin": "columna", "mapa": "producto", "pink": "serie", "fred": "serie",
                "pagados": "producto", "percibidos": "producto", "eurostat": "serie", "metalcharts": "simbolo"}


def cargar_fuentes() -> dict:
    carburantes = leer("apoyo/carburantes.json", {}) or {}
    metalcharts = leer("apoyo/metalcharts.json", {}) or {}
    return {
        "_carburantes_dato": carburantes.get("dato"),
        "carburantes": carburantes.get("series", {}),
        "boletin": (leer("apoyo/boletin.json", {}) or {}).get("series", {}),
        "mapa": (leer("apoyo/mapa.json", {}) or {}).get("series", {}),
        "fred": (leer("apoyo/fred.json", {}) or {}).get("series", {}),
        "pink": (leer("pink.json", {}) or {}).get("series", {}),
        "panel": (leer("apoyo/panel.json", {}) or {}).get("series", {}),
        "pagados": (leer("apoyo/pagados.json", {}) or {}).get("series", {}),
        "percibidos": (leer("apoyo/percibidos.json", {}) or {}).get("series", {}),
        "eurostat": (leer("apoyo/eurostat.json", {}) or {}).get("series", {}),
        # MetalCharts: 6 precios por dia laborable; se queda el ultimo de cada dia
        "metalcharts": {s: sorted({f[:10]: v for f, v in serie}.items())
                        for s, serie in metalcharts.get("series", {}).items()},
        "_metalcharts_hora": {s: serie[-1][0] for s, serie in metalcharts.get("series", {}).items() if serie},
    }


def preferir(respaldo: list, preferida: list) -> list:
    """Serie mensual con el dato del canal preferido cuando existe y, si no, el de respaldo."""
    por_mes = {f: v for f, v in respaldo}
    por_mes.update({f: v for f, v in preferida})
    return sorted(por_mes.items())


def _serie(definicion: dict, fuentes: dict, cfg: dict | None = None) -> list[tuple[str, float]]:
    tipo = definicion.get("fuente")
    if tipo == "panel":
        canal, respaldo = _canales_panel(cfg or {}, definicion)
        datos = fuentes.get("panel", {})
        factor = float(definicion.get("factor", 1))
        serie = preferir(datos.get(f"{definicion['producto']}|{respaldo}", []),
                         datos.get(f"{definicion['producto']}|{canal}", []))
        return [(f, v * factor) for f, v in serie]
    datos = fuentes.get(tipo, {}).get(definicion.get(CLAVE_FUENTE.get(tipo, ""), ""), [])
    factor = float(definicion.get("factor", 1))
    # FRED fecha sus series mensuales el dia 1 (AAAA-MM-01): se tratan como medias del mes
    mensual = tipo == "fred" and definicion.get("frecuencia") == "mensual"
    return [(f[:7] if mensual else f, v * factor) for f, v in datos]


def combinar(historia: list, actual: list) -> list:
    """Une la historia (otra fuente) con la serie actual, sin solapes.

    Las fechas mensuales ('AAAA-MM') de la historia solo se usan para meses
    anteriores al primer dato de la serie actual.
    """
    if not actual:
        return list(historia)
    primero = actual[0][0]
    previos = [(f, v) for f, v in historia if (f < primero[:7] if len(f) == 7 else f < primero)]
    return previos + list(actual)


def fecha_fin(f: str) -> date:
    """Fecha en la que un dato deja de ser 'el ultimo': fin de mes para los mensuales."""
    if len(f) == 7:
        a, m = int(f[:4]), int(f[5:7])
        return date(a, m, calendar.monthrange(a, m)[1])
    return date.fromisoformat(f[:10])


def _fecha_media(f: str) -> date:
    return date(int(f[:4]), int(f[5:7]), 15) if len(f) == 7 else date.fromisoformat(f[:10])


def mensualizar(serie: list) -> list[tuple[str, float]]:
    grupos: dict[str, list[float]] = {}
    for f, v in serie:
        grupos.setdefault(f[:7], []).append(v)
    return [(m, sum(vs) / len(vs)) for m, vs in sorted(grupos.items())]


def resumen(serie: list, meses_media: int = 10, n_actual: int | None = None) -> dict | None:
    """'n_actual' = cuantos datos finales vienen de la fuente principal (el resto es
    historia de otra fuente). El cambio frente al dato anterior solo compara datos
    de la misma fuente, porque cada una calcula su media a su manera."""
    if not serie:
        return None
    f_ult, v_ult = serie[-1]
    r = {"fecha": f_ult, "valor": v_ult, "anterior": None, "cambio_pct": None,
         "interanual_pct": None, "tendencia": None, "mensual": mensualizar(serie)}
    if len(serie) >= 2 and (n_actual is None or n_actual >= 2):
        f_ant, v_ant = serie[-2]
        r["anterior"] = {"fecha": f_ant, "valor": v_ant}
        r["cambio_pct"] = (v_ult / v_ant - 1) * 100 if v_ant else None

    # Interanual: el dato mas cercano a un ano antes (tolerancia segun la frecuencia)
    objetivo = _fecha_media(f_ult) - timedelta(days=365)
    tolerancia = 20 if len(f_ult) == 7 else 10
    cercano = min(serie, key=lambda x: abs((_fecha_media(x[0]) - objetivo).days))
    if abs((_fecha_media(cercano[0]) - objetivo).days) <= tolerancia and cercano[1]:
        r["interanual_pct"] = (v_ult / cercano[1] - 1) * 100

    # Tendencia descriptiva: ultimo dato frente a la media de los ultimos N meses
    m = r["mensual"]
    if len(m) >= meses_media + 1:
        media = sum(v for _, v in m[-meses_media:]) / meses_media
        media_ant = sum(v for _, v in m[-meses_media - 1:-1]) / meses_media
        r["tendencia"] = {"media": media, "diferencia_pct": (v_ult / media - 1) * 100,
                          "pendiente": "subiendo" if media > media_ant else "bajando" if media < media_ant else "plana",
                          "meses": meses_media}
    return r


def reciente(r: dict, frecuencia: str, dias: dict, hoy: date, propio: int | None = None) -> bool:
    """'propio' = dias que una fuente concreta puede tardar (config: 'dias_reciente' en el
    ambito), para fuentes oficiales que publican siempre con meses de retraso."""
    limite = int(propio) if propio else int(dias.get(frecuencia, 75))
    return (hoy - fecha_fin(r["fecha"])).days <= limite


def elegir(ambitos: dict, vista: str, dias: dict, hoy: date) -> tuple[str | None, str | None]:
    """Que ambito mostrar cuando se pide 'vista'.

    - Si el ambito pedido tiene dato reciente, ese.
    - Si no tiene datos, o su dato no es reciente y otro ambito tiene uno mas nuevo,
      se muestra el ambito con el dato mas reciente, y se explica por que.
    Devuelve (ambito_mostrado, motivo o None).
    """
    disponibles = {a: d for a, d in ambitos.items() if d.get("resumen")}
    if not disponibles:
        return None, None
    nombre = NOMBRES_AMBITO.get(vista, vista)
    if vista in disponibles:
        d = disponibles[vista]
        if reciente(d["resumen"], d["frecuencia"], dias, hoy, d.get("dias_reciente")):
            return vista, None
        propio = fecha_fin(d["resumen"]["fecha"])
        mas_nuevos = {a: x for a, x in disponibles.items() if fecha_fin(x["resumen"]["fecha"]) > propio}
        if not mas_nuevos:
            return vista, None
        mejor = max(mas_nuevos, key=lambda a: (fecha_fin(mas_nuevos[a]["resumen"]["fecha"]), -AMBITOS.index(a)))
        return mejor, f"sin dato reciente de {nombre}"
    mejor = max(disponibles, key=lambda a: (fecha_fin(disponibles[a]["resumen"]["fecha"]), -AMBITOS.index(a)))
    return mejor, f"sin datos de {nombre}"


def multiplicador(origen: list, f_tienda: str, v_tienda: float) -> dict | None:
    """Cuantas veces el precio en tienda supera al de origen en el mismo mes."""
    mes = f_tienda[:7]
    del_mes = [v for f, v in origen if f[:7] == mes]
    if not del_mes or not v_tienda:
        return None
    media = sum(del_mes) / len(del_mes)
    return {"veces": v_tienda / media, "mes": mes, "origen": media} if media else None


def precio_estimado(indice: list, ref: dict | None, fuentes: dict, cfg, cambio) -> list | None:
    """Indice de precios (2021 = 100) -> precio estimado en euros.

    precio(mes) = precio medio de referencia en el ano base, en euros
                  x indice(mes) / indice medio del ano base.
    La referencia es un precio mundial (Banco Mundial, FRED...); si cotiza en dolares,
    cada mes se pasa a euros con su cambio. Si falta algo, devuelve None y se sigue
    mostrando el indice.
    """
    if not ref:
        return None
    anio = str(ref.get("anio", 2021))
    serie_ref = _serie({"frecuencia": "mensual", **ref}, fuentes, cfg)
    if ref.get("unidad", "$").startswith("$"):
        if not cambio:
            return None
        serie_ref = cambio.a_euros(mensualizar(serie_ref))
    ref_anio = [v for f, v in mensualizar(serie_ref) if f.startswith(anio)]
    ind_anio = [v for f, v in mensualizar(indice) if f.startswith(anio)]
    if len(ref_anio) < 6 or len(ind_anio) < 6:          # al menos medio ano para la media
        return None
    precio_base = sum(ref_anio) / len(ref_anio)
    indice_base = sum(ind_anio) / len(ind_anio)
    return [(f, v / indice_base * precio_base) for f, v in indice]


def cambio_usd() -> list:
    """Dolares por euro, diario: el oficial del BCE y, donde falte, el de FRED (DEXUSEU)."""
    por_dia = {f[:10]: v for f, v in ((leer("macro.json", {}) or {}).get("series", {}) or {}).get("DEXUSEU", []) if v}
    por_dia.update({f[:10]: v for f, v in ((leer("cambio.json", {}) or {}).get("series", {}) or {}).get("USD", []) if v})
    return sorted(por_dia.items())


class TipoCambio:
    """Dolares por euro (FRED, DEXUSEU), diario. Para pasar a euros las series en dolares
    con el cambio de cada fecha: el dia (o el anterior con dato) en las series diarias y
    semanales, y la media del mes en las mensuales."""

    def __init__(self, diario: list):
        self.dias = sorted((f[:10], float(v)) for f, v in diario if v)
        self.fechas = [f for f, _ in self.dias]
        meses: dict[str, list[float]] = {}
        for f, v in self.dias:
            meses.setdefault(f[:7], []).append(v)
        self.meses = {m: sum(vs) / len(vs) for m, vs in meses.items()}

    def __bool__(self):
        return bool(self.dias)

    def en(self, fecha: str) -> float | None:
        if len(fecha) == 7:
            return self.meses.get(fecha)
        import bisect
        i = bisect.bisect_right(self.fechas, fecha[:10]) - 1
        if i < 0 or (date.fromisoformat(fecha[:10]) - date.fromisoformat(self.fechas[i])).days > 10:
            return None
        return self.dias[i][1]

    def a_euros(self, serie: list) -> list:
        """Serie en dolares -> en euros. Los datos sin cambio conocido se descartan."""
        salida = []
        for f, v in serie:
            c = self.en(f)
            if c:
                salida.append((f, v / c))
        return salida


def decimales_por_defecto(unidad: str) -> int:
    """Precios por tonelada sin decimales (15.436 $/tonelada); el resto, con dos."""
    return 0 if "tonelada" in unidad else 2


def tienda(cfg, amb: dict, origen: list, fuentes: dict, meses_media: int) -> dict | None:
    """Precio en tienda (panel de consumo) junto al de origen, si el ambito lo define."""
    t = amb.get("tienda")
    if not t:
        return None
    definicion = {"fuente": "panel", **t}
    serie = _serie(definicion, fuentes, cfg)
    if not serie:
        return {**t, "resumen": None}
    canal, respaldo = _canales_panel(cfg, definicion)
    datos = fuentes.get("panel", {})
    factor = float(t.get("factor", 1))
    solo_pref = [(f, v * factor) for f, v in datos.get(f"{t['producto']}|{canal}", [])]
    solo_resp = [(f, v * factor) for f, v in datos.get(f"{t['producto']}|{respaldo}", [])]
    r = resumen(serie, meses_media)
    # El cambio en un ano compara siempre la misma medida: supermercado con supermercado
    # si existe el dato de hace un ano; si no, la media de todas las tiendas en ambos meses.
    r_pref = resumen(solo_pref, meses_media) if solo_pref else None
    r_resp = resumen(solo_resp, meses_media) if solo_resp else None
    if r_pref and r_pref["fecha"] == r["fecha"] and r_pref["interanual_pct"] is not None:
        r["interanual_pct"], r["interanual_base"] = r_pref["interanual_pct"], "supermercado"
    elif r_resp and r_resp["fecha"] == r["fecha"]:
        r["interanual_pct"], r["interanual_base"] = r_resp["interanual_pct"], "todas las tiendas"
    else:
        r["interanual_pct"], r["interanual_base"] = None, None
    preferidos = {f for f, _ in solo_pref}
    return {"decimales": decimales_por_defecto(t["unidad"]), **t, "resumen": r, "frecuencia": "mensual",
            "canal_ultimo": "supermercado" if r["fecha"] in preferidos else "todas las tiendas",
            # 'multiplicador: false' en config.yaml cuando la tienda vende un producto
            # elaborado (trigo -> pan): compararlos kilo a kilo no tendria sentido.
            "multiplicador": multiplicador(origen, r["fecha"], r["valor"]) if t.get("multiplicador", True) else None,
            "fuente_nombre": FUENTES_NOMBRE["panel"]}


def empalmar(historia: list, actual: list, minimo: int = 12) -> list:
    """Pone la historia (otra estadistica del mismo producto, con otra unidad o categoria) al
    nivel de la serie actual: se multiplica por la media del cociente actual / historia en
    los meses en que coinciden. Sin al menos 'minimo' meses comunes no se usa la historia."""
    h = dict(mensualizar(historia))
    a = dict(mensualizar(actual))
    comunes = [m for m in h if m in a and h[m] > 0]
    if len(comunes) < minimo:
        return []
    k = sum(a[m] / h[m] for m in comunes) / len(comunes)
    return [(f, v * k) for f, v in historia]


def serie_ambito(amb: dict, fuentes: dict, cfg, cambio, en_euros: bool) -> dict:
    """La serie que se muestra de un ambito (historia + actual, en euros si toca y, en los
    indices con referencia, como precio estimado). La usan la web y las previsiones."""
    actual = _serie(amb, fuentes, cfg)
    historia = _serie(amb["historia"], fuentes, cfg) if amb.get("historia") else []
    if historia and actual and amb["historia"].get("empalme"):
        historia = empalmar(historia, actual)
    unidad, usd = amb["unidad"], None
    if en_euros and unidad.startswith("$") and cambio:
        # Se guarda el ultimo dato en dolares para mostrarlo al lado
        ult = (combinar(historia, actual) if actual else historia)[-1:]
        usd = {"valor": ult[0][1], "unidad": unidad} if ult else None
        actual, historia = cambio.a_euros(actual), cambio.a_euros(historia)
        unidad = "€" + unidad[1:]
    serie = combinar(historia, actual) if actual else historia
    # Indices (2021 = 100): si hay un precio de referencia mundial, se pasan a
    # precio estimado en euros; si no, se muestran como cambio frente a 2021
    indice = None
    if unidad.startswith("puntos") and serie:
        indice = {"valor": serie[-1][1], "base": amb.get("base_indice", 2021)}
        estimada = precio_estimado(serie, amb.get("referencia"), fuentes, cfg, cambio)
        if estimada:
            serie, unidad = estimada, amb["referencia"].get("unidad_eur", "€/tonelada")
            actual = serie
    return {"actual": actual, "historia": historia, "serie": serie, "unidad": unidad,
            "usd": usd, "indice": indice}


def preparar(cfg, hoy: date | None = None) -> list[dict]:
    """Estructura lista para las plantillas: grupos -> materias -> ambitos y vistas."""
    hoy = hoy or date.today()
    acfg = cfg.get("apoyo", {})
    dias = acfg.get("dias_reciente", {})
    meses_media = cfg["indicadores"]["tendencia"]["meses_media"]
    fuentes = cargar_fuentes()
    # Precios en dolares -> euros con el cambio de cada fecha (config: apoyo.en_euros)
    en_euros = acfg.get("en_euros", True)
    cambio = TipoCambio(cambio_usd())
    grupos = []
    pestanas: dict[str, str] = {}       # nombre de pestana -> id (el del primer grupo que la usa)
    for g in acfg.get("grupos", []):
        pestana = g.get("pestana") or g["nombre"]
        pestanas.setdefault(pestana, g["id"])
        lista = []
        for m in g.get("materias", []):
            ambitos = {}
            for a in AMBITOS:
                amb = m.get("ambitos", {}).get(a)
                if not amb:
                    continue
                s = serie_ambito(amb, fuentes, cfg, cambio, en_euros)
                actual, historia, serie = s["actual"], s["historia"], s["serie"]
                unidad, usd, indice = s["unidad"], s["usd"], s["indice"]
                fuentes_usadas = [FUENTES_NOMBRE.get(amb["fuente"], amb["fuente"])]
                if amb.get("historia") and historia:
                    h = FUENTES_NOMBRE.get(amb["historia"]["fuente"], amb["historia"]["fuente"])
                    if h not in fuentes_usadas:
                        fuentes_usadas.append(h)
                r = resumen(serie, meses_media, n_actual=len(actual) if actual and historia else None)
                if r and amb["fuente"] == "carburantes" and actual:
                    r["hora"] = fuentes.get("_carburantes_dato")     # hora exacta del dato
                if r and amb["fuente"] == "metalcharts" and actual and len(r["fecha"]) == 10:
                    r["hora"] = fuentes.get("_metalcharts_hora", {}).get(amb["simbolo"])
                ambitos[a] = {"decimales": decimales_por_defecto(amb["unidad"]),
                              **{k: v for k, v in amb.items() if k != "historia"},
                              "unidad": unidad, "usd": usd, "indice": indice,
                              "estimado": bool(indice) and not unidad.startswith("puntos"),
                              "decimales": (decimales_por_defecto(unidad) if indice and not unidad.startswith("puntos")
                                            else amb.get("decimales", decimales_por_defecto(amb["unidad"]))),
                              "id": a, "nombre": amb.get("etiqueta") or NOMBRES_AMBITO[a],
                              "frecuencia": amb.get("frecuencia", "mensual") if actual else "mensual",
                              "fuente_nombre": fuentes_usadas[0] if actual else fuentes_usadas[-1],
                              "fuentes": fuentes_usadas, "resumen": r,
                              "solo_historia": not actual and bool(historia),
                              # Que mide el precio principal: en origen (lo que cobra el
                              # productor) o en tienda (panel de consumo, lo que paga el hogar)
                              "medida": "tienda" if amb["fuente"] == "panel" else "origen",
                              "tienda": tienda(cfg, amb, serie, fuentes, meses_media)}
            vistas = {}
            for v in AMBITOS:
                mostrado, motivo = elegir(ambitos, v, dias, hoy)
                vistas[v] = {"ambito": mostrado, "motivo": motivo}
            con_tienda = any(d.get("tienda") or d["medida"] == "tienda" for d in ambitos.values())
            lista.append({**{k: v for k, v in m.items() if k != "ambitos"}, "ambitos": ambitos, "vistas": vistas,
                          "grupo": g["id"], "con_tienda": con_tienda})
        grupos.append({**{k: v for k, v in g.items() if k != "materias"}, "materias": lista,
                       "pestana": pestana, "pestana_id": pestanas[pestana],
                       "con_tienda": any(x["con_tienda"] for x in lista)})
    return grupos
