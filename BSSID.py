import subprocess
import re
import platform
import json

def all_networks():
    if platform.system() == 'Linux':
        #cmd = "iwconfig wlan0 | grep -i --color=never 'signal level'"
        raise Exception("Linux not supported yet")
    elif platform.system() == 'Windows':
        cmd = "netsh wlan show networks mode=bssid"
        input_text = subprocess.check_output(cmd, shell=True).decode('utf-8')
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
                if current_network:
                    data["Networks"].append(current_network)
                ssid = re.sub(r'^SSID \d+ :', '', line).strip()
                current_network = {
                    "SSID": ssid,
                    "BSSIDs": []
                }
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

    else:
        raise Exception("Unsupported OS")

def network_list(BSSID=False):
    # Print the list of SSIDs
    data = all_networks()
    SSID_Return = []
    for network in data["Networks"]:
        if BSSID:
            for bssid in network["BSSIDs"]:
                SSID_BSSID = {"SSID": network["SSID"], "BSSID": bssid["BSSID"]}
                SSID_Return.append(SSID_BSSID)
        else:
            SSID_Return.append({"SSID": network["SSID"]})
    return SSID_Return

def ssid_network(SSID):
    # Print info on ssid
    data = all_networks()
    for network in data["Networks"]:
        if network["SSID"] == SSID:
            data["Networks"] = [network]
    return data

def ssid_signal(SSID):
    # print SSID signal strength
    if SSID:
        data = ssid_network(SSID)
    else:
        data = all_networks()
    signal_data = []
    for network in data["Networks"]:
        for bssid in network["BSSIDs"]:
            BSSID_signal = {"BSSID": bssid["BSSID"], "Signal": bssid["Signal"]}
            signal_data.append(BSSID_signal)
    return signal_data

if __name__ == "__main__":
    print("ALL NETWORKS\n" )
    print(all_networks())
    print("\n------------------------\n")
    print("NETWORK LIST\n")
    SSID = network_list()
    print(SSID)
    print("\n------------------------\n")
    print("SSID NETWORK\n" )
    print(ssid_network(SSID=SSID[0]["SSID"]))
    print("\n------------------------\n")
    print("SSID_SIGNAL\n")
    print(ssid_signal(SSID=SSID[0]["SSID"]))