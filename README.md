# RugBuster Live Desk — Windows patrol prototype

**Chrome repair update:** The extension's scanner was restored as version 0.2.1. Chrome-to-Desk following is temporarily disabled while its integration fault is investigated. Use the extension's normal right-click Scan. Do not follow the pairing instructions below or load version 0.2.0. Desktop tracking, history, prices and patrol remain available.

The wordmark uses the site's Orbitron weight/spacing and exact purple → cyan → green gradient. The supplied shield remains the Windows tray icon.

## Windows program

Ready copy: `%LOCALAPPDATA%/RugBuster/Live Desk/Program/RugBuster Live Desk.exe`, with a desktop shortcut. X hides the app in the tray. Tray click opens it; right-click offers Hide/Quit. Starting another instance brings the existing one forward. Windows can put the shield under its hidden-icons arrow. Automatic start at sign-in is not configured.

Data and logs stay beside the Program folder, so updating the program preserves the watchlist. Keep `_internal` beside the portable exe. Microsoft Edge WebView2 is required and already available on this PC. No Python installation is needed for the built app.

## Connect Chrome once

1. In Live Desk press **Connect Chrome** to reveal the pairing code.
2. In Chrome open `chrome://extensions`, enable Developer mode, and load/reload the `rugbuster-chrome-extension` folder. Alternatively unpack `rugbuster-live-desk-extension-0.2.0.zip` first and load that folder.
3. Open the extension, paste the code under **Live Desk / Windows**, press **Connect**, and accept Chrome's supported-site permissions.
4. Open a supported Solana token page. The desktop shows its last browser token and last-seen time. **Keep under patrol** saves it for continued tracking. **Send token** in the extension retries manually.

This activation has not been performed in your Chrome profile. Supported exact routes: pump.fun coins (including language prefixes), Solscan tokens, Birdeye Solana tokens, GMGN Solana tokens, Jupiter tokens, DexScreener Solana pairs. Pairs resolve through DexScreener; they are not treated as token addresses. No page text or full browsing URLs are sent to the desktop. Incognito tabs are skipped. Disconnect disables following, deletes the saved pairing code and removes optional host grants. It does not stop tokens you explicitly saved under patrol.

## What works

- Preview tokens from the browser before saving them.
- Local SQLite watchlist, up to 20 tokens; original baseline remains unchanged on refresh.
- Risk score/category, creator status and creator share changes are recorded. Duplicate responses do not create duplicate events. Up to 200 events per token retained; latest 30 displayed.
- Removing a token clears its baseline/history; tracking it again starts a new baseline.
- Patrol checks the existing `/score` API every five minutes while the program runs. On/Paused persists between restarts. Dashboard refreshes only read local data. Failed requests retain data and wait five minutes before retrying.
- Tray notifications report newly retrieved API changes after startup.
- Price batch refresh every 60 seconds via DexScreener, including the browser preview. Old quotes retain their timestamps and show STALE after 120 seconds.
- Authenticated loopback browser bridge; origin/host validation; separate local UI token and persistent extension pairing code.
- Design demo uses labeled illustrative values and makes no API calls for those examples.

API evidence may be cached. Retrieval time is separate from observation time. A lower creator balance alone does not prove a sale. Creator exit/high-risk display states reflect API findings, not independent real-time blockchain verification. No direct Helius/RPC calls were added to the desktop, but backend refresh and HTTP requests are not guaranteed cost-free. For distribution, replace independent client polling with shared backend events.

Phone/web watchlist synchronization and TURMO USB output are still pending. The screen is not recognized by Windows, so the app shows a display preview. The browser bridge is tested with HTTP integration and mocked extension APIs; the installed Chrome-to-app flow requires the activation above.

## Development and verification

`python -m unittest test_server test_desktop` from this folder; `node test-live-desk.mjs` from the extension folder. Fifteen Python tests cover data, baseline, pause/retry, pairing and tray lifecycle; JavaScript tests cover supported routes, payload, deduplication and disabled following. Build with `.venv/Scripts/python.exe -m PyInstaller` using `build-desktop.ps1`. Price chart and always-on-top miniwindow are not implemented in this increment.
