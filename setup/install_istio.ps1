# DARWIN - Istio Installation Script
# Run this AFTER minikube is started

Write-Host "=== Installing Istio Service Mesh ===" -ForegroundColor Cyan
Write-Host ""

# Check if minikube is running
Write-Host "Checking minikube status..." -NoNewline
$minikubeStatus = minikube status 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host " ✗ Minikube is not running!" -ForegroundColor Red
    Write-Host "Please start minikube first: minikube start --cpus=4 --memory=8192" -ForegroundColor Yellow
    exit 1
}
Write-Host " ✓" -ForegroundColor Green

# Check if istioctl is available
$istioctl = Get-Command istioctl -ErrorAction SilentlyContinue
if (-Not $istioctl) {
    Write-Host "Downloading Istio..." -ForegroundColor Yellow

    # Download Istio
    $installDir = "$env:USERPROFILE\darwin-tools"
    if (-Not (Test-Path $installDir)) {
        New-Item -ItemType Directory -Force -Path $installDir | Out-Null
    }

    cd $installDir
    $istioUrl = "https://github.com/istio/istio/releases/download/1.20.0/istio-1.20.0-win.zip"
    $istioZip = "$installDir\istio.zip"

    Invoke-WebRequest -Uri $istioUrl -OutFile $istioZip -UseBasicParsing
    Expand-Archive -Path $istioZip -DestinationPath $installDir -Force
    Remove-Item $istioZip -Force

    # Add to PATH
    $istioBin = "$installDir\istio-1.20.0\bin"
    $env:Path = "$istioBin;$env:Path"

    Write-Host "✓ Istio downloaded" -ForegroundColor Green
}

# Install Istio with demo profile
Write-Host "Installing Istio to Kubernetes..." -ForegroundColor Yellow
istioctl install --set profile=demo -y

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Istio installed successfully" -ForegroundColor Green
} else {
    Write-Host "✗ Istio installation failed" -ForegroundColor Red
    exit 1
}

# Create darwin namespace with Istio injection enabled
Write-Host "Creating darwin namespace..." -ForegroundColor Yellow
kubectl create namespace darwin --dry-run=client -o yaml | kubectl apply -f -
kubectl label namespace darwin istio-injection=enabled --overwrite

Write-Host "✓ Namespace 'darwin' created with Istio sidecar injection" -ForegroundColor Green

# Create honeypot namespace
Write-Host "Creating darwin-honeypot namespace..." -ForegroundColor Yellow
kubectl create namespace darwin-honeypot --dry-run=client -o yaml | kubectl apply -f -
kubectl label namespace darwin-honeypot istio-injection=enabled --overwrite

Write-Host "✓ Namespace 'darwin-honeypot' created" -ForegroundColor Green

# Verify installation
Write-Host ""
Write-Host "Verifying Istio installation..." -ForegroundColor Yellow
kubectl get pods -n istio-system

Write-Host ""
Write-Host "=== Istio Installation Complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Istio components:"
Write-Host "- Control Plane: istiod"
Write-Host "- Ingress Gateway: istio-ingressgateway"
Write-Host "- Egress Gateway: istio-egressgateway"
Write-Host ""
Write-Host "Namespaces created:"
Write-Host "- darwin (with sidecar injection)"
Write-Host "- darwin-honeypot (with sidecar injection)"
Write-Host ""
Write-Host "Next step: .\setup\install_databases.ps1" -ForegroundColor Cyan
