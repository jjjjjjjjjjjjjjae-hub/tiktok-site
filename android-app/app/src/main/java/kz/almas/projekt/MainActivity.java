package kz.almas.projekt;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.KeyguardManager;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.SslErrorHandler;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.ProgressBar;

import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.security.MessageDigest;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

public class MainActivity extends Activity {
    private static final String HOME_URL =
            "https://jjjjjjjjjjjjjjae-hub.github.io/tiktok-site/";
    private static final String ALLOWED_HOST = "jjjjjjjjjjjjjjae-hub.github.io";
    private static final String ALLOWED_PATH = "/tiktok-site";
    private static final int FILE_CHOOSER_REQUEST = 1001;
    private static final int DEVICE_UNLOCK_REQUEST = 1002;
    private static final String SESSION_PREFS = "almas_secure_session";
    private static final String SESSION_VALUE = "encrypted_value";
    private static final String SESSION_KEY_ALIAS = "almas_session_key_v1";

    private WebView webView;
    private ProgressBar progressBar;
    private ValueCallback<Uri[]> fileUploadCallback;
    private boolean deviceUnlockInProgress;
    private boolean nativeBridgeAttached;

    @Override
    @SuppressLint("SetJavaScriptEnabled")
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        WebView.setWebContentsDebuggingEnabled(false);
        enterImmersiveMode();

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);

        webView = new WebView(this);
        webView.setBackgroundColor(Color.BLACK);
        root.addView(webView, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));

        progressBar = new ProgressBar(this);
        FrameLayout.LayoutParams progressParams = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.CENTER);
        root.addView(progressBar, progressParams);
        setContentView(root);

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(true);
        settings.setBuiltInZoomControls(false);
        settings.setDisplayZoomControls(false);
        settings.setSupportZoom(false);
        settings.setUseWideViewPort(true);
        settings.setLoadWithOverviewMode(true);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setSupportMultipleWindows(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            settings.setSafeBrowsingEnabled(true);
        }

        CookieManager cookieManager = CookieManager.getInstance();
        cookieManager.setAcceptCookie(true);
        cookieManager.setAcceptThirdPartyCookies(webView, true);

        webView.setWebViewClient(new LockedWebViewClient());
        webView.setWebChromeClient(new AppWebChromeClient());
        attachNativeBridge();

        if (savedInstanceState == null) {
            webView.loadUrl(HOME_URL);
        } else {
            webView.restoreState(savedInstanceState);
        }
    }

    private boolean isAllowedUrl(Uri uri) {
        if (uri == null || !"https".equalsIgnoreCase(uri.getScheme())) {
            return false;
        }
        if (!ALLOWED_HOST.equalsIgnoreCase(uri.getHost())) {
            return false;
        }
        String path = uri.getPath();
        return path != null && (path.equals(ALLOWED_PATH)
                || path.startsWith(ALLOWED_PATH + "/"));
    }

    private boolean isAuthPage(Uri uri) {
        if (!isAllowedUrl(uri)) {
            return false;
        }
        String path = uri.getPath();
        return ALLOWED_PATH.equals(path)
                || (ALLOWED_PATH + "/").equals(path)
                || (ALLOWED_PATH + "/index.html").equals(path);
    }

    private void attachNativeBridge() {
        if (webView != null && !nativeBridgeAttached) {
            webView.addJavascriptInterface(new NativeBridge(), "AlmasNative");
            nativeBridgeAttached = true;
        }
    }

    private void detachNativeBridge() {
        if (webView != null && nativeBridgeAttached) {
            webView.removeJavascriptInterface("AlmasNative");
            nativeBridgeAttached = false;
        }
    }

    private void showConnectionError() {
        String html = "<!doctype html><html lang='kk'><head>"
                + "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                + "<style>html,body{height:100%;margin:0;background:#050505;color:#fff;"
                + "font-family:sans-serif}body{display:grid;place-items:center;text-align:center}"
                + ".box{padding:24px}a{display:inline-block;margin-top:16px;padding:12px 22px;"
                + "border-radius:999px;background:#25f4ee;color:#050505;text-decoration:none;"
                + "font-weight:700}</style></head><body><div class='box'>"
                + "<h2>Қосылу қатесі</h2><p>Интернетті тексеріп, қайта көріңіз.</p>"
                + "<a href='" + HOME_URL + "'>Қайта көру</a>"
                + "</div></body></html>";
        webView.loadDataWithBaseURL(HOME_URL, html, "text/html", "UTF-8", null);
    }

    private void enterImmersiveMode() {
        getWindow().setStatusBarColor(Color.BLACK);
        getWindow().setNavigationBarColor(Color.BLACK);
        getWindow().getDecorView().setSystemUiVisibility(
                View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                        | View.SYSTEM_UI_FLAG_FULLSCREEN
                        | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                        | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_LAYOUT_STABLE);
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) {
            enterImmersiveMode();
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        enterImmersiveMode();
        if (webView != null) {
            webView.onResume();
        }
    }

    @Override
    protected void onPause() {
        if (webView != null) {
            webView.onPause();
        }
        super.onPause();
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        if (webView != null) {
            webView.saveState(outState);
        }
        super.onSaveInstanceState(outState);
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else if (webView != null) {
            webView.loadUrl(HOME_URL);
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == DEVICE_UNLOCK_REQUEST) {
            deviceUnlockInProgress = false;
            notifyDeviceUnlock(resultCode == RESULT_OK);
            return;
        }
        if (requestCode == FILE_CHOOSER_REQUEST && fileUploadCallback != null) {
            Uri[] result = WebChromeClient.FileChooserParams.parseResult(resultCode, data);
            fileUploadCallback.onReceiveValue(result);
            fileUploadCallback = null;
            return;
        }
        super.onActivityResult(requestCode, resultCode, data);
    }

    @Override
    protected void onDestroy() {
        if (fileUploadCallback != null) {
            fileUploadCallback.onReceiveValue(null);
            fileUploadCallback = null;
        }
        if (webView != null) {
            webView.stopLoading();
            detachNativeBridge();
            webView.setWebChromeClient(null);
            webView.setWebViewClient(null);
            webView.destroy();
            webView = null;
        }
        super.onDestroy();
    }

    private void notifyDeviceUnlock(boolean success) {
        if (webView == null) {
            return;
        }
        webView.post(() -> webView.evaluateJavascript(
                "window.AlmasApp&&window.AlmasApp.onDeviceUnlock(" + success + ");",
                null));
    }

    private String getStableDeviceId() {
        try {
            String androidId = Settings.Secure.getString(
                    getContentResolver(),
                    Settings.Secure.ANDROID_ID);
            String source = getPackageName() + ":" + String.valueOf(androidId);
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(source.getBytes(StandardCharsets.UTF_8));
            return Base64.encodeToString(
                    digest,
                    Base64.URL_SAFE | Base64.NO_WRAP | Base64.NO_PADDING);
        } catch (Exception error) {
            return "";
        }
    }

    private SecretKey getOrCreateSessionKey() throws Exception {
        KeyStore keyStore = KeyStore.getInstance("AndroidKeyStore");
        keyStore.load(null);
        if (keyStore.containsAlias(SESSION_KEY_ALIAS)) {
            return (SecretKey) keyStore.getKey(SESSION_KEY_ALIAS, null);
        }

        KeyGenerator keyGenerator = KeyGenerator.getInstance(
                KeyProperties.KEY_ALGORITHM_AES,
                "AndroidKeyStore");
        keyGenerator.init(new KeyGenParameterSpec.Builder(
                SESSION_KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .build());
        return keyGenerator.generateKey();
    }

    private String encryptSession(String plaintext) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateSessionKey());
        byte[] encrypted = cipher.doFinal(plaintext.getBytes(StandardCharsets.UTF_8));
        return Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP)
                + "."
                + Base64.encodeToString(encrypted, Base64.NO_WRAP);
    }

    private String decryptSession(String packed) throws Exception {
        String[] parts = packed.split("\\.", 2);
        if (parts.length != 2) {
            throw new IllegalArgumentException("Invalid session payload");
        }
        byte[] iv = Base64.decode(parts[0], Base64.NO_WRAP);
        byte[] encrypted = Base64.decode(parts[1], Base64.NO_WRAP);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(
                Cipher.DECRYPT_MODE,
                getOrCreateSessionKey(),
                new GCMParameterSpec(128, iv));
        return new String(cipher.doFinal(encrypted), StandardCharsets.UTF_8);
    }

    private final class NativeBridge {
        @JavascriptInterface
        public String getDeviceId() {
            return getStableDeviceId();
        }

        @JavascriptInterface
        public boolean isDeviceSecure() {
            KeyguardManager keyguardManager =
                    (KeyguardManager) getSystemService(Context.KEYGUARD_SERVICE);
            return keyguardManager != null && keyguardManager.isDeviceSecure();
        }

        @JavascriptInterface
        public void requestDeviceUnlock() {
            runOnUiThread(() -> {
                if (deviceUnlockInProgress) {
                    return;
                }

                KeyguardManager keyguardManager =
                        (KeyguardManager) getSystemService(Context.KEYGUARD_SERVICE);
                if (keyguardManager == null || !keyguardManager.isDeviceSecure()) {
                    notifyDeviceUnlock(false);
                    return;
                }

                Intent unlockIntent = keyguardManager.createConfirmDeviceCredentialIntent(
                        "almas projekt",
                        "Ойынға кіру үшін телефон құлпын растаңыз");
                if (unlockIntent == null) {
                    notifyDeviceUnlock(false);
                    return;
                }

                try {
                    deviceUnlockInProgress = true;
                    startActivityForResult(unlockIntent, DEVICE_UNLOCK_REQUEST);
                } catch (ActivityNotFoundException error) {
                    deviceUnlockInProgress = false;
                    notifyDeviceUnlock(false);
                }
            });
        }

        @JavascriptInterface
        public void saveSession(String sessionJson) {
            if (sessionJson == null || sessionJson.length() > 8192) {
                return;
            }
            try {
                getSharedPreferences(SESSION_PREFS, MODE_PRIVATE)
                        .edit()
                        .putString(SESSION_VALUE, encryptSession(sessionJson))
                        .apply();
            } catch (Exception error) {
                clearSession();
            }
        }

        @JavascriptInterface
        public String getSession() {
            SharedPreferences preferences =
                    getSharedPreferences(SESSION_PREFS, MODE_PRIVATE);
            String encrypted = preferences.getString(SESSION_VALUE, "");
            if (encrypted == null || encrypted.isEmpty()) {
                return "";
            }
            try {
                return decryptSession(encrypted);
            } catch (Exception error) {
                clearSession();
                return "";
            }
        }

        @JavascriptInterface
        public void clearSession() {
            getSharedPreferences(SESSION_PREFS, MODE_PRIVATE)
                    .edit()
                    .remove(SESSION_VALUE)
                    .apply();
        }
    }

    private final class LockedWebViewClient extends WebViewClient {
        @Override
        public void onPageStarted(WebView view, String url, Bitmap favicon) {
            if (isAuthPage(Uri.parse(url))) {
                attachNativeBridge();
            } else {
                detachNativeBridge();
            }
            super.onPageStarted(view, url, favicon);
        }

        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            return !isAllowedUrl(request.getUrl());
        }

        @Override
        public boolean shouldOverrideUrlLoading(WebView view, String url) {
            return !isAllowedUrl(Uri.parse(url));
        }

        @Override
        public void onReceivedError(
                WebView view,
                WebResourceRequest request,
                WebResourceError error) {
            if (request.isForMainFrame()) {
                showConnectionError();
            }
        }

        @Override
        public void onReceivedSslError(
                WebView view,
                SslErrorHandler handler,
                SslError error) {
            handler.cancel();
            showConnectionError();
        }
    }

    private final class AppWebChromeClient extends WebChromeClient {
        @Override
        public void onProgressChanged(WebView view, int newProgress) {
            progressBar.setVisibility(newProgress < 100 ? View.VISIBLE : View.GONE);
        }

        @Override
        public boolean onShowFileChooser(
                WebView view,
                ValueCallback<Uri[]> callback,
                FileChooserParams params) {
            if (fileUploadCallback != null) {
                fileUploadCallback.onReceiveValue(null);
            }
            fileUploadCallback = callback;
            try {
                startActivityForResult(params.createIntent(), FILE_CHOOSER_REQUEST);
                return true;
            } catch (ActivityNotFoundException error) {
                fileUploadCallback = null;
                callback.onReceiveValue(null);
                return false;
            }
        }
    }
}
