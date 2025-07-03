import subprocess
import time
import sys
import pystray
from PIL import Image
import threading
import os
import json
import ctypes
import getpass
import re # Added re import

if sys.platform == "win32":
    import winreg


fan_speed_percentage = 0.0 # Initialize fan speed percentage


def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

def custom_notify(icon_obj, message, title=None):
    """Show a notification, using notify-send on Linux and pystray.Icon.notify on Windows."""
    if sys.platform.startswith("linux"):
        command = ["notify-send"]
        if title:
            command.append(title)
        command.append(message)
        try:
            subprocess.run(command, check=True)
        except FileNotFoundError:
            print("notify-send command not found. Falling back to pystray notification.")
            icon_obj.notify(message, title)
        except subprocess.CalledProcessError as e:
            print(f"Error sending notification via notify-send: {e}. Falling back to pystray notification.")
            icon_obj.notify(message, title)
    elif sys.platform == "win32":
        icon_obj.notify(message, title)
    else:
        print(f"Notification (unsupported platform): {title}: {message}")


# Load the DLL
if sys.platform == "win32":
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
if sys.platform == "win32":
    if not asus_dll.InitializeWinIo():
        print("Failed to initialize WinIo")
        sys.exit()
else:
    print("Running on non-Windows platform, skipping WinIO initialization.")

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
    if sys.platform == "win32":
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_ALL_ACCESS)
            value, regtype = winreg.QueryValueEx(key, "FanControl")
            if value:
                winreg.DeleteValue(key, "FanControl")
                custom_notify(icon, "Removed from startup", "Fan Control")
            else:
                winreg.SetValueEx(key, "FanControl", 0, winreg.REG_SZ, f'"{sys.executable}" "{os.path.abspath(__file__)}"')
                custom_notify(icon, "Added to startup", "Fan Control")
            winreg.CloseKey(key)
        except WindowsError:
            winreg.SetValueEx(key, "FanControl", 0, winreg.REG_SZ, f'"{sys.executable}" "{os.path.abspath(__file__)}"')
            custom_notify(icon, "Added to startup", "Fan Control")
            winreg.CloseKey(key)


def get_temperature():
    """Get current temperature"""
    if sys.platform == "win32":
        temp_ulong = asus_dll.Thermal_Read_Cpu_Temperature()
        temp_celsius = temp_ulong
        return temp_celsius
    else:
        try:
            # Attempt to get CPU temperature using lm_sensors
            result = subprocess.run(['sensors'], capture_output=True, text=True, check=True)
            output = result.stdout
            # This regex tries to find a temperature value for 'Package id' or 'Core'
            # It's a common pattern for CPU temperatures in `sensors` output.
            match = re.search(r'(Package id|Core \d+):\s*\+?(-?\d+\.?\d*)°C', output)
            if match:
                return float(match.group(2))
            else:
                print("Could not parse temperature from 'sensors' output.")
                return 0 # Return 0 or handle error appropriately
        except FileNotFoundError:
            print("Command 'sensors' not found. Make sure lm_sensors is installed.")
            return 0 # Return 0 or handle error appropriately
        except subprocess.CalledProcessError as e:
            print(f"Error executing 'sensors': {e}")
            return 0 # Return 0 or handle error appropriately


def get_fan_speed():
    """Get current fan speed"""
    fan_speeds = []
    fan_count = asus_dll.HealthyTable_FanCounts()
    for i in range(fan_count):
        asus_dll.HealthyTable_SetFanIndex(i)
        fan_speed = asus_dll.HealthyTable_FanRPM()
        fan_speeds.append(fan_speed)
    return ", ".join(map(str, fan_speeds))


def set_asusctl_fan_curve(percentage: int):
    """Set fan curve using asusctl for non-Windows platforms."""
    global fan_speed_percentage
    fan_speed_percentage = percentage

    # Ensure 100% at 100c and at least 50% at 90c
    p90 = max(50, percentage) # At least 50% at 90c
    p100 = 100 # Always 100% at 100c

    curve_data = f"30c:{percentage}%,40c:{percentage}%,50c:{percentage}%,60c:{percentage}%,70c:{percentage}%,80c:{percentage}%,90c:{p90}%,100c:{p100}%"

    commands = [
        f"asusctl fan-curve -m Quiet -f cpu -D {curve_data}",
        f"asusctl fan-curve -m Quiet -f gpu -D {curve_data}",
        "asusctl fan-curve -m Quiet -e true"
    ]
    for cmd in commands:
        try:
            subprocess.run(cmd, shell=True, check=True)
            print(f"Executed: {cmd}")
        except subprocess.CalledProcessError as e:
            print(f"Error executing '{cmd}': {e}")
        except FileNotFoundError:
            print(f"Command '{cmd.split(' ')[0]}' not found. Make sure asusctl is installed and in your PATH.")

def set_fan_speed(speed):
    """Set fan speed"""
    if sys.platform == "win32":
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
    else:
        set_asusctl_fan_curve(speed)


def on_exit(icon):
    global not_break
    not_break = False
    icon.stop()
    if sys.platform == "win32":
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
    custom_notify(icon, f"Current temperature: {get_temperature()}°C\n{get_fan_speed()}   ({int(fan_speed)}%)\n{status_str}{config_status}")


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
    custom_notify(icon, "Starting FAN control", "Fan Control")
    time.sleep(2)
    
    threading.Thread(target=setup).start()
    
    icon.run()



def load_config():
    global config
    default_config = {
        "max_temp": 80,
        "min_temp": 75,
        "full_at_temp": 90,
        "stop_at_temp": 65,
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
        
        if sys.platform == "win32" and not driver_fix:
            print('Running driver fix')
            os.system('run.bat')
            driver_fix = True
            continue
        elif not driver_fix: # For non-Windows, just mark as fixed
            print('Skipping driver fix for non-Windows platform.')
            driver_fix = True
            continue
        
        if status_str != 'Everything ok':
            custom_notify(icon, status_str)
            time.sleep(10)
        
        time.sleep(1)
        if temp < config["stop_at_temp"] and D < 2:
            time.sleep(4)
            if temp < config["stop_at_temp"] - 20:
                time.sleep(5)
        n += 1



if __name__ == "__main__":
    main()
