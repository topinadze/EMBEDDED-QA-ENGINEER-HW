import re
import time
import serial
import allure
from config.test_config import SERIAL_BAUDRATE, SERIAL_TIMEOUT, BOOT_DELAY


class DeviceDriver:
    ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

    def __init__(self, port: str, timeout: float = SERIAL_TIMEOUT):
        self.port = port
        self.timeout = timeout
        self.serial: serial.Serial | None = None

    @allure.step("Відкриття serial-з'єднання та очищення буферів")
    def open(self) -> None:
        if self.serial is None:
            self.serial = serial.Serial(
                port=self.port,
                baudrate=SERIAL_BAUDRATE,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout,
            )
        elif not self.serial.is_open:
            self.serial.open()

        self.serial.reset_input_buffer()
        self.serial.reset_output_buffer()

    @allure.step("Очищення та закриття serial-порт.")
    def close(self) -> None:
        if self.serial and self.serial.is_open:
            self.serial.close()
            self.serial = None

    @allure.step("Зчитування всіх рядків з serial-порту протягом заданого timeout: '{timeout}'")
    def read_lines(self, timeout: float) -> list[str]:
        if not self.serial or not self.serial.is_open:
            raise RuntimeError("Serial port is not open. Call open() first.")

        lines = []
        start_time = time.time()

        while (time.time() - start_time) < timeout:
            if self.serial.in_waiting > 0:
                raw_line = self.serial.readline()
                try:
                    line_str = raw_line.decode("utf-8", errors="replace")
                except Exception:
                    line_str = str(raw_line)

                cleaned_line = line_str.replace("\r", "").replace("\n", "")
                cleaned_line = self.ANSI_ESCAPE.sub("", cleaned_line)
                cleaned_line = cleaned_line.strip()

                if cleaned_line:
                    lines.append(cleaned_line)
            else:
                time.sleep(0.01)

        return lines

    def ensure_ends_with_rn(self, command: str) -> str:
        """Гарантує, що команда закінчується рівно на \\r\\n."""
        return command.rstrip("\r\n") + "\r\n"

    @allure.step("UART TX: '{command}'")
    def send_command(self, command: str) -> list[str]:
        if not self.serial or not self.serial.is_open:
            raise RuntimeError("Serial port is not open. Call open() first.")

        formatted_command = self.ensure_ends_with_rn(command)

        self.serial.reset_input_buffer()
        self.serial.write(formatted_command.encode("utf-8"))
        self.serial.flush()

        time.sleep(0.3)

        lines = self.read_lines(self.timeout)

        # Додаємо вивід пристрою як вкладення до конкретного кроку команди
        if lines:
            allure.attach(
                "\n".join(lines),
                name=f"Response ({command})",
                attachment_type=allure.attachment_type.TEXT,
            )

        return lines

    @allure.step("Очікування паттерна у виводі: '{pattern}' (timeout: {timeout}s)")
    def wait_for(self, pattern: str, timeout: float) -> bool:
        if not self.serial or not self.serial.is_open:
            raise RuntimeError("Serial port is not open. Call open() first.")

        start_time = time.time()
        while (time.time() - start_time) < timeout:
            time_elapsed = time.time() - start_time
            lines = self.read_lines(min(0.2, timeout - time_elapsed))
            for line in lines:
                if pattern.lower() in line.lower():
                    return True
        return False

    @allure.step("Авторизація користувача '{username}'")
    def login(self, username: str, password: str) -> bool:
        response_lines = self.send_command(f"login {username} {password}")

        for line in response_lines:
            if "session started" in line.lower() or "logged in" in line.lower():
                return True

        return self.wait_for("session started", timeout=SERIAL_TIMEOUT)

    @allure.step("Перезавантаження пристрою (reboot)")
    def reboot(self, wait_pattern: str = "App started", timeout: float = BOOT_DELAY) -> bool:
        try:
            self.send_command("reboot")
        except Exception:
            pass

        # Замість жорсткого time.sleep(8.0) чекаємо паттерн App started
        return self.wait_for(wait_pattern, timeout=timeout)
