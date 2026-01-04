# Antoni IA API

API REST para gestión remota del equipo de IA con Ollama. Permite encender, apagar y verificar el estado del equipo de forma remota mediante Wake-on-LAN y SSH.

## Características

- **Autenticación con API Keys**: Todas las operaciones requieren autenticación
- **Test de estado**: Verifica si el equipo está online y si Ollama está respondiendo
- **Wake-on-LAN**: Arranca el equipo remotamente mediante magic packet
- **Apagado remoto**: Apaga el equipo via SSH
- **Dockerizado**: Listo para desplegar con Docker y Traefik
- **Integración con n8n**: Endpoints diseñados para flujos de automatización

## Requisitos previos

- Docker y Docker Compose instalados
- Traefik configurado (si usas el docker-compose incluido)
- Wake-on-LAN habilitado en el equipo de IA
- Acceso SSH al equipo de IA

## Instalación

### 1. Clonar o copiar el proyecto

```bash
cd antoni-ia-api
```

### 2. Configurar variables de entorno

Copia el archivo `.env.example` a `.env` y edita los valores:

```bash
cp .env.example .env
```

Edita el archivo `.env` con tus valores:

```env
# Configuración del equipo de IA
EQUIPO_IA=192.168.1.190
IA_MAC=18:c0:4d:3b:fc:8f
OLLAMA_PORT=11434
OPEN_WEBUI_PORT=3000

# Configuración SSH
SSH_USER=tu_usuario
SSH_PASS=tu_contraseña
SSH_PORT=22

# API Keys (separadas por comas si son múltiples)
API_KEYS=tu_api_key_secreta_aqui,otra_api_key_opcional

# Configuración de Traefik
SUBDOMINIO=ia-api.tudominio.com
```

### 3. Construir y ejecutar con Docker Compose

```bash
docker-compose up -d --build
```

### 4. Verificar que está funcionando

```bash
curl https://ia-api.tudominio.com/
```

## Uso de la API

Todas las peticiones (excepto el endpoint raíz `/`) requieren el header `X-API-Key`:

```bash
X-API-Key: tu_api_key_secreta_aqui
```

### Endpoints disponibles

#### GET / - Información de la API

```bash
curl https://ia-api.tudominio.com/
```

**Respuesta:**
```json
{
  "api": "Antoni IA API",
  "version": "1.0.0",
  "status": "running"
}
```

#### GET /test - Verificar estado del equipo y Ollama

```bash
curl -H "X-API-Key: tu_api_key" https://ia-api.tudominio.com/test
```

**Respuesta:**
```json
{
  "equipo_online": true,
  "ollama_online": true,
  "mensaje": "Equipo y Ollama funcionando correctamente"
}
```

#### POST /arrancar - Arrancar el equipo de IA

```bash
curl -X POST -H "X-API-Key: tu_api_key" https://ia-api.tudominio.com/arrancar
```

**Respuesta:**
```json
{
  "success": true,
  "mensaje": "Magic packet enviado a 18:c0:4d:3b:fc:8f. El equipo debería arrancar en breve."
}
```

#### POST /apagar - Apagar el equipo de IA

```bash
curl -X POST -H "X-API-Key: tu_api_key" https://ia-api.tudominio.com/apagar
```

**Respuesta:**
```json
{
  "success": true,
  "mensaje": "Comando de apagado enviado correctamente. El equipo se apagará en breve."
}
```

## Integración con n8n

### Ejemplo de flujo para verificar estado

1. **HTTP Request Node**:
   - Method: GET
   - URL: `https://ia-api.tudominio.com/test`
   - Headers:
     - Name: `X-API-Key`
     - Value: `{{$env.IA_API_KEY}}`

2. **IF Node**: Verificar `equipo_online` y `ollama_online`

3. **Acción según resultado**: Enviar notificación, arrancar equipo, etc.

### Ejemplo de flujo para arrancar equipo

1. **HTTP Request Node**:
   - Method: POST
   - URL: `https://ia-api.tudominio.com/arrancar`
   - Headers:
     - Name: `X-API-Key`
     - Value: `{{$env.IA_API_KEY}}`

2. **Wait Node**: Esperar 60 segundos

3. **HTTP Request Node**: Verificar con `/test` si arrancó correctamente

## Documentación de la API

Una vez en funcionamiento, puedes acceder a la documentación interactiva:

- **Swagger UI**: `https://ia-api.tudominio.com/docs`
- **ReDoc**: `https://ia-api.tudominio.com/redoc`

## Configuración de Traefik

El proyecto está configurado para usar Traefik con:
- Red externa `traefik`
- HTTPS automático con Let's Encrypt
- Certificado SSL automático

Asegúrate de que tu configuración de Traefik tenga:
- Red `traefik` creada
- Certificado resolver configurado como `letsencrypt`

## Notas de seguridad

- Cambia las API Keys por valores seguros y únicos
- No compartas el archivo `.env`
- Considera usar variables de entorno o secretos de Docker para credenciales SSH
- El apagado del equipo requiere que el usuario SSH tenga permisos sudo sin contraseña para el comando `shutdown`

## Desarrollo local (sin Docker)

```bash
# Instalar dependencias
pip install -r requirements.txt

# Ejecutar
python main.py
```

La API estará disponible en `http://localhost:8000`

## Solución de problemas

### El equipo no arranca con Wake-on-LAN
- Verifica que Wake-on-LAN esté habilitado en la BIOS
- Asegúrate de que la MAC address sea correcta
- Verifica que el equipo esté en la misma red o accesible

### Error al apagar via SSH
- Verifica credenciales SSH
- Asegura que el usuario tenga permisos sudo para shutdown
- Configura sudo sin contraseña: `echo "usuario ALL=(ALL) NOPASSWD: /sbin/shutdown" | sudo tee /etc/sudoers.d/shutdown`

### Error 401 Unauthorized
- Verifica que el header `X-API-Key` esté presente
- Asegúrate de usar una API Key válida definida en `API_KEYS`
