# https://www.statology.org/normalize-data-between-0-and-100/

def normalize(value, min_value, max_value, min_normalized, max_normalized):
    try:
        value = int(value)
    except ValueError:
        return 0

    if value < min_value or value > max_value:
        raise ValueError("Value out of range")

    try:
        return round(((value - min_value) / (max_value - min_value)) * (max_normalized - min_normalized) + min_normalized)
    except ZeroDivisionError:
        return 100
