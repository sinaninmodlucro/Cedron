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


def _fuentes_de(cfg, tipo: str, clave: str) -> list[str]:
    """Valores de 'clave' de todos los ambitos (e historias) que usan la fuente 'tipo'."""
    salida = []
    for m in materias(cfg):
        for amb in m.get("ambitos", {}).values():
            for d in (amb, amb.get("historia") or {}):
                if d.get("fuente") == tipo and d.get(clave) and d[clave] not in salida:
                    salida.append(d[clave])
    return salida


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
    }


def _serie(definicion: dict, fuentes: dict) -> list[tuple[str, float]]:
    tipo = definicion.get("fuente")
    datos = fuentes.get(tipo, {}).get(definicion.get(CLAVE_FUENTE.get(tipo, ""), ""), [])
    factor = float(definicion.get("factor", 1))
    return [(f, v * factor) for f, v in datos]


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
                actual = _serie(amb, fuentes)
                historia = _serie(amb["historia"], fuentes) if amb.get("historia") else []
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
                              "solo_historia": not actual and bool(historia)}
            vistas = {}
            for v in AMBITOS:
                mostrado, motivo = elegir(ambitos, v, dias, hoy)
                vistas[v] = {"ambito": mostrado, "motivo": motivo}
            lista.append({**{k: v for k, v in m.items() if k != "ambitos"}, "ambitos": ambitos, "vistas": vistas,
                          "grupo": g["id"]})
        grupos.append({**{k: v for k, v in g.items() if k != "materias"}, "materias": lista})
    return grupos
