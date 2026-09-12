package kz.almas.remote;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.graphics.Path;
import android.view.accessibility.AccessibilityEvent;

public class RemoteAccessibilityService extends AccessibilityService {
    private static volatile RemoteAccessibilityService instance;
    private static volatile String foregroundPackage = "";

    @Override public void onServiceConnected() { instance = this; }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        if (event == null) return;
        CharSequence pkg = event.getPackageName();
        if (pkg != null) foregroundPackage = pkg.toString();
    }

    @Override public void onInterrupt() {}
    @Override public void onDestroy() { if (instance == this) instance = null; super.onDestroy(); }

    public static String getForegroundPackage() {
        String p = foregroundPackage;
        return p == null ? "" : p;
    }

    public static boolean tap(float nx, float ny) {
        RemoteAccessibilityService s = instance;
        if (s == null) return false;
        int w = s.getResources().getDisplayMetrics().widthPixels;
        int h = s.getResources().getDisplayMetrics().heightPixels;
        Path p = new Path();
        p.moveTo(clamp(nx) * w, clamp(ny) * h);
        GestureDescription.StrokeDescription stroke = new GestureDescription.StrokeDescription(p, 0, 50);
        return s.dispatchGesture(new GestureDescription.Builder().addStroke(stroke).build(), null, null);
    }

    public static boolean swipe(float x1, float y1, float x2, float y2, long durationMs) {
        RemoteAccessibilityService s = instance;
        if (s == null) return false;
        int w = s.getResources().getDisplayMetrics().widthPixels;
        int h = s.getResources().getDisplayMetrics().heightPixels;
        Path p = new Path();
        p.moveTo(clamp(x1) * w, clamp(y1) * h);
        p.lineTo(clamp(x2) * w, clamp(y2) * h);
        long d = Math.max(80, Math.min(durationMs, 1200));
        GestureDescription.StrokeDescription stroke = new GestureDescription.StrokeDescription(p, 0, d);
        return s.dispatchGesture(new GestureDescription.Builder().addStroke(stroke).build(), null, null);
    }

    public static boolean dualSwipe(
            float x1, float y1, float x2, float y2,
            float x3, float y3, float x4, float y4,
            long durationMs) {
        RemoteAccessibilityService s = instance;
        if (s == null) return false;
        int w = s.getResources().getDisplayMetrics().widthPixels;
        int h = s.getResources().getDisplayMetrics().heightPixels;
        long d = Math.max(80, Math.min(durationMs, 1200));

        Path p1 = new Path();
        p1.moveTo(clamp(x1) * w, clamp(y1) * h);
        p1.lineTo(clamp(x2) * w, clamp(y2) * h);

        Path p2 = new Path();
        p2.moveTo(clamp(x3) * w, clamp(y3) * h);
        p2.lineTo(clamp(x4) * w, clamp(y4) * h);

        GestureDescription.StrokeDescription s1 = new GestureDescription.StrokeDescription(p1, 0, d);
        GestureDescription.StrokeDescription s2 = new GestureDescription.StrokeDescription(p2, 0, d);
        GestureDescription gesture = new GestureDescription.Builder()
                .addStroke(s1)
                .addStroke(s2)
                .build();
        return s.dispatchGesture(gesture, null, null);
    }

    private static float clamp(float v) { return Math.max(0f, Math.min(1f, v)); }
}
