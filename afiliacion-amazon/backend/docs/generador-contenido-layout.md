# Generador de Contenidos – Reglas de maquetación (v1.3+)

Este documento describe el **contrato actual** de maquetación del microservicio `generador-contenido`. Cualquier cambio futuro en esta lógica debe revisarse contra estas reglas y probarse con HTML real antes de desplegar.

## 1. Flujo general

- El frontend llama a `frontend-api` → este reparte productos y llama a `generador-contenido`.
- `generador-contenido` recibe una lista de `productos` (titulo, marca, url_afiliado, url_imagen, precio, etc.).
- Se construye un prompt para OpenAI y se genera **HTML libre**.
- Sobre ese HTML se aplica una **postproducción agresiva**, que es la que fija el layout.

Todo lo que aparece en la preview y en el XML (WP All Import) sale de este HTML postprocesado.

## 2. Orden de cada bloque de producto

Para cada producto, el objetivo es mantener este orden:

1. `H3` con el título del producto.
2. Imagen en `<figure class="product-figure"><img .../></figure>`.
3. Párrafos narrativos del producto (texto editorial).
4. Párrafo narrativo de precio (si existe) con enlace a Amazon y precio (por ejemplo: `Este modelo está disponible en Amazon aquí por 49,99 €.`).
5. `Precio orientativo` (div) con el precio enriquecido de PAAPI.
6. Botón `Comprar en Amazon`.
7. (Opcional) Párrafo(s) de cierre general del artículo.

## 3. Delimitación del segmento de producto

Para cada producto `p`:

- Se busca su URL de imagen (`url_imagen`) o de afiliado (`url_afiliado`) dentro del HTML.
- Se localiza el último heading antes del match (`<h2>`, `<h3>`, `<h4>`).
  - Ese heading se reemplaza/normaliza a `<h3>` con el `display` del producto (marca + título).
  - El **inicio de segmento** (`seg_start`) se fija justo **después** del `</h3>`.
- El **fin de segmento** (`seg_end`) se fija en:
  - el siguiente `<h2>/<h3>/<h4>` que aparezca, **o**
  - el final del documento, si es el último producto.

Todo lo que ocurre entre `seg_start` y `seg_end` se considera el bloque del producto.

## 4. Imágenes

Dentro del segmento del producto:

- Si el fragmento **no** empieza ya por `<figure>` o `<img>`, se busca el **primer** `<img>` del segmento.
- Se extrae ese `<img>` y se mueve al inicio del segmento envuelto como:

```html
<figure class="product-figure">{img_tag}</figure>
```

- Si, tras insertar el botón (ver punto 6), queda una imagen suelta inmediatamente después del `div.btn-buy-amz-wrapper` dentro del mismo segmento, se reescribe el bloque como:

```html
<figure class="product-figure"><img .../></figure>
<div class="btn-buy-amz-wrapper">...</div>
```

De esta forma, la imagen nunca queda **por debajo** del botón.

## 5. Párrafo narrativo de precio

En el segmento del producto puede haber un párrafo editorial que ya mencione:

- el enlace de Amazon, y
- un precio en euros.

Ejemplo:

```html
<p>Este modelo está disponible en <a href="https://www.amazon.es/...">Amazon</a> por 49,99 €.</p>
```

La lógica actual:

- Busca en el segmento el primer `<p>` que:
  - contenga un `href` con `amazon.`
  - y contenga un patrón de precio en euros (un número tipo `99,99` o `99.99` seguido de `€`).
- Si se encuentra, **ese párrafo se usa como punto de inserción** del bloque `Precio orientativo + botón`.
- Si no se encuentra:
  - Se usan los cierres `</p>` para decidir el punto de inserción (ver sección siguiente).

## 6. Posición de `Precio orientativo` y botón

Dentro del segmento ya normalizado:

1. Se calcula el índice `insert_at` (posición en el HTML global) en función del caso:
   - Si se detectó párrafo narrativo de precio con enlace a Amazon y precio en euros → `insert_at` se fija **justo después** de ese `</p>`.
   - Si **no** hay dicho párrafo:
     - Se enumeran todos los `</p>` del segmento.
     - Si **es el último producto** (no hay siguiente heading) y hay ≥ 2 `</p>` → se usa el **penúltimo** `</p>` como punto de inserción, dejando el último libre para cierre general.
     - En cualquier otro caso → se usa el **último** `</p>` del segmento.
   - Si no hay `</p>` en el segmento → se intenta insertar después de `</figure>` o `</a>`.

2. Antes de insertar el precio se limpian del segmento:

```html
<div class="text-muted small">Precio orientativo: ...</div>
```

que el modelo haya generado, para evitar duplicados o incoherencias.

3. Se inserta:

```html
<div class="text-muted small">Precio orientativo: {p.precio}</div>
```

4. A continuación, si en el segmento **no existen ya** botones con `class="btn-buy-amz"`, se inserta:

```html
<div class="btn-buy-amz-wrapper" style="margin-top:0.5rem;margin-bottom:1.25rem;">
  <a class="btn-buy-amz" style="display:inline-block;padding:0.35rem 0.9rem;border-radius:0.25rem;background-color:#0d6efd;color:#ffffff;text-decoration:none;font-size:0.9rem;"
     href="{link}" target="_blank" rel="nofollow sponsored noopener">Comprar en Amazon</a>
</div>
```

Con esto se garantiza que:

- El párrafo editorial con precio (y enlace) va **encima** de `Precio orientativo`.
- `Precio orientativo` va **encima** del botón.
- El último párrafo global del artículo (cierre tipo “En resumen / En conclusión / Aprovechar las ofertas…”) queda **debajo** del botón.

## 7. Reglas de no-regresión

Cuando se toque el código de maquetación en `generador-contenido/main.py` hay que respetar estas reglas:

1. **No eliminar** la detección de segmento (`seg_start` / `seg_end`) basada en H3 y siguiente heading.
2. **No cambiar** el orden conceptual H3 → imagen → texto → precio narrativo (si existe) → `Precio orientativo` → botón → cierre general.
3. Mantener siempre la comprobación de botón existente (`'btn-buy-amz' not in segment_after_price`) para no duplicar botones.
4. No volver a inyectar `Precio orientativo` si el precio es "Precio no disponible".
5. Probar siempre con:
   - Caso con párrafo final de cierre.
   - Caso **sin** párrafo final de cierre.
   - Caso donde el modelo genera un párrafo con enlace a Amazon + precio.
   - Caso donde el modelo **no** genera ese párrafo.

Ante cualquier bug nuevo, antes de cambiar nada:

- Obtener el HTML/XML **exacto** del producto problemático.
- Ajustar la heurística contra ese caso concreto.
- Verificar que no rompe los otros patrones de esta lista.

## 8. Exportación a WordPress (WP All Import) y featured_image

La exportación de artículos a XML se realiza desde el microservicio `frontend-api`.
Además del `post_content` generado por `generador-contenido`, el XML incluye ahora:

- `category`: siempre `"Productos recomendados"`.
- `tags`: siempre `"Amazon"`.
- `caption`: siempre `"Amazon"`.
- `featured_image`: URL de imagen hero para la cabecera del post.

El campo `featured_image` rota entre una lista fija de URLs hero (`HERO_IMAGES`) que se
pueden configurar por entorno mediante las variables de entorno:

- `FRONTEND_HERO_1`
- `FRONTEND_HERO_2`
- `FRONTEND_HERO_3`
- `FRONTEND_HERO_4`

Si no se definen estas variables, se usan las URLs por defecto configuradas en
`frontend-api/main.py` (pensadas para el entorno de testing). WP All Import debe mapear
`featured_image` al campo de **Imagen destacada** del post.
