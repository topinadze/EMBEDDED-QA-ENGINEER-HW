import statistics
import allure
import pytest
from drivers.device_driver import DeviceDriver


@pytest.fixture
def distance_physical_env(authenticated_device: DeviceDriver):
    """
    Підготовка середовища для фізичного датчика (HC-SR04 / US-025 / US-100):
    1. Перемикає пристрій у режим вимірювання відстані та запускає сенсор.
    2. Teardown: Зупиняє сенсор і повертає стандартний режим.
    """
    authenticated_device.send_command("sensor mode distance")
    authenticated_device.send_command("sensor start")
    
    yield authenticated_device
    
    with allure.step("Teardown: Зупинка сенсора та повернення режимів"):
        authenticated_device.send_command("sensor stop")
        authenticated_device.send_command("sensor mode temp")


@allure.epic("Embedded Hardware Testing")
@allure.feature("Physical Distance Sensor")
class TestDistanceStability:

    @allure.story("Physical Sensor Stability")
    @allure.title("Test physical distance readings stability across 100 measurements")
    @allure.severity(allure.severity_level.CRITICAL)
    @pytest.mark.distance
    @pytest.mark.functional
    @pytest.mark.hw_9
    def test_distance_readings_are_stable(
        self,
        distance_physical_env: DeviceDriver,
    ):
        """
        Збір 100 вимірів з реального датчика та розрахунок статистики.
        Переконайтеся, що об'єкт зафіксований на відстані ~35–50 см від датчика.
        """
        device = distance_physical_env
        num_samples = 100

        with allure.step(f"1. Збір {num_samples} реальних вимірів з датчика"):
            raw_readings = device.get_distance_readings(
                samples_count=num_samples, 
                timeout_per_sample=0.05
            )

        with allure.step("2. Обчислення та формування Allure Attachment зі статистикою"):
            # Фільтруємо можливі таймаути/помилки (-1.0)
            valid_readings = [r for r in raw_readings if r > 0]
            failed_count = len(raw_readings) - len(valid_readings)

            assert len(valid_readings) > 0, "Усі виміри повернули помилку або таймаут!"

            # Обчислення метрик
            mean_val = statistics.mean(valid_readings)
            std_val = statistics.stdev(valid_readings) if len(valid_readings) > 1 else 0.0
            min_val = min(valid_readings)
            max_val = max(valid_readings)
            spread = max_val - min_val

            # Формування тексту для звітів
            metrics_report = (
                f"=== PHYSICAL SENSOR STABILITY REPORT ===\n"
                f"Total Samples Requested: {num_samples}\n"
                f"Valid Samples Received:  {len(valid_readings)}\n"
                f"Failed/Timeout Samples:  {failed_count}\n"
                f"----------------------------------------\n"
                f"Mean Distance:           {mean_val:.2f} cm\n"
                f"Std Deviation (Noise):   {std_val:.2f} cm\n"
                f"Min Reading:             {min_val:.2f} cm\n"
                f"Max Reading:             {max_val:.2f} cm\n"
                f"Spread (Max - Min):      {spread:.2f} cm\n"
                f"========================================"
            )

            # Консольний вивід
            print(f"\n{metrics_report}")

            # Allure Attachment
            allure.attach(
                metrics_report,
                name="Physical Distance Sensor Statistics",
                attachment_type=allure.attachment_type.TEXT,
            )

        with allure.step("3. Перевірка критеріїв стабільності (Asserts)"):
            assert failed_count == 0, f"Виявлено {failed_count} таймаутів/збоїв під час збору вимірів!"
            assert std_val < 1.5, f"Std {std_val:.2f} cm >= 1.5 cm (занадто високий шум)!"
            assert spread < 5.0, f"Max-Min spread ({spread:.2f} cm) >= 5.0 cm (виявлено сплески/викиди)!"