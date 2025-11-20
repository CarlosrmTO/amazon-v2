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

## 8. Estado actual de `generador-contenido` y refactor pendiente de layout

> **Contexto (20/11/2025):** Tras varias regresiones de layout se ha vuelto a una
> versión estable y se ha creado una rama específica para refactorizar el layout
> de productos sin tocar `main`.

### 8.1 Versiones y ramas

- **Fichero clave**: `backend/microservicios/generador-contenido/main.py`.
- **Versión estable en `main`**: commit `35bc9e9` (`GC: rollback a 1.4 + primer parrafo SEO y normalizacion de enlaces`).
- **Tag de release estable**: `gc-v1.4-estable-20251120` apunta a esa versión.
- **Rollback exacto**: commit `d87bb83` vuelve el fichero a `35bc9e9` después de los
  experimentos de layout.
- **Rama de trabajo para el refactor**: `gc-layout-refactor`, creada desde el
  estado estable. Cualquier cambio de layout debe hacerse aquí y solo pasarse a
  `main` cuando esté probado.

### 8.2 Qué hace ahora la versión estable (35bc9e9)

- **SEO del primer párrafo**
  - El prompt fuerza que el **primer `<p>`** mencione la `palabra_clave_principal`
    y/o el `tema` (ej.: "Black Friday cuidado personal").

- **Normalización de enlaces `<a>`**
  - Se aplica `_normalize_anchor` sobre todos los `<a>` del HTML final.
  - Resultado: todos los enlaces salen como:

    ```html
    <a ... target="_blank" rel="noreferrer noopener sponsored nofollow">
    ```

  - No se reordena el contenido, solo se limpian/añaden atributos.

- **Layout de producto (1.4)**
  - Para cada producto:
    - Se busca la `url_imagen` o `url_afiliado` en el HTML generado por el modelo.
    - Se inserta/reemplaza un heading (`<h3>` en esta versión) antes del bloque
      donde aparece.
    - Se define un **segmento** entre ese heading y el siguiente `<h2-4>`.
    - Dentro del segmento se mueve la primera `<img>` al principio (como
      `<figure>`) y se inserta un bloque de `Precio orientativo + botón` según
      heurísticas de párrafo narrativo.
  - Hay una inyección defensiva de imágenes al final si el modelo ignora alguna
    `url_imagen`.

### 8.3 Limitaciones conocidas

- El emparejamiento heading/imagen/texto es **frágil**: si el modelo mezcla
  headings y productos (ej.: H2 de Garnier justo antes de la imagen de CeraVe),
  la heurística puede reciclar headings y desalinear el contenido.
- Pueden aparecer **botones o bloques de precio duplicados**, especialmente si
  el modelo ya generó sus propios botones o si el último párrafo editorial
  contiene enlaces de producto.
- No hay un contrato rígido por producto del tipo:

  ```html
  <h2/h3>titulo producto</h2/h3>
  <img ... />
  <p>texto producto</p>
  <div class="text-muted small">Precio orientativo: ...</div>
  <div class="btn-buy-amz-wrapper">...</div>
  ```

### 8.4 Requisitos pendientes para `gc-layout-refactor`

La rama `gc-layout-refactor` debe abordar estos puntos sin romper la release
estable:

1. **Estructura fija por producto**

   Para cada producto se quiere imponer de forma estricta:

   ```html
   <h2>título del producto</h2>
   <img src="URL_IMAGEN" alt="..." loading="lazy" />
   <p>...texto principal del producto (con enlace Amazon)...</p>
   <div class="text-muted small">Precio orientativo: {precio}</div>
   <div class="btn-buy-amz-wrapper" ...>
     <a class="btn-buy-amz" ... href="URL_AFILIADO"
        target="_blank" rel="noreferrer noopener sponsored nofollow">
       Comprar en Amazon
     </a>
   </div>
   ```

   - Un único bloque de botón por producto.
   - Sin botones ni bloques de precio "huérfanos" al final del artículo.

2. **Emparejamiento correcto título/imagen/texto/precio/botón**

   - El heading de cada producto debe corresponder siempre a su propia imagen,
     párrafo principal (con su `url_afiliado`), precio y botón.
   - No se debe reciclar un heading de otro producto solo por proximidad en el
     HTML libre del modelo.

3. **Mantener las mejoras ya implementadas**

   - Primer párrafo SEO.
   - Normalización global de `<a>`.
   - Comportamiento actual de `frontend-api` (títulos sintéticos limpios y
     rotación de `featured_image`).

4. **Estrategia sugerida**

   - Cambiar el prompt para que el modelo devuelva bloques de producto más
     estructurados (por ejemplo, `<producto>...</producto>` o
     `<div class="producto">...</div>` con subtags claras para título, imagen,
     texto, precio y enlace).
   - Parsear esos bloques en el backend y construir el HTML final del artículo
     a partir de bloques canónicos por producto, en lugar de depender solo de
     regex sobre el HTML libre del modelo.

---

Este documento sirve como punto de entrada rápido tras un restart: abre este
archivo, revisa secciones 2–8 y luego inspecciona el código de cada
microservicio si hace falta profundizar.
