# Sobe o Contract Analyzer com Docker Compose (Windows)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Test-Path ".env")) {
    if (Test-Path ".env.docker.example") {
        Copy-Item ".env.docker.example" ".env"
        Write-Host "Arquivo .env criado a partir de .env.docker.example — edite OPENAI_API_KEY antes de usar em producao."
    } else {
        Write-Error "Crie um arquivo .env com OPENAI_API_KEY (veja .env.docker.example)."
    }
}

docker compose up -d --build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$port = "8501"
if (Test-Path ".env") {
    $m = Select-String -Path ".env" -Pattern "^\s*APP_PORT\s*=\s*(\d+)" | Select-Object -First 1
    if ($m) { $port = $m.Matches.Groups[1].Value }
}

Write-Host ""
Write-Host "Contract Analyzer em execucao: http://localhost:$port"
Write-Host "Logs: docker compose logs -f"
Write-Host "Parar: docker compose down"
