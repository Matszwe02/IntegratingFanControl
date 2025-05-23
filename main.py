import subprocess
import time
import sys
import pystray
from PIL import Image
import threading
import os
import winreg
import json
import ctypes
import getpass

def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


# Load the DLL
dll_path = resource_path("AsusWinIO64.dll")
asus_dll = ctypes.WinDLL(dll_path)

# Define the function signatures
asus_dll.InitializeWinIo.restype = ctypes.c_bool
asus_dll.ShutdownWinIo.restype = ctypes.c_bool
asus_dll.HealthyTable_SetFanIndex.argtypes = [ctypes.c_byte]
asus_dll.HealthyTable_SetFanTestMode.argtypes = [ctypes.c_char]
asus_dll.HealthyTable_SetFanPwmDuty.argtypes = [ctypes.c_byte]
asus_dll.HealthyTable_FanRPM.restype = ctypes.c_int
asus_dll.HealthyTable_FanCounts.restype = ctypes.c_int
asus_dll.Thermal_Read_Cpu_Temperature.restype = ctypes.c_ulong

# Initialize WinIo
if not asus_dll.InitializeWinIo():
    print("Failed to initialize WinIo")
    sys.exit()

fan_speed = 0

last_fan = -1
avg_temp = -1

config = {}

not_break = True
n = 0

image_path = resource_path("icon.png")
config_path = './config.json'

deadzone = 10

status_str = ''

icon = None

driver_fix = False


def toggle_startup(icon):
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_ALL_ACCESS)
        value, regtype = winreg.QueryValueEx(key, "FanControl")
        if value:
            winreg.DeleteValue(key, "FanControl")
            icon.notify("Removed from startup", "Fan Control")
        else:
            winreg.SetValueEx(key, "FanControl", 0, winreg.REG_SZ, f'"{sys.executable}" "{os.path.abspath(__file__)}"')
            icon.notify("Added to startup", "Fan Control")
        winreg.CloseKey(key)
    except WindowsError:
        winreg.SetValueEx(key, "FanControl", 0, winreg.REG_SZ, f'"{sys.executable}" "{os.path.abspath(__file__)}"')
        icon.notify("Added to startup", "Fan Control")
        winreg.CloseKey(key)


def get_temperature():
    """Get current temperature"""
    temp_ulong = asus_dll.Thermal_Read_Cpu_Temperature()
    temp_celsius = temp_ulong
    return temp_celsius


def get_fan_speed():
    """Get current fan speed"""
    fan_speeds = []
    fan_count = asus_dll.HealthyTable_FanCounts()
    for i in range(fan_count):
        asus_dll.HealthyTable_SetFanIndex(i)
        fan_speed = asus_dll.HealthyTable_FanRPM()
        fan_speeds.append(fan_speed)
    return ", ".join(map(str, fan_speeds))


def set_fan_speed(speed):
    """Set fan speed"""
    out_speed = deadzone + (speed * (100 - deadzone) / 100)
    if out_speed <= deadzone:
        out_speed = 0

    value = int(out_speed / 100.0 * 255)
    
    fan_count = asus_dll.HealthyTable_FanCounts()
    print(f'{fan_count=}')
    print(f'{value=}')
    for i in range(fan_count):
        asus_dll.HealthyTable_SetFanIndex(i)
        asus_dll.HealthyTable_SetFanTestMode(1)
        asus_dll.HealthyTable_SetFanPwmDuty(value)


def on_exit(icon):
    global not_break
    not_break = False
    icon.stop()
    asus_dll.ShutdownWinIo()
    exit()


def save_config():
    global config
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=4)

def update_config(key, value):
    global config
    config[key] = value
    save_config()
    icon.update_menu() # Update the menu to reflect the changes

def change_temp_setting(key, delta):
    def handler(icon, item):
        update_config(key, config[key] + delta)
    return handler

def toggle_always_change(icon, item):
    update_config("always_change", not config["always_change"])

def show_status(icon):
    config_status = "\nCurrent Configuration:\n"
    for key, value in config.items():
        config_status += f"{key}: {value}\n"
    icon.notify(f"Current temperature: {get_temperature()}°C\n{get_fan_speed()}   ({int(fan_speed)}%)\n{status_str}{config_status}")


def main():
    global image_path
    global not_break
    global icon
    image = Image.open(image_path).resize((64, 64))
    
    menu = pystray.Menu(
        pystray.MenuItem('Show Status', show_status),
        pystray.MenuItem('Settings', pystray.Menu(
            pystray.MenuItem(lambda item: f'Max Temp: {config.get("max_temp", 85)}', pystray.Menu(
                pystray.MenuItem('+5', change_temp_setting('max_temp', 5)),
                pystray.MenuItem('-5', change_temp_setting('max_temp', -5))
            )),
            pystray.MenuItem(lambda item: f'Min Temp: {config.get("min_temp", 80)}', pystray.Menu(
                pystray.MenuItem('+5', change_temp_setting('min_temp', 5)),
                pystray.MenuItem('-5', change_temp_setting('min_temp', -5))
            )),
            pystray.MenuItem(lambda item: f'Full at Temp: {config.get("full_at_temp", 95)}', pystray.Menu(
                pystray.MenuItem('+5', change_temp_setting('full_at_temp', 5)),
                pystray.MenuItem('-5', change_temp_setting('full_at_temp', -5))
            )),
            pystray.MenuItem(lambda item: f'Stop at Temp: {config.get("stop_at_temp", 70)}', pystray.Menu(
                pystray.MenuItem('+5', change_temp_setting('stop_at_temp', 5)),
                pystray.MenuItem('-5', change_temp_setting('stop_at_temp', -5))
            )),
            pystray.MenuItem(lambda item: f'Change Factor: {config.get("change_factor", 0.2):.1f}', pystray.Menu(
                pystray.MenuItem('+0.1', change_temp_setting('change_factor', 0.1)),
                pystray.MenuItem('-0.1', change_temp_setting('change_factor', -0.1))
            )),
            pystray.MenuItem(lambda item: f'Deadzone: {config.get("deadzone", 10)}', pystray.Menu(
                pystray.MenuItem('+1', change_temp_setting('deadzone', 1)),
                pystray.MenuItem('-1', change_temp_setting('deadzone', -1))
            )),
            pystray.MenuItem('Always Change Fan Speed', toggle_always_change, checked=lambda item: config.get("always_change", False))
        )),
        pystray.MenuItem('Toggle Auto Start', toggle_startup),
        pystray.MenuItem('Exit', on_exit)
    )

    icon = pystray.Icon("Fan Control", image, menu=menu)
    icon.notify("Starting FAN control", "Fan Control")
    time.sleep(2)
    
    threading.Thread(target=setup).start()
    
    icon.run()



def load_config():
    global config
    default_config = {
        "max_temp": 85,
        "min_temp": 80,
        "full_at_temp": 95,
        "stop_at_temp": 70,
        "change_factor": 0.2,
        "deadzone": 10,
        "always_change": False
    }
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print(f"Config file not found or invalid at {config_path}. Creating with default values.")
        config = default_config
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=4)


def setup():
    global fan_speed, last_fan, avg_temp, n, status_str, driver_fix
    
    load_config()

    while not_break:
        
        status_str = 'Everything ok'
        
        temp = get_temperature()
        print(temp)
        
        if temp > config["max_temp"]:
            fan_speed += (temp-config["max_temp"])/2
        
        if temp < config["min_temp"]:
            fan_speed -= (config["min_temp"]-temp)/5
        
        
        if avg_temp == -1: avg_temp = temp
        D = (temp - avg_temp) * config["change_factor"]
        avg_temp = ((avg_temp * 9 + temp) / 10)
        
        fan_speed += max(D, 0)
        
        
        if temp > config["full_at_temp"]: fan_speed = 100
        if temp < config["stop_at_temp"]: fan_speed = 0
        
        fan_speed = int(fan_speed)
        if fan_speed < 0: fan_speed = 0
        if fan_speed > 100: fan_speed = 100
        
        if temp < 5:
            set_fan_speed(100)
            time.sleep(10)
            status_str = 'CRITITAL: Cannot gather CPU temp'
        
        if last_fan != fan_speed or config["always_change"] or n > 6:
            set_fan_speed(int(fan_speed))
        last_fan = fan_speed
        
        if not driver_fix:
            print('Running driver fix')
            os.system('run.bat')
            driver_fix = True
            continue
        
        if status_str != 'Everything ok':
            icon.notify(status_str)
            time.sleep(10)
        
        time.sleep(1)
        if temp < config["stop_at_temp"] and D < 2:
            time.sleep(4)
            if temp < config["stop_at_temp"] - 20:
                time.sleep(5)
        n += 1



if __name__ == "__main__":
    main()
