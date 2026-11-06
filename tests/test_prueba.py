"""Pruebas de la prueba historica de las reglas (cedron/prueba.py)."""
import math
import unittest

from cedron import build, prueba
from cedron import indicators as ind

from tests.test_cedron import CFG_IND, meses  # noqa: F401

CFG = {
    "indicadores": CFG_IND,
    "activos": [
        {"id": "oro", "nombre": "Oro", "macro": True},
        {"id": "plata", "nombre": "Plata", "macro": True},
        {"id": "cobre", "nombre": "Cobre"},
    ],
}


def serie_ondulada(n, periodo=48, base=100.0, amplitud=30.0, inicio="2005-01"):
    return meses([base + amplitud * math.sin(2 * math.pi * i / periodo) + i * 0.1 for i in range(n)], inicio)


def macro_diaria(desde="2005-01", meses_total=264):
    tipo, dolar = [], []
    for i, (m, _) in enumerate(meses([0] * meses_total, desde)):
        tipo.append((f"{m}-15", math.sin(i / 7)))
        dolar.append((f"{m}-15", 100 + 5 * math.cos(i / 9)))
    return tipo, dolar


class PruebaHistorica(unittest.TestCase):
    def setUp(self):
        n = 264   # 22 anios
        self.mensuales = {"oro": serie_ondulada(n), "plata": serie_ondulada(n, 36, 20, 6),
                          "cobre": serie_ondulada(n, 60, 3, 1)}
        self.tipo, self.dolar = macro_diaria()

    def test_calcula_todos_los_activos_y_meses(self):
        r = prueba.calcular(CFG, self.mensuales, self.tipo, self.dolar, {}, anios=15,
                            corte="2019-01", remuestreos=20)
        self.assertEqual(set(r["activos"]), {"oro", "plata", "cobre"})
        self.assertEqual(r["activos"]["oro"]["meses"], 180)
        self.assertNotIn("macro", r["activos"]["cobre"]["indicadores"])
        self.assertIn("suma", r["activos"]["oro"]["indicadores"])
        # Sin datos de la CFTC el posicionamiento queda sin datos, sin romper nada
        self.assertEqual(r["activos"]["oro"]["indicadores"]["posicionamiento"]["veredicto"]["clase"],
                         "sin_datos")

    def test_candidatas(self):
        cand = {"m12": {"texto": "Momento 12", "indicadores": {"momento": {"meses": 12, "umbral_pct": 0}}},
                "sin_ratio": {"texto": "Sin ratio", "quitar": {"oro": ["ratio"]}}}
        r = prueba.calcular(CFG, self.mensuales, self.tipo, self.dolar, {}, anios=15,
                            corte="2019-01", remuestreos=0, candidatas=cand)
        # La candidata solo evalua lo que cambia (y la suma)
        self.assertEqual(set(r["candidatas"]["m12"]["activos"]["oro"]["indicadores"]), {"momento", "suma"})
        self.assertEqual(set(r["candidatas"]["sin_ratio"]["activos"]["oro"]["indicadores"]), {"suma"})
        self.assertEqual(r["candidatas"]["sin_ratio"]["activos"]["oro"]["quitados"], ["ratio"])
        # Las reglas actuales no se tocan
        self.assertEqual(r["activos"]["oro"]["quitados"], [])

    def test_lectura_igual_que_la_web(self):
        cl = CFG_IND["lectura"]
        for puntos in ({"a": 1, "b": 1, "c": 0}, {"a": -1, "b": -1, "c": 1}, {"a": 1, "b": None, "c": 0},
                       {"a": -1, "b": -1, "c": -1, "d": 1}):
            res = [ind.Resultado(k, k, v, "", "") for k, v in puntos.items()]
            web = ind.combinar("oro", "Oro", res, cl).lectura
            esperado = {1: "favorable", 0: "neutral", -1: "desfavorable", None: "datos insuficientes"}
            self.assertEqual(esperado[prueba.lectura_de(puntos, set(), cl)], web, puntos)

    def test_salto_de_un_mes(self):
        serie = meses([100, 200, 400, 400, 400])
        filas = [{"i": 0}]
        self.assertEqual(prueba._futuros(serie, filas, (1,), 0)[0][1], 100.0)
        self.assertEqual(prueba._futuros(serie, filas, (1,), 1)[0][1], 100.0)   # 200 -> 400
        self.assertEqual(prueba._futuros(serie, filas, (2,), 1)[0][2], 100.0)
        self.assertEqual(prueba._futuros(serie, filas, (3,), 1)[0][3], 100.0)   # 200 -> 400

    def test_no_mira_al_futuro(self):
        """La senal de un mes no puede cambiar si se alteran los meses posteriores."""
        a = prueba.senales(CFG, self.mensuales, self.tipo, self.dolar, {}, 15)
        alterado = {k: v[:200] + [(m, x * 3) for m, x in v[200:]] for k, v in self.mensuales.items()}
        corte = self.mensuales["oro"][200][0]          # primer mes alterado
        tipo = [(f, v if f < corte else v + 5) for f, v in self.tipo]
        b = prueba.senales(CFG, alterado, tipo, self.dolar, {}, 15)
        comprobados = 0
        for aid in a:
            for fa, fb in zip(a[aid], b[aid]):
                if fa["mes"] < corte:
                    self.assertEqual(fa["puntos"], fb["puntos"], (aid, fa["mes"]))
                    comprobados += 1
        self.assertGreater(comprobados, 100)

    def test_veredictos(self):
        def caso(puntos, cambios, remuestreos=200):
            f = [{"i": i, "mes": ind.restar_meses("1990-01", -i), "puntos": {"x": p}}
                 for i, p in enumerate(puntos)]
            fut = {i: {6: c} for i, c in enumerate(cambios)}
            return prueba.veredicto(f, "x", fut, (6,), "2000-01", remuestreos)["clase"]

        n = 80   # 240 meses: 1990-2009, corte en 2000
        # Tras +1 sube y tras -1 baja en los dos periodos: coherente
        self.assertEqual(caso([1, -1, 0] * n, [5, -5, 0] * n), "coherente")
        # Lo contrario: al reves
        self.assertEqual(caso([1, -1, 0] * n, [-5, 5, 0] * n), "al_reves")
        # Funciona en el periodo de eleccion y falla en el de comprobacion: inestable
        self.assertEqual(caso([1, -1, 0] * n, [5, -5, 0] * 40 + [-5, 5, 0] * 40), "inestable")
        # Casi siempre +1
        self.assertEqual(caso([1] * 200 + [0] * 40, [1] * 240), "fija")
        # Casi nunca da senal
        self.assertEqual(caso([0] * 236 + [1, -1, 1, -1], [1] * 240), "rara")

    def test_pocos_aciertos_por_casualidad(self):
        """Con cambios inventados al azar, casi nunca debe salir un resultado seguro."""
        import random
        f = [{"i": i, "mes": ind.restar_meses("1990-01", -i), "puntos": {"x": p}}
             for i, p in enumerate([1, -1, 0] * 80)]
        falsos = 0
        for s in range(60):
            rng = random.Random(s)
            fut = {i: {6: rng.gauss(0, 40)} for i in range(240)}
            clase = prueba.veredicto(f, "x", fut, (6,), "2000-01", 100, semilla=s)["clase"]
            falsos += clase in ("coherente", "al_reves")
        self.assertLessEqual(falsos, 6)    # 10 % como maximo (lo esperado es ~5 %)

    def test_datos_para_la_web(self):
        r = prueba.calcular(CFG, self.mensuales, self.tipo, self.dolar, {}, anios=15,
                            corte="2019-01", remuestreos=0,
                            candidatas={"m12": {"texto": "M", "indicadores": {"momento": {"meses": 12}}}})
        d = build.datos_prueba(r, CFG)
        self.assertEqual(d["fin_eleccion"], "2018-12")
        self.assertEqual(d["candidatas"][0]["texto"], "M")
        self.assertEqual(d["indicadores"][0]["activo"], "Oro")
        self.assertEqual(d["indicadores"][0]["indicador"], "Tendencia")
        self.assertEqual(d["lecturas"][0]["lectura"], "Todos los meses")
        self.assertIsNone(build.datos_prueba(None, CFG))


if __name__ == "__main__":
    unittest.main()
