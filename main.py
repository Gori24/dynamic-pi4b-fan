import RPi.GPIO as GPIO
import subprocess
import time
from datetime import datetime


FAN_PIN = 17       # BCM GPIO pin
TEMP_ON  = 60.0    # top threshold to turn fan ON (°C)
TEMP_OFF = 50.0    # bottom threshold to turn fan OFF (°C)
INTERVAL = 5       # time between checks (seconds)


def log(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}]\t{message}")


def get_cpu_temp() -> float:
    result = subprocess.run(['vcgencmd', 'measure_temp'], capture_output=True, text=True)
    temp_str = result.stdout.strip()
    return float(temp_str.replace("temp=", "").replace("'C", ""))


def main():
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(FAN_PIN, GPIO.OUT, initial=GPIO.LOW)
    fan_on = False

    log("Fan control started. Interrupt with Ctrl+C.")
    try:
        while True:
            temp = get_cpu_temp()
            if not fan_on and temp >= TEMP_ON:
                GPIO.output(FAN_PIN, GPIO.HIGH)
                fan_on = True
                log(f"{temp:.1f}°C - Fan ON")
            elif fan_on and temp < TEMP_OFF:
                GPIO.output(FAN_PIN, GPIO.LOW)
                fan_on = False
                log(f"{temp:.1f}°C - Fan OFF")
            else:
                log(f"{temp:.1f}°C - {'ON' if fan_on else 'OFF'}")
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        log("Shutting down...")
    finally:
        GPIO.output(FAN_PIN, GPIO.LOW)
        GPIO.cleanup()


if __name__ == "__main__":
    main()
