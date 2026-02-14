# Claude Code Instructions for Oura Integration

This file contains instructions for Claude Code when working on this Home Assistant integration.

## Version Bumping

**IMPORTANT**: After implementing any new feature or fix, always bump the version number in `manifest.json` before committing.

### Semantic Versioning Rules

- **Patch** (2.7.0 → 2.7.1): Bug fixes, minor improvements, no new features
- **Minor** (2.7.0 → 2.8.0): New features, new sensors, backwards-compatible changes
- **Major** (2.7.0 → 3.0.0): Breaking changes, removed features, API changes

### Version Bump Workflow

1. **After completing implementation**, update `custom_components/oura/manifest.json`:
   ```json
   "version": "X.Y.Z"
   ```

2. **Create two commits**:
   ```bash
   # First commit: The feature/fix
   git add <modified files>
   git commit -m "feat: Description of feature"

   # Second commit: Version bump
   git add custom_components/oura/manifest.json
   git commit -m "chore: Bump version to X.Y.Z"

   git push
   ```

3. **OR combine in one commit** if the feature is small:
   ```bash
   git add <all files including manifest.json>
   git commit -m "feat: Description\n\nBump version to X.Y.Z"
   git push
   ```

### GitHub Release Creation

**CRITICAL**: After bumping the version and pushing, **ALWAYS create a GitHub release**. This is what users see as the "latest" version.

```bash
gh release create vX.Y.Z \
  --title "vX.Y.Z - Brief Feature Description" \
  --notes "$(cat <<'EOF'
## 🎉 What's New in vX.Y.Z

### New Sensors/Features
- List new sensors with entity IDs
- Describe new functionality

### Technical Improvements
- List code quality improvements
- Performance enhancements
- Bug fixes

### Use Cases
Provide example automations or use cases

### Files Changed
- List key modified files

**Full Changelog**: https://github.com/nicholasmparker/Oura-Home-Assistant-Integration-Full/compare/vPREV...vX.Y.Z
EOF
)"
```

**Release Notes Template:**
- Start with "What's New" for user-facing changes
- Include example automations for new sensors
- List technical improvements
- Always include the full changelog link

## Git Commit Conventions

Follow [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` - New features
- `fix:` - Bug fixes
- `chore:` - Maintenance (version bumps, dependencies)
- `docs:` - Documentation only
- `refactor:` - Code restructuring without behavior changes
- `test:` - Adding or updating tests

Always include:
```
Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
```

## Code Review

After completing a significant feature, invoke Bob for code review:
```
User: "bob can you check it out"
```

Bob will review for:
- Maintainability and readability
- Home Assistant best practices
- Potential bugs and edge cases
- Missing tests or translations

## Testing Checklist

Before marking work complete:

- [ ] Version bumped in `manifest.json`
- [ ] All files committed and pushed
- [ ] **GitHub release created** (users see this as "latest")
- [ ] `strings.json` translations added for new entities
- [ ] Bob code review completed
- [ ] Critical issues from Bob's review addressed
- [ ] Sensors follow HA state type rules (string/number/date/datetime/None)
- [ ] Binary sensors use `binary_sensor` platform (not sensor with on/off)
- [ ] Error handling includes 401 graceful degradation for optional features

## Home Assistant Specific Rules

### Sensor State Types
Sensor `native_value` MUST be one of:
- `str` (for text, comma-separated lists)
- `int` or `float` (for numbers)
- `datetime` (for timestamps)
- `None` (when unavailable)

**NEVER** return Python lists, dicts, or other types - use `extra_state_attributes` instead.

### Translation Files
Every new entity needs entries in `strings.json`:
```json
{
  "entity": {
    "sensor": {
      "sensor_key": {"name": "Sensor Name"}
    },
    "binary_sensor": {
      "binary_sensor_key": {"name": "Binary Sensor Name"}
    }
  }
}
```

### Statistics
When adding new statistics to `statistics.py`:
1. Add to `STATISTICS_METADATA` with proper `has_mean`/`has_sum` flags
2. Add to `DATA_SOURCE_CONFIG` with mappings or custom_processor
3. Implement and register custom processor if needed
4. Use `_parse_date_to_timestamp()` for consistent date handling

## Project Structure

```
custom_components/oura/
├── __init__.py          # Platform registration, setup
├── manifest.json        # VERSION LIVES HERE
├── const.py             # SENSOR_TYPES definitions
├── api.py               # Oura API endpoints
├── coordinator.py       # Data processing (_process_* methods)
├── sensor.py            # Sensor platform
├── binary_sensor.py     # Binary sensor platform
├── statistics.py        # Long-term statistics import
└── strings.json         # Entity translations
```

## When Adding New Sensors

1. **API Layer** (`api.py`):
   - Add to `API_ENDPOINTS` dict
   - Implement `_async_get_*()` method with 401 handling

2. **Coordinator** (`coordinator.py`):
   - Add `_process_*()` call to `_process_data()`
   - Implement processing method
   - Use `dt_util.now()` for timezone-aware dates

3. **Sensor Definitions** (`const.py`):
   - Add to `SENSOR_TYPES` dict with proper metadata

4. **Sensor Platform** (`sensor.py` or `binary_sensor.py`):
   - Add `extra_state_attributes` if needed
   - Binary states go in `binary_sensor.py` (use `is_on` property)

5. **Statistics** (`statistics.py`):
   - Add to `STATISTICS_METADATA`
   - Add to `DATA_SOURCE_CONFIG`
   - Implement custom processor if aggregation needed

6. **Translations** (`strings.json`):
   - Add entity translation entries

7. **Version Bump** (`manifest.json`):
   - Increment version appropriately

## Common Patterns

### 401 Error Handling (Optional Features)
```python
async def _async_get_feature(self, start_date, end_date):
    url = f"{API_BASE_URL}/feature"
    params = {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()}
    try:
        return await self._async_get(url, params)
    except ClientResponseError as err:
        if err.status == 401:  # Feature not available
            return {"data": []}
        raise
```

### Processing Today's Data
```python
def _process_data_type(self, data, processed):
    if data_list := data.get("data_type", {}).get("data"):
        if data_list and len(data_list) > 0:
            today = dt_util.now().date()
            # Filter for today or process latest entry
            latest = data_list[-1]
            processed["sensor_key"] = latest.get("field")
```

### Timestamp Parsing
```python
# ISO 8601 with Z or +00:00
datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
```

## Remember

- **Always** bump version after features
- **Always** add translations for new entities
- **Always** use proper sensor state types
- **Always** handle 401 errors gracefully for optional features
- **Never** commit without pushing
- **Never** skip Bob's review for significant changes
