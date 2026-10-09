# Windows equivalent of the Makefile:  .\make.ps1 data | mocks | train | eval | demo | api | web | test | setup
param([Parameter(Mandatory = $true)][string]$Target)
$ErrorActionPreference = 'Stop'
$Py = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
Set-Location $PSScriptRoot

switch ($Target) {
    'setup' { python -m venv .venv; & $Py -m pip install -r requirements.txt; Push-Location web; npm install; Pop-Location }
    'data'  { & $Py -m orbitguard.download }
    'mocks' { & $Py -m api.mock.generate_mocks }
    'train' { & $Py -m orbitguard.features; & $Py -m orbitguard.models }
    'eval'  { & $Py -m orbitguard.evaluate; & $Py -m orbitguard.pc }
    'demo'  { & $Py -m orbitguard.build_demo }
    'api'   { & $Py -m uvicorn api.main:app --reload --port 8000 }
    'web'   { Push-Location web; npm run dev; Pop-Location }
    'test'  { & $Py -m pytest -q }
    default { Write-Error "Unknown target '$Target'" }
}
