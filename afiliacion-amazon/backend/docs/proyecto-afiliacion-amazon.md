# Proyecto afiliación Amazon – Guía de referencia rápida

## 1. Arquitectura general

- **api-paapi** (Python, FastAPI)
  - Envuelve PAAPI5 oficial de Amazon.
  - Endpoints principales:
    - `GET /buscar`: recibe `busqueda`, `categoria`, `num_resultados`, `pagina`.
  - Responsabilidades:
    - Traducir categorías en español a índices válidos de PAAPI.
    - Llamar a Amazon, normalizar la respuesta a una lista de productos.
    - Enriquecer el precio con formato humano y datos de descuento.
    - **Filtrar productos sin descuento** (`has_discount == False` → se descartan).

- **frontend-api** (Python, FastAPI)
  - Orquesta todo el flujo de generación y exportación.
  - Endpoints principales:
    - `POST /generar-articulos`: devuelve HTML listo para preview.
    - `POST /export/wp-all-import`: devuelve XML en JSON.
    - `POST /export/wp-all-import/file` y `/zip`: descargables.
  - Responsabilidades:
    - Construir las keywords para PAAPI a partir de `palabra_clave_principal`.
    - Llamar a `api-paapi` sobre‑pidiendo productos para poder filtrar.
    - Filtrar por **descuento** y por coincidencia con la palabra clave principal
      usando un stemming sencillo en español.
    - Repartir los productos entre artículos sin repetir.
    - Llamar a `generador-contenido` con el grupo de productos de cada artículo.
    - Construir el XML compatible con **WP All Import**.

- **generador-contenido** (Python, FastAPI + OpenAI)
  - Recibe `tema`, lista de `productos` y palabras clave.
  - Construye un prompt editorial para The Objective.
  - Llama al modelo de OpenAI y luego **postprocesa agresivamente el HTML**.
  - Resultados: `titulo`, `subtitulo` fijo explicativo, `articulo` (HTML listo).

---

## 2. Reglas clave de layout de producto

Referencia detallada: `backend/docs/generador-contenido-layout.md`.

Resumen operativo (cómo debería verse cada producto en WordPress):

1. **Orden dentro del bloque de producto**
   - `H3` con título del producto (marca + modelo cuando aplica).
   - Imagen del producto.
   - Párrafos narrativos/editoriales.
   - Párrafo narrativo de precio (si el modelo lo ha generado).
   - `div` de **Precio orientativo** con el precio calculado por PAAPI.
   - Botón "Comprar en Amazon" con estilo inline amarillo.
   - (Opcional) Párrafo(s) de cierre general del artículo debajo del botón.

2. **Normas de estabilidad**
   - El botón nunca debe aparecer **por encima** de la imagen ni del texto.
   - No se deben generar **más de un botón** por producto.
   - No deben aparecer líneas duplicadas de "Precio orientativo".
   - En el último producto del artículo, el botón debe ir **antes** de cualquier
     párrafo de resumen global ("En resumen", "En conclusión", etc.).
   - La publicidad de WordPress debe caer **después** del bloque de producto
     (precio + botón), no entre párrafos del mismo producto.

---

## 3. Flujo de generación de artículos

1. El frontend llama a `frontend-api /generar-articulos` o `/export/wp-all-import`.
2. `frontend-api` calcula el total de productos a pedir:
   - `max_total = num_articulos * items_por_articulo`.
   - Llama a `api-paapi` pidiendo `total_items = min(max_total * 2, 50)`.
3. `api-paapi` devuelve solo productos **con descuento**.
4. `frontend-api` filtra de nuevo para asegurar:
   - `tiene_descuento(p)` (precio con `-X%`, `antes`, `ahorro`).
   - Coincidencia de título con `palabra_clave_principal` usando `_stem_es`.
5. Se recorta a `max_total` y se reparten los productos entre artículos.
6. Para cada grupo se llama a `generador-contenido /generar-articulo`.
7. `generador-contenido` devuelve HTML ya maquetado; `frontend-api` lo usa:
   - Para la **preview** (respuesta JSON de `/generar-articulos`).
   - Para el **XML** (función `build_wpai_xml`).

---

## 4. Export a WordPress (WP All Import)

Función: `build_wpai_xml` en `frontend-api/main.py`.

Por cada artículo genera un `<item>` con:

- `post_title`: título sintético limpio (sin `#N`, sin "(Black Friday)" literal).
- `post_excerpt`: subtítulo explicativo fijo del generador.
- `post_content`: el HTML de `generador-contenido` (sin `<html>`, `<body>`, etc.).
- `category`: `"Productos recomendados"`.
- `tags`: `"Amazon"`.
- `caption`: `"Amazon"`.
- `featured_image`: URL de imagen hero (ver sección 5).
- `post_status`: `draft`.
- `post_type`: `post`.

### Mapeo recomendado en WP All Import

- `post_title` → Título del artículo.
- `post_excerpt` → Extracto.
- `post_content` → Contenido.
- `category` → Categoría (o usar para asignar categoría por campo personalizado).
- `tags` → Etiquetas.
- `caption` → Campo personalizado si es necesario.
- `featured_image` → **Imagen destacada** del post.

---

## 5. featured_image y héroes rotatorios

`frontend-api` expone un mecanismo sencillo para las imágenes de cabecera:

- Constante `HERO_IMAGES` en `frontend-api/main.py`:

  ```python
  HERO_IMAGES = [
      os.getenv("FRONTEND_HERO_1", "https://testing.theobjective.com/wp-content/uploads/2025/11/amazon4.jpeg"),
      os.getenv("FRONTEND_HERO_2", "https://testing.theobjective.com/wp-content/uploads/2025/11/amazon3.jpeg"),
      os.getenv("FRONTEND_HERO_3", "https://testing.theobjective.com/wp-content/uploads/2025/11/Amazon2-scaled.jpg"),
      os.getenv("FRONTEND_HERO_4", "https://testing.theobjective.com/wp-content/uploads/2025/11/amazon1.jpg"),
  ]
  ```

- En `build_wpai_xml` se construye una lista `heroes = [u for u in HERO_IMAGES if u]`.
- Para cada `<item>` se hace:

  ```python
  hero_url = heroes[(idx - 1) % len(heroes)]
  xml_parts.append(f"    <featured_image>{escape(hero_url)}</featured_image>")
  ```

Es decir:

- Si hay `N` artículos y `M` imágenes hero, se usa **rotación cíclica**.
- Si no hay ninguna URL configurada (todas vacías), no se añade `featured_image`.

### Configuración por entorno

En Railway (o el orquestador que se use) se deben definir, por servicio `frontend-api`:

- `FRONTEND_HERO_1=https://.../hero1.jpg`
- `FRONTEND_HERO_2=https://.../hero2.jpg`
- `FRONTEND_HERO_3=https://.../hero3.jpg`
- `FRONTEND_HERO_4=https://.../hero4.jpg`

En **testing** se pueden usar las URLs de pruebas; en **producción** se cambian por
las definitivas sin tocar código.

---

## 6. Variables de entorno críticas

- Comunes a backend:
  - `HOST`, `PORT` de cada microservicio.

- `api-paapi`:
  - `AWS_ACCESS_KEY`, `AWS_SECRET_KEY`.
  - `PAAPI_ASSOCIATE_TAG` / `AMAZON_ASSOCIATE_TAG` (afiliado, por defecto `theobjective-21`).
  - `PAAPI_COUNTRY` (normalmente `ES`).

- `frontend-api`:
  - `API_PAAPI_URL` (URL base de `api-paapi`).
  - `GEN_CONTENT_URL` (URL base de `generador-contenido`).
  - `DEFAULT_ITEMS_PER_ARTICLE`.
  - `DEFAULT_SEARCH_INDEX` (categoría por defecto tipo `All`).
  - `FRONTEND_HERO_1..4` (imágenes hero para `featured_image`).

- `generador-contenido`:
  - `OPENAI_API_KEY`.
  - `DEFAULT_AFFILIATE_TAG` (por defecto `theobjective-21`).

---

## 7. Checklist rápido tras cambios o restart

1. **Comprobar health endpoints**
   - `api-paapi/health` → `initialized: true`, claves presentes.
   - `frontend-api/health` → URLs correctas de `api_paapi_url` y `gen_content_url`.
   - `generador-contenido/health` → `openai_configured: true`.

2. **Probar flujo mínimo en testing**
   - Generar 1 artículo con 1–2 productos (palabra clave muy concreta).
   - Verificar en la preview:
     - Orden H3 → imagen → texto → precio → botón.
     - Solo productos con descuento.
   - Exportar XML y hacer import a WordPress:
     - Revisar que la publicidad cae debajo del bloque de producto.
     - Confirmar que `featured_image` se asigna correctamente a la imagen
       destacada.

3. **Antes de tocar layout**
   - Leer completo `backend/docs/generador-contenido-layout.md`.
   - Extraer el HTML real del caso problemático.
   - Ajustar la heurística en `generador-contenido/main.py` y añadir, si hace falta,
     una nota en la documentación para no repetir pruebas a ciegas.

---

Este documento sirve como punto de entrada rápido tras un restart: abre este
archivo, revisa secciones 2–5 y luego inspecciona el código de cada microservicio
si hace falta profundizar.
