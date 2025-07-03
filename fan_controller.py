import time

class FanController:
    def __init__(self, config: dict[str, float|int], utils_instance):
        self.config = config
        self.last_fan = 0
        self.fan_speed = 0
        self.avg_temp = -1
        self.n = 0
        self.utils = utils_instance

    def get_temperature(self):
        """Get current temperature"""
        return self.utils.get_temperature()
        
    def set_fan_speed(self, speed):
        """Set fan speed"""
        deadzone = self.config.get("deadzone", 10)
        self.utils.set_fan_speed(speed, deadzone)

    def calculate_fan_speed(self, current_temp):
        max_temp = self.config.get("max_temp", 85)
        min_temp = self.config.get("min_temp", 80)
        full_at_temp = self.config.get("full_at_temp", 95)
        stop_at_temp = self.config.get("stop_at_temp", 70)
        change_factor = self.config.get("change_factor", 0.2)
        always_change = self.config.get("always_change", False)

        if current_temp >= full_at_temp:
            target_speed = 100
        elif current_temp <= stop_at_temp:
            target_speed = 0
        elif current_temp > min_temp:
            target_speed = int(100 * (current_temp - min_temp) / (max_temp - min_temp))
            target_speed = max(0, min(100, target_speed))
        else:
            target_speed = 0

        if always_change:
            self.fan_speed = target_speed
        else:
            if current_temp > self.avg_temp:
                self.fan_speed = min(100, self.fan_speed + int((current_temp - self.avg_temp) * change_factor))
            elif current_temp < self.avg_temp:
                self.fan_speed = max(0, self.fan_speed - int((self.avg_temp - current_temp) * change_factor))
            
            # Ensure fan speed doesn't exceed target if temperature drops
            if self.fan_speed > target_speed and current_temp <= max_temp:
                self.fan_speed = max(target_speed, self.fan_speed - 5) # Gradually reduce if over target
            elif self.fan_speed < target_speed and current_temp >= min_temp:
                self.fan_speed = min(target_speed, self.fan_speed + 5) # Gradually increase if under target

        if self.avg_temp == -1: self.avg_temp = current_temp
        self.avg_temp = ((self.avg_temp * 9 + current_temp) / 10)

        return self.fan_speed

    def controller_loop(self):
        status_str = 'Everything ok'
        current_temp = self.get_temperature()
        
        print(current_temp)
        
        if current_temp < 5:
            self.set_fan_speed(100)
            time.sleep(10)
            status_str = 'CRITITAL: Cannot gather CPU temp'
            return self.fan_speed, status_str

        new_fan_speed = self.calculate_fan_speed(current_temp)
        
        if self.last_fan != new_fan_speed or self.config["always_change"] or self.n > 6:
            self.set_fan_speed(int(new_fan_speed))
            self.last_fan = new_fan_speed
            self.n = 0
        
        time.sleep(1)
        if current_temp < self.config["stop_at_temp"] and (current_temp - self.avg_temp) * self.config["change_factor"] < 2:
            time.sleep(4)
            if current_temp < self.config["stop_at_temp"] - 20:
                time.sleep(5)
        self.n += 1
        return self.fan_speed, status_str
