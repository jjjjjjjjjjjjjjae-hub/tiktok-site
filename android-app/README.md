# almas projekt

Android WebView application for:

`https://jjjjjjjjjjjjjjae-hub.github.io/tiktok-site/`

The app is locked to landscape, uses an immersive full-screen WebView, has no address/search bar, blocks navigation away from the configured GitHub Pages site, and supports the site's `.almasinvite` file picker.

Version 1.1 adds a restricted JavaScript bridge on the sign-in page only. It can confirm the phone PIN/pattern lock, derive an app-specific device identifier, and store the account session encrypted with Android Keystore. The bridge is removed before the stadium page and its third-party viewer load.

## APK build

Open the repository's **Actions** tab, choose **Build almas projekt APK**, then choose **Run workflow**. Download `almas-projekt-apk` from the completed run's Artifacts section.

Changes under `android-app` are checked automatically with the same APK build.
