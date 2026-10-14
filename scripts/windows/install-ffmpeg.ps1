$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$toolRoot = Join-Path $projectRoot '.tools\ffmpeg'
$binRoot = Join-Path $toolRoot 'bin'
if (Test-Path (Join-Path $binRoot 'ffmpeg.exe')) {
    & (Join-Path $binRoot 'ffmpeg.exe') -version
    exit 0
}
New-Item -ItemType Directory -Path $binRoot -Force | Out-Null
$archivePath = Join-Path $toolRoot 'ffmpeg-release-essentials.zip'
$baseUrl = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
Invoke-WebRequest -Uri $baseUrl -OutFile $archivePath
$checksum = (Invoke-WebRequest -Uri "$baseUrl.sha256").Content
if ($checksum -is [byte[]]) { $checksum = [System.Text.Encoding]::UTF8.GetString($checksum) }
$expected = ([regex]::Match([string]$checksum, '[a-fA-F0-9]{64}')).Value
$actual = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash
if (-not $expected -or $actual -ne $expected) { throw 'FFmpeg SHA256 校验失败' }
$staging = Join-Path $toolRoot ([guid]::NewGuid().ToString('N'))
Expand-Archive -LiteralPath $archivePath -DestinationPath $staging
$binaries = Get-ChildItem -LiteralPath $staging -Recurse -File | Where-Object { $_.Name -in @('ffmpeg.exe', 'ffprobe.exe') }
if ($binaries.Count -ne 2) { throw 'FFmpeg 压缩包中未找到预期程序' }
foreach ($binary in $binaries) { Copy-Item -LiteralPath $binary.FullName -Destination (Join-Path $binRoot $binary.Name) }
Set-Content -LiteralPath (Join-Path $toolRoot 'SHA256.txt') -Value $actual -Encoding UTF8
& (Join-Path $binRoot 'ffmpeg.exe') -version
