$ErrorActionPreference = 'Stop'
$projectDir = $PSScriptRoot
$logPath = Join-Path $projectDir 'backend_setup.log'
$installerPath = Join-Path $env:TEMP 'OllamaSetup-project.exe'
$ollamaPath = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'

Start-Transcript -Path $logPath -Append
try {
    if (-not (Test-Path -LiteralPath $ollamaPath)) {
        Write-Output 'Downloading Ollama. Interrupted downloads resume automatically.'
        & curl.exe --location --fail --continue-at - --retry 5 --retry-delay 5 --connect-timeout 30 --output $installerPath 'https://github.com/ollama/ollama/releases/download/v0.35.1/OllamaSetup.exe'
        if ($LASTEXITCODE -ne 0) { throw 'Ollama download failed. Run this script again to resume.' }
        $signature = Get-AuthenticodeSignature -LiteralPath $installerPath
        if ($signature.Status -ne 'Valid') { throw 'Installer signature is invalid; installation stopped.' }
        $installer = Start-Process -FilePath $installerPath -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-' -Wait -PassThru -WindowStyle Hidden
        if ($installer.ExitCode -ne 0) { throw "Installer failed with exit code $($installer.ExitCode)." }
    }
    if (-not (Test-Path -LiteralPath $ollamaPath)) { throw 'Ollama executable was not installed in the expected location.' }
    try {
        Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5 | Out-Null
    } catch {
        Start-Process -FilePath $ollamaPath -ArgumentList 'serve' -WindowStyle Hidden
        $ready = $false
        for ($attempt = 0; $attempt -lt 30; $attempt++) {
            Start-Sleep -Seconds 2
            try {
                Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 | Out-Null
                $ready = $true
                break
            } catch { }
        }
        if (-not $ready) { throw 'Ollama service did not start within 60 seconds.' }
    }
    $pythonPath = Join-Path $projectDir '.venv\Scripts\python.exe'
    Push-Location -LiteralPath $projectDir
    try {
        $modelName = & $pythonPath -c 'from sql_engine import OLLAMA_MODEL; print(OLLAMA_MODEL)'
        if ($LASTEXITCODE -ne 0) { throw 'Cannot read app model settings.' }
        Write-Output "Downloading configured model: $modelName"
        & $ollamaPath pull $modelName
        if ($LASTEXITCODE -ne 0) { throw 'Model download failed. Run this script again to resume.' }
        & $pythonPath -m tests.live_check
        if ($LASTEXITCODE -ne 0) { throw 'Live generation failed. See the diagnostic message above.' }
        Write-Output 'Backend installation and live SQL generation passed. Restart the app using run_app.bat.'
    } finally {
        Pop-Location
    }
} catch {
    Write-Output "SETUP FAILED: $_"
    exit 1
} finally {
    Stop-Transcript
}
