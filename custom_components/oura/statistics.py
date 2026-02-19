"""Import historical Oura data as Home Assistant Long-Term Statistics.

This module provides a configuration-driven approach to importing Oura Ring data
as Home Assistant long-term statistics, significantly reducing code duplication.
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Callable

from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    async_import_statistics as async_import_statistics_ha,
    StatisticData,
    StatisticMetaData,
    StatisticMeanType,
)
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.const import (
    UnitOfTemperature,
    UnitOfTime,
    UnitOfEnergy,
    UnitOfLength,
)

from .const import DOMAIN, METERS_PER_MILE

_LOGGER = logging.getLogger(__name__)


def _get_unit_class(unit: str | None) -> str | None:
    """Map unit of measurement to device class for statistics.

    Required for Home Assistant 2026.11+ compatibility.
    Returns the appropriate device class string based on the unit,
    or None if the unit doesn't map to a standard device class.
    """
    if unit is None:
        return None

    # Map standard HA unit constants to device classes
    if unit in (UnitOfTime.HOURS, UnitOfTime.MINUTES, UnitOfTime.SECONDS):
        return SensorDeviceClass.DURATION
    if unit == UnitOfTemperature.CELSIUS:
        return SensorDeviceClass.TEMPERATURE
    if unit in (UnitOfEnergy.KILO_CALORIE, UnitOfEnergy.KILO_WATT_HOUR):
        return SensorDeviceClass.ENERGY
    if unit in (UnitOfLength.MILES, UnitOfLength.KILOMETERS, UnitOfLength.METERS):
        return SensorDeviceClass.DISTANCE

    # Custom units without standard device classes
    # These include: "score", "bpm", "ms", "steps", "MET·min",
    # "%", "ml/kg/min", "years"
    return None

# Statistics metadata for all Oura sensors
STATISTICS_METADATA = {
    "sleep_score": {"name": "Sleep Score", "unit": None, "has_mean": True, "has_sum": False},
    "sleep_efficiency": {"name": "Sleep Efficiency", "unit": "%", "has_mean": True, "has_sum": False},
    "restfulness": {"name": "Restfulness", "unit": "%", "has_mean": True, "has_sum": False},
    "sleep_timing": {"name": "Sleep Timing", "unit": None, "has_mean": True, "has_sum": False},
    "total_sleep_duration": {"name": "Total Sleep Duration", "unit": UnitOfTime.HOURS, "has_mean": True, "has_sum": False},
    "deep_sleep_duration": {"name": "Deep Sleep Duration", "unit": UnitOfTime.HOURS, "has_mean": True, "has_sum": False},
    "rem_sleep_duration": {"name": "REM Sleep Duration", "unit": UnitOfTime.HOURS, "has_mean": True, "has_sum": False},
    "light_sleep_duration": {"name": "Light Sleep Duration", "unit": UnitOfTime.HOURS, "has_mean": True, "has_sum": False},
    "awake_time": {"name": "Awake Time", "unit": UnitOfTime.HOURS, "has_mean": True, "has_sum": False},
    "sleep_latency": {"name": "Sleep Latency", "unit": UnitOfTime.MINUTES, "has_mean": True, "has_sum": False},
    "time_in_bed": {"name": "Time in Bed", "unit": UnitOfTime.HOURS, "has_mean": True, "has_sum": False},
    "bedtime_start": {"name": "Bedtime Start", "unit": None, "has_mean": False, "has_sum": False},
    "bedtime_end": {"name": "Bedtime End", "unit": None, "has_mean": False, "has_sum": False},
    "deep_sleep_percentage": {"name": "Deep Sleep Percentage", "unit": "%", "has_mean": True, "has_sum": False},
    "rem_sleep_percentage": {"name": "REM Sleep Percentage", "unit": "%", "has_mean": True, "has_sum": False},
    "average_sleep_hrv": {"name": "Average Sleep HRV", "unit": "ms", "has_mean": True, "has_sum": False},
    "lowest_sleep_heart_rate": {"name": "Lowest Sleep Heart Rate", "unit": "bpm", "has_mean": True, "has_sum": False},
    "average_sleep_heart_rate": {"name": "Average Sleep Heart Rate", "unit": "bpm", "has_mean": True, "has_sum": False},
    "readiness_score": {"name": "Readiness Score", "unit": None, "has_mean": True, "has_sum": False},
    "temperature_deviation": {"name": "Temperature Deviation", "unit": UnitOfTemperature.CELSIUS, "has_mean": True, "has_sum": False},
    "resting_heart_rate": {"name": "Resting Heart Rate Score", "unit": None, "has_mean": True, "has_sum": False},
    "hrv_balance": {"name": "HRV Balance Score", "unit": None, "has_mean": True, "has_sum": False},
    "sleep_regularity": {"name": "Sleep Regularity Score", "unit": None, "has_mean": True, "has_sum": False},
    "activity_score": {"name": "Activity Score", "unit": None, "has_mean": True, "has_sum": False},
    "steps": {"name": "Steps", "unit": "steps", "has_mean": False, "has_sum": True},
    "active_calories": {"name": "Active Calories", "unit": UnitOfEnergy.KILO_CALORIE, "has_mean": False, "has_sum": True},
    "total_calories": {"name": "Total Calories", "unit": UnitOfEnergy.KILO_CALORIE, "has_mean": False, "has_sum": True},
    "target_calories": {"name": "Target Calories", "unit": UnitOfEnergy.KILO_CALORIE, "has_mean": True, "has_sum": False},
    "met_min_high": {"name": "High Activity MET Minutes", "unit": "min", "has_mean": False, "has_sum": True},
    "met_min_medium": {"name": "Medium Activity MET Minutes", "unit": "min", "has_mean": False, "has_sum": True},
    "met_min_low": {"name": "Low Activity MET Minutes", "unit": "min", "has_mean": False, "has_sum": True},
    "average_heart_rate": {"name": "Average Heart Rate", "unit": "bpm", "has_mean": True, "has_sum": False},
    "min_heart_rate": {"name": "Minimum Heart Rate", "unit": "bpm", "has_mean": True, "has_sum": False},
    "max_heart_rate": {"name": "Maximum Heart Rate", "unit": "bpm", "has_mean": True, "has_sum": False},
    "stress_high_duration": {"name": "Stress High Duration", "unit": UnitOfTime.MINUTES, "has_mean": True, "has_sum": False},
    "recovery_high_duration": {"name": "Recovery High Duration", "unit": UnitOfTime.MINUTES, "has_mean": True, "has_sum": False},
    "stress_day_summary": {"name": "Stress Day Summary", "unit": None, "has_mean": False, "has_sum": False},
    "resilience_level": {"name": "Resilience Level", "unit": None, "has_mean": False, "has_sum": False},
    "sleep_recovery_score": {"name": "Sleep Recovery Score", "unit": None, "has_mean": True, "has_sum": False},
    "daytime_recovery_score": {"name": "Daytime Recovery Score", "unit": None, "has_mean": True, "has_sum": False},
    "stress_resilience_score": {"name": "Stress Resilience Score", "unit": None, "has_mean": True, "has_sum": False},
    "spo2_average": {"name": "SpO2 Average", "unit": "%", "has_mean": True, "has_sum": False},
    "breathing_disturbance_index": {"name": "Breathing Disturbance Index", "unit": None, "has_mean": True, "has_sum": False},
    "vo2_max": {"name": "VO2 Max", "unit": "ml/kg/min", "has_mean": True, "has_sum": False},
    "cardiovascular_age": {"name": "Cardiovascular Age", "unit": "years", "has_mean": True, "has_sum": False},
    "optimal_bedtime_start": {"name": "Optimal Bedtime Start", "unit": None, "has_mean": False, "has_sum": False},
    "optimal_bedtime_end": {"name": "Optimal Bedtime End", "unit": None, "has_mean": False, "has_sum": False},
    # Workout statistics (aggregated daily totals, separate from "last_workout_*" real-time sensors)
    "daily_workouts": {"name": "Daily Workouts", "unit": None, "has_mean": False, "has_sum": True},
    "daily_workout_distance": {"name": "Daily Workout Distance", "unit": UnitOfLength.MILES, "has_mean": False, "has_sum": True},
    "daily_workout_calories": {"name": "Daily Workout Calories", "unit": UnitOfEnergy.KILO_CALORIE, "has_mean": False, "has_sum": True},
    "daily_workout_duration": {"name": "Daily Workout Duration", "unit": UnitOfTime.MINUTES, "has_mean": False, "has_sum": True},
    # Session statistics (aggregated daily totals)
    "daily_mindfulness_sessions": {"name": "Daily Mindfulness Sessions", "unit": None, "has_mean": False, "has_sum": True},
    "daily_meditation_duration": {"name": "Daily Meditation Duration", "unit": UnitOfTime.MINUTES, "has_mean": False, "has_sum": True},
    # Tag statistics
    "daily_tag_count": {"name": "Daily Tag Count", "unit": None, "has_mean": False, "has_sum": True},
    # Rest Mode statistics
    "daily_rest_mode_duration": {"name": "Daily Rest Mode Duration", "unit": UnitOfTime.HOURS, "has_mean": False, "has_sum": True},
    "daily_rest_mode_count": {"name": "Daily Rest Mode Periods", "unit": None, "has_mean": False, "has_sum": True},
}

# Configuration mapping API data sources to sensor mappings
DATA_SOURCE_CONFIG = {
    "sleep": {
        "mappings": [
            {"sensor_key": "sleep_score", "api_path": "score"},
            # Note: sleep_efficiency moved to sleep_detail (actual %, not contributor score)
            {"sensor_key": "restfulness", "api_path": "contributors.restfulness"},
            {"sensor_key": "sleep_timing", "api_path": "contributors.timing"},
        ],
    },
    "sleep_detail": {
        "mappings": [
            {"sensor_key": "sleep_efficiency", "api_path": "efficiency"},  # Actual sleep efficiency %
            {"sensor_key": "total_sleep_duration", "api_path": "total_sleep_duration", "transform": "seconds_to_hours"},
            {"sensor_key": "deep_sleep_duration", "api_path": "deep_sleep_duration", "transform": "seconds_to_hours"},
            {"sensor_key": "rem_sleep_duration", "api_path": "rem_sleep_duration", "transform": "seconds_to_hours"},
            {"sensor_key": "light_sleep_duration", "api_path": "light_sleep_duration", "transform": "seconds_to_hours"},
            {"sensor_key": "awake_time", "api_path": "awake_time", "transform": "seconds_to_hours"},
            {"sensor_key": "sleep_latency", "api_path": "latency", "transform": "seconds_to_minutes"},
            {"sensor_key": "time_in_bed", "api_path": "time_in_bed", "transform": "seconds_to_hours"},
            {"sensor_key": "average_sleep_hrv", "api_path": "average_hrv"},
            {"sensor_key": "lowest_sleep_heart_rate", "api_path": "lowest_heart_rate"},
            {"sensor_key": "average_sleep_heart_rate", "api_path": "average_heart_rate"},
            {"sensor_key": "bedtime_start", "api_path": "bedtime_start", "transform": "iso_to_datetime"},
            {"sensor_key": "bedtime_end", "api_path": "bedtime_end", "transform": "iso_to_datetime"},
        ],
        "computed": [
            {
                "sensor_key": "deep_sleep_percentage",
                "compute": lambda entry: _compute_percentage(entry, "deep_sleep_duration", "total_sleep_duration"),
            },
            {
                "sensor_key": "rem_sleep_percentage",
                "compute": lambda entry: _compute_percentage(entry, "rem_sleep_duration", "total_sleep_duration"),
            },
        ],
    },
    "readiness": {
        "mappings": [
            {"sensor_key": "readiness_score", "api_path": "score"},
            {"sensor_key": "temperature_deviation", "api_path": "temperature_deviation"},
            {"sensor_key": "resting_heart_rate", "api_path": "contributors.resting_heart_rate"},
            {"sensor_key": "hrv_balance", "api_path": "contributors.hrv_balance"},
            {"sensor_key": "sleep_regularity", "api_path": "contributors.sleep_regularity"},
        ],
    },
    "activity": {
        "mappings": [
            {"sensor_key": "activity_score", "api_path": "score"},
            {"sensor_key": "steps", "api_path": "steps"},
            {"sensor_key": "active_calories", "api_path": "active_calories"},
            {"sensor_key": "total_calories", "api_path": "total_calories"},
            {"sensor_key": "target_calories", "api_path": "target_calories"},
            {"sensor_key": "met_min_high", "api_path": "high_activity_met_minutes"},
            {"sensor_key": "met_min_medium", "api_path": "medium_activity_met_minutes"},
            {"sensor_key": "met_min_low", "api_path": "low_activity_met_minutes"},
        ],
    },
    "heartrate": {
        "custom_processor": "heartrate",
    },
    "stress": {
        "mappings": [
            {"sensor_key": "stress_high_duration", "api_path": "stress_high", "transform": "seconds_to_minutes"},
            {"sensor_key": "recovery_high_duration", "api_path": "recovery_high", "transform": "seconds_to_minutes"},
            {"sensor_key": "stress_day_summary", "api_path": "day_summary"},
        ],
    },
    "resilience": {
        "mappings": [
            {"sensor_key": "resilience_level", "api_path": "level"},
            {"sensor_key": "sleep_recovery_score", "api_path": "contributors.sleep_recovery"},
            {"sensor_key": "daytime_recovery_score", "api_path": "contributors.daytime_recovery"},
            {"sensor_key": "stress_resilience_score", "api_path": "contributors.stress"},
        ],
    },
    "spo2": {
        "mappings": [
            {"sensor_key": "spo2_average", "api_path": "spo2_percentage.average"},
            {"sensor_key": "breathing_disturbance_index", "api_path": "breathing_disturbance_index"},
        ],
    },
    "vo2_max": {
        "mappings": [
            {"sensor_key": "vo2_max", "api_path": "vo2_max"},
        ],
    },
    "cardiovascular_age": {
        "mappings": [
            {"sensor_key": "cardiovascular_age", "api_path": "vascular_age"},
        ],
    },
    "sleep_time": {
        "mappings": [
            {"sensor_key": "optimal_bedtime_start", "api_path": "optimal_bedtime_start"},
            {"sensor_key": "optimal_bedtime_end", "api_path": "optimal_bedtime_end"},
        ],
    },
    "workout": {
        "custom_processor": "workout",
    },
    "session": {
        "custom_processor": "session",
    },
    "tag": {
        "custom_processor": "tag",
    },
    "enhanced_tag": {
        "custom_processor": "enhanced_tag",
    },
    "rest_mode": {
        "custom_processor": "rest_mode",
    },
}

# Custom processor registry - maps processor names to functions
# This avoids fragile globals() lookups
CUSTOM_PROCESSORS = {
    "heartrate": None,  # Will be set after function definition
    "workout": None,    # Will be set after function definition
    "session": None,    # Will be set after function definition
    "tag": None,        # Will be set after function definition
    "enhanced_tag": None,  # Will be set after function definition
    "rest_mode": None,  # Will be set after function definition
}


async def async_import_statistics(
    hass: HomeAssistant,
    data: dict[str, Any],
    entry: ConfigEntry,
) -> None:
    """Import historical Oura data as long-term statistics.

    Args:
        hass: Home Assistant instance
        data: Historical data from Oura API
        entry: Config entry for unique ID generation
    """
    _LOGGER.info("Starting statistics import from historical data")

    total_stats = 0

    # Process each configured data source
    for source_key, config in DATA_SOURCE_CONFIG.items():
        source_data = data.get(source_key, {}).get("data")
        if not source_data:
            continue

        # Check if custom processor is specified
        if custom_processor := config.get("custom_processor"):
            processor_func = CUSTOM_PROCESSORS.get(custom_processor)
            if processor_func:
                stats_count = await processor_func(hass, source_data, entry)
                total_stats += stats_count
                _LOGGER.debug("Imported %d %s statistics", stats_count, source_key)
            else:
                _LOGGER.error("Custom processor '%s' not found in registry", custom_processor)
            continue

        # Use generic processor
        stats_count = await _process_generic_statistics(hass, source_data, config, entry)
        total_stats += stats_count
        _LOGGER.debug("Imported %d %s statistics", stats_count, source_key)

    _LOGGER.info("Successfully imported %d total statistics data points", total_stats)


async def _process_generic_statistics(
    hass: HomeAssistant,
    data_list: list[dict[str, Any]],
    config: dict[str, Any],
    entry: ConfigEntry,
) -> int:
    """Process data using generic configuration-driven approach.

    Args:
        hass: Home Assistant instance
        data_list: List of data entries from API
        config: Configuration with mappings and computed fields
        entry: Config entry for unique ID generation

    Returns:
        Number of statistics imported
    """
    stats_count = 0

    # Initialize data collectors for each sensor
    sensor_data: dict[str, list[dict[str, Any]]] = {}
    for mapping in config.get("mappings", []):
        sensor_data[mapping["sensor_key"]] = []

    for computed in config.get("computed", []):
        sensor_data[computed["sensor_key"]] = []

    # Process each data entry
    for entry_data in data_list:
        timestamp = _parse_date_to_timestamp(entry_data.get("day"))
        if not timestamp:
            continue

        # Process direct mappings
        for mapping in config.get("mappings", []):
            value = _get_nested_value(entry_data, mapping["api_path"])
            if value is not None:
                # Apply transformation if specified
                if transform := mapping.get("transform"):
                    value = _apply_transformation(value, transform)

                sensor_data[mapping["sensor_key"]].append({
                    "timestamp": timestamp,
                    "value": value,
                })

        # Process computed fields
        for computed in config.get("computed", []):
            value = computed["compute"](entry_data)
            if value is not None:
                sensor_data[computed["sensor_key"]].append({
                    "timestamp": timestamp,
                    "value": value,
                })

    # Import statistics for each sensor
    for sensor_key, data_points in sensor_data.items():
        if data_points:
            await _create_statistic(hass, sensor_key, data_points, entry)
            stats_count += len(data_points)

    return stats_count


async def _process_heartrate_statistics(
    hass: HomeAssistant,
    heartrate_data: list[dict[str, Any]],
    entry: ConfigEntry,
) -> int:
    """Process heart rate data with special daily aggregation logic.

    Heart rate data comes as individual readings throughout the day,
    so we need to aggregate them into daily statistics.
    """
    stats_count = 0

    # Group heart rate readings by day
    daily_readings: dict[str, list[int]] = {}

    for data_entry in heartrate_data:
        if bpm := data_entry.get("bpm"):
            # Extract date from timestamp
            timestamp_str = data_entry.get("timestamp", "")
            if timestamp_str:
                day = timestamp_str.split("T")[0]
                if day not in daily_readings:
                    daily_readings[day] = []
                daily_readings[day].append(bpm)

    # Calculate daily statistics
    sensor_data = {
        "average_heart_rate": [],
        "min_heart_rate": [],
        "max_heart_rate": [],
    }

    for day, readings in daily_readings.items():
        timestamp = _parse_date_to_timestamp(day)
        if not timestamp or not readings:
            continue

        sensor_data["average_heart_rate"].append({
            "timestamp": timestamp,
            "value": sum(readings) / len(readings),
        })
        sensor_data["min_heart_rate"].append({
            "timestamp": timestamp,
            "value": min(readings),
        })
        sensor_data["max_heart_rate"].append({
            "timestamp": timestamp,
            "value": max(readings),
        })

    # Import statistics
    for sensor_key, data_points in sensor_data.items():
        if data_points:
            await _create_statistic(hass, sensor_key, data_points, entry)
            stats_count += len(data_points)

    return stats_count


async def _process_workout_statistics(
    hass: HomeAssistant,
    workout_data: list[dict[str, Any]],
    entry: ConfigEntry,
) -> int:
    """Process workout data with daily aggregation logic.

    Workouts need to be aggregated by day to calculate:
    - Number of workouts per day
    - Total distance per day
    - Total calories per day
    - Total workout duration per day
    """
    stats_count = 0

    # Group workouts by day
    daily_workouts: dict[str, list[dict[str, Any]]] = {}

    for workout in workout_data:
        day = workout.get("day")
        if day:
            if day not in daily_workouts:
                daily_workouts[day] = []
            daily_workouts[day].append(workout)

    # Calculate daily statistics
    sensor_data = {
        "daily_workouts": [],
        "daily_workout_distance": [],
        "daily_workout_calories": [],
        "daily_workout_duration": [],
    }

    for day, workouts in daily_workouts.items():
        timestamp = _parse_date_to_timestamp(day)
        if not timestamp:
            continue

        # Count workouts
        sensor_data["daily_workouts"].append({
            "timestamp": timestamp,
            "value": len(workouts),
        })

        # Sum distance (convert from meters to miles)
        total_distance_meters = sum(w.get("distance", 0) for w in workouts if w.get("distance"))
        if total_distance_meters > 0:
            sensor_data["daily_workout_distance"].append({
                "timestamp": timestamp,
                "value": round(total_distance_meters / METERS_PER_MILE, 2),
            })

        # Sum calories
        total_calories = sum(w.get("calories", 0) for w in workouts if w.get("calories"))
        if total_calories > 0:
            sensor_data["daily_workout_calories"].append({
                "timestamp": timestamp,
                "value": total_calories,
            })

        # Sum duration (convert to minutes)
        total_duration = 0
        for workout in workouts:
            start_time = workout.get("start_datetime")
            end_time = workout.get("end_datetime")
            if start_time and end_time:
                try:
                    start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                    end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                    duration_seconds = (end_dt - start_dt).total_seconds()
                    total_duration += duration_seconds
                except (ValueError, AttributeError):
                    pass

        if total_duration > 0:
            sensor_data["daily_workout_duration"].append({
                "timestamp": timestamp,
                "value": total_duration / 60,  # Convert to minutes
            })

    # Import statistics
    for sensor_key, data_points in sensor_data.items():
        if data_points:
            await _create_statistic(hass, sensor_key, data_points, entry)
            stats_count += len(data_points)

    return stats_count


# Register workout processor
CUSTOM_PROCESSORS["workout"] = _process_workout_statistics


async def _process_session_statistics(
    hass: HomeAssistant,
    session_data: list[dict[str, Any]],
    entry: ConfigEntry,
) -> int:
    """Process session data with daily aggregation logic.

    Sessions (meditation, breathing, rest) need to be aggregated by day to calculate:
    - Number of mindfulness sessions per day
    - Total meditation duration per day
    """
    stats_count = 0

    # Group sessions by day
    daily_sessions: dict[str, list[dict[str, Any]]] = {}

    for session in session_data:
        day = session.get("day")
        if day:
            if day not in daily_sessions:
                daily_sessions[day] = []
            daily_sessions[day].append(session)

    # Calculate daily statistics
    sensor_data = {
        "daily_mindfulness_sessions": [],
        "daily_meditation_duration": [],
    }

    mindfulness_types = ["meditation", "breathing", "rest"]

    for day, sessions in daily_sessions.items():
        timestamp = _parse_date_to_timestamp(day)
        if not timestamp:
            continue

        # Filter to mindfulness sessions
        mindfulness_sessions = [
            s for s in sessions
            if s.get("type") in mindfulness_types
        ]

        # Count mindfulness sessions
        sensor_data["daily_mindfulness_sessions"].append({
            "timestamp": timestamp,
            "value": len(mindfulness_sessions),
        })

        # Sum duration (convert to minutes)
        total_duration = 0
        for session in mindfulness_sessions:
            start_time = session.get("start_datetime")
            end_time = session.get("end_datetime")
            if start_time and end_time:
                try:
                    start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                    end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                    duration_seconds = (end_dt - start_dt).total_seconds()
                    total_duration += duration_seconds
                except (ValueError, AttributeError):
                    pass

        if total_duration > 0:
            sensor_data["daily_meditation_duration"].append({
                "timestamp": timestamp,
                "value": total_duration / 60,  # Convert to minutes
            })

    # Import statistics
    for sensor_key, data_points in sensor_data.items():
        if data_points:
            await _create_statistic(hass, sensor_key, data_points, entry)
            stats_count += len(data_points)

    return stats_count


# Register session processor
CUSTOM_PROCESSORS["session"] = _process_session_statistics


async def _process_tag_statistics(
    hass: HomeAssistant,
    tag_data: list[dict[str, Any]],
    entry: ConfigEntry,
) -> int:
    """Process tag data for statistics import.

    Note: Basic tag endpoint doesn't provide rich enough data for meaningful statistics.
    Use enhanced_tag processor instead.
    """
    return 0


async def _process_enhanced_tag_statistics(
    hass: HomeAssistant,
    enhanced_tag_data: list[dict[str, Any]],
    entry: ConfigEntry,
) -> int:
    """Process enhanced tag data with daily aggregation logic.

    Enhanced tags provide rich metadata (tag_type_code, start_time, end_time, comment)
    and are aggregated by day to calculate daily tag counts.
    """
    stats_count = 0

    # Group enhanced tags by day
    daily_tags: dict[str, int] = {}

    for tag_entry in enhanced_tag_data:
        day = tag_entry.get("day")
        if day:
            if day not in daily_tags:
                daily_tags[day] = 0
            daily_tags[day] += 1

    # Create daily statistics
    sensor_data = {
        "daily_tag_count": [],
    }

    for day, count in daily_tags.items():
        timestamp = _parse_date_to_timestamp(day)
        if not timestamp:
            continue

        sensor_data["daily_tag_count"].append({
            "timestamp": timestamp,
            "value": count,
        })

    # Import statistics
    for sensor_key, data_points in sensor_data.items():
        if data_points:
            await _create_statistic(hass, sensor_key, data_points, entry)
            stats_count += len(data_points)

    return stats_count


async def _process_rest_mode_statistics(
    hass: HomeAssistant,
    rest_mode_data: list[dict[str, Any]],
    entry: ConfigEntry,
) -> int:
    """Process rest mode data with daily aggregation logic.

    Rest mode periods are aggregated by day to calculate:
    - Number of rest mode periods per day
    - Total rest mode duration per day (in hours)
    """
    stats_count = 0

    # Track rest mode periods that overlap with each day
    daily_rest_mode: dict[str, dict[str, Any]] = {}

    for period in rest_mode_data:
        start_day = period.get("start_day")
        end_day = period.get("end_day")
        start_time = period.get("start_time")
        end_time = period.get("end_time")

        if not all([start_day, end_day, start_time, end_time]):
            continue

        try:
            start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
            duration_seconds = (end_dt - start_dt).total_seconds()

            # For simplicity, attribute the entire period to the start day
            # In a more sophisticated approach, we could split multi-day periods
            if start_day not in daily_rest_mode:
                daily_rest_mode[start_day] = {
                    "count": 0,
                    "total_duration": 0,
                }

            daily_rest_mode[start_day]["count"] += 1
            daily_rest_mode[start_day]["total_duration"] += duration_seconds

        except (ValueError, AttributeError) as e:
            _LOGGER.debug("Error parsing rest mode period: %s", e)
            continue

    # Create daily statistics
    sensor_data = {
        "daily_rest_mode_count": [],
        "daily_rest_mode_duration": [],
    }

    for day, stats in daily_rest_mode.items():
        timestamp = _parse_date_to_timestamp(day)
        if not timestamp:
            continue

        # Count of rest mode periods
        sensor_data["daily_rest_mode_count"].append({
            "timestamp": timestamp,
            "value": stats["count"],
        })

        # Total duration in hours
        duration_hours = stats["total_duration"] / 3600
        if duration_hours > 0:
            sensor_data["daily_rest_mode_duration"].append({
                "timestamp": timestamp,
                "value": duration_hours,
            })

    # Import statistics
    for sensor_key, data_points in sensor_data.items():
        if data_points:
            await _create_statistic(hass, sensor_key, data_points, entry)
            stats_count += len(data_points)

    return stats_count


# Register tag processors
CUSTOM_PROCESSORS["tag"] = _process_tag_statistics
CUSTOM_PROCESSORS["enhanced_tag"] = _process_enhanced_tag_statistics
CUSTOM_PROCESSORS["rest_mode"] = _process_rest_mode_statistics


# Register heartrate processor
CUSTOM_PROCESSORS["heartrate"] = _process_heartrate_statistics


async def _create_statistic(
    hass: HomeAssistant,
    sensor_key: str,
    data_points: list[dict[str, Any]],
    entry: ConfigEntry,
) -> None:
    """Create and import a statistic for a sensor."""
    if not data_points:
        return

    metadata = STATISTICS_METADATA.get(sensor_key)
    if not metadata:
        _LOGGER.warning("No metadata found for sensor: %s", sensor_key)
        return

    # Hybrid approach for statistic_id
    # 1. Try to find existing entity in registry
    # 2. Fallback to default naming convention if not found
    registry = er.async_get(hass)
    unique_id = f"{entry.entry_id}_{sensor_key}"
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)

    if entity_id:
        statistic_id = entity_id
    else:
        # Fallback for fresh installs where entities don't exist yet
        # Matches the default entity ID format: sensor.oura_ring_{sensor_key}
        statistic_id = f"sensor.oura_ring_{sensor_key}"

    # Determine source and import method
    # If statistic_id has a colon, it's an external statistic (domain:name)
    # If not, it's an entity ID (sensor.name), so we use the recorder source
    if ":" in statistic_id:
        source = DOMAIN
        import_func = async_add_external_statistics
    else:
        source = "recorder"
        import_func = async_import_statistics_ha

    # Determine mean_type based on sensor characteristics
    if not metadata["has_mean"]:
        mean_type = StatisticMeanType.NONE
    elif sensor_key in ("optimal_bedtime_start", "optimal_bedtime_end"):
        # Time of day values should use circular mean for proper averaging
        mean_type = StatisticMeanType.CIRCULAR
    else:
        # All other numeric sensors use arithmetic mean
        mean_type = StatisticMeanType.ARITHMETIC

    # Get unit_class for HA 2026.11+ compatibility
    unit_class = _get_unit_class(metadata["unit"])

    # Create metadata
    stat_metadata = StatisticMetaData(
        has_mean=metadata["has_mean"],
        has_sum=metadata["has_sum"],
        mean_type=mean_type,
        name=metadata["name"],
        source=source,
        statistic_id=statistic_id,
        unit_class=unit_class,
        unit_of_measurement=metadata["unit"],
    )

    # Create data points
    statistics = []
    for point in data_points:
        stat_data = StatisticData(
            start=point["timestamp"],
            mean=point["value"] if metadata["has_mean"] else None,
            sum=point["value"] if metadata["has_sum"] else None,
        )
        statistics.append(stat_data)

    # Import to database
    import_func(hass, stat_metadata, statistics)
    _LOGGER.debug(
        "Imported %d statistics for %s (%s)",
        len(statistics),
        metadata["name"],
        sensor_key,
    )


def _get_nested_value(data: dict[str, Any], path: str) -> Any:
    """Get a value from nested dictionary using dot notation.

    Args:
        data: Dictionary to extract from
        path: Dot-separated path (e.g., "contributors.efficiency")

    Returns:
        Value at path, or None if not found
    """
    keys = path.split(".")
    value = data

    for key in keys:
        if isinstance(value, dict):
            value = value.get(key)
            if value is None:
                return None
        else:
            return None

    return value


def _apply_transformation(value: Any, transform: str, **kwargs) -> Any:
    """Apply a transformation to a value.

    Args:
        value: Value to transform
        transform: Transformation name
        **kwargs: Additional arguments for transformation

    Returns:
        Transformed value
    """
    if transform == "seconds_to_hours":
        return value / 3600
    elif transform == "seconds_to_minutes":
        return value / 60
    elif transform == "percentage":
        total = kwargs.get("total", 100)
        return (value / total) * 100 if total else 0
    elif transform == "iso_to_datetime":
        # Parse ISO datetime string to datetime object
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                return None
        return value

    return value


def _compute_percentage(entry: dict[str, Any], numerator_key: str, denominator_key: str) -> float | None:
    """Compute a percentage from two entry fields.

    Args:
        entry: Data entry
        numerator_key: Key for numerator value
        denominator_key: Key for denominator value

    Returns:
        Percentage value rounded to 1 decimal, or None if can't compute
    """
    numerator = entry.get(numerator_key)
    denominator = entry.get(denominator_key)

    if numerator is None or denominator is None or denominator == 0:
        return None

    return round((numerator / denominator) * 100, 1)


def _parse_date_to_timestamp(date_str: str | None) -> datetime | None:
    """Parse ISO date string to datetime object.

    Args:
        date_str: ISO format date string (e.g., "2024-01-15")

    Returns:
        Datetime object in UTC timezone, or None if parsing fails
    """
    if not date_str:
        return None

    try:
        # Parse the date string and set time to noon UTC
        # This ensures statistics appear on the correct day in all timezones
        date_parts = date_str.split("T")[0].split("-")
        year, month, day = int(date_parts[0]), int(date_parts[1]), int(date_parts[2])
        return datetime(year, month, day, 12, 0, 0, tzinfo=timezone.utc)
    except (ValueError, IndexError) as err:
        _LOGGER.warning("Failed to parse date '%s': %s", date_str, err)
        return None
