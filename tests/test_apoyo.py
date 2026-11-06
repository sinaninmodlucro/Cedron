"""Pruebas de las materias primas de apoyo (conectores simulados y calculos)."""
import io
import unittest
from datetime import date, datetime
from unittest import mock

from cedron import apoyo
from cedron import sources as src
from test_fuentes import Respuesta


def excel(filas, hoja="Hoja1"):
    from openpyxl import Workbook
    wb = Workbook()
    wb.active.title = hoja
    for f in filas:
        wb.active.append(f)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class Conectores(unittest.TestCase):
    def test_carburantes(self):
        estaciones = [{"Precio Gasoleo A": "1,800"}, {"Precio Gasoleo A": "2,000"}, {"Precio Gasoleo A": ""}] * 600
        cuerpo = {"Fecha": "06/11/2026 12:31:54", "ListaEESSPrecio": estaciones, "ResultadoConsulta": "OK"}
        with mock.patch("cedron.sources.requests.get", return_value=Respuesta(json_=cuerpo)):
            d = src.carburantes_media(["Precio Gasoleo A"])
        media, n = d["medias"]["Precio Gasoleo A"]
        self.assertAlmostEqual(media, 1.9)
        self.assertEqual(n, 1200)                       # los vacios no cuentan
        self.assertEqual(d["fecha"], "2026-11-06T11:31:54Z")   # hora de Madrid (CET) a UTC

    def test_carburantes_formato_cambiado(self):
        cuerpo = {"Fecha": "06/11/2026 12:31:54", "ListaEESSPrecio": [{"Otro": "1"}] * 2000}
        with mock.patch("cedron.sources.requests.get", return_value=Respuesta(json_=cuerpo)):
            with self.assertRaisesRegex(src.FuenteError, "pocas gasolineras"):
                src.carburantes_media(["Precio Gasoleo A"])

    def test_boletin(self):
        contenido = excel([
            ["Consumer prices", "CTR", "EU_price_with_tax_diesel", "CTR", "ES_price_with_tax_diesel"],
            [None, None, "Gas oil", None, "Gas oil"],
            ["Date", None, "1000 l", None, "1000 l"],
            [datetime(2026, 11, 2), "EU_", 2153.9, "ES_", 1898.3],
            [datetime(2026, 10, 26), "EU_", 2146.0, "ES_", None],
        ], hoja="Prices with taxes")
        pagina = Respuesta('<a href="/document/download/x_en?filename=Weekly_Oil_Bulletin_Prices_History_maticni_4web.xlsx">x</a>')
        with mock.patch("cedron.sources.requests.get", side_effect=[pagina, Respuesta(contenido)]):
            s = src.boletin_petroleo(["EU_price_with_tax_diesel", "ES_price_with_tax_diesel"])
        self.assertEqual(s["EU_price_with_tax_diesel"], [("2026-10-26", 2146.0), ("2026-11-02", 2153.9)])
        self.assertEqual(s["ES_price_with_tax_diesel"], [("2026-11-02", 1898.3)])

    def test_mapa(self):
        contenido = excel([
            ["PRECIOS MEDIOS NACIONALES"],
            [2026],
            ["SECTOR", "(esp)", "PRODUCTOS AGRARIOS", "Semana 43", "Semana 44"],
            [None, None, None, "19/10-25/10", "26/10-01/11"],
            ["PORCINO", "(14)", "Porcino >60% magro (S) (€/100kg Canal)", 163.93, 160.25],
            [None, "(15)", "Pollo (€/100kg Canal) ", 234.38, "-"],
        ])
        pagina = Respuesta('<a href="/dam/x/precios_medios_nacionales_2025-s52.xlsx">a</a>'
                           '<a href="/dam/x/precios_medios_nacionales_2026-s36.xlsx">b</a>')
        with mock.patch("cedron.sources.requests.get", side_effect=[pagina, Respuesta(contenido)]) as g:
            s = src.mapa_semanal(["Porcino >60% magro (S)", "Pollo ("])
        self.assertTrue(g.call_args_list[1][0][0].endswith("2026-s36.xlsx"))     # el ano mas reciente
        self.assertEqual(g.call_args_list[1][1]["verify"], src.CERT_FNMT)        # verifica con la FNMT
        self.assertEqual(s["Porcino >60% magro (S)"], [("2026-10-19", 163.93), ("2026-10-26", 160.25)])
        self.assertEqual(s["Pollo ("], [("2026-10-19", 234.38)])                 # "-" se descarta

    def test_mapa_producto_inexistente(self):
        contenido = excel([["SECTOR", "x", "PRODUCTOS", "Semana 44"], [None, None, "Otra cosa", 1.0]])
        pagina = Respuesta('<a href="/dam/x/precios_medios_nacionales_2026.xlsx">b</a>')
        with mock.patch("cedron.sources.requests.get", side_effect=[pagina, Respuesta(contenido)]):
            with self.assertRaisesRegex(src.FuenteError, "producto no encontrado"):
                src.mapa_semanal(["Pollo ("])

    def test_mapa_producto_de_temporada_sin_datos(self):
        contenido = excel([
            ["SECTOR", "x", "PRODUCTOS", "Semana 1"],
            [None, "(12)", "Naranja (€/100kg)", "-"],              # fuera de temporada
            [None, "(13)", "Patata (€/100kg)", 39.25],
        ])
        pagina = Respuesta('<a href="/dam/x/precios_medios_nacionales_2027.xlsx">b</a>')
        with mock.patch("cedron.sources.requests.get", side_effect=[pagina, Respuesta(contenido)]):
            s = src.mapa_semanal(["Naranja (", "Patata"])
        self.assertEqual(s["Naranja ("], [])                      # sin datos, pero no rompe la fuente
        self.assertEqual(s["Patata"], [("2027-01-04", 39.25)])

    def test_precios_pagados(self):
        def libro(filas):
            from openpyxl import Workbook
            wb = Workbook()
            wb.active.title = "CONTENIDO A"
            wb.active.append(["UREA 46%"])                         # indice: sin cabecera, se ignora
            h = wb.create_sheet("PrePag1")
            for f in filas:
                h.append(f)
            buf = io.BytesIO()
            wb.save(buf)
            return buf.getvalue()
        cab = [["PRECIOS PAGADOS POR LOS AGRICULTORES"], ["EUROS POR 100kg s/IVA"],
               ["PRODUCTOS", "AÑO", "Enero", "Febrero", "Marzo"]]
        nuevo = libro(cab + [["ABONOS"], ["UREA 46% (100kg)", 2026, 75.0, 78.5, 0],
                             [None, 2025, 50.0, 51.0, 52.0],
                             ["NITRATO AMONICO 33,5 (100kg)", 2026, 60.0, 61.0, 0]])
        viejo = libro(cab + [["UREA   46%  (100kg)", 2025, 49.0, 49.5, 49.9],
                             [None, 2024, 40.0, None, None]])
        pagina = Respuesta('<a href="/dam/x/indices-y-precios-pagados-agrarios--2026-.xlsx">n</a>'
                           '<a href="/dam/x/indicesypreciospagadosagrariosenero2015.xlsx">v</a>')
        with mock.patch("cedron.sources.requests.get",
                        side_effect=[pagina, Respuesta(viejo), Respuesta(nuevo)]) as g:
            d = src.precios_pagados(["UREA 46%"])
        self.assertEqual(g.call_args_list[1][0][0], "https://www.mapa.gob.es/dam/x/indicesypreciospagadosagrariosenero2015.xlsx")
        self.assertEqual(d["UREA 46%"], [("2024-01", 40.0), ("2025-01", 50.0), ("2025-02", 51.0), ("2025-03", 52.0),
                                         ("2026-01", 75.0), ("2026-02", 78.5)])   # manda el reciente; el 0 no cuenta

    def test_bce_cambio(self):
        csv_ = ("KEY,FREQ,TIME_PERIOD,OBS_VALUE,TITLE\n"
                "EXR.D.USD.EUR.SP00.A,D,2026-11-06,1.1165,\"US dollar/Euro, 2.15 pm\"\n"
                "EXR.D.USD.EUR.SP00.A,D,2026-11-05,1.1224,x\n"
                "EXR.D.USD.EUR.SP00.A,D,2026-11-04,,x\n")
        with mock.patch("cedron.sources.requests.get", return_value=Respuesta(csv_)):
            s = src.bce_cambio("USD", "2026-11-01")
        self.assertEqual(s, [("2026-11-05", 1.1224), ("2026-11-06", 1.1165)])     # el vacio no cuenta

    def test_eurostat(self):
        # JSON-stat: 2 territorios x 2 actividades x 2 meses, aplanado en ese orden
        cuerpo = {"id": ["freq", "unit", "nace_r2", "geo", "time"], "size": [1, 1, 2, 2, 2],
                  "dimension": {"freq": {"category": {"index": {"M": 0}}},
                                "unit": {"category": {"index": {"I21": 0}}},
                                "nace_r2": {"category": {"index": {"C241": 0, "C2442": 1}}},
                                "geo": {"category": {"index": {"EU27_2020": 0, "ES": 1}}},
                                "time": {"category": {"index": {"2026-08": 0, "2026-09": 1}}}},
                  "value": {"0": 104.9, "1": 105.3, "2": 107.5, "4": 141.4, "5": 141.1, "6": 141.6, "7": 140.6}}
        with mock.patch("cedron.sources.requests.get", return_value=Respuesta(json_=cuerpo)) as g:
            s = src.eurostat_indices(["ES|C2442", "EU27_2020|C241", "ES|C241"], "2016-01")
        self.assertEqual(s["ES|C2442"], [("2026-08", 141.6), ("2026-09", 140.6)])
        self.assertEqual(s["EU27_2020|C241"], [("2026-08", 104.9), ("2026-09", 105.3)])
        self.assertEqual(s["ES|C241"], [("2026-08", 107.5)])               # el dato que falta no se inventa
        self.assertIn(("unit", "I21"), g.call_args[1]["params"])
        with mock.patch("cedron.sources.requests.get", return_value=Respuesta(json_=cuerpo)):
            with self.assertRaisesRegex(src.FuenteError, "no tiene la serie"):
                src.eurostat_indices(["FR|C241"], "2016-01")

    def test_panel_nombre_repetido(self):
        orden = [("CACAO SOLUBLE", ["CACAO SOLUBLE", 7.7]), ("NORMAL", ["NORMAL", 7.6]),
                 ("ARROZ", ["ARROZ", 2.4]), ("NORMAL", ["NORMAL", 1.6]), ("TOMATES", ["TOMATES", 2.4]),
                 ("TOMATES", ["TOMATES", 2.0])]
        self.assertEqual(src._fila_panel(orden, "ARROZ>NORMAL")[1], 1.6)
        self.assertEqual(src._fila_panel(orden, "TOMATES")[1], 2.4)          # la primera: frescos
        self.assertIsNone(src._fila_panel(orden, "PASTA>NORMAL"))

    def test_panel_consumo(self):
        def hoja(titulo, mes):
            return [["CONSUMO HOGARES"],
                    [mes, "PENETRACION (%)", None, "PRECIO MEDIO kg ó litros", None, "VALOR"],
                    [None, "T.ESPAÑA", "SUPERMERCADO", "T.ESPA�A", "SUPERMERCADO", "T.ESPAÑA"],
                    ["CARNE CERDO", 77.5, 60.1, 7.62, 7.16, 999.0]]
        from openpyxl import Workbook
        wb = Workbook()
        wb.active.title = "Julio 2026"
        for f in hoja("Julio 2026", "JULIO 26"):
            wb.active.append(f)
        h = wb.create_sheet("agosto")                         # formato antiguo: mes solo en el titulo interno
        for f in hoja("agosto", "AGOSTO 26"):
            h.append(f)
        buf = io.BytesIO()
        wb.save(buf)
        pagina = Respuesta('<a href="/es/dam/x/2026ago-datos-mensuales-panel-consumo-hogares-canales-base2021.abc.xlsx">x</a>')
        with mock.patch("cedron.sources.requests.get", side_effect=[pagina, Respuesta(buf.getvalue())]):
            d = src.panel_consumo([("CARNE CERDO", "SUPERMERCADO"), ("CARNE CERDO", "T.ESPAÑA")])
        self.assertEqual(d[("CARNE CERDO", "SUPERMERCADO")], [("2026-07", 7.16), ("2026-08", 7.16)])
        self.assertEqual(d[("CARNE CERDO", "T.ESPAÑA")][-1], ("2026-08", 7.62))   # bloque de precio, no penetracion


class Salud(unittest.TestCase):
    def test_fuente_sin_uso_no_avisa(self):
        from cedron import engine
        cfg = {"medios": [], "apoyo": {"grupos": [{"materias": [
            {"ambitos": {"espana": {"fuente": "boletin", "columna": "ES"}}}]}]}}
        estado = mock.Mock()
        fuentes = {"Ministerio (carburantes)": {"fallos_seguidos": 3},
                   "Comisión Europea (Oil Bulletin)": {"fallos_seguidos": 3}}
        estado.get.return_value = fuentes
        avisos = engine.revisar_salud(cfg, estado)
        self.assertEqual(len(avisos), 1)                          # solo la que se sigue usando
        self.assertIn("Oil Bulletin", avisos[0])
        self.assertNotIn("Ministerio (carburantes)", fuentes)     # y se olvida su historial


class Calculos(unittest.TestCase):
    def test_tipo_cambio(self):
        c = apoyo.TipoCambio([["2026-09-29", 1.10], ["2026-09-30", 1.20], ["2026-10-01", 1.25], ["2026-10-02", 1.15]])
        self.assertAlmostEqual(c.en("2026-09"), 1.15)                 # mensual: media del mes
        self.assertEqual(c.en("2026-10-04"), 1.15)                    # fin de semana: el ultimo dia con dato
        self.assertIsNone(c.en("2026-11-30"))                         # demasiado lejos: no se inventa
        euros = c.a_euros([("2026-09", 115.0), ("2020-01", 1.0)])       # 2020: sin cambio, se descarta
        self.assertEqual([f for f, _ in euros], ["2026-09"])
        self.assertAlmostEqual(euros[0][1], 100.0)

    def test_preferir_supermercado(self):
        todas = [("2026-06", 7.5), ("2026-07", 7.6), ("2026-08", 7.7)]
        super_ = [("2026-08", 7.2)]
        self.assertEqual(apoyo.preferir(todas, super_), [("2026-06", 7.5), ("2026-07", 7.6), ("2026-08", 7.2)])

    def test_multiplicador(self):
        origen = [("2026-08-03", 1.6), ("2026-08-10", 1.8), ("2026-09-07", 2.0)]
        m = apoyo.multiplicador(origen, "2026-08", 6.8)
        self.assertAlmostEqual(m["veces"], 4.0)
        self.assertIsNone(apoyo.multiplicador(origen, "2026-05", 6.8))      # sin origen ese mes

    def test_combinar_historia_mensual(self):
        historia = [("2026-08", 1.0), ("2026-09", 2.0), ("2026-10", 3.0)]
        actual = [("2026-10-05", 10.0), ("2026-10-06", 11.0)]
        self.assertEqual(apoyo.combinar(historia, actual),
                         [("2026-08", 1.0), ("2026-09", 2.0), ("2026-10-05", 10.0), ("2026-10-06", 11.0)])

    def test_fred_mensual_como_mes(self):
        fuentes = {"fred": {"PPORKUSDM": [["2026-08-01", 80.0], ["2026-09-01", 83.0]]}}
        d = {"fuente": "fred", "serie": "PPORKUSDM", "frecuencia": "mensual", "factor": 0.5}
        self.assertEqual(apoyo._serie(d, fuentes), [("2026-08", 40.0), ("2026-09", 41.5)])

    def test_resumen(self):
        serie = [(f"{a}-{m:02d}", 100.0 + i) for i, (a, m) in
                 enumerate((a, m) for a in (2025, 2026) for m in range(1, 13))][:22]   # 2025-01 .. 2026-10
        r = apoyo.resumen(serie, 10)
        self.assertEqual((r["fecha"], r["valor"]), ("2026-10", 121.0))
        self.assertAlmostEqual(r["cambio_pct"], (121 / 120 - 1) * 100)
        self.assertAlmostEqual(r["interanual_pct"], (121 / 109 - 1) * 100)     # frente a 2025-10
        self.assertEqual(r["tendencia"]["pendiente"], "subiendo")
        self.assertGreater(r["tendencia"]["diferencia_pct"], 0)

    def test_resumen_no_compara_fuentes_distintas(self):
        serie = [("2026-11-02", 1.90), ("2026-11-06", 1.88)]     # boletin UE + 1 dato del Ministerio
        self.assertIsNone(apoyo.resumen(serie, 10, n_actual=1)["cambio_pct"])
        self.assertIsNotNone(apoyo.resumen(serie, 10, n_actual=2)["cambio_pct"])

    def _amb(self, fecha, frecuencia):
        return {"resumen": {"fecha": fecha}, "frecuencia": frecuencia}

    def test_elegir(self):
        dias = {"horaria": 2, "diaria": 10, "semanal": 21, "mensual": 75}
        hoy = date(2026, 11, 6)
        ambitos = {"espana": self._amb("2026-10-26", "semanal"), "global": self._amb("2026-10", "mensual")}
        self.assertEqual(apoyo.elegir(ambitos, "espana", dias, hoy), ("espana", None))
        # Europa no existe: se muestra el dato mas reciente (el mensual de octubre cuenta hasta el 31)
        self.assertEqual(apoyo.elegir(ambitos, "europa", dias, hoy), ("global", "sin datos de Europa"))
        # Espana antigua y global mas nueva: se cambia a global
        viejo = {"espana": self._amb("2026-08-03", "semanal"), "global": self._amb("2026-10", "mensual")}
        self.assertEqual(apoyo.elegir(viejo, "espana", dias, hoy), ("global", "sin dato reciente de España"))
        # Espana antigua pero nadie tiene nada mas nuevo: se queda Espana
        solo = {"espana": self._amb("2026-08-03", "semanal")}
        self.assertEqual(apoyo.elegir(solo, "espana", dias, hoy), ("espana", None))
        self.assertEqual(apoyo.elegir({}, "espana", dias, hoy), (None, None))
        # Fuente oficial con retraso conocido ('dias_reciente' propio): sigue valiendo
        lento = {"espana": {**self._amb("2026-07", "mensual"), "dias_reciente": 150},
                 "global": self._amb("2026-10", "mensual")}
        self.assertEqual(apoyo.elegir(lento, "espana", dias, hoy), ("espana", None))


if __name__ == "__main__":
    unittest.main()
