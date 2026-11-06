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
            vacio = any(not series.get(p) for p in productos)
            anios = list(range(hoy.year - ANIOS_MAPA_INICIAL, hoy.year + 1)) if vacio else \
                ([hoy.year - 1, hoy.year] if hoy.month == 1 else [hoy.year])
            nuevas = src.mapa_semanal(productos, anios)
            for p, s in nuevas.items():
                series[p] = _fusionar(series.get(p, []), [list(x) for x in s])
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
            vacio = any(not series.get(f"{p}|{c}") for p, c in pares)
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
}
CLAVE_FUENTE = {"carburantes": "campo", "boletin": "columna", "mapa": "producto", "pink": "serie", "fred": "serie"}


def cargar_fuentes() -> dict:
    carburantes = leer("apoyo/carburantes.json", {}) or {}
    return {
        "_carburantes_dato": carburantes.get("dato"),
        "carburantes": carburantes.get("series", {}),
        "boletin": (leer("apoyo/boletin.json", {}) or {}).get("series", {}),
        "mapa": (leer("apoyo/mapa.json", {}) or {}).get("series", {}),
        "fred": (leer("apoyo/fred.json", {}) or {}).get("series", {}),
        "pink": (leer("pink.json", {}) or {}).get("series", {}),
        "panel": (leer("apoyo/panel.json", {}) or {}).get("series", {}),
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


def reciente(r: dict, frecuencia: str, dias: dict, hoy: date) -> bool:
    return (hoy - fecha_fin(r["fecha"])).days <= int(dias.get(frecuencia, 75))


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
        if reciente(d["resumen"], d["frecuencia"], dias, hoy):
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
    return {**t, "resumen": r, "frecuencia": "mensual",
            "canal_ultimo": "supermercado" if r["fecha"] in preferidos else "todas las tiendas",
            "multiplicador": multiplicador(origen, r["fecha"], r["valor"]),
            "fuente_nombre": FUENTES_NOMBRE["panel"]}


def preparar(cfg, hoy: date | None = None) -> list[dict]:
    """Estructura lista para las plantillas: grupos -> materias -> ambitos y vistas."""
    hoy = hoy or date.today()
    acfg = cfg.get("apoyo", {})
    dias = acfg.get("dias_reciente", {})
    meses_media = cfg["indicadores"]["tendencia"]["meses_media"]
    fuentes = cargar_fuentes()
    grupos = []
    for g in acfg.get("grupos", []):
        lista = []
        for m in g.get("materias", []):
            ambitos = {}
            for a in AMBITOS:
                amb = m.get("ambitos", {}).get(a)
                if not amb:
                    continue
                actual = _serie(amb, fuentes, cfg)
                historia = _serie(amb["historia"], fuentes, cfg) if amb.get("historia") else []
                serie = combinar(historia, actual) if actual else historia
                fuentes_usadas = [FUENTES_NOMBRE.get(amb["fuente"], amb["fuente"])]
                if amb.get("historia") and historia:
                    h = FUENTES_NOMBRE.get(amb["historia"]["fuente"], amb["historia"]["fuente"])
                    if h not in fuentes_usadas:
                        fuentes_usadas.append(h)
                r = resumen(serie, meses_media, n_actual=len(actual) if actual and historia else None)
                if r and amb["fuente"] == "carburantes" and actual:
                    r["hora"] = fuentes.get("_carburantes_dato")     # hora exacta del dato
                ambitos[a] = {**{k: v for k, v in amb.items() if k != "historia"},
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
                       "con_tienda": any(x["con_tienda"] for x in lista)})
    return grupos
