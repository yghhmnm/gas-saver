
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$syn = New-Object System.Speech.Synthesis.SpeechSynthesizer
$syn.SelectVoice('Microsoft Zira Desktop')
$syn.Rate = -1
$base = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($i in 1..6) {
  $txt = Get-Content -Raw -Encoding UTF8 (Join-Path $base "audio\s$i.txt")
  $syn.SetOutputToWaveFile((Join-Path $base "audio\s$i.wav"))
  $syn.Speak($txt)
}
$syn.SetOutputToNull()
$syn.Dispose()
Write-Output "tts done"
