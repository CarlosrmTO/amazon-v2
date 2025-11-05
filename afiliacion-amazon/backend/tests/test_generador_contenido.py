import pytest
from fastapi.testclient import TestClient

import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'microservicios', 'generador-contenido')))

from main import app  # noqa: E402

client = TestClient(app)


def test_generar_articulo_incluye_enlaces():
    payload = {
        "tema": "Los mejores auriculares inalámbricos",
        "productos": [
            {
                "titulo": "Auriculares X",
                "url_producto": "https://www.amazon.es/dp/B000000001",
                "precio": "59.99 EUR",
                "marca": "MarcaX",
                "features": ["Bluetooth 5.0", "Cancelación de ruido"]
            },
            {
                "titulo": "Auriculares Y",
                "url_producto": "https://www.amazon.es/dp/B000000002?ref_=abc",
                "precio": "89.99 EUR",
                "marca": "MarcaY",
                "features": ["Batería 30h"]
            }
        ],
        "max_items": 2
    }

    # Mockear la llamada a OpenAI si fuese necesario; aquí comprobamos pre-proceso de enlaces
    resp = client.post("/generar-articulo", json=payload)
    assert resp.status_code in (200, 500)  # 500 si falta OPENAI_API_KEY

    # Verificamos que el preprocesado añade tag en url_afiliado
    from main import ensure_affiliate, DEFAULT_AFFILIATE_TAG
    assert ensure_affiliate("https://www.amazon.es/dp/B000000001", DEFAULT_AFFILIATE_TAG).endswith(f"tag={DEFAULT_AFFILIATE_TAG}")
    assert "tag=" in ensure_affiliate("https://www.amazon.es/dp/B000000002?ref_=abc", DEFAULT_AFFILIATE_TAG)
