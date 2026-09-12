package kz.almas.remote;

import android.Manifest;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.media.projection.MediaProjectionManager;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.view.Gravity;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.net.Inet4Address;
import java.net.NetworkInterface;
import java.security.SecureRandom;
import java.util.Collections;

public class MainActivity extends Activity {
    private static final int CAPTURE_REQUEST = 44;
    private static final String PREFS = "almas_remote";
    private static final String KEY_PIN = "pair_pin";
    private TextView status;
    private TextView rootStatus;
    private String pin;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 200);
        }

        SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        pin = prefs.getString(KEY_PIN, null);
        if (pin == null || pin.length() != 6) {
            pin = String.format("%06d", new SecureRandom().nextInt(1_000_000));
            prefs.edit().putString(KEY_PIN, pin).apply();
        }
        buildUi();
    }

    private void buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(36, 24, 36, 24);
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        root.setBackgroundColor(Color.rgb(20, 20, 24));

        TextView title = text("ALMAS REMOTE HOST V2.2", 28, Color.WHITE);
        title.setGravity(Gravity.CENTER);
        root.addView(title, fullWrap());

        TextView ip = text("Телефон IP: " + getLocalIp() + "\nVideo: 5050   Control: 5051", 19, Color.LTGRAY);
        ip.setGravity(Gravity.CENTER);
        ip.setPadding(0, 18, 0, 10);
        root.addView(ip, fullWrap());

        TextView pinView = text("PAIR PIN: " + pin, 26, Color.WHITE);
        pinView.setGravity(Gravity.CENTER);
        pinView.setPadding(0, 12, 0, 18);
        root.addView(pinView, fullWrap());

        Button rootBtn = button("0. ROOT MODE қосу (Magisk Grant)");
        rootBtn.setOnClickListener(v -> requestRoot());
        root.addView(rootBtn, fullWrap());

        rootStatus = text("ROOT: тексерілмеген", 16, Color.LTGRAY);
        rootStatus.setGravity(Gravity.CENTER);
        root.addView(rootStatus, fullWrap());

        Button access = button("1. Басқару рұқсатын ашу (Accessibility)");
        access.setOnClickListener(v -> startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)));
        root.addView(access, fullWrap());

        Button start = button("2. Экранды бөлісуді бастау");
        start.setOnClickListener(v -> requestProjection());
        root.addView(start, fullWrap());

        Button stop = button("Серверді тоқтату");
        stop.setOnClickListener(v -> {
            stopService(new Intent(this, RemoteService.class));
            status.setText("Сервер тоқтатылды.");
        });
        root.addView(stop, fullWrap());

        status = text("Алдымен ROOT рұқсатын бер, Accessibility қос, кейін экранды бөлісуді баста.", 17, Color.LTGRAY);
        status.setPadding(0, 18, 0, 0);
        status.setGravity(Gravity.CENTER);
        root.addView(status, fullWrap());

        TextView warning = text("ROOT тек сен Magisk-та Grant басқанда беріледі. /dev/uinput табылса, келесі input backend соны пайдалана алады.", 14, Color.GRAY);
        warning.setPadding(0, 12, 0, 0);
        warning.setGravity(Gravity.CENTER);
        root.addView(warning, fullWrap());
        setContentView(root);
    }

    private void requestRoot() {
        rootStatus.setText("ROOT: Magisk рұқсатын күтіп тұр...");
        status.setText("Magisk терезесі шықса — Grant / Разрешить бас.");
        new Thread(() -> {
            RootBridge.Status s = RootBridge.probeInteractive();
            runOnUiThread(() -> {
                if (s.root) {
                    rootStatus.setText(s.uinput ? "ROOT: ON ✅   /dev/uinput: BAR ✅" : "ROOT: ON ✅   /dev/uinput: ЖОҚ");
                    status.setText(s.uinput
                            ? "Root дайын. uinput табылды — kernel-level input backend жасауға болады."
                            : "Root дайын. Touchpad fallback жұмыс істейді; uinput жоқ болса Accessibility backend қолданылады.");
                } else {
                    rootStatus.setText("ROOT: OFF ❌");
                    status.setText("Root берілмеді. Magisk-та Almas Remote Host үшін Grant таңда.");
                }
            });
        }, "root-probe").start();
    }

    private void requestProjection() {
        MediaProjectionManager mpm = (MediaProjectionManager) getSystemService(Context.MEDIA_PROJECTION_SERVICE);
        startActivityForResult(mpm.createScreenCaptureIntent(), CAPTURE_REQUEST);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == CAPTURE_REQUEST && resultCode == RESULT_OK && data != null) {
            stopService(new Intent(this, RemoteService.class));

            Intent i = new Intent(this, RemoteService.class);
            i.putExtra("resultCode", resultCode);
            i.putExtra("projectionData", data);
            i.putExtra("pin", pin);
            if (Build.VERSION.SDK_INT >= 26) startForegroundService(i); else startService(i);
            status.setText("Сервер іске қосылды. Ноутбуктан осы IP + PIN арқылы қосыл.");
        } else if (requestCode == CAPTURE_REQUEST) {
            status.setText("Экранды бөлісуге рұқсат берілмеді.");
        }
    }

    private static LinearLayout.LayoutParams fullWrap() {
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        p.setMargins(0, 7, 0, 7);
        return p;
    }

    private TextView text(String s, int sp, int color) {
        TextView t = new TextView(this);
        t.setText(s); t.setTextSize(sp); t.setTextColor(color);
        return t;
    }

    private Button button(String s) {
        Button b = new Button(this); b.setText(s); b.setAllCaps(false); return b;
    }

    private String getLocalIp() {
        try {
            for (NetworkInterface nif : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                for (java.net.InetAddress a : Collections.list(nif.getInetAddresses())) {
                    if (!a.isLoopbackAddress() && a instanceof Inet4Address) return a.getHostAddress();
                }
            }
        } catch (Exception ignored) {}
        return "IP табылмады";
    }
}
