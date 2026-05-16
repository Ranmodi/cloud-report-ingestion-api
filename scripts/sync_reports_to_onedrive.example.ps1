param(
  [string]$Bucket = "example-project-report-ingestion",
  [string]$Prefix = "report-ingestion/drive-sync/Relatórios atualizados",
  [string]$Destino = "C:\Users\YourUser\OneDrive - EXAMPLE COMPANY\Dashboard - API\Relatórios atualizados"
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $Destino | Out-Null
$Origem = "gs://$Bucket/$Prefix"

# Requer Google Cloud CLI autenticado na máquina local.
gcloud storage rsync $Origem $Destino --recursive
Write-Host "Relatórios sincronizados em $Destino"
