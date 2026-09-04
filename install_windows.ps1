param(
    [switch]$SkipModel,
    [switch]$SkipRuntime,
    [switch]$SkipWorkflowCopy,
    [int]$ParallelDownloads = 8
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw 'PowerShell 7 or newer is required. Install it with: winget install Microsoft.PowerShell'
}

$pluginDir = $PSScriptRoot
$comfyRoot = (Resolve-Path (Join-Path $pluginDir '..\..')).Path
if (-not (Test-Path (Join-Path $comfyRoot 'folder_paths.py'))) {
    throw "This repository must be cloned under ComfyUI/custom_nodes. Detected root: $comfyRoot"
}
$modelDir = Join-Path $comfyRoot 'models\LLM\Qwen3.8-27B-GGUF'
$cacheDir = Join-Path $pluginDir 'download-cache'
$runtimeDir = Join-Path $pluginDir 'runtime\llama-b10621'
$skillDir = Join-Path $pluginDir 'official\h3-prompt-writing'
$workflowDir = Join-Path $comfyRoot 'user\default\workflows'
New-Item -ItemType Directory -Force -Path $modelDir,$cacheDir,$runtimeDir,(Join-Path $skillDir 'references') | Out-Null

function Assert-Hash([string]$Path, [string]$Expected) {
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $Expected) { throw "SHA256 mismatch: $Path; expected $Expected; actual $actual" }
}

function Get-VerifiedFile([string]$Url, [string]$Path, [string]$Hash) {
    if (Test-Path -LiteralPath $Path) {
        try { Assert-Hash $Path $Hash; Write-Host "Already verified: $Path"; return } catch {}
    }
    $partial = "$Path.part"
    Invoke-WebRequest -Uri $Url -OutFile $partial -MaximumRetryCount 3 -RetryIntervalSec 2
    Assert-Hash $partial $Hash
    Move-Item -LiteralPath $partial -Destination $Path -Force
    Write-Host "Verified: $Path"
}

function Get-RangedVerifiedFile([string]$Url, [string]$Path, [long]$Size, [string]$Hash) {
    if (Test-Path -LiteralPath $Path) {
        try { Assert-Hash $Path $Hash; Write-Host "Already verified: $Path"; return } catch {}
    }
    $chunkSize = 32MB
    $fileChunkDir = Join-Path $cacheDir ([IO.Path]::GetFileName($Path))
    New-Item -ItemType Directory -Force -Path $fileChunkDir | Out-Null
    $chunks = for ($start = 0L; $start -lt $Size; $start += $chunkSize) {
        $end = [Math]::Min($start + $chunkSize - 1, $Size - 1)
        [PSCustomObject]@{ Start=$start; End=$end; Total=$Size; Url=$Url; Path=(Join-Path $fileChunkDir "$start.chunk") }
    }
    Write-Host "Downloading $([IO.Path]::GetFileName($Path)) in $($chunks.Count) resumable chunks..."
    $chunks | ForEach-Object -Parallel {
        $ProgressPreference = 'SilentlyContinue'
        $chunk = $_
        $expected = $chunk.End - $chunk.Start + 1
        if ((Test-Path -LiteralPath $chunk.Path) -and (Get-Item $chunk.Path).Length -eq $expected) { return }
        for ($attempt = 1; $attempt -le 5; $attempt++) {
            try {
                $response = Invoke-WebRequest -Uri $chunk.Url -Headers @{ Range="bytes=$($chunk.Start)-$($chunk.End)" } -OutFile $chunk.Path -PassThru -TimeoutSec 120
                $contentRange = @($response.Headers.'Content-Range')[0]
                if ($response.StatusCode -ne 206 -or $contentRange -ne "bytes $($chunk.Start)-$($chunk.End)/$($chunk.Total)" -or (Get-Item $chunk.Path).Length -ne $expected) {
                    throw "Invalid range response at byte $($chunk.Start)"
                }
                break
            } catch {
                if ($attempt -eq 5) { throw }
                Start-Sleep -Seconds ([Math]::Min(10, 2 * $attempt))
            }
        }
    } -ThrottleLimit $ParallelDownloads
    $assembled = "$Path.assembling"
    $out = [IO.File]::Open($assembled, [IO.FileMode]::Create, [IO.FileAccess]::Write)
    try {
        foreach ($chunk in $chunks) {
            $input = [IO.File]::OpenRead($chunk.Path)
            try { $input.CopyTo($out) } finally { $input.Dispose() }
        }
    } finally { $out.Dispose() }
    Assert-Hash $assembled $Hash
    Move-Item -LiteralPath $assembled -Destination $Path -Force
    Remove-Item -LiteralPath $fileChunkDir -Recurse -Force
    Write-Host "Verified: $Path"
}

$skillRevision = 'd21241f0a4b3acbb34c97dae47fa417b7065e438'
$skillBase = "https://raw.githubusercontent.com/MiniMax-AI/MiniMax-H3/$skillRevision/skills/h3-prompt-writing"
Get-VerifiedFile "$skillBase/SKILL.md" (Join-Path $skillDir 'SKILL.md') 'a7000443588ca3f145e3b3fd8900f14e0325dc460bd811268fac89a9dc8e56d0'
Get-VerifiedFile "$skillBase/references/base-en.txt" (Join-Path $skillDir 'references\base-en.txt') '2cfebc096a6e08370f288d468d90b60f7f9bcb938f94bf090816e910e48e75fc'
Get-VerifiedFile "$skillBase/references/ref-en.txt" (Join-Path $skillDir 'references\ref-en.txt') '1e574f356716ad55612247ffb7bbccbcdb484ad96599d63c7dca1af186b1fab7'

if (-not $SkipRuntime) {
    $llamaZip = Join-Path $cacheDir 'llama-b10621-win-cuda-13.3-x64.zip'
    $cudaZip = Join-Path $cacheDir 'cudart-llama-win-cuda-13.3-x64.zip'
    Get-VerifiedFile 'https://github.com/ggml-org/llama.cpp/releases/download/b10621/llama-b10621-bin-win-cuda-13.3-x64.zip' $llamaZip '23549ccc00b6a18d74348e95d4789f7e96c9efb11cf6e3f1b185baef34d7449f'
    Get-VerifiedFile 'https://github.com/ggml-org/llama.cpp/releases/download/b10621/cudart-llama-bin-win-cuda-13.3-x64.zip' $cudaZip '1462a050eb4c684921ba51dcc4cc488a036674c3e73e9945ee705b854808d03e'
    Expand-Archive -LiteralPath $llamaZip -DestinationPath $runtimeDir -Force
    Expand-Archive -LiteralPath $cudaZip -DestinationPath $runtimeDir -Force
    $servers = @(Get-ChildItem -LiteralPath $runtimeDir -Filter llama-server.exe -Recurse)
    if ($servers.Count -ne 1) { throw "Expected one llama-server.exe, found $($servers.Count)" }
}

if (-not $SkipModel) {
    $modelBase = 'https://huggingface.co/unsloth/Qwen3.8-27B-GGUF/resolve/4ca720788d1e01f1bff70c033e0d0028fd02e502'
    Get-RangedVerifiedFile "$modelBase/mmproj-F16.gguf?download=true" (Join-Path $modelDir 'mmproj-F16.gguf') 927607488 'cbb841a9ee0636b2ec172f5bb8df2ea8dfeb01e90fe7c6126581d662a0b4e43e'
    Get-RangedVerifiedFile "$modelBase/Qwen3.8-27B-UD-Q4_K_M.gguf?download=true" (Join-Path $modelDir 'Qwen3.8-27B-UD-Q4_K_M.gguf') 16464440224 '322e194ff79741c7baa497c240f677f54b201b0efab44ca8e50f122b39123482'
}

if (-not $SkipWorkflowCopy) {
    New-Item -ItemType Directory -Force -Path $workflowDir | Out-Null
    Copy-Item -LiteralPath (Join-Path $pluginDir 'workflows\H3_QwenLocal_PromptOnly.json'),(Join-Path $pluginDir 'workflows\H3_QwenLocal_Ref2VA.json') -Destination $workflowDir -Force
}

Write-Host ''
Write-Host 'Installation complete. Restart ComfyUI and open H3_QwenLocal_PromptOnly first.'
