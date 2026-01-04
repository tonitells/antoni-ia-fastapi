from fastapi import FastAPI, Security, HTTPException, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
import os
from dotenv import load_dotenv
import httpx
import asyncio
from wakeonlan import send_magic_packet
import paramiko
import socket

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
SSH_SUDO_PASS = os.getenv("SSH_SUDO_PASS", SSH_PASS)  # Por defecto usa el mismo que SSH
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


async def check_host_connectivity(host: str, port: int = 22, timeout: float = 2.0) -> bool:
    """
    Verifica si un host está online intentando conectarse a un puerto TCP.
    Por defecto usa el puerto SSH (22) que suele estar abierto.
    """
    try:
        # Ejecutar la conexión en un executor para no bloquear
        loop = asyncio.get_event_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)

        await loop.run_in_executor(None, sock.connect, (host, port))
        sock.close()
        return True
    except (socket.timeout, socket.error, OSError):
        return False
    finally:
        try:
            sock.close()
        except:
            pass


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
            "SSH_PORT": SSH_PORT,
            "SSH_USER": SSH_USER,
            "SSH_PASS_SET": bool(SSH_PASS),
            "SSH_SUDO_PASS_SET": bool(SSH_SUDO_PASS),
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

    # Verificar si el equipo está encendido (conexión TCP al puerto SSH)
    try:
        equipo_online = await check_host_connectivity(EQUIPO_IA, port=int(SSH_PORT), timeout=2.0)

        if not equipo_online:
            mensaje = f"Equipo no accesible en {EQUIPO_IA}:{SSH_PORT}"
    except Exception as e:
        mensaje = f"Error al verificar conectividad: {str(e)}"
        equipo_online = False

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
            mensaje = f"Equipo online pero no se puede conectar a Ollama en puerto {OLLAMA_PORT}"
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
    ssh = None
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

        # Intentar con sudo primero
        stdin, stdout, stderr = ssh.exec_command("sudo shutdown -h now", get_pty=True)

        # Si se requiere contraseña para sudo, enviarla
        if SSH_SUDO_PASS:
            stdin.write(SSH_SUDO_PASS + '\n')
            stdin.flush()

        # Esperar un momento para que el comando se procese
        exit_status = stdout.channel.recv_exit_status()
        error_output = stderr.read().decode('utf-8', errors='ignore').strip()
        std_output = stdout.read().decode('utf-8', errors='ignore').strip()

        ssh.close()

        # Si el comando con sudo falló, informar
        if exit_status != 0:
            # Intentar sin sudo como respaldo
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

                stdin, stdout, stderr = ssh.exec_command("shutdown -h now")
                exit_status2 = stdout.channel.recv_exit_status()

                ssh.close()

                if exit_status2 != 0:
                    error_msg = f"Error al ejecutar shutdown. Salida: {std_output}. Error: {error_output}"
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=error_msg
                    )
            except HTTPException:
                raise
            except Exception as e2:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Sudo falló y shutdown sin sudo también: {error_output}. {str(e2)}"
                )

        return MessageResponse(
            success=True,
            mensaje="Comando de apagado enviado correctamente. El equipo se apagará en breve."
        )
    except HTTPException:
        raise
    except paramiko.AuthenticationException:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Error de autenticación SSH. Verifica SSH_USER y SSH_PASS"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al apagar equipo via SSH: {str(e)}"
        )
    finally:
        if ssh:
            try:
                ssh.close()
            except:
                pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
