# Cedron: contexto para Claude

Este archivo resume todo lo decidido y construido hasta el 6 de noviembre de 2026. Léelo entero antes de proponer cambios.

## Quién es el usuario y cómo trabajar con él

- Es el dueño del proyecto. **No sabe programar** y es la primera vez que usa GitHub. Habla **español**: responde siempre en español.
- Explica las cosas paso a paso, con palabras sencillas y sin jerga. Si hay que tocar algo en GitHub, di exactamente qué botón pulsar.
- Quiere un proyecto **profesional, sin prisas**: prioriza que las cosas funcionen bien y sean fiables antes que hacerlas rápido.
- Decidió que todo sea **automático**. Si algo no le convence, se ajustan parámetros en `config.yaml` (no se añaden revisiones manuales).
- Si se añade o cambia una regla de la metodología, **se le informa y se decide con él**, y se anota en la página de metodología («Cambios en la metodología»).
- Nunca le pidas que pegue claves o contraseñas en el chat. Los secretos se guardan solo en GitHub.

## Qué es Cedron

Web **privada, de uso personal**, de análisis **informativo** sobre metales preciosos y materias primas: precios actualizados, noticias filtradas por relevancia y un panel de indicadores objetivos por activo. Se actualiza sola cada hora con fuentes gratuitas.

- Repositorio: https://github.com/sinaninmodlucro/Cedron (público; el código y los datos de mercado son visibles, no hay nada personal).
- Web: https://sinaninmodlucro.github.io/Cedron/ — **cada página se publica cifrada** y se abre con contraseña.
- Plan original del proyecto (documento): https://claude.ai/artifact/XvoXociiTkrfZtVwdyNqas
- Activos: oro, plata, platino, paladio, cobre. Fase 2 prevista: energía y agrícolas (desde el histórico del Banco Mundial).

## Límites legales (no los rompas)

Aunque ahora es de uso privado, se diseñó para poder abrirse al público en España sin autorización de la CNMV:

- Es **información general, no asesoramiento**. Nada de recomendaciones personalizadas, perfiles o cuestionarios.
- Se habla del **activo** (el oro como materia prima), **nunca de productos financieros concretos** (ETF, ETC, fondos, acciones mineras). Por eso hay filtros que descartan noticias de compraventa de ETF/acciones.
- Lecturas como «favorable / neutral / desfavorable» con los datos que las justifican, nunca «compra» o «vende».
- Transparencia: metodología publicada, autor identificado, fecha y fuente de cada dato, historial público de aciertos y fallos.
- Si alguna vez se abre al público: desactivar los cuatro feeds marcados como «solo uso privado» en `config.yaml`, revisar las condiciones de los RSS del FT e Investing.com, y completar `templates/legal.html` (titular, NIF, domicilio, conflictos de interés; ahora tiene corchetes) y validarlo con un abogado de mercado de valores.

## Arquitectura

Web estática autogenerada. Sin servidor ni base de datos.

```
GitHub Actions (cada hora, minuto 17 UTC)  →  run.py
  1. cedron/engine.py   recoge y valida datos  → data/*.json (se guardan en el repo)
  2. cedron/indicators.py  calcula indicadores (funciones puras)
  3. cedron/news.py     puntúa y selecciona noticias
  4. cedron/build.py    genera la web en _site/ con templates/ (Jinja2)
  5. cedron/cifrado.py  cifra cada página (si existe CEDRON_PASSWORD)
  6. GitHub Pages publica _site/ (solo si existe la contraseña)
```

- `config.yaml`: **todos los parámetros ajustables**, comentados línea a línea. Es lo primero que hay que tocar para cualquier ajuste.
- `cedron/apoyo.py`: **materias primas de apoyo** (sección `apoyo` de `config.yaml`): recoge, guarda en `data/apoyo/*.json` y calcula el resumen (último dato, cambio frente al anterior de la misma fuente, interanual y posición frente a la media de 10 meses). Elige qué ámbito mostrar (España / Europa / Global) con `elegir()`. Páginas `templates/materias.html` y `templates/materia.html`; selectores en `static/vistas.js` (pestañas por grupo con `pestana:` en `config.yaml`, ámbito España/Europa/Global y precio «Origen y tienda / En origen / En tienda»; el segundo aparece en cualquier materia con `tienda:` en `config.yaml`, y se usará también para las agrícolas).
- **Euros**: las materias de apoyo en dólares se pasan a euros con el cambio de cada fecha (`apoyo.TipoCambio`, DEXUSEU de FRED, guardado 11 años en `data/macro.json`); se muestra al lado el último precio en dólares. Se desactiva con `apoyo.en_euros: false`.
- **Comparar** (`templates/comparar.html` + `static/comparar.js`): elegir materias sueltas y grupos «en conjunto» (media simple en base 100), por ámbito y periodo (1, 3, 5, 10 años); máximo 8 líneas con la paleta validada para daltonismo (`--serie-1..8` en `estilo.css`, claro y oscuro). Los datos los prepara `build.datos_comparacion`.
- `cedron/certificados/`: certificado raíz público de la FNMT, necesario para verificar `www.mapa.gob.es` (Python no lo trae). Solo se usa para esa web.
- `cedron/sources.py`: conectores. Lanzan `FuenteError` con mensaje claro; nunca inventan datos.
- `cedron/store.py`: lectura/escritura atómica de JSON en `data/` (o `CEDRON_DATA`).
- `cedron/demo.py`: datos **inventados** para ver la web sin claves (`python run.py --demo` → `_site_demo/`, con aviso visible).
- `templates/acceso.html`: pantalla de contraseña (no pasa por Jinja; usa `__DATOS__` y `__RAIZ__`).
- `tests/`: 47 pruebas (`python -m unittest discover tests`). Se ejecutan en cada actualización; **pásalas antes de subir cambios**.
- `.github/workflows/actualizar.yml`: la automatización. Si una fuente falla 3 veces seguidas, abre una incidencia en GitHub (le llega por correo) y la cierra al recuperarse.

Comandos:
```
pip install -r requirements.txt
python run.py --demo        # vista de ejemplo con datos inventados
python run.py               # ejecución real (claves como variables de entorno)
python run.py --solo-web    # regenera la web con los datos guardados
python run.py --forzar      # pide todas las fuentes aunque no toque
python -m unittest discover tests
```

## Secretos de GitHub (nombres exactos; nunca pidas sus valores)

`METALCHARTS_KEY`, `FRED_KEY`, `NEWSDATA_KEY`, `CEDRON_PASSWORD` (contraseña de la web, mínimo 12 caracteres; si falta, la web no se publica).

## Fuentes de datos (verificadas en noviembre de 2026)

| Fuente | Uso | Límite gratuito | Notas |
| --- | --- | --- | --- |
| MetalCharts `/v1/prices` | Precio actual de los 5 metales | **200 consultas/mes**, histórico solo 30 días | Se pide 6 veces por día laborable (8, 11, 14, 17, 20, 23 h Madrid), tope 190/mes. Cobre en $/libra |
| Banco Mundial Pink Sheet | Histórico mensual desde 1960 | Sin clave | CC BY 4.0. La URL del Excel cambia cada mes: se descubre en la página. **No tiene paladio**. Cobre en $/tonelada (se convierte) |
| FRED | DFII10 (tipo real 10 años), DTWEXBGS (dólar), DEXUSEU (euro/dólar) | 120/min | 1 vez al día |
| CFTC COT Legacy (`jun7-fc8e`) | Posicionamiento no comercial | Sin clave | Códigos: oro 088691, plata 084691, platino 076651, paladio 075651, cobre 085692 |
| NewsData.io `/api/1/latest` | Noticias (categoría business) | 200 créditos/día | Tope 150/día; 1 consulta por hora |
| Ministerio Transición Ecológica (carburantes) | **Desactivada el 6-nov-2026**: corta las conexiones desde GitHub (SSL). El diésel de España sale del Weekly Oil Bulletin | Sin clave | El conector sigue en el código por si vuelve |
| Comisión Europea, Weekly Oil Bulletin | Diésel España y media UE, semanal desde 2005 | Sin clave | El Excel histórico se descubre en la página |
| MAPA, precios medios nacionales | Cerdo, pollo, ternera (y cereales para el bloque 2), semanal | Sin clave | Un Excel por año; certificado FNMT. La primera vez baja 5 años |
| MAPA, panel de consumo en hogares (por canales) | Precio en tienda (supermercado) de carne, huevos y leche | Sin clave | Mensual, 2-3 meses de retraso. Un Excel por año; el canal SUPERMERCADO solo existe desde 2025 y antes se usa T.ESPAÑA (todas las tiendas). Los Excel de 2022-2024 nombran las hojas «enero»…; el mes sale del título interno |
| MAPA, precios pagados por los agricultores | Fertilizantes en España (urea, nitrato amónico cálcico, DAP, cloruro potásico, complejo 15-15-15) | Sin clave | Mensual en €/100 kg sin IVA, ~3 meses de retraso (por eso `dias_reciente: 150`). Se leen todos los Excel de la página (histórico desde 2005); el 0 marca meses sin publicar |
| Eurostat `sts_inpp_m` | Índices de precios de fábrica de España y la UE (acero C241, aluminio C2442, cobre C2444, plomo-zinc-estaño C2443, madera C161, cemento C2351/C235, hormigón C2363, estructuras C2511) | Sin clave | Mensual, 2021 = 100, 1-2 meses de retraso. `indic_bt=PRC_PRR` (el `_DOM` no trae datos). Cemento solo de la UE: usar C235 |
| FRED (apoyo) | Brent, WTI, Henry Hub, diésel EE. UU. (EIA); cerdo (FMI) | FRED_KEY | El FMI: revisar condiciones si la web se abre al público |
| RSS | Noticias | — | Fed, BCE, Banco de Inglaterra, Expansión, Cinco Días, FT Materias primas, Investing.com (en y es), Silver Institute y GoldSeek funcionan (validados el 6-nov-2026). FT e Investing: RSS para uso personal, revisar condiciones si se abre al público |

Descartadas, no las reintroduzcas sin revisar sus condiciones: **OilPriceAPI** (todos sus planes son de uso interno, no permiten mostrar datos al público), **Alpha Vantage** (uso comercial del plan gratuito no aclarado), **NewsAPI.org y GNews** (plan gratuito no comercial). Desde el entorno anterior no se podía acceder a internet salvo por las herramientas; desde Claude Code sí podrás probar las fuentes directamente.

## Metodología (resumen)

Cinco indicadores por activo, cada uno −1/0/+1; suma ≥ +2 favorable, ≤ −2 desfavorable, neutral en medio; con menos de 3 indicadores disponibles no hay lectura.
1. **Tendencia**: precio frente a media de 10 meses (≈200 sesiones) y pendiente de la media.
2. **Momento**: cambio frente a la media mensual de hace 3 meses (umbral 5 %).
3. **Macro** (solo preciosos): tipo real y dólar frente a hace 3 meses; ambos bajan +1, ambos suben −1.
4. **Posicionamiento**: percentil del neto especulativo en 3 años; lectura contraria (≥ p90 → −1, ≤ p10 → +1).
5. **Ratio**: oro/plata (oro y plata) y platino/oro (platino) frente a su media de 10 años (±1 desviación típica).

Las series mensuales unen el Banco Mundial con los cierres diarios propios (`data/historico/`). El historial público (`data/historial_lecturas.json`) solo guarda lecturas con precio real del día.

Noticias: nota 0–100 = relevancia 40 + calidad del medio 25 + actualidad 20 + confirmación 15. Umbral de publicación **55** (bajado de 60 el 6-nov-2026). Los medios externos (vía NewsData) deben tener contexto de mercado en el titular. Medios comerciales necesitan confirmación de otro medio. Hay lista de medios bloqueados (webs de noticias automáticas) y de frases excluidas.

## Diseño

Concepto: «informe de ensayo de metales». El elemento memorable es el **contraste** (sello ovalado de doble línea con la lectura). Todo lo demás, sobrio.
- Colores: papel `#F2F4F1`, tinta petróleo `#1D3A3A`, gris `#55686A`, verdín `#2F7D6B` (favorable), óxido `#A2412B` (desfavorable). Modo oscuro propio.
- Tipografía: Archivo (ancho expandido) para cifras y títulos, Literata para texto. Servidas desde Bunny Fonts (RGPD).
- Alineado a la izquierda, sin tarjetas genéricas, sin etiquetas en mayúsculas, signo menos tipográfico (−) y formato numérico español.
- Gráfico SVG generado en Python con cruceta y globo (`static/grafico.js`) y tabla de datos accesible.

## Estado y pendientes (a 6-nov-2026)

Funciona: todas las fuentes de datos, lecturas de oro, plata, platino y cobre, web cifrada publicada.

Pendiente, por orden de prioridad:
1. **Feeds de noticias** (hecho en parte el 6-nov-2026): Cinco Días arreglado (sección `mercados-financieros`) y añadidos Banco de Inglaterra, FT, Investing.com (en/es) y Silver Institute; en la simulación se pasó de 2 a 18 noticias publicadas. Kitco ya no tiene RSS y Mining.com bloquea lectores: siguen desactivados. Además, **por decisión del usuario y solo mientras la web sea privada**, se activaron The Northern Miner, Mining Technology (noticias de empresas mineras), FXStreet (desactivado después: bloquea las conexiones desde GitHub con 403) y el feed de análisis de Investing.com (análisis técnico de terceros). En la simulación salían unas 40 noticias. **Si la web se abre al público, hay que desactivar esos cuatro** (están marcados en `config.yaml`).
2. **Prueba histórica de 15 años** (fase 4 del plan, aún no hecha): comprobar con el histórico del Banco Mundial que las reglas no dan resultados absurdos, quitar las que no aporten y publicar los resultados en la página de metodología.
3. **Paladio**: no tiene lectura hasta acumular historia propia (sin Banco Mundial). Valorar otra fuente histórica con licencia adecuada.
4. **Materias primas de apoyo** (decidido con el usuario el 6-nov-2026). Sin lectura: solo precio, cambios y tendencia. **España primero**, luego Europa, luego global; un selector en la web elige el ámbito y, si falta un dato reciente, se muestra el último de otro ámbito, indicándolo. Bloques, en este orden:
   - **Bloque 1, energía + ganadería: HECHO** (diésel, Brent, WTI, gas, carbón; cerdo, pollo, ternera, huevos, leche). En España, la ganadería muestra **precio en origen y en supermercado** (decisión del usuario: «junto al de origen»), con el multiplicador tienda/origen del mismo mes. El usuario NO quiere solo precios de origen: quería precios reales de supermercado. No se leen webs de supermercados (sin API oficial ni condiciones verificadas). Pendiente dentro del bloque: gas en España (MIBGAS, revisar condiciones), Europa para ganadería (el portal agroalimentario de la UE estaba suspendido el 6-nov-2026), leche cruda en origen (FEGA).
   - Noticias: Bloomberg Mercados, Industrias y Línea activos (solo uso privado); Bloomberg Economía desactivado por ruido.
   - **Bloque 2, agrícolas + fertilizantes: HECHO** (6-nov-2026). Criterio del usuario: lo más consumido en España (volumen del panel de consumo) y **siempre trigo, arroz y AOVE**; lo demás por la cadena de costes. Grupos: «Agrícolas principales» (trigo con pan en tienda sin multiplicador, arroz, AOVE, girasol, patata, tomate, naranja, plátano, manzana, cebolla, azúcar), «Agrícolas de apoyo» (maíz, cebada, soja, café, cacao, algodón) y «Fertilizantes» (urea, nitrato amónico cálcico, DAP, potasa, complejo 15-15-15). Selector «Origen y tienda / En origen / En tienda» en lista y fichas. Pendiente: Europa (portal agroalimentario de la UE suspendido); el Banco Mundial dejó de publicar la cebada en 2020.
   - **Bloque 3, metales industriales + construcción: HECHO** (6-nov-2026). Pestaña «Construcción» con dos grupos: «Metales industriales» (acero, aluminio, cobre, zinc, níquel, plomo, estaño, mineral de hierro) y «Madera y otros materiales de construcción» (madera aserrada, cemento, hormigón, estructuras metálicas). España y Europa: índices de precios de fábrica de **Eurostat** (`sts_inpp_m`, 2021 = 100; no hay precios en euros gratuitos); global: Banco Mundial y FMI (madera de coníferas `PSAWOREUSDM`). Plomo, zinc y estaño comparten índice en Eurostat (se muestra con el zinc). Pendiente: comprobar si la respuesta de MetalCharts trae metales industriales (se guarda la lista en `metalcharts_simbolos` del estado) para tener precio global varias veces al día sin gastar consultas.
   - Bloque 4: **cadena de costes**: estimaciones de cómo se transmiten los precios (gas → fertilizantes → cereales → pienso → carne; petróleo → diésel → todo; energía + metales → construcción). Es una regla nueva: diseñarla con el usuario, con datos históricos medibles, publicada y sin recomendaciones.
5. Opcional: dominio propio; si se quiere ocultar también el repositorio, estudiar Cloudflare Pages + Access.

## Forma de trabajar en este repositorio

- Antes de subir: `python -m unittest discover tests` y, si cambia la web, `python run.py --demo` y revisar el resultado.
- La automatización hace commits horarios en `data/`: haz `git pull --rebase` antes de `git push`.
- Mensajes de commit en español, describiendo el cambio.
- Tras un cambio de `config.yaml`, `cedron/`, `templates/` o `static/`, el push regenera la web (con `--solo-web`). Para aplicar filtros de noticias nuevos o pedir datos, lanza «Run workflow» en la pestaña Actions.
- Cada cambio de parámetros relevante se anota con fecha en el comentario de `config.yaml`.
