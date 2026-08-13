[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Drawing

$applicationRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $applicationRoot '..\..'))
$electronRoot = Join-Path $repositoryRoot 'studio\edmg-studio'
$assetRoot = Join-Path $applicationRoot 'Assets'
$brandRoot = Join-Path $assetRoot 'Brand'

function Assert-AssetTarget {
    param([Parameter(Mandatory)][string]$Path)

    $candidate = [System.IO.Path]::GetFullPath($Path)
    $allowedRoot = $assetRoot.TrimEnd('\') + '\'
    if (-not $candidate.StartsWith($allowedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to write outside the WinUI asset directory: $candidate"
    }
}

function Set-HighQualityRendering {
    param([Parameter(Mandatory)][System.Drawing.Graphics]$Graphics)

    $Graphics.CompositingMode = [System.Drawing.Drawing2D.CompositingMode]::SourceOver
    $Graphics.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
    $Graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $Graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $Graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
}

function Draw-ImageContain {
    param(
        [Parameter(Mandatory)][System.Drawing.Graphics]$Graphics,
        [Parameter(Mandatory)][System.Drawing.Image]$Image,
        [Parameter(Mandatory)][System.Drawing.RectangleF]$Bounds
    )

    $scale = [Math]::Min($Bounds.Width / $Image.Width, $Bounds.Height / $Image.Height)
    $width = [single]($Image.Width * $scale)
    $height = [single]($Image.Height * $scale)
    $x = [single]($Bounds.X + (($Bounds.Width - $width) / 2))
    $y = [single]($Bounds.Y + (($Bounds.Height - $height) / 2))
    $Graphics.DrawImage($Image, $x, $y, $width, $height)
}

function Draw-ImageCover {
    param(
        [Parameter(Mandatory)][System.Drawing.Graphics]$Graphics,
        [Parameter(Mandatory)][System.Drawing.Image]$Image,
        [Parameter(Mandatory)][System.Drawing.RectangleF]$Bounds
    )

    $scale = [Math]::Max($Bounds.Width / $Image.Width, $Bounds.Height / $Image.Height)
    $sourceWidth = [single]($Bounds.Width / $scale)
    $sourceHeight = [single]($Bounds.Height / $scale)
    $sourceX = [single](($Image.Width - $sourceWidth) / 2)
    $sourceY = [single](($Image.Height - $sourceHeight) / 2)
    $source = [System.Drawing.RectangleF]::new($sourceX, $sourceY, $sourceWidth, $sourceHeight)
    $Graphics.DrawImage($Image, $Bounds, $source, [System.Drawing.GraphicsUnit]::Pixel)
}

function Save-SquareLogo {
    param(
        [Parameter(Mandatory)][System.Drawing.Image]$Logo,
        [Parameter(Mandatory)][int]$Size,
        [Parameter(Mandatory)][string]$Path,
        [double]$PaddingRatio = 0.035
    )

    Assert-AssetTarget -Path $Path
    $bitmap = [System.Drawing.Bitmap]::new($Size, $Size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    try {
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        try {
            Set-HighQualityRendering -Graphics $graphics
            $graphics.Clear([System.Drawing.ColorTranslator]::FromHtml('#041417'))
            $padding = [single]($Size * $PaddingRatio)
            $bounds = [System.Drawing.RectangleF]::new($padding, $padding, $Size - (2 * $padding), $Size - (2 * $padding))
            Draw-ImageContain -Graphics $graphics -Image $Logo -Bounds $bounds
        }
        finally {
            $graphics.Dispose()
        }
        $bitmap.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
    }
    finally {
        $bitmap.Dispose()
    }
}

function Save-BrandedWideAsset {
    param(
        [Parameter(Mandatory)][System.Drawing.Image]$Logo,
        [Parameter(Mandatory)][System.Drawing.Image]$Background,
        [Parameter(Mandatory)][int]$Width,
        [Parameter(Mandatory)][int]$Height,
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][bool]$Splash
    )

    Assert-AssetTarget -Path $Path
    $bitmap = [System.Drawing.Bitmap]::new($Width, $Height, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    try {
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        try {
            Set-HighQualityRendering -Graphics $graphics
            Draw-ImageCover -Graphics $graphics -Image $Background -Bounds ([System.Drawing.RectangleF]::new(0, 0, $Width, $Height))
            $overlay = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(205, 4, 20, 23))
            try {
                $graphics.FillRectangle($overlay, 0, 0, $Width, $Height)
            }
            finally {
                $overlay.Dispose()
            }

            if ($Splash) {
                $logoBounds = [System.Drawing.RectangleF]::new(82, 72, 456, 456)
                $titleX = 590
                $titleY = 218
                $titleSize = 58
                $subtitleSize = 24
            }
            else {
                $logoBounds = [System.Drawing.RectangleF]::new(18, 18, 264, 264)
                $titleX = 310
                $titleY = 96
                $titleSize = 34
                $subtitleSize = 16
            }

            Draw-ImageContain -Graphics $graphics -Image $Logo -Bounds $logoBounds
            $titleFont = [System.Drawing.Font]::new('Segoe UI', $titleSize, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
            $subtitleFont = [System.Drawing.Font]::new('Segoe UI', $subtitleSize, [System.Drawing.FontStyle]::Regular, [System.Drawing.GraphicsUnit]::Pixel)
            $titleBrush = [System.Drawing.SolidBrush]::new([System.Drawing.ColorTranslator]::FromHtml('#EEF5F4'))
            $accentBrush = [System.Drawing.SolidBrush]::new([System.Drawing.ColorTranslator]::FromHtml('#35D8DF'))
            try {
                $graphics.DrawString('EDMG Studio', $titleFont, $titleBrush, [single]$titleX, [single]$titleY)
                $graphics.DrawString('Music-reactive AI video studio', $subtitleFont, $accentBrush, [single]$titleX, [single]($titleY + $titleSize + 10))
            }
            finally {
                $titleFont.Dispose()
                $subtitleFont.Dispose()
                $titleBrush.Dispose()
                $accentBrush.Dispose()
            }
        }
        finally {
            $graphics.Dispose()
        }
        $bitmap.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
    }
    finally {
        $bitmap.Dispose()
    }
}

New-Item -ItemType Directory -Path $brandRoot -Force | Out-Null

$logoSource = Join-Path $electronRoot 'public\studio-logo.png'
$backgroundSource = Join-Path $electronRoot 'public\studio-background.jpg'
$workspaceSource = Join-Path $electronRoot 'public\workspace-flair.jpg'
$iconSource = Join-Path $electronRoot 'electron-resources\app-icon.ico'

foreach ($source in @($logoSource, $backgroundSource, $workspaceSource, $iconSource)) {
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Required EDMG source asset is missing: $source"
    }
}

$brandCopies = @{
    $logoSource = (Join-Path $brandRoot 'StudioLogo.png')
    $backgroundSource = (Join-Path $brandRoot 'StudioBackground.jpg')
    $workspaceSource = (Join-Path $brandRoot 'WorkspaceFlair.jpg')
}
foreach ($entry in $brandCopies.GetEnumerator()) {
    Assert-AssetTarget -Path $entry.Value
    Copy-Item -LiteralPath $entry.Key -Destination $entry.Value -Force
}

$appIconTarget = Join-Path $assetRoot 'AppIcon.ico'
Assert-AssetTarget -Path $appIconTarget
Copy-Item -LiteralPath $iconSource -Destination $appIconTarget -Force

$logo = [System.Drawing.Image]::FromFile($logoSource)
$background = [System.Drawing.Image]::FromFile($backgroundSource)
try {
    Save-SquareLogo -Logo $logo -Size 300 -Path (Join-Path $assetRoot 'Square150x150Logo.scale-200.png')
    Save-SquareLogo -Logo $logo -Size 88 -Path (Join-Path $assetRoot 'Square44x44Logo.scale-200.png') -PaddingRatio 0.02
    Save-SquareLogo -Logo $logo -Size 24 -Path (Join-Path $assetRoot 'Square44x44Logo.targetsize-24_altform-unplated.png') -PaddingRatio 0
    Save-SquareLogo -Logo $logo -Size 48 -Path (Join-Path $assetRoot 'Square44x44Logo.targetsize-48_altform-lightunplated.png') -PaddingRatio 0
    Save-SquareLogo -Logo $logo -Size 50 -Path (Join-Path $assetRoot 'StoreLogo.png') -PaddingRatio 0.02
    Save-SquareLogo -Logo $logo -Size 48 -Path (Join-Path $assetRoot 'LockScreenLogo.scale-200.png') -PaddingRatio 0.02
    Save-BrandedWideAsset -Logo $logo -Background $background -Width 620 -Height 300 -Path (Join-Path $assetRoot 'Wide310x150Logo.scale-200.png') -Splash $false
    Save-BrandedWideAsset -Logo $logo -Background $background -Width 1240 -Height 600 -Path (Join-Path $assetRoot 'SplashScreen.scale-200.png') -Splash $true
}
finally {
    $logo.Dispose()
    $background.Dispose()
}

Write-Host "Generated EDMG Studio WinUI assets in $assetRoot"
