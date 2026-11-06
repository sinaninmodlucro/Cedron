"""Pruebas de la cadena de costes con datos inventados de respuesta conocida."""
import math
import random
import unittest

from cedron import build, cadena
from cedron import indicators as ind


def meses(n, inicio="1990-01"):
    return [ind.restar_meses(inicio, -i) for i in range(n)]


def serie_aleatoria(n, semilla, sigma=0.05):
    rng = random.Random(semilla)
    x, out = 0.0, []
    for _ in range(n):
        x += rng.gauss(0, sigma)
        out.append(x)
    return out


class Cadena(unittest.TestCase):
    def setUp(self):
        self.m = meses(300)
        self.la = serie_aleatoria(300, 1)
        ruido = serie_aleatoria(300, 2, 0.01)
        # abajo = la mitad de arriba, con un mes de retraso, mas ruido pequeno
        self.arriba = {m: math.exp(v) * 100 for m, v in zip(self.m, self.la)}
        self.abajo = {m: math.exp(0.5 * (self.la[i - 1] if i else 0) + ruido[i]) * 50
                      for i, m in enumerate(self.m)}

    def test_traslado_conocido(self):
        r = cadena.evaluar(self.arriba, self.abajo, remuestreos=0)
        self.assertEqual(r["clase"], "comprobado")
        b = {x["h"]: x["b"] for x in r["perfil"]}
        self.assertAlmostEqual(b[0], 0.0, delta=0.08)      # en el mismo mes, casi nada
        self.assertAlmostEqual(b[6], 0.5, delta=0.08)      # a seis meses, la mitad
        self.assertEqual(r["tarda_mitad"], 1)

    def test_sin_relacion(self):
        otra = {m: math.exp(v) * 10 for m, v in zip(self.m, serie_aleatoria(300, 9))}
        self.assertEqual(cadena.evaluar(self.arriba, otra, remuestreos=0)["clase"], "no_se_aprecia")

    def test_pocos_datos(self):
        corto = {m: v for m, v in self.abajo.items() if m < "1994-01"}
        self.assertEqual(cadena.evaluar(self.arriba, corto, remuestreos=0)["clase"], "pocos")

    def test_subidas_y_bajadas(self):
        # abajo traslada las subidas enteras y las bajadas casi nada
        la, lb = self.la, [0.0]
        for i in range(1, 300):
            d = la[i] - la[i - 1]
            lb.append(lb[-1] + (d if d > 0 else 0.1 * d))
        abajo = {m: math.exp(v) * 20 for m, v in zip(self.m, lb)}
        a = cadena.asimetria(self.arriba, abajo, self.m)
        self.assertTrue(a[3]["clara"])
        self.assertGreater(a[3]["subidas"], a[3]["bajadas"])

    def test_pendiente(self):
        b = {h: min(h / 4, 1) * 0.5 for h in range(13)}          # llega del todo a los 4 meses
        # Arriba sube un 10 % (en log) en 2026-01; abajo tiene datos hasta 2026-02
        p = cadena.pendiente(b, [("2026-01", 0.1)], "2026-02")
        self.assertAlmostEqual(p, 0.1 * (0.5 - b[1]))
        # Si abajo ya tiene datos de 12 meses despues, no queda nada
        self.assertEqual(cadena.pendiente(b, [("2025-01", 0.1)], "2026-02"), 0.0)
        # Un cambio posterior al ultimo dato de abajo queda entero
        self.assertAlmostEqual(cadena.pendiente(b, [("2026-03", 0.1)], "2026-02"), 0.05)

    def test_huecos(self):
        """Los meses que faltan no se cuentan como cambios de un mes."""
        con_hueco = {m: v for i, (m, v) in enumerate(self.abajo.items()) if i % 25 != 0}
        r = cadena.evaluar(self.arriba, con_hueco, remuestreos=0)
        self.assertEqual(r["clase"], "comprobado")

    def test_contraer(self):
        self.assertEqual(build._contraer("de el diésel"), "del diésel")
        self.assertEqual(build._contraer("a el pollo"), "al pollo")
        self.assertEqual(build._contraer("de la urea"), "de la urea")


if __name__ == "__main__":
    unittest.main()
