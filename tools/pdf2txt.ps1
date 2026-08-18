# Extract text from a PDF using the installed Word COM automation.
# Usage: powershell -File pdf2txt.ps1 -Pdf <in.pdf> -Out <out.txt>
param(
    [Parameter(Mandatory = $true)][string]$Pdf,
    [Parameter(Mandatory = $true)][string]$Out
)

$ErrorActionPreference = 'Stop'
$pdfFull = (Resolve-Path -LiteralPath $Pdf).Path
$outFull = [System.IO.Path]::GetFullPath($Out)

$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0

try {
    # Open the PDF read-only; Word converts it to a document model on load.
    # Args: FileName, ConfirmConversions=$false, ReadOnly=$true
    $doc = $word.Documents.Open($pdfFull, $false, $true)
    # wdFormatUnicodeText = 7
    $doc.SaveAs2($outFull, 7)
    # wdDoNotSaveChanges = 0
    $doc.Close(0)
    Write-Output "OK -> $outFull"
}
finally {
    $word.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
}
