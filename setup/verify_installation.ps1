# DARWIN Project - Installation Verification Script
# Run this after installation to check all tools

Write-Host "=== DARWIN Installation Verification ===" -ForegroundColor Cyan
Write-Host ""

$allGood = $true

# Check Docker
Write-Host "Checking Docker..." -NoNewline
try {
    $dockerVersion = docker --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host " ✓ $dockerVersion" -ForegroundColor Green
    } else {
        Write-Host " ✗ Not working" -ForegroundColor Red
        $allGood = $false
    }
} catch {
    Write-Host " ✗ Not installed" -ForegroundColor Red
    $allGood = $false
}

# Check Minikube
Write-Host "Checking Minikube..." -NoNewline
try {
    $minikubeVersion = minikube version --short 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host " ✓ $minikubeVersion" -ForegroundColor Green
    } else {
        Write-Host " ✗ Not working" -ForegroundColor Red
        $allGood = $false
    }
} catch {
    Write-Host " ✗ Not installed" -ForegroundColor Red
    $allGood = $false
}

# Check Kubectl
Write-Host "Checking Kubectl..." -NoNewline
try {
    $kubectlVersion = kubectl version --client --short 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host " ✓ $kubectlVersion" -ForegroundColor Green
    } else {
        Write-Host " ✗ Not working" -ForegroundColor Red
        $allGood = $false
    }
} catch {
    Write-Host " ✗ Not installed" -ForegroundColor Red
    $allGood = $false
}

# Check Helm
Write-Host "Checking Helm..." -NoNewline
try {
    $helmVersion = helm version --short 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host " ✓ $helmVersion" -ForegroundColor Green
    } else {
        Write-Host " ✗ Not working" -ForegroundColor Red
        $allGood = $false
    }
} catch {
    Write-Host " ✗ Not installed" -ForegroundColor Red
    $allGood = $false
}

# Check Python
Write-Host "Checking Python..." -NoNewline
try {
    $pythonVersion = python --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host " ✓ $pythonVersion" -ForegroundColor Green
    } else {
        Write-Host " ✗ Not working" -ForegroundColor Red
        $allGood = $false
    }
} catch {
    Write-Host " ✗ Not installed" -ForegroundColor Red
    $allGood = $false
}

# Check Go
Write-Host "Checking Go..." -NoNewline
try {
    $goVersion = go version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host " ✓ $goVersion" -ForegroundColor Green
    } else {
        Write-Host " ✗ Not working" -ForegroundColor Red
        $allGood = $false
    }
} catch {
    Write-Host " ✗ Not installed" -ForegroundColor Red
    $allGood = $false
}

# Check Node
Write-Host "Checking Node.js..." -NoNewline
try {
    $nodeVersion = node --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host " ✓ $nodeVersion" -ForegroundColor Green
    } else {
        Write-Host " ✗ Not working" -ForegroundColor Red
        $allGood = $false
    }
} catch {
    Write-Host " ✗ Not installed" -ForegroundColor Red
    $allGood = $false
}

# Check NPM
Write-Host "Checking NPM..." -NoNewline
try {
    $npmVersion = npm --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host " ✓ v$npmVersion" -ForegroundColor Green
    } else {
        Write-Host " ✗ Not working" -ForegroundColor Red
        $allGood = $false
    }
} catch {
    Write-Host " ✗ Not installed" -ForegroundColor Red
    $allGood = $false
}

Write-Host ""
if ($allGood) {
    Write-Host "=== All tools installed successfully! ===" -ForegroundColor Green
    Write-Host ""
    Write-Host "Next steps:"
    Write-Host "1. Start minikube: minikube start --cpus=4 --memory=8192"
    Write-Host "2. Install Istio: cd setup && .\install_istio.ps1"
    Write-Host "3. Install databases: cd setup && .\install_databases.ps1"
} else {
    Write-Host "=== Some tools are missing ===" -ForegroundColor Red
    Write-Host "Please run: .\setup\install_windows.ps1" -ForegroundColor Yellow
}
Write-Host ""
