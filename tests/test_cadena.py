"""Pruebas de la cadena de costes con datos inventados de respuesta conocida."""
import math
import random
import unittest

from cedron import build, cadena, prevision
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

    def test_pendiente_por_plazo(self):
        b = {h: min(h / 4, 1) * 0.5 for h in range(13)}
        # Visto hace 1 mes: en 2 meses mas llega hasta b[3]; en 12, todo
        self.assertAlmostEqual(cadena.pendiente(b, [("2026-01", 0.1)], "2026-02", 2), 0.1 * (b[3] - b[1]))
        self.assertAlmostEqual(cadena.pendiente(b, [("2026-01", 0.1)], "2026-02", 12), 0.1 * (0.5 - b[1]))

    def test_previsiones_e_historial(self):
        r = cadena.evaluar(self.arriba, self.abajo, remuestreos=0)
        self.assertEqual(set(r["previsiones"]), {"3", "12"})
        self.assertEqual(set(r["previsiones"]["3"]["piezas"]), {"traslado", "inercia", "desfase"})
        p3 = r["previsiones"]["3"]
        self.assertEqual(p3["vence"], ind.restar_meses(p3["desde_mes"], -3))
        self.assertGreater(p3["prueba"]["acierto_direccion"], 0.5)   # el traslado es real: acierta
        # Se apunta una vez; al llegar el dato del mes de vencimiento se anota el resultado
        registro = cadena.anotar_previsiones([], "x", r["previsiones"], self.abajo)
        cadena.anotar_previsiones(registro, "x", r["previsiones"], self.abajo)
        self.assertEqual(len(registro), 2)
        futuro = {**self.abajo, p3["vence"]: p3["base"] * 1.10}
        cadena.anotar_previsiones(registro, "x", {}, futuro)
        hecho = [x for x in registro if x["plazo"] == 3][0]
        self.assertAlmostEqual(hecho["real"], 10.0)
        res = cadena.resumen_previsiones(registro, "x")
        self.assertEqual((res["hechas"], res["vencidas"]), (2, 1))

    def test_combinacion_de_calculos(self):
        """Un rasgo que de verdad anticipa el precio mejora a la media; uno de ruido, no."""
        rng = random.Random(5)
        senal = [rng.gauss(0, 1) for _ in range(400)]
        lp, x = {0: 0.0}, 0.0
        for n in range(1, 400):
            x += 0.02 * senal[n - 1] + rng.gauss(0, 0.02)      # el cambio de n depende de la senal de n-1
            lp[n] = x
        bueno = {n: [senal[n]] for n in range(400)}
        ruido = {n: [rng.gauss(0, 1)] for n in range(400)}
        c = prevision.combinar(lp, {"bueno": bueno}, 1, 200, remuestreos=100)
        self.assertTrue(c["prueba"]["valido"])
        self.assertGreater(c["prueba"]["acierto_direccion"], 0.6)
        self.assertIn("bueno", c["prevision"]["piezas"])
        c = prevision.combinar(lp, {"ruido": ruido}, 1, 200, remuestreos=100)
        self.assertFalse(c["prueba"]["valido"])
        # Sin rasgos, la prevision es la media historica
        c = prevision.combinar(lp, {}, 3, 200, remuestreos=0)
        self.assertAlmostEqual(c["prevision"]["total"], c["prevision"]["media"])
        # Un calculo externo (como el traslado pendiente) entra en la media a partes iguales
        c = prevision.combinar(lp, {}, 3, 200, {"ext": {399: 0.01}}, 399, remuestreos=0)
        self.assertAlmostEqual(c["prevision"]["total"], c["prevision"]["media"] + 0.005)

    def test_rasgos_de_metal_usan_el_mes_anterior(self):
        lp = {n: 0.01 * n for n in range(100)}
        r = prevision.rasgos_metal(lp, {})
        self.assertAlmostEqual(r["tendencia"][50][0], lp[49] - lp[37])
        self.assertNotIn(12, r["tendencia"])
        self.assertEqual(prevision.mes(prevision.num("2026-11")), "2026-11")

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
