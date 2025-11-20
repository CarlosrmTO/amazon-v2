from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field
from typing import List, Optional
from dotenv import load_dotenv
import os
import httpx
from fastapi.middleware.cors import CORSMiddleware
import io
import zipfile
import re

load_dotenv()

app = FastAPI(
    title="Frontend API Orquestación",
    description="Orquesta PAAPI y Generador de Contenidos y exporta a XML WP All Import",
    docs_url="/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"status": "ok", "service": "frontend-api"}

def _ensure_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return u
    if u.startswith("http://") or u.startswith("https://"):
        return u
    return "https://" + u

API_PAAPI_URL = _ensure_url(os.getenv("API_PAAPI_URL", "http://localhost:8000"))
GEN_CONTENT_URL = _ensure_url(os.getenv("GEN_CONTENT_URL", "http://localhost:8010"))
DEFAULT_ITEMS_PER_ARTICLE = int(os.getenv("DEFAULT_ITEMS_PER_ARTICLE", 5))
DEFAULT_CATEGORY = os.getenv("DEFAULT_SEARCH_INDEX", "All")

APP_VERSION = os.getenv("APP_VERSION", "1.3.0")
BUILD_ID = os.getenv("BUILD_ID", "dev")

# Imágenes hero para featured_image en WP All Import.
# En producción se pueden sobreescribir vía variables de entorno
# FRONTEND_HERO_1..4 o ajustando este listado directamente.
HERO_IMAGES = [
    os.getenv("FRONTEND_HERO_1", "https://testing.theobjective.com/wp-content/uploads/2025/11/amazon4.jpeg"),
    os.getenv("FRONTEND_HERO_2", "https://testing.theobjective.com/wp-content/uploads/2025/11/amazon3.jpeg"),
    os.getenv("FRONTEND_HERO_3", "https://testing.theobjective.com/wp-content/uploads/2025/11/Amazon2-scaled.jpg"),
    os.getenv("FRONTEND_HERO_4", "https://testing.theobjective.com/wp-content/uploads/2025/11/amazon1.jpg"),
]

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": APP_VERSION,
        "build_id": BUILD_ID,
        "api_paapi_url": API_PAAPI_URL,
        "gen_content_url": GEN_CONTENT_URL,
        "default_items_per_article": DEFAULT_ITEMS_PER_ARTICLE,
        "default_category": DEFAULT_CATEGORY,
    }

class Producto(BaseModel):
    titulo: str
    url_producto: str
    url_afiliado: str
    url_imagen: Optional[str] = None
    precio: Optional[str] = None
    marca: Optional[str] = None
    features: Optional[List[str]] = None
    tiene_descuento: Optional[bool] = None

class LoteRequest(BaseModel):
    tema: Optional[str] = None
    busqueda: str = Field(default="", description="keywords de búsqueda en Amazon")
    categoria: str = Field(default=DEFAULT_CATEGORY)
    num_articulos: int = Field(default=1, ge=1, le=10)
    items_por_articulo: int = Field(default=DEFAULT_ITEMS_PER_ARTICLE, ge=1, le=10)
    palabra_clave_principal: Optional[str] = None
    palabras_clave_secundarias: Optional[List[str]] = Field(default_factory=list)

class Articulo(BaseModel):
    titulo: str
    subtitulo: str
    subtitulo_ia: Optional[str] = None
    articulo: str

class LoteResponse(BaseModel):
    articulos: List[Articulo]


def chunk(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def _stem_es(word: str) -> str:
    """Normalización muy simple para singular/plural y masculino/femenino en español.
    No es un lematizador completo, pero ayuda a casar 'aspirador', 'aspiradora', 'aspiradores', etc.
    """
    w = word.lower().strip()
    if len(w) <= 3:
        return w
    for suf in ("es", "as", "os", "s", "a", "o"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)]
    return w


async def buscar_productos(busqueda: str, categoria: str, total: int) -> List[Producto]:
    # Normalizar categoria: 'All' -> "" para evitar rechazos en PAAPI
    categoria_n = (categoria or "").strip()
    if categoria_n.lower() == "all":
        categoria_n = ""

    productos: List[Producto] = []
    remaining = max(1, total)
    pagina = 1
    async with httpx.AsyncClient(timeout=30.0) as client:
        while remaining > 0 and pagina <= 10:  # PAAPI pagina 1..10
            item_count = min(10, remaining)     # PAAPI máx 10 por request
            params = {
                "busqueda": busqueda,
                "num_resultados": item_count,
                "pagina": pagina,
            }
            if categoria_n:
                params["categoria"] = categoria_n
            r = await client.get(f"{API_PAAPI_URL}/buscar", params=params)
            if r.status_code != 200:
                # Reintento conservador: sin categoria y con n=5
                retry_params = {
                    "busqueda": busqueda,
                    "num_resultados": min(5, item_count),
                    "pagina": pagina,
                }
                r_retry = await client.get(f"{API_PAAPI_URL}/buscar", params=retry_params)
                if r_retry.status_code != 200:
                    raise HTTPException(status_code=502, detail=f"Error PAAPI (p{pagina} n{item_count} cat='{categoria_n}') and retry: {r.text} | retry: {r_retry.text}")
                r = r_retry
            data = r.json() or []
            for d in data:
                productos.append(Producto(
                    titulo=d.get("titulo", ""),
                    url_producto=d.get("url_producto", ""),
                    url_afiliado=d.get("url_afiliado", ""),
                    url_imagen=d.get("url_imagen"),
                    precio=d.get("precio"),
                    marca=d.get("marca"),
                    features=None,
                    tiene_descuento=d.get("tiene_descuento"),
                ))
            remaining -= len(data) if data else item_count
            pagina += 1
    return productos


async def generar_articulo(tema: str, productos: List[Producto], kw_main: Optional[str], kw_sec: List[str]) -> Articulo:
    payload = {
        "tema": tema,
        "productos": [p.model_dump() for p in productos],
        "max_items": len(productos),
        "palabra_clave_principal": kw_main,
        "palabras_clave_secundarias": kw_sec,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(f"{GEN_CONTENT_URL}/generar-articulo", json=payload)
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Error Generador: {r.text}")
    data = r.json()
    return Articulo(**data)


@app.post("/generar-articulos", response_model=LoteResponse)
async def generar_articulos(req: LoteRequest):
    try:
        # Pedimos más productos a PAAPI de los que necesitamos para poder
        # filtrar por descuento y palabra clave sin quedarnos tan cortos.
        # Luego recortamos a max_total más abajo.
        max_total = req.num_articulos * req.items_por_articulo
        total_items = min(max_total * 2, 50)

        # Construir keywords para PAAPI: si hay palabra_clave_principal, usamos
        # exclusivamente esa (ej. "aspiradoras"), sin añadir "black friday" u
        # otros términos. Si no hay principal, usamos busqueda.
        base_kw = (req.busqueda or "").strip()
        main_kw = (req.palabra_clave_principal or "").strip()
        base_kw_lower = base_kw.lower()
        if main_kw:
            kw_paapi = main_kw
        else:
            # Modo especial Black Friday: usamos "Black Friday" como contexto
            # editorial, pero no como keyword directa para PAAPI porque suele
            # devolver pocos o ningún resultado útil. Intentamos extraer la
            # parte de producto de la búsqueda, y si queda vacía usamos un
            # genérico como "ofertas".
            if "black friday" in base_kw_lower:
                producto = base_kw_lower.replace("black friday", "").strip(" ,.-")
                kw_paapi = producto or "ofertas"
            else:
                kw_paapi = base_kw

        productos = await buscar_productos(kw_paapi, req.categoria, total_items)
        # Reordenar: primero con precio disponible, luego el resto
        def has_precio(p):
            v = (p.precio or '').strip().lower()
            return bool(v) and not v.startswith('precio no disponible')
        productos = sorted(productos, key=lambda p: (not has_precio(p)))

        # Para este generador, priorizamos SIEMPRE productos en oferta.
        # api-paapi ya enriquece el campo precio con cosas como
        # "(-20%)", "20%", "antes ...", "ahorro ..." cuando hay descuento.
        # Consideramos que hay descuento si el texto del precio contiene "%"
        # (porcentaje) o palabras como "antes"/"ahorro".
        def tiene_descuento(p):
            # Si api-paapi ya ha marcado el producto como rebajado, confiamos en ese flag.
            if getattr(p, "tiene_descuento", None) is True:
                return True
            v = (p.precio or '').strip().lower()
            if not v or v.startswith('precio no disponible'):
                return False
            if '%' in v:
                return True
            return 'antes' in v or 'ahorro' in v

        productos_con_desc = [p for p in productos if tiene_descuento(p)]
        if productos_con_desc:
            productos = productos_con_desc
        else:
            # Modo especial Black Friday: algunas ofertas reales no vienen marcadas
            # limpiamente en PAAPI. Si la búsqueda contiene "black friday" y no
            # hemos detectado descuentos, usamos como fallback los productos que al
            # menos tienen un precio disponible, para no quedarnos sin artículos.
            base_kw_lower = (req.busqueda or "").strip().lower()
            if "black friday" in base_kw_lower:
                candidatos_fallback = [p for p in productos if has_precio(p)]
                productos = candidatos_fallback
            else:
                # En el resto de casos seguimos siendo estrictos: sin descuento,
                # preferimos no generar artículos.
                productos = []

        # Filtrar por palabra clave principal en el título cuando exista.
        # Si no hay coincidencias, preferimos quedarnos sin productos antes que mezclar categorías.
        main_kw = (req.palabra_clave_principal or '').strip().lower()
        if main_kw:
            def match_main(p):
                t = (p.titulo or '').lower()
                # Comparamos por palabras con un stemming muy simple para cubrir
                # singular/plural y masculino/femenino de forma genérica.
                kw_tokens = [tok for tok in re.split(r"\W+", main_kw) if tok]
                title_tokens = [tok for tok in re.split(r"\W+", t) if tok]
                stem_kw = {_stem_es(tok) for tok in kw_tokens}
                stem_title = {_stem_es(tok) for tok in title_tokens}
                return bool(stem_kw & stem_title)
            productos = [p for p in productos if match_main(p)]

        # Distribuir los productos disponibles de forma lo más equilibrada posible
        # entre los artículos, sin repetir productos y respetando el máximo
        # items_por_articulo.
        productos = productos[:max_total]
        total_disp = len(productos)
        grupos: List[List[Producto]] = []
        if total_disp == 0:
            grupos = []
        else:
            base = total_disp // req.num_articulos
            extra = total_disp % req.num_articulos
            idx_p = 0
            for i in range(req.num_articulos):
                # Número objetivo para este artículo (no superar items_por_articulo)
                target = base + (1 if i < extra else 0)
                target = min(target, req.items_por_articulo)
                if target <= 0:
                    grupos.append([])
                    continue
                grupos.append(productos[idx_p: idx_p + target])
                idx_p += target

        articulos: List[Articulo] = []
        idx = 1
        for grupo in grupos:
            tema = req.tema or f"Selección de productos más vendidos de ({req.busqueda}) #{idx}"
            articulo = await generar_articulo(tema, grupo, req.palabra_clave_principal, req.palabras_clave_secundarias)
            articulos.append(articulo)
            idx += 1
        return LoteResponse(articulos=articulos)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def build_wpai_xml(req: LoteRequest, articulos: List[Articulo]) -> str:
    """Construye XML simple compatible con WP All Import.
    El título del post se genera de forma sintética a partir de los parámetros
    de búsqueda, para evitar restos como '#1' o '(Black Friday)'.
    """
    from xml.sax.saxutils import escape
    xml_parts = ["<?xml version=\"1.0\" encoding=\"UTF-8\"?>", "<items>"]

    def _synthetic_title(idx: int) -> str:
        q = (req.busqueda or "").strip()
        kw = (req.palabra_clave_principal or "").strip()
        q_lower = q.lower()

        # Caso especial: Black Friday u otras promos en la búsqueda
        if "black friday" in q_lower:
            contexto = "Black Friday"
            # Intentar extraer el tipo de producto de la búsqueda si no hay palabra principal
            producto = kw or q_lower.replace("black friday", "").strip(" ,-")
            if producto:
                return f"Selección de {producto} más vendidos en {contexto}"
            return f"Selección de productos más vendidos en {contexto}"

        # Caso general sin Black Friday
        if kw and q:
            # Ej: busqueda="jabón", kw="orgánico" -> "Selección de jabón orgánico más vendidos"
            return f"Selección de {q} {kw} más vendidos"
        if kw:
            return f"Selección de {kw} más vendidos"
        if q:
            return f"Selección de {q} más vendidos"
        return "Selección de productos más vendidos"

    # Precalcular lista de hero válidas (no vacías) para rotación
    heroes = [u for u in HERO_IMAGES if u]

    for idx, a in enumerate(articulos, start=1):
        xml_parts.append("  <item>")
        post_title = _synthetic_title(idx)
        xml_parts.append(f"    <post_title>{escape(post_title)}</post_title>")
        xml_parts.append(f"    <post_excerpt>{escape(a.subtitulo)}</post_excerpt>")
        xml_parts.append(f"    <post_content><![CDATA[{a.articulo}]]></post_content>")
        if a.subtitulo_ia:
            xml_parts.append(f"    <subtitulo_ia>{escape(a.subtitulo_ia)}</subtitulo_ia>")
        # featured_image: rotamos entre las imágenes hero configuradas.
        # Para que rote aunque solo se genere un artículo por export, usamos
        # un índice derivado del título sintético en lugar del índice
        # secuencial del artículo.
        # Si no hay ninguna configurada, simplemente no añadimos el campo.
        if heroes:
            try:
                h_idx = abs(hash(post_title)) % len(heroes)
            except Exception:
                h_idx = (idx - 1) % len(heroes)
            hero_url = heroes[h_idx]
            xml_parts.append(f"    <featured_image>{escape(hero_url)}</featured_image>")
        # Campos auxiliares para WP All Import (evitar rellenar a mano)
        xml_parts.append("    <category>Productos recomendados</category>")
        xml_parts.append("    <tags>Amazon</tags>")
        xml_parts.append("    <caption>Amazon</caption>")
        xml_parts.append("    <post_status>draft</post_status>")
        xml_parts.append("    <post_type>post</post_type>")
        xml_parts.append("  </item>")
    xml_parts.append("</items>")
    return "\n".join(xml_parts)


class ExportRequest(LoteRequest):
    pass

class ExportResponse(BaseModel):
    xml: str

@app.post("/export/wp-all-import", response_model=ExportResponse)
async def export_wp_all_import(req: ExportRequest):
    lote = await generar_articulos(req)
    xml = build_wpai_xml(req, lote.articulos)
    return ExportResponse(xml=xml)


@app.post("/export/wp-all-import/file")
async def export_wp_all_import_file(req: ExportRequest):
    lote = await generar_articulos(req)
    xml = build_wpai_xml(req, lote.articulos)
    headers = {
        "Content-Disposition": "attachment; filename=theobjective_articulos.xml"
    }
    return Response(content=xml, media_type="application/xml", headers=headers)


@app.post("/export/wp-all-import/zip")
async def export_wp_all_import_zip(req: ExportRequest):
    lote = await generar_articulos(req)
    xml = build_wpai_xml(req, lote.articulos)

    memfile = io.BytesIO()
    with zipfile.ZipFile(memfile, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("theobjective_articulos.xml", xml)
        for idx, a in enumerate(lote.articulos, start=1):
            md = f"# {a.titulo}\n\n_{a.subtitulo}_\n\n{a.articulo}\n"
            zf.writestr(f"articulo_{idx:02d}.md", md)
    memfile.seek(0)
    headers = {"Content-Disposition": "attachment; filename=theobjective_export.zip"}
    return Response(content=memfile.read(), media_type="application/zip", headers=headers)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", 8020)))
