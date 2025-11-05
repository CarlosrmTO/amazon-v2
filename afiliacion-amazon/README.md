# Generador de Contenidos para Afiliados de Amazon

Este proyecto es un sistema completo para generar contenido de afiliación de Amazon, incluyendo artículos y listas de productos con enlaces de afiliación.

## Características principales

- Búsqueda de productos en Amazon a través de PAAPI5
- Generación de contenido único y atractivo
- Inclusión automática de enlaces de afiliación
- Interfaz web intuitiva
- Arquitectura de microservicios escalable

## Estructura del proyecto

```
afiliacion-amazon/
├── backend/
│   ├── microservicios/
│   │   ├── api-paapi/         # Microservicio para interactuar con PAAPI5
│   │   ├── generador-contenido/ # Microservicio para generar contenido
│   │   └── frontend-api/      # API para el frontend
│   └── tests/                 # Tests unitarios e integración
└── frontend/                  # Aplicación web
    ├── public/
    └── src/
        ├── components/
        ├── pages/
        └── services/
```

## Configuración inicial

1. Clona el repositorio
2. Copia el archivo `.env.example` a `.env` y configura tus credenciales de Amazon Associates
3. Instala las dependencias de cada microservicio
4. Inicia los servicios necesarios

## Instalación

### API PAAPI

```bash
cd backend/microservicios/api-paapi
cp .env.example .env
# Edita el archivo .env con tus credenciales
pip install -r requirements.txt
uvicorn main:app --reload
```

## Uso

1. Inicia el microservicio de la API PAAPI
2. Accede a la documentación de la API en `http://localhost:8000/docs`
3. Realiza búsquedas de productos y genera contenido de afiliación

## Licencia

MIT License
