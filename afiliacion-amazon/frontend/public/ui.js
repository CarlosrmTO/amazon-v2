function ensureUrl(u){
  const s = (u||'').trim();
  if(!s) return s;
  const withProto = s.startsWith('http://') || s.startsWith('https://') ? s : `https://${s}`;
  return withProto.replace(/\/?$/, '');
}

const DEFAULT_API_BASE = 'https://frontend-api-production-060a.up.railway.app';

function getApiBaseInput(){
  return document.getElementById('api_base');
}

function loadApiBase(){
  try{
    const saved = localStorage.getItem('api_base');
    if(saved && saved.trim()) return saved.trim();
  }catch(_){}
  return DEFAULT_API_BASE;
}

function saveApiBase(v){
  try{ localStorage.setItem('api_base', v||''); }catch(_){}
}

async function generarArticulos() {
  const apiBase = ensureUrl(getApiBaseInput().value);
  saveApiBase(apiBase);
  const busqueda = document.getElementById('busqueda').value.trim();
  const categoria = document.getElementById('categoria').value.trim();
  const num_articulos = parseInt(document.getElementById('num_articulos').value, 10) || 1;
  const items_por_articulo = parseInt(document.getElementById('items_por_articulo').value, 10) || 5;
  const tema = document.getElementById('tema').value.trim();
  const kw_main = document.getElementById('kw_main').value.trim();
  const kw_sec = document.getElementById('kw_sec').value.split(',').map(s => s.trim()).filter(Boolean);

  const payload = {
    busqueda,
    categoria,
    num_articulos,
    items_por_articulo,
    tema: tema || null,
    palabra_clave_principal: kw_main || null,
    palabras_clave_secundarias: kw_sec
  };

  const status = document.getElementById('status');
  const preview = document.getElementById('preview');
  status.textContent = 'Generando artículos...';
  preview.innerHTML = '';

  try {
    const res = await fetch(`${apiBase}/generar-articulos`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) {
      const txt = await res.text();
      throw new Error(`Error ${res.status}: ${txt}`);
    }
    const data = await res.json();
    const arts = data.articulos || [];

    if (!arts.length) {
      preview.innerHTML = '<div class="alert alert-warning">No se generaron artículos.</div>';
    } else {
      const html = arts.map((a, i) => `
        <div class="mb-4">
          <h4 class="mb-1">${escapeHtml(a.titulo || `Artículo ${i+1}`)}</h4>
          <div class="text-muted mb-2">${escapeHtml(a.subtitulo || '')}</div>
          <div class="border rounded p-3 bg-white" style="white-space:pre-wrap">${a.articulo}</div>
        </div>
      `).join('');
      preview.innerHTML = html;
    }
    status.textContent = 'Completado';
  } catch (err) {
    status.textContent = 'Error';
    preview.innerHTML = `<div class="alert alert-danger">${escapeHtml(err.message)}</div>`;
  }
}

async function exportarXML() {
  const apiBase = ensureUrl(getApiBaseInput().value);
  saveApiBase(apiBase);
  const busqueda = document.getElementById('busqueda').value.trim();
  const categoria = document.getElementById('categoria').value.trim();
  const num_articulos = parseInt(document.getElementById('num_articulos').value, 10) || 1;
  const items_por_articulo = parseInt(document.getElementById('items_por_articulo').value, 10) || 5;
  const tema = document.getElementById('tema').value.trim();
  const kw_main = document.getElementById('kw_main').value.trim();
  const kw_sec = document.getElementById('kw_sec').value.split(',').map(s => s.trim()).filter(Boolean);

  const payload = {
    busqueda,
    categoria,
    num_articulos,
    items_por_articulo,
    tema: tema || null,
    palabra_clave_principal: kw_main || null,
    palabras_clave_secundarias: kw_sec
  };

  const status = document.getElementById('status');
  status.textContent = 'Generando XML...';

  try {
    const res = await fetch(`${apiBase}/export/wp-all-import/file`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) {
      const txt = await res.text();
      throw new Error(`Error ${res.status}: ${txt}`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'theobjective_articulos.xml';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    status.textContent = 'XML descargado';
  } catch (err) {
    status.textContent = 'Error';
    alert(err.message);
  }
}

function escapeHtml(str) {
  return (str || '').replace(/[&<>"']/g, function (m) {
    return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#39;'})[m];
  });
}

window.addEventListener('DOMContentLoaded', () => {
  const input = getApiBaseInput();
  if(input){
    const current = (input.value||'').trim();
    if(!current || current.includes('localhost')){
      input.value = loadApiBase();
    }
  }
  document.getElementById('btn-generar').addEventListener('click', generarArticulos);
  document.getElementById('btn-exportar').addEventListener('click', exportarXML);
});
