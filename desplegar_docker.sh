#!/bin/bash

# Script para desplegar antoni-ia-fastapi con Traefik
# Actualiza el repositorio y reconstruye el contenedor

set -e  # Salir si hay algún error

echo "=========================================="
echo "  Desplegando Antoni IA FastAPI"
echo "=========================================="
echo ""

# Colores para output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Directorio del script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo -e "${YELLOW}[1/5]${NC} Actualizando repositorio..."
if git pull origin main; then
    echo -e "${GREEN}✓${NC} Repositorio actualizado"
else
    echo -e "${RED}✗${NC} Error al actualizar repositorio"
    exit 1
fi
echo ""

echo -e "${YELLOW}[2/5]${NC} Verificando red proxy..."
if ! docker network ls | grep -q "proxy"; then
    echo "  → Creando red proxy..."
    docker network create proxy
    echo -e "${GREEN}✓${NC} Red proxy creada"
else
    echo -e "${GREEN}✓${NC} Red proxy existe"
fi
echo ""

echo -e "${YELLOW}[3/5]${NC} Verificando red macvlan_local..."
if ! docker network ls | grep -q "macvlan_local"; then
    echo -e "${RED}✗${NC} Red macvlan_local no existe"
    echo "  Ejecuta el siguiente comando para crearla:"
    echo ""
    echo "  docker network create -d macvlan \\"
    echo "    --subnet=192.168.1.0/24 \\"
    echo "    --gateway=192.168.1.1 \\"
    echo "    --ip-range=192.168.1.240/28 \\"
    echo "    --aux-address=\"host=192.168.1.230\" \\"
    echo "    -o parent=enp45s0 \\"
    echo "    macvlan_local"
    echo ""
    exit 1
else
    echo -e "${GREEN}✓${NC} Red macvlan_local existe"
fi
echo ""

echo -e "${YELLOW}[4/5]${NC} Deteniendo contenedor anterior (si existe)..."
if docker ps -a | grep -q "antoni-ia-api"; then
    docker-compose -f docker-compose.yml -f docker-compose.traefik.yml down
    echo -e "${GREEN}✓${NC} Contenedor detenido"
else
    echo "  → No hay contenedor anterior"
fi
echo ""

echo -e "${YELLOW}[5/5]${NC} Construyendo y levantando contenedor con Traefik..."
docker-compose -f docker-compose.yml -f docker-compose.traefik.yml up -d --build
echo -e "${GREEN}✓${NC} Contenedor levantado"
echo ""

echo "=========================================="
echo -e "${GREEN}  ✓ Despliegue completado${NC}"
echo "=========================================="
echo ""
echo "Estado del contenedor:"
docker ps | grep antoni-ia-api || echo "  Contenedor no encontrado"
echo ""
echo "Para ver los logs en tiempo real:"
echo "  docker-compose logs -f"
echo ""
echo "Para verificar el servicio:"
echo "  curl https://fastapi.tonitells.ddns.net/"
echo ""
