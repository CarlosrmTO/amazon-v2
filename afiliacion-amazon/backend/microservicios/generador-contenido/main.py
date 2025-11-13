from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
from dotenv import load_dotenv
import os

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

def ensure_affiliate(url: str, tag: str) -> str:
    if not url:
        return url
    if "?" in url:
        # ya tiene query, añadimos &tag=
        if "tag=" in url:
            return url
        return f"{url}&tag={tag}"
    return f"{url}?tag={tag}"

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

        # Heurística simple de título/subtítulo (el contenido final ya es el cuerpo editorial)
        titulo = req.tema or "Selección de más vendidos"
        subtitulo = "Artículo editorial para The Objective"

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
