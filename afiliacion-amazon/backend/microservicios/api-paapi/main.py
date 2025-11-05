from fastapi import FastAPI, HTTPException, Query
from paapi5_python_sdk.api.default_api import DefaultApi
from paapi5_python_sdk.configuration import Configuration
from paapi5_python_sdk.api_client import ApiClient
from paapi5_python_sdk.models.search_items_request import SearchItemsRequest
from paapi5_python_sdk.models.search_items_resource import SearchItemsResource
from paapi5_python_sdk.rest import ApiException
import os
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from pydantic import BaseModel

# Cargar variables de entorno
load_dotenv()

app = FastAPI(title="API PAAPI5", 
              description="API para interactuar con Amazon Product Advertising API 5.0")

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
HOST = os.getenv('PAAPI_HOST', 'webservices.amazon.es')
REGION = os.getenv('PAAPI_REGION', 'eu-west-1')
PARTNER_TAG = os.getenv('PAAPI_ASSOCIATE_TAG') or os.getenv('AMAZON_ASSOCIATE_TAG') or 'theobjective-21'

if not ACCESS_KEY or not SECRET_KEY:
    # Se informará en runtime si falta configuración
    pass

_paapi_config = Configuration(
    access_key=ACCESS_KEY,
    secret_key=SECRET_KEY,
    host=HOST,
    region=REGION,
)
api = DefaultApi(ApiClient(_paapi_config))

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
    num_resultados: int = Query(10, ge=1, le=50, description="Número de resultados (1-50)"),
    sort_by: str = Query("SalesRank", description="Orden (por ejemplo: SalesRank)")
):
    """
    Busca productos en Amazon y devuelve los resultados con enlaces de afiliado
    """
    try:
        # Configuración de la búsqueda
        search_items_resource = [
            SearchItemsResource.ITEMINFO_TITLE,
            SearchItemsResource.IMAGES_PRIMARY_LARGE,
            SearchItemsResource.ITEMINFO_BY_LINE_INFO,
            SearchItemsResource.OFFERS_LISTINGS_PRICE,
        ]

        search_request = SearchItemsRequest(
            partner_tag=PARTNER_TAG,
            partner_type='Associates',
            keywords=busqueda,
            search_index=categoria,
            item_count=num_resultados,
            resources=search_items_resource,
            sort_by=sort_by
        )

        # Realizar la búsqueda
        response = api.search_items(search_request)
        
        if response.search_result is None:
            return []

        # Procesar resultados
        resultados = []
        for item in response.search_result.items:
            # Construir URL de afiliado
            url_base = item.detail_page_url
            tag_afiliado = f"?tag={PARTNER_TAG}"
            url_afiliado = f"{url_base}{tag_afiliado if '?' not in url_base else '&' + tag_afiliado[1:]}"
            
            # Obtener precio
            precio = "Precio no disponible"
            if hasattr(item, 'offers') and item.offers and item.offers.listings:
                precio = f"{item.offers.listings[0].price.amount} {item.offers.listings[0].price.currency}"
            
            # Obtener marca
            marca = None
            if hasattr(item, 'item_info') and hasattr(item.item_info, 'by_line_info'):
                marca = item.item_info.by_line_info.manufacturer
            
            # Calificaciones (no garantizadas, omitimos para compatibilidad segura)
            calificacion = None
            total_valoraciones = None
            
            resultados.append(ProductoRespuesta(
                asin=item.asin,
                titulo=item.item_info.title.display_value if hasattr(item, 'item_info') else "Sin título",
                precio=precio,
                url_imagen=item.images.primary.large.url if hasattr(item, 'images') and item.images.primary.large else "",
                url_producto=url_base,
                url_afiliado=url_afiliado,
                marca=marca,
                calificacion=calificacion,
                total_valoraciones=total_valoraciones
            ))
        
        return resultados
    
    except ApiException as e:
        raise HTTPException(status_code=500, detail=f"Error en la API de Amazon: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
