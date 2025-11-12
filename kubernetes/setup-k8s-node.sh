#!/bin/bash

# Kubernetes Node Setup Script
# Run this on BOTH master and worker nodes
# Usage: sudo bash setup-k8s-node.sh

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}Kubernetes Node Setup Script${NC}"
echo -e "${GREEN}======================================${NC}"

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Please run as root (use sudo)${NC}"
    exit 1
fi

echo -e "\n${YELLOW}Step 1: Updating system...${NC}"
apt update && apt upgrade -y

echo -e "\n${YELLOW}Step 2: Disabling swap...${NC}"
swapoff -a
sed -i '/ swap / s/^/#/' /etc/fstab
echo "✓ Swap disabled"

echo -e "\n${YELLOW}Step 3: Loading kernel modules...${NC}"
cat <<EOF | tee /etc/modules-load.d/k8s.conf
overlay
br_netfilter
EOF

modprobe overlay
modprobe br_netfilter
echo "✓ Kernel modules loaded"

echo -e "\n${YELLOW}Step 4: Configuring sysctl...${NC}"
cat <<EOF | tee /etc/sysctl.d/k8s.conf
net.bridge.bridge-nf-call-iptables  = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward                 = 1
EOF

sysctl --system
echo "✓ Sysctl configured"

echo -e "\n${YELLOW}Step 5: Installing containerd...${NC}"
apt install -y apt-transport-https ca-certificates curl software-properties-common

# Add Docker repository
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

apt update
apt install -y containerd.io

# Configure containerd
mkdir -p /etc/containerd
containerd config default | tee /etc/containerd/config.toml

# Enable SystemdCgroup
sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml

systemctl restart containerd
systemctl enable containerd
echo "✓ Containerd installed and configured"

echo -e "\n${YELLOW}Step 6: Installing Kubernetes components...${NC}"

# Add Kubernetes repository
mkdir -p /etc/apt/keyrings
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.28/deb/Release.key | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.28/deb/ /' | tee /etc/apt/sources.list.d/kubernetes.list

apt update
apt install -y kubelet kubeadm kubectl
apt-mark hold kubelet kubeadm kubectl

systemctl enable kubelet
echo "✓ Kubernetes components installed"

echo -e "\n${GREEN}======================================${NC}"
echo -e "${GREEN}Node preparation complete!${NC}"
echo -e "${GREEN}======================================${NC}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo ""
echo -e "  ${GREEN}On MASTER node:${NC}"
echo -e "    1. Set hostname: sudo hostnamectl set-hostname k8s-master"
echo -e "    2. Initialize cluster: sudo kubeadm init --pod-network-cidr=10.244.0.0/16 --apiserver-advertise-address=<MASTER_IP>"
echo -e "    3. Configure kubectl (see output)"
echo -e "    4. Install network plugin (Flannel or Calico)"
echo ""
echo -e "  ${GREEN}On WORKER node:${NC}"
echo -e "    1. Set hostname: sudo hostnamectl set-hostname k8s-worker1"
echo -e "    2. Run the 'kubeadm join' command from master output"
echo ""
echo -e "  ${YELLOW}Don't forget to update /etc/hosts on both nodes!${NC}"
echo ""

