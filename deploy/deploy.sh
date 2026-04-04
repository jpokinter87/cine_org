#!/usr/bin/env bash
# deploy.sh — Mise à jour et redémarrage de CineOrg
# Usage : ./deploy/deploy.sh (depuis le serveur)
set -euo pipefail

# --- Configuration ---
PROJECT_DIR="/home/jp/PythonProject/cine_org"
SERVICE_NAME="cineorg"

# --- Couleurs ---
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}=== Déploiement CineOrg ===${NC}"

# 1. Mise à jour du code
echo -e "\n${GREEN}[1/4]${NC} Git pull..."
cd "$PROJECT_DIR"
git pull

# 2. Mise à jour des dépendances
echo -e "\n${GREEN}[2/4]${NC} Synchronisation des dépendances..."
uv sync

# 3. Redémarrage du service
echo -e "\n${GREEN}[3/4]${NC} Redémarrage du service..."
sudo systemctl restart "$SERVICE_NAME"

# 4. Résumé
echo -e "\n${GREEN}[4/4]${NC} Vérification..."
sleep 2
echo ""
echo "Commit actuel :"
git log --oneline -1
echo ""
sudo systemctl status "$SERVICE_NAME" --no-pager
echo -e "\n${GREEN}=== Déploiement terminé ===${NC}"
