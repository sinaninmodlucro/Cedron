# Cedron

Web de análisis informativo sobre metales preciosos y materias primas. Se actualiza sola cada hora con datos de fuentes públicas y gratuitas, y se publica gratis en GitHub Pages.

## Cómo funciona

Cada hora, GitHub ejecuta el motor de Cedron:

1. Pide precios a MetalCharts (en las horas fijadas en `config.yaml`, de lunes a viernes, sin pasar del límite gratuito).
2. Una vez al día actualiza el histórico mensual del Banco Mundial, los datos macro de FRED y el posicionamiento de la CFTC.
3. Recoge noticias de los medios de la lista y de NewsData.io, las puntúa y se queda con las mejores.
4. Calcula los indicadores de cada metal y guarda el historial.
5. Genera la web y la publica.

Si una fuente falla tres veces seguidas, GitHub abre una incidencia y te llega un correo. La web sigue funcionando y marca los datos afectados.

## Puesta en marcha (una sola vez)

Los nombres de los menús de GitHub pueden variar ligeramente.

1. **Crea el repositorio.** En GitHub, botón «New repository», nombre `cedron`, visibilidad **Public** (necesario para que la automatización y la web sean gratuitas; tus claves nunca serán visibles).
2. **Sube los archivos** de esta carpeta (incluida la carpeta oculta `.github`). Desde la web: «Add file» → «Upload files» y arrastra todo.
3. **Guarda las claves como secretos.** En el repositorio: «Settings» → «Secrets and variables» → «Actions» → «New repository secret». Crea tres, con estos nombres exactos:
   - `METALCHARTS_KEY`: la clave de metalcharts.org (empieza por `mc_live_`)
   - `FRED_KEY`: la clave de fred.stlouisfed.org
   - `NEWSDATA_KEY`: la clave de newsdata.io

   Nunca pegues las claves en un chat, un correo o un archivo del repositorio.
4. **Activa la web.** «Settings» → «Pages» → en «Source», elige «GitHub Actions».
5. **Primera ejecución.** Pestaña «Actions» → «Actualizar Cedron» → «Run workflow», marca «Pedir todas las fuentes» y ejecuta. Tarda unos 2 minutos.
6. La web queda en `https://TU-USUARIO.github.io/cedron/`.

## Ajustar parámetros

Todo lo ajustable está en **`config.yaml`**, con una explicación en cada línea: umbrales de los indicadores, pesos y umbral de las noticias, lista de medios y su nota, horas de consulta de precios. Para cambiar algo, abre el archivo en GitHub, pulsa el lápiz, edita y guarda («Commit changes»). La web se regenera sola en un par de minutos.

Si un cambio afecta a la metodología, anótalo en la página de metodología (`templates/metodologia.html`, sección «Cambios en la metodología») para mantener la transparencia.

## Límites de los planes gratuitos

| Fuente | Límite | Cómo lo respeta Cedron |
| --- | --- | --- |
| MetalCharts | 200 consultas al mes | 6 consultas por día laborable (unas 130 al mes), con tope configurable en 190 |
| NewsData.io | 200 créditos al día | Una consulta por hora, tope de 150 al día |
| FRED | 120 consultas por minuto | 3 consultas al día |
| Banco Mundial, CFTC, RSS | Sin clave | Una vez al día (noticias: cada hora) |

## Para quien programe

```
pip install -r requirements.txt
python run.py --demo          # vista de ejemplo con datos inventados en _site_demo/
python run.py                 # ejecución real (necesita las claves como variables de entorno)
python -m unittest discover tests
```

Estructura: `cedron/sources.py` (conectores), `cedron/indicators.py` (cálculos, funciones puras), `cedron/news.py` (puntuación de noticias), `cedron/engine.py` (orquestación), `cedron/build.py` y `templates/` (web).

## Licencias de los datos

Banco Mundial Pink Sheet: CC BY 4.0. FRED: uso con atribución, solo series sin copyright de terceros. CFTC: dominio público. MetalCharts y NewsData.io: planes gratuitos con uso comercial permitido según sus condiciones (revisarlas antes del lanzamiento). Noticias: solo titular y enlace al original.
