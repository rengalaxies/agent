# Export a PPTX to PDF and one PNG per slide with Microsoft PowerPoint (Windows).
# Usage: powershell -File export_pdf.ps1 <deck.pptx> <out.pdf> <preview-dir>
param([string]$Deck, [string]$Pdf, [string]$Preview)
$ErrorActionPreference = 'Stop'
$app = New-Object -ComObject PowerPoint.Application
try {
    $doc = $app.Presentations.Open((Resolve-Path $Deck).Path, $true, $false, $false)
    $doc.SaveAs([IO.Path]::GetFullPath($Pdf), 32)  # ppSaveAsPDF
    New-Item -ItemType Directory -Force $Preview | Out-Null
    foreach ($slide in $doc.Slides) {
        $slide.Export([IO.Path]::GetFullPath((Join-Path $Preview ("slide-{0}.png" -f $slide.SlideIndex))), 'PNG', 1280, 720)
    }
    $doc.Close()
} finally {
    $app.Quit()
}
