# Directorio de Servicios Scraper

Scraper para descubrir y rankear perfiles públicos de un directorio de
negocios/servicios (por ejemplo: plomeros, servicios de limpieza,
electricistas, restaurantes, etc.) a partir de una **keyword + ubicación**.
Corre en local y también está preparado para desplegarse como **Apify
Actor**.

> Este proyecto solo extrae **información públicamente visible** en páginas
> web y **datos de contacto explícitamente publicados** por el propio sitio
> (teléfono, WhatsApp, email, redes). No evade CAPTCHAs, logins ni controles
> de acceso, y no infiere datos que no estén presentes en la página (se
> devuelve `null`).

---

## 1. Qué hace el proyecto

Dado un `keyword` (ej. `"servicios de limpieza"`) y una `location` (ej.
`"Medellín, Colombia"`), el pipeline:

1. Obtiene resultados de búsqueda orgánicos mediante un **proveedor de
   búsqueda** (un Actor SERP de Apify, nunca scrapeando Google directamente
   para evitar CAPTCHAs/bloqueos).
2. Deduplica y filtra URLs irrelevantes (Google, YouTube, Facebook,
   Instagram, TikTok, logins, búsquedas internas, etc.).
3. Visita cada URL restante con Playwright/Crawlee, con concurrencia
   limitada, timeouts, reintentos con backoff y respeto de `robots.txt`.
4. Extrae datos del perfil con una cascada de estrategias: JSON-LD →
   Schema.org → Open Graph → meta tags → HTML semántico → selectores
   conocidos → fallback DOM.
5. Normaliza los datos (nombre, URL, ubicación, rating, reviews, teléfono,
   imágenes).
6. Calcula un `score` (0-100) y un `data_quality_score` (0-100).
7. Ordena (`ranking`) por score, luego rating, luego cantidad de reseñas.
8. Genera un Dataset final (Apify Dataset y/o JSON/CSV locales).

Cualquier error por página (403, 404, 429, timeout, bloqueo, HTML inválido)
se registra con `status` y `error_type` **sin detener el resto del crawl**.

---

## 2. Arquitectura

```
scraper/
├── .actor/                  # Configuración del Apify Actor
│   ├── actor.json
│   ├── input_schema.json
│   ├── output_schema.json
│   └── Dockerfile
├── src/
│   ├── main.py              # Orquestación del pipeline + entrypoint Apify/local
│   ├── search_provider.py   # Interfaz SearchProvider + adaptador Apify + estático
│   ├── profile_scraper.py   # Crawler Playwright/Crawlee (visita perfiles)
│   ├── extractors.py        # Extracción robusta (JSON-LD/OG/meta/DOM)
│   ├── normalizers.py       # Normalización de campos
│   ├── scoring.py           # Cálculo de score y data_quality_score
│   ├── models.py            # Dataclasses (SearchResult, ProfileRecord, ...)
│   ├── storage.py           # Guardado JSON/CSV local + Actor.push_data
│   └── utils.py             # Filtrado de URLs, dedup, logging, robots.txt
├── tests/
│   ├── test_normalizers.py
│   ├── test_scoring.py
│   ├── test_extractors.py
│   ├── manual_dry_run.py    # Prueba end-to-end offline (servidor local + fixtures)
│   └── fixtures/site/       # Páginas HTML de prueba
├── requirements.txt
├── .env.example
└── README.md
```

`run_pipeline()` en `src/main.py` contiene toda la lógica de negocio y no
depende del Apify SDK, por lo que es directamente testeable. `main()` es el
adaptador delgado que usa `Actor.get_input()` / `Actor.push_data()` del SDK
de Apify (funciona igual en local, con almacenamiento emulado, y en la nube
de Apify).

---

## 3. Instalación

Requisitos: Python 3.11+, y Node no es necesario. Se recomienda un entorno
virtual.

```bash
cd scraper
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium   # descarga el navegador si no lo tienes
```

---

## 4. Variables de entorno

Copia `.env.example` a `.env` y complétalo (nunca subas `.env` a git):

| Variable | Descripción |
|---|---|
| `APIFY_API_TOKEN` | Token de tu cuenta de Apify. Requerido para usar el proveedor de búsqueda vía Apify (SERP). |
| `SEARCH_ACTOR_ID` | ID del Actor de Apify usado como proveedor SERP. Por defecto `apify/google-search-scraper`. |
| `SEARCH_SEED_RESULTS_FILE` | Ruta a un JSON local con resultados de búsqueda "semilla" (`[{position, title, url, description}, ...]`). Si se define, se usa en vez de llamar a la API — útil para pruebas locales sin token. |
| `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` | Ruta al binario de Chromium, si no está en la ubicación estándar de Playwright. |
| `SCRAPER_OUTPUT_DIR` | Carpeta donde se guardan `dataset.json` / `dataset.csv` en ejecuciones locales (por defecto `data`). |

**Nunca se hardcodean API keys en el código.**

---

## 5. Cómo ejecutar localmente

### Opción A: con Apify CLI (recomendado)

```bash
npm install -g apify-cli   # una sola vez
cd scraper
apify run
```

Edita el input en `storage/key_value_stores/default/INPUT.json` (Apify CLI
lo crea automáticamente la primera vez) o usa `apify run --input '{...}'`.

### Opción B: sin Apify CLI

El SDK de Apify funciona en local sin el CLI, emulando el almacenamiento en
una carpeta `storage/`. Crea el input manualmente:

```bash
mkdir -p storage/key_value_stores/default
cat > storage/key_value_stores/default/INPUT.json <<'EOF'
{
    "keyword": "servicios de limpieza",
    "location": "Medellín, Colombia",
    "maxSearchResults": 20,
    "maxProfiles": 20,
    "minRating": 0,
    "minReviews": 0,
    "onlyVerified": false
}
EOF

export APIFY_API_TOKEN=tu_token   # o usa SEARCH_SEED_RESULTS_FILE para probar sin token
python -m src.main
```

El resultado se publica en el Dataset de Apify (`storage/datasets/default/`)
y además se guarda en `data/dataset.json` y `data/dataset.csv`.

---

## 6. Cómo ejecutar dry_run

El modo `dryRun` limita automáticamente la ejecución a un máximo de **3**
resultados de búsqueda y **3** perfiles, con logging detallado. Es la forma
recomendada de probar el proyecto sin generar tráfico innecesario:

```json
{
    "keyword": "servicios de limpieza",
    "location": "Medellín, Colombia",
    "dryRun": true
}
```

También puedes correr la prueba end-to-end incluida, que levanta un servidor
HTTP local con páginas de ejemplo (no depende de red externa ni de
`APIFY_API_TOKEN`) y valida ranking, deduplicación, filtrado y manejo de
errores:

```bash
cd scraper
.venv/bin/python -m tests.manual_dry_run
```

---

## 7. Cómo desplegar en Apify

1. Instala el Apify CLI: `npm install -g apify-cli`
2. Autentícate: `apify login`
3. Desde la carpeta `scraper/`: `apify push`
4. Configura las variables de entorno del Actor en la consola de Apify
   (`APIFY_API_TOKEN` no es necesario dentro del propio Actor si usas otro
   Actor de la misma cuenta como proveedor SERP —Apify inyecta su propio
   token de ejecución—, pero sí necesitas `SEARCH_ACTOR_ID` si usas uno
   distinto al de por defecto).
5. Corre el Actor desde la consola o vía API, pasando el input según el
   schema (`.actor/input_schema.json`).

El `Dockerfile` en `.actor/` usa la imagen oficial
`apify/actor-python-playwright`, que ya incluye Python + Playwright/Chromium.

---

## 8. Cómo configurar el input

Ver `.actor/input_schema.json` para el detalle completo. Campos principales:

```json
{
    "keyword": "servicios de limpieza",
    "location": "Medellín, Colombia",
    "maxSearchResults": 50,
    "maxProfiles": 50,
    "minRating": 0,
    "minReviews": 0,
    "onlyVerified": false,
    "dryRun": false
}
```

Campos avanzados opcionales: `concurrency` (default 5), `requestTimeoutSecs`
(default 30), `maxRetries` (default 2).

---

## 9. Estructura del output

Cada registro del Dataset final tiene esta forma:

```json
{
    "ranking": 1,
    "score": 96.25,
    "data_quality_score": 100,
    "status": "ok",
    "name": "...",
    "main_image": "https://...",
    "images": ["https://...", "https://..."],
    "description": "...",
    "location": "...",
    "rating": 4.9,
    "review_count": 325,
    "verified": true,
    "public_phone": "...",
    "public_whatsapp": "...",
    "public_email": "...",
    "public_social": ["..."],
    "profile_url": "...",
    "domain": "...",
    "google_position": 1,
    "search_title": "...",
    "search_description": "...",
    "scraped_at": "..."
}
```

Perfiles que no pudieron visitarse (bloqueo, 403/404/429, timeout) aparecen
con un registro reducido:

```json
{
    "profile_url": "...",
    "status": "blocked",
    "error_type": "403",
    "ranking": null
}
```

Perfiles visitados correctamente pero que no cumplen `minRating` /
`minReviews` / `onlyVerified` aparecen con `status: "filtered"` y también sin
`ranking` (quedan fuera del ranking final, pero visibles para trazabilidad).

Campos inexistentes en la página se devuelven como `null` (o `[]` para listas
como `images`) — nunca se inventan valores.

---

## 10. Cómo exportar el Dataset

- **Desde Apify**: en la consola del Actor run, pestaña *Dataset* → *Export*
  (JSON, CSV, Excel, etc.), o vía API/CLI: `apify actors:run-dataset`.
- **En local**: el pipeline ya escribe `data/dataset.json` y
  `data/dataset.csv` automáticamente en cada corrida local (configurable con
  `SCRAPER_OUTPUT_DIR`).

---

## 11. Errores frecuentes

| Problema | Causa probable | Solución |
|---|---|---|
| `No hay proveedor de búsqueda configurado` | Falta `APIFY_API_TOKEN` y no se definió `SEARCH_SEED_RESULTS_FILE` | Define `APIFY_API_TOKEN` en `.env`, o usa un archivo semilla para pruebas locales |
| `Executable doesn't exist at .../chromium...` | Playwright no encuentra el navegador | Corre `python -m playwright install chromium`, o define `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` |
| `Chromium sandboxing failed!` | El proceso corre como root (contenedores) | El proyecto ya añade `--no-sandbox` automáticamente cuando detecta `uid==0`; si persiste, revisa permisos del contenedor |
| Muchos perfiles con `status: blocked` | El sitio bloquea bots o exige JavaScript avanzado/CAPTCHA | Es el comportamiento esperado: no se intenta evadir. Reduce concurrencia o revisa `robots.txt` del sitio |
| Resultados vacíos con `SEARCH_SEED_RESULTS_FILE` | El JSON no tiene el formato `{position, title, url, description}` | Revisa el formato del archivo semilla |

---

## 12. Cómo cambiar el proveedor de búsqueda

El sistema usa la interfaz abstracta `SearchProvider`
(`src/search_provider.py`):

```python
class SearchProvider(ABC):
    @abstractmethod
    def search(self, keyword: str, location: str, max_results: int) -> List[SearchResult]:
        ...
```

Para usar un proveedor distinto (otra API SERP, otro Actor de Apify, etc.):

1. Crea una clase que herede de `SearchProvider` e implemente `search()`.
2. Ajusta `get_search_provider()` en `search_provider.py` para instanciar tu
   nuevo proveedor según la configuración disponible (variables de entorno).
3. No hace falta tocar el resto del pipeline: `main.py` solo depende de la
   interfaz `SearchProvider`.

---

## Tests

```bash
cd scraper
.venv/bin/python -m pytest -q          # 49 tests unitarios (normalizers, scoring, extractors)
.venv/bin/python -m tests.manual_dry_run  # prueba end-to-end offline
```
