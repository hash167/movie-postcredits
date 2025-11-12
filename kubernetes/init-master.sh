#!/bin/bash

# Initialize Kubernetes Master Node
# Run this ONLY on the master node AFTER running setup-k8s-node.sh
# Usage: sudo bash init-master.sh <MASTER_IP>

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Please run as root (use sudo)${NC}"
    exit 1
fi

if [ -z "$1" ]; then
    echo -e "${RED}Error: Master IP address required${NC}"
    echo "Usage: sudo bash init-master.sh <MASTER_IP>"
    echo "Example: sudo bash init-master.sh 192.168.1.10"
    exit 1
fi

MASTER_IP=$1

echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}Initializing Kubernetes Master${NC}"
echo -e "${GREEN}======================================${NC}"
echo -e "Master IP: ${YELLOW}$MASTER_IP${NC}"
echo ""

# Set hostname
hostnamectl set-hostname k8s-master
echo "✓ Hostname set to k8s-master"

echo -e "\n${YELLOW}Initializing cluster (this may take 2-5 minutes)...${NC}"
kubeadm init --pod-network-cidr=10.244.0.0/16 --apiserver-advertise-address=$MASTER_IP

echo -e "\n${YELLOW}Configuring kubectl...${NC}"
mkdir -p $HOME/.kube
cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
chown $(id -u):$(id -g) $HOME/.kube/config
echo "✓ kubectl configured"

echo -e "\n${YELLOW}Installing Flannel network plugin...${NC}"
kubectl apply -f https://github.com/flannel-io/flannel/releases/latest/download/kube-flannel.yml
echo "✓ Flannel installed"

echo -e "\n${GREEN}======================================${NC}"
echo -e "${GREEN}Master node initialized!${NC}"
echo -e "${GREEN}======================================${NC}"
echo ""
echo -e "${YELLOW}Waiting for node to be ready...${NC}"
sleep 10

# Wait for node to be ready
for i in {1..30}; do
    if kubectl get nodes | grep -q "Ready"; then
        echo -e "${GREEN}✓ Master node is Ready!${NC}"
        break
    fi
    echo "  Waiting... ($i/30)"
    sleep 5
done

echo ""
echo -e "${YELLOW}Cluster status:${NC}"
kubectl get nodes
echo ""

echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}Next Steps:${NC}"
echo -e "${GREEN}======================================${NC}"
echo ""
echo -e "1. ${YELLOW}Get the join command for worker nodes:${NC}"
echo -e "   ${GREEN}kubeadm token create --print-join-command${NC}"
echo ""
echo -e "2. ${YELLOW}On worker node, run the join command shown above${NC}"
echo ""
echo -e "3. ${YELLOW}Verify cluster:${NC}"
echo -e "   ${GREEN}kubectl get nodes${NC}"
echo ""
echo -e "4. ${YELLOW}Deploy your application:${NC}"
echo -e "   ${GREEN}kubectl apply -f kubernetes/${NC}"
echo ""

# Save join command for easy access
echo "#!/bin/bash" > /root/join-command.sh
kubeadm token create --print-join-command >> /root/join-command.sh
chmod +x /root/join-command.sh
echo -e "${YELLOW}Join command saved to: /root/join-command.sh${NC}"
echo ""

