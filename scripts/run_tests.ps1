# Executa testes automatizados e gera relatório HTML
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

$env:PYTHONPATH = (Get-Location).Path
$venvPy = ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Error "Ambiente .venv não encontrado. Execute: py -m venv .venv"
}

& $venvPy -m pip install -q -r requirements-dev.txt

$reportDir = "reports"
New-Item -ItemType Directory -Force -Path $reportDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$htmlReport = "$reportDir\pytest_report_$stamp.html"
$mdReport = "$reportDir\TEST_REPORT.md"

Write-Host "Executando pytest..."
& $venvPy -m pytest tests `
    --html="$htmlReport" --self-contained-html `
    --cov=app.core --cov=app.db --cov-report=term-missing `
    2>&1 | Tee-Object -FilePath "$reportDir\pytest_last_run.log"

$exitCode = $LASTEXITCODE

# Gera markdown resumido
$log = Get-Content "$reportDir\pytest_last_run.log" -Raw -ErrorAction SilentlyContinue
$passed = if ($log -match "(\d+) passed") { $Matches[1] } else { "?" }
$failed = if ($log -match "(\d+) failed") { $Matches[1] } else { "0" }
$skipped = if ($log -match "(\d+) skipped") { $Matches[1] } else { "0" }

@"
# Relatório de testes automatizados — BGF Contract Analyzer

**Data:** $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
**Resultado:** $passed passed, $failed failed, $skipped skipped
**Relatório HTML:** [$htmlReport]($htmlReport)

## Escopo

| Suite | O que valida |
|-------|----------------|
| test_imports_core | Imports de módulos core/db e dependências |
| test_text_diff | Diff determinístico, zero falso positivo em textos idênticos |
| test_extractor_comments | Extração de texto/comentários nos PDFs em contracts/ |
| test_reviewer_offline | Revisão local de comentários sem Gemini |
| test_auth_database | Login, owner_user_id, persistência de comentários |

## Contratos usados

- ``BVV... - BGF.pdf`` × ``...BGF_revisao.pdf`` — 89 comentários, texto extraído idêntico
- ``contracts/_temp/a_*_comentarios.pdf`` × ``b_*_devolutiva_revisao.pdf`` — diff real

## Saída completa

``````
$log
``````
"@ | Set-Content -Encoding UTF8 $mdReport

Write-Host ""
Write-Host "Relatório HTML: $htmlReport"
Write-Host "Relatório MD:   $mdReport"
exit $exitCode
