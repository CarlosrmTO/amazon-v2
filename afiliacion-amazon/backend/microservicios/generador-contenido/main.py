from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
from dotenv import load_dotenv
import os
import re
import unicodedata
from html import unescape as html_unescape

# OpenAI SDK v1.x
from openai import OpenAI

load_dotenv()

app = FastAPI(title="Generador de Contenidos",
              description="Microservicio que genera artículos humanos para afiliación Amazon")
DEFAULT_AFFILIATE_TAG = os.getenv("DEFAULT_AFFILIATE_TAG", "theobjective-21")

def get_openai_client():
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY no configurada")
    return OpenAI(api_key=key)

@app.get("/")
async def root():
    return {"status": "ok", "service": "generador-contenido"}

@app.get("/health")
async def health():
    try:
        has_key = bool(os.getenv("OPENAI_API_KEY"))
        return {"status": "ok", "openai_configured": has_key, "affiliate_tag": DEFAULT_AFFILIATE_TAG}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

class Producto(BaseModel):
    titulo: str
    url_producto: str
    url_afiliado: Optional[str] = None
    precio: Optional[str] = None
    marca: Optional[str] = None
    url_imagen: Optional[str] = None
    features: Optional[List[str]] = None

class GenerarArticuloRequest(BaseModel):
    tema: Optional[str] = None
    productos: List[Producto] = Field(default_factory=list)
    max_items: int = Field(default=10, ge=1, le=10)
    tono: str = Field(default="humano, cercano, coloquial pero profesional")
    palabra_clave_principal: Optional[str] = None
    palabras_clave_secundarias: Optional[List[str]] = Field(default_factory=list)

class GenerarArticuloResponse(BaseModel):
    titulo: str
    subtitulo: str
    subtitulo_ia: Optional[str] = None
    articulo: str
    resumen: Optional[str] = None

STYLE_RULES = (
    "Actúa como redactor humano especializado en tecnología, consumo y tendencias digitales para The Objective. "
    "Redacta 100% natural, con rigor periodístico y estilo editorial humano (ritmo variado, microanécdotas reales o plausibles, observaciones personales verificables). "
    "Evita cualquier trazo de automatización o muletillas típicas de IA. "
    "Objetivo: ayudar a decidir una compra sin parecer publicidad. "
    "Tono: informativo y elegante, sin repeticiones; ritmo humano con matices. "
    "Evitar estructuras mecánicas ('pros y contras', 'conclusión final' o 'guía de compra'). "
    "Contenido mínimo: introducción con contexto/por qué importa; explicación natural de productos, características, ventajas y diferenciadores; opinión equilibrada sutil; cierre editorial que conecte con experiencia/tendencia. "
    "Afiliación: incluir enlaces de Amazon con '?tag=theobjective-21' de forma contextual (por ejemplo: 'puede encontrarse en Amazon con descuento aquí'). "
    "SEO: usar la palabra clave principal y 2–3 secundarias de forma orgánica; priorizar coherencia narrativa. "
    "Longitud objetivo: 600–900 palabras. Español de España."
)

SYSTEM_PROMPT = f"""
Eres un redactor humano de The Objective. Aplica estrictamente estas pautas editoriales:
{STYLE_RULES}
"""

def normalize_model_html(s: str) -> str:
    try:
        if not s:
            return ""
        txt = s.strip()
        # Remove any fenced code blocks
        txt = re.sub(r"```\s*[a-zA-Z]*\s*\n", "", txt)
        txt = txt.replace("```", "")
        # Unescape HTML entities if needed
        if '&lt;' in txt and '&gt;' in txt:
            txt = html_unescape(txt)
        return txt.strip()
    except Exception:
        return s or ""

def ensure_affiliate(url: str, tag: str) -> str:
    if not url:
        return url
    try:
        from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
        u = urlparse(url)
        q = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if k.lower() != 'tag']
        q.append(('tag', tag))
        new_q = urlencode(q, doseq=True)
        return urlunparse((u.scheme, u.netloc, u.path, u.params, new_q, u.fragment))
    except Exception:
        base = url.split('#',1)[0]
        base = re.sub(r"([?&])tag=[^&]*", r"\1", base)
        sep = '&' if '?' in base else '?'
        return f"{base}{sep}tag={tag}"

@app.post("/generar-articulo", response_model=GenerarArticuloResponse)
async def generar_articulo(req: GenerarArticuloRequest):
    try:
        # 1. Preparar productos y mapa por ID
        productos = req.productos[: req.max_items]
        for p in productos:
            p.url_afiliado = ensure_affiliate(p.url_afiliado or p.url_producto, DEFAULT_AFFILIATE_TAG)
        
        productos_map = {str(i): p for i, p in enumerate(productos, 1)}

        # 2. Construir contexto de entrada para el LLM
        productos_context = []
        for idx, p in enumerate(productos, start=1):
            feats = ", ".join(p.features or [])
            productos_context.append(
                f"ID {idx}: {p.titulo}\n"
                f"   Marca: {p.marca or '-'} | Precio: {p.precio or '-'}\n"
                f"   Características: {feats}\n"
            )
        productos_str = "\n".join(productos_context)

        keywords_main = req.palabra_clave_principal or (req.tema or "").strip()
        keywords_sec = ", ".join(req.palabras_clave_secundarias or [])

        # 3. Prompt con estructura XML estricta
        user_prompt = f"""
Escribe un artículo sobre: {req.tema or 'selección de productos'}.
Palabra clave principal: {keywords_main}
Palabras clave secundarias: {keywords_sec}

Productos disponibles (tienes {len(productos)}):
{productos_str}

INSTRUCCIONES DE ESTRUCTURA Y SALIDA (IMPORTANTE):
No devuelvas texto libre ni Markdown. Devuelve UNICAMENTE un bloque XML con la siguiente estructura exacta:

<articulo>
  <titular>Titulo atractivo aquí</titular>
  <subtitulo>Subtítulo breve y original</subtitulo>
  <intro>
    <p>Párrafo de introducción 1 (debe incluir la palabra clave principal "{keywords_main}")...</p>
    <p>Párrafo de introducción 2...</p>
  </intro>
  <items>
    <!-- Genera un bloque <item> para CADA uno de los {len(productos)} productos, en el orden que prefieras o el dado -->
    <item id="ID_DEL_PRODUCTO">
       <nombre>Nombre editorial del producto</nombre>
       <texto>
         <p>Descripción, opinión y análisis del producto...</p>
       </texto>
    </item>
  </items>
  <cierre>
    <p>Conclusión o cierre editorial...</p>
  </cierre>
</articulo>

REGLAS DE CONTENIDO:
1. El PRIMER párrafo de <intro> debe mencionar "{keywords_main}" de forma natural.
2. En <items>, el atributo "id" debe coincidir con el ID numérico de la lista de productos.
3. En <texto>, usa HTML semántico (<p>, <b>, etc.) pero NO incluyas imágenes, precios, ni botones; eso lo añadirá el sistema automáticamente.
4. Redacción humana, sin muletillas de IA.
"""

        client = get_openai_client()
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=2000,
        )
        raw_output = completion.choices[0].message.content
        
        # 4. Parseo del XML (Pseudo-XML con Regex para robustez)
        raw_clean = normalize_model_html(raw_output)
        
        def extract_tag(tag, text, flags=re.IGNORECASE | re.DOTALL):
            m = re.search(f"<{tag}>(.*?)</{tag}>", text, flags)
            return m.group(1).strip() if m else None

        titulo_model = extract_tag("titular", raw_clean) or req.tema
        subtitulo_ia = extract_tag("subtitulo", raw_clean)
        intro_html = extract_tag("intro", raw_clean) or ""
        cierre_html = extract_tag("cierre", raw_clean) or ""
        
        # Extraer items
        items_block_match = re.search(r"<items>(.*?)</items>", raw_clean, re.IGNORECASE | re.DOTALL)
        items_block = items_block_match.group(1) if items_block_match else raw_clean
        
        items_iter = re.finditer(r'<item\s+id=["\']?(\d+)["\']?\s*>(.*?)</item>', items_block, re.IGNORECASE | re.DOTALL)
        
        article_body_parts = []
        
        if intro_html:
            article_body_parts.append(intro_html)
            
        for m in items_iter:
            pid = m.group(1)
            content_inner = m.group(2)
            
            product_obj = productos_map.get(pid)
            if not product_obj:
                continue
                
            nombre_editorial = extract_tag("nombre", content_inner) or product_obj.titulo
            texto_editorial = extract_tag("texto", content_inner) or ""
            
            # Construcción Determinista: H2 -> Imagen -> Texto -> Precio -> Botón
            h2 = f"<h2>{nombre_editorial}</h2>"
            
            figure = ""
            if product_obj.url_imagen:
                alt_text = (product_obj.marca or product_obj.titulo)[:100].replace('"', '')
                figure = (
                    f'<figure class="product-figure">'
                    f'<img src="{product_obj.url_imagen}" alt="{alt_text}" loading="lazy" />'
                    f'</figure>'
                )
            
            texto_clean = re.sub(r'<div[^>]*class="btn-buy-amz[^>]*>.*?</div>', '', texto_editorial, flags=re.DOTALL)
            
            price_div = ""
            if product_obj.precio and not "no disponible" in str(product_obj.precio).lower():
                price_div = f'<div class="text-muted small">Precio orientativo: {product_obj.precio}</div>'
            
            btn_div = ""
            link = product_obj.url_afiliado or product_obj.url_producto
            if link:
                btn_div = (
                    f'<div class="btn-buy-amz-wrapper" style="margin-top:0.5rem;margin-bottom:1.25rem;">'
                    f'<a class="btn-buy-amz" style="display:inline-block;padding:0.35rem 0.9rem;'
                    f'border-radius:0.25rem;background-color:rgb(251,225,11);color:#000000;'
                    f'text-decoration:none;font-size:0.9rem;" '
                    f'href="{link}" target="_blank" rel="noreferrer noopener sponsored nofollow">Comprar en Amazon</a>'
                    f'</div>'
                )
            
            block_html = f"{h2}\n{figure}\n{texto_clean}\n{price_div}\n{btn_div}\n"
            article_body_parts.append(block_html)

        if cierre_html:
            article_body_parts.append(cierre_html)
            
        full_html = "\n".join(article_body_parts)
        
        def _normalize_anchor(match: re.Match) -> str:
            attrs = match.group(1) or ""
            attrs = re.sub(r"\s+target=\"[^\"]*\"", "", attrs, flags=re.IGNORECASE)
            attrs = re.sub(r"\s+rel=\"[^\"]*\"", "", attrs, flags=re.IGNORECASE)
            attrs = attrs.rstrip()
            extra = ' target="_blank" rel="noreferrer noopener sponsored nofollow"'
            return f"<a{attrs}{extra}>"

        full_html = re.sub(r"<a([^>]*)>", _normalize_anchor, full_html, flags=re.IGNORECASE)
        
        subtitulo_fijo = (
            "Este artículo se ha elaborado con apoyo de herramientas de análisis y generación de "
            "contenido para seleccionar y describir los productos más relevantes disponibles en Amazon."
        )

        return GenerarArticuloResponse(
            titulo=titulo_model or "Artículo Recomendado",
            subtitulo=subtitulo_fijo,
            subtitulo_ia=subtitulo_ia,
            articulo=full_html,
            resumen=None,
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", 8010)))
