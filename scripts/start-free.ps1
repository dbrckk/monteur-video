# Windows PowerShell: Docker Desktop must be running.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
docker compose version | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Installe et demarre Docker Desktop." }

if (-not (Test-Path ".env")) { [System.IO.File]::WriteAllText((Join-Path (Get-Location) ".env"), "") }
$lines = [System.IO.File]::ReadAllLines((Join-Path (Get-Location) ".env"))
$secretLine = $lines | Where-Object { $_ -match '^APP_API_TOKEN=' } | Select-Object -First 1
if ($secretLine -and $secretLine -notmatch '^APP_API_TOKEN=[A-Za-z0-9_-]{32,}$') {
    throw "APP_API_TOKEN invalide. Corrige .env avant de lancer le tunnel."
}
if (-not $secretLine) {
    $bytes = New-Object byte[] 36
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $secret = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_')
    Add-Content -Path ".env" -Value ("APP_API_TOKEN=" + $secret)
    Write-Host "Cle privee generee dans .env"
} else { $secret = $secretLine.Substring(14) }
if (-not ($lines | Where-Object { $_ -match '^MAX_UPLOAD_GB=' })) {
    Add-Content -Path ".env" -Value "MAX_UPLOAD_GB=20"
}
docker compose -f compose.yaml -f compose.remote.yaml config --quiet
if ($LASTEXITCODE -ne 0) { throw "Configuration Docker Compose invalide." }
docker compose -f compose.yaml -f compose.remote.yaml up --build -d
if ($LASTEXITCODE -ne 0) { throw "Demarrage du moteur impossible." }
$url = $null
for ($i = 0; $i -lt 40; $i++) {
    $logs = docker compose -f compose.yaml -f compose.remote.yaml logs --no-color tunnel 2>&1 | Out-String
    $matchesFound = [regex]::Matches($logs, 'https://[A-Za-z0-9-]+\.trycloudflare\.com')
    if ($matchesFound.Count -gt 0) {
        $url = $matchesFound[$matchesFound.Count - 1].Value
        break
    }
    Start-Sleep -Seconds 2
}
if (-not $url) { throw "Tunnel non disponible. Consulter les logs Docker Compose (service tunnel)." }
Write-Host ""
Write-Host "1. Site Android : https://dbrckk.github.io/monteur-video/"
Write-Host ("2. Adresse HTTPS du moteur : " + $url)
Write-Host ("3. Cle d'acces privee : " + $secret)
Write-Host "Garde ton ordinateur allume pendant les transferts et les rendus."
