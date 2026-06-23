# ============================================================================
#  TOAI - one-shot setup for a FRESH Windows PC.
#  Run via TOAI_Install.bat (double-click). Assumes this repo already sits at
#  C:\lior (restore the lior folder from the D backup, or git clone, first).
#  Does: Python + deps, optional API key, NinjaScript -> NinjaTrader, desktop
#  shortcuts, and (optional) restore C:\LIOR_ML from the latest D backup.
#  No admin needed (user-scope winget / setx / file copies).
# ============================================================================
$ErrorActionPreference = 'Continue'
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "================ TOAI install ================" -ForegroundColor Cyan
Write-Host "repo: $repo`n"

function Get-Python {
    $c = Get-Command python -ErrorAction SilentlyContinue
    if ($c -and $c.Source -notlike '*WindowsApps*') { return $c.Source }
    foreach ($p in @("$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
                     "C:\Program Files\Python3*\python.exe")) {
        $hit = Get-ChildItem $p -ErrorAction SilentlyContinue | Sort-Object FullName | Select-Object -Last 1
        if ($hit) { return $hit.FullName }
    }
    return $null
}

# ---- 1) Python ----
$py = Get-Python
if (-not $py) {
    Write-Host "[1/6] Installing Python 3.12 (winget)..." -ForegroundColor Yellow
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install -e --id Python.Python.3.12 --scope user `
            --accept-source-agreements --accept-package-agreements
        $py = Get-Python
    }
    if (-not $py) {
        Write-Host "  Could not auto-install. Install Python 3.10+ from python.org" -ForegroundColor Red
        Write-Host "  (tick Add python.exe to PATH), then re-run this installer." -ForegroundColor Red
        Read-Host "Press Enter to close"; exit 1
    }
}
Write-Host "[1/6] Python: $py" -ForegroundColor Green

# ---- 2) Python dependencies ----
Write-Host "[2/6] Installing Python dependencies..." -ForegroundColor Yellow
& $py -m pip install --upgrade pip
& $py -m pip install -r (Join-Path $repo 'requirements.txt')

# ---- 3) Anthropic API key (optional - AI Coach only) ----
Write-Host "[3/6] Anthropic API key (optional, for the AI Coach tab)." -ForegroundColor Yellow
$key = Read-Host "  Paste ANTHROPIC_API_KEY (sk-ant-...) or press Enter to skip"
if ($key.Trim()) {
    setx ANTHROPIC_API_KEY $key.Trim() | Out-Null
    Write-Host "  Saved as a user env var." -ForegroundColor Green
}

# ---- 4) NinjaScript -> NinjaTrader 8 Custom ----
Write-Host "[4/6] Installing NinjaScript (AddOn + indicators)..." -ForegroundColor Yellow
$ntCustom = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'NinjaTrader 8\bin\Custom'
if (Test-Path $ntCustom) {
    $src     = Join-Path $repo 'ninjascript_v4_gauge_tick'
    $addons  = Join-Path $ntCustom 'AddOns'
    $inds    = Join-Path $ntCustom 'Indicators'
    New-Item -ItemType Directory -Force -Path $addons, $inds | Out-Null
    Copy-Item (Join-Path $src 'TOAIExecutionLogger.cs') $addons -Force
    foreach ($f in 'TOAIExporterGaugeTick.cs','TOAIGaugeHUD.cs','TOAISignalLabelGaugeTick.cs') {
        Copy-Item (Join-Path $src $f) $inds -Force
    }
    Write-Host "  Copied AddOn + 3 indicators. Compile in NinjaTrader (F5)." -ForegroundColor Green
} else {
    Write-Host "  NinjaTrader 8 not found ($ntCustom)." -ForegroundColor Red
    Write-Host "  Install NinjaTrader, then re-run (or copy ninjascript_v4_gauge_tick\*.cs manually)." -ForegroundColor Red
}

# ---- 5) Desktop shortcuts ----
Write-Host "[5/6] Desktop shortcuts..." -ForegroundColor Yellow
$desk = [Environment]::GetFolderPath('Desktop')
$ws = New-Object -ComObject WScript.Shell
function Make-Shortcut($name, $target, $minimized) {
    $sc = $ws.CreateShortcut((Join-Path $desk "$name.lnk"))
    $sc.TargetPath = $target
    $sc.WorkingDirectory = Split-Path $target
    if ($minimized) { $sc.WindowStyle = 7 }   # run minimized
    $chrome = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
    if ((Test-Path $chrome) -and $minimized) { $sc.IconLocation = "$chrome,0" }
    $sc.Save()
}
Make-Shortcut 'TOAI Analytics'   (Join-Path $repo 'TOAI_Analytics_App.bat') $true
Make-Shortcut 'TOAI Backup to D' (Join-Path $repo 'TOAI_Backup_ToD.bat')    $false
Write-Host "  Created TOAI Analytics + TOAI Backup to D." -ForegroundColor Green

# ---- 6) Restore data from the latest D backup (optional) ----
Write-Host "[6/6] Restore C:\LIOR_ML from a D backup (optional)..." -ForegroundColor Yellow
$bk = Get-ChildItem 'D:\TOAI_Backup_*\LIOR_ML' -Directory -ErrorAction SilentlyContinue |
      Sort-Object FullName | Select-Object -Last 1
if ($bk) {
    if ((Read-Host "  Restore $($bk.FullName) to C:\LIOR_ML ? (y/N)") -eq 'y') {
        robocopy $bk.FullName 'C:\LIOR_ML' /E /R:2 /W:2 /NFL /NDL /NP | Out-Null
        Write-Host "  Restored." -ForegroundColor Green
    }
} else {
    Write-Host "  No D:\TOAI_Backup_*\LIOR_ML found - copy the data folder to C:\LIOR_ML manually." -ForegroundColor DarkYellow
}

Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host " DONE. Remaining steps:" -ForegroundColor Cyan
Write-Host "   1. NinjaTrader -> NinjaScript Editor -> Compile (F5)."
Write-Host "   2. Add the TOAIExporterGaugeTick indicator to your MES chart."
Write-Host "   3. Double-click the TOAI Analytics desktop shortcut -> trade."
Write-Host "============================================================" -ForegroundColor Cyan
Read-Host "Press Enter to close"
