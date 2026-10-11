[CmdletBinding(PositionalBinding = $false)]
param(
    [Parameter(Mandatory)]
    [ValidateSet('list', 'create', 'rename', 'delete', 'add', 'remove', 'logo', 'clear-logo', 'mode', 'ffmpeg', 'build')]
    [string]$Action,
    [Parameter(Mandatory)] [string]$StateRoot,
    # Radio1, Radio2 or Radio3; create picks the first free slot without it.
    [string]$Slot = '',
    # create and rename: the station's name. mode: replace or add.
    [string]$Value = '',
    # add, remove, logo and ffmpeg: folders or files.
    [Parameter(ValueFromRemainingArguments)] [string[]]$Paths = @()
)

# Launcher support for custom radio stations (tools/pinyon_radio.py, #445).
# Prints one JSON object; a failure prints {"result": "error", ...} and
# exits 1.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'release-common.ps1')
$arguments = @((Join-Path $PSScriptRoot 'pinyon.py'), 'radio')
switch ($Action) {
    'create' { $arguments += 'create', $Value; if ($Slot) { $arguments += '--slot', $Slot } }
    'rename' { $arguments += 'rename', $Slot, $Value }
    'delete' { $arguments += 'delete', $Slot }
    'add' { $arguments += 'add', $Slot; $arguments += $Paths }
    'remove' { $arguments += 'remove', $Slot; $arguments += $Paths }
    'logo' { $arguments += 'logo', $Slot; $arguments += $Paths }
    'clear-logo' { $arguments += 'logo', $Slot, '--clear' }
    'mode' { $arguments += 'mode', $Slot, $Value }
    'ffmpeg' { $arguments += 'ffmpeg'; $arguments += $Paths }
    default { $arguments += $Action }
}
$arguments += '--state-root', ([IO.Path]::GetFullPath($StateRoot)), '--json'
& (Get-PinyonPython) @arguments
exit $LASTEXITCODE
