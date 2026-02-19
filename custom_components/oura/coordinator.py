"""DataUpdateCoordinator for Oura Ring."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import OuraApiClient
from .const import DOMAIN, DEFAULT_UPDATE_INTERVAL, METERS_PER_MILE
from .statistics import async_import_statistics

_LOGGER = logging.getLogger(__name__)


class OuraDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching Oura Ring data."""

    def __init__(
        self,
        hass: HomeAssistant,
        api_client: OuraApiClient,
        entry: ConfigEntry,
        update_interval_minutes: int = DEFAULT_UPDATE_INTERVAL,
    ) -> None:
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=update_interval_minutes),
        )
        self.api_client = api_client
        self.entry = entry
        self.historical_data_loaded = False

    async def _async_update_data(self) -> dict[str, Any]:
        """Update data via API."""
        try:
            # For regular updates, only fetch 1 day of data
            data = await self.api_client.async_get_data(days_back=1)
            processed_data = self._process_data(data)

            # Check if we got any actual data back
            # If all endpoints failed, processed_data will be empty
            if not processed_data:
                _LOGGER.warning(
                    "No data returned from API (all endpoints failed). "
                    "Keeping existing data if available. Will retry in %s minutes.",
                    self.update_interval.total_seconds() / 60,
                )
                # If we have existing data, keep it
                if self.data:
                    return self.data
                # If no existing data, this is a problem
                raise UpdateFailed("No data available from API")

            return processed_data

        except Exception as err:
            # Log the error but keep existing data to maintain sensor states
            # This handles transient network issues gracefully
            _LOGGER.warning(
                "Error communicating with API (will retry in %s minutes): %s",
                self.update_interval.total_seconds() / 60,
                err
            )

            # If we have existing data, return it to keep sensors showing last known values
            if self.data:
                _LOGGER.debug("Keeping existing data due to transient error")
                return self.data

            # If no existing data (first run), raise the error
            raise UpdateFailed(f"Error communicating with API: {err}") from err

    async def async_load_historical_data(self, days: int) -> None:
        """Load historical data on first setup.

        Args:
            days: Number of days of historical data to fetch
        """
        try:
            _LOGGER.info("Loading %d days of historical data...", days)
            historical_data = await self.api_client.async_get_data(days_back=days)

            # Import historical data as long-term statistics
            try:
                await async_import_statistics(self.hass, historical_data, self.entry)
                _LOGGER.info("Historical data loaded successfully")
            except Exception as stats_err:
                _LOGGER.error("Failed to import statistics: %s", stats_err)
                raise

            # Process and store the LATEST day's data for current sensor states
            processed_data = self._process_data(historical_data)

            # Update the coordinator's data with current information
            self.data = processed_data
            self.historical_data_loaded = True
        except Exception as err:
            _LOGGER.error("Failed to fetch historical data: %s", err)
            raise

    def _process_data(self, data: dict[str, Any]) -> dict[str, Any]:
        """Process the raw API data into sensor values.

        Orchestrates processing of all data sources by delegating to specialized methods.
        """
        processed = {}

        # Process each data type using specialized methods
        self._process_sleep_scores(data, processed)
        self._process_sleep_details(data, processed)
        self._process_readiness(data, processed)
        self._process_activity(data, processed)
        self._process_heart_rate(data, processed)
        self._process_stress(data, processed)
        self._process_resilience(data, processed)
        self._process_spo2(data, processed)
        self._process_vo2_max(data, processed)
        self._process_cardiovascular_age(data, processed)
        self._process_sleep_time(data, processed)
        self._process_workout(data, processed)
        self._process_session(data, processed)
        self._process_tag(data, processed)
        self._process_enhanced_tag(data, processed)
        self._process_rest_mode(data, processed)

        return processed

    def _process_sleep_scores(self, data: dict[str, Any], processed: dict[str, Any]) -> None:
        """Process sleep scores (contribution scores, not durations)."""
        if sleep_data := data.get("sleep", {}).get("data"):
            if sleep_data and len(sleep_data) > 0:
                latest_sleep = sleep_data[-1]
                processed["sleep_score"] = latest_sleep.get("score")
                # Store the data date for verification
                if day := latest_sleep.get("day"):
                    processed["_data_date"] = day
                if contributors := latest_sleep.get("contributors"):
                    efficiency_value = contributors.get("efficiency")
                    _LOGGER.debug("Sleep efficiency from daily_sleep contributors: %s", efficiency_value)
                    processed["sleep_efficiency"] = efficiency_value
                    processed["restfulness"] = contributors.get("restfulness")
                    processed["sleep_timing"] = contributors.get("timing")

    def _process_sleep_details(self, data: dict[str, Any], processed: dict[str, Any]) -> None:
        """Process detailed sleep data (actual durations and HRV)."""
        if sleep_detail_data := data.get("sleep_detail", {}).get("data"):
            if sleep_detail_data and len(sleep_detail_data) > 0:
                latest_sleep_detail = sleep_detail_data[-1]

                # Check if sleep_detail has an efficiency field
                if "efficiency" in latest_sleep_detail:
                    _LOGGER.debug("Sleep efficiency found in sleep_detail endpoint: %s", latest_sleep_detail.get("efficiency"))

                # Extract duration values
                total_sleep_seconds = latest_sleep_detail.get("total_sleep_duration")
                deep_sleep_seconds = latest_sleep_detail.get("deep_sleep_duration")
                rem_sleep_seconds = latest_sleep_detail.get("rem_sleep_duration")
                light_sleep_seconds = latest_sleep_detail.get("light_sleep_duration")

                # Convert durations from seconds to hours (0 is valid for sleep durations)
                if total_sleep_seconds is not None:
                    processed["total_sleep_duration"] = total_sleep_seconds / 3600
                if deep_sleep_seconds is not None:
                    processed["deep_sleep_duration"] = deep_sleep_seconds / 3600
                if rem_sleep_seconds is not None:
                    processed["rem_sleep_duration"] = rem_sleep_seconds / 3600
                if light_sleep_seconds is not None:
                    processed["light_sleep_duration"] = light_sleep_seconds / 3600
                if (awake := latest_sleep_detail.get("awake_time")) is not None:
                    processed["awake_time"] = awake / 3600
                if (latency := latest_sleep_detail.get("latency")) is not None:
                    processed["sleep_latency"] = latency / 60  # Convert to minutes
                if (time_in_bed := latest_sleep_detail.get("time_in_bed")) is not None:
                    processed["time_in_bed"] = time_in_bed / 3600

                # Calculate sleep stage percentages
                if total_sleep_seconds and total_sleep_seconds > 0:
                    if deep_sleep_seconds is not None:
                        processed["deep_sleep_percentage"] = round(
                            (deep_sleep_seconds / total_sleep_seconds) * 100, 1
                        )
                    if rem_sleep_seconds is not None:
                        processed["rem_sleep_percentage"] = round(
                            (rem_sleep_seconds / total_sleep_seconds) * 100, 1
                        )

                # HRV during sleep
                if average_hrv := latest_sleep_detail.get("average_hrv"):
                    processed["average_sleep_hrv"] = average_hrv

                # Bedtime timestamps (when you went to sleep and woke up)
                # Parse ISO 8601 datetime strings (e.g., "2024-01-15T23:30:00+00:00") to datetime objects
                if bedtime_start := latest_sleep_detail.get("bedtime_start"):
                    try:
                        processed["bedtime_start"] = datetime.fromisoformat(bedtime_start.replace('Z', '+00:00'))
                    except (ValueError, AttributeError) as e:
                        _LOGGER.debug("Error parsing bedtime_start '%s': %s", bedtime_start, e)

                if bedtime_end := latest_sleep_detail.get("bedtime_end"):
                    try:
                        processed["bedtime_end"] = datetime.fromisoformat(bedtime_end.replace('Z', '+00:00'))
                    except (ValueError, AttributeError) as e:
                        _LOGGER.debug("Error parsing bedtime_end '%s': %s", bedtime_end, e)


                if lowest_heart_rate := latest_sleep_detail.get("lowest_heart_rate"):
                    processed["lowest_sleep_heart_rate"] = lowest_heart_rate
                if average_heart_rate := latest_sleep_detail.get("average_heart_rate"):
                    processed["average_sleep_heart_rate"] = average_heart_rate

                # Low battery alert flag (always set, defaults to False)
                processed["low_battery_alert"] = latest_sleep_detail.get("low_battery_alert", False)

    def _process_readiness(self, data: dict[str, Any], processed: dict[str, Any]) -> None:
        """Process readiness data (contributors are scores 1-100)."""
        if readiness_data := data.get("readiness", {}).get("data"):
            if readiness_data and len(readiness_data) > 0:
                latest_readiness = readiness_data[-1]
                processed["readiness_score"] = latest_readiness.get("score")
                processed["temperature_deviation"] = latest_readiness.get("temperature_deviation")

                if contributors := latest_readiness.get("contributors"):
                    processed["resting_heart_rate"] = contributors.get("resting_heart_rate")
                    processed["hrv_balance"] = contributors.get("hrv_balance")
                    # Sleep regularity is a separate contributor in the readiness data
                    if sleep_regularity := contributors.get("sleep_regularity"):
                        processed["sleep_regularity"] = sleep_regularity

    def _process_activity(self, data: dict[str, Any], processed: dict[str, Any]) -> None:
        """Process activity data (steps, calories, MET minutes)."""
        if activity_data := data.get("activity", {}).get("data"):
            if activity_data and len(activity_data) > 0:
                latest_activity = activity_data[-1]
                processed["activity_score"] = latest_activity.get("score")
                processed["steps"] = latest_activity.get("steps")
                processed["active_calories"] = latest_activity.get("active_calories")
                processed["total_calories"] = latest_activity.get("total_calories")
                processed["target_calories"] = latest_activity.get("target_calories")
                processed["met_min_high"] = latest_activity.get("high_activity_met_minutes")
                processed["met_min_medium"] = latest_activity.get("medium_activity_met_minutes")
                processed["met_min_low"] = latest_activity.get("low_activity_met_minutes")

    def _process_heart_rate(self, data: dict[str, Any], processed: dict[str, Any]) -> None:
        """Process heart rate data with aggregation from recent readings."""
        if heartrate_data := data.get("heartrate", {}).get("data"):
            if heartrate_data and len(heartrate_data) > 0:
                # Latest reading
                latest_hr = heartrate_data[-1]
                processed["current_heart_rate"] = latest_hr.get("bpm")
                processed["heart_rate_timestamp"] = latest_hr.get("timestamp")

                # Aggregate recent readings
                recent_readings = [hr.get("bpm") for hr in heartrate_data[-10:] if hr.get("bpm")]
                if recent_readings:
                    processed["average_heart_rate"] = sum(recent_readings) / len(recent_readings)
                    processed["min_heart_rate"] = min(recent_readings)
                    processed["max_heart_rate"] = max(recent_readings)

    def _process_stress(self, data: dict[str, Any], processed: dict[str, Any]) -> None:
        """Process stress data (durations and day summary)."""
        if stress_data := data.get("stress", {}).get("data"):
            if stress_data and len(stress_data) > 0:
                latest_stress = stress_data[-1]
                # Convert from seconds to minutes - 0 is valid for stress durations
                if (stress_high := latest_stress.get("stress_high")) is not None:
                    processed["stress_high_duration"] = stress_high / 60
                if (recovery_high := latest_stress.get("recovery_high")) is not None:
                    processed["recovery_high_duration"] = recovery_high / 60
                processed["stress_day_summary"] = latest_stress.get("day_summary")

    def _process_resilience(self, data: dict[str, Any], processed: dict[str, Any]) -> None:
        """Process resilience data (level and recovery scores)."""
        if resilience_data := data.get("resilience", {}).get("data"):
            if resilience_data and len(resilience_data) > 0:
                latest_resilience = resilience_data[-1]
                processed["resilience_level"] = latest_resilience.get("level")

                if contributors := latest_resilience.get("contributors"):
                    processed["sleep_recovery_score"] = contributors.get("sleep_recovery")
                    processed["daytime_recovery_score"] = contributors.get("daytime_recovery")
                    processed["stress_resilience_score"] = contributors.get("stress")

    def _process_spo2(self, data: dict[str, Any], processed: dict[str, Any]) -> None:
        """Process SpO2 data (blood oxygen - Gen3 and Oura Ring 4 only)."""
        if spo2_data := data.get("spo2", {}).get("data"):
            if spo2_data and len(spo2_data) > 0:
                latest_spo2 = spo2_data[-1]
                if spo2_percentage := latest_spo2.get("spo2_percentage"):
                    processed["spo2_average"] = spo2_percentage.get("average")
                processed["breathing_disturbance_index"] = latest_spo2.get("breathing_disturbance_index")

    def _process_vo2_max(self, data: dict[str, Any], processed: dict[str, Any]) -> None:
        """Process VO2 Max fitness data."""
        if vo2_max_data := data.get("vo2_max", {}).get("data"):
            if vo2_max_data and len(vo2_max_data) > 0:
                latest_vo2 = vo2_max_data[-1]
                processed["vo2_max"] = latest_vo2.get("vo2_max")

    def _process_cardiovascular_age(self, data: dict[str, Any], processed: dict[str, Any]) -> None:
        """Process cardiovascular age data."""
        if cardiovascular_age_data := data.get("cardiovascular_age", {}).get("data"):
            if cardiovascular_age_data and len(cardiovascular_age_data) > 0:
                latest_cv_age = cardiovascular_age_data[-1]
                processed["cardiovascular_age"] = latest_cv_age.get("vascular_age")

    def _process_sleep_time(self, data: dict[str, Any], processed: dict[str, Any]) -> None:
        """Process sleep time recommendations (optimal bedtime windows).

        Converts seconds-from-midnight offsets to UTC datetime using the day_tz timezone offset.
        """
        if sleep_time_data := data.get("sleep_time", {}).get("data"):
            if sleep_time_data and len(sleep_time_data) > 0:
                latest_sleep_time = sleep_time_data[-1]

                if optimal_bedtime := latest_sleep_time.get("optimal_bedtime"):
                    day_str = latest_sleep_time.get("day")
                    day_tz = optimal_bedtime.get("day_tz", 0)
                    start_offset = optimal_bedtime.get("start_offset")
                    end_offset = optimal_bedtime.get("end_offset")

                    if day_str and start_offset is not None:
                        try:
                            date_obj = datetime.strptime(day_str, "%Y-%m-%d")
                            # Convert offsets (seconds from midnight local time) to UTC
                            start_dt = date_obj + timedelta(seconds=start_offset) - timedelta(seconds=day_tz)
                            end_dt = date_obj + timedelta(seconds=end_offset) - timedelta(seconds=day_tz)

                            # Make timezone-aware for Home Assistant
                            start_dt = start_dt.replace(tzinfo=timezone.utc)
                            end_dt = end_dt.replace(tzinfo=timezone.utc)

                            processed["optimal_bedtime_start"] = start_dt
                            processed["optimal_bedtime_end"] = end_dt
                        except Exception as e:
                            _LOGGER.warning("Error calculating sleep time: %s", e)

    def _process_workout(self, data: dict[str, Any], processed: dict[str, Any]) -> None:
        """Process workout data (count, type, distance, calories, intensity, duration)."""
        if workout_data := data.get("workout", {}).get("data"):
            if workout_data and len(workout_data) > 0:
                # Get today's date for filtering (using HA's configured timezone)
                today = dt_util.now().date()
                _LOGGER.debug("Processing %d workouts. Today's date: %s", len(workout_data), today)

                # Count workouts that occurred today
                today_workouts = []
                for w in workout_data:
                    if day_str := w.get("day"):
                        try:
                            workout_date = datetime.strptime(day_str, "%Y-%m-%d").date()
                            if workout_date == today:
                                today_workouts.append(w)
                        except ValueError:
                            _LOGGER.debug("Error parsing workout day: %s", day_str)

                processed["workouts_today"] = len(today_workouts)
                _LOGGER.debug("Found %d workouts for today. Workout days: %s",
                             len(today_workouts), [w.get("day") for w in workout_data])

                # Get the most recent workout for "last_workout_*" sensors
                latest_workout = workout_data[-1]

                # Extract workout type (activity name)
                if activity := latest_workout.get("activity"):
                    processed["last_workout_type"] = activity

                # Extract distance (convert from meters to miles) - 0 is valid for stationary workouts
                if (distance := latest_workout.get("distance")) is not None:
                    processed["last_workout_distance"] = round(distance / METERS_PER_MILE, 2)

                # Extract calories - 0 is valid
                if (calories := latest_workout.get("calories")) is not None:
                    processed["last_workout_calories"] = calories

                # Extract intensity (easy, moderate, hard)
                if intensity := latest_workout.get("intensity"):
                    processed["last_workout_intensity"] = intensity

                # Calculate duration from start/end timestamps
                start_time = latest_workout.get("start_datetime")
                end_time = latest_workout.get("end_datetime")

                if start_time and end_time:
                    try:
                        start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                        end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                        duration_seconds = (end_dt - start_dt).total_seconds()
                        # Convert to minutes
                        processed["last_workout_duration"] = duration_seconds / 60
                    except (ValueError, AttributeError) as e:
                        _LOGGER.debug("Error calculating workout duration: %s", e)

                # Store raw workout data for sensor attributes
                processed["_last_workout_raw"] = latest_workout

    def _process_session(self, data: dict[str, Any], processed: dict[str, Any]) -> None:
        """Process session data (mindfulness, meditation, breathing)."""
        if session_data := data.get("session", {}).get("data"):
            if session_data and len(session_data) > 0:
                # Get today's date for filtering (using HA's configured timezone)
                today = dt_util.now().date()

                # Filter sessions for today
                today_sessions = [
                    s for s in session_data
                    if s.get("day") and datetime.fromisoformat(s["day"]).date() == today
                ]

                # Count mindfulness sessions (meditation or breathing types)
                mindfulness_types = ["meditation", "breathing", "rest"]
                mindfulness_sessions = [
                    s for s in today_sessions
                    if s.get("type") in mindfulness_types
                ]
                processed["mindfulness_sessions_today"] = len(mindfulness_sessions)

                # Sum duration of all mindfulness sessions (convert from seconds to minutes)
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
                        except (ValueError, AttributeError) as e:
                            _LOGGER.debug("Error calculating session duration: %s", e)

                # Convert total duration to minutes
                processed["meditation_duration_today"] = total_duration / 60

    def _process_tag(self, data: dict[str, Any], processed: dict[str, Any]) -> None:
        """Process tag data (user-created tags for tracking events)."""
        if tag_data := data.get("tag", {}).get("data"):
            if tag_data and len(tag_data) > 0:
                # Get today's date for filtering (using HA's configured timezone)
                today = dt_util.now().date()

                # Filter tags for today
                today_tags = []
                for tag_entry in tag_data:
                    if day_str := tag_entry.get("day"):
                        try:
                            tag_date = datetime.strptime(day_str, "%Y-%m-%d").date()
                            if tag_date == today:
                                # Extract the tags list from this entry
                                if tags := tag_entry.get("tags"):
                                    today_tags.extend(tags)
                        except ValueError:
                            _LOGGER.debug("Error parsing tag day: %s", day_str)

                # Remove duplicates while preserving order
                unique_tags = list(dict.fromkeys(today_tags))

                # Store as comma-separated string (HA sensor states must be string/number/date/datetime/None)
                # The list is also stored in attributes for programmatic access
                processed["tags_today"] = ", ".join(unique_tags) if unique_tags else ""
                processed["_tags_today_list"] = unique_tags  # Store list for attributes
                processed["tag_count_today"] = len(unique_tags)

                # Store latest tag entry for attributes
                if tag_data:
                    processed["_latest_tag_entry"] = tag_data[-1]

    def _process_enhanced_tag(self, data: dict[str, Any], processed: dict[str, Any]) -> None:
        """Process enhanced tag data (provides tag_type_code, start_time, end_time, comment)."""
        if enhanced_tag_data := data.get("enhanced_tag", {}).get("data"):
            if enhanced_tag_data and len(enhanced_tag_data) > 0:
                # Get today's date for filtering (using HA's configured timezone)
                today = dt_util.now().date()

                # Filter enhanced tags for today
                today_enhanced_tags = []
                for enhanced_tag_entry in enhanced_tag_data:
                    if day_str := enhanced_tag_entry.get("day"):
                        try:
                            tag_date = datetime.strptime(day_str, "%Y-%m-%d").date()
                            if tag_date == today:
                                today_enhanced_tags.append(enhanced_tag_entry)
                        except ValueError:
                            _LOGGER.debug("Error parsing enhanced tag day: %s", day_str)

                # Store enhanced tag data for sensor attributes
                # This provides rich metadata: tag_type_code, start_time, end_time, comment
                processed["_enhanced_tags_today"] = today_enhanced_tags

    def _process_rest_mode(self, data: dict[str, Any], processed: dict[str, Any]) -> None:
        """Process rest mode period data."""
        # Set default to prevent stale states when API data stops arriving
        processed["rest_mode_active"] = False

        if rest_mode_data := data.get("rest_mode", {}).get("data"):
            if rest_mode_data and len(rest_mode_data) > 0:
                # Get current time
                now = dt_util.now()

                # Check if any rest mode period is currently active
                is_active = False
                active_period = None
                active_start_time = None
                active_end_time = None

                for period in rest_mode_data:
                    start_time_str = period.get("start_time")
                    end_time_str = period.get("end_time")

                    if start_time_str and end_time_str:
                        try:
                            start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                            end_time = datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))

                            # Check if current time is within this period
                            if start_time <= now <= end_time:
                                is_active = True
                                active_period = period
                                active_start_time = start_time
                                active_end_time = end_time
                                break
                        except (ValueError, AttributeError) as e:
                            _LOGGER.debug("Error parsing rest mode times: %s", e)

                # Store rest mode status
                processed["rest_mode_active"] = is_active

                # Store timestamps if rest mode is active (reuse already-parsed datetimes)
                if is_active and active_period:
                    processed["rest_mode_start"] = active_start_time
                    processed["rest_mode_end"] = active_end_time
                    processed["_active_rest_mode_raw"] = active_period
