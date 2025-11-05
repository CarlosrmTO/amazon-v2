import types
import pytest
from fastapi.testclient import TestClient
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'microservicios', 'api-paapi')))
from main import app

client = TestClient(app)


class _Price:
    def __init__(self):
        self.amount = 19.99
        self.currency = "EUR"

class _Listing:
    def __init__(self):
        self.price = _Price()

class _Offers:
    def __init__(self):
        self.listings = [_Listing()]

class _Title:
    def __init__(self):
        self.display_value = "Producto Demo"

class _ByLine:
    def __init__(self):
        self.manufacturer = "MarcaDemo"

class _ItemInfo:
    def __init__(self):
        self.title = _Title()
        self.by_line_info = _ByLine()

class _ImageLarge:
    def __init__(self):
        self.url = "https://example.com/img.jpg"

class _ImagesPrimary:
    def __init__(self):
        self.large = _ImageLarge()

class _Images:
    def __init__(self):
        self.primary = _ImagesPrimary()

class _Item:
    def __init__(self, i):
        self.asin = f"ASIN{i}"
        self.detail_page_url = f"https://www.amazon.es/dp/ASIN{i}"
        self.offers = _Offers()
        self.item_info = _ItemInfo()
        self.images = _Images()

class _SearchResult:
    def __init__(self, n):
        self.items = [_Item(i) for i in range(1, n+1)]

class _Response:
    def __init__(self, n):
        self.search_result = _SearchResult(n)


def test_buscar_construye_enlace_afiliado(monkeypatch):
    # Forzar tag para test
    monkeypatch.setenv('PAAPI_ASSOCIATE_TAG', 'theobjective-21')

    # Monkeypatch de la llamada al SDK
    import main as api_mod
    def fake_search_items(req):
        return _Response(2)
    monkeypatch.setattr(api_mod, 'api', types.SimpleNamespace(search_items=fake_search_items))

    resp = client.get('/buscar', params={
        'busqueda': 'auriculares',
        'categoria': 'All',
        'num_resultados': 2,
        'sort_by': 'SalesRank'
    })
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]['url_afiliado'].startswith('https://www.amazon.es/dp/ASIN1')
    assert 'tag=theobjective-21' in data[0]['url_afiliado']
