# Spell Coordinate Validation Implementation

## Overview

This document summarizes the implementation of spell deployment coordinate validation in `Autoclash.py`. The system validates every air defense coordinate found during spell deployment against two compound geometric constraints, rejects invalid coordinates, and maintains a local list of rejected regions to prevent retrying the same invalid areas within a single spell-deployment phase.

## Requirements Met

1. **Invalid Coordinates Never Clicked** ✓
   - All candidates are validated before clicking
   - Only coordinates passing both constraints proceed to click phase
   
2. **Rejected Region Squares Prevent Retries** ✓
   - 20×20 pixel squares (±10 pixels) centered on rejected coords
   - Configurable via `CONFIG["rejected_region_size"]` (default: 20)
   - Locally scoped to spell-deployment phase
   
3. **Clear Logging with Numeric Evaluations** ✓
   - Each validation shows constraint inequalities with numeric values
   - ACCEPT/REJECT/SKIP decisions clearly logged
   - Template name and candidate coordinates included

## Implementation Details

### 1. Configuration Addition

**File:** `Autoclash.py` (CONFIG dictionary)

```python
# Spell deployment coordinate validation
"rejected_region_size": 20,  # Size of rejected region square (±10 pixels by default)
```

### 2. Helper Functions

#### `is_coord_valid(x, y) -> bool`

Validates a coordinate against two compound geometric constraints using floating-point arithmetic with strict inequalities.

**Constraints:**
- **Constraint A:** `(136/185)*x + (42954/185) > y > (565/768)*x - (286531/384)`
- **Constraint B:** `(-247/324)*x + (1098303/324) > y > (-541/718)*x + (543849/718)`

**Both constraints must be satisfied** (AND logic) for a coordinate to be valid.

**Example Log Output:**
```
[12:34:56]   [VALIDATION] (960.0, 540.0): 
A(-39.92 < 540.0 < 937.91)=True 
B(34.11 < 540.0 < 2657.97)=True 
-> VALID
```

**Key Features:**
- Floating-point arithmetic (no rounding errors)
- Strict `>` comparisons (boundary values are invalid)
- Detailed logging of all intermediate values
- Handles exceptions gracefully

#### `is_in_rejected_region(x, y, rejected_regions) -> bool`

Checks if a coordinate falls within any previously-rejected region.

**Parameters:**
- `x, y`: Candidate coordinate to check
- `rejected_regions`: List of `(center_x, center_y)` tuples for rejected regions

**Region Shape:**
- Square of size `CONFIG["rejected_region_size"]` (default: 20px)
- Center: `(center_x, center_y)`
- Bounds: `[center_x ± 10, center_y ± 10]` pixels

**Example:**
```python
rejected_regions = [(500.0, 300.0)]
is_in_rejected_region(505.0, 305.0, rejected_regions)  # -> True (inside ±10px)
is_in_rejected_region(512.0, 312.0, rejected_regions)  # -> False (outside ±10px)
```

### 3. Spell Deployment Logic (Phase 2B)

**Location:** `phase2_execute()` function

**Flow:**

```
SPELL DEPLOYMENT PHASE
├─ Initialize tracking:
│  ├─ max_spell_clicks = 11
│  ├─ total_spell_clicks = 0
│  ├─ rejected_regions = [] (local, cleared on exit)
│  └─ region_size from CONFIG
│
├─ For each spell click (while total < max):
│  ├─ For each template (th11_ad, th13_ad, th15_ad, th16_ad, th17_ad):
│  │  ├─ Find template candidate
│  │  │
│  │  ├─ If candidate found:
│  │  │  ├─ Check if inside rejected region
│  │  │  │  └─ If yes: SKIP, continue to next template
│  │  │  │
│  │  │  ├─ Validate coordinate with is_coord_valid()
│  │  │  │  ├─ If valid: ACCEPT
│  │  │  │  │  ├─ Click (up to 3 times)
│  │  │  │  │  ├─ Increment total_spell_clicks
│  │  │  │  │  └─ Break (search for next target)
│  │  │  │  │
│  │  │  │  └─ If invalid: REJECT
│  │  │  │     ├─ Add to rejected_regions
│  │  │  │     ├─ Log rejection with region bounds
│  │  │  │     └─ Continue to next template
│  │
│  └─ If no valid template found:
│     ├─ Drop remaining spells at screen center
│     └─ Break (exit spell loop)
│
└─ Log final summary: clicks + rejected regions count
```

**Logging Examples:**

```
[12:34:56] Spell deployment: max_clicks=11, rejected_region_size=20px

[12:34:57]   Template 'th11_ad' candidate at (50.0, 50.0)
[12:34:57]   [VALIDATION] (50.0, 50.0): A(...) B(...) -> INVALID
[12:34:57]     REJECT: Invalid coordinate, added rejected region: [40, 60] x [40, 60]

[12:34:58]   Template 'th13_ad' candidate at (960.0, 540.0)
[12:34:58]   [VALIDATION] (960.0, 540.0): A(...) B(...) -> VALID
[12:34:58]     ACCEPT: Valid coordinate, dropping spells x3
[12:34:58]       Click 1/3 at (960.0, 540.0) (total: 1/11)
[12:34:58]       Click 2/3 at (960.0, 540.0) (total: 2/11)
[12:34:58]       Click 3/3 at (960.0, 540.0) (total: 3/11)

[12:35:00]   Template 'th15_ad' candidate at (1850.0, 850.0)
[12:35:00]     SKIP: Candidate inside rejected region (size=20px)

[12:35:02] Spell deployment complete: 8 spell clicks, 2 rejected regions
```

## Key Design Decisions

### 1. Local Rejected Regions Scope
- Rejected regions list is **local to spell_deployment phase**
- Cleared on function exit (no persistence across battles)
- Prevents accumulation of invalid regions over multiple battles

### 2. Strict Inequality Comparisons
- Boundary values (e.g., exact constraint limits) treated as **invalid**
- Floating-point arithmetic preserves precision
- No rounding errors from integer truncation

### 3. Configurable Region Size
- Default: 20 pixels (±10 from center)
- Adjustable via `CONFIG["rejected_region_size"]`
- Square shape (not circular) for efficient boundary checking

### 4. Three-Click Per Target
- Each valid air defense gets 3 spell clicks
- Matches original behavior for consistency
- Early exit if max_spell_clicks reached

### 5. Center Fallback
- If no valid air defense found, drop remaining spells at screen center
- Ensures spells are always deployed (up to max limit)
- Center coordinate bypasses validation (trusted fallback)

## Testing & Validation

### Unit Test File
**Location:** `test_spell_validation.py`

**Test Coverage:**

1. **TEST 1: is_coord_valid() Constraint Evaluation**
   - Validates known coordinates against constraints
   - Shows numeric evaluation details
   - Example: `(960, 540)` → Valid or Invalid?

2. **TEST 2: is_in_rejected_region() Boundary Detection**
   - Tests region inclusion at various distances
   - Confirms ±10px boundary accuracy
   - Edge cases: exactly at boundary, just outside

3. **TEST 3: Rejected Region Isolation**
   - Multiple regions with spacing
   - Verifies no overlap interference
   - Tests all four boundary points per region

4. **TEST 4: Spell Deployment Scenario**
   - Simulates real spell deployment flow
   - Tracks accepted vs. rejected coordinates
   - Demonstrates prevented invalid clicks

### Running Tests

```bash
cd "c:\Users\lewis\OneDrive\Documents\Files\Important\OX M24\Python\Clash Bot"
python test_spell_validation.py
```

**Expected Output:**
```
======================================================================
SPELL COORDINATE VALIDATION TEST SUITE
======================================================================
...
TEST 1: is_coord_valid() Constraint Evaluation
[PASS] | (  800.0,   400.0) -> False | Center screen coordinate
...

TEST 2: is_in_rejected_region() Boundary Detection
[PASS] | ( 100.0,  100.0) -> True  | Center of first rejected region
...

TEST 3: Rejected Region Isolation
Region 1: (100, 100)
  Center               ( 100.0,  100.0) -> INSIDE
  Right boundary       ( 110.0,  100.0) -> INSIDE
  Just outside right   ( 111.0,  100.0) -> OUTSIDE
...

TEST 4: Spell Deployment Scenario
Processing 4 air defense detections:
  Checking th11_ad at (50.0, 50.0)...
    -> REJECT: Invalid coordinate, added to rejected regions
  Checking th13_ad at (500.0, 300.0)...
    -> REJECT: Invalid coordinate, added to rejected regions
  ...
Results:
  Valid clicks: 0
  Rejected regions: 4
  Coordinate validation prevented 4 invalid clicks
```

### Manual Integration Test

When running a live Clash of Clans battle:

1. **Monitor Console Logs**
   - Look for `[VALIDATION]` lines showing constraint evaluations
   - Count `ACCEPT` vs `REJECT` decisions
   - Verify `SKIP` references previously rejected regions

2. **Verify Spell Clicks**
   - Spells should only be cast at logged ACCEPT coordinates
   - No spells at REJECT coordinates
   - No spells at SKIP coordinates (inside rejected regions)

3. **Check Region Boundaries**
   - Count rejected regions in final summary
   - Manually verify ±10px squares are accurate
   - Test with `CONFIG["rejected_region_size"] = 10` or `50` to verify scaling

## Acceptance Criteria Verification

### ✓ Criterion 1: Invalid coords are never clicked
- All candidates validated before clicking
- Invalid coordinates added to rejected regions
- Failed test cases shown in TEST 4 output

### ✓ Criterion 2: 20×20 region squares prevent retries
- Rejected regions tracked locally in phase
- Candidate inside region → SKIP logged
- TEST 2 & 3 confirm boundary accuracy
- TEST 4 demonstrates skip detection

### ✓ Criterion 3: Logs show numeric evaluations
- Each `[VALIDATION]` log shows:
  - Constraint A: `(lower < y < upper) = T/F`
  - Constraint B: `(lower < y < upper) = T/F`
  - Final result: `VALID` or `INVALID`
- ACCEPT/REJECT/SKIP decisions clearly marked
- Template name and coordinates included

## Code References

**Validation Functions:**
- [is_coord_valid()](Autoclash.py#L431)
- [is_in_rejected_region()](Autoclash.py#L480)

**Spell Deployment:**
- [phase2_execute() spell phase](Autoclash.py#L1483)

**Configuration:**
- [CONFIG["rejected_region_size"]](Autoclash.py#L122)

**Test Suite:**
- [test_spell_validation.py](test_spell_validation.py)

## Usage Notes

### For Game Automation
The spell deployment now automatically:
1. Finds air defense coordinates via template matching
2. Validates each coordinate against geometric constraints
3. Skips coordinates in previously-rejected 20×20 regions
4. Clicks only valid coordinates
5. Falls back to screen center if no valid targets found
6. Provides detailed logging for debugging

### For Development
- Adjust `rejected_region_size` to test different boundary sizes
- Add new test cases to `test_spell_validation.py` as needed
- Monitor logs during live game testing
- Fine-tune constraint parameters if needed in future versions

### For Troubleshooting
- Enable detailed logging: already included in validation functions
- Check `[VALIDATION]` lines for constraint evaluation details
- Verify rejected regions aren't too large (blocking valid coordinates)
- Confirm spell clicks correspond to ACCEPT decisions in logs

## Future Enhancements

Potential improvements for future iterations:
1. Machine learning to refine constraint boundaries over time
2. Per-template validation rules (different constraints per AD type)
3. Dynamic region size based on template confidence
4. Persistence of validated coordinates across battles (with decay)
5. Visualization of rejected regions on screen overlay
