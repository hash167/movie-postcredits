#!/bin/bash

# Reset/Remove Kubernetes Installation
# Run this script on ANY node (master or worker) to clean up Kubernetes
# Usage: sudo bash reset-k8s.sh

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${RED}======================================${NC}"
echo -e "${RED}Kubernetes Cleanup Script${NC}"
echo -e "${RED}======================================${NC}"
echo ""
echo -e "${YELLOW}⚠️  WARNING: This will completely remove Kubernetes from this node!${NC}"
echo ""
read -p "Are you sure you want to continue? (type 'yes' to confirm): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo -e "${GREEN}Aborted.${NC}"
    exit 0
fi

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Please run as root (use sudo)${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}Step 1: Draining node (if part of cluster)...${NC}"
if command -v kubectl &> /dev/null; then
    HOSTNAME=$(hostname)
    kubectl drain $HOSTNAME --delete-emptydir-data --force --ignore-daemonsets 2>/dev/null || true
    kubectl delete node $HOSTNAME 2>/dev/null || true
    echo "✓ Node drained (if it was part of a cluster)"
else
    echo "✓ kubectl not found, skipping drain"
fi

echo -e "\n${YELLOW}Step 2: Resetting kubeadm...${NC}"
if command -v kubeadm &> /dev/null; then
    kubeadm reset -f
    echo "✓ kubeadm reset complete"
else
    echo "✓ kubeadm not found, skipping"
fi

echo -e "\n${YELLOW}Step 3: Stopping Kubernetes services...${NC}"
systemctl stop kubelet 2>/dev/null || true
systemctl stop containerd 2>/dev/null || true
echo "✓ Services stopped"

echo -e "\n${YELLOW}Step 4: Removing Kubernetes packages...${NC}"
apt-mark unhold kubelet kubeadm kubectl 2>/dev/null || true
apt-get remove -y kubelet kubeadm kubectl 2>/dev/null || true
apt-get purge -y kubelet kubeadm kubectl 2>/dev/null || true
echo "✓ Kubernetes packages removed"

echo -e "\n${YELLOW}Step 5: Removing containerd (optional - keeping by default)...${NC}"
read -p "Remove containerd too? This will affect Docker. (y/N): " REMOVE_CONTAINERD
if [ "$REMOVE_CONTAINERD" = "y" ] || [ "$REMOVE_CONTAINERD" = "Y" ]; then
    apt-get remove -y containerd.io 2>/dev/null || true
    apt-get purge -y containerd.io 2>/dev/null || true
    rm -rf /etc/containerd
    echo "✓ Containerd removed"
else
    echo "✓ Containerd kept (use 'sudo apt remove containerd.io' to remove manually)"
fi

echo -e "\n${YELLOW}Step 6: Cleaning up directories and files...${NC}"
rm -rf /etc/kubernetes
rm -rf /var/lib/kubelet
rm -rf /var/lib/etcd
rm -rf /etc/cni/net.d
rm -rf /opt/cni/bin
rm -rf $HOME/.kube
rm -rf /var/lib/containerd
rm -rf /run/kubernetes
rm -rf /var/log/pods
rm -rf /var/log/containers
echo "✓ Directories cleaned"

echo -e "\n${YELLOW}Step 7: Removing iptables rules...${NC}"
iptables -F && iptables -t nat -F && iptables -t mangle -F && iptables -X
echo "✓ iptables rules flushed"

echo -e "\n${YELLOW}Step 8: Removing network interfaces...${NC}"
ip link delete cni0 2>/dev/null || true
ip link delete flannel.1 2>/dev/null || true
ip link delete kube-bridge 2>/dev/null || true
echo "✓ Network interfaces removed"

echo -e "\n${YELLOW}Step 9: Removing configuration files...${NC}"
rm -f /etc/apt/sources.list.d/kubernetes.list
rm -f /etc/apt/sources.list.d/docker.list
rm -f /etc/apt/keyrings/kubernetes-apt-keyring.gpg
rm -f /etc/systemd/system/kubelet.service.d/10-kubeadm.conf
rm -rf /etc/systemd/system/kubelet.service.d
echo "✓ Configuration files removed"

echo -e "\n${YELLOW}Step 10: Reloading systemd...${NC}"
systemctl daemon-reload
systemctl reset-failed
echo "✓ Systemd reloaded"

echo -e "\n${YELLOW}Step 11: Cleaning apt cache...${NC}"
apt-get autoremove -y
apt-get autoclean
echo "✓ Apt cache cleaned"

echo ""
echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}Cleanup Complete!${NC}"
echo -e "${GREEN}======================================${NC}"
echo ""
echo -e "${YELLOW}Summary:${NC}"
echo "  ✓ Kubernetes cluster left (if was member)"
echo "  ✓ kubeadm reset performed"
echo "  ✓ Kubernetes packages removed"
echo "  ✓ Directories cleaned"
echo "  ✓ Network interfaces removed"
echo "  ✓ Configuration files deleted"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "  1. Reboot recommended: ${GREEN}sudo reboot${NC}"
echo "  2. After reboot, you can reinstall K8s: ${GREEN}bash kubernetes/setup-k8s-node.sh${NC}"
echo ""
echo -e "${YELLOW}Note: Containerd was preserved. To remove it manually:${NC}"
echo "  ${GREEN}sudo apt-get remove -y containerd.io${NC}"
echo ""

