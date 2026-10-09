import subprocess
import re
import platform
import shutil
import time


def channel_from_freq(freq):
    freq = int(round(float(freq)))
    if freq == 2484:
        return 14
    if 2412 <= freq < 2484:
        return (freq - 2407) // 5
    if 5150 <= freq <= 5895:
        return (freq - 5000) // 5
    if 5925 <= freq <= 7125:
        return (freq - 5950) // 5
    return None


def band_from_freq(freq):
    freq = float(freq)
    if freq < 3000:
        return "2.4 GHz"
    if freq < 5925:
        return "5 GHz"
    return "6 GHz"


def band_from_channel(channel):
    if channel is None:
        return ""
    return "2.4 GHz" if channel <= 14 else "5 GHz"


def windows_quality_to_dbm(quality):
    # netsh reports WLAN_SIGNAL_QUALITY, a linear mapping of -100 dBm..-50 dBm onto 0..100%
    return int(round(quality / 2 - 100))


def networkmanager_quality_to_dbm(quality):
    # NetworkManager maps -90 dBm..-20 dBm onto 0..100%
    return int(round(-90 + quality * 0.7))


def _windows_trigger_scan(wait=3.5):
    # netsh only reports the OS's cached scan results, so ask the driver for a fresh scan first.
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                        ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

        class WLAN_INTERFACE_INFO(ctypes.Structure):
            _fields_ = [("InterfaceGuid", GUID),
                        ("strInterfaceDescription", ctypes.c_wchar * 256),
                        ("isState", wintypes.DWORD)]

        class WLAN_INTERFACE_INFO_LIST(ctypes.Structure):
            _fields_ = [("dwNumberOfItems", wintypes.DWORD), ("dwIndex", wintypes.DWORD),
                        ("InterfaceInfo", WLAN_INTERFACE_INFO * 1)]

        wlanapi = ctypes.windll.wlanapi
        handle = wintypes.HANDLE()
        version = wintypes.DWORD()
        if wlanapi.WlanOpenHandle(2, None, ctypes.byref(version), ctypes.byref(handle)) != 0:
            return False
        try:
            iface_list = ctypes.POINTER(WLAN_INTERFACE_INFO_LIST)()
            if wlanapi.WlanEnumInterfaces(handle, None, ctypes.byref(iface_list)) != 0:
                return False
            try:
                count = iface_list.contents.dwNumberOfItems
                infos = ctypes.cast(ctypes.byref(iface_list.contents.InterfaceInfo),
                                    ctypes.POINTER(WLAN_INTERFACE_INFO))
                for i in range(count):
                    wlanapi.WlanScan(handle, ctypes.byref(infos[i].InterfaceGuid), None, None, None)
            finally:
                wlanapi.WlanFreeMemory(iface_list)
        finally:
            wlanapi.WlanCloseHandle(handle, None)
    except Exception:
        return False
    time.sleep(wait)
    return True


def all_networks():
    # Windows only: parse `netsh wlan show networks mode=bssid`
    cmd = "netsh wlan show networks mode=bssid"
    input_text = subprocess.check_output(cmd, shell=True).decode('utf-8', errors='replace')
    # Initialize the data structure
    data = {
        "Interface_name": "WiFi",
        "Networks": []
    }

    # Split the input text into lines
    lines = input_text.strip().split('\n')

    # Initialize variables
    current_network = None
    current_bssid = None

    # Process each line
    for line in lines:
        line = line.strip()
        if re.match(r'^SSID \d+ :', line):
            if current_bssid:
                current_network["BSSIDs"].append(current_bssid)
                current_bssid = None
            if current_network:
                data["Networks"].append(current_network)
            ssid = re.sub(r'^SSID \d+ :', '', line).strip()
            current_network = {
                "SSID": ssid,
                "BSSIDs": []
            }
        elif current_network is None:
            continue
        elif re.match(r'^Network type\s*:', line):
            current_network["Network_type"] = re.sub(r'^Network type\s*:', '', line).strip()
        elif re.match(r'^Authentication\s*:', line):
            current_network["Authentication"] = re.sub(r'^Authentication\s*:', '', line).strip()
        elif re.match(r'^Encryption\s*:', line):
            current_network["Encryption"] = re.sub(r'^Encryption\s*:', '', line).strip()
        elif re.match(r'^BSSID \d+\s*:', line):
            if current_bssid:
                current_network["BSSIDs"].append(current_bssid)
            bssid = re.sub(r'^BSSID \d+\s*:', '', line).strip()
            current_bssid = {
                "BSSID": bssid
            }
        elif current_bssid is None:
            continue
        elif re.match(r'^Signal\s*:', line):
            current_bssid["Signal"] = re.sub(r'^Signal\s*:', '', line).strip()
        elif re.match(r'^Radio type\s*:', line):
            current_bssid["Radio_type"] = re.sub(r'^Radio type\s*:', '', line).strip()
        elif re.match(r'^Band\s*:', line):
            current_bssid["Band"] = re.sub(r'^Band\s*:', '', line).strip()
        elif re.match(r'^Channel\s*:', line):
            current_bssid["Channel"] = re.sub(r'^Channel\s*:', '', line).strip()
        elif re.match(r'^Connected Stations\s*:', line):
            current_bssid["Connected_Stations"] = re.sub(r'^Connected Stations\s*:', '', line).strip()
        elif re.match(r'^Channel Utilization\s*:', line):
            current_bssid["Channel_Utilization"] = re.sub(r'^Channel Utilization\s*:', '', line).strip()
        elif re.match(r'^Medium Available Capacity\s*:', line):
            current_bssid["Medium_Available_Capacity"] = re.sub(r'^Medium Available Capacity\s*:', '', line).strip()
        elif re.match(r'^Basic rates \(Mbps\)\s*:', line):
            current_bssid["Basic_rates_Mbps"] = re.sub(r'^Basic rates \(Mbps\)\s*:', '', line).strip().split()
        elif re.match(r'^Other rates \(Mbps\)\s*:', line):
            current_bssid["Other_rates_Mbps"] = re.sub(r'^Other rates \(Mbps\)\s*:', '', line).strip().split()

    # Add the last network and BSSID
    if current_bssid:
        current_network["BSSIDs"].append(current_bssid)
    if current_network:
        data["Networks"].append(current_network)
    return data


def _scan_windows():
    _windows_trigger_scan()
    readings = []
    for network in all_networks()["Networks"]:
        for bssid in network["BSSIDs"]:
            match = re.search(r'(\d+)', bssid.get("Signal", ""))
            if not match:
                continue
            channel = int(bssid["Channel"]) if bssid.get("Channel", "").isdigit() else None
            readings.append({
                "SSID": network["SSID"],
                "BSSID": bssid["BSSID"].lower(),
                "Signal": windows_quality_to_dbm(int(match.group(1))),
                "Channel": channel,
                "Band": bssid.get("Band") or band_from_channel(channel),
                "Security": network.get("Authentication", ""),
            })
    return readings


def _scan_nmcli():
    base = ["nmcli", "-t", "-f", "SSID,BSSID,SIGNAL,CHAN,FREQ,SECURITY", "device", "wifi", "list"]
    try:
        output = subprocess.run(base + ["--rescan", "yes"], capture_output=True, text=True, check=True).stdout
    except subprocess.CalledProcessError:
        # NetworkManager refuses back-to-back rescans; fall back to its cached results
        output = subprocess.run(base + ["--rescan", "no"], capture_output=True, text=True, check=True).stdout
    readings = []
    for line in output.splitlines():
        fields = [f.replace("\\:", ":").replace("\\\\", "\\") for f in re.split(r'(?<!\\):', line)]
        if len(fields) < 6 or not fields[2].isdigit():
            continue
        ssid, bssid, signal, chan, freq, security = fields[:6]
        freq_match = re.search(r'(\d+)', freq)
        readings.append({
            "SSID": ssid,
            "BSSID": bssid.lower(),
            "Signal": networkmanager_quality_to_dbm(int(signal)),
            "Channel": int(chan) if chan.isdigit() else None,
            "Band": band_from_freq(freq_match.group(1)) if freq_match else band_from_channel(int(chan) if chan.isdigit() else None),
            "Security": security,
        })
    return readings


def _scan_iw():
    interfaces = re.findall(r'Interface\s+(\S+)', subprocess.check_output(["iw", "dev"], text=True))
    if not interfaces:
        raise Exception("No wireless interface found")
    result = subprocess.run(["iw", "dev", interfaces[0], "scan"], capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception("iw scan failed (it usually needs root): " + result.stderr.strip())
    readings = []
    current = None
    for line in result.stdout.splitlines():
        stripped = line.strip()
        bss = re.match(r'^BSS ([0-9a-fA-F:]{17})', line)
        if bss:
            current = {"SSID": "", "BSSID": bss.group(1).lower(), "Signal": None,
                       "Channel": None, "Band": "", "Security": "Open"}
            readings.append(current)
        elif current is None:
            continue
        elif stripped.startswith("freq:"):
            freq = float(stripped.split(":", 1)[1])
            current["Channel"] = channel_from_freq(freq)
            current["Band"] = band_from_freq(freq)
        elif stripped.startswith("signal:"):
            current["Signal"] = int(round(float(re.search(r'(-?[\d.]+)', stripped).group(1))))
        elif stripped.startswith("SSID:"):
            current["SSID"] = stripped[5:].strip()
        elif stripped.startswith("RSN:"):
            current["Security"] = "WPA2/WPA3"
        elif stripped.startswith("WPA:") and current["Security"] == "Open":
            current["Security"] = "WPA"
    return [r for r in readings if r["Signal"] is not None]


def scan():
    """Scan for access points. Returns one reading per BSSID:
    {"SSID", "BSSID", "Signal" (dBm), "Channel", "Band", "Security"}"""
    system = platform.system()
    if system == 'Windows':
        return _scan_windows()
    elif system == 'Linux':
        if shutil.which("nmcli"):
            return _scan_nmcli()
        if shutil.which("iw"):
            return _scan_iw()
        raise Exception("Linux scanning needs NetworkManager (nmcli) or iw")
    else:
        raise Exception("Unsupported OS")


def network_list():
    return sorted({reading["SSID"] for reading in scan()})


if __name__ == "__main__":
    for reading in sorted(scan(), key=lambda r: -r["Signal"]):
        print(f'{reading["Signal"]:>4} dBm  ch {reading["Channel"]!s:>3}  {reading["Band"]:<8} '
              f'{reading["BSSID"]}  {reading["SSID"]}')
