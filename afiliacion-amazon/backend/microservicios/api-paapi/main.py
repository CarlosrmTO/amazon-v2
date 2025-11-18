from fastapi import FastAPI, HTTPException, Query
from amazon_paapi import AmazonApi
import os
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from pydantic import BaseModel

# Cargar variables de entorno
load_dotenv()

app = FastAPI(title="API PAAPI5", 
              description="API para interactuar con Amazon Product Advertising API 5.0")

@app.on_event("startup")
async def _on_startup():
    try:
        import logging, os as _os
        logging.getLogger("uvicorn").info(f"api-paapi starting on PORT={_os.getenv('PORT')}")
    except Exception:
        pass

@app.get("/")
async def root():
    return {"status": "ok", "service": "api-paapi"}

# Configuración CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuración de la API de Amazon
ACCESS_KEY = os.getenv('AWS_ACCESS_KEY')
SECRET_KEY = os.getenv('AWS_SECRET_KEY')
PARTNER_TAG = os.getenv('PAAPI_ASSOCIATE_TAG') or os.getenv('AMAZON_ASSOCIATE_TAG') or 'theobjective-21'
# País para AmazonApi ("ES" para España)
COUNTRY = os.getenv('PAAPI_COUNTRY', 'ES')

amazon_api = None
if ACCESS_KEY and SECRET_KEY:
    try:
        amazon_api = AmazonApi(ACCESS_KEY, SECRET_KEY, PARTNER_TAG, COUNTRY)
    except Exception:
        amazon_api = None

@app.get("/health")
async def health():
    try:
        def _mask(s: Optional[str]):
            if not s:
                return None
            return s[:2] + "***" + s[-2:]
        return {
            "status": "ok",
            "initialized": bool(amazon_api is not None),
            "has_access_key": bool(ACCESS_KEY),
            "has_secret_key": bool(SECRET_KEY),
            "partner_tag": _mask(PARTNER_TAG),
            "country": COUNTRY,
        }
    except Exception as e:
        # Siempre devolver JSON para facilitar diagnóstico
        return {"status": "error", "detail": str(e)}

class ProductoRespuesta(BaseModel):
    asin: str
    titulo: str
    precio: str
    url_imagen: str
    url_producto: str
    url_afiliado: str
    marca: Optional[str] = None
    calificacion: Optional[float] = None
    total_valoraciones: Optional[int] = None

@app.get("/buscar", response_model=List[ProductoRespuesta])
async def buscar_productos(
    busqueda: str = Query(..., description="Término de búsqueda"),
    categoria: str = Query("All", description="Categoría de búsqueda"),
    num_resultados: int = Query(10, ge=1, le=50, description="Número de resultados solicitados (1-50)"),
    sort_by: str = Query("SalesRank", description="Orden (por ejemplo: SalesRank)"),
    pagina: int = Query(1, ge=1, le=10, description="Página de resultados (1-10)")
):
    """
    Busca productos en Amazon y devuelve los resultados con enlaces de afiliado
    """
    try:
        if amazon_api is None:
            raise HTTPException(status_code=500, detail={
                "error": "PAAPI not initialized",
                "has_access_key": bool(ACCESS_KEY),
                "has_secret_key": bool(SECRET_KEY),
                "partner_tag": PARTNER_TAG,
                "country": COUNTRY,
            })

        # Nota: python-amazon-paapi no expone un 'sort_by' directo en todas las operaciones.
        # Priorizar num_resultados y categoría; la ordenación por SalesRank se aproxima según disponibilidad.
        # PAAPI limita item_count a [1,10] y item_page a [1,10]
        item_count = max(1, min(10, int(num_resultados)))
        kwargs = {
            "keywords": busqueda,
            "item_count": item_count,
            "item_page": pagina,
        }
        # Nota: algunos wrappers de PAAPI ya inyectan 'resources' internamente.
        # Evitamos pasarlo aquí para no provocar 'multiple values for keyword argument "resources"'.
        # Normalizar categoría: mapear nombres comunes en español a índices válidos de PAAPI
        cat_in = (categoria or "").strip()
        cat_l = cat_in.lower()
        CATEGORY_MAP = {
            "tecnologia": "Electronics",
            "tecnología": "Electronics",
            "electronica": "Electronics",
            "electrónica": "Electronics",
            "informatica": "Computers",
            "informática": "Computers",
            "videojuegos": "VideoGames",
            "hogar": "HomeAndKitchen",
            "cocina": "Kitchen",
            "moda": "Fashion",
            "deportes": "SportsAndOutdoors",
            "libros": "Books",
            "cine": "MoviesAndTV",
            "peliculas": "MoviesAndTV",
            "películas": "MoviesAndTV",
            "series": "TV",
            "juguetes": "ToysAndGames",
        }
        mapped = None
        if cat_l and cat_l != "all":
            mapped = CATEGORY_MAP.get(cat_l)
            # Si el usuario ya pasó un índice válido (en inglés), permitirlo directamente
            VALID_LIKE = {"Electronics","Computers","VideoGames","HomeAndKitchen","Kitchen","Fashion","SportsAndOutdoors","Books","MoviesAndTV","TV","ToysAndGames"}
            if not mapped and cat_in in VALID_LIKE:
                mapped = cat_in
        if mapped:
            kwargs["search_index"] = mapped
        try:
            result = amazon_api.search_items(**kwargs)
        except Exception as e:
            # Reintento conservador: sin search_index y con menos resultados
            try:
                safe_kwargs = {
                    "keywords": busqueda.strip(),
                    "item_count": min(5, item_count),
                    "item_page": pagina,
                }
                result = amazon_api.search_items(**safe_kwargs)
            except Exception as e2:
                detail = {
                    "error": "PAAPI invalid parameters",
                    "first_attempt": {k: v for k, v in kwargs.items() if k != "keywords"},
                    "second_attempt": {k: v for k, v in safe_kwargs.items() if k != "keywords"},
                    "message": str(e2) or str(e),
                }
                raise HTTPException(status_code=400, detail=detail)

        # Normalizar posibles envoltorios (p.ej., SearchResult) a lista de items
        def _to_list(x):
            if x is None:
                return []
            if isinstance(x, list):
                return x
            for attr in ("items", "search_result", "searchResult", "results", "Results"):
                v = getattr(x, attr, None)
                if v is not None:
                    try:
                        return list(v) if not isinstance(v, list) else v
                    except Exception:
                        pass
            try:
                return list(x)
            except Exception:
                return []

        items = _to_list(result)

        if not items:
            return []

        resultados = []

        def _get_image_url(it):
            try:
                # Plan A: atributos directos
                direct = (
                    getattr(it, 'image_url', None)
                    or getattr(it, 'large_image_url', None)
                )
                if direct:
                    return direct
                # Plan B: rutas anidadas comunes
                def walk(obj, path):
                    cur = obj
                    for p in path:
                        cur = getattr(cur, p, None)
                        if cur is None:
                            return None
                    return cur
                candidates = [
                    ('images', 'primary', 'large', 'url'),
                    ('images', 'primary', 'medium', 'url'),
                    ('images', 'primary', 'small', 'url'),
                    ('large_image', 'url'),
                    ('medium_image', 'url'),
                    ('small_image', 'url'),
                    ('image', 'url'),
                ]
                for path in candidates:
                    v = walk(it, path)
                    if isinstance(v, str) and v:
                        return v
            except Exception:
                pass
            return ""
        def _get_title(it):
            try:
                def walk_any(obj, path):
                    cur = obj
                    for p in path:
                        if isinstance(p, int):
                            if isinstance(cur, (list, tuple)) and len(cur) > p:
                                cur = cur[p]
                            else:
                                return None
                        else:
                            cur = getattr(cur, p, None)
                            if cur is None:
                                return None
                    return cur

                candidates = [
                    ('item_info', 'title', 'display_value'),
                    ('item_info', 'product_title', 'display_value'),
                    ('title',),
                    ('product_title',),
                ]
                for path in candidates:
                    v = walk_any(it, path)
                    if isinstance(v, str) and v.strip():
                        return v.strip()
            except Exception:
                pass
            return getattr(it, 'title', None) or getattr(it, 'product_title', None) or ''

        for item in items:
            # Construir URL de afiliado
            url_base = getattr(item, 'detail_page_url', '') or getattr(item, 'url', '')
            tag_afiliado = f"?tag={PARTNER_TAG}"
            url_afiliado = f"{url_base}{tag_afiliado if '?' not in url_base else '&' + tag_afiliado[1:]}"
            
            # Obtener precio
            precio = "Precio no disponible"
            has_discount = False
            try:
                def walk_any(obj, path):
                    cur = obj
                    for p in path:
                        if isinstance(p, int):
                            if isinstance(cur, (list, tuple)) and len(cur) > p:
                                cur = cur[p]
                            else:
                                return None
                        else:
                            cur = getattr(cur, p, None)
                            if cur is None:
                                return None
                    return cur

                # 1) display_amount si existe ("EUR 59,99" o similar)
                display_candidates = [
                    ('offers', 'listings', 0, 'price', 'display_amount'),
                    ('offers', 'summaries', 0, 'lowest_price', 'display_amount'),
                    ('price', 'display_amount'),
                ]
                for path in display_candidates:
                    disp = walk_any(item, path)
                    if isinstance(disp, str) and disp.strip():
                        precio = disp.strip()
                        break

                if precio == "Precio no disponible":
                    # 2) amount + currency
                    amount_candidates = [
                        ('offers', 'listings', 0, 'price', 'amount'),
                        ('offers', 'summaries', 0, 'lowest_price', 'amount'),
                        ('list_price', 'amount'),
                        ('price', 'amount'),
                    ]
                    currency_candidates = [
                        ('offers', 'listings', 0, 'price', 'currency'),
                        ('offers', 'summaries', 0, 'lowest_price', 'currency'),
                        ('list_price', 'currency'),
                        ('price', 'currency'),
                    ]
                    amount = None
                    currency = None
                    for path in amount_candidates:
                        v = walk_any(item, path)
                        if v is not None:
                            amount = v
                            break
                    for path in currency_candidates:
                        v = walk_any(item, path)
                        if v is not None:
                            currency = v
                            break
                    if amount and currency:
                        try:
                            amt = float(amount)
                            # Formato EUR bonito
                            if str(currency).upper() in ("EUR", "EURO", "€"):
                                precio = f"{amt:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"
                            else:
                                precio = f"{amt:.2f} {currency}"
                        except Exception:
                            precio = f"{amount} {currency}"
                
                # 3) Enriquecer con precio de lista y ahorro si existe
                try:
                    # savings puede venir como display_amount/amount/percentage
                    list_amt = (
                        walk_any(item, ('offers','listings',0,'price','savings','basis'))
                        or walk_any(item, ('list_price','amount'))
                    )
                    list_cur = (
                        walk_any(item, ('list_price','currency'))
                        or walk_any(item, ('offers','listings',0,'price','currency'))
                    )
                    save_pct = (
                        walk_any(item, ('offers','listings',0,'price','savings','percentage'))
                        or walk_any(item, ('offers','summaries',0,'lowest_price','savings','percentage'))
                    )
                    save_display = (
                        walk_any(item, ('offers','listings',0,'price','savings','display_amount'))
                        or walk_any(item, ('offers','summaries',0,'lowest_price','savings','display_amount'))
                    )
                    save_amount = (
                        walk_any(item, ('offers','listings',0,'price','savings','amount'))
                        or walk_any(item, ('offers','summaries',0,'lowest_price','savings','amount'))
                    )
                    if list_amt and list_cur:
                        try:
                            la = float(list_amt)
                            if str(list_cur).upper() in ("EUR","EURO","€"):
                                list_display = f"{la:,.2f}".replace(",","X").replace(".",",").replace("X",".") + " €"
                            else:
                                list_display = f"{la:.2f} {list_cur}"
                            if precio != "Precio no disponible":
                                if save_pct is not None:
                                    precio = f"{precio} (antes {list_display}, -{int(save_pct)}%)"
                                    has_discount = True
                                elif save_display or save_amount:
                                    try:
                                        if save_display:
                                            sd = str(save_display)
                                        else:
                                            sa = float(save_amount)
                                            sd = f"{sa:,.2f}".replace(",","X").replace(".",",").replace("X",".") + (" €" if str(list_cur).upper() in ("EUR","EURO","€") else f" {list_cur}")
                                        precio = f"{precio} (ahorro {sd}, antes {list_display})"
                                        has_discount = True
                                    except Exception:
                                        pass
                        except Exception:
                            pass
                    else:
                        # Si no tenemos list price pero tenemos porcentaje de ahorro, añadimos el porcentaje solo
                        if precio != "Precio no disponible" and save_pct is not None:
                            precio = f"{precio} (-{int(save_pct)}%)"
                            has_discount = True
                except Exception:
                    pass
            except Exception:
                pass
            # Si el producto no tiene ningún indicador de descuento, lo descartamos:
            if not has_discount:
                continue

            # Obtener marca
            marca = getattr(item, 'brand', None) or getattr(item, 'manufacturer', None)
            
            # Calificaciones (no garantizadas en este wrapper)
            calificacion = None
            total_valoraciones = None
            
            resultados.append(ProductoRespuesta(
                asin=getattr(item, 'asin', ''),
                titulo=(_get_title(item) or "Sin título"),
                precio=precio,
                url_imagen=_get_image_url(item),
                url_producto=url_base,
                url_afiliado=url_afiliado,
                marca=marca,
                calificacion=calificacion,
                total_valoraciones=total_valoraciones
            ))
        
        return resultados
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
