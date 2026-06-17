Set-Location "e:\我熬篮球"
$port = 8765
# mirror
$dest = "$env:USERPROFILE\woao_dashboard"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item -Force "docs\index.html","docs\data.json" -Destination $dest -ErrorAction SilentlyContinue
Set-Location $dest
Start-Process "http://127.0.0.1:$port/index.html"
python -m http.server $port
