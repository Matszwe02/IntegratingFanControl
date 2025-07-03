import sys
import ctypes
import subprocess
import re
import os
import sys # For getting executable path

class Utils:
    def get_temperature(self):
        raise NotImplementedError

    def set_fan_speed(self, speed):
        raise NotImplementedError

    def get_fan_speed_display(self):
        raise NotImplementedError

    def toggle_startup(self, icon_obj): # Added icon_obj parameter
        raise NotImplementedError

    def shutdown_cleanup(self):
        pass # Optional cleanup for derived classes

class UtilsWin(Utils):
    def __init__(self, resource_path_func):
        self.resource_path = resource_path_func
        self.asus_dll = None
        self._load_asus_dll()

    def _load_asus_dll(self):
        try:
            dll_path = self.resource_path("AsusWinIO64.dll")
            self.asus_dll = ctypes.CDLL(dll_path)
            self.asus_dll.Thermal_Read_Cpu_Temperature.restype = ctypes.c_ulong
            self.asus_dll.HealthyTable_FanCounts.restype = ctypes.c_int
            self.asus_dll.HealthyTable_SetFanIndex.argtypes = [ctypes.c_int]
            self.asus_dll.HealthyTable_SetFanTestMode.argtypes = [ctypes.c_int]
            self.asus_dll.HealthyTable_SetFanPwmDuty.argtypes = [ctypes.c_int]
            self.asus_dll.HealthyTable_FanRPM.restype = ctypes.c_int
        except Exception as e:
            print(f"Failed to load AsusWinIO64.dll: {e}")
            self.asus_dll = None

    def get_temperature(self):
        if self.asus_dll:
            temp_ulong = self.asus_dll.Thermal_Read_Cpu_Temperature()
            temp_celsius = temp_ulong
            return temp_celsius
        else:
            print("Error: asus_dll not loaded for Windows temperature reading.")
            return 0

    def set_fan_speed(self, speed, deadzone):
        if self.asus_dll:
            out_speed = deadzone + (speed * (100 - deadzone) / 100)
            if out_speed <= deadzone:
                out_speed = 0

            value = int(out_speed / 100.0 * 255)
            
            fan_count = self.asus_dll.HealthyTable_FanCounts()
            print(f'{fan_count=}')
            print(f'{value=}')
            for i in range(fan_count):
                self.asus_dll.HealthyTable_SetFanIndex(i)
                self.asus_dll.HealthyTable_SetFanTestMode(1)
                self.asus_dll.HealthyTable_SetFanPwmDuty(value)
        else:
            print("Error: asus_dll not loaded for Windows fan speed setting.")

    def get_fan_speed_display(self):
        if self.asus_dll:
            fan_speeds = []
            fan_count = self.asus_dll.HealthyTable_FanCounts()
            for i in range(fan_count):
                self.asus_dll.HealthyTable_SetFanIndex(i)
                fan_speed_rpm = self.asus_dll.HealthyTable_FanRPM()
                fan_speeds.append(fan_speed_rpm)
            return ", ".join(map(str, fan_speeds))
        else:
            return "N/A"

    def shutdown_cleanup(self):
        if self.asus_dll:
            try:
                fan_count = self.asus_dll.HealthyTable_FanCounts()
                for i in range(fan_count):
                    self.asus_dll.HealthyTable_SetFanIndex(i)
                    self.asus_dll.HealthyTable_SetFanTestMode(0) # Disable test mode
            except Exception as e:
                print(f"Error during shutdown cleanup: {e}")

    def toggle_startup(self, icon_obj):
        try:
            import winreg # For Windows registry operations
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_ALL_ACCESS)
            # Check if the entry exists
            try:
                value, regtype = winreg.QueryValueEx(key, "FanControl")
                is_enabled = True
            except FileNotFoundError:
                is_enabled = False

            if is_enabled:
                winreg.DeleteValue(key, "FanControl")
                icon_obj.notify("Removed from startup", "Fan Control")
            else:
                # Use self.resource_path to get the executable path
                executable_path = self.resource_path(os.path.basename(sys.executable))
                winreg.SetValueEx(key, "FanControl", 0, winreg.REG_SZ, f'"{executable_path}" "{os.path.abspath(sys.argv[0])}"')
                icon_obj.notify("Added to startup", "Fan Control")
            winreg.CloseKey(key)
        except Exception as e: # Catching generic Exception for robustness
            print(f"Error toggling Windows startup: {e}")
            icon_obj.notify(f"Error toggling startup: {e}", "Fan Control Error")

class UtilsLinux(Utils):
    def get_temperature(self):
        try:
            result = subprocess.run(['sensors'], capture_output=True, text=True, check=True)
            output = result.stdout
            match = re.search(r'(Package id|Core \d+):\s*\+?(-?\d+\.?\d*)°C', output)
            if match:
                return float(match.group(2))
            else:
                print("Could not parse temperature from 'sensors' output.")
                return 0
        except FileNotFoundError:
            print("Command 'sensors' not found. Make sure lm_sensors is installed.")
            return 0
        except subprocess.CalledProcessError as e:
            print(f"Error executing 'sensors': {e}")
            return 0

    def set_fan_speed(self, percentage: int, deadzone=None): # deadzone is not used for Linux
        p90 = max(50, percentage)
        p100 = 100

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

    def get_fan_speed_display(self):
        return "N/A" # asusctl does not provide direct fan RPM reading easily

    def toggle_startup(self, icon_obj): # Changed parameter name to icon_obj for consistency
        autostart_dir = os.path.join(os.path.expanduser("~"), ".config", "autostart")
        desktop_file_path = os.path.join(autostart_dir, "asus-fan-control.desktop")
        
        is_enabled = os.path.exists(desktop_file_path)

        if not is_enabled: # If not enabled, enable it
            os.makedirs(autostart_dir, exist_ok=True)
            script_path = os.path.abspath(sys.argv[0]) # Path to main.py or compiled executable
            
            # If running as a script, ensure it's executed with python3
            if script_path.endswith(".py"):
                exec_command = f"python3 {script_path}"
            else:
                exec_command = script_path # If compiled, just use the executable path

            content = f"""[Desktop Entry]
Type=Application
Exec={exec_command}
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Name=Asus Fan Control
Comment=Starts Asus Fan Control on login
"""
            try:
                with open(desktop_file_path, "w") as f:
                    f.write(content)
                print(f"Enabled startup for Linux: {desktop_file_path}")
                icon_obj.notify("Added to startup", "Fan Control")
            except Exception as e:
                print(f"Error creating desktop file for startup: {e}")
                icon_obj.notify(f"Error adding to startup: {e}", "Fan Control Error")
        else: # If enabled, disable it
            try:
                os.remove(desktop_file_path)
                print(f"Disabled startup for Linux: {desktop_file_path}")
                icon_obj.notify("Removed from startup", "Fan Control")
            except Exception as e:
                print(f"Error deleting desktop file for startup: {e}")
                icon_obj.notify(f"Error removing from startup: {e}", "Fan Control Error")
