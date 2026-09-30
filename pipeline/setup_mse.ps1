# Downloads Magic Set Editor (Full Magic Pack: M15, modern and old frame templates) and
# installs its Magic fonts for the current user. Windows only.
#   powershell -ExecutionPolicy Bypass -File pipeline/setup_mse.ps1 [-Dir mse]
param([string]$Dir = "mse")

$paths = @(
  "/magicseteditor.com", "/magicseteditor.exe", "/Magic - Fonts/*",
  "/data/en.mse-locale/", "/data/magic.mse-game/",
  "/data/magic-m15-altered.mse-style/", "/data/magic-m15-mainframe-planeswalker.mse-style/",
  "/data/magic-old.mse-style/", "/data/magic-new.mse-style/", "/data/magic-new-miracle.mse-style/",
  "/data/magic-blends.mse-include/", "/data/magic-default-image.mse-include/",
  "/data/magic-mainframe-extras.mse-include/", "/data/magic-modules.mse-include/",
  "/data/magic-pride.mse-include/",
  "/data/magic-mana-large.mse-symbol-font/", "/data/magic-mana-small.mse-symbol-font/"
)

if (-not (Test-Path "$Dir/magicseteditor.com")) {
  git clone --depth 1 --filter=blob:none --no-checkout https://github.com/MagicSetEditorPacks/Full-Magic-Pack $Dir
  if ($LASTEXITCODE) { throw "git clone failed" }
  git -C $Dir sparse-checkout set --no-cone @paths
  if ($LASTEXITCODE) { throw "git sparse-checkout failed" }
  git -C $Dir checkout
  if ($LASTEXITCODE) { throw "git checkout failed" }
}

# Montserrat (SIL OFL): free look-alike of Gotham, the font of the bottom line of real cards
# (collector number, set code, artist); installed with the Magic fonts below.
$extra = Join-Path $Dir "Magic - Fonts\montserrat"
New-Item -ItemType Directory -Force $extra | Out-Null
foreach ($w in "Regular", "Medium", "SemiBold") {
  $dest = Join-Path $extra "Montserrat-$w.ttf"
  if (-not (Test-Path $dest)) {
    Invoke-WebRequest "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-$w.ttf" `
      -OutFile $dest -UseBasicParsing
  }
}

# Font install: system-wide when running as admin (CI runners), per-user otherwise.
# Also registered for the current session so MSE sees them without a new logon.
Add-Type -Namespace W -Name F -MemberDefinition `
  '[DllImport("gdi32.dll", CharSet = CharSet.Unicode)] public static extern int AddFontResourceW(string f);'
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
         ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($admin) {
  $fontDir = Join-Path $env:WINDIR "Fonts"
  $reg = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"
} else {
  $fontDir = Join-Path $env:LOCALAPPDATA "Microsoft\Windows\Fonts"
  $reg = "HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Fonts"
}
New-Item -ItemType Directory -Force $fontDir | Out-Null
if (-not (Test-Path $reg)) { New-Item -Force $reg | Out-Null }
Get-ChildItem (Join-Path $Dir "Magic - Fonts") -Recurse -File |
  Where-Object { $_.Extension -in ".ttf", ".otf" } |
  ForEach-Object {
    $f = $_
    $dest = Join-Path $fontDir $f.Name
    # the pack also ships copies of Windows' own fonts (Times, Calibri, Arial...): keep those
    if (Test-Path $dest) { return }
    try {
      Copy-Item $f.FullName $dest -Force
      $val = if ($admin) { $f.Name } else { $dest }
      New-ItemProperty $reg -Name "$($f.BaseName) (TrueType)" -Value $val -Force | Out-Null
      [void][W.F]::AddFontResourceW($dest)
    } catch { Write-Warning "font $($f.Name): $_" }
  }
Write-Host "Magic Set Editor ready in $Dir"
