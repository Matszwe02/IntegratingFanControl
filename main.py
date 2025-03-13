import subprocess
import time
import sys
import pystray
from PIL import Image
import threading
import os
import winreg


fan_speed = 0

last_fan = -1
avg_temp = -1


max_temp = 85
min_temp = 80
full_at_temp = 95
stop_at_temp = 70
change_factor = 0.2

deadzone = 10
always_change = False


not_break = True
n = 0

fan_app_path = './AsusFanControl.exe'
image_path = './icon.png'



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
    result = subprocess.run([fan_app_path, '--get-cpu-temp'], capture_output=True, text=True, shell=True)
    x = result.stdout.strip().replace('Current CPU temp:', '')
    return float(x)


def get_fan_speed():
    """Get current fan speed"""
    result = subprocess.run([fan_app_path, '--get-fan-speeds'], capture_output=True, text=True, shell=True)
    return result.stdout.strip()



def set_fan_speed(speed):
    """Set fan speed"""
    # if speed < deadzone: speed = 0
    
    out_speed = deadzone + (speed * (100 - deadzone) / 100)
    if out_speed == deadzone: out_speed = 0

    subprocess.run([fan_app_path, '--set-fan-speed=0:' + str(max(int(out_speed), 1))], shell=True)
    subprocess.run([fan_app_path, '--set-fan-speed=1:' + str(max(int(out_speed*4/5), 1))], shell=True)



def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


def on_exit(icon):
    global not_break
    not_break = False
    icon.stop()
    exit()


def show_status(icon):
    icon.notify(f"Current temperature: {get_temperature()}°C\n{get_fan_speed()}   ({int(fan_speed)}%)")



def main():
    global image_path, fan_app_path
    global not_break
    image_path = resource_path("icon.png")
    fan_app_path = resource_path("AsusFanControl.exe")
    image = Image.open(image_path).resize((64, 64))
    
    menu = pystray.Menu(
        pystray.MenuItem('Show Status', show_status),
        pystray.MenuItem('Toggle Auto Start', toggle_startup),
        pystray.MenuItem('Exit', on_exit)
    )

    icon = pystray.Icon("Fan Control", image, menu=menu)
    icon.notify("Starting FAN control", "Fan Control")
    time.sleep(2)
    
    threading.Thread(target=setup).start()
    
    icon.run()



def setup():
    global fan_speed, last_fan, avg_temp
    
    while not_break:
        
        temp = get_temperature()
        print(temp)
        
        if temp > max_temp:
            fan_speed += (temp-max_temp)/2
        
        if temp < min_temp:
            fan_speed -= (min_temp-temp)/5
        
        
        if avg_temp == -1: avg_temp = temp
        D = (temp - avg_temp) * change_factor
        avg_temp = ((avg_temp * 9 + temp) / 10)
        
        fan_speed += max(D, 0)
        
        
        if temp > full_at_temp: fan_speed = 100
        if temp < stop_at_temp: fan_speed = 0
        
        fan_speed = int(fan_speed)
        if fan_speed < 0: fan_speed = 0
        if fan_speed > 100: fan_speed = 100
        
        if last_fan != fan_speed or always_change or n > 6:
            set_fan_speed(int(fan_speed))
        last_fan = fan_speed
        
        
        time.sleep(1)
        if temp < stop_at_temp and D < 2:
            time.sleep(4)
            if temp < stop_at_temp - 20:
                time.sleep(5)
        n += 1



if __name__ == "__main__":
    main()