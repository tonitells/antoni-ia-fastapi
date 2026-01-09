from fastapi import FastAPI, Security, HTTPException, status
from fastapi.security import APIKeyHeader
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import os
from dotenv import load_dotenv
import httpx
import asyncio
from wakeonlan import send_magic_packet
import paramiko
import socket
import json
from datetime import datetime
from pathlib import Path

load_dotenv()

# Ruta al archivo de estado
STATUS_FILE = Path("status/status.json")
BASE_STATUS_FILE = Path("status/base.json")

app = FastAPI(
    title="Antoni IA API",
    description="API para gestión remota del equipo de IA con Ollama",
    version="1.0.0",
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


# ===== FUNCIONES DE GESTIÓN DE ESTADO =====


async def read_status() -> dict:
    """
    Lee el estado actual desde status.json y verifica el estado real del equipo.
    Actualiza logical_on y phisical_on si han cambiado.
    """
    try:
        # Leer el estado guardado
        if STATUS_FILE.exists():
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                current_status = json.load(f)
        else:
            # Si no existe, crear desde base.json
            if BASE_STATUS_FILE.exists():
                with open(BASE_STATUS_FILE, "r", encoding="utf-8") as f:
                    base_status = json.load(f)
                write_status(base_status)
                current_status = base_status
            else:
                # Si tampoco existe base.json, crear estado por defecto
                default_status = {
                    "logical_on": False,
                    "phisical_on": False,
                    "peticions_ollama": 0,
                    "permanent_on": False,
                    "message": "Equip desconnectat",
                    "datetime": datetime.utcnow().isoformat() + "Z",
                }
                write_status(default_status)
                current_status = default_status

        # Verificar el estado real del equipo
        equipo_online = False
        ollama_online = False
        mensaje = ""

        try:
            equipo_online = await check_host_connectivity(
                EQUIPO_IA, port=int(SSH_PORT), timeout=2.0
            )

            if not equipo_online:
                mensaje = f"Equip no accessible a {EQUIPO_IA}:{SSH_PORT}"
        except Exception as e:
            mensaje = f"Error en verificar connectivitat: {str(e)}"
            equipo_online = False

        # Verificar si Ollama está respondiendo
        if equipo_online:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(
                        f"http://{EQUIPO_IA}:{OLLAMA_PORT}/api/tags"
                    )
                    ollama_online = response.status_code == 200
                    if ollama_online:
                        mensaje = "Equip i Ollama funcionant correctament"
                    else:
                        mensaje = f"Equip online però Ollama ha respost amb codi {response.status_code}"
            except httpx.ConnectError as e:
                mensaje = f"Equip online però no es pot connectar a Ollama al port {OLLAMA_PORT} : {str(e)}"
            except httpx.TimeoutException:
                mensaje = "Equip online però Ollama no respon (timeout)"
            except Exception as e:
                mensaje = f"Equip online però error en verificar Ollama: {str(e)}"
        elif not mensaje:
            mensaje = "Equip apagat o no accessible"

        # Actualizar el estado si ha cambiado
        if (
            current_status.get("logical_on") != ollama_online
            or current_status.get("phisical_on") != equipo_online
        ):
            current_status["logical_on"] = ollama_online
            current_status["phisical_on"] = equipo_online
            current_status["message"] = f"Estat verificat: {mensaje}"
            write_status(current_status)

        return current_status

    except Exception as e:
        # En caso de error, retornar estado por defecto
        return {
            "logical_on": False,
            "phisical_on": False,
            "peticions_ollama": 0,
            "permanent_on": False,
            "message": f"Error llegint estat: {str(e)}",
            "datetime": datetime.utcnow().isoformat() + "Z",
        }


def write_status(status_data: dict):
    """Escribe el estado en status.json"""
    try:
        # Asegurar que el directorio existe
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)

        # Actualizar el timestamp
        status_data["datetime"] = datetime.utcnow().isoformat() + "Z"

        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(status_data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error writing status file: {e}")


async def update_status(updates: dict, message: str):
    """
    Actualiza campos específicos del estado y añade un mensaje.

    Args:
        updates: Diccionario con los campos a actualizar
        message: Mensaje descriptivo de la operación
    """
    status = await read_status()
    status.update(updates)
    status["message"] = message
    write_status(status)
    return status


async def verify_api_key(api_key: str = Security(API_KEY_HEADER)):
    if not api_key or api_key not in API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Key",
        )
    return api_key


async def check_host_connectivity(
    host: str, port: int = 22, timeout: float = 2.0
) -> bool:
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


class ModelInfo(BaseModel):
    name: str
    size: int = None
    modified_at: str = None


class ModelsResponse(BaseModel):
    success: bool
    mensaje: str
    models: list[ModelInfo] = []


# Modelos para proxy de Ollama
class OllamaGenerateRequest(BaseModel):
    model: str
    prompt: str
    stream: bool = Field(default=False)
    options: Optional[Dict[str, Any]] = None
    system: Optional[str] = None
    template: Optional[str] = None
    context: Optional[List[int]] = None
    raw: Optional[bool] = None


class OllamaChatMessage(BaseModel):
    role: str  # system, user, assistant
    content: str
    images: Optional[List[str]] = None


class OllamaChatRequest(BaseModel):
    model: str
    messages: List[OllamaChatMessage]
    stream: bool = Field(default=False)
    options: Optional[Dict[str, Any]] = None


class OllamaPullRequest(BaseModel):
    name: str  # nombre del modelo
    stream: bool = Field(default=True)


class OllamaDeleteRequest(BaseModel):
    name: str  # nombre del modelo a eliminar


class OllamaShowRequest(BaseModel):
    name: str  # nombre del modelo


@app.get("/")
async def root():
    return {"api": "Antoni IA API", "version": "1.0.0", "status": "running"}


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
            "WOL_PORT": WOL_PORT,
        },
    }

    # Test ping manualmente
    try:
        if os.name == "nt":
            cmd = f"ping -n 1 -w 2000 {EQUIPO_IA}"
        else:
            cmd = f"ping -c 1 -W 2 {EQUIPO_IA}"

        process = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        debug_data["ping_test"] = {
            "command": cmd,
            "returncode": process.returncode,
            "stdout": stdout.decode().strip(),
            "stderr": stderr.decode().strip() if stderr else "",
        }
    except Exception as e:
        debug_data["ping_test"] = {"error": str(e)}

    return debug_data


@app.get(
    "/test", response_model=StatusResponse, dependencies=[Security(verify_api_key)]
)
async def test_ia():
    """
    Verifica el estado del equipo de IA y si Ollama está respondiendo.
    Actualiza logical_on y phisical_on en el archivo de estado.
    Requiere API Key en header X-API-Key.
    """
    equipo_online = False
    ollama_online = False
    mensaje = ""

    # Verificar si el equipo está encendido (conexión TCP al puerto SSH)
    try:
        equipo_online = await check_host_connectivity(
            EQUIPO_IA, port=int(SSH_PORT), timeout=2.0
        )

        if not equipo_online:
            mensaje = f"Equip no accessible a {EQUIPO_IA}:{SSH_PORT}"
    except Exception as e:
        mensaje = f"Error en verificar connectivitat: {str(e)}"
        equipo_online = False

    # Verificar si Ollama está respondiendo
    if equipo_online:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"http://{EQUIPO_IA}:{OLLAMA_PORT}/api/tags"
                )
                ollama_online = response.status_code == 200
                if ollama_online:
                    mensaje = "Equip i Ollama funcionant correctament"
                else:
                    mensaje = f"Equip online però Ollama ha respost amb codi {response.status_code}"
        except httpx.ConnectError as e:
            mensaje = f"Equip online però no es pot connectar a Ollama al port {OLLAMA_PORT} : {str(e)}"
        except httpx.TimeoutException:
            mensaje = "Equip online però Ollama no respon (timeout)"
        except Exception as e:
            mensaje = f"Equip online però error en verificar Ollama: {str(e)}"
    elif not mensaje:
        mensaje = "Equip apagat o no accessible"

    # Actualizar el estado en el archivo status.json
    await update_status(
        updates={"logical_on": ollama_online, "phisical_on": equipo_online},
        message=f"Test: {mensaje}",
    )

    return StatusResponse(
        equipo_online=equipo_online, ollama_online=ollama_online, mensaje=mensaje
    )


@app.get(
    "/lista_modelos",
    response_model=ModelsResponse,
    dependencies=[Security(verify_api_key)],
)
async def lista_modelos():
    """
    Lista todos los modelos instalados en Ollama.
    Requiere API Key en header X-API-Key.
    """
    try:
        # Verificar si el equipo está encendido
        equipo_online = await check_host_connectivity(
            EQUIPO_IA, port=int(SSH_PORT), timeout=2.0
        )

        if not equipo_online:
            return ModelsResponse(
                success=False,
                mensaje=f"L'equip està apagat o no respon a {EQUIPO_IA}:{SSH_PORT}",
                models=[],
            )

        # Obtener lista de modelos desde Ollama
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"http://{EQUIPO_IA}:{OLLAMA_PORT}/api/tags")

            if response.status_code != 200:
                return ModelsResponse(
                    success=False,
                    mensaje=f"Ollama ha respost amb codi {response.status_code}",
                    models=[],
                )

            data = response.json()
            models = []

            # Parsear la respuesta de Ollama
            if "models" in data:
                for model in data["models"]:
                    models.append(
                        ModelInfo(
                            name=model.get("name", ""),
                            size=model.get("size"),
                            modified_at=model.get("modified_at"),
                        )
                    )

            return ModelsResponse(
                success=True,
                mensaje=f"S'han trobat {len(models)} model(s) instal·lat(s)",
                models=models,
            )

    except httpx.ConnectError:
        return ModelsResponse(
            success=False,
            mensaje=f"No es pot connectar a Ollama a {EQUIPO_IA}:{OLLAMA_PORT}",
            models=[],
        )
    except httpx.TimeoutException:
        return ModelsResponse(
            success=False, mensaje="Timeout en connectar amb Ollama", models=[]
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en obtenir llista de models: {str(e)}",
        )


@app.post(
    "/arrancar", response_model=MessageResponse, dependencies=[Security(verify_api_key)]
)
async def arrancar_equipo():
    """
    Envía un magic packet Wake-on-LAN para arrancar el equipo de IA.
    Incrementa el contador peticions_ollama.
    Primero verifica si el equipo ya está encendido.
    Requiere API Key en header X-API-Key.
    """
    try:
        # Leer el estado actual
        current_status = await read_status()

        # Verificar si el equipo ya está encendido
        equipo_online = await check_host_connectivity(
            EQUIPO_IA, port=int(SSH_PORT), timeout=2.0
        )

        # Incrementar contador de peticiones
        new_peticions = current_status.get("peticions_ollama", 0) + 1

        if equipo_online:
            # Actualizar estado: equipo ya online, incrementar contador
            await update_status(
                updates={"peticions_ollama": new_peticions, "phisical_on": True},
                message=f"Arrancar: Equip ja encès. Peticions: {new_peticions}",
            )

            return MessageResponse(
                success=True,
                mensaje=f"L'equip ja està encès i responent a {EQUIPO_IA}:{SSH_PORT}. Peticions Ollama: {new_peticions}",
            )

        # El equipo está apagado, enviar magic packet
        send_magic_packet(IA_MAC, ip_address=WOL_BROADCAST, port=WOL_PORT)

        # Actualizar estado: WOL enviado, incrementar contador
        await update_status(
            updates={"peticions_ollama": new_peticions},
            message=f"Arrancar: Magic packet enviat. Peticions: {new_peticions}",
        )

        return MessageResponse(
            success=True,
            mensaje=f"Magic packet enviat a {IA_MAC} via {WOL_BROADCAST}:{WOL_PORT}. Peticions Ollama: {new_peticions}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en intentar arrencar equip: {str(e)}",
        )


@app.post(
    "/apagar", response_model=MessageResponse, dependencies=[Security(verify_api_key)]
)
async def apagar_equipo():
    """
    Gestiona el apagado del equipo con sistema de contador de peticiones.
    - Decrementa el contador peticions_ollama
    - Solo apaga físicamente si peticions_ollama < 1
    - Respeta permanent_on: si está en true, no apaga físicamente aunque peticions_ollama < 1
    - Actualiza logical_on y phisical_on a false solo si se envía señal de apagado físico
    Requiere API Key en header X-API-Key.
    """
    ssh = None
    try:
        # Leer el estado actual
        current_status = await read_status()

        # Verificar si el equipo ya está apagado
        equipo_online = await check_host_connectivity(
            EQUIPO_IA, port=int(SSH_PORT), timeout=2.0
        )

        if not equipo_online:
            # Equipo ya apagado, decrementar contador (mínimo 0)
            new_peticions = max(0, current_status.get("peticions_ollama", 0) - 1)
            await update_status(
                updates={
                    "peticions_ollama": new_peticions,
                    "phisical_on": False,
                    "logical_on": False,
                },
                message=f"Apagar: Equip ja apagat. Peticions: {new_peticions}",
            )

            return MessageResponse(
                success=True,
                mensaje=f"L'equip ja està apagat. Peticions Ollama: {new_peticions}",
            )
        else:
            # Decrementar contador de peticiones (mínimo 0)
            new_peticions = max(0, current_status.get("peticions_ollama", 0) - 1)
        permanent_on = current_status.get("permanent_on", False)

        # Determinar si se debe apagar físicamente
        should_shutdown_physically = (new_peticions < 1) and (not permanent_on)

        if not should_shutdown_physically:
            # No apagar físicamente, solo actualizar contador
            reason = (
                "permanent_on activat"
                if permanent_on
                else f"hi ha {new_peticions} petició(ns) activa(es)"
            )
            await update_status(
                updates={"peticions_ollama": new_peticions},
                message=f"Apagar: No s'apaga físicament ({reason}). Peticions: {new_peticions}",
            )

            return MessageResponse(
                success=True,
                mensaje=f"Comptador decrementat a {new_peticions}. No s'apaga físicament: {reason}",
            )

        # Apagar físicamente el equipo
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        ssh.connect(
            hostname=EQUIPO_IA,
            port=SSH_PORT,
            username=SSH_USER,
            password=SSH_PASS,
            timeout=5,
        )

        # Ejecutar shutdown con sudo usando la contraseña desde SSH_SUDO_PASS
        # Usa sudo -S para leer la contraseña desde stdin
        shutdown_command = f'echo "{SSH_SUDO_PASS}" | sudo -S shutdown -h now'
        stdin, stdout, stderr = ssh.exec_command(shutdown_command)

        # Esperar un momento para que el comando se procese
        exit_status = stdout.channel.recv_exit_status()
        error_output = stderr.read().decode("utf-8", errors="ignore").strip()
        std_output = stdout.read().decode("utf-8", errors="ignore").strip()

        ssh.close()

        # Si el comando con sudo falló, intentar sin sudo como respaldo
        if exit_status != 0:
            try:
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(
                    hostname=EQUIPO_IA,
                    port=SSH_PORT,
                    username=SSH_USER,
                    password=SSH_PASS,
                    timeout=5,
                )

                stdin, stdout, stderr = ssh.exec_command("shutdown -h now")
                exit_status2 = stdout.channel.recv_exit_status()

                ssh.close()

                if exit_status2 != 0:
                    error_msg = f"Error en executar shutdown. Sortida: {std_output}. Error: {error_output}"
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=error_msg,
                    )
            except HTTPException:
                raise
            except Exception as e2:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Sudo ha fallat i shutdown sense sudo també: {error_output}. {str(e2)}",
                )

        # Actualizar estado: apagado físico enviado
        await update_status(
            updates={
                "peticions_ollama": new_peticions,
                "logical_on": False,
                "phisical_on": False,
            },
            message=f"Apagar: Apagat físic enviat. Peticions: {new_peticions}",
        )

        return MessageResponse(
            success=True,
            mensaje=f"Apagat físic enviat. Peticions: {new_peticions}. L'equip s'apagarà aviat.",
        )

    except HTTPException:
        raise
    except paramiko.AuthenticationException:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Error d'autenticació SSH. Verifica SSH_USER i SSH_PASS",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en apagar equip via SSH: {str(e)}",
        )
    finally:
        if ssh:
            try:
                ssh.close()
            except:
                pass


@app.post(
    "/permanent_on_enable",
    response_model=MessageResponse,
    dependencies=[Security(verify_api_key)],
)
async def permanent_on_enable():
    """
    Activa el modo permanent_on.
    Cuando está activado, el equipo NO se apagará físicamente aunque peticions_ollama sea < 1.
    Requiere API Key en header X-API-Key.
    """
    try:
        await update_status(
            updates={"permanent_on": True},
            message="Permanent_on activat: l'equip no s'apagarà automàticament",
        )

        return MessageResponse(
            success=True,
            mensaje="Mode permanent_on activat. L'equip no s'apagarà automàticament.",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en activar permanent_on: {str(e)}",
        )


@app.post(
    "/permanent_on_disable",
    response_model=MessageResponse,
    dependencies=[Security(verify_api_key)],
)
async def permanent_on_disable():
    """
    Desactiva el modo permanent_on.
    El equipo podrá apagarse automáticamente cuando peticions_ollama sea < 1.
    Requiere API Key en header X-API-Key.
    """
    try:
        await update_status(
            updates={"permanent_on": False},
            message="Permanent_on desactivat: l'equip es podrà apagar automàticament",
        )

        return MessageResponse(
            success=True,
            mensaje="Mode permanent_on desactivat. L'equip es podrà apagar automàticament.",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en desactivar permanent_on: {str(e)}",
        )


@app.get("/status", dependencies=[Security(verify_api_key)])
async def get_status():
    """
    Obtiene el estado actual del sistema desde status.json.
    Muestra logical_on, phisical_on, peticions_ollama, permanent_on, message y datetime.
    Requiere API Key en header X-API-Key.
    """

    try:
        current_status = await read_status()
        return current_status
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en llegir estat: {str(e)}",
        )


@app.post("/init", dependencies=[Security(verify_api_key)])
async def init_status():
    """
    Inicializa el estado del sistema verificando el estado real del equipo.
    - Verifica si el equipo está encendido (phisical_on)
    - Verifica si Ollama está respondiendo (logical_on)
    - Resetea peticions_ollama a 0
    - Resetea permanent_on a false
    Útil para sincronizar el estado después de un reinicio del servidor o cambios manuales.
    Requiere API Key en header X-API-Key.
    """
    try:
        equipo_online = False
        ollama_online = False
        mensaje = ""

        # Verificar si el equipo está encendido (conexión TCP al puerto SSH)
        try:
            equipo_online = await check_host_connectivity(
                EQUIPO_IA, port=int(SSH_PORT), timeout=2.0
            )

            if not equipo_online:
                mensaje = f"Equip no accessible a {EQUIPO_IA}:{SSH_PORT}"
        except Exception as e:
            mensaje = f"Error en verificar connectivitat: {str(e)}"
            equipo_online = False

        # Verificar si Ollama está respondiendo
        if equipo_online:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(
                        f"http://{EQUIPO_IA}:{OLLAMA_PORT}/api/tags"
                    )
                    ollama_online = response.status_code == 200
                    if ollama_online:
                        mensaje = "Init: Equip i Ollama funcionant correctament"
                    else:
                        mensaje = f"Init: Equip online però Ollama ha respost amb codi {response.status_code}"
            except httpx.ConnectError:
                mensaje = f"Init: Equip online però no es pot connectar a Ollama al port {OLLAMA_PORT}"
            except httpx.TimeoutException:
                mensaje = "Init: Equip online però Ollama no respon (timeout)"
            except Exception as e:
                mensaje = (
                    f"Init: Equip online però error en verificar Ollama: {str(e)}"
                )
        else:
            mensaje = "Init: Equip apagat o no accessible"

        # Inicializar el estado con valores reseteados
        new_status = await update_status(
            updates={
                "logical_on": ollama_online,
                "phisical_on": equipo_online,
                "peticions_ollama": 0,
                "permanent_on": False,
            },
            message=mensaje,
        )

        return {
            "success": True,
            "mensaje": f"Estat inicialitzat. {mensaje}",
            "status": new_status,
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en inicialitzar estat: {str(e)}",
        )


@app.post(
    "/shutdown", response_model=MessageResponse, dependencies=[Security(verify_api_key)]
)
async def shutdown_force():
    """
    Apagado forzado del equipo.
    Resetea el estado completo: permanent_on=false, logical_on=false, phisical_on=false, peticions_ollama=0
    y envía comando de apagado físico via SSH.
    Requiere API Key en header X-API-Key.
    """
    ssh = None
    try:
        # Verificar si el equipo está online
        equipo_online = await check_host_connectivity(
            EQUIPO_IA, port=int(SSH_PORT), timeout=2.0
        )

        if not equipo_online:
            # Equipo ya apagado, solo resetear estado
            await update_status(
                updates={
                    "permanent_on": False,
                    "logical_on": False,
                    "phisical_on": False,
                    "peticions_ollama": 0,
                },
                message="Shutdown forçat: Equip ja estava apagat, estat resetejat",
            )

            return MessageResponse(
                success=True,
                mensaje="L'equip ja està apagat. Estat resetejat completament.",
            )

        # Equipo está encendido, proceder con apagado forzado
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        ssh.connect(
            hostname=EQUIPO_IA,
            port=SSH_PORT,
            username=SSH_USER,
            password=SSH_PASS,
            timeout=5,
        )

        # Ejecutar shutdown con sudo
        shutdown_command = f'echo "{SSH_SUDO_PASS}" | sudo -S shutdown -h now'
        stdin, stdout, stderr = ssh.exec_command(shutdown_command)

        exit_status = stdout.channel.recv_exit_status()
        error_output = stderr.read().decode("utf-8", errors="ignore").strip()
        std_output = stdout.read().decode("utf-8", errors="ignore").strip()

        ssh.close()

        # Si el comando con sudo falló, intentar sin sudo
        if exit_status != 0:
            try:
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(
                    hostname=EQUIPO_IA,
                    port=SSH_PORT,
                    username=SSH_USER,
                    password=SSH_PASS,
                    timeout=5,
                )

                stdin, stdout, stderr = ssh.exec_command("shutdown -h now")
                exit_status2 = stdout.channel.recv_exit_status()

                ssh.close()

                if exit_status2 != 0:
                    error_msg = f"Error en executar shutdown. Sortida: {std_output}. Error: {error_output}"
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=error_msg,
                    )
            except HTTPException:
                raise
            except Exception as e2:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Sudo ha fallat i shutdown sense sudo també: {error_output}. {str(e2)}",
                )

        # Actualizar estado: todo reseteado
        await update_status(
            updates={
                "permanent_on": False,
                "logical_on": False,
                "phisical_on": False,
                "peticions_ollama": 0,
            },
            message="Shutdown forçat: Apagat físic enviat, estat completament resetejat",
        )

        return MessageResponse(
            success=True,
            mensaje="Apagat forçat enviat. Estat completament resetejat. L'equip s'apagarà aviat.",
        )

    except HTTPException:
        raise
    except paramiko.AuthenticationException:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Error d'autenticació SSH. Verifica SSH_USER i SSH_PASS",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en executar shutdown forçat: {str(e)}",
        )
    finally:
        if ssh:
            try:
                ssh.close()
            except:
                pass


# ===== ENDPOINTS DE PROXY A OLLAMA =====


@app.post("/ollama/generate", dependencies=[Security(verify_api_key)])
async def ollama_generate(request: OllamaGenerateRequest):
    """
    Proxy para generar texto con Ollama.
    Soporta tanto streaming como respuestas completas.
    Requiere API Key en header X-API-Key.
    """
    try:
        # Verificar que el equipo esté online
        equipo_online = await check_host_connectivity(
            EQUIPO_IA, port=int(SSH_PORT), timeout=2.0
        )
        if not equipo_online:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"L'equip d'IA està apagat o no respon a {EQUIPO_IA}:{SSH_PORT}",
            )

        url = f"http://{EQUIPO_IA}:{OLLAMA_PORT}/api/generate"

        async with httpx.AsyncClient(timeout=300.0) as client:
            if request.stream:
                # Streaming response
                async def stream_generator():
                    async with client.stream(
                        "POST", url, json=request.model_dump()
                    ) as response:
                        if response.status_code != 200:
                            error_text = await response.aread()
                            raise HTTPException(
                                status_code=response.status_code,
                                detail=f"Error d'Ollama: {error_text.decode()}",
                            )
                        async for chunk in response.aiter_bytes():
                            yield chunk

                return StreamingResponse(
                    stream_generator(), media_type="application/x-ndjson"
                )
            else:
                # Non-streaming response
                response = await client.post(url, json=request.model_dump())
                if response.status_code != 200:
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=f"Error d'Ollama: {response.text}",
                    )
                return response.json()

    except httpx.ConnectError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No es pot connectar a Ollama a {EQUIPO_IA}:{OLLAMA_PORT}",
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Timeout en connectar amb Ollama",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en proxy generate: {str(e)}",
        )


@app.post("/ollama/chat", dependencies=[Security(verify_api_key)])
async def ollama_chat(request: OllamaChatRequest):
    """
    Proxy para chat con Ollama.
    Soporta tanto streaming como respuestas completas.
    Requiere API Key en header X-API-Key.
    """
    try:
        # Verificar que el equipo esté online
        equipo_online = await check_host_connectivity(
            EQUIPO_IA, port=int(SSH_PORT), timeout=2.0
        )
        if not equipo_online:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"L'equip d'IA està apagat o no respon a {EQUIPO_IA}:{SSH_PORT}",
            )

        url = f"http://{EQUIPO_IA}:{OLLAMA_PORT}/api/chat"

        async with httpx.AsyncClient(timeout=300.0) as client:
            if request.stream:
                # Streaming response
                async def stream_generator():
                    async with client.stream(
                        "POST", url, json=request.model_dump()
                    ) as response:
                        if response.status_code != 200:
                            error_text = await response.aread()
                            raise HTTPException(
                                status_code=response.status_code,
                                detail=f"Error d'Ollama: {error_text.decode()}",
                            )
                        async for chunk in response.aiter_bytes():
                            yield chunk

                return StreamingResponse(
                    stream_generator(), media_type="application/x-ndjson"
                )
            else:
                # Non-streaming response
                response = await client.post(url, json=request.model_dump())
                if response.status_code != 200:
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=f"Error d'Ollama: {response.text}",
                    )
                return response.json()

    except httpx.ConnectError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No es pot connectar a Ollama a {EQUIPO_IA}:{OLLAMA_PORT}",
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Timeout en connectar amb Ollama",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en proxy chat: {str(e)}",
        )


@app.post("/ollama/pull", dependencies=[Security(verify_api_key)])
async def ollama_pull(request: OllamaPullRequest):
    """
    Proxy para descargar modelos en Ollama.
    Por defecto usa streaming para mostrar progreso.
    Requiere API Key en header X-API-Key.
    """
    try:
        # Verificar que el equipo esté online
        equipo_online = await check_host_connectivity(
            EQUIPO_IA, port=int(SSH_PORT), timeout=2.0
        )
        if not equipo_online:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"L'equip d'IA està apagat o no respon a {EQUIPO_IA}:{SSH_PORT}",
            )

        url = f"http://{EQUIPO_IA}:{OLLAMA_PORT}/api/pull"

        async with httpx.AsyncClient(
            timeout=3600.0
        ) as client:  # 1 hora timeout para pulls grandes
            if request.stream:
                # Streaming response para ver progreso
                async def stream_generator():
                    async with client.stream(
                        "POST", url, json=request.model_dump()
                    ) as response:
                        if response.status_code != 200:
                            error_text = await response.aread()
                            raise HTTPException(
                                status_code=response.status_code,
                                detail=f"Error d'Ollama: {error_text.decode()}",
                            )
                        async for chunk in response.aiter_bytes():
                            yield chunk

                return StreamingResponse(
                    stream_generator(), media_type="application/x-ndjson"
                )
            else:
                # Non-streaming response
                response = await client.post(url, json=request.model_dump())
                if response.status_code != 200:
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=f"Error d'Ollama: {response.text}",
                    )
                return response.json()

    except httpx.ConnectError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No es pot connectar a Ollama a {EQUIPO_IA}:{OLLAMA_PORT}",
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Timeout en descarregar model (pot ser que sigui molt gran)",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en proxy pull: {str(e)}",
        )


@app.post("/ollama/delete", dependencies=[Security(verify_api_key)])
async def ollama_delete(request: OllamaDeleteRequest):
    """
    Proxy para eliminar modelos de Ollama.
    Requiere API Key en header X-API-Key.
    """
    try:
        # Verificar que el equipo esté online
        equipo_online = await check_host_connectivity(
            EQUIPO_IA, port=int(SSH_PORT), timeout=2.0
        )
        if not equipo_online:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"L'equip d'IA està apagat o no respon a {EQUIPO_IA}:{SSH_PORT}",
            )

        url = f"http://{EQUIPO_IA}:{OLLAMA_PORT}/api/delete"

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.delete(url, json=request.model_dump())

            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Error d'Ollama: {response.text}",
                )

            return {
                "success": True,
                "mensaje": f"Model '{request.name}' eliminat correctament",
            }

    except httpx.ConnectError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No es pot connectar a Ollama a {EQUIPO_IA}:{OLLAMA_PORT}",
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Timeout en eliminar model",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en proxy delete: {str(e)}",
        )


@app.post("/ollama/show", dependencies=[Security(verify_api_key)])
async def ollama_show(request: OllamaShowRequest):
    """
    Proxy para obtener información detallada de un modelo en Ollama.
    Requiere API Key en header X-API-Key.
    """
    try:
        # Verificar que el equipo esté online
        equipo_online = await check_host_connectivity(
            EQUIPO_IA, port=int(SSH_PORT), timeout=2.0
        )
        if not equipo_online:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"L'equip d'IA està apagat o no respon a {EQUIPO_IA}:{SSH_PORT}",
            )

        url = f"http://{EQUIPO_IA}:{OLLAMA_PORT}/api/show"

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=request.model_dump())

            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Error d'Ollama: {response.text}",
                )

            return response.json()

    except httpx.ConnectError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No es pot connectar a Ollama a {EQUIPO_IA}:{OLLAMA_PORT}",
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Timeout en obtenir informació del model",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en proxy show: {str(e)}",
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
