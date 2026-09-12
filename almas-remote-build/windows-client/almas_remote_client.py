import io, json, math, os, queue, socket, struct, threading, time, tkinter as tk
from tkinter import messagebox, ttk
from PIL import Image, ImageTk

APP = "Almas Remote Client"
PROFILE = os.path.join(os.path.expanduser("~"), ".almas_remote_profile.json")
ACTIONS = ["joystick", "run", "jump", "fire", "aim", "reload", "interact"]
LABELS = {"joystick":"Joystick ортасы", "run":"Run", "jump":"Jump", "fire":"Fire", "aim":"Aim", "reload":"Reload", "interact":"Interact"}
DEFAULT = {"joystick":[0.18,0.73], "run":[0.82,0.61], "jump":[0.89,0.48], "fire":[0.92,0.67], "aim":[0.82,0.37], "reload":[0.76,0.77], "interact":[0.62,0.64], "joystick_radius":0.10}

class App:
    def __init__(self, root):
        self.root=root; root.title(APP); root.geometry("1180x720"); root.minsize(900,560)
        self.profile=self.load_profile(); self.video_sock=None; self.ctrl_sock=None; self.connected=False
        self.frames=queue.Queue(maxsize=2); self.pressed=set(); self.bind_mode=None; self.current_image=None; self.current_photo=None
        self.img_rect=(0,0,1,1); self.running=True
        self.foreground_package=""; self.game_mode=False; self.mouse_start=None
        self.build_ui(); self.bind_inputs(); root.after(30,self.ui_tick)
        threading.Thread(target=self.movement_loop,daemon=True).start()

    def build_ui(self):
        top=ttk.Frame(self.root,padding=8); top.pack(fill="x")
        ttk.Label(top,text="Телефон IP:").pack(side="left"); self.ip=tk.StringVar(value="192.168.1.100")
        ttk.Entry(top,textvariable=self.ip,width=16).pack(side="left",padx=(4,10)); ttk.Label(top,text="PIN:").pack(side="left")
        self.pin=tk.StringVar(); ttk.Entry(top,textvariable=self.pin,width=9,show="•").pack(side="left",padx=(4,10))
        self.btn_connect=ttk.Button(top,text="Қосылу",command=self.toggle_connect); self.btn_connect.pack(side="left")
        self.status=tk.StringVar(value="Қосылмаған"); ttk.Label(top,textvariable=self.status).pack(side="left",padx=14)
        self.mode=tk.StringVar(value="MOUSE MODE"); ttk.Label(top,textvariable=self.mode,font=("Segoe UI",10,"bold")).pack(side="right",padx=8)

        body=ttk.Panedwindow(self.root,orient="horizontal"); body.pack(fill="both",expand=True)
        left=ttk.Frame(body); right=ttk.Frame(body,padding=8); body.add(left,weight=5); body.add(right,weight=2)
        self.canvas=tk.Canvas(left,bg="#111111",highlightthickness=0); self.canvas.pack(fill="both",expand=True)
        self.canvas.bind("<ButtonPress-1>",self.on_mouse_down)
        self.canvas.bind("<ButtonRelease-1>",self.on_mouse_up)
        self.canvas.bind("<Button-3>",self.on_canvas_right)
        self.canvas.bind("<MouseWheel>",self.on_mouse_wheel)

        ttk.Label(right,text="Key Mapping",font=("Segoe UI",14,"bold")).pack(anchor="w",pady=(0,8))
        ttk.Label(right,text="Бұл басқару Free Fire ашылғанда ғана автоматты жұмыс істейді.",wraplength=280).pack(anchor="w",pady=(0,8))
        for a in ACTIONS: ttk.Button(right,text=f"Орнын қою: {LABELS[a]}",command=lambda x=a:self.set_bind(x)).pack(fill="x",pady=2)
        ttk.Label(right,text="Joystick радиусы").pack(anchor="w",pady=(12,0)); self.radius=tk.DoubleVar(value=float(self.profile.get("joystick_radius",0.10)))
        ttk.Scale(right,from_=0.03,to=0.22,variable=self.radius,command=self.radius_changed).pack(fill="x")
        ttk.Separator(right).pack(fill="x",pady=12)
        ttk.Label(right,text="FREE FIRE GAME MODE:\nW/A/S/D — жүру\nShift — жүгіру\nSpace — секіру\nR — оқтау\nF — әрекет\nMouse Right — прицел\n\nMOUSE MODE:\nLeft click — басу\nDrag — сырғыту\nWheel — жоғары/төмен",justify="left").pack(anchor="w")
        ttk.Button(right,text="Профильді сақтау",command=self.save_profile).pack(fill="x",pady=(16,4)); ttk.Button(right,text="Әдепкіге қайтару",command=self.reset_profile).pack(fill="x")

    def bind_inputs(self):
        self.root.bind_all("<KeyPress>",self.key_down)
        self.root.bind_all("<KeyRelease>",self.key_up)

    def load_profile(self):
        try:
            with open(PROFILE,"r",encoding="utf-8") as f: p=json.load(f)
            out=DEFAULT.copy(); out.update(p); return out
        except Exception: return DEFAULT.copy()

    def save_profile(self):
        self.profile["joystick_radius"]=float(self.radius.get())
        with open(PROFILE,"w",encoding="utf-8") as f: json.dump(self.profile,f,indent=2)
        self.status.set("Профиль сақталды")

    def reset_profile(self): self.profile=DEFAULT.copy(); self.radius.set(DEFAULT["joystick_radius"]); self.redraw()
    def radius_changed(self,_=None): self.profile["joystick_radius"]=float(self.radius.get()); self.redraw()
    def set_bind(self,action): self.bind_mode=action; self.status.set(f"{LABELS[action]} орнын экраннан таңда")

    def on_mouse_down(self,e):
        n=self.canvas_to_normalized(e.x,e.y)
        if n:self.mouse_start=(n,time.time())

    def on_mouse_up(self,e):
        end=self.canvas_to_normalized(e.x,e.y)
        start_info=self.mouse_start; self.mouse_start=None
        if not end or not start_info:return
        start,t0=start_info
        if self.bind_mode:
            self.profile[self.bind_mode]=[end[0],end[1]]; self.status.set(f"{LABELS[self.bind_mode]} қойылды"); self.bind_mode=None; self.redraw(); return
        dx=end[0]-start[0]; dy=end[1]-start[1]; dist=math.hypot(dx,dy)
        if (not self.game_mode) and dist>0.012:
            dur=max(90,min(650,int((time.time()-t0)*1000)))
            self.send(f"SWIPE {start[0]:.5f} {start[1]:.5f} {end[0]:.5f} {end[1]:.5f} {dur}")
        else:
            self.send(f"TAP {end[0]:.5f} {end[1]:.5f}")

    def on_canvas_right(self,e):
        n=self.canvas_to_normalized(e.x,e.y)
        if not n or self.bind_mode:return
        if self.game_mode:
            p=self.profile.get("aim")
            if p:self.send(f"TAP {p[0]:.5f} {p[1]:.5f}")
        else:
            self.send(f"TAP {n[0]:.5f} {n[1]:.5f}")

    def on_mouse_wheel(self,e):
        if self.game_mode:return
        c=self.canvas_to_normalized(e.x,e.y)
        if not c:return
        amount=-0.22 if e.delta>0 else 0.22
        y2=max(0.05,min(0.95,c[1]+amount))
        self.send(f"SWIPE {c[0]:.5f} {c[1]:.5f} {c[0]:.5f} {y2:.5f} 180")

    def key_down(self,e):
        k=e.keysym.lower()
        if k in self.pressed:return
        self.pressed.add(k)
        if not self.game_mode:return
        if k in ("shift_l","shift_r"):self.tap_action("run")
        elif k=="space":self.tap_action("jump")
        elif k=="r":self.tap_action("reload")
        elif k=="f":self.tap_action("interact")

    def key_up(self,e): self.pressed.discard(e.keysym.lower())

    def tap_action(self,name):
        if not self.game_mode:return
        p=self.profile.get(name)
        if p:self.send(f"TAP {p[0]:.5f} {p[1]:.5f}")

    def movement_loop(self):
        while self.running:
            dx=(1 if "d" in self.pressed else 0)-(1 if "a" in self.pressed else 0)
            dy=(1 if "s" in self.pressed else 0)-(1 if "w" in self.pressed else 0)
            if self.game_mode and (dx or dy) and self.connected:
                mag=math.hypot(dx,dy); dx/=mag; dy/=mag
                c=self.profile.get("joystick",[0.18,0.73]); r=float(self.profile.get("joystick_radius",0.10))
                x2=max(0,min(1,c[0]+dx*r)); y2=max(0,min(1,c[1]+dy*r))
                self.send(f"SWIPE {c[0]:.5f} {c[1]:.5f} {x2:.5f} {y2:.5f} 160")
                time.sleep(0.145)
            else: time.sleep(0.04)

    def toggle_connect(self):
        if self.connected:self.disconnect();return
        ip=self.ip.get().strip(); pin=self.pin.get().strip()
        if not ip or len(pin)!=6: messagebox.showwarning(APP,"Телефон IP және 6 санды PIN енгіз."); return
        self.status.set("Қосылып жатыр..."); threading.Thread(target=self.connect_worker,args=(ip,pin),daemon=True).start()

    def connect_worker(self,ip,pin):
        try:
            vs=socket.create_connection((ip,5050),timeout=5); vs.settimeout(None); vs.sendall(f"PIN {pin}\n".encode())
            cs=socket.create_connection((ip,5051),timeout=5); cs.settimeout(None); cs.sendall(f"PIN {pin}\n".encode())
            self.video_sock,self.ctrl_sock=vs,cs; self.connected=True
            self.root.after(0,lambda:(self.status.set("Қосылды"),self.btn_connect.config(text="Ажырату")))
            threading.Thread(target=self.control_status_loop,args=(cs,),daemon=True).start()
            self.video_loop(vs)
        except Exception as ex:
            self.root.after(0,lambda e=str(ex):self.status.set("Қате: "+e)); self.disconnect(silent=True)

    def control_status_loop(self,s):
        try:
            f=s.makefile("r",encoding="utf-8",newline="\n")
            while self.connected:
                line=f.readline()
                if not line:break
                line=line.strip()
                if line.startswith("APP "):
                    pkg=line[4:].strip(); self.foreground_package=pkg
                    active=self.is_game_package(pkg)
                    if active != self.game_mode:
                        self.game_mode=active
                        self.pressed.clear()
                        self.root.after(0,self.update_mode_ui)
        except Exception:
            pass

    def is_game_package(self,pkg):
        p=(pkg or "").lower()
        return "freefire" in p or p in ("com.dts.freefireth","com.dts.freefiremax")

    def update_mode_ui(self):
        if self.game_mode:
            self.mode.set("🎮 GAME MODE — Free Fire")
            self.status.set("Free Fire анықталды: пернетақта басқаруы қосылды")
        else:
            self.mode.set("🖱 MOUSE MODE")
            if self.connected:self.status.set("Тышқан режимі: click / drag / wheel")
        self.redraw()

    def recv_exact(self,s,n):
        out=bytearray()
        while len(out)<n:
            b=s.recv(n-len(out))
            if not b:raise ConnectionError("Байланыс үзілді")
            out.extend(b)
        return bytes(out)

    def video_loop(self,s):
        try:
            while self.connected:
                size=struct.unpack(">I",self.recv_exact(s,4))[0]
                if size<=0 or size>10000000:raise ValueError("Bad frame")
                img=Image.open(io.BytesIO(self.recv_exact(s,size))).convert("RGB")
                if self.frames.full():
                    try:self.frames.get_nowait()
                    except queue.Empty:pass
                self.frames.put(img)
        except Exception as ex:
            if self.connected:self.root.after(0,lambda e=str(ex):self.status.set("Видео тоқтады: "+e))
        finally:self.disconnect(silent=True)

    def disconnect(self,silent=False):
        self.connected=False; self.game_mode=False; self.pressed.clear()
        for s in (self.video_sock,self.ctrl_sock):
            try:
                if s:s.close()
            except Exception:pass
        self.video_sock=self.ctrl_sock=None
        try:self.root.after(0,lambda:self.mode.set("MOUSE MODE"))
        except Exception:pass
        if not silent:self.status.set("Қосылмаған")
        try:self.btn_connect.config(text="Қосылу")
        except Exception:pass

    def send(self,command):
        s=self.ctrl_sock
        if not self.connected or not s:return
        try:s.sendall((command+"\n").encode())
        except Exception:self.disconnect()

    def ui_tick(self):
        try:
            while True:self.current_image=self.frames.get_nowait()
        except queue.Empty:pass
        if self.current_image is not None:self.redraw()
        self.root.after(40,self.ui_tick)

    def redraw(self):
        if self.current_image is None:return
        cw=max(2,self.canvas.winfo_width()); ch=max(2,self.canvas.winfo_height()); iw,ih=self.current_image.size; scale=min(cw/iw,ch/ih)
        rw,rh=max(1,int(iw*scale)),max(1,int(ih*scale)); x=(cw-rw)//2; y=(ch-rh)//2
        disp=self.current_image.resize((rw,rh),Image.Resampling.BILINEAR)
        self.current_photo=ImageTk.PhotoImage(disp); self.canvas.delete("all"); self.canvas.create_image(x,y,anchor="nw",image=self.current_photo); self.img_rect=(x,y,rw,rh)
        if self.game_mode or self.bind_mode:
            for a in ACTIONS:
                p=self.profile.get(a)
                if not p:continue
                px=x+p[0]*rw; py=y+p[1]*rh
                self.canvas.create_oval(px-7,py-7,px+7,py+7,outline="white",width=2)
                self.canvas.create_text(px+10,py-10,text=LABELS[a],anchor="sw",fill="white")
            c=self.profile.get("joystick")
            if c:
                r=float(self.profile.get("joystick_radius",0.10))*min(rw,rh); px=x+c[0]*rw; py=y+c[1]*rh
                self.canvas.create_oval(px-r,py-r,px+r,py+r,outline="white",dash=(5,3))

    def canvas_to_normalized(self,x,y):
        ix,iy,rw,rh=self.img_rect
        if x<ix or y<iy or x>ix+rw or y>iy+rh:return None
        return ((x-ix)/rw,(y-iy)/rh)

    def close(self): self.running=False; self.disconnect(silent=True); self.root.destroy()

if __name__=="__main__":
    root=tk.Tk(); app=App(root); root.protocol("WM_DELETE_WINDOW",app.close); root.mainloop()
