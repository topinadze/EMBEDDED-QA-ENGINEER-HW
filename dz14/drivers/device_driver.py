import re
import time
import serial
import allure

try:
    from config.wifi_config import (
        SERIAL_BAUDRATE,
        SERIAL_TIMEOUT,
        REBOOT_TIMEOUT,
        WIFI_CONNECT_TIMEOUT,
    )
except ModuleNotFoundError:
    from dz14.config.wifi_config import (
        SERIAL_BAUDRATE,
        SERIAL_TIMEOUT,
        REBOOT_TIMEOUT,
        WIFI_CONNECT_TIMEOUT,
    )


class DeviceDriver:
    """
    UART Device Driver для ESP32-S3 (SENTRY-C1 / station_WiFi / Bluedroid_GATT_Server).
    Побудований на базі оригінального DeviceDriver з підтримкою Wi-Fi та BLE.
    """
    ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    IP_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
    # Парсить вивід сканування: "  [ 1] TopA-node                         -33 dBm"
    SCAN_LINE_PATTERN = re.compile(r"\[\s*\d+\s*\]\s*(.*?)\s+-\d+\s*dBm", re.IGNORECASE)
    SCAN_SSID_PATTERN = re.compile(r"\bSSID:\s*(.+)$", re.IGNORECASE)

    def __init__(self, port: str, timeout: float = SERIAL_TIMEOUT):
        self.port = port
        self.timeout = timeout
        self.serial: serial.Serial | None = None
        self.last_wifi_connect_duration: float | None = None
        self.uart_log: list[str] = []
        self._sensitive_uart_values: set[str] = set()

    def reset_uart_log(self) -> None:
        self.uart_log.clear()
        self._sensitive_uart_values.clear()

    def attach_uart_log(self) -> None:
        log_text = "\n".join(self.uart_log)
        for value in sorted(self._sensitive_uart_values, key=len, reverse=True):
            log_text = log_text.replace(value, "[REDACTED]")

        allure.attach(
            log_text or "No UART output was captured.",
            name="UART log",
            attachment_type=allure.attachment_type.TEXT,
        )

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

    @allure.step("Очищення та закриття serial-порту")
    def close(self) -> None:
        if self.serial and self.serial.is_open:
            self.serial.close()
            self.serial = None

    #@allure.step("Зчитування всіх рядків з serial-порту протягом заданого timeout: '{timeout}'")
    def read_lines(self, timeout: float) -> list[str]:
        """
        Зчитує всі рядки з порту протягом заданого timeout.
        Зберігає оригінальну логіку фільтрації ANSI та CR/LF.
        Зчитує доступні байти чанками без зависання на рядках-промптах без кінцевого '\\n'.
        """
        if not self.serial or not self.serial.is_open:
            raise RuntimeError("Serial port is not open. Call open() first.")

        lines = []
        start_time = time.time()
        buffer = ""

        while (time.time() - start_time) < timeout:
            if self.serial.in_waiting > 0:
                raw_chunk = self.serial.read(self.serial.in_waiting)
                try:
                    chunk_str = raw_chunk.decode("utf-8", errors="replace")
                except Exception:
                    chunk_str = str(raw_chunk)

                buffer += chunk_str

                if "\n" in buffer:
                    parts = buffer.split("\n")
                    for p in parts[:-1]:
                        cleaned = p.replace("\r", "")
                        cleaned = self.ANSI_ESCAPE.sub("", cleaned).strip()
                        if cleaned:
                            lines.append(cleaned)
                    buffer = parts[-1]
            else:
                time.sleep(0.01)

        # Залишок у буфері (наприклад, інтерактивний промпт без \n)
        if buffer:
            cleaned = buffer.replace("\r", "")
            cleaned = self.ANSI_ESCAPE.sub("", cleaned).strip()
            if cleaned:
                lines.append(cleaned)

        self.uart_log.extend(lines)
        return lines

    def ensure_ends_with_rn(self, command: str) -> str:
        """Гарантує, що команда закінчується рівно на \\r\\n."""
        return command.rstrip("\r\n") + "\r\n"
    
    def send_line(self, command: str) -> None:
        """Відправляє команду/рядок у UART без очищення буфера (для інтерактивних діалогів)."""
        if not self.serial or not self.serial.is_open:
            raise RuntimeError("Serial port is not open. Call open() first.")
        formatted = self.ensure_ends_with_rn(command)
        self.serial.write(formatted.encode("utf-8"))
        self.serial.flush()

    @allure.step("UART TX: '{command}'")
    def send_command(self, command: str, timeout: float = SERIAL_TIMEOUT) -> list[str]:
        if not self.serial or not self.serial.is_open:
            raise RuntimeError("Serial port is not open. Call open() first.")

        formatted_command = self.ensure_ends_with_rn(command)

        self.serial.reset_input_buffer()
        self.serial.write(formatted_command.encode("utf-8"))
        self.serial.flush()

        time.sleep(0.15)
        lines = self.read_lines(timeout)

        if lines:
            try:
                allure.attach(
                    "\n".join(lines),
                    name=f"Response ({command})",
                    attachment_type=allure.attachment_type.TEXT,
                )
            except Exception:
                pass

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

    def wait_for_any(self, patterns: list[str], timeout: float) -> str | None:
        """Очікує появу будь-якого з патернів у виводі. Повертає перший знайдений патерн або None."""
        if not self.serial or not self.serial.is_open:
            raise RuntimeError("Serial port is not open. Call open() first.")

        start_time = time.time()
        while (time.time() - start_time) < timeout:
            time_elapsed = time.time() - start_time
            lines = self.read_lines(min(0.2, timeout - time_elapsed))
            for line in lines:
                line_lower = line.lower()
                for p in patterns:
                    if p.lower() in line_lower:
                        return p
        return None

    @allure.step("Перезавантаження пристрою (reboot)")
    def reboot(self, wait_pattern: str = "ready", timeout: float = REBOOT_TIMEOUT) -> bool:
        try:
            self.send_command("reboot")
        except Exception:
            pass
        return self.wait_for(wait_pattern, timeout=timeout)

    # =========================================================================
    # Методи розширення для ДЗ-14 (Wi-Fi згідно секції A1)
    # =========================================================================

    @allure.step("Wi-Fi Scan: Пошук доступних мереж")
    def wifi_scan(self, timeout: float = 8.0) -> list[str]:
        """
        Відправляє 'scan' та повертає список імен знайдених мереж (SSID).
        """
        lines = self.send_command("scan", timeout=timeout)
        ssids: list[str] = []

        for line in lines:
            match = self.SCAN_LINE_PATTERN.search(line)
            if match:
                ssid = match.group(1).strip()
                field_match = self.SCAN_SSID_PATTERN.search(ssid)
                if field_match:
                    ssid = re.split(
                        r"\s+RSSI:",
                        field_match.group(1),
                        maxsplit=1,
                        flags=re.IGNORECASE,
                    )[0].strip()
            else:
                field_match = self.SCAN_SSID_PATTERN.search(line)
                if not field_match:
                    continue
                ssid = re.split(
                    r"\s+RSSI:", field_match.group(1), maxsplit=1, flags=re.IGNORECASE
                )[0].strip()

            if ssid and ssid not in ssids:
                ssids.append(ssid)

        try:
            allure.attach(
                f"Знайдено мереж: {len(ssids)}\nSSIDs:\n" + "\n".join(ssids),
                name="Wi-Fi Scan Result",
                attachment_type=allure.attachment_type.TEXT,
            )
        except Exception:
            pass

        return ssids

    @allure.step("Wi-Fi Connect: Інтерактивний діалог для '{ssid}'")
    def wifi_connect(
        self,
        ssid: str = "",
        password: str = "",
        timeout: float = WIFI_CONNECT_TIMEOUT,
    ) -> bool:
        """
        Проходить інтерактивний діалог команди 'connect':
        1. Відправляє 'connect'
        2. Дочікується промпта SSID (або вибору мережі)
        3. Відправляє SSID (або Enter)
        4. Якщо запитується пароль — дочікується промпта пароля та відправляє password
        5. Дочікується результату з'єднання.
        Повертає True або False.
        """
        self.last_wifi_connect_duration = None
        if password:
            self._sensitive_uart_values.add(password)
        self.serial.reset_input_buffer()
        self.send_line("connect")

        # 1. Очікуємо промпт вибору мережі / SSID (сканування займає ~3-4 сек)
        matched = self.wait_for_any(
            ["enter ssid", "number from list", "select ssid", "enter password"],
            timeout=7.0,
        )
        if not matched:
            return False

        #Якщо прошивка одразу попросила пароль (connect був з аргументом)
        if "password" in matched.lower() and not ssid:
            with allure.step("UART TX: Wi-Fi password (redacted)"):
                self.send_line(password)
            connect_started = time.monotonic()
        else:
            # 2. Відправляємо SSID (або Enter)
            self.send_line(ssid)
            connect_started = time.monotonic() if not ssid else None

            # 3. Якщо вводили SSID (не порожній Enter), чекаємо на промпт пароля
            if ssid:
                matched_pwd = self.wait_for_any(
                    ["enter password", "password:", "too short"], timeout=5.0
                )
                if not matched_pwd:
                    return False

                if "too short" in matched_pwd.lower():
                    return False

                with allure.step("UART TX: Wi-Fi password (redacted)"):
                    self.send_line(password)
                connect_started = time.monotonic()

        # 4. Очікуємо результату з'єднання
        start_res = time.monotonic()
        while (time.monotonic() - start_res) < timeout:
            remaining = timeout - (time.monotonic() - start_res)
            lines = self.read_lines(min(0.5, remaining))
            full_text = " ".join(lines).lower()

            if "too short" in full_text or "connection timeout" in full_text:
                return False
            if "got ip" in full_text or "sta connected" in full_text:
                if connect_started is not None:
                    self.last_wifi_connect_duration = time.monotonic() - connect_started
                return True
            if "fail" in full_text or "disconnect" in full_text:
                if "retry to connect" not in full_text and "connected to ssid" not in full_text:
                    return False

        # Останній фолбек перевірки статусу
        return self.wifi_status()["connected"]

    @allure.step("Wi-Fi Status: Отримання статусу підключення")
    def wifi_status(self, timeout: float = 2.0) -> dict:
        """
        Виконує команду 'status' та повертає dict:
        {'connected': bool, 'ssid': str | None, 'ip': str | None, 'rssi': str | None, 'raw': list[str]}
        """
        lines = self.send_command("status", timeout=timeout)
        full_text = " ".join(lines).lower()

        ip_match = self.IP_PATTERN.search(full_text)
        ip_addr = ip_match.group(0) if ip_match else None

        if "disconnected" in full_text or "not connected" in full_text:
            connected = False
        elif "got ip" in full_text or "connected" in full_text or ip_addr is not None:
            connected = True
        else:
            connected = False

        ssid = None
        rssi = None

        for line in lines:
            line_lower = line.lower()
            if "ssid:" in line_lower:
                parts = line.split("ssid:", 1)
                if len(parts) > 1:
                    ssid_candidate = parts[1].split()[0].strip() if parts[1].split() else None
                    if ssid_candidate:
                        ssid = ssid_candidate
            if "rssi:" in line_lower:
                parts = line.split("rssi:", 1)
                if len(parts) > 1:
                    rssi_candidate = parts[1].split()[0].strip() if parts[1].split() else None
                    if rssi_candidate:
                        rssi = rssi_candidate

        result = {
            "connected": connected,
            "ssid": ssid,
            "ip": ip_addr,
            "rssi": rssi,
            "raw": lines,
        }

        try:
            allure.attach(
                str(result),
                name="Parsed Wi-Fi Status",
                attachment_type=allure.attachment_type.TEXT,
            )
        except Exception:
            pass

        return result

    @allure.step("Wi-Fi Disconnect: Розрив Wi-Fi з'єднання")
    def wifi_disconnect(self, timeout: float = 3.0) -> list[str]:
        """Виконує команду 'disconnect'."""
        return self.send_command("disconnect", timeout=timeout)
