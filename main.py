import subprocess
import time
import sys
import pystray
from PIL import Image
import threading
import os
import json
import getpass
import re
import ctypes # Added ctypes for DLL loading
from fan_controller import FanController
from utils import UtilsWin, UtilsLinux # Import the new utility classes

if sys.platform == "win32":
    import winreg

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

config = {}
not_break = True
image_path = resource_path("icon.png")
config_path = './config.json'
status_str = ''
icon = None
fan_controller = None

def shutdown():
    """Perform cleanup before exit."""
    global fan_controller
    if fan_controller and fan_controller.utils: # Check if fan_controller and its utils instance exist
        fan_controller.utils.shutdown_cleanup()

def on_exit(icon):
    global not_break
    not_break = False
    icon.stop()
    shutdown() # Call the new shutdown function
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
    
    current_temp = fan_controller.utils.get_temperature() if fan_controller and fan_controller.utils else "N/A"
    current_fan_speed_display = fan_controller.utils.get_fan_speed_display() if fan_controller and fan_controller.utils else "N/A"
    current_fan_percentage = int(fan_controller.fan_speed) if fan_controller else "N/A"

    custom_notify(icon, f"Current temperature: {current_temp}°C\n{current_fan_speed_display}   ({current_fan_percentage}%)\n{status_str}{config_status}", "Fan Control Status")

def main():
    print("Main application starting...")
    global image_path
    global not_break
    global icon
    global fan_controller
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
        pystray.MenuItem('Toggle Auto Start', lambda icon_obj, item: utils_instance.toggle_startup(icon_obj)),
        pystray.MenuItem('Exit', on_exit)
    )

    icon = pystray.Icon("Fan Control", image, menu=menu)
    custom_notify(icon, "Starting FAN control", "Fan Control")
    time.sleep(2)
    
    load_config() # Load config before initializing FanController

    # Instantiate the correct utility class based on the platform
    if sys.platform == "win32":
        utils_instance = UtilsWin(resource_path)
    else:
        utils_instance = UtilsLinux()
    
    fan_controller = FanController(config, utils_instance)
    
    print("Launching setup thread...")
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
    global status_str
    print("Setup thread started.")
    
    while not_break:
        print(f"Calling fan_controller.controller_loop()...")
        _, status_str = fan_controller.controller_loop() # Unpack the tuple correctly
        print(f"Controller loop returned status: {status_str}")
        if status_str != 'Everything ok':
            custom_notify(icon, status_str)
            time.sleep(10)
        time.sleep(1) # This sleep is handled inside controller_loop now, but keep for main loop

main()
