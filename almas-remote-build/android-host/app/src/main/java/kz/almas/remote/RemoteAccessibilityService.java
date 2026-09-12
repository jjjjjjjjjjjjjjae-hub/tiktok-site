package kz.almas.remote;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.graphics.Path;
import android.os.Handler;
import android.view.accessibility.AccessibilityEvent;

import java.util.ArrayDeque;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * V2 input backend.
 *
 * One dispatcher owns every synthetic pointer.  This is the important bit:
 * joystick, held action buttons and direct touchpad drags are continued in the
 * SAME GestureDescription, so a jump/fire/camera gesture does not cancel the
 * movement pointer that is already down.
 */
public class RemoteAccessibilityService extends AccessibilityService {
    private static volatile RemoteAccessibilityService instance;
    private static volatile String foregroundPackage = "";

    private Handler main;
    private InputEngine engine;

    @Override
    public void onServiceConnected() {
        instance = this;
        main = new Handler(getMainLooper());
        engine = new InputEngine(this, main);
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        if (event == null) return;
        CharSequence pkg = event.getPackageName();
        if (pkg != null) foregroundPackage = pkg.toString();
    }

    @Override public void onInterrupt() {}

    @Override
    public void onDestroy() {
        if (engine != null) engine.cancelAll();
        if (instance == this) instance = null;
        super.onDestroy();
    }

    public static String getForegroundPackage() {
        String p = foregroundPackage;
        return p == null ? "" : p;
    }

    public static boolean isReady() {
        RemoteAccessibilityService s = instance;
        return s != null && s.engine != null;
    }

    public static void tap(float x, float y) {
        RemoteAccessibilityService s = instance;
        if (s != null && s.engine != null) s.engine.queueTap(x, y);
    }

    public static void swipe(float x1, float y1, float x2, float y2, long durationMs) {
        RemoteAccessibilityService s = instance;
        if (s != null && s.engine != null) s.engine.queueSwipe(x1, y1, x2, y2, durationMs);
    }

    public static void joystickDown(float cx, float cy, float tx, float ty) {
        RemoteAccessibilityService s = instance;
        if (s != null && s.engine != null) s.engine.pointerDown("joystick", cx, cy, tx, ty);
    }

    public static void joystickMove(float tx, float ty) {
        RemoteAccessibilityService s = instance;
        if (s != null && s.engine != null) s.engine.pointerMove("joystick", tx, ty);
    }

    public static void joystickUp() {
        RemoteAccessibilityService s = instance;
        if (s != null && s.engine != null) s.engine.pointerUp("joystick");
    }

    public static void directDown(float x, float y) {
        RemoteAccessibilityService s = instance;
        if (s != null && s.engine != null) s.engine.pointerDown("direct", x, y, x, y);
    }

    public static void directMove(float x, float y) {
        RemoteAccessibilityService s = instance;
        if (s != null && s.engine != null) s.engine.pointerMove("direct", x, y);
    }

    public static void directUp() {
        RemoteAccessibilityService s = instance;
        if (s != null && s.engine != null) s.engine.pointerUp("direct");
    }

    public static void holdDown(String id, float x, float y) {
        RemoteAccessibilityService s = instance;
        if (s != null && s.engine != null) s.engine.pointerDown("hold:" + id, x, y, x, y);
    }

    public static void holdUp(String id) {
        RemoteAccessibilityService s = instance;
        if (s != null && s.engine != null) s.engine.pointerUp("hold:" + id);
    }

    /** Camera is intentionally a transient swipe, not another forever-held pointer.
     * It is composed in the same gesture as the persistent joystick/hold pointers.
     */
    public static void cameraDelta(float anchorX, float anchorY, float dx, float dy) {
        RemoteAccessibilityService s = instance;
        if (s != null && s.engine != null) s.engine.queueCamera(anchorX, anchorY, dx, dy);
    }

    public static void cancelAll() {
        RemoteAccessibilityService s = instance;
        if (s != null && s.engine != null) s.engine.cancelAll();
    }

    public static boolean globalBack() {
        RemoteAccessibilityService s = instance;
        return s != null && s.performGlobalAction(GLOBAL_ACTION_BACK);
    }

    public static boolean globalHome() {
        RemoteAccessibilityService s = instance;
        return s != null && s.performGlobalAction(GLOBAL_ACTION_HOME);
    }

    public static boolean globalRecents() {
        RemoteAccessibilityService s = instance;
        return s != null && s.performGlobalAction(GLOBAL_ACTION_RECENTS);
    }

    private static final class PointerState {
        final String id;
        boolean desiredDown;
        boolean hasContinuation;
        float startX, startY;
        float x, y;
        float targetX, targetY;
        GestureDescription.StrokeDescription stroke;

        PointerState(String id) { this.id = id; }
    }

    private static final class TransientStroke {
        final float x1, y1, x2, y2;
        final long duration;
        TransientStroke(float x1, float y1, float x2, float y2, long duration) {
            this.x1 = x1; this.y1 = y1; this.x2 = x2; this.y2 = y2;
            this.duration = duration;
        }
    }

    private static final class InputEngine {
        private static final long CHUNK_MS = 34;
        private static final int MAX_TRANSIENT_QUEUE = 32;

        private final RemoteAccessibilityService service;
        private final Handler handler;
        private final Object lock = new Object();
        private final LinkedHashMap<String, PointerState> pointers = new LinkedHashMap<>();
        private final ArrayDeque<TransientStroke> transientQueue = new ArrayDeque<>();

        private boolean busy;
        private boolean pumpPosted;
        private float cameraAnchorX = 0.72f;
        private float cameraAnchorY = 0.50f;
        private float cameraDx;
        private float cameraDy;

        InputEngine(RemoteAccessibilityService service, Handler handler) {
            this.service = service;
            this.handler = handler;
        }

        void pointerDown(String id, float sx, float sy, float tx, float ty) {
            synchronized (lock) {
                PointerState p = pointer(id);
                p.startX = clamp(sx); p.startY = clamp(sy);
                p.targetX = clamp(tx); p.targetY = clamp(ty);
                if (!p.desiredDown) {
                    p.x = p.startX; p.y = p.startY;
                }
                p.desiredDown = true;
                postPumpLocked();
            }
        }

        void pointerMove(String id, float x, float y) {
            synchronized (lock) {
                PointerState p = pointer(id);
                p.targetX = clamp(x); p.targetY = clamp(y);
                if (!p.desiredDown) {
                    p.startX = p.targetX; p.startY = p.targetY;
                    p.x = p.targetX; p.y = p.targetY;
                    p.desiredDown = true;
                }
                postPumpLocked();
            }
        }

        void pointerUp(String id) {
            synchronized (lock) {
                PointerState p = pointers.get(id);
                if (p == null) return;
                p.desiredDown = false;
                postPumpLocked();
            }
        }

        void queueTap(float x, float y) {
            queueTransient(x, y, x, y, 46);
        }

        void queueSwipe(float x1, float y1, float x2, float y2, long durationMs) {
            queueTransient(x1, y1, x2, y2, Math.max(60, Math.min(durationMs, 500)));
        }

        void queueCamera(float anchorX, float anchorY, float dx, float dy) {
            synchronized (lock) {
                cameraAnchorX = clamp(anchorX);
                cameraAnchorY = clamp(anchorY);
                // Merge high-rate camera deltas; newest accumulated state wins.
                cameraDx = clampDelta(cameraDx + dx);
                cameraDy = clampDelta(cameraDy + dy);
                postPumpLocked();
            }
        }

        void cancelAll() {
            synchronized (lock) {
                for (PointerState p : pointers.values()) p.desiredDown = false;
                transientQueue.clear();
                cameraDx = cameraDy = 0f;
                postPumpLocked();
            }
        }

        private void queueTransient(float x1, float y1, float x2, float y2, long duration) {
            synchronized (lock) {
                while (transientQueue.size() >= MAX_TRANSIENT_QUEUE) transientQueue.pollFirst();
                transientQueue.addLast(new TransientStroke(
                        clamp(x1), clamp(y1), clamp(x2), clamp(y2), duration));
                postPumpLocked();
            }
        }

        private PointerState pointer(String id) {
            PointerState p = pointers.get(id);
            if (p == null) {
                p = new PointerState(id);
                pointers.put(id, p);
            }
            return p;
        }

        private void postPumpLocked() {
            if (pumpPosted || busy) return;
            pumpPosted = true;
            handler.post(this::pump);
        }

        private void pump() {
            final GestureDescription gesture;
            final boolean shouldContinue;
            synchronized (lock) {
                pumpPosted = false;
                if (busy) return;

                GestureDescription.Builder gb = new GestureDescription.Builder();
                int strokeCount = 0;

                // Persistent pointers (joystick, direct drag, held action buttons).
                for (Map.Entry<String, PointerState> e : pointers.entrySet()) {
                    PointerState p = e.getValue();
                    if (p.desiredDown) {
                        Path path = new Path();
                        GestureDescription.StrokeDescription next;
                        if (!p.hasContinuation || p.stroke == null) {
                            path.moveTo(pxX(p.startX), pxY(p.startY));
                            path.lineTo(pxX(p.targetX), pxY(p.targetY));
                            next = new GestureDescription.StrokeDescription(path, 0, CHUNK_MS, true);
                        } else {
                            path.moveTo(pxX(p.x), pxY(p.y));
                            path.lineTo(pxX(p.targetX), pxY(p.targetY));
                            next = p.stroke.continueStroke(path, 0, CHUNK_MS, true);
                        }
                        gb.addStroke(next);
                        strokeCount++;
                        p.stroke = next;
                        p.hasContinuation = true;
                        p.x = p.targetX; p.y = p.targetY;
                    } else if (p.hasContinuation && p.stroke != null) {
                        // Finish this logical finger cleanly instead of letting it get stuck.
                        Path path = new Path();
                        path.moveTo(pxX(p.x), pxY(p.y));
                        path.lineTo(pxX(p.x), pxY(p.y));
                        GestureDescription.StrokeDescription end =
                                p.stroke.continueStroke(path, 0, CHUNK_MS, false);
                        gb.addStroke(end);
                        strokeCount++;
                        p.stroke = null;
                        p.hasContinuation = false;
                    }
                    if (strokeCount >= 7) break; // Android max is larger; keep headroom for transients.
                }

                // One camera swipe per chunk. Repeated small swipes give effectively unbounded
                // camera rotation while preserving the joystick pointer in the same gesture.
                if (strokeCount < 8 && (Math.abs(cameraDx) > 0.0001f || Math.abs(cameraDy) > 0.0001f)) {
                    float dx = cameraDx;
                    float dy = cameraDy;
                    cameraDx = cameraDy = 0f;
                    float x2 = clamp(cameraAnchorX + dx);
                    float y2 = clamp(cameraAnchorY + dy);
                    Path cp = new Path();
                    cp.moveTo(pxX(cameraAnchorX), pxY(cameraAnchorY));
                    cp.lineTo(pxX(x2), pxY(y2));
                    gb.addStroke(new GestureDescription.StrokeDescription(cp, 0, CHUNK_MS, false));
                    strokeCount++;
                }

                // Add at most one tap/swipe per chunk to keep latency predictable.
                if (strokeCount < 9 && !transientQueue.isEmpty()) {
                    TransientStroke t = transientQueue.pollFirst();
                    Path tp = new Path();
                    tp.moveTo(pxX(t.x1), pxY(t.y1));
                    tp.lineTo(pxX(t.x2), pxY(t.y2));
                    gb.addStroke(new GestureDescription.StrokeDescription(tp, 0, t.duration, false));
                    strokeCount++;
                }

                if (strokeCount == 0) return;
                gesture = gb.build();
                busy = true;
                shouldContinue = hasMoreWorkLocked();
            }

            boolean accepted = service.dispatchGesture(gesture,
                    new GestureResultCallback() {
                        @Override
                        public void onCompleted(GestureDescription gestureDescription) {
                            synchronized (lock) {
                                busy = false;
                                if (hasMoreWorkLocked()) postPumpLocked();
                            }
                        }

                        @Override
                        public void onCancelled(GestureDescription gestureDescription) {
                            synchronized (lock) {
                                busy = false;
                                // The framework cancelled the whole gesture: continuation tokens
                                // are no longer valid. Desired pointers are restarted next pump.
                                for (PointerState p : pointers.values()) {
                                    p.stroke = null;
                                    p.hasContinuation = false;
                                    if (p.desiredDown) {
                                        p.startX = p.targetX;
                                        p.startY = p.targetY;
                                        p.x = p.targetX;
                                        p.y = p.targetY;
                                    }
                                }
                                if (hasMoreWorkLocked()) {
                                    handler.postDelayed(() -> {
                                        synchronized (lock) { postPumpLocked(); }
                                    }, 8);
                                }
                            }
                        }
                    }, handler);

            if (!accepted) {
                synchronized (lock) {
                    busy = false;
                    for (PointerState p : pointers.values()) {
                        p.stroke = null;
                        p.hasContinuation = false;
                    }
                    if (shouldContinue || hasMoreWorkLocked()) {
                        handler.postDelayed(() -> {
                            synchronized (lock) { postPumpLocked(); }
                        }, 12);
                    }
                }
            }
        }

        private boolean hasMoreWorkLocked() {
            if (!transientQueue.isEmpty()) return true;
            if (Math.abs(cameraDx) > 0.0001f || Math.abs(cameraDy) > 0.0001f) return true;
            for (PointerState p : pointers.values()) {
                if (p.desiredDown || p.hasContinuation) return true;
            }
            return false;
        }

        private float pxX(float normalized) {
            return clamp(normalized) * service.getResources().getDisplayMetrics().widthPixels;
        }

        private float pxY(float normalized) {
            return clamp(normalized) * service.getResources().getDisplayMetrics().heightPixels;
        }

        private static float clamp(float v) { return Math.max(0f, Math.min(1f, v)); }
        private static float clampDelta(float v) { return Math.max(-0.16f, Math.min(0.16f, v)); }
    }
}
