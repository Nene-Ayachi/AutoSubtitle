$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$bundleRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$runtimeRoot = Join-Path $bundleRoot 'runtime'
$sha = [Security.Cryptography.SHA256]::Create()
$mutexId = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($bundleRoot.ToLowerInvariant()))).Replace('-', '')
$sha.Dispose()
$mutex = New-Object Threading.Mutex($false, "Local\MediaTool-$mutexId")
$ownsMutex = $false
try {
    try { $ownsMutex = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $ownsMutex = $true }
    if (-not $ownsMutex) {
        Write-Host 'Media Tool is already running from this folder.'
        exit 0
    }
    # Keep DLL lookup and Python imports inside the bundle, without changing
    # machine/user environment variables or depending on Conda activation.
    Remove-Item Env:PYTHONHOME, Env:PYTHONPATH, Env:CONDA_PREFIX -ErrorAction SilentlyContinue
    $env:PYTHONUTF8 = '1'
    $env:PYTHONNOUSERSITE = '1'
    $env:PATH = "$runtimeRoot;$runtimeRoot\Library\bin;$runtimeRoot\Scripts;$env:SystemRoot\System32;$env:SystemRoot"
    $markerPath = Join-Path $runtimeRoot '.media-tool-runtime-root'
    $ready = (Test-Path -LiteralPath $markerPath) -and ((Get-Content -LiteralPath $markerPath -Raw).Trim() -eq $runtimeRoot)
    if (-not $ready) {
        Write-Host 'Preparing private Python runtime (first launch or folder relocation); this may take a few minutes...'
        $manifest = Get-Content -LiteralPath (Join-Path $bundleRoot 'bundle-manifest.json') -Raw | ConvertFrom-Json
        $archivePath = Join-Path $bundleRoot 'runtime.zip'
        $runtimeHasher = [Security.Cryptography.SHA256]::Create()
        $runtimeStream = [IO.File]::OpenRead($archivePath)
        try { $runtimeHash = [BitConverter]::ToString($runtimeHasher.ComputeHash($runtimeStream)).Replace('-', '') }
        finally { $runtimeStream.Dispose(); $runtimeHasher.Dispose() }
        if ($runtimeHash -ne $manifest.runtime_sha256) { throw 'Runtime checksum mismatch. Extract the original distribution again.' }
        if (Test-Path -LiteralPath $runtimeRoot) {
            $resolvedRuntime = (Resolve-Path -LiteralPath $runtimeRoot).Path
            if (-not [string]::Equals($resolvedRuntime, (Join-Path $bundleRoot 'runtime'), [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe runtime cleanup path.' }
            if ((Get-Item -LiteralPath $runtimeRoot).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Runtime must not be a directory link.' }
            Remove-Item -LiteralPath $runtimeRoot -Recurse -Force
        }
        # Use Windows' built-in .NET directly; do not depend on optional
        # PowerShell modules supplied by a developer installation/PSModulePath.
        [Reflection.Assembly]::LoadWithPartialName('System.IO.Compression.FileSystem') | Out-Null
        [IO.Compression.ZipFile]::ExtractToDirectory($archivePath, $runtimeRoot)
        # conda-pack's standalone relocation script needs no installed Conda.
        & (Join-Path $runtimeRoot 'python.exe') (Join-Path $runtimeRoot 'Scripts\conda-unpack-script.py')
        if ($LASTEXITCODE -ne 0) { throw 'Private runtime relocation failed.' }
        Set-Content -LiteralPath $markerPath -Value $runtimeRoot -Encoding UTF8
    }
    & (Join-Path $runtimeRoot 'python.exe') (Join-Path $bundleRoot 'launcher.py') @args
    if ($LASTEXITCODE -ne 0) { throw "Media Tool exited with code $LASTEXITCODE. See console output above." }
} catch {
    Write-Host $_ -ForegroundColor Red
    exit 1
} finally {
    if ($ownsMutex) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
