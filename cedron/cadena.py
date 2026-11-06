"""Cadena de costes: cuanto y en cuanto tiempo se traslada un precio a otro.

Metodo (el de los bancos centrales para medir el traslado de precios: proyecciones
locales de Jorda, 2005). Para cada eslabon "arriba -> abajo" y cada plazo h de 0 a
12 meses se estima, con datos mensuales:

    ln abajo[t+h] - ln abajo[t-1] = a + b_h * (ln arriba[t] - ln arriba[t-1]) + controles

donde los controles son los cambios de los 3 meses anteriores de ambos precios. b_h
es el traslado acumulado: si arriba sube un 10 % en un mes, abajo ha subido de media
un 10 * b_h % h meses despues. Los errores son de Newey-West (los meses seguidos se
parecen y los plazos se solapan).

Un eslabon se da por COMPROBADO si, a 6 meses (plazo fijado de antemano), el traslado
es positivo con un intervalo del 95 % que no incluye el cero y es positivo tambien en
cada mitad del periodo por separado. Los demas se muestran como "no se aprecia".

Subidas frente a bajadas ("cohetes y plumas", Bacon 1991; Borenstein, Cameron y
Gilbert 1997): la misma estimacion separando los meses en que arriba sube de los que
baja. Se publica la diferencia solo si a 3 meses es clara (95 %).

Traslado pendiente: lo que, segun el traslado medio, falta por llegar abajo de los
cambios de arriba de los ultimos 12 meses. Se pone a prueba a ciegas: en cada mes de
la segunda mitad se calcula solo con datos anteriores y se compara con lo que paso en
los 12 meses siguientes. Si no mejora a la simple media historica, no se publica.

Las funciones de calculo son puras; ejecutar() lee data/ y escribe data/cadena.json.
"""
from __future__ import annotations

import logging
import math
import random

from cedron import apoyo
from cedron.store import escribir, iso, leer

log = logging.getLogger("cedron.cadena")

VERSION = 1                # subirla al cambiar el metodo: se recalcula sin esperar al mes siguiente
PLAZOS = list(range(13))   # 0 a 12 meses
PLAZO_PRINCIPAL = 6
PLAZO_ASIMETRIA = 3
RETARDOS = 3
MINIMO_MESES = 72          # seis anios de datos comunes como minimo
Z95 = 1.959964


# ---------------------------------------------------------------------------
# Algebra minima (sin dependencias)
# ---------------------------------------------------------------------------
def _inversa(M: list[list[float]]) -> list[list[float]] | None:
    k = len(M)
    A = [row[:] for row in M]
    inv = [[float(i == j) for j in range(k)] for i in range(k)]
    for c in range(k):
        p = max(range(c, k), key=lambda r: abs(A[r][c]))
        if abs(A[p][c]) < 1e-12:
            return None
        A[c], A[p] = A[p], A[c]
        inv[c], inv[p] = inv[p], inv[c]
        piv = A[c][c]
        A[c] = [x / piv for x in A[c]]
        inv[c] = [x / piv for x in inv[c]]
        for r in range(k):
            if r != c and A[r][c]:
                f = A[r][c]
                A[r] = [a - f * b for a, b in zip(A[r], A[c])]
                inv[r] = [a - f * b for a, b in zip(inv[r], inv[c])]
    return inv


def mco(X: list[list[float]], y: list[float], hac: int | None = None):
    """Minimos cuadrados. Devuelve (coeficientes, covarianza de Newey-West o None)."""
    k = len(X[0])
    XtX = [[sum(r[i] * r[j] for r in X) for j in range(k)] for i in range(k)]
    inv = _inversa(XtX)
    if inv is None:
        return None, None
    Xty = [sum(r[i] * v for r, v in zip(X, y)) for i in range(k)]
    beta = [sum(inv[i][j] * Xty[j] for j in range(k)) for i in range(k)]
    if hac is None:
        return beta, None
    e = [v - sum(b * x for b, x in zip(beta, r)) for r, v in zip(X, y)]
    g = [[x * ee for x in r] for r, ee in zip(X, e)]
    S = [[sum(gt[i] * gt[j] for gt in g) for j in range(k)] for i in range(k)]
    for L in range(1, hac + 1):
        w = 1 - L / (hac + 1)
        for t in range(L, len(g)):
            a, b = g[t], g[t - L]
            for i in range(k):
                for j in range(k):
                    S[i][j] += w * (a[i] * b[j] + b[i] * a[j])
    cov = [[sum(inv[i][p] * S[p][q] * inv[q][j] for p in range(k) for q in range(k))
            for j in range(k)] for i in range(k)]
    return beta, cov


# ---------------------------------------------------------------------------
# Proyecciones locales (puras)
# ---------------------------------------------------------------------------
def _comunes(arriba: dict, abajo: dict, desde: str = "", hasta: str = "9999") -> list[str]:
    """Meses con dato en las dos series (los huecos se saltan al estimar)."""
    meses = sorted(m for m in set(arriba) & set(abajo) if desde <= m <= hasta and arriba[m] > 0 and abajo[m] > 0)
    return meses


def _filas(arriba: dict, abajo: dict, meses: list[str], h: int, asimetrica: bool = False):
    la = [math.log(arriba[m]) for m in meses]
    lb = [math.log(abajo[m]) for m in meses]
    num = [int(m[:4]) * 12 + int(m[5:7]) for m in meses]
    X, y = [], []
    for i in range(RETARDOS + 1, len(meses) - h):
        # solo tramos de meses seguidos (p. ej. los abonos de Espana tienen meses sin publicar)
        if num[i + h] - num[i - RETARDOS - 1] != h + RETARDOS + 1:
            continue
        d = la[i] - la[i - 1]
        fila = [1.0] + ([max(d, 0.0), min(d, 0.0)] if asimetrica else [d])
        fila += [la[i - j] - la[i - j - 1] for j in range(1, RETARDOS + 1)]
        fila += [lb[i - j] - lb[i - j - 1] for j in range(1, RETARDOS + 1)]
        X.append(fila)
        y.append(lb[i + h] - lb[i - 1])
    return X, y


def traslado(arriba: dict, abajo: dict, meses: list[str], plazos=PLAZOS, errores: bool = True) -> dict:
    """{h: (b, error tipico, n)} para cada plazo h."""
    out = {}
    for h in plazos:
        X, y = _filas(arriba, abajo, meses, h)
        if len(X) < 40:
            continue
        beta, cov = mco(X, y, h + 1 if errores else None)
        if beta is None:
            continue
        out[h] = (beta[1], math.sqrt(max(cov[1][1], 0)) if cov else None, len(X))
    return out


def asimetria(arriba: dict, abajo: dict, meses: list[str], plazos=(1, 3, 6)) -> dict:
    """Traslado de las subidas y de las bajadas por separado, y su diferencia."""
    out = {}
    for h in plazos:
        X, y = _filas(arriba, abajo, meses, h, asimetrica=True)
        if len(X) < 60:
            continue
        beta, cov = mco(X, y, h + 1)
        if beta is None:
            continue
        dif = beta[1] - beta[2]
        se = math.sqrt(max(cov[1][1] + cov[2][2] - 2 * cov[1][2], 0))
        out[h] = {"subidas": beta[1], "bajadas": beta[2], "diferencia": dif, "error": se,
                  "clara": abs(dif) > Z95 * se if se else False}
    return out


def pendiente(b: dict, cambios: list[tuple[str, float]], ultimo_abajo: str) -> float | None:
    """Lo que falta por trasladarse abajo (en log) de los cambios recientes de arriba.

    b: {h: traslado acumulado} con h de 0 a 12. cambios: [(mes, cambio en log de arriba)].
    Un cambio de arriba en el mes s ya deberia verse abajo en la parte b[ultimo_abajo - s]
    (nada si s es posterior al ultimo dato de abajo); el total, a 12 meses, es b[12].
    """
    if 12 not in b:
        return None
    total = 0.0
    a_fin = int(ultimo_abajo[:4]) * 12 + int(ultimo_abajo[5:7])
    for mes, d in cambios:
        s = int(mes[:4]) * 12 + int(mes[5:7])
        visto_hace = a_fin - s
        if visto_hace >= 12:
            continue
        ya = 0.0 if visto_hace < 0 else b.get(visto_hace, 0.0)
        total += d * (b[12] - ya)
    return total


def _r2_fuera(casos) -> float | None:
    if len(casos) < 24:
        return None
    sse_m = sum((y - p) ** 2 for y, p, _ in casos)
    sse_b = sum((y - m) ** 2 for y, _, m in casos)
    return 1 - sse_m / sse_b if sse_b else None


def probar_pendiente(arriba: dict, abajo: dict, meses: list[str], remuestreos: int = 300,
                     semilla: int = 2026) -> dict:
    """Prueba a ciegas del traslado pendiente en la segunda mitad del periodo.

    Cada enero se reestima el traslado solo con datos que ya se conocian; cada mes se
    compara (media historica + pendiente) con lo que cambio abajo en los 12 meses
    siguientes, frente a la media historica sola. R2 fuera de muestra > 0 = mejora.
    """
    la = {m: math.log(arriba[m]) for m in meses}
    lb = {m: math.log(abajo[m]) for m in meses}
    inicio = len(meses) // 2
    casos, b, anio = [], None, None
    for t in range(inicio, len(meses) - 12):
        m = meses[t]
        if b is None or m[:4] != anio:
            anio = m[:4]
            conocidos = meses[:t + 1]
            est = traslado({k: arriba[k] for k in conocidos}, {k: abajo[k] for k in conocidos},
                           conocidos, errores=False)
            # en el plazo h solo valen filas cuyo resultado ya se conocia: _filas ya lo asegura
            b = {h: v[0] for h, v in est.items()}
            if 12 not in b:
                b = None
                continue
        historia = [lb[meses[j + 12]] - lb[meses[j]] for j in range(0, t - 12)]
        if len(historia) < 24:
            continue
        media = sum(historia) / len(historia)
        cambios = [(meses[j], la[meses[j]] - la[meses[j - 1]]) for j in range(max(1, t - 12), t + 1)]
        p = pendiente(b, cambios, m) or 0.0
        y = lb[meses[t + 12]] - lb[m]
        casos.append((y, media + p, media))
    r2 = _r2_fuera(casos)
    ic = None
    if r2 is not None and remuestreos:
        rng = random.Random(semilla)
        n, vals = len(casos), []
        for _ in range(remuestreos):
            muestra = []
            while len(muestra) < n:
                j = rng.randrange(0, max(n - 12, 1))
                muestra.extend(casos[j:j + 12])
            v = _r2_fuera(muestra[:n])
            if v is not None:
                vals.append(v)
        vals.sort()
        if vals:
            ic = (vals[int(len(vals) * 0.025)], vals[int(len(vals) * 0.975) - 1])
    return {"r2": r2, "intervalo": ic, "casos": len(casos),
            "desde": meses[inicio] if len(meses) > inicio else None,
            "valido": bool(r2 is not None and r2 > 0 and ic and ic[0] > 0)}


def evaluar(arriba: dict, abajo: dict, desde: str = "", remuestreos: int = 300) -> dict:
    """Todo lo que se publica de un eslabon."""
    meses = _comunes(arriba, abajo, desde)
    if len(meses) < MINIMO_MESES:
        return {"clase": "pocos", "meses": len(meses)}
    t = traslado(arriba, abajo, meses)
    mitad = len(meses) // 2
    m1 = traslado(arriba, abajo, meses[:mitad], [PLAZO_PRINCIPAL])
    m2 = traslado(arriba, abajo, meses[mitad:], [PLAZO_PRINCIPAL])
    perfil = [{"h": h, "b": b, "bajo": b - Z95 * se, "alto": b + Z95 * se} for h, (b, se, _) in sorted(t.items())]
    p = t.get(PLAZO_PRINCIPAL)
    b1 = m1.get(PLAZO_PRINCIPAL, (None,))[0]
    b2 = m2.get(PLAZO_PRINCIPAL, (None,))[0]
    comprobado = bool(p and p[0] - Z95 * p[1] > 0 and b1 is not None and b1 > 0 and b2 is not None and b2 > 0)
    salida = {"clase": "comprobado" if comprobado else "no_se_aprecia", "meses": len(meses),
              "desde": meses[0], "hasta": meses[-1], "perfil": perfil,
              "mitades": {"corte": meses[mitad], "antes": b1, "despues": b2}}
    if not comprobado:
        return salida
    b12 = t.get(12, (None,))[0]
    if b12 and b12 > 0:   # cuanto tarda: primer plazo con la mitad del efecto a 12 meses
        salida["tarda_mitad"] = next((h for h in sorted(t) if t[h][0] >= b12 / 2), None)
    asi = asimetria(arriba, abajo, meses)
    salida["asimetria"] = {"plazos": asi, "clara": bool(asi.get(PLAZO_ASIMETRIA, {}).get("clara"))}
    prueba = probar_pendiente(arriba, abajo, meses, remuestreos)
    salida["prueba_pendiente"] = prueba
    if prueba["valido"]:
        ultimo_abajo = max(abajo)
        meses_arriba = sorted(arriba)
        cambios = [(meses_arriba[j], math.log(arriba[meses_arriba[j]] / arriba[meses_arriba[j - 1]]))
                   for j in range(max(1, len(meses_arriba) - 24), len(meses_arriba))]
        valor = pendiente({h: v[0] for h, v in t.items()}, cambios, ultimo_abajo)
        salida["pendiente"] = {"valor": None if valor is None else (math.exp(valor) - 1) * 100,
                               "desde_mes": ultimo_abajo, "arriba_hasta": meses_arriba[-1]}
    return salida


# ---------------------------------------------------------------------------
# Datos (disco)
# ---------------------------------------------------------------------------
def _mensual(pares) -> dict:
    d: dict[str, list[float]] = {}
    for f, v in pares:
        if v is not None and v > 0:
            d.setdefault(str(f)[:7], []).append(float(v))
    return {m: sum(v) / len(v) for m, v in d.items()}


def cargar_serie(ref: str, cambio: "apoyo.TipoCambio | None", en_euros: bool) -> dict:
    """ref = "origen:nombre": pink, pagados, boletin, eurostat o fred (apoyo)."""
    origen, _, nombre = ref.partition(":")
    archivos = {"pink": "pink.json", "pagados": "apoyo/pagados.json", "boletin": "apoyo/boletin.json",
                "eurostat": "apoyo/eurostat.json", "fred": "apoyo/fred.json"}
    datos = ((leer(archivos[origen], {}) or {}).get("series", {}) or {}).get(nombre, [])
    serie = _mensual(datos)
    if en_euros:
        if not cambio:
            return {}
        serie = {m: v / cambio.meses[m] for m, v in serie.items() if cambio.meses.get(m)}
    return serie


def ejecutar(cfg: dict) -> dict:
    ccfg = cfg.get("cadena") or {}
    cambio = apoyo.TipoCambio(apoyo.cambio_usd())
    remuestreos = int(ccfg.get("remuestreos", 300))
    cadenas = []
    for c in ccfg.get("cadenas", []):
        eslabones = []
        for e in c.get("eslabones", []):
            arriba = cargar_serie(e["arriba"]["serie"], cambio, e["arriba"].get("en_euros", False))
            abajo = cargar_serie(e["abajo"]["serie"], cambio, e["abajo"].get("en_euros", False))
            try:
                r = evaluar(arriba, abajo, str(e.get("desde", "")), remuestreos)
            except (ValueError, ZeroDivisionError) as err:
                log.warning("Cadena %s: %s", e["id"], err)
                r = {"clase": "pocos", "meses": 0}
            eslabones.append({"id": e["id"], "arriba": e["arriba"]["nombre"], "abajo": e["abajo"]["nombre"],
                              "arriba_corto": e["arriba"].get("corto", e["arriba"]["nombre"].lower()),
                              "abajo_corto": e["abajo"].get("corto", e["abajo"]["nombre"].lower()),
                              "fuentes": e.get("fuentes", ""), "nota": e.get("nota", ""), **r})
        cadenas.append({"id": c["id"], "nombre": c["nombre"], "eslabones": eslabones})
    resultado = {"cadenas": cadenas, "calculado": iso(), "plazo_principal": PLAZO_PRINCIPAL,
                 "plazo_asimetria": PLAZO_ASIMETRIA}
    escribir("cadena.json", resultado)
    return resultado
