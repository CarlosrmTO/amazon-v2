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
    "Imágenes: cuando haya URL de imagen del producto, insertar una etiqueta HTML <img src=... alt=... loading=\"lazy\" /> bajo el párrafo donde se menciona, con pie o contexto mínimo, sin galerías. "
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
        # Remove any fenced code blocks (with or without language) globally
        txt = re.sub(r"```\s*[a-zA-Z]*\s*\n", "", txt)
        txt = txt.replace("```", "")
        # Remove leading standalone 'html' token before first tag
        txt = re.sub(r"^\s*html\s*(?=<|\n)", "", txt, flags=re.IGNORECASE)
        # If entire document tags present, keep body inner if available
        m = re.search(r"<body[^>]*>([\s\S]*?)</body>", txt, flags=re.IGNORECASE)
        if m:
            txt = m.group(1)
        # Drop a top-level <h1> the model may add and keep following content
        txt = re.sub(r"^\s*<h1[^>]*>[\s\S]*?</h1>\s*", "", txt, flags=re.IGNORECASE)
        # Unescape HTML entities if the model returned escaped tags
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
        # Fallback simple
        base = url.split('#',1)[0]
        base = re.sub(r"([?&])tag=[^&]*", r"\1", base)
        sep = '&' if '?' in base else '?'
        return f"{base}{sep}tag={tag}"

@app.post("/generar-articulo", response_model=GenerarArticuloResponse)
async def generar_articulo(req: GenerarArticuloRequest):
    try:
        # Limitar productos y asegurar tag
        productos = req.productos[: req.max_items]
        for p in productos:
            p.url_afiliado = ensure_affiliate(p.url_afiliado or p.url_producto, DEFAULT_AFFILIATE_TAG)

        # Construir contexto de productos
        productos_md = []
        for idx, p in enumerate(productos, start=1):
            feats = "\n      - ".join(p.features or [])
            productos_md.append(
                f"{idx}. {p.titulo}\n"
                f"   Marca: {p.marca or '-'} | Precio: {p.precio or '-'}\n"
                f"   Enlace: {p.url_afiliado}\n"
                f"   Imagen: {p.url_imagen or '-'}\n"
                f"   Características:\n      - {feats if feats else '-'}\n"
            )
        productos_md_str = "\n".join(productos_md) if productos_md else "(Sin productos: usa categorías por defecto)"

        keywords_main = req.palabra_clave_principal or (req.tema or "").strip()
        keywords_sec = ", ".join(req.palabras_clave_secundarias or [])

        user_prompt = f"""
Escribe un artículo LISTO PARA PUBLICAR (HTML limpio) sobre: {req.tema or 'selección de más vendidos'}.
Palabra clave principal: {keywords_main or '-'}
Palabras clave secundarias: {keywords_sec or '-'}

Productos disponibles (usa 1–10 de forma selectiva; cada uno incluye título, enlace con afiliado y, cuando exista, URL de imagen):
{productos_md_str}

Instrucciones estrictas de salida (cumple todas):
- Salida en HTML semántico (párrafos <p>, subtítulos <h2>/<h3> si fluyen de forma natural; nada de Markdown).
- Integra microanécdotas o observaciones reales/plausibles y tono humano; evita frases hechas de IA.
- Cuando el producto tenga URL de imagen, incluye justo tras mencionarlo una etiqueta <img src="" alt="" loading="lazy" /> con alt descriptivo (marca o modelo) y proporción de párrafos natural.
- Enlaces de Amazon: usa el enlace de afiliado proporcionado (ya contiene ?tag=theobjective-21) de forma contextual.
- 600–900 palabras; coherencia narrativa; sin secciones mecánicas ni listados forzados.
"""

        client = get_openai_client()
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.8,
            max_tokens=1400,
        )
        content = completion.choices[0].message.content

        # Normalizar HTML del modelo para evitar "html" visible o fences
        content = normalize_model_html(content)

        # Inyección defensiva de imágenes si el modelo las omitiera
        try:
            html = content or ""
            for p in productos:
                if p.url_imagen:
                    if (p.url_imagen not in html) and (p.url_afiliado not in html):
                        alt = (p.marca or p.titulo or "Producto").strip()[:120]
                        figure = (
                            f"\n<figure class=\"product-figure\">"
                            f"<img src=\"{p.url_imagen}\" alt=\"{alt}\" loading=\"lazy\" />"
                            f"<figcaption><a href=\"{p.url_afiliado}\">Ver en Amazon</a></figcaption>"
                            f"</figure>\n"
                        )
                        html += figure
            content = html
        except Exception:
            pass

        try:
            html = content or ""
            for p in productos:
                display = (f"{(p.marca or '').strip()} {p.titulo}" if p.marca else p.titulo).strip()
                if not display:
                    continue
                target_img = p.url_imagen or ""
                target_link = p.url_afiliado or p.url_producto or ""
                pos = -1
                used_img = False
                if target_img:
                    pos = html.find(target_img)
                    if pos != -1:
                        used_img = True
                if pos == -1 and target_link:
                    pos = html.find(target_link)
                if pos == -1:
                    continue
                head_matches = list(re.finditer(r'<h([2-4])([^>]*)>(.*?)</h\1>', html[:pos], flags=re.IGNORECASE|re.DOTALL))
                # Insertar o reemplazar por H3 y fijar el inicio de segmento justo DESPUÉS del H3
                if head_matches:
                    last = head_matches[-1]
                    h_attrs = last.group(2)
                    new_h3 = f"<h3{h_attrs}>{display}</h3>"
                    h3_start, h3_end = last.start(), last.end()
                    html = html[:h3_start] + new_h3 + html[h3_end:]
                    # calcular nuevo fin del H3 tras reemplazo
                    h3_end_new = h3_start + len(new_h3)
                    seg_start = h3_end_new
                else:
                    # Buscar el inicio del contenedor del primer match (p/figure/img/a)
                    search_window = html[:pos]
                    candidates = [
                        search_window.rfind('<p'),
                        search_window.rfind('<figure'),
                        search_window.rfind('<img'),
                        search_window.rfind('<a'),
                    ]
                    container_start = max([c for c in candidates if c != -1] or [pos])
                    ins = f"<h3>{display}</h3>"
                    html = html[:container_start] + ins + html[container_start:]
                    seg_start = container_start + len(ins)
                next_h = re.search(r'<h[2-4][^>]*>', html[seg_start:], flags=re.IGNORECASE)
                # Detectar un posible párrafo de cierre general tipo "En resumen"
                resumen_match = re.search(r'<p[^>]*>\s*En resumen', html[seg_start:], flags=re.IGNORECASE)
                if next_h:
                    next_h_pos = seg_start + next_h.start()
                else:
                    next_h_pos = len(html)
                if resumen_match:
                    resumen_pos = seg_start + resumen_match.start()
                else:
                    resumen_pos = None

                if resumen_pos is not None and resumen_pos < next_h_pos:
                    seg_end = resumen_pos
                else:
                    seg_end = next_h_pos

                segment = html[seg_start:seg_end]
                # Determinístico: tomar el PRIMER <img> (aunque esté dentro de <p>), quitarlo y colocarlo al inicio como <figure>
                # Si ya empieza por <figure> o <img>, no hacer nada
                if not re.match(r'^\s*<(figure|img)\b', segment, flags=re.IGNORECASE):
                    img_any = re.search(r'<img[^>]*>', segment, flags=re.IGNORECASE)
                    if img_any:
                        img_tag = img_any.group(0)
                        # Quitar el <img> del lugar original
                        segment_wo_img = segment[:img_any.start()] + segment[img_any.end():]
                        # Envolver como figure minimal
                        figure = f"<figure class=\"product-figure\">{img_tag}</figure>"
                        segment = figure + segment_wo_img
                        html = html[:seg_start] + segment + html[seg_end:]
                        seg_end = seg_start + len(segment)
                # Insertar precio/botón después del último párrafo del segmento del
                # producto (entre este H3 y el siguiente H2/H3/H4). Así cualquier
                # párrafo narrativo de precio queda por encima, y el bloque de precio
                # orientativo + botón queda pegado al producto pero antes de la
                # conclusión general.
                last_p_close = segment.rfind('</p>')
                if last_p_close != -1:
                    insert_at = seg_start + last_p_close + 4
                else:
                    # si no hay párrafos, intentar después del cierre de <figure> o </a>
                    fig_close = segment.find('</figure>')
                    if fig_close != -1:
                        insert_at = seg_start + fig_close + len('</figure>')
                    else:
                        a_close = segment.find('</a>')
                        insert_at = (seg_start + a_close + 4) if a_close != -1 else seg_end
                # Inyectar precio visible si existe y no es "Precio no disponible".
                # Antes de hacerlo, limpiamos cualquier línea previa de "Precio orientativo"
                # que el modelo haya podido generar, para evitar duplicados y
                # discrepancias de descuento.
                if p.precio and not str(p.precio).strip().lower().startswith('precio no disponible'):
                    # Limpiar divs previos de "Precio orientativo" en el segmento.
                    seg_html = html[seg_start:seg_end]
                    seg_html_clean = re.sub(
                        r'<div[^>]*class="text-muted small"[^>]*>[^<]*Precio orientativo:[\s\S]*?</div>',
                        '',
                        seg_html,
                        flags=re.IGNORECASE,
                    )
                    if seg_html_clean != seg_html:
                        html = html[:seg_start] + seg_html_clean + html[seg_end:]
                        seg_end = seg_start + len(seg_html_clean)
                    price_html = f'<div class="text-muted small">Precio orientativo: {p.precio}</div>'
                    html = html[:insert_at] + price_html + html[insert_at:]
                    insert_at += len(price_html)

                # Solo inyectar botón si en el segmento del producto no existe ya
                # un botón con clase 'btn-buy-amz'. Esto evita duplicados cuando el
                # modelo haya generado uno por su cuenta.
                segment_after_price = html[seg_start:seg_end]
                if 'btn-buy-amz' not in segment_after_price:
                    link = p.url_afiliado or target_link
                    if link:
                        btn = (
                            f'<div class="btn-buy-amz-wrapper" style="margin-top:0.5rem;">'
                            f'<a class="btn-buy-amz" style="display:inline-block;padding:0.35rem 0.9rem;border-radius:0.25rem;background-color:#0d6efd;color:#ffffff;text-decoration:none;font-size:0.9rem;" '
                            f'href="{link}" target="_blank" rel="nofollow sponsored noopener">Comprar en Amazon</a>'
                            f'</div>'
                        )
                        html = html[:insert_at] + btn + html[insert_at:]
            content = html
        except Exception:
            pass

        # Heurística simple de título/subtítulo (el contenido final ya es el cuerpo editorial)
        titulo = req.tema or "Selección de más vendidos"
        subtitulo = "Artículo editorial para The Objective"

        try:
            html = content or ""
            def _strip_accents(s: str) -> str:
                try:
                    import unicodedata
                    return ''.join(ch for ch in unicodedata.normalize('NFD', s) if unicodedata.category(ch) != 'Mn')
                except Exception:
                    return s
            def _eq_loose(a: str, b: str) -> bool:
                aa = _strip_accents((a or '').strip()).lower()
                bb = _strip_accents((b or '').strip()).lower()
                return aa == bb
            # Eliminar cualquier H4 que siga inmediatamente a un H3 (subtítulo innecesario)
            html = re.sub(r'(<h3[^>]*>[\s\S]*?</h3>)\s*<h4[^>]*>[\s\S]*?</h4>', r'\1', html, flags=re.IGNORECASE)
            html = re.sub(r'<p>\s*<a[^>]+href="https?://[^"\s]*amazon\.[^"\s]*"[^>]*>[\s\S]{0,40}</a>\s*</p>', '', html, flags=re.IGNORECASE)
            content = html
        except Exception:
            pass

        return GenerarArticuloResponse(
            titulo=titulo,
            subtitulo=subtitulo,
            articulo=content,
            resumen=None,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", 8010)))
