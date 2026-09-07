import allure
import pytest
from drivers.device_driver import DeviceDriver


@allure.epic("Embedded Testing")
@allure.feature("Configuration & NVS Persistence")
class TestConfigPersistence:

    @allure.story("NVS Persistence")
    @allure.title("Config Survives Reboot via NVS Save/Load")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.issue(
        "BUG-301", name="NVS Presistence issue. NVS doesnt load properly after reboot"
    )
    @pytest.mark.xfail
    @pytest.mark.config
    @pytest.mark.functional
    @pytest.mark.hw_9
    @pytest.mark.parametrize("threshold", [2, 10])  # , 50, 100, 400
    def test_config_survives_reboot(
        self,
        authenticated_device: DeviceDriver,  # Вже залогінений до reboot
        user_credentials: tuple[str, str],
        threshold: int,
    ):
        user, password = user_credentials

        with allure.step(
            f"1. Встановлення порогу: config set alarm_threshold {threshold}"
        ):
            set_res = " ".join(
                authenticated_device.send_command(
                    f"config set alarm_threshold {threshold}"
                )
            )
            assert (
                f"alarm_threshold = {threshold}" in set_res
            ), f"FAIL: Помилка встановлення конфігурації: '{set_res}'"

        with allure.step("2. Збереження налаштувань у NVS: config save"):
            save_res = " ".join(
                authenticated_device.send_command("config save")
            ).lower()
            assert (
                "Committing to NVS".lower() in save_res
                and "Saved successfully.".lower() in save_res
            ), f"FAIL: Не вдалося зберегти конфігурацію в NVS: '{save_res}'"

        authenticated_device.reboot()

        with allure.step("3. Повторна авторизація"):
            authenticated_device.send_command(f"register {user} {password}")
            authenticated_device.login(user, password)

        with allure.step("4. Завантаження налаштувань з NVS: config load"):
            load_res = " ".join(
                authenticated_device.send_command("config load")
            ).lower()
            assert (
                "loaded" in load_res or "ok" in load_res
            ), f"FAIL: Не вдалося завантажити конфігурацію з NVS: '{load_res}'"

        with allure.step(f"5. Перевірка, що збережений поріг дорівнює {threshold}"):
            get_res = " ".join(
                authenticated_device.send_command("config get alarm_threshold")
            )

            assert (
                f"alarm_threshold = {threshold}" in get_res
            ), f"FAIL: Значення alarm_threshold не збереглося після reboot! Отримано: '{get_res}'"
