<#
.SYNOPSIS
Cut a release: set the version, build the package, commit and tag, so the tag always matches the manifest.

.DESCRIPTION
    .\tools\release.ps1                asks whether this is a patch, minor or major release (or a version you type), then asks to confirm and to push
    .\tools\release.ps1 0.2.3          builds dist\<name>-0.2.3.zip, commits the new version and tags v0.2.3
    .\tools\release.ps1 0.2.3 -Push    and pushes main and the tag, which makes the Release workflow test and publish it on GitHub
    .\tools\release.ps1 -BuildOnly     only builds the package of the version now in the manifest

If PowerShell says running scripts is disabled, start it as: powershell -ExecutionPolicy Bypass -File .\tools\release.ps1 0.2.3
Needs only Windows PowerShell and git. The unit tests are run by the Release workflow before it publishes.
Nothing is committed or tagged unless the package builds. Without -Push, the commands to publish are printed.
The package holds the same files as tools\build_release.py (which the workflow runs): keep the two lists in step.
#>
param(
    [Parameter(Position = 0)][string]$Version,
    [switch]$Push,
    [switch]$BuildOnly
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Name = 'Fusion Manage Item Management'   # Fusion needs the folder, the script and the manifest to share this name
$Manifest = Join-Path $Root "$Name.manifest"
$Include = @("$Name.py", "$Name.manifest", 'LICENSE', 'README.md', 'src', 'resources')
$Branch = 'main'
$Utf8 = New-Object System.Text.UTF8Encoding($false)

function Invoke-Git {
    $output = & git -C $Root @args
    if ($LASTEXITCODE) { throw "git $($args -join ' ') failed: $output" }
    return $output
}

function Get-ManifestVersion {
    # Not ConvertFrom-Json: Windows PowerShell 5.1 rejects the manifest's empty-named description key.
    if ([IO.File]::ReadAllText($Manifest) -notmatch '"version"\s*:\s*"([^"]*)"') { throw "No `"version`" found in $Name.manifest." }
    return $Matches[1]
}

function Set-ManifestVersion([string]$New) {
    # Only the version text changes; the rest of the file keeps its layout and line endings.
    $text = [IO.File]::ReadAllText($Manifest)
    $pattern = '("version"\s*:\s*")[^"]*(")'
    if ($text -notmatch $pattern) { throw "No `"version`" found in $Name.manifest." }
    [IO.File]::WriteAllText($Manifest, [regex]::new($pattern).Replace($text, "`${1}$New`${2}", 1), $Utf8)
}

function Build-Package {
    $out = Join-Path $Root 'dist'
    New-Item -ItemType Directory -Force $out | Out-Null
    $target = Join-Path $out ("{0}-{1}.zip" -f $Name.Replace(' ', '-'), (Get-ManifestVersion))
    if (Test-Path $target) { Remove-Item $target }
    Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::Open($target, 'Create')
    try {
        foreach ($entry in $Include) {
            $path = Join-Path $Root $entry
            if (-not (Test-Path $path)) { throw "Missing from the add-in: $entry" }
            $files = if ((Get-Item $path).PSIsContainer) { Get-ChildItem $path -Recurse -File | Sort-Object FullName } else { Get-Item $path }
            foreach ($file in $files) {
                if ($file.FullName -match '[\\/]__pycache__[\\/]' -or $file.Extension -in '.pyc', '.pyo') { continue }
                $relative = $file.FullName.Substring($Root.Length).TrimStart('\', '/').Replace('\', '/')
                [void][IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $file.FullName, "$Name/$relative", 'Optimal')
            }
        }
    } finally {
        $archive.Dispose()
    }
    Write-Host ("Wrote {0} ({1} KB)" -f $target, [int]((Get-Item $target).Length / 1KB))
}

function Read-Choice([string]$Prompt) { return (Read-Host $Prompt).Trim() }

function Stop-Release { Write-Host "Cancelled; nothing was changed."; exit 0 }

function Select-Version([string]$Current) {
    # Ask how far to move the version: the next patch, minor or major, or a version typed in.
    $v = [version]$Current
    $options = [ordered]@{
        '1' = @{ Label = 'Patch'; Version = "$($v.Major).$($v.Minor).$($v.Build + 1)"; Note = 'fixes and small changes' }
        '2' = @{ Label = 'Minor'; Version = "$($v.Major).$($v.Minor + 1).0"; Note = 'new features' }
        '3' = @{ Label = 'Major'; Version = "$($v.Major + 1).0.0"; Note = 'breaking changes' }
    }
    Write-Host "`nCurrent version: $Current`n"
    foreach ($key in $options.Keys) {
        Write-Host ("  [{0}] {1,-6} {2,-8} {3}" -f $key, $options[$key].Label, $options[$key].Version, $options[$key].Note)
    }
    Write-Host '  [4] Enter a version'
    Write-Host '  [Q] Cancel'
    $answer = Read-Choice "`nChoose"
    if ($options.Contains($answer)) { return $options[$answer].Version }
    if ($answer -eq '4') { return Read-Choice 'Version' }
    Stop-Release
}

if ($BuildOnly) { Build-Package; return }

# Stop unless a release can be made from here.
if ((Invoke-Git rev-parse --abbrev-ref HEAD) -ne $Branch) { throw "Releases are made from $Branch; switch to it first." }
if (Invoke-Git status --porcelain) { throw 'The working tree has uncommitted changes; commit or stash them first.' }
$current = Get-ManifestVersion
$interactive = -not $Version
if ($interactive) { $Version = Select-Version $current }
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "'$Version' is not a version such as 0.2.3." }
if ([version]$Version -le [version]$current) { throw "$Version is not newer than the manifest version $current." }
if (Invoke-Git tag --list "v$Version") { throw "The tag v$Version already exists." }
if ($interactive -and (Read-Choice "Release $Version (currently $current)? [y/N]") -notmatch '^[yY]') { Stop-Release }

Set-ManifestVersion $Version
try {
    Build-Package
} catch {
    Invoke-Git checkout -- "$Name.manifest" | Out-Null   # a failed build leaves the manifest as it was
    throw
}
Invoke-Git add "$Name.manifest" | Out-Null
Invoke-Git commit -m "Set the add-in version to $Version" | Out-Null
Invoke-Git tag -a "v$Version" -m "Version $Version" | Out-Null
Write-Host "Committed the version and tagged v$Version."

if ($interactive -and -not $Push) { $Push = (Read-Choice "Push $Branch and v$Version now, which publishes the release? [y/N]") -match '^[yY]' }
if ($Push) {
    Invoke-Git push origin $Branch | Out-Null
    Invoke-Git push origin "v$Version" | Out-Null
    Write-Host "Pushed $Branch and v$Version; the Release workflow will test and publish it."
} else {
    Write-Host "To publish:`n    git push origin $Branch`n    git push origin v$Version"
}
