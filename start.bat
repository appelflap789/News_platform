@echo off
rem Opens the News Scraper Platform. Since 3 November 2026 it runs on the home server (jacob228), day and
rem night, and scrapes there by itself; this PC only opens its dashboard. The home Wi-Fi address is tried
rem first, then the Tailscale address (for when you are away; Tailscale must be on on this PC).
rem Running a copy on this PC instead: see "On the home server" in README.md.
setlocal
set PORT=8765
set ADDRESSES=192.168.1.161 100.75.117.66

for %%A in (%ADDRESSES%) do (
    curl.exe -sf -m 3 -o nul "http://%%A:%PORT%/api/stats"
    if not errorlevel 1 (
        start "" "http://%%A:%PORT%/"
        exit /b 0
    )
)

echo.
echo  The News Scraper Platform on the home server cannot be reached.
echo.
echo   - At home: is the server on, and is this PC on the home Wi-Fi?
echo   - Away from home: is Tailscale switched on on this PC?
echo.
echo  Tried: %ADDRESSES% (port %PORT%)
echo.
pause
