# Parse .env and set environment variables for the current process
Get-Content .env | Foreach-Object {
    if ($_ -match "^\s*([^#]\w*)\s*=\s*(.*)") {
        $name = $matches[1]
        $value = $matches[2]
        if ($value.StartsWith('"') -and $value.EndsWith('"')) {
            $value = $value.Substring(1, $value.Length - 2)
        } elseif ($value.StartsWith("'") -and $value.EndsWith("'")) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
}

$password = [Environment]::GetEnvironmentVariable("LAVALINK_SERVER_PASSWORD")
if ([string]::IsNullOrWhiteSpace($password)) {
    $password = "youshallnotpass"
}

Write-Host "Starting Lavalink in the background..."
cd LavaLink
Start-Process -FilePath "java" -ArgumentList "-jar", "Lavalink.jar" -NoNewWindow
cd ..

Write-Host "Waiting for Lavalink to become healthy..."
$lavalink_ready = $false
$max_retries = 30
$retry_count = 0

while (-not $lavalink_ready -and $retry_count -lt $max_retries) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8080/version" -Headers @{ "Authorization" = $password } -UseBasicParsing -ErrorAction Stop
        if ($response.StatusCode -eq 200) {
            $lavalink_ready = $true
            Write-Host "Lavalink is up and running!"
        }
    } catch {
        $retry_count++
        Write-Host "Waiting for Lavalink... (Attempt $retry_count/$max_retries)"
        Start-Sleep -Seconds 2
    }
}

if (-not $lavalink_ready) {
    Write-Host "Error: Lavalink failed to start within the expected time."
    exit 1
}

Write-Host "Starting Bot..."
.\.venv\Scripts\python.exe bot.py
