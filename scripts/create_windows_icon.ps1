param(
  [Parameter(Mandatory = $true)]
  [string]$OutputPath
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

function New-RoundedRectanglePath([float]$x, [float]$y, [float]$width, [float]$height, [float]$radius) {
  $path = New-Object System.Drawing.Drawing2D.GraphicsPath
  $diameter = $radius * 2
  $path.AddArc($x, $y, $diameter, $diameter, 180, 90)
  $path.AddArc($x + $width - $diameter, $y, $diameter, $diameter, 270, 90)
  $path.AddArc($x + $width - $diameter, $y + $height - $diameter, $diameter, $diameter, 0, 90)
  $path.AddArc($x, $y + $height - $diameter, $diameter, $diameter, 90, 90)
  $path.CloseFigure()
  return $path
}

function New-IconPng([int]$size) {
  $bitmap = New-Object System.Drawing.Bitmap($size, $size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
  $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
  $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
  $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
  $graphics.Clear([System.Drawing.Color]::Transparent)
  $graphics.ScaleTransform($size / 256.0, $size / 256.0)

  $backgroundPath = New-RoundedRectanglePath 12 12 232 232 48
  $backgroundBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 17, 24, 39))
  $graphics.FillPath($backgroundBrush, $backgroundPath)

  $knightPoints = [System.Drawing.PointF[]]@(
    [System.Drawing.PointF]::new(54, 202),
    [System.Drawing.PointF]::new(67, 174),
    [System.Drawing.PointF]::new(87, 151),
    [System.Drawing.PointF]::new(89, 127),
    [System.Drawing.PointF]::new(101, 103),
    [System.Drawing.PointF]::new(121, 84),
    [System.Drawing.PointF]::new(116, 61),
    [System.Drawing.PointF]::new(136, 42),
    [System.Drawing.PointF]::new(163, 47),
    [System.Drawing.PointF]::new(187, 65),
    [System.Drawing.PointF]::new(174, 75),
    [System.Drawing.PointF]::new(158, 68),
    [System.Drawing.PointF]::new(162, 91),
    [System.Drawing.PointF]::new(182, 106),
    [System.Drawing.PointF]::new(196, 130),
    [System.Drawing.PointF]::new(187, 153),
    [System.Drawing.PointF]::new(169, 166),
    [System.Drawing.PointF]::new(170, 194),
    [System.Drawing.PointF]::new(198, 194),
    [System.Drawing.PointF]::new(207, 211),
    [System.Drawing.PointF]::new(48, 211)
  )
  $knightPath = New-Object System.Drawing.Drawing2D.GraphicsPath
  $knightPath.AddPolygon($knightPoints)
  $knightBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 236, 253, 245))
  $graphics.FillPath($knightBrush, $knightPath)

  $eyeBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 16, 185, 129))
  $graphics.FillEllipse($eyeBrush, 143, 82, 9, 9)

  $memory = New-Object System.IO.MemoryStream
  $bitmap.Save($memory, [System.Drawing.Imaging.ImageFormat]::Png)
  $png = $memory.ToArray()
  $memory.Dispose()
  $eyeBrush.Dispose()
  $knightBrush.Dispose()
  $knightPath.Dispose()
  $backgroundBrush.Dispose()
  $backgroundPath.Dispose()
  $graphics.Dispose()
  $bitmap.Dispose()
  return ,$png
}

$sizes = @(16, 24, 32, 48, 64, 128, 256)
$images = @($sizes | ForEach-Object { New-IconPng $_ })
$headerSize = 6
$entrySize = 16
$offset = $headerSize + ($entrySize * $images.Count)
$stream = New-Object System.IO.MemoryStream
$writer = New-Object System.IO.BinaryWriter($stream)
$writer.Write([UInt16]0)
$writer.Write([UInt16]1)
$writer.Write([UInt16]$images.Count)

for ($i = 0; $i -lt $images.Count; $i++) {
  $size = $sizes[$i]
  $png = [byte[]]$images[$i]
  $writer.Write([byte]$(if ($size -eq 256) { 0 } else { $size }))
  $writer.Write([byte]$(if ($size -eq 256) { 0 } else { $size }))
  $writer.Write([byte]0)
  $writer.Write([byte]0)
  $writer.Write([UInt16]1)
  $writer.Write([UInt16]32)
  $writer.Write([UInt32]$png.Length)
  $writer.Write([UInt32]$offset)
  $offset += $png.Length
}
foreach ($png in $images) {
  $writer.Write([byte[]]$png)
}

$directory = Split-Path -Parent $OutputPath
if (!(Test-Path -LiteralPath $directory)) {
  New-Item -ItemType Directory -Path $directory -Force | Out-Null
}
[System.IO.File]::WriteAllBytes($OutputPath, $stream.ToArray())
$writer.Dispose()
$stream.Dispose()
Write-Output "Generated multi-size Windows icon: $OutputPath"
