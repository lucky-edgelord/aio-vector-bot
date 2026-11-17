# Run Vectiq in the foreground (Ctrl-C stops it). Extra arguments go to vectiq, e.g. .\run.ps1 --check
Set-Location $PSScriptRoot
& .\.venv\Scripts\python.exe -m vectiq @args
exit $LASTEXITCODE
