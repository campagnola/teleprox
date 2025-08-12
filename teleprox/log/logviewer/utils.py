# Utility functions and constants for log viewer styling and level handling
# Contains color schemes, level-to-cipher conversion, and other shared utilities

Stylesheet = """
    body {color: #000; font-family: sans;}
    .entry {}
    .error .message {color: #900}
    .warning .message {color: #740}
    .user .message {color: #009}
    .status .message {color: #090}
    .logExtra {margin-left: 40px;}
    .traceback {color: #555; height: 0px;}
    .timestamp {color: #000;}
"""


# Major log level colors
_level_color_stops = {
    0: (0, 0, 255),      # Blue
    10: (128, 128, 128), # Grey
    20: (0, 0, 0),       # Black
    30: (255, 128, 0),   # Orange
    40: (255, 0, 0),     # Red
    50: (128, 0, 0),     # Dark red
}

# Compute interpolated colors for all levels 0-50
level_colors = {}
for level in range(51):
    # Find the two stops to interpolate between
    lower_stop = max(k for k in _level_color_stops.keys() if k <= level)
    upper_stop = min(k for k in _level_color_stops.keys() if k >= level)
    
    # Interpolate between stops
    lower_r, lower_g, lower_b = _level_color_stops[lower_stop]
    upper_r, upper_g, upper_b = _level_color_stops[upper_stop]
    
    # Calculate interpolation factor
    factor = 1 if lower_stop == upper_stop else (level - lower_stop) / (upper_stop - lower_stop)
    
    # Interpolate each color component
    r = int(lower_r + (upper_r - lower_r) * factor)
    g = int(lower_g + (upper_g - lower_g) * factor)
    b = int(lower_b + (upper_b - lower_b) * factor)
    
    # Convert to hex format
    level_colors[level] = f"#{r:02X}{g:02X}{b:02X}"


available_thread_colors = ['#B00', '#0B0', '#00B', '#BB0', '#B0B', '#0BB', '#CA0', '#C0A', '#0CA', '#AC0', '#A0C', '#0AC']
thread_colors = {}
def thread_color(thread_name):
    global thread_colors
    try:
        return thread_colors[thread_name]
    except KeyError:
        thread_colors[thread_name] = available_thread_colors[len(thread_colors) % len(available_thread_colors)]
        return thread_colors[thread_name]


# Level cipher system for chained filtering
def level_to_cipher(level_int):
    """Convert integer level (0-50) to cipher character for filtering."""
    if 0 <= level_int <= 25:
        return chr(ord('a') + level_int)  # a-z
    elif 26 <= level_int <= 50:
        return chr(ord('A') + (level_int - 26))  # A-Y
    else:
        return 'Z'  # fallback for > 50


def parse_level_value(value_str):
    """Parse level value from user input, supporting both numbers and names."""
    # Standard Python logging level names
    level_names = {
        'debug': 10, 'info': 20, 'warning': 30, 'warn': 30,
        'error': 40, 'critical': 50, 'fatal': 50
    }
    
    value_str = value_str.strip().lower()
    
    # Try parsing as number first
    try:
        return int(value_str)
    except ValueError:
        pass
    
    # Try parsing as level name
    return level_names.get(value_str, 0)


def level_threshold_to_cipher_regex(threshold):
    """Convert level threshold to cipher regex pattern for levels >= threshold."""
    if threshold <= 0:
        return ".*"  # Match all levels
    
    # Create character class with ranges for better readability and performance
    patterns = []
    
    # Add lowercase range if needed (a-z covers 0-25)
    if threshold <= 25:
        start_char = level_to_cipher(threshold)
        patterns.append(f"{start_char}-z")
    
    # Add uppercase range if needed (A-Y covers 26-50)  
    if threshold <= 50:
        if threshold <= 25:
            patterns.append("A-Y")
        else:
            start_char = level_to_cipher(threshold)
            patterns.append(f"{start_char}-Y")
    
    # Add fallback for > 50
    if threshold <= 50:
        patterns.append("Z")
    
    if not patterns:
        return "Z"  # Only match fallback level
    
    # Create character class with ranges
    return f"[{''.join(patterns)}]"