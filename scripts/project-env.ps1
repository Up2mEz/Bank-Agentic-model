# Dot-source from any directory. Environment changes affect this shell only.
$projectWorkspaceRoot = Split-Path -Parent $PSScriptRoot
$projectMerchantRoot = Join-Path $projectWorkspaceRoot '.local\merchant-dev'
if (-not (Test-Path -LiteralPath (Join-Path $projectMerchantRoot 'tools\go\bin\go.exe'))) {
    # Temporary bridge; never create another toolchain at this legacy location.
    if (-not (Test-Path -LiteralPath 'D:\merchant-dev\tools\go\bin\go.exe')) {
        throw 'Merchant toolchain is not installed. See docs/PROJECT_LAYOUT_TH.md.'
    }
    Write-Warning 'Merchant runtime migration is pending; using the existing toolchain.'
    . 'D:\merchant-dev\env.ps1'
    return
}

$projectCachePaths = @{
    TEMP = 'tmp'; TMP = 'tmp'; GOPATH = 'cache\go'; GOCACHE = 'cache\go-build'
    GOMODCACHE = 'cache\go-mod'; GOTMPDIR = 'tmp\go'; PUB_CACHE = 'cache\pub'
    GRADLE_USER_HOME = 'cache\gradle'; ANDROID_USER_HOME = 'cache\android'
    UV_CACHE_DIR = 'cache\uv'; PIP_CACHE_DIR = 'cache\pip'
    npm_config_cache = 'cache\npm'; PLAYWRIGHT_BROWSERS_PATH = 'cache\playwright'
    HF_HOME = 'cache\huggingface'; COREPACK_HOME = 'cache\corepack'
    BUN_INSTALL_CACHE_DIR = 'cache\bun'; XDG_CACHE_HOME = 'cache\xdg'
    XDG_CONFIG_HOME = 'cache\config'; XDG_DATA_HOME = 'cache\data'
    APPDATA = 'cache\appdata\Roaming'; LOCALAPPDATA = 'cache\appdata\Local'
    USERPROFILE = 'cache\user-profile'; ANDROID_AVD_HOME = 'cache\android-avd'
    ANDROID_EMULATOR_HOME = 'cache\android-emulator'
}
foreach ($projectCacheName in $projectCachePaths.Keys) {
    $projectCachePath = Join-Path $projectMerchantRoot $projectCachePaths[$projectCacheName]
    [Environment]::SetEnvironmentVariable($projectCacheName, $projectCachePath, 'Process')
    New-Item -ItemType Directory -Path $projectCachePath -Force | Out-Null
}
$env:ANDROID_HOME = Join-Path $projectMerchantRoot 'tools\android-sdk'
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:UV_PYTHON_INSTALL_DIR = Join-Path $projectMerchantRoot 'tools\python'
$env:npm_config_prefix = Join-Path $projectMerchantRoot 'tools\npm-global'
$env:GOENV = Join-Path $projectMerchantRoot 'cache\go-env'
$env:GOTOOLCHAIN = 'local'
$env:FLUTTER_SUPPRESS_ANALYTICS = 'true'
$env:DART_SUPPRESS_ANALYTICS = 'true'
$env:CI = 'true'
$env:JAVA_HOME = Join-Path $projectMerchantRoot 'tools\jdk'

# Replace the old per-project JVM paths while preserving other JVM options.
$projectJavaOptions = [string]$env:JAVA_TOOL_OPTIONS
$projectJavaOverrides = @()
foreach ($projectJavaSetting in @{
    'user.home' = $env:USERPROFILE; 'java.io.tmpdir' = $env:TEMP
}.GetEnumerator()) {
    $projectJavaPattern = '-D' + [regex]::Escape($projectJavaSetting.Key) + '=(?:"[^"]*"|\S+)'
    $projectJavaValue = '-D' + $projectJavaSetting.Key + '="' + $projectJavaSetting.Value + '"'
    $projectJavaOptions = [regex]::Replace($projectJavaOptions, $projectJavaPattern, '').Trim()
    $projectJavaOverrides += $projectJavaValue
}
$env:JAVA_TOOL_OPTIONS = ((@($projectJavaOptions) + $projectJavaOverrides) -join ' ').Trim()

$projectToolPaths = @('go\bin','flutter\bin','postgres\bin','jdk\bin',
    'android-sdk\platform-tools','android-sdk\cmdline-tools\latest\bin') |
    ForEach-Object { Join-Path $projectMerchantRoot ('tools\' + $_) } |
    Where-Object { Test-Path -LiteralPath $_ -PathType Container }
$projectOtherPaths = $env:Path -split ';' | Where-Object {
    $_ -and $_ -notlike 'D:\merchant-dev\tools\*' -and $_ -notin $projectToolPaths
}
$env:Path = (@($projectToolPaths) + @($projectOtherPaths)) -join ';'
