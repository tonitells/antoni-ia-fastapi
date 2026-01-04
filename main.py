from fastapi import FastAPI, Security, HTTPException, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
import os
from dotenv import load_dotenv
import httpx
import asyncio
from wakeonlan import send_magic_packet
import paramiko

load_dotenv()

app = FastAPI(
    title="Antoni IA API",
    description="API para gestión remota del equipo de IA con Ollama",
    version="1.0.0"
)

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

# Configuración desde .env
EQUIPO_IA = os.getenv("EQUIPO_IA")
IA_MAC = os.getenv("IA_MAC")
OLLAMA_PORT = os.getenv("OLLAMA_PORT", "11434")
SSH_USER = os.getenv("SSH_USER")
SSH_PASS = os.getenv("SSH_PASS")
SSH_PORT = int(os.getenv("SSH_PORT", "22"))
API_KEYS = os.getenv("API_KEYS", "").split(",")
# Dirección de broadcast para Wake-on-LAN (por defecto usa la de la red del equipo)
WOL_BROADCAST = os.getenv("WOL_BROADCAST", "255.255.255.255")
WOL_PORT = int(os.getenv("WOL_PORT", "9"))


async def verify_api_key(api_key: str = Security(API_KEY_HEADER)):
    if not api_key or api_key not in API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Key"
        )
    return api_key


class StatusResponse(BaseModel):
    equipo_online: bool
    ollama_online: bool
    mensaje: str


class MessageResponse(BaseModel):
    success: bool
    mensaje: str


@app.get("/")
async def root():
    return {
        "api": "Antoni IA API",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/debug", dependencies=[Security(verify_api_key)])
async def debug_info():
    """
    Endpoint de debug para diagnosticar problemas de conectividad.
    Requiere API Key en header X-API-Key.
    """
    import platform

    debug_data = {
        "os_name": os.name,
        "platform": platform.system(),
        "python_version": platform.python_version(),
        "config": {
            "EQUIPO_IA": EQUIPO_IA,
            "IA_MAC": IA_MAC,
            "OLLAMA_PORT": OLLAMA_PORT,
            "WOL_BROADCAST": WOL_BROADCAST,
            "WOL_PORT": WOL_PORT
        }
    }

    # Test ping manualmente
    try:
        if os.name == 'nt':
            cmd = f"ping -n 1 -w 2000 {EQUIPO_IA}"
        else:
            cmd = f"ping -c 1 -W 2 {EQUIPO_IA}"

        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        debug_data["ping_test"] = {
            "command": cmd,
            "returncode": process.returncode,
            "stdout": stdout.decode().strip(),
            "stderr": stderr.decode().strip() if stderr else ""
        }
    except Exception as e:
        debug_data["ping_test"] = {
            "error": str(e)
        }

    return debug_data


@app.get("/test", response_model=StatusResponse, dependencies=[Security(verify_api_key)])
async def test_ia():
    """
    Verifica el estado del equipo de IA y si Ollama está respondiendo.
    Requiere API Key en header X-API-Key.
    """
    equipo_online = False
    ollama_online = False
    mensaje = ""

    # Verificar si el equipo está encendido (ping)
    try:
        if os.name == 'nt':  # Windows
            cmd = f"ping -n 1 -w 2000 {EQUIPO_IA}"
        else:  # Linux/Mac/Docker
            cmd = f"ping -c 1 -W 2 {EQUIPO_IA}"

        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()
        equipo_online = process.returncode == 0

        if not equipo_online:
            # Ping falló - proporcionar más información
            mensaje = f"Ping falló (código {process.returncode}). "
            if stderr:
                mensaje += f"Error: {stderr.decode().strip()[:100]}"
    except Exception as e:
        mensaje = f"Error al ejecutar ping: {str(e)}"

    # Verificar si Ollama está respondiendo
    if equipo_online:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"http://{EQUIPO_IA}:{OLLAMA_PORT}/api/tags")
                ollama_online = response.status_code == 200
                if ollama_online:
                    mensaje = "Equipo y Ollama funcionando correctamente"
                else:
                    mensaje = f"Equipo online pero Ollama respondió con código {response.status_code}"
        except httpx.ConnectError as e:
            mensaje = f"Equipo online pero no se puede conectar a Ollama: {str(e)}"
        except httpx.TimeoutException:
            mensaje = f"Equipo online pero Ollama no responde (timeout)"
        except Exception as e:
            mensaje = f"Equipo online pero error al verificar Ollama: {str(e)}"
    elif not mensaje:
        mensaje = "Equipo apagado o no accesible"

    return StatusResponse(
        equipo_online=equipo_online,
        ollama_online=ollama_online,
        mensaje=mensaje
    )


@app.post("/arrancar", response_model=MessageResponse, dependencies=[Security(verify_api_key)])
async def arrancar_equipo():
    """
    Envía un magic packet Wake-on-LAN para arrancar el equipo de IA.
    Requiere API Key en header X-API-Key.
    """
    try:
        # Enviar magic packet a la dirección de broadcast configurada
        send_magic_packet(IA_MAC, ip_address=WOL_BROADCAST, port=WOL_PORT)
        return MessageResponse(
            success=True,
            mensaje=f"Magic packet enviado a {IA_MAC} via {WOL_BROADCAST}:{WOL_PORT}. El equipo debería arrancar en breve."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al enviar magic packet: {str(e)}"
        )


@app.post("/apagar", response_model=MessageResponse, dependencies=[Security(verify_api_key)])
async def apagar_equipo():
    """
    Apaga el equipo de IA de manera incondicional via SSH.
    Requiere API Key en header X-API-Key.
    """
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        ssh.connect(
            hostname=EQUIPO_IA,
            port=SSH_PORT,
            username=SSH_USER,
            password=SSH_PASS,
            timeout=5
        )

        stdin, stdout, stderr = ssh.exec_command("sudo shutdown -h now")

        ssh.close()

        return MessageResponse(
            success=True,
            mensaje="Comando de apagado enviado correctamente. El equipo se apagará en breve."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al apagar equipo via SSH: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
