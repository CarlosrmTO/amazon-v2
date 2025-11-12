from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field
from typing import List, Optional
from dotenv import load_dotenv
import os
import httpx
from fastapi.middleware.cors import CORSMiddleware
import io
import zipfile

load_dotenv()

app = FastAPI(title="Frontend API Orquestación",
              description="Orquesta PAAPI y Generador de Contenidos y exporta a XML WP All Import")

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

@app.get("/health")
async def health():
    return {
        "status": "ok",
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

class LoteRequest(BaseModel):
    tema: Optional[str] = None
    busqueda: str = Field(default="", description="keywords de búsqueda en Amazon")
    categoria: str = Field(default=DEFAULT_CATEGORY)
    num_articulos: int = Field(default=3, ge=1, le=10)
    items_por_articulo: int = Field(default=DEFAULT_ITEMS_PER_ARTICLE, ge=1, le=10)
    palabra_clave_principal: Optional[str] = None
    palabras_clave_secundarias: Optional[List[str]] = Field(default_factory=list)

class Articulo(BaseModel):
    titulo: str
    subtitulo: str
    articulo: str

class LoteResponse(BaseModel):
    articulos: List[Articulo]


def chunk(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


async def buscar_productos(busqueda: str, categoria: str, total: int) -> List[Producto]:
    params = {
        "busqueda": busqueda,
        "categoria": categoria,
        "num_resultados": total,
        "sort_by": "SalesRank",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(f"{API_PAAPI_URL}/buscar", params=params)
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Error PAAPI: {r.text}")
    data = r.json()
    productos: List[Producto] = []
    for d in data:
        productos.append(Producto(
            titulo=d.get("titulo", ""),
            url_producto=d.get("url_producto", ""),
            url_afiliado=d.get("url_afiliado", ""),
            url_imagen=d.get("url_imagen"),
            precio=d.get("precio"),
            marca=d.get("marca"),
            features=None
        ))
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
        total_items = req.num_articulos * req.items_por_articulo
        productos = await buscar_productos(req.busqueda, req.categoria, total_items)
        grupos = list(chunk(productos, req.items_por_articulo))[:req.num_articulos]

        articulos: List[Articulo] = []
        idx = 1
        for grupo in grupos:
            tema = req.tema or f"Selección de más vendidos ({req.busqueda}) #{idx}"
            articulo = await generar_articulo(tema, grupo, req.palabra_clave_principal, req.palabras_clave_secundarias)
            articulos.append(articulo)
            idx += 1
        return LoteResponse(articulos=articulos)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def build_wpai_xml(articulos: List[Articulo]) -> str:
    # XML simple compatible con WP All Import: <items><item><post_title>... etc.
    from xml.sax.saxutils import escape
    xml_parts = ["<?xml version=\"1.0\" encoding=\"UTF-8\"?>", "<items>"]
    for a in articulos:
        xml_parts.append("  <item>")
        xml_parts.append(f"    <post_title>{escape(a.titulo)}</post_title>")
        xml_parts.append(f"    <post_excerpt>{escape(a.subtitulo)}</post_excerpt>")
        xml_parts.append(f"    <post_content><![CDATA[{a.articulo}]]></post_content>")
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
    xml = build_wpai_xml(lote.articulos)
    return ExportResponse(xml=xml)


@app.post("/export/wp-all-import/file")
async def export_wp_all_import_file(req: ExportRequest):
    lote = await generar_articulos(req)
    xml = build_wpai_xml(lote.articulos)
    headers = {
        "Content-Disposition": "attachment; filename=theobjective_articulos.xml"
    }
    return Response(content=xml, media_type="application/xml", headers=headers)


@app.post("/export/wp-all-import/zip")
async def export_wp_all_import_zip(req: ExportRequest):
    lote = await generar_articulos(req)
    xml = build_wpai_xml(lote.articulos)

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
