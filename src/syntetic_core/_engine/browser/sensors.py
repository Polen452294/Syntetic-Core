"""Native Chromium Generic Sensor readings for a stationary, coherent pose."""

import math
from typing import Any

from playwright.async_api import Page

from syntetic_core._engine.personas import SensorMotion, StationarySensors


def sensor_readings(pose: StationarySensors) -> dict[str, dict[str, dict[str, float]]]:
    roll, pitch, yaw = (math.radians(v) / 2 for v in (pose.roll, pose.pitch, pose.yaw))
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    x, y, z, w = (
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
        cr * cp * cy + sr * sp * sy,
    )
    # Quaternion rotates device coordinates into the reference frame. Rotate
    # reference gravity by its inverse to obtain acceleration in device axes.
    gravity = {
        "x": 9.80665 * 2 * (x * z - w * y),
        "y": 9.80665 * 2 * (y * z + w * x),
        "z": 9.80665 * (1 - 2 * (x * x + y * y)),
    }
    zero = {"x": 0.0, "y": 0.0, "z": 0.0}
    return {
        "accelerometer": {"xyz": gravity},
        "gravity": {"xyz": gravity},
        "linear-acceleration": {"xyz": zero},
        "gyroscope": {"xyz": zero},
        "relative-orientation": {"quaternion": {"x": x, "y": y, "z": z, "w": w}},
    }


def perlin_value_and_rate(position: float, seed: int) -> tuple[float, float]:
    """Seeded 1D gradient noise and its analytic derivative (both continuous)."""
    cell = math.floor(position)
    fraction = position - cell

    def gradient(index: int) -> float:
        value = ((index & 0xFFFFFFFF) ^ seed) & 0xFFFFFFFF
        value = ((value ^ (value >> 16)) * 0x7FEB352D) & 0xFFFFFFFF
        value = ((value ^ (value >> 15)) * 0x846CA68B) & 0xFFFFFFFF
        return 1.0 if (value ^ (value >> 16)) & 1 else -1.0

    left, right = gradient(cell), gradient(cell + 1)
    fade = fraction**3 * (fraction * (fraction * 6 - 15) + 10)
    slope = 30 * fraction**2 * (fraction - 1) ** 2
    a, b = left * fraction, right * (fraction - 1)
    return 2 * (a + fade * (b - a)), 2 * (left + slope * (b - a) + fade * (right - left))


def moving_sensor_readings(
    base: StationarySensors, motion: SensorMotion, elapsed: float
) -> dict[str, dict[str, dict[str, float]]]:
    angular_frequency = 2 * math.pi / motion.period_seconds
    phase = angular_frequency * elapsed
    noise = [
        perlin_value_and_rate(elapsed + 0.37, motion.tremor_seed + axis * 7919) for axis in range(3)
    ]
    angles = [
        motion.amplitude * math.sin(phase + offset) + motion.tremor_amplitude * value
        for offset, (value, _) in zip((0, math.pi / 2, math.pi / 4), noise, strict=True)
    ]
    pose = StationarySensors(
        roll=(base.roll + angles[0] + 180) % 360 - 180,
        pitch=base.pitch + angles[1],
        yaw=(base.yaw + angles[2]) % 360,
    )
    readings = sensor_readings(pose)
    velocity = math.radians(motion.amplitude) * angular_frequency
    roll_rate, pitch_rate, yaw_rate = (
        velocity * math.cos(phase + offset) + math.radians(motion.tremor_amplitude) * rate
        for offset, (_, rate) in zip((0, math.pi / 2, math.pi / 4), noise, strict=True)
    )
    roll, pitch = math.radians(pose.roll), math.radians(pose.pitch)
    readings["gyroscope"] = {
        "xyz": {
            "x": roll_rate - yaw_rate * math.sin(pitch),
            "y": pitch_rate * math.cos(roll) + yaw_rate * math.sin(roll) * math.cos(pitch),
            "z": -pitch_rate * math.sin(roll) + yaw_rate * math.cos(roll) * math.cos(pitch),
        }
    }
    return readings


SENSOR_OBSERVATION_SCRIPT = """async () => Object.fromEntries(await Promise.all(
        [['accelerometer', 'Accelerometer'], ['gyroscope', 'Gyroscope'],
         ['relative-orientation', 'RelativeOrientationSensor']].map(([key, name]) =>
            new Promise((resolve, reject) => {
                if (typeof window[name] !== 'function') {
                    reject(new Error(name + ' unavailable')); return;
                }
                const sensor = new window[name]({frequency: 30});
                const finish = (callback, value) => {
                    clearTimeout(timer); sensor.stop(); callback(value);
                };
                const timer = setTimeout(() => finish(reject,
                    new Error(name + ' reading timeout')), 3000);
                sensor.onreading = () => finish(resolve, [key,
                    sensor.quaternion ? {quaternion: Array.from(sensor.quaternion)}
                        : {x:sensor.x, y:sensor.y, z:sensor.z}]);
                sensor.onerror = event => finish(reject, new Error(event.error.name));
                sensor.start();
            })
        )
    ))"""


async def observe_sensors(page: Page) -> dict[str, Any]:
    """Observe sensor events; does not grant permissions or install emulation."""
    return await page.evaluate(SENSOR_OBSERVATION_SCRIPT)


def readings_match(pose: StationarySensors, actual: dict[str, Any]) -> bool:
    expected = sensor_readings(pose)
    for kind in ("accelerometer", "gyroscope", "relative-orientation"):
        reading = actual.get(kind, {})
        if kind == "relative-orientation":
            values = reading.get("quaternion", [])
            target = list(expected[kind]["quaternion"].values())
            if len(values) != 4:
                return False
            # Chromium rounds angle and axis to 0.1 degrees for privacy.
            # A quaternion and its negation represent the same orientation.
            if (
                all(isinstance(value, (float, int)) for value in values)
                and sum(value * wanted for value, wanted in zip(values, target, strict=True)) < 0
            ):
                target = [-value for value in target]
            tolerance = 0.002
        else:
            values = [reading.get(axis) for axis in ("x", "y", "z")]
            target = list(expected[kind]["xyz"].values())
            # Native accelerometer readings are rounded to the nearest 0.1 m/s².
            tolerance = 0.050001 if kind == "accelerometer" else 1e-6
        if any(
            not isinstance(value, (float, int))
            or not math.isclose(value, wanted, abs_tol=tolerance)
            for value, wanted in zip(values, target, strict=True)
        ):
            return False
    return True
