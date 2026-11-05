"""Indicadores de contexto de Cedron.

Cada indicador devuelve -1 (desfavorable), 0 (neutral), +1 (favorable) o None
(sin datos suficientes). La suma da la lectura general. Las reglas exactas estan
en config.yaml y se explican en la pagina de metodologia.

Todas las funciones son puras: reciben series y devuelven resultados, sin red
ni disco, para poder probarlas con datos historicos.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta

LIBRAS_POR_TONELADA = 2204.62262


@dataclass
class Resultado:
    id: str
    nombre: str
    puntos: int | None
    dato: str
    explicacion: str
    fecha: str | None = None


@dataclass
class Lectura:
    activo: str
    indicadores: list[Resultado] = field(default_factory=list)
    total: int = 0
    disponibles: int = 0
    lectura: str = "datos insuficientes"
    frase: str = ""


# ---------------------------------------------------------------------------
# Utilidades de series
# ---------------------------------------------------------------------------
def media(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def fmt_pct(x: float) -> str:
    return f"{x:+.1f} %".replace(".", ",").replace("-", "−")


def fmt_num(x: float, dec: int = 2) -> str:
    s = f"{x:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def valor_en_fecha(serie: list[tuple[str, float]], objetivo: str) -> float | None:
    """Ultimo valor con fecha <= objetivo (serie ordenada por fecha)."""
    candidato = None
    for f, v in serie:
        if f <= objetivo:
            candidato = v
        else:
            break
    return candidato


def serie_mensual(pink: list[tuple[str, float]], diario: list[tuple[str, float]],
                  factor_pink: float = 1.0) -> list[tuple[str, float]]:
    """Une el historico mensual del Banco Mundial con los cierres diarios propios.

    Los meses que el Banco Mundial ya publico mandan; los posteriores se calculan
    como media de los cierres diarios que Cedron ha ido guardando.
    """
    meses = {m: v / factor_pink for m, v in pink}
    por_mes: dict[str, list[float]] = {}
    for f, v in diario:
        por_mes.setdefault(f[:7], []).append(v)
    ultimo_pink = max(meses) if meses else ""
    for m, vals in por_mes.items():
        if m > ultimo_pink:
            meses[m] = sum(vals) / len(vals)
    return sorted(meses.items())


def restar_meses(mes: str, n: int) -> str:
    a, m = int(mes[:4]), int(mes[5:7])
    total = a * 12 + (m - 1) - n
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


# ---------------------------------------------------------------------------
# Indicadores
# ---------------------------------------------------------------------------
def tendencia(mensual: list[tuple[str, float]], precio: float, cfg: dict) -> Resultado:
    n = cfg["meses_media"]
    nombre = "Tendencia de largo plazo"
    if len(mensual) < n + 1:
        return Resultado("tendencia", nombre, None, "sin datos",
                         f"Hacen falta al menos {n + 1} meses de historia.")
    valores = [v for _, v in mensual]
    mm_actual = media(valores[-n:])
    mm_previa = media(valores[-n - 1:-1])
    distancia = (precio / mm_actual - 1) * 100
    subiendo = mm_actual > mm_previa
    if precio > mm_actual and subiendo:
        puntos, estado = 1, "por encima de su media y con la media al alza"
    elif precio < mm_actual and not subiendo:
        puntos, estado = -1, "por debajo de su media y con la media a la baja"
    else:
        puntos, estado = 0, "sin una dirección clara"
    return Resultado("tendencia", nombre, puntos,
                     f"{fmt_pct(distancia)} frente a la media de {n} meses",
                     f"El precio está {estado}.", mensual[-1][0])


def momento(mensual: list[tuple[str, float]], precio: float, cfg: dict) -> Resultado:
    n, umbral = cfg["meses"], cfg["umbral_pct"]
    nombre = "Momento"
    if len(mensual) < n + 1:
        return Resultado("momento", nombre, None, "sin datos",
                         f"Hacen falta al menos {n + 1} meses de historia.")
    referencia = mensual[-1 - n][1]
    cambio = (precio / referencia - 1) * 100
    puntos = 1 if cambio > umbral else -1 if cambio < -umbral else 0
    texto = ("subida" if cambio > 0 else "caída") + f" de {abs(cambio):.1f}".replace(".", ",") + " %"
    return Resultado("momento", nombre, puntos,
                     f"{fmt_pct(cambio)} en {n} meses",
                     f"Una {texto} frente a la media de hace {n} meses; "
                     f"cuenta como señal si supera el {umbral} %.", mensual[-1][0])


def macro(tipo_real: list[tuple[str, float]], dolar: list[tuple[str, float]],
          hoy: date, cfg: dict) -> Resultado:
    nombre = "Entorno macro"
    if not tipo_real or not dolar:
        return Resultado("macro", nombre, None, "sin datos", "No hay datos de FRED.")
    atras = (hoy - timedelta(days=round(cfg["meses"] * 30.4))).isoformat()
    tr_hoy, tr_antes = tipo_real[-1][1], valor_en_fecha(tipo_real, atras)
    dx_hoy, dx_antes = dolar[-1][1], valor_en_fecha(dolar, atras)
    if tr_antes is None or dx_antes is None:
        return Resultado("macro", nombre, None, "sin datos",
                         "La serie de FRED no llega tan atrás.")
    d_tr = tr_hoy - tr_antes
    d_dx = (dx_hoy / dx_antes - 1) * 100
    baja_tr = d_tr <= -cfg["umbral_tipo_real"]
    sube_tr = d_tr >= cfg["umbral_tipo_real"]
    baja_dx = d_dx <= -cfg["umbral_dolar_pct"]
    sube_dx = d_dx >= cfg["umbral_dolar_pct"]
    if baja_tr and baja_dx:
        puntos = 1
    elif sube_tr and sube_dx:
        puntos = -1
    else:
        puntos = 0
    signo_tr = f"{d_tr:+.2f}".replace(".", ",").replace("-", "−")
    return Resultado(
        "macro", nombre, puntos,
        f"En {cfg['meses']} meses: tipo real {signo_tr} puntos; dólar {fmt_pct(d_dx)}",
        "Tipos reales y dólar a la baja suelen favorecer a los metales preciosos; "
        "ambos al alza, lo contrario. Si van en direcciones distintas, cuenta como neutral.",
        min(tipo_real[-1][0], dolar[-1][0]))


def posicionamiento(cot: list[dict], cfg: dict) -> Resultado:
    nombre = "Posicionamiento especulativo"
    semanas = cfg["anios"] * 52
    validos = [c for c in cot if c.get("neto_pct") is not None][-semanas:]
    if len(validos) < 52:
        return Resultado("posicionamiento", nombre, None, "sin datos",
                         "Hace falta al menos un año de informes de la CFTC.")
    actual = validos[-1]["neto_pct"]
    por_debajo = sum(1 for c in validos if c["neto_pct"] < actual)
    percentil = por_debajo / (len(validos) - 1) * 100 if len(validos) > 1 else 50
    if percentil >= cfg["percentil_alto"]:
        puntos, estado = -1, "en zona de euforia (lectura contraria: riesgo de corrección)"
    elif percentil <= cfg["percentil_bajo"]:
        puntos, estado = 1, "en zona de pesimismo extremo (lectura contraria: margen de recuperación)"
    else:
        puntos, estado = 0, "sin excesos"
    return Resultado("posicionamiento", nombre, puntos,
                     f"Percentil {percentil:.0f} de los últimos {cfg['anios']} años",
                     f"Los grandes especuladores están {estado}.", validos[-1]["fecha"])


def ratio(numerador: list[tuple[str, float]], denominador: list[tuple[str, float]],
          etiqueta: str, invertir: bool, cfg: dict) -> Resultado:
    """Compara un ratio entre metales con su media de N anios (puntuacion z).

    invertir=False: un ratio ALTO es desfavorable para el activo (esta caro).
    invertir=True:  un ratio ALTO es favorable para el activo (el otro esta caro).
    """
    nombre = f"Valoración relativa ({etiqueta})"
    den = dict(denominador)
    pares = [(m, v / den[m]) for m, v in numerador if m in den and den[m]]
    pares = pares[-cfg["anios"] * 12:]
    if len(pares) < 36:
        return Resultado("ratio", nombre, None, "sin datos",
                         "Hacen falta al menos 3 años de historia mensual común.")
    valores = [v for _, v in pares]
    mu, sigma = statistics.mean(valores), statistics.pstdev(valores)
    actual = valores[-1]
    z = (actual - mu) / sigma if sigma else 0
    caro = z >= cfg["desviaciones"]
    barato = z <= -cfg["desviaciones"]
    if invertir:
        caro, barato = barato, caro
    puntos = -1 if caro else 1 if barato else 0
    estado = ("caro" if puntos == -1 else "barato" if puntos == 1 else "en su rango habitual")
    return Resultado("ratio", nombre, puntos,
                     f"Ratio {fmt_num(actual)} (media {cfg['anios']} años: {fmt_num(mu)})",
                     f"Frente al otro metal, el activo está {estado}.", pares[-1][0])


# ---------------------------------------------------------------------------
# Lectura final
# ---------------------------------------------------------------------------
def combinar(activo: str, nombre_activo: str, resultados: list[Resultado], cfg: dict) -> Lectura:
    disponibles = [r for r in resultados if r.puntos is not None]
    total = sum(r.puntos for r in disponibles)
    lectura = Lectura(activo, resultados, total, len(disponibles))
    if len(disponibles) < 3:
        lectura.lectura = "datos insuficientes"
        lectura.frase = (f"Aún no hay datos suficientes para una lectura del {nombre_activo.lower()}: "
                         f"{len(disponibles)} de {len(resultados)} indicadores disponibles.")
        return lectura
    if total >= cfg["favorable_desde"]:
        lectura.lectura = "favorable"
    elif total <= cfg["desfavorable_hasta"]:
        lectura.lectura = "desfavorable"
    else:
        lectura.lectura = "neutral"
    a_favor = [r.nombre.lower() for r in disponibles if r.puntos == 1]
    en_contra = [r.nombre.lower() for r in disponibles if r.puntos == -1]
    partes = []
    if a_favor:
        partes.append("a favor: " + _lista(a_favor))
    if en_contra:
        partes.append("en contra: " + _lista(en_contra))
    detalle = "; ".join(partes) if partes else "ningún indicador da señal clara"
    articulo = "del" if nombre_activo.lower() in ("oro", "cobre", "platino", "paladio") else "de la"
    suma = "0" if total == 0 else f"{total:+d}".replace("-", "−")
    lectura.frase = (f"El contexto {articulo} {nombre_activo.lower()} es {lectura.lectura}: "
                     f"suma {suma} con {len(disponibles)} indicadores. {detalle[0].upper() + detalle[1:]}.")
    return lectura


def _lista(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " y " + xs[-1]
