#!/bin/bash
# scripts/power_saving.sh
# ------------------------
# OS-level idle power reduction, run ONCE at boot before main.py starts.
# This is NOT a sleep/wake cycle — the Pi Zero 2 W has no supported deep
# sleep without extra PMIC hardware. This just turns off peripherals the
# project doesn't use, which on a battery-powered handheld device is the
# highest-leverage, lowest-risk power saving available.
#
# Installed via systemd/power-saving.service (runs once, before
# bus-route-identifier.service — see that unit's `Before=` / `After=`).
#
# Review each line before enabling on your own build: disabling Wi-Fi
# means no SSH access without physically removing the SD card, so
# comment that line out while you're still actively developing.

set -e

# --- HDMI output: unused on a headless handheld device (~30mA saved) ---
/usr/bin/tvservice -o 2>/dev/null || true

# --- CPU governor: "ondemand" balances the capture/OCR burst against
#     idle power, better than "performance" (always max clock) for a
#     device that's idle >95% of the time waiting for a button press.
#     Do NOT use "powersave" here — it can add enough scheduling latency
#     to a cold OCR burst to threaten the 1.5s budget.
echo "ondemand" | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor > /dev/null

# --- Bluetooth: disabled at the overlay level is cleaner (uncomment in
#     /boot/firmware/config.txt: dtoverlay=disable-bt) since that also
#     frees the PL011 UART. This runtime toggle is the fallback if you
#     want a boot-time-controllable option instead of hardcoding it.
if command -v rfkill &> /dev/null; then
    rfkill block bluetooth || true
fi

# --- Wi-Fi: ONLY disable this once your deployment/update workflow no
#     longer needs SSH access. Left commented out by default.
# rfkill block wifi || true

echo "power_saving.sh: applied idle power reductions"
