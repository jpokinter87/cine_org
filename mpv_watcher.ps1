$queueFile = "C:\Apps\mpv_queue.txt"
Write-Host "mpv watcher actif - en attente..."
while ($true) {
    if (Test-Path $queueFile) {
        $path = (Get-Content $queueFile -Raw -Encoding UTF8).Trim()
        Remove-Item $queueFile
        if ($path) {
            Write-Host "Lecture: $path"
            Start-Process "c:\Apps\mpv\mpv.exe" -ArgumentList "--fs","`"$path`""
        }
    }
    Start-Sleep -Milliseconds 500
}
