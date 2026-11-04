# IncidentFlow promo video

Remotion project + Playwright filming script for the ~90 s IncidentFlow presentation video.
Design: `../docs/superpowers/specs/2026-11-04-promo-video-design.md`.

```powershell
npm install
npx playwright install chromium
npm test            # unit tests (timeline, callouts, architecture facts)
npm run studio      # preview in the browser
```

Footage (`footage/`, `public/take*`) and renders (`out/`) are git-ignored: raw takes can contain
sensitive frames.
