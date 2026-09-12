#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <linux/uinput.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define AXIS_MAX 32767
#define MAX_SLOTS 10

static int fd = -1;
static int active[MAX_SLOTS];
static int tracking[MAX_SLOTS];
static int next_tracking = 100;
static int active_count = 0;

static int emit_ev(int type, int code, int value) {
    struct input_event ev;
    memset(&ev, 0, sizeof(ev));
    ev.type = type;
    ev.code = code;
    ev.value = value;
    return write(fd, &ev, sizeof(ev)) == sizeof(ev) ? 0 : -1;
}

static void sync_ev(void) { emit_ev(EV_SYN, SYN_REPORT, 0); }

static int clampv(int v) {
    if (v < 0) return 0;
    if (v > AXIS_MAX) return AXIS_MAX;
    return v;
}

static void update_primary(int slot, int x, int y) {
    if (slot == 0 || active_count == 1) {
        emit_ev(EV_ABS, ABS_X, clampv(x));
        emit_ev(EV_ABS, ABS_Y, clampv(y));
    }
}

static void touch_down(int slot, int x, int y) {
    if (slot < 0 || slot >= MAX_SLOTS) return;
    if (!active[slot]) {
        active[slot] = 1;
        tracking[slot] = next_tracking++;
        if (next_tracking > 60000) next_tracking = 100;
        active_count++;
    }
    emit_ev(EV_ABS, ABS_MT_SLOT, slot);
    emit_ev(EV_ABS, ABS_MT_TRACKING_ID, tracking[slot]);
    emit_ev(EV_ABS, ABS_MT_POSITION_X, clampv(x));
    emit_ev(EV_ABS, ABS_MT_POSITION_Y, clampv(y));
    emit_ev(EV_ABS, ABS_MT_PRESSURE, 50);
    update_primary(slot, x, y);
    if (active_count == 1) {
        emit_ev(EV_KEY, BTN_TOUCH, 1);
        emit_ev(EV_KEY, BTN_TOOL_FINGER, 1);
    }
    sync_ev();
}

static void touch_move(int slot, int x, int y) {
    if (slot < 0 || slot >= MAX_SLOTS || !active[slot]) return;
    emit_ev(EV_ABS, ABS_MT_SLOT, slot);
    emit_ev(EV_ABS, ABS_MT_POSITION_X, clampv(x));
    emit_ev(EV_ABS, ABS_MT_POSITION_Y, clampv(y));
    emit_ev(EV_ABS, ABS_MT_PRESSURE, 50);
    update_primary(slot, x, y);
    sync_ev();
}

static void touch_up(int slot) {
    if (slot < 0 || slot >= MAX_SLOTS || !active[slot]) return;
    emit_ev(EV_ABS, ABS_MT_SLOT, slot);
    emit_ev(EV_ABS, ABS_MT_TRACKING_ID, -1);
    active[slot] = 0;
    tracking[slot] = 0;
    if (active_count > 0) active_count--;
    if (active_count == 0) {
        emit_ev(EV_KEY, BTN_TOUCH, 0);
        emit_ev(EV_KEY, BTN_TOOL_FINGER, 0);
    }
    sync_ev();
}

static void tap_at(int slot, int x, int y, int ms) {
    if (ms < 8) ms = 8;
    if (ms > 120) ms = 120;
    touch_down(slot, x, y);
    usleep((useconds_t)ms * 1000);
    touch_up(slot);
}

static void swipe_at(int slot, int x1, int y1, int x2, int y2, int ms) {
    if (ms < 16) ms = 16;
    if (ms > 500) ms = 500;
    int steps = ms / 8;
    if (steps < 2) steps = 2;
    if (steps > 50) steps = 50;
    touch_down(slot, x1, y1);
    for (int i = 1; i <= steps; i++) {
        int x = x1 + (x2 - x1) * i / steps;
        int y = y1 + (y2 - y1) * i / steps;
        touch_move(slot, x, y);
        usleep((useconds_t)(ms * 1000 / steps));
    }
    touch_up(slot);
}

static int setup_uinput(void) {
    fd = open("/dev/uinput", O_WRONLY | O_NONBLOCK);
    if (fd < 0) return -1;

    ioctl(fd, UI_SET_EVBIT, EV_KEY);
    ioctl(fd, UI_SET_KEYBIT, BTN_TOUCH);
    ioctl(fd, UI_SET_KEYBIT, BTN_TOOL_FINGER);
    ioctl(fd, UI_SET_EVBIT, EV_ABS);
    ioctl(fd, UI_SET_PROPBIT, INPUT_PROP_DIRECT);

    ioctl(fd, UI_SET_ABSBIT, ABS_X);
    ioctl(fd, UI_SET_ABSBIT, ABS_Y);
    ioctl(fd, UI_SET_ABSBIT, ABS_MT_SLOT);
    ioctl(fd, UI_SET_ABSBIT, ABS_MT_TRACKING_ID);
    ioctl(fd, UI_SET_ABSBIT, ABS_MT_POSITION_X);
    ioctl(fd, UI_SET_ABSBIT, ABS_MT_POSITION_Y);
    ioctl(fd, UI_SET_ABSBIT, ABS_MT_PRESSURE);

    struct uinput_user_dev uidev;
    memset(&uidev, 0, sizeof(uidev));
    snprintf(uidev.name, UINPUT_MAX_NAME_SIZE, "Almas Remote Root Touch");
    uidev.id.bustype = BUS_VIRTUAL;
    uidev.id.vendor = 0x41A5;
    uidev.id.product = 0x2203;
    uidev.id.version = 1;

    uidev.absmin[ABS_X] = 0;
    uidev.absmax[ABS_X] = AXIS_MAX;
    uidev.absmin[ABS_Y] = 0;
    uidev.absmax[ABS_Y] = AXIS_MAX;
    uidev.absmin[ABS_MT_SLOT] = 0;
    uidev.absmax[ABS_MT_SLOT] = MAX_SLOTS - 1;
    uidev.absmin[ABS_MT_TRACKING_ID] = 0;
    uidev.absmax[ABS_MT_TRACKING_ID] = 65535;
    uidev.absmin[ABS_MT_POSITION_X] = 0;
    uidev.absmax[ABS_MT_POSITION_X] = AXIS_MAX;
    uidev.absmin[ABS_MT_POSITION_Y] = 0;
    uidev.absmax[ABS_MT_POSITION_Y] = AXIS_MAX;
    uidev.absmin[ABS_MT_PRESSURE] = 0;
    uidev.absmax[ABS_MT_PRESSURE] = 255;

    if (write(fd, &uidev, sizeof(uidev)) != sizeof(uidev)) return -2;
    if (ioctl(fd, UI_DEV_CREATE) < 0) return -3;
    usleep(250000);
    return 0;
}

int main(void) {
    int rc = setup_uinput();
    if (rc != 0) {
        printf("ERROR %d errno=%d %s\n", rc, errno, strerror(errno));
        fflush(stdout);
        return 2;
    }

    printf("READY\n");
    fflush(stdout);

    char line[256];
    while (fgets(line, sizeof(line), stdin)) {
        int slot, x, y, x2, y2, ms;
        if (sscanf(line, "D %d %d %d", &slot, &x, &y) == 3) {
            touch_down(slot, x, y);
        } else if (sscanf(line, "M %d %d %d", &slot, &x, &y) == 3) {
            touch_move(slot, x, y);
        } else if (sscanf(line, "U %d", &slot) == 1) {
            touch_up(slot);
        } else if (sscanf(line, "T %d %d %d %d", &slot, &x, &y, &ms) == 4) {
            tap_at(slot, x, y, ms);
        } else if (sscanf(line, "S %d %d %d %d %d %d", &slot, &x, &y, &x2, &y2, &ms) == 6) {
            swipe_at(slot, x, y, x2, y2, ms);
        } else if (strncmp(line, "CANCEL", 6) == 0) {
            for (int i = 0; i < MAX_SLOTS; i++) touch_up(i);
        } else if (strncmp(line, "PING", 4) == 0) {
            printf("PONG\n");
            fflush(stdout);
        } else if (strncmp(line, "QUIT", 4) == 0) {
            break;
        }
    }

    for (int i = 0; i < MAX_SLOTS; i++) touch_up(i);
    ioctl(fd, UI_DEV_DESTROY);
    close(fd);
    return 0;
}
