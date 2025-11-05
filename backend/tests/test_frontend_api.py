import pytest
from fastapi.testclient import TestClient
import os
import importlib.util

FE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'afiliacion-amazon', 'backend', 'microservicios', 'frontend-api', 'main.py'))
spec = importlib.util.spec_from_file_location('frontend_api_main', FE_PATH)
fe_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fe_module)  # type: ignore
app = fe_module.app  # noqa

client = TestClient(app)


async def _fake_buscar_productos(busqueda, categoria, total):
    # Devuelve productos mínimos
    items = []
    for i in range(total):
        items.append(type('P', (), {
            'titulo': f'Producto {i+1}',
            'url_producto': f'https://www.amazon.es/dp/ASIN{i+1}',
            'url_afiliado': f'https://www.amazon.es/dp/ASIN{i+1}?tag=theobjective-21',
            'url_imagen': 'https://example.com/img.jpg',
            'precio': '19.99 EUR',
            'marca': 'Marca',
            'features': None,
            'model_dump': lambda self=None: {
                'titulo': f'Producto {i+1}',
                'url_producto': f'https://www.amazon.es/dp/ASIN{i+1}',
                'url_afiliado': f'https://www.amazon.es/dp/ASIN{i+1}?tag=theobjective-21',
                'url_imagen': 'https://example.com/img.jpg',
                'precio': '19.99 EUR',
                'marca': 'Marca',
                'features': None,
            }
        })())
    return items


async def _fake_generar_articulo(tema, productos, kw_main, kw_sec):
    body = "Contenido demo con enlace contextual a Amazon y tono editorial."
    return type('A', (), {
        'titulo': tema,
        'subtitulo': 'Subtitulo demo',
        'articulo': body,
    })()


def test_generar_articulos_y_xml(monkeypatch):
    mod = fe_module
    monkeypatch.setattr(mod, 'buscar_productos', _fake_buscar_productos)
    monkeypatch.setattr(mod, 'generar_articulo', _fake_generar_articulo)

    payload = {
        'busqueda': 'auriculares',
        'categoria': 'All',
        'num_articulos': 2,
        'items_por_articulo': 2,
        'tema': 'Tema de prueba',
        'palabra_clave_principal': 'auriculares inalámbricos',
        'palabras_clave_secundarias': ['Bluetooth 5.3']
    }

    r = client.post('/generar-articulos', json=payload)
    assert r.status_code == 200
    data = r.json()
    assert len(data['articulos']) == 2

    r2 = client.post('/export/wp-all-import', json=payload)
    assert r2.status_code == 200
    xml = r2.json()['xml']
    assert '<items>' in xml and '</items>' in xml
    assert '<post_title>' in xml and '<post_content>' in xml

    r3 = client.post('/export/wp-all-import/zip', json=payload)
    assert r3.status_code == 200
    assert r3.headers.get('Content-Type') == 'application/zip'


def test_health_ok():
    r = client.get('/health')
    assert r.status_code == 200
    data = r.json()
    assert 'status' in data and data['status'] == 'ok'
    assert 'api_paapi_url' in data
    assert 'gen_content_url' in data


def test_ensure_url_normalization():
    mod = fe_module
    assert mod._ensure_url('example.com') == 'https://example.com'
    assert mod._ensure_url('https://example.com') == 'https://example.com'
    assert mod._ensure_url('') == ''
