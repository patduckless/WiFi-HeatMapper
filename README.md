# Wi-Fi Heat Mapper
A somewhat simple Python script to generate heatmaps of wifi SSIDs in windows.

## Features
  - Every scan records all access points (BSSIDs) heard, with signal in dBm, channel and band
  - Each AP is interpolated separately, then combined into the selected view:
    - **Signal Strength** – strongest AP at each location (-30 to -90 dBm scale)
    - **Secondary Coverage** – second strongest AP (roaming / redundancy)
    - **Number of APs** – how many APs are heard above the minimum signal
    - **Channel Overlap** – APs on the same (or overlapping 2.4 GHz) channel as the strongest one
    - **Strongest AP** – which AP serves each area
  - Filter by network (SSID) and band (2.4 / 5 / 6 GHz)
  - Heatmap only covers the surveyed area and fades out away from measurement points
  - Estimated AP locations, survey route, hover readout of the value under the cursor
  - Report window and PNG export with legend and -67 / -75 dBm contour lines
  - Surveys saved as JSON (old `.txt` results can still be opened)

## How to run
  ```
  pip install -r requirements.txt
  python window.py
  ```

  - Left click: take a measurement at that spot (stand still until the point appears)
  - Right click: delete the nearest measurement
  - Ctrl+Z: undo the last measurement

  Linux needs NetworkManager (`nmcli`), or `iw` run as root.

## Tested on
  - Windows 11
