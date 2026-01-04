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
            response = await asyncio.create_subprocess_shell(
                f"ping -n 1 -w 1000 {EQUIPO_IA}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
        else:  # Linux/Mac
            response = await asyncio.create_subprocess_shell(
                f"ping -c 1 -W 1 {EQUIPO_IA}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

        await response.communicate()
        equipo_online = response.returncode == 0
    except Exception as e:
        mensaje = f"Error al verificar equipo: {str(e)}"

    # Verificar si Ollama está respondiendo
    if equipo_online:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(f"http://{EQUIPO_IA}:{OLLAMA_PORT}/api/tags")
                ollama_online = response.status_code == 200
                mensaje = "Equipo y Ollama funcionando correctamente"
        except Exception as e:
            mensaje = f"Equipo online pero Ollama no responde: {str(e)}"
    else:
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
        send_magic_packet(IA_MAC)
        return MessageResponse(
            success=True,
            mensaje=f"Magic packet enviado a {IA_MAC}. El equipo debería arrancar en breve."
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
