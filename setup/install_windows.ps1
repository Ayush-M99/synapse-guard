# DARWIN Project - Windows Installation Script
# Run this in PowerShell as Administrator

Write-Host "=== DARWIN Setup for Windows ===" -ForegroundColor Cyan
Write-Host ""

# Create installation directory
$installDir = "$env:USERPROFILE\darwin-tools"
New-Item -ItemType Directory -Force -Path $installDir | Out-Null
$env:Path += ";$installDir"

# 1. Install Minikube
Write-Host "Installing Minikube..." -ForegroundColor Yellow
$minikubeUrl = "https://storage.googleapis.com/minikube/releases/latest/minikube-windows-amd64.exe"
$minikubePath = "$installDir\minikube.exe"
if (-Not (Test-Path $minikubePath)) {
    Invoke-WebRequest -Uri $minikubeUrl -OutFile $minikubePath -UseBasicParsing
    Write-Host "✓ Minikube installed" -ForegroundColor Green
} else {
    Write-Host "✓ Minikube already exists" -ForegroundColor Green
}

# 2. Install Kubectl
Write-Host "Installing Kubectl..." -ForegroundColor Yellow
$kubectlUrl = "https://dl.k8s.io/release/v1.28.0/bin/windows/amd64/kubectl.exe"
$kubectlPath = "$installDir\kubectl.exe"
if (-Not (Test-Path $kubectlPath)) {
    Invoke-WebRequest -Uri $kubectlUrl -OutFile $kubectlPath -UseBasicParsing
    Write-Host "✓ Kubectl installed" -ForegroundColor Green
} else {
    Write-Host "✓ Kubectl already exists" -ForegroundColor Green
}

# 3. Install Helm
Write-Host "Installing Helm..." -ForegroundColor Yellow
$helmUrl = "https://get.helm.sh/helm-v3.13.0-windows-amd64.zip"
$helmZip = "$installDir\helm.zip"
if (-Not (Test-Path "$installDir\helm.exe")) {
    Invoke-WebRequest -Uri $helmUrl -OutFile $helmZip -UseBasicParsing
    Expand-Archive -Path $helmZip -DestinationPath $installDir -Force
    Move-Item "$installDir\windows-amd64\helm.exe" "$installDir\helm.exe" -Force
    Remove-Item "$installDir\windows-amd64" -Recurse -Force
    Remove-Item $helmZip -Force
    Write-Host "✓ Helm installed" -ForegroundColor Green
} else {
    Write-Host "✓ Helm already exists" -ForegroundColor Green
}

# 4. Install Go (requires download and manual install)
Write-Host "Checking Go installation..." -ForegroundColor Yellow
$goVersion = go version 2>$null
if (-Not $goVersion) {
    Write-Host "Go not found. Downloading Go 1.22..." -ForegroundColor Yellow
    $goUrl = "https://go.dev/dl/go1.22.0.windows-amd64.msi"
    $goInstaller = "$installDir\go-installer.msi"
    Invoke-WebRequest -Uri $goUrl -OutFile $goInstaller -UseBasicParsing
    Write-Host "Go installer downloaded to: $goInstaller" -ForegroundColor Cyan
    Write-Host "Please run the installer manually, then restart PowerShell." -ForegroundColor Yellow
} else {
    Write-Host "✓ Go already installed: $goVersion" -ForegroundColor Green
}

# 5. Install Node.js (requires download and manual install)
Write-Host "Checking Node.js installation..." -ForegroundColor Yellow
$nodeVersion = node --version 2>$null
if (-Not $nodeVersion) {
    Write-Host "Node.js not found. Downloading Node.js 20 LTS..." -ForegroundColor Yellow
    $nodeUrl = "https://nodejs.org/dist/v20.11.0/node-v20.11.0-x64.msi"
    $nodeInstaller = "$installDir\node-installer.msi"
    Invoke-WebRequest -Uri $nodeUrl -OutFile $nodeInstaller -UseBasicParsing
    Write-Host "Node.js installer downloaded to: $nodeInstaller" -ForegroundColor Cyan
    Write-Host "Please run the installer manually, then restart PowerShell." -ForegroundColor Yellow
} else {
    Write-Host "✓ Node.js already installed: $nodeVersion" -ForegroundColor Green
}

# Add to PATH permanently
Write-Host ""
Write-Host "Adding tools to PATH..." -ForegroundColor Yellow
$currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($currentPath -notlike "*$installDir*") {
    [Environment]::SetEnvironmentVariable("Path", "$currentPath;$installDir", "User")
    Write-Host "✓ PATH updated (restart terminal to apply)" -ForegroundColor Green
}

Write-Host ""
Write-Host "=== Installation Summary ===" -ForegroundColor Cyan
Write-Host "Tool directory: $installDir"
Write-Host ""
Write-Host "Next steps:"
Write-Host "1. Restart PowerShell or terminal"
Write-Host "2. If Go/Node installers were downloaded, run them manually"
Write-Host "3. Verify installation: .\setup\verify_installation.ps1"
Write-Host ""
