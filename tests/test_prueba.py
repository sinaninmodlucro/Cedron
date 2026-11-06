"""Pruebas de la prueba historica de las reglas (cedron/prueba.py)."""
import math
import unittest

from cedron import build, prueba
from cedron import indicators as ind

from tests.test_cedron import CFG_IND, meses

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
        r = prueba.calcular(CFG, self.mensuales, self.tipo, self.dolar, {}, anios=15)
        self.assertEqual(set(r["activos"]), {"oro", "plata", "cobre"})
        self.assertEqual(r["activos"]["oro"]["meses"], 180)
        self.assertNotIn("macro", r["activos"]["cobre"]["indicadores"])
        # Sin datos de la CFTC el posicionamiento queda sin datos, sin romper nada
        self.assertEqual(r["activos"]["oro"]["indicadores"]["posicionamiento"]["veredicto"]["clase"],
                         "sin_datos")

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
        def filas(puntos, cambios):
            return [{"i": i, "mes": ind.restar_meses("2010-01", -i), "precio": 100, "puntos": {"x": p}}
                    for i, p in enumerate(puntos)], cambios

        def fut_de(cambios):
            return lambda f, h: cambios[f["i"]]

        # Tras +1 siempre sube y tras -1 siempre baja: coherente
        f, c = filas([1, -1, 0] * 20, [5, -5, 0] * 20)
        self.assertEqual(prueba.veredicto(f, "x", fut_de(c), (6,))["clase"], "coherente")
        # Lo contrario: al reves
        f, c = filas([1, -1, 0] * 20, [-5, 5, 0] * 20)
        self.assertEqual(prueba.veredicto(f, "x", fut_de(c), (6,))["clase"], "al_reves")
        # Funciona en la primera mitad y falla en la segunda: inestable
        f, c = filas([1, -1, 0] * 20, [5, -5, 0] * 10 + [-5, 5, 0] * 10)
        self.assertEqual(prueba.veredicto(f, "x", fut_de(c), (6,))["clase"], "inestable")
        # Casi siempre +1
        f, c = filas([1] * 50 + [0] * 10, [1] * 60)
        self.assertEqual(prueba.veredicto(f, "x", fut_de(c), (6,))["clase"], "fija")
        # Casi nunca da senal
        f, c = filas([0] * 58 + [1, -1], [1] * 60)
        self.assertEqual(prueba.veredicto(f, "x", fut_de(c), (6,))["clase"], "rara")

    def test_datos_para_la_web(self):
        r = prueba.calcular(CFG, self.mensuales, self.tipo, self.dolar, {}, anios=15)
        d = build.datos_prueba(r, CFG)
        self.assertEqual(d["indicadores"][0]["activo"], "Oro")
        self.assertEqual(d["indicadores"][0]["indicador"], "Tendencia")
        self.assertEqual(d["lecturas"][0]["lectura"], "Todos los meses")
        self.assertIsNone(build.datos_prueba(None, CFG))


if __name__ == "__main__":
    unittest.main()
