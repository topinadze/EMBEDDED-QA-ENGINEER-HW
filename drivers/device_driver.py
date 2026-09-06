import re
import time
import serial


class DeviceDriver:
    ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

    def __init__(self, port: str, timeout: float = 2.0):
        self.port = port
        self.timeout = timeout
        self.serial: serial.Serial | None = None

    def open(self) -> None:
        """Відкриває serial-з'єднання та очищує буфери."""
        if self.serial is None:
            self.serial = serial.Serial(
                port=self.port,
                baudrate=115200,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout,
            )
        elif not self.serial.is_open:
            self.serial.open()
        # Чистимо буфери
        self.serial.reset_input_buffer()
        self.serial.reset_output_buffer()

    def close(self) -> None:
        """Очищує та закриває serial-порт."""
        if self.serial and self.serial.is_open:
            self.serial.close()
            self.serial = None

    def read_lines(self, timeout: float) -> list[str]:
        """Зчитує всі рядки з serial-порту протягом заданого timeout."""
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

                # 1. Прибираємо всі \r та \n
                cleaned_line = line_str.replace("\r", "").replace("\n", "")

                # 2. Видаляємо ANSI escape-коди
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

    def send_command(self, command: str) -> list[str]:
        """Відправляє команду в serial-порт та повертає відповідь."""
        if not self.serial or not self.serial.is_open:
            raise RuntimeError("Serial port is not open. Call open() first.")

        formatted_command = self.ensure_ends_with_rn(command)

        self.serial.reset_input_buffer()
        self.serial.write(formatted_command.encode("utf-8"))
        self.serial.flush()

        time.sleep(0.3)

        return self.read_lines(self.timeout)

    def wait_for(self, pattern: str, timeout: float) -> bool:
        """Очікує появу підрядка pattern у виводі протягом timeout."""
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

    def login(self, username: str, password: str) -> bool:
        """Виконує авторизацію та перевіряє успішність сесії."""
        response_lines = self.send_command(f"login {username} {password}")
        print(f"[LOGIN RESPONSE]: {response_lines}")

        for line in response_lines:
            if "session started" in line.lower() or "logged in" in line.lower():
                return True

        return self.wait_for("session started", timeout=2.0)

    def reboot(self):
        """Виконує перезавантаження девайсу"""
        # При перезагрузці логи можуть не читатись тому ловимо і ігноруємо помилки
        try:
            self.send_command("reboot")
        except Exception:
            pass

        time.sleep(3.0)

        if self.serial and self.serial.is_open:
            self.serial.reset_input_buffer()
            self.serial.reset_output_buffer()
